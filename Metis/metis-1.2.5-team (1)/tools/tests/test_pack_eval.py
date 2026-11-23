import json
import os
import shutil
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import pack_eval  # noqa: E402


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


class PackEval(unittest.TestCase):
    def setUp(self):
        self.kb = tempfile.mkdtemp()
        nodes = [{"id": "table:APP.CLAIM_HDR", "type": "table", "name": "APP.CLAIM_HDR"}]
        write(os.path.join(self.kb, "CROSS-LAYER/LINK_GRAPH.yaml"), yaml.safe_dump({"nodes": nodes, "edges": []}))
        write(os.path.join(self.kb, "db/CLAIM_HDR.md"), "# CLAIM_HDR\n\nAPP.CLAIM_HDR holds one row per claim.\n")
        write(os.path.join(self.kb, "ops/Archival.md"), "# Archival\n\nOld rows move to cold storage after seven years of retention.\n")
        write(os.path.join(self.kb, "ops/Other.md"), "# Other\n\nPrinter toner is ordered monthly.\n")
        self.golden = [
            {"id": "G-0001", "question": "What does APP.CLAIM_HDR hold?", "cite": ["db/CLAIM_HDR.md"], "include": []},
            {"id": "G-0002", "question": "How long is retention before cold storage?", "cite": ["ops/Archival.md"], "include": []},
            {"id": "G-0003", "question": "A question with no page", "cite": [], "include": []}]
        write(os.path.join(self.kb, "_FEEDBACK/GOLDEN.yaml"), yaml.safe_dump({"golden": self.golden}))

    def tearDown(self):
        shutil.rmtree(self.kb)

    def test_scores_recall_precision_and_skips_questions_with_no_page(self):
        r = pack_eval.evaluate(self.kb, budget=6000, k=3)
        self.assertEqual(r["questions"], 2)
        self.assertEqual(r["skipped_no_cited_page"], ["G-0003"])
        self.assertEqual(r["mean"]["recall"], 1.0)
        self.assertEqual(r["mean"]["hit_at_k"], 1.0)
        self.assertEqual(pack_eval.verdict(r, 0.8, 0.0), [])

    def test_search_finds_what_names_only_cannot(self):
        r = pack_eval.evaluate(self.kb, budget=6000, k=3, compare=True)
        self.assertGreater(r["mean"]["recall"], r["mean_names_only"]["recall"])
        self.assertEqual(r["mean_names_only"]["recall"], 0.5)

    def test_score_one_counts_missing(self):
        s = pack_eval.score_one(["a.md", "b.md"], ["a.md", "c.md"], {"a.md": "full", "c.md": "headline"}, 1)
        self.assertEqual((s["recall"], s["precision"], s["hit_at_k"], s["full_tier"], s["missing"]), (0.5, 0.5, 1, 0.5, ["b.md"]))

    def test_gate_fails_below_threshold_and_below_baseline(self):
        r = pack_eval.evaluate(self.kb)
        self.assertTrue(pack_eval.verdict(r, 1.1, 0.0))
        r["mean"] = {"recall": 0.7, "precision": 1.0}
        self.assertTrue(pack_eval.verdict(r, 0.0, 0.0, {"mean": {"recall": 1.0, "precision": 1.0}}))
        self.assertEqual(pack_eval.verdict(r, 0.0, 0.0, {"mean": {"recall": 0.71, "precision": 1.0}}), [])

    def test_no_golden_questions_is_a_problem_not_a_pass(self):
        os.remove(os.path.join(self.kb, "_FEEDBACK/GOLDEN.yaml"))
        r = pack_eval.evaluate(self.kb)
        self.assertTrue(pack_eval.verdict(r, 0.0, 0.0))

    def test_cli_exit_code_and_baseline_file(self):
        base = os.path.join(self.kb, "base.json")
        self.assertEqual(pack_eval.main([self.kb, "--write-baseline", base]), 0)
        with open(base, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["mean"]["recall"], 1.0)
        self.assertEqual(pack_eval.main([self.kb, "--baseline", base]), 0)
        self.assertEqual(pack_eval.main([self.kb, "--min-recall", "1.1"]), 1)


if __name__ == "__main__":
    unittest.main()
