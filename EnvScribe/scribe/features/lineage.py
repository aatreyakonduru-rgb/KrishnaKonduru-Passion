"""Feature 7 - Data lineage: service -> SQL statement -> table -> column, joined to the DB catalog.

SQL text is found in string literals (including `"a" + "b"` concatenation and text blocks) and in .sql files, then parsed
with sqlglot. Anything that does not parse is counted, never guessed. Dynamic SQL (variables spliced into the text) is not
resolved. All lineage facts are DERIVED and record their rule.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

from ..facts import ev, make_fact
from ..scanners import code as codescan
from ..util import read_text
from .common import Ctx, Result, cite, header, md_cell

_LIT = r'"""(?:.|\n)*?"""|"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\'|`[^`]*`'
_RUN = re.compile(rf"(?:{_LIT})(?:\s*(?:\+\s*)?(?:{_LIT}))*")
_PIECE = re.compile(_LIT)
_START = re.compile(r"(?is)^\s*\(?\s*(select|insert|update|delete|merge|with|create\s+(?:or\s+replace\s+)?(?:table|view)|alter\s+table|drop\s+table|truncate\s+table)\b")
_SHAPE = {"select": re.compile(r"(?is)\bfrom\b"), "update": re.compile(r"(?is)\bset\b"), "insert": re.compile(r"(?is)\binto\b"),
          "delete": re.compile(r"(?is)\bfrom\b"), "with": re.compile(r"(?is)\bselect\b")}
_PLACEHOLDER = [(re.compile(r"\$\{[^}]*\}|#\{[^}]*\}|\{\{[^}]*\}\}|\{\w*\}"), "__p__"), (re.compile(r"%\(\w+\)s|%s"), "?")]
MAX_PER_REPO = 3000
MAX_STATEMENT = 8000


def _body(piece: str) -> str:
    if piece.startswith('"""'):
        return piece[3:-3]
    return piece[1:-1]


def _unescape(s: str) -> str:
    return s.replace("\\n", " ").replace("\\t", " ").replace('\\"', '"').replace("\\'", "'")


def candidates(text: str, is_sql_file: bool):
    """Yield (line, statement_text)."""
    if is_sql_file:
        yield 1, text
        return
    for m in _RUN.finditer(text):
        sql = " ".join(_unescape(_body(p.group(0))) for p in _PIECE.finditer(m.group(0)))
        sql = re.sub(r"\s+", " ", sql).strip()
        if len(sql) < 12 or len(sql) > MAX_STATEMENT:
            continue
        st = _START.match(sql)
        if not st:
            continue
        key = st.group(1).lower().split()[0]
        shape = _SHAPE.get(key)
        if shape and not shape.search(sql):
            continue
        yield text.count("\n", 0, m.start()) + 1, sql


def analyse(sql: str) -> list[dict]:
    """Return [{operation, statement, table, schema, columns, unresolved}] for one SQL text (may hold several statements)."""
    import sqlglot
    from sqlglot import exp
    for rx, rep in _PLACEHOLDER:
        sql = rx.sub(rep, sql)
    out: list[dict] = []
    for tree in sqlglot.parse(sql):
        if tree is None:
            continue
        stype = type(tree).__name__.lower()
        is_write = isinstance(tree, (exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Create, exp.Alter, exp.Drop, exp.TruncateTable))
        ctes = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
        alias: dict[str, str] = {}
        tables: list[exp.Table] = []
        for t in tree.find_all(exp.Table):
            if not t.name or t.name.lower() in ctes:
                continue
            tables.append(t)
            alias[(t.alias or t.name).lower()] = t.name.lower()
            alias[t.name.lower()] = t.name.lower()
        if not tables:
            continue
        target = tables[0] if is_write else None
        cols: dict[str, set] = defaultdict(set)
        unresolved: set = set()
        for c in tree.find_all(exp.Column):
            nm = c.name.lower()
            if not nm or nm == "*":
                continue
            q = (c.table or "").lower()
            if q and q in alias:
                cols[alias[q]].add(nm)
            elif not q and len({t.name.lower() for t in tables}) == 1:
                cols[tables[0].name.lower()].add(nm)
            else:
                unresolved.add(nm)
        if isinstance(tree, exp.Insert) and isinstance(tree.this, exp.Schema):
            for ce in tree.this.expressions:
                nm = getattr(ce, "name", "")
                if nm:
                    cols[tables[0].name.lower()].add(nm.lower())
        seen = set()
        for t in tables:
            name = t.name.lower()
            if name in seen:
                continue
            seen.add(name)
            op = "write" if (target is not None and t is target) else "read"
            out.append({"operation": op, "statement": stype, "table": name, "schema": (t.db or "").lower() or None,
                        "columns": sorted(cols.get(name, set())), "unresolved": sorted(unresolved)[:20]})
    return out


