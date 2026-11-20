"""kb_scan.py and sandbox_fallback.py tests: temp repos and injected environments, no network, no real secrets."""
import os
import socket
import subprocess
import sys
import tempfile
import unittest
import urllib.request

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)

import kb_scan  # noqa: E402
import sandbox_fallback as sf  # noqa: E402


def put(root, rel, text):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def sample_repo():
    root = tempfile.mkdtemp()
    put(root, "README.md", "# Shop\n\nA small shop API used to test the scanner.\n")
    put(root, "api/routes.py", 'from fastapi import APIRouter\nrouter = APIRouter()\n\n\n@router.get("/orders")\n'
                               'def list_orders():\n    return []\n\n\n@router.post("/orders")\n'
                               'async def create_order():\n    return {}\n')
    put(root, "api/flask_app.py", 'from flask import Flask\napp = Flask(__name__)\n\n@app.route("/ping", methods=["GET", "POST"])\n'
                                  'def ping():\n    return "ok"\n')
    put(root, "api/urls.py", 'from django.urls import path\nurlpatterns = [path("health/", views.health)]\n')
    put(root, "api/models.py", 'from django.db import models\n\nclass Order(models.Model):\n'
                               '    number = models.CharField(max_length=20)\n    owner = models.ForeignKey("User", on_delete=models.CASCADE)\n')
    put(root, "db/schema.sql", "CREATE TABLE ORDERS (\n  ID INTEGER PRIMARY KEY,\n  TOTAL NUMERIC(10,2),\n"
                               "  PRIMARY KEY (ID)\n);\nSELECT * FROM ORDER_LINE JOIN ORDERS ON 1=1;\n")
    put(root, "web/app/page.tsx", "export default function Home() { return null }\n")
    put(root, "web/app/orders/[id]/page.tsx", "export default function O() { return null }\n")
    put(root, "web/app/api/ping/route.ts", "export async function GET() { return Response.json({}) }\n")
    put(root, "requirements.txt", "fastapi>=0.100\nrequests==2.31.0\n# comment\n")
    put(root, "web/package.json", '{"name": "web", "scripts": {"dev": "next dev"}, "dependencies": {"next": "14.0.0"}}')
    put(root, "tests/test_orders.py", "def test_x():\n    pass\n")
    put(root, "node_modules/lib/index.js", 'app.get("/should-not-appear", () => {})\n')
    put(root, ".devin/rules/x.yaml", "framework: true\n")
    put(root, "sdlc/framework/tools/tool.py", '@router.get("/framework-route")\ndef f(): pass\n')
    put(root, "docs/knowledge-base/old.md", "@router.get('/kb-route')\n")
    return root


