#!/usr/bin/env python3
"""Build the Acme Claims link graph: typed links between stories, business objects, tables, columns,
endpoints, screens, ETL jobs, systems, code files and test files, in one file.

Every link is copied from something that exists and names it: the ontology, the cross-layer matrix,
an import line in a test file, or a commit whose message names a Acme Claims story. Nothing is inferred
from a name. `tools/ontology_lookup.py walk` and `drift` read it.

    python3 sdlc/framework/tools/kbgen/gen_link_graph.py [--out FILE] [--git-until REF]
    python3 sdlc/framework/tools/kbgen/gen_link_graph.py --check   # exit 1 when stale
"""
import argparse
import datetime
import os
import re
import subprocess
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import behave_links  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
KB = "docs/knowledge-base"
GRAPH = KB + "/CROSS-LAYER/ACME_LINK_GRAPH.yaml"
GENERATOR = "sdlc/framework/tools/kbgen/gen_link_graph.py"
SRC = {
    "ontology": KB + "/CROSS-LAYER/ACME_ONTOLOGY.yaml",
    "matrix": KB + "/CROSS-LAYER/CROSS_LAYER_IMPACT_MATRIX.yaml",
}
CODE_ROOTS = ("api/", "web/src/", "web-portal/", "api-portal/", "web-admin/")
TEST_ROOTS = ("web/src/__tests__", "api")


def story_projects():
    """Jira project keys whose stories are linked: jira.project, plus jira.linked_projects for the other
    teams whose code and KB this team reads (read only, through its own service account)."""
    sys.path.insert(0, os.path.join(HERE, "..", "..", "console"))
    try:
        import sdlc_profile
        jira = sdlc_profile.PROFILE.get("jira", {})
    except (ImportError, SystemExit, AttributeError):
        return ["ACME"]
    keys = [jira.get("project") or "ACME"] + list(jira.get("linked_projects") or [])
    return [k for i, k in enumerate(keys) if re.fullmatch(r"[A-Z][A-Z0-9_]+", k) and k not in keys[:i]]


def story_re(projects):
    return re.compile(r"\b(?:%s)-\d+\b" % "|".join(re.escape(p) for p in projects))


STORY_PROJECTS = story_projects()
STORY_RE = story_re(STORY_PROJECTS)
FILE_LINE_RE = re.compile(r"^([\w./@\[\]()-]+?):(\d+)$")
GAPS = [
    "Behave scenarios are read from ACME/claims-qa (read only). A scenario reaches a table only when its step code names a databaseQueries key as a literal, and a screen only through the Page-object element it clicks; steps that match no step definition, and query keys built at run time, are not linked.",
    "Story to file links come only from commits whose message names a Acme Claims story; work merged without a key is not linked.",
    "Endpoint tables are the tables named in the router folder (table_evidence_scope), not traced into the handler body.",
]
Loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
Dumper = getattr(yaml, "CSafeDumper", yaml.SafeDumper)


def load(rel):
    with open(os.path.join(REPO, rel), encoding="utf-8") as fh:
        return yaml.load(fh, Loader=Loader) or {}


class Builder:
    def __init__(self):
        self.nodes = {}
        self.edges = {}

    def node(self, kind, key, **attrs):
        nid = "%s:%s" % (kind, key)
        n = self.nodes.setdefault(nid, {"type": kind, "name": key})
        for k, v in attrs.items():
            if v and k not in n:
                n[k] = v
        return nid

    def edge(self, a, kind, b, source):
        if a and b and a != b:
            self.edges.setdefault((a, kind, b), str(source))


def file_of(ref):
    m = FILE_LINE_RE.match(str(ref or ""))
    return m.group(1) if m else str(ref or "")


