"""onboarding.py: reading path by team, approver or role, from pages, graph, glossary and open questions."""
import json
import os
import shutil
import sys
import tempfile
import unittest

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
for _p in (TOOLS, os.path.join(TOOLS, "ui")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import onboarding  # noqa: E402

PROFILE = {"owners": {"kb_owner": "Ana Lead"},
           "gate": {"teams": [{"name": "Data", "owns": ["data/*"], "approvers": ["Dee Data"]},
                              {"name": "Empty", "owns": ["nothing/*"], "approvers": ["Eve Empty"]}]}}
GRAPH = {"nodes": [{"id": "table:orders", "type": "table", "name": "orders"},
                   {"id": "table:payments", "type": "table", "name": "payments"},
                   {"id": "class:Id", "type": "class", "name": "Id"}],
         "edges": [{"from": "table:orders", "rel": "references", "to": "table:payments", "source": "[E: x]"},
                   {"from": "table:payments", "rel": "references", "to": "table:orders", "source": "[E: x]"}]}
QUESTIONS = {"questions": [
    {"id": "Q-0001", "question": "Who owns payments?", "priority": "P2", "answer_role": "data lead", "status": "open",
     "blocks": ["data/pay.md"]},
    {"id": "Q-0002", "question": "Closed one", "priority": "P2", "answer_role": "data lead", "status": "closed", "blocks": ["data/pay.md"]}]}


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


class Onboarding(unittest.TestCase):
    def setUp(self):
        self.kb = os.path.join(tempfile.mkdtemp(), "KB")
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump(PROFILE))
        write(os.path.join(self.kb, "CROSS-LAYER", "LINK_GRAPH.yaml"), yaml.safe_dump(GRAPH))
        write(os.path.join(self.kb, "_QUESTIONS", "VALIDATE_KB.yaml"), yaml.safe_dump(QUESTIONS))
        write(os.path.join(self.kb, "data", "pay.md"), "# Payments\n\nThe orders and payments tables link. [E: file:r.txt]\n")
        write(os.path.join(self.kb, "data", "ord.md"), "# Orders\n\nThe orders table. [E: file:r.txt]\n")
        write(os.path.join(self.kb, "app", "ui.md"), "# UI\n\nA screen. [E: file:r.txt]\n")
        write(os.path.join(self.kb, ".metis", "glossary.yaml"), yaml.safe_dump({"entries": [
            {"term": "Settlement", "meaning": "Money moves", "where_in_kb": ["data/pay.md"]},
            {"term": "Elsewhere", "meaning": "x", "where_in_kb": ["app/ui.md"]}]}))

    def tearDown(self):
        shutil.rmtree(os.path.dirname(self.kb), ignore_errors=True)

    def test_team_scope_orders_by_objects_named_and_ranks_objects_by_links(self):
        r = onboarding.build(self.kb, "Data")
        self.assertEqual(r["scope"], "team Data")
        self.assertEqual([p["path"] for p in r["read_in_order"]], ["data/pay.md", "data/ord.md"])
        self.assertEqual(r["read_in_order"][0]["objects"], 2)
        self.assertEqual({o["id"] for o in r["key_objects"]}, {"table:orders", "table:payments"})
        self.assertNotIn("class:Id", {o["id"] for o in r["key_objects"]})  # name under 3 characters is not matched
        self.assertEqual([t["term"] for t in r["glossary"]], ["Settlement"])
        self.assertEqual([q["id"] for q in r["open_questions"]], ["Q-0001"])

    def test_approver_name_resolves_to_team(self):
        self.assertEqual(onboarding.build(self.kb, "dee data")["scope"], "team Data")

    def test_role_scope_uses_pages_its_questions_block(self):
        r = onboarding.build(self.kb, "data lead")
        self.assertIn("role data lead", r["scope"])
        self.assertEqual([p["path"] for p in r["read_in_order"]], ["data/pay.md"])
        self.assertEqual(r["pages_in_scope"], 1)

    def test_unknown_name_falls_back_to_whole_kb_and_says_so(self):
        r = onboarding.build(self.kb, "Nobody")
        self.assertEqual(r["scope"], "whole KB")
        self.assertEqual(r["pages_in_scope"], 3)
        self.assertTrue(any("nothing in the profile" in n for n in r["notes"]))

    def test_team_with_no_pages_falls_back_with_note(self):
        r = onboarding.build(self.kb, "Empty")
        self.assertEqual(r["pages_in_scope"], 3)
        self.assertTrue(any("owns no page yet" in n for n in r["notes"]))

    def test_no_graph_is_noted_not_an_error(self):
        os.remove(os.path.join(self.kb, "CROSS-LAYER", "LINK_GRAPH.yaml"))
        r = onboarding.build(self.kb, "Data")
        self.assertEqual(r["key_objects"], [])
        self.assertTrue(any("no link graph" in n for n in r["notes"]))

    def test_labels_keep_a_reader_away_from_pages_above_clearance(self):
        write(os.path.join(self.kb, "data", "pay.md"),
              "---\nsensitivity: restricted\n---\n# Payments\n\nThe orders and payments tables link. [E: file:r.txt]\n")
        r = onboarding.build(self.kb, "Data", as_who="reader")
        self.assertNotIn("data/pay.md", [p["path"] for p in r["read_in_order"]])
        r = onboarding.build(self.kb, "Data", as_who="Ana Lead")
        self.assertIn("data/pay.md", [p["path"] for p in r["read_in_order"]])

    def test_writes_nothing_into_the_kb_and_markdown_has_no_evidence_tags(self):
        before = sorted(os.path.join(d, f) for d, _, fs in os.walk(self.kb) for f in fs)
        md = onboarding.to_markdown(onboarding.build(self.kb, "Data"))
        self.assertEqual(before, sorted(os.path.join(d, f) for d, _, fs in os.walk(self.kb) for f in fs))
        self.assertNotIn("[E:", md)
        self.assertIn("Q-0001", md)

    def test_cli_out_and_json(self):
        out = os.path.join(os.path.dirname(self.kb), "path.json")
        self.assertEqual(onboarding.main(["path", self.kb, "Data", "--json", "--out", out]), 0)
        with open(out, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["scope"], "team Data")
        self.assertEqual(onboarding.main(["path", os.path.join(self.kb, "nope"), "Data"]), 2)


if __name__ == "__main__":
    unittest.main()
