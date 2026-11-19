"""Pull the table-to-table joins the application actually executes out of its SQL.

The CLAIMS_UI_DATA schema has PRIMARY KEY constraints only — no FOREIGN KEYs — so the only
hard evidence of how tables relate is the SQL in the API code. This script walks the Python
sources under api/ and api-portal/, finds every SQL string literal, resolves FROM/JOIN
aliases and records each `a.col = b.col` predicate in an ON clause as an edge, with the file
that proves it.

Nothing is inferred from column names. A pair of tables that share a column but are never
joined in code does not appear here.

Usage:
    python3 extract_app_joins.py            # writes DB-DOCS/16_DB_APP_JOINS.yaml
    python3 extract_app_joins.py --print    # dump to stdout instead
"""
import argparse
import ast
import re
from collections import defaultdict
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[4]
KB = REPO / "docs" / "knowledge-base"
OUT = KB / "DB-DOCS" / "16_DB_APP_JOINS.yaml"
SOURCE_ROOTS = ("api", "api-portal")
TABLE_RE = r"(?:\{?[\w.]+\}?\.)*((?:VB|VBC|SDLC)_\w+)"
KEYWORDS = {"ON", "WHERE", "LEFT", "RIGHT", "INNER", "OUTER", "JOIN", "FULL", "CROSS", "AS", "SET",
            "GROUP", "ORDER", "LIMIT", "UNION", "SELECT", "AND", "OR", "USING", "WITH", "QUALIFY"}
FROM_JOIN_RE = re.compile(r"\b(?:FROM|JOIN)\s+" + TABLE_RE + r"(?:\s+AS)?(?:\s+(\w+))?", re.I)
ON_RE = re.compile(r"\bON\b(.*?)(?=\b(?:LEFT|RIGHT|INNER|FULL|CROSS|JOIN|WHERE|GROUP|ORDER|LIMIT|QUALIFY|UNION|SELECT)\b|;|\)|$)",
                   re.I | re.S)
PRED_RE = re.compile(r"(\w+)\.(\w+)\s*=\s*(\w+)\.(\w+)")


def sql_strings(path):
    """Yield every string literal in a Python file that looks like SQL with a join."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return
    for node in ast.walk(tree):
        text = None
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = node.value
        elif isinstance(node, ast.JoinedStr):
            parts = []
            for v in node.values:
                if isinstance(v, ast.Constant):
                    parts.append(str(v.value))
                else:
                    parts.append("{expr}")
            text = "".join(parts)
        if text and re.search(r"\bJOIN\b", text, re.I) and re.search(r"\bON\b", text, re.I):
            yield node.lineno, text


def edges_in(sql):
    aliases = {}
    for m in FROM_JOIN_RE.finditer(sql):
        table, alias = m.group(1).upper(), m.group(2)
        aliases[table] = table
        if alias and alias.upper() not in KEYWORDS:
            aliases[alias.upper()] = table
    for on in ON_RE.finditer(sql):
        for a, ac, b, bc in PRED_RE.findall(on.group(1)):
            ta, tb = aliases.get(a.upper()), aliases.get(b.upper())
            if not ta or not tb or ta == tb:
                continue
            # normalise direction so the same edge from two queries collapses to one
            left, right = sorted([(ta, ac.upper()), (tb, bc.upper())])
            yield left, right


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--print", action="store_true")
    args = ap.parse_args()

    edges = defaultdict(lambda: {"files": set(), "occurrences": 0})
    files_read = 0
    for root in SOURCE_ROOTS:
        for path in sorted((REPO / root).rglob("*.py")):
            if "test" in path.parts or "tests" in path.parts:
                continue
            found = False
            for lineno, sql in sql_strings(path):
                for left, right in edges_in(sql):
                    key = (left, right)
                    edges[key]["files"].add(f"{path.relative_to(REPO)}:{lineno}")
                    edges[key]["occurrences"] += 1
                    found = True
            files_read += found

    tables = sorted({t for (l, r) in edges for t in (l[0], r[0])})
    out = {
        "generator": "sdlc/framework/tools/kbgen/extract_app_joins.py",
        "source": "SQL string literals in " + " and ".join(SOURCE_ROOTS) + " (Python, excluding test folders)",
        "evidence_rule": "every edge has at least one file:line whose SQL contains the predicate; nothing is inferred from column names",
        "environment_independent": True,
        "note": "Table names are as written in the code; the schema/database prefix is stripped because the code fills it in at runtime.",
        "files_with_joins": files_read,
        "tables": tables,
        "edges": [],
    }
    for (l, r), info in sorted(edges.items()):
        out["edges"].append({
            "left_table": l[0], "left_column": l[1], "right_table": r[0], "right_column": r[1],
            "occurrences": info["occurrences"], "evidence": sorted(info["files"]),
        })
    text = ("# Table joins the Acme Claims application executes — extracted from its SQL.\n"
            "# Do not hand-edit; re-run extract_app_joins.py.\n" + yaml.safe_dump(out, sort_keys=False, width=120))
    if args.print:
        print(text)
    else:
        OUT.write_text(text)
        print(f"wrote {OUT.relative_to(REPO)}: {len(out['edges'])} edges over {len(tables)} tables from {files_read} files")


if __name__ == "__main__":
    main()
