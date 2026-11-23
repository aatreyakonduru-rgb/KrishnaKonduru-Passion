import datetime
import os
import shutil
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import kb_gate  # noqa: E402
import page_owners  # noqa: E402


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


class PageOwnersTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.kb = os.path.join(self.tmp, "kb")
        prof = {
            "owners": {"kb_owner": "Ana Lead", "app_owner": "Raj Dev"},
            "review": {"default_days": 60},
            "gate": {"teams": [
                {"name": "Claims Team", "owns": ["claims/*"], "approvers": ["Cleo Claims"]},
            ]},
        }
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump(prof))
        write(os.path.join(self.kb, "_EVIDENCE", "files", "f.txt"), "sample\n")
        write(os.path.join(self.kb, "claims", "p1.md"), "# P1\n\n- Fact [E: file:f.txt]\n")
        write(os.path.join(self.kb, "context", "p2.md"), "# P2\n\n- Fact [E: file:f.txt]\n")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_default_owner_from_gate_teams(self):
        info1 = page_owners.page_info(self.kb, "claims/p1.md")
        self.assertEqual(info1["owner"], "Claims Team")
        self.assertEqual(info1["review_every_days"], 60)
        self.assertTrue(info1["is_overdue"])  # never reviewed

    def test_files_without_owner(self):
        unowned = page_owners.files_without_owner(self.kb)
        self.assertIn("context/p2.md", unowned)
        self.assertNotIn("claims/p1.md", unowned)

    def test_set_page_owner_and_days(self):
        page_owners.set_page(self.kb, "context/p2.md", owner="Raj Dev", days=30, by="Ana Lead")
        info = page_owners.page_info(self.kb, "context/p2.md")
        self.assertEqual(info["owner"], "Raj Dev")
        self.assertEqual(info["review_every_days"], 30)
        self.assertEqual(info["set_by"], "Ana Lead")

    def test_mark_reviewed_by_lead_and_due_calculation(self):
        today = datetime.date(2026, 6, 1)
        page_owners.set_page(self.kb, "claims/p1.md", days=30)
        page_owners.mark_reviewed(self.kb, "claims/p1.md", by="Ana Lead", on="2026-06-01")

        # As of 2026-06-15, it should not be overdue
        info = page_owners.page_info(self.kb, "claims/p1.md", as_of="2026-06-15")
        self.assertFalse(info["is_overdue"])
        self.assertEqual(info["next_due"], "2026-07-01")
        self.assertEqual(info["days_until_due"], 16)

        # As of 2026-07-10, it should be overdue
        info2 = page_owners.page_info(self.kb, "claims/p1.md", as_of="2026-07-10")
        self.assertTrue(info2["is_overdue"])
        self.assertEqual(info2["overdue_days"], 9)

    def test_mark_reviewed_by_owner_or_approver(self):
        # Cleo is approver for Claims Team
        page_owners.mark_reviewed(self.kb, "claims/p1.md", by="Cleo Claims", on="2026-06-01")
        info = page_owners.page_info(self.kb, "claims/p1.md")
        self.assertEqual(info["last_reviewed"], "2026-06-01")

    def test_mark_reviewed_refused_for_stranger(self):
        with self.assertRaises(kb_gate.GateError) as cm:
            page_owners.mark_reviewed(self.kb, "claims/p1.md", by="Stranger Bob")
        self.assertIn("neither a lead", str(cm.exception))

    def test_due_pages_ordering(self):
        page_owners.set_page(self.kb, "claims/p1.md", days=30)
        page_owners.set_page(self.kb, "context/p2.md", days=10)
        page_owners.mark_reviewed(self.kb, "claims/p1.md", by="Ana Lead", on="2026-01-01")
        page_owners.mark_reviewed(self.kb, "context/p2.md", by="Ana Lead", on="2026-05-01")

        due = page_owners.due_pages(self.kb, as_of="2026-06-01")
        self.assertEqual(len(due), 2)
        # claims/p1.md was due 2026-01-31, so more overdue than context/p2.md (due 2026-05-11)
        self.assertEqual(due[0]["page"], "claims/p1.md")

    def test_cli(self):
        self.assertEqual(page_owners.main(["set", self.kb, "context/p2.md", "--owner", "Ana Lead"]), 0)
        self.assertEqual(page_owners.main(["show", self.kb, "context/p2.md"]), 0)
        self.assertEqual(page_owners.main(["due", self.kb]), 0)
        self.assertEqual(page_owners.main(["stale-report", self.kb]), 0)
        self.assertEqual(page_owners.main(["mark-reviewed", self.kb, "context/p2.md", "--by", "Ana Lead"]), 0)


if __name__ == "__main__":
    unittest.main()
