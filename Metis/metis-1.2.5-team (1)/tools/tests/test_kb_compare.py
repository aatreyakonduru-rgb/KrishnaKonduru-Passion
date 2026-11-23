"""Tests for kb_compare.py (staged rebuild against the live knowledge base) — stdlib unittest only."""
import os
import shutil
import sys
import tempfile
import unittest

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)

import kb_compare  # noqa: E402


def _force(func, path, _):
    # Windows keeps .git object files read-only, which blocks rmtree
    os.chmod(path, 0o700)
    func(path)


def write(root, rel, text):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


class CompareTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.live, self.stage = os.path.join(self.tmp, "live"), os.path.join(self.tmp, "stage")
        write(self.live, "DB/01.md", "# One\n## Scope\nOrders [E: q1]\nOwner is Sam [E: stated by Sam, 2026-01-02]\n")
        write(self.live, "DB/01.PATCHES.md", "- fix owner\n")
        write(self.live, "DB/02.md", "# Two\nsame\n")
        write(self.live, "DB/99_hand_made.md", "# Kept by hand\n")
        write(self.stage, "DB/01.md", "# One\nOrders [E: q1]\nOwner [?]\n")
        write(self.stage, "DB/02.md", "# Two\nsame\n")
        write(self.stage, "DB/03.md", "# Three\n[A] guess\n")

    def tearDown(self):
        shutil.rmtree(self.tmp, onerror=_force)

    def test_statuses_and_review_flags(self):
        r = kb_compare.compare(self.live, self.stage)
        f = r["files"]
        self.assertEqual((f["DB/01.md"]["status"], f["DB/02.md"]["status"], f["DB/03.md"]["status"]),
                         ("changed", "same", "new"))
        one = f["DB/01.md"]
        self.assertEqual(one["patches_sidecar"], "DB/01.PATCHES.md")
        self.assertEqual(len(one["hand_facts_dropped"]), 1)
        self.assertEqual(one["headings_gone"], ["Scope"])
        self.assertEqual((one["tags_live"]["unknown"], one["tags_staged"]["unknown"]), (0, 1))
        self.assertEqual(r["not_rebuilt"], ["DB/" + "99_hand_made.md"])
        self.assertTrue(kb_compare.needs_review(one))

    def test_yaml_comments_are_not_headings(self):
        write(self.live, "DB/12_registry.yaml", "# Generated: 2026-01-01\na: 1\n")
        write(self.stage, "DB/12_registry.yaml", "# Generated: 2026-02-01\na: 1\n")
        e = kb_compare.compare(self.live, self.stage)["files"]["DB/12_registry.yaml"]
        self.assertEqual((e["headings_gone"], e["headings_new"]), ([], []))
        self.assertFalse(kb_compare.needs_review(e))

    def test_renamed_sections_are_not_gone(self):
        write(self.live, "M/a.md", "# Report\n## Generated: 2025-07-28\n## 1. TECHNOLOGY STACK\nDjango `5.1`\n"
                                    "## 9. ASYNC / CONCURRENCY PATTERNS DETECTED\nasync def\n"
                                    "## 11. SECURITY \u2014 OPEN PATHS\n`/actuator/health` is open, ENABLE_AUTH\n")
        write(self.stage, "M/a.md", "# Report\n## 1. Technology stack\nDjango `5.1`\n"
                                     "## 9. Concurrency patterns\nasync def\n"
                                     "## 10. Flags\n`/actuator/health` has no auth\n")
        e = kb_compare.compare(self.live, self.stage)["files"]["M/a.md"]
        self.assertIn(("1. TECHNOLOGY STACK", "1. Technology stack"), e["headings_renamed"])
        self.assertIn(("9. ASYNC / CONCURRENCY PATTERNS DETECTED", "9. Concurrency patterns"), e["headings_renamed"])
        self.assertEqual(e["headings_gone"], ["11. SECURITY \u2014 OPEN PATHS"])
        real = [g for g in e["sections_gone"] if not g.get("title_line")]
        self.assertEqual(real[0]["terms_kept_pct"], 50)
        self.assertEqual(e["headings_new"], ["10. Flags"])
        self.assertEqual(e["title_lines_gone"], ["Generated: 2025-07-28"])
        report = kb_compare.markdown(kb_compare.compare(self.live, self.stage))
        self.assertIn("Section gone: 11. SECURITY \u2014 OPEN PATHS (50% of its 2 names", report)
        self.assertIn("1. TECHNOLOGY STACK -> 1. Technology stack", report)

    def test_mapping_and_report(self):
        write(self.live, "DB/11_contracts.yaml", "a: 1\n")
        write(self.stage, "DB/9B_contracts.yaml", "a: 2\n")
        r = kb_compare.compare(self.live, self.stage, {"DB/9B_contracts.yaml": "DB/11_contracts.yaml"})
        self.assertEqual(r["files"]["DB/9B_contracts.yaml"]["status"], "changed")
        self.assertNotIn("DB/" + "11_contracts.yaml", r["not_rebuilt"])
        md = kb_compare.markdown(r)
        self.assertIn("Dropped a hand-supplied fact", md)
        self.assertIn("`DB/03.md`", md)

    def test_keep_list(self):
        write(self.live, "DB/15_from_workbook.yaml", "a: 1\n")
        write(self.live, "DB/03.md", "# Three\nmade by hand\n")
        keep = [("DB/15_*", "the orders workbook"), ("DB/03.md", "hand-written")]
        r = kb_compare.compare(self.live, self.stage, keep=keep)
        self.assertIn({"file": "DB/" + "15_from_workbook.yaml", "source": "the orders workbook"}, r["kept"])
        self.assertNotIn("DB/" + "15_from_workbook.yaml", r["not_rebuilt"])
        self.assertIn("DB/" + "99_hand_made.md", r["not_rebuilt"])
        self.assertEqual(r["keep_conflicts"], ["DB/03.md"])
        md = kb_compare.markdown(r)
        self.assertIn("Don't replace", md)
        self.assertIn("the orders workbook", md)

    def test_cli_rejects_missing_folder(self):
        self.assertEqual(kb_compare.main([self.live, os.path.join(self.tmp, "nope")]), 2)


if __name__ == "__main__":
    unittest.main()
