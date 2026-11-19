"""Render an environment-specific DB knowledge-base set from a Snowflake metadata snapshot.

The snapshot is a folder of JSON files pulled from <DB>.INFORMATION_SCHEMA (see
`extract_db_snapshot.py` for the exact queries). Nothing here talks to Snowflake; the
renderer is deterministic so a re-run over the same snapshot produces the same files.

Usage:
    python3 gen_db_kb.py --env sit --snapshot /path/to/SIT01_CLAIMS
    python3 gen_db_kb.py --env dev --snapshot /path/to/DEV01_CLAIMS --baseline web/.../DB-DOCS

Output folder comes from `docs_dir` in .devin/rules/snowflake-environments.yaml.
Every generated file states its source database and snapshot date in the header.
The prod (P01) documents at the DB-DOCS root are the baseline for the delta report and
are never written by this script.
"""
import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[4]
KB = REPO / "docs" / "knowledge-base"
ENV_FILE = REPO / ".devin" / "rules" / "snowflake-environments.yaml"
SCHEMA = "CLAIMS_UI_DATA"
RAW_PREFIXES = ("RAW_", "KF_TMS")
CODE_COL_RE = re.compile(r"(_CD|_IND|_TYPE|_STTS|_FLAG|_FLG|_LVL)$")


def is_edl(col):
    return col.startswith(RAW_PREFIXES) or col == "KF_TMS"


def load(snapshot):
    d = {}
    for name in ("tables", "columns", "schemas", "views", "constraints", "policies", "codes"):
        d[name] = json.load(open(snapshot / f"{name}.json"))
    return d


def fmt_type(c):
    t = c["DATA_TYPE"]
    if t == "TEXT" and c.get("CHARACTER_MAXIMUM_LENGTH"):
        return f"VARCHAR({c['CHARACTER_MAXIMUM_LENGTH']})"
    if t == "NUMBER" and c.get("NUMERIC_PRECISION"):
        return f"NUMBER({c['NUMERIC_PRECISION']},{c['NUMERIC_SCALE'] or 0})"
    if t == "TIMESTAMP_NTZ":
        return "TIMESTAMP_NTZ(9)"
    return t


def header(env, db, snap_date, doc, extra=None):
    lines = ["---", f"source_db: {db}", f"environment: {env}", f"schema: {SCHEMA}",
             f"generated_date: {snap_date}", f"row_counts_as_of: {snap_date}",
             "confirmed_by: INFORMATION_SCHEMA (tables, columns, schemata, views, table_constraints, policy_references) + GROUP BY on code columns",
             "generator: sdlc/framework/tools/kbgen/gen_db_kb.py", f"document: {doc}"]
    if extra:
        lines += extra
    lines += ["---", ""]
    return "\n".join(lines)


