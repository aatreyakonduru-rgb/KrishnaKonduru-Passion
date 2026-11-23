#!/usr/bin/env python3
"""The Metis UI: eight screens over one KB. Standard library plus PyYAML; nothing to install.

    METIS_KB=/path/to/KB python3 server.py [--port 8765] [--host 127.0.0.1]
    python3 server.py --kb /path/to/KB

Screens: Home, Setup, Build, KB files, Ask, Questions, Approve, Coverage. Model work (writing KB pages, reasoning answers) is queued
as tasks for a Devin session (see tasks.py and the skill `metis-tasks`); everything else runs here.

Safety:
  - Listens on 127.0.0.1 unless --host says otherwise. A host that is not loopback needs METIS_UI_PASSWORD (HTTP basic auth, any
    user name); the server refuses to start without it. In Devin cloud, expose the port through the session's port forward.
  - Every form carries a per-run token; a POST without it is refused.
  - "You are" (top right) is a name kept in a cookie. It decides who the page says approved something; whether that person is a lead
    is checked by kb_gate.py against the KB profile, as everywhere else in Metis.
  - Writes stay inside the KB folder (metis-writes). Source repos and databases are never written.
"""
import argparse
import base64
import hmac
import inspect
import os
import secrets
import sys
import threading
import urllib.parse
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import api  # noqa: E402
import auth_oidc  # noqa: E402
import ui_common as C  # noqa: E402
import views  # noqa: E402

SCREENS = {"/": views.home, "/setup": views.setup, "/build": views.build, "/files": views.files, "/ask": views.ask,
           "/questions": views.questions_view, "/approve": views.approve, "/coverage": views.coverage, "/task": views.task_view}
ACTIONS = {
    "/setup/profile": ("/setup", views.act_setup_profile), "/setup/detect": ("/setup", views.act_setup_detect),
    "/setup/approve": ("/setup", views.act_setup_approve), "/setup/databases": ("/setup", views.act_setup_databases),
    "/setup/check": ("/setup", views.act_setup_check),
    "/build/start": ("/build", views.act_build_start), "/build/finish": ("/build", views.act_build_finish),
    "/build/cancel": ("/build", views.act_build_cancel), "/task/requeue": ("/build", views.act_task_requeue),
    "/ask/new": ("/ask", views.act_ask_new), "/ask/rate": ("/ask", views.act_ask_rate), "/ask/reply": ("/ask", views.act_ask_reply),
    "/ask/clarify": ("/ask", views.act_ask_clarify), "/ask/reword": ("/ask", views.act_ask_reword),
    "/questions/answer": ("/questions", views.act_question_answer), "/questions/raise": ("/questions", views.act_question_raise),
    "/approve/lock": ("/approve", views.act_approve_lock), "/approve/batch": ("/approve", views.act_approve_batch),
    "/approve/feedback": ("/approve", views.act_approve_feedback), "/coverage/refresh": ("/coverage", views.act_coverage_refresh),
}
def load_screens():
    """Add every tools/ui/screens_*.py. A module defines SCREENS {path: fn(ctx, q, flash=None, error=None)},
    ACTIONS {path: (screen path, fn(ctx, form) -> (where, message))} and NAV [(path, label)]. A clash of paths is an error;
    a module that does not import is reported on stderr and skipped, so one broken screen never takes the others down."""
    failed = {}
    for name in sorted(os.listdir(HERE)):
        if not (name.startswith("screens_") and name.endswith(".py")):
            continue
        try:
            m = __import__(name[:-3])
            for p in list(m.SCREENS) + list(m.ACTIONS):
                if p in SCREENS or p in ACTIONS:
                    raise ValueError("path %s is already used" % p)
            for p, (screen, _) in m.ACTIONS.items():
                if screen not in SCREENS and screen not in m.SCREENS:
                    raise ValueError("action %s returns to unknown screen %s" % (p, screen))
        except Exception as err:
            failed[name] = "%s: %s" % (type(err).__name__, err)
            sys.stderr.write("screen module %s skipped: %s\n" % (name, failed[name]))
            continue
        SCREENS.update(m.SCREENS)
        ACTIONS.update(m.ACTIONS)
        C.NAV_MORE.extend(m.NAV)
    return failed


LOAD_FAILED = load_screens()
if "/search" in SCREENS:  # the top bar search goes to the global search once that screen exists; /files?find= keeps working
    C.SEARCH_FORM = ("/search", "q", "Search the KB")
