"""Test on my PC: Argus side of Cloud -> PC -> Cloud testing.

"Test on my PC" makes a folder for the ticket, clones or fetches the repo into it, checks out the
PR branch, finds the story's test pack in the repo, opens the evidence run, tells the Cloud session
the PC has control, and starts Devin Local over ACP (``devin acp``) with /test-on-pc. Argus
shows Devin Local's replies and its permission questions as buttons. "Return to Cloud" checks that
nothing is left unpushed, packs the evidence, sends it to the same Cloud session and hands control
back. Every step runs on this PC with this PC's git, the tester's own Devin login and Devin API key.

The Devin API key is kept in Windows Credential Manager (entered once on the page) or read from
DEVIN_API_KEY. Devin Local gets no API key, so only Argus can send to Cloud. Jira is never
used here. Stdlib only.
"""
import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid

import sdlc_profile as team

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = team.ROOT
TOOLS = os.path.join(team.FRAMEWORK_DIR, "tools")
EVIDENCE = team.FRAMEWORK + "/tools/evidence.py"
PACK_DIR = team.FRAMEWORK + "/context/test-packs"
REPO_PATH = team.REPO_SLUG
REPO_NAME = REPO_PATH.split("/")[-1]
KEY_TARGET = "sdlc-workbench:DEVIN_API_KEY"
NO_KEY_ENV = ("DEVIN_API_KEY", team.JIRA_TOKEN_ENV)
TICKET_RE = re.compile(r"^[A-Z][A-Z0-9]*-[A-Za-z0-9-]{1,40}$")
BRANCH_RE = re.compile(r"^(?!-)(?!.*\.\.)[A-Za-z0-9._/-]{1,200}$")
SESSION_RE = re.compile(r"(?:sessions/)?((?:devin-)?[0-9a-f]{32})")
TRANSCRIPT_MAX = 400
READY_WORDS = "Ready to return to Cloud"


class PcError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def work_root():
    return os.path.expanduser(os.environ.get("SDLC_WORK_ROOT", os.path.join("~", "sdlc", "work")))


def redact_url(url):
    return re.sub(r"//[^/@\s]+@", "//***@", url or "")


def tester_python():
    """How Devin Local should call Python, matching the allow list in .devin/config.json."""
    if os.name == "nt" and shutil.which("py"):
        return "py -3"
    return "python3" if shutil.which("python3") else "python"


def devin_cli():
    return os.environ.get("SDLC_DEVIN_CLI") or shutil.which("devin") or ""


# --------------------------------------------------------------------------- the Devin API key

class _FileTime(ctypes.Structure):
    _fields_ = [("lo", ctypes.c_uint32), ("hi", ctypes.c_uint32)]


class _Credential(ctypes.Structure):
    _fields_ = [("Flags", ctypes.c_uint32), ("Type", ctypes.c_uint32), ("TargetName", ctypes.c_wchar_p),
                ("Comment", ctypes.c_wchar_p), ("LastWritten", _FileTime),
                ("CredentialBlobSize", ctypes.c_uint32), ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
                ("Persist", ctypes.c_uint32), ("AttributeCount", ctypes.c_uint32),
                ("Attributes", ctypes.c_void_p), ("TargetAlias", ctypes.c_wchar_p),
                ("UserName", ctypes.c_wchar_p)]


CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2


def key_store():
    """Name of the secure store this PC has, or "" when only the environment variable works."""
    return "Windows Credential Manager" if os.name == "nt" else ""


def load_key():
    """The Devin API key: DEVIN_API_KEY wins, then Windows Credential Manager. Never logged."""
    if os.environ.get("DEVIN_API_KEY"):
        return os.environ["DEVIN_API_KEY"]
    if os.name != "nt":
        return ""
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    found = ctypes.POINTER(_Credential)()
    if not advapi.CredReadW(KEY_TARGET, CRED_TYPE_GENERIC, 0, ctypes.byref(found)):
        return ""
    try:
        cred = found.contents
        return ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize).decode("utf-16-le")
    finally:
        advapi.CredFree(found)


def save_key(value):
    if os.name != "nt":
        raise PcError(400, "this PC has no secure store Argus can use; set DEVIN_API_KEY "
                           "before starting Argus instead")
    blob = value.encode("utf-16-le")
    buf = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
    cred = _Credential(Type=CRED_TYPE_GENERIC, TargetName=KEY_TARGET, CredentialBlobSize=len(blob),
                       CredentialBlob=ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)),
                       Persist=CRED_PERSIST_LOCAL_MACHINE, UserName="DEVIN_API_KEY",
                       Comment="Devin API key for the SDLC Argus")
    if not ctypes.WinDLL("advapi32", use_last_error=True).CredWriteW(ctypes.byref(cred), 0):
        raise PcError(500, "Windows Credential Manager refused the key (error %d)" % ctypes.get_last_error())


# --------------------------------------------------------------------------- git and the helper

def run(cmd, cwd, env=None, timeout=600):
    try:
        done = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, errors="replace",
                              timeout=timeout)
    except FileNotFoundError:
        raise PcError(500, "%s is not installed on this PC" % cmd[0])
    except subprocess.TimeoutExpired:
        raise PcError(504, "%s timed out after %d s" % (" ".join(cmd[:3]), timeout))
    return done.returncode, (done.stdout + done.stderr).strip()


