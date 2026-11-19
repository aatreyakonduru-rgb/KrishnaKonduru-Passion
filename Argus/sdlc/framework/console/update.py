"""Keep Argus on the newest commit of the branch it runs from: see when Bitbucket is ahead,
fast-forward this checkout and restart the server, so nobody types git or py -3 to get a new version."""
import os
import re
import subprocess
import sys
import threading
import time

from pctest import PcError

FETCH_EVERY_SECONDS = 90
TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")


# Called after each fetch from Bitbucket with (ok, error); Argus server puts it on its status light.
ON_FETCH = None

def _git(repo, *args, timeout=60):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    try:
        done = subprocess.run(["git"] + list(args), cwd=repo, capture_output=True, text=True, errors="replace",
                              timeout=timeout, env=env)
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)
    return done.returncode, (done.stdout + done.stderr).strip()


def restart_process():
    """Start this server again with the same arguments, on the code now in the checkout.
    Call it from the main thread once the HTTP server has stopped and released the port."""
    argv = [sys.executable] + sys.argv
    sys.stdout.flush()
    sys.stderr.flush()
    if os.name == "nt":
        subprocess.Popen(argv)
        os._exit(0)
    os.execv(sys.executable, argv)


def _version(path, pattern):
    try:
        with open(path, encoding="utf-8") as fh:
            found = re.search(pattern, fh.read(), re.M)
    except OSError:
        return ""
    return found.group(1).strip() if found else ""


def about(repo, tools=TOOLS):
    """What the Help menu's About shows: the framework version (distribution_map.yaml, or tools/VERSION
    in a shared copy), the shared-prompt version (sdlc/kb/VERSION), and the branch, commit and
    commit date of ``repo``."""
    out = {"version": _version(os.path.join(tools, "distribution_map.yaml"), r'^version:\s*"?([^"\s#]+)')
                      or _version(os.path.join(tools, "VERSION"), r"^(\S+)"),
           "prompts_version": _version(os.path.join(repo, "sdlc", "kb", "VERSION"), r"^(\S+)"),
           "branch": "", "commit": "", "commit_date": ""}
    code, line = _git(repo, "log", "-1", "--format=%h|%cI")
    if not code and "|" in line:
        out["commit"], out["commit_date"] = line.split("|", 1)
    code, branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if not code and branch != "HEAD":
        out["branch"] = branch
    return out


class Updater:
    def __init__(self, repo, busy=lambda: "", restart=None, delay=1.0, fetch=True):
        """``restart`` is called (on a timer, so the reply goes out first) after a successful update;
        the server passes its own ``shutdown`` and calls restart_process() once serve_forever returns."""
        self.repo, self.busy, self.delay, self.fetch = repo, busy, delay, fetch
        self.restart = restart or restart_process
        self.restarting = False
        self.lock = threading.Lock()
        self.fetched, self.fetch_error, self.timer = 0, "", None

    def status(self, fresh=False):
        code, branch = _git(self.repo, "rev-parse", "--abbrev-ref", "HEAD")
        if code or branch == "HEAD":
            return {"ok": False, "why": "This copy of Argus is not on a branch, so it cannot update itself."}
        with self.lock:
            if self.fetch and (fresh or time.time() - self.fetched > FETCH_EVERY_SECONDS):
                code, out = _git(self.repo, "fetch", "-q", "origin",
                                 "+refs/heads/%s:refs/remotes/origin/%s" % (branch, branch))
                self.fetch_error = out[-300:] if code else ""
                self.fetched = time.time()
                if ON_FETCH:
                    ON_FETCH(not code, self.fetch_error)
        _, head = _git(self.repo, "rev-parse", "HEAD")
        code, remote = _git(self.repo, "rev-parse", "--verify", "-q", "origin/" + branch)
        out = {"ok": not code, "branch": branch, "head": head[:8], "remote": remote[:8] if not code else "",
               "behind": 0, "ahead": 0, "dirty": False, "busy": False, "fetch_error": self.fetch_error, "why": ""}
        if code:
            out["why"] = "Bitbucket has no branch %s." % branch
            return out
        for key, spec in (("behind", "HEAD..origin/"), ("ahead", "origin/%s..HEAD")):
            rng = spec + branch if key == "behind" else spec % branch
            _, n = _git(self.repo, "rev-list", "--count", rng)
            out[key] = int(n) if n.isdigit() else 0
        _, dirty = _git(self.repo, "status", "--porcelain", "--untracked-files=no")
        out["dirty"] = bool(dirty.strip())
        if out["dirty"]:
            out["why"] = "This copy of Argus has local changes. Commit or undo them first."
        elif out["ahead"]:
            out["why"] = "This copy of Argus has commits that are not on Bitbucket. Push them first."
        else:
            out["why"] = self.busy() or ""
            out["busy"] = bool(out["why"])
        return out

    def apply(self):
        st = self.status(fresh=True)
        if not st["ok"] or st["why"]:
            raise PcError(409, st["why"])
        if not st["behind"]:
            return dict(st, updated=False)
        code, out = _git(self.repo, "merge", "--ff-only", "-q", "origin/" + st["branch"])
        if code:
            raise PcError(409, "Could not update: %s" % out[-300:])
        self.restarting = True
        self.timer = threading.Timer(self.delay, self.restart)
        self.timer.start()
        return dict(self.status(), updated=True, was=st["head"])
