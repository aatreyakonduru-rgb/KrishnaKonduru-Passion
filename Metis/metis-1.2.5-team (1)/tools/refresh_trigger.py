#!/usr/bin/env python3
"""Event-driven refresh: when source code changes, work out which KB pages went stale and queue one task to refresh only those.

    python3 refresh_trigger.py plan  <kb> (--files repo/path ... | --git REPO FROM TO | --payload FILE | --env | --since-build)
                                          [--repo NAME] [--branch NAME ...] [--task --by NAME] [--no-write]
    python3 refresh_trigger.py show  <kb>                         the last refresh plan
    python3 refresh_trigger.py serve-webhook <kb> [--host 127.0.0.1] [--port 8766] [--secret-env VAR] [--branch NAME ...] [--task --by NAME]
    python3 refresh_trigger.py schedule <kb> [--every hourly|daily|weekly] [--at HH:MM] [--day mon] [--by NAME]

Where the list of changed files comes from (one per run):
  --files      repo-relative paths written as the KB tags them, `api/src/Orders.java`; with --repo, plain paths in that repo
  --git        `--git api <from> <to>`: `git diff --name-only` in the local clone of that repo (build_plan.repo_dirs); read only
  --payload    a Bitbucket push event saved as JSON (Server/Data Center `repo:refs_changed`, Cloud `repo:push`). A push event names
               commits, not files, so the files come from the same `git diff` in the local clone. The clone must already hold
               the new commit (fetch first). A new branch has no old commit: the commit recorded by the last build is used.
  --env        pipeline variables: METIS_CHANGED_FILES (lines or commas) with METIS_REPO, or METIS_REPO + METIS_BEFORE + METIS_AFTER
               (METIS_AFTER defaults to BITBUCKET_COMMIT). BITBUCKET_REPO_SLUG gives the repo when METIS_REPO is not set.
  --since-build  everything build_plan.py `stale` lists: source files changed since the commits the last build recorded

A repo that cannot be compared (no clone, commit not in the clone, nothing recorded) makes every page citing it stale, as in
build_plan.py, and the plan says so. Pages are found from the [E: repo/path:line] tags (build_plan.cited_files). Derived files
(the link graph, matrix, registries) are left out: tools regenerate them; a session does not rewrite them.

The plan is written to <kb>/.metis/refresh_plan.json: the trigger, the changed files, the stale pages with their reasons, notes,
and the task id if one was queued. It holds file names only. With --task, one task is queued in <kb>/.metis/tasks (the Devin task
queue of ui/tasks.py, kind build-stage): a Devin session claims it, refreshes only the listed pages into a staging folder under
_REGEN, and stages the result to _PENDING through kb_gate.py propose, where a lead certifies it. Nothing here calls the Devin API
or a model, and nothing writes into the KB. A task for the same pages is not queued twice while one is queued or running.
After a lead certifies the refreshed pages, run `build_plan.py record <kb>` so they stop showing as stale.

`serve-webhook` is a tiny HTTP listener for Bitbucket webhooks (POST /webhook). It binds to 127.0.0.1 unless --host says otherwise
(then put it behind your own TLS proxy), refuses to start without a shared secret in the environment variable named by --secret-env
(default METIS_WEBHOOK_SECRET; or `refresh.secret_env` in the profile), and answers 401 to any request whose `X-Hub-Signature`
(`sha256=<hex>`, HMAC-SHA256 of the body) is missing or wrong. It writes the plan; it queues a task only with --task.
NEEDS YOUR BITBUCKET TO VERIFY: the header names and payload shapes follow the Bitbucket documentation and are tested here only
with made-up payloads.

`schedule` only PRINTS a cron line, a Windows Task Scheduler command and a wording for a Devin schedule. It installs nothing.
"""
import argparse
import datetime
import hashlib
import hmac
import json
import os
import re
import shlex
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "ui"))
import build_plan  # noqa: E402
import kb_gate  # noqa: E402

PLAN = os.path.join(".metis", "refresh_plan.json")
MAX_BODY = 1024 * 1024
MAX_FILES_SHOWN = 200
ZERO = re.compile(r"^0+$")
HEX = re.compile(r"^[0-9a-fA-F]{7,64}$")
REV = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/~^@{}-]{0,100}$")
DEFAULT_SECRET_ENV = "METIS_WEBHOOK_SECRET"
LOOPBACK = ("127.0.0.1", "localhost", "::1")
PUSH_EVENTS = ("repo:refs_changed", "repo:push")
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
CRON_DAY = dict(zip(DAYS, ("1", "2", "3", "4", "5", "6", "0")))
WORK = threading.Lock()


