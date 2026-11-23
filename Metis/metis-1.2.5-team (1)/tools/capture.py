#!/usr/bin/env python3
"""Capture a note or snippet someone pastes (a chat line, an email paragraph, something said in a meeting) as a KB page
that keeps its source. Nothing is summarised or reworded: each line the person gave becomes one fact line, and the
exact text is kept as a supplied file the line's source tag points at.

    python3 capture.py add <kb> --title "<page title>" --by "<who captured it>" --source "<where it came from>"
                          (--text "<snippet>" | --file <text file> | --stdin)

What it writes:
    <kb>/_EVIDENCE/files/capture-<date>-<slug>.txt   the snippet, as given
    <kb>/context/captures/<slug>.md                  one fact line per snippet line:  - <line> [E: file:<name> "<quote>"]
                                                     with a Sources section: who captured it, when, and from where

When the lead gate is closed the page goes to _PENDING/<batch>/ for a lead to certify (the snippet file is evidence, which the
gate does not govern). Before the gate is closed the page is written straight into the KB.

Refuses, and writes nothing, when the snippet looks like a password, key, card number or SSN, when a line has no stretch of
text that can be quoted (a line made only of ] ; or " characters), or when the finished page fails the same source check
verify_kb.py runs. A line is not checked for being true: the page says who gave this text, not that it is right.
"""
import argparse
import datetime
import os
import re
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kb_gate  # noqa: E402
import sensitive  # noqa: E402

GENERATOR = "capture.py"
FOLDER = "context/captures"
UNQUOTABLE = re.compile(r'[\];"]')


class CaptureError(ValueError):
    pass


def quote_of(line):
    """The longest stretch of the line that the tag syntax can carry (no ] ; or "), or None."""
    best = max((p.strip() for p in UNQUOTABLE.split(line)), key=len, default="")
    return best if len(best) >= 3 else None


def unique(kb, rel_dir, stem, ext):
    n, name = 1, stem
    while os.path.exists(os.path.join(kb, rel_dir, name + ext)):
        n += 1
        name = "%s-%d" % (stem, n)
    return name


def build(title, by, source, evidence_name, lines, today):
    head = yaml.safe_dump({"title": title, "generated_by": GENERATOR, "captured_by": by, "captured_on": today,
                           "source": source}, sort_keys=False, allow_unicode=True).rstrip()
    out = ["---", head, "---", "", "# %s" % title, ""]
    for line in lines:
        out.append('- %s [E: file:%s "%s"]' % (line, evidence_name, quote_of(line)))
    out += ["", "## Sources", "",
            "- Text given by %s on %s, from %s; kept exactly as given in `_EVIDENCE/files/%s`. Captured, not checked for accuracy." % (
                by, today, source, evidence_name)]
    return "\n".join(out) + "\n"


def add(kb, title, by, source, text):
    """Returns {page, evidence, staged_in or None, lines}. Raises CaptureError (nothing written) on any problem."""
    for label, val in (("a title", title), ("who captured it (--by)", by), ("where it came from (--source)", source)):
        if not (val or "").strip():
            raise CaptureError("say %s" % label)
    title, by, source = title.strip(), by.strip(), " ".join(source.split())
    text = (text or "").replace("\r\n", "\n")
    lines = [" ".join(ln.split()) for ln in text.split("\n") if ln.strip()]
    if not lines:
        raise CaptureError("nothing to capture: the text is empty")
    bad = ["line %d: looks like a %s" % (f["line"], f["kind"]) for f in sensitive.scan(text) if f["level"] == sensitive.BLOCK]
    if bad:
        raise CaptureError("take this out first, nothing was written: " + "; ".join(bad))
    for n, line in enumerate(lines, 1):
        if quote_of(line) is None:
            raise CaptureError("line %d has no text that can be quoted (only ] ; \" characters, or under 3 letters): %s" % (n, line[:40]))
    today = datetime.date.today().isoformat()
    stem = kb_gate.slug(title)
    ev_name = unique(kb, "_EVIDENCE/files", "capture-%s-%s" % (today, stem), ".txt") + ".txt"
    rel = "%s/%s.md" % (FOLDER, unique(kb, FOLDER, stem, ".md"))
    body = build(title, by, source, ev_name, lines, today)
    ev_path = os.path.join(kb, "_EVIDENCE", "files", ev_name)
    os.makedirs(os.path.dirname(ev_path), exist_ok=True)
    with open(ev_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    found, _ = kb_gate.source_problems(kb, rel, body)
    if found:
        os.remove(ev_path)
        raise CaptureError("the page failed the source check: " + "; ".join("%s (line %d)" % (p[2], p[1]) for p in found))
    batch = None
    if kb_gate.is_locked(kb):
        batch = kb_gate.new_batch(kb, "capture " + title)
        kb_gate.stage_text(kb, batch, rel, body)
    else:
        dst = os.path.join(kb, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(body)
    return {"page": rel, "evidence": "_EVIDENCE/files/" + ev_name, "staged_in": batch, "lines": len(lines)}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Capture a pasted note as a sourced KB page.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("kb")
    a.add_argument("--title", required=True)
    a.add_argument("--by", required=True)
    a.add_argument("--source", required=True)
    g = a.add_mutually_exclusive_group(required=True)
    g.add_argument("--text")
    g.add_argument("--file")
    g.add_argument("--stdin", action="store_true")
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)
    if args.text is not None:
        text = args.text
    elif args.file:
        with open(args.file, encoding="utf-8-sig", errors="replace") as fh:
            text = fh.read()
    else:
        text = sys.stdin.read()
    try:
        r = add(args.kb, args.title, args.by, args.source, text)
    except CaptureError as e:
        print("capture: %s" % e)
        return 1
    print("capture: %d lines -> %s (source kept in %s)" % (r["lines"], r["page"], r["evidence"]))
    if r["staged_in"]:
        print("capture: staged in batch %s, not in the KB yet. A lead must certify it." % r["staged_in"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
