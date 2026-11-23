#!/usr/bin/env python3
"""Time-aware facts: which line of the KB was true on a given date, and what has expired.

    python3 facts_time.py build   <kb>                       write <kb>/.metis/facts.sqlite from the pages
    python3 facts_time.py as-of   <kb> <YYYY-MM-DD> [--all]   dated lines that were valid on that date (--all adds undated lines)
    python3 facts_time.py history <kb> <object>               every line that mentions the object (or sits on that page), oldest first
    python3 facts_time.py expired <kb> [--today YYYY-MM-DD]   valid-to has passed and nothing supersedes the line
    python3 facts_time.py page-at <kb> <rev> <path>           the whole page as it was at a git revision (`git show`)

The markdown page format does not change. A line may carry an optional annotation AFTER its [E: ...] tag:

    - Claims are paid within 30 days [E: file:rules.txt "30 days"] {valid-from: 2026-03-01; valid-to: 2026-09-30; superseded-by: context/rules-v2.md:14}

Keys (all optional, `;` between them, ISO dates only; `_` may be written for `-`):
    valid-from     first day the line is true            (also written `as-of` or `as of`: true as of that day)
    valid-to       last day the line is true (inclusive) (also written `valid-until`)
    superseded-by  a KB page (the page replaces this line) or a fact id `<kb path>:<line>`

A `{...}` group whose keys are not in this list is ignored, so `{env: prod; sensitivity: restricted}` (claim_labels.py) can sit
beside it on the same line. verify_kb.py is unaffected: its tag pattern only looks inside `[...]`.

A line is valid on date D when valid-from <= D (if given) and D <= its end (if given). The end is valid-to, else, when
superseded-by names a line or page that has a valid-from, the day before that valid-from. A superseded line whose end cannot be worked
out is reported as "superseded (end unknown)" and is not valid. A line with no annotation is always valid and is left out of `as-of`
unless --all is given.

Section annotations. The same group on a Markdown heading applies to every fact line under it, down to the next heading of the same or a
higher level (a `##` section ends at the next `##` or `#`; its `###` subsections are inside it and inherit it):

    ## Claim rules {as of: 2026-03-01; valid-until: 2026-09-30}
    - Claims are paid within 30 days [E: file:rules.txt "30 days"]                          <- valid 2026-03-01 .. 2026-09-30
    - Appeals take 10 days [E: file:rules.txt "10 days"] {valid-to: 2026-05-31}            <- valid-from from the heading, own valid-to

A line's own annotation overrides the section's, key by key: a key the line gives wins, a key it leaves out comes from the section.
A subsection heading overrides its parent the same way. The heading line is itself a dated line. A section whose merged dates
contradict (valid-to before valid-from) is reported as a problem on the line. `as-of` rows say which heading they inherited from
(`from_section`, shown as `[section path:line]` on the command line). Text outside backticks is read; headings inside code blocks
and front matter are not.

Edges: graph_store.py is not changed. `as_of_edges(kb, date)` reads CROSS-LAYER/LINK_GRAPH.yaml and, when present, a columns file
CROSS-LAYER/edge_validity.yaml:
    edges: [{from: "table:ORDERS", rel: reads, to: "endpoint:GET /orders", valid_from: 2026-01-01, valid_to: 2026-06-30}]
(an edge in LINK_GRAPH.yaml that itself carries valid_from / valid_to is honoured too). An edge with no dates is always in force.
"""
import argparse
import datetime
import os
import re
import sqlite3
import subprocess
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import verify_kb  # noqa: E402

DB = os.path.join(".metis", "facts.sqlite")
SKIP_DIRS = ("_EVIDENCE", ".metis", "Archive", ".git", "_PENDING", "_FEEDBACK", "_REGEN", "_QUESTIONS")
KEYS = ("valid-from", "valid-to", "superseded-by")
ALIASES = {"valid-until": "valid-to", "as-of": "valid-from", "as of": "valid-from"}   # keys read as another key
ACCEPTED = KEYS + tuple(ALIASES)
HEADING = re.compile(r"^ {0,3}(#{1,6})\s+\S")
GROUP = re.compile(r"\{([^{}]*)\}")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
EDGE_COLUMNS = os.path.join("CROSS-LAYER", "edge_validity.yaml")
SCHEMA = """
create table facts (id integer primary key, path text, line integer, text text, valid_from text, valid_to text,
                    superseded_by text, annotated integer, section text);
create table problems (path text, line integer, problem text);
create index facts_path on facts(path);
"""


