#!/usr/bin/env python3
"""Who reads the KB: a record of which KB files packs and answers used, and a report of what is read and what is not.

    python3 telemetry.py record <kb> --kind pack|answer --files REL [REL ...] [--pack-id ID] [--tokens N] [--by NAME]
    python3 telemetry.py report <kb>

Events go to <kb>/.metis/usage/<YYYY-MM>.jsonl, one JSON object per line: time, kind, pack id, KB files used, who, tokens.
No question text and no answer text is stored. The folder has a .gitignore of `*`, so events stay on the machine and are
not part of any pull request. Nothing in this file is KB content and none of it is read by the source check.

`report` lists how often each KB file was used in a pack or cited in an answer, and how many hand-written pages were
never used. Use alone it shows what is read, not whether it was right. It also joins the likes and dislikes in
_FEEDBACK (feedback.py) by KB file: for each file, the likes and dislikes of answers that cited it, set beside how often
it was used. A dislike names the answer, not the page: a page cited in a disliked answer may be right and the answer wrong
(the wrong page was picked, or a right page was misread). Read the join as "look here first", not as a verdict on a page.
A lead's decision is kept apart: a dislike a lead declined is counted as declined, not as a mark against the page.
"""
import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import feedback  # noqa: E402
import kb_coverage  # noqa: E402

DIR = os.path.join(".metis", "usage")


