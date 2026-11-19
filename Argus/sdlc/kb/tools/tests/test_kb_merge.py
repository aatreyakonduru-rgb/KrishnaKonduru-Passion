"""Tests for kb_merge.py (merge a staged KB document into the live one) — stdlib unittest only."""
import os
import sys
import unittest

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)

import kb_merge  # noqa: E402

LIVE = """# OLD TITLE
## A0. Said above already
Runs `runserver` [E: Dockerfile:5]
The `runserver` process reads `Dockerfile` settings.
## A1. TECHNOLOGY STACK
| Part | Tool | Source |
|---|---|---|
| WSGI Server (Linux) | Gunicorn | setup.py |
## A2. Pool
Set `POOL_SIZE` to tune it. Debt at services/db.py:10\u201312
```
# not a heading
```
"""

STAGED = """---
version: 2.0
---
# Title: api
## A1. Technology stack
Runs `runserver` [E: Dockerfile:5]
## A9. What changed from the previous TRD
| Previous TRD said | Code today | Evidence |
|---|---|---|
| Gunicorn is the Linux server | The container runs `runserver` | [E: Dockerfile:5] |
| Pool size set by `POOL_SIZE`; debt at `db.py:10-12` | Fixed at 10 | [E: db.py:3] |
## Files read
`Dockerfile`
"""


class MergeTests(unittest.TestCase):
    def setUp(self):
        self.merged, self.report = kb_merge.merge(LIVE, STAGED)

    def test_staged_body_comes_first_unchanged(self):
        self.assertTrue(self.merged.startswith(STAGED.rstrip()))

    def test_lines_the_new_version_does_not_say_are_kept(self):
        kept = self.merged.split("## " + kb_merge.KEPT, 1)[1]
        for line in LIVE.splitlines()[5:]:
            if line.strip() and not line.startswith("#"):
                self.assertIn(line.rstrip(" |")[:30], kept)

    def test_lines_the_new_version_already_says_are_left_out(self):
        kept = self.merged.split("## " + kb_merge.KEPT, 1)[1]
        self.assertNotIn("Runs `runserver`", kept)
        self.assertNotIn("reads `Dockerfile` settings", kept)
        self.assertNotIn("A0. Said above already", kept)
        self.assertEqual(self.report["left_out"], 2)

    def test_kept_lines_are_labelled_unverified(self):
        self.assertIn("not re-checked against the source", self.merged)
        merged, _ = kb_merge.merge(LIVE, STAGED, archived_as="Archive/2026-01-02/x.md")
        self.assertIn("`Archive/2026-01-02/x.md`", merged)

    def test_table_header_is_kept_with_its_rows(self):
        self.assertIn("| Part | Tool | Source |\n|---|---|---|\n| WSGI", self.merged)

    def test_duplicate_copy_is_merged_too(self):
        merged, _ = kb_merge.merge(LIVE, STAGED, also=[("x/dup.md", "# Dup\nOnly the duplicate says `ZETA`.\n")])
        self.assertIn("**From the duplicate copy `x/dup.md`:**", merged)
        self.assertIn("Only the duplicate says `ZETA`.", merged)

    def test_headings_drop_two_levels_but_not_inside_code(self):
        self.assertIn("\n### OLD TITLE\n", self.merged)
        self.assertIn("\n#### A2. Pool\n", self.merged)
        self.assertIn("\n# not a heading\n", self.merged)

    def test_renamed_section_points_to_new_title(self):
        self.assertIn('under "A1. Technology stack"', self.merged)

    def test_contradicted_lines_are_marked(self):
        self.assertIn("| setup.py **Corrected:** the source today says: The container runs `runserver`. |", self.merged)
        self.assertIn("Debt at services/db.py:10\u201312 **Corrected:** the source today says: Fixed at 10.", self.merged)
        self.assertEqual(list(self.report["corrections"].values()), [1, 1])

    def test_exact_names_are_case_sensitive(self):
        merged, report = kb_merge.merge("Role is ROLE-ADMIN\n", STAGED.replace("`POOL_SIZE`", "`ROLE-Admin`"))
        self.assertNotIn("**Corrected:**", merged.split(kb_merge.KEPT, 1)[1])

    def test_merging_the_same_rebuild_again_changes_nothing(self):
        self.assertEqual(kb_merge.merge(self.merged, STAGED)[0], self.merged)

    def test_merging_a_later_rebuild_does_not_nest_kept_text(self):
        again, _ = kb_merge.merge(self.merged, STAGED.replace("version: 2.0", "version: 3.0"))
        self.assertEqual(again.count("## " + kb_merge.KEPT + "\n"), 1)
        self.assertEqual(again.count(kb_merge.intro(None)), 1)
        self.assertEqual(again.count("\n### OLD TITLE\n"), 1)
        self.assertNotIn("### Title: api", again)


class YamlMergeTests(unittest.TestCase):
    OLD = "metadata:\n  generated: '2026-01-01'\n  owner: Pat\nitems:\n- a\n- b\nold_only:\n  x: 1\n"
    NEW = "# built by a script\nmetadata:\n  generated: '2026-02-02'\nitems:\n- a\n- c\n"

    def test_only_old_keys_and_items_are_kept(self):
        import yaml
        merged, report = kb_merge.merge_yaml(self.OLD, self.NEW)
        self.assertTrue(merged.startswith(self.NEW.rstrip()))
        kept = yaml.safe_load(merged)[kb_merge.YAML_KEPT]
        self.assertEqual(kept["items"], ["b"])
        self.assertEqual(kept["old_only"], {"x": 1})
        self.assertEqual(kept["metadata"], {"owner": "Pat"})

    def test_nothing_only_old_means_the_new_text(self):
        self.assertEqual(kb_merge.merge_yaml("a: 1\n", "# s\na: 2\n")[0], "# s\na: 2\n")

    def test_merging_again_changes_nothing(self):
        merged, _ = kb_merge.merge_yaml(self.OLD, self.NEW)
        self.assertEqual(kb_merge.merge_yaml(merged, self.NEW)[0], merged)


if __name__ == "__main__":
    unittest.main()