def git(cwd, *args, check=True, timeout=600):
    code, out = run(["git"] + list(args), cwd, timeout=timeout)
    if check and code:
        raise PcError(502, "git %s failed: %s" % (args[0], redact_url(out)[-600:]))
    return out if not code else ("" if check else out)


def origin_url():
    """Where to clone from: SDLC_REPO_URL, else the origin of the checkout Argus runs from,
    so the PC uses the same URL form (with or without /scm/) that already works on it."""
    url = os.environ.get("SDLC_REPO_URL", "").strip()
    if not url:
        code, out = run(["git", "remote", "get-url", "origin"], ROOT)
        url = out.strip() if not code else ""
    if not url:
        raise PcError(500, "set SDLC_REPO_URL to the Bitbucket clone URL of %s" % REPO_PATH)
    return url


def sibling_url(url, project, repo):
    """Clone URL of another Bitbucket repo, in the same form as ``url``."""
    if REPO_PATH.lower() not in url.lower():
        raise PcError(500, "cannot work out the clone URL of %s/%s from %s" % (project, repo, redact_url(url)))
    i = url.lower().index(REPO_PATH.lower())
    return url[:i] + "%s/%s" % (project, repo) + url[i + len(REPO_PATH):]


def evidence_module():
    sys.path.insert(0, TOOLS)
    try:
        import evidence
    finally:
        sys.path.remove(TOOLS)
    return evidence


def load_pack(path):
    evidence = evidence_module()
    try:
        return evidence.load_pack(path)
    except Exception as exc:
        raise PcError(400, "cannot read the test pack %s: %s" % (os.path.basename(path), exc))


def find_pack(repo_dir, ticket, branch, wanted=""):
    """The test pack for this ticket on this branch, as a repo-relative path."""
    folder = os.path.join(repo_dir, *PACK_DIR.split("/"))
    names = sorted(n for n in os.listdir(folder) if n.endswith((".yaml", ".yml", ".json"))) \
        if os.path.isdir(folder) else []
    if wanted:
        if wanted not in names:
            raise PcError(404, "%s is not in %s on %s" % (wanted, PACK_DIR, branch))
        return PACK_DIR + "/" + wanted
    # Packs merged from older branches ride along on new ones; only this branch's own count.
    matches = [n for n in names if load_pack(os.path.join(folder, n)).get("branch") == branch]
    if len(matches) == 1:
        return PACK_DIR + "/" + matches[0]
    if not matches:
        raise PcError(404, "branch %s has no test pack of its own in %s yet. Ask the Cloud session to run "
                           "/eval, which writes and commits it" % (branch, PACK_DIR))
    raise PcError(409, "pick the test pack: %s" % ", ".join(matches))


def ticket_in(ticket, name):
    return re.search(r"(?<![A-Z0-9])%s(?![0-9])" % re.escape(ticket), name.upper()) is not None


EVIDENCE_LINE = re.compile(r"\[SDLC\] evidence (\S+) (\S+) ([0-9a-f]{7,40}) passed=(\d+) failed=(\d+) not_run=(\d+)")
TESTED_LINE = re.compile(r"Tested on (\S+) by (\S+), (\S+?)\.(?:\s|$)")
ZIP_LINK = re.compile(r"https://\S+\.zip")
JIRA_TICKET = re.compile(r"^%s$" % team.TICKET)
JIRA_ASK = re.compile(r"\[SDLC\] post-to-jira (\S+) (%s)" % team.TICKET)
JIRA_DONE = re.compile(r"\[SDLC\] jira-comment (\S+) (https://\S+)")


def evidence_history(messages):
    """Every evidence message a PC sent to a Cloud session, newest first: counts, who, which PC, when,
    which commit and the zip. Devin quoting the line back does not count; only what was sent in. A run
    sent twice (a retry after the upload failed) is one row, the copy with the zip kept. ``jira`` says
    whether Post to Jira was asked for (``ticket``) and the comment link Devin replied with (``url``)."""
    out, seen, runs, asked, done = [], set(), {}, {}, {}
    for m in messages or []:
        text = m.get("message") or ""
        a = JIRA_ASK.search(text) if m.get("source") != "devin" else None
        d = JIRA_DONE.search(text) if m.get("source") == "devin" else None
        if a:
            asked[a.group(1)] = a.group(2)
        if d:
            done[d.group(1)] = d.group(2)
        e = EVIDENCE_LINE.search(text)
        if m.get("source") == "devin" or not e or m.get("event_id") in seen:
            continue
        seen.add(m.get("event_id"))
        t, z = TESTED_LINE.search(text), ZIP_LINK.search(text)
        same = (e.groups(), t.group(0)) if t else None
        if same in runs:
            if z and not runs[same]["zip"]:
                runs[same]["zip"] = z.group(0)
            continue
        out.append({"event_id": m.get("event_id"), "sent_at": m.get("created_at") or "",
                    "req": e.group(1), "story": e.group(2), "commit": e.group(3)[:12],
                    "passed": int(e.group(4)), "failed": int(e.group(5)), "not_run": int(e.group(6)),
                    "machine": t.group(1) if t else "", "tested_by": t.group(2) if t else "",
                    "tested_at": t.group(3) if t else "", "zip": z.group(0) if z else ""})
        if same:
            runs[same] = out[-1]
    for r in out:
        r["jira"] = {"ticket": asked.get(r["event_id"], ""), "url": done.get(r["event_id"], "")}
    return sorted(out, key=lambda r: r["tested_at"] or r["sent_at"], reverse=True)


