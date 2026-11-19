import os
import sys
import tempfile
import unittest

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import verifier  # noqa: E402


class VerifierTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.matrix = os.path.join(self.tmp, "matrix.yaml")
        with open(self.matrix, "w") as fh:
            yaml.safe_dump({"metadata": {}, "documented_chains": [
                {"chain_id": "DC-001", "change_impact": "HIGH"},
                {"chain_id": "DC-009", "change_impact": "LOW"}]}, fh)

    def test_risk_from_basis(self):
        self.assertEqual(verifier.risk("RISK=0/2 (Safe)", matrix=self.matrix)[0], "low")
        self.assertEqual(verifier.risk("SCOPE=2/2\n  RISK=1/2 (Managed)", matrix=self.matrix)[0], "medium")
        self.assertEqual(verifier.risk("RISK=2/2 (High)", matrix=self.matrix)[0], "high")

    def test_missing_score_is_low_with_reason(self):
        tier, why = verifier.risk("", matrix=self.matrix)
        self.assertEqual(tier, "low")
        self.assertIn("no RISK score", why)

    def test_high_chain_raises_tier(self):
        tier, why = verifier.risk("RISK=0/2", ["DC-001", "DC-009"], matrix=self.matrix)
        self.assertEqual(tier, "high")
        self.assertIn("DC-001 HIGH", why)
        self.assertEqual(verifier.risk("RISK=0/2", ["DC-009"], matrix=self.matrix)[0], "low")

    def test_gate(self):
        self.assertTrue(verifier.gate(self.tmp, "S1", "low")[0])
        ok, why = verifier.gate(self.tmp, "S1", "medium")
        self.assertFalse(ok)
        self.assertIn("no verifier verdict", why)
        verifier.record(self.tmp, "S1", "fail", ["AC-1 — a.py:3 — not handled"], today="2026-10-14")
        self.assertFalse(verifier.gate(self.tmp, "S1", "high")[0])
        data = verifier.record(self.tmp, "S1", "pass", today="2026-10-15")
        self.assertEqual(len(data["rounds"]), 2)
        self.assertTrue(verifier.gate(self.tmp, "S1", "high")[0])

    def test_record_rejects_other_verdicts(self):
        with self.assertRaises(ValueError):
            verifier.record(self.tmp, "S1", "maybe")

    def test_prompt_is_read_only(self):
        text = verifier.prompt("S1", "AC-1 x", "diff", "claims: []")
        self.assertIn("Read only", text)
        self.assertIn("VERDICT: pass", text)

    def test_start_dry_run_sends_nothing(self):
        res = verifier.start("S1", "AC", "claims: []", "diff")
        self.assertTrue(res["dry_run"])

    def test_metrics_counts_rework(self):
        verifier.record(self.tmp, "S2", "fail", ["x"], today="2026-10-14")
        verifier.record(self.tmp, "S2", "pass", today="2026-10-15")
        m = verifier.metrics(self.tmp)
        self.assertEqual(m["claims"], [])
        self.assertEqual(m["verifier"][0]["rework"], 1)
        self.assertEqual(m["verifier"][0]["verdict"], "pass")

    def graph(self):
        return verifier.confidence.link_graph.Graph({"nodes": {
            "file:a.py": {"type": "file", "name": "a.py"}, "file:b.py": {"type": "file", "name": "b.py"},
            "file:c.py": {"type": "file", "name": "c.py"}},
            "edges": [{"from": "file:a.py", "to": "file:b.py", "type": "imports", "source": "a.py:1"}]})

    def test_missed_impacts(self):
        files = {"ACME-1": ["a.py"], "ACME-9": ["b.py", "c.py"]}
        res = verifier.missed_impacts("ACME-1", ["ACME-9"], self.graph(), files_of=lambda k: files.get(k, []))
        self.assertEqual(res["predicted"], 2)
        self.assertEqual(res["defects"][0]["missed"], ["c.py"])
        self.assertEqual(res["missed"], 1)
        self.assertIn("result: 1 missed", verifier.missed_trace(res))

    def test_metrics_reads_linked_defects_for_jira_keys(self):
        verifier.record(self.tmp, "STORY-2", "pass", jira="ACME-1", today="2026-10-14")
        files = {"ACME-1": ["a.py"], "ACME-9": ["c.py"]}
        m = verifier.metrics(self.tmp, graph=self.graph(), defects_for=lambda keys: {k: ["ACME-9"] for k in keys},
                             files_of=lambda k: files.get(k, []))
        self.assertTrue(m["defects_read"])
        self.assertEqual(m["impacts"][0]["story"], "ACME-1")
        self.assertEqual(m["impacts"][0]["missed"], 1)
        self.assertFalse(verifier.metrics(self.tmp)["defects_read"])


if __name__ == "__main__":
    unittest.main()
