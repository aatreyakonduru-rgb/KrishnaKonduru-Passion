#!/usr/bin/env python3
"""Keep the cross-layer matrix, the QA-suite coverage, the ontology, the link graph and the KB manifest in step with the code.

Run on the PR branch before the PR (/implement), and with --check in /pr-readiness and the pre-push
hook. Bitbucket does not tell Devin when a PR merges, so this runs before the merge; KB documents
that need Snowflake are reported "after merge" and /kb-refresh rebuilds them after deployment.

    python3 sdlc/framework/tools/kb_sync.py [--base origin/feature/devin-sdlc]
    python3 sdlc/framework/tools/kb_sync.py --check [--base REF]   # exit 1 when stale

Prints one `[SDLC] sync` line per artefact and one `[SDLC] drift` line for Argus Trace.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "kbgen"))

import gen_link_graph  # noqa: E402
import gen_qa_suite  # noqa: E402
import link_graph  # noqa: E402
import ontology_lookup  # noqa: E402

REPO = gen_link_graph.REPO
KB = gen_link_graph.KB
MATRIX = KB + "/CROSS-LAYER/CROSS_LAYER_IMPACT_MATRIX.yaml"
ONTOLOGY = KB + "/CROSS-LAYER/ACME_ONTOLOGY.yaml"
MATRIX_GEN = "sdlc/framework/tools/kbgen/gen_cross_module_matrix.py"
ONTOLOGY_GEN = "sdlc/framework/tools/kbgen/gen_ontology.py"
MANIFEST_TOOL = "sdlc/framework/tools/kb_manifest.py"


def run(*args):
    return subprocess.run([sys.executable] + list(args), capture_output=True, text=True, cwd=REPO)


def same(a, b):
    try:
        with open(a, encoding="utf-8") as x, open(b, encoding="utf-8") as y:
            return gen_link_graph.body(x.read()) == gen_link_graph.body(y.read())
    except OSError:
        return False


def matrix_step(check):
    fd, tmp = tempfile.mkstemp(suffix=".yaml")
    os.close(fd)
    try:
        r = run(MATRIX_GEN, "--out", tmp)
        if r.returncode != 0:
            return "not run", "the generator failed: %s" % (r.stderr.strip().splitlines() or ["?"])[-1]
        if same(tmp, os.path.join(REPO, MATRIX)):
            return "current", "no difference from the code and registries"
        if check:
            return "stale", "the code or registries changed; run python3 sdlc/framework/tools/kb_sync.py"
        os.replace(tmp, os.path.join(REPO, MATRIX))
        return "updated", "rebuilt from the code and registries"
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def qa_step(check):
    return gen_qa_suite.run(check)


def ontology_step(check):
    res = ontology_lookup.check()
    if res.get("fresh"):
        return "current", "no difference from the KB registries and the matrix"
    if check:
        return "stale", res.get("fix") or res.get("error") or "rebuild needed"
    r = run(ONTOLOGY_GEN)
    if r.returncode != 0:
        return "not run", "the generator failed: %s" % (r.stderr.strip().splitlines() or ["?"])[-1]
    return "updated", "rebuilt the YAML and the HTML page"


def graph_step(check):
    res = gen_link_graph.check()
    if res["fresh"] is None:
        if check:
            return "not run", res["error"]
    elif res["fresh"]:
        return "current", "no difference from the ontology, matrix, test imports and story commits"
    elif check:
        return "stale", res.get("fix") or res.get("error")
    gen_link_graph.main([])
    return "updated", "rebuilt from the ontology, matrix, test imports and story commits"


def manifest_step(check):
    r = run(MANIFEST_TOOL, "validate")
    if r.returncode == 0:
        return "current", "every KB file matches its size and hash"
    if check:
        return "stale", "run python3 %s generate" % MANIFEST_TOOL
    r = run(MANIFEST_TOOL, "generate")
    return ("updated", r.stdout.strip()) if r.returncode == 0 else ("not run", r.stderr.strip()[-200:])


STEPS = [
    ("CROSS_LAYER_IMPACT_MATRIX.yaml", matrix_step, "the matrix is read from the code; a PR that moves code moves it"),
    ("03_QA_SUITE_COVERAGE.yaml", qa_step, "the QA-suite coverage is read from claims-qa, read only; the ontology copies its counts"),
    ("ACME_ONTOLOGY.yaml", ontology_step, "the ontology reads the registries and the matrix"),
    ("ACME_LINK_GRAPH.yaml", graph_step, "the graph is built from the ontology, matrix, tests and commits"),
    ("KNOWLEDGE-MANIFEST.yaml", manifest_step, "the manifest pins every KB file the steps above may have changed"),
]


def sync(check=False, base=None):
    files = ontology_lookup.changed_files(base) if base else []
    rows = []
    for name, step, why in STEPS:
        result, detail = step(check)
        rows.append({"artifact": name, "result": result, "detail": detail, "why": why})
    touches = ontology_lookup.Ontology(ontology_lookup.load()).touches(files) if files else None
    if touches and touches.get("verdict") == "after-merge":
        rows.append({"artifact": "KB documents built from Snowflake", "result": "not run",
                     "detail": "code changed; DB-DOCS that need Snowflake are rebuilt after deployment by /kb-refresh",
                     "why": touches.get("what_to_do") or ""})
    drift = link_graph.Graph(link_graph.load()).drift(files) if files else None
    stale = [r for r in rows if r["result"] == "stale"] or (drift and drift["verdict"] == "stale")
    return {"check": check, "base": base, "files": files, "rows": rows, "drift": drift, "ok": not stale}


def trace_lines(res):
    out = []
    for r in res["rows"]:
        action = ("compared with a fresh build" if res["check"] else "regenerated") + ": " + r["detail"]
        out.append("[SDLC] sync %s — %s; why: %s; result: %s" % (r["artifact"], action, r["why"], r["result"]))
    d = res["drift"]
    if d is not None:
        out.append("[SDLC] drift ACME_LINK_GRAPH.yaml — re-read %d cited lines in %d changed files %s; why: links the change "
                   "relies on must still match the code; result: %s" % (d["checked"], len(res["files"]), json.dumps(d["summary"]), d["verdict"]))
    elif res["base"] and not res["files"]:
        out.append("[SDLC] drift ACME_LINK_GRAPH.yaml — no committed change against %s; why: drift is checked for the files a "
                   "branch changes; result: current" % res["base"])
    elif res["base"] is None:
        out.append("[SDLC] drift ACME_LINK_GRAPH.yaml — no --base given; why: drift is checked for the files a branch changes; result: not run")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="change nothing; exit 1 when an artefact is stale")
    ap.add_argument("--base", help="compare with this ref to find the changed files (e.g. origin/feature/devin-sdlc)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    res = sync(a.check, a.base)
    if a.json:
        print(json.dumps(res, indent=1, default=str))
    else:
        print("\n".join(trace_lines(res)))
        for r in (res["drift"] or {}).get("rows", []):
            if r["status"] in ("stale", "missing", "moved"):
                print("  %s %s [%s] %s" % (r["status"], r["link"], r["source"], r["why"]))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
