"""Tests for adr.py, qa_scenarios.py and gate_review.py — stdlib unittest only.

    python3 -m unittest sdlc/framework/tools/tests/test_adr_qa_review.py -v
"""
import datetime
import json
import os
import shutil
import sys
import tempfile
import textwrap
import unittest

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)

import adr  # noqa: E402
import gate_review  # noqa: E402
import metrics  # noqa: E402
import qa_scenarios  # noqa: E402

ROSTER = [{"name": "Resource 3", "email": "resource3@acme.example"}]


def fill(path, extra=""):
    text = open(path, encoding="utf-8").read()
    text = text.replace("What forced a decision, in two or three sentences. Tag every fact `[E: source]`, `[A]` or `[?]`.",
                        "The contract grid loads every row at once [E: web/src/app/grid.ts]." + extra)
    text = text.replace("What we will do, written so someone can check later whether the code still does it.",
                        "Page the grid on the server, 50 rows at a time.")
    text = text.replace("- {path, Confluence page id, PR or Jira key}", "- web/src/app/grid.ts")
    open(path, "w", encoding="utf-8").write(text)


class AdrTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)

    def test_new_numbers_and_slug(self):
        a = adr.create("Server-side paging for the grid", directory=self.dir, today=datetime.date(2026, 9, 29))
        b = adr.create("Second one", directory=self.dir)
        self.assertTrue(os.path.basename(a).startswith("ADR-0001-server-side-paging"))
        self.assertTrue(os.path.basename(b).startswith("ADR-0002-"))
        rec = adr.parse(a)
        self.assertEqual(rec["id"], "ADR-0001")
        self.assertEqual(rec["fields"]["Status"], "Proposed")
        self.assertEqual(rec["fields"]["Date"], "2026-09-29")

    def test_template_fails_check_until_filled(self):
        path = adr.create("Paging", directory=self.dir)
        _, problems = adr.check(path)
        self.assertTrue(any("template text" in p for p in problems))
        self.assertTrue(any("Sources read" in p for p in problems))
        fill(path)
        _, problems = adr.check(path)
        self.assertEqual(problems, [])

    def test_tag_lists_enforced(self):
        path = adr.create("Paging", directory=self.dir)
        fill(path, " Row counts may grow [A]. Peak volume is not known [?].")
        _, problems = adr.check(path)
        self.assertTrue(any("[A]" in p for p in problems))
        self.assertTrue(any("[?]" in p for p in problems))

    def test_accept_needs_roster_person(self):
        path = adr.create("Paging", directory=self.dir)
        fill(path)
        with self.assertRaises(SystemExit):
            adr.accept(path, "Somebody Else", directory=self.dir, roster=ROSTER)
        adr.accept(path, "Resource 3", directory=self.dir, roster=ROSTER)
        rec, problems = adr.check(path)
        self.assertEqual(rec["fields"]["Status"], "Accepted")
        self.assertIn("Resource 3", rec["fields"]["Deciders"])
        self.assertEqual(problems, [])

    def test_supersede_links_both_and_index(self):
        old = adr.create("Paging", directory=self.dir)
        new = adr.create("Paging v2", directory=self.dir)
        for p in (old, new):
            fill(p)
        adr.supersede("ADR-0001", "ADR-0002", directory=self.dir)
        self.assertEqual(adr.parse(old)["fields"]["Superseded by"], "ADR-0002")
        self.assertEqual(adr.parse(new)["fields"]["Supersedes"], "ADR-0001")
        self.assertEqual(adr.check(old)[1], [])
        index = adr.render_index(self.dir)
        self.assertIn("| [ADR-0001](%s) | Paging | Superseded |" % os.path.basename(old), index)


STEPS_PY = '''
from behave import step, Given, When

@Given("The user is on Acme Claims Home Page")
def home(context):
    pass

@step('user clicks on Add button for Contract')
def add(context):
    pass

@When('user enters "{field}" as "{value}"')
def enter(context, field, value):
    pass
'''