def jira_comment_request(run, ticket, jira_host):
    """The message that asks the Cloud session to put one run's results on the Jira ticket. It must not
    contain the evidence line, or the history would count it as another run."""
    eid = run["event_id"]
    text = ("Test on my PC results for %s %s: %d passed, %d failed, %d not run.\n"
            "Tested on %s by %s at %s, commit %s.\n" % (
                run["req"], run["story"], run["passed"], run["failed"], run["not_run"], run["machine"] or "?",
                run["tested_by"] or "?", run["tested_at"] or run["sent_at"], run["commit"]))
    if run["zip"]:
        text += "Evidence: %s\n" % run["zip"]
    return ("[SDLC] post-to-jira %s %s\n"
            "The tester clicked Post to Jira in Argus. That click approves exactly one comment on %s and "
            "nothing else. Add the text between the --- lines as one comment on %s with the Jira service account: "
            f"POST %s/rest/api/2/issue/%s/comment, bearer {team.JIRA_TOKEN_ENV}, body {{\"body\": <text>}}. "
            "Don't change anything else in Jira, and don't retry if it fails. When it's added, reply with this one "
            "line, using the new comment's id: [SDLC] jira-comment %s %s/browse/%s?focusedCommentId=<id>\n"
            "If it fails, reply with the error instead.\n---\n%s---" % (
                eid, ticket, ticket, ticket, jira_host, ticket, eid, jira_host, ticket, text))



WRAP_ASK = re.compile(r"\[SDLC\] wrap-up-check (%s)" % team.TICKET)
WRAP_DONE = re.compile(r"\[SDLC\] wrap-up (%s) (ready|not-ready)[ \t]*([^\n]*)" % team.TICKET)
JIRA_NEXT = re.compile(r"\[SDLC\] jira-next (%s) ([^\n]*)" % team.TICKET)
MOVE_ASK = re.compile(r"\[SDLC\] jira-move (%s) (\d+)" % team.TICKET)
MOVE_DONE = re.compile(r"\[SDLC\] jira-moved (%s) ([^\n]+)" % team.TICKET)
TRANSITION = re.compile(r"^(\d+)=(.+)$")


def wrapup_state(messages, ticket):
    """Where a ticket's wrap-up stands, read from the Cloud session: whether Argus asked Cloud to
    check that everything is in place, Cloud's verdict, the Jira transitions it can offer, and any move the
    tester asked for. Only the newest check counts; asking again starts over."""
    st = {"asked": False, "verdict": "", "reason": "", "transitions": [], "move": {}}
    for m in messages or []:
        text, devin = m.get("message") or "", m.get("source") == "devin"
        a = WRAP_ASK.search(text) if not devin else None
        if a and a.group(1) == ticket:
            st = {"asked": True, "verdict": "", "reason": "", "transitions": [], "move": {}}
            continue
        if not devin:
            mv = MOVE_ASK.search(text)
            if mv and mv.group(1) == ticket and st["verdict"] == "ready":
                name = next((t["name"] for t in st["transitions"] if t["id"] == mv.group(2)), "")
                st["move"] = {"id": mv.group(2), "name": name, "status": ""}
            continue
        for d in WRAP_DONE.finditer(text):
            if d.group(1) == ticket and st["asked"]:
                st["verdict"], st["reason"] = d.group(2), d.group(3).strip()
        for n in JIRA_NEXT.finditer(text):
            if n.group(1) == ticket and st["asked"]:
                st["transitions"] = [{"id": t.group(1), "name": t.group(2).strip()}
                                     for t in (TRANSITION.match(x.strip()) for x in n.group(2).split("|")) if t]
        for d in MOVE_DONE.finditer(text):
            if d.group(1) == ticket and st["move"]:
                st["move"]["status"] = d.group(2).strip()
    return st


def wrapup_request(ticket, jira_host):
    """Asks the ticket's Cloud session, after the PC handed back, whether anything is left to do."""
    return ("[SDLC] wrap-up-check %s\n"
            "The tester is back from Test on my PC. Check that the work on %s is complete before anyone moves it on:\n"
            "1. The newest evidence message in this session has failed=0, and every not-run item has a reason.\n"
            "2. The story's pull request exists, and nothing pushed since the tested commit is untested.\n"
            "3. No open question, unsigned gate or other step in this session is still waiting for this story.\n"
            "4. Read the ticket's Jira transitions with the Jira service account, read only: GET %s/rest/api/2/issue/%s"
            f"/transitions, bearer {team.JIRA_TOKEN_ENV}.\n"
            "Then reply with these two lines and nothing else on them:\n"
            "[SDLC] wrap-up %s ready <one short sentence>   or   [SDLC] wrap-up %s not-ready <what is left>\n"
            "[SDLC] jira-next %s <id>=<transition name>|<id>=<transition name>...\n"
            "Don't change Jira, the pull request, the repository or Confluence. The tester picks the next Jira "
            "status and what happens to this session in Argus." % (
                ticket, ticket, jira_host, ticket, ticket, ticket, ticket))


