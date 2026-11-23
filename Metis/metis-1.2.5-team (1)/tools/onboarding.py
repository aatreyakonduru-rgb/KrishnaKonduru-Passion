#!/usr/bin/env python3
"""A reading path for someone new to the KB, built from what is already in it: the pages their team owns, the objects those pages
name in the link graph, the glossary terms that point at them, and the open questions waiting on their role.

    python3 onboarding.py path <kb> <team | approver name | role> [--as NAME_OR_ROLE] [--limit N] [--json] [--out FILE]

The first word picks the scope, in this order:
  a team in the profile (gate.teams)        the pages that team owns (gate.teams.owns)
  an approver of a team                     the same, for that person's team
  a role that open questions are waiting on  the pages those questions block
  anything else                              the whole KB, with a note saying nothing named this role

Order: pages that name the most graph objects come first (broad pages before narrow ones). That is a count of names found in
the text, not a judgement of importance, and a short object name (Pet) can match ordinary prose. Objects are ranked by how many
links touch them in CROSS-LAYER/LINK_GRAPH.yaml. Glossary terms are those whose `where_in_kb` names a page in scope. Open questions
are listed as gaps: the path says what nobody knows yet, not only what is known.

This is a navigation aid, not KB content: it writes nothing into the KB (only --out, to a path you choose) and carries no [E:] tags,
because it states no new fact; every line is a pointer to a page, object, term or question that has its own source.
`--as` applies the claim-label filter (claim_labels.py) so a reader is not pointed at pages above their clearance; no `--as` means
the lowest clearance when the KB uses labels. It does not track who has read what, and it is not a quiz or a course.
"""
import argparse
import json
import os
import re
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (HERE, os.path.join(HERE, "ui")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import claim_labels  # noqa: E402
import kb_coverage  # noqa: E402
import kb_gate  # noqa: E402
import questions  # noqa: E402

COUNTED_TYPES = set(kb_coverage.COUNTED)


def graph(kb):
    """(nodes {id: {type, name}}, links per node {id: n}) from LINK_GRAPH.yaml; empty when there is none."""
    p = os.path.join(kb, "CROSS-LAYER", "LINK_GRAPH.yaml")
    if not os.path.isfile(p):
        return {}, {}
    with open(p, encoding="utf-8") as fh:
        g = yaml.safe_load(fh) or {}
    nodes = {n["id"]: {"type": n.get("type"), "name": str(n.get("name"))} for n in g.get("nodes") or [] if n.get("id")}
    deg = {}
    for e in g.get("edges") or []:
        for end in (e.get("from"), e.get("to")):
            deg[end] = deg.get(end, 0) + 1
    return nodes, deg


def title_of(rel, text):
    meta, body = kb_gate.front(text)
    if meta.get("title"):
        return str(meta["title"])
    for line in body.splitlines():
        m = re.match(r"^#\s+(.*)", line.strip())
        if m:
            return m.group(1).strip()
    return rel


def open_questions(kb):
    return [q for q in questions.load(questions.reg_path(kb)).get("questions") or [] if q.get("status") == "open"]


def scope_for(kb, who, pages, qs):
    """(label, set of page paths or None for all, note)."""
    key = kb_gate.clean(who).lower()
    for t in kb_gate.teams(kb):
        if t["name"].lower() == key or any(a.lower() == key for a in t["approvers"]):
            mine = {rel for rel in pages if (kb_gate.team_of(kb, rel) or {}).get("name") == t["name"]}
            if mine:
                return "team %s" % t["name"], mine, None
            return "team %s" % t["name"], None, "team %s owns no page yet; showing the whole KB" % t["name"]
    waiting = [q for q in qs if kb_gate.clean(q.get("answer_role")).lower() == key]
    blocked = {b for q in waiting for b in (q.get("blocks") if isinstance(q.get("blocks"), list) else [q.get("blocks")]) if b}
    blocked &= set(pages)
    if blocked:
        return "role %s (pages its open questions block)" % kb_gate.clean(who), blocked, None
    return "whole KB", None, "nothing in the profile or the question register names '%s'; showing the whole KB" % kb_gate.clean(who)


def build(kb, who, as_who=None, limit=12):
    kb = os.path.abspath(kb)
    viewer = claim_labels.Viewer(kb, as_who)
    texts = viewer.filter_pages(kb_coverage.page_files(kb))
    nodes, deg = graph(kb)
    qs = open_questions(kb)
    label, scope, note = scope_for(kb, who, texts, qs)
    pages = {rel: t for rel, t in texts.items() if scope is None or rel in scope}
    objs = {nid: n for nid, n in nodes.items() if n["type"] in COUNTED_TYPES and len(n["name"]) >= 3}
    lowered = {rel: t.lower() for rel, t in pages.items()}
    on_page = {rel: [nid for nid, n in objs.items() if kb_coverage.named(n["name"], [lowered[rel]])] for rel in pages}
    order = sorted(pages, key=lambda r: (-len(on_page[r]), r))
    read = [{"path": r, "title": title_of(r, pages[r]), "objects": len(on_page[r])} for r in order[:max(0, limit)]]
    seen = {nid for r in order for nid in on_page[r]}
    top = sorted(seen, key=lambda n: (-deg.get(n, 0), n))[:max(0, limit)]
    objects = [{"id": n, "links": deg.get(n, 0)} for n in top]
    from glossary import load as load_glossary
    terms = []
    for e in load_glossary(kb)["entries"]:
        hits = [w for w in e["where_in_kb"] if w.replace("\\", "/").strip("/") in pages]
        if hits:
            terms.append({"term": e["term"], "meaning": e["meaning"], "where_in_kb": hits})
    shown = set(pages)
    waiting = []
    for q in qs:
        blocks = q.get("blocks") if isinstance(q.get("blocks"), list) else [q.get("blocks")]
        if kb_gate.clean(q.get("answer_role")).lower() == kb_gate.clean(who).lower() or (scope is not None and shown & set(blocks)):
            waiting.append({"id": q.get("id"), "question": q.get("question"), "priority": q.get("priority"),
                            "answer_role": q.get("answer_role"), "blocks": [b for b in blocks if b]})
    notes = [note] if note else []
    if viewer.active and viewer.withheld:
        notes.append("%d lines are above the reader's clearance and were left out of the path" % viewer.withheld)
    if not nodes:
        notes.append("no link graph (CROSS-LAYER/LINK_GRAPH.yaml); pages are ordered by name and no objects are listed")
    return {"for": kb_gate.clean(who), "scope": label, "pages_in_scope": len(pages), "notes": notes, "read_in_order": read,
            "key_objects": objects, "glossary": terms, "open_questions": waiting}


def to_markdown(r):
    out = ["# Reading path for %s" % r["for"], "", "Scope: %s (%d pages). Generated from the KB; it states no new fact." % (r["scope"], r["pages_in_scope"]), ""]
    out += ["> %s" % n for n in r["notes"]] + ([""] if r["notes"] else [])
    out += ["## 1. Read these pages, in this order", ""]
    out += ["%d. `%s` - %s (%d objects named)" % (i, p["path"], p["title"], p["objects"]) for i, p in enumerate(r["read_in_order"], 1)] or ["(none)"]
    out += ["", "## 2. Objects to know (most links first)", ""]
    out += ["- `%s` (%d links)" % (o["id"], o["links"]) for o in r["key_objects"]] or ["(none)"]
    out += ["", "## 3. Terms that point at these pages", ""]
    out += ["- **%s**: %s (see %s)" % (t["term"], t["meaning"] or "no meaning written", ", ".join("`%s`" % w for w in t["where_in_kb"])) for t in r["glossary"]] or ["(none)"]
    out += ["", "## 4. Not known yet (open questions)", ""]
    out += ["- %s [%s] %s - waiting on %s; blocks %s" % (q["id"], q["priority"], q["question"], q["answer_role"], ", ".join(q["blocks"]) or "nothing named") for q in r["open_questions"]] or ["(none)"]
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("path")
    p.add_argument("kb")
    p.add_argument("who", help="a team, a team approver, or a role that open questions wait on")
    p.add_argument("--as", dest="as_who", help="reader whose clearance applies when the KB uses claim labels (default: the lowest)")
    p.add_argument("--limit", type=int, default=12)
    p.add_argument("--json", action="store_true")
    p.add_argument("--out", help="write the path to this file instead of printing it")
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)
    if not os.path.isdir(a.kb):
        print("error: no KB folder %s" % a.kb, file=sys.stderr)
        return 2
    r = build(a.kb, a.who, a.as_who, a.limit)
    text = json.dumps(r, indent=2) if a.json else to_markdown(r)
    if a.out:
        with open(a.out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        print("onboarding: %d pages, %d objects, %d terms, %d open questions -> %s" % (
            len(r["read_in_order"]), len(r["key_objects"]), len(r["glossary"]), len(r["open_questions"]), a.out))
    else:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
