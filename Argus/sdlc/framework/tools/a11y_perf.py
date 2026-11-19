#!/usr/bin/env python3
"""Accessibility and performance checks for the pages a story changes, run by /eval.

    a11y_perf.py run    --story REQ-X-STORY-n --url URL [--url URL ...] [--out FILE]
    a11y_perf.py report --story REQ-X-STORY-n --result result.json [...] [--out FILE]

`run` opens each URL in the Devin machine's Chrome (a11y_perf.mjs over CDP port 29229), checks alt text, form
labels, button and link names, page language, heading order and duplicate ids, and reads load time, largest
contentful paint, request count and transfer size. Limits are in .devin/rules/a11y-perf.yaml. Writes
{story}-A11Y-PERF.md with PASS or FAIL; a page that could not be read is listed, never passed.
"""
import argparse
import collections
import json
import os
import subprocess
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
RULES = os.path.join(ROOT, ".devin", "rules", "a11y-perf.yaml")
PERF_LABELS = {"lcp_ms": "Largest contentful paint (ms)", "load_ms": "Load (ms)",
               "transfer_kb": "Transferred (KB)", "requests": "Requests"}


def load_rules(path=RULES):
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def grade(result, rules):
    """{"url", "status", "blocking", "warnings", "perf": [(metric, value, limit, ok)], "error"} for one page."""
    if result.get("error") or "findings" not in result:
        return {"url": result.get("url", ""), "status": "NOT READ", "blocking": [], "warnings": [], "perf": [],
                "error": result.get("error") or "no result"}
    a = rules.get("accessibility") or {}
    blocking = [f for f in result["findings"] if f["rule"] in (a.get("blocking") or [])]
    warnings = [f for f in result["findings"] if f["rule"] not in (a.get("blocking") or [])]
    perf = []
    for metric, limit in (rules.get("performance") or {}).items():
        value = (result.get("perf") or {}).get(metric)
        perf.append((metric, value, limit, value is not None and value <= limit))
    ok = not blocking and all(p[3] for p in perf)
    return {"url": result.get("url", ""), "status": "PASS" if ok else "FAIL", "blocking": blocking,
            "warnings": warnings, "perf": perf, "error": ""}


def overall(pages):
    if not pages or any(p["status"] == "NOT READ" for p in pages):
        return "INCOMPLETE"
    return "PASS" if all(p["status"] == "PASS" for p in pages) else "FAIL"


def render(story, pages):
    lines = ["# %s — Accessibility and performance" % story, "",
             "## Overall Status: %s" % overall(pages), ""]
    for p in pages:
        lines += ["## %s — %s" % (p["url"], p["status"]), ""]
        if p["error"]:
            lines += ["Could not be read: %s" % p["error"], ""]
            continue
        lines += ["| Measure | Value | Limit | Result |", "|---|---|---|---|"]
        lines += ["| %s | %s | %s | %s |" % (PERF_LABELS.get(m, m), "—" if v is None else v, lim, "ok" if ok else "over")
                  for m, v, lim, ok in p["perf"]]
        lines.append("")
        for title, items in (("Blocking accessibility findings", p["blocking"]), ("Warnings", p["warnings"])):
            counts = collections.Counter(f["rule"] for f in items)
            lines.append("**%s:** %s" % (title, ", ".join("%s (%d)" % c for c in sorted(counts.items())) or "none"))
            lines += ["- `%s`: %s — `%s`" % (f["rule"], f["message"], f["element"].replace("`", "'")) for f in items[:20]]
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def read_page(url, port="29229"):
    try:
        out = subprocess.run(["node", "--experimental-websocket", os.path.join(HERE, "a11y_perf.mjs"), url, port],
                             capture_output=True, text=True, timeout=90)
        return json.loads(out.stdout.strip().splitlines()[-1])
    except (subprocess.SubprocessError, OSError, ValueError, IndexError) as exc:
        return {"url": url, "error": "%s" % exc}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--url", action="append", required=True)
    r.add_argument("--port", default="29229")
    p = sub.add_parser("report")
    p.add_argument("--result", action="append", required=True)
    for s in (r, p):
        s.add_argument("--story", required=True)
        s.add_argument("--out", default="")
    a = ap.parse_args(argv)
    rules = load_rules()
    if a.cmd == "run":
        results = [read_page(u, a.port) for u in a.url]
    else:
        results = []
        for path in a.result:
            with open(path, encoding="utf-8") as fh:
                results.append(json.load(fh))
    pages = [grade(x, rules) for x in results]
    text = render(a.story, pages)
    out = a.out or "%s-A11Y-PERF.md" % a.story
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(text)
    print("[SDLC] a11y/perf %s: %s -> %s" % (a.story, overall(pages), out))
    return 0 if overall(pages) == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
