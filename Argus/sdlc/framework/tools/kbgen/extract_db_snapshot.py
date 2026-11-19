"""Print (or record) the INFORMATION_SCHEMA queries that make up a DB knowledge-base snapshot.

Snowflake is reached through the user-scoped Snowflake nonprod MCP (`sql_exec_tool`), which
runs in the Devin session rather than on this box, so this script cannot execute the SQL itself.
It does two things instead:

1. `--env sit` prints every statement, in order, with the JSON file each result must be saved to.
   The Devin session runs them through `sql_exec_tool` and writes each result set as a list of
   row dicts ({column: value}) to <snapshot>/<name>.json, plus meta.json with the snapshot date.
2. `--check <snapshot>` verifies a snapshot folder is complete before gen_db_kb.py is run.

Per-table statements (policy references, code-value distributions) are emitted as templates; the
session expands them over the table list from tables.json. Result shape per file:

  tables.json       INFORMATION_SCHEMA.TABLES rows for the SDLC schemas
  columns.json      INFORMATION_SCHEMA.COLUMNS rows for CLAIMS_UI_DATA
  schemas.json      INFORMATION_SCHEMA.SCHEMATA rows
  views.json        INFORMATION_SCHEMA.VIEWS rows for the CLAIMS_UI_DATA* and ETL_SEMANTIC schemas
  constraints.json  INFORMATION_SCHEMA.TABLE_CONSTRAINTS rows for CLAIMS_UI_DATA
  policies.json     {table: [POLICY_REFERENCES rows]}
  codes.json        {table: [{COL, VAL, N}]}  (columns with <= 30 distinct values kept; RAW_* platform
                    audit columns left out; a table whose result is too big for one call is
                    counted column by column; rows ordered by COL, then N descending)
  ui_mstr_terms.json  VBC_UI_CNTRCT_MSTR_TERMS rows (read by gen_ui_field_map.py; optional here, but
                      without it every Contract stepper field comes out NOT_IN_MASTER_TERMS)
  ui_term_xref.json   VBC_UI_MSTR_TERM_XREF rows (same)
  meta.json         {"database": ..., "snapshot_date": "YYYY-MM-DD"}
"""
import argparse
import json
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[4]
ENV_FILE = REPO / ".devin" / "rules" / "snowflake-environments.yaml"
SCHEMA = "CLAIMS_UI_DATA"
SUPPORT_SCHEMAS = "'CLAIMS_DATA_STG','CLAIMS_DATA_RAWZ','CLAIMS_DATA_RAWZ_STG','CLAIMS_DATA_ETL_SEMANTIC','CLAIMS_DATA_APPCODE'"
AUDIT_COLUMN_PREFIX = "RAW_"
CODE_COLUMN_SUFFIXES = ("_CD", "_IND", "_TYPE", "_STTS", "_FLAG", "_FLG", "_LVL")
REQUIRED = ("tables", "columns", "schemas", "views", "constraints", "policies", "codes", "meta")


