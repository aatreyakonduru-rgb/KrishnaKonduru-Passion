#!/usr/bin/env python3
"""Pull a random sample of source tags so a person can check the tag really supports the line it sits on.

    python3 tag_audit.py <kb> [--n 25] [--seed 1] [-o AUDIT.md]

verify_kb.py proves a tag points at something that exists (and, when a quote is given, that the quote is there). It cannot
prove the source says what the line claims. This shows the line, the tag and the words at the source side by side for a
sample, so a lead or reviewer can judge it. Each entry has a blank "Verdict" for ok or wrong. Files that are generated from
other files (manifest, graph, matrix) are not sampled. The seed makes a sample repeatable; use a new one each review.
"""
import argparse
import os
import random
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import verify_kb  # noqa: E402

SKIP_DIRS = (".git", "_EVIDENCE", ".metis", "Archive", "_REGEN", "_PENDING", "_FEEDBACK", "_QUESTIONS", "VISUALIZATION", "CROSS-LAYER")
SKIP_FILES = ("KNOWLEDGE-MANIFEST.yaml",)


def source_text(chk, part):
    """The words at the source for one tag part, or None when they cannot be shown."""
    scheme, sep, rest = part.strip().partition(":")
    try:
        if sep and scheme == "kb":
            m = re.match(r'^([^:"\s]+)(?::(\d+)(?:-(\d+))?)?', rest.strip())
            lines = chk.lines(os.path.join(chk.kb, m.group(1)))
            a = int(m.group(2) or 1)
            b = int(m.group(3) or m.group(2) or min(len(lines), a + 4))
            return "\n".join(lines[a - 1:b])[:600]
        if sep and scheme == "file":
            name = rest.strip().split(' "')[0]
            return "\n".join(chk.lines(os.path.join(chk.kb, "_EVIDENCE", "files", name))[:8])[:600]
        if sep and scheme == "doc":
            m = re.match(r'^([\w.-]+)#(\S+)\s+"(.+)"$', rest.strip())
            return 'quote checked at %s#%s: "%s"' % m.groups() if m else None
        if sep and scheme in ("query", "confluence", "jira", "answer", "settings"):
            return None
        m = verify_kb.LINE_REF.match(part.strip())
        if m:
            path, err = chk.repo_path(m.group(1))
            if err:
                return None
            lines = chk.lines(path)
            a = int(m.group(2))
            b = int(m.group(3) or a)
            return "\n".join(lines[a - 1:b])[:600]
    except (OSError, AttributeError, ValueError, IndexError):
        return None
    return None


def candidates(kb):
    chk = verify_kb.Checker(kb)
    out = []
    for d, dirs, fs in os.walk(kb):
        dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS)
        for f in sorted(fs):
            if not f.endswith(".md") or f in SKIP_FILES:
                continue
            rel = os.path.relpath(os.path.join(d, f), kb).replace(os.sep, "/")
            with open(os.path.join(d, f), encoding="utf-8", errors="replace") as fh:
                in_code = False
                for n, line in enumerate(fh.read().splitlines(), 1):
                    if line.strip().startswith("```"):
                        in_code = not in_code
                        continue
                    if in_code:
                        continue
                    for kind, value in verify_kb.TAG.findall(line):
                        if kind == "E":
                            out.append((rel, n, line.strip(), value.strip()))
    return chk, out


def sample(kb, n=25, seed=1):
    chk, cands = candidates(kb)
    rnd = random.Random(seed)
    picked = rnd.sample(cands, min(n, len(cands)))
    rows = []
    for rel, ln, line, value in sorted(picked):
        shown = [(p.strip(), source_text(chk, p)) for p in value.split(";")]
        rows.append({"file": rel, "line": ln, "text": line, "tag": value, "sources": shown})
    return rows, len(cands)


def render(rows, total):
    L = ["# Tag audit", "",
         "%d of %d tagged lines. For each, read the line and the words at its source. Write ok if the source supports the line, "
         "or wrong and why. A wrong verdict means the page is rebuilt." % (len(rows), total), ""]
    for i, r in enumerate(rows, 1):
        L += ["## %d. %s line %d" % (i, r["file"], r["line"]), "", "Line: %s" % r["text"], "", "Tag: %s" % r["tag"], ""]
        for tag, text in r["sources"]:
            L += ["Source `%s`:" % tag, "", "```", text if text else "(not shown here; check %s by hand)" % tag.split(":")[0], "```", ""]
        L += ["Verdict: ", ""]
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("kb")
    ap.add_argument("--n", type=int, default=25)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("-o")
    a = ap.parse_args(argv)
    rows, total = sample(os.path.abspath(a.kb), a.n, a.seed)
    text = render(rows, total)
    if a.o:
        with open(a.o, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        print("Wrote %s (%d of %d tagged lines)" % (a.o, len(rows), total))
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
