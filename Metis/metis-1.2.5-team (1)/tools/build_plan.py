#!/usr/bin/env python3
"""Plan an incremental rebuild, and keep run folders and checkpoints so a long build can resume.

    python3 build_plan.py record <kb>                 remember each source repo's commit as of this build (<kb>/.metis/built-from.yaml)
    python3 build_plan.py stale  <kb> [--json]        KB pages whose cited source files changed since then; only these are rebuilt
    python3 build_plan.py run    <kb> <name>          make a new run folder <kb>/_REGEN/<date>-<name>[-2...]; prints its path
    python3 build_plan.py done   <run folder> <stage>  mark a stage finished
    python3 build_plan.py next   <run folder> <stage> [<stage> ...]   first listed stage not yet finished (blank when all are)

`stale` reads the [E: <repo>/<path>:<line>] tags in every KB page, asks git (`git diff --name-only <built commit> HEAD`) which
files changed in each repo, and lists the pages that cite one. A page with no source-repo tags is never stale here (documents
and answers have their own re-sync). If a repo has no recorded commit, or the recorded commit is gone (a shallow clone, a
force push), the repo is listed as "cannot compare" and every page citing it is stale. Git is only ever read.
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import verify_kb  # noqa: E402

STATE = os.path.join(".metis", "built-from.yaml")
SKIP = (".git", "_EVIDENCE", ".metis", "Archive", "_REGEN", "_PENDING", "_FEEDBACK", "_QUESTIONS")
CITE = re.compile(r"^([^:\s/]+)/([^:\s]+):\d+(?:-\d+)?(?:\s+\".*\")?$")


def git(repo, *args):
    r = subprocess.run(["git", "-C", repo] + list(args), capture_output=True, text=True, timeout=120)
    return r.returncode, r.stdout


def repo_dirs(kb):
    chk = verify_kb.Checker(kb)
    out = {}
    for name in chk.repos:
        path, err = chk.repo_path(name + "/x")
        if not err:
            out[name] = os.path.dirname(path)
    return out


def record(kb):
    state = {"recorded_on": datetime.date.today().isoformat(), "repos": {}}
    for name, d in repo_dirs(kb).items():
        code, out = git(d, "rev-parse", "HEAD")
        if code == 0 and out.strip():
            state["repos"][name] = out.strip()
    os.makedirs(os.path.join(kb, ".metis"), exist_ok=True)
    with open(os.path.join(kb, STATE), "w", encoding="utf-8", newline="\n") as fh:
        yaml.safe_dump(state, fh, sort_keys=True)
    return state["repos"]


def cited_files(kb):
    """{page: {repo: {path, ...}}} from the source-repo tags in each KB page."""
    out = {}
    for d, dirs, fs in os.walk(kb):
        dirs[:] = [x for x in dirs if x not in SKIP]
        for f in fs:
            if not f.endswith((".md", ".yaml", ".yml")):
                continue
            rel = os.path.relpath(os.path.join(d, f), kb).replace(os.sep, "/")
            with open(os.path.join(d, f), encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            for kind, value in verify_kb.TAG.findall(text):
                if kind != "E":
                    continue
                for part in value.split(";"):
                    m = CITE.match(part.strip())
                    if m:
                        out.setdefault(rel, {}).setdefault(m.group(1), set()).add(m.group(2))
    return out


def changed_since_build(kb):
    """({repo: set of changed paths, or None when it cannot be compared}, notes), against the commits recorded at the last build."""
    built = {}
    p = os.path.join(kb, STATE)
    if os.path.isfile(p):
        with open(p, encoding="utf-8") as fh:
            built = (yaml.safe_load(fh) or {}).get("repos") or {}
    changed, notes = {}, []
    for name, d in repo_dirs(kb).items():
        old = built.get(name)
        if not old:
            changed[name] = None
            notes.append("%s: no commit recorded, so every page citing it is listed" % name)
            continue
        code, out = git(d, "diff", "--name-only", old, "HEAD")
        if code != 0:
            changed[name] = None
            notes.append("%s: commit %s is not in the clone, so every page citing it is listed" % (name, old[:8]))
            continue
        changed[name] = {x.strip() for x in out.splitlines() if x.strip()}
    return changed, notes


def stale(kb):
    """([{page, reasons}], notes). Pages that cite a source file that changed, or a repo that cannot be compared."""
    changed, notes = changed_since_build(kb)
    result = []
    for page, repos in sorted(cited_files(kb).items()):
        reasons = []
        for repo, paths in sorted(repos.items()):
            if repo not in changed:
                continue
            if changed[repo] is None:
                reasons.append("%s: cannot compare" % repo)
                continue
            reasons += ["%s/%s changed" % (repo, path) for path in sorted(paths) if path in changed[repo]]
        if reasons:
            result.append({"page": page, "reasons": reasons})
    return result, notes


def new_run(kb, name):
    base = "%s-%s" % (datetime.date.today().isoformat(), re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "run")
    root = os.path.join(kb, "_REGEN")
    run, n = base, 1
    while os.path.exists(os.path.join(root, run)):
        n += 1
        run = "%s-%d" % (base, n)
    os.makedirs(os.path.join(root, run))
    return os.path.join(root, run)


def finished(run):
    p = os.path.join(run, "CHECKPOINT.yaml")
    if not os.path.isfile(p):
        return []
    with open(p, encoding="utf-8") as fh:
        return (yaml.safe_load(fh) or {}).get("done") or []


def mark(run, stage):
    d = finished(run)
    if stage not in d:
        d.append(stage)
    with open(os.path.join(run, "CHECKPOINT.yaml"), "w", encoding="utf-8", newline="\n") as fh:
        yaml.safe_dump({"done": d, "updated": datetime.datetime.now().isoformat(timespec="seconds")}, fh, sort_keys=False)


def next_stage(run, stages):
    d = set(finished(run))
    return next((s for s in stages if s not in d), "")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("record"); a.add_argument("kb")
    a = sub.add_parser("stale"); a.add_argument("kb"); a.add_argument("--json", action="store_true")
    a = sub.add_parser("run"); a.add_argument("kb"); a.add_argument("name")
    a = sub.add_parser("done"); a.add_argument("run"); a.add_argument("stage")
    a = sub.add_parser("next"); a.add_argument("run"); a.add_argument("stages", nargs="+")
    args = ap.parse_args(argv)
    if args.cmd == "record":
        r = record(os.path.abspath(args.kb))
        print("recorded %d repos in %s" % (len(r), STATE.replace(os.sep, "/")))
    elif args.cmd == "stale":
        pages, notes = stale(os.path.abspath(args.kb))
        if args.json:
            print(json.dumps({"stale": pages, "notes": notes}, indent=2))
        else:
            for n in notes:
                print("note: " + n)
            for p in pages:
                print("%s\t%s" % (p["page"], "; ".join(p["reasons"][:3])))
            print("%d pages to rebuild" % len(pages))
    elif args.cmd == "run":
        print(new_run(os.path.abspath(args.kb), args.name))
    elif args.cmd == "done":
        mark(args.run, args.stage)
    else:
        print(next_stage(args.run, args.stages))
    return 0


if __name__ == "__main__":
    sys.exit(main())
