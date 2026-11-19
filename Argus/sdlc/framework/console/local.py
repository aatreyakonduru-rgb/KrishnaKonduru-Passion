#!/usr/bin/env python3
"""Local Devin — a command box on your own PC for your Devin Cloud sessions.

Type anything you would type to Devin Cloud. A few commands run right here on your machine, so the
page they produce opens in your own browser instead of on the Devin VM:

  /argus [stop|status]   start (or stop) Argus on this PC and open it
  /workbench, /console       older names for /argus
  /dashboard [lens]          build your role dashboard and open it (on this PC when it has a Jira key,
                             otherwise in Devin Cloud with the Jira service account)
  /help                      list these commands

Everything else starts a Devin Cloud session (or goes to the session you have open). Devin is asked
to post any page or report it would attach as a ``[SDLC] artefact`` block; this box saves it and
opens it in your browser when it arrives; files Devin attaches are fetched through the Devin API and
open the same way. Sessions are listed from the Devin API, so the box shows the same sessions you see
in the Devin web app.

Stdlib only. Run from a checkout of the repo:
  python3 <framework>/console/local.py --user <e-mail, Jira username or Devin user id>
then open http://127.0.0.1:8785 (it opens by itself unless --no-browser).
Needs a Devin API key only (DEVIN_API_KEY, or the one saved on Argus page). With
the Jira token variable (jira.token_env in .devin/rules/sdlc-profile.json) set, /dashboard is built on this PC in seconds; without it a Devin Cloud
session builds it with the service account and the box opens the page here (about a minute). The
Argus reads its Jira ticket lists the same way, so a PC never needs the Jira token.
State lives in ~/.sdlc/local (SDLC_LOCAL_HOME) — nothing is written into the repository.
"""
import argparse
import importlib.util
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import server as wb  # noqa: E402

LOCAL_TAG = "sdlc-local"
DEFAULT_PORT = 8785
STATE_DIR = os.path.expanduser(os.environ.get("SDLC_LOCAL_HOME", "~/.sdlc/local"))
ARTEFACT_DIR = os.path.join(STATE_DIR, "artefacts")
DASHBOARD_PATH = os.path.join(STATE_DIR, "dashboard.html")
SESSIONS_PATH = os.path.join(STATE_DIR, "dashboard-sessions.json")
SEEN_PATH = os.path.join(STATE_DIR, "seen.json")
WORKBENCH_PID = os.path.join(STATE_DIR, "workbench.pid")
WORKBENCH_LOG = os.path.join(STATE_DIR, "workbench.log")
WORKBENCH_PORT = int(os.environ.get("SDLC_CONSOLE_PORT", "8787"))
WORKBENCH_SERVER = os.path.join(HERE, "server.py")
PAGE = os.path.join(HERE, "static", "local.html")
SESSION_ID_RE = re.compile(r"^(devin-)?[A-Za-z0-9_-]{8,64}$")
CSRF_HEADER = "X-Local-Devin"
DASHBOARD_TAG = "sdlc-dashboard"
JIRA_ENV = wb.JIRA_TOKEN_ENV
ATTACHMENT_RE = re.compile(r"/attachments/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
                           r"/([^\s\"'<>()\[\]`]+)")
UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

LOCAL_COMMANDS = {
    "argus": "Start %s on this PC and open it (/argus stop, /argus status)." % wb.WORKBENCH_TITLE,
    "workbench": "Older name for /argus.",
    "console": "Older name for /argus.",
    "dashboard": "Build your role dashboard and open it; without a Jira key on this PC Devin Cloud builds it "
                 "(/dashboard <lens> for another role's view).",
    "help": "List the commands that run on this PC.",
}

CLOUD_RULES = [
    "",
    "This session was started from Local Devin, a command box on the user's own PC. The user reads your "
    "replies there, and pages open in the browser on their PC, not on this machine. Work exactly as you "
    "would for a message typed in the Devin web app, with one addition:",
    "- Pages and files. Attachments and browser previews do not reach the command box. Anything you would "
    "attach or preview (HTML page, Markdown report, dashboard, spreadsheet as CSV), also post in chat as "
    "`[SDLC] artefact <file name> — ready` followed by its full content in one fenced code block. For a "
    "file that already exists in the repository, post `[SDLC] artefact <path from the repo root> — repo "
    "file` with no code block.",
]


