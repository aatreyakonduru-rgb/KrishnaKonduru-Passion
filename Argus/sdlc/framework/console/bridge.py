"""Bridge transport: Argus drives Devin through its host Devin Cloud session, with no API key.

When Argus runs inside a person's own Devin Cloud session (started with !argus or /argus), a
program on the VM cannot call Devin's session tools; only the session can. So each Devin call becomes a request
file in <state>/bridge/outbox: a list of built-in tool calls (devin_session_create, devin_session_interact,
devin_session_search, upload_attachment). A small loop in the host session (the /argus skill starts it) runs
them and writes the tool output to <state>/bridge/inbox; this module turns that text back into the same shapes
the Devin API client returns, so the pages, runs and gates do not change. The loop touches <state>/bridge/alive
every second. When it stops because someone typed in the host session, the session restarts it in the same turn, so
for GRACE_SECONDS after the last heartbeat calls wait in the outbox and the page says "reconnecting"; only after that
do they fail, with a message that says how to wake it.

The bridge is the team default. SDLC_DEVIN_TRANSPORT=api picks the Devin API key on the person's PC instead;
start-workbench.cmd and the desktop icon set it.
"""
import json
import os
import re
import threading
import time
import uuid

TOOLS = ("devin_session_create", "devin_session_interact", "devin_session_search", "devin_session_events",
         "upload_attachment")
ALIVE_SECONDS = 15
GRACE_SECONDS = int(os.environ.get("SDLC_BRIDGE_GRACE", "300"))
WAKE_HINT = ("Argus's Devin bridge is not running. Send any message to the Devin session that hosts this "
             "page (titled RESERVED, or type /argus there) and it starts again.")
RECONNECT_HINT = ("Devin Cloud is reconnecting: the host session is answering a message and starts the bridge again "
                  "by itself. Your request waits and goes through when it is back.")
PC_HINT = " On a PC, start Argus with SDLC_DEVIN_TRANSPORT=api to use your Devin API key."
SESSION_ID_RE = re.compile(r"(?:devin-)?([0-9a-f]{32})")
MESSAGE_RE = re.compile(r"^\[(\w+)[^\]]*\] @ (\d+) \((event-[^)]+)\)\s*$")
AFTER_RE = re.compile(r"Pass after=(\S+?)\s+to fetch")
TRUNCATED_RE = re.compile(r"\.\.\. \[truncated\]\s*$")
EVENT_HEAD_RE = re.compile(r"^--- (event-\S+) ---\s*$", re.M)
FULL_BODY_CHARS = 100000
FULL_BODY_KEEP = 500
LATE_KEEP_SECONDS = 900    # a reply that comes after Argus stopped waiting is still picked up this long
STALE_SECONDS = 600        # bridge files nobody waits for are removed once this old
SWEEP_SECONDS = 600


class BridgeError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def transport():
    return "api" if os.environ.get("SDLC_DEVIN_TRANSPORT", "").strip().lower() == "api" else "bridge"


def bare_id(devin_id):
    m = SESSION_ID_RE.search(devin_id or "")
    return m.group(1) if m else (devin_id or "")


def v1_status(status, detail=""):
    """The v3 status of the session tools in the v1 words Argus uses (ENDED, blocked, finished)."""
    status, detail = (status or "").lower(), (detail or "").lower()
    if status in ("exit", "error", "expired", "suspended"):
        return status
    if status == "finished" or "finished" in detail:
        return "finished"
    if "block" in detail or "waiting" in detail:
        return "blocked"
    return "working" if status in ("running", "working", "new", "claimed", "resuming") else status


def parse_details(text):
    """`key: value` lines of devin_session_interact get, as a dict in the Devin API shape."""
    raw = {}
    for line in (text or "").splitlines():
        m = re.match(r"^\s{2}([a-z_]+): (.*)$", line)
        if m:
            raw.setdefault(m.group(1), m.group(2).strip())
    out = dict(raw)
    out["session_id"] = "devin-" + bare_id(raw.get("session_id", ""))
    out["tags"] = [t.strip() for t in raw.get("tags", "").split(",") if t.strip()]
    out["status_enum"] = v1_status(raw.get("status"), raw.get("status_detail"))
    prs = re.findall(r"https?://\S+?(?=[\s,\[]|$)", raw.get("pull_requests", ""))
    if prs:
        out["pull_request"] = {"url": prs[0]}
    return out


