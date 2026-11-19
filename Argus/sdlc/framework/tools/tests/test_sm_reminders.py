"""Scrum Master reminders asked to the ticket owner."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

import scrum_metrics  # noqa: E402
import sm_reminders as R  # noqa: E402


def defect(key, versions):
    return {"key": key, "fields": {"summary": "Fix it", "issuetype": {"name": "Defect"}, "status": {"name": "Open",
            "statusCategory": {"key": "new"}}, "assignee": {"displayName": "Example, Ann"}, "fixVersions": versions,
            "subtasks": [], "labels": []}}


class SmRemindersTest(unittest.TestCase):
    def test_defect_without_fix_version_is_a_gap_and_a_question(self):
        rows = scrum_metrics.standup_rows({"stories": [defect("ACME-9", []), defect("ACME-8", [{"name": "R1"}])],
                                           "subtasks": []})
        codes = [(r["key"], r["code"]) for r in rows if r["code"] == "no_fix_version"]
        self.assertEqual(codes, [("ACME-9", "no_fix_version")])
        q = R.questions_for(rows, "Ann Example")
        self.assertIn("Which release", q[0]["question"])
        self.assertEqual(R.questions_for(rows, "Ben Example"), [])

    def test_answers_become_a_field_change_and_a_comment(self):
        calls = R.answer_calls("ACME-1", "Example, Ann", due="2026-10-30", question="When will you close it?")
        self.assertEqual(calls[0]["body"], {"fields": {"duedate": "2026-10-30"}})
        self.assertIn("Answer from Example, Ann: due date 2026-10-30", calls[1]["body"]["body"])
        self.assertEqual(len(R.answer_calls("ACME-1", "A", note="waiting on data")), 1)
        with self.assertRaises(ValueError):
            R.answer_calls("ACME-1", "A")


if __name__ == "__main__":
    unittest.main()
