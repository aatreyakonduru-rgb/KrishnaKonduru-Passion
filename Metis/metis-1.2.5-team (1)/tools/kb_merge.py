#!/usr/bin/env python3
"""Merge a staged knowledge-base document into the live one without losing what the live one said.

    python3 kb_merge.py LIVE STAGED --out MERGED [--also OLD ...] [--archived-as PATH] [--json]

Markdown. The staged copy, rebuilt from the source, becomes the body, unchanged. Below it,
under "## Kept from the previous version", come the lines of the live copy (and of any --also
copy, such as a duplicate of the same document) that the staged copy does not already cover,
with their headings two levels lower:

  - a line the staged copy has word for word is left out;
  - a line the staged copy's "What changed from the previous ..." table contradicts is always
    kept, and marked **Corrected** with what the source says today. A row matches a line when
    every `quoted` name in its "previous" cell is on the line exactly (else every name and
    number, else every longer word, ignoring case); "a; b" in a cell is two claims;
  - any other line is left out when the staged copy already says it: the same line appears
    there, or the line has at least two names or numbers, one of them not a bare number, and
    every one of them appears in the staged copy. Lines without that evidence are kept;
  - kept lines were not re-checked in this rebuild, and the section says so;
  - an old section that the staged copy covers under another title points to that title.

YAML. The staged text is kept as it is. A top-level key, a sub-key or a list item that only the
live copy has is added under `kept_from_previous_version:`. A value the rebuild changed is not
kept: the old one is in the archive.

The full live copy is never needed in the merged file: kb_promote.py archives it first, and
--archived-as names that copy in the kept section. Merging the same rebuild again changes
nothing, and a later merge does not nest the kept sections. Only --out is written.
"""
import argparse
import json
import re
import sys

import yaml

import kb_compare

KEPT = "Kept from the previous version"
YAML_KEPT = "kept_from_previous_version"
CHANGED = re.compile(r"^#{1,6}\s+(?:[A-Z]?\d+[.)]?\s+)?What changed from the previous\b.*$", re.M | re.I)
FENCE = re.compile(r"^\s*(```|~~~)")
HEAD = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
WORD = re.compile(r"[a-z][a-z0-9_]{4,}")
NUMBER = re.compile(r"^\d+(?:[.,]\d+)?$")
FILLER = {"there", "their", "which", "where", "these", "those", "about", "being", "every", "would",
          "could", "should", "previous", "server"}


def intro(archived_as):
    where = " The full previous version is kept in `%s`." % archived_as if archived_as else ""
    return ("These lines come from the previous version of this document, and the version above does "
            "not already say them. They were not re-checked against the source in this rebuild, so treat "
            "each one as unverified until someone checks it. A line the source now contradicts is marked "
            "**Corrected**, with what the source says today. Headings are two levels lower than above."
            + where)


def dashes(text):
    return text.replace("\u2013", "-").replace("\u2014", "-")


def corrections(staged):
    """[(old claim, source today)] from the staged copy's "What changed" table."""
    m = CHANGED.search(staged)
    if not m:
        return []
    rows = []
    for line in staged[m.end():].splitlines():
        if line.startswith("#"):
            break
        if not line.lstrip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2 or set(cells[0]) <= set("-: "):
            continue
        rows.append((cells[0], cells[1]))
    return rows[1:] if rows and rows[0][0].lower().startswith("previous") else rows


def keys(claim):
    """(names that must appear exactly, words that must appear in any case) for one claim."""
    exact = [dashes(t.rstrip("*")) for t in re.findall(r"`([^`\n]+)`", claim) if t.rstrip("*")]
    if exact:
        return exact, []
    found = [dashes(t.rstrip("*")) for t in kb_compare.terms(claim) if t.rstrip("*")]
    if found:
        return found, []
    words = [w for w in WORD.findall(claim.lower()) if w not in FILLER] or WORD.findall(claim.lower())
    return [], words


def matches(line, key):
    exact, words = key
    if not exact and not words:
        return False
    text = dashes(line)
    return all(t in text for t in exact) and all(w in text.lower() for w in words)


def mark(line, today):
    note = " **Corrected:** the source today says: %s." % today.rstrip(".")
    if line.rstrip().endswith("|") and line.lstrip().startswith("|"):
        return line.rstrip()[:-1].rstrip() + note + " |"
    return line.rstrip() + note


def covered(line, staged_lines, staged_terms):
    if line.strip() in staged_lines:
        return True
    t = kb_compare.terms(line)
    return (len(t) >= 2 and any(not NUMBER.match(x) for x in t)
            and all(x in staged_terms for x in t))


def is_table_rule(line):
    return line.lstrip().startswith("|") and set(line.strip()) <= set("|-: ")