def parse_groups(line, allowed):
    """({key: value}, problems) from every `{k: v; k: v}` group on the line whose keys are all in `allowed`; other groups are
    skipped. Text inside backticks is ignored. Keys are lower-cased and `_` is read as `-`."""
    values, problems = {}, []
    text = re.sub(r"`[^`]*`", lambda m: " " * len(m.group(0)), line)
    for m in GROUP.finditer(text):
        pairs = []
        for part in m.group(1).split(";"):
            if not part.strip():
                continue
            k, sep, v = part.partition(":")
            pairs.append((k.strip().lower().replace("_", "-"), v.strip() if sep else ""))
        if not pairs or any(k not in allowed for k, _ in pairs):
            continue
        for k, v in pairs:
            if not v:
                problems.append("annotation key '%s' has no value" % k)
            elif k in values:
                problems.append("annotation key '%s' is given twice" % k)
            else:
                values[k] = v
    return values, problems


def _date_ok(s):
    try:
        datetime.date.fromisoformat(s)
        return bool(DATE.match(s))
    except ValueError:
        return False


def line_annotation(line):
    """({valid-from, valid-to, superseded-by} found on the line, problems). `valid-until`, `as-of` and `as of` are read as
    valid-to, valid-from and valid-from."""
    vals, problems = parse_groups(line, ACCEPTED)
    for k in [k for k in vals if k in ALIASES]:
        v, canon = vals.pop(k), ALIASES[k]
        if canon in vals:
            problems.append("annotation key '%s' is given twice (as '%s' and '%s')" % (canon, canon, k))
        else:
            vals[canon] = v
    for k in ("valid-from", "valid-to"):
        if k in vals and not _date_ok(vals[k]):
            problems.append("%s must be a date like 2026-03-01, got '%s'" % (k, vals[k]))
            del vals[k]
    if vals.get("valid-from") and vals.get("valid-to") and vals["valid-to"] < vals["valid-from"]:
        problems.append("valid-to %s is before valid-from %s" % (vals["valid-to"], vals["valid-from"]))
    return vals, problems


def parse_date(s):
    s = str(s or "").strip()
    if not _date_ok(s):
        raise ValueError("date must look like 2026-03-01, got '%s'" % s)
    return s


def db_path(kb):
    return os.path.join(kb, DB)


def _walk(text):
    """(line number, line) for every line outside front matter and code blocks."""
    in_code = in_front = False
    for n, line in enumerate(text.replace("\r\n", "\n").splitlines(), 1):
        s = line.strip()
        if n == 1 and s == "---":
            in_front = True
            continue
        if in_front:
            in_front = s != "---"
            continue
        if s.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        yield n, line


def fact_lines(text):
    """(line number, text) for lines outside front matter and code blocks that carry a source tag or a dating annotation."""
    for n, line in _walk(text):
        if verify_kb.TAG.search(line) or parse_groups(line, ACCEPTED)[0]:
            yield n, line.rstrip()


def fact_sections(text):
    """(line number, text, section values, section ref) for each fact line (as fact_lines), with the dates of the heading section it
    sits in: the nearest enclosing headings' annotations merged outermost first, so an inner heading overrides an outer one per key.
    The ref is "line N" of the heading that last set a value (None when no heading in force carries dates). A heading line gets the
    sections above it, not its own group (that is its own annotation)."""
    stack = []                                # [(level, merged values, ref)] of the headings in force
    for n, line in _walk(text):
        m = HEADING.match(line)
        above = (stack[-1][1], stack[-1][2]) if stack else ({}, None)
        if m:
            level = len(m.group(1))
            while stack and stack[-1][0] >= level:
                stack.pop()
            above = (stack[-1][1], stack[-1][2]) if stack else ({}, None)
            own = line_annotation(line)[0]
            stack.append((level, dict(above[0], **own), n if own else above[1]))
        if verify_kb.TAG.search(line) or parse_groups(line, ACCEPTED)[0]:
            yield n, line.rstrip(), above[0], above[1]


def pages(kb):
    for d, dirs, files in os.walk(kb):
        dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS)
        for f in sorted(files):
            if f.endswith(".md"):
                yield os.path.relpath(os.path.join(d, f), kb).replace(os.sep, "/")


def split_ref(ref):
    """('path', line or None) for a superseded-by value."""
    m = re.match(r"^(.*):(\d+)$", ref)
    return (m.group(1), int(m.group(2))) if m else (ref, None)


