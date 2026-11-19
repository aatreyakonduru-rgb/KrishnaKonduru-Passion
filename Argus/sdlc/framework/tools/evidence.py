#!/usr/bin/env python3
"""Evidence from a test run on a developer PC, packed so the Cloud session can trust it.

Cloud writes a test pack for a story (.devin/templates/test-pack.yaml) and commits it on the PR
branch. On the PC, /test-on-pc uses this tool to run the pack's automated checks, record what the
tester saw for each acceptance criterion, and send one zip back to the same Cloud session. Cloud
runs `verify` on that zip before it writes the test report.

    evidence.py start   PACK                      # HEAD is the pack's commit (+ test-pack-only commits)
    evidence.py run     PACK [--check CHK-1 ...]  # run the automated checks, logs scrubbed
    evidence.py mark    PACK AC-1 passed|failed|not-run [--note ".."] [--screenshot F --no-member-data]
    evidence.py status  PACK                      # what is recorded so far
    evidence.py pack    PACK [--skip-remote-check]  # tree clean + PR head still this commit, then zip
    evidence.py send    PACK --session devin-<id> [--jira ACME-n] [--live]  # PR head re-checked first
    evidence.py control pc|cloud PACK --session devin-<id> [--live]
    evidence.py verify  ZIP [--commit SHA]        # Cloud side: hashes, commit, per-item results

Every result is one of: passed, failed, not run. A check whose prerequisites are missing (an env
var named in needs_env, or build_check's "credential not provisioned" exit 5) is recorded as not
run with the reason, never as passed. Runs live outside the repository under
~/.sdlc/evidence/{REQ}-{STORY}/{commit}/ (SDLC_EVIDENCE_HOME overrides). Nothing leaves the PC
without --live. Needs DEVIN_API_KEY for send/control; ACME_JIRA_TOKEN only for --jira.
"""
import argparse
import datetime
import hashlib
import importlib.util
import json
import os
import platform
import re
import shutil
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
import zipfile

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
DEVIN_API = os.environ.get("DEVIN_API_BASE", "https://api.devin.ai").rstrip("/")
RETRY_WAITS = (5, 10, 20, 30, 60)
STATUSES = ("passed", "failed", "not run")
WHERE = "ran on PC"
SECRET_ENV = ("ARTIFACTORY_TOKEN", "DEVIN_API_KEY", "ACME_JIRA_TOKEN")
PACK_DIR = "sdlc/framework/context/test-packs/"
TEXT_EXT = (".log", ".txt", ".json", ".md", ".yaml", ".yml", ".xml", ".html")

PATTERNS = [
    (re.compile(r"(?i)(authorization\s*[:=]\s*(?:bearer|basic)\s+)\S+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]{8,}"), r"\1[REDACTED]"),
    (re.compile(r"\bapk_(?:user_)?[A-Za-z0-9_-]{8,}"), "[REDACTED]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}"), "[REDACTED-JWT]"),
    (re.compile(r"(?i)(_authToken|_auth|password|passwd|pwd|secret|token|api[_-]?key)(\s*[=:]\s*)(\"?)[^\s\"',;]+"),
     r"\1\2\3[REDACTED]"),
    (re.compile(r"(://[^/\s:@]+:)[^@\s/]+@"), r"\1[REDACTED]@"),
]


class EvidenceError(Exception):
    pass


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def git(*args, check=True):
    out = subprocess.run(["git", "-C", ROOT] + list(args), capture_output=True, text=True)
    if check and out.returncode != 0:
        raise EvidenceError("git %s failed: %s" % (" ".join(args), out.stderr.strip()[:300]))
    return out.stdout.strip()


# ------------------------------------------------------------------ test pack

def load_pack(path):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    if path.endswith(".json") or yaml is None:
        pack = json.loads(text)
    else:
        pack = yaml.safe_load(text)
    missing = [k for k in ("req_id", "story_id", "commit", "branch") if not pack.get(k)]
    if missing:
        raise EvidenceError("test pack %s is missing %s" % (path, ", ".join(missing)))
    ids = [c["id"] for c in pack.get("checks") or []] + [a["id"] for a in pack.get("acceptance") or []]
    if len(ids) != len(set(ids)):
        raise EvidenceError("test pack %s repeats an id" % path)
    if not ids:
        raise EvidenceError("test pack %s has no checks and no acceptance criteria" % path)
    return pack