def kept_lines(old, staged, rows, renamed, stats):
    """The lines of `old` to keep, with headings demoted and pointers to renamed sections."""
    staged_lines = {l.strip() for l in staged.splitlines() if l.strip()}
    staged_terms = kb_compare.terms(staged)
    out, pending, table_head, block = [], [], [], []
    state = {"fenced": False, "gap": False, "row": 0}

    def put(line):
        if state["gap"] and out and out[-1] != "":
            out.append("")
        state["gap"] = False
        out.append(line)

    def flush():
        for level, text in pending:
            state["gap"] = True
            put("#" * min(6, level + 2) + " " + text)
            state["gap"] = True
            if text in renamed:
                put("*Now covered above under \"%s\".*" % renamed[text])
                state["gap"] = True
        pending.clear()
        for line in table_head:
            put(line)
        table_head.clear()

    lines = old.splitlines()
    if lines and lines[0].strip() == "---" and "---" in [l.strip() for l in lines[1:]]:
        end = [l.strip() for l in lines[1:]].index("---") + 2
        stats["left_out"] += end
        lines = lines[end:]
    for line in lines:
        if FENCE.match(line) or state["fenced"]:
            block.append(line)
            if FENCE.match(line):
                state["fenced"] = not state["fenced"]
            if not state["fenced"]:
                if "\n".join(block).strip() in staged:
                    stats["left_out"] += len(block)
                else:
                    flush()
                    state["gap"] = True
                    for b in block:
                        put(b)
                    state["gap"] = True
                    stats["kept"] += len(block)
                block = []
            continue
        h = HEAD.match(line)
        if h:
            level = len(h.group(1))
            while pending and pending[-1][0] >= level:
                pending.pop()
            pending.append((level, h.group(2)))
            table_head.clear()
            state["row"] = 0
            continue
        if not line.strip() or set(line.strip()) <= set("-*_"):
            table_head.clear()
            state["row"] = 0
            state["gap"] = True
            continue
        if line.lstrip().startswith("|"):
            state["row"] += 1
            if state["row"] == 1 or (state["row"] == 2 and is_table_rule(line)):
                table_head.append(line)
                continue
        else:
            state["row"] = 0
            table_head.clear()
        if line.strip() in staged_lines:
            stats["left_out"] += 1
            continue
        hit = []
        for old_claim, today, ks in rows:
            if any(matches(line, k) for k in ks):
                stats["corrections"][old_claim] += 1
                hit.append(today)
        if hit:
            for today in hit:
                line = mark(line, today)
        elif covered(line, staged_lines, staged_terms):
            stats["left_out"] += 1
            continue
        flush()
        put(line)
        stats["kept"] += 1
    return out


def merge(live, staged, also=(), archived_as=None):
    """Return (merged text, report). `also` is [(name, text)] of further old copies."""
    head, _, earlier = live.partition("\n## %s\n" % KEPT)
    if head.strip() == staged.strip() and not also:
        return live, {"already_merged": True}
    rows = [(o, t, [keys(c) for c in o.split(";") if c.strip()]) for o, t in corrections(staged)]
    stats = {"kept": 0, "left_out": 0, "corrections": {o: 0 for o, _, _ in rows}}
    parts = []
    for name, text in [(None, head)] + list(also):
        renamed = dict(kb_compare.match_sections(text, staged)[0])
        lines = kept_lines(text, staged, rows, renamed, stats)
        if lines and name:
            lines = ["**From the duplicate copy `%s`:**" % name, ""] + lines
        if lines:
            parts.append("\n".join(lines).strip())
    earlier = earlier.strip()
    if earlier.startswith("These lines come from the previous version"):
        earlier = earlier.split("\n\n", 1)[1] if "\n\n" in earlier else ""
    if earlier:
        parts.append(earlier.strip())
    if not parts:
        return staged, stats
    merged = "%s\n\n## %s\n\n%s\n\n%s\n" % (staged.rstrip(), KEPT, intro(archived_as), "\n\n".join(parts))
    return merged, stats


def _only_in_old(old, new):
    if isinstance(old, dict) and isinstance(new, dict):
        out = {}
        for k, v in old.items():
            if k not in new:
                out[k] = v
            elif isinstance(v, (dict, list)):
                sub = _only_in_old(v, new[k])
                if sub:
                    out[k] = sub
        return out
    if isinstance(old, list) and isinstance(new, list):
        seen = {json.dumps(x, sort_keys=True, default=str) for x in new}
        return [x for x in old if json.dumps(x, sort_keys=True, default=str) not in seen]
    return None


def merge_yaml(live, staged, archived_as=None):
    old, new = yaml.safe_load(live) or {}, yaml.safe_load(staged) or {}
    if isinstance(old, dict):
        old.pop(YAML_KEPT, None)
    extra = _only_in_old(old, new) if isinstance(old, dict) and isinstance(new, dict) else None
    earlier = (yaml.safe_load(live) or {}).get(YAML_KEPT) if isinstance(yaml.safe_load(live), dict) else None
    if isinstance(earlier, dict):
        for k, v in earlier.items():
            if k != "note" and k not in (extra or {}):
                extra = extra or {}
                extra[k] = v
    if not extra:
        return staged, {"kept_keys": []}
    note = ("Only in the previous version and not re-checked in this rebuild; treat as unverified. "
            + ("Full previous version: %s" % archived_as if archived_as else ""))
    block = yaml.safe_dump({YAML_KEPT: dict({"note": note.strip()}, **extra)}, sort_keys=False,
                           allow_unicode=True, width=120)
    return staged.rstrip() + "\n\n# %s\n%s" % (KEPT, block), {"kept_keys": list(extra)}


def merge_file(live_text, staged_text, path, also=(), archived_as=None):
    if path.lower().endswith(".md"):
        return merge(live_text, staged_text, also, archived_as)
    if path.lower().endswith((".yaml", ".yml")):
        return merge_yaml(live_text, staged_text, archived_as)
    return staged_text, {"replaced": True}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("live")
    ap.add_argument("staged")
    ap.add_argument("--out", required=True)
    ap.add_argument("--also", nargs="*", default=[], help="further old copies of the same document")
    ap.add_argument("--archived-as", help="where the full previous version is archived")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    also = [(p, kb_compare.read(p)) for p in args.also]
    merged, report = merge_file(kb_compare.read(args.live), kb_compare.read(args.staged), args.live,
                                also, args.archived_as)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(merged)
    print(json.dumps(report, indent=2, default=str) if args.json else
          "\n".join("%s: %s" % kv for kv in report.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
