#!/usr/bin/env python3
"""Compare a staged knowledge-base rebuild with the live knowledge base.

    python3 kb_compare.py LIVE_DIR STAGE_DIR [--map MAP.yaml] [--keep KEEP.yaml] [--out REPORT.md] [--json]

A rebuild writes into a staging folder first (`prompts.py render --stage`). This tool lists,
for every staged file, whether it is new or changed against the live copy, and what a
reviewer has to check before the staged copy may replace the live one:

  - lines added and removed; sections that are new, renamed or gone. Headings are matched
    ignoring case, numbering and punctuation, and a renamed section is paired with its old
    title. For a gone section, the report says how much of its content (names in backticks,
    numbers, identifiers) still appears elsewhere in the staged copy;
  - evidence tags ([E: ...], [A], [?]) and old-style tags in each copy;
  - facts a person supplied by hand ([E: stated by ...]) that the staged copy dropped;
  - a `.PATCHES.md` sidecar next to the live file, whose entries must be carried over;
  - live files in the same folders that the rebuild did not produce.

MAP.yaml maps a staged relative path to a different live relative path, for teams whose
live file names differ from the prompt output names:  {stage/rel/path.md: live/rel/path.md}

KEEP.yaml lists live files that no prompt builds, such as documents made from a spreadsheet or
written by hand:  {keep: [{path: rel/path/or/pattern*, source: where it came from}]}. They are
reported as kept, not as needing a decision, and a staged file that would replace one is flagged.

It only reads files. Nothing is replaced.
"""
import argparse
import difflib
import fnmatch
import json
import os
import re
import sys

import yaml

TAGS = {
    "evidence": re.compile(r"\[E:"),
    "assumption": re.compile(r"\[A\]"),
    "unknown": re.compile(r"\[\?\]"),
    "old_style": re.compile(r"\[CONFIRMED|\[INFERRED|REQUIRES STAKEHOLDER INPUT|\[QUERY FAILED"),
}
HAND_FACT = re.compile(r"\[E:\s*stated by[^\]]*\]", re.I)
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.M)
NUMBERING = re.compile(r"^(?:[A-Z]?\d+[a-z]?(?:\.\d+)*[.)]?|[A-Z]\.)\s+")
TERM = re.compile(r"`([^`\n]{2,80})`|\b([A-Z][A-Z0-9_]{3,}|[a-z]+_[a-z0-9_]+|[A-Za-z]+[A-Z][a-z]+\w*|\d{2,}(?:[.,]\d+)?)\b")
RENAME_MIN = 0.6
STOP = {"the", "and", "of", "for", "a", "an", "to", "in", "on", "by", "or", "with", "identified", "detected"}
SKIP_DIRS = {".git", "__pycache__"}


def files_under(root):
    out = []
    for base, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for n in names:
            out.append(os.path.relpath(os.path.join(base, n), root).replace(os.sep, "/"))
    return sorted(out)