def run_dir(pack):
    home = os.environ.get("SDLC_EVIDENCE_HOME") or os.path.join(os.path.expanduser("~"), ".sdlc", "evidence")
    return os.path.join(home, "%s-%s" % (pack["req_id"], pack["story_id"]), str(pack["commit"])[:12])


def run_file(pack):
    return os.path.join(run_dir(pack), "run.json")


def load_run(pack):
    path = run_file(pack)
    if not os.path.exists(path):
        raise EvidenceError("no run open for this pack — run `evidence.py start` first")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def save_run(pack, run):
    with open(run_file(pack), "w", encoding="utf-8") as fh:
        json.dump(run, fh, indent=2, sort_keys=True)


def same_commit(a, b):
    a, b = str(a or "").lower(), str(b or "").lower()
    n = min(len(a), len(b))
    return n >= 7 and a[:n] == b[:n]


def pack_only_since(code_commit, head):
    """True when head is code_commit, or descends from it and only adds or changes test packs."""
    if same_commit(head, code_commit):
        return True
    full = git("rev-parse", "--verify", "--quiet", str(code_commit) + "^{commit}", check=False)
    if not full:
        return False
    if subprocess.run(["git", "-C", ROOT, "merge-base", "--is-ancestor", full, head],
                      capture_output=True).returncode != 0:
        return False
    changed = [f for f in git("diff", "--name-only", full, head).splitlines() if f]
    return all(f.startswith(PACK_DIR) for f in changed)


# ------------------------------------------------------------------ scrubbing

