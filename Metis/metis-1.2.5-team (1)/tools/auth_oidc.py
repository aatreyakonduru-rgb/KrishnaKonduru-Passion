#!/usr/bin/env python3
"""Single sign-on for the Metis UI: OpenID Connect authorization-code flow with PKCE. Standard library only.

    python3 auth_oidc.py check <kb> [--online]     check the `auth` section of the KB profile; --online also fetches the
                                                   provider's discovery document and key set

Profile section (all keys under `auth:` in <kb>/.metis/kb-profile.yaml; `mode: none` or no section = no sign-in, as before):

    auth:
      mode: oidc                          # none (default) or oidc
      issuer: https://login.example.com/tenant/v2.0
      client_id: metis-ui
      client_secret_env: METIS_OIDC_SECRET   # name of the environment variable holding the secret (omit for a public client)
      redirect_uri: https://metis.example.com/oidc/callback
      scopes: [openid, profile, email]
      allowed_domains: [example.com]      # optional: only these email domains may sign in
      session_secret_env: METIS_SESSION_SECRET   # environment variable with 16+ random characters; signs the session cookie
      groups_claim: groups                # optional, default groups
      group_map: {metis-leads: lead, metis-devs: member}   # optional: identity-provider group -> Metis role
      session_hours: 8                    # optional, default 8

What is checked, and what is not:
  - The flow: /login redirects to the provider with state, nonce and a PKCE (S256) challenge; /oidc/callback exchanges the code
    for tokens at the provider's token endpoint and validates the ID token: signature (RS256, against the provider's JWKS),
    iss, aud (and azp when there are several), exp, iat, nbf, nonce. Algorithms other than RS256 (including `none` and HS256)
    are refused. The identity is the verified `preferred_username`, else `email`.
  - The signature check is RSASSA-PKCS1-v1_5 with SHA-256 done with Python integers (pow), compared with the exactly
    re-built encoded message, so no padding oddity is accepted. If the `cryptography` package is installed it is used
    instead (guarded import); the pure-Python path is the fallback and is tested on its own.
  - The session is a cookie signed with HMAC-SHA256 under a secret that only the server knows; a cookie that was not signed by
    this server, was changed, or has expired is not a session. The name cookie of the no-SSO mode is ignored when SSO is on.
  - Tested against a fake in-process provider only. It has not been run against Azure AD, Okta, Ping or any real provider:
    that needs your identity provider (claims, key rotation, clock skew, and consent screens differ). SCIM is not built.
"""
import argparse
import base64
import hashlib
import hmac
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

try:  # optional: a faster, audited RSA check when the package is there
    from cryptography.exceptions import InvalidSignature as _InvalidSignature
    from cryptography.hazmat.primitives import hashes as _hashes
    from cryptography.hazmat.primitives.asymmetric import padding as _padding
    from cryptography.hazmat.primitives.asymmetric import rsa as _rsa
    HAVE_CRYPTOGRAPHY = True
except Exception:  # not installed or unusable: the pure-Python check below is used
    HAVE_CRYPTOGRAPHY = False

HERE = os.path.dirname(os.path.abspath(__file__))
SESSION_COOKIE = "metis_session"
TX_COOKIE = "metis_oidc"
TX_SECONDS = 600
LEEWAY = 60
MIN_RSA_BITS = 2048
LOOPBACK = ("127.0.0.1", "localhost", "::1")
# DER prefix of DigestInfo for SHA-256 (RFC 8017, section 9.2 note 1)
SHA256_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")
USE_CRYPTOGRAPHY = True  # tests switch this off to exercise the pure-Python path


class AuthError(ValueError):
    """Sign-in cannot continue; the text is safe to show to the person."""


class UnknownKey(AuthError):
    pass


