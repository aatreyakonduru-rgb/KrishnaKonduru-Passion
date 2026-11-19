"""Analyses derived deterministically from facts: cross-links, environment matrix, ownership, PII map, lineage, diagram-vs-code."""
from __future__ import annotations

import re
from collections import defaultdict

from .facts import ev, make_fact

_PII_COL = re.compile(r"(?i)(ssn|social|passport|dob|birth|email|phone|mobile|address|first_?name|last_?name|full_?name|salary|iban|card|pan|national|tax_?id|gender)")


def link_facts(facts: list[dict]) -> list[dict]:
    """Cross-linking: exact matches only. Each link is a DERIVED fact recording its rule."""
    links: list[dict] = []
    keys_defined: dict[str, list[dict]] = defaultdict(list)
    for f in facts:
        if f["kind"] == "config_entry":
            keys_defined[f["attrs"]["key"]].append(f)
    for f in facts:
        k, a = f["kind"], f["attrs"]
        if k == "config_key_use" and a["key"] in keys_defined:
            for d in keys_defined[a["key"]][:5]:
                links.append(make_fact("link", f"config-used-by:{a['key']}", {"relation": "config_key_used_in_code", "key": a["key"],
                                       "code": f"{a['repo']}/{a['path']}", "config": f"{d['attrs']['repo']}/{d['attrs']['path']}",
                                       "environment": d["attrs"].get("environment")}, "DERIVED", f["evidence"] + d["evidence"][:1], "linker",
                                       "exact match: @Value/getProperty key == config key"))
        if k == "env_var_use":
            nm = a["name"]
            for d in keys_defined.get(nm, [])[:3]:
                links.append(make_fact("link", f"env-var:{nm}", {"relation": "env_var_defined_in_config", "name": nm, "code": f"{a['repo']}/{a['path']}"},
                                       "DERIVED", f["evidence"] + d["evidence"][:1], "linker", "exact match: env var name == config key"))
    endpoints = {(f["attrs"]["verb"], f["attrs"]["path"]): f for f in facts if f["kind"] == "endpoint"}
    for f in facts:
        if f["kind"] == "api_operation" and f["attrs"].get("protocol") == "rest":
            key = (f["attrs"]["verb"], f["attrs"]["path"])
            if key in endpoints:
                e = endpoints[key]
                links.append(make_fact("link", f"contract-served-by:{key[0]} {key[1]}", {
                    "relation": "contract_operation_implemented_by_code", "operation": f"{key[0]} {key[1]}",
                    "contract": f"{f['attrs']['repo']}/{f['attrs'].get('path_file')}", "code": f"{e['attrs']['repo']}/{e['attrs']['file']}"},
                    "DERIVED", f["evidence"] + e["evidence"][:1], "linker", "exact match: verb and path identical in contract and code"))
    tables = {f["attrs"]["table"] for f in facts if f["kind"] == "db_table"}
    for f in facts:
        if f["kind"] == "table_reference" and f["attrs"]["table"] in tables:
            links.append(make_fact("link", f"table-used:{f['attrs']['table']}", {"relation": "code_references_catalog_table", "table": f["attrs"]["table"],
                                   "code": f"{f['attrs']['repo']}/{f['attrs']['path']}"}, "DERIVED", f["evidence"], "linker",
                                   "exact name match between static SQL text and catalog table name"))
    return links


def env_matrix(facts: list[dict], normalize) -> dict:
    """{key: {ENV: value}} with differences flagged. Secret-like keys appear as presence only."""
    matrix: dict[str, dict[str, str]] = defaultdict(dict)
    for f in facts:
        if f["kind"] != "config_entry":
            continue
        a = f["attrs"]
        env = normalize(a["environment"]) if a.get("environment") else None
        if not env:
            continue
        label = "[present]" if a.get("secret_like") else str(a["value"])
        matrix[f"{a['repo']}::{a['key']}"][env] = label
    rows = []
    envs = sorted({e for r in matrix.values() for e in r})
    for key, vals in sorted(matrix.items()):
        distinct = {v for v in vals.values()}
        rows.append({"key": key, "values": vals, "differs": len(distinct) > 1, "missing_in": [e for e in envs if e not in vals]})
    return {"environments": envs, "rows": rows}


def ownership(facts: list[dict], codeowners: list[tuple[str, str, str]]) -> list[dict]:
    """codeowners: [(repo, pattern, owner)]. Records only what CODEOWNERS states."""
    return [{"repo": r, "pattern": p, "owner": o, "source": f"{r}/CODEOWNERS"} for r, p, o in codeowners]


def pii_candidates(facts: list[dict]) -> list[dict]:
    """Indicator only: column or field names that look personal. For human review, not a compliance determination."""
    out = []
    for f in facts:
        if f["kind"] == "db_column" and _PII_COL.search(f["attrs"].get("column", "")):
            out.append({"where": f["subject"], "name": f["attrs"]["column"], "basis": "column name pattern", "evidence": f["evidence"][0]})
        if f["kind"] == "api_schema":
            for p in f["attrs"].get("properties", []):
                if _PII_COL.search(p):
                    out.append({"where": f["subject"], "name": p, "basis": "API field name pattern", "evidence": f["evidence"][0]})
    return out


def doc_vs_code(facts: list[dict]) -> list[dict]:
    """Report documented diagram connections whose endpoints are known apps but have no code-derived evidence. Report-only."""
    apps = {f["attrs"].get("repo") for f in facts if f["kind"] == "source_file"}
    code_edges = {(f["attrs"]["repo"], u) for f in facts if f["kind"] == "url_reference" for u in [f["attrs"]["url"]]}
    out = []
    for f in facts:
        if f["kind"] == "diagram_edge":
            a, b = f["attrs"]["from"], f["attrs"]["to"]
            known = [x for x in (a, b) if x in apps]
            out.append({"type": "documented-connection", "from": a, "to": b, "known_apps_in_edge": known,
                        "verification": "not verified against code: no cross-service call analysis for this pair" if known else "endpoints not matched to code apps",
                        "evidence": f["evidence"][0]})
    return out


def lineage(facts: list[dict]) -> list[dict]:
    """API field -> code file -> table, only where exact names appear. Marked static-only."""
    cols: dict[str, list[dict]] = defaultdict(list)
    for f in facts:
        if f["kind"] == "db_column":
            cols[f["attrs"]["column"].lower()].append(f)
    out = []
    for f in facts:
        if f["kind"] == "api_schema":
            for p in f["attrs"].get("properties", []):
                for c in cols.get(p.lower(), [])[:3]:
                    out.append({"api_field": f"{f['attrs']['name']}.{p}", "column": c["subject"], "basis": "identical name only; not a verified data flow",
                                "evidence": [f["evidence"][0], c["evidence"][0]]})
    return out