def read(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def tag_counts(text):
    return {k: len(rx.findall(text)) for k, rx in TAGS.items()}


def hand_facts(text):
    """Lines that carry a fact a person supplied, keyed by the text around the tag."""
    return [line.strip() for line in text.splitlines() if HAND_FACT.search(line)]


def sidecar(live_path):
    if live_path.endswith(".PATCHES.md"):
        return None
    return os.path.splitext(live_path)[0] + ".PATCHES.md"


def norm_heading(h):
    """Heading text without numbering, case, punctuation or filler words."""
    h = NUMBERING.sub("", h.strip())
    words = re.findall(r"[a-z0-9]+", h.lower())
    return " ".join(w for w in words if w not in STOP)


def sections(text):
    """[(heading, body)] for each Markdown heading, body up to the next heading."""
    marks = list(HEADING.finditer(text))
    return [(m.group(1), text[m.end():marks[i + 1].start() if i + 1 < len(marks) else len(text)])
            for i, m in enumerate(marks)]


def terms(text):
    return {a or b for a, b in TERM.findall(text)}


def similarity(a, b):
    wa, wb = set(a.split()), set(b.split())
    overlap = len(wa & wb) / max(1, min(len(wa), len(wb)))
    return max(overlap, difflib.SequenceMatcher(None, a, b).ratio())


def match_sections(old, new):
    """Pair old and new sections: same after normalising, else the most similar title.

    Returns (renamed, gone, added) where renamed is [(old, new)] and gone carries the share
    of the old section's terms that still appear anywhere in the new text.
    """
    old_s, new_s = sections(old), sections(new)
    new_by_norm = {}
    for h, _ in new_s:
        new_by_norm.setdefault(norm_heading(h), h)
    used, renamed, left = set(), [], []
    for h, body in old_s:
        n = norm_heading(h)
        if n in new_by_norm and new_by_norm[n] not in used:
            used.add(new_by_norm[n])
            if h != new_by_norm[n]:
                renamed.append((h, new_by_norm[n]))
        else:
            left.append((h, body))
    gone = []
    new_terms = terms(new)
    for h, body in left:
        n = norm_heading(h)
        best, score = None, 0.0
        for nh, _ in new_s:
            if nh in used:
                continue
            sc = similarity(n, norm_heading(nh))
            if sc > score:
                best, score = nh, sc
        if best and score >= RENAME_MIN:
            used.add(best)
            renamed.append((h, best))
            continue
        if not NUMBERING.match(h) and (not body.strip() or HEADING.match(body.strip())):
            gone.append({"heading": h, "title_line": True})
            continue
        t = terms(body)
        kept = round(100 * len(t & new_terms) / len(t)) if t else None
        gone.append({"heading": h, "terms": len(t), "terms_kept_pct": kept})
    added = [h for h, _ in new_s if h not in used and h not in {o for o, _ in old_s}]
    return renamed, gone, added


def compare_file(live_path, stage_path):
    new = read(stage_path)
    entry = {"tags_staged": tag_counts(new)}
    if not os.path.exists(live_path):
        entry["status"] = "new"
        return entry
    old = read(live_path)
    entry["tags_live"] = tag_counts(old)
    if old == new:
        entry["status"] = "same"
        return entry
    entry["status"] = "changed"
    added = removed = 0
    for line in difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=0):
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    entry["lines_added"], entry["lines_removed"] = added, removed
    # Only Markdown has headings: a "# ..." line in YAML is a comment.
    markdown = str(live_path).lower().endswith(".md")
    renamed, gone, added = match_sections(old, new) if markdown else ([], [], [])
    entry["headings_renamed"] = renamed
    entry["headings_gone"] = [g["heading"] for g in gone if not g.get("title_line")]
    entry["title_lines_gone"] = [g["heading"] for g in gone if g.get("title_line")]
    entry["sections_gone"] = gone
    entry["headings_new"] = added
    entry["hand_facts_dropped"] = [f for f in hand_facts(old) if f not in new]
    return entry


def load_keep(path):
    """[(pattern, source)] from a keep list: {keep: [{path: ..., source: ...}]}."""
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return [(k["path"], k.get("source", "")) for k in data.get("keep") or []]


def kept_by(rel, keep):
    """The source note of the keep entry that covers rel, else None."""
    rel = rel.replace(os.sep, "/")
    for pattern, source in keep or []:
        if fnmatch.fnmatch(rel, pattern):
            return source or "on the keep list"
    return None


def live_name(mapping, rel):
    """The live name a staged file maps to. A list maps to its first name; the rest are duplicates."""
    name = (mapping or {}).get(rel, rel)
    return name[0] if isinstance(name, list) else name


def duplicates(mapping, rel):
    """Further live copies of the same document, to be merged into the first and archived."""
    name = (mapping or {}).get(rel)
    return list(name[1:]) if isinstance(name, list) else []


def compare(live, stage, mapping=None, keep=None):
    mapping = mapping or {}
    staged = [f for f in files_under(stage) if not f.endswith(".PATCHES.md")]
    report = {"live": live, "stage": stage, "files": {}, "not_rebuilt": [], "kept": [], "keep_conflicts": []}
    touched = set()
    for rel in staged:
        live_rel = live_name(mapping, rel)
        live_path = os.path.join(live, live_rel)
        entry = compare_file(live_path, os.path.join(stage, rel))
        entry["live_file"] = live_rel
        for other in [live_rel] + duplicates(mapping, rel) + [rel]:
            side = sidecar(os.path.join(live, other))
            if side and os.path.exists(side):
                entry["patches_sidecar"] = os.path.relpath(side, live).replace(os.sep, "/")
                break
        report["files"][rel] = entry
        if kept_by(live_rel, keep) and entry["status"] != "new":
            report["keep_conflicts"].append(rel)
        touched.add(os.path.dirname(live_rel))
    produced = {e["live_file"] for e in report["files"].values()}
    produced |= {d for rel in report["files"] for d in duplicates(mapping, rel)}
    for folder in sorted(touched):
        base = os.path.join(live, folder)
        if not os.path.isdir(base):
            continue
        for name in sorted(os.listdir(base)):
            rel = os.path.normpath(os.path.join(folder, name)).replace(os.sep, "/")
            if os.path.isfile(os.path.join(base, name)) and rel not in produced and not name.endswith(".PATCHES.md"):
                source = kept_by(rel, keep)
                if source:
                    report["kept"].append({"file": rel, "source": source})
                else:
                    report["not_rebuilt"].append(rel)
    return report