class Scan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = sample_repo()
        cls.files, cls.counts = kb_scan.build(cls.root, commit="abc1234", today="2026-01-02")

    def eps(self):
        files = kb_scan.list_files(self.root, "docs/knowledge-base")
        texts = {r: kb_scan.read(os.path.join(self.root, r)) for r in files}
        return kb_scan.endpoints(files, texts)

    def test_fastapi_routes_have_method_path_handler_and_line(self):
        found = {(e["method"], e["path"], e["handler"], e["line"]) for e in self.eps() if e["file"] == "api/routes.py"}
        self.assertEqual(found, {("GET", "/orders", "list_orders", 5), ("POST", "/orders", "create_order", 10)})

    def test_flask_route_reads_its_methods(self):
        e = [x for x in self.eps() if x["path"] == "/ping"][0]
        self.assertEqual((e["method"], e["framework"]), ("GET/POST", "flask"))

    def test_django_url_pattern(self):
        e = [x for x in self.eps() if x["file"] == "api/urls.py"][0]
        self.assertEqual((e["path"], e["handler"], e["framework"]), ("health/", "views.health", "django"))

    def test_next_route_handler_takes_its_path_from_the_folder(self):
        e = [x for x in self.eps() if x["framework"] == "next-route-handler"][0]
        self.assertEqual((e["method"], e["path"]), ("GET", "/api/ping"))

    def test_framework_kb_dependency_and_build_folders_are_skipped(self):
        paths = " ".join(e["path"] for e in self.eps())
        for bad in ("should-not-appear", "framework-route", "kb-route"):
            self.assertNotIn(bad, paths)

    def test_sql_table_and_columns_ignore_constraints(self):
        files = ["db/schema.sql"]
        tables, _, refs = kb_scan.data_model(files, {"db/schema.sql": kb_scan.read(os.path.join(self.root, "db/schema.sql"))})
        self.assertEqual(tables[0]["table"], "ORDERS")
        self.assertEqual([c["name"] for c in tables[0]["columns"]], ["ID", "TOTAL"])
        self.assertIn("ORDER_LINE", [r["table"] for r in refs])

    def test_django_model_fields(self):
        _, models, _ = kb_scan.data_model(["api/models.py"], {"api/models.py": kb_scan.read(os.path.join(self.root, "api/models.py"))})
        self.assertEqual(models[0]["model"], "Order")
        self.assertEqual([c["name"] for c in models[0]["columns"]], ["number", "owner"])

    def test_ui_routes_drop_groups_and_keep_dynamic_segments(self):
        routes = {r["route"] for r in kb_scan.ui_routes(kb_scan.list_files(self.root, "docs/knowledge-base"))}
        self.assertEqual(routes, {"/", "/orders/[id]"})

    def test_dependencies(self):
        files = ["requirements.txt", "web/package.json"]
        deps = kb_scan.dependencies(files, {f: kb_scan.read(os.path.join(self.root, f)) for f in files})
        py = [d for d in deps if d["kind"] == "python-requirements"][0]
        self.assertEqual([p["name"] for p in py["packages"]], ["fastapi", "requests"])
        self.assertEqual([d for d in deps if d["kind"] == "node-package"][0]["scripts"], ["dev"])

    def test_every_file_names_the_generator_and_commit(self):
        for name, text in self.files.items():
            self.assertIn("kb_scan.py", text, name)
        self.assertIn("abc1234", self.files["10_ENDPOINT_REGISTRY.yaml"])

    def test_counts(self):
        self.assertEqual((self.counts["endpoints"], self.counts["ui_routes"]), (5, 2))

    def test_written_yaml_parses_back_when_pyyaml_is_there(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML not installed")
        for name in ("10_ENDPOINT_REGISTRY.yaml", "20_DATA_MODEL.yaml", "30_DEPENDENCIES.yaml", "40_UI_ROUTES.yaml"):
            data = yaml.safe_load(self.files[name])
            self.assertEqual(data["generator"], "kb_scan.py 1", name)
        eps = yaml.safe_load(self.files["10_ENDPOINT_REGISTRY.yaml"])
        self.assertEqual(eps["count"], len(eps["endpoints"]))

    def test_a_value_that_looks_like_a_secret_is_never_copied(self):
        root = tempfile.mkdtemp()
        put(root, "app.py", 'API_KEY = "sk-live-0123456789abcdef0123456789abcdef"\n@app.get("/x")\ndef x(): pass\n')
        files, _ = kb_scan.build(root, commit="c", today="2026-01-02")
        for name, text in files.items():
            self.assertNotIn("0123456789abcdef", text, name)


class Run(unittest.TestCase):
    def setUp(self):
        self.root = sample_repo()

    def test_writes_under_repo_scan_and_second_run_changes_nothing(self):
        first = kb_scan.run(self.root, manifest=False)
        self.assertEqual(len(first["written"]), 6)
        self.assertTrue(os.path.isfile(os.path.join(self.root, "docs", "knowledge-base", "REPO-SCAN", "10_ENDPOINT_REGISTRY.yaml")))
        second = kb_scan.run(self.root, manifest=False)
        self.assertEqual((second["written"], len(second["unchanged"])), ([], 6))

    def test_check_reports_stale_after_the_code_changes_and_writes_nothing(self):
        kb_scan.run(self.root, manifest=False)
        put(self.root, "api/more.py", '@router.delete("/orders/{id}")\ndef remove(): pass\n')
        res = kb_scan.run(self.root, manifest=False, check=True)
        self.assertIn("10_ENDPOINT_REGISTRY.yaml", res["stale"])
        again = kb_scan.run(self.root, manifest=False, check=True)
        self.assertEqual(res["stale"], again["stale"])  # --check did not repair it

    def test_never_overwrites_a_file_it_did_not_write(self):
        folder = os.path.join(self.root, "docs", "knowledge-base", "REPO-SCAN")
        put(self.root, "docs/knowledge-base/REPO-SCAN/README.md", "# written by hand\n")
        res = kb_scan.run(self.root, manifest=False)
        self.assertEqual([s["file"] for s in res["skipped"]], ["README.md"])
        with open(os.path.join(folder, "README.md"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "# written by hand\n")

    def test_force_replaces_it(self):
        put(self.root, "docs/knowledge-base/REPO-SCAN/README.md", "# written by hand\n")
        res = kb_scan.run(self.root, manifest=False, force=True)
        self.assertIn("README.md", res["written"])

    def test_empty_repo_is_an_error_not_a_crash(self):
        res = kb_scan.run(tempfile.mkdtemp(), manifest=False)
        self.assertIn("no source files", res["error"])

    def test_cli_exit_codes(self):
        cmd = [sys.executable, os.path.join(TOOLS, "kb_scan.py"), "--root", self.root, "--no-manifest"]
        self.assertEqual(subprocess.run(cmd + ["--check"], capture_output=True).returncode, 1)  # nothing written yet
        self.assertEqual(subprocess.run(cmd, capture_output=True).returncode, 0)
        self.assertEqual(subprocess.run(cmd + ["--check"], capture_output=True).returncode, 0)

    def test_stage_folder_is_used_and_the_live_kb_is_untouched(self):
        res = kb_scan.run(self.root, stage="stage/scan", manifest=False)
        self.assertEqual(res["folder"], "stage/scan")
        self.assertFalse(os.path.exists(os.path.join(self.root, "docs", "knowledge-base", "REPO-SCAN")))


class Decide(unittest.TestCase):
    ENV = {}

    def d(self, env=None, runtime="local", key=False):
        return sf.decide(env if env is not None else {}, runtime, "ZEPHYR_JIRA_TOKEN", key)

    def test_nothing_configured_on_a_pc_uses_the_sandbox(self):
        self.assertTrue(self.d()["use"])

    def test_a_jira_token_means_no_sandbox_even_if_it_is_wrong(self):
        r = self.d({"ZEPHYR_JIRA_TOKEN": "not-a-real-token"})
        self.assertFalse(r["use"])
        self.assertIn("ZEPHYR_JIRA_TOKEN", r["why"])

    def test_a_devin_key_means_no_sandbox(self):
        self.assertFalse(self.d(key=True)["use"])

    def test_cloud_and_unknown_runtimes_never_fall_back(self):
        for runtime in ("cloud", "unknown"):
            r = self.d(runtime=runtime)
            self.assertFalse(r["use"], runtime)
            self.assertIn(runtime, r["why"])

    def test_opt_out_values(self):
        for v in ("off", "0", "false", "NO"):
            self.assertFalse(self.d({"SDLC_SANDBOX_FALLBACK": v})["use"], v)
        self.assertTrue(self.d({"SDLC_SANDBOX_FALLBACK": "on"})["use"])

    def test_an_address_someone_already_set_is_respected(self):
        for var in ("SDLC_SANDBOX_URL", "SDLC_JIRA_BASE"):
            self.assertFalse(self.d({var: "http://127.0.0.1:1"})["use"], var)

    def test_the_reason_never_contains_a_secret_value(self):
        r = self.d({"ZEPHYR_JIRA_TOKEN": "sekrit-value-123"})
        self.assertNotIn("sekrit-value-123", r["why"])


class Ensure(unittest.TestCase):
    def test_makes_the_sandbox_starts_its_server_and_answers(self):
        folder = os.path.join(tempfile.mkdtemp(), "sb")
        profile = {"jira": {"token_env": "ZEPHYR_JIRA_TOKEN"}, "confluence": {"token_env": "ZEPHYR_CONFLUENCE_TOKEN"}}
        info = sf.ensure(folder, root=tempfile.mkdtemp(), profile=profile, ports=[0])
        try:
            self.assertTrue(info["made"])
            self.assertTrue(os.path.isfile(os.path.join(folder, "jira.yaml")))
            self.assertEqual(info["env"]["SDLC_SANDBOX_URL"], info["url"])
            self.assertEqual(info["env"]["ZEPHYR_JIRA_TOKEN"], sf.SANDBOX_USER)
            req = urllib.request.Request(info["url"] + "/rest/api/2/myself", headers={"Authorization": "Bearer " + sf.SANDBOX_USER})
            with urllib.request.urlopen(req, timeout=10) as r:
                self.assertEqual(r.status, 200)
            self.assertNotIn("server", sf.public(info, "why"))
        finally:
            info["server"].shutdown()
            info["server"].server_close()

    def test_a_second_call_reuses_the_folder(self):
        folder = os.path.join(tempfile.mkdtemp(), "sb")
        profile = {"jira": {"token_env": "T"}}
        a = sf.ensure(folder, tempfile.mkdtemp(), profile, ports=[0])
        a["server"].shutdown()
        a["server"].server_close()
        b = sf.ensure(folder, tempfile.mkdtemp(), profile, ports=[0])
        try:
            self.assertFalse(b["made"])
        finally:
            b["server"].shutdown()
            b["server"].server_close()

    def test_a_folder_that_holds_other_files_is_refused_not_wiped(self):
        folder = tempfile.mkdtemp()
        put(folder, "precious.txt", "keep me")
        with self.assertRaises(RuntimeError):
            sf.ensure(folder, tempfile.mkdtemp(), {"jira": {}}, ports=[0])
        self.assertTrue(os.path.isfile(os.path.join(folder, "precious.txt")))

    def test_no_free_port_is_a_plain_error(self):
        folder = os.path.join(tempfile.mkdtemp(), "sb")
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        try:
            with self.assertRaises(RuntimeError) as ctx:
                sf.ensure(folder, tempfile.mkdtemp(), {"jira": {}}, ports=[s.getsockname()[1]])
            self.assertIn("no free port", str(ctx.exception))
        finally:
            s.close()


if __name__ == "__main__":
    unittest.main()
