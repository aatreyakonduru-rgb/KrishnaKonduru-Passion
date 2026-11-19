"""Build the Acme Claims ontology from the knowledge base: a business layer (objects, relationships,
states, rules) over a data layer (datasets, tables, columns, jobs, lineage), plus impact paths.

Nothing is inferred: every item is copied from a KB file and names that file. Links between the
layers are made only where a table name matches exactly. What the sources cannot settle is
listed under open_questions.

    python3 sdlc/framework/tools/kbgen/gen_ontology.py [--out-dir DIR]
"""
import argparse
import datetime
import json
import os
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import artifact_kit  # noqa: E402
from artifact_kit import esc  # noqa: E402

REPO = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
KB = "docs/knowledge-base"
SRC = {
    "entities": KB + "/DB-DOCS/13_DB_ENTITY_REGISTRY.yaml",
    "semantic": KB + "/DB-DOCS/09_DB_SEMANTIC_LAYER.yaml",
    "lineage": KB + "/DB-DOCS/11_DB_DATA_LINEAGE.yaml",
    "contracts": KB + "/DB-DOCS/11_DB_DATA_CONTRACTS.yaml",
    "registry": KB + "/DB-DOCS/DB_TABLE_REGISTRY.yaml",
    "cff": KB + "/DB-DOCS/15_CFF_TABLE_CATALOGUE.yaml",
    "glossary_cols": KB + "/DB-DOCS/DB_COLUMN_GLOSSARY.yaml",
    "app_joins": KB + "/DB-DOCS/16_DB_APP_JOINS.yaml",
    "etl_io": KB + "/ETL/claims-etl/13_ETL_TABLE_IO_CONTRACT.yaml",
    "etl_patterns": KB + "/ETL/claims-etl/12_ETL_SQL_PATTERNS.yaml",
    "impact": KB + "/CROSS-LAYER/CROSS_LAYER_IMPACT_MATRIX.CURATED.yaml",
    "app_matrix": KB + "/CROSS-LAYER/CROSS_LAYER_IMPACT_MATRIX.yaml",
    "t01": KB + "/DB-DOCS/SIT/22_DB_COLUMN_SNAPSHOT.yaml",
    "qa": KB + "/QA-AUTOMATION-DERIVED/03_QA_SUITE_COVERAGE.yaml",
    "fin_catalog": KB + "/ETL/claims-etl-sdlcfin_files/02_FINANCE_METRICS_AGENT_CATALOG.yaml",
    "fin_t01": KB + "/DB-DOCS/SIT/23_FIN_COLUMN_SNAPSHOT.yaml",
}
OUT_DIR = KB + "/CROSS-LAYER"
ETL_REPO = "ACMEETL/claims-etl"


