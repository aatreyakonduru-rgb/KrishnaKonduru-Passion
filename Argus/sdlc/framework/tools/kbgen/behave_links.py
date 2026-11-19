"""Behave scenarios from the ACME/claims-qa QA repository, for the link graph. Read only: nothing is written there.

Each scenario becomes a test node. Its steps are matched to the step definitions (tools/qa_scenarios.py).
A scenario checks a table when a matched step function, or a Page-object method it calls (two calls deep), names a query key
whose SQL reads that table, and covers a screen when a matched step function, or the Page-object method it calls, uses the element that links to that route. When the QA repository is
not on this machine, the links from the committed graph are kept as they are.
"""
import ast
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import qa_scenarios  # noqa: E402

QA_NAME = "ACME/claims-qa"
PREFIX = QA_NAME + ":"
ROUTE = re.compile(r"acme(/[A-Za-z][\w/]*)")
PAGE_IMPORT = re.compile(r"^\s*from\s+features\.Pages(?:\.(\w+))?\s+import\s+([\w, ]+)")


def qa_repo():
    return os.environ.get("CLAIMS_QA_REPO") or os.path.expanduser("~/repos/claims-qa")


def qa_commit(path):
    r = subprocess.run(["git", "-C", path, "rev-parse", "HEAD"], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def read(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def quoted(key, text):
    return '"%s"' % key in text or "'%s'" % key in text


def function_spans(path):
    try:
        tree = ast.parse(read(path))
    except SyntaxError:
        return {}
    return {n.name: (n.lineno, getattr(n, "end_lineno", n.lineno)) for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


ATTR = re.compile(r"^\s*(\w+)\s*=\s*[\"'].*?acme(/[A-Za-z][\w/]*)")


def page_routes(repo):
    """Page-object attributes that link to a Acme Claims route: {attribute: (route, 'Page.py:line')}."""
    out, root = {}, os.path.join(repo, "features", "Pages")
    for name in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        if name.endswith(".py"):
            rel = "features/Pages/" + name
            for n, text in enumerate(read(os.path.join(repo, rel)).splitlines(), 1):
                m = ATTR.match(text)
                if m:
                    out.setdefault(m.group(1), (m.group(2).rstrip("/"), "%s:%d" % (rel, n)))
    return out


def qa_branch(path):
    r = subprocess.run(["git", "-C", path, "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def scan(repo=None):
    """Read the whole QA suite once. None when the repository is absent.

    Returns the step definitions (with how many scenario steps use each), the query keys (with where the code names
    them), the TestData sets and field mappings, and per scenario: its tags, stories, the tables its steps' query keys
    read, the routes its steps' Page elements link to, the TestData sets its Examples or steps name, and its steps that
    match no step definition."""
    repo = repo or qa_repo()
    if not os.path.isdir(os.path.join(repo, "features")):
        return None
    steps = qa_scenarios.load_steps(repo)
    queries = qa_scenarios.load_queries(repo)
    data_sets, mappings = qa_scenarios.load_test_data(repo)
    attrs = page_routes(repo)
    page_bodies = {}
    proot = os.path.join(repo, "features", "Pages")
    pages = sorted(n for n in os.listdir(proot) if n.endswith(".py")) if os.path.isdir(proot) else []
    for name in pages:
        lines = read(os.path.join(proot, name)).splitlines()
        for fn, (lo, hi) in function_spans(os.path.join(proot, name)).items():
            page_bodies.setdefault(fn, "\n".join(lines[lo - 1:hi]))
    spans, text_of, key_at = {}, {}, {}
    for s in steps:
        f = s["file"]
        if f not in spans:
            spans[f] = function_spans(os.path.join(repo, f))
            text_of[f] = read(os.path.join(repo, f)).splitlines()
    for f in sorted(text_of) + ["features/Pages/" + n for n in pages]:
        for n, text in enumerate(text_of.get(f) or read(os.path.join(repo, f)).splitlines(), 1):
            for k in queries:
                if quoted(k, text):
                    key_at.setdefault(k, "%s:%d" % (f, n))
    used = {}
    scenarios, features = [], 0
    for dirpath, dirs, files in os.walk(os.path.join(repo, "features")):
        dirs.sort()
        for name in sorted(files):
            if not name.endswith(".feature"):
                continue
            features += 1
            rel = os.path.relpath(os.path.join(dirpath, name), repo)
            scen = qa_scenarios.parse_feature(read(os.path.join(repo, rel)))
            background = [st for sc in scen if sc.get("background") for st in sc["steps"]]
            for sc in scen:
                if sc.get("background"):
                    continue
                tag = next((t for t in sc["tags"] if t.lower() != name[:-8].lower() and not re.fullmatch(r"ACME-\d+", t)), None)
                rec = {"id": "test:%s%s@%s" % (PREFIX, rel, tag or "line%d" % sc["line"]), "feature": rel, "line": sc["line"],
                       "name": sc["name"], "tags": sc["tags"], "stories": [t for t in sc["tags"] if re.fullmatch(r"ACME-\d+", t)],
                       "steps": 0, "tables": {}, "screens": {}, "data_sets": [], "unmatched": []}
                cells = {v for row in sc["examples"] for v in row.values()}
                for st in background + sc["steps"]:
                    rec["steps"] += 1
                    cells |= set(re.findall(r"\"([^\"<>]+)\"", st["text"]))
                    m = qa_scenarios.match_step(re.sub(r"\"<[^>]+>\"", '"x"', st["text"]), steps)
                    if not m:
                        rec["unmatched"].append({"text": st["text"], "line": st["line"]})
                        continue
                    f = m["file"]
                    used["%s:%d" % (f, m["line"])] = used.get("%s:%d" % (f, m["line"]), 0) + 1
                    lo, hi = spans[f].get(m["function"], (m["line"], m["line"]))
                    body = "\n".join(text_of[f][lo - 1:hi])
                    for _ in range(2):
                        body += "\n".join(page_bodies.get(c, "") for c in set(re.findall(r"\.(\w+)\(", body)))
                    for k, at in key_at.items():
                        if quoted(k, body):
                            for t in queries[k]["tables"]:
                                rec["tables"].setdefault(t.split(".")[-1].upper(), PREFIX + at)
                    for a, (r, src) in attrs.items():
                        if re.search(r"\b%s\b" % a, body):
                            rec["screens"].setdefault(r, PREFIX + src)
                rec["data_sets"] = sorted(c for c in cells if c in data_sets)
                scenarios.append(rec)
    for s in steps:
        s["used"] = used.get("%s:%d" % (s["file"], s["line"]), 0)
    return {"repo": QA_NAME, "branch": qa_branch(repo), "commit": qa_commit(repo), "features": features,
            "steps": steps, "queries": queries, "key_at": key_at, "data_sets": data_sets, "field_mappings": mappings,
            "scenarios": scenarios}


def link(b, screens, repo=None, suite=None):
    """Add the scenarios to Builder b. Returns metadata about the QA repository, or None when it is absent."""
    suite = suite or scan(repo)
    if suite is None:
        return None
    for sc in suite["scenarios"]:
        tid = b.node("test", sc["id"][len("test:"):], scenario=sc["name"])
        for t in sc["stories"]:
            b.edge(b.node("story", t), "tested_by", tid, "%s%s:%d" % (PREFIX, sc["feature"], sc["line"]))
        for t, src in sc["tables"].items():
            b.edge(tid, "checks", b.node("table", t), src)
        for r, src in sc["screens"].items():
            if "screen:" + r in screens:
                b.edge(tid, "covers", "screen:" + r, src)
    return {"repo": QA_NAME, "commit": suite["commit"],
            "unmatched_steps": sum(len(sc["unmatched"]) for sc in suite["scenarios"])}


def keep(b, committed):
    """QA repository absent: carry over the scenario nodes and links of the committed graph."""
    nodes = committed.get("nodes") or {}
    for e in committed.get("edges") or []:
        if str(e.get("source", "")).startswith(PREFIX):
            for nid in (e["from"], e["to"]):
                n = nodes.get(nid) or {}
                kind, _, key = nid.partition(":")
                b.node(kind, key, **{k: v for k, v in n.items() if k not in ("type", "name")})
            b.edge(e["from"], e["type"], e["to"], e["source"])
    return (committed.get("metadata") or {}).get("qa_repo")