class RefreshError(ValueError):
    pass


def clean(x):
    return " ".join(str(x or "").split())


def settings(kb):
    s = kb_gate.profile(kb).get("refresh")
    return s if isinstance(s, dict) else {}


# ---- repo names and git -----------------------------------------------------------------------
def kb_repo_name(kb, slug):
    """The repo name the KB's [E: repo/path:line] tags use for a Bitbucket repository slug."""
    dirs = build_plan.repo_dirs(kb)
    if slug in dirs:
        return slug
    prof = kb_gate.profile(kb)
    mapped = clean((prof.get("bitbucket") or {}).get("source_repo")) if isinstance(prof.get("bitbucket"), dict) else ""
    return mapped or slug


def recorded_commit(kb, repo):
    st = kb_gate.load_yaml(os.path.join(kb, build_plan.STATE))
    return (st.get("repos") or {}).get(repo)


def safe_rev(rev, what="commit"):
    if not REV.match(str(rev or "")):
        raise RefreshError("%s is not a commit or branch name I will pass to git: %r" % (what, str(rev)[:40]))
    return str(rev)


def git_changed(kb, repo, old, new):
    """({paths} or None, note): `git diff --name-only old new` in the clone of `repo`. None means it cannot be compared."""
    d = build_plan.repo_dirs(kb).get(repo)
    if not d:
        return None, "%s: no local clone under sources.repos, so every page citing it is listed" % repo
    old = old or recorded_commit(kb, repo)
    if not old:
        return None, "%s: no old commit given and none recorded by a build, so every page citing it is listed" % repo
    safe_rev(old, "old commit")
    safe_rev(new, "new commit")
    code, out = build_plan.git(d, "diff", "--name-only", old, new, "--")
    if code != 0:
        return None, "%s: %s..%s cannot be compared in the clone (fetch it first), so every page citing it is listed" % (repo, str(old)[:8], str(new)[:8])
    return {x.strip() for x in out.splitlines() if x.strip()}, ""


def add_changes(changes, repo, paths):
    """Merge into {repo: set or None}; None (cannot compare) wins."""
    if paths is None or changes.get(repo, set()) is None:
        changes[repo] = None
    else:
        changes.setdefault(repo, set()).update(paths)


# ---- where the changes come from --------------------------------------------------------------
def split_files(kb, files, repo=None):
    """{repo: {paths}} from `repo/path` strings (or plain paths with `repo`)."""
    out = {}
    for f in files:
        f = str(f).strip().lstrip("/")
        if not f:
            continue
        if repo:
            out.setdefault(repo, set()).add(f)
        else:
            head, _, rest = f.partition("/")
            if not rest:
                raise RefreshError("write the path as repo/path (the repo name as in the KB's source tags), or give --repo: %s" % f)
            out.setdefault(head, set()).add(rest)
    return out


def parse_payload(data):
    """A Bitbucket push event -> (repo slug, [{branch, old, new}]). Raises RefreshError when it is not a push event.
    Tag pushes and deletions are skipped."""
    if not isinstance(data, dict):
        raise RefreshError("the payload is not a JSON object")
    repo = data.get("repository") if isinstance(data.get("repository"), dict) else {}
    items = []
    if isinstance(data.get("changes"), list):  # Bitbucket Server / Data Center, repo:refs_changed
        slug = clean(repo.get("slug"))
        for c in data["changes"]:
            ref = c.get("ref") or {}
            new, old = clean(c.get("toHash")), clean(c.get("fromHash"))
            if c.get("type") == "DELETE" or ref.get("type", "BRANCH") != "BRANCH" or not new or ZERO.match(new):
                continue
            items.append({"branch": re.sub(r"^refs/heads/", "", clean(ref.get("id")) or clean(ref.get("displayId"))),
                          "old": None if not old or ZERO.match(old) else old, "new": new})
    elif isinstance((data.get("push") or {}).get("changes"), list):  # Bitbucket Cloud, repo:push
        slug = clean(repo.get("full_name") or repo.get("name")).split("/")[-1]
        for c in data["push"]["changes"]:
            new, old = c.get("new"), c.get("old")
            if not isinstance(new, dict) or new.get("type") != "branch" or not (new.get("target") or {}).get("hash"):
                continue
            items.append({"branch": clean(new.get("name")), "old": ((old or {}).get("target") or {}).get("hash") or None,
                          "new": new["target"]["hash"]})
    else:
        raise RefreshError("not a Bitbucket push payload (no `changes` and no `push.changes`)")
    if not slug:
        raise RefreshError("the payload does not name the repository")
    for it in items:
        for k in ("old", "new"):
            if it[k] and not HEX.match(it[k]):
                raise RefreshError("a commit id in the payload is not hexadecimal")
    return slug, items


