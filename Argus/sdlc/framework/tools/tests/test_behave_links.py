import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "kbgen"))
import behave_links  # noqa: E402
import gen_link_graph  # noqa: E402

FEATURE = """@Contract
Feature: Contract

  @ACME-1234 @Contract_01
  Scenario: Add a contract
    Given The user is on Acme Claims Home Page
    When user clicks on the Contract tile
    Then user checks "<BasicInfo>" in database
    And a step nobody wrote
"""
STEPS = """from behave import *
from features.Pages.Contract_Page import Contract_Page


@given("The user is on Acme Claims Home Page")
def home(context):
    pass


@when("user clicks on the Contract tile")
def tile(context):
    Contract_Page.open_contract(context)


@then('user checks "{info}" in database')
def db(context, info):
    run("GetContract")
"""
PAGE = """class Contract_Page:
    Contract_Tile = "//*[@href='acme/contractproviderconf']"
    Other_Tile = "//*[@href='acme/financeconf']"


def open_contract(context):
    click(context, Contract_Page.Contract_Tile)
"""


class BehaveLinksTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        for rel, text in {"features/FeatureFiles/Contract.feature": FEATURE, "features/steps/contract.py": STEPS,
                          "features/Pages/Contract_Page.py": PAGE,
                          "features/databaseQueries/q.txt": '{"GetContract": "select a from CL_CNTRCT c join P01.S.CL_PG p on 1=1"}'}.items():
            os.makedirs(os.path.dirname(os.path.join(root, rel)), exist_ok=True)
            with open(os.path.join(root, rel), "w") as fh:
                fh.write(text)

    def tearDown(self):
        self.tmp.cleanup()

    def _build(self):
        b = gen_link_graph.Builder()
        for r in ("/contractproviderconf", "/financeconf"):
            b.node("screen", r)
        meta = behave_links.link(b, dict(b.nodes), self.tmp.name)
        return b, meta

    def test_scenario_links_story_screen_and_tables_with_qa_sources(self):
        b, meta = self._build()
        tid = "test:ACME/claims-qa:features/FeatureFiles/Contract.feature@Contract_01"
        self.assertEqual(b.nodes[tid]["scenario"], "Add a contract")
        edges = {(a, k, c): s for (a, k, c), s in b.edges.items()}
        self.assertEqual(edges[("story:ACME-1234", "tested_by", tid)], "ACME/claims-qa:features/FeatureFiles/Contract.feature:5")
        self.assertEqual(edges[(tid, "covers", "screen:/contractproviderconf")], "ACME/claims-qa:features/Pages/Contract_Page.py:2")
        self.assertNotIn((tid, "covers", "screen:/financeconf"), edges)
        self.assertEqual(edges[(tid, "checks", "table:CL_CNTRCT")], "ACME/claims-qa:features/steps/contract.py:17")
        self.assertIn((tid, "checks", "table:CL_PG"), edges)
        self.assertEqual(meta["repo"], "ACME/claims-qa")
        self.assertEqual(meta["unmatched_steps"], 1)

    def test_absent_qa_repo_keeps_the_committed_links(self):
        b, _ = self._build()
        committed = {"metadata": {"qa_repo": {"repo": "ACME/claims-qa", "commit": "abc"}},
                     "nodes": dict(b.nodes),
                     "edges": [{"from": a, "type": k, "to": c, "source": s} for (a, k, c), s in b.edges.items()]
                     + [{"from": "file:x.py", "type": "covers", "to": "file:y.py", "source": "x.py:1"}]}
        self.assertIsNone(behave_links.link(gen_link_graph.Builder(), {}, os.path.join(self.tmp.name, "missing")))
        again = gen_link_graph.Builder()
        meta = behave_links.keep(again, committed)
        self.assertEqual(meta["commit"], "abc")
        self.assertEqual(set(again.edges), set(b.edges))
        self.assertEqual(again.nodes["test:ACME/claims-qa:features/FeatureFiles/Contract.feature@Contract_01"]["scenario"],
                         "Add a contract")


if __name__ == "__main__":
    unittest.main()
