"""Database catalog collection (Snowflake, AWS RDS and similar). Metadata only: INFORMATION_SCHEMA / catalog views, never row data.

The connection is created lazily from environment variables; the query runner is injectable so the logic is testable offline.
Snowflake in a headless VM cannot use 'externalbrowser' SSO; use an OAuth token or key-pair instead (SNOWFLAKE_AUTHENTICATOR=oauth + SNOWFLAKE_TOKEN).
"""
from __future__ import annotations

import os
from typing import Callable

from ..facts import ev, make_fact
from .readonly import check_sql

SNOWFLAKE_QUERIES = {
    "tables": ("SELECT table_catalog, table_schema, table_name, table_type FROM {db}.INFORMATION_SCHEMA.TABLES "
               "WHERE table_schema <> 'INFORMATION_SCHEMA'"),
    "columns": ("SELECT table_schema, table_name, column_name, data_type, is_nullable, ordinal_position FROM {db}.INFORMATION_SCHEMA.COLUMNS "
                "WHERE table_schema <> 'INFORMATION_SCHEMA'"),
}
POSTGRES_QUERIES = {
    "tables": "SELECT table_catalog, table_schema, table_name, table_type FROM information_schema.tables WHERE table_schema NOT IN ('pg_catalog','information_schema')",
    "columns": ("SELECT table_schema, table_name, column_name, data_type, is_nullable, ordinal_position FROM information_schema.columns "
                "WHERE table_schema NOT IN ('pg_catalog','information_schema')"),
}


def collect_catalog(engine: str, label: str, run_query: Callable[[str], list[tuple]], database: str = "",
                    schemas: list[str] | None = None, max_rows: int = 50_000) -> list[dict]:
    """label: logical name used in citations (never a host). Only metadata statements pass check_sql."""
    q = SNOWFLAKE_QUERIES if engine == "snowflake" else POSTGRES_QUERIES
    facts: list[dict] = []
    src = f"{engine}:{label}"
    for name in ("tables", "columns"):
        sql = q[name].format(db=database or "CURRENT_DATABASE()") if engine == "snowflake" else q[name]
        check_sql(sql)
        rows = run_query(sql)[:max_rows]
        for r in rows:
            if name == "tables":
                _, schema, table, ttype = r[:4]
                if schemas and schema not in schemas:
                    continue
                facts.append(make_fact("db_table", f"{label}.{schema}.{table}".lower(), {"engine": engine, "schema": schema, "table": table.lower(), "table_type": ttype},
                                       "OBSERVED", [ev(src, f"INFORMATION_SCHEMA.TABLES {schema}.{table}")], "db_catalog"))
            else:
                schema, table, col, dtype, nullable, pos = r[:6]
                if schemas and schema not in schemas:
                    continue
                facts.append(make_fact("db_column", f"{label}.{schema}.{table}.{col}".lower(), {
                    "engine": engine, "schema": schema, "table": table.lower(), "column": col.lower(), "data_type": dtype,
                    "nullable": str(nullable).upper() in ("YES", "Y", "TRUE"), "position": pos},
                    "OBSERVED", [ev(src, f"INFORMATION_SCHEMA.COLUMNS {schema}.{table}.{col}")], "db_catalog"))
    return facts


def snowflake_runner() -> Callable[[str], list[tuple]]:
    """Open a Snowflake connection from env (oauth token or key-pair). Metadata queries only."""
    import snowflake.connector  # type: ignore  # optional dependency, imported lazily
    auth = os.environ.get("SNOWFLAKE_AUTHENTICATOR", "oauth")
    if auth == "externalbrowser":
        raise RuntimeError("externalbrowser SSO needs a GUI browser; use SNOWFLAKE_AUTHENTICATOR=oauth with SNOWFLAKE_TOKEN, or key-pair auth")
    kw = {"account": os.environ["SNOWFLAKE_ACCOUNT"], "authenticator": auth, "role": os.environ.get("SNOWFLAKE_ROLE"),
          "warehouse": os.environ.get("SNOWFLAKE_WAREHOUSE"), "database": os.environ.get("SNOWFLAKE_DATABASE")}
    if auth == "oauth":
        kw["token"] = os.environ["SNOWFLAKE_TOKEN"]
    conn = snowflake.connector.connect(**{k: v for k, v in kw.items() if v})

    def run(sql: str):
        check_sql(sql)
        cur = conn.cursor()
        try:
            cur.execute(sql)
            return cur.fetchall()
        finally:
            cur.close()
    return run


def rds_inventory(describe: Callable[[], list[dict]]) -> list[dict]:
    """Instance metadata from the AWS API (describe-db-instances). Endpoint hosts are dropped; only engine/version/class are kept."""
    facts = []
    for i in describe():
        ident = i.get("DBInstanceIdentifier", "?")
        facts.append(make_fact("db_instance", f"rds:{ident}", {
            "engine": i.get("Engine"), "engine_version": i.get("EngineVersion"), "instance_class": i.get("DBInstanceClass"),
            "multi_az": i.get("MultiAZ"), "storage_gb": i.get("AllocatedStorage")},
            "OBSERVED", [ev(f"aws-rds:{ident}", "DescribeDBInstances")], "db_catalog"))
    return facts