def from_payload(kb, data, branches=()):
    """(changes, trigger, notes) from a push payload."""
    slug, items = parse_payload(data)
    repo = kb_repo_name(kb, slug)
    changes, notes = {}, []
    kept = [it for it in items if not branches or it["branch"] in branches]
    if len(kept) < len(items):
        notes.append("%d change%s on other branches ignored" % (len(items) - len(kept), "" if len(items) - len(kept) == 1 else "s"))
    for it in kept:
        paths, note = git_changed(kb, repo, it["old"], it["new"])
        add_changes(changes, repo, paths)
        if note:
            notes.append(note)
    trig = {"kind": "payload", "repo": repo, "branches": sorted({it["branch"] for it in kept}),
            "from": kept[0]["old"] if kept else None, "to": kept[-1]["new"] if kept else None}
    return changes, trig, notes


def from_env(kb, env):
    repo = clean(env.get("METIS_REPO") or env.get("BITBUCKET_REPO_SLUG"))
    repo = kb_repo_name(kb, repo) if repo else ""
    listed = [x for x in re.split(r"[\n,]+", env.get("METIS_CHANGED_FILES") or "") if x.strip()]
    changes, notes = {}, []
    if listed:
        if not repo and any("/" not in x for x in listed):
            raise RefreshError("METIS_CHANGED_FILES holds plain paths: set METIS_REPO too")
        for r, p in split_files(kb, listed, repo or None).items():
            add_changes(changes, r, p)
        return changes, {"kind": "env", "repo": repo or None, "from": None, "to": None}, notes
    if not repo:
        raise RefreshError("set METIS_CHANGED_FILES, or METIS_REPO with METIS_BEFORE and METIS_AFTER")
    new = env.get("METIS_AFTER") or env.get("BITBUCKET_COMMIT") or "HEAD"
    old = env.get("METIS_BEFORE") or None
    paths, note = git_changed(kb, repo, old, new)
    add_changes(changes, repo, paths)
    if note:
        notes.append(note)
    return changes, {"kind": "env", "repo": repo, "from": old, "to": new}, notes


# ---- stale pages ------------------------------------------------------------------------------
def pages_for(kb, changes):
    """([{page, reasons}], notes): hand-written pages that cite a changed file, or a repo that cannot be compared."""
    out, skipped = [], 0
    for page, repos in sorted(build_plan.cited_files(kb).items()):
        reasons = []
        for repo, paths in sorted(repos.items()):
            if repo not in changes:
                continue
            if changes[repo] is None:
                reasons.append("%s: cannot compare" % repo)
            else:
                reasons += ["%s/%s changed" % (repo, p) for p in sorted(paths) if p in changes[repo]]
        if not reasons:
            continue
        if kb_gate.derived(page):
            skipped += 1
            continue
        out.append({"page": page, "reasons": reasons})
    return out, (["%d derived file%s left out (tools regenerate them)" % (skipped, "" if skipped == 1 else "s")] if skipped else [])


def make_plan(kb, changes, trigger, notes=(), pages=None):
    notes = list(notes)
    if pages is None:
        pages, more = pages_for(kb, changes)
        notes += more
    shown = {r: (sorted(p)[:MAX_FILES_SHOWN] if p is not None else "cannot compare") for r, p in sorted(changes.items())}
    for r, p in changes.items():
        if p is not None and len(p) > MAX_FILES_SHOWN:
            notes.append("%s: %d changed files, the first %d are listed" % (r, len(p), MAX_FILES_SHOWN))
    ident = hashlib.sha256(json.dumps([p["page"] for p in pages]).encode("utf-8")).hexdigest()[:12]
    return {"id": "R-" + ident, "created": datetime.datetime.now().isoformat(timespec="seconds"), "trigger": trigger, "changed": shown,
            "pages": pages, "notes": notes, "task": None, "stage_dir": None,
            "status": "stale pages found" if pages else "nothing is stale"}