def parse_command(text):
    """('workbench', 'stop') for a local command, (None, text) for anything that goes to Devin Cloud."""
    m = re.match(r"^\s*/([a-z-]+)\b\s*(.*)$", text or "", re.S)
    if m and m.group(1) in LOCAL_COMMANDS:
        return m.group(1), m.group(2).strip()
    return None, (text or "").strip()


def cloud_prompt(text):
    return "\n".join(["Repository: @%s" % wb.REPO_SLUG, "", text] + CLOUD_RULES)


def safe_name(name):
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", (name or "").strip()).strip("._") or "artefact"
    return base[:120]


def short_id(devin_id):
    return devin_id if devin_id.startswith("devin-") else "devin-" + devin_id


# --------------------------------------------------------------------------- Argus on this PC

def _get(url, timeout=2):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status == 200
    except (OSError, ValueError):
        return False


def workbench_base(port=None):
    return "http://127.0.0.1:%d" % (port or WORKBENCH_PORT)


def workbench_up(port=None):
    return _get(workbench_base(port) + "/api/config")


def start_workbench(user, port=None, timeout=45):
    """(url, note) — reuses an Argus already on the port, else starts server.py detached."""
    base = workbench_base(port)
    if workbench_up(port):
        return base, "Argus was already running."
    os.makedirs(STATE_DIR, exist_ok=True)
    cmd = [sys.executable, WORKBENCH_SERVER, "--port", str(port or WORKBENCH_PORT)] + (["--user", user] if user else [])
    kw = {"cwd": wb.ROOT, "stdin": subprocess.DEVNULL, "stderr": subprocess.STDOUT}
    if os.name == "nt":
        kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        kw["start_new_session"] = True
    with open(WORKBENCH_LOG, "ab") as log:
        proc = subprocess.Popen(cmd, stdout=log, **kw)
    with open(WORKBENCH_PID, "w") as fh:
        fh.write(str(proc.pid))
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            raise wb.ApiError(502, "Argus stopped straight away; see %s" % WORKBENCH_LOG)
        if workbench_up(port):
            return base, "Started Argus."
        time.sleep(0.5)
    raise wb.ApiError(504, "Argus did not answer within %d seconds; see %s" % (timeout, WORKBENCH_LOG))


def stop_workbench():
    """Stops Argus this box started. One started by run.sh is stopped with run.sh stop."""
    try:
        with open(WORKBENCH_PID) as fh:
            pid = int(fh.read().strip())
    except (OSError, ValueError):
        return "No Argus started from here is running."
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass
    os.remove(WORKBENCH_PID)
    return "Stopped Argus."


def dashboard_builds_here():
    """True when this PC can build the dashboard itself: a Jira key (or fixture) and PyYAML."""
    return bool(os.environ.get(JIRA_ENV) or wb.DASHBOARD_CACHE) and importlib.util.find_spec("yaml") is not None


def attachments_in(text):
    """[(uuid, file name)] for every Devin attachment URL in a chat message, in order, without repeats."""
    out = []
    for attachment_id, name in ATTACHMENT_RE.findall(text or ""):
        name = urllib.parse.unquote(name).rstrip(".,;:")
        if name and (attachment_id, name) not in out:
            out.append((attachment_id, name))
    return out


def dashboard_prompt(person, lens=""):
    cmd = "python3 %s/console/local.py --cloud-dashboard %s" % (wb.team.FRAMEWORK, person["jira_user"])
    if lens:
        cmd += " --lens %s" % lens
    return "\n".join([
        "Repository: @%s" % wb.REPO_SLUG,
        "",
        "Build the %s role dashboard for %s (%s) and hand it back to their Local Devin box." % (
            wb.PRODUCT, person["name"], person["jira_user"]),
        "",
        "1. From the repository root, run exactly:",
        "   " + cmd,
        "   It builds the dashboard with the Jira service account in this session, uploads the HTML as a",
        "   Devin attachment and prints one line starting with `[SDLC] attachment`.",
        "2. Post that line in chat exactly as printed. That is the whole task; the box closes this session.",
        "3. If the command fails, post its error output instead. Never retry Jira after HTTP 401 or 403.",
        "Do not change the repository, Jira or Confluence, and do not open a PR.",
    ])


