"""The sandbox: sample company, Jira and Confluence over files, the query language and the database."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "sandbox"))
import sandbox_db as db  # noqa: E402
import sandbox_jql as jql  # noqa: E402
import make_sandbox  # noqa: E402
import sandbox_server as server  # noqa: E402


class SandboxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="sandbox-test-")
        cls.folder = os.path.join(cls.dir, "sbx")
        cls.made = make_sandbox.make(cls.folder)
        cls.srv = server.serve(cls.folder, port=0)
        cls.url = "http://127.0.0.1:%d" % cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        shutil.rmtree(cls.dir, ignore_errors=True)

    def call(self, method, path, body=None, user="resource3"):
        req = urllib.request.Request(self.url + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": "Bearer " + user, "Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
        return json.loads(raw) if raw else None

    def search(self, query, fields="summary,status"):
        return self.call("GET", "/rest/api/2/search?" + urllib.parse.urlencode({"jql": query, "fields": fields}))

    def test_the_sample_company_is_complete(self):
        for name in ("jira.yaml", "confluence/index.yaml", "confluence/index.html", "sample.db", "roster.csv",
                     "sample-kb/MODULES/claims-intake/00_DISCOVERY_REPORT.md", "acme-claims/.git", "origin.git"):
            self.assertTrue(os.path.exists(os.path.join(self.folder, name)), name)
        data = server.load_yaml(os.path.join(self.folder, "jira.yaml"), {})
        types = [r["issuetype"] for r in data["issues"].values()]
        self.assertEqual((types.count("Epic"), types.count("Story"), types.count("Bug")), (3, 15, 6))
        self.assertGreaterEqual(types.count("Sub-task"), 30)
        self.assertEqual(len(data["users"]), 22)

    def test_signs_in_as_the_user_named_by_the_token(self):
        self.assertEqual(self.call("GET", "/rest/api/2/myself")["name"], "resource3")

    def test_the_team_queries_return_issues(self):
        sprint = self.search('project = ACME AND "IT Team" = Acme-Claims-Web AND sprint in openSprints() '
                             'AND issuetype in (Story, Bug, Task) ORDER BY rank ASC')
        self.assertGreater(sprint["total"], 5)
        self.assertEqual(sprint["warningMessages"], [])
        qa = self.search('project = ACME AND status in ("Ready for QA", "In QA") AND resolution = Unresolved')
        self.assertTrue(all(i["fields"]["status"]["name"] in ("Ready for QA", "In QA") for i in qa["issues"]))
        self.assertGreaterEqual(self.search("project = ACME AND updated >= -1000d")["total"], 54)

    def test_create_comment_and_move_a_ticket(self):
        key = self.call("POST", "/rest/api/2/issue", {"fields": {
            "project": {"key": "ACME"}, "issuetype": {"name": "Sub-task"}, "summary": "Question: which date?",
            "parent": {"key": "ACME-2"}, "labels": ["Question"], "assignee": {"name": "resource6"}}})["key"]
        self.call("POST", "/rest/api/2/issue/%s/comment" % key, {"body": "answered"})
        done = [t for t in self.call("GET", "/rest/api/2/issue/%s/transitions" % key)["transitions"]
                if t["name"] == "Done"][0]
        self.call("POST", "/rest/api/2/issue/%s/transitions" % key, {"transition": {"id": done["id"]}})
        f = self.call("GET", "/rest/api/2/issue/%s?fields=status,resolution,comment,parent" % key)["fields"]
        self.assertEqual((f["status"]["name"], f["resolution"]["name"], f["comment"]["total"], f["parent"]["key"]),
                         ("Done", "Done", 1, "ACME-2"))
        on_disk = server.load_yaml(os.path.join(self.folder, "jira.yaml"), {})
        self.assertIn(key, on_disk["issues"])

    def test_pages_are_created_found_and_versioned(self):
        page = self.call("POST", "/rest/api/content", {"type": "page", "title": "Test Page", "space": {"key": "ACMEWIKI"},
                                                       "ancestors": [{"id": "100000"}],
                                                       "body": {"storage": {"value": "<p>one</p>"}}})
        self.assertEqual(page["ancestors"][0]["id"], "100000")
        found = self.call("GET", "/rest/api/content?" + urllib.parse.urlencode({"title": "Test Page", "spaceKey": "ACMEWIKI"}))
        self.assertEqual(found["size"], 1)
        v2 = self.call("PUT", "/rest/api/content/%s" % page["id"], {"version": {"number": 2}, "title": "Test Page",
                                                                 "body": {"storage": {"value": "<p>two</p>"}}})
        self.assertEqual(v2["version"]["number"], 2)
        with self.assertRaises(urllib.error.HTTPError) as err:
            self.call("POST", "/rest/api/content", {"type": "page", "title": "Test Page", "space": {"key": "ACMEWIKI"}})
        self.assertEqual(err.exception.code, 400)
        with urllib.request.urlopen(self.url + "/pages/viewpage.action?pageId=" + page["id"]) as resp:
            self.assertIn(b"<p>two</p>", resp.read())

    def test_the_database_is_read_only(self):
        con = db.connect(self.folder)
        names = [t["table"] for t in db.tables(con)]
        self.assertEqual(names, sorted(make_sandbox.TABLES))
        cols, rows = db.query(con, "SELECT COUNT(*) FROM SDLC_CLAIM")
        self.assertEqual(rows[0][0], 300)
        with self.assertRaises(Exception):
            con.execute("DELETE FROM SDLC_CLAIM")

    def test_the_app_and_etl_have_the_layout_the_kb_generators_read(self):
        for name in ("acme-claims/api/apps/app/api.py", "acme-claims/api/apps/claims/api.py",
                     "acme-claims/web/src/Services/Utility/endpoints.ts", "acme-claims/web/src/app/claims/page.tsx",
                     "acme-claims/web/src/app/contracts/page.tsx", "acme-claims/web/src/app/payments/page.tsx",
                     "claims-etl/scripts/sql/claims_nightly_load.sql", "claims-etl/scripts/python/bank_file.py",
                     "claims-etl/.git"):
            self.assertTrue(os.path.exists(os.path.join(self.folder, name)), name)

    def run_app(self, code):
        """Run code in the sample app's api/ folder against a copy of sample.db."""
        api = os.path.join(self.folder, "acme-claims", "api")
        copy = os.path.join(tempfile.mkdtemp(dir=self.dir), "acme.db")
        shutil.copyfile(os.path.join(self.folder, "sample.db"), copy)
        r = subprocess.run([sys.executable, "-c", code], cwd=api, capture_output=True, text=True,
                           env=dict(os.environ, ACME_DB=copy, PYTHONPATH=api, DJANGO_SETTINGS_MODULE="acme.settings"))
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        return json.loads(r.stdout)

    def test_the_sample_app_queries_run_on_the_sample_database(self):
        for name in ("acme-claims/run.py", "acme-claims/api/manage.py", "acme-claims/api/requirements.txt",
                     "acme-claims/api/acme/settings.py", "acme-claims/web/next.config.js",
                     "acme-claims/web/src/app/layout.tsx", "acme-claims/.gitignore"):
            self.assertTrue(os.path.isfile(os.path.join(self.folder, name)), name)
        out = self.run_app("""
import json
from apps.claims import queries as c
from apps.contracts import queries as k
from apps.payments import queries as p
claims = c.rows(c.LIST_CLAIMS, member_id=1, status=None)
new = c.write(c.INSERT_CLAIM, member_id=1, provider_id=2, contract_id=3, service_date="2026-01-02", lob="Medicare")
c.write(c.INSERT_LINE, claim_id=new, proc_code="CPT99213", billed=120.0)
k.write(k.UPDATE_RATE, rate_pct=71.5, contract_id=4)
print(json.dumps({"claims": claims, "paid": c.rows(c.LIST_CLAIMS, member_id=1, status="paid"),
                  "new": c.one(c.ONE_CLAIM, claim_id=new), "rate": k.one(k.ONE_CONTRACT, contract_id=4)["rate_pct"],
                  "months": p.rows(p.MONTHLY, lob=None)[:1], "lines": p.rows(p.LINES, payment_id=1)}))
""")
        self.assertTrue(out["claims"])
        self.assertEqual(set(out["claims"][0]), {"claim_id", "service_date", "status", "lob", "provider_name"})
        self.assertTrue(all(x["status"] == "paid" for x in out["paid"]))
        self.assertEqual((out["new"]["claim_id"], out["new"]["status"]), (301, "pending"))
        self.assertEqual(out["rate"], 71.5)
        self.assertEqual(set(out["months"][0]), {"month", "lob", "total"})
        self.assertTrue(out["lines"])

    def test_the_sample_api_answers_through_django(self):
        has = subprocess.run([sys.executable, "-c", "import importlib.util as u, sys; "
                              "sys.exit(not (u.find_spec('django') and u.find_spec('ninja')))"], capture_output=True)
        if has.returncode:
            self.skipTest("Django and Django Ninja are not installed here (run.py setup installs them)")
        out = self.run_app("""
import json
import django
django.setup()
from django.test import Client
web = Client()
listed = web.get("/acme/api/claims/list", {"member_id": 1})
claim = {"member_id": 1, "provider_id": 2, "contract_id": 3, "service_date": "2026-01-02", "lob": "Medicare",
         "lines": [{"proc_code": "CPT99213", "billed": 120}]}
saved = web.post("/acme/api/claims/submit", claim, content_type="application/json")
from apps.db import write
write("UPDATE SDLC_MEMBER SET PLAN_CD = NULL WHERE MEMBER_ID = 2")
refused = web.post("/acme/api/claims/submit", dict(claim, member_id=2), content_type="application/json")
timeline = web.get("/acme/api/claims/timeline", {"claim_id": saved.json()["claim_id"]})
rate = web.put("/acme/api/contracts/rate?contract_id=1", {"rate_pct": 66}, content_type="application/json")
print(json.dumps({"list": listed.status_code, "saved": saved.json(), "refused": [refused.status_code, refused.json()],
                  "timeline": timeline.json(), "rate": rate.json()["rate_pct"],
                  "missing": web.get("/acme/api/contracts/list").status_code}))
""")
        self.assertEqual(out["list"], 200)
        self.assertEqual(out["saved"]["status"], "pending")
        self.assertEqual(out["refused"], [400, {"detail": "The member has no active plan"}])
        self.assertEqual(out["timeline"], [{"status": "submitted", "date": "2026-01-02"}])
        self.assertEqual((out["rate"], out["missing"]), (66, 200))

    def test_the_hand_kept_kb_is_there_for_intake_and_research(self):
        kb = os.path.join(self.folder, "sample-kb")
        for name in ("DB-DOCS/16_REQUIREMENT_ROUTING_MAP.yaml", "DB-DOCS/DB_TABLE_REGISTRY.yaml",
                     "DB-DOCS/13_DB_ENTITY_REGISTRY.yaml", "DB-DOCS/09_DB_SEMANTIC_LAYER.yaml",
                     "DB-DOCS/11_DB_DATA_LINEAGE.yaml", "CROSS-LAYER/CROSS_LAYER_IMPACT_MATRIX.CURATED.yaml",
                     "SHARED/DOMAIN_CONTEXT.md", "MODULES/claims-web/api/01_BUSINESS_REQUIREMENTS.md"):
            self.assertTrue(os.path.isfile(os.path.join(kb, name)), name)
        routing = server.load_yaml(os.path.join(kb, "DB-DOCS/16_REQUIREMENT_ROUTING_MAP.yaml"), {})
        ask = "expire a provider contract when its end date passes"
        hits = [e["id"] for e in routing["routing_entries"] if any(t in ask for t in e["triggers"])]
        self.assertEqual(hits, ["contract_rates"])
        registry = server.load_yaml(os.path.join(kb, "DB-DOCS/DB_TABLE_REGISTRY.yaml"), {})
        self.assertLessEqual(set(make_sandbox.TABLES), {t["name"] for t in registry["tables"]})