def secret_values(pack):
    values = set()
    names = set(SECRET_ENV)
    for env_file in (pack.get("setup") or {}).get("env_files") or []:
        names.update(env_file.get("keys") or [])
        path = os.path.join(ROOT, env_file.get("path", ""))
        if env_file.get("path") and os.path.isfile(path):
            with open(path, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if "=" in line and not line.lstrip().startswith("#"):
                        values.add(line.split("=", 1)[1].strip().strip("\"'"))
    for name in names:
        if os.environ.get(name):
            values.add(os.environ[name])
    return sorted((v for v in values if len(v) >= 6), key=len, reverse=True)


def scrub_text(text, values=()):
    for value in values:
        text = text.replace(value, "[REDACTED]")
    for pattern, repl in PATTERNS:
        text = pattern.sub(repl, text)
    return text


# ------------------------------------------------------------------ commands

def cmd_start(args):
    pack = load_pack(args.pack)
    head = git("rev-parse", "HEAD")
    if not pack_only_since(pack["commit"], head):
        raise EvidenceError("this checkout is at %s but the test pack is for %s — check out the PR commit first"
                            % (head[:12], str(pack["commit"])[:12]))
    code_commit = git("rev-parse", str(pack["commit"]) + "^{commit}")
    os.makedirs(os.path.join(run_dir(pack), "logs"), exist_ok=True)
    os.makedirs(os.path.join(run_dir(pack), "screenshots"), exist_ok=True)
    if os.path.exists(run_file(pack)) and not args.restart:
        print("run already open: %s (use --restart to clear it)" % run_dir(pack))
        return 0
    results = {}
    for item in (pack.get("checks") or []) + (pack.get("acceptance") or []):
        results[item["id"]] = {"status": "not run", "where": WHERE, "note": "not attempted", "files": []}
    run = {
        "req_id": pack["req_id"], "story_id": pack["story_id"], "jira_key": pack.get("jira_key", ""),
        "pr_url": pack.get("pr_url", ""), "branch": pack["branch"], "commit": code_commit, "head": head,
        "cloud_session": pack.get("cloud_session", ""),
        "tested_by": git("config", "--get", "user.email", check=False) or os.environ.get("USERNAME")
        or os.environ.get("USER", ""),
        "machine": platform.node(), "os": platform.platform(), "started_at": now(), "results": results,
    }
    save_run(pack, run)
    print("run opened at %s for %s %s, commit %s" % (run_dir(pack), pack["req_id"], pack["story_id"], head[:12]))
    return 0


def resolve(command):
    if command and command[0] in ("python", "python3", "py"):
        return [sys.executable] + command[1:]
    exe = shutil.which(command[0])
    return [exe] + command[1:] if exe else command


def cmd_run(args):
    pack = load_pack(args.pack)
    run = load_run(pack)
    values = secret_values(pack)
    wanted = set(args.check or [])
    for check in pack.get("checks") or []:
        if wanted and check["id"] not in wanted:
            continue
        result = run["results"][check["id"]]
        missing = [n for n in check.get("needs_env") or [] if not os.environ.get(n)]
        missing += ["command " + n for n in check.get("needs_cmd") or [] if not shutil.which(n)]
        missing += ["Python package " + n for n in check.get("needs_modules") or []
                    if importlib.util.find_spec(n) is None]
        if missing:
            result.update(status="not run", note="missing on this PC: " + ", ".join(missing), at=now())
            print("%-8s not run   %s" % (check["id"], result["note"]))
            continue
        command = check["command"] if isinstance(check["command"], list) else check["command"].split()
        log_name = "logs/%s.log" % check["id"]
        try:
            out = subprocess.run(resolve(command), cwd=os.path.join(ROOT, check.get("cwd", ".")),
                                 capture_output=True, text=True, errors="replace",
                                 timeout=int(check.get("timeout_minutes", 60)) * 60)
            code, text = out.returncode, out.stdout + out.stderr
        except FileNotFoundError:
            code, text = None, "command not found: %s" % command[0]
        except subprocess.TimeoutExpired:
            code, text = -1, "timed out after %s minutes" % check.get("timeout_minutes", 60)
        with open(os.path.join(run_dir(pack), log_name), "w", encoding="utf-8") as fh:
            fh.write(scrub_text("$ %s\n\n%s" % (" ".join(command), text), values))
        if code is None:
            status, note = "not run", text
        elif code == 0:
            status, note = "passed", "exit 0"
        elif code == int(check.get("not_run_exit", -999)):
            status, note = "not run", "exit %d: prerequisite missing (see log)" % code
        else:
            status, note = "failed", "exit %d" % code
        result.update(status=status, note=note, files=[log_name], at=now())
        print("%-8s %-9s %s" % (check["id"], status, note))
    save_run(pack, run)
    return 0


def cmd_mark(args):
    pack = load_pack(args.pack)
    run = load_run(pack)
    status = args.status.replace("-", " ")
    if args.id not in run["results"]:
        raise EvidenceError("%s is not in the test pack" % args.id)
    if args.screenshot and not args.no_member_data:
        raise EvidenceError("screenshots need --no-member-data: look at each one first and confirm it shows "
                            "no member data, names or real IDs")
    result = run["results"][args.id]
    files = list(result.get("files") or [])
    for shot in args.screenshot or []:
        name = "screenshots/%s-%d%s" % (args.id, len(files) + 1, os.path.splitext(shot)[1].lower())
        shutil.copyfile(shot, os.path.join(run_dir(pack), name))
        files.append(name)
    note = scrub_text(args.note or "", secret_values(pack))
    result.update(status=status, note=note, files=files, at=now(),
                  checked_by=run.get("tested_by", ""), member_data_checked=bool(args.no_member_data))
    save_run(pack, run)
    print("%s %s" % (args.id, status))
    return 0


def counts(results):
    return {s: sum(1 for r in results.values() if r["status"] == s) for s in STATUSES}


def summary_line(run):
    c = counts(run["results"])
    return "[SDLC] evidence %s %s %s passed=%d failed=%d not_run=%d" % (
        run["req_id"], run["story_id"], run["commit"][:12], c["passed"], c["failed"], c["not run"])


def cmd_status(args):
    pack = load_pack(args.pack)
    run = load_run(pack)
    for item_id, r in run["results"].items():
        print("%-8s %-9s %s" % (item_id, r["status"], r.get("note", "")))
    print(summary_line(run))
    return 0


def zip_path(pack):
    name = "evidence-%s-%s-%s.zip" % (pack["req_id"], pack["story_id"], str(pack["commit"])[:12])
    return os.path.join(run_dir(pack), name)


def check_pr_head(run, skip_flag):
    tested = run.get("head") or run["commit"]
    line = git("ls-remote", "origin", "refs/heads/" + run["branch"], check=False)
    remote = line.split()[0] if line else ""
    if not remote:
        raise EvidenceError("could not read %s from origin. Fix the network, or pass %s "
                            "(Cloud will see that the check was skipped)" % (run["branch"], skip_flag))
    if not same_commit(remote, tested):
        raise EvidenceError("the PR branch is now at %s, not the tested %s. Something was pushed after this "
                            "run started; test the new commit" % (remote[:12], tested[:12]))


def cmd_pack(args):
    pack = load_pack(args.pack)
    run = load_run(pack)
    head = git("rev-parse", "HEAD")
    tested = run.get("head") or run["commit"]
    if not same_commit(head, tested):
        raise EvidenceError("HEAD moved to %s after the run started at %s — the evidence would not match"
                            % (head[:12], tested[:12]))
    dirty = git("status", "--porcelain", "--untracked-files=no")
    if dirty:
        raise EvidenceError("this checkout has uncommitted changes to tracked files. Commit and push any fix "
                            "(then test the new commit), or discard them:\n" + dirty)
    if args.skip_remote_check:
        run["remote_check"] = "skipped"
    else:
        check_pr_head(run, "--skip-remote-check")
        run["remote_check"] = "PR head matched at " + now()
    run["packed_at"] = now()
    base = run_dir(pack)
    hashes = {}
    for item in run["results"].values():
        for rel in item.get("files") or []:
            with open(os.path.join(base, rel), "rb") as fh:
                hashes[rel] = hashlib.sha256(fh.read()).hexdigest()
    manifest = dict(run, files=hashes, summary=summary_line(run), tool="evidence.py")
    out = zip_path(pack)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))
        for rel in hashes:
            zf.write(os.path.join(base, rel), rel)
    save_run(pack, run)
    print(out)
    print(summary_line(run))
    return 0


