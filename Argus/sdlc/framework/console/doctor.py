"""Check my PC: everything Argus and Test on my PC need on this machine, each with a plain fix."""
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

import pctest
from update import _git


def _run(argv, timeout=20):
    try:
        done = subprocess.run(argv, capture_output=True, text=True, errors="replace", timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)
    return done.returncode, (done.stdout + done.stderr).strip()


def _item(name, ok, detail, fix=""):
    return {"name": name, "ok": bool(ok), "detail": detail, "fix": "" if ok else fix}


def _first_line(text):
    return (text or "").strip().splitlines()[0][:200] if (text or "").strip() else ""


def check_python():
    v = sys.version_info
    return _item("Python", v >= (3, 8), "Python %d.%d.%d runs Argus." % tuple(v[:3]),
                 "Install Python 3.8 or newer, then start Argus again.")


def check_git(repo):
    code, out = _git(repo, "--version", timeout=20)
    return _item("Git", not code, _first_line(out) if not code else "git did not run: " + _first_line(out),
                 "Install Git for Windows, then start Argus again.")


def check_copy(updater):
    st = updater.status()
    if not st.get("ok"):
        return _item("This copy of Argus", False, "Cannot check it for updates.",
                     st.get("why") or "Start Argus from its git checkout.")
    detail = "On %s at %s." % (st["branch"], st["head"])
    if st.get("behind"):
        detail += " %d update(s) waiting: use Update Argus in the top bar." % st["behind"]
    bad = st.get("dirty") or st.get("ahead")
    return _item("This copy of Argus", not bad, detail, st.get("why", ""))


def check_bitbucket(repo):
    _, url = _git(repo, "remote", "get-url", "origin", timeout=20)
    code, out = _git(repo, "ls-remote", "origin", "HEAD", timeout=30)
    where = pctest.redact_url(_first_line(url))
    return _item("Bitbucket", not code, ("Reached " + where) if not code else "Could not reach %s: %s" % (where, _first_line(out)),
                 "Check you are on the company network or VPN, and that git can sign in to Bitbucket "
                 "(run git fetch once in Argus folder and sign in if asked).")


KEY_FIX = "Paste your Devin API key in the box under This PC (Devin Cloud → Settings → API keys)."


def check_devin_key(devin):
    return _item("Devin API key", devin.key, "Saved." if devin.key else "Not saved yet.", KEY_FIX)


def check_devin_cloud(devin):
    if not devin.key:
        return _item("Devin Cloud", False, "Not tried: no API key yet.", KEY_FIX)
    try:
        devin.list_sessions("sdlc-workbench", limit=1)
    except Exception as exc:  # noqa: BLE001 - any failure is the answer here
        msg = _first_line(str(exc))
        refused = " 401 " in " %s " % msg or " 403 " in " %s " % msg
        return _item("Devin Cloud", False, "Devin Cloud did not answer: " + msg,
                     "The saved key was refused. Make a new key in Devin Cloud → Settings → API keys and save it again."
                     if refused else "Check the network connection to Devin Cloud, then try again.")
    return _item("Devin Cloud", True, "Devin Cloud answered with the saved key.")


def check_devin_cli():
    cli = pctest.devin_cli()
    fix = "Install the Devin CLI once (docs.devin.ai/cli), check devin --version works in a new terminal, then reload this page."
    if not cli:
        return _item("Devin Local (CLI)", False, "The devin command was not found.", fix)
    code, out = _run([cli, "--version"])
    return _item("Devin Local (CLI)", not code, (_first_line(out) or cli) if not code else "devin --version failed: " + _first_line(out), fix)


def check_tester_python():
    cmd = pctest.tester_python()
    code, out = _run(cmd.split() + ["--version"])
    return _item("Python for Devin Local", not code,
                 ("Devin Local runs checks with %s (%s)." % (cmd, _first_line(out))) if not code else "%s did not run: %s" % (cmd, _first_line(out)),
                 "Install Python 3 so that '%s --version' works in a new terminal." % cmd)


def check_work_root():
    root = pctest.work_root()
    try:
        os.makedirs(root, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=root):
            pass
    except OSError as exc:
        return _item("Ticket folders", False, "Cannot write to %s: %s" % (root, exc),
                     "Set SDLC_WORK_ROOT to a folder you can write to, then start Argus again.")
    return _item("Ticket folders", True, "Each ticket gets its own folder under %s." % root)


def run(repo, updater, devin):
    checks = [check_python, lambda: check_git(repo), lambda: check_copy(updater), lambda: check_bitbucket(repo),
              lambda: check_devin_key(devin), lambda: check_devin_cloud(devin), check_devin_cli,
              check_tester_python, check_work_root]
    names = ["Python", "Git", "This copy of Argus", "Bitbucket", "Devin API key", "Devin Cloud",
             "Devin Local (CLI)", "Python for Devin Local", "Ticket folders"]

    def safe(pair):
        fn, name = pair
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - one broken check must not hide the others
            return _item(name, False, "The check itself failed: %s" % _first_line(str(exc)), "")

    with ThreadPoolExecutor(max_workers=len(checks)) as pool:
        return list(pool.map(safe, zip(checks, names)))
