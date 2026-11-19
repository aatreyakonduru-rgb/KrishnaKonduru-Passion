#!/usr/bin/env python3
"""Feedback on the framework itself: after a gate brief or an artefact, one line from the person who read it.

Kept in docs/knowledge-base/SHARED/framework-feedback.yaml, never in Jira. A new line is shown
first and written only with --write, after the person types "approved". The Tech Lead's Framework feedback tab
reads summary().

Argus's Feedback form, and the problems Argus notices about itself, arrive as a
SDLC-WORKBENCH-FEEDBACK v1 block. import writes it as one new file per send under
SHARED/workbench-feedback/<YYYY>/<MM>/, so two people's sends never touch the same file. The Leads
dashboard reads them with noticed_summary() (Argus noticed tab) and form_feedback() (Team feedback tab).

    framework_feedback.py add --by NAME --on WHAT --useful yes|no [--note TEXT] [--write]
    framework_feedback.py summary
    framework_feedback.py import --block FILE [--write]
"""
import argparse
import datetime
import glob
import json
import os
import re
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
PATH = os.path.join(ROOT, "docs", "knowledge-base", "SHARED", "framework-feedback.yaml")
BATCH_DIR = os.path.join(ROOT, "docs", "knowledge-base", "SHARED", "workbench-feedback")
BLOCK = "SDLC-WORKBENCH-FEEDBACK"
BATCH_ID = re.compile(r"^\d{8}-\d{4}-[0-9a-f]{6}$")
# Numbers shaped like an SSN or a long member/claim id are taken out before anything is written.
IDENTIFIERS = re.compile(r"\b\d{3}-\d{2}-\d{4}\b|\b[A-Z]{0,3}\d{9,}\b")
QUESTION = "Was this useful? Yes or no, and one line on why (or skip)."


def load(path=PATH):
    if not os.path.exists(path):
        return {"feedback": []}
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    data.setdefault("feedback", [])
    return data


def add(data, by, on, useful, note="", today=None):
    if useful not in ("yes", "no"):
        raise ValueError("useful is yes or no")
    if not by or not on:
        raise ValueError("give who (--by) and what it is about (--on)")
    entry = {"date": (today or datetime.date.today()).isoformat(), "by": by, "on": on, "useful": useful,
             "note": (note or "").strip()[:300]}
    data["feedback"].append(entry)
    return entry


def summary(data):
    """Per thing: how many said yes and no, and the latest notes, the least useful first."""
    out = {}
    for e in data.get("feedback") or []:
        row = out.setdefault(e["on"], {"on": e["on"], "yes": 0, "no": 0, "notes": []})
        row[e["useful"]] += 1
        if e.get("note"):
            row["notes"].append("%s (%s): %s" % (e["by"], e["date"], e["note"]))
    return sorted(out.values(), key=lambda r: (-r["no"], r["on"]))


def _scrub(value):
    if isinstance(value, str):
        return IDENTIFIERS.sub("<removed>", value)
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items()}
    return value


def parse_block(text):
    """Argus's block -> its batch, checked. Raises ValueError with what is wrong."""
    text = (text or "").strip()
    first, _, rest = text.partition("\n")
    if first.strip().lstrip("#").strip() != BLOCK + " v1":
        raise ValueError("this is not a %s v1 block" % BLOCK)
    try:
        body = json.loads(rest)
    except ValueError as exc:
        raise ValueError("the block's body is not the JSON Argus writes: %s" % exc)
    if not isinstance(body, dict) or not BATCH_ID.match(str(body.get("batch", ""))):
        raise ValueError("the block has no batch id like 20261024-2010-a1b2c3")
    for key in ("feedback", "noticed"):
        if not isinstance(body.get(key, []), list):
            raise ValueError("%s must be a list" % key)
    if not body.get("feedback") and not body.get("noticed"):
        raise ValueError("the block has no feedback and no noticed problems")
    return _scrub(body)


def batch_path(body, base=BATCH_DIR):
    b = body["batch"]
    return os.path.join(base, b[:4], b[4:6], b + ".yaml")


