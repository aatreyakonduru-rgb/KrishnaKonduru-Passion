#!/usr/bin/env python3
"""Keep a compact history of how the KB measured at each build, so a team can see whether it is getting better or worse.

    python3 kb_trend.py record <kb>            append one snapshot for this build to <kb>/.metis/trend.jsonl
    python3 kb_trend.py show   <kb> [--last N] print the last N snapshots (default 10)

One JSON line per build: time, and counts only (no page text, no question text, no names):
  coverage  graph objects named in no page, catalogue tables named in no page, rejected links, impact relations not understood
            (from CROSS-LAYER/COVERAGE.yaml; absent when kb_coverage.py has not been run)
  verify    files, tags, fact lines, problems (from verify_kb.Checker, or the result you pass in)
  golden    questions in the set, and static problems (a KB file a question relies on is gone); no model is run here
  questions open questions in the register, and how many are P1
  quality   contradiction pairs, near-duplicate page pairs, broken links, orphan pages, counted from the reports of
            kb_contradict.py, kb_dupes.py and kb_links.py when those reports exist
  pages     hand-written pages

`record(kb)` is meant to be called once, at the end of a build (see build_outputs.py). It is append-only; the same build run twice
makes two lines. Reading it is `trend(kb, last=N)`. `sparkline(values)` draws a small inline SVG for the UI; it needs no script.
The file is a local record of measurements, not KB content: nothing reads it as a claim.
"""
import argparse
import datetime
import html
import json
import os
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import golden  # noqa: E402
import kb_coverage  # noqa: E402
import questions  # noqa: E402
import verify_kb  # noqa: E402

FILE = os.path.join(".metis", "trend.jsonl")
SERIES = {"Problems the source check finds": ("verify", "problems"), "Objects named in no page": ("coverage", "objects_unnamed"),
          "Open questions": ("questions", "open"), "Golden static problems": ("golden", "static_problems"),
          "Contradiction pairs": ("quality", "contradictions"), "Near-duplicate page pairs": ("quality", "duplicate_pages"),
          "Broken links": ("quality", "broken_links"), "Hand-written pages": ("pages", None)}


def path(kb):
    return os.path.join(kb, FILE)


def load_yaml(p):
    if not os.path.isfile(p):
        return {}
    with open(p, encoding="utf-8") as fh:
        try:
            return yaml.safe_load(fh) or {}
        except yaml.YAMLError:
            return {}


def coverage_counts(kb):
    cov = load_yaml(os.path.join(kb, "CROSS-LAYER", "COVERAGE.yaml"))
    if not cov:
        return None
    objs = cov.get("objects") or {}
    return {"objects_unnamed": sum(int(v.get("named_in_no_page", 0)) for v in objs.values() if isinstance(v, dict)),
            "objects_in_graph": sum(int(v.get("in_graph", 0)) for v in objs.values() if isinstance(v, dict)),
            "tables_unnamed": int((cov.get("catalogue_tables") or {}).get("named_in_no_page", 0)),
            "rejected_links": len(cov.get("rejected_links") or []),
            "relations_not_understood": len(((cov.get("impact_not_understood") or {}).get("relations")) or [])}


def quality_counts(kb):
    out = {}
    for key, rel, field in (("contradictions", "CONTRADICTIONS.yaml", "pairs"), ("duplicate_pages", "DUPLICATES.yaml", "page_pairs"),
                            ("broken_links", "LINK_CHECK.yaml", "broken_links"), ("orphan_pages", "LINK_CHECK.yaml", "orphan_pages")):
        rep = load_yaml(os.path.join(kb, "CROSS-LAYER", rel))
        if isinstance(rep.get(field), int):
            out[key] = rep[field]
    return out or None