# ---- small helpers -------------------------------------------------------------------------------------
def b64u(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64u_dec(text):
    try:
        text = str(text)
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except Exception:
        raise AuthError("token is not well formed")


def _json(data):
    try:
        out = json.loads(data.decode("utf-8"))
    except Exception:
        raise AuthError("token is not well formed")
    if not isinstance(out, dict):
        raise AuthError("token is not well formed")
    return out


def _real(v):
    s = " ".join(str(v if v is not None else "").split())
    return "" if not s or (s.startswith("<") and s.endswith(">")) else s


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _url_ok(url, what):
    u = urllib.parse.urlparse(str(url))
    if u.scheme == "https" and u.hostname:
        return
    if u.scheme == "http" and u.hostname in LOOPBACK:
        return  # a local provider for development and tests
    raise AuthError("%s must be an https address (got %r)" % (what, str(url)[:80]))


# ---- configuration -------------------------------------------------------------------------------------
def config(prof):
    """The `auth` section as a dict, or None when sign-in is off. Raises AuthError when it is on but cannot work."""
    a = (prof or {}).get("auth")
    if not isinstance(a, dict):
        return None
    mode = str(a.get("mode") or "none").strip().lower()
    if mode == "none":
        return None
    if mode != "oidc":
        raise AuthError("auth.mode must be none or oidc, not %r" % mode)
    cfg = {"mode": "oidc"}
    for key in ("issuer", "client_id", "redirect_uri", "session_secret_env"):
        cfg[key] = _real(a.get(key))
        if not cfg[key]:
            raise AuthError("auth.%s is not set in the KB profile" % key)
    cfg["client_secret_env"] = _real(a.get("client_secret_env"))
    _url_ok(cfg["issuer"], "auth.issuer")
    _url_ok(cfg["redirect_uri"], "auth.redirect_uri")
    sc = a.get("scopes") or ["openid", "profile", "email"]
    sc = sc.split() if isinstance(sc, str) else [str(x) for x in sc]
    cfg["scopes"] = sc if "openid" in sc else ["openid"] + sc
    cfg["allowed_domains"] = [str(d).strip().lower().lstrip("@") for d in (a.get("allowed_domains") or []) if str(d).strip()]
    cfg["groups_claim"] = _real(a.get("groups_claim")) or "groups"
    gm = a.get("group_map") or {}
    cfg["group_map"] = {str(k): str(v) for k, v in gm.items()} if isinstance(gm, dict) else {}
    try:
        hours = int(a.get("session_hours") or 8)
    except (TypeError, ValueError):
        raise AuthError("auth.session_hours must be a number")
    cfg["session_hours"] = min(max(hours, 1), 24 * 14)
    return cfg


def session_secret(cfg, env=None):
    v = (env if env is not None else os.environ).get(cfg["session_secret_env"], "")
    if len(v) < 16:
        raise AuthError("the environment variable %s must hold a secret of at least 16 characters" % cfg["session_secret_env"])
    return v


def client_secret(cfg, env=None):
    name = cfg.get("client_secret_env")
    if not name:
        return ""
    v = (env if env is not None else os.environ).get(name, "")
    if not v:
        raise AuthError("the environment variable %s (auth.client_secret_env) is empty" % name)
    return v


# ---- talking to the provider ---------------------------------------------------------------------------
def http_json(url, data=None, headers=None, timeout=10):
    """GET (or POST of form `data`) and parse a JSON object. Nothing is sent but what is passed in."""
    body = urllib.parse.urlencode(data).encode("ascii") if data is not None else None
    req = urllib.request.Request(url, data=body, headers=dict(headers or {}))
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(1024 * 1024 + 1)
    except urllib.error.HTTPError as err:
        detail = ""
        try:
            detail = json.loads(err.read(4096).decode("utf-8", "replace")).get("error_description") or ""
        except Exception:
            pass
        raise AuthError("the identity provider answered %s at %s%s" % (err.code, urllib.parse.urlparse(url).path, (": " + str(detail)[:120]) if detail else ""))
    except (urllib.error.URLError, OSError, ValueError) as err:
        raise AuthError("cannot reach the identity provider at %s: %s" % (urllib.parse.urlparse(url).netloc, getattr(err, "reason", err)))
    if len(raw) > 1024 * 1024:
        raise AuthError("the identity provider's answer is too large")
    try:
        out = json.loads(raw.decode("utf-8"))
    except ValueError:
        raise AuthError("the identity provider did not answer with JSON at %s" % urllib.parse.urlparse(url).path)
    if not isinstance(out, dict):
        raise AuthError("the identity provider's answer is not a JSON object")
    return out


_CACHE = {}


def clear_cache():
    _CACHE.clear()


def discovery(issuer, fetch=None, ttl=3600):
    """The provider's discovery document, checked against the configured issuer."""
    key = ("disc", issuer)
    hit = _CACHE.get(key)
    if hit and hit[0] > time.time():
        return hit[1]
    doc = (fetch or http_json)(issuer.rstrip("/") + "/.well-known/openid-configuration")
    if str(doc.get("issuer") or "").rstrip("/") != issuer.rstrip("/"):
        raise AuthError("the provider's discovery document names a different issuer; check auth.issuer")
    for k in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        if not doc.get(k):
            raise AuthError("the provider's discovery document has no %s" % k)
        _url_ok(doc[k], k)
    _CACHE[key] = (time.time() + ttl, doc)
    return doc


def jwks(doc, fetch=None, force=False, ttl=3600):
    key = ("jwks", doc["jwks_uri"])
    hit = _CACHE.get(key)
    if hit and hit[0] > time.time() and not force:
        return hit[1]
    keys = (fetch or http_json)(doc["jwks_uri"]).get("keys")
    if not isinstance(keys, list):
        raise AuthError("the provider's key set has no keys")
    _CACHE[key] = (time.time() + ttl, keys)
    return keys


# ---- RS256 ---------------------------------------------------------------------------------------------
def _pick_key(keys, kid):
    cands = [k for k in keys if isinstance(k, dict) and k.get("kty") == "RSA" and k.get("use") in (None, "sig")
             and k.get("alg") in (None, "RS256")]
    if kid is not None:
        cands = [k for k in cands if k.get("kid") == kid]
    elif len(cands) != 1:
        cands = []
    if not cands:
        raise UnknownKey("no key in the provider's key set matches this token")
    k = cands[0]
    try:
        n = int.from_bytes(b64u_dec(k["n"]), "big")
        e = int.from_bytes(b64u_dec(k["e"]), "big")
    except (KeyError, AuthError):
        raise AuthError("the provider's key is not a usable RSA key")
    return n, e


def rs256_verify(n, e, message, signature, python_only=False):
    """True when `signature` is a valid RSASSA-PKCS1-v1_5 / SHA-256 signature of `message` under the public key (n, e)."""
    if n.bit_length() < MIN_RSA_BITS or n % 2 == 0 or e < 3 or e % 2 == 0 or e >= n:
        return False
    k = (n.bit_length() + 7) // 8
    if len(signature) != k:
        return False
    if HAVE_CRYPTOGRAPHY and USE_CRYPTOGRAPHY and not python_only:
        try:
            _rsa.RSAPublicNumbers(e, n).public_key().verify(signature, message, _padding.PKCS1v15(), _hashes.SHA256())
            return True
        except (_InvalidSignature, ValueError):
            return False
    s = int.from_bytes(signature, "big")
    if s >= n:
        return False
    em = pow(s, e, n).to_bytes(k, "big")
    t = SHA256_PREFIX + hashlib.sha256(message).digest()
    expected = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
    return hmac.compare_digest(em, expected)


def verify_id_token(token, keys, issuer, client_id, nonce, now=None, leeway=LEEWAY, python_only=False):
    """The verified claims of an ID token, or AuthError. `keys` is the provider's JWKS key list."""
    now = time.time() if now is None else now
    parts = str(token or "").split(".")
    if len(parts) != 3 or not all(parts):
        raise AuthError("the ID token is not well formed")
    header = _json(b64u_dec(parts[0]))
    if header.get("alg") != "RS256":
        raise AuthError("the ID token uses the algorithm %r; only RS256 is accepted" % str(header.get("alg"))[:20])
    n, e = _pick_key(keys, header.get("kid"))
    if not rs256_verify(n, e, (parts[0] + "." + parts[1]).encode("ascii"), b64u_dec(parts[2]), python_only):
        raise AuthError("the ID token's signature is not valid")
    c = _json(b64u_dec(parts[1]))
    if c.get("iss") != issuer:
        raise AuthError("the ID token was issued by a different issuer")
    aud = c.get("aud")
    auds = [aud] if isinstance(aud, str) else aud if isinstance(aud, list) else []
    if client_id not in auds:
        raise AuthError("the ID token is for a different application (audience)")
    if len(auds) > 1 and c.get("azp") != client_id:
        raise AuthError("the ID token's authorized party is not this application")
    if not _num(c.get("exp")):
        raise AuthError("the ID token has no expiry")
    if now - leeway >= c["exp"]:
        raise AuthError("the ID token has expired")
    if _num(c.get("iat")) and c["iat"] > now + leeway:
        raise AuthError("the ID token was issued in the future; check the clocks")
    if _num(c.get("nbf")) and c["nbf"] > now + leeway:
        raise AuthError("the ID token is not valid yet")
    if not isinstance(c.get("nonce"), str) or not hmac.compare_digest(c["nonce"].encode(), str(nonce).encode()):
        raise AuthError("the ID token does not belong to this sign-in (nonce)")
    if not isinstance(c.get("sub"), str) or not c["sub"]:
        raise AuthError("the ID token has no subject")
    return c


def identity_from_claims(cfg, claims):
    """{user, email, sub, roles} from verified claims. The name is preferred_username, else email."""
    pref = _real(claims.get("preferred_username")) if isinstance(claims.get("preferred_username"), str) else ""
    email = _real(claims.get("email")) if isinstance(claims.get("email"), str) else ""
    verified = claims.get("email_verified") is not False  # a provider that does not say is not suspected
    user = pref or (email if verified else "")
    if not user:
        raise AuthError("the ID token has no preferred_username and no verified email, so there is no name to record")
    if cfg["allowed_domains"]:
        where = (email if verified else "") or (pref if "@" in pref else "")
        domain = where.rpartition("@")[2].lower() if "@" in where else ""
        if domain not in cfg["allowed_domains"]:
            raise AuthError("this account's email domain is not allowed to sign in to Metis")
    raw = claims.get(cfg["groups_claim"])
    groups = [raw] if isinstance(raw, str) else [g for g in raw if isinstance(g, str)] if isinstance(raw, list) else []
    roles = sorted({cfg["group_map"][g] for g in groups if g in cfg["group_map"]})
    return {"user": user[:120], "email": email, "sub": claims["sub"], "roles": roles}


# ---- signed blobs: the sign-in transaction cookie and the session cookie -------------------------------
def sign_blob(secret, payload):
    body = b64u(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    return body + "." + b64u(hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest())


def open_blob(secret, blob, kind, now=None):
    """The payload of a blob this server signed, of the given kind and not expired; otherwise None."""
    try:
        body, _, mac = str(blob or "").partition(".")
        want = b64u(hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest())
        if not body or not hmac.compare_digest(mac.encode("ascii"), want.encode("ascii")):
            return None
        data = json.loads(b64u_dec(body).decode("utf-8"))
    except (AuthError, ValueError, UnicodeError):
        return None
    if not isinstance(data, dict) or data.get("k") != kind or not _num(data.get("exp")):
        return None
    return data if data["exp"] > (time.time() if now is None else now) else None


def make_session(cfg, secret, ident, now=None):
    now = time.time() if now is None else now
    return sign_blob(secret, {"k": "sess", "user": ident["user"], "sub": ident["sub"], "roles": ident["roles"],
                              "exp": int(now + cfg["session_hours"] * 3600)})


def read_session(secret, value, now=None):
    return open_blob(secret, value, "sess", now)


# ---- the two steps of the flow ---------------------------------------------------------------------------
def begin_login(cfg, secret, back="/", fetch=None, now=None):
    """(url to send the browser to, value for the sign-in transaction cookie)."""
    now = time.time() if now is None else now
    doc = discovery(cfg["issuer"], fetch)
    state, nonce, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    params = {"response_type": "code", "client_id": cfg["client_id"], "redirect_uri": cfg["redirect_uri"],
              "scope": " ".join(cfg["scopes"]), "state": state, "nonce": nonce,
              "code_challenge": b64u(hashlib.sha256(verifier.encode("ascii")).digest()), "code_challenge_method": "S256"}
    ep = doc["authorization_endpoint"]
    url = ep + ("&" if "?" in ep else "?") + urllib.parse.urlencode(params)
    tx = sign_blob(secret, {"k": "tx", "state": state, "nonce": nonce, "cv": verifier, "back": back, "exp": int(now + TX_SECONDS)})
    return url, tx


def finish_login(cfg, secret, tx_blob, params, secret_client="", fetch=None, post=None, now=None, python_only=False):
    """Check the callback and return (identity, where to go next). `params` are the callback's query values."""
    if params.get("error"):
        raise AuthError("the identity provider did not sign you in: %s" % " ".join(
            str(params.get(k) or "") for k in ("error", "error_description")).strip()[:200])
    tx = open_blob(secret, tx_blob, "tx", now)
    if not tx:
        raise AuthError("this sign-in has expired or did not start here; start again")
    if not hmac.compare_digest(str(params.get("state") or "").encode(), tx["state"].encode()):
        raise AuthError("the sign-in state does not match; start again")
    code = str(params.get("code") or "")
    if not code:
        raise AuthError("the provider sent no authorization code")
    doc = discovery(cfg["issuer"], fetch)
    data = {"grant_type": "authorization_code", "code": code, "redirect_uri": cfg["redirect_uri"],
            "client_id": cfg["client_id"], "code_verifier": tx["cv"]}
    headers = {}
    if secret_client:
        methods = doc.get("token_endpoint_auth_methods_supported") or ["client_secret_basic"]
        if "client_secret_basic" in methods:
            pair = "%s:%s" % (urllib.parse.quote(cfg["client_id"], safe=""), urllib.parse.quote(secret_client, safe=""))
            headers["Authorization"] = "Basic " + base64.b64encode(pair.encode("utf-8")).decode("ascii")
        else:
            data["client_secret"] = secret_client
    tok = (post or http_json)(doc["token_endpoint"], data, headers)
    id_token = tok.get("id_token")
    if not id_token:
        raise AuthError("the provider's answer has no ID token")
    try:
        claims = verify_id_token(id_token, jwks(doc, fetch), cfg["issuer"], cfg["client_id"], tx["nonce"], now, python_only=python_only)
    except UnknownKey:  # keys may have been rotated: fetch the set once more
        claims = verify_id_token(id_token, jwks(doc, fetch, force=True), cfg["issuer"], cfg["client_id"], tx["nonce"], now,
                                 python_only=python_only)
    return identity_from_claims(cfg, claims), tx.get("back") or "/"


# ---- command line --------------------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("check")
    a.add_argument("kb")
    a.add_argument("--online", action="store_true")
    args = ap.parse_args(argv)
    import yaml
    path = os.path.join(args.kb, ".metis", "kb-profile.yaml")
    prof = {}
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            prof = yaml.safe_load(fh) or {}
    try:
        cfg = config(prof)
        if cfg is None:
            print("auth.mode is none: no sign-in (the name box is used)")
            return 0
        session_secret(cfg)
        client_secret(cfg)
        print("auth.mode oidc: issuer %s, client %s, redirect %s, RSA check by %s" % (
            cfg["issuer"], cfg["client_id"], cfg["redirect_uri"], "cryptography" if HAVE_CRYPTOGRAPHY else "pure Python"))
        if args.online:
            doc = discovery(cfg["issuer"])
            print("discovery ok; %d signing key(s)" % len(jwks(doc)))
        else:
            print("not checked against the provider (add --online)")
    except AuthError as err:
        print("problem: %s" % err, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