def jira_move_request(ticket, transition, jira_host):
    """The one Jira transition the tester picked in the wrap-up box."""
    return ("[SDLC] jira-move %s %s\n"
            "The tester picked \"%s\" for %s in Argus wrap-up. That click approves exactly this one Jira "
            "transition and nothing else. Do it with the Jira service account: POST %s/rest/api/2/issue/%s/transitions, "
            f"bearer {team.JIRA_TOKEN_ENV}, body {{\"transition\": {{\"id\": \"%s\"}}}}. Don't retry if it fails and don't "
            "change any field. When it's done, read the ticket's status and reply with this one line:\n"
            "[SDLC] jira-moved %s <new status>\n"
            "If it fails, reply with the error instead." % (
                ticket, transition["id"], transition["name"], ticket, jira_host, ticket, transition["id"], ticket))

def lookup(ticket, sessions=None, max_branches=40):
    """Everything Test on my PC needs, from the ticket alone: the Bitbucket branches named after it,
    the test packs on each, and the Cloud session a pack names. ``sessions(ticket)`` is the fallback
    for the session: [{"url", "title"}] from Devin Cloud. Reads only; uses a small cache repo."""
    ticket = (ticket or "").strip().upper()
    if not TICKET_RE.match(ticket):
        raise PcError(400, "the ticket must look like %s-1234 or REQ-001-STORY-1" % team.PROJECT)
    url = origin_url()
    cache = os.path.join(work_root(), ".lookup.git")
    if not os.path.isdir(cache):
        os.makedirs(cache, exist_ok=True)
        git(cache, "init", "--bare", "-q")
    if git(cache, "remote", "get-url", "origin", check=False).strip() != url:
        git(cache, "remote", "remove", "origin", check=False)
        git(cache, "remote", "add", "origin", url)
        git(cache, "config", "remote.origin.promisor", "true")
        git(cache, "config", "remote.origin.partialclonefilter", "blob:none")
    heads = []
    for line in git(cache, "ls-remote", "--heads", "origin", timeout=120).splitlines():
        sha, _, ref = line.partition("\t")
        name = ref.strip()[len("refs/heads/"):]
        if name and ticket_in(ticket, name) and BRANCH_RE.match(name):
            heads.append((name, sha.strip()))
    heads = sorted(heads)[:max_branches]
    if heads:
        # One shallow fetch for every branch, trees only: blobs (the packs) come on demand.
        git(cache, "fetch", "-q", "--depth", "1", "--filter=blob:none", "origin",
            *["+refs/heads/%s:refs/lookup/%s" % (n, n) for n, _ in heads], timeout=900)
    branches = []
    for name, sha in heads:
        ref = "refs/lookup/" + name
        packs = []
        for path in git(cache, "ls-tree", "--name-only", ref, PACK_DIR + "/").splitlines():
            fname = path.rsplit("/", 1)[-1]
            if not fname.endswith((".yaml", ".yml", ".json")):
                continue
            tmp = os.path.join(cache, "pack-" + uuid.uuid4().hex[:8] + os.path.splitext(fname)[1])
            try:
                with open(tmp, "w", encoding="utf-8") as fh:
                    fh.write(git(cache, "show", "%s:%s" % (ref, path)))
                data = load_pack(tmp)
            except PcError:
                continue
            finally:
                if os.path.exists(tmp):
                    os.remove(tmp)
            if data.get("branch") == name:
                packs.append({"name": fname, "session": data.get("cloud_session") or "",
                              "story": "%s %s" % (data.get("req_id", ""), data.get("story_id", "")),
                              "commit": str(data.get("commit", ""))[:12]})
        branches.append({"branch": name, "head": sha[:12], "packs": packs})
    with_pack = [b for b in branches if b["packs"]]
    choices = with_pack or branches
    pick = {"branch": "", "session": "", "pack": "", "session_from": ""}
    if len(choices) == 1:
        b = choices[0]
        pick["branch"] = b["branch"]
        if len(b["packs"]) == 1:
            pick["session"], pick["session_from"] = b["packs"][0]["session"], "test pack"
    found = []
    if sessions is not None:
        try:
            found = sessions(ticket) or []
        except Exception:
            found = []
    if pick["branch"] and not pick["session"] and len(found) == 1:
        pick["session"], pick["session_from"] = found[0].get("url", ""), "Devin Cloud"
    return {"ticket": ticket, "branches": branches, "sessions": found, "pick": pick}


# --------------------------------------------------------------------------- Devin Local over ACP