LOOPBACK = ("127.0.0.1", "localhost", "::1")
MAX_BODY = 2 * 1024 * 1024
WRITE_LOCK = threading.Lock()


class Form(dict):
    """Form fields: .get gives the first value, .getall every value of a repeated field."""
    def __init__(self, pairs):
        super().__init__()
        self.multi = {}
        for k, v in pairs:
            self.multi.setdefault(k, []).append(v)
            self.setdefault(k, v)

    def getall(self, k):
        return self.multi.get(k, [])


def make_handler(kb, password):
    token = secrets.token_urlsafe(24)

    class Handler(BaseHTTPRequestHandler):
        server_version = "Metis"

        def log_message(self, fmt, *a):
            sys.stderr.write("%s %s\n" % (self.address_string(), fmt % a))

        # ---- helpers
        def cookie(self, name):
            c = cookies.SimpleCookie(self.headers.get("Cookie") or "")
            return c[name].value if name in c else ""

        def user(self):
            return C.clean(urllib.parse.unquote(self.cookie("metis_user")))

        def auth_cfg(self):
            """(OIDC settings or None, problem). Read from the profile on every request. A profile that asks for OIDC but cannot
            work gives a problem and the server then refuses to serve pages, never falling back to the name box."""
            try:
                return auth_oidc.config(C.profile(kb)), ""
            except auth_oidc.AuthError as err:
                return None, str(err)

        def session(self, cfg):
            """The signed session of this browser, or None. Only a cookie this server signed counts."""
            try:
                return auth_oidc.read_session(auth_oidc.session_secret(cfg), self.cookie(auth_oidc.SESSION_COOKIE))
            except auth_oidc.AuthError:
                return None

        def ctx(self):
            cfg, _ = self.auth_cfg()
            if cfg:  # with sign-in on, the name comes from the signed session only; the metis_user cookie is ignored
                s = self.session(cfg) or {}
                user, roles, sso = C.clean(s.get("user")), s.get("roles") or [], True
            else:
                user, roles, sso = self.user(), [], False
            return C.Ctx(kb, token, user, self.cookie("theme"), C.clean(urllib.parse.unquote(self.cookie("metis_env"))), sso, roles)

        def sso_gate(self, path):
            """True when the request was answered here: sign-in is misconfigured, or the person has no session yet."""
            cfg, problem = self.auth_cfg()
            if problem:
                self.send(503, page_error(C.Ctx(kb, token), "Sign-in is not set up", problem))
                return True
            if not cfg or path in ("/health", "/login", "/oidc/callback", "/logout", "/theme") or self.session(cfg):
                return False
            if self.command == "GET":
                self.redirect("/login?" + urllib.parse.urlencode({"back": safe_back(self.path)}))
            else:
                self.redirect("/login")
            return True

        def back_to(self, default="/"):
            """Where to return after a small action: the page the person was on (path and query, flash text dropped)."""
            u = urllib.parse.urlparse(self.headers.get("Referer") or "")
            if u.path.rstrip("/") not in SCREENS and u.path != "/":
                return default
            q = [(k, v) for k, v in urllib.parse.parse_qsl(u.query) if k not in ("m", "e")]
            return (u.path or "/") + ("?" + urllib.parse.urlencode(q) if q else "")

        def theme_cookie(self, value):
            if value not in C.THEMES:
                raise C.UiError("The theme must be one of: %s." % ", ".join(C.THEMES))
            return [("Set-Cookie", "theme=%s; Path=/; SameSite=Lax; HttpOnly; Max-Age=31536000" % value)]

        def oidc(self, path, q):
            """/login, /oidc/callback, /logout. All answers are pages or redirects; none shows a secret or a token."""
            cfg, _ = self.auth_cfg()
            if not cfg:
                return self.send(404, page_error(self.ctx(), "Not found", "Sign-in is not turned on (auth.mode in the KB profile)."))
            secure = "; Secure" if cfg["redirect_uri"].startswith("https:") else ""
            if path == "/logout":
                gone = [("Set-Cookie", "%s=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax%s" % (auth_oidc.SESSION_COOKIE, secure))]
                return self.send(200, '<!DOCTYPE html><meta charset="utf-8"><title>Signed out</title><p>You are signed out of Metis. '
                                 '<a href="/login">Sign in again</a></p>', extra=gone)
            try:
                secret = auth_oidc.session_secret(cfg)
                if path == "/login":
                    url, tx = auth_oidc.begin_login(cfg, secret, safe_back(q.get("back")))
                    return self.redirect(url, extra=[("Set-Cookie", "%s=%s; Path=/; Max-Age=%d; HttpOnly; SameSite=Lax%s" % (
                        auth_oidc.TX_COOKIE, tx, auth_oidc.TX_SECONDS, secure))])
                ident, back = auth_oidc.finish_login(cfg, secret, self.cookie(auth_oidc.TX_COOKIE), q, auth_oidc.client_secret(cfg))
            except auth_oidc.AuthError as err:
                return self.send(403, page_error(C.Ctx(kb, token), "Sign-in failed", str(err)))
            sess = auth_oidc.make_session(cfg, secret, ident)
            return self.redirect(safe_back(back), extra=[
                ("Set-Cookie", "%s=%s; Path=/; Max-Age=%d; HttpOnly; SameSite=Lax%s" % (
                    auth_oidc.SESSION_COOKIE, sess, cfg["session_hours"] * 3600, secure)),
                ("Set-Cookie", "%s=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax%s" % (auth_oidc.TX_COOKIE, secure))])

        def authed(self):
            if not password:
                return True
            h = self.headers.get("Authorization") or ""
            if h.startswith("Basic "):
                try:
                    given = base64.b64decode(h[6:]).decode("utf-8", "replace").partition(":")[2]
                    return hmac.compare_digest(given.encode(), password.encode())
                except Exception:
                    return False
            return False

        def deny(self):
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="Metis"')
            self.send_header("Content-Length", "0")
            self.end_headers()

        def send(self, code, body, ctype="text/html; charset=utf-8", extra=()):
            data = body.encode("utf-8") if isinstance(body, str) else body
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "same-origin")
            for k, v in extra:
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def redirect(self, where, msg=None, err=None, extra=()):
            path, _, frag = where.partition("#")
            if msg or err:
                path += ("&" if "?" in path else "?") + urllib.parse.urlencode({"m" if msg else "e": msg or err})
            self.send_response(303)
            self.send_header("Location", path + ("#" + frag if frag else ""))
            self.send_header("Content-Length", "0")
            for k, v in extra:
                self.send_header(k, v)
            self.end_headers()

        def render(self, path, q, flash=None, error=None, form_values=None):
            fn = SCREENS[path]
            params = inspect.signature(fn).parameters
            kw = {}
            if "flash" in params:
                kw["flash"] = flash
            if "error" in params:
                kw["error"] = error
            if form_values is not None and "values" in params:
                kw["values"] = form_values
            return fn(self.ctx(), q, **kw)

        # ---- GET
        def do_GET(self):
            if not self.authed():
                return self.deny()
            u = urllib.parse.urlparse(self.path)
            q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
            path = u.path.rstrip("/") or "/"
            try:
                if self.sso_gate(path):
                    return
                if path in ("/login", "/oidc/callback", "/logout"):
                    return self.oidc(path, q)
                if path == "/theme":
                    return self.redirect(self.back_to(), extra=self.theme_cookie(q.get("set", "")))
                if path.startswith("/viz/"):
                    return self.viz(path[5:])
                served = api.handle(kb, self.ctx().user, "GET", path, q, secured=bool(password))
                if served:
                    return self.send(*served)
                if path == "/health":
                    return self.send(200, "ok", "text/plain")
                if path not in SCREENS:
                    return self.send(404, page_error(self.ctx(), "Not found", "There is no page at %s." % path))
                return self.send(200, self.render(path, q, q.get("m"), q.get("e")))
            except C.UiError as err:
                return self.send(400, page_error(self.ctx(), "Cannot show this", str(err)))
            except Exception as err:  # a screen must never take the server down
                sys.stderr.write("error on %s: %r\n" % (path, err))
                return self.send(500, page_error(self.ctx(), "Something went wrong", "%s: %s" % (type(err).__name__, err)))

        def viz(self, rel):
            root = os.path.join(kb, "VISUALIZATION")
            p = os.path.normpath(os.path.join(root, urllib.parse.unquote(rel)))
            if not p.startswith(os.path.normpath(root) + os.sep) or not os.path.isfile(p):
                return self.send(404, "not found", "text/plain")
            ctype = "text/html; charset=utf-8" if p.endswith(".html") else "application/octet-stream"
            with open(p, "rb") as fh:
                self.send(200, fh.read(), ctype, [("Content-Security-Policy", "sandbox allow-scripts")])

        # ---- POST
        def do_POST(self):
            if not self.authed():
                return self.deny()
            u = urllib.parse.urlparse(self.path)
            path = u.path.rstrip("/") or "/"
            if self.sso_gate(path):
                return
            if path in ("/openapi.json", "/llms.txt") or path.startswith("/api/"):
                return self.send(*api.handle(kb, "", "POST", path, {}))
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = 0
            if n > MAX_BODY:
                return self.send(413, "too large", "text/plain")
            raw = self.rfile.read(n).decode("utf-8", "replace")
            f = Form(urllib.parse.parse_qsl(raw, keep_blank_values=True))
            if not hmac.compare_digest(str(f.get("_t", "")), token):
                return self.send(403, page_error(self.ctx(), "Page expired", "Reload the page and try again."))
            if path == "/theme":  # the same thing as GET /theme?set=..., for a form
                try:
                    return self.redirect(self.back_to(), extra=self.theme_cookie(C.clean(f.get("set"))))
                except C.UiError as err:
                    return self.send(400, page_error(self.ctx(), "Cannot set the theme", str(err)))
            if path == "/env":
                name = C.clean(f.get("name"))
                if name not in C.environments(kb)[0]:
                    return self.send(400, page_error(self.ctx(), "Cannot switch environment", "That environment is not in db-environments.yaml."))
                ck = "metis_env=%s; Path=/; SameSite=Lax; HttpOnly; Max-Age=31536000" % urllib.parse.quote(name)
                return self.redirect(self.back_to(), "Environment: %s." % name, extra=[("Set-Cookie", ck)])
            if path == "/whoami" and self.auth_cfg()[0]:
                return self.send(403, page_error(self.ctx(), "Signed in through SSO", "Your name comes from the identity provider and cannot be typed over."))
            if path == "/whoami":
                name = C.clean(f.get("name"))[:80]
                back = self.headers.get("Referer") or "/"
                back = urllib.parse.urlparse(back).path or "/"
                ck = "metis_user=%s; Path=/; SameSite=Strict; HttpOnly; Max-Age=31536000" % urllib.parse.quote(name)
                return self.redirect(back if back in SCREENS else "/", "You are %s." % name if name else "Name cleared.", extra=[("Set-Cookie", ck)])
            if path not in ACTIONS:
                return self.send(404, page_error(self.ctx(), "Not found", "There is no action at %s." % path))
            screen, action = ACTIONS[path]
            ctx = self.ctx()
            try:
                with WRITE_LOCK:
                    where, msg = action(ctx, f)
                return self.redirect(where, msg)
            except (C.UiError, ValueError) as err:
                # show the screen the person was on, with the problem and, for the profile, what they typed
                vals = dict(f) if path == "/setup/profile" else None
                if vals is not None:
                    vals["roles"] = {r: f.get("role_" + r.replace(" ", "_"), "") for r in views.setup_ops.ROLES}
                return self.send(400, self.render(screen, {}, None, str(err), vals))
            except Exception as err:
                sys.stderr.write("error on %s: %r\n" % (path, err))
                return self.send(500, self.render(screen, {}, None, "%s: %s" % (type(err).__name__, err)))

    return Handler