def parse_messages(text):
    """Messages of devin_session_interact get_messages in the v1 transcript shape Devin.messages reads."""
    out, cur = [], None
    for line in (text or "").splitlines():
        m = MESSAGE_RE.match(line)
        if m:
            cur = {"type": "user_message" if m.group(1) == "user" else "devin_message", "event_id": m.group(3),
                   "timestamp": int(m.group(2)), "message": ""}
            out.append(cur)
        elif cur is not None:
            cur["message"] += ("\n" if cur["message"] else "") + line
    for m in out:
        m["message"] = m["message"].strip()
    return out


def parse_event_messages(text):
    """{event_id: message} from devin_session_events details: each `--- event-... ---` block's `contents:` JSON."""
    out, parts = {}, EVENT_HEAD_RE.split(text or "")
    for eid, body in zip(parts[1::2], parts[2::2]):
        at = body.find("contents:")
        if at < 0:
            continue
        try:
            msg = json.loads(body[at + len("contents:"):].strip()).get("message")
        except (ValueError, AttributeError):
            continue
        if isinstance(msg, str):
            out[eid] = msg
    return out


def parse_search(text):
    """One dict per `- <id> | title | status=... | key=value` line of devin_session_search."""
    out = []
    for line in (text or "").splitlines():
        if not line.startswith("- "):
            continue
        parts = [p.strip() for p in line[2:].split(" | ")]
        if len(parts) < 2 or not SESSION_ID_RE.fullmatch(parts[0]):
            continue
        row = {"session_id": "devin-" + parts[0], "title": parts[1]}
        for p in parts[2:]:
            if "=" in p:
                k, v = p.split("=", 1)
                row[k] = v
        st = row.get("status", "")
        m = re.match(r"^(\S+)(?: \((.*)\))?$", st)
        row["status_enum"] = v1_status(*(m.groups() if m else (st, "")))
        row["tags"] = [t for t in row.get("tags", "").split(",") if t]
        for k in ("created", "updated"):
            if row.get(k, "").isdigit():
                row[k + "_at"] = int(row[k])
        out.append(row)
    return out