def from_ontology(b, onto):
    src = os.path.basename(SRC["ontology"])
    bl, dl, al, im = (onto.get(k) or {} for k in ("business_layer", "data_layer", "application_layer", "impact"))
    for o in bl.get("objects") or []:
        oid = b.node("object", o["id"], label=o.get("label"))
        s = "%s objects.%s (%s)" % (src, o["id"], o.get("source") or "")
        if o.get("table"):
            b.edge(oid, "stored_in", b.node("table", o["table"]), s)
        for t in o.get("related_tables") or []:
            b.edge(oid, "related_table", b.node("table", t), s)
    for r in bl.get("relationships") or []:
        if r.get("from_table") and r.get("to_table"):
            b.edge(b.node("table", r["from_table"]), "joins", b.node("table", r["to_table"]),
                   "%s relationships.%s on %s (%s)" % (src, r.get("id"), r.get("join"), r.get("source") or ""))
    for t in dl.get("tables") or []:
        b.node("table", t["name"], module=t.get("module"))
    for j in dl.get("jobs") or []:
        jid = b.node("job", j["id"], path=j.get("path"), repo=j.get("repo"))
        s = "%s:%s" % (j.get("repo"), j.get("path"))
        for t in j.get("reads") or []:
            b.edge(jid, "reads", b.node("table", t), s)
        for t in j.get("writes") or []:
            b.edge(jid, "writes", b.node("table", t), s)
    for sy in dl.get("systems") or []:
        sid = b.node("system", sy["id"], label=sy.get("name"))
        kind = "feeds" if sy.get("direction") == "in" else "reads"
        for t in sy.get("tables") or []:
            b.edge(sid, kind, b.node("table", t), sy.get("source") or src)
    for e in al.get("endpoints") or []:
        eid = b.node("endpoint", e["id"], handler=e.get("handler"), app=e.get("app"))
        if e.get("code"):
            b.edge(eid, "handled_by", b.node("file", file_of(e["code"])), e["code"])
        s = "%s endpoints (%s)" % (src, e.get("table_evidence_scope") or "")
        for t in e.get("tables_read") or []:
            b.edge(eid, "reads", b.node("table", t), s)
        for t in e.get("tables_written") or []:
            b.edge(eid, "writes", b.node("table", t), s)
    for sc in al.get("screens") or []:
        sid = b.node("screen", sc["route"], page=sc.get("page"))
        if sc.get("page"):
            b.edge(sid, "page", b.node("file", sc["page"]), sc["page"])
        for ep in sc.get("endpoints") or []:
            b.edge(sid, "calls", b.node("endpoint", ep), "%s screens %s" % (src, sc["route"]))
    for c in im.get("chains") or []:
        cid = b.node("chain", c["id"], label=c.get("business_name"), risk=c.get("risk"))
        attr = str(c.get("attribute") or "")
        if "." in attr:
            col = b.node("column", attr)
            b.edge(col, "part_of", b.node("table", attr.split(".")[0]), src)
            b.edge(cid, "documents", col, c.get("source") or src)


def from_matrix(b, matrix):
    src = os.path.basename(SRC["matrix"])
    verbs = {"read": "reads", "write": "writes", "reference": "names"}
    for t, row in (matrix.get("tables") or {}).items():
        tid = b.node("table", t)
        for api in row.get("api") or []:
            for f in api.get("files") or []:
                for acc in api.get("access") or ["reference"]:
                    b.edge(b.node("file", file_of(f)), verbs.get(acc, "names"), tid, f)
        for test in row.get("tests") or []:
            for story in STORY_RE.findall(str(test.get("story") or "")):
                b.edge(b.node("story", story), "tested_on", tid,
                       "%s tables.%s.tests (05_TEST_CASE_CATALOGUE.md)" % (src, t))
    for c, row in (matrix.get("columns") or {}).items():
        if "." not in c:
            continue
        cid = b.node("column", c)
        b.edge(cid, "part_of", b.node("table", c.split(".")[0]), src)
        for f in row.get("api_files") or []:
            b.edge(b.node("file", file_of(f)), "names", cid, f)
    for r, row in (matrix.get("screens") or {}).items():
        sid = b.node("screen", r, page=row.get("page"))
        for story in row.get("tests") or []:
            for s in STORY_RE.findall(str(story)):
                b.edge(b.node("story", s), "tested_on", sid, "%s screens.%s.tests (05_TEST_CASE_CATALOGUE.md)" % (src, r))


IMPORT_TS = re.compile(r"""^\s*import\s.*?from\s+['"]([^'"]+)['"]|^\s*(?:jest\.mock|require)\(\s*['"]([^'"]+)['"]""")
IMPORT_PY = re.compile(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))")


def _resolve_ts(spec, test_path):
    if spec.startswith("@/"):
        base = os.path.join("web/src", spec[2:])
    elif spec.startswith("."):
        base = os.path.normpath(os.path.join(os.path.dirname(test_path), spec))
    else:
        return None
    for cand in [base] + [base + e for e in (".tsx", ".ts", ".jsx", ".js")] + \
                [os.path.join(base, "index" + e) for e in (".tsx", ".ts", ".js")]:
        if os.path.isfile(os.path.join(REPO, cand)):
            return cand.replace(os.sep, "/")
    return None


def _resolve_py(mod, test_path):
    parts = mod.split(".")
    for root in ("api", os.path.dirname(test_path)):
        for cand in (os.path.join(root, *parts) + ".py", os.path.join(root, *parts, "__init__.py")):
            if os.path.isfile(os.path.join(REPO, cand)):
                return cand.replace(os.sep, "/")
    return None


def test_files():
    for root in TEST_ROOTS:
        for dirpath, dirs, files in os.walk(os.path.join(REPO, root)):
            dirs[:] = sorted(d for d in dirs if d not in ("node_modules", ".next", "__pycache__"))
            for f in sorted(files):
                if re.search(r"\.(test|spec)\.(tsx?|jsx?)$", f) or re.match(r"test_.*\.py$", f):
                    yield os.path.relpath(os.path.join(dirpath, f), REPO).replace(os.sep, "/")