def since_build(kb):
    pages, notes = build_plan.stale(kb)
    pages = [p for p in pages if not kb_gate.derived(p["page"])]
    return make_plan(kb, {}, {"kind": "since-build", "repo": None, "from": None, "to": None}, notes, pages)


# ---- the plan file and the task ---------------------------------------------------------------
def write_plan(kb, plan):
    p = os.path.join(kb, PLAN)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(plan, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, p)
    return p


def load_plan(kb):
    p = os.path.join(kb, PLAN)
    if not os.path.isfile(p):
        return None
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def instructions(kb, plan, stage_dir):
    kbp = os.path.abspath(kb)
    L = ["Refresh ONLY the stale KB pages listed below, with the Metis skills (`kb-build`, with --rebuild for the modules these pages belong to).",
         "KB folder: %s" % kbp, "Staging folder: %s" % stage_dir,
         "Do not rewrite any page that is not listed. Read the source lines each page cites, rewrite the page into the staging folder under the "
         "same relative path, and keep an [E: ...] source tag on every statement. What no source shows becomes a question "
         "(python3 <metis>/tools/questions.py add). Never write into the KB folder itself.", "", "Stale pages (%d):" % len(plan["pages"])]
    for p in plan["pages"]:
        L.append("- %s (%s)" % (p["page"], "; ".join(p["reasons"][:3])))
    L += ["", "When the pages are written:",
          "  python3 <metis>/tools/verify_kb.py   (check the staged pages against their sources)",
          "  python3 <metis>/tools/kb_gate.py propose \"%s\" --batch refresh --from \"%s\"   (stages them in _PENDING for a lead)" % (kbp, stage_dir),
          "  python3 <metis>/tools/ui/tasks.py complete \"%s\" <task id> --by \"<your name>\" --note \"<pages refreshed, pages skipped and why>\"" % kbp,
          "If the gate is not locked yet, do not write into the KB: say so in the note and let the person run the normal build. "
          "A lead certifies the batch; then `build_plan.py record` is run so these pages stop showing as stale."]
    return "\n".join(L)


def create_task(kb, plan, by):
    """Queue one build-stage task for the plan's pages (ui/tasks.py format). Returns the task, or the existing one for the same pages."""
    import tasks
    if not plan["pages"]:
        raise RefreshError("no stale pages, so there is nothing to queue")
    ref = plan["id"]
    for t in tasks.all_tasks(kb):
        if t.get("ref") == ref and t.get("status") in ("queued", "running", "waiting-user"):
            plan["task"], plan["status"] = t["id"], "task already %s" % t["status"]
            return t
    stage_dir = build_plan.new_run(kb, "refresh")
    t = tasks.create(kb, "build-stage", "Refresh %d stale page%s (%s)" % (len(plan["pages"]), "" if len(plan["pages"]) == 1 else "s", ref),
                     instructions(kb, plan, stage_dir), clean(by) or "refresh_trigger", ref=ref, stage="refresh")
    plan.update(task=t["id"], stage_dir=stage_dir.replace(os.sep, "/"), status="task queued")
    return t


def run_plan(kb, changes, trigger, notes=(), pages=None, task=False, by=None, write=True):
    plan = make_plan(kb, changes, trigger, notes, pages)
    with WORK:
        if task and plan["pages"]:
            create_task(kb, plan, by)
        if write:
            write_plan(kb, plan)
    return plan


# ---- the webhook listener ---------------------------------------------------------------------
def sign(secret, body):
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def signature_ok(secret, body, headers):
    given = headers.get("X-Hub-Signature") or headers.get("X-Metis-Signature") or ""
    return bool(secret) and bool(given) and hmac.compare_digest(sign(secret, body), given.strip())


def handle(kb, secret, body, headers, branches=(), task=False, by=None):
    """(status code, JSON-able reply) for one webhook request. Unsigned or wrongly signed requests get 401 and are not parsed."""
    if not signature_ok(secret, body, headers):
        return 401, {"error": "missing or wrong signature"}
    event = headers.get("X-Event-Key") or ""
    if event and event not in PUSH_EVENTS:
        return 200, {"ignored": "event %s is not a push" % event[:40]}
    try:
        data = json.loads(body.decode("utf-8"))
        changes, trigger, notes = from_payload(kb, data, tuple(branches))
    except (ValueError, UnicodeDecodeError) as err:
        return 400, {"error": str(err)[:200]}
    if not changes and not trigger["branches"]:
        return 200, {"ignored": "no branch push to look at", "notes": notes}
    plan = run_plan(kb, changes, trigger, notes, task=task, by=by or "webhook")
    return 202, {"plan": plan["id"], "pages": len(plan["pages"]), "task": plan["task"], "status": plan["status"]}


