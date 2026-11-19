"""What Argus notices about itself while people use it, and the feedback they send from it.

Two files in Argus's state folder, on this machine only:
  noticed.json   one line per kind of problem, counted, with first and last seen and a suggested fix
  feedback.json  feedback from the form, with the session details Argus already had, until sent

Send makes one SDLC-WORKBENCH-FEEDBACK v1 block of everything not sent yet. A Devin run turns it into one
new file under SHARED/workbench-feedback/ (framework_feedback.py import), and the Leads dashboard reads those.
"""
import datetime
import json
import os
import re
import threading
import time
import uuid

BLOCK = "SDLC-WORKBENCH-FEEDBACK"
KINDS = ("problem", "idea", "worked")
ABOUT = ("Argus page", "Dashboard", "Gate brief", "Skill", "Other")
QUIET_SECONDS = 600  # the same problem again within this time of the last count only moves last seen
SAVE_SECONDS = 30  # how often a repeat that only moves last seen is written to noticed.json
KEEP_DAYS = 30
MAX_LINES = 300

# (where it happened, words in what was seen, short title, what fixes it). First match wins; order matters.
FIXES = [
    ("jira", r"\b(401|403)\b|unauthori[sz]ed|forbidden",
     "Jira refused the key",
     "The Jira token has expired or lost access. On a PC: paste a new token in Settings. In Devin Cloud: rotate "
     "the Jira service-account secret, then restart Argus."),
    ("jira", r"through devin cloud",
     "Jira read through Devin Cloud failed",
     "Jira is read through Devin Cloud here, so this follows a Devin Cloud problem: fix that line first."),
    ("jira", r"timed? ?out|connection|unreachable|urlopen|name or service|remote end|ssl",
     "Jira did not answer",
     "Network or VPN between this machine and Jira. Check the VPN and press Check now. If it lasts more than an "
     "hour for several people, raise it with the platform team."),
    ("jira", r"\b5\d\d\b",
     "Jira had a server error",
     "Jira itself failed. Nothing to fix in Argus; retry later and check the Jira status page."),
    ("devin", r"\b(401|403)\b|unauthori[sz]ed|forbidden|no key",
     "Devin Cloud refused the key",
     "The Devin API key is missing or expired. On a PC: paste a new key in Settings. In Devin Cloud: start "
     "/argus again in the host session."),
    ("devin", r"\b429\b|rate",
     "Devin Cloud said too many calls",
     "Too many calls in a short time. Wait a minute. If it happens daily, slow the refresh timers in console.js."),
    ("devin", r"bridge|heartbeat|host session|outbox",
     "The Devin bridge stopped",
     "The loop in the Devin session that hosts this Argus stopped. Send any message to that session (or type "
     "/argus there) to start it again."),
    ("devin", r"\b5\d\d\b|timed? ?out|connection",
     "Devin Cloud did not answer",
     "Devin Cloud was down or slow for a moment. Retry; if it lasts, check the Devin status page."),
    ("bitbucket", r"auth|credential|401|403",
     "Bitbucket refused the sign-in",
     "Run `git fetch origin` in Argus folder and sign in when Git asks (Git Credential Manager)."),
    ("bitbucket", r"",
     "Bitbucket could not be reached",
     "Network or VPN to Bitbucket. Updates wait until it is back; nothing is lost."),
    ("api", r"pick who you are|who you are first|cannot tell who",
     "A button was pressed before Argus knew who the person is",
     "The person had not picked themselves in the top bar. Make that button pick the person from the roster, "
     "or ask before it is pressed."),
    ("api", r"\b5\d\d\b|traceback|exception|failed:",
     "Argus server failed",
     "An Argus bug: the server failed on that page. Look at the path and error, reproduce it and fix "
     "console/server.py."),
    ("api", r"",
     "Argus said no to a request",
     "The page let the person do something the server then refused. If many people hit it, the page should "
     "explain it or stop it before the click."),
    ("run_error", r"",
     "A Devin run ended in error",
     "Open the session to see why. Start a fresh run with the same input; if the same step fails again, the "
     "skill's steps for it need a fix."),
    ("run_stuck", r"",
     "A Devin run went quiet",
     "Devin had no new message for a long time after Argus last wrote to it. Press Wake once. If that "
     "does not help, open the session: it may be waiting on something Argus does not show."),
    ("run_poll", r"",
     "Argus could not read a session",
     "Usually Devin Cloud was down for a moment. If it keeps happening for one run, the session may be gone: "
     "close the run."),
    ("wake_repeat", r"",
     "Wake pressed again and again",
     "The person kept pressing Wake because nothing moved. Open the session; Argus page should say what "
     "the run is waiting for."),
    ("repeat_action", r"",
     "The same action started again within minutes",
     "The person did not see that the first one had started. The page should show the running action more "
     "clearly."),
    ("screen", r"",
     "The page broke (a script error)",
     "An Argus bug in the page itself. The file and line are in what was seen; fix it in console/static."),
]
NEEDS_A_LOOK = ("Something Argus does not recognise", "Needs a look: read what was seen and add a fix for "
                "it to FIXES in console/observer.py.")


def suggest(where, detail):
    """-> (title, fix) for a problem: the first FIXES line for this place whose words are in what was seen."""
    text = (detail or "").lower()
    for place, words, title, fix in FIXES:
        if place == where and re.search(words, text):
            return title, fix
    return NEEDS_A_LOOK


def signature(where, detail):
    """Problems that differ only in ids, numbers or quoted values count as one."""
    text = (detail or "").lower()
    text = re.sub(r"https?://\S+", "<link>", text)
    text = re.sub(r"\b[0-9a-f]{8,}\b", "#", text)
    text = re.sub(r"\b[a-z]+-\d+\b", "<key>", text)
    text = re.sub(r"\d+", "#", text)
    text = re.sub(r"'[^']*'|\"[^\"]*\"", "<v>", text)
    return "%s|%s" % (where, re.sub(r"\s+", " ", text).strip()[:120])


