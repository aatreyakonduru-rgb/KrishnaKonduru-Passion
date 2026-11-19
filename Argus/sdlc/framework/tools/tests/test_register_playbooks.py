"""register_playbooks.py reads each playbook file and creates or updates it by macro."""
import glob
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import register_playbooks as rp  # noqa: E402

BOOK = "# Playbook: X\n\n## Title\n\n```\nTeam: Start\n```\n\n## Playbook Body\n\n---\n\nRun `/start`.\n"


class RegisterPlaybooksTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        for name, text in (("PB-01-start.md", BOOK), ("PB-02-notes.md", "# only notes\n"),
                           ("PLAYBOOK-GUIDE.md", BOOK)):
            with open(os.path.join(self.dir, name), "w", encoding="utf-8") as fh:
                fh.write(text)

    def test_reads_title_macro_and_body(self):
        books = rp.local(self.dir)
        self.assertEqual([(b["file"], b["title"], b["macro"]) for b in books],
                         [("PB-01-start.md", "Team: Start", "!pb_01_start")])
        self.assertEqual(books[0]["body"], "---\n\nRun `/start`.\n")

    def test_every_repo_playbook_parses_with_a_unique_macro(self):
        books = rp.local()
        runnable = [f for f in glob.glob(os.path.join(rp.PLAYBOOKS, "PB-*.md"))
                    if "## Playbook Body" in open(f, encoding="utf-8").read()]
        self.assertEqual(sorted(b["file"] for b in books), sorted(os.path.basename(f) for f in runnable))
        self.assertEqual(len({b["macro"] for b in books}), len(books))
        self.assertTrue(all(b["body"].strip() and b["title"] for b in books))

    def test_plan_creates_updates_or_leaves_alone(self):
        b = rp.local(self.dir)[0]
        self.assertEqual(rp.plan([b], [])[0][0], "create")
        self.assertEqual(rp.plan([b], [dict(b, playbook_id="p1")])[0][0], "same")
        self.assertEqual(rp.plan([b], [dict(b, body="old", playbook_id="p1")])[0][0], "update")

    def test_apply_posts_new_and_puts_changed(self):
        calls = []

        def api(method, path, key, data=None):
            calls.append((method, path, data and data["macro"]))
            return {"items": [{"macro": "!pb_01_start", "title": "old", "body": "", "playbook_id": "p1"}]} \
                if method == "GET" else {}
        with mock.patch.dict(os.environ, {"DEVIN_API_KEY": "k"}), mock.patch("sys.stdout"):
            self.assertEqual(rp.main(["--folder", self.dir, "--apply"], api=api), 0)
            self.assertEqual(calls[1:], [("PUT", "/v1/playbooks/p1", "!pb_01_start")])
            calls.clear()
            self.assertEqual(rp.main(["--folder", self.dir], api=api), 0)
            self.assertEqual([c[0] for c in calls], ["GET"])

    def test_no_key_lists_and_refuses_to_apply(self):
        with mock.patch.dict(os.environ, {"DEVIN_API_KEY": ""}), mock.patch("sys.stdout"):
            self.assertEqual(rp.main(["--folder", self.dir]), 0)
            self.assertEqual(rp.main(["--folder", self.dir, "--apply"]), 2)


if __name__ == "__main__":
    unittest.main()