EXISTING_FEATURE = '''Feature: Contract
  @Contract_Information
  @ACME_Contract_01
  Scenario Outline: existing
    Given The user is on Acme Claims Home Page
    Examples:
      | ContractDetails    |
      | ContractDetails_01 |
'''


class QaScenariosTest(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.repo)
        for d in ("features/steps", "features/FeatureFiles/Acme Claims", "features/databaseQueries", "TestData"):
            os.makedirs(os.path.join(self.repo, d))
        open(os.path.join(self.repo, "features/steps/contract.py"), "w").write(STEPS_PY)
        open(os.path.join(self.repo, "features/FeatureFiles/Acme Claims/Contract.feature"), "w").write(EXISTING_FEATURE)
        json.dump({"GetContractInformation_UPLD": "SELECT CNTRCT_ID FROM CL_UI_CNTRCT_UPLD WHERE CNTRCT_ID = 'ReplaceContractID'"},
                  open(os.path.join(self.repo, "features/databaseQueries/ACME_ContractInformation.txt"), "w"))
        json.dump({"ContractDetails_01": {"name": "Test"}}, open(os.path.join(self.repo, "TestData/Contract_Information.json"), "w"))
        open(os.path.join(self.repo, "TestData/Contract_Parameters_Field_Mapping.py"), "w").write("X = 1\n")
        self.inv = qa_scenarios.inventory(self.repo)

    def test_inventory(self):
        self.assertEqual(len(self.inv["steps"]), 3)
        self.assertEqual(self.inv["queries"]["GetContractInformation_UPLD"]["tables"], ["CL_UI_CNTRCT_UPLD"])
        self.assertIn("ContractDetails_01", self.inv["test_data"])
        self.assertEqual(self.inv["field_mappings"], ["TestData/Contract_Parameters_Field_Mapping.py"])
        self.assertIn("ACME_Contract_01", self.inv["tags"])

    def test_parse_placeholders_match(self):
        self.assertIsNotNone(qa_scenarios.match_step('user enters "Contract Name" as "<name>"', self.inv["steps"]))
        self.assertIsNone(qa_scenarios.match_step("user deletes the contract", self.inv["steps"]))

    def test_next_tag(self):
        self.assertEqual(qa_scenarios.next_tag("ACME_Contract_", self.inv["tags"]), "ACME_Contract_02")
        self.assertEqual(qa_scenarios.next_tag("ACME_New_", self.inv["tags"]), "ACME_New_01")

    def test_check_draft(self):
        draft = textwrap.dedent('''
            Feature: Contract
              # covers: AC-1
              @Contract_Information
              @ACME_Contract_01
              Scenario Outline: add a contract
                Given The user is on Acme Claims Home Page
                And user clicks on Add button for Contract
                # NEW STEP
                Then user deletes the contract
                Examples:
                  | ContractDetails    | ContractInfo_UPLD           | Member    |
                  | ContractDetails_01 | GetContractInformation_UPLD | 123456789 |
        ''')
        report, problems = qa_scenarios.check_draft(draft, self.inv, ["AC-1", "AC-2"])
        joined = "\n".join(problems)
        self.assertIn("no step definition for 'user deletes the contract'", joined)
        self.assertIn("@ACME_Contract_01 already used", joined)
        self.assertNotIn("@Contract_Information", joined)  # group tags are shared on purpose
        self.assertIn("AC-2 is not covered", joined)
        self.assertIn("looks like long number", joined)
        self.assertEqual(report["coverage"]["AC-1"], ["add a contract"])
        self.assertEqual(sum(1 for s in report["steps"] if s["match"]), 2)

    def test_clean_draft_passes(self):
        draft = textwrap.dedent('''
            Feature: Contract
              # covers: AC-1
              @ACME_Contract_02
              Scenario Outline: add
                Given The user is on Acme Claims Home Page
                Examples:
                  | ContractDetails    |
                  | ContractDetails_01 |
        ''')
        _, problems = qa_scenarios.check_draft(draft, self.inv, ["AC-1"])
        self.assertEqual(problems, [])

    def test_unknown_data_key_flagged(self):
        draft = "Feature: x\n  @ACME_Contract_09\n  Scenario Outline: y\n    Given The user is on Acme Claims Home Page\n" \
                "    Examples:\n      | ContractDetails |\n      | ContractDetails_99 |\n"
        _, problems = qa_scenarios.check_draft(draft, self.inv, None)
        self.assertTrue(any("ContractDetails_99" in p for p in problems))