def _ctx():
    return ssl._create_unverified_context()


def devin_call(method, path, body=None, headers=None, raw=None):
    key = os.environ.get("DEVIN_API_KEY")
    if not key:
        raise EvidenceError("DEVIN_API_KEY is not set on this PC")
    h = {"Authorization": "Bearer " + key, "Accept": "application/json"}
    data = raw
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    h.update(headers or {})
    for wait in RETRY_WAITS + (None,):
        req = urllib.request.Request(DEVIN_API + "/v1" + path, data=data, headers=h, method=method)
        try:
            with urllib.request.urlopen(req, context=_ctx(), timeout=120) as resp:
                text = resp.read().decode() or "{}"
            break
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:300]
            # A session that has just woken up or restarted refuses messages for a short while.
            if wait is None or not (exc.code in (429, 502, 503, 504) or "still initializing" in detail):
                raise EvidenceError("Devin API %d on %s: %s" % (exc.code, path, detail))
            print("Devin API %d on %s (%s); trying again in %ds" % (exc.code, path, detail[:80], wait),
                  file=sys.stderr)
            time.sleep(wait)
        except urllib.error.URLError as exc:
            raise EvidenceError("cannot reach %s (%s)" % (DEVIN_API, exc.reason))
    try:
        return json.loads(text)
    except ValueError:
        return text.strip().strip('"')


def session_id(value):
    m = re.search(r"([0-9a-f]{32})", value or "")
    if not m:
        raise EvidenceError("not a Devin session id or URL: %r" % value)
    return "devin-" + m.group(1)


def post_message(session, text, live):
    if not live:
        print("DRY-RUN POST %s/v1/sessions/%s/message\n%s" % (DEVIN_API, session, text))
        return
    devin_call("POST", "/sessions/%s/message" % session, {"message": text})
    print("sent to %s" % session)