class CloudDevin(wb.Devin):
    """Argus's Devin client; upload and download now live in server.Devin."""


# --------------------------------------------------------------------------- the box

class Box:
    def __init__(self, devin, person, open_browser=True):
        self.devin = devin
        self.person = person
        self.open_browser = open_browser
        self.lock = threading.Lock()
        self.seen = self._load_seen()

    # ----- state
    @staticmethod
    def _load_seen():
        try:
            with open(SEEN_PATH, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return {}

    def _save_seen(self):
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(SEEN_PATH, "w", encoding="utf-8") as fh:
            json.dump(self.seen, fh)

    def open_page(self, url):
        """Opens a page in this PC's browser; the box runs on the PC, so this is the user's own browser."""
        if self.open_browser:
            webbrowser.open(url, new=2)

    # ----- local commands
    def run_local(self, name, arg, base):
        if name == "help":
            return {"kind": "local", "text": "\n".join("/%s — %s" % (k, v) for k, v in LOCAL_COMMANDS.items()) +
                    "\nAnything else is sent to Devin Cloud."}
        if name in ("argus", "workbench", "console"):
            if arg == "stop":
                return {"kind": "local", "text": stop_workbench()}
            if arg == "status":
                up = workbench_up()
                return {"kind": "local", "text": "Argus is %s at %s." % (
                    "running" if up else "not running", workbench_base()), "url": workbench_base() if up else ""}
            url, note = start_workbench(self.person["jira_user"] if self.person else "")
            self.open_page(url)
            return {"kind": "local", "text": note + " Opened " + url, "url": url}
        if name == "dashboard":
            if not dashboard_builds_here():
                return self.dashboard_in_cloud(arg)
            self.build_dashboard(arg)
            url = base + "/dashboard"
            self.open_page(url)
            return {"kind": "local", "text": "Dashboard built on this PC. Opened " + url, "url": url}
        raise wb.ApiError(400, "unknown local command /%s" % name)

    def my_sessions_file(self):
        if not (self.person and self.person.get("email") and self.devin.key):
            return None
        try:
            found = self.devin.sessions_of(self.person["email"])
        except wb.ApiError:
            return None
        keep = [{"session_id": i.get("session_id"), "title": i.get("title"),
                 "status": i.get("status_enum") or i.get("status"), "updated": i.get("updated_at"),
                 "tags": i.get("tags") or []}
                for i in found if wb.CLOSED_TAG not in (i.get("tags") or [])
                and (i.get("status_enum") or i.get("status")) not in wb.ENDED]
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(SESSIONS_PATH, "w", encoding="utf-8") as fh:
            json.dump({"sessions": keep}, fh)
        return SESSIONS_PATH

    def build_dashboard(self, lens=""):
        if not self.person:
            raise wb.ApiError(400, "start Local Devin with --user <your e-mail> so the dashboard knows who you are")
        os.makedirs(STATE_DIR, exist_ok=True)
        cmd = [sys.executable, wb.GEN_DASHBOARD, "--user", self.person["jira_user"], "-o", DASHBOARD_PATH]
        if lens:
            cmd += ["--lens", lens.split()[0]]
        if wb.DASHBOARD_CACHE:
            cmd += ["--cache", wb.DASHBOARD_CACHE]
        sessions = self.my_sessions_file()
        if sessions:
            cmd += ["--sessions", sessions]
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=600, cwd=wb.ROOT)
        if done.returncode:
            raise wb.ApiError(502, "dashboard failed: " + (done.stderr or done.stdout)[-600:])
        return DASHBOARD_PATH

    # ----- Devin Cloud
    def dashboard_in_cloud(self, lens=""):
        """Has a Devin Cloud session build the dashboard with the Jira service account; the page opens
        here when the session attaches it."""
        if not self.person:
            raise wb.ApiError(400, "start Local Devin with --user <your e-mail> so the dashboard knows who you are")
        lens = lens.split()[0] if lens else ""
        title = "Dashboard for %s%s" % (self.person["name"], " (%s)" % lens if lens else "")
        session = self.devin.create_session(dashboard_prompt(self.person, lens), title, [LOCAL_TAG, DASHBOARD_TAG])
        sid = session.get("session_id", "")
        with self.lock:
            self.seen[sid] = []
            self._save_seen()
        return {"kind": "created", "session_id": sid, "url": session.get("url", ""),
                "text": "There is no Jira key on this PC, so Devin Cloud is building your dashboard with the "
                        "service account. It opens here when it is ready, usually in a minute or two."}

    def command(self, text, session_id, base):
        name, rest = parse_command(text)
        if name:
            return self.run_local(name, rest, base)
        if not rest:
            raise wb.ApiError(400, "nothing to send")
        if session_id:
            self.devin.send(short_id(session_id), rest)
            return {"kind": "sent", "session_id": short_id(session_id)}
        tags = [LOCAL_TAG]
        session = self.devin.create_session(cloud_prompt(rest), rest.splitlines()[0][:80], tags)
        sid = session.get("session_id", "")
        with self.lock:
            self.seen[sid] = []
            self._save_seen()
        return {"kind": "created", "session_id": sid, "url": session.get("url", "")}

    def sessions(self):
        if self.person and self.person.get("email"):
            found = self.devin.sessions_of(self.person["email"])
        else:
            found = self.devin.list_sessions(LOCAL_TAG)
        out = []
        for i in found:
            tags = i.get("tags") or []
            out.append({"session_id": i.get("session_id"), "title": i.get("title") or "(untitled)",
                        "status": i.get("status_enum") or i.get("status") or "", "updated": i.get("updated_at") or "",
                        "closed": wb.CLOSED_TAG in tags, "local": LOCAL_TAG in tags, "tags": tags})
        out.sort(key=lambda s: s["updated"], reverse=True)
        return out

    def session(self, devin_id, base):
        devin_id = short_id(devin_id)
        info = self.devin.session(devin_id)
        messages, artefacts = [], []
        for m in wb.Devin.messages(info):
            messages.append({"source": m["source"], "at": m.get("created_at"), "text": m.get("message", "")})
            if m["source"] != "devin":
                continue
            for art in wb.parse_devin_message(m.get("message", ""))[3]:
                artefacts.append(self._store_artefact(devin_id, len(artefacts), art, base))
            for attachment_id, fname in attachments_in(m.get("message", "")):
                artefacts.append({"n": len(artefacts), "name": fname, "key": "att:" + attachment_id,
                                  "url": "%s/attachment/%s/%s/%s" % (base, devin_id, attachment_id,
                                                                     urllib.parse.quote(fname, safe="")),
                                  "repo_file": False})
        with self.lock:
            first_look = devin_id not in self.seen
            seen = set(self.seen.get(devin_id, []))
            fresh = [a for a in artefacts if a["key"] not in seen]
            self.seen[devin_id] = sorted(seen | {a["key"] for a in artefacts})
            if fresh or first_look:
                self._save_seen()
        if not first_look:
            for a in fresh:
                self.open_page(a["url"])
        tags = info.get("tags") or []
        if DASHBOARD_TAG in tags and wb.CLOSED_TAG not in tags and any(a["key"].startswith("att:") for a in artefacts):
            try:
                wb.close_session(self.devin, devin_id, tags)
            except wb.ApiError:
                pass
        return {"session_id": devin_id, "title": info.get("title") or "", "url": info.get("url", ""),
                "status": info.get("status_enum") or info.get("status") or "", "messages": messages,
                "artefacts": artefacts, "opened": [a["url"] for a in fresh] if not first_look else []}

    def _store_artefact(self, devin_id, n, art, base):
        name = art["name"].strip()
        if art.get("repo_file"):
            rel = wb.repo_rel(name)
            url = base + "/repo?" + urllib.parse.urlencode({"path": rel}) if rel else ""
            return {"n": n, "name": name, "key": "repo:" + name, "url": url, "repo_file": True}
        folder = os.path.join(ARTEFACT_DIR, safe_name(devin_id))
        os.makedirs(folder, exist_ok=True)
        fname = "%02d-%s" % (n, safe_name(name))
        with open(os.path.join(folder, fname), "w", encoding="utf-8") as fh:
            fh.write(art.get("body") or "")
        return {"n": n, "name": name, "key": "%d:%s" % (n, name),
                "url": "%s/view/%s/%s" % (base, safe_name(devin_id), urllib.parse.quote(fname)), "repo_file": False}

    def attachment(self, devin_id, attachment_id, name):
        """Path of a Devin attachment saved on this PC, downloaded the first time it is opened."""
        folder = os.path.join(ARTEFACT_DIR, safe_name(devin_id))
        path = os.path.join(folder, "att-%s-%s" % (attachment_id, safe_name(name)))
        if not os.path.exists(path):
            data = self.devin.download(attachment_id, name)
            os.makedirs(folder, exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(data)
        return path

    def close(self, devin_id):
        return wb.close_session(self.devin, devin_id, [LOCAL_TAG])


# --------------------------------------------------------------------------- HTTP

IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
               ".webp": "image/webp", ".pdf": "application/pdf"}