def safe_back(target):
    """A local path to return to after sign-in; anything that could leave this site becomes '/'."""
    t = str(target or "/")
    if not t.startswith("/") or t.startswith("//") or "\\" in t or any(ord(c) < 32 for c in t):
        return "/"
    return t


def page_error(ctx, title, text):
    return C.page(ctx, title, "", "<h1>%s</h1><p><a href=\"/\">Back to Home</a></p>" % C.esc(title), error=text)


def serve(kb, host, port, password=None):
    kb = os.path.abspath(kb)
    if not os.path.isdir(kb):
        raise SystemExit("KB folder not found: %s (create it, or point METIS_KB at it)" % kb)
    if host not in LOOPBACK and not password:
        raise SystemExit("Refusing to listen on %s without a password. Set METIS_UI_PASSWORD, or use --host 127.0.0.1." % host)
    os.makedirs(os.path.join(kb, ".metis"), exist_ok=True)
    srv = ThreadingHTTPServer((host, port), make_handler(kb, password))
    return srv


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--kb", default=os.environ.get("METIS_KB"))
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args(argv)
    if not a.kb:
        print("Give the KB folder: --kb <folder> or METIS_KB.", file=sys.stderr)
        return 2
    srv = serve(a.kb, a.host, a.port, os.environ.get("METIS_UI_PASSWORD"))
    print("Metis UI for %s on http://%s:%d/" % (os.path.abspath(a.kb), a.host, a.port), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