def needs_review(entry):
    return entry["status"] != "same" and (
        entry.get("hand_facts_dropped") or entry.get("patches_sidecar") or entry.get("headings_gone"))


def markdown(report):
    files = report["files"]
    by = {s: sorted(r for r, e in files.items() if e["status"] == s) for s in ("new", "changed", "same")}
    out = ["# Knowledge-base rebuild comparison", "",
           "Live: `%s`  " % report["live"], "Staged: `%s`" % report["stage"], "",
           "| Staged files | New | Changed | Same | Live files not rebuilt |",
           "|---|---|---|---|---|",
           "| %d | %d | %d | %d | %d |" % (len(files), len(by["new"]), len(by["changed"]), len(by["same"]),
                                         len(report["not_rebuilt"])), ""]
    flagged = [r for r in by["changed"] if needs_review(files[r])]
    if report.get("keep_conflicts"):
        out += ["## Don't replace: these live files are on the keep list", "",
                "No prompt builds them, so the staged copy must not replace them.", ""]
        out += ["- `%s`" % r for r in report["keep_conflicts"]] + [""]
    out += ["## Check these first", ""]
    if not flagged:
        out.append("No changed file drops a hand-supplied fact or a section, or has a patch sidecar.")
    for rel in flagged:
        e = files[rel]
        out.append("### `%s`" % rel)
        if e.get("patches_sidecar"):
            out.append("- Has hand patches in `%s`: confirm each entry is in the staged copy." % e["patches_sidecar"])
        for f in e.get("hand_facts_dropped", []):
            out.append("- Dropped a hand-supplied fact: `%s`" % f[:200])
        if e.get("title_lines_gone"):
            out.append("- Title-block lines gone (no text under them): %s" % "; ".join(
                t[:60] for t in e["title_lines_gone"]))
        for g in e.get("sections_gone", []):
            if g.get("title_line"):
                continue
            if g["terms_kept_pct"] is None:
                out.append("- Section gone: %s (no names or numbers in it to trace)" % g["heading"])
            else:
                out.append("- Section gone: %s (%d%% of its %d names and numbers appear elsewhere in the staged copy)"
                           % (g["heading"], g["terms_kept_pct"], g["terms"]))
        if e.get("headings_renamed"):
            out.append("- Renamed, content kept under the new title: %d section(s)" % len(e["headings_renamed"]))
            for o, n in e["headings_renamed"]:
                out.append("  - %s -> %s" % (o, n))
        out.append("")
    out += ["", "## Changed", "",
            "| File | Lines + / - | Sections new / renamed / gone | [E] live -> staged | [A] | [?] | Old-style tags live -> staged |",
            "|---|---|---|---|---|---|---|"]
    for rel in by["changed"]:
        e = files[rel]
        tl, ts = e["tags_live"], e["tags_staged"]
        out.append("| `%s` | %d / %d | %d / %d / %d | %d -> %d | %d -> %d | %d -> %d | %d -> %d |" % (
            rel, e["lines_added"], e["lines_removed"], len(e["headings_new"]), len(e.get("headings_renamed", [])),
            len(e["headings_gone"]),
            tl["evidence"], ts["evidence"], tl["assumption"], ts["assumption"], tl["unknown"], ts["unknown"],
            tl["old_style"], ts["old_style"]))
    out += ["", "## New (no live copy)", ""] + (["- `%s`" % r for r in by["new"]] or ["None."])
    out += ["", "## Same", ""] + (["- `%s`" % r for r in by["same"]] or ["None."])
    out += ["", "## Live files in the same folders that the rebuild did not produce", "",
            "Each needs a decision: keep as is (not built by a prompt), retire, or rebuild.", ""]
    out += ["- `%s`" % r for r in report["not_rebuilt"]] or ["None."]
    if report.get("kept"):
        out += ["", "## Kept as they are (on the keep list, not built by a prompt)", "",
                "| File | Where it came from |", "|---|---|"]
        out += ["| `%s` | %s |" % (k["file"], k["source"]) for k in report["kept"]]
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("live")
    ap.add_argument("stage")
    ap.add_argument("--map", help="YAML mapping of staged relative path to live relative path")
    ap.add_argument("--keep", help="YAML list of live files no prompt builds, to keep as they are")
    ap.add_argument("--out", help="write the Markdown report to this file")
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    args = ap.parse_args(argv)
    for d in (args.live, args.stage):
        if not os.path.isdir(d):
            print("not a folder: %s" % d, file=sys.stderr)
            return 2
    mapping = {}
    if args.map:
        with open(args.map, encoding="utf-8") as fh:
            mapping = yaml.safe_load(fh) or {}
    report = compare(args.live, args.stage, mapping, load_keep(args.keep) if args.keep else None)
    text = json.dumps(report, indent=2) if args.json else markdown(report)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print("wrote %s" % args.out)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