def from_tests(b):
    for path in test_files():
        tid = b.node("test", path)
        with open(os.path.join(REPO, path), encoding="utf-8", errors="replace") as fh:
            for n, line in enumerate(fh, 1):
                if path.endswith(".py"):
                    m = IMPORT_PY.match(line)
                    target = _resolve_py(m.group(1) or m.group(2), path) if m else None
                else:
                    m = IMPORT_TS.match(line)
                    target = _resolve_ts(m.group(1) or m.group(2), path) if m else None
                if target and target != path:
                    b.edge(tid, "covers", b.node("file", target), "%s:%d" % (path, n))


def git_sha(ref):
    r = subprocess.run(["git", "rev-parse", ref], capture_output=True, text=True, cwd=REPO)
    return r.stdout.strip() if r.returncode == 0 else None


def from_git(b, until):
    r = subprocess.run(["git", "log", "--no-merges", "--format=@@%H\t%s", "--name-only", until, "--"] + list(CODE_ROOTS),
                       capture_output=True, text=True, cwd=REPO)
    if r.returncode != 0:
        return False
    stories, sha = [], None
    for line in r.stdout.splitlines():
        if line.startswith("@@"):
            sha, _, subject = line[2:].partition("\t")
            stories = sorted(set(STORY_RE.findall(subject)))
        elif line and stories and line.startswith(CODE_ROOTS) and os.path.isfile(os.path.join(REPO, line)):
            for s in stories:
                b.edge(b.node("story", s), "changed", b.node("file", line), "commit %s" % sha[:10])
    return True


def build(until_sha):
    b = Builder()
    from_ontology(b, load(SRC["ontology"]))
    from_matrix(b, load(SRC["matrix"]))
    from_tests(b)
    qa = behave_links.link(b, b.nodes)
    if qa is None and os.path.isfile(os.path.join(REPO, GRAPH)):
        qa = behave_links.keep(b, load(GRAPH))
    git_ok = from_git(b, until_sha) if until_sha else False
    edges = [{"from": a, "type": k, "to": c, "source": s} for (a, k, c), s in sorted(b.edges.items())]
    counts = {}
    for n in b.nodes.values():
        counts[n["type"]] = counts.get(n["type"], 0) + 1
    return {
        "metadata": {
            "name": "Acme Claims link graph",
            "generated": datetime.date.today().isoformat(),
            "generator": GENERATOR,
            "git_until": until_sha if git_ok else None,
            "sources": sorted(SRC.values()) + ["git log (commit messages naming Acme Claims stories)",
                                               "test files under " + ", ".join(TEST_ROOTS),
                                               "Behave features of ACME/claims-qa (read only)"],
            "rule": "Every link names the file (and line where there is one), the KB entry or the commit that "
                    "proves it. Code is the authority: a link the code contradicts is reported, not trusted.",
            "how_to_read": "nodes are <type>:<name>; edges read from -type-> to. Ask with "
                           "ontology_lookup.py walk <item> --hops N and check cited lines with ontology_lookup.py drift.",
            "qa_repo": qa,
            "gaps": GAPS,
            "counts": dict(sorted(counts.items()), edges=len(edges)),
        },
        "nodes": dict(sorted(b.nodes.items())),
        "edges": edges,
    }


def dump(graph, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("# Acme Claims link graph - generated by %s; do not hand-edit.\n" % GENERATOR)
        yaml.dump(graph, fh, Dumper=Dumper, sort_keys=False, allow_unicode=True, width=1000)


def body(text):
    return [ln for ln in text.splitlines() if not ln.startswith("  generated:")]


def check(path=None):
    path = path or os.path.join(REPO, GRAPH)
    if not os.path.isfile(path):
        return {"fresh": False, "error": "%s does not exist" % GRAPH, "fix": "python3 " + GENERATOR}
    committed = load(os.path.relpath(path, REPO))
    until = (committed.get("metadata") or {}).get("git_until")
    if until and not git_sha(until):
        return {"fresh": None, "error": "commit %s is not in this clone (shallow?): not run" % until[:10]}
    tmp = path + ".check.tmp"
    try:
        dump(build(until), tmp)
        with open(path, encoding="utf-8") as a, open(tmp, encoding="utf-8") as c:
            fresh = body(a.read()) == body(c.read())
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return {"fresh": fresh, "fix": None if fresh else "python3 %s, then commit %s" % (GENERATOR, GRAPH)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=os.path.join(REPO, GRAPH))
    ap.add_argument("--git-until", default="HEAD", help="last commit whose story keys are read (default HEAD)")
    ap.add_argument("--check", action="store_true", help="rebuild in memory and compare; exit 1 when stale")
    a = ap.parse_args(argv)
    if a.check:
        res = check()
        if res["fresh"] is None:
            print("link graph check not run: %s" % res["error"])
            return 0
        print("link graph is current" if res["fresh"] else "link graph is STALE - %s" % (res.get("fix") or res.get("error")))
        return 0 if res["fresh"] else 1
    graph = build(git_sha(a.git_until))
    dump(graph, a.out)
    print("wrote %s: %s" % (os.path.relpath(a.out, REPO), graph["metadata"]["counts"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
