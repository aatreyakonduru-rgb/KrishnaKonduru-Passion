#!/usr/bin/env python3
"""Checks that a code change rests on evidence, runs the tests its links reach, and keeps the data contract.

    confidence.py claims   CLAIMS.yaml [--today YYYY-MM-DD]       # /plan and /implement: every claim has a source
    confidence.py tests    [--base REF] [FILE ...] [--pack PACK]  # tests the link graph reaches from the change
    confidence.py required --pack PACK [--ran PATH ...]           # /eval, /pr-readiness: every selected test ran
    confidence.py contract [--base REF] [FILE ...]                # changed SQL against the table registry

A claims file lists what a plan relies on, each with its evidence:

    claims:
      - id: C1
        text: "PG_syncup.sql writes CL_PG_LOB"
        evidence: ["graph:job:PG_syncup.sql -writes-> table:CL_PG_LOB"]
      - id: C2
        text: "the LOB list is read in the contract provider view"
        evidence: ["api/apps/contractproviderconf/views.py:120"]
        expect: "CL_PG_LOB"

Evidence forms: path:line (the line exists; with `expect`, that text is within 3 lines of it),
path (the file exists), kb:<path>, graph:<node id>, graph:<from> -<type>-> <to>, chain:<DC-id>.
.devin/rules/confidence.yaml says until when an unverified claim only warns; after that date it
blocks SDLC_04. Every command prints [SDLC] trace lines (.devin/rules/workbench-trace.md); add
--json for the raw result. Checks that need Snowflake are reported "not run", never passed.
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import link_graph  # noqa: E402

REPO = link_graph.REPO
CONFIG = ".devin/rules/confidence.yaml"
REGISTRY = "docs/knowledge-base/DB-DOCS/DB_TABLE_REGISTRY.yaml"
WINDOW = 3
TEST_NAME = re.compile(r"(^|/)(test_[^/]*\.py|[^/]*\.test\.(ts|tsx|js|jsx)|[^/]*_test\.py)$")
EDGE_REF = re.compile(r"^(\S+)\s+-(\w+)->\s+(\S+)$")
WORD = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b")
TABLE_CTX = re.compile(r"\b(?:FROM|JOIN|INTO|UPDATE|TABLE)\s+(?:\w+\.){0,2}([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)\b")
SQL_EXT = (".sql", ".py")
ASSIGN = re.compile(r"\b([A-Z][A-Z0-9_]+)\s*=\s*('[^']*'|-?\d+(?:\.\d+)?)")


def rel(path):
    return os.path.relpath(os.path.join(REPO, path), REPO)


def read_lines(path):
    try:
        with open(os.path.join(REPO, path), encoding="utf-8", errors="replace") as fh:
            return fh.read().splitlines()
    except OSError:
        return None


def config():
    try:
        with open(os.path.join(REPO, CONFIG)) as fh:
            return yaml.safe_load(fh) or {}
    except OSError:
        return {}


def git(*args):
    try:
        return subprocess.run(["git", "-C", REPO] + list(args), capture_output=True, text=True, check=True).stdout
    except (subprocess.CalledProcessError, OSError):
        return None


def changed_files(base, files):
    if files:
        return sorted(set(files)), None
    if not base:
        return [], "no --base and no files"
    out = git("diff", "--name-only", "%s...HEAD" % base)
    if out is None:
        return [], "%s is not in this clone" % base
    return sorted(f for f in out.splitlines() if f), None


# ---- claims -------------------------------------------------------------------------------------

def check_evidence(ref, expect, graph):
    ref = str(ref).strip()
    if ref.startswith("graph:"):
        body = ref[6:].strip()
        m = EDGE_REF.match(body)
        if m:
            a, kind, b = m.groups()
            ok = any(e["from"] == a and e["type"] == kind and e["to"] == b for e in graph.edges)
            return ok, "link in the graph" if ok else "no such link in the link graph"
        ok = body in graph.nodes
        return ok, "node in the graph" if ok else "no node %s in the link graph" % body
    if ref.startswith("chain:"):
        ok = ("chain:" + ref[6:].strip()) in graph.nodes
        return ok, "matrix chain" if ok else "no chain %s in the matrix" % ref[6:].strip()
    if ref.startswith("kb:"):
        ref = ref[3:].strip()
    path, _, line = ref.rpartition(":") if re.search(r":\d+$", ref) else (ref, "", "")
    lines = read_lines(path)
    if lines is None:
        return False, "%s does not exist" % path
    if not line:
        return True, "file exists"
    n = int(line)
    if n < 1 or n > len(lines):
        return False, "%s has %d lines, not %d" % (path, len(lines), n)
    if expect:
        window = "\n".join(lines[max(0, n - 1 - WINDOW):n + WINDOW]).lower()
        if str(expect).lower() not in window:
            return False, "%r is not within %d lines of %s:%d" % (expect, WINDOW, path, n)
    return True, "line checked"


def claim_mode(today=None):
    cfg = (config().get("unverified_claims") or {})
    until = cfg.get("warn_until")
    today = today or datetime.date.today().isoformat()
    if until and str(today) > str(until):
        return "block", str(until)
    return "warn", str(until) if until else None


def claims(path, today=None, graph=None):
    graph = graph or link_graph.Graph(link_graph.load())
    with open(path) as fh:
        data = yaml.safe_load(fh) or {}
    rows = []
    for c in data.get("claims") or []:
        ev = c.get("evidence") or []
        if isinstance(ev, str):
            ev = [ev]
        checks = [(r,) + check_evidence(r, c.get("expect"), graph) for r in ev]
        bad = [why for _r, ok, why in checks if not ok]
        rows.append({"id": c.get("id"), "text": c.get("text", ""), "evidence": ev,
                     "status": "verified" if ev and not bad else "unverified",
                     "why": "no evidence given" if not ev else ("; ".join(bad) or "all evidence checked")})
    mode, until = claim_mode(today)
    unverified = [r for r in rows if r["status"] == "unverified"]
    return {"file": path, "rows": rows, "verified": len(rows) - len(unverified), "unverified": len(unverified),
            "mode": mode, "warn_until": until, "blocks": bool(unverified) and mode == "block"}


def claims_trace(res):
    name = os.path.basename(res["file"])
    miss = ", ".join("%s: %s" % (r["id"], r["why"]) for r in res["rows"] if r["status"] != "verified")
    result = "verified" if not res["unverified"] else (
        "unverified, blocks SDLC_04" if res["blocks"] else "unverified, warning until %s" % (res["warn_until"] or "set"))
    return ["[SDLC] evidence %s — %d claims: %d verified, %d unverified%s; why: every claim in the plan needs a "
            "file:line, graph link, matrix chain or KB file behind it; result: %s"
            % (name, len(res["rows"]), res["verified"], res["unverified"], (" (" + miss + ")") if miss else "", result)]


# ---- test selection -----------------------------------------------------------------------------

QA_PREFIX = "ACME/claims-qa:"


def is_test(path):
    return bool(TEST_NAME.search(path))


def select_tests(files, graph, hops=2):
    picked = {}
    for f in files:
        if is_test(f):
            picked.setdefault(f, "changed in this branch")
            continue
        start = "file:" + f
        if start not in graph.nodes:
            continue
        r = graph.walk(start, hops=hops, types=["test"])
        for x in r["reached"].get("test", []):
            path = x["id"].split(":", 1)[1]
            picked.setdefault(path, "%s (%s)" % (" ; ".join(x["path"]), ", ".join(x["sources"])))
    rows = []
    for i, p in enumerate(sorted(picked)):
        row = {"id": "TST-%d" % (i + 1), "path": p, "why": picked[p], "status": "not run"}
        if p.startswith(QA_PREFIX):
            row["run_by"] = "QA"
        rows.append(row)
    return rows


def tests(base=None, files=None, pack=None, graph=None):
    graph = graph or link_graph.Graph(link_graph.load())
    changed, err = changed_files(base, files)
    selected = select_tests(changed, graph) if changed else []
    unlinked = [f for f in changed if not is_test(f) and "file:" + f not in graph.nodes]
    res = {"changed": changed, "selected": selected, "unlinked": unlinked, "error": err, "pack": pack}
    if pack and not err:
        with open(pack) as fh:
            data = yaml.safe_load(fh) or {}
        old = {t.get("path"): t for t in data.get("selected_tests") or []}
        for t in selected:
            if t["path"] in old and old[t["path"]].get("status") in ("passed", "failed"):
                t["status"] = old[t["path"]]["status"]
        data["selected_tests"] = selected
        with open(pack, "w") as fh:
            yaml.safe_dump(data, fh, sort_keys=False, allow_unicode=True, width=120)
    return res


def tests_trace(res):
    if res["error"]:
        return ["[SDLC] tests link graph — could not list the changed files: %s; why: tests are picked from the "
                "change; result: not run" % res["error"]]
    where = os.path.basename(res["pack"]) if res["pack"] else "link graph"
    gap = ("; %d changed files have no link in the graph, so their tests come from /eval STEP 1 only"
           % len(res["unlinked"])) if res["unlinked"] else ""
    return ["[SDLC] tests %s — %d test files from %d changed files: %s%s; why: the graph links each changed file to "
            "the tests that import it or cover its tables; result: %s"
            % (where, len(res["selected"]), len(res["changed"]), ", ".join(t["path"] for t in res["selected"]) or "none",
               gap, "selected" if res["selected"] else "none selected")]


def required(pack, ran=()):
    with open(pack) as fh:
        data = yaml.safe_load(fh) or {}
    ran = set(ran or ())
    rows = []
    for t in data.get("selected_tests") or []:
        status = t.get("status") or "not run"
        if t.get("path") in ran and status == "not run":
            status = "ran"
        rows.append(dict(t, status=status))
    missing = [r for r in rows if r["status"] == "not run" and r.get("run_by") != "QA"]
    for_qa = [r for r in rows if r["status"] == "not run" and r.get("run_by") == "QA"]
    failed = [r for r in rows if r["status"] == "failed"]
    return {"pack": pack, "rows": rows, "missing": missing, "for_qa": for_qa, "failed": failed,
            "ok": not missing and not failed}


def required_trace(res):
    bad = ", ".join("%s %s" % (r["path"], r["status"]) for r in res["missing"] + res["failed"])
    qa = ("; %d Behave scenarios for QA to run in SIT (ACME/claims-qa)" % len(res["for_qa"])) if res.get("for_qa") else ""
    return ["[SDLC] tests %s — %d selected tests: %d not run, %d failed%s%s; why: every test the link graph picked "
            "must run before SDLC_05 and SDLC_06; result: %s"
            % (os.path.basename(res["pack"]), len(res["rows"]), len(res["missing"]), len(res["failed"]),
               (" (" + bad + ")") if bad else "", qa, "passed" if res["ok"] else "failed")]


# ---- contract -----------------------------------------------------------------------------------

def known_columns(graph):
    with open(os.path.join(REPO, REGISTRY)) as fh:
        reg = yaml.safe_load(fh) or {}
    shared = {c["name"]: c.get("type", "") for c in reg.get("shared_columns") or []}
    tables, listed = {}, set()
    for t in reg.get("tables") or []:
        cols = {c["name"]: c.get("type", "") for c in t.get("columns") or []}
        tables[t["name"]] = cols
        if cols:
            listed.add(t["name"])
    for nid, n in graph.nodes.items():
        if n.get("type") == "table":
            tables.setdefault(n["name"], {})
        elif n.get("type") == "column" and "." in n["name"]:
            tname, col = n["name"].split(".", 1)
            tables.setdefault(tname, {}).setdefault(col, "")
            listed.add(tname)
    return tables, listed, shared


def added_lines(base, path):
    if not base:
        lines = read_lines(path) or []
        return list(enumerate(lines, 1))
    out = git("diff", "-U0", "%s...HEAD" % base, "--", path) or ""
    rows, n = [], 0
    for line in out.splitlines():
        m = re.match(r"^@@ -\S+ \+(\d+)", line)
        if m:
            n = int(m.group(1))
            continue
        if line.startswith("+") and not line.startswith("+++"):
            rows.append((n, line[1:]))
            n += 1
    return rows


def type_problem(dbtype, value):
    t = (dbtype or "").upper()
    quoted = value.startswith("'")
    text = value.strip("'")
    if t.startswith("NUMBER") and quoted and not re.fullmatch(r"-?\d+(\.\d+)?", text):
        return "%s is %s, the SQL sets text %s" % ("column", t, value)
    m = re.match(r"(VAR)?CHAR\((\d+)\)", t)
    if m and quoted and len(text) > int(m.group(2)):
        return "value %s is longer than %s" % (value, t)
    return None


def contract(base=None, files=None, graph=None):
    graph = graph or link_graph.Graph(link_graph.load())
    changed, err = changed_files(base, files)
    tables, listed, shared = known_columns(graph)
    rows = []
    for f in changed:
        if not f.endswith(SQL_EXT) or is_test(f) or read_lines(f) is None:
            continue
        whole = "\n".join(read_lines(f)).upper()
        in_file = {t for t in tables if re.search(r"\b%s\b" % re.escape(t), whole)}
        cols = dict(shared)
        for t in in_file:
            cols.update(tables[t])
        seen = {}
        for n, text in added_lines(base, f):
            src = "%s:%d" % (f, n)
            named = set(TABLE_CTX.findall(text))
            for w in sorted(named - set(tables)):
                hit = {"source": src, "item": w, "status": "unknown table",
                       "why": "not in the table registry or the ontology; confirm the name or add it to the KB"}
                seen.setdefault((f, w, hit["status"]), hit)
            aliases = set(re.findall(r"\bAS\s+([A-Z][A-Z0-9_]+)", text, re.I))
            for w in sorted(set(WORD.findall(text)) - named - aliases):
                if w in tables or w in cols or not (in_file and in_file <= listed):
                    continue
                owners = sorted(t for t, c in tables.items() if w in c)[:3]
                if owners:
                    hit = {"source": src, "item": w, "status": "unknown column",
                           "why": "not a column of %s; it is a column of %s" % (", ".join(sorted(in_file)), ", ".join(owners))}
                    seen.setdefault((f, w, hit["status"]), hit)
            for col, value in ASSIGN.findall(text):
                problem = type_problem(cols.get(col), value) if col in cols else None
                if problem:
                    hit = {"source": src, "item": col, "status": "type mismatch", "why": problem.replace("column", col, 1)}
                    seen.setdefault((f, col, hit["status"]), hit)
        rows += list(seen.values())
    unchecked = sorted({f for f in changed if f.endswith(SQL_EXT) and not is_test(f)})
    return {"changed": changed, "files": unchecked, "rows": rows, "error": err,
            "verdict": "not run" if err else ("failed" if any(r["status"] != "unknown table" for r in rows)
                                              else "warning" if rows else "passed"),
            "live": "not run: no Snowflake connection in Devin Cloud"}


def contract_trace(res):
    lines = []
    if res["error"]:
        lines.append("[SDLC] contract registry — could not list the changed files: %s; why: the contract is checked "
                     "for the change; result: not run" % res["error"])
    else:
        bad = ", ".join("%s %s at %s" % (r["item"], r["status"], r["source"]) for r in res["rows"][:5])
        lines.append("[SDLC] contract DB_TABLE_REGISTRY.yaml — checked table and column names and literal types in "
                     "%d changed SQL/Python files%s; why: a wrong column or type breaks the API before it reaches a "
                     "test; result: %s" % (len(res["files"]), (": " + bad) if bad else "", res["verdict"]))
    lines.append("[SDLC] contract Snowflake — live column types, row counts and data rules; why: the registry can "
                 "lag the database; result: not run")
    return lines


# ---- cli ----------------------------------------------------------------------------------------

def emit(res, lines, as_json):
    if as_json:
        print(json.dumps(res, indent=2, default=str))
    else:
        print("\n".join(lines))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("claims")
    p.add_argument("file")
    p.add_argument("--today")
    p = sub.add_parser("tests")
    p.add_argument("files", nargs="*")
    p.add_argument("--base")
    p.add_argument("--pack")
    p = sub.add_parser("required")
    p.add_argument("--pack", required=True)
    p.add_argument("--ran", nargs="*", default=[])
    p = sub.add_parser("contract")
    p.add_argument("files", nargs="*")
    p.add_argument("--base")
    for p in sub.choices.values():
        p.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if args.command == "claims":
        res = claims(args.file, args.today)
        lines = claims_trace(res) + ["  %s %s — %s" % (r["id"], r["status"], r["why"]) for r in res["rows"]]
        emit(res, lines, args.json)
        return 1 if res["blocks"] else 0
    if args.command == "tests":
        res = tests(args.base, args.files, args.pack)
        emit(res, tests_trace(res) + ["  %s %s — %s" % (t["id"], t["path"], t["why"]) for t in res["selected"]], args.json)
        return 0
    if args.command == "required":
        res = required(args.pack, args.ran)
        emit(res, required_trace(res), args.json)
        return 0 if res["ok"] else 1
    res = contract(args.base, args.files)
    emit(res, contract_trace(res) + ["  %s %s — %s" % (r["source"], r["status"], r["why"]) for r in res["rows"]], args.json)
    return 1 if res["verdict"] == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
