#!/usr/bin/env python3
"""Architecture Decision Records (ADRs) for Acme Claims — create, list, check, accept, supersede, index.

An ADR is a short dated note: what we decided, why, what we turned down, who signed off.
Records live in docs/knowledge-base/DECISIONS/ as ADR-NNNN-<slug>.md and the
README.md there is a generated index. Nothing here decides anything — it files what people decided.

    python3 adr.py new "Keep contract grid on server-side paging" --req REQ-12 --deciders "Resource 3"
    python3 adr.py list
    python3 adr.py check [ADR-0001 ...]          # structure + tag rules; exit 1 on problems
    python3 adr.py accept ADR-0001 --by "Resource 3"
    python3 adr.py supersede ADR-0001 --by ADR-0004
    python3 adr.py index                         # rewrite DECISIONS/README.md
"""
import argparse
import datetime
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gates  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
ADR_DIR = os.path.join(ROOT, "docs", "knowledge-base", "DECISIONS")
TEMPLATE = os.path.join(ROOT, ".devin", "templates", "adr.md")
STATUSES = ("Proposed", "Accepted", "Rejected", "Superseded", "Deprecated")
SECTIONS = ("Context", "Decision", "Options considered", "Consequences", "Sources read",
            "Open questions", "Assumptions", "Don't know")
FILE_RE = re.compile(r"^ADR-(\d{4})-[a-z0-9-]+\.md$")
FIELD_RE = re.compile(r"^\|\s*([^|]+?)\s*\|\s*(.*?)\s*\|\s*$")


def adr_dir():
    return os.environ.get("SDLC_ADR_DIR", ADR_DIR)


def slugify(title):
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", title.lower())).strip("-")[:60] or "decision"


def records(directory=None):
    directory = directory or adr_dir()
    if not os.path.isdir(directory):
        return []
    return sorted(os.path.join(directory, f) for f in os.listdir(directory) if FILE_RE.match(f))


def resolve(ref, directory=None):
    """ADR-0003, 3, 0003 or a path -> the file path."""
    if os.path.isfile(ref):
        return ref
    m = re.search(r"(\d+)", ref)
    if m:
        prefix = "ADR-%04d-" % int(m.group(1))
        for path in records(directory):
            if os.path.basename(path).startswith(prefix):
                return path
    raise SystemExit("no ADR matches %r" % ref)


def parse(path):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    title_m = re.search(r"^# (ADR-\d{4}): (.+)$", text, re.M)
    fields = {}
    for line in text.splitlines():
        if line.startswith("## "):
            break
        m = FIELD_RE.match(line)
        if m and m.group(1) not in ("Field", "---"):
            fields[m.group(1)] = m.group(2)
    sections, current = {}, None
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = []
        elif current:
            sections[current].append(line)
    return {"path": path, "text": text, "id": title_m.group(1) if title_m else None,
            "title": title_m.group(2).strip() if title_m else None, "fields": fields,
            "sections": {k: "\n".join(v).strip() for k, v in sections.items()}}


def _placeholder(value):
    return not value or bool(re.search(r"\{[^}]+\}", value))


def list_items(body):
    """Bullet items that are real content, not template placeholders."""
    return [ln for ln in body.splitlines() if ln.strip().startswith("- ") and not _placeholder(ln)]


def check(path):
    rec = parse(path)
    problems = []
    if not rec["id"]:
        problems.append("title line must be '# ADR-NNNN: <title>'")
    status = rec["fields"].get("Status", "")
    if status not in STATUSES:
        problems.append("Status %r is not one of %s" % (status, ", ".join(STATUSES)))
    try:
        datetime.date.fromisoformat(rec["fields"].get("Date", ""))
    except ValueError:
        problems.append("Date must be YYYY-MM-DD")
    for name in SECTIONS:
        if name not in rec["sections"]:
            problems.append("missing section '## %s'" % name)
    for name in ("Context", "Decision"):
        body = rec["sections"].get(name, "")
        if not body or _placeholder(body.splitlines()[0]) or body.startswith("What "):
            problems.append("section '%s' is still the template text" % name)
    if not list_items(rec["sections"].get("Sources read", "")):
        problems.append("'Sources read' lists nothing — an ADR must say what it was based on")
    body_text = "\n".join(v for k, v in rec["sections"].items() if k not in ("Assumptions", "Don't know"))
    if "[A]" in body_text and not list_items(rec["sections"].get("Assumptions", "")):
        problems.append("text uses [A] but 'Assumptions' lists nothing")
    if "[?]" in body_text and not list_items(rec["sections"].get("Don't know", "")):
        problems.append("text uses [?] but 'Don't know' lists nothing")
    if status == "Accepted":
        deciders = rec["fields"].get("Deciders", "")
        if _placeholder(deciders) or not deciders.strip():
            problems.append("Accepted ADR must name its deciders")
    if status == "Superseded" and not re.search(r"ADR-\d{4}", rec["fields"].get("Superseded by", "")):
        problems.append("Superseded ADR must say which ADR replaced it")
    return rec, problems