class SandboxKbBuildTests(unittest.TestCase):
    """The installed copy's generators build the rest of the KB from the sample app (needs the shared copy layout)."""

    def test_build_kb_fills_the_registries_matrix_ontology_and_link_graph(self):
        tools = os.path.dirname(HERE)
        if os.path.basename(os.path.dirname(tools)) != "framework":
            self.skipTest("runs in an installed copy, where the generators read api/, web/ and the KB folder")
        sys.path.insert(0, os.path.join(tools, "kbgen"))
        import gen_ontology
        import sample_app
        repo = gen_ontology.REPO
        tmp = tempfile.mkdtemp(prefix="sandbox-kb-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        folder = os.path.join(tmp, "sbx")
        made = make_sandbox.make(folder)
        target = made["repo"]
        framework = os.path.relpath(os.path.dirname(tools), repo)
        shutil.copytree(os.path.join(repo, framework), os.path.join(target, framework),
                        ignore=shutil.ignore_patterns("__pycache__", "context"))
        shutil.copytree(os.path.join(folder, "sample-kb"), os.path.join(target, gen_ontology.KB), dirs_exist_ok=True)
        steps = sample_app.build_kb(target, os.path.dirname(framework))
        self.assertEqual([s for s in steps if not s[1]], [])
        self.assertTrue(os.path.isfile(os.path.join(target, gen_ontology.OUT_DIR, "ACME_ONTOLOGY.yaml")))
        kb = os.path.join(target, gen_ontology.KB)
        for name in ("MODULES/claims-web/api/10_ENDPOINT_REGISTRY.yaml", "MODULES/claims-web/web/12_COMPONENT_REGISTRY.yaml",
                     "ETL/claims-etl/13_ETL_TABLE_IO_CONTRACT.yaml", "CROSS-LAYER/CROSS_LAYER_IMPACT_MATRIX.yaml"):
            self.assertTrue(os.path.isfile(os.path.join(kb, name)), name)
        lookup = os.path.join(target, framework, "tools", "ontology_lookup.py")
        r = subprocess.run([sys.executable, lookup, "context", "Claim", "--json"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        ctx = json.loads(r.stdout)
        self.assertIn("POST /api/claims/submit", ctx["endpoints"])
        self.assertIn("/claims/submit", ctx["screens"])


class JqlTests(unittest.TestCase):
    CTX = {"user": "me", "sprints": [{"id": 1, "state": "active", "name": "26.4.1"}],
           "user_of": lambda n: {"name": n, "displayName": n.title()}, "sprint": lambda s: {"id": s, "name": "26.4.1"},
           "category": lambda s: "done" if s == "Done" else "indeterminate",
           "custom": lambda f: "customfield_1" if f.strip('"').lower() == "it team" else None, "project_name": "Acme"}

    def issue(self, **kw):
        base = {"key": "ACME-7", "status": "In QA", "issuetype": "Story", "assignee": "me", "labels": ["Question"],
                "sprints": [1], "fields": {"customfield_1": "Web"}, "summary": "Upload claim documents"}
        base.update(kw)
        return base

    def test_clauses_and_logic(self):
        i = self.issue()
        for q in ('project = ACME AND assignee = currentUser()', 'status in ("In QA", Done) AND resolution = Unresolved',
                  '"IT Team" = Web AND sprint in openSprints()', 'labels in (Approval, Question)', 'summary ~ "claim upload"',
                  'NOT status = Done', '(type = Bug OR issuetype = Story) AND key in (ACME-7, ACME-8)',
                  'assignee is not EMPTY', 'unknownfield = x'):
            self.assertTrue(jql.match(q, i, dict(self.CTX)), q)
        for q in ('status = Done', 'assignee = other', 'labels is EMPTY', 'resolution is not EMPTY'):
            self.assertFalse(jql.match(q, i, dict(self.CTX)), q)

    def test_order_by(self):
        self.assertEqual(jql.order("project = X ORDER BY status ASC, updated DESC"),
                         [("status", False), ("updated", True)])

    def test_bad_query_is_an_error(self):
        with self.assertRaises(jql.JqlError):
            jql.parse('status in ("Done"')


if __name__ == "__main__":
    unittest.main()
