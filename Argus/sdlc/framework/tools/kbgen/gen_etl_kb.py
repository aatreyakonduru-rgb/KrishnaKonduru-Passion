"""Regenerate 13_ETL_TABLE_IO_CONTRACT.yaml from the claims-etl repo.

The ETL repo is expected as a sibling checkout; override with SDLC_ETL_REPO.
"""
import json
import os
import re
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
KB = REPO / "docs" / "knowledge-base"
# SDLC_KB_OUT: write into a staging copy of the KB (e.g. _REGEN/<date>) instead of the live one.
KB_OUT = Path(os.environ.get("SDLC_KB_OUT") or KB)

ETL = str(Path(os.environ.get("SDLC_ETL_REPO", REPO.parent / "claims-etl")))
OUT = str(KB_OUT / "ETL/claims-etl/13_ETL_TABLE_IO_CONTRACT.yaml")
os.makedirs(os.path.dirname(OUT), exist_ok=True)
TODAY = date.today().isoformat()
PLACEHOLDER = re.compile(r"\$?\{[A-Za-z_]+\}\.")


def q(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def read(p):
    return open(p, encoding="utf-8", errors="replace").read()


def strip_comments(sql):
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    sql = re.sub(r"--[^\n]*", " ", sql)
    return sql


def clean(name):
    name = name.strip().strip(";,()")
    name = PLACEHOLDER.sub("", name)          # {SDLCUI_DB_NM}.{SDLCUI_SCHMA_NM}.X -> X
    name = name.split(".")[-1]
    return name.upper()


VALID = re.compile(r"^[A-Z][A-Z0-9_]{2,}$")
KEYWORDS = {
    "SELECT", "TABLE", "VALUES", "QUERY", "TEXT", "DUAL", "LATERAL", "UNNEST",
    "EXCEPTIONS", "IDENTIFIER", "RESULT_SCAN", "INFORMATION_SCHEMA",
}


def cte_names(sql):
    """Names bound by WITH ... AS ( ... ) — not physical tables."""
    return {m.upper() for m in re.findall(r"(?:\bWITH\s+|,\s*)([A-Za-z_]\w*)\s+AS\s*\(", sql, re.I)}


def tables(pattern, sql, exclude=frozenset()):
    out = set()
    for m in re.findall(pattern, sql, re.I):
        t = clean(m)
        if VALID.match(t) and t not in KEYWORDS and t not in exclude:
            out.add(t)
    return out


SQL_HINT = re.compile(r"\b(SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM|MERGE\s+INTO|CREATE\s+TABLE)\b", re.I)


def embedded_sql(py_src):
    """Only SQL inside string literals — avoids matching python import statements."""
    groups = re.findall(r'"""(.*?)"""' + r"|'''(.*?)'''" + r'|"([^"\n]{20,})"' + r"|'([^'\n]{20,})'",
                        py_src, re.S)
    flat = [c for g in groups for c in g if c]
    return "\n".join(c for c in flat if SQL_HINT.search(c))


def header_tables(raw, key):
    m = re.search(r"#\s*%s\s*:\s*([^\n]*)" % key, raw, re.I)
    if not m:
        return []
    return sorted({clean(x) for x in m.group(1).split(",") if clean(x) and VALID.match(clean(x))})


TOKEN = r"((?:\$?\{[A-Za-z_]+\}\.)*[A-Za-z_][\w$]*(?:\.[A-Za-z_][\w$]*)*)"

scripts = []
sql_dir = os.path.join(ETL, "scripts/sql")
for f in sorted(os.listdir(sql_dir)):
    if not f.endswith(".sql"):
        continue
    raw = read(os.path.join(sql_dir, f))
    sql = strip_comments(raw)
    ctes = cte_names(sql)
    writes = (tables(r"INSERT\s+INTO\s+" + TOKEN, sql, ctes)
              | tables(r"MERGE\s+INTO\s+" + TOKEN, sql, ctes)
              | tables(r"UPDATE\s+" + TOKEN + r"\s+SET", sql, ctes)
              | tables(r"DELETE\s+FROM\s+" + TOKEN, sql, ctes))
    creates = (tables(r"CREATE\s+(?:OR\s+REPLACE\s+)?(?:TEMPORARY\s+|TEMP\s+|TRANSIENT\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?" + TOKEN, sql, ctes)
               | tables(r"CREATE\s+(?:OR\s+REPLACE\s+)?VIEW\s+" + TOKEN, sql, ctes))
    reads = (tables(r"FROM\s+" + TOKEN, sql, ctes) | tables(r"JOIN\s+" + TOKEN, sql, ctes)) - writes - creates
    reads = {t for t in reads if not t.endswith("_TEMP")}
    scripts.append({
        "name": f,
        "path": f"scripts/sql/{f}",
        "lines": raw.count("\n") + 1,
        "title": (re.search(r"#\s*Title\s*:\s*([^\n]*)", raw) or [None, ""])[1].strip() if re.search(r"#\s*Title\s*:", raw) else "",
        "description": (re.search(r"#\s*Description\s*:\s*([^\n]*)", raw).group(1).strip()
                        if re.search(r"#\s*Description\s*:", raw) else ""),
        "header_source_tables": header_tables(raw, "SourceTables"),
        "header_target_tables": header_tables(raw, "Target ?Tables"),
        "reads": sorted(reads),
        "writes": sorted(writes),
        "creates": sorted(creates),
    })

py_scripts = []
py_dir = os.path.join(ETL, "scripts/python")
for dp, _d, fs in os.walk(py_dir):
    for f in sorted(fs):
        if not f.endswith(".py"):
            continue
        p = os.path.join(dp, f)
        raw = read(p)
        sql = strip_comments(embedded_sql(raw))
        ctes = cte_names(sql)
        py_scripts.append({
            "name": f,
            "path": os.path.relpath(p, ETL).replace(os.sep, "/"),
            "lines": raw.count("\n") + 1,
            "description": (re.search(r"#\s*Description\s*:\s*([^\n]*)", raw).group(1).strip()
                            if re.search(r"#\s*Description\s*:", raw) else ""),
            "reads": sorted(tables(r"FROM\s+" + TOKEN, sql, ctes) | tables(r"JOIN\s+" + TOKEN, sql, ctes)),
            "writes": sorted(tables(r"INSERT\s+INTO\s+" + TOKEN, sql, ctes)
                             | tables(r"UPDATE\s+" + TOKEN + r"\s+SET", sql, ctes)
                             | tables(r"MERGE\s+INTO\s+" + TOKEN, sql, ctes)
                             | tables(r"DELETE\s+FROM\s+" + TOKEN, sql, ctes)),
            "imports": sorted({m for m in re.findall(r"^\s*(?:import|from)\s+([\w.]+)", raw, re.M)}),
        })

# per-table rollup
table_io = {}
for s in scripts + py_scripts:
    for t in s["reads"]:
        table_io.setdefault(t, {"read_by": [], "written_by": [], "created_by": []})["read_by"].append(s["path"])
    for t in s["writes"]:
        table_io.setdefault(t, {"read_by": [], "written_by": [], "created_by": []})["written_by"].append(s["path"])
    for t in s.get("creates", []):
        table_io.setdefault(t, {"read_by": [], "written_by": [], "created_by": []})["created_by"].append(s["path"])

# cross-check against the DB registry
import yaml  # noqa: E402
reg = yaml.safe_load(open(str(KB / "DB-DOCS/DB_TABLE_REGISTRY.yaml")))
registry_tables = set()
for t in reg.get("tables", []):
    n = t.get("name") or t.get("table") or t.get("table_name")
    if n:
        registry_tables.add(str(n).upper())

unknown = sorted(t for t in table_io if t not in registry_tables and not t.endswith("_TEMP"))
temp_objects = sorted(t for t in table_io if t.endswith("_TEMP"))

lines = [
    "# Acme Claims ETL Table I/O Contract",
    "# Confidence: 1.0 — generated by static scan of the claims-etl repo",
    f'# Generated: {TODAY}',
    "# Table references are parsed from the SQL/Python statements themselves;",
    "# the `header_*` fields are what the script header comment claims, kept so the",
    "# two can be compared (a mismatch means the header is stale).",
    "",
    "metadata:",
    "  confidence: 1.0",
    f'  generated: "{TODAY}"',
    '  source_repo: "ACMEETL/claims-etl"',
    f'  source_commit: "{os.popen("git -C %s rev-parse --short HEAD" % ETL).read().strip()}"',
    '  database_placeholder: "{SDLCUI_DB_NM}.{SDLCUI_SCHMA_NM}"',
    '  generation_method: "regex scan of scripts/sql/*.sql and scripts/python/**/*.py"',
    f"  total_sql_scripts: {len(scripts)}",
    f"  total_python_scripts: {len(py_scripts)}",
    f"  total_tables_referenced: {len(table_io)}",
    "  not_available:",
    '    - "claims-etl-glue — repository not accessible to this session"',
    '    - "claims-etl-lambda — repository not accessible to this session"',
    "",
    "sql_scripts:",
]
for s in scripts:
    lines += [
        f"  - name: {s['name']}",
        f"    path: {s['path']}",
        f"    lines: {s['lines']}",
        f"    description: {q(s['description'])}",
        f"    reads: {json.dumps(s['reads'])}",
        f"    writes: {json.dumps(s['writes'])}",
        f"    creates: {json.dumps(s['creates'])}",
        f"    header_source_tables: {json.dumps(s['header_source_tables'])}",
        f"    header_target_tables: {json.dumps(s['header_target_tables'])}",
    ]

lines += ["", "python_scripts:"]
for s in py_scripts:
    lines += [
        f"  - name: {s['name']}",
        f"    path: {s['path']}",
        f"    lines: {s['lines']}",
        f"    description: {q(s['description'])}",
        f"    reads: {json.dumps(s['reads'])}",
        f"    writes: {json.dumps(s['writes'])}",
    ]

lines += ["", "tables:"]
for t in sorted(table_io):
    io = table_io[t]
    lines += [
        f"  - name: {t}",
        f"    kind: {'temp' if t.endswith('_TEMP') else 'physical'}",
        f"    in_db_registry: {str(t in registry_tables).lower()}",
        f"    read_by: {json.dumps(sorted(set(io['read_by'])))}",
        f"    written_by: {json.dumps(sorted(set(io['written_by'])))}",
        f"    created_by: {json.dumps(sorted(set(io['created_by'])))}",
    ]

lines += [
    "",
    "# Persistent tables referenced by ETL but absent from DB-DOCS/DB_TABLE_REGISTRY.yaml.",
    "# Mostly FeedFile-layer tables (CL_*) that live outside the CLAIMS_UI_DATA schema the",
    "# registry covers; each one is a candidate for /db-discovery once Snowflake access",
    "# is available.",
    "tables_not_in_db_registry:",
]
lines += [f"  - {t}" for t in unknown] or ["  []"]
lines += [
    "",
    "# Session-scoped objects created and dropped inside the scripts themselves.",
    "temp_objects:",
]
lines += [f"  - {t}" for t in temp_objects] or ["  []"]

open(OUT, "w").write("\n".join(lines).rstrip("\n") + "\n")
print("sql", len(scripts), "py", len(py_scripts), "tables", len(table_io),
      "not in registry", len(unknown))