def next_number(directory=None):
    nums = [int(FILE_RE.match(os.path.basename(p)).group(1)) for p in records(directory)]
    return (max(nums) + 1) if nums else 1


def create(title, req=None, jira=None, deciders=None, directory=None, today=None):
    directory = directory or adr_dir()
    os.makedirs(directory, exist_ok=True)
    num = next_number(directory)
    with open(TEMPLATE, encoding="utf-8") as fh:
        text = fh.read()
    text = (text.replace("{NNNN}", "%04d" % num).replace("{Title}", title)
                .replace("{YYYY-MM-DD}", (today or datetime.date.today()).isoformat()))
    if req:
        text = text.replace("{REQ-ID STORY-ID, or none}", req)
    if jira:
        text = text.replace("{ACME-nnnn, or none}", jira)
    if deciders:
        text = text.replace("{named people from .devin/rules/people.yaml}", deciders)
    path = os.path.join(directory, "ADR-%04d-%s.md" % (num, slugify(title)))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def set_field(path, field, value):
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    for i, line in enumerate(lines):
        m = FIELD_RE.match(line)
        if m and m.group(1) == field:
            lines[i] = "| %s | %s |" % (field, value)
            break
    else:
        raise SystemExit("%s has no '%s' field" % (path, field))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def accept(ref, by, directory=None, roster=None):
    path = resolve(ref, directory)
    person = gates.find_person(by, roster)
    if not person:
        raise SystemExit("%r is not on .devin/rules/people.yaml — an ADR is accepted by a named person" % by)
    rec = parse(path)
    deciders = rec["fields"].get("Deciders", "")
    names = [person["name"]] if _placeholder(deciders) else [d.strip() for d in deciders.split(";") if d.strip()]
    if person["name"] not in names:
        names.append(person["name"])
    set_field(path, "Deciders", "; ".join(names))
    set_field(path, "Status", "Accepted")
    return path


def supersede(old_ref, new_ref, directory=None):
    old, new = resolve(old_ref, directory), resolve(new_ref, directory)
    old_id, new_id = parse(old)["id"], parse(new)["id"]
    set_field(old, "Status", "Superseded")
    set_field(old, "Superseded by", new_id)
    set_field(new, "Supersedes", old_id)
    return old, new


def render_index(directory=None):
    rows = [parse(p) for p in records(directory)]
    out = ["# Acme Claims Architecture Decision Records", "",
           "Generated by `sdlc/framework/tools/adr.py index` — do not edit by hand.", "",
           "An ADR is a short, dated note of one design decision: what we decided, why, which options we",
           "turned down, and who signed off. Create one with `/adr \"<decision>\"`.", ""]
    if not rows:
        out.append("No decisions recorded yet.")
    else:
        out += ["| ADR | Title | Status | Date | Deciders |", "|---|---|---|---|---|"]
        for r in rows:
            f = r["fields"]
            out.append("| [%s](%s) | %s | %s | %s | %s |" % (
                r["id"], os.path.basename(r["path"]), r["title"], f.get("Status", ""), f.get("Date", ""),
                "" if _placeholder(f.get("Deciders")) else f.get("Deciders", "")))
    return "\n".join(out) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("new")
    p.add_argument("title")
    p.add_argument("--req")
    p.add_argument("--jira")
    p.add_argument("--deciders")
    sub.add_parser("list")
    p = sub.add_parser("check")
    p.add_argument("refs", nargs="*")
    p = sub.add_parser("accept")
    p.add_argument("ref")
    p.add_argument("--by", required=True)
    p = sub.add_parser("supersede")
    p.add_argument("ref")
    p.add_argument("--by", required=True, help="the ADR that replaces it")
    sub.add_parser("index")
    args = parser.parse_args(argv)

    if args.command == "new":
        print(create(args.title, req=args.req, jira=args.jira, deciders=args.deciders))
    elif args.command == "list":
        for path in records():
            r = parse(path)
            print("%s  %-10s %s  %s" % (r["id"], r["fields"].get("Status", ""), r["fields"].get("Date", ""), r["title"]))
    elif args.command == "check":
        paths = [resolve(r) for r in args.refs] or records()
        bad = 0
        for path in paths:
            _, problems = check(path)
            print("%s %s" % ("FAIL" if problems else "OK  ", os.path.relpath(path, ROOT)))
            for pr in problems:
                print("     - " + pr)
            bad += bool(problems)
        return 1 if bad else 0
    elif args.command == "accept":
        print(accept(args.ref, args.by))
    elif args.command == "supersede":
        print("\n".join(supersede(args.ref, args.by)))
    elif args.command == "index":
        os.makedirs(adr_dir(), exist_ok=True)
        path = os.path.join(adr_dir(), "README.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(render_index())
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