def compute(ctx: Ctx) -> dict:
    if "lineage" in ctx.cache:
        return ctx.cache["lineage"]
    facts: list[dict] = []
    stats = {"statements": 0, "unparsed": 0, "files_with_sql": 0}
    for f in ctx.k("source_file"):
        a = f["attrs"]
        repo, rel = a["repo"], a["path"]
        root = ctx.repos.get(repo)
        if not root or a.get("language") in (None, "markdown", "html", "css"):
            continue
        if any(x and x in rel for x in ctx.settings.exclude_sources):
            continue
        text, _ = read_text(str(Path(root) / rel), ctx.settings.max_file_bytes)
        if not text or not re.search(r"(?i)\b(select|insert|update|delete|merge|create|alter|drop|truncate)\b", text):
            continue
        per_repo = sum(1 for x in facts if x["attrs"]["repo"] == repo)
        found = False
        for line, sql in candidates(text, a.get("language") == "sql"):
            if per_repo >= MAX_PER_REPO:
                break
            try:
                rows = analyse(sql)
            except Exception:
                stats["unparsed"] += 1
                continue
            if not rows:
                stats["unparsed"] += 1
                continue
            found = True
            stats["statements"] += 1
            for r in rows:
                per_repo += 1
                facts.append(make_fact(
                    "sql_access", f"{repo}/{rel}:L{line}:{r['table']}:{r['operation']}",
                    {"repo": repo, "path": rel, "table": r["table"], "schema": r["schema"], "operation": r["operation"], "statement": r["statement"],
                     "columns": r["columns"], "unresolved_columns": r["unresolved"], "is_test": a.get("is_test", False)},
                    "DERIVED", [ev(f"{repo}/{rel}", f"L{line}", sql[:160])], "lineage",
                    "sqlglot parse of a SQL string literal or .sql file; static text only, dynamic SQL is not resolved"))
        if found:
            stats["files_with_sql"] += 1
    res = {"facts": facts, "stats": stats}
    ctx.cache["lineage"] = res
    return res


def run(ctx: Ctx) -> Result:
    try:
        import sqlglot  # noqa: F401
    except ImportError:
        return Result(files={"lineage/index.md": header("Data lineage", ctx) + "UNKNOWN: the `sqlglot` package is not installed, so SQL was not parsed.\n"},
                      index=["- [Data lineage](lineage/index.md)"], coverage={"lineage": "not run: sqlglot missing"})
    comp = compute(ctx)
    facts = comp["facts"]
    st = comp["stats"]
    cat_tables: dict[str, list[dict]] = defaultdict(list)
    cat_cols: dict[tuple, dict] = {}
    for f in ctx.k("db_table"):
        cat_tables[f["attrs"]["table"]].append(f)
    for f in ctx.k("db_column"):
        cat_cols[(f["attrs"]["table"], f["attrs"]["column"])] = f
    ctx.cache["catalog_tables"] = set(cat_tables)

    by_table: dict[str, list[dict]] = defaultdict(list)
    for f in facts:
        by_table[f["attrs"]["table"]].append(f)
    md = [header("Data lineage (static SQL)", ctx, "service → statement → table → column. DERIVED from SQL text found in code; dynamic SQL is not resolved."),
          f"{st['statements']} statement(s) parsed in {st['files_with_sql']} file(s); {st['unparsed']} candidate(s) did not parse and were skipped.\n"]
    if not cat_tables:
        md.append("> UNKNOWN: no live catalog was read, so tables below are not checked against a database. Configure `db_catalogs` to join them.\n")
    md.append("## Tables used by code\n\n| Table | Services | Reads | Writes | In catalog | Columns used |\n|---|---|---|---|---|---|")
    graphrows = []
    for tbl, fs in sorted(by_table.items()):
        repos = sorted({f["attrs"]["repo"] for f in fs})
        rd = sum(1 for f in fs if f["attrs"]["operation"] == "read")
        wr = len(fs) - rd
        cols = sorted({c for f in fs for c in f["attrs"]["columns"]})
        if not cat_tables:
            incat = "unknown"
        elif tbl in cat_tables:
            missing = [c for c in cols if (tbl, c) not in cat_cols] if cat_cols else []
            incat = "yes" + (f" (columns not in catalog: {', '.join(missing[:6])})" if missing else "")
        else:
            incat = "**not found**"
        md.append(f"| `{md_cell(tbl)}` | {', '.join(f'`{r}`' for r in repos)} | {rd} | {wr} | {md_cell(incat)} | {md_cell(', '.join(cols[:12]))} |")
        graphrows.append({"table": tbl, "services": repos, "reads": rd, "writes": wr, "columns": cols, "in_catalog": incat})
    if not by_table:
        md.append("| _none_ | | | | | |")
    md.append("\n## Statements (first 200)\n")
    for f in facts[:200]:
        a = f["attrs"]
        md.append(f"- `{a['repo']}` {a['operation']} `{a['table']}` ({a['statement']}) cols: {', '.join(a['columns'][:10]) or '-'} - {cite(f)}")
    # catalog tables nothing in code touches
    if cat_tables:
        unused = sorted(t for t in cat_tables if t not in by_table)
        md.append(f"\n## Catalog tables no scanned code references ({len(unused)})\n")
        md += [f"- `{t}`" for t in unused[:300]] or ["- none"]
    ph = [f for f in facts if f["attrs"]["unresolved_columns"]]
    if ph:
        md.append(f"\n## Columns that could not be attributed to one table\n\n{len(ph)} statement(s) use unqualified columns across several tables; those columns are listed on the fact but not assigned.\n")
    return Result(files={"lineage/index.md": "\n".join(md) + "\n", "lineage/lineage.json": json.dumps({"stats": st, "tables": graphrows}, indent=1)},
                  facts=facts, index=["- [Data lineage](lineage/index.md)"],
                  coverage={"lineage": f"{st['statements']} SQL statements parsed; {len(by_table)} tables; {st['unparsed']} unparsed"})
