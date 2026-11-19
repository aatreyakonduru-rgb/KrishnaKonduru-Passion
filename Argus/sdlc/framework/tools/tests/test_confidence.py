"""Claims need a source, the graph picks the tests, picked tests must run, SQL keeps the registry's names."""
import os
import sys
import tempfile
import unittest

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import confidence  # noqa: E402
import link_graph  # noqa: E402


class ConfidenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.g = link_graph.Graph(link_graph.load())

    def setUp(self):
        self.dir = tempfile.mkdtemp(dir=confidence.REPO, prefix=".conf-test-")
        self.rel = os.path.relpath(self.dir, confidence.REPO)

    def tearDown(self):
        for f in os.listdir(self.dir):
            os.remove(os.path.join(self.dir, f))
        os.rmdir(self.dir)

    def write(self, name, text):
        with open(os.path.join(self.dir, name), "w") as fh:
            fh.write(text)
        return os.path.join(self.rel, name)

    @unittest.skip('checks the knowledge base or application folders of the team that built the copy')
    def test_claims_verified_and_unverified_and_mode(self):
        src = self.write("a.py", "x = 1\nq = 'select * from CL_PG_LOB'\n")
        path = self.write("claims.yaml", yaml.safe_dump({"claims": [
            {"id": "C1", "text": "job writes table", "evidence": ["graph:job:PG_syncup.sql -writes-> table:CL_PG_LOB"]},
            {"id": "C2", "text": "line reads it", "evidence": [src + ":2"], "expect": "cl_pg_lob"},
            {"id": "C3", "text": "wrong line", "evidence": [src + ":40"]},
            {"id": "C4", "text": "no source"},
            {"id": "C5", "text": "bad text", "evidence": [src + ":1"], "expect": "CL_NOPE"},
            {"id": "C6", "text": "kb file", "evidence": ["kb:" + confidence.CONFIG]}]}))
        res = confidence.claims(os.path.join(confidence.REPO, path), today="2000-01-01", graph=self.g)
        status = {r["id"]: r["status"] for r in res["rows"]}
        self.assertEqual(status, {"C1": "verified", "C2": "verified", "C3": "unverified", "C4": "unverified",
                                  "C5": "unverified", "C6": "verified"})
        line = confidence.claims_trace(res)[0]
        self.assertTrue(line.startswith("[SDLC] evidence claims.yaml — 6 claims: 3 verified, 3 unverified"))
        orig = confidence.config
        try:
            confidence.config = lambda: {"unverified_claims": {"warn_until": "2026-01-31"}}
            self.assertEqual(confidence.claim_mode("2026-01-31"), ("warn", "2026-01-31"))
            self.assertEqual(confidence.claim_mode("2026-02-01"), ("block", "2026-01-31"))
            res = confidence.claims(os.path.join(confidence.REPO, path), today="2026-02-01", graph=self.g)
            self.assertTrue(res["blocks"])
            self.assertTrue(confidence.claims_trace(res)[0].endswith("result: unverified, blocks SDLC_04"))
        finally:
            confidence.config = orig

    @unittest.skip('checks the knowledge base or application folders of the team that built the copy')
    def test_tests_selected_written_to_pack_and_required(self):
        pack = os.path.join(self.dir, "pack.yaml")
        with open(pack, "w") as fh:
            yaml.safe_dump({"req_id": "REQ-1", "checks": []}, fh)
        res = confidence.tests(files=["api/libs/consumers/heartbeat.py", "api/x/test_new.py"], pack=pack, graph=self.g)
        paths = [t["path"] for t in res["selected"]]
        self.assertIn("api/libs/consumers/test/test_heartbeat.py", paths)
        self.assertIn("api/x/test_new.py", paths)
        self.assertIn("selected", confidence.tests_trace(res)[0])
        req = confidence.required(pack)
        self.assertFalse(req["ok"])
        self.assertEqual(len(req["missing"]), 2)
        self.assertTrue(confidence.required(pack, ran=paths)["ok"])
        with open(pack) as fh:
            data = yaml.safe_load(fh)
        data["selected_tests"][0]["status"] = "failed"
        with open(pack, "w") as fh:
            yaml.safe_dump(data, fh)
        self.assertFalse(confidence.required(pack, ran=paths)["ok"])
        self.assertIn("result: failed", confidence.required_trace(confidence.required(pack))[0])

    def test_behave_scenarios_are_listed_for_qa_not_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            pack = os.path.join(tmp, "pack.yaml")
            rows = [{"id": "TST-1", "path": "ACME/claims-qa:features/FeatureFiles/A.feature@A_01", "why": "w",
                     "status": "not run", "run_by": "QA"}]
            with open(pack, "w") as fh:
                yaml.safe_dump({"selected_tests": rows}, fh)
            res = confidence.required(pack)
            self.assertTrue(res["ok"])
            self.assertEqual(len(res["for_qa"]), 1)
            self.assertIn("1 Behave scenarios for QA", confidence.required_trace(res)[0])
            rows[0]["status"] = "failed"
            with open(pack, "w") as fh:
                yaml.safe_dump({"selected_tests": rows}, fh)
            self.assertFalse(confidence.required(pack)["ok"])
        qa = "test:ACME/claims-qa:f.feature@T_01"
        g = link_graph.Graph({"nodes": {"file:p.tsx": {"type": "file", "name": "p.tsx"},
                                        "screen:/x": {"type": "screen", "name": "/x"},
                                        qa: {"type": "test", "name": qa[5:]}},
                              "edges": [{"from": "screen:/x", "type": "page", "to": "file:p.tsx", "source": "p.tsx"},
                                        {"from": qa, "type": "covers", "to": "screen:/x",
                                         "source": "ACME/claims-qa:features/Pages/P.py:3"}]})
        picked = confidence.select_tests(["p.tsx"], g)
        self.assertEqual([(t["path"], t.get("run_by")) for t in picked], [(qa[5:], "QA")])

    @unittest.skip('checks the knowledge base or application folders of the team that built the copy')
    def test_contract_flags_unknown_names_and_types(self):
        with open(os.path.join(confidence.REPO, confidence.REGISTRY)) as fh:
            reg = yaml.safe_load(fh)
        t = [x for x in reg["tables"] if x.get("columns") and any(c["type"].startswith("VARCHAR(") for c in x["columns"])][0]
        col = [c for c in t["columns"] if c["type"].startswith("VARCHAR(")][0]
        n = int(col["type"][8:-1])
        sql = self.write("q.sql", "SELECT %s FROM %s\nWHERE %s = '%s'\nJOIN CL_NO_SUCH_TABLE x ON 1=1\nSELECT %s AS MADE_UP_ALIAS FROM %s\n"
                         % (col["name"], t["name"], col["name"], "x" * (n + 1), col["name"], t["name"]))
        res = confidence.contract(files=[sql], graph=self.g)
        found = {(r["item"], r["status"]) for r in res["rows"]}
        self.assertIn((col["name"], "type mismatch"), found)
        self.assertIn(("CL_NO_SUCH_TABLE", "unknown table"), found)
        self.assertNotIn(("MADE_UP_ALIAS", "unknown column"), found)
        self.assertEqual(res["verdict"], "failed")
        lines = confidence.contract_trace(res)
        self.assertTrue(lines[-1].endswith("result: not run"))
        self.assertEqual(confidence.contract(base="no-such-ref-xyz", graph=self.g)["verdict"], "not run")

    def test_sdlc04_warns_then_blocks_on_claims(self):
        import gates
        orig_dir, orig_cfg = gates.session_store.session_dir, confidence.config
        try:
            gates.session_store.session_dir = lambda req, owner=None, create=False: self.dir
            confidence.config = lambda: {"unverified_claims": {"warn_until": "2026-01-31"}}
            self.assertIsNone(gates.claims_check("REQ-1", "SDLC_05_CODE_REVIEW", "STORY-1", "2026-03-01"))
            ev = gates.claims_check("REQ-1", "SDLC_04_ROUTING_APPROVAL", "STORY-1", "2026-01-01")
            self.assertTrue(ev["missing"])
            self.assertIn("warning until 2026-01-31", gates.evidence_line(ev))
            with self.assertRaises(SystemExit):
                gates.claims_check("REQ-1", "SDLC_04_ROUTING_APPROVAL", "STORY-1", "2026-03-01")
            self.write("STORY-1-claims.yaml", yaml.safe_dump({"claims": [{"id": "C1", "text": "x", "evidence": [confidence.CONFIG]}]}))
            ev = gates.claims_check("REQ-1", "SDLC_04_ROUTING_APPROVAL", "STORY-1", "2026-03-01")
            self.assertEqual((ev["verified"], ev["unverified"]), (1, 0))
            self.write("STORY-1-claims.yaml", yaml.safe_dump({"claims": [{"id": "C1", "text": "x"}]}))
            with self.assertRaises(SystemExit):
                gates.claims_check("REQ-1", "SDLC_04_ROUTING_APPROVAL", "STORY-1", "2026-03-01")
        finally:
            gates.session_store.session_dir, confidence.config = orig_dir, orig_cfg


if __name__ == "__main__":
    unittest.main()
