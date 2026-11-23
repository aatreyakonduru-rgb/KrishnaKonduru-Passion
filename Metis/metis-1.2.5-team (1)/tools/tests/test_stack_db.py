import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import db_catalog  # noqa: E402
import detect_stack  # noqa: E402
import gen_registry  # noqa: E402
import verify_kb  # noqa: E402


def _force(func, path, _):
    # Windows keeps .git object files read-only, which blocks rmtree
    os.chmod(path, 0o700)
    func(path)


def w(p, t):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(t)


def git(path):
    subprocess.run("git init -q && git add -A && git -c user.email=t@t -c user.name=t commit -qm i", shell=True, cwd=path, check=True)


class Stack(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()
        self.kb = os.path.join(self.ws, "team", "kb")
        w(os.path.join(self.ws, "api/pom.xml"), "<project>\n<artifactId>spring-boot-starter-web</artifactId>\n"
          "<artifactId>postgresql</artifactId>\n<artifactId>snowflake-jdbc</artifactId>\n</project>\n")
        w(os.path.join(self.ws, "api/src/main/resources/application-sit.yml"),
          "spring:\n  datasource:\n    url: jdbc:postgresql://h:5432/pcms?currentSchema=core\n    password: s3cr3tvalue\n")
        w(os.path.join(self.ws, "api/src/main/resources/application-dev.yml"), "spring:\n  datasource:\n    url: ${DB_URL}\n")
        w(os.path.join(self.ws, "ui/package.json"), '{"dependencies": {"react": "18", "@angular/core": "1"}, "devDependencies": {"vite": "5"}}\n')
        w(os.path.join(self.ws, "sencha/app.json"), '{"name": "X", "framework": "ext"}\n')
        w(os.path.join(self.ws, "etl/requirements.txt"), "psycopg2-binary==2\nsnowflake-connector-python\n")
        w(os.path.join(self.ws, "etl/config/prod/db.yaml"), "database: PCMS_DB\nschema: STAGE\napi_token: abc123\n")
        for r in ("api", "ui", "sencha", "etl"):
            git(os.path.join(self.ws, r))
        w(os.path.join(self.kb, ".metis/kb-profile.yaml"), yaml.safe_dump({"sources": {"workspace_root": self.ws, "repos": {}}}))

    def tearDown(self):
        shutil.rmtree(self.ws, onerror=_force)

    def detected(self):
        self.assertEqual(detect_stack.cmd_detect(self.kb, True), 0)
        with open(os.path.join(self.kb, ".metis", "DETECTED_STACK.yaml"), encoding="utf-8") as fh:
            return yaml.safe_load(fh)

    def names(self, det, cat):
        return {(i["name"], i["repo"]) for i in det["items"] if i["category"] == cat}

    def test_reads_every_cloned_repo(self):
        self.assertEqual({r["name"] for r in self.detected()["repos_read"]}, {"api", "ui", "sencha", "etl"})

    def test_frameworks_from_build_files(self):
        det = self.detected()
        self.assertIn(("Spring Boot", "api"), self.names(det, "framework"))
        ui = self.names(det, "ui")
        for n in ("React", "Vite", "Angular"):
            self.assertIn((n, "ui"), ui)
        self.assertIn(("Sencha Ext JS", "sencha"), ui)
        self.assertIn(("Python", "etl"), self.names(det, "language"))

    def test_every_database_engine_found_with_environment(self):
        det = self.detected()
        engines = {(i.get("engine"), i["repo"], i.get("env")) for i in det["items"] if i["category"] == "database"}
        self.assertIn(("PostgreSQL", "api", "sit"), engines)
        self.assertIn(("Snowflake", "api", None), engines)
        self.assertIn(("PostgreSQL", "etl", None), engines)
        self.assertIn(("Snowflake", "etl", None), engines)

    def test_all_databases_and_schemas_listed(self):
        det = self.detected()
        conn = {(i["key"], i["value"], i.get("env")) for i in det["items"] if i["category"] == "connection"}
        self.assertTrue({("database", "pcms", "sit"), ("schema", "core", "sit"), ("database", "PCMS_DB", "prod"),
                         ("schema", "STAGE", "prod")} <= conn)

    def test_every_finding_cites_a_line_that_checks_out(self):
        det = self.detected()
        c = verify_kb.Checker(self.kb)
        c.root, c.repos = self.ws, det["repos"]
        for i in det["items"]:
            self.assertTrue(i["sources"])
            for s in i["sources"]:
                for k, v in verify_kb.TAG.findall(s):
                    self.assertIsNone(c.resolve(k, v), s)

    def test_secret_values_never_written(self):
        self.detected()
        text = open(os.path.join(self.kb, ".metis", "DETECTED_STACK.yaml"), encoding="utf-8").read()
        self.assertNotIn("s3cr3tvalue", text)
        self.assertNotIn("abc123", text)

    def test_placeholder_becomes_question_not_a_value(self):
        det = self.detected()
        self.assertTrue(any(u["repo"] == "api" and u["env"] == "dev" for u in det["unresolved"]))
        self.assertFalse(any("DB_URL" in str(i.get("value")) for i in det["items"]))
        reg = yaml.safe_load(open(os.path.join(self.kb, "_QUESTIONS", "VALIDATE_KB.yaml"), encoding="utf-8"))
        self.assertTrue(any("set outside the repo" in q["question"] for q in reg["questions"]))

    def test_approve_with_changes_is_traceable(self):
        self.detected()
        ch = os.path.join(self.ws, "ch.yaml")
        w(ch, yaml.safe_dump({"add": [{"category": "database", "name": "Oracle", "engine": "Oracle", "repo": "etl"}],
                              "remove": [{"category": "ui", "name": "Angular", "repo": "ui"}]}))
        self.assertEqual(detect_stack.cmd_approve(self.kb, "Team Lead", ch), 0)
        st = yaml.safe_load(open(os.path.join(self.kb, ".metis", "stack.yaml"), encoding="utf-8"))
        self.assertFalse(any(i["name"] == "Angular" for i in st["items"]))
        added = [i for i in st["items"] if i["name"] == "Oracle"][0]
        self.assertRegex(added["sources"][0], r"^\[E: answer:Q-\d{4}\]$")
        self.assertEqual(st["approved_by"], "Team Lead")
        self.assertTrue(os.path.isfile(os.path.join(self.kb, "context", "TECH_STACK.yaml")))
        out = subprocess.run([sys.executable, os.path.join(os.path.dirname(HERE), "verify_kb.py"), self.kb],
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)

    def test_approve_needs_a_name(self):
        self.detected()
        self.assertEqual(detect_stack.cmd_approve(self.kb, " "), 1)

    def test_remove_of_unknown_item_fails(self):
        self.detected()
        ch = os.path.join(self.ws, "ch.yaml")
        w(ch, yaml.safe_dump({"remove": [{"category": "ui", "name": "Nothing"}]}))
        self.assertEqual(detect_stack.cmd_approve(self.kb, "T", ch), 1)

    def test_show_reports_new_findings_since_approval(self):
        self.detected()
        detect_stack.cmd_approve(self.kb, "T")
        w(os.path.join(self.ws, "ui/package.json"), '{"dependencies": {"react": "18", "vue": "3"}}\n')
        self.detected()
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            detect_stack.cmd_show(self.kb)
        self.assertIn("new: Vue in ui", buf.getvalue())
        self.assertIn("no longer found: Vite in ui", buf.getvalue())


class Databases(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()
        self.kb = os.path.join(self.ws, "team", "kb")
        w(os.path.join(self.kb, ".metis/kb-profile.yaml"), yaml.safe_dump({
            "paths": {"db_docs": "<KB>/db"}, "sources": {"workspace_root": self.ws, "repos": {"legacy": "legacy"}}}))
        w(os.path.join(self.kb, ".metis/db-environments.yaml"), yaml.safe_dump({"reference_environment": "sit", "environments": {
            "sit": {"databases": [{"label": "ANA", "engine": "snowflake", "database": "ANA_SIT", "schemas": ["MART", "STAGE"]},
                                  {"label": "PCMS", "engine": "postgresql", "database": "pcms", "schemas": []},
                                  {"label": "OLD", "engine": "schema-files", "database": "OLDDB", "repo": "legacy",
                                   "paths": ["db/*.sql"]}]},
            "dev": {"databases": [{"label": "ANA", "engine": "snowflake", "database": "ANA_DEV", "schemas": ["MART"]}]}}}))
        w(os.path.join(self.ws, "legacy/db/schema.sql"),
          "CREATE TABLE app.customer (\n  id INTEGER PRIMARY KEY,\n  name VARCHAR(50)\n);\n"
          "create table if not exists app.orders (\n  order_id integer not null,\n"
          "  customer_id integer references app.customer(id),\n  CONSTRAINT pk PRIMARY KEY (order_id)\n);\n")
        q = os.path.join(self.kb, "_EVIDENCE/queries")

        def save(i, rows):
            w(os.path.join(q, i + ".sql"), "select 1\n")
            w(os.path.join(q, i + ".json"), json.dumps(rows))
        t = lambda db, s, n: {"TABLE_CATALOG": db, "TABLE_SCHEMA": s, "TABLE_NAME": n, "TABLE_TYPE": "BASE TABLE"}  # noqa: E731
        c = lambda db, s, n, col, ty: {"TABLE_CATALOG": db, "TABLE_SCHEMA": s, "TABLE_NAME": n, "COLUMN_NAME": col, "DATA_TYPE": ty}  # noqa: E731
        save("CATALOG-TABLES-SIT-ANA", [t("ANA_SIT", "MART", "CLAIM"), t("ANA_SIT", "STAGE", "CLAIM"), t("ANA_SIT", "MART", "NEW_T")])
        save("CATALOG-COLUMNS-SIT-ANA", [c("ANA_SIT", "MART", "CLAIM", "ID", "NUMBER"), c("ANA_SIT", "MART", "CLAIM", "AMT", "NUMBER"),
                                         c("ANA_SIT", "STAGE", "CLAIM", "ID", "TEXT"), c("ANA_SIT", "MART", "NEW_T", "X", "TEXT")])
        save("CATALOG-TABLES-SIT-PCMS", [t("pcms", "core", "member"), t("pcms", "audit", "member")])
        save("CATALOG-COLUMNS-SIT-PCMS", [c("pcms", "core", "member", "id", "integer"), c("pcms", "audit", "member", "id", "integer")])
        save("CATALOG-FKEYS-SIT-PCMS", [{"fk_schema_name": "audit", "fk_table_name": "member", "fk_column_name": "id",
                                         "pk_schema_name": "core", "pk_table_name": "member", "pk_column_name": "id"}])
        save("CATALOG-TABLES-DEV-ANA", [t("ANA_DEV", "MART", "CLAIM")])
        save("CATALOG-COLUMNS-DEV-ANA", [c("ANA_DEV", "MART", "CLAIM", "ID", "VARCHAR"), c("ANA_DEV", "MART", "CLAIM", "AMT", "NUMBER"),
                                         c("ANA_DEV", "MART", "CLAIM", "DEV_ONLY", "TEXT")])

    def tearDown(self):
        shutil.rmtree(self.ws, onerror=_force)

    def run_build(self):
        self.assertEqual(gen_registry.main([self.kb]), 0)
        load = lambda p: yaml.safe_load(open(os.path.join(self.kb, "db", p), encoding="utf-8"))  # noqa: E731
        return load("DB_TABLE_REGISTRY.yaml"), load("DB_DRIFT.yaml"), load

    def test_plan_writes_read_only_queries_per_database_and_schema(self):
        ref, rows = db_catalog.plan(self.kb)
        self.assertEqual(ref, "sit")
        ids = {r[2] for r in rows if r[2]}
        self.assertIn("CATALOG-TABLES-SIT-ANA", ids)
        self.assertIn("CATALOG-FKEYS-SIT-PCMS", ids)
        self.assertIn("CATALOG-COLUMNS-DEV-ANA", ids)
        sql = open(os.path.join(self.kb, "_EVIDENCE/queries/CATALOG-TABLES-SIT-ANA.sql"), encoding="utf-8").read()
        self.assertIn("ANA_SIT.INFORMATION_SCHEMA.TABLES", sql)
        self.assertIn("IN ('MART', 'STAGE')", sql)
        pg = open(os.path.join(self.kb, "_EVIDENCE/queries/CATALOG-TABLES-SIT-PCMS.sql"), encoding="utf-8").read()
        self.assertNotIn(" IN ()", pg)
        self.assertTrue(any(r[2] is None and "schema files" in r[3] for r in rows))
        self.assertFalse(db_catalog.read_only("DROP TABLE x"))

    def test_same_table_name_in_two_schemas_and_databases_kept_apart(self):
        reg, _, _ = self.run_build()
        keys = {t["key"] for t in reg["tables"]}
        self.assertTrue({"ANA_SIT.MART.CLAIM", "ANA_SIT.STAGE.CLAIM", "pcms.core.member", "pcms.audit.member"} <= keys)
        self.assertEqual({d["label"] for d in reg["databases"]}, {"ANA", "PCMS", "OLD"})
        self.assertIn({"from": "pcms.audit.member.id", "to": "pcms.core.member.id", "source": "[E: query:CATALOG-FKEYS-SIT-PCMS]"},
                      reg["foreign_keys"])

    def test_schema_files_cite_their_lines(self):
        reg, _, _ = self.run_build()
        t = {x["key"]: x for x in reg["tables"]}
        self.assertIn("OLDDB.app.orders", t)
        self.assertEqual([c["name"] for c in t["OLDDB.app.orders"]["columns"]], ["order_id", "customer_id"])
        self.assertEqual(t["OLDDB.app.orders"]["columns"][0]["nullable"], "NO")
        self.assertIn({"from": "OLDDB.app.orders.customer_id", "to": "OLDDB.app.customer.id",
                       "source": '[E: legacy/db/schema.sql:7 "references app.customer(id)"]'}, reg["foreign_keys"])
        c = verify_kb.Checker(self.kb)
        for x in t.values():
            for s in [x["source"]] + [col["source"] for col in x["columns"]]:
                for k, v in verify_kb.TAG.findall(s):
                    self.assertIsNone(c.resolve(k, v), s)

    def test_each_environment_has_its_own_snapshot(self):
        _, _, load = self.run_build()
        self.assertEqual(load("environments/dev/CATALOG_SNAPSHOT.yaml")["environment"], "dev")
        self.assertEqual({t["key"] for t in load("environments/dev/CATALOG_SNAPSHOT.yaml")["tables"]}, {"ANA_DEV.MART.CLAIM"})

    def test_drift_matches_by_label_not_database_name(self):
        _, dr, _ = self.run_build()
        d = {(x["table"], x.get("column"), x["change"]) for x in dr["differences"]}
        self.assertIn(("ANA.MART.CLAIM", "ID", "type NUMBER in sit, VARCHAR in dev"), d)
        self.assertIn(("ANA.MART.CLAIM", "DEV_ONLY", "column only in dev"), d)
        self.assertIn(("ANA.MART.NEW_T", None, "table only in sit"), d)
        self.assertFalse(any(x[0] == "ANA.MART.CLAIM" and x[1] == "AMT" for x in d))
        for x in dr["differences"]:
            self.assertTrue(x["sources"])


if __name__ == "__main__":
    unittest.main()