class AcpAgent:
    """One ``devin acp`` process and session. Messages are JSON-RPC 2.0, one per line."""

    def __init__(self, cwd, command=None, env=None):
        self.cwd, self.command, self.env = cwd, command, env
        self.proc = None
        self.session_id = ""
        self.lock = threading.Lock()
        self.next_id = 0
        self.waiting = {}
        self.transcript = []
        self.permissions = {}
        self.busy = False
        self.prompt_id = None
        self.stop_reason = ""
        self.error = ""

    def start(self, timeout=120):
        cmd = self.command or [devin_cli(), "acp"]
        if not cmd[0]:
            raise PcError(500, "the Devin CLI is not installed on this PC. Install it once "
                               "(https://docs.devin.ai/cli), run `devin auth login`, then try again")
        try:
            self.proc = subprocess.Popen(cmd, cwd=self.cwd, env=self.env, stdin=subprocess.PIPE,
                                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                         encoding="utf-8", errors="replace", bufsize=1)
        except OSError as exc:
            raise PcError(500, "could not start Devin Local: %s" % exc)
        threading.Thread(target=self._read, daemon=True).start()
        self.request("initialize", {"protocolVersion": 1, "clientCapabilities": {},
                                    "clientInfo": {"name": "sdlc-workbench", "version": "1"}}, timeout)
        self.session_id = self.request("session/new", {"cwd": self.cwd, "mcpServers": []}, timeout)["sessionId"]
        return self.session_id

    def _write(self, msg):
        if not self.alive():
            raise PcError(409, "Devin Local has stopped")
        with self.lock:
            self.proc.stdin.write(json.dumps(msg) + "\n")
            self.proc.stdin.flush()

    def _send(self, method, params):
        with self.lock:
            self.next_id += 1
            rid = self.next_id
            self.waiting[rid] = {"event": threading.Event(), "reply": None}
        self._write({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        return rid

    def request(self, method, params, timeout=120):
        rid = self._send(method, params)
        slot = self.waiting[rid]
        if not slot["event"].wait(timeout):
            raise PcError(504, "Devin Local did not answer %s within %d s" % (method, timeout))
        reply = slot["reply"]
        if "error" in reply:
            raise PcError(502, "Devin Local: %s" % (reply["error"].get("message") or reply["error"]))
        return reply.get("result") or {}

    def prompt(self, text, who="you"):
        if self.busy:
            raise PcError(409, "Devin Local is still working; wait for it to finish or press Stop")
        self.busy, self.stop_reason = True, ""
        self._note({"role": who, "text": text})
        self.prompt_id = self._send("session/prompt", {"sessionId": self.session_id,
                                                       "prompt": [{"type": "text", "text": text}]})

    def answer(self, request_id, option_id):
        perm = self.permissions.get(str(request_id))
        if not perm:
            raise PcError(404, "that question has already been answered")
        if option_id not in [o["optionId"] for o in perm["options"]]:
            raise PcError(400, "not one of the offered answers")
        outcome = {"outcome": "selected", "optionId": option_id} if option_id else {"outcome": "cancelled"}
        self._write({"jsonrpc": "2.0", "id": perm["rpc_id"], "result": {"outcome": outcome}})
        del self.permissions[str(request_id)]
        name = next(o["name"] for o in perm["options"] if o["optionId"] == option_id)
        self._note({"role": "answer", "text": "%s: %s" % (perm["title"], name)})

    def cancel(self):
        if self.alive() and self.session_id:
            self._write({"jsonrpc": "2.0", "method": "session/cancel", "params": {"sessionId": self.session_id}})

    def stop(self):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.stdin.close()
            except OSError:
                pass
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self.proc and self.proc.stdout:
            try:
                self.proc.stdout.close()
            except (OSError, ValueError):
                pass
        self.busy = False

    def alive(self):
        return bool(self.proc) and self.proc.poll() is None

    def ready(self):
        """True once Devin Local has finished a turn that says the run is ready to return."""
        last = next((t for t in reversed(self.transcript) if t["role"] == "devin"), None)
        return not self.busy and bool(last) and READY_WORDS.lower() in last["text"].lower()

    def _note(self, entry):
        entry.setdefault("at", time.time())
        self.transcript.append(entry)
        del self.transcript[:-TRANSCRIPT_MAX]

    def _read(self):
        for line in self.proc.stdout:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            try:
                self._handle(msg)
            except Exception as exc:  # one bad message must not stop the reader
                self.error = "could not read a message from Devin Local: %s" % exc
        self.busy = False
        if not self.error:
            self.error = "Devin Local has stopped"

    def _handle(self, msg):
        method = msg.get("method")
        if method is None and "id" in msg:
            if msg["id"] == self.prompt_id:
                self.busy = False
                if "error" in msg:
                    self.error = str(msg["error"].get("message") or msg["error"])
                    self._note({"role": "error", "text": self.error})
                else:
                    self.stop_reason = (msg.get("result") or {}).get("stopReason", "")
            slot = self.waiting.get(msg["id"])
            if slot:
                slot["reply"] = msg
                slot["event"].set()
            return
        params = msg.get("params") or {}
        if method == "session/request_permission":
            call = params.get("toolCall") or {}
            key = uuid.uuid4().hex[:12]
            self.permissions[key] = {
                "id": key, "rpc_id": msg.get("id"), "title": call.get("title") or "Devin Local asks to go ahead",
                "kind": call.get("kind") or "",
                "options": [{"optionId": o.get("optionId"), "name": o.get("name") or o.get("optionId"),
                             "kind": o.get("kind") or ""} for o in params.get("options") or []],
            }
            self._note({"role": "ask", "text": self.permissions[key]["title"], "permission": key})
            return
        if method == "session/update":
            update = params.get("update") or {}
            kind = update.get("sessionUpdate")
            if kind == "agent_message_chunk":
                text = (update.get("content") or {}).get("text") or ""
                last = self.transcript[-1] if self.transcript else None
                if last and last["role"] == "devin":
                    last["text"] += text
                else:
                    self._note({"role": "devin", "text": text})
            elif kind == "tool_call":
                self._note({"role": "tool", "id": update.get("toolCallId"), "text": update.get("title") or "",
                            "status": update.get("status") or "pending"})
            elif kind == "tool_call_update":
                for t in reversed(self.transcript):
                    if t["role"] == "tool" and t.get("id") == update.get("toolCallId"):
                        t["status"] = update.get("status") or t["status"]
                        t["text"] = update.get("title") or t["text"]
                        break
            return
        if "id" in msg:
            self._write({"jsonrpc": "2.0", "id": msg["id"],
                         "error": {"code": -32601, "message": "Argus does not offer %s" % method}})

    def snapshot(self):
        return {"alive": self.alive(), "busy": self.busy, "session_id": self.session_id,
                "stop_reason": self.stop_reason, "error": self.error, "ready": self.ready(),
                "transcript": list(self.transcript),
                "permissions": [{k: v for k, v in p.items() if k != "rpc_id"} for p in self.permissions.values()]}


# --------------------------------------------------------------------------- one PC test

PHASES = [("code", "Get the code"), ("control", "PC has control"), ("checks", "Automatic checks"),
          ("answers", "Your answers"), ("return", "Return to Cloud"), ("back", "Back with Cloud")]
PREP_PHASE = {"Tell Cloud the PC has control": "control", "Start Devin Local with /test-on-pc": "control"}
RETURN_STEPS = ("Check nothing is left unpushed", "Seal the evidence", "Send the evidence to Cloud",
                "Hand control back to Cloud")


def read_results(path):
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh).get("results") or {}
    except (OSError, ValueError):
        return {}


def has_result(r):
    return bool(r) and (r.get("status") != "not run" or r.get("note") != "not attempted")


def progress(t, results):
    """Where a PC test is, for the step strip: phase, counts and one line on what is happening now."""
    a = t.get("agent") or {}
    checks, acs = t.get("check_ids") or [], t.get("ac_ids") or []
    done_checks = sum(1 for i in checks if has_result(results.get(i)))
    done_acs = sum(1 for i in acs if has_result(results.get(i)))
    steps = t.get("steps") or []
    last = steps[-1] if steps else None
    state = t.get("state")
    if state == "returned":
        phase = "back"
    elif state == "returning" or (last and last["name"] in RETURN_STEPS):
        phase = "return"
    elif state == "preparing" or (state == "failed" and t.get("control") != "pc"):
        phase = PREP_PHASE.get(last["name"], "code") if last else "code"
    elif done_checks < len(checks):
        phase = "checks"
    elif done_acs < len(acs) or not a.get("ready"):
        phase = "answers"
    else:
        phase = "return"

    if state == "failed":
        now = "Stopped: " + (t.get("error") or "see the steps below").splitlines()[0]
    elif state in ("preparing", "returning"):
        now = (last["name"] if last else "Starting") + "…"
    elif state == "returned":
        now = "Back with Cloud. The evidence is in the Cloud session."
    elif a.get("permissions"):
        now = "Waiting for you: Devin Local asks to run a command. Answer in the orange box."
    elif a.get("busy"):
        tool = next((m for m in reversed(a.get("transcript") or []) if m.get("role") == "tool"), None)
        what = "running the automatic checks" if phase == "checks" else "working"
        doing = " (%s)" % tool["text"] if tool and tool.get("status") != "completed" else ""
        now = "Devin Local is %s%s." % (what, doing)
    elif a.get("ready"):
        now = "Ready. Press Return to Cloud."
    else:
        now = "Waiting for you: answer Devin Local in the box below."
    return {"phase": phase, "phases": [{"key": k, "label": label} for k, label in PHASES],
            "checks": {"done": done_checks, "total": len(checks)},
            "answers": {"done": done_acs, "total": len(acs)},
            "now": now, "failed": state == "failed"}


def first_prompt(t):
    py = tester_python()
    return "\n".join([
        "/test-on-pc %s" % t["pack"],
        "",
        "The SDLC Argus started you and has already done STEP 0 to STEP 2:",
        "- this checkout is on %s at %s, with no local changes;" % (t["branch"], t["head"][:12]),
        "- `evidence.py start` opened the run;",
        "- `[SDLC] control pc` went to the Cloud session %s." % t["session"],
        "Start at STEP 3 and do STEP 3 to STEP 6 only. Run the helper as `%s %s`." % (py, EVIDENCE),
        "Do not run `pack`, `send` or `control`, do not commit or push, and do not sign anything. "
        "The tester presses Return to Cloud in Argus, which packs, sends and hands control back.",
        "Ask the tester one acceptance item at a time and wait for their answer.",
        "When every check and acceptance item has a result, run `%s %s status %s` and end your reply "
        "with the words \"%s\"." % (py, EVIDENCE, t["pack"], READY_WORDS),
    ])


class PcTests:
    """Every Test on my PC run Argus has started since it came up."""

    def __init__(self, key_source=load_key, agent_factory=AcpAgent, threaded=True):
        self.key_source, self.agent_factory, self.threaded = key_source, agent_factory, threaded
        self.tests = {}
        self.agents = {}
        self.lock = threading.Lock()

    # ---- helpers
    def _step(self, t, name, fn):
        step = {"name": name, "status": "running", "detail": "", "at": time.time()}
        with self.lock:
            t["steps"].append(step)
        try:
            detail = fn()
        except PcError as exc:
            step.update(status="failed", detail=str(exc))
            raise
        except Exception as exc:
            step.update(status="failed", detail="%s: %s" % (type(exc).__name__, exc))
            raise PcError(500, step["detail"])
        step.update(status="done", detail=detail or "")
        return detail

    def _evidence(self, t, *args):
        env = dict(os.environ)
        key = self.key_source()
        if key:
            env["DEVIN_API_KEY"] = key
        code, out = run([sys.executable, os.path.join(t["folder"], *EVIDENCE.split("/"))] + list(args),
                        t["folder"], env=env, timeout=900)
        if code:
            raise PcError(502, out[-800:] or "evidence.py %s failed (exit %d)" % (args[0], code))
        return out[-800:]

    def _agent_env(self):
        env = {k: v for k, v in os.environ.items() if k not in NO_KEY_ENV}
        env["PYTHONIOENCODING"] = "utf-8"
        return env

    def _go(self, fn, t):
        def body():
            try:
                fn(t)
            except PcError as exc:
                with self.lock:
                    t["state"], t["error"] = "failed", str(exc)
        if self.threaded:
            threading.Thread(target=body, daemon=True).start()
        else:
            body()

    # ---- public
    def start(self, ticket, branch, session, pack=""):
        ticket = (ticket or "").strip().upper()
        branch = (branch or "").strip()
        m = SESSION_RE.search(session or "")
        if not TICKET_RE.match(ticket):
            raise PcError(400, "the ticket must look like %s-1234 or REQ-001-STORY-1" % team.PROJECT)
        if not BRANCH_RE.match(branch):
            raise PcError(400, "that is not a branch name")
        if not m:
            raise PcError(400, "paste the Cloud session link, so evidence goes back to the right session")
        if pack and not re.match(r"^[A-Za-z0-9._-]+\.(ya?ml|json)$", pack):
            raise PcError(400, "the test pack must be a file name in %s" % PACK_DIR)
        if not self.key_source():
            raise PcError(400, "add your Devin API key first (Settings on the welcome page)")
        with self.lock:
            for other in self.tests.values():
                if other["ticket"] == ticket and other["state"] in ("preparing", "testing", "returning"):
                    raise PcError(409, "%s is already being tested on this PC" % ticket)
            t = {"id": uuid.uuid4().hex[:12], "ticket": ticket, "branch": branch,
                 "session": m.group(1) if m.group(1).startswith("devin-") else "devin-" + m.group(1),
                 "folder": os.path.join(work_root(), ticket, REPO_NAME), "pack": pack, "head": "",
                 "state": "preparing", "error": "", "steps": [], "started_at": time.time(), "result": ""}
            self.tests[t["id"]] = t
        self._go(self._prepare, t)
        return self.public(t["id"])

    def _prepare(self, t):
        folder = t["folder"]

        def get_code():
            if not os.path.isdir(os.path.join(folder, ".git")):
                os.makedirs(os.path.dirname(folder), exist_ok=True)
                git(os.path.dirname(folder), "clone", "--no-checkout", origin_url(), folder, timeout=1800)
                return "cloned into %s" % folder
            if git(folder, "status", "--porcelain", "--untracked-files=no"):
                raise PcError(409, "%s has uncommitted changes. Commit and push them, or discard them, "
                                   "then try again" % folder)
            return "using %s" % folder

        def checkout():
            b = t["branch"]
            git(folder, "fetch", "origin", "+refs/heads/%s:refs/remotes/origin/%s" % (b, b), timeout=900)
            if git(folder, "rev-parse", "--verify", "--quiet", "refs/heads/" + b, check=False):
                ahead = git(folder, "rev-list", "--count", "origin/%s..%s" % (b, b))
                if ahead.strip() not in ("", "0"):
                    raise PcError(409, "the local %s has %s commit(s) that are not on Bitbucket. Push them "
                                       "first" % (b, ahead.strip()))
            git(folder, "checkout", "-B", b, "origin/" + b)
            t["head"] = git(folder, "rev-parse", "HEAD")
            return "%s at %s" % (b, t["head"][:12])

        def pack():
            t["pack"] = find_pack(folder, t["ticket"], t["branch"], t["pack"])
            data = load_pack(os.path.join(folder, *t["pack"].split("/")))
            if data.get("branch") and data["branch"] != t["branch"]:
                raise PcError(409, "%s is for branch %s, not %s" % (t["pack"], data["branch"], t["branch"]))
            t["req_story"] = "%s %s" % (data.get("req_id", ""), data.get("story_id", ""))
            t["check_ids"] = [c["id"] for c in data.get("checks") or []]
            t["ac_ids"] = [c["id"] for c in data.get("acceptance") or []]
            t["run_file"] = evidence_module().run_file(data)
            t["extra_repos"] = (data.get("setup") or {}).get("repos") or []
            return t["pack"]

        def other_repos():
            done = []
            for r in t["extra_repos"]:
                name = r.get("name") or r.get("repo")
                if not re.match(r"^[A-Za-z0-9_.-]+$", name or "") or not re.match(
                        r"^[A-Za-z0-9_-]+$", r.get("project") or ""):
                    raise PcError(400, "setup.repos needs a project and a repo name for each entry")
                there = os.path.join(os.path.dirname(folder), name)
                if not os.path.isdir(os.path.join(there, ".git")):
                    url = sibling_url(origin_url(), r["project"], r.get("repo") or name)
                    git(os.path.dirname(folder), "clone", url,
                        there, timeout=1800)
                else:
                    git(there, "fetch", "origin", timeout=900)
                if r.get("branch"):
                    if not BRANCH_RE.match(r["branch"]):
                        raise PcError(400, "setup.repos branch %r is not a branch name" % r["branch"])
                    git(there, "checkout", "-B", r["branch"], "origin/" + r["branch"])
                done.append("%s at %s" % (name, git(there, "rev-parse", "--short=12", "HEAD")))
            return ", ".join(done) or "none needed"

        def agent():
            a = self.agent_factory(folder, env=self._agent_env())
            with self.lock:
                self.agents[t["id"]] = a
            a.start()
            a.prompt(first_prompt(t), who="workbench")
            return "Devin Local session %s" % a.session_id

        self._step(t, "Ticket folder and code", get_code)
        self._step(t, "Check out the PR branch", checkout)
        self._step(t, "Find the test pack", pack)
        self._step(t, "Other repos the pack needs", other_repos)
        self._step(t, "Open the evidence run", lambda: self._evidence(t, "start", t["pack"]))
        self._step(t, "Tell Cloud the PC has control",
                   lambda: self._evidence(t, "control", "pc", t["pack"], "--session", t["session"], "--live"))
        t["control"] = "pc"
        self._step(t, "Start Devin Local with /test-on-pc", agent)
        with self.lock:
            t["state"] = "testing"

    def prompt(self, test_id, text):
        a = self._agent(test_id)
        if not (text or "").strip():
            raise PcError(400, "nothing to send")
        a.prompt(text.strip())
        return self.public(test_id)

    def permission(self, test_id, request_id, option_id):
        self._agent(test_id).answer(request_id, option_id)
        return self.public(test_id)

    def return_to_cloud(self, test_id, release_only=False):
        t = self._test(test_id)
        a = self.agents.get(test_id)
        if t["state"] not in ("testing", "failed") or not t.get("control") == "pc":
            raise PcError(409, "this PC does not have control of %s" % t["ticket"])
        if a and a.busy:
            raise PcError(409, "Devin Local is still working; wait for it to finish or press Stop")
        with self.lock:
            t["state"], t["error"] = "returning", ""
        self._go(self._release if release_only else self._return, t)
        return self.public(test_id)

    def _return(self, t):
        folder, b = t["folder"], t["branch"]

        def pushed():
            if git(folder, "status", "--porcelain", "--untracked-files=no"):
                raise PcError(409, "there are uncommitted changes in %s. Commit and push them, or discard "
                                   "them, before returning" % folder)
            git(folder, "fetch", "origin", "+refs/heads/%s:refs/remotes/origin/%s" % (b, b), timeout=900)
            ahead = git(folder, "rev-list", "--count", "origin/%s..HEAD" % b).strip()
            if ahead not in ("", "0"):
                raise PcError(409, "%s commit(s) here are not pushed. Push them to %s first; Cloud then "
                                   "writes a new pack, because this run tested the old commit" % (ahead, b))
            return "nothing left unpushed"

        self._step(t, "Check nothing is left unpushed", pushed)
        self._step(t, "Seal the evidence", lambda: self._evidence(t, "pack", t["pack"]))
        t["result"] = self._step(t, "Send the evidence to Cloud",
                                 lambda: self._evidence(t, "send", t["pack"], "--session", t["session"], "--live"))
        self._release(t)

    def _release(self, t):
        self._step(t, "Hand control back to Cloud",
                   lambda: self._evidence(t, "control", "cloud", t["pack"], "--session", t["session"], "--live"))
        a = self.agents.get(t["id"])
        if a:
            a.stop()
        with self.lock:
            t["state"], t["control"] = "returned", "cloud"

    def stop_agent(self, test_id):
        a = self._agent(test_id)
        a.cancel()
        return self.public(test_id)

    def _test(self, test_id):
        t = self.tests.get(test_id)
        if not t:
            raise PcError(404, "no such PC test")
        return t

    def _agent(self, test_id):
        self._test(test_id)
        a = self.agents.get(test_id)
        if not a:
            raise PcError(409, "Devin Local is not running for this test yet")
        return a

    def public(self, test_id):
        t = self._test(test_id)
        with self.lock:
            out = {k: v for k, v in t.items() if k not in ("extra_repos", "run_file")}
            out["steps"] = [dict(s) for s in t["steps"]]
        a = self.agents.get(test_id)
        out["agent"] = a.snapshot() if a else None
        out["progress"] = progress(out, read_results(t.get("run_file")))
        return out

    def all(self):
        return [self.public(i) for i in sorted(self.tests, key=lambda i: -self.tests[i]["started_at"])]


def login():
    """Starts ``devin auth login``; it opens the browser for the normal sign-in."""
    cli = devin_cli()
    if not cli:
        raise PcError(500, "the Devin CLI is not installed on this PC (https://docs.devin.ai/cli)")
    subprocess.Popen([cli, "auth", "login"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)
    return {"started": True}
