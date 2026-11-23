import json
import os
import shutil
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import golden  # noqa: E402
import kb_coverage  # noqa: E402
import kb_trend as T  # noqa: E402
import questions  # noqa: E402

PROFILE = {"owners": {"kb_owner": "Ana Lead"}}


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


class Trend(unittest.TestCase):
    def setUp(self):
        self.kb = tempfile.mkdtemp()
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump(PROFILE))
        write(os.path.join(self.kb, "_EVIDENCE", "files", "r.txt"), "x\n")
        write(os.path.join(self.kb, "context", "a.md"), "# A\n\n- Fact. [E: file:r.txt]\n")
        write(os.path.join(self.kb, "context", "b.md"), "# B\n\n- Unsourced line.\n")

    def tearDown(self):
        shutil.rmtree(self.kb, ignore_errors=True)

    def test_no_file_means_empty(self):
        self.assertEqual(T.trend(self.kb), [])
        self.assertEqual(T.main(["show", self.kb]), 0)

    def test_record_appends_one_compact_line_per_build(self):
        s1 = T.record(self.kb)
        s2 = T.record(self.kb)
        with open(os.path.join(self.kb, ".metis", "trend.jsonl"), encoding="utf-8") as fh:
            lines = [json.loads(l) for l in fh if l.strip()]
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0], s1)
        self.assertEqual(s1["verify"]["problems"], 1)
        self.assertEqual(s1["verify"]["files"], 2)
        self.assertEqual(s1["pages"], 2)
        self.assertEqual(s1["questions"], {"open": 0, "p1": 0})
        self.assertNotIn("coverage", s2)
        self.assertNotIn("quality", s2)

    def test_reads_coverage_and_open_questions_and_golden(self):
        write(os.path.join(self.kb, "CROSS-LAYER", "COVERAGE.yaml"), yaml.safe_dump(
            {"objects": {"table": {"in_graph": 5, "named_in_no_page": 3, "names": []}, "job": {"in_graph": 2, "named_in_no_page": 1, "names": []}},
             "catalogue_tables": {"in_registry": 4, "named_in_no_page": 2, "names": []}, "rejected_links": [{"x": 1}],
             "impact_not_understood": {"relations": ["a", "b"], "node_types": []}}))
        questions.cmd_raise(self.kb, "What is X?", "business", "Pat Lee", "P1")
        questions.cmd_raise(self.kb, "What is Y?", "data", "Pat Lee", "P2")
        golden.add(self.kb, "Q?", ["context/a.md"], [], "Ana Lead")
        s = T.snapshot(self.kb)
        self.assertEqual(s["coverage"], {"objects_unnamed": 4, "objects_in_graph": 7, "tables_unnamed": 2, "rejected_links": 1,
                                         "relations_not_understood": 2})
        self.assertEqual(s["questions"], {"open": 2, "p1": 1})
        self.assertEqual(s["golden"], {"questions": 1, "static_problems": 0})

    def test_reads_quality_reports_when_present(self):
        write(os.path.join(self.kb, "CROSS-LAYER", "CONTRADICTIONS.yaml"), yaml.safe_dump({"pairs": 3}))
        write(os.path.join(self.kb, "CROSS-LAYER", "DUPLICATES.yaml"), yaml.safe_dump({"page_pairs": 2}))
        write(os.path.join(self.kb, "CROSS-LAYER", "LINK_CHECK.yaml"), yaml.safe_dump({"broken_links": 1, "orphan_pages": 4}))
        self.assertEqual(T.snapshot(self.kb)["quality"], {"contradictions": 3, "duplicate_pages": 2, "broken_links": 1, "orphan_pages": 4})

    def test_a_passed_verify_result_is_used_without_checking_again(self):
        s = T.snapshot(self.kb, {"files": 9, "tags": 8, "fact_lines": 7, "problems": []})
        self.assertEqual(s["verify"], {"files": 9, "tags": 8, "fact_lines": 7, "problems": 0})

    def test_trend_returns_last_n_oldest_first_and_skips_bad_lines(self):
        for i in range(5):
            T.record(self.kb, {"files": i, "tags": 0, "fact_lines": 0, "problems": []})
        with open(os.path.join(self.kb, ".metis", "trend.jsonl"), "a", encoding="utf-8") as fh:
            fh.write("not json\n[1]\n")
        got = T.trend(self.kb, 3)
        self.assertEqual([g["verify"]["files"] for g in got], [2, 3, 4])
        self.assertEqual(len(T.trend(self.kb, 0)), 5)

    def test_stores_no_text(self):
        questions.cmd_raise(self.kb, "Secret question text?", "business", "Pat Lee")
        T.record(self.kb)
        with open(os.path.join(self.kb, ".metis", "trend.jsonl"), encoding="utf-8") as fh:
            raw = fh.read()
        self.assertNotIn("Secret", raw)
        self.assertNotIn("Pat Lee", raw)

    def test_trend_file_is_not_a_page(self):
        T.record(self.kb)
        self.assertEqual(sorted(kb_coverage.page_files(self.kb)), ["context/a.md", "context/b.md"])


class Draw(unittest.TestCase):
    def test_series_and_change(self):
        snaps = [{"verify": {"problems": 5}, "pages": 3}, {"verify": {"problems": 2}, "pages": 4}, {"verify": {}}]
        s = T.series(snaps)
        self.assertEqual(s["Problems the source check finds"], [5, 2, None])
        self.assertEqual(s["Hand-written pages"], [3, 4, None])
        self.assertNotIn("Broken links", s)
        self.assertEqual(T.change([5, None, 2]), (5, 2))
        self.assertIsNone(T.change([5]))

    def test_sparkline_is_inline_svg_with_no_script(self):
        svg = T.sparkline([1, 3, 2, 5], label="Open <questions>")
        self.assertTrue(svg.startswith("<svg") and svg.endswith("</svg>"))
        self.assertIn("polyline", svg)
        self.assertIn("circle", svg)
        self.assertIn("Open &lt;questions&gt;", svg)
        self.assertNotIn("<script", svg)

    def test_sparkline_flat_single_empty_and_gap(self):
        self.assertIn("circle", T.sparkline([4, 4, 4]))
        self.assertIn("circle", T.sparkline([7]))
        self.assertNotIn("circle", T.sparkline([]))
        self.assertNotIn("circle", T.sparkline([None, None]))
        gap = T.sparkline([1, None, 2, 3])
        self.assertEqual(gap.count("<polyline"), 1)


if __name__ == "__main__":
    unittest.main()
