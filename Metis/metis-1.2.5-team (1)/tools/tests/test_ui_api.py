"""The read-only JSON API (tools/ui/api.py) served by the real UI server: endpoints, labels, auth, and read-only behaviour."""
import base64
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
for _p in (TOOLS, os.path.join(TOOLS, "ui")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import api  # noqa: E402
import server  # noqa: E402

PROFILE = {"product": {"name": "Demo"}, "owners": {"kb_owner": "Ana Lead"},
           "gate": {"teams": [{"name": "Data", "owns": ["data/*"], "approvers": ["Dee Data"]}]}}
GRAPH = {"nodes": [{"id": "table:orders", "type": "table", "name": "orders"},
                   {"id": "table:payments", "type": "table", "name": "payments"}],
         "edges": [{"from": "table:orders", "rel": "references", "to": "table:payments",
                    "source": '[E: kb:data/orders.md "orders table"]', "origin": "stated"}]}
QUESTIONS = {"questions": [
    {"id": "Q-0001", "question": "Who owns payments?", "type": "data", "priority": "P2", "answer_role": "data lead",
     "status": "open", "blocks": ["data/orders.md"], "context": ["secret context [E: x]"]},
    {"id": "Q-0002", "question": "Closed one", "type": "data", "priority": "P3", "answer_role": "data lead", "status": "closed",
     "answer": "yes", "answered_by": "Dee", "blocks": []}]}


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def tree(root):
    return sorted((d, f) for d, _, fs in os.walk(root) for f in fs if os.sep + ".metis" not in d)


class Api(unittest.TestCase):
    password = None

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.kb = os.path.join(cls.tmp, "KB")
        write(os.path.join(cls.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump(PROFILE))
        write(os.path.join(cls.kb, "CROSS-LAYER", "LINK_GRAPH.yaml"), yaml.safe_dump(GRAPH))
        write(os.path.join(cls.kb, "_QUESTIONS", "VALIDATE_KB.yaml"), yaml.safe_dump(QUESTIONS))
        write(os.path.join(cls.kb, "_EVIDENCE", "files", "r.txt"), "orders table\n")
        write(os.path.join(cls.kb, "data", "orders.md"), '# Orders\n\nThe orders table feeds payments. [E: file:r.txt "orders table"]\n')
        write(os.path.join(cls.kb, "data", "SECRETS.md"), "# Secrets\n\npassword: hunter2hunter2 for orders [E: file:r.txt]\n")
        write(os.path.join(cls.kb, ".metis", "glossary.yaml"), yaml.safe_dump({"entries": [
            {"term": "Order", "synonyms": ["purchase"], "meaning": "A purchase", "where_in_kb": ["data/orders.md"]}]}))
        cls.srv = server.serve(cls.kb, host="127.0.0.1", port=0, password=cls.password)
        cls.base = "http://127.0.0.1:%d" % cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def get(self, path, headers=None, method="GET"):
        req = urllib.request.Request(self.base + path, headers=headers or {}, method=method, data=b"" if method == "POST" else None)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.headers.get("Content-Type"), r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            try:
                return e.code, e.headers.get("Content-Type"), e.read().decode("utf-8")
            finally:
                e.close()

    def j(self, path, **kw):
        code, _, body = self.get(path, **kw)
        return code, json.loads(body)


class Endpoints(Api):
    def test_search_returns_source_tag_and_ignores_blocked_pages(self):
        code, d = self.j("/api/v1/search?q=orders+table")
        self.assertEqual(code, 200)
        self.assertEqual(d["results"][0]["path"], "data/orders.md")
        self.assertIn('[E: file:r.txt "orders table"]', d["results"][0]["snippet"])
        self.assertNotIn("data/SECRETS.md", [r["path"] for r in d["results"]])

    def test_search_needs_q_and_bounds_limit(self):
        self.assertEqual(self.j("/api/v1/search")[0], 400)
        self.assertEqual(self.j("/api/v1/search?q=orders&limit=abc")[0], 400)
        self.assertEqual(self.j("/api/v1/search?q=orders&limit=9999")[0], 200)

    def test_page(self):
        code, d = self.j("/api/v1/page?path=data/orders.md")
        self.assertEqual((code, d["title"], d["withheld_lines"]), (200, "Orders", 0))
        self.assertIn("[E: file:r.txt", d["text"])
        self.assertEqual(self.j("/api/v1/page?path=data/SECRETS.md")[0], 404)         # blocked by sensitive.py
        self.assertEqual(self.j("/api/v1/page?path=..%2F..%2Fetc%2Fpasswd")[0], 404)  # not a KB page
        self.assertEqual(self.j("/api/v1/page?path=.metis/kb-profile.yaml")[0], 404)
        self.assertEqual(self.j("/api/v1/page")[0], 400)

    def test_impact_down_and_up(self):
        code, d = self.j("/api/v1/impact?node=table:payments")
        self.assertEqual(code, 200)
        self.assertEqual([r["moves"] for r in d["results"]], ["table:orders"])
        self.assertEqual(d["results"][0]["via"][0]["source"], '[E: kb:data/orders.md "orders table"]')
        code, d = self.j("/api/v1/impact?node=table:orders&direction=up")
        self.assertEqual((code, [r["changes"] for r in d["results"]]), (200, ["table:payments"]))
        self.assertEqual(self.j("/api/v1/impact?node=table:nope")[0], 404)
        self.assertEqual(self.j("/api/v1/impact?node=table:orders&direction=sideways")[0], 400)
        self.assertEqual(self.j("/api/v1/impact")[0], 400)

    def test_questions_filter_and_no_context_lines(self):
        code, d = self.j("/api/v1/questions?status=open")
        self.assertEqual([q["id"] for q in d["questions"]], ["Q-0001"])
        self.assertNotIn("context", d["questions"][0])
        self.assertEqual(self.j("/api/v1/questions")[1]["total"], 2)
        self.assertEqual(self.j("/api/v1/questions?status=bogus")[0], 400)

    def test_glossary_and_onboarding(self):
        self.assertEqual(self.j("/api/v1/glossary")[1]["entries"][0]["term"], "Order")
        code, d = self.j("/api/v1/onboarding?for=Data")
        self.assertEqual((code, d["scope"]), (200, "team Data"))
        self.assertEqual(self.j("/api/v1/onboarding")[0], 400)

    def test_openapi_and_llms_txt(self):
        code, d = self.j("/openapi.json")
        self.assertEqual((code, d["openapi"]), (200, "3.0.3"))
        self.assertEqual(set(api.ENDPOINTS) | {"/llms.txt"}, set(d["paths"]))
        self.assertNotIn("security", d)
        code, ctype, body = self.get("/llms.txt")
        self.assertEqual(code, 200)
        self.assertTrue(ctype.startswith("text/plain"))
        self.assertIn("# Demo knowledge base", body)
        self.assertIn("/api/v1/page?path=data/orders.md", body)
        self.assertNotIn("SECRETS", body)

    def test_unknown_api_path_post_and_existing_routes(self):
        self.assertEqual(self.j("/api/v1/nope")[0], 404)
        self.assertEqual(self.get("/api/v1/search?q=x", method="POST")[0], 405)
        self.assertEqual(self.get("/health")[2], "ok")

    def test_read_only(self):
        before = tree(self.kb)
        for p in ("/api/v1/search?q=orders", "/api/v1/page?path=data/orders.md", "/api/v1/questions", "/api/v1/glossary",
                  "/api/v1/onboarding?for=Data", "/openapi.json", "/llms.txt"):
            self.get(p)
        self.assertEqual(before, tree(self.kb))


class Handle(unittest.TestCase):
    """handle() called directly: non-GET, and labelled lines stay out for a caller who may not see them."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.kb = os.path.join(self.tmp, "KB")
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump(PROFILE))
        write(os.path.join(self.kb, "_EVIDENCE", "files", "r.txt"), "x\n")
        write(os.path.join(self.kb, "data", "open.md"), '---\nsensitivity: public\n---\n# Open\n\nPublic zebra fact. [E: file:r.txt "x"]\n')
        write(os.path.join(self.kb, "data", "locked.md"),
              '---\nsensitivity: restricted\n---\n# Locked\n\nVault zebra rotation. [E: file:r.txt "x"]\n')
        write(os.path.join(self.kb, "_QUESTIONS", "VALIDATE_KB.yaml"), yaml.safe_dump({"questions": [
            {"id": "Q-0001", "question": "About the vault?", "type": "data", "priority": "P2", "answer_role": "x", "status": "open",
             "blocks": ["data/locked.md"]}]}))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def call(self, path, user, query=None, method="GET"):
        code, body, _ = api.handle(self.kb, user, method, path, query or {})
        return code, body

    def test_not_an_api_path_is_left_to_the_server(self):
        self.assertIsNone(api.handle(self.kb, "", "GET", "/files", {}))

    def test_only_get(self):
        self.assertEqual(self.call("/api/v1/search", "", {"q": "zebra"}, method="POST")[0], 405)
        self.assertEqual(self.call("/openapi.json", "", method="DELETE")[0], 405)

    def test_page_search_index_and_questions_follow_clearance(self):
        self.assertEqual(self.call("/api/v1/page", "", {"path": "data/locked.md"})[0], 404)
        self.assertEqual(self.call("/api/v1/page", "Ana Lead", {"path": "data/locked.md"})[0], 200)
        found = [r["path"] for r in json.loads(self.call("/api/v1/search", "", {"q": "zebra"})[1])["results"]]
        self.assertEqual(found, ["data/open.md"])
        found = [r["path"] for r in json.loads(self.call("/api/v1/search", "Ana Lead", {"q": "zebra"})[1])["results"]]
        self.assertIn("data/locked.md", found)
        self.assertNotIn("locked.md", self.call("/llms.txt", "")[1])
        self.assertIn("locked.md", self.call("/llms.txt", "Ana Lead")[1])
        d = json.loads(self.call("/api/v1/questions", "")[1])
        self.assertEqual((d["total"], d["left_out"]), (0, 1))
        self.assertEqual(json.loads(self.call("/api/v1/questions", "Ana Lead")[1])["total"], 1)


class Secured(Api):
    password = "s3cret"

    def basic(self, pw):
        return {"Authorization": "Basic " + base64.b64encode(("any:" + pw).encode()).decode()}

    def test_every_api_path_needs_the_ui_password(self):
        for p in ("/api/v1/search?q=orders", "/api/v1/page?path=data/orders.md", "/openapi.json", "/llms.txt"):
            self.assertEqual(self.get(p)[0], 401, p)
            self.assertEqual(self.get(p, self.basic("wrong"))[0], 401, p)
            self.assertEqual(self.get(p, self.basic("s3cret"))[0], 200, p)

    def test_openapi_declares_basic_auth_only_when_a_password_is_set(self):
        d = json.loads(self.get("/openapi.json", self.basic("s3cret"))[2])
        self.assertEqual(d["security"], [{"basic": []}])


if __name__ == "__main__":
    unittest.main()