def parse_baseline_catalog(path):
    """Return {table: {col: (type, nullable)}} from a 07_DB_SCHEMA_CATALOG.md."""
    out = {}
    cur = None
    for line in path.read_text().splitlines():
        m = re.match(r"^## ([A-Z0-9_]+)\s*$", line)
        if m:
            cur = m.group(1)
            out.setdefault(cur, {})
            continue
        m = re.match(r"^\|\s*\d+\s*\|\s*([A-Z0-9_]+)\s*\|\s*([A-Z_0-9]+)\s*\|\s*(YES|NO)\s*\|", line)
        if m and cur:
            out[cur][m.group(1)] = (m.group(2), m.group(3))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", required=True)
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--baseline", default=str(KB / "DB-DOCS"),
                    help="folder holding the prod-derived docs used for the delta report")
    ap.add_argument("--snapshot-date", default=None)
    ap.add_argument("--out-root", default=str(KB), help="write under <out-root>/DB-DOCS/<docs_dir> instead of the live KB (for example a _REGEN staging folder)")
    args = ap.parse_args()

    envs = yaml.safe_load(ENV_FILE.read_text())
    if args.env not in envs["environments"]:
        raise SystemExit(f"{args.env} is not in {ENV_FILE}")
    e = envs["environments"][args.env]
    db, docs_dir, label = e["database"], e["docs_dir"], e["label"]
    snapshot = Path(args.snapshot)
    snap_date = args.snapshot_date or json.load(open(snapshot / "meta.json"))["snapshot_date"]
    if docs_dir == ".":
        raise SystemExit("refusing to write into the DB-DOCS root (production baseline); this script builds the lower regions only")
    out = Path(args.out_root).resolve() / "DB-DOCS" / docs_dir
    out.mkdir(parents=True, exist_ok=True)
    print(f"Snowflake target: {db} ({args.env}) -> {out}")

    d = load(snapshot)
    base_tables = sorted([t for t in d["tables"] if t["TABLE_SCHEMA"] == SCHEMA and t["TABLE_TYPE"] == "BASE TABLE"],
                         key=lambda t: t["TABLE_NAME"])
    tnames = [t["TABLE_NAME"] for t in base_tables]
    cols_by_t = defaultdict(list)
    for c in d["columns"]:
        cols_by_t[c["TABLE_NAME"]].append(c)
    for v in cols_by_t.values():
        v.sort(key=lambda c: int(c["ORDINAL_POSITION"]))
    pk_by_t = {c["TABLE_NAME"]: c["CONSTRAINT_NAME"] for c in d["constraints"] if c["CONSTRAINT_TYPE"] == "PRIMARY KEY"}
    total_cols = sum(len(cols_by_t[t]) for t in tnames)
    total_rows = sum(int(t["ROW_COUNT"] or 0) for t in base_tables)
    with_data = sum(1 for t in base_tables if int(t["ROW_COUNT"] or 0) > 0)
    view_counts = Counter(v["TABLE_SCHEMA"] for v in d["views"])
    obj_counts = Counter((t["TABLE_SCHEMA"], t["TABLE_TYPE"]) for t in d["tables"])
    schema_info = {s["SCHEMA_NAME"]: s for s in d["schemas"]}
    pol_tables = {t: rows for t, rows in d["policies"].items() if isinstance(rows, list)}
    pol_names = Counter((r["POLICY_KIND"], f"{r['POLICY_DB']}.{r['POLICY_SCHEMA']}.{r['POLICY_NAME']}")
                        for rows in pol_tables.values() for r in rows)
    no_policy = [t for t in tnames if not pol_tables.get(t)]

    # ---------- 00 discovery report ----------
    L = [header(args.env, db, snap_date, "00_DB_DISCOVERY_REPORT"),
         f"# {db}.{SCHEMA} — Discovery Report ({label})", "",
         f"Everything below was read from `{db}.INFORMATION_SCHEMA` on {snap_date} through the Snowflake "
         f"nonprod MCP. Tag `[E: INFORMATION_SCHEMA]` applies to every number in this file unless marked otherwise. "
         f"Nothing here is inferred from the P01 documents.", "",
         "## 1. Summary", "", "| Metric | Value |", "|---|---|",
         f"| Base tables in {SCHEMA} | {len(tnames)} |", f"| Columns in {SCHEMA} | {total_cols:,} |",
         f"| Rows (INFORMATION_SCHEMA.ROW_COUNT, approximate) | {total_rows:,} |",
         f"| Tables with data | {with_data} |", f"| Zero-row tables | {len(tnames) - with_data} |",
         f"| Views in {SCHEMA}_ALLPHI / _NOHAPHI / _NOPHI | {view_counts.get(SCHEMA + '_ALLPHI', 0)} / {view_counts.get(SCHEMA + '_NOHAPHI', 0)} / {view_counts.get(SCHEMA + '_NOPHI', 0)} |",
         f"| Tables with a PRIMARY KEY constraint | {sum(1 for t in tnames if t in pk_by_t)} |",
         f"| Row-access-policy references | {sum(len(v) for v in pol_tables.values())} on {sum(1 for v in pol_tables.values() if v)} tables |",
         "", "## 2. Schema layers", "",
         "| Schema | Object type | Count | Retention (days) | Managed access | Comment |", "|---|---|---|---|---|---|"]
    for (sch, typ), n in sorted(obj_counts.items()):
        s = schema_info.get(sch, {})
        L.append(f"| {sch} | {typ} | {n} | {s.get('RETENTION_TIME', '')} | {s.get('IS_MANAGED_ACCESS', '')} | {(s.get('COMMENT') or '').strip()} |")
    L += ["", "## 3. EDL header pattern", "",
          "Columns present on every base table, by ordinal position. Business columns start after these.", "",
          "| Position | Column | Type | Nullable | Default | Tables carrying it |", "|---|---|---|---|---|---|"]
    edl = defaultdict(Counter)
    for t in tnames:
        for c in cols_by_t[t]:
            if is_edl(c["COLUMN_NAME"]):
                edl[c["COLUMN_NAME"]][(int(c["ORDINAL_POSITION"]), fmt_type(c), c["IS_NULLABLE"], c["COLUMN_DEFAULT"] or "")] += 1
    for col, variants in sorted(edl.items(), key=lambda kv: min(k[0] for k in kv[1])):
        for (pos, typ, nul, dflt), n in sorted(variants.items()):
            L.append(f"| {pos} | {col} | {typ} | {nul} | {dflt} | {n} |")
    L += ["", "## 4. Table inventory", "",
          "| Table | Rows | Columns | PK constraint | Created | Last altered | Comment |", "|---|---|---|---|---|---|---|"]
    for t in base_tables:
        n = t["TABLE_NAME"]
        L.append(f"| {n} | {int(t['ROW_COUNT'] or 0):,} | {len(cols_by_t[n])} | {pk_by_t.get(n, '—')} | {t['CREATED']} | {t['LAST_ALTERED']} | {(t.get('COMMENT') or '').strip()} |")
    L += ["", "## 5. Zero-row tables", "",
          "Structure exists, no data on the snapshot date. That is an observation, not a statement about whether the feature is used.", ""]
    L += [f"- {t['TABLE_NAME']} (created {t['CREATED']})" for t in base_tables if int(t["ROW_COUNT"] or 0) == 0]
    L += ["", "## 6. Views per base table", "",
          "Base tables that do **not** have a matching view in one of the three PHI schemas:", ""]
    views_by_schema = defaultdict(set)
    for v in d["views"]:
        views_by_schema[v["TABLE_SCHEMA"]].add(v["TABLE_NAME"])
    missing_any = False
    for t in tnames:
        miss = [s for s in (SCHEMA + "_ALLPHI", SCHEMA + "_NOHAPHI", SCHEMA + "_NOPHI") if t not in views_by_schema[s]]
        if miss:
            missing_any = True
            L.append(f"- {t}: no view in {', '.join(miss)}")
    if not missing_any:
        L.append("- none — every base table has a view in all three PHI schemas")
    orphan_views = sorted(set().union(*[views_by_schema[s] for s in views_by_schema if s.startswith(SCHEMA)]) - set(tnames))
    L += ["", "Views with no base table of the same name in " + SCHEMA + ":", ""]
    L += [f"- {v}" for v in orphan_views] or ["- none"]
    L += ["", "## 7. Policies (POLICY_REFERENCES)", "", "| Kind | Policy | Tables referencing it |", "|---|---|---|"]
    for (kind, name), n in sorted(pol_names.items()):
        L.append(f"| {kind} | {name} | {n} |")
    L += ["", "Tables with **no** policy reference: " + (", ".join(no_policy) if no_policy else "none"), "",
          "Masking policies are attached to view columns in the PHI schemas, not to base tables; POLICY_REFERENCES on the base "
          "tables therefore only shows the row-access policy. Column-level masking was not extracted in this snapshot. [?]", "",
          "## 8. Open items", "",
          "- KEY_COLUMN_USAGE was not queried, so PK constraint *columns* are not listed — only the constraint name. [?]",
          "- ROW_COUNT is Snowflake's catalog estimate, not a `COUNT(*)`.", ""]
    (out / "00_DB_DISCOVERY_REPORT.md").write_text("\n".join(L))

    # ---------- 07 schema catalog ----------
    L = [header(args.env, db, snap_date, "07_DB_SCHEMA_CATALOG"),
         f"# {db}.{SCHEMA} — Complete Schema Catalog ({label})", "",
         f"**Total tables:** {len(tnames)} | **Total columns:** {total_cols:,}", "",
         f"Complete column inventory for `{db}.{SCHEMA}` as of {snap_date}. EDL header columns are present on all "
         "tables and omitted from the per-table listings (see 00_DB_DISCOVERY_REPORT.md section 3). "
         "Types are shown as INFORMATION_SCHEMA.DATA_TYPE to stay comparable with the P01 catalog.", "", "---", ""]
    for t in tnames:
        L += [f"## {t}", "", "| Pos | Column | Type | Nullable | Default |", "|-----|--------|------|----------|---------|"]
        for c in cols_by_t[t]:
            if is_edl(c["COLUMN_NAME"]):
                continue
            L.append(f"| {c['ORDINAL_POSITION']} | {c['COLUMN_NAME']} | {c['DATA_TYPE']} | {c['IS_NULLABLE']} | {c['COLUMN_DEFAULT'] or ''} |")
        L.append("")
    (out / "07_DB_SCHEMA_CATALOG.md").write_text("\n".join(L))

    # ---------- table registry yaml ----------
    shared = []
    seen = set()
    for t in tnames:
        for c in cols_by_t[t]:
            if is_edl(c["COLUMN_NAME"]) and c["COLUMN_NAME"] not in seen:
                seen.add(c["COLUMN_NAME"])
                shared.append({"name": c["COLUMN_NAME"], "type": fmt_type(c), "nullable": c["IS_NULLABLE"] == "YES",
                               **({"default": c["COLUMN_DEFAULT"]} if c["COLUMN_DEFAULT"] else {})})
    reg = {
        "database": db, "environment": args.env, "schema": SCHEMA, "snapshot_date": snap_date,
        "generator": "sdlc/framework/tools/kbgen/gen_db_kb.py",
        "row_access_policies": [{"name": name, "kind": kind, "tables": n} for (kind, name), n in sorted(pol_names.items())],
        "shared_columns": shared,
        "tables": [],
    }
    for t in base_tables:
        n = t["TABLE_NAME"]
        reg["tables"].append({
            "name": n, "row_count": int(t["ROW_COUNT"] or 0), "created": t["CREATED"], "last_altered": t["LAST_ALTERED"],
            "pk_constraint": pk_by_t.get(n), "policy": [r["POLICY_NAME"] for r in pol_tables.get(n, [])],
            "columns": [{"name": c["COLUMN_NAME"], "type": fmt_type(c), "nullable": c["IS_NULLABLE"] == "YES",
                         **({"default": c["COLUMN_DEFAULT"]} if c["COLUMN_DEFAULT"] else {}),
                         **({"comment": c["COMMENT"]} if c.get("COMMENT") else {})}
                        for c in cols_by_t[n] if not is_edl(c["COLUMN_NAME"])],
        })
    with open(out / "DB_TABLE_REGISTRY.yaml", "w") as f:
        f.write(f"# SDLC/Acme Claims Schema Registry — {db}.{SCHEMA} ({label})\n# Generated from INFORMATION_SCHEMA snapshot {snap_date}. "
                "Do not hand-edit; re-run gen_db_kb.py.\n")
        yaml.safe_dump(reg, f, sort_keys=False, width=120)

    # ---------- 05 code values ----------
    L = [header(args.env, db, snap_date, "05_DB_CODE_VALUES"),
         f"# {db}.{SCHEMA} — Observed Code Values ({label})", "",
         "Distinct values actually present in code-like columns (`*_CD`, `*_IND`, `*_TYPE`, `*_STTS`, `*_FLAG`, `*_LVL`) "
         f"on {snap_date}, with row counts. Columns with more than 30 distinct values are left out. "
         "A value listed here exists in the data; a value **not** listed may still be valid — the application code and "
         "business rules decide that, not this file. Meanings are not given here because they cannot be read from the schema. [?]", "", "---", ""]
    for t in tnames:
        rows = d["codes"].get(t)
        if not rows or isinstance(rows, dict):
            continue
        L += [f"## {t}", ""]
        by_col = defaultdict(list)
        for r in rows:
            by_col[r["COL"]].append(r)
        for col, rs in by_col.items():
            vals = ", ".join(f"`{r['VAL'] if r['VAL'] is not None else 'NULL'}` ({int(r['N']):,})" for r in rs)
            L.append(f"- **{col}**: {vals}")
        L.append("")
    (out / "05_DB_CODE_VALUES.md").write_text("\n".join(L))

    # ---------- 06 security inventory ----------
    L = [header(args.env, db, snap_date, "06_DB_SECURITY_INVENTORY"),
         f"# {db}.{SCHEMA} — Security Inventory ({label})", "",
         "What Snowflake reports about access controls on this schema. This is an inventory, not a review: it says what is "
         "attached, not whether that is right.", "",
         "## Row access policies", "", "| Table | Policy | Kind | Status |", "|---|---|---|---|"]
    for t in tnames:
        for r in pol_tables.get(t, []):
            L.append(f"| {t} | {r['POLICY_DB']}.{r['POLICY_SCHEMA']}.{r['POLICY_NAME']} | {r['POLICY_KIND']} | {r['POLICY_STATUS']} |")
        if not pol_tables.get(t):
            L.append(f"| {t} | — none — | | |")
    L += ["", "## PHI view schemas", "", "| Schema | Views | Comment |", "|---|---|---|"]
    for sch in sorted(view_counts):
        L.append(f"| {sch} | {view_counts[sch]} | {(schema_info.get(sch, {}).get('COMMENT') or '').strip()} |")
    L += ["", "## Columns that look like identifiers or sensitive data", "",
          "Name-pattern scan only (TIN, NPI, SSN, DOB, name, address, phone, email, hash key). Whether a column is PHI/PII "
          "is decided by the data classification, not by its name. [?]", "", "| Table | Column | Type |", "|---|---|---|"]
    sens = re.compile(r"(TIN|NPI|SSN|BRTH|DOB|_NM$|_NAME|ADDR|PHONE|EMAIL|HASH_KEY|MBR_ID|SBSCRBR)")
    for t in tnames:
        for c in cols_by_t[t]:
            if not is_edl(c["COLUMN_NAME"]) and sens.search(c["COLUMN_NAME"]):
                L.append(f"| {t} | {c['COLUMN_NAME']} | {fmt_type(c)} |")
    L.append("")
    (out / "06_DB_SECURITY_INVENTORY.md").write_text("\n".join(L))

    # ---------- 90 delta vs prod baseline ----------
    base_cat = Path(args.baseline) / "07_DB_SCHEMA_CATALOG.md"
    questions = []
    if base_cat.exists():
        base = parse_baseline_catalog(base_cat)
        base_hdr = re.search(r"source_db:\s*(\S+).*?generated_date:\s*(\S+)", base_cat.read_text(), re.S)
        base_db, base_date = (base_hdr.group(1), base_hdr.group(2)) if base_hdr else ("baseline", "?")
        new_tables = [t for t in tnames if t not in base]
        gone_tables = [t for t in base if t not in tnames]
        common = [t for t in tnames if t in base]
        L = [header(args.env, db, snap_date, "90_DELTA_VS_PROD_BASELINE"),
             f"# {db} vs {base_db} — What is different ({label})", "",
             f"Live `{db}.{SCHEMA}` ({snap_date}) compared with the {base_db} catalog generated {base_date} "
             f"(`{base_cat.relative_to(REPO)}`). The {base_db} catalog is the team's production baseline and is not "
             "changed by this report. Where the two differ, this file says so and asks; it does not decide which side is right.", "",
             "## Headline", "", f"- {len(common)} of {len(base)} baseline tables exist in {db}. [E: both catalogs]",
             f"- {len(new_tables)} tables exist in {db} but not in the {base_db} catalog. [E: both catalogs]",
             f"- {len(gone_tables)} baseline tables are missing from {db}. [E: both catalogs]", "",
             f"## Tables only in {db}", ""]
        rc = {t["TABLE_NAME"]: t for t in base_tables}
        L += ["| Table | Rows | Columns (non-EDL) | Created |", "|---|---|---|---|"]
        for t in new_tables:
            L.append(f"| {t} | {int(rc[t]['ROW_COUNT'] or 0):,} | {sum(1 for c in cols_by_t[t] if not is_edl(c['COLUMN_NAME']))} | {rc[t]['CREATED']} |")
        L += ["", f"## Baseline tables missing from {db}", ""]
        L += [f"- {t}" for t in gone_tables] or ["- none"]
        L += ["", "## Column differences on shared tables", ""]
        any_diff = False
        for t in common:
            live = {c["COLUMN_NAME"]: (c["DATA_TYPE"], c["IS_NULLABLE"]) for c in cols_by_t[t] if not is_edl(c["COLUMN_NAME"])}
            b = base[t]
            added = sorted(set(live) - set(b))
            removed = sorted(set(b) - set(live))
            changed = sorted(c for c in set(live) & set(b) if live[c] != b[c])
            if not (added or removed or changed):
                continue
            any_diff = True
            L += [f"### {t}", ""]
            if added:
                L.append(f"- Added in {db}: " + ", ".join(f"`{c}`" for c in added))
            if removed:
                L.append(f"- In {base_db} catalog, not in {db}: " + ", ".join(f"`{c}`" for c in removed))
            for c in changed:
                L.append(f"- `{c}`: {base_db} {b[c][0]}/{'NULL' if b[c][1] == 'YES' else 'NOT NULL'} → {db} {live[c][0]}/{'NULL' if live[c][1] == 'YES' else 'NOT NULL'}")
            L.append("")
            if removed:
                questions.append((t, f"Columns {', '.join(removed)} are in the {base_db} catalog but not in {db}.{SCHEMA}. "
                                     f"Were they dropped for the next release, or is {db} behind?"))
        if not any_diff:
            L.append("- none")
        if new_tables:
            questions.insert(0, ("(schema)", f"{len(new_tables)} tables exist in {db} but not in the {base_db} catalog: "
                                             f"{', '.join(new_tables)}. Are they already deployed to production (catalog stale), "
                                             f"or {label}-only pending release?"))
        (out / "90_DELTA_VS_PROD_BASELINE.md").write_text("\n".join(L))

    # ---------- OPEN_QUESTIONS.md ----------
    L = [header(args.env, db, snap_date, "OPEN_QUESTIONS"),
         f"# {db} ({label}) — Open Questions", "",
         "Things the schema cannot tell us. Each one is marked `[REQUIRES STAKEHOLDER INPUT]` so the dashboard's "
         "\"Documents waiting on a business answer\" panel picks it up; `/document-validation` collects them into a form. "
         "Answer by editing the document named in each item, or through the form. The consolidated entries live in "
         "`VALIDATION/KB_OPEN_QUESTIONS.yaml`, section \"Lower-region database documentation\" (ids `lower_region_*`).", "", "---", ""]
    n = 0
    for scope, qtext in questions:
        n += 1
        L += [f"### {args.env.upper()}-Q{n} · {scope}", "", f"[REQUIRES STAKEHOLDER INPUT] {qtext}", "",
              f"- Evidence: `{db}.INFORMATION_SCHEMA` snapshot {snap_date}; baseline `DB-DOCS/07_DB_SCHEMA_CATALOG.md`.",
              "- Owner: Acme Claims DBA / release manager. [A: owner assumed from who deploys schema changes]", ""]
    empty_new = [t for t in tnames if int(rc[t]["ROW_COUNT"] or 0) == 0 and base_cat.exists() and t not in base] if base_cat.exists() else []
    if empty_new:
        n += 1
        L += [f"### {args.env.upper()}-Q{n} · empty new tables", "",
              f"[REQUIRES STAKEHOLDER INPUT] These {db}-only tables have no rows: {', '.join(empty_new)}. "
              "Is the loading process for them still being built, or are they seeded by the UI at first use?", "",
              "- Owner: Acme Claims dev lead / ETL owner. [A]", ""]
    n += 1
    L += [f"### {args.env.upper()}-Q{n} · code value meanings", "",
          f"[REQUIRES STAKEHOLDER INPUT] `05_DB_CODE_VALUES.md` lists the code, indicator, status, type, flag and level values present in {db} "
          "but not what they mean. `05a_DB_CODE_VALUE_QUESTIONS.md` breaks this into one block per table (registered as "
          "`code_values_<table>` in the validation form). For each column: what does each value mean, is an indicator Y/N or "
          "tri-state, which status values are terminal or legacy, and who owns the definition?", "", "- Owner: BSA. [A]", ""]
    (out / "OPEN_QUESTIONS.md").write_text("\n".join(L))

    # ---------- README + snapshot copy ----------
    L = [f"# DB-DOCS/{docs_dir} — {db} ({label})", "",
         f"Knowledge-base set for the **{label}** Snowflake environment, generated from `{db}.INFORMATION_SCHEMA` on {snap_date}.",
         "The production set (PRD01_CLAIMS) lives one level up at `DB-DOCS/` and is the team's baseline; this folder never overwrites it.", "",
         "| File | What it is |", "|---|---|",
         "| 00_DB_DISCOVERY_REPORT.md | Counts, schema layers, EDL header, table inventory with row counts, views, policies |",
         "| 07_DB_SCHEMA_CATALOG.md | Every business column on every base table (same layout as the P01 catalog, so the two diff cleanly) |",
         "| 05_DB_CODE_VALUES.md | Distinct values seen in code/indicator/status columns |",
         "| 06_DB_SECURITY_INVENTORY.md | Row-access policy references, PHI view schemas, identifier-looking columns |",
         "| 90_DELTA_VS_PROD_BASELINE.md | Table and column differences against the P01 catalog |",
         "| OPEN_QUESTIONS.md | `[REQUIRES STAKEHOLDER INPUT]` items for the dashboard / document-validation |",
         "| DB_TABLE_REGISTRY.yaml | Machine-readable registry (tables, columns, PK constraint, policy) |",
         "| _snapshot/ | The raw INFORMATION_SCHEMA extract the files above were rendered from |", "",
         "## Regenerate", "", "```", f"python3 sdlc/framework/tools/kbgen/extract_db_snapshot.py --env {args.env}   # prints the SQL to run through the Snowflake MCP",
         f"python3 sdlc/framework/tools/kbgen/gen_db_kb.py --env {args.env} --snapshot <folder with the JSON results>", "```", "",
         "Or run `/app-knowledge-refresh --env " + args.env + "`, which does both and writes here.", ""]
    (out / "README.md").write_text("\n".join(L))
    snapdir = out / "_snapshot"
    snapdir.mkdir(exist_ok=True)
    for name in ("tables", "columns", "schemas", "views", "constraints", "policies", "codes", "meta"):
        src = snapshot / f"{name}.json"
        if src.exists():
            json.dump(json.load(open(src)), open(snapdir / f"{name}.json", "w"), separators=(",", ":"), sort_keys=True)
    print(f"wrote {len(list(out.glob('*')))} files to {out.relative_to(REPO)}; {len(tnames)} tables, {total_cols} columns, {len(questions)} delta questions")


if __name__ == "__main__":
    main()
