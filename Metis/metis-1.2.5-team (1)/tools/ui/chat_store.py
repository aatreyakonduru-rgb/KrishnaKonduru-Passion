"""Where Chat keeps its conversation threads between server runs.

A thread is only a list of ask ids (the ask records in <kb>/.metis/asks hold the question and the answer, exactly as shown). This
module stores nothing else about a turn: per message one JSON line {"v": 1, "user", "thread", "id", "at"} in

    <kb>/.metis/chat/<user>-<hash>.jsonl        one file per user (lower-case name); a record whose "user" is not that user is ignored

The folder has a .gitignore of `*` and is listed in kb_manifest.LOCAL, so it is local to this machine and is not KB content (kb_gate
does not govern `.metis`). No question text, answer text, KB line text or secret is written here.

Limits: the newest MAX_MESSAGES (200) ids per thread and the MAX_THREADS (50) most recently used threads per user are kept; older ones
are dropped on the next write. Every write rewrites the user's file to a temporary file in the same folder and swaps it in with
os.replace, so a crash leaves the old file or the new one, never half of one. A damaged line is skipped on read. A folder that cannot
be written is not an error for Chat: callers catch OSError and carry on in memory.

Reading a thread does not re-check labels: the caller (screens_chat) filters the answer text it shows through claim_labels.
"""
import datetime
import hashlib
import json
import os
import re
import tempfile
import time
import threading

DIR = os.path.join(".metis", "chat")
MAX_MESSAGES = 200
MAX_THREADS = 50
DEFAULT_THREAD = "main"
ID = re.compile(r"^A-\d{1,9}$")
THREAD = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
LOCK = threading.RLock()


def norm_user(user):
    return " ".join(str(user or "").split()).lower()


def path(kb, user):
    u = norm_user(user)
    if not u:
        raise ValueError("no user")
    slug = re.sub(r"[^a-z0-9]+", "_", u).strip("_")[:24] or "user"
    return os.path.join(kb, DIR, "%s-%s.jsonl" % (slug, hashlib.sha256(u.encode("utf-8")).hexdigest()[:10]))


def _read(kb, user):
    """[(thread, id, at)] in file order for this user. Missing file, damaged lines and other users' records are skipped."""
    u, out = norm_user(user), []
    try:
        with open(path(kb, user), encoding="utf-8") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if (isinstance(r, dict) and r.get("user") == u and ID.match(str(r.get("id"))) and THREAD.match(str(r.get("thread")))):
                    out.append((r["thread"], r["id"], str(r.get("at") or "")))
    except OSError:
        pass
    return out


def _cap(rows):
    """Newest MAX_MESSAGES per thread, and only the MAX_THREADS threads with the latest message."""
    last = {}
    for i, (t, _, _) in enumerate(rows):
        last[t] = i
    keep = set(sorted(last, key=last.get, reverse=True)[:MAX_THREADS])
    per = {}
    for i in range(len(rows) - 1, -1, -1):
        t = rows[i][0]
        if t in keep:
            per.setdefault(t, []).append(i)
    ok = {i for idx in per.values() for i in idx[:MAX_MESSAGES]}
    return [r for i, r in enumerate(rows) if i in ok]


def _write(kb, user, rows):
    p = path(kb, user)
    folder = os.path.dirname(p)
    os.makedirs(folder, exist_ok=True)
    guard = os.path.join(folder, ".gitignore")
    if not os.path.isfile(guard):
        with open(guard, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("*\n")
    u = norm_user(user)
    fd, tmp = tempfile.mkstemp(prefix=".chat-", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            for t, i, at in rows:
                fh.write(json.dumps({"v": 1, "user": u, "thread": t, "id": i, "at": at}, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        for attempt in range(6):        # Windows may deny the swap for a moment while another process has the file open
            try:
                os.replace(tmp, p)
                break
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.05 * (attempt + 1))
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def load(kb, user, thread=DEFAULT_THREAD):
    """The ids of one thread, oldest first (at most MAX_MESSAGES)."""
    with LOCK:
        return [i for t, i, _ in _read(kb, user) if t == thread][-MAX_MESSAGES:]


def threads(kb, user):
    """{thread: [ids]} for the user, each thread capped; at most MAX_THREADS threads."""
    out = {}
    with LOCK:
        for t, i, _ in _cap(_read(kb, user)):
            out.setdefault(t, []).append(i)
    return out


def add(kb, user, aid, thread=DEFAULT_THREAD):
    """Append one message id to the thread and rewrite the file within the caps. Raises ValueError for a bad id/thread/user and
    OSError when the file cannot be written."""
    if not ID.match(str(aid)) or not THREAD.match(str(thread)):
        raise ValueError("bad thread or id")
    with LOCK:
        rows = _read(kb, user)
        rows.append((thread, aid, datetime.datetime.now().isoformat(timespec="seconds")))
        _write(kb, user, _cap(rows))


def clear(kb, user, thread=DEFAULT_THREAD):
    """Drop one thread of the user (the ask records stay in Ask)."""
    with LOCK:
        rows = _read(kb, user)
        keep = [r for r in rows if r[0] != thread]
        if len(keep) != len(rows):
            _write(kb, user, keep)