class GateReviewTest(unittest.TestCase):
    GATES = {"SDLC_07_ENV_PROMOTION_APPROVAL"}

    def task(self, **kw):
        t = {"id": "T1", "kind": "manual_work", "stage": "release", "task": "copy files",
             "evidence": ["[E: somewhere]"], "status": "open", "automation": "a script",
             "frequency": "daily", "minutes_each": "[?]", "done_by_today": "Dev", "candidate_owner": "[?]"}
        t.update(kw)
        return t

    def test_repo_register_is_valid(self):
        self.assertEqual(gate_review.validate(gate_review.load_register(), None), [])

    def test_human_decision_cannot_be_automated_or_skipped(self):
        bad = self.task(id="D1", kind="human_decision", status="automated", automation="skip this gate",
                        gate="SDLC_07_ENV_PROMOTION_APPROVAL")
        problems = gate_review.validate([bad], self.GATES)
        self.assertTrue(any("cannot be marked automated" in p for p in problems))
        self.assertTrue(any("may not retire" in p for p in problems))

    def test_evidence_must_be_tagged(self):
        problems = gate_review.validate([self.task(evidence=["someone said so"])], self.GATES)
        self.assertTrue(any("[E: source]" in p for p in problems))

    def test_unknown_size_stays_unknown_and_recorded_minutes_rank(self):
        tasks = [self.task(id="SLOW"), self.task(id="KNOWN", minutes_each=5, frequency="weekly")]
        rows = [{"at": "2026-09-29T10:00:00Z", "event": "manual_step", "task": "SLOW", "minutes": 30},
                {"at": "2026-09-29T11:00:00Z", "event": "manual_step", "task": "SLOW", "minutes": 20},
                {"at": "2026-09-29T12:00:00Z", "event": "manual_step", "task": "GHOST", "minutes": 5}]
        summ = metrics.summary(rows)
        self.assertEqual(summ["manual_steps"]["SLOW"], {"count": 2, "total_minutes": 50.0, "avg_minutes": 25.0})
        result = gate_review.review(tasks, summ, [])
        first = result["backlog"][0]
        self.assertEqual(first["task"]["id"], "SLOW")
        self.assertEqual(first["monthly_minutes"], 550)
        self.assertEqual(first["priority"], "high")
        self.assertEqual(result["backlog"][1]["monthly_minutes"], 20)
        self.assertEqual(result["unregistered"], ["GHOST"])
        no_data = gate_review.review([self.task(id="X")], metrics.summary([]), [])
        self.assertEqual(no_data["backlog"][0]["priority"], "size unknown")

    def test_slow_gate_is_kept(self):
        rows = [{"at": "2026-09-01T00:00:00Z", "event": "gate_presented", "requirement_id": "R",
                 "gate": "SDLC_07_ENV_PROMOTION_APPROVAL"},
                {"at": "2026-09-03T00:00:00Z", "event": "gate_decided", "requirement_id": "R",
                 "gate": "SDLC_07_ENV_PROMOTION_APPROVAL", "decision": "approved"}]
        result = gate_review.review([], metrics.summary(rows), [{"id": "SDLC_07_ENV_PROMOTION_APPROVAL"}])
        advice = result["gates"][0]["advice"]
        self.assertTrue(advice.startswith("Keep."))
        self.assertIn("automate the evidence", advice)
        report = gate_review.render(result, "m.jsonl")
        for word in ("retire", "remove the gate", "auto-approve"):
            self.assertNotIn(word, report.lower())


if __name__ == "__main__":
    unittest.main()
