import json
import os
import shutil
import sys
import tempfile
import unittest

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import build_outputs  # noqa: E402
import gen_matrix  # noqa: E402
import gen_registry  # noqa: E402
import kb_manifest  # noqa: E402
import verify_kb  # noqa: E402


def w(p, t):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(t)


def L(f, r, t, s):
    return {"from": {"type": f[0], "name": f[1]}, "rel": r, "to": {"type": t[0], "name": t[1]}, "source": s}


class Outputs(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.kb = os.path.join(self.root, "team", "kb")
        w(os.path.join(self.root, "api/src/A.java"), 'class A {\n  @GetMapping("/orders")\n  String q = "FROM ORDERS";\n}\n')
        w(os.path.join(self.root, "ui/src/P.tsx"), "useFetch('/orders')\n")
        w(os.path.join(self.root, "etl/j.py"), "read('APP.ORDERS')\nwrite('RPT.T')\n")
        w(os.path.join(self.kb, ".metis/kb-profile.yaml"), yaml.safe_dump({
            "product": {"name": "T", "short_name": "t"}, "paths": {"db_docs": "<KB>/db"}, "db": {"kb_environment": "dev"},
            "sources": {"workspace_root": self.root, "repos": {"api": "api", "ui": "ui", "etl": "etl"}}}))
        w(os.path.join(self.kb, ".metis/db-environments.yaml"), yaml.safe_dump({"reference_environment": "dev", "environments": {
            "dev": {"databases": [{"label": "D", "engine": "snowflake", "database": "D"}]}}}))

    def tearDown(self):
        shutil.rmtree(self.root)

    def links(self, extra=()):
        w(os.path.join(self.kb, "m/x.links.yaml"), yaml.safe_dump({"links": [
            L(("screen", "P"), "calls", ("endpoint", "GET /orders"), "[E: ui/src/P.tsx:1 \"useFetch('/orders')\"]"),
            L(("endpoint", "GET /orders"), "reads", ("table", "APP.ORDERS"), '[E: api/src/A.java:3 "FROM ORDERS"]'),
            L(("job", "j"), "reads", ("table", "APP.ORDERS"), "[E: etl/j.py:1 \"APP.ORDERS\"]")] + list(extra)}))

    def catalog(self):
        q = os.path.join(self.kb, "_EVIDENCE/queries")
        for qid, rows in (("CATALOG-TABLES", [{"TABLE_SCHEMA": "APP", "TABLE_NAME": "ORDERS", "TABLE_TYPE": "BASE TABLE"},
                                              {"TABLE_SCHEMA": "APP", "TABLE_NAME": "C", "TABLE_TYPE": "BASE TABLE"}]),
                          ("CATALOG-COLUMNS", [{"TABLE_SCHEMA": "APP", "TABLE_NAME": "ORDERS", "COLUMN_NAME": "C_ID", "ORDINAL_POSITION": 1, "DATA_TYPE": "NUMBER"},
                                               {"TABLE_SCHEMA": "APP", "TABLE_NAME": "C", "COLUMN_NAME": "C_ID", "ORDINAL_POSITION": 1, "DATA_TYPE": "NUMBER"}]),
                          ("CATALOG-FKEYS", [{"fk_schema_name": "APP", "fk_table_name": "ORDERS", "fk_column_name": "C_ID",
                                              "pk_schema_name": "APP", "pk_table_name": "C", "pk_column_name": "C_ID"}])):
            w(os.path.join(q, qid + ".sql"), "select 1\n")
            w(os.path.join(q, qid + ".json"), json.dumps(rows))

    def test_full_run_writes_visualization_folder_and_verifies(self):
        self.links()
        self.catalog()
        self.assertEqual(build_outputs.main([self.kb]), 0)
        for f in ("index.html", "ONTOLOGY.html", "ERD.html", "KB_HEALTH.html", "KB_MANIFEST.html"):
            self.assertTrue(os.path.isfile(os.path.join(self.kb, "VISUALIZATION", f)), f)
        for f in ("CROSS-LAYER/IMPACT_MATRIX.yaml", "CROSS-LAYER/QA_COVERAGE.yaml", "db/DB_TABLE_REGISTRY.yaml",
                  "db/ERD.md", "db/CORTEX_SEMANTIC_MODEL.yaml", "KNOWLEDGE-MANIFEST.yaml"):
            self.assertTrue(os.path.isfile(os.path.join(self.kb, f)), f)
        self.assertEqual(verify_kb.Checker(self.kb).run()["problems"], [])

    def test_visual_pages_have_no_purple_banner_or_logo(self):
        self.links()
        self.catalog()
        self.assertEqual(build_outputs.main([self.kb]), 0)
        for f in ("index.html", "ONTOLOGY.html", "ERD.html", "KB_HEALTH.html", "KB_MANIFEST.html", "TECH_STACK.html", "DB_DRIFT.html"):
            path = os.path.join(self.kb, "VISUALIZATION", f)
            if os.path.isfile(path):
                with open(path, encoding="utf-8") as fh:
                    content = fh.read()
                self.assertNotIn("linear-gradient", content, "linear-gradient found in %s" % f)
                self.assertNotIn("data:image/png;base64", content, "base64 logo found in %s" % f)
                self.assertNotIn("data:image/svg+xml;base64", content, "base64 svg logo found in %s" % f)
                self.assertIn("background:#fff", content)
                self.assertIn(".embedded header,.embedded footer{display:none}", content)

    def test_ontology_grouped_menu_structure(self):
        self.links()
        self.catalog()
        self.assertEqual(build_outputs.main([self.kb]), 0)
        with open(os.path.join(self.kb, "VISUALIZATION", "ONTOLOGY.html"), encoding="utf-8") as fh:
            content = fh.read()
        for grp in ("overview", "explore", "domain", "data", "quality"):
            self.assertIn("data-grp='%s'" % grp, content)
        for tab in ("overview", "graph", "flows", "impact", "sec-bo", "sec-rels", "sec-rules", "sec-proc",
                    "sec-tables", "lineage", "sec-apps", "sec-qa", "sec-openq"):
            self.assertIn("data-t='%s'" % tab, content)
            self.assertIn("id='%s'" % tab, content)
        self.assertIn("role='tablist'", content)
        self.assertIn("role='tab'", content)
        self.assertIn("role='tabpanel'", content)

    def test_unsourced_link_not_drawn_and_build_fails(self):
        self.links([L(("endpoint", "GET /orders"), "reads", ("table", "APP.MADE_UP"), "[E: api/src/A.java:40]"),
                    L(("endpoint", "GET /orders"), "reads", ("table", "APP.NO_TAG"), "")])
        self.assertEqual(build_outputs.main([self.kb]), 1)
        with open(os.path.join(self.kb, "VISUALIZATION", "ONTOLOGY.html"), encoding="utf-8") as fh:
            page = fh.read()
        data = page.split("var D=", 1)[1]
        self.assertNotIn('"table:APP.MADE_UP"', data.split('"rejected"')[0])
        self.assertNotIn('"table:APP.NO_TAG"', data.split('"rejected"')[0])

    def test_impact_chain_follows_direction_and_names_sources(self):
        self.links()
        build_outputs.main([self.kb])
        m = gen_matrix.load(os.path.join(self.kb, "CROSS-LAYER/IMPACT_MATRIX.yaml"))["entries"]
        moves = {c["moves"] for c in m["table:APP.ORDERS"]["chain"]}
        self.assertEqual(moves, {"endpoint:GET /orders", "screen:P", "job:j"})
        self.assertNotIn("screen:P", m)  # nothing depends on the screen
        for c in m["table:APP.ORDERS"]["chain"]:
            self.assertTrue(all(s["source"].startswith("[E:") for s in c["via"]))

    def test_curated_chain_kept_only_when_sourced(self):
        self.links()
        w(os.path.join(self.kb, "CROSS-LAYER/IMPACT_MATRIX.CURATED.yaml"), yaml.safe_dump({"chains": [
            {"start": {"type": "table", "name": "APP.ORDERS"}, "steps": [{"from": "a", "rel": "reads", "to": "b", "source": '[E: api/src/A.java:3 "FROM ORDERS"]'}]},
            {"start": {"type": "table", "name": "APP.ORDERS"}, "steps": [{"from": "a", "rel": "reads", "to": "b", "source": "someone said so"}]}]}))
        _, curated, rejected, _, _ = gen_matrix.build(self.kb)
        self.assertEqual((len(curated), len(rejected)), (1, 1))

    def test_underscore_relation_is_followed_and_unknown_ones_are_reported(self):
        self.links([L(("endpoint", "GET /orders"), "handled_by", ("class", "OrderCtl"), '[E: api/src/A.java:1 "class A"]'),
                    L(("class", "OrderCtl"), "maps_to", ("dbt_model", "orders"), '[E: api/src/A.java:3 "FROM ORDERS"]')])
        build_outputs.main([self.kb])
        m = gen_matrix.load(os.path.join(self.kb, "CROSS-LAYER/IMPACT_MATRIX.yaml"))
        self.assertIn("endpoint:GET /orders", {c["moves"] for c in m["entries"]["class:OrderCtl"]["chain"]})
        self.assertEqual(m["not_understood"]["relations"], {"maps_to": 1})
        self.assertEqual(m["not_understood"]["node_types"], {"dbt_model": 1})

    def test_no_tests_source_means_nothing_tested(self):
        self.links()
        build_outputs.main([self.kb])
        cov = gen_matrix.load(os.path.join(self.kb, "CROSS-LAYER/QA_COVERAGE.yaml"))
        self.assertFalse(cov["test_sources_read"])
        self.assertTrue(all(x["tested_by"] == [] for v in cov["items"].values() for x in v))

    def test_missing_optional_sources_still_builds_pages(self):
        self.assertIsNone(gen_registry.build(self.kb, {}))
        self.assertEqual(build_outputs.main([self.kb]), 0)
        self.assertTrue(os.path.isfile(os.path.join(self.kb, "VISUALIZATION", "ERD.html")))
        self.assertFalse(os.path.exists(os.path.join(self.kb, "db", "ERD.md")))

    def test_manifest_validate_detects_change(self):
        self.links()
        build_outputs.main([self.kb])
        self.assertEqual(kb_manifest.main(["validate", self.kb]), 0)
        w(os.path.join(self.kb, "m/new.md"), "x\n")
        self.assertEqual(kb_manifest.main(["validate", self.kb]), 1)

    def test_yaml_escaped_quotes_resolve(self):
        self.links()
        rep = verify_kb.Checker(self.kb).run()
        self.assertEqual(rep["problems"], [])


if __name__ == "__main__":
    unittest.main()
