"""Counts the docs repeat (tests, screens, tools, skills), taken from the code, and a check that the docs agree.

    python3 doc_metrics.py show                 print the counts
    python3 doc_metrics.py check [--docs <dir>]  exit 1 when a metrics block in a doc is out of date
    python3 doc_metrics.py write [--docs <dir>]  rewrite the metrics blocks in place

A doc opts in with a block (kept in sync by `write`, verified by `check`):

    <!-- metrics:begin -->
    ...generated lines...
    <!-- metrics:end -->

`check` also lists, as advice only, loose numbers in the same docs ("954 tests", "27 screens") that differ from the code.
Older lines in a progress log are history and may rightly differ, so those do not fail the check.
Counts: tests = test cases unittest discovers in tools/tests (skips are counted by the run, not here); screens = paths in
ui/server.SCREENS; tools = top-level tools/*.py; skills = skills/*/SKILL.md. Standard library only.
"""
import argparse
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.abspath(os.path.join(HERE, ".."))
DEFAULT_DOCS = os.path.abspath(os.path.join(PLUGIN, "..", "documentation"))
EXTRA_DOCS = [os.path.abspath(os.path.join(PLUGIN, "..", "Metis-2.0.0-Release-Record.md"))]
BEGIN, END = "<!-- metrics:begin -->", "<!-- metrics:end -->"
LOOSE = {"tests": re.compile(r"\b(\d{3,5}) tests\b"), "screens": re.compile(r"\b(\d{1,3}) screens\b")}
BLOCK = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.S)


def count():
    sys.path[:0] = [HERE, os.path.join(HERE, "ui")]
    tests_dir = os.path.join(HERE, "tests")
    suite = unittest.defaultTestLoader.discover(tests_dir, pattern="test_*.py", top_level_dir=HERE)
    screens = None
    try:
        import server  # noqa: E402
        screens = len(server.SCREENS)
    except Exception:
        pass
    return {
        "tests": suite.countTestCases(),
        "screens": screens,
        "tools": len([f for f in os.listdir(HERE) if f.endswith(".py")]),
        "skills": len([d for d in os.listdir(os.path.join(PLUGIN, "skills"))
                       if os.path.isfile(os.path.join(PLUGIN, "skills", d, "SKILL.md"))]),
    }


def block(m):
    return "\n".join([
        BEGIN,
        "Counted from the code by `tools/doc_metrics.py`; run `python3 doc_metrics.py write` to refresh.",
        "- Tests discovered: %s" % m["tests"],
        "- UI screens (paths in `server.SCREENS`): %s" % m["screens"],
        "- Tools (`tools/*.py`): %s" % m["tools"],
        "- Skills: %s" % m["skills"],
        END])


def doc_files(docs):
    out = []
    for root, _d, files in os.walk(docs):
        out += [os.path.join(root, f) for f in files if f.endswith(".md")]
    return out + [p for p in EXTRA_DOCS if os.path.isfile(p) and p not in out]


def read(p):
    with open(p, encoding="utf-8", newline="") as fh:
        return fh.read()


def check(m, docs):
    stale, advice = [], []
    want = block(m)
    for p in doc_files(docs):
        norm = read(p).replace("\r\n", "\n")
        if any(found != want for found in BLOCK.findall(norm)):
            stale.append(p)
        for key, rx in LOOSE.items():
            for n in set(rx.findall(norm)):
                if m.get(key) is not None and int(n) != m[key]:
                    advice.append("%s: says %s %s, code has %s" % (os.path.basename(p), n, key, m[key]))
    return stale, sorted(set(advice))


def write(m, docs):
    changed, want = [], block(m)
    for p in doc_files(docs):
        text = read(p)
        crlf = "\r\n" in text
        norm = text.replace("\r\n", "\n")
        new = BLOCK.sub(lambda _m: want, norm)
        if new != norm:
            with open(p, "w", encoding="utf-8", newline="") as fh:
                fh.write(new.replace("\n", "\r\n") if crlf else new)
            changed.append(p)
    return changed


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=["show", "check", "write"])
    ap.add_argument("--docs", default=DEFAULT_DOCS)
    a = ap.parse_args(argv)
    m = count()
    if a.cmd == "show":
        for k, v in m.items():
            print("%-8s %s" % (k, v))
        return 0
    if a.cmd == "write":
        for p in write(m, a.docs):
            print("updated", p)
        return 0
    stale, advice = check(m, a.docs)
    for p in stale:
        print("STALE metrics block:", p)
    for line in advice:
        print("advice:", line)
    print("%d stale block(s), %d loose number(s) differ from the code" % (len(stale), len(advice)))
    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main())