def content_for(path, data):
    """(bytes, content type) for a saved artefact or repo file."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".html", ".htm"):
        return data, "text/html; charset=utf-8"
    if ext == ".md":
        return wb.markdown_page(os.path.basename(path), data.decode("utf-8", "replace")), "text/html; charset=utf-8"
    if ext == ".svg":
        return data, "image/svg+xml"
    if ext in IMAGE_TYPES:
        return data, IMAGE_TYPES[ext]
    return data, "text/plain; charset=utf-8"


class Handler(BaseHTTPRequestHandler):
    box = None

    def log_message(self, fmt, *a):
        pass

    def _base(self):
        return "http://%s" % (self.headers.get("Host") or "127.0.0.1:%d" % self.server.server_address[1])

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else (
            json.dumps(body).encode() if ctype == "application/json" else body.encode("utf-8"))
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _file(self, path, ctype=None):
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except OSError:
            return self._send(404, {"error": "not found"})
        if ctype:
            return self._send(200, data, ctype)
        return self._send(200, *content_for(path, data))

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        p, q = url.path, dict(urllib.parse.parse_qsl(url.query))
        try:
            if p == "/":
                with open(PAGE, "rb") as fh:
                    return self._send(200, wb.team.fill_page(fh.read(), wb.PAGE_VALUES), "text/html; charset=utf-8")
            if p == "/api/config":
                person = self.box.person
                return self._send(200, {
                    "devin_ok": wb.HEALTH.report("devin", self.box.devin.key)["connected"],
                    "devin_configured": bool(self.box.devin.key), "jira_configured": bool(os.environ.get(JIRA_ENV)),
                    "jira_ok": bool(os.environ.get(JIRA_ENV)) and wb.HEALTH.report("jira", True)["connected"],
                    "jira_via": "here" if os.environ.get(JIRA_ENV) else "cloud",
                    "dashboard_built": "here" if dashboard_builds_here() else "devin cloud",
                    "user": {"name": person["name"], "jira_user": person["jira_user"], "email": person["email"]}
                    if person else None,
                    "commands": LOCAL_COMMANDS, "workbench": workbench_base(), "devin_app": wb.DEVIN_APP})
            if p == "/api/sessions":
                return self._send(200, {"sessions": self.box.sessions()})
            m = re.match(r"^/api/sessions/([A-Za-z0-9_-]+)$", p)
            if m and SESSION_ID_RE.match(m.group(1)):
                return self._send(200, self.box.session(m.group(1), self._base()))
            if p == "/dashboard":
                return self._file(DASHBOARD_PATH, "text/html; charset=utf-8")
            m = re.match(r"^/attachment/([A-Za-z0-9_-]+)/([^/]+)/([^/]+)$", p)
            if m:
                fname = urllib.parse.unquote(m.group(3))
                if not (SESSION_ID_RE.match(m.group(1)) and UUID_RE.match(m.group(2))) or \
                        fname != os.path.basename(fname) or fname.startswith("."):
                    return self._send(404, {"error": "not found"})
                path = self.box.attachment(m.group(1), m.group(2), fname)
                return self._file(path) if not fname.lower().endswith((".html", ".htm")) else \
                    self._file(path, "text/html; charset=utf-8")
            m = re.match(r"^/view/([A-Za-z0-9_-]+)/([^/]+)$", p)
            if m:
                fname = urllib.parse.unquote(m.group(2))
                if fname != os.path.basename(fname) or fname.startswith("."):
                    return self._send(404, {"error": "not found"})
                return self._file(os.path.join(ARTEFACT_DIR, m.group(1), fname))
            if p == "/repo":
                rel = wb.repo_rel(q.get("path", ""))
                if not rel:
                    return self._send(404, {"error": "not a repository page"})
                try:
                    data, _where = wb.repo_file(rel)
                except OSError:
                    return self._send(404, {"error": "%s is not in this checkout" % rel})
                return self._send(200, *content_for(rel, data))
            return self._send(404, {"error": "not found"})
        except wb.ApiError as exc:
            return self._send(exc.status, {"error": str(exc)})

    def do_POST(self):
        p = urllib.parse.urlparse(self.path).path
        if self.headers.get(CSRF_HEADER) != "1":
            return self._send(403, {"error": "missing %s header" % CSRF_HEADER})
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}") if length else {}
            if p == "/api/command":
                sid = (body.get("session_id") or "").strip()
                if sid and not SESSION_ID_RE.match(sid):
                    return self._send(400, {"error": "bad session id"})
                return self._send(200, self.box.command(body.get("text") or "", sid, self._base()))
            m = re.match(r"^/api/sessions/([A-Za-z0-9_-]+)/close$", p)
            if m and SESSION_ID_RE.match(m.group(1)):
                return self._send(200, {"closed": self.box.close(m.group(1))})
            return self._send(404, {"error": "not found"})
        except wb.ApiError as exc:
            return self._send(exc.status, {"error": str(exc)})
        except (ValueError, subprocess.SubprocessError) as exc:
            return self._send(400, {"error": str(exc)})


def cloud_dashboard(user, lens="", devin=None):
    """Builds a dashboard on this machine and uploads it as a Devin attachment for a Local Devin box."""
    person = wb.find_person(user)
    if not person:
        print("%s is not on %s" % (user, wb.PEOPLE_PATH), file=sys.stderr)
        return 2
    devin = devin or CloudDevin()
    try:
        path = Box(devin, person, open_browser=False).build_dashboard(lens)
        name = "dashboard-%s%s.html" % (safe_name(person["jira_user"]), "-" + safe_name(lens) if lens else "")
        url = devin.upload(path, name)
    except wb.ApiError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print("[SDLC] attachment %s — %s" % (name, url))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", type=int, default=int(os.environ.get("SDLC_LOCAL_PORT", DEFAULT_PORT)))
    ap.add_argument("--user", default=os.environ.get("SDLC_CONSOLE_JIRA_USER", ""),
                    help="you: e-mail, Jira username or Devin user id on .devin/rules/people.yaml")
    ap.add_argument("--no-browser", action="store_true", help="do not open pages in this machine's browser")
    ap.add_argument("--cloud-dashboard", metavar="JIRA_USER",
                    help="run by a Devin Cloud session: build this person's dashboard, upload it and print its link")
    ap.add_argument("--lens", default="", help="with --cloud-dashboard: the role lens to show")
    args = ap.parse_args(argv)
    if args.cloud_dashboard:
        return cloud_dashboard(args.cloud_dashboard, args.lens)
    person = wb.find_person(args.user)
    if args.user and not person:
        print("--user %r is not on %s; sessions are listed by the %s tag only" % (args.user, wb.PEOPLE_PATH, LOCAL_TAG))
    Handler.box = Box(wb.Devin(), person, open_browser=not args.no_browser)
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = "http://127.0.0.1:%d" % args.port
    print("Local Devin on %s%s  (Devin API %s)" % (
        url, " as %s" % person["name"] if person else "", "ok" if Handler.box.devin.key else "NO KEY"))
    if not args.no_browser:
        webbrowser.open(url, new=2)
    srv.serve_forever()


if __name__ == "__main__":
    sys.exit(main())