def statements(db):
    return [
        ("tables.json", f"""SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE, ROW_COUNT, BYTES, COMMENT, CREATED::DATE AS CREATED,
       LAST_ALTERED::DATE AS LAST_ALTERED, RETENTION_TIME, IS_TRANSIENT, CLUSTERING_KEY
FROM {db}.INFORMATION_SCHEMA.TABLES
WHERE TABLE_SCHEMA LIKE '{SCHEMA}%' OR TABLE_SCHEMA IN ({SUPPORT_SCHEMAS})
ORDER BY 1, 2"""),
        ("columns.json", f"""SELECT TABLE_NAME, ORDINAL_POSITION, COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, NUMERIC_PRECISION,
       NUMERIC_SCALE, IS_NULLABLE, COLUMN_DEFAULT, COMMENT, IS_IDENTITY
FROM {db}.INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = '{SCHEMA}' ORDER BY 1, 2"""),
        ("schemas.json", f"""SELECT SCHEMA_NAME, RETENTION_TIME, IS_TRANSIENT, IS_MANAGED_ACCESS, CREATED::DATE AS CREATED, COMMENT
FROM {db}.INFORMATION_SCHEMA.SCHEMATA ORDER BY 1"""),
        ("views.json", f"""SELECT TABLE_SCHEMA, TABLE_NAME, IS_SECURE FROM {db}.INFORMATION_SCHEMA.VIEWS
WHERE TABLE_SCHEMA LIKE '{SCHEMA}%' OR TABLE_SCHEMA = 'CLAIMS_DATA_ETL_SEMANTIC' ORDER BY 1, 2"""),
        ("constraints.json", f"""SELECT TABLE_NAME, CONSTRAINT_NAME, CONSTRAINT_TYPE FROM {db}.INFORMATION_SCHEMA.TABLE_CONSTRAINTS
WHERE TABLE_SCHEMA = '{SCHEMA}' ORDER BY 1, 2"""),
        ("ui_mstr_terms.json", f"""SELECT TERM_ID, TERM_NM, TERM_TYPE_CD, UI_TYPE_CD, CNFGRN_ID, GRP_NM, GRP_ID, DSPLY_SQNC_NBR, BSNS_DESC
FROM {db}.{SCHEMA}.VBC_UI_CNTRCT_MSTR_TERMS ORDER BY TERM_ID"""),
        ("ui_term_xref.json", f"""SELECT TERM_ID, TERM_TBL_NM, TERM_CLMN_NM, ACTV_IND
FROM {db}.{SCHEMA}.VBC_UI_MSTR_TERM_XREF ORDER BY TERM_ID, TERM_TBL_NM, TERM_CLMN_NM"""),
        ("policies.json  (one call per table in tables.json, keyed by table)",
         f"""SELECT POLICY_DB, POLICY_SCHEMA, POLICY_NAME, POLICY_KIND, REF_COLUMN_NAME, POLICY_STATUS
FROM TABLE({db}.INFORMATION_SCHEMA.POLICY_REFERENCES(REF_ENTITY_NAME => '{db}.{SCHEMA}.<TABLE>', REF_ENTITY_DOMAIN => 'TABLE'))"""),
        ("codes.json  (one call per table with rows; UNION ALL one SELECT per column whose name ends in "
         + "/".join(CODE_COLUMN_SUFFIXES) + ", except " + AUDIT_COLUMN_PREFIX + "* audit columns; keep columns with <= 30 distinct values)",
         f"""SELECT '<COL>' AS COL, <COL>::VARCHAR AS VAL, COUNT(*) AS N FROM {db}.{SCHEMA}.<TABLE> GROUP BY 1, 2"""),
    ]


def check(folder):
    folder = Path(folder)
    missing = [n for n in REQUIRED if not (folder / f"{n}.json").exists()]
    if missing:
        print("missing:", ", ".join(missing))
        return 1
    tables = json.load(open(folder / "tables.json"))
    base = [t["TABLE_NAME"] for t in tables if t["TABLE_SCHEMA"] == SCHEMA and t["TABLE_TYPE"] == "BASE TABLE"]
    pol = json.load(open(folder / "policies.json"))
    codes = json.load(open(folder / "codes.json"))
    gaps = [t for t in base if t not in pol or t not in codes]
    errs = [t for t in base if isinstance(pol.get(t), dict) or isinstance(codes.get(t), dict)]
    meta = json.load(open(folder / "meta.json"))
    print(f"{meta.get('database')} snapshot {meta.get('snapshot_date')}: {len(base)} base tables, "
          f"{len(json.load(open(folder / 'columns.json')))} columns; per-table gaps: {gaps or 'none'}; errors: {errs or 'none'}")
    return 1 if gaps else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env")
    ap.add_argument("--check", metavar="SNAPSHOT_DIR")
    a = ap.parse_args()
    if a.check:
        sys.exit(check(a.check))
    if not a.env:
        ap.error("--env or --check is required")
    envs = yaml.safe_load(ENV_FILE.read_text())
    if a.env not in envs["environments"]:
        sys.exit(f"{a.env} is not in {ENV_FILE}")
    db = envs["environments"][a.env]["database"]
    print(f"Snowflake target: {db} ({a.env})\n")
    for target, sql in statements(db):
        print(f"-- => {target}\n{sql};\n")


if __name__ == "__main__":
    main()