def snapshot(kb, verify=None):
    """The counts for this moment as a dict. `verify` is a verify_kb result (Checker.run()) to avoid checking twice."""
    kb = os.path.abspath(kb)
    rep = verify if verify is not None else verify_kb.Checker(kb).run()
    reg = (questions.load(questions.reg_path(kb)).get("questions") or [])
    open_q = [q for q in reg if isinstance(q, dict) and q.get("status") == "open"]
    try:
        gold = {"questions": len(golden.load(kb).get("golden") or []), "static_problems": len(golden.static(kb))}
    except Exception:
        gold = None
    snap = {"at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "pages": len(kb_coverage.page_files(kb)),
            "verify": {"files": rep.get("files", 0), "tags": rep.get("tags", 0), "fact_lines": rep.get("fact_lines", 0),
                       "problems": len(rep.get("problems") or [])},
            "questions": {"open": len(open_q), "p1": sum(1 for q in open_q if q.get("priority") == "P1")}}
    for key, val in (("coverage", coverage_counts(kb)), ("golden", gold), ("quality", quality_counts(kb))):
        if val is not None:
            snap[key] = val
    return snap


def record(kb, verify=None):
    """Append one snapshot line to <kb>/.metis/trend.jsonl and return it."""
    snap = snapshot(kb, verify)
    p = path(os.path.abspath(kb))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(snap, sort_keys=True) + "\n")
    return snap


def trend(kb, last=10):
    """The last `last` snapshots, oldest first. A line that is not valid JSON is skipped. Missing file means []."""
    p = path(os.path.abspath(kb))
    out = []
    if os.path.isfile(p):
        with open(p, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    try:
                        v = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(v, dict):
                        out.append(v)
    return out[-last:] if last else out


def values(snaps, group, key=None):
    """One number per snapshot for a series (None where a snapshot did not record it)."""
    out = []
    for s in snaps:
        v = s.get(group)
        if key is not None:
            v = v.get(key) if isinstance(v, dict) else None
        out.append(v if isinstance(v, (int, float)) and not isinstance(v, bool) else None)
    return out


def series(snaps):
    """{label: [numbers]} for the series the UI draws; a series with no number at all is left out."""
    out = {}
    for label, (group, key) in SERIES.items():
        v = values(snaps, group, key)
        if any(x is not None for x in v):
            out[label] = v
    return out


def change(vals):
    """(first number, last number) of a series, or None when fewer than two numbers exist."""
    got = [v for v in vals if v is not None]
    return (got[0], got[-1]) if len(got) >= 2 else None


def sparkline(vals, width=120, height=28, label=""):
    """Inline SVG of a series: a line with the last point marked. No script, no external file. None values leave a gap."""
    pts = [(i, v) for i, v in enumerate(vals) if v is not None]
    title = "<title>%s</title>" % html.escape(label) if label else ""
    head = '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" role="img">%s' % (width, height, width, height, title)
    if not pts:
        return head + "</svg>"
    pad = 3
    lo, hi = min(v for _, v in pts), max(v for _, v in pts)
    span = (hi - lo) or 1
    n = max(len(vals) - 1, 1)

    def xy(i, v):
        x = pad + (width - 2 * pad) * (i / n if len(vals) > 1 else 0.5)
        y = (height / 2) if hi == lo else pad + (height - 2 * pad) * (1 - (v - lo) / span)
        return round(x, 1), round(y, 1)

    segs, cur = [], []
    for i, v in enumerate(vals):
        if v is None:
            if cur:
                segs.append(cur)
            cur = []
        else:
            cur.append(xy(i, v))
    if cur:
        segs.append(cur)
    body = "".join('<polyline fill="none" stroke="#3b82d4" stroke-width="1.5" points="%s"/>' % " ".join("%s,%s" % p for p in s)
                   for s in segs if len(s) > 1)
    lx, ly = xy(*pts[-1])
    return head + body + '<circle cx="%s" cy="%s" r="2.5" fill="#3b82d4"/></svg>' % (lx, ly)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record"); r.add_argument("kb")
    s = sub.add_parser("show"); s.add_argument("kb"); s.add_argument("--last", type=int, default=10)
    a = ap.parse_args(argv)
    kb = os.path.abspath(a.kb)
    if a.cmd == "record":
        snap = record(kb)
        print("trend: recorded %s (%d problems, %d open questions)" % (snap["at"], snap["verify"]["problems"], snap["questions"]["open"]))
        return 0
    snaps = trend(kb, a.last)
    if not snaps:
        print("trend: no builds recorded yet")
        return 0
    for label, vals in series(snaps).items():
        print("%-34s %s" % (label, " ".join("-" if v is None else str(v) for v in vals)))
    print("trend: %d builds shown" % len(snaps))
    return 0


if __name__ == "__main__":
    sys.exit(main())