def build(kb):
    """Rebuild <kb>/.metis/facts.sqlite. Returns (lines indexed, annotated lines, problems [(path, line, text)])."""
    kb = os.path.abspath(kb)
    os.makedirs(os.path.dirname(db_path(kb)), exist_ok=True)
    if os.path.exists(db_path(kb)):
        os.remove(db_path(kb))
    con = sqlite3.connect(db_path(kb))
    con.executescript(SCHEMA)
    rows, problems, annotated = [], [], 0
    known = set(pages(kb))
    for rel in sorted(known):
        with open(os.path.join(kb, rel), encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        for n, line, inherited, sec in fact_sections(text):
            own, probs = line_annotation(line)
            sup = own.get("superseded-by")
            if sup and split_ref(sup)[0] not in known:
                probs.append("superseded-by points at %s, which is not a page in the KB" % sup)
            vals = dict(inherited, **own)                      # the line's own keys win; the rest come from the section
            if inherited and vals.get("valid-from") and vals.get("valid-to") and vals["valid-to"] < vals["valid-from"] \
                    and not (own.get("valid-from") and own.get("valid-to")):
                probs.append("valid-to %s is before valid-from %s (one of them comes from the section at line %s)" % (
                    vals["valid-to"], vals["valid-from"], sec))
            used_section = sec if inherited and any(k not in own for k in inherited) else None
            problems += [(rel, n, p) for p in probs]
            annotated += 1 if vals else 0
            rows.append((rel, n, line.strip(), vals.get("valid-from"), vals.get("valid-to"), vals.get("superseded-by"),
                         1 if vals else 0, "%s:%d" % (rel, used_section) if used_section else None))
    con.executemany("insert into facts (path, line, text, valid_from, valid_to, superseded_by, annotated, section) "
                    "values (?,?,?,?,?,?,?,?)", rows)
    con.executemany("insert into problems values (?,?,?)", problems)
    con.commit()
    con.close()
    return len(rows), annotated, problems


def connect(kb):
    kb = os.path.abspath(kb)
    if os.path.isfile(db_path(kb)):                     # an index written before section annotations has no `section` column
        old = sqlite3.connect(db_path(kb))
        try:
            stale = "section" not in [r[1] for r in old.execute("pragma table_info(facts)")]
        except sqlite3.DatabaseError:
            stale = True
        finally:
            old.close()
        if stale:
            os.remove(db_path(kb))
    if not os.path.isfile(db_path(kb)):
        build(kb)
    con = sqlite3.connect(db_path(kb))
    con.row_factory = sqlite3.Row
    return con


def fact_id(row):
    return "%s:%d" % (row["path"], row["line"])


def _superseder_start(con, ref):
    """valid-from of the line or page that replaces a fact, or None."""
    path, ln = split_ref(ref)
    if ln:
        r = con.execute("select valid_from as v from facts where path=? and line=?", (path, ln)).fetchone()
    else:
        r = con.execute("select min(valid_from) as v from facts where path=? and valid_from is not null", (path,)).fetchone()
    return r["v"] if r else None


def end_of(con, row):
    """(last valid day or None, known). known is False for a superseded line whose end cannot be worked out."""
    if row["valid_to"]:
        return row["valid_to"], True
    if row["superseded_by"]:
        start = _superseder_start(con, row["superseded_by"])
        if start:
            return (datetime.date.fromisoformat(start) - datetime.timedelta(days=1)).isoformat(), True
        return None, False
    return None, True


def status(con, row, day):
    """valid | not yet | ended | superseded (end unknown)"""
    if row["valid_from"] and day < row["valid_from"]:
        return "not yet"
    end, known = end_of(con, row)
    if not known:
        return "superseded (end unknown)"
    if end and day > end:
        return "ended"
    return "valid"


def as_of(kb, date, include_undated=False):
    """Lines valid on `date`: [{id, path, line, text, valid_from, valid_to, superseded_by, from_section}]. `from_section` is
    "path:line" of the heading a date was inherited from, or None."""
    day = parse_date(date)
    con = connect(kb)
    try:
        out = []
        for r in con.execute("select * from facts order by path, line"):
            if not r["annotated"] and not include_undated:
                continue
            if status(con, r, day) == "valid":
                out.append({"id": fact_id(r), "path": r["path"], "line": r["line"], "text": r["text"], "valid_from": r["valid_from"],
                            "valid_to": r["valid_to"], "superseded_by": r["superseded_by"], "from_section": r["section"]})
        return out
    finally:
        con.close()


def history(kb, obj):
    """Every indexed line that mentions `obj` (case-insensitive) or sits on the page `obj`, oldest valid-from first, with its
    status today: [{id, text, valid_from, valid_to, superseded_by, status}]."""
    obj = str(obj or "").strip()
    if not obj:
        raise ValueError("name the object to look up")
    con = connect(kb)
    try:
        today = datetime.date.today().isoformat()
        rows = [r for r in con.execute("select * from facts") if obj.lower() in r["text"].lower() or r["path"] == obj]
        rows.sort(key=lambda r: (r["valid_from"] or "", r["path"], r["line"]))
        return [{"id": fact_id(r), "text": r["text"], "valid_from": r["valid_from"], "valid_to": r["valid_to"],
                 "superseded_by": r["superseded_by"], "status": status(con, r, today) if r["annotated"] else "no dates"} for r in rows]
    finally:
        con.close()


def expired(kb, today=None):
    """Lines whose valid-to is before `today` and that nothing supersedes, plus superseded lines whose end cannot be worked out:
    [{id, text, valid_to, why}]."""
    day = parse_date(today or datetime.date.today().isoformat())
    con = connect(kb)
    try:
        out = []
        for r in con.execute("select * from facts where annotated=1 order by path, line"):
            if r["superseded_by"]:
                if not end_of(con, r)[1]:
                    out.append({"id": fact_id(r), "text": r["text"], "valid_to": r["valid_to"], "why": "superseded, no end date"})
            elif r["valid_to"] and r["valid_to"] < day:
                out.append({"id": fact_id(r), "text": r["text"], "valid_to": r["valid_to"], "why": "valid-to passed, not superseded"})
        return out
    finally:
        con.close()


# ---- git: whole-page history -------------------------------------------------------------------
def page_at(kb, rev, path):
    """The text of a KB page at a git revision, via `git show <rev>:./<path>` run inside the KB folder. Raises ValueError when
    git, the revision or the path is not usable."""
    kb = os.path.abspath(kb)
    rev, path = str(rev or "").strip(), str(path or "").strip().replace("\\", "/")
    if not rev or rev.startswith("-") or re.search(r"\s", rev):
        raise ValueError("not a usable revision: %r" % rev)
    if not path or path.startswith("/") or ".." in path.split("/"):
        raise ValueError("give the page as a path inside the KB, e.g. context/rules.md")
    try:
        r = subprocess.run(["git", "show", "%s:./%s" % (rev, path)], cwd=kb, capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as err:
        raise ValueError("git could not be run: %s" % err)
    if r.returncode:
        raise ValueError("git show failed: %s" % (r.stderr.decode("utf-8", "replace").strip() or "unknown error"))
    return r.stdout.decode("utf-8", "replace")


# ---- edges -------------------------------------------------------------------------------------
def _load(path):
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def as_of_edges(kb, date, columns_file=None):
    """Edges of CROSS-LAYER/LINK_GRAPH.yaml in force on `date`. Validity comes from the edge itself (valid_from / valid_to) or from
    the optional columns file (default CROSS-LAYER/edge_validity.yaml), matched on from + rel + to. Each returned edge has
    valid_from and valid_to filled in (None when open)."""
    day = parse_date(date)
    kb = os.path.abspath(kb)
    edges = _load(os.path.join(kb, "CROSS-LAYER", "LINK_GRAPH.yaml")).get("edges") or []
    cols = _load(columns_file or os.path.join(kb, EDGE_COLUMNS)).get("edges") or []
    extra = {(c.get("from"), str(c.get("rel")), c.get("to")): c for c in cols if isinstance(c, dict)}
    out = []
    for e in edges:
        c = extra.get((e.get("from"), str(e.get("rel")), e.get("to"))) or {}
        vf = str(e.get("valid_from") or c.get("valid_from") or "") or None
        vt = str(e.get("valid_to") or c.get("valid_to") or "") or None
        if (vf and day < vf) or (vt and day > vt):
            continue
        out.append(dict(e, valid_from=vf, valid_to=vt))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("build"); a.add_argument("kb")
    a = sub.add_parser("as-of"); a.add_argument("kb"); a.add_argument("date"); a.add_argument("--all", action="store_true")
    a = sub.add_parser("history"); a.add_argument("kb"); a.add_argument("object")
    a = sub.add_parser("expired"); a.add_argument("kb"); a.add_argument("--today")
    a = sub.add_parser("page-at"); a.add_argument("kb"); a.add_argument("rev"); a.add_argument("path")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "build":
            n, ann, probs = build(args.kb)
            for p, ln, why in probs:
                print("%s:%d: %s" % (p, ln, why))
            print("%d lines indexed, %d with dates, %d problems -> %s" % (n, ann, len(probs), db_path(os.path.abspath(args.kb))))
            return 1 if probs else 0
        if args.cmd == "as-of":
            rows = as_of(args.kb, args.date, args.all)
            for r in rows:
                print("%s\t%s%s" % (r["id"], r["text"], "  [section %s]" % r["from_section"] if r["from_section"] else ""))
            print("%d lines valid on %s" % (len(rows), args.date))
        elif args.cmd == "history":
            rows = history(args.kb, args.object)
            for r in rows:
                print("%s\t%s..%s\t%s\t%s" % (r["id"], r["valid_from"] or "?", r["valid_to"] or "?", r["status"], r["text"]))
            print("%d lines mention %s" % (len(rows), args.object))
        elif args.cmd == "expired":
            rows = expired(args.kb, args.today)
            for r in rows:
                print("%s\t%s\t%s\t%s" % (r["id"], r["valid_to"] or "-", r["why"], r["text"]))
            print("%d expired lines" % len(rows))
            return 1 if rows else 0
        else:
            sys.stdout.write(page_at(args.kb, args.rev, args.path))
    except ValueError as err:
        print("error: %s" % err, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
