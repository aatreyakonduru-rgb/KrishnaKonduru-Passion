#!/usr/bin/env python3
"""ERD and Cortex Analyst semantic model from the table registry and sourced key/join links.

    python3 gen_db_assets.py <kb> [--settings <kb>/.metis/kb-profile.yaml]

Reads <db_docs>/DB_TABLE_REGISTRY.yaml (gen_registry.py) and CROSS-LAYER/LINK_GRAPH.yaml. Relationships come
only from column `references` links (declared foreign keys) and `joins` links (joins the code runs, with
file and line). Writes <db_docs>/ERD.md (Mermaid) and, when the KB environment's database is in
db-environments.yaml, <db_docs>/CORTEX_SEMANTIC_MODEL.yaml. Descriptions are taken only from
catalogue comments; a column without a comment gets no description.
"""
import argparse
import os
import re
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gen_registry  # noqa: E402

TIME = re.compile(r"DATE|TIME", re.I)
NUM = re.compile(r"NUMBER|DECIMAL|NUMERIC|INT|FLOAT|DOUBLE|REAL", re.I)


def load(p):
    if not os.path.isfile(p):
        return {}
    with open(p, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def relationships(kb, tables):
    g = load(os.path.join(kb, "CROSS-LAYER", "LINK_GRAPH.yaml"))
    rels = []
    for e in g.get("edges") or []:
        r = str(e["rel"]).lower()
        if r not in ("references", "joins") or not (e["from"].startswith("column:") and e["to"].startswith("column:")):
            continue
        a, b = e["from"][7:].rsplit(".", 1), e["to"][7:].rsplit(".", 1)
        if len(a) == 2 and len(b) == 2 and a[0] in tables and b[0] in tables:
            rels.append({"from_table": a[0], "from_column": a[1], "to_table": b[0], "to_column": b[1],
                         "kind": r, "source": e["source"]})
    return rels


def mid(s):
    return re.sub(r"[^A-Za-z0-9_]", "_", s)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("kb")
    ap.add_argument("--settings")
    a = ap.parse_args(argv)
    meta = os.path.join(a.kb, ".metis")
    settings = load(a.settings or os.path.join(meta, "kb-profile.yaml"))
    out = gen_registry.db_docs(a.kb, settings)
    regp = os.path.join(out, "DB_TABLE_REGISTRY.yaml")
    reg = load(regp)
    if not reg.get("tables"):
        print("no table registry; ERD and semantic model not built")
        return 0
    regrel = os.path.relpath(regp, a.kb)
    tables = {t.get("key") or "%s.%s" % (t["schema"], t["name"]): t for t in reg["tables"]}
    rels = relationships(a.kb, tables)
    used = sorted({r["from_table"] for r in rels} | {r["to_table"] for r in rels})
    md = ["# Entity relationship diagram", "",
          "Tables and columns from the table registry, relationships from declared keys and from joins the code "
          "runs. [E: kb:%s]" % regrel, ""]
    if rels:
        md += ["```mermaid", "erDiagram"]
        for t in used:
            md.append("  %s {" % mid(t))
            keys = {r["from_column"] for r in rels if r["from_table"] == t} | {r["to_column"] for r in rels if r["to_table"] == t}
            for c in tables[t]["columns"]:
                if c["name"] in keys:
                    md.append("    %s %s" % (mid(str(c.get("data_type") or "UNKNOWN").split("(")[0]), mid(c["name"])))
            md.append("  }")
        for r in rels:
            md.append('  %s }o--|| %s : "%s %s"' % (mid(r["from_table"]), mid(r["to_table"]), r["kind"], mid(r["from_column"])))
        md += ["```", "", "## Sources", "", "| From | To | Kind | Source |", "|---|---|---|---|"]
        md += ["| %s.%s | %s.%s | %s | %s |" % (r["from_table"], r["from_column"], r["to_table"], r["to_column"], r["kind"],
                                               r["source"]) for r in rels]
    else:
        md += ["## Open questions", "", "No declared keys and no sourced joins were found, so no relationships are drawn.", ""]
    with open(os.path.join(out, "ERD.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md) + "\n")
    snow = {k: t for k, t in tables.items() if str(t.get("engine") or "").lower() == "snowflake" and t.get("database")}
    if not snow:
        print("ERD written; semantic model not built: it is a Snowflake Cortex model and no Snowflake tables are in the registry")
        return 0
    model = {"name": (settings.get("product") or {}).get("short_name") or "kb", "tables": [], "relationships": []}
    for key in sorted(snow):
        t = snow[key]
        e = {"name": mid(t["name"]), "base_table": {"database": t["database"], "schema": t.get("schema"), "table": t["name"]}}
        if t.get("comment"):
            e["description"] = t["comment"]
        for c in t["columns"]:
            kind = "time_dimensions" if TIME.search(str(c.get("data_type"))) else "facts" if NUM.search(str(c.get("data_type"))) else "dimensions"
            d = {"name": mid(c["name"]).lower(), "expr": c["name"], "data_type": c.get("data_type")}
            if c.get("comment"):
                d["description"] = c["comment"]
            e.setdefault(kind, []).append(d)
        model["tables"].append(e)
    for r in rels:
        if r["kind"] == "references" and r["from_table"] in snow and r["to_table"] in snow:
            model["relationships"].append({"name": mid("%s_%s" % (tables[r["from_table"]]["name"], r["from_column"])).lower(),
                                           "left_table": mid(tables[r["from_table"]]["name"]),
                                           "right_table": mid(tables[r["to_table"]]["name"]),
                                           "relationship_columns": [{"left_column": r["from_column"], "right_column": r["to_column"]}],
                                           "join_type": "left_outer", "relationship_type": "many_to_one"})
    with open(os.path.join(out, "CORTEX_SEMANTIC_MODEL.yaml"), "w", encoding="utf-8") as fh:
        fh.write("# Generated by gen_db_assets.py. Tables, columns and databases from the table registry [E: kb:%s];\n"
                 "# relationships only from declared foreign keys [E: kb:%s]. Descriptions only from catalogue comments.\n" % (regrel, regrel))
        yaml.safe_dump(model, fh, sort_keys=False, allow_unicode=True, width=120)
    print("ERD: %d tables, %d relationships; semantic model: %d tables -> %s" % (len(used), len(rels), len(model["tables"]), out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