def make_server(kb, secret, host="127.0.0.1", port=8766, branches=(), task=False, by=None):
    if not secret:
        raise RefreshError("no shared secret: set the environment variable named by --secret-env before starting the listener")

    class H(BaseHTTPRequestHandler):
        server_version = "MetisRefresh"

        def log_message(self, fmt, *a):
            sys.stderr.write("refresh webhook: " + fmt % a + "\n")

        def send_json(self, code, obj):
            data = json.dumps(obj).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self.send_json(405, {"error": "POST /webhook"})

        def do_POST(self):
            if self.path.split("?")[0].rstrip("/") != "/webhook":
                return self.send_json(404, {"error": "not found"})
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = 0
            if n > MAX_BODY:
                return self.send_json(413, {"error": "too large"})
            body = self.rfile.read(n) if n > 0 else b""
            try:
                code, reply = handle(kb, secret, body, self.headers, branches, task, by)
            except Exception as err:  # a bad request must never take the listener down
                sys.stderr.write("refresh webhook error: %r\n" % err)
                code, reply = 500, {"error": "could not make the plan"}
            self.send_json(code, reply)

    return HTTPServer((host, port), H)


# ---- schedule helper --------------------------------------------------------------------------
def schedule_lines(kb, every="daily", at="02:00", day="mon", by="Metis schedule"):
    """Printable lines for cron, Windows Task Scheduler and a Devin schedule. Installs nothing."""
    m = re.match(r"^([01]?\d|2[0-3]):([0-5]\d)$", at or "")
    if not m:
        raise RefreshError("--at must look like 02:00")
    if every not in ("hourly", "daily", "weekly"):
        raise RefreshError("--every must be hourly, daily or weekly")
    if every == "weekly" and day.lower()[:3] not in DAYS:
        raise RefreshError("--day must be one of %s" % ", ".join(DAYS))
    hh, mm, day = int(m.group(1)), int(m.group(2)), day.lower()[:3]
    tool = os.path.abspath(__file__)
    kbp = os.path.abspath(kb)
    args = ["plan", kbp, "--since-build", "--task", "--by", by]
    posix = "python3 %s %s" % (shlex.quote(tool), " ".join(shlex.quote(a) for a in args))
    win_inner = 'python "%s" %s' % (tool, " ".join('"%s"' % a if " " in a or "\\" in a else a for a in args))
    when = {"hourly": "every hour at minute %02d" % mm, "daily": "every day at %02d:%02d" % (hh, mm),
            "weekly": "every week on %s at %02d:%02d" % (day.capitalize(), hh, mm)}[every]
    cron = {"hourly": "%d * * * *" % mm, "daily": "%d %d * * *" % (mm, hh), "weekly": "%d %d * * %s" % (mm, hh, CRON_DAY[day])}[every]
    win = {"hourly": "/SC HOURLY /MO 1 /ST 00:%02d" % mm, "daily": "/SC DAILY /ST %02d:%02d" % (hh, mm),
           "weekly": "/SC WEEKLY /D %s /ST %02d:%02d" % (day.upper(), hh, mm)}[every]
    return {"when": when,
            "cron": "%s %s" % (cron, posix),
            "windows": 'schtasks /Create %s /TN "Metis refresh" /TR "%s"' % (win, win_inner.replace('"', '\\"')),
            "devin": ("Devin schedule, %s: run `%s`, then claim the queued task with the metis-tasks skill and refresh only its pages. "
                      "(Wording only; the Devin schedule screen is yours to fill in. Needs your Devin to verify.)" % (when, posix))}