def cmd_send(args):
    pack = load_pack(args.pack)
    run = load_run(pack)
    out = zip_path(pack)
    if not run.get("packed_at") or not os.path.exists(out):
        raise EvidenceError("run `evidence.py pack` first")
    session = session_id(args.session or run.get("cloud_session"))
    if run.get("remote_check") != "skipped" and not args.skip_remote_check:
        check_pr_head(run, "--skip-remote-check")
    name = os.path.basename(out)
    with open(out, "rb") as fh:
        payload = fh.read()
    url = "(attachment)"
    if args.live:
        boundary = uuid.uuid4().hex
        body = (("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"%s\"\r\n"
                 "Content-Type: application/zip\r\n\r\n") % (boundary, name)).encode() + payload + (
                    "\r\n--%s--\r\n" % boundary).encode()
        res = devin_call("POST", "/attachments", raw=body,
                         headers={"Content-Type": "multipart/form-data; boundary=" + boundary})
        url = res.get("url", "") if isinstance(res, dict) else res
    else:
        print("DRY-RUN POST %s/v1/attachments  %s (%d bytes)" % (DEVIN_API, name, len(payload)))
    tested = "Tested on %s by %s, %s. %s." % (
        run["machine"], run["tested_by"], run["packed_at"], run.get("remote_check", ""))
    verify = "Verify with: python3 sdlc/framework/tools/evidence.py verify %s --commit <PR head>" % name
    text = "\n".join([summary_line(run), tested, verify,
                      url])
    post_message(session, text, args.live)
    if args.jira:
        sys.path.insert(0, HERE)
        import session_store  # noqa: E402
        session_store.JiraAttachments(live=args.live).upload(args.jira, name, payload)
    return 0


def cmd_control(args):
    pack = load_pack(args.pack)
    session = session_id(args.session or pack.get("cloud_session"))
    if args.side == "pc":
        text = ("[SDLC] control pc %s\nThe PC has control for %s %s. Do not push to %s until you see "
                "[SDLC] control cloud." % (str(pack["commit"])[:12], pack["req_id"], pack["story_id"], pack["branch"]))
    else:
        text = "[SDLC] control cloud\nThe PC has finished testing %s %s; Cloud has control again." % (
            pack["req_id"], pack["story_id"])
    post_message(session, text, args.live)
    return 0


def cmd_verify(args):
    with zipfile.ZipFile(args.zip) as zf:
        manifest = json.loads(zf.read("manifest.json"))
        problems = []
        for rel, digest in (manifest.get("files") or {}).items():
            if hashlib.sha256(zf.read(rel)).hexdigest() != digest:
                problems.append("%s does not match its hash" % rel)
    if args.commit and not any(same_commit(args.commit, manifest.get(k)) for k in ("commit", "head")):
        problems.append("evidence is for %s but the PR head is %s"
                        % (manifest.get("commit", "")[:12], args.commit[:12]))
    if manifest.get("remote_check") == "skipped":
        problems.append("warning: the PC skipped the PR-head check")
    print("%s %s commit %s, tested by %s on %s" % (
        manifest.get("req_id"), manifest.get("story_id"), manifest.get("commit", "")[:12],
        manifest.get("tested_by"), manifest.get("machine")))
    for item_id, r in sorted((manifest.get("results") or {}).items()):
        print("%-8s %-9s %-10s %s" % (item_id, r["status"], r.get("where", WHERE), r.get("note", "")))
    for p in problems:
        print("PROBLEM: " + p)
    return 1 if any(not p.startswith("warning") for p in problems) else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    def command(name, fn, *positional):
        p = sub.add_parser(name)
        for arg in positional:
            p.add_argument(arg)
        p.set_defaults(fn=fn)
        return p

    command("start", cmd_start, "pack").add_argument("--restart", action="store_true")
    command("run", cmd_run, "pack").add_argument("--check", action="append")
    p = command("mark", cmd_mark, "pack", "id")
    p.add_argument("status", choices=["passed", "failed", "not-run"])
    p.add_argument("--note")
    p.add_argument("--screenshot", action="append")
    p.add_argument("--no-member-data", action="store_true")
    command("status", cmd_status, "pack")
    command("pack", cmd_pack, "pack").add_argument("--skip-remote-check", action="store_true")
    p = command("send", cmd_send, "pack")
    p.add_argument("--session")
    p.add_argument("--skip-remote-check", action="store_true")
    p.add_argument("--jira")
    p.add_argument("--live", action="store_true")
    p = sub.add_parser("control")
    p.add_argument("side", choices=["pc", "cloud"])
    p.add_argument("pack")
    p.add_argument("--session")
    p.add_argument("--live", action="store_true")
    p.set_defaults(fn=cmd_control)
    command("verify", cmd_verify, "zip").add_argument("--commit")
    args = ap.parse_args(argv)
    try:
        return args.fn(args)
    except EvidenceError as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