def load(key):
    with open(os.path.join(REPO, SRC[key]), encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def fname(key):
    return os.path.basename(SRC[key])


def slug(name):
    return "".join(c if c.isalnum() else "_" for c in name.lower()).strip("_")


def as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


# ---------------------------------------------------------------- business layer

def build_objects(ent, sem):
    sem_aliases = (sem.get("guardrails") or {}).get("entity_aliases") or {}
    sem_entities = sem.get("entities") or {}
    objects = []
    for e in ent.get("entities", []):
        oid = slug(e["canonical_name"])
        sem_key = next((k for k, v in sem_entities.items() if v.get("primary_table") == e.get("canonical_table")), None)
        aliases = list(dict.fromkeys(as_list(e.get("aliases")) + as_list((sem_aliases.get(sem_key) or {}).get("aliases"))))
        obj = {
            "id": oid,
            "entity_id": e["entity_id"],
            "label": e["canonical_name"],
            "aliases": aliases,
            "table": e.get("canonical_table"),
            "key": e.get("canonical_key"),
        }
        if sem_key and sem_entities[sem_key].get("display_name"):
            obj["display"] = sem_entities[sem_key]["display_name"]
        if e.get("active_record_filter"):
            obj["current_row"] = e["active_record_filter"]
        if e.get("status_location"):
            s = e["status_location"]
            obj["status"] = {"table": s.get("table"), "column": s.get("column"), "join": s.get("join")}
        if e.get("contract_types"):
            obj["types"] = [{"code": t["code"], "name": t["name"]} for t in e["contract_types"]]
        for k in ("dependency_flow", "link_to_pg", "tracking_table", "description"):
            if e.get(k):
                obj[k] = e[k]
        related = list(dict.fromkeys(as_list(e.get("related_tables")) +
                                     as_list((sem_entities.get(sem_key) or {}).get("related_tables"))))
        if related:
            obj["related_tables"] = related
        obj["confidence"] = e.get("confidence")
        obj["source"] = "%s %s; %s" % (fname("entities"), e["entity_id"], e.get("source", ""))
        objects.append(obj)
    return objects


def table_owner_map(objects):
    """table -> object id, only for tables an entity names as its canonical or status table."""
    owners = {}
    for o in objects:
        if o.get("table"):
            owners.setdefault(o["table"], o["id"])
        if o.get("status"):
            owners.setdefault(o["status"]["table"], o["id"])
    return owners


def build_relationships(sem, objects):
    owners = table_owner_map(objects)
    rels = []
    for j in sem.get("joins", []):
        rels.append({
            "id": slug(j["name"]),
            "name": j["name"],
            "from_table": j["left_table"],
            "to_table": j["right_table"],
            "from_object": owners.get(j["left_table"]),
            "to_object": owners.get(j["right_table"]),
            "join": j["join_key"],
            "cardinality": j.get("cardinality"),
            "note": j.get("note"),
            "confidence": j.get("confidence"),
            "source": "%s joins" % fname("semantic"),
        })
    # Bridge: a table that joins to two different objects links those objects.
    bridges = {}
    for r in rels:
        if r["to_object"] and not r["from_object"]:
            bridges.setdefault(r["from_table"], set()).add(r["to_object"])
    for table, objs in sorted(bridges.items()):
        if len(objs) == 2:
            a, b = sorted(objs)
            rels.append({
                "id": "%s_via_%s" % (a + "_" + b, slug(table)),
                "name": "%s ↔ %s (via %s)" % (a, b, table),
                "from_object": a, "to_object": b, "via": table,
                "cardinality": "many-to-many (bridge table)",
                "source": "%s joins (both joins from %s)" % (fname("semantic"), table),
            })
    pairs = {frozenset((r.get("from_object"), r.get("to_object"))) for r in rels}
    for o in objects:
        if o.get("link_to_pg") and frozenset((o["id"], owners.get("CL_PG_PROV_HRCHY"))) not in pairs:
            rels.append({"id": "%s_to_provider_group" % o["id"], "name": "%s → TIN/NPI" % o["label"],
                         "from_object": o["id"], "to_object": owners.get("CL_PG_PROV_HRCHY"),
                         "join": o["link_to_pg"], "source": "%s %s link_to_pg" % (fname("entities"), o["entity_id"])})
    return rels


def build_states(sem):
    out = {}
    for name, d in (sem.get("value_dictionaries") or {}).items():
        out[name] = {"description": d.get("description"), "values": d.get("values")}
        if d.get("flow"):
            out[name]["flow"] = d["flow"]
        out[name]["source"] = "%s value_dictionaries" % fname("semantic")
    return out


def build_phrases(ent):
    out = []
    for a in ent.get("code_aliases", []):
        out.append({"id": a["alias_id"], "phrases": as_list(a.get("user_phrase")), "resolves_to": a.get("resolves_to"),
                    "sql": a.get("sql_snippet"), "source": "%s %s" % (fname("entities"), a["alias_id"])})
    return out


def build_metrics(cat):
    out = []
    for m in (cat or {}).get("metrics") or []:
        out.append({"id": m["id"], "label": m.get("name"), "aliases": as_list(m.get("also_called")), "area": m.get("area"),
                    "means": m.get("means"), "how": m.get("how"),
                    "tables": [t.get("table") for t in m.get("tables") or [] if t.get("table")],
                    "code_note": m.get("code_note"),
                    "source": "%s metrics.%s" % (fname("fin_catalog"), m["id"])})
    return out


def build_finance_tables(snap):
    out = []
    for name, t in sorted(((snap or {}).get("tables") or {}).items()):
        out.append({"name": name, "schema": snap.get("schema"), "work_table": t.get("work_table", False),
                    "columns": sorted((t.get("columns") or {}).keys()),
                    "source": "%s (%s, column names only)" % (fname("fin_t01"), snap.get("database"))})
    return out


def build_rules(sem):
    g = sem.get("guardrails") or {}
    out = []
    for group in ("mandatory_filters", "forbidden_actions", "query_rules", "response_rules"):
        for text in g.get(group, []):
            out.append({"kind": group, "rule": text, "source": "%s guardrails.%s" % (fname("semantic"), group)})
    return out


def build_processes(lin):
    out = []
    for f in lin.get("internal_flows", []):
        p = {"id": f["flow_id"], "name": f["name"], "description": (f.get("description") or "").strip()}
        if f.get("stages"):
            p["stages"] = [{"stage": s.get("stage"), "tables": s.get("tables"), "trigger": s.get("trigger"),
                            "status_written": s.get("status_written")} for s in f["stages"]]
        if f.get("execution_order"):
            p["execution_order"] = [{"step": s.get("step"), "jobs": s.get("jobs"), "depends_on": s.get("depends_on")}
                                    for s in f["execution_order"]]
        if f.get("routing_rules"):
            p["routing_rules"] = [{"rqst_type_codes": r.get("rqst_type_codes"), "detail_table": r.get("detail_table")}
                                  for r in f["routing_rules"]]
        p["confidence"] = f.get("confidence")
        p["source"] = "%s %s" % (fname("lineage"), f["flow_id"])
        out.append(p)
    return out


# ---------------------------------------------------------------- data layer

def build_datasets(reg, lin):
    ds = [{
        "id": "sdlc_ui_base",
        "location": "%s.%s" % (reg.get("database"), reg.get("schema")),
        "row_policy": (reg.get("row_access_policy") or {}).get("name"),
        "row_policy_columns": (reg.get("row_access_policy") or {}).get("columns"),
        "versioning": reg.get("versioning_defaults"),
        "source": fname("registry"),
    }]
    for p in lin.get("phi_flows", []):
        if not p.get("phi_column_example"):
            continue
        ds.append({
            "id": "phi_tiers_%s" % slug(p.get("phi_column_example", "")),
            "example_column": "%s.%s" % (p.get("source_table"), p.get("phi_column_example")),
            "masked_in": p.get("masked_in"), "unmasked_in": p.get("unmasked_in"),
            "masking_policy": p.get("masking_policy"),
            "source": "%s phi_flows" % fname("lineage"),
        })
    return ds


def build_tables(reg, cff, gcols, etl, joins, contracts, objects, lin, t01):
    owners = table_owner_map(objects)
    related = {}
    for o in objects:
        for t in o.get("related_tables", []):
            related.setdefault(t, []).append(o["id"])
    phi = {}
    for e in gcols.get("entries", []):
        for col, c in (e.get("columns") or {}).items():
            phi[(e["table"], col)] = c.get("pii_phi")
    for p in lin.get("phi_flows", []):
        phi[(p.get("source_table"), p.get("phi_column_example"))] = True
    contract_cols = {}
    for t in contracts.get("tables", []):
        for c in t.get("contracts", []):
            contract_cols[(t["table"], c["column"])] = c

    tables = {}

    def get(name):
        return tables.setdefault(name, {"name": name, "sources": []})

    for t in reg.get("tables", []):
        x = get(t["name"])
        x.update({"layer": t.get("layer"), "module": t.get("module"), "status": t.get("status")})
        if t.get("pk"):
            x["pk"] = t["pk"]
        x["_cols"] = {c["name"]: {"name": c["name"], "type": c.get("type"), "nullable": c.get("nullable")}
                      for c in t.get("columns", [])}
        x["sources"].append(fname("registry"))
    for t in cff.get("tables", []):
        x = get(t["table"])
        x.setdefault("module", t.get("module"))
        x["cff_sheet"] = t.get("cff_sheet")
        x["ui_section"] = t.get("ui_section")
        cols = x.setdefault("_cols", {})
        for c in t.get("columns", []):
            cur = cols.setdefault(c["column"], {"name": c["column"]})
            cur.setdefault("type", c.get("datatype"))
            cur["mandatory"] = c.get("mandatory")
            if c.get("description"):
                cur["description"] = c["description"]
        x["sources"].append(fname("cff"))
    for t in etl.get("tables", []):
        if t.get("kind") == "temp":
            continue
        x = get(t["name"])
        x["etl_read_by"] = t.get("read_by") or []
        x["etl_written_by"] = t.get("written_by") or []
        x["sources"].append(fname("etl_io"))
    for name in joins.get("tables", []):
        get(name)["sources"].append(fname("app_joins"))
    env = (t01.get("metadata") or {}).get("environment", "T01")
    for t in t01.get("tables", []):
        x = get(t["name"])
        cols = x.setdefault("_cols", {})
        for c in t.get("columns", []):
            cur = cols.setdefault(c["name"], {"name": c["name"]})
            if not cur.get("type"):
                cur["type"] = c.get("type")
                cur["type_from"] = env
            if cur.get("nullable") is None and "mandatory" not in cur:
                cur["nullable"] = c.get("nullable")
            if c.get("phi_mask"):
                cur["phi"] = True
                cur["phi_mask"] = c["phi_mask"]
                cur["phi_from"] = env
        x["sources"].append("SIT/" + fname("t01"))

    out = []
    for name in sorted(tables):
        x = tables[name]
        cols = x.pop("_cols", {})
        for (tname, col), flag in phi.items():
            if tname == name and flag is not None and "phi_from" not in cols.get(col, {}):
                cols.setdefault(col, {"name": col})["phi"] = bool(flag)
        for (tname, col), c in contract_cols.items():
            if tname == name:
                cur = cols.setdefault(col, {"name": col})
                cur["contract"] = {k: c[k] for k in ("api_field", "fe_display", "fe_location", "validation") if c.get(k)}
        if cols:
            x["columns"] = list(cols.values())
        rep = []
        if name in owners:
            rep.append(owners[name])
        rep += [o for o in related.get(name, []) if o not in rep]
        if rep:
            x["represents"] = rep
        x["sources"] = sorted(set(x["sources"]))
        out.append(x)
    return out


def build_jobs(etl, patterns):
    used_by = {}
    for p in patterns.get("patterns", []):
        for f in p.get("used_by", []):
            used_by.setdefault(f, []).append("%s %s" % (p["id"], p["name"]))
    jobs = []
    for kind in ("sql_scripts", "python_scripts"):
        for s in etl.get(kind, []):
            j = {"id": s["name"], "repo": ETL_REPO, "path": s.get("path"), "kind": kind.split("_")[0],
                 "description": s.get("description") or None,
                 "reads": sorted(set(s.get("reads") or [])), "writes": sorted(set(s.get("writes") or []))}
            if used_by.get(s["name"]):
                j["patterns"] = used_by[s["name"]]
            j["source"] = fname("etl_io")
            jobs.append(j)
    return jobs


def build_lineage(jobs, lin, temp):
    edges = []
    for j in jobs:
        for r in j["reads"]:
            if r in temp:
                continue
            for w in j["writes"]:
                if w in temp or w == r:
                    continue
                edges.append({"from": r, "via": j["id"], "to": w, "source": fname("etl_io")})
    systems = []
    for f in lin.get("inbound_flows", []):
        systems.append({"id": f["flow_id"], "direction": "in", "name": f["name"], "system": f.get("source_system"),
                        "tables": f.get("target_tables"), "trigger": f.get("trigger"),
                        "confidence": f.get("confidence"), "source": "%s %s" % (fname("lineage"), f["flow_id"])})
    for f in lin.get("outbound_flows", []):
        systems.append({"id": f["flow_id"], "direction": "out", "name": f["name"], "system": f.get("consumer_system"),
                        "system_name": f.get("consumer_full_name"), "tables": f.get("source_tables"),
                        "trigger": f.get("trigger"), "note": (f.get("note") or "").strip() or None,
                        "confidence": f.get("confidence"), "source": "%s %s" % (fname("lineage"), f["flow_id"])})
    return edges, systems


def build_column_lineage(t01):
    """Cross-table column edges Snowflake saw written (ACCESS_HISTORY); same-table rewrites are dropped."""
    out = []
    for e in t01.get("column_lineage", []):
        st, tt = e["source"].rsplit(".", 1)[0], e["target"].rsplit(".", 1)[0]
        if st != tt:
            out.append({"source": e["source"], "target": e["target"], "queries_30d": e.get("queries_30d"),
                        "last_seen": e.get("last_seen")})
    return out


def build_application(matrix, objects, tables):
    """Screens -> endpoints -> tables, copied from the cross-layer impact matrix (code is the evidence)."""
    src = fname("app_matrix")
    endpoints = []
    for eid, e in sorted((matrix.get("endpoints") or {}).items()):
        endpoints.append({"id": eid, "app": e.get("app"), "handler": e.get("handler"),
                          "code": "%s:%s" % (e.get("file"), e.get("line")),
                          "tables_read": e.get("tables_read") or [], "tables_written": e.get("tables_written") or [],
                          "table_evidence_scope": e.get("table_evidence_scope"), "screens": e.get("screens") or [],
                          "source": "%s endpoints" % src})
    screens = []
    for route, sc in sorted((matrix.get("screens") or {}).items()):
        screens.append({"route": route, "page": sc.get("page"), "services": sc.get("services") or [],
                        "endpoints": sc.get("endpoints") or [], "tables": sc.get("tables") or [],
                        "fields": sc.get("fields") or [], "source": "%s screens" % src})
    by_table = {t["name"]: t for t in tables}
    for e in endpoints:
        for kind, key in (("api_reads", "tables_read"), ("api_writes", "tables_written")):
            for t in e[key]:
                if t in by_table:
                    by_table[t].setdefault(kind, []).append(e["id"])
    for o in objects:
        mine = {t["name"] for t in tables if o["id"] in t.get("represents", [])}
        o["screens"] = [s_["route"] for s_ in screens if mine & set(s_["tables"])]
        o["endpoints"] = [e["id"] for e in endpoints if mine & set(e["tables_read"] + e["tables_written"])]
    return {"screens": screens, "endpoints": endpoints,
            "note": "Endpoint tables are the tables named in the router folder's SQL and Python (table_evidence_scope), "
                    "not traced into each handler body, so an endpoint may list tables a sibling handler uses."}


def build_code_joins(joins):
    return [{"left": "%s.%s" % (e["left_table"], e["left_column"]), "right": "%s.%s" % (e["right_table"], e["right_column"]),
             "occurrences": e.get("occurrences"), "evidence": e.get("evidence"), "source": fname("app_joins")}
            for e in joins.get("edges", [])]


def build_impact(imp):
    chains = []
    for c in imp.get("dependency_chains", []):
        def parts(items):
            out = []
            for w in items or []:
                label = w.get("component") or w.get("endpoint") or w.get("script") or ", ".join(as_list(w.get("systems")))
                out.append({"layer": w.get("layer"), "item": label, "action": w.get("action")})
            return out
        chains.append({"id": c["chain_id"], "attribute": "%s.%s" % (c["db_table"], c.get("db_column")),
                       "business_name": c.get("business_name"), "risk": c.get("change_impact"),
                       "written_by": parts(c.get("writers")), "read_by": parts(c.get("readers")),
                       "if_changed": c.get("if_changed"), "source": "%s %s" % (fname("impact"), c["chain_id"])})
    summary = [dict(t, source=fname("impact")) for t in imp.get("table_impact_summary", [])]
    return chains, summary


def build_questions(lin, etl, patterns, tables, objects, t01):
    qs = []
    for q in lin.get("open_questions", []):
        qs.append({"id": q["id"], "question": " ".join(q["question"].split()), "owner": q.get("assigned_to"),
                   "impact": q.get("impact"), "source": fname("lineage")})
    for i, q in enumerate(patterns.get("open_questions", []), 1):
        qs.append({"id": "ETL-PAT-%d" % i, "question": q["question"], "owner": q.get("owner"), "source": fname("etl_patterns")})
    missing = etl.get("tables_not_in_db_registry") or []
    temp = set(etl.get("temp_objects") or [])
    real_missing = [t for t in missing if t not in temp and not t.startswith("TEMP_")]
    if real_missing:
        qs.append({"id": "GAP-REGISTRY", "question": "ETL touches %d non-temp tables that DB_TABLE_REGISTRY does not list "
                   "(e.g. %s). Which database/schema holds each, and should they be registered?"
                   % (len(real_missing), ", ".join(real_missing[:6])), "owner": "DB/ETL lead", "source": fname("etl_io")})
    if t01:
        qs.append({"id": "GAP-PROD-COLUMNS", "question": "Column types, PHI masking and column lineage not covered by the prod-derived "
                   "KB were filled from %s (SIT), the only SDLC environment the nonprod MCP can read besides D01. Prod (P01) "
                   "may differ; column lineage covers only writes seen in the last 30 days." % t01["metadata"]["database"],
                   "owner": "DB lead", "source": "SIT/" + fname("t01")})
    no_obj = [o["label"] for o in objects if not o.get("table")]
    if no_obj:
        qs.append({"id": "GAP-OBJECT-TABLE", "question": "Objects without a canonical table: %s" % ", ".join(no_obj),
                   "owner": "DB lead", "source": fname("entities")})
    return qs


def add_tested_by(objects, qa):
    """Copy each object's scenario count from the QA-suite coverage file (kbgen/gen_qa_suite.py)."""
    rows = {r["id"]: r for r in qa.get("objects") or []}
    for o in objects:
        r = rows.get(o["id"])
        if r is not None:
            o["tested_by"] = {"scenarios": r["scenarios"], "by_table": r["by_table"], "source": SRC["qa"]}


def qa_tab(qa):
    if not qa:
        return "<p>No QA-suite coverage file yet: run <code>%s</code>.</p>" % "sdlc/framework/tools/kbgen/gen_qa_suite.py"
    m, u = qa["metadata"], qa["untested"]
    src = m["source"]
    head = ("<p>Read only from <code>%s</code>, branch <code>%s</code>, commit <code>%s</code>. %s</p>"
            % (esc(src["repo"]), esc(src["branch"]), esc((src["commit"] or "?")[:8]), esc(m["rule"])))
    c = m["counts"]
    head += "<p>%d scenarios in %d feature files, %d step definitions, %d query keys, %d steps that match no step definition.</p>" % (
        c["scenarios"], c["feature_files"], c["step_definitions"], c["query_keys"], c["unmatched_steps"])
    scr = table(["Screen", "Scenarios"], [["<code>%s</code>" % esc(s["route"]), "%d" % s["scenarios"]] for s in qa["screens"]])
    tbl = table(["Table", "Scenarios", "Query keys"], [["<code>%s</code>" % esc(t["table"]), "%d" % t["scenarios"],
                                                      chip_list(t["query_keys"])] for t in qa["tables"]])
    gap = ("<h3>Not tested by any scenario</h3><p><b>Objects:</b> %s</p><p><b>Screens:</b> %s</p><p><b>Tables the API reads or writes "
           "(%d):</b> %s</p>" % (chip_list(u["objects"]), chip_list(u["screens"]), len(u["app_tables"]), chip_list(u["app_tables"])))
    return (head + "<h3>Screens</h3>" + scr + "<h3>Tables the scenarios check</h3>" + tbl + gap +
            "<p><small>Step library, query keys, TestData and unmatched steps: <code>%s</code> (.md beside it).</small></p>" % esc(SRC["qa"]))


def build():
    ent, sem, lin, con = load("entities"), load("semantic"), load("lineage"), load("contracts")
    reg, cff, gcols, joins = load("registry"), load("cff"), load("glossary_cols"), load("app_joins")
    etl, pat, imp = load("etl_io"), load("etl_patterns"), load("impact")
    objects = build_objects(ent, sem)
    jobs = build_jobs(etl, pat)
    temp = set(etl.get("temp_objects") or []) | {t["name"] for t in etl.get("tables", []) if t.get("kind") == "temp"}
    edges, systems = build_lineage(jobs, lin, temp)
    t01 = load("t01") if os.path.exists(os.path.join(REPO, SRC["t01"])) else {}
    tables = build_tables(reg, cff, gcols, etl, joins, con, objects, lin, t01)
    chains, summary = build_impact(imp)
    application = build_application(load("app_matrix"), objects, tables)
    qa = load("qa") if os.path.exists(os.path.join(REPO, SRC["qa"])) else {}
    add_tested_by(objects, qa)
    fin_cat = load("fin_catalog") if os.path.exists(os.path.join(REPO, SRC["fin_catalog"])) else {}
    fin_t01 = load("fin_t01") if os.path.exists(os.path.join(REPO, SRC["fin_t01"])) else {}
    return {
        "metadata": {
            "name": "Acme Claims ontology",
            "generated": datetime.date.today().isoformat(),
            "generator": "sdlc/framework/tools/kbgen/gen_ontology.py",
            "source_database": "%s.%s" % (reg.get("database"), reg.get("schema")),
            "sources": sorted(SRC.values()),
            "out_of_scope_for_now": ["Glue and Lambda jobs (claims-etl-glue, claims-etl-lambda)",
                                     "Reconciliation, provider payment and anomaly history (VBC Atlas AI) — added when the Atlas team shares it"],
            "rule": "Every item is copied from the KB file named in its source. Business objects link to tables only "
                    "where the entity registry or semantic layer names the table. Nothing is inferred from column names.",
            "how_to_read": {
                "business_layer": "objects, relationships, states, phrases, rules, processes, metrics (finance numbers and the words people use for them) — what the business talks about",
                "data_layer": "datasets, tables (columns, PHI, represents: object ids), jobs, job_io (job reads table A and writes table B — "
                              "not proof that A feeds B), column_lineage (column-to-column writes Snowflake observed in T01), "
                              "code_joins, systems, finance_tables (CLAIMS_FIN_DATA in T01, column names only) — where the data lives and moves",
                "application_layer": "screens (route, page, endpoints it calls, tables behind them) and endpoints (handler file:line, "
                                     "tables read/written); tables carry api_reads/api_writes and objects carry screens/endpoints",
                "tested_by": "on each object: how many claims-qa Behave scenarios check its tables (QA-AUTOMATION-DERIVED/03_QA_SUITE_COVERAGE.yaml)",
                "impact": "chains: change this attribute -> who writes it, who reads it, what to update",
                "open_questions": "anything the sources cannot settle; do not resolve by guessing",
            },
        },
        "business_layer": {
            "objects": objects,
            "relationships": build_relationships(sem, objects),
            "states": build_states(sem),
            "phrases": build_phrases(ent),
            "rules": build_rules(sem),
            "processes": build_processes(lin),
            "metrics": build_metrics(fin_cat),
        },
        "data_layer": {
            "datasets": build_datasets(reg, lin),
            "tables": tables,
            "jobs": jobs,
            "job_io": edges,
            "column_lineage": build_column_lineage(t01),
            "systems": systems,
            "code_joins": build_code_joins(joins),
            "finance_tables": build_finance_tables(fin_t01),
        },
        "application_layer": application,
        "impact": {"chains": chains, "table_summary": summary},
        "open_questions": build_questions(lin, etl, pat, tables, objects, t01),
    }


# ---------------------------------------------------------------- HTML

def chip_list(items):
    return " ".join('<span class="a-chip">%s</span>' % esc(i) for i in items if i) or "—"


def table(head, rows, cls=""):
    return ('<div class="a-table-scroll"><table class="a-table %s"><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>'
            % (cls, "".join("<th>%s</th>" % esc(h) for h in head),
               "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % c for c in r) for r in rows)))


def render_graph(onto):
    """Static SVG: inbound systems -> business objects -> downstream systems, plus object-to-object links.

    Each line has its own end point on the box edge (ordered by where the other end sits, so lines do not
    cross at the box), an arrow showing which way data moves and a hover title naming the tables it carries.
    Hovering or clicking a box keeps only that box's lines bright (JS below)."""
    objs = onto["business_layer"]["objects"]
    tables_of = {}
    for o in objs:
        for t in [o.get("table")] + o.get("related_tables", []):
            if t:
                tables_of.setdefault(t, set()).add(o["id"])
    systems = onto["data_layer"]["systems"]
    ins = [s for s in systems if s["direction"] == "in"]
    outs = [s for s in systems if s["direction"] == "out"]
    W, rowh, top = 1180, 72, 40
    n = max(len(objs), len(ins), len(outs))
    H = top + n * rowh + 20
    xin, xobj, xout, bw, bh = 20, 470, 900, 260, 48

    def ys(count):
        start = top + (n - count) * rowh / 2
        return [start + i * rowh for i in range(count)]

    pos = {}
    for o, y in zip(objs, ys(len(objs))):
        pos[o["id"]] = (xobj, y)

    def links(s):
        by = {}
        for t in s.get("tables") or []:
            for oid in tables_of.get(t, ()):
                by.setdefault(oid, []).append(t)
        return by

    def mean_y(s):
        ids = list(links(s))
        return sum(pos[i][1] for i in ids) / len(ids) if ids else 1e9

    ins.sort(key=mean_y)
    outs.sort(key=mean_y)
    for s, y in zip(ins, ys(len(ins))):
        pos[s["id"]] = (xin, y)
    for s, y in zip(outs, ys(len(outs))):
        pos[s["id"]] = (xout, y)

    edges = []
    for s in ins:
        for oid, tabs in sorted(links(s).items()):
            edges.append((s["id"], oid, "e-in", "%s → %s: %s" % (s["name"].split("—")[0].strip(), oid, ", ".join(sorted(tabs)))))
    for s in outs:
        for oid, tabs in sorted(links(s).items()):
            edges.append((oid, s["id"], "e-out", "%s → %s: %s" % (oid, s["name"], ", ".join(sorted(tabs)))))
    label = {o["id"]: o["label"] for o in objs}
    edges = [(a, b, c, t.replace(a + " →", label.get(a, a) + " →").replace("→ " + b + ":", "→ " + label.get(b, b) + ":"))
             for a, b, c, t in edges]

    ports = {}
    for i, (a, b, _, _) in enumerate(edges):
        ports.setdefault((a, "r"), []).append((pos[b][1], i))
        ports.setdefault((b, "l"), []).append((pos[a][1], i))
    at = {}
    for (node, side), lst in ports.items():
        lst.sort()
        step = (bh - 12) / max(len(lst), 1)
        for k, (_, i) in enumerate(lst):
            at[(i, side)] = pos[node][1] + 6 + step * (k + .5)

    parts = ['<defs>%s</defs>' % "".join(
        '<marker id="ar-%s" viewBox="0 0 8 8" refX="7" refY="4" markerUnits="userSpaceOnUse" markerWidth="11" markerHeight="11" orient="auto-start-reverse">'
        '<path d="M0 0 L8 4 L0 8 z" class="%s"/></marker>' % (c, c) for c in ("e-in", "e-out", "e-rel"))]
    for i, (a, b, cls, title) in enumerate(edges):
        x1, y1, x2, y2 = pos[a][0] + bw, at[(i, "r")], pos[b][0], at[(i, "l")]
        mx = (x1 + x2) / 2
        parts.append('<path class="%s" data-a="%s" data-b="%s" marker-end="url(#ar-%s)" d="M%.0f %.1f C%.0f %.1f %.0f %.1f %.0f %.1f">'
                     '<title>%s</title></path>' % (cls, a, b, cls, x1, y1, mx, y1, mx, y2, x2 - 2, y2, esc(title)))
    seen = set()
    rels = []
    for r in onto["business_layer"]["relationships"]:
        a, b = r.get("from_object"), r.get("to_object")
        if a and b and a != b and frozenset((a, b)) not in seen:
            seen.add(frozenset((a, b)))
            rels.append((a, b, [x["name"] for x in onto["business_layer"]["relationships"]
                                if {x.get("from_object"), x.get("to_object")} == {a, b}]))
    for k, (a, b, names) in enumerate(rels):
        (x1, y1), (x2, y2) = pos[a], pos[b]
        bend = xobj + bw + 30 + 26 * k + abs(y2 - y1) / 8
        parts.append('<path class="e-rel" data-a="%s" data-b="%s" d="M%.0f %.0f C%.0f %.0f %.0f %.0f %.0f %.0f"><title>%s</title></path>'
                     % (a, b, x1 + bw, y1 + bh - 6, bend, y1 + bh - 6, bend, y2 + bh - 6, x2 + bw, y2 + bh - 6,
                        esc("%s ↔ %s: %s" % (label[a], label[b], "; ".join(names)))))

    def box(key, title, sub, cls):
        x, y = pos[key]
        full = title + (" — " + sub if sub else "")
        parts.append('<g class="%s" data-node="%s" tabindex="0"><title>%s</title><rect x="%.0f" y="%.0f" width="%d" height="%d" rx="6"/>'
                     '<text x="%.0f" y="%.0f" class="t1">%s</text><text x="%.0f" y="%.0f" class="t2">%s</text></g>'
                     % (cls, key, esc(full), x, y, bw, bh, x + 10, y + 20, esc(title if len(title) <= 34 else title[:33] + "…"),
                        x + 10, y + 37, esc(sub if len(sub) <= 40 else sub[:39] + "…")))

    linked = {e[0] for e in edges} | {e[1] for e in edges}
    for s in ins:
        box(s["id"], s["name"].split("—")[0].strip(), s.get("system") or "", "n-sys" + ("" if s["id"] in linked else " none"))
    for o in objs:
        box(o["id"], o["label"], "%s · %s" % (o.get("table") or "", o.get("key") or ""), "n-obj" + ("" if o["id"] in linked else " none"))
    for s in outs:
        box(s["id"], s["name"], "", "n-sys" + ("" if s["id"] in linked else " none"))
    head = ('<text x="%d" y="22" class="col">Sources (inbound flows)</text><text x="%d" y="22" class="col">Business objects</text>'
            '<text x="%d" y="22" class="col">Downstream consumers</text>' % (xin, xobj, xout))
    return ('<div class="graph" id="ov-out" data-hl><svg viewBox="0 0 %d %.0f" role="img" aria-label="Acme Claims ontology graph">%s%s</svg></div>'
            % (W, H, head, "".join(parts)))


LOOKS = (("plain", "Plain"), ("dashes", "Moving dashes"), ("dots", "Travelling dots"),
         ("follow", "Follow the data (click a box)"), ("sized", "Sized by volume"), ("gradient", "Gradient lines"),
         ("combo", "Dashes + sized + follow"))


def look_bar(target, extra=""):
    """The Look picker above a graph; the choice is shared by both graphs and remembered in the browser."""
    opts = "".join('<option value="%s">%s</option>' % kv for kv in LOOKS)
    return ('<div class="looks"><label>Look <select class="a-select lk-pick" data-for="%s" aria-label="Graph look">%s</select></label>'
            '%s<span class="lk-hint" data-for="%s"></span></div>' % (target, opts, extra, target))


def render_lineage_graph(onto):
    """Per-object table graph: what feeds the object's tables and what they feed, one hop each way."""
    objs = {o["id"]: o["label"] for o in onto["business_layer"]["objects"]}
    members = {}
    for t in onto["data_layer"]["tables"]:
        for oid in t.get("represents", []):
            members.setdefault(oid, []).append(t["name"])
    edges = {}
    for e in onto["data_layer"]["job_io"]:
        edges.setdefault((e["from"], e["to"]), set()).add(e["via"].split("/")[-1])
    for e in onto["data_layer"]["column_lineage"]:
        a = e["source"].rsplit(".", 1)[0].split(".")[-1]
        b = e["target"].rsplit(".", 1)[0].split(".")[-1]
        edges.setdefault((a, b), set()).add("column lineage (T01)")
    data = {"objects": [[k, objs[k], sorted(members.get(k, []))] for k in objs],
            "edges": [[a, b, sorted(v)] for (a, b), v in sorted(edges.items()) if a != b]}
    opts = "".join('<option value="%s">%s</option>' % (esc(k), esc(v)) for k, v in objs.items())
    return ('<p>Pick a business object. The middle column is the tables it lives in; the left column is what writes into them '
            '(ETL job reads/writes and T01 column lineage), the right column is what they are written into. Blue: from an ETL job; '
            'green: column lineage Snowflake observed in T01; dashed: one table of the object feeds another. Hover or click a table to see only its lines, with the jobs listed underneath. '
            'Tables with the same name start are grouped into one box (for example <code>TEMP_STAGE_* (5)</code>); click the box to open it. '
            'Find jumps to a table, in this object or another; the zoom buttons make the graph bigger or smaller. Look changes how the lines are drawn.</p>'
            '<div class="looks"><label>Object <select class="a-select" id="lg-pick">%s</select></label>'
            '<label><input type="checkbox" id="lg-group" checked> Group similar tables</label>'
            '<label>Find <input type="search" class="a-input" id="lg-find" list="lg-names" placeholder="table name"></label><datalist id="lg-names"></datalist>'
            '<span class="lk-zoom" role="group" aria-label="Zoom"><button type="button" class="a-btn" data-z="-1" aria-label="Zoom out">−</button>'
            '<button type="button" class="a-btn" data-z="0">Fit</button><button type="button" class="a-btn" data-z="1" aria-label="Zoom in">+</button></span></div>'
            '%s'
            '<div class="lg graph" id="lg-out" data-hl></div><div class="lg-why" id="lg-why"></div><script type="application/json" id="lg-data">%s</script>'
            % (opts, look_bar("lg-out"), json.dumps(data).replace("</", "<\\/")))


def render_html(onto):
    bl, dl, im, al = onto["business_layer"], onto["data_layer"], onto["impact"], onto["application_layer"]
    tabs = []
    counts = [("Business objects", len(bl["objects"])), ("Relationships", len(bl["relationships"])),
              ("Screens", len(al["screens"])), ("API endpoints", len(al["endpoints"])), ("Tables", len(dl["tables"])), ("Columns", sum(len(t.get("columns", [])) for t in dl["tables"])),
              ("ETL jobs", len(dl["jobs"])), ("Job read/write edges", len(dl["job_io"])),
              ("Column lineage edges (T01)", len(dl["column_lineage"])),
              ("Code-evidenced joins", len(dl["code_joins"])), ("Impact chains", len(im["chains"])),
              ("Open questions", len(onto["open_questions"]))]
    overview = ('<div class="stats">%s</div>' % "".join('<div class="a-panel stat"><b>%d</b><span>%s</span></div>' % (n, esc(k))
                                                         for k, n in counts)
                + '<div class="a-callout"><p><b>Three layers.</b> The business layer names what Acme Claims works with (Provider Group, '
                  'Contract, Run Request …), their states and rules. The application layer lists the screens, the endpoints '
                  'they call and the tables behind each. The data layer says where each lives (tables, columns, PHI), '
                  'which jobs move it and which systems read it. A table links up to an object through <code>represents</code>. '
                  'Impact paths walk both: object → table → job that writes it → systems that read it. The Data lineage graph tab draws the tables of one object with what writes into them and what they write into.</p></div>'
                + look_bar("ov-out", '<button type="button" class="a-btn" id="ov-play">Play the main flows</button>')
                + render_graph(onto)
                + '<div class="lk-story" id="ov-story" aria-live="polite"></div>'
                + '<p class="legend"><span class="k k-in"></span>feeds the object\'s tables <span class="k k-out"></span>read by downstream <span class="k k-rel"></span>object-to-object relationship. Hover or click a box to see only its lines; hover a line for the tables it carries. A grey box has no table linked to it yet. Look changes how the lines are drawn (moving, sized by how many tables they carry, or traced hop by hop from the box you click); Play the main flows walks through each source in turn.</p>')
    tabs.append(("Overview", overview, None))

    rows = []
    for o in bl["objects"]:
        st = o.get("status")
        rows.append(["<b>%s</b>" % esc(o["label"]),
                     "<code>%s</code><br><small>key %s</small>" % (esc(o.get("table")), esc(o.get("key"))),
                     chip_list(o["aliases"]),
                     esc("%s.%s" % (st["table"], st["column"])) if st else "—",
                     chip_list(o.get("related_tables", [])),
                     chip_list(o.get("screens", [])), "%d" % len(o.get("endpoints", [])),
                     ("%d scenarios" % o["tested_by"]["scenarios"]) if o.get("tested_by") else "—",
                     "<small>%s</small>" % esc(o["source"])])
    tabs.append(("Business objects", table(["Object", "Table", "Aliases", "Status lives in", "Related tables", "Screens",
                                            "Endpoints", "Tested by", "Source"], rows),
                 len(bl["objects"])))

    rows = [[esc(r["name"]), esc(r.get("from_object") or r.get("from_table")), esc(r.get("to_object") or r.get("to_table")),
             "<code>%s</code>" % esc(r.get("join") or ("via " + r.get("via", ""))), esc(r.get("cardinality") or ""),
             "<small>%s</small>" % esc(r["source"])] for r in bl["relationships"]]
    rel = table(["Relationship", "From", "To", "Join", "Cardinality", "Source"], rows)
    rows = [["<code>%s</code>" % esc(j["left"]), "<code>%s</code>" % esc(j["right"]), esc(j.get("occurrences")),
             "<small>%s</small>" % esc(", ".join(j.get("evidence") or []))] for j in dl["code_joins"]]
    rel += '<h3>Joins found in application SQL (with file:line)</h3>' + table(["Left", "Right", "Uses", "Evidence"], rows)
    tabs.append(("Relationships", rel, len(bl["relationships"]) + len(dl["code_joins"])))

    st = ""
    for name, d in bl["states"].items():
        vals = d.get("values") or {}
        st += ('<details class="a-panel"><summary><b>%s</b> — %s</summary>%s%s</details>'
               % (esc(name), esc(d.get("description")), ('<p>Flow: %s</p>' % esc(d["flow"])) if d.get("flow") else "",
                  table(["Value", "Meaning"], [["<code>%s</code>" % esc(k), esc(v)] for k, v in vals.items()])
                  if isinstance(vals, dict) else esc(vals)))
    st += "<h3>Rules</h3>" + table(["Kind", "Rule", "Source"], [[esc(r["kind"].replace("_", " ")), esc(r["rule"]),
                                                              "<small>%s</small>" % esc(r["source"])] for r in bl["rules"]])
    st += "<h3>Phrases → data</h3>" + table(["Phrase", "Resolves to", "SQL"], [
        [chip_list(p["phrases"]), "<code>%s</code>" % esc(p["resolves_to"]), "<code>%s</code>" % esc(p.get("sql"))]
        for p in bl["phrases"]])
    tabs.append(("States & rules", st, len(bl["states"]) + len(bl["rules"])))

    pr = ""
    for p in bl["processes"]:
        body = '<p>%s</p>' % esc(p["description"])
        if p.get("stages"):
            body += table(["Stage", "Tables", "Trigger", "Status"], [[esc(s["stage"]), chip_list(s.get("tables") or []),
                                                                     esc(s.get("trigger")), esc(s.get("status_written"))]
                                                                    for s in p["stages"]])
        if p.get("execution_order"):
            body += table(["Step", "Jobs", "Depends on"], [[esc(s["step"]), chip_list(s.get("jobs") or []), esc(s.get("depends_on"))]
                                                         for s in p["execution_order"]])
        if p.get("routing_rules"):
            body += table(["Request types", "Detail table"], [[chip_list(r.get("rqst_type_codes") or []), esc(r.get("detail_table"))]
                                                              for r in p["routing_rules"]])
        pr += '<details class="a-panel"><summary><b>%s</b></summary>%s<p><small>%s</small></p></details>' % (
            esc(p["name"]), body, esc(p["source"]))
    tabs.append(("Processes", pr, len(bl["processes"])))

    rows = []
    for t in dl["tables"]:
        cols = t.get("columns", [])
        coltab = table(["Column", "Type", "Mandatory", "PHI", "Description"], [
            ["<code>%s</code>" % esc(c["name"]), esc(c.get("type")), esc(c.get("mandatory", "")),
             "PHI" if c.get("phi") else "", esc(c.get("description", ""))] for c in cols]) if cols else ""
        rows.append(['<code>%s</code>' % esc(t["name"]), esc(t.get("layer") or ""), esc(t.get("module") or ""),
                     esc(t.get("status") or ""), chip_list(t.get("represents", [])),
                     ('<details><summary>%d columns%s</summary>%s</details>'
                      % (len(cols), " · %d PHI" % sum(1 for c in cols if c.get("phi")) if any(c.get("phi") for c in cols) else "",
                         coltab)) if cols else "—",
                     "<small>%s</small>" % esc(", ".join(t.get("etl_written_by", [])) or ""),
                     "<small>%s</small>" % esc(", ".join(t["sources"]))])
    dt = ('<input class="a-field filter" type="search" placeholder="Filter tables…" aria-label="Filter tables" data-filter="tables">'
          + table(["Table", "Layer", "Module", "Prod status", "Represents", "Columns", "Written by (ETL)", "Sources"], rows, "tables"))
    ds = table(["Dataset", "Detail", "Source"], [[esc(d["id"]), "<code>%s</code>" % esc({k: v for k, v in d.items() if k not in ("id", "source")}),
                                                 "<small>%s</small>" % esc(d["source"])] for d in dl["datasets"]])
    tabs.append(("Data: tables & columns", "<h3>Datasets</h3>" + ds + "<h3>Tables</h3>" + dt, len(dl["tables"])))

    rows = [["<code>%s</code>" % esc(j["id"]), esc(j.get("description") or ""), chip_list(j["reads"]), chip_list(j["writes"])]
            for j in dl["jobs"]]
    jb = table(["Job", "Description", "Reads", "Writes"], rows)
    rows = [[esc("into Acme Claims" if s["direction"] == "in" else "out of Acme Claims"), esc(s["name"]), esc(s.get("system") or ""),
             chip_list(s.get("tables") or []), esc(s.get("trigger") or "")] for s in dl["systems"]]
    jb = "<h3>System flows</h3>" + table(["Direction", "Name", "System", "Tables", "Trigger"], rows) + "<h3>ETL jobs</h3>" + jb
    rows = [["<code>%s</code>" % esc(e["from"]), "<code>%s</code>" % esc(e["via"]), "<code>%s</code>" % esc(e["to"])]
            for e in dl["job_io"]]
    jb += ('<h3>Job reads → writes (the job reads the first table and writes the second)</h3><input class="a-field filter" type="search" placeholder="Filter lineage…" '
           'aria-label="Filter lineage" data-filter="lineage">' + table(["From", "Job", "To"], rows, "lineage"))
    jb += ('<p>The %d column-to-column edges Snowflake saw written in T01 are in <code>ACME_ONTOLOGY.yaml</code> under '
           '<code>data_layer.column_lineage</code>; the Data lineage graph tab draws them at table level.</p>' % len(dl["column_lineage"]))
    tabs.append(("Data: jobs & lineage", jb, len(dl["jobs"])))
    tabs.insert(1, ("Data lineage graph", render_lineage_graph(onto), None))

    ip = ""
    for c in im["chains"]:
        def lines(items):
            return "<br>".join("<b>%s</b> %s — %s" % (esc(i["layer"]), esc(i["item"]), esc(i.get("action") or "")) for i in items)
        ip += ('<details class="a-panel" open><summary><b>%s</b> <code>%s</code> · risk <b>%s</b></summary>%s</details>'
               % (esc(c.get("business_name") or c["attribute"]), esc(c["attribute"]), esc(c.get("risk")),
                  table(["Written by", "Read by", "If changed"], [[lines(c["written_by"]), lines(c["read_by"]),
                                                                  "<br>".join("<b>%s</b> %s (%s)" % (esc(x.get("layer")), esc(x.get("action")), esc(x.get("effort")))
                                                                              for x in c.get("if_changed") or [])]], "even")))
    tabs.append(("Impact paths", ip, len(im["chains"])))

    rows = [["<code>%s</code>" % esc(s_["route"]), "<small>%s</small>" % esc(s_["page"]), chip_list(s_["services"]),
             "%d" % len(s_["endpoints"]), chip_list(s_["tables"])] for s_ in al["screens"]]
    ap = "<h3>Screens</h3>" + table(["Route", "Page", "Services", "Endpoints", "Tables behind it"], rows)
    rows = [["<code>%s</code>" % esc(e["id"]), "<small>%s<br>%s</small>" % (esc(e["handler"]), esc(e["code"])),
             chip_list(e["tables_read"]), chip_list(e["tables_written"]), chip_list(e["screens"])] for e in al["endpoints"]]
    ap += ('<h3>API endpoints</h3><p>%s</p><input class="a-field filter" type="search" placeholder="Filter endpoints…" '
           'aria-label="Filter endpoints" data-filter="eps">' % esc(al["note"])
           + table(["Endpoint", "Handler", "Reads", "Writes", "Screens"], rows, "eps"))
    tabs.append(("Application: screens & APIs", ap, len(al["screens"]) + len(al["endpoints"])))

    rows = [[esc(q["question"]), esc(q.get("owner") or ""), "<small>%s</small>" % esc(q["source"])]
            for q in onto["open_questions"]]
    src = "".join("<li><code>%s</code></li>" % esc(s) for s in onto["metadata"]["sources"])
    qa = load("qa") if os.path.exists(os.path.join(REPO, SRC["qa"])) else {}
    tabs.append(("QA coverage", qa_tab(qa), (qa.get("metadata") or {}).get("counts", {}).get("scenarios")))
    tabs.append(("Open questions & sources", table(["Question", "Owner", "Source"], rows)
                 + '<h3>Built from</h3><ul>%s</ul><p>%s</p>' % (src, esc(onto["metadata"]["rule"])), len(onto["open_questions"])))

    def btn(i, t, n):
        return ('<button class="a-btn" id="tabbtn-%d" role="tab" type="button" aria-controls="tab-%d" aria-selected="%s">%s</button>'
                % (i, i, "true" if i == 0 else "false", esc(t)))

    def panel(i, t, b):
        intro = '<p class="intro">%s</p>' % esc(INTRO[t]) if INTRO.get(t) else ""
        return ('<section class="a-section" id="tab-%d" role="tabpanel" aria-labelledby="tabbtn-%d"%s>'
                '<h2 class="a-section__title">%s</h2>%s%s</section>' % (i, i, "" if i == 0 else " hidden", esc(t), intro, b))

    body = ('<div class="a-tabs a-tabs--wrap" data-a-tabs role="tablist" aria-label="Ontology sections">%s</div>%s'
            % ("".join(btn(i, t, n) for i, (t, _, n) in enumerate(tabs)),
               "".join(panel(i, t, b) for i, (t, b, _) in enumerate(tabs))))
    return artifact_kit.render_page(
        "Acme Claims ontology", body,
        subtitle=esc("Business, application and data layers of %s · built from the Acme Claims knowledge base · as of %s"
                     % (onto["metadata"]["source_database"], onto["metadata"]["generated"])),
        footnote=esc("Generated by %s. Every item names the KB file it came from." % onto["metadata"]["generator"]),
        extra_css=CSS + ".a-table-scroll{content-visibility:auto;contain-intrinsic-size:auto 480px}", before_kit_js=PICK_TAB_JS, extra_js=JS, body_class="ontology")


INTRO = {
    "Overview": "A map of Acme Claims on one page. On the left, where data comes into Acme Claims; in the middle, the seven things the "
                "business works with; on the right, the systems that use Acme Claims data. A line means data moves that way.",
    "Business objects": "The seven things Acme Claims is about, what people also call them, the table each lives in, where its "
                        "status is kept, and which screens and API endpoints touch it.",
    "Relationships": "How the business objects connect, with the exact join the database uses. The second table lists "
                     "the joins found in the application's own SQL, with the file and line.",
    "States & rules": "What each status code means and the order statuses move in, then the rules every query must follow "
                      "(tenant filter, current row only, no direct PHI access) and the everyday phrases that map to data.",
    "Processes": "The flows that run inside Acme Claims: approving a provider group, routing a run request to its detail table, "
                 "the order run-request jobs run in, and how history is kept.",
    "Data: tables & columns": "Where the data physically lives. Each table shows which business object it belongs to, "
                              "which ETL scripts write it, and its columns with type and PHI flag. Values marked T01 "
                              "came from SIT because the production documents did not cover them.",
    "Data: jobs & lineage": "The systems that send data in and take it out, then every ETL script with the tables it reads "
                            "and writes. Read and write together does not prove one table feeds the other.",
    "Impact paths": "If one of these fields changes, who writes it, who reads it, and what has to be updated. Start here "
                    "to judge the risk of a change.",
    "Application: screens & APIs": "Each screen with the API endpoints it calls and the tables behind them, then every "
                                   "endpoint with its handler in the code and the tables it reads and writes.",
    "Open questions & sources": "What the sources cannot answer yet and who owns each question, followed by the files this "
                                "ontology was built from.",
}

PICK_TAB_JS = """(function () {
  var wanted = location.hash.replace("#", "");
  if (wanted.indexOf("tab-") !== 0 || !document.getElementById(wanted)) return;
  document.querySelectorAll('[data-a-tabs] [role="tab"]').forEach(function (tab) {
    tab.setAttribute("aria-selected", tab.getAttribute("aria-controls") === wanted ? "true" : "false");
  });
}());"""

CSS = """
.ontology .stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:14px}
.ontology .stat{display:flex;flex-direction:column;padding:12px}
.ontology .stat b{font-size:1.6rem;color:rgb(var(--text-accent))}
.ontology .graph{overflow-x:auto;margin-top:12px}
.ontology .graph svg{width:100%;min-width:900px;height:auto}
.ontology .graph rect{stroke-width:1.2}
.ontology .n-obj rect{fill:rgb(var(--text-accent)/.10);stroke:rgb(var(--text-accent))}
.ontology .n-sys rect{fill:rgb(var(--text-blue)/.08);stroke:rgb(var(--text-blue))}
.ontology .graph .t1{font-size:13px;font-weight:600;fill:rgb(var(--text-primary))}
.ontology .graph .t2{font-size:11px;fill:rgb(var(--text-secondary))}
.ontology .graph .col{font-size:13px;font-weight:700;fill:rgb(var(--text-secondary))}
.ontology .graph path{fill:none;stroke-width:1.6;opacity:.85;transition:opacity .15s,stroke-width .15s}
.ontology .graph marker path{opacity:1;stroke:none}
.ontology marker .e-in{fill:rgb(var(--text-blue))}.ontology marker .e-out{fill:rgb(var(--text-green))}.ontology marker .e-rel{fill:rgb(var(--text-accent))}
.ontology #lg-ar path{fill:rgb(var(--text-blue))}
.ontology .graph g[data-node]{cursor:pointer;outline:none}
.ontology .graph .none rect{stroke-dasharray:4 3;opacity:.6}
.ontology .graph svg.focus path[data-a]{opacity:.08}
.ontology .graph svg.focus path[data-a].on{opacity:1;stroke-width:2.6}
.ontology .graph svg.focus g[data-node]{opacity:.35}
.ontology .graph svg.focus g[data-node].on{opacity:1}
.ontology .lg path.in{stroke:rgb(var(--text-accent));stroke-dasharray:4 3}
.ontology .lg-why{font-size:.85rem;color:rgb(var(--text-secondary));min-height:1.2em}
.ontology .lg-why ul{margin:4px 0 0 18px;padding:0}
.ontology .e-in{stroke:rgb(var(--text-blue))}
.ontology .e-out{stroke:rgb(var(--text-green))}
.ontology .e-rel{stroke:rgb(var(--text-accent));stroke-dasharray:4 3}
.ontology .legend{font-size:.85rem}
.ontology .legend .k{display:inline-block;width:22px;height:0;border-top:2px solid;margin:0 6px 3px 14px;vertical-align:middle}
.ontology .legend .k-in{border-color:rgb(var(--text-blue))}.ontology .legend .k-out{border-color:rgb(var(--text-green))}
.ontology .legend .k-rel{border-color:rgb(var(--text-accent));border-top-style:dashed}
.ontology .lg svg{width:100%;min-width:900px;height:auto}
.ontology .lg .n rect{fill:rgb(var(--bg-elevated));stroke:rgb(var(--border-primary))}
.ontology .lg .n.me rect{fill:rgb(var(--text-accent)/.10);stroke:rgb(var(--text-accent))}
.ontology .lg text{font-size:12px;fill:rgb(var(--text-primary))}
.ontology .lg path{fill:none;stroke:rgb(var(--text-blue));stroke-width:1.3;opacity:.75}
.ontology .lg path.cl{stroke:rgb(var(--text-green))}
.ontology details.a-panel{margin:8px 0;padding:8px 12px}
.ontology details summary{cursor:pointer}
.ontology .filter{width:100%;max-width:420px;margin:6px 0 10px}
.ontology .a-table td{vertical-align:top}
.ontology .a-chip{margin:1px 2px}
.ontology .a-shell{padding-top:12px}
.ontology .a-section{margin-top:14px}
.ontology .a-section__title{margin-bottom:2px}
.ontology .intro{margin:0 0 10px;color:rgb(var(--text-secondary));max-width:110ch}
.ontology table.even{table-layout:fixed;width:100%}
.ontology table.even td,.ontology table.even th{width:33.33%}
.ontology details.a-panel{margin:6px 0}
.ontology .looks{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center;margin:10px 0 0;font-size:.9rem}
.ontology .lk-hint{color:rgb(var(--text-secondary))}
.ontology .lk-zoom .a-btn{min-width:2.2em;padding:2px 8px}
.ontology .lk-story{min-height:1.4em;margin-top:6px;font-weight:600;color:rgb(var(--text-accent))}
.ontology .lg .grp rect{stroke-dasharray:5 3;stroke-width:1.6}
@keyframes lk-dash{to{stroke-dashoffset:-14}}
@keyframes lk-draw{from{stroke-dashoffset:var(--len)}to{stroke-dashoffset:0}}
.ontology .graph svg.lk-dashes path[data-a]:not(.e-rel):not(.in){stroke-dasharray:7 7;animation:lk-dash .8s linear infinite}
.ontology .graph svg.lk-dashes.focus path[data-a]:not(.on){animation:none}
.ontology .graph svg.lk-trace path[data-a]{opacity:.1}
.ontology .graph svg.lk-trace path[data-a].hop{opacity:1;stroke-width:3px;stroke-dasharray:var(--len);animation:lk-draw .7s ease-out both}
.ontology .graph svg.lk-trace g[data-node]{opacity:.35}
.ontology .graph svg.lk-trace g[data-node].hop{opacity:1}
.ontology .graph svg.lk-trace g[data-node].hop rect{stroke-width:2.5}
.ontology .lk-dot{pointer-events:none}
@media (prefers-reduced-motion: reduce){
.ontology .graph svg.lk-dashes path[data-a],.ontology .graph svg.lk-trace path[data-a].hop{animation:none}
.ontology .lk-dot{display:none}}
"""

JS = """
function hl(box, cb){
  var svg = box.querySelector('svg'), pinned = null;
  if (!svg) return;
  function tracing(){ return svg.classList.contains('lk-trace'); }
  function show(id){
    svg.classList.toggle('focus', !!id);
    var near = {}; if (id) near[id] = 1;
    svg.querySelectorAll('path[data-a]').forEach(function(p){
      var on = !!id && (p.getAttribute('data-a') === id || p.getAttribute('data-b') === id);
      p.classList.toggle('on', on);
      if (on) { near[p.getAttribute('data-a')] = 1; near[p.getAttribute('data-b')] = 1; }
    });
    svg.querySelectorAll('g[data-node]').forEach(function(g){ g.classList.toggle('on', !!near[g.getAttribute('data-node')]); });
    if (cb) cb(id);
  }
  svg.querySelectorAll('g[data-node]').forEach(function(g){
    var id = g.getAttribute('data-node');
    g.addEventListener('mouseenter', function(){ if (!pinned && !tracing()) show(id); });
    g.addEventListener('mouseleave', function(){ if (!pinned && !tracing()) show(null); });
    g.addEventListener('focus', function(){ if (!pinned && !tracing()) show(id); });
    g.addEventListener('click', function(){
      if (box.lkLook === 'follow' || box.lkLook === 'combo') { pinned = null; show(null); lkTrace(box, id); if (cb) cb(id); return; }
      pinned = pinned === id ? null : id; show(pinned || id); });
  });
  svg.addEventListener('click', function(ev){ if (!ev.target.closest('g[data-node]')) { pinned = null; show(null); if (tracing()) lkApply(box); } });
  return {pin: function(id){ if (tracing()) lkApply(box); pinned = id; show(id); }};
}
var LK_HINTS = {plain: 'Hover or click a box to see only its lines.',
  dashes: 'Dashes move the way the data moves. With a box selected, only its lines move.',
  dots: 'Dots travel along each line; a line that carries more has more dots.',
  follow: 'Click a box: its path lights up one hop at a time, downstream. Click the background to clear.',
  sized: 'The thicker the line, the more it carries: tables on the overview, jobs on the lineage graph.',
  gradient: 'Each line fades in from where the data comes from to where it goes.',
  combo: 'Moving dashes, thickness by volume, and click a box to follow its data hop by hop.'};
var LK_NS = 'http://www.w3.org/2000/svg';
function lkGet(){ try { return localStorage.getItem('acme-ontology-look') || 'plain'; } catch (e) { return 'plain'; } }
function lkSet(v){ try { localStorage.setItem('acme-ontology-look', v); } catch (e) {} }
function lkFlow(svg){ return [].slice.call(svg.querySelectorAll('path[data-a]')).filter(function(p){ return !p.classList.contains('e-rel'); }); }
function lkCarries(p){ var t = (p.querySelector('title') || {}).textContent || '', i = t.indexOf(': '); return i < 0 ? 1 : t.slice(i + 2).split(',').length; }
function lkStop(box){ (box.lkTimer || []).forEach(clearTimeout); box.lkTimer = []; }
function lkApply(box){
  var svg = box.querySelector('svg'), v = box.lkLook || 'plain';
  lkStop(box);
  if (!svg) return;
  svg.classList.remove('lk-dashes', 'lk-trace');
  svg.querySelectorAll('.lk-x').forEach(function(n){ n.parentNode.removeChild(n); });
  svg.querySelectorAll('.hop').forEach(function(n){ n.classList.remove('hop'); });
  var defs = svg.querySelector('defs');
  lkFlow(svg).forEach(function(p, i){
    p.id = box.id + '-p' + i; p.style.strokeWidth = ''; p.style.stroke = '';
    p.style.setProperty('--len', Math.ceil(p.getTotalLength()));
    if (v === 'sized' || v === 'combo') p.style.strokeWidth = Math.min(1.2 + 1.1 * lkCarries(p), 9) + 'px';
    if (v === 'gradient' && defs) {
      // end points from the path data, not getBBox(): a graph on a hidden tab has no layout yet
      var xy = (p.getAttribute('d') || '').match(/-?\d+(?:\.\d+)?/g) || [0, 0, 1, 0], n = xy.length;
      var c = getComputedStyle(p).stroke, g = document.createElementNS(LK_NS, 'linearGradient');
      g.id = p.id + '-g'; g.setAttribute('class', 'lk-x'); g.setAttribute('gradientUnits', 'userSpaceOnUse');
      g.setAttribute('x1', xy[0]); g.setAttribute('y1', xy[1]);
      g.setAttribute('x2', +xy[n - 2] === +xy[0] ? +xy[0] + 1 : xy[n - 2]); g.setAttribute('y2', xy[n - 1]);
      g.innerHTML = '<stop offset="0" stop-color="' + c + '" stop-opacity=".15"/><stop offset="1" stop-color="' + c + '"/>';
      defs.appendChild(g); p.style.stroke = 'url(#' + g.id + ')';
    }
    if (v === 'dots') {
      var n = Math.min(lkCarries(p), 4), col = getComputedStyle(p).stroke;
      for (var k = 0; k < n; k++) {
        var d = document.createElementNS(LK_NS, 'circle');
        d.setAttribute('r', 3.2); d.setAttribute('class', 'lk-dot lk-x'); d.setAttribute('fill', col);
        d.innerHTML = '<animateMotion dur="3.2s" begin="' + (k * 3.2 / n).toFixed(2) + 's" repeatCount="indefinite"><mpath href="#' + p.id + '"/></animateMotion>';
        svg.appendChild(d);
      }
    }
  });
  if (v === 'dashes' || v === 'combo') svg.classList.add('lk-dashes');
}
function lkLevels(svg, start){
  var paths = lkFlow(svg), seen = {}, nodes = [[start]], hops = [], used = [];
  seen[start] = 1;
  while (hops.length < 6) {
    var front = nodes[nodes.length - 1], next = [], ps = [];
    paths.forEach(function(p){ var a = p.getAttribute('data-a'), b = p.getAttribute('data-b');
      if (front.indexOf(a) >= 0 && used.indexOf(p) < 0) { used.push(p); ps.push(p); if (!seen[b]) { seen[b] = 1; next.push(b); } } });
    if (!ps.length) break;
    hops.push(ps); nodes.push(next);
  }
  return {nodes: nodes, hops: hops};
}
function lkTrace(box, start){
  var svg = box.querySelector('svg'), lv = lkLevels(svg, start);
  lkStop(box);
  svg.classList.remove('lk-dashes', 'focus'); svg.classList.add('lk-trace');
  svg.querySelectorAll('.hop,.on').forEach(function(n){ n.classList.remove('hop', 'on'); });
  function mark(ids){ svg.querySelectorAll('g[data-node]').forEach(function(g){ if (ids.indexOf(g.getAttribute('data-node')) >= 0) g.classList.add('hop'); }); }
  mark([start]);
  lv.hops.forEach(function(ps, k){
    box.lkTimer.push(setTimeout(function(){ ps.forEach(function(p){ p.classList.add('hop'); }); }, k * 850));
    box.lkTimer.push(setTimeout(function(){ mark(lv.nodes[k + 1]); }, k * 850 + 600));
  });
  return lv;
}
function lkName(svg, id){
  var g = [].slice.call(svg.querySelectorAll('g[data-node]')).filter(function(x){ return x.getAttribute('data-node') === id; })[0];
  return g && g.querySelector('title') ? g.querySelector('title').textContent.split(' — ')[0] : id;
}
document.querySelectorAll('.lk-pick').forEach(function(sel){
  sel.value = lkGet();
  sel.addEventListener('change', function(){
    lkSet(sel.value);
    document.querySelectorAll('.lk-pick').forEach(function(o){ o.value = sel.value; });
    document.querySelectorAll('.graph[data-hl]').forEach(function(b){ b.lkLook = sel.value; lkApply(b); });
    document.querySelectorAll('.lk-hint').forEach(function(h){ h.textContent = LK_HINTS[sel.value] || ''; });
  });
});
document.querySelectorAll('.lk-hint').forEach(function(h){ h.textContent = LK_HINTS[lkGet()] || ''; });
document.querySelectorAll('.graph[data-hl]:not(#lg-out)').forEach(function(b){ b.lkLook = lkGet(); b.lkPin = hl(b).pin; lkApply(b); });
(function(){
  var box = document.getElementById('ov-out'), btn = document.getElementById('ov-play'), cap = document.getElementById('ov-story');
  if (!box || !btn) return;
  var svg = box.querySelector('svg'), playing = [];
  function stop(){ playing.forEach(clearTimeout); playing = []; btn.textContent = 'Play the main flows'; cap.textContent = ''; lkApply(box); }
  btn.addEventListener('click', function(){
    if (playing.length) { stop(); return; }
    var srcs = {}, dst = {};
    lkFlow(svg).forEach(function(p){ srcs[p.getAttribute('data-a')] = 1; dst[p.getAttribute('data-b')] = 1; });
    var order = [].slice.call(svg.querySelectorAll('g[data-node]')).map(function(g){ return g.getAttribute('data-node'); })
      .filter(function(id){ return srcs[id] && !dst[id]; });
    btn.textContent = 'Stop';
    order.forEach(function(id, i){
      playing.push(setTimeout(function(){
        var lv = lkTrace(box, id);
        cap.textContent = (i + 1) + ' of ' + order.length + ': ' + lv.nodes.filter(function(n){ return n.length; })
          .map(function(n){ return n.map(function(x){ return lkName(svg, x); }).join(', '); }).join('  →  ');
      }, i * 5000));
    });
    playing.push(setTimeout(stop, order.length * 5000));
  });
})();
(function(){
  var d = JSON.parse(document.getElementById('lg-data').textContent), pick = document.getElementById('lg-pick');
  var out = document.getElementById('lg-out'), why = document.getElementById('lg-why');
  function esc(s){return String(s).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}
  function draw(){
    var o = d.objects.filter(function(x){return x[0] === pick.value;})[0], mid = o[2], inMid = {};
    if (drawn !== pick.value) { opened = {}; drawn = pick.value; }
    mid.forEach(function(t){inMid[t] = 1;});
    var up = {}, down = {}, lines = [], inner = [];
    d.edges.forEach(function(e){
      if (inMid[e[1]] && !inMid[e[0]]) { up[e[0]] = 1; lines.push([0, e]); }
      else if (inMid[e[0]] && !inMid[e[1]]) { down[e[1]] = 1; lines.push([2, e]); }
      else if (inMid[e[0]] && inMid[e[1]]) { inner.push(e); }
    });
    groups = {};
    if (grpBox.checked) [[0, up], [2, down]].forEach(function(sd){
      var by = {};
      Object.keys(sd[1]).forEach(function(t){ var p = t.split('_'); if (p.length > 2) { var k = p[0] + '_' + p[1] + '_'; (by[k] = by[k] || []).push(t); } });
      Object.keys(by).forEach(function(k){ if (by[k].length >= 3 && !opened[sd[0] + k]) {
        var gid = sd[0] + ':' + k + '*'; groups[gid] = {side: sd[0], key: k, members: by[k], label: k + '* (' + by[k].length + ')'};
        by[k].forEach(function(t){ delete sd[1][t]; }); sd[1][gid] = 1; } });
    });
    var alias = {};
    Object.keys(groups).forEach(function(gid){ groups[gid].members.forEach(function(t){ alias[groups[gid].side + t] = gid; }); });
    var merged = {}, ml = [];
    lines.forEach(function(l){ var e = l[1], a = l[0] === 0 ? (alias['0' + e[0]] || e[0]) : e[0], b = l[0] === 2 ? (alias['2' + e[1]] || e[1]) : e[1], k = l[0] + '|' + a + '|' + b;
      if (!merged[k]) { merged[k] = [l[0], [a, b, []]]; ml.push(merged[k]); }
      e[2].forEach(function(v){ if (merged[k][1][2].indexOf(v) < 0) merged[k][1][2].push(v); }); });
    lines = ml;
    var X = [10, 420, 830], W = 260, H = 26, G = 8, n = Math.max(Object.keys(up).length, mid.length, Object.keys(down).length, 1);
    var top = 30, midTop = top + (n - mid.length) * (H + G) / 2, my = {};
    mid.forEach(function(t, j){ my[t] = midTop + j * (H + G); });
    function bary(side, t){ var s = 0, c = 0; lines.forEach(function(l){ var e = l[1];
      if (l[0] === side && (e[0] === t || e[1] === t)) { s += my[side === 0 ? e[1] : e[0]]; c++; } }); return c ? s / c : 0; }
    var cols = [Object.keys(up), mid, Object.keys(down)], pos = {}, svg = [];
    [0, 2].forEach(function(i){ cols[i].sort(function(a, b){ return bary(i, a) - bary(i, b) || (a < b ? -1 : 1); }); });
    cols.forEach(function(c, i){ var t0 = i === 1 ? midTop : top + (n - c.length) * (H + G) / 2;
      c.forEach(function(t, j){ pos[i + ':' + t] = [X[i], t0 + j * (H + G)]; }); });
    var ports = {}, at = {};
    lines.forEach(function(l, k){ var e = l[1], a = l[0] === 0 ? '0:' + e[0] : '1:' + e[0], b = l[0] === 0 ? '1:' + e[1] : '2:' + e[1];
      l.push(a, b); (ports[a + 'r'] = ports[a + 'r'] || []).push([pos[b][1], k]); (ports[b + 'l'] = ports[b + 'l'] || []).push([pos[a][1], k]); });
    Object.keys(ports).forEach(function(key){ var lst = ports[key].sort(function(p, q){ return p[0] - q[0]; }), node = key.slice(0, -1), st = (H - 6) / lst.length;
      lst.forEach(function(p, j){ at[p[1] + key.slice(-1)] = pos[node][1] + 3 + st * (j + .5); }); });
    svg.push('<defs><marker id="lg-ar" viewBox="0 0 8 8" refX="7" refY="4" markerUnits="userSpaceOnUse" markerWidth="8" markerHeight="8" orient="auto"><path d="M0 0 L8 4 L0 8 z"/></marker></defs>');
    lines.forEach(function(l, k){ var e = l[1], a = pos[l[2]], b = pos[l[3]];
      var x1 = a[0] + W, y1 = at[k + 'r'], x2 = b[0] - 2, y2 = at[k + 'l'], mx = (x1 + x2) / 2;
      var cls = e[2].length === 1 && e[2][0].indexOf('column') === 0 ? 'cl' : '';
      svg.push('<path class="'+cls+'" data-a="'+esc(e[0])+'" data-b="'+esc(e[1])+'" marker-end="url(#lg-ar)" d="M'+x1+' '+y1+' C'+mx+' '+y1+' '+mx+' '+y2+' '+x2+' '+y2+'"><title>'+esc(e[0]+' → '+e[1]+': '+e[2].join(', '))+'</title></path>'); });
    inner.forEach(function(e, k){ var a = pos['1:' + e[0]], b = pos['1:' + e[1]]; if (!a || !b) return;
      var x = X[1] + W, m = x + 24 + (k % 4) * 10;
      svg.push('<path class="in" data-a="'+esc(e[0])+'" data-b="'+esc(e[1])+'" marker-end="url(#lg-ar)" d="M'+x+' '+(a[1]+H/2)+' C'+m+' '+(a[1]+H/2)+' '+m+' '+(b[1]+H/2)+' '+(x+2)+' '+(b[1]+H/2)+'"><title>'+esc(e[0]+' → '+e[1]+': '+e[2].join(', '))+'</title></path>'); });
    cols.forEach(function(c, i){ c.forEach(function(t){ var p = pos[i + ':' + t];
      svg.push('<g class="n'+(i === 1 ? ' me' : '')+(groups[t] ? ' grp' : '')+'" data-node="'+esc(t)+'"'+(groups[t] ? ' data-group="'+esc(groups[t].side + groups[t].key)+'"' : '')+' tabindex="0"><rect x="'+p[0]+'" y="'+p[1]+'" width="'+W+'" height="'+H+'" rx="5"/><text x="'+(p[0]+8)+'" y="'+(p[1]+17)+'">'+esc(groups[t] ? groups[t].label : t.length > 34 ? t.slice(0, 33) + '…' : t)+'</text><title>'+esc(groups[t] ? groups[t].label + ' — ' + groups[t].members.join(', ') + ' (click to open)' : t)+'</title></g>'); }); });
    var hd = ['Written from', o[1] + ' tables', 'Written into'].map(function(h, i){ return '<text x="'+X[i]+'" y="18" style="font-weight:700">'+esc(h)+'</text>'; }).join('');
    out.innerHTML = mid.length ? '<svg viewBox="0 0 1100 '+(40 + n * (H + G))+'" role="img" aria-label="Lineage for '+esc(o[1])+'">'+hd+svg.join('')+'</svg>' : '<p>No table is linked to this object yet.</p>';
    why.innerHTML = '';
    zoom(0);
    out.lkLook = lkGet();
    out.lkPin = hl(out, function(t){
      if (!t) { why.innerHTML = ''; return; }
      var w = [], mem = groups[t] ? groups[t].members : [t];
      d.edges.forEach(function(e){ if ((mem.indexOf(e[0]) >= 0 || mem.indexOf(e[1]) >= 0) && (inMid[e[0]] || inMid[e[1]])) w.push('<li><b>'+esc(e[0])+' → '+esc(e[1])+'</b> — '+esc(e[2].join(', '))+'</li>'); });
      why.innerHTML = '<b>'+esc(groups[t] ? groups[t].label : t)+'</b>' + (w.length ? '<ul>'+w.join('')+'</ul>' : ': no lines');
    }).pin;
    out.querySelectorAll('g[data-group]').forEach(function(g){ g.addEventListener('click', function(){ opened[g.getAttribute('data-group')] = 1; draw(); }); });
    lkApply(out);
    var names = {};
    mid.concat(Object.keys(up), Object.keys(down)).forEach(function(t){ (groups[t] ? groups[t].members : [t]).forEach(function(m){ names[m] = 1; }); });
    document.getElementById('lg-names').innerHTML = Object.keys(names).sort().map(function(t){ return '<option value="'+esc(t)+'">'; }).join('');
    return names;
  }
  var groups = {}, opened = {}, drawn = null, z = 1, grpBox = document.getElementById('lg-group'), find = document.getElementById('lg-find');
  function zoom(step){
    z = step === 0 && arguments.length && zoom.fit ? 1 : Math.max(.5, Math.min(3, z + step * .25)); zoom.fit = false;
    var s = out.querySelector('svg'); if (s) { s.style.width = (100 * z) + '%'; s.style.minWidth = (900 * z) + 'px'; }
  }
  document.querySelectorAll('.lk-zoom [data-z]').forEach(function(b){ b.addEventListener('click', function(){
    var st = +b.getAttribute('data-z'); if (!st) zoom.fit = true; zoom(st); }); });
  function locate(){
    var q = find.value.trim().toUpperCase(); if (!q) return;
    function hit(list){ return list.filter(function(t){ return t.toUpperCase() === q; })[0] || list.filter(function(t){ return t.toUpperCase().indexOf(q) >= 0; })[0]; }
    var t = hit(Object.keys(draw.names || {}));
    if (!t) {
      var all = {}; d.objects.forEach(function(x){ x[2].forEach(function(n){ all[n] = 1; }); }); d.edges.forEach(function(e){ all[e[0]] = 1; all[e[1]] = 1; });
      t = hit(Object.keys(all));
      var o = t && (d.objects.filter(function(x){ return x[2].indexOf(t) >= 0; })[0] || d.objects.filter(function(x){ return d.edges.some(function(e){
        return (e[0] === t && x[2].indexOf(e[1]) >= 0) || (e[1] === t && x[2].indexOf(e[0]) >= 0); }); })[0]);
      if (o) { pick.value = o[0]; draw.names = draw(); } else t = null;
    }
    if (!t) { why.textContent = 'No table matching "' + find.value + '" in the lineage graphs.'; return; }
    Object.keys(groups).forEach(function(gid){ if (groups[gid].members.indexOf(t) >= 0) { opened[groups[gid].side + groups[gid].key] = 1; draw.names = draw(); } });
    out.lkPin(t);
    var g = [].slice.call(out.querySelectorAll('g[data-node]')).filter(function(x){ return x.getAttribute('data-node') === t; })[0];
    if (g && g.scrollIntoView) g.scrollIntoView({block: 'nearest', inline: 'center'});
  }
  find.addEventListener('change', locate);
  find.addEventListener('keydown', function(ev){ if (ev.key === 'Enter') locate(); });
  grpBox.addEventListener('change', function(){ opened = {}; draw.names = draw(); });
  pick.addEventListener('change', function(){ draw.names = draw(); }); draw.names = draw();
})();
document.querySelectorAll('input[data-filter]').forEach(function(inp){
  inp.addEventListener('input', function(){
    var q = inp.value.toLowerCase();
    document.querySelectorAll('table.' + inp.dataset.filter + ' > tbody > tr').forEach(function(tr){
      tr.hidden = q && tr.textContent.toLowerCase().indexOf(q) < 0;
    });
  });
});
"""


class Dumper(yaml.SafeDumper):
    pass


def _str(dumper, value):
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


Dumper.add_representer(str, _str)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out-dir", default=os.path.join(REPO, OUT_DIR))
    args = ap.parse_args()
    onto = build()
    os.makedirs(args.out_dir, exist_ok=True)
    y = os.path.join(args.out_dir, "ACME_ONTOLOGY.yaml")
    h = os.path.join(args.out_dir, "ACME_ONTOLOGY.html")
    with open(y, "w", encoding="utf-8") as fh:
        fh.write("# Acme Claims ontology — generated by %s. Do not edit by hand; edit the KB sources and re-run.\n"
                 % onto["metadata"]["generator"])
        yaml.dump(onto, fh, Dumper=Dumper, sort_keys=False, allow_unicode=True, width=120)
    with open(h, "w", encoding="utf-8") as fh:
        fh.write(render_html(onto))
    print("wrote %s\nwrote %s" % (os.path.relpath(y, REPO), os.path.relpath(h, REPO)))


if __name__ == "__main__":
    main()