# ---- cli --------------------------------------------------------------------------------------
def describe(plan):
    L = ["%s: %s" % (plan["id"], plan["status"])]
    t = plan["trigger"]
    L.append("trigger: %s%s" % (t["kind"], " repo %s" % t["repo"] if t.get("repo") else ""))
    for r, p in plan["changed"].items():
        L.append("changed in %s: %s" % (r, p if isinstance(p, str) else "%d file%s" % (len(p), "" if len(p) == 1 else "s")))
    for p in plan["pages"]:
        L.append("%s\t%s" % (p["page"], "; ".join(p["reasons"][:3])))
    L += ["note: " + n for n in plan["notes"]]
    L.append("%d stale page%s%s" % (len(plan["pages"]), "" if len(plan["pages"]) == 1 else "s", "; task %s" % plan["task"] if plan["task"] else ""))
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("plan"); a.add_argument("kb")
    src = a.add_mutually_exclusive_group(required=True)
    src.add_argument("--files", nargs="+"); src.add_argument("--git", nargs=3, metavar=("REPO", "FROM", "TO"))
    src.add_argument("--payload"); src.add_argument("--env", action="store_true"); src.add_argument("--since-build", action="store_true")
    a.add_argument("--repo"); a.add_argument("--branch", action="append", default=[])
    a.add_argument("--task", action="store_true"); a.add_argument("--by", default="refresh_trigger"); a.add_argument("--no-write", action="store_true")
    a = sub.add_parser("show"); a.add_argument("kb")
    a = sub.add_parser("serve-webhook"); a.add_argument("kb"); a.add_argument("--host", default="127.0.0.1")
    a.add_argument("--port", type=int, default=8766); a.add_argument("--secret-env"); a.add_argument("--branch", action="append", default=[])
    a.add_argument("--task", action="store_true"); a.add_argument("--by", default="webhook")
    a = sub.add_parser("schedule"); a.add_argument("kb"); a.add_argument("--every", default="daily"); a.add_argument("--at", default="02:00")
    a.add_argument("--day", default="mon"); a.add_argument("--by", default="Metis schedule")
    args = ap.parse_args(argv)
    kb = os.path.abspath(args.kb)
    try:
        if args.cmd == "plan":
            changes, notes = {}, []
            if args.since_build:
                plan = since_build(kb)
                if args.task and plan["pages"]:
                    create_task(kb, plan, args.by)
                if not args.no_write:
                    write_plan(kb, plan)
            else:
                if args.files:
                    trig = {"kind": "files", "repo": args.repo, "from": None, "to": None}
                    for r, p in split_files(kb, args.files, args.repo).items():
                        add_changes(changes, r, p)
                elif args.git:
                    repo = kb_repo_name(kb, args.git[0])
                    paths, note = git_changed(kb, repo, args.git[1], args.git[2])
                    add_changes(changes, repo, paths)
                    notes += [note] if note else []
                    trig = {"kind": "git", "repo": repo, "from": args.git[1], "to": args.git[2]}
                elif args.payload:
                    raw = sys.stdin.read() if args.payload == "-" else open(args.payload, encoding="utf-8").read()
                    changes, trig, notes = from_payload(kb, json.loads(raw), tuple(args.branch))
                else:
                    changes, trig, notes = from_env(kb, os.environ)
                plan = run_plan(kb, changes, trig, notes, task=args.task, by=args.by, write=not args.no_write)
            print(describe(plan))
            if not args.no_write:
                print("plan written to %s" % PLAN.replace(os.sep, "/"))
        elif args.cmd == "show":
            plan = load_plan(kb)
            print(describe(plan) if plan else "no refresh plan yet")
        elif args.cmd == "schedule":
            s = schedule_lines(kb, args.every, args.at, args.day, args.by)
            print("Runs %s. Nothing is installed; copy the line you want.\n\ncron:\n%s\n\nWindows Task Scheduler:\n%s\n\n%s" % (
                s["when"], s["cron"], s["windows"], s["devin"]))
        else:
            env = args.secret_env or settings(kb).get("secret_env") or DEFAULT_SECRET_ENV
            if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", env):
                raise RefreshError("--secret-env is the NAME of an environment variable, never the secret")
            secret = os.environ.get(env)
            if args.host not in LOOPBACK:
                print("warning: listening on %s; put it behind your own TLS proxy, the secret signs requests but does not encrypt them" % args.host,
                      file=sys.stderr)
            branches = tuple(args.branch) or tuple(as_list(settings(kb).get("branches")))
            srv = make_server(kb, secret, args.host, args.port, branches, args.task, args.by)
            print("listening on http://%s:%d/webhook (secret from %s; %s)" % (args.host, srv.server_address[1], env,
                                                                             "queues a task" if args.task else "writes the plan only"))
            try:
                srv.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                srv.server_close()
    except (RefreshError, ValueError) as err:
        print("error: %s" % err, file=sys.stderr)
        return 2
    return 0


def as_list(v):
    return [clean(x) for x in (v if isinstance(v, (list, tuple)) else [v]) if clean(x)] if v else []


if __name__ == "__main__":
    sys.exit(main())