def record(kb, kind, files, pack_id=None, tokens=None, by=None, skipped=0, lines=None, anchors=None):
    if lines and anchors is None:  # a stable fingerprint of each cited line, so counts survive an edit (telemetry_lines.py)
        try:
            import telemetry_lines
            anchors = telemetry_lines.anchors_for(kb, lines)
        except Exception:  # noqa: BLE001  never stops a record
            anchors = None
    folder = os.path.join(kb, DIR)
    os.makedirs(folder, exist_ok=True)
    guard = os.path.join(folder, ".gitignore")
    if not os.path.isfile(guard):
        with open(guard, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("*\n")
    now = datetime.datetime.now(datetime.timezone.utc)
    event = {"at": now.isoformat(timespec="seconds"), "kind": kind, "files": sorted(set(files)), "by": by or None,
             "pack_id": pack_id, "tokens": tokens, "skipped": skipped}
    if lines:  # optional "path:line" references the answer cited (see telemetry_lines.py); never text
        event["lines"] = sorted(set(lines))
    if anchors:  # optional "path:line#fingerprint" (salted hash of the line, see telemetry_lines.py); never text
        event["anchors"] = sorted(set(anchors))
    with open(os.path.join(folder, now.strftime("%Y-%m") + ".jsonl"), "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(event, sort_keys=True) + "\n")
    return event


def events(kb):
    folder = os.path.join(kb, DIR)
    out = []
    if not os.path.isdir(folder):
        return out
    for name in sorted(os.listdir(folder)):
        if name.endswith(".jsonl"):
            with open(os.path.join(folder, name), encoding="utf-8") as fh:
                out += [json.loads(line) for line in fh if line.strip()]
    return out


def rated(kb):
    """{KB file: {up, down, declined}} from the answers people liked or disliked and the files each cited."""
    out = {}
    for f in feedback.load(kb).get("feedback") or []:
        for rel in f.get("cited_files") or []:
            row = out.setdefault(rel, {"up": 0, "down": 0, "declined": 0})
            if f.get("rating") == "up":
                row["up"] += 1
            elif f.get("status") == "declined":
                row["declined"] += 1
            else:
                row["down"] += 1
    return out


def by_team(kb, ev):
    """Use counted by the team that owns the file (gate.teams in the KB profile; first matching glob), and by the person who
    recorded it. Counts and file names only: no question or answer text is stored, so none can appear here. A reader is
    placed in a team only when the profile lists them as that team's approver; everyone else is "(not in a team)".
    "by_owner_team" says whose pages are read; "by_reader" says who reads, not which team the reader belongs to."""
    import kb_gate
    approver_team = {}
    for t in kb_gate.teams(kb):
        for a in t["approvers"]:
            approver_team.setdefault(a.lower(), t["name"])
    owner, reader = {}, {}
    for e in ev:
        key = "packs" if e["kind"] == "pack" else "answers"
        for f in e["files"]:
            t = kb_gate.team_of(kb, f)
            row = owner.setdefault(t["name"] if t else kb_gate.UNASSIGNED, {"packs": 0, "answers": 0, "files": set()})
            row[key] += 1
            row["files"].add(f)
        who = e.get("by") or "(not recorded)"
        row = reader.setdefault(who, {"packs": 0, "answers": 0, "team": approver_team.get(who.lower(), "(not in a team)")})
        row[key] += 1
    return ({k: {"packs": v["packs"], "answers": v["answers"], "files": len(v["files"])} for k, v in sorted(owner.items())},
            dict(sorted(reader.items())))


def report(kb):
    ev = events(kb)
    used = {}
    for e in ev:
        for f in e["files"]:
            row = used.setdefault(f, {"packs": 0, "answers": 0})
            row["packs" if e["kind"] == "pack" else "answers"] += 1
    pages = sorted(kb_coverage.page_files(kb))
    never = [p for p in pages if p not in used]
    marks = rated(kb)
    fb = {f: dict(m, used=sum(used.get(f, {}).values())) for f, m in sorted(marks.items())}
    owner_team, reader = by_team(kb, ev)
    return {"events": len(ev), "packs": sum(1 for e in ev if e["kind"] == "pack"),
            "by_owner_team": owner_team, "by_reader": reader,
            "answers": sum(1 for e in ev if e["kind"] == "answer"), "files_used": dict(sorted(used.items())),
            "pages": len(pages), "pages_never_used": never, "feedback": fb,
            "look_first": sorted((f for f, m in fb.items() if m["down"]), key=lambda f: (-fb[f]["down"], fb[f]["up"], f)),
            "rated_but_not_used": [f for f, m in fb.items() if not m["used"]]}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record")
    r.add_argument("kb")
    r.add_argument("--kind", required=True, choices=("pack", "answer"))
    r.add_argument("--files", nargs="+", required=True)
    r.add_argument("--pack-id")
    r.add_argument("--tokens", type=int)
    r.add_argument("--by")
    p = sub.add_parser("report")
    p.add_argument("kb")
    a = ap.parse_args(argv)
    if a.cmd == "record":
        record(a.kb, a.kind, a.files, a.pack_id, a.tokens, a.by)
        print("recorded %s use of %d files" % (a.kind, len(a.files)))
        return 0
    rep = report(a.kb)
    print("%d packs and %d answers recorded; %d of %d hand-written pages never used"
          % (rep["packs"], rep["answers"], len(rep["pages_never_used"]), rep["pages"]))
    for f, c in sorted(rep["files_used"].items(), key=lambda kv: (-(kv[1]["packs"] + kv[1]["answers"]), kv[0])):
        print("%3d packs %3d answers  %s" % (c["packs"], c["answers"], f))
    for f in rep["pages_never_used"]:
        print("  never used  %s" % f)
    if rep["by_owner_team"]:
        print("\nUse of each team's pages (gate.teams; file names only, never question text):")
        for t, c in rep["by_owner_team"].items():
            print("%3d packs %3d answers %3d files  %s" % (c["packs"], c["answers"], c["files"], t))
        print("By who recorded the use (a team shows only for a listed approver):")
        for w, c in rep["by_reader"].items():
            print("%3d packs %3d answers  %s [%s]" % (c["packs"], c["answers"], w, c["team"]))
    if rep["feedback"]:
        print("\nLikes and dislikes by KB file (answers that cited it); a lead-declined dislike is counted apart:")
        for f, m in sorted(rep["feedback"].items(), key=lambda kv: (-kv[1]["down"], -kv[1]["up"], kv[0])):
            print("%3d up %3d down %3d declined  used %3d  %s" % (m["up"], m["down"], m["declined"], m["used"], f))
        if rep["look_first"]:
            print("Look first (most dislikes): %s" % ", ".join(rep["look_first"][:5]))
        if rep["rated_but_not_used"]:
            print("Rated but never recorded as used (usage was off, or the answer was not recorded): %s"
                  % ", ".join(rep["rated_but_not_used"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
