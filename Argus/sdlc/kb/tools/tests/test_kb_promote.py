import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import kb_promote  # noqa: E402


def put(root, rel, text):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


def get(root, rel):
    with open(os.path.join(root, rel)) as fh:
        return fh.read()


class PromoteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.live = os.path.join(self.tmp, "kb")
        self.stage = os.path.join(self.tmp, "stage")
        put(self.live, "DB/a.md", "old a")
        put(self.stage, "DB/a.md", "new a")
        put(self.stage, "DB/b.md", "new b")
        put(self.stage, "DB/9B.yaml", "new contracts")
        put(self.live, "DB/11.yaml", "old contracts")

    def test_replaces_and_archives(self):
        kb_promote.promote(self.live, self.stage, ["DB/a.md", "DB/b.md"], "Pat", today="2026-01-02")
        self.assertEqual(get(self.live, "DB/a.md"), "new a")
        self.assertEqual(get(self.live, "DB/b.md"), "new b")
        self.assertEqual(get(self.live, "Archive/2026-01-02/DB/a.md"), "old a")
        self.assertFalse(os.path.exists(os.path.join(self.live, "Archive/2026-01-02/DB/b.md")))
        log = get(self.live, "Archive/PROMOTIONS.log")
        self.assertIn("Pat\tDB/a.md", log)
        self.assertIn("(new)", log)
        self.assertEqual(get(self.stage, "DB/a.md"), "new a")

    def test_map_writes_live_name(self):
        kb_promote.promote(self.live, self.stage, ["DB/9B.yaml"], "Pat", {"DB/9B.yaml": "DB/11.yaml"},
                           today="2026-01-02")
        self.assertEqual(get(self.live, "DB/11.yaml"), "new contracts")
        self.assertFalse(os.path.exists(os.path.join(self.live, "DB/9B.yaml")))

    def test_needs_approver_and_files(self):
        with self.assertRaises(ValueError):
            kb_promote.promote(self.live, self.stage, ["DB/a.md"], " ")
        with self.assertRaises(ValueError):
            kb_promote.promote(self.live, self.stage, [], "Pat")
        with self.assertRaises(ValueError):
            kb_promote.promote(self.live, self.stage, ["DB/missing.md"], "Pat")
        self.assertEqual(get(self.live, "DB/a.md"), "old a")

    def test_keep_list_is_never_replaced(self):
        with self.assertRaises(ValueError):
            kb_promote.promote(self.live, self.stage, ["DB/a.md"], "Pat", keep=[("DB/a*", "workbook")])
        self.assertEqual(get(self.live, "DB/a.md"), "old a")

    def test_merge_keeps_old_lines_and_archives_the_old_copy(self):
        put(self.live, "DB/a.md", "# A\nOnly the old copy says `OLDNAME`.\n")
        put(self.stage, "DB/a.md", "# A\nNew text [E: x:1]\n")
        kb_promote.promote(self.live, self.stage, ["DB/a.md"], "Pat", today="2026-01-02", merge=True)
        text = get(self.live, "DB/a.md")
        self.assertTrue(text.startswith("# A\nNew text [E: x:1]"))
        self.assertIn("Only the old copy says `OLDNAME`.", text)
        self.assertIn("`Archive/2026-01-02/DB/a.md`", text)
        self.assertEqual(get(self.live, "Archive/2026-01-02/DB/a.md"), "# A\nOnly the old copy says `OLDNAME`.\n")

    def test_merge_folds_in_a_duplicate_and_moves_it_to_the_archive(self):
        put(self.live, "DB/a_dup.md", "# Dup\nOnly the duplicate says `DUPNAME`.\n")
        put(self.live, "DB/a_dup.PATCHES.md", "patches")
        kb_promote.promote(self.live, self.stage, ["DB/a.md"], "Pat", {"DB/a.md": ["DB/a.md", "DB/a_dup.md"]},
                           today="2026-01-02", merge=True)
        self.assertIn("Only the duplicate says `DUPNAME`.", get(self.live, "DB/a.md"))
        self.assertFalse(os.path.exists(os.path.join(self.live, "DB/a_dup.md")))
        self.assertEqual(get(self.live, "Archive/2026-01-02/DB/a_dup.md"), "# Dup\nOnly the duplicate says `DUPNAME`.\n")
        self.assertEqual(get(self.live, "Archive/2026-01-02/DB/a_dup.PATCHES.md"), "patches")
        self.assertIn("duplicate merged into DB/a.md", get(self.live, "Archive/PROMOTIONS.log"))

    def test_merge_reads_windows_1252_files(self):
        with open(os.path.join(self.live, "DB/a.md"), "wb") as fh:
            fh.write("# A\nOld \u2014 only here `OLDNAME`.\n".encode("cp1252"))
        kb_promote.promote(self.live, self.stage, ["DB/a.md"], "Pat", today="2026-01-02", merge=True)
        self.assertIn("Old \u2014 only here `OLDNAME`.", get(self.live, "DB/a.md"))

    def test_refuses_to_overwrite_an_archived_copy(self):
        put(self.live, "Archive/2026-01-02/DB/a.md", "earlier archive")
        with self.assertRaises(ValueError):
            kb_promote.promote(self.live, self.stage, ["DB/a.md"], "Pat", today="2026-01-02")

    def test_merge_of_a_new_file_just_adds_it(self):
        kb_promote.promote(self.live, self.stage, ["DB/b.md"], "Pat", merge=True)
        self.assertEqual(get(self.live, "DB/b.md"), "new b")

    def test_dry_run_changes_nothing(self):
        steps = kb_promote.promote(self.live, self.stage, ["DB/a.md"], "Pat", dry_run=True)
        self.assertEqual(len(steps), 1)
        self.assertEqual(get(self.live, "DB/a.md"), "old a")
        self.assertFalse(os.path.exists(os.path.join(self.live, "Archive")))


if __name__ == "__main__":
    unittest.main()
