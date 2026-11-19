import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import devin_usage  # noqa: E402

SESSIONS = [
    {"session_id": "a", "title": "ACME-101 /plan", "tags": ["sdlc-workbench"], "created_at": "2026-10-01T10:00:00Z",
     "updated_at": "2026-10-01T12:30:00Z"},
    {"session_id": "b", "title": "Verifier: ACME-101", "tags": ["sdlc-verifier", "ACME-101"],
     "created_at": "2026-10-02T10:00:00Z", "updated_at": "2026-10-02T10:30:00Z"},
    {"session_id": "c", "title": "Argus Jira reader", "tags": ["sdlc-jira-read"], "created_at": "2026-10-02T10:00:00Z",
     "updated_at": "2026-10-02T11:00:00Z"},
]


class DevinUsageTests(unittest.TestCase):
    def test_groups_by_story_and_stage_and_skips_sessions_with_no_story(self):
        got = devin_usage.rows(SESSIONS)
        self.assertEqual([(r["story"], r["stage"], r["sessions"], r["hours"]) for r in got],
                         [("ACME-101", "plan", 1, 2.5), ("ACME-101", "verifier", 1, 0.5)])
        self.assertTrue(all(r["acus"] is None for r in got))

    def test_acus_only_from_an_export(self):
        got = devin_usage.rows(SESSIONS, {"b": 3.5})
        self.assertEqual([r["acus"] for r in got], [None, 3.5])


if __name__ == "__main__":
    unittest.main()
