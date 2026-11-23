import base64
import hashlib
import http.client
import http.cookies
import json
import os
import re
import secrets
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
for _p in (TOOLS, os.path.join(TOOLS, "ui")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import auth_oidc as A  # noqa: E402


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


# ---- RSA key generation with Miller-Rabin, in pure Python (the test makes its own keys) ----------------
SMALL = [p for p in range(3, 2000, 2) if all(p % q for q in range(3, int(p ** 0.5) + 1, 2))]


def is_probable_prime(n, rounds=24):
    if n < 2:
        return False
    if n in (2, 3):
        return True
    if n % 2 == 0:
        return False
    for p in SMALL:
        if n == p:
            return True
        if n % p == 0:
            return False
    d, r = n - 1, 0
    while d % 2 == 0:
        d //= 2
        r += 1
    for _ in range(rounds):
        a = secrets.randbelow(n - 3) + 2
        x = pow(a, d, n)
        if x in (1, n - 1):
            continue
        for _ in range(r - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


def gen_prime(bits):
    while True:
        c = secrets.randbits(bits) | (1 << (bits - 1)) | (1 << (bits - 2)) | 1
        if is_probable_prime(c):
            return c


def gen_rsa(bits=2048, e=65537):
    while True:
        p, q = gen_prime(bits // 2), gen_prime(bits // 2)
        if p == q:
            continue
        phi = (p - 1) * (q - 1)
        if phi % e == 0:
            continue
        n = p * q
        if n.bit_length() != bits:
            continue
        return n, e, pow(e, -1, phi)


class Key(object):
    def __init__(self, kid):
        self.kid = kid
        self.n, self.e, self.d = gen_rsa()

    def jwk(self):
        size = (self.n.bit_length() + 7) // 8
        return {"kty": "RSA", "use": "sig", "alg": "RS256", "kid": self.kid,
                "n": A.b64u(self.n.to_bytes(size, "big")), "e": A.b64u(self.e.to_bytes(3, "big"))}

    def sign(self, message):
        k = (self.n.bit_length() + 7) // 8
        t = A.SHA256_PREFIX + hashlib.sha256(message).digest()
        em = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
        return pow(int.from_bytes(em, "big"), self.d, self.n).to_bytes(k, "big")


KEY_A = None
KEY_B = None


def keys():
    global KEY_A, KEY_B
    if KEY_A is None:
        KEY_A, KEY_B = Key("kid-a"), Key("kid-b")
    return KEY_A, KEY_B


def jwt(key, claims, header=None, alg="RS256"):
    h = {"alg": alg, "typ": "JWT", "kid": key.kid}
    h.update(header or {})
    head = A.b64u(json.dumps(h).encode())
    body = A.b64u(json.dumps(claims).encode())
    return "%s.%s.%s" % (head, body, A.b64u(key.sign((head + "." + body).encode())))


class FakeProvider(object):
    """An identity provider in this process: discovery, JWKS, an authorize step done by calling authorize(), and a token endpoint."""
    def __init__(self, key, client_id="metis-ui", client_secret="s3cret-value", redirect_uri="http://127.0.0.1:1/oidc/callback"):
        self.key, self.client_id, self.client_secret = key, client_id, client_secret
        self.published = [key]
        self.codes = {}
        self.claims = {"preferred_username": "ana@example.com", "email": "ana@example.com", "groups": ["metis-leads"], "sub": "u-1"}
        self.tamper = None   # function(claims) -> claims, applied to the token the provider issues
        self.sign_with = None
        self.nonce_override = None
        self.token_calls = 0
        prov = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, obj):
                data = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.path == "/.well-known/openid-configuration":
                    return self._send(200, {"issuer": prov.issuer, "authorization_endpoint": prov.issuer + "/authorize",
                                            "token_endpoint": prov.issuer + "/token", "jwks_uri": prov.issuer + "/jwks",
                                            "token_endpoint_auth_methods_supported": ["client_secret_basic"]})
                if self.path == "/jwks":
                    return self._send(200, {"keys": [k.jwk() for k in prov.published]})
                self._send(404, {"error": "not_found"})

            def do_POST(self):
                if self.path != "/token":
                    return self._send(404, {"error": "not_found"})
                form = dict(urllib.parse.parse_qsl(self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()))
                prov.token_calls += 1
                auth = self.headers.get("Authorization") or ""
                want = "Basic " + base64.b64encode(("%s:%s" % (prov.client_id, prov.client_secret)).encode()).decode()
                if prov.client_secret and auth != want:
                    return self._send(401, {"error": "invalid_client"})
                rec = prov.codes.pop(form.get("code"), None)  # a code works once
                if not rec or form.get("redirect_uri") != rec["redirect_uri"]:
                    return self._send(400, {"error": "invalid_grant", "error_description": "bad or used code"})
                challenge = A.b64u(hashlib.sha256(form.get("code_verifier", "").encode()).digest())
                if challenge != rec["challenge"]:
                    return self._send(400, {"error": "invalid_grant", "error_description": "PKCE verifier does not match"})
                now = int(time.time())
                claims = dict(prov.claims, iss=prov.issuer, aud=prov.client_id, iat=now, exp=now + 300,
                              nonce=prov.nonce_override or rec["nonce"])
                if prov.tamper:
                    claims = prov.tamper(claims)
                self._send(200, {"id_token": jwt(prov.sign_with or prov.key, claims), "access_token": "x", "token_type": "Bearer"})

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.issuer = "http://127.0.0.1:%d" % self.http.server_address[1]
        threading.Thread(target=self.http.serve_forever, daemon=True).start()

    def close(self):
        self.http.shutdown()
        self.http.server_close()

    def authorize(self, url):
        """What the browser does at the provider after the person signs in: returns the query the provider sends back."""
        u = urllib.parse.urlparse(url)
        assert url.startswith(self.issuer + "/authorize"), url
        q = dict(urllib.parse.parse_qsl(u.query))
        assert q["response_type"] == "code" and q["client_id"] == self.client_id
        assert q["code_challenge_method"] == "S256" and q["code_challenge"] and q["state"] and q["nonce"]
        assert "openid" in q["scope"].split()
        code = secrets.token_urlsafe(12)
        self.codes[code] = {"challenge": q["code_challenge"], "nonce": q["nonce"], "redirect_uri": q["redirect_uri"]}
        return {"code": code, "state": q["state"]}


def claims(prov_issuer="https://idp.example", aud="metis-ui", nonce="n1", **over):
    now = int(time.time())
    c = {"iss": prov_issuer, "aud": aud, "sub": "u-1", "iat": now, "exp": now + 300, "nonce": nonce, "preferred_username": "ana@example.com"}
    c.update(over)
    return c


class RsaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.a, cls.b = keys()

    def test_generated_key_is_2048_bits_and_signs_verifiably(self):
        self.assertEqual(self.a.n.bit_length(), 2048)
        sig = self.a.sign(b"hello")
        self.assertTrue(A.rs256_verify(self.a.n, self.a.e, b"hello", sig, python_only=True))

    def test_pure_python_path_rejects_bad_signatures(self):
        sig = self.a.sign(b"hello")
        self.assertFalse(A.rs256_verify(self.a.n, self.a.e, b"hellO", sig, python_only=True))
        self.assertFalse(A.rs256_verify(self.b.n, self.b.e, b"hello", sig, python_only=True))  # another key
        self.assertFalse(A.rs256_verify(self.a.n, self.a.e, b"hello", bytes([sig[0] ^ 1]) + sig[1:], python_only=True))
        self.assertFalse(A.rs256_verify(self.a.n, self.a.e, b"hello", sig[:-1], python_only=True))
        self.assertFalse(A.rs256_verify(self.a.n, self.a.e, b"hello", b"\x00" * len(sig), python_only=True))

    def test_weak_or_odd_keys_are_refused(self):
        self.assertFalse(A.rs256_verify(2 ** 1024 + 1, 65537, b"x", b"\x00" * 129, python_only=True))  # too small
        self.assertFalse(A.rs256_verify(self.a.n, 1, b"x", b"\x01" * 256, python_only=True))

    def test_signature_with_sloppy_padding_is_refused(self):
        """A signature over a message with extra bytes after the digest (the classic e=3 forgery shape) must not verify."""
        k = 256
        t = A.SHA256_PREFIX + hashlib.sha256(b"m").digest()
        em = b"\x00\x01" + b"\xff" * 8 + b"\x00" + t + b"\x01" * (k - 11 - len(t))
        sig = pow(int.from_bytes(em, "big"), self.a.d, self.a.n).to_bytes(k, "big")
        self.assertFalse(A.rs256_verify(self.a.n, self.a.e, b"m", sig, python_only=True))

    @unittest.skipUnless(A.HAVE_CRYPTOGRAPHY, "cryptography is not installed")
    def test_cryptography_and_pure_python_agree(self):
        sig = self.a.sign(b"agree")
        for msg, s in ((b"agree", sig), (b"disagree", sig)):
            self.assertEqual(A.rs256_verify(self.a.n, self.a.e, msg, s), A.rs256_verify(self.a.n, self.a.e, msg, s, python_only=True))


class TokenTests(unittest.TestCase):
    ISS = "https://idp.example"

    @classmethod
    def setUpClass(cls):
        cls.a, cls.b = keys()

    def verify(self, token, nonce="n1", keyset=None, now=None, **kw):
        return A.verify_id_token(token, keyset or [self.a.jwk(), self.b.jwk()], self.ISS, "metis-ui", nonce, now, python_only=True, **kw)

    def test_a_good_token_passes(self):
        c = self.verify(jwt(self.a, claims()))
        self.assertEqual(c["preferred_username"], "ana@example.com")

    def test_forged_token_signed_by_another_key_is_rejected(self):
        evil = Key("kid-a")  # the attacker names the real kid but signs with their own key
        with self.assertRaisesRegex(A.AuthError, "signature"):
            self.verify(jwt(evil, claims()))

    def test_tampered_payload_is_rejected(self):
        h, p, s = jwt(self.a, claims()).split(".")
        forged = dict(json.loads(A.b64u_dec(p)), preferred_username="root@example.com")
        with self.assertRaisesRegex(A.AuthError, "signature"):
            self.verify("%s.%s.%s" % (h, A.b64u(json.dumps(forged).encode()), s))

    def test_expired_token_is_rejected(self):
        old = int(time.time()) - 3600
        with self.assertRaisesRegex(A.AuthError, "expired"):
            self.verify(jwt(self.a, claims(iat=old - 100, exp=old)))

    def test_wrong_audience_is_rejected(self):
        with self.assertRaisesRegex(A.AuthError, "audience"):
            self.verify(jwt(self.a, claims(aud="another-app")))
        with self.assertRaisesRegex(A.AuthError, "audience"):
            self.verify(jwt(self.a, claims(aud=["x", "y"])))

    def test_audience_list_needs_the_authorized_party(self):
        self.verify(jwt(self.a, claims(aud=["metis-ui", "other"], azp="metis-ui")))
        with self.assertRaisesRegex(A.AuthError, "authorized party"):
            self.verify(jwt(self.a, claims(aud=["metis-ui", "other"])))

    def test_wrong_issuer_and_wrong_nonce_are_rejected(self):
        with self.assertRaisesRegex(A.AuthError, "issuer"):
            self.verify(jwt(self.a, claims(**{"iss": "https://evil.example"})))
        with self.assertRaisesRegex(A.AuthError, "nonce"):
            self.verify(jwt(self.a, claims()), nonce="different")
        with self.assertRaisesRegex(A.AuthError, "nonce"):
            c = claims()
            del c["nonce"]
            self.verify(jwt(self.a, c))

    def test_algorithm_none_and_hs256_are_refused(self):
        c = A.b64u(json.dumps(claims()).encode())
        none = A.b64u(json.dumps({"alg": "none", "kid": "kid-a"}).encode()) + "." + c + ".AAAA"
        with self.assertRaisesRegex(A.AuthError, "only RS256"):
            self.verify(none)
        head = A.b64u(json.dumps({"alg": "HS256", "kid": "kid-a"}).encode())
        mac = A.b64u(__import__("hmac").new(b"public-key-bytes", (head + "." + c).encode(), hashlib.sha256).digest())
        with self.assertRaisesRegex(A.AuthError, "only RS256"):
            self.verify("%s.%s.%s" % (head, c, mac))

    def test_unknown_kid_and_malformed_tokens(self):
        with self.assertRaises(A.UnknownKey):
            self.verify(jwt(self.a, claims()), keyset=[self.b.jwk()])
        for bad in ("", "abc", "a.b", "a.b.c.d", "..", "!!!.???.***", None):
            with self.assertRaises(A.AuthError):
                self.verify(bad)

    def test_missing_expiry_or_subject_is_rejected(self):
        c = claims()
        del c["exp"]
        with self.assertRaisesRegex(A.AuthError, "expiry"):
            self.verify(jwt(self.a, c))
        c = claims()
        del c["sub"]
        with self.assertRaisesRegex(A.AuthError, "subject"):
            self.verify(jwt(self.a, c))

    def test_clock_leeway_is_small(self):
        now = time.time()
        just_gone = jwt(self.a, claims(iat=int(now) - 100, exp=int(now) - 30))
        self.verify(just_gone)  # inside the 60 s allowance for clock drift
        with self.assertRaisesRegex(A.AuthError, "expired"):
            self.verify(just_gone, now=now + 120)
        with self.assertRaisesRegex(A.AuthError, "future"):
            self.verify(jwt(self.a, claims(iat=int(now) + 3600, exp=int(now) + 4000)))


class IdentityTests(unittest.TestCase):
    def cfg(self, **over):
        prof = {"auth": dict({"mode": "oidc", "issuer": "https://idp.example", "client_id": "metis-ui", "redirect_uri": "https://m.example/oidc/callback",
                              "session_secret_env": "S", "group_map": {"metis-leads": "lead", "metis-devs": "member"}}, **over)}
        return A.config(prof)

    def test_default_is_no_sign_in(self):
        self.assertIsNone(A.config({}))
        self.assertIsNone(A.config({"auth": None}))
        self.assertIsNone(A.config({"auth": {"mode": "none", "issuer": "x"}}))
        self.assertIsNone(A.config({"auth": {}}))

    def test_bad_configuration_is_explained(self):
        for over, text in (({"mode": "saml"}, "mode"), ({"issuer": ""}, "issuer"), ({"client_id": "<your id>"}, "client_id"),
                           ({"issuer": "http://idp.example"}, "https"), ({"redirect_uri": "ftp://x"}, "https"),
                           ({"session_secret_env": ""}, "session_secret_env")):
            with self.assertRaisesRegex(A.AuthError, text):
                self.cfg(**over)

    def test_preferred_username_then_email(self):
        c = self.cfg()
        self.assertEqual(A.identity_from_claims(c, {"sub": "1", "preferred_username": "ana", "email": "a@x.com"})["user"], "ana")
        self.assertEqual(A.identity_from_claims(c, {"sub": "1", "email": "a@x.com"})["user"], "a@x.com")
        with self.assertRaises(A.AuthError):
            A.identity_from_claims(c, {"sub": "1"})
        with self.assertRaises(A.AuthError):  # an email the provider says is not verified is not an identity
            A.identity_from_claims(c, {"sub": "1", "email": "a@x.com", "email_verified": False})

    def test_groups_map_to_roles(self):
        c = self.cfg()
        i = A.identity_from_claims(c, {"sub": "1", "preferred_username": "ana", "groups": ["metis-leads", "other", "metis-devs"]})
        self.assertEqual(i["roles"], ["lead", "member"])
        self.assertEqual(A.identity_from_claims(c, {"sub": "1", "preferred_username": "a", "groups": "metis-leads"})["roles"], ["lead"])
        self.assertEqual(A.identity_from_claims(c, {"sub": "1", "preferred_username": "a", "groups": 5})["roles"], [])

    def test_allowed_domains(self):
        c = self.cfg(allowed_domains=["Example.com"])
        A.identity_from_claims(c, {"sub": "1", "email": "a@example.com"})
        with self.assertRaisesRegex(A.AuthError, "domain"):
            A.identity_from_claims(c, {"sub": "1", "preferred_username": "a", "email": "a@evil.com"})
        with self.assertRaisesRegex(A.AuthError, "domain"):
            A.identity_from_claims(c, {"sub": "1", "preferred_username": "a"})  # no email at all: cannot show the domain

    def test_signed_blobs(self):
        c = self.cfg()
        sess = A.make_session(c, "secret-secret-secret-1", {"user": "ana", "sub": "1", "roles": ["lead"]})
        self.assertEqual(A.read_session("secret-secret-secret-1", sess)["user"], "ana")
        self.assertIsNone(A.read_session("another-secret-value-2", sess))
        body, _, mac = sess.partition(".")
        forged = A.b64u(json.dumps({"k": "sess", "user": "root", "exp": int(time.time()) + 999, "roles": []}).encode())
        self.assertIsNone(A.read_session("secret-secret-secret-1", forged + "." + mac))
        self.assertIsNone(A.read_session("secret-secret-secret-1", sess, now=time.time() + 9 * 3600))  # expired
        self.assertIsNone(A.read_session("secret-secret-secret-1", ""))
        self.assertIsNone(A.read_session("secret-secret-secret-1", "garbage"))
        tx = A.sign_blob("secret-secret-secret-1", {"k": "tx", "exp": int(time.time()) + 99})
        self.assertIsNone(A.read_session("secret-secret-secret-1", tx))  # a sign-in transaction is not a session


class FlowTests(unittest.TestCase):
    """finish_login and begin_login against the fake provider, without the Metis web server."""
    @classmethod
    def setUpClass(cls):
        cls.a, cls.b = keys()

    def setUp(self):
        A.clear_cache()
        self.prov = FakeProvider(self.a)
        self.cfg = A.config({"auth": {"mode": "oidc", "issuer": self.prov.issuer, "client_id": "metis-ui", "client_secret_env": "X",
                                      "redirect_uri": "http://127.0.0.1:9/oidc/callback", "session_secret_env": "S", "allowed_domains": ["example.com"],
                                      "group_map": {"metis-leads": "lead"}}})
        self.secret = "0123456789abcdef-secret"

    def tearDown(self):
        self.prov.close()

    def login(self, **kw):
        url, tx = A.begin_login(self.cfg, self.secret, "/golden")
        back = self.prov.authorize(url)
        return A.finish_login(self.cfg, self.secret, tx, back, self.prov.client_secret, python_only=True, **kw)

    def test_authorization_url_has_pkce_state_nonce(self):
        url, tx = A.begin_login(self.cfg, self.secret)
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
        self.assertEqual((q["response_type"], q["code_challenge_method"], q["client_id"]), ("code", "S256", "metis-ui"))
        self.assertEqual(q["scope"], "openid profile email")
        self.assertGreaterEqual(len(q["state"]), 16)
        self.assertGreaterEqual(len(q["nonce"]), 16)
        payload = A.open_blob(self.secret, tx, "tx")
        self.assertEqual(q["code_challenge"], A.b64u(hashlib.sha256(payload["cv"].encode()).digest()))
        self.assertNotIn(payload["cv"], url)  # the verifier never travels in the URL

    def test_full_flow_gives_the_verified_identity_and_where_to_go(self):
        ident, back = self.login()
        self.assertEqual(ident["user"], "ana@example.com")
        self.assertEqual(ident["roles"], ["lead"])
        self.assertEqual(back, "/golden")

    def test_state_mismatch_replayed_code_and_missing_transaction(self):
        url, tx = A.begin_login(self.cfg, self.secret)
        back = self.prov.authorize(url)
        with self.assertRaisesRegex(A.AuthError, "state"):
            A.finish_login(self.cfg, self.secret, tx, dict(back, state="other"), self.prov.client_secret, python_only=True)
        A.finish_login(self.cfg, self.secret, tx, back, self.prov.client_secret, python_only=True)
        with self.assertRaisesRegex(A.AuthError, "identity provider answered 400"):  # a code works once
            A.finish_login(self.cfg, self.secret, tx, back, self.prov.client_secret, python_only=True)
        with self.assertRaisesRegex(A.AuthError, "expired or did not start here"):
            A.finish_login(self.cfg, self.secret, "", back, self.prov.client_secret, python_only=True)
        with self.assertRaisesRegex(A.AuthError, "expired"):
            A.finish_login(self.cfg, self.secret, tx, back, self.prov.client_secret, now=time.time() + 3600, python_only=True)
        with self.assertRaisesRegex(A.AuthError, "no authorization code"):
            A.finish_login(self.cfg, self.secret, tx, {"state": back["state"]}, self.prov.client_secret, python_only=True)

    def test_provider_error_is_reported_not_trusted(self):
        _, tx = A.begin_login(self.cfg, self.secret)
        with self.assertRaisesRegex(A.AuthError, "access_denied"):
            A.finish_login(self.cfg, self.secret, tx, {"error": "access_denied", "error_description": "no"}, "", python_only=True)

    def test_pkce_is_enforced_by_the_provider(self):
        url, tx = A.begin_login(self.cfg, self.secret)
        back = self.prov.authorize(url)
        other = A.open_blob(self.secret, tx, "tx")
        other["cv"] = "x" * 50
        bad = A.sign_blob(self.secret, other)
        with self.assertRaisesRegex(A.AuthError, "PKCE"):
            A.finish_login(self.cfg, self.secret, bad, back, self.prov.client_secret, python_only=True)

    def test_wrong_client_secret_is_refused_by_the_provider(self):
        url, tx = A.begin_login(self.cfg, self.secret)
        with self.assertRaisesRegex(A.AuthError, "401"):
            A.finish_login(self.cfg, self.secret, tx, self.prov.authorize(url), "wrong", python_only=True)

    def test_forged_expired_wrong_audience_and_nonce_tokens_from_the_token_endpoint(self):
        evil = Key("kid-a")
        cases = [("signature", dict(sign_with=evil)),
                 ("expired", dict(tamper=lambda c: dict(c, iat=c["iat"] - 9999, exp=c["exp"] - 9999))),
                 ("audience", dict(tamper=lambda c: dict(c, aud="someone-else"))),
                 ("issuer", dict(tamper=lambda c: dict(c, iss="https://evil.example"))),
                 ("nonce", dict(nonce_override="replayed-nonce"))]
        for text, attrs in cases:
            for k in ("sign_with", "tamper", "nonce_override"):
                setattr(self.prov, k, None)
            for k, v in attrs.items():
                setattr(self.prov, k, v)
            with self.assertRaisesRegex(A.AuthError, text, msg=text):
                self.login()

    def test_domain_not_allowed(self):
        self.prov.claims = dict(self.prov.claims, email="mal@evil.com", preferred_username="mal")
        with self.assertRaisesRegex(A.AuthError, "domain"):
            self.login()

    def test_rotated_key_is_picked_up_with_one_refetch(self):
        self.login()  # caches the key set with key A
        new = Key("kid-new")
        self.prov.published = [self.a, new]
        self.prov.sign_with = new
        ident, _ = self.login()
        self.assertEqual(ident["user"], "ana@example.com")

    def test_unreachable_provider_and_wrong_issuer_document(self):
        A.clear_cache()
        cfg = dict(self.cfg, issuer="http://127.0.0.1:1")
        with self.assertRaisesRegex(A.AuthError, "cannot reach"):
            A.begin_login(cfg, self.secret)
        A.clear_cache()
        cfg = dict(self.cfg, issuer=self.prov.issuer + "/")
        A.begin_login(cfg, self.secret)  # a trailing slash is the same issuer for discovery
        A.clear_cache()
        self.prov.issuer = "http://127.0.0.1:1/other"
        with self.assertRaisesRegex(A.AuthError, "different issuer"):
            A.discovery(self.cfg["issuer"])


class ServerTests(unittest.TestCase):
    """The Metis web server with auth.mode oidc, against the fake provider. The RSA check runs the pure-Python path."""
    @classmethod
    def setUpClass(cls):
        import server
        cls.server = server
        cls.a, cls.b = keys()

    def setUp(self):
        A.clear_cache()
        self.patches = [mock.patch.object(A, "USE_CRYPTOGRAPHY", False),
                        mock.patch.dict(os.environ, {"METIS_TEST_SESSION": "session-secret-0123456789", "METIS_TEST_CLIENT": "s3cret-value"})]
        for p in self.patches:
            p.start()
        self.prov = FakeProvider(self.a)
        self.d = tempfile.mkdtemp()
        self.kb = os.path.join(self.d, "kb")
        write(os.path.join(self.kb, "context", "rules.md"), "Claims are paid within 30 days.\n")
        self.srv = self.server.serve(self.kb, host="127.0.0.1", port=0, password=None)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.profile(owners={"kb_owner": "ana@example.com"})

    def profile(self, auth=None, **more):
        a = {"mode": "oidc", "issuer": self.prov.issuer, "client_id": "metis-ui", "client_secret_env": "METIS_TEST_CLIENT",
             "redirect_uri": "http://127.0.0.1:%d/oidc/callback" % self.port, "session_secret_env": "METIS_TEST_SESSION",
             "group_map": {"metis-leads": "lead"}}
        a.update(auth or {})
        prof = {"product": {"name": "Demo"}, "auth": a}
        prof.update(more)
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump(prof))

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.prov.close()
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.d, ignore_errors=True)

    # a tiny browser: keeps cookies, never follows redirects
    def req(self, method, path, jar, data=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        h = dict(headers or {})
        if jar:
            h["Cookie"] = "; ".join("%s=%s" % kv for kv in jar.items())
        body = urllib.parse.urlencode(data).encode() if data is not None else None
        if body is not None:
            h["Content-Type"] = "application/x-www-form-urlencoded"
        c.request(method, path, body=body, headers=h)
        r = c.getresponse()
        text = r.read().decode("utf-8", "replace")
        for k, v in r.getheaders():
            if k.lower() == "set-cookie":
                sc = http.cookies.SimpleCookie(v)
                for name, m in sc.items():
                    if m.value == "" or m["max-age"] == "0":
                        jar.pop(name, None)
                    else:
                        jar[name] = m.value
        out = (r.status, {k.lower(): v for k, v in r.getheaders()}, text, [v for k, v in r.getheaders() if k.lower() == "set-cookie"])
        c.close()
        return out

    def sign_in(self, jar, back="/"):
        code, hdr, _, _ = self.req("GET", "/login?back=" + urllib.parse.quote(back), jar)
        self.assertEqual(code, 303)
        cb = self.prov.authorize(hdr["location"])
        code, hdr, body, cookies_ = self.req("GET", "/oidc/callback?" + urllib.parse.urlencode(cb), jar)
        return code, hdr, body, cookies_

    def page_token(self, jar):
        return re.search(r'name="_t" value="([^"]+)"', self.req("GET", "/golden", jar)[2]).group(1)  # the name box (and its token) is gone

    def test_without_a_session_every_page_goes_to_login(self):
        for path in ("/", "/files", "/golden"):
            code, hdr, _, _ = self.req("GET", path, {})
            self.assertEqual(code, 303)
            self.assertTrue(hdr["location"].startswith("/login?back="), hdr["location"])
        self.assertEqual(self.req("POST", "/whoami", {}, {"name": "x", "_t": "t"})[0], 303)
        self.assertEqual(self.req("GET", "/health", {})[0], 200)

    def test_login_redirects_to_the_provider_with_pkce(self):
        jar = {}
        code, hdr, _, cookies_ = self.req("GET", "/login", jar)
        self.assertEqual(code, 303)
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(hdr["location"]).query))
        self.assertEqual(q["code_challenge_method"], "S256")
        self.assertEqual(q["redirect_uri"], "http://127.0.0.1:%d/oidc/callback" % self.port)
        self.assertTrue(any("HttpOnly" in c and c.startswith(A.TX_COOKIE) for c in cookies_))

    def test_full_sign_in_shows_the_verified_identity(self):
        jar = {}
        code, hdr, _, cookies_ = self.sign_in(jar, "/golden")
        self.assertEqual((code, hdr["location"]), (303, "/golden"))
        sess = [c for c in cookies_ if c.startswith(A.SESSION_COOKIE)][0]
        self.assertIn("HttpOnly", sess)
        self.assertIn("SameSite=Lax", sess)
        self.assertNotIn(A.TX_COOKIE, jar)  # the transaction cookie is cleared
        code, _, body, _ = self.req("GET", "/golden", jar)
        self.assertEqual(code, 200)
        self.assertIn("Signed in as", body)
        self.assertIn("<b>ana@example.com</b>", body)
        self.assertNotIn('name="name"', body)  # the name box is gone
        self.assertIn("SSO roles: lead", body)
        self.assertNotIn(self.prov.client_secret, body)

    def test_a_cookie_cannot_spoof_the_user(self):
        jar = {}
        self.sign_in(jar)
        jar["metis_user"] = "Mallory"
        body = self.req("GET", "/", jar)[2]
        self.assertIn("<b>ana@example.com</b>", body)
        self.assertNotIn("Mallory", body)
        # no session at all: the name cookie does not get you in either
        code, _, _, _ = self.req("GET", "/", {"metis_user": "Ana"})
        self.assertEqual(code, 303)

    def test_forged_or_expired_session_cookie_is_not_a_session(self):
        jar = {}
        self.sign_in(jar)
        good = jar[A.SESSION_COOKIE]
        body, _, mac = good.partition(".")
        forged = A.b64u(json.dumps({"k": "sess", "user": "root", "roles": ["lead"], "sub": "1", "exp": int(time.time()) + 9999}).encode())
        for bad in (forged + "." + mac, A.sign_blob("a-guess-at-the-secret-1", json.loads(A.b64u_dec(body))), "x", good[:-3] + "AAA"):
            self.assertEqual(self.req("GET", "/", {A.SESSION_COOKIE: bad})[0], 303)
        old = A.sign_blob(os.environ["METIS_TEST_SESSION"], {"k": "sess", "user": "ana", "sub": "1", "roles": [], "exp": int(time.time()) - 5})
        self.assertEqual(self.req("GET", "/", {A.SESSION_COOKIE: old})[0], 303)

    def test_whoami_is_refused_while_sso_is_on(self):
        jar = {}
        self.sign_in(jar)
        tok = self.page_token(jar)
        code, _, body, cookies_ = self.req("POST", "/whoami", jar, {"name": "Mallory", "_t": tok})
        self.assertEqual(code, 403)
        self.assertFalse(any("metis_user" in c for c in cookies_))
        self.assertIn("Signed in through SSO", body)

    def test_gate_actions_record_the_verified_identity(self):
        import golden
        jar = {"metis_user": "Mallory"}
        self.sign_in(jar)
        tok = self.page_token(jar)
        form = {"question": "How fast are claims paid?", "cite": "context/rules.md", "include": "30 days", "_t": tok}
        code, _, body, _ = self.req("POST", "/golden/add", jar, form)
        self.assertEqual(code, 303, body[:300])
        g = golden.load(self.kb)["golden"][0]
        self.assertEqual(g["added_by"], "ana@example.com")

    def test_a_signed_in_person_who_is_not_a_lead_cannot_use_a_lead_action(self):
        import golden
        self.prov.claims = dict(self.prov.claims, preferred_username="pat@example.com", email="pat@example.com", groups=[])
        jar = {}
        self.sign_in(jar)
        tok = self.page_token(jar)
        code, _, body, _ = self.req("POST", "/golden/add", jar, {"question": "q", "cite": "context/rules.md", "_t": tok})
        self.assertEqual(code, 400)
        self.assertIn("pat@example.com", body)
        self.assertEqual(golden.load(self.kb).get("golden") or [], [])

    def test_callback_failures_show_a_page_and_set_no_session(self):
        jar = {}
        code, hdr, _, _ = self.req("GET", "/login", jar)
        cb = self.prov.authorize(hdr["location"])
        bad = dict(cb, state="tampered")
        code, _, body, cookies_ = self.req("GET", "/oidc/callback?" + urllib.parse.urlencode(bad), jar)
        self.assertEqual(code, 403)
        self.assertIn("Sign-in failed", body)
        self.assertFalse(any(c.startswith(A.SESSION_COOKIE) for c in cookies_))
        code, _, body, _ = self.req("GET", "/oidc/callback?code=abc&state=x", {})
        self.assertEqual(code, 403)
        self.prov.tamper = lambda c: dict(c, aud="other-app")
        jar = {}
        _, hdr, _, _ = self.req("GET", "/login", jar)
        code, _, body, cookies_ = self.req("GET", "/oidc/callback?" + urllib.parse.urlencode(self.prov.authorize(hdr["location"])), jar)
        self.assertEqual(code, 403)
        self.assertIn("audience", body)
        self.assertFalse(any(c.startswith(A.SESSION_COOKIE) for c in cookies_))

    def test_open_redirect_through_back_is_blocked(self):
        for evil in ("//evil.example/x", "http://evil.example", "\\\\evil", "/ok\r\nSet-Cookie: a=b"):
            jar = {}
            code, hdr, _, _ = self.req("GET", "/login?back=" + urllib.parse.quote(evil), jar)
            cb = self.prov.authorize(hdr["location"])
            code, hdr, _, _ = self.req("GET", "/oidc/callback?" + urllib.parse.urlencode(cb), jar)
            self.assertEqual((code, hdr["location"]), (303, "/"), evil)

    def test_logout_clears_the_session(self):
        jar = {}
        self.sign_in(jar)
        code, _, body, _ = self.req("GET", "/logout", jar)
        self.assertEqual(code, 200)
        self.assertNotIn(A.SESSION_COOKIE, jar)
        self.assertEqual(self.req("GET", "/", jar)[0], 303)

    def test_misconfigured_sso_stops_the_server_and_never_falls_back_to_the_name_box(self):
        self.profile(auth={"session_secret_env": "METIS_NOT_SET_ANYWHERE"})
        jar = {"metis_user": "Ana"}
        code, _, body, _ = self.req("GET", "/", jar)
        self.assertEqual(code, 303)  # no session; and /login says why it cannot continue
        code, _, body, _ = self.req("GET", "/login", {})
        self.assertEqual(code, 403)
        self.assertIn("METIS_NOT_SET_ANYWHERE", body)
        self.profile(auth={"issuer": "not a url"})
        code, _, body, _ = self.req("GET", "/", {"metis_user": "Ana"})
        self.assertEqual(code, 503)
        self.assertIn("Sign-in is not set up", body)

    def test_mode_none_is_exactly_todays_behaviour(self):
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump({"product": {"name": "Demo"}, "auth": {"mode": "none"}}))
        code, _, body, _ = self.req("GET", "/", {"metis_user": "Ana%20Lead"})
        self.assertEqual(code, 200)
        self.assertIn('name="name"', body)
        self.assertIn('value="Ana Lead"', body)
        self.assertNotIn("Signed in as", body)
        self.assertEqual(self.req("GET", "/login", {})[0], 404)
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump({"product": {"name": "Demo"}}))
        self.assertEqual(self.req("GET", "/", {})[0], 200)


class CliTests(unittest.TestCase):
    def test_check_command(self):
        kb = tempfile.mkdtemp()
        try:
            self.assertEqual(A.main(["check", kb]), 0)
            write(os.path.join(kb, ".metis", "kb-profile.yaml"), yaml.safe_dump({"auth": {
                "mode": "oidc", "issuer": "https://idp.example", "client_id": "c", "redirect_uri": "https://m.example/oidc/callback",
                "session_secret_env": "METIS_TEST_CLI_SECRET"}}))
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("METIS_TEST_CLI_SECRET", None)
                self.assertEqual(A.main(["check", kb]), 1)  # the secret variable is not set
            with mock.patch.dict(os.environ, {"METIS_TEST_CLI_SECRET": "x" * 20}):
                self.assertEqual(A.main(["check", kb]), 0)
        finally:
            shutil.rmtree(kb, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