def import_block(text, write=False, base=BATCH_DIR):
    """-> (path, batch). Writes the one new file only with write; never overwrites an earlier send."""
    body = parse_block(text)
    path = batch_path(body, base)
    if os.path.exists(path):
        raise ValueError("batch %s is already in %s" % (body["batch"], os.path.relpath(path, ROOT)))
    if write:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("# Sent from Argus (Feedback form and the problems it noticed). One file per send.\n")
            yaml.safe_dump(body, fh, sort_keys=False, allow_unicode=True, width=110)
    return path, body


def load_batches(base=BATCH_DIR):
    out = []
    for path in sorted(glob.glob(os.path.join(base, "*", "*", "*.yaml"))):
        try:
            with open(path, encoding="utf-8") as fh:
                body = yaml.safe_load(fh) or {}
        except (OSError, yaml.YAMLError):
            continue
        if isinstance(body, dict) and body.get("batch"):
            out.append(body)
    return out


def noticed_summary(batches):
    """One row per kind of problem across every send: how often, how many people, which roles, first and last
    seen, the suggested fix and the latest thing seen. Most often first."""
    rows = {}
    for b in batches:
        for n in b.get("noticed") or []:
            key = n.get("sig") or "%s|%s" % (n.get("where"), n.get("title"))
            row = rows.setdefault(key, {"title": n.get("title", ""), "where": n.get("where", ""), "fix": n.get("fix", ""),
                                        "count": 0, "people": set(), "roles": set(), "first": n.get("first", ""),
                                        "last": "", "detail": ""})
            row["count"] += int(n.get("count") or 1)
            if b.get("by"):
                row["people"].add(b["by"])
            if b.get("role"):
                row["roles"].add(b["role"])
            row["first"] = min(row["first"] or n.get("first", ""), n.get("first", "") or row["first"])
            if n.get("last", "") >= row["last"]:
                row["last"], row["detail"] = n.get("last", ""), n.get("detail", "")
    out = [dict(r, people=len(r["people"]), roles=sorted(r["roles"])) for r in rows.values()]
    return sorted(out, key=lambda r: (-r["count"], -r["people"], r["title"]))


def form_feedback(batches):
    """What people sent from the Feedback form, newest first, each with the session details it was sent with."""
    rows = [dict(f, batch=b.get("batch"), workbench=b.get("workbench") or {}) for b in batches
            for f in b.get("feedback") or []]
    return sorted(rows, key=lambda r: r.get("at", ""), reverse=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("--by", required=True)
    a.add_argument("--on", required=True)
    a.add_argument("--useful", required=True, choices=["yes", "no"])
    a.add_argument("--note", default="")
    a.add_argument("--write", action="store_true")
    sub.add_parser("summary")
    i = sub.add_parser("import", help="write a SDLC-WORKBENCH-FEEDBACK v1 block as one new file")
    i.add_argument("--block", required=True)
    i.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd == "import":
        with open(args.block, encoding="utf-8") as fh:
            text = fh.read()
        try:
            path, body = import_block(text, write=args.write)
        except ValueError as exc:
            print("refused: %s" % exc)
            return 2
        print("%s: %d feedback, %d noticed problems from %s (%s)" % (
            os.path.relpath(path, ROOT), len(body.get("feedback") or []), len(body.get("noticed") or []),
            body.get("by") or "Argus", body.get("role") or "no role"))
        for f in body.get("feedback") or []:
            print("  - %s about %s: %s" % (f.get("kind"), f.get("about"), (f.get("text") or "")[:120]))
        for n in body.get("noticed") or []:
            print("  - noticed x%s: %s" % (n.get("count"), n.get("title")))
        print("written" if args.write else "Preview only: run again with --write.")
        return 0
    data = load()
    if args.cmd == "summary":
        print(json.dumps(summary(data), indent=1))
        return 0
    print(yaml.safe_dump(add(data, args.by, args.on, args.useful, args.note), sort_keys=False))
    if not args.write:
        print("Preview only: run again with --write after they say approved.")
        return 0
    with open(PATH, "w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, sort_keys=False, allow_unicode=True)
    print("written to %s" % os.path.relpath(PATH, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