def _now_iso(t):
    return datetime.datetime.utcfromtimestamp(t).strftime("%Y-%m-%dT%H:%MZ")


class Observer:
    def __init__(self, state_dir):
        self.dir = state_dir
        self.noticed_path = os.path.join(state_dir, "noticed.json")
        self.feedback_path = os.path.join(state_dir, "feedback.json")
        self.lock = threading.Lock()
        self.noticed_at = 0.0
        self.lines = self._read(self.noticed_path, {}).get("lines", {})
        fb = self._read(self.feedback_path, {})
        self.pending = fb.get("pending", [])
        self.last_send = fb.get("last_send", 0)

    @staticmethod
    def _read(path, default):
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return default

    def _write(self, path, data):
        os.makedirs(self.dir, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1)
        os.replace(tmp, path)

    def _save(self):
        self._save_noticed()
        self._write(self.feedback_path, {"pending": self.pending, "last_send": self.last_send})

    def _save_noticed(self, now=None):
        self._write(self.noticed_path, {"lines": self.lines})
        self.noticed_at = now or time.time()

    def note(self, where, detail, page="", now=None):
        """Something went wrong. Never raises: noticing must not break what the person is doing."""
        try:
            now = now or time.time()
            detail = re.sub(r"\s+", " ", str(detail or "")).strip()[:400]
            sig = signature(where, detail)
            with self.lock:
                line = self.lines.get(sig)
                repeat = bool(line and now - line.get("counted", line["first"]) < QUIET_SECONDS)
                if repeat:
                    line["last"] = now
                elif line:
                    line.update(count=line["count"] + 1, last=now, counted=now, detail=detail,
                                page=page or line.get("page", ""))
                else:
                    title, fix = suggest(where, detail)
                    self.lines[sig] = line = {"sig": sig, "where": where, "title": title, "fix": fix,
                                              "detail": detail, "page": page, "count": 1, "sent": 0,
                                              "first": now, "last": now, "counted": now}
                self._prune(now)
                # A repeat within the quiet time only moves "last seen": written at most every SAVE_SECONDS.
                if not repeat or now - self.noticed_at >= SAVE_SECONDS:
                    self._save_noticed(now)
            return line
        except Exception:  # noqa: BLE001
            return None

    def _prune(self, now):
        old = [s for s, ln in self.lines.items() if now - ln["last"] > KEEP_DAYS * 86400 and ln["sent"] >= ln["count"]]
        for s in old:
            self.lines.pop(s)
        if len(self.lines) > MAX_LINES:
            for s in sorted(self.lines, key=lambda s: self.lines[s]["last"])[:len(self.lines) - MAX_LINES]:
                self.lines.pop(s)

    def recent(self, hours=24, now=None):
        now = now or time.time()
        with self.lock:
            rows = [dict(ln) for ln in self.lines.values() if now - ln["last"] <= hours * 3600]
        return sorted(rows, key=lambda r: -r["last"])

    def unsent(self):
        with self.lock:
            return [dict(ln, count=ln["count"] - ln["sent"]) for ln in self.lines.values() if ln["count"] > ln["sent"]]

    def add_feedback(self, by, role, kind, about, text, context, now=None):
        kind = kind if kind in KINDS else "problem"
        text = (text or "").strip()
        if not text:
            raise ValueError("say what happened or what you would like")
        entry = {"id": uuid.uuid4().hex[:8], "at": _now_iso(now or time.time()), "by": by or "", "role": role or "",
                 "kind": kind, "about": about if about in ABOUT else "Other", "text": text[:2000],
                 "context": context or {}}
        with self.lock:
            self.pending.append(entry)
            self._save()
        return entry

    def batch(self, by, role, workbench, now=None):
        """-> (block text, batch id) of all feedback and noticed problems not sent yet, or ("", "")."""
        now = now or time.time()
        noticed = [{"title": r["title"], "where": r["where"], "fix": r["fix"], "detail": r["detail"],
                    "page": r.get("page", ""), "count": r["count"], "first": _now_iso(r["first"]),
                    "last": _now_iso(r["last"]), "sig": r["sig"]} for r in self.unsent()]
        with self.lock:
            feedback = list(self.pending)
        if not noticed and not feedback:
            return "", ""
        batch_id = "%s-%s" % (time.strftime("%Y%m%d-%H%M", time.gmtime(now)), uuid.uuid4().hex[:6])
        body = {"batch": batch_id, "sent": _now_iso(now), "by": by, "role": role, "workbench": workbench or {},
                "feedback": feedback, "noticed": noticed}
        return "%s v1\n%s" % (BLOCK, json.dumps(body, indent=1, sort_keys=True)), batch_id

    def mark_sent(self, block, now=None):
        """The block was handed to a run: its lines and feedback are not sent again."""
        body = json.loads(block.split("\n", 1)[1])
        sent_ids = {f["id"] for f in body["feedback"]}
        with self.lock:
            for n in body["noticed"]:
                line = self.lines.get(n["sig"])
                if line:
                    line["sent"] = min(line["count"], line["sent"] + n["count"])
            self.pending = [f for f in self.pending if f["id"] not in sent_ids]
            self.last_send = now or time.time()
            self._save()

    def daily_due(self, hours, now=None):
        """Noticed problems wait at most `hours` before they go on their own (0: never on their own)."""
        now = now or time.time()
        return bool(hours) and now - self.last_send >= hours * 3600 and bool(self.unsent() or self.pending)