class BridgeDevin:
    """Same calls as server.Devin, through the host session. `key` is a marker so 'is Devin configured' checks pass."""

    key = "bridge"

    def __init__(self, folder, app_base, user_ids=None, timeout=None, clock=time.time, sleep=time.sleep):
        self.dir = folder
        self.app = app_base.rstrip("/")
        self.user_ids = user_ids or (lambda email: [])
        self.timeout = timeout or int(os.environ.get("SDLC_BRIDGE_TIMEOUT", "120"))
        self.clock, self.sleep = clock, sleep
        self.full_bodies = {}
        self.late, self.late_lock, self.swept = {}, threading.Lock(), 0.0
        for sub in ("outbox", "inbox"):
            os.makedirs(os.path.join(folder, sub), exist_ok=True)

    def host_session(self):
        """The host session's devin id, written by the loop to <state>/bridge/host; "" until it has run."""
        try:
            with open(os.path.join(self.dir, "host"), encoding="utf-8") as fh:
                m = SESSION_ID_RE.search(fh.read())
        except OSError:
            return ""
        return "devin-" + m.group(1) if m else ""

    def alive(self):
        try:
            return self.clock() - os.path.getmtime(os.path.join(self.dir, "alive")) < ALIVE_SECONDS
        except OSError:
            return False

    def reconnecting(self):
        """The loop stopped a short while ago in Devin Cloud: it is expected back, so calls wait instead of failing."""
        if self.alive() or not self.host_session():
            return False
        try:
            return self.clock() - os.path.getmtime(os.path.join(self.dir, "alive")) < GRACE_SECONDS
        except OSError:
            return False

    def up(self):
        return self.alive() or self.reconnecting()

    def wake_hint(self):
        """In Devin Cloud (a host session has run) only the host step; a PC that never had one also gets the api switch."""
        return WAKE_HINT if self.host_session() else WAKE_HINT + PC_HINT

    def call(self, *calls):
        """Run the tool calls in the host session; the text each one returned, in order."""
        for tool, _ in calls:
            if tool not in TOOLS:
                raise BridgeError(400, "the bridge does not run %s" % tool)
        if not self.up():
            raise BridgeError(503, self.wake_hint())
        rid = uuid.uuid4().hex
        tmp = os.path.join(self.dir, "outbox", rid + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"id": rid, "calls": [{"tool": t, "args": a} for t, a in calls]}, fh)
        os.replace(tmp, os.path.join(self.dir, "outbox", rid + ".json"))
        reply, end = os.path.join(self.dir, "inbox", rid + ".json"), self.clock() + self.timeout
        while not os.path.exists(reply):
            if self.clock() > end or not self.up():
                waiting = self.reconnecting()
                try:
                    os.remove(os.path.join(self.dir, "outbox", rid + ".json"))
                except OSError:
                    pass
                with self.late_lock:
                    self.late[rid] = (calls, self.clock())
                raise BridgeError(503 if waiting else 504, RECONNECT_HINT if waiting else self.wake_hint())
            self.sleep(0.2)
        try:
            with open(reply, encoding="utf-8") as fh:
                data = json.load(fh)
        except ValueError as exc:
            raise BridgeError(502, "the bridge reply could not be read (%s)" % exc)
        finally:
            try:
                os.remove(reply)
            except OSError:
                pass
        out = []
        for r in data.get("results") or []:
            if r.get("error"):
                m = re.search(r"HTTP (4\d\d)\b", r["error"])
                raise BridgeError(int(m.group(1)) if m else 502, "Devin session tools: %s" % r["error"])
            out.append(r.get("text") or "")
        return out

    def create_session(self, prompt, title, tags):
        text = self.call(("devin_session_create", {"sessions": [{"prompt": prompt, "title": title,
                                                                    "tags": list(tags or [])}]}))[0]
        sid = bare_id(text)
        if not SESSION_ID_RE.fullmatch(sid):
            raise BridgeError(502, "Devin did not return a session id: %s" % text[:200])
        return {"session_id": "devin-" + sid, "url": "%s/sessions/%s" % (self.app, sid), "status_enum": "working"}

    def session(self, devin_id, after=None):
        """The session's details and messages. With `after` (the msg_after of an earlier read) only the messages
        from that page on are read; a cursor the tools no longer take falls back to the whole transcript."""
        sid = "devin-" + bare_id(devin_id)
        info = parse_details(self.call(("devin_session_interact", {"action": "get", "session_id": sid}))[0])
        try:
            info["messages"], info["msg_after"] = self._messages_from(sid, after)
        except Exception:  # noqa: BLE001
            if not after:
                raise
            info["messages"], info["msg_after"] = self._messages_from(sid, None)
        info.setdefault("url", "%s/sessions/%s" % (self.app, bare_id(devin_id)))
        return info

    def _all_messages(self, sid, pages=20):
        return self._messages_from(sid, None, pages)[0]

    def _messages_from(self, sid, after, pages=20):
        """(messages from `after` on, the cursor of the last page read). The next read starts at that cursor, so it
        reads the last page again plus anything new, never the whole transcript."""
        out, start = [], after
        for _ in range(pages):
            args = {"action": "get_messages", "session_id": sid, "first": 100}
            if after:
                args["after"] = after
            start = after
            text = self.call(("devin_session_interact", args))[0]
            out += parse_messages(text)
            m = AFTER_RE.search(text)
            if not m:
                break
            after = start = m.group(1)
        self._full_bodies(sid, out)
        return out, start

    def _full_bodies(self, sid, msgs):
        """get_messages cuts long bodies short (`... [truncated]`), which can drop a question round or a gate at the
        end; those are read in full from the session's events. A host loop that does not run devin_session_events
        yet leaves them short."""
        cut = [m for m in msgs if TRUNCATED_RE.search(m["message"]) and m.get("event_id")]
        want = [m["event_id"] for m in cut if m["event_id"] not in self.full_bodies]
        for i in range(0, len(want), 20):
            try:
                text = self.call(("devin_session_events", {"action": "details", "session_id": sid,
                                                           "event_ids": want[i:i + 20],
                                                           "max_content_length": FULL_BODY_CHARS}))[0]
            except BridgeError:
                break
            self.full_bodies.update(parse_event_messages(text))
        while len(self.full_bodies) > FULL_BODY_KEEP:
            self.full_bodies.pop(next(iter(self.full_bodies)))
        for m in cut:
            full = self.full_bodies.get(m["event_id"])
            if full:
                m["message"] = full.strip()

    def collect_late(self):
        """[(calls, texts)] of calls that timed out here but whose reply came afterwards; also clears bridge
        files nobody waits for any more."""
        out, now = [], self.clock()
        with self.late_lock:
            waiting = list(self.late.items())
        for rid, (calls, at) in waiting:
            path = os.path.join(self.dir, "inbox", rid + ".json")
            if os.path.exists(path):
                try:
                    with open(path, encoding="utf-8") as fh:
                        data = json.load(fh)
                    os.remove(path)
                except (OSError, ValueError):
                    data = None
                with self.late_lock:
                    self.late.pop(rid, None)
                if data and not any(r.get("error") for r in data.get("results") or []):
                    out.append((calls, [r.get("text") or "" for r in data.get("results") or []]))
            elif now - at > LATE_KEEP_SECONDS:
                with self.late_lock:
                    self.late.pop(rid, None)
        if now - self.swept >= SWEEP_SECONDS:
            self.swept = now
            self._sweep(now)
        return out

    def _sweep(self, now):
        with self.late_lock:
            waiting = set(self.late)
        for sub, ends in (("inbox", (".json", ".tmp")), ("outbox", (".tmp",))):
            folder = os.path.join(self.dir, sub)
            try:
                names = os.listdir(folder)
            except OSError:
                continue
            for name in names:
                if not name.endswith(ends) or name.split(".")[0] in waiting:
                    continue
                path = os.path.join(folder, name)
                try:
                    if now - os.path.getmtime(path) > STALE_SECONDS:
                        os.remove(path)
                except OSError:
                    pass

    @staticmethod
    def messages(info):
        return [{"event_id": m.get("event_id"), "created_at": m.get("timestamp"),
                 "source": "devin" if m.get("type") == "devin_message" else "user", "message": m.get("message", "")}
                for m in info.get("messages") or []]

    def send(self, devin_id, text):
        self.call(("devin_session_interact", {"action": "message", "session_id": "devin-" + bare_id(devin_id),
                                              "message": text}))
        return {}

    def list_sessions(self, tag, limit=50):
        return parse_search(self.call(("devin_session_search", {"tags": [tag], "first": min(limit, 100)}))[0])

    def updated_of(self, session_ids):
        """Search rows (with updated_at) of exactly these sessions, 100 to a search."""
        ids = list(dict.fromkeys("devin-" + bare_id(s) for s in session_ids if s))
        rows = []
        for i in range(0, len(ids), 100):
            args = {"session_ids": ids[i:i + 100], "first": 100}
            rows += parse_search(self.call(("devin_session_search", args))[0])
        return rows

    def sessions_of(self, email, limit=100):
        ids = self.user_ids(email)
        if not ids:
            return []
        return parse_search(self.call(("devin_session_search", {"user_ids": ids, "first": min(limit, 100)}))[0])

    def team_sessions(self, people, since):
        """Search rows of the sessions these roster people touched since `since` (unix seconds), one search."""
        ids = sorted({p.get("devin_user_id") for p in people if p.get("devin_user_id")})
        if not ids:
            return []
        args = {"user_ids": ids, "updated_after": int(since), "first": 100}
        return parse_search(self.call(("devin_session_search", args))[0])

    def terminate(self, devin_id):
        self.call(("devin_session_interact", {"action": "terminate", "session_id": "devin-" + bare_id(devin_id)}))
        return {}

    def set_tags(self, devin_id, tags):
        self.call(("devin_session_interact", {"action": "set_tags", "session_id": "devin-" + bare_id(devin_id),
                                              "tags": list(tags)}))
        return {}

    def upload(self, path, name):
        text = self.call(("upload_attachment", {"file_path": os.path.abspath(path)}))[0]
        m = re.search(r"https?://\S+", text)
        if not m:
            raise BridgeError(502, "upload of %s gave no link: %s" % (name, text[:200]))
        return m.group(0).rstrip(").,")

    def download(self, attachment_id, name):
        raise BridgeError(501, "attachments cannot be fetched through the bridge; in Devin Cloud Argus "
                               "reads Jira directly with the team's service account")
