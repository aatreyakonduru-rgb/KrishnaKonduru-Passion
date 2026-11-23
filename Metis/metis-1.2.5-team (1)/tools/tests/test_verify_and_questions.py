import json
import os
import sys
import tempfile
import unittest

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import questions  # noqa: E402
import verify_kb  # noqa: E402


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.kb = os.path.join(self.tmp, "team-repo", "kb")
        write(os.path.join(self.tmp, "api-repo", "src", "OrderController.java"),
              'package x;\n@RestController\n@GetMapping("/orders")\npublic class OrderController {}\n')
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump({
            "product": {"name": "Sample"},
            "sources": {"workspace_root": self.tmp, "repos": {"api": "api-repo"}},
            "owners": {"roles": {"dev lead": "Pat Lee"}}}))
        write(os.path.join(self.kb, "_EVIDENCE", "queries", "DB-01-Q1.sql"), "SELECT 1")
        write(os.path.join(self.kb, "_EVIDENCE", "queries", "DB-01-Q1.json"), "[]")

    def run_check(self, text):
        write(os.path.join(self.kb, "doc.md"), text)
        return verify_kb.Checker(self.kb).run()["problems"]


class VerifyTests(Fixture):
    def test_good_tags_pass(self):
        probs = self.run_check('# Orders\n\n- GET /orders [E: api/src/OrderController.java:3 "/orders"]\n'
                               "- Table count is 1 [E: query:DB-01-Q1]\n")
        self.assertEqual(probs, [])

    def test_quote_must_match(self):
        probs = self.run_check('- GET /items [E: api/src/OrderController.java:3 "/items"]\n')
        self.assertIn("quoted text not found", probs[0]["problem"])

    def test_line_out_of_range(self):
        self.assertIn("outside", self.run_check("- x [E: api/src/OrderController.java:99]\n")[0]["problem"])

    def test_untagged_fact_fails(self):
        self.assertIn("no source tag", self.run_check("- Orders are shipped daily\n")[0]["problem"])

    def test_assumption_tag_not_allowed(self):
        probs = self.run_check("- Orders ship daily [A]\n")
        self.assertTrue(any("bare [A]" in p["problem"] for p in probs))

    def test_unknown_needs_registered_question(self):
        self.assertIn("not in the register", self.run_check("- Schedule [?: Q-0001]\n")[0]["problem"])

    def test_heading_tag_covers_section_and_open_questions_exempt(self):
        probs = self.run_check("## Endpoints [E: api/src/OrderController.java:1-4]\n\n- GET /orders\n\n"
                               "## Open questions\n\n- Who owns this?\n")
        self.assertEqual(probs, [])

    def test_table_header_not_a_fact(self):
        probs = self.run_check("| Path | Source |\n|---|---|\n| /orders | [E: api/src/OrderController.java:3] |\n")
        self.assertEqual(probs, [])

    def test_unknown_repo(self):
        self.assertIn("not listed", self.run_check("- x [E: web/src/a.ts:1]\n")[0]["problem"])


class QuestionTests(Fixture):
    def new(self, **kw):
        q = {"question": "Which job loads ORDERS?", "type": "etl-batch", "priority": "P1",
             "context": ["Table exists [E: query:DB-01-Q1]"], "blocks": ["kb/etl/ORDERS.md"]}
        q.update(kw)
        path = os.path.join(self.tmp, "new.yaml")
        write(path, yaml.safe_dump([q]))
        return path

    def test_add_assigns_id_role_and_dedupes(self):
        self.assertEqual(questions.cmd_add(self.kb, self.new()), 0)
        self.assertEqual(questions.cmd_add(self.kb, self.new()), 0)
        reg = questions.load(questions.reg_path(self.kb))
        self.assertEqual(len(reg["questions"]), 1)
        self.assertEqual(reg["questions"][0]["id"], "Q-0001")
        self.assertEqual(reg["questions"][0]["answer_role"], "etl lead")

    def test_possible_answer_needs_source(self):
        self.assertEqual(questions.cmd_add(self.kb, self.new(possible_answers=["Nightly job"])), 1)

    def test_answer_then_verify_accepts_answer_tag(self):
        questions.cmd_add(self.kb, self.new())
        ans = os.path.join(self.tmp, "a.json")
        write(ans, json.dumps([{"id": "Q-0001", "answer": "LOAD_ORDERS", "answered_by": "Pat Lee"}]))
        self.assertEqual(questions.cmd_answer(self.kb, ans), 0)
        self.assertEqual(self.run_check("- Loaded by LOAD_ORDERS [E: answer:Q-0001]\n"), [])

    def test_open_question_is_not_an_answer(self):
        questions.cmd_add(self.kb, self.new())
        self.assertIn("no recorded answer", self.run_check("- x [E: answer:Q-0001]\n")[0]["problem"])

    def test_html_renders(self):
        questions.cmd_add(self.kb, self.new())
        self.assertEqual(questions.cmd_html(self.kb), 0)
        page = open(os.path.join(self.kb, "_QUESTIONS", "VALIDATE_KB.html"), encoding="utf-8").read()
        self.assertIn("None found in sources", page)
        self.assertIn("Q-0001", page)


if __name__ == "__main__":
    unittest.main()


class GraphTests(Fixture):
    def test_only_sourced_links_kept(self):
        import gen_graph
        write(os.path.join(self.kb, "app", "api.links.yaml"), yaml.safe_dump({"links": [
            {"from": {"type": "endpoint", "name": "GET /orders"}, "rel": "handled by",
             "to": {"type": "class", "name": "OrderController"},
             "source": '[E: api/src/OrderController.java:3-4 "OrderController"]'},
            {"from": {"type": "endpoint", "name": "GET /orders"}, "rel": "reads",
             "to": {"type": "table", "name": "ORDERS"}},
            {"from": {"type": "endpoint", "name": "GET /orders"}, "rel": "reads",
             "to": {"type": "table", "name": "ITEMS"}, "source": "[E: api/src/OrderController.java:50]"}]}))
        nodes, edges, rejected, types, rels = gen_graph.build(self.kb)
        self.assertEqual(len(edges), 1)
        self.assertEqual(len(rejected), 2)
        self.assertEqual(gen_graph.main([self.kb]), 0)
        self.assertTrue(os.path.isfile(os.path.join(self.kb, "CROSS-LAYER", "LINK_GRAPH.yaml")))
