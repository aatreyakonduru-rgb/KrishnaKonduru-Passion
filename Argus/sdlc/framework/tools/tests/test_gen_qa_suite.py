import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "kbgen"))

import behave_links  # noqa: E402
import gen_ontology  # noqa: E402
import gen_qa_suite  # noqa: E402
from test_behave_links import FEATURE, PAGE, STEPS  # noqa: E402

OBJECTS = [{"id": "contract", "label": "Contract", "table": "CL_CNTRCT", "status": {"table": "CL_UI_CNTRCT_STTS"}},
           {"id": "run_request", "label": "Run Request", "table": "CL_RUN_RQST"}]
MATRIX = {"screens": {"/contractproviderconf": {}, "/financeconf": {}},
          "tables": {"CL_CNTRCT": {"api": [{"app": "x"}]}, "CL_RUN_RQST": {"api": [{"app": "y"}]}, "CL_ETL_ONLY": {}}}


class GenQaSuiteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        files = {"features/FeatureFiles/Contract.feature": FEATURE + '\n    Examples:\n      | BasicInfo |\n      | Basic_01 |\n',
                 "features/steps/contract.py": STEPS + '\n@then("nobody uses this")\ndef unused(context):\n    pass\n',
                 "features/Pages/Contract_Page.py": PAGE,
                 "features/databaseQueries/q.txt": '{"GetContract": "select a from CL_CNTRCT", "Runtime": "select b from CL_PG"}',
                 "TestData/Contract.json": '{"Basic_01": {}, "Basic_02": {}}',
                 "TestData/Contract_Basic_Field_Mapping.py": "M = {}\n"}
        for rel, text in files.items():
            os.makedirs(os.path.dirname(os.path.join(root, rel)), exist_ok=True)
            with open(os.path.join(root, rel), "w") as fh:
                fh.write(text)
        self.cov = gen_qa_suite.build(behave_links.scan(root), OBJECTS, MATRIX)

    def tearDown(self):
        self.tmp.cleanup()

    def test_coverage_comes_only_from_proven_links(self):
        objs = {o["id"]: o for o in self.cov["objects"]}
        self.assertEqual(objs["contract"]["scenarios"], 1)
        self.assertEqual(objs["contract"]["by_table"], {"CL_CNTRCT": 1})
        self.assertEqual(objs["run_request"]["scenarios"], 0)
        screens = {s["route"]: s["scenarios"] for s in self.cov["screens"]}
        self.assertEqual(screens, {"/contractproviderconf": 1, "/financeconf": 0})
        u = self.cov["untested"]
        self.assertEqual(u, {"objects": ["run_request"], "screens": ["/financeconf"], "app_tables": ["CL_RUN_RQST"]})

    def test_catalogues_and_gaps(self):
        sc = self.cov["scenarios"][0]
        self.assertEqual(sc["stories"], ["ACME-1234"])
        self.assertEqual(sc["data_sets"], ["Basic_01"])
        self.assertEqual(sc["unmatched_steps"], 1)
        lib = {s["pattern"]: s for s in self.cov["step_library"]}
        self.assertEqual(lib["The user is on Acme Claims Home Page"]["used_by_steps"], 1)
        self.assertEqual(lib["nobody uses this"]["used_by_steps"], 0)
        q = {x["key"]: x for x in self.cov["queries"]}
        self.assertEqual(q["GetContract"]["named_at"], "features/steps/contract.py:17")
        self.assertEqual(self.cov["gaps"]["queries_not_named_in_code"], ["Runtime"])
        self.assertEqual(self.cov["gaps"]["unmatched_steps"][0]["text"], "a step nobody wrote")
        self.assertEqual(self.cov["test_data"]["field_mappings"], ["TestData/Contract_Basic_Field_Mapping.py"])
        self.assertEqual(self.cov["metadata"]["counts"]["test_data_sets"], 2)
        self.assertIn("| Run Request | 0 | — |", gen_qa_suite.md(self.cov))

    def test_absent_repo_is_not_run_and_keeps_the_committed_file(self):
        out = os.path.join(self.tmp.name, "cov.yaml")
        result, detail = gen_qa_suite.run(check=True, repo=os.path.join(self.tmp.name, "missing"), out=out)
        self.assertEqual(result, "not run")
        self.assertFalse(os.path.exists(out))
        line = gen_qa_suite.trace_line(result, detail)
        self.assertTrue(line.startswith("[SDLC] qa 03_QA_SUITE_COVERAGE.yaml — ACME/claims-qa is not on this machine"))
        self.assertTrue(line.endswith("result: not run"))

    def test_ontology_copies_the_counts(self):
        objs = [dict(o) for o in OBJECTS]
        gen_ontology.add_tested_by(objs, self.cov)
        self.assertEqual(objs[0]["tested_by"]["scenarios"], 1)
        self.assertEqual(objs[1]["tested_by"]["scenarios"], 0)
        self.assertIn("QA-AUTOMATION-DERIVED/03_QA_SUITE_COVERAGE.yaml", objs[0]["tested_by"]["source"])
        self.assertIn("Not tested by any scenario", gen_ontology.qa_tab(self.cov))


if __name__ == "__main__":
    unittest.main()
