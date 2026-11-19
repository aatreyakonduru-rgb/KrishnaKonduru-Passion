import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import hotfix  # noqa: E402


def issue(summary="Claims page blank - PROD", labels=("incident-INC0012345",), kind="Defect"):
    return {"fields": {"summary": summary, "labels": list(labels), "issuetype": {"name": kind}}}


class HotfixTest(unittest.TestCase):
    def test_incident_defect_is_eligible(self):
        self.assertEqual(hotfix.eligible(issue()), (True, []))

    def test_story_without_incident_is_not(self):
        ok, why = hotfix.eligible(issue(summary="Claims page blank", labels=(), kind="Story"))
        self.assertFalse(ok)
        self.assertEqual(len(why), 3)

    def test_due_date_skips_the_weekend(self):
        self.assertEqual(hotfix.due_after(datetime.date(2026, 10, 16), 2), datetime.date(2026, 10, 20))

    def test_followup_subtask(self):
        p = hotfix.followup_payload("ACME-9", "Resource 3", "resource3", datetime.date(2026, 10, 20))["fields"]
        self.assertEqual(p["parent"], {"key": "ACME-9"})
        self.assertEqual(p["duedate"], "2026-10-20")
        self.assertEqual(p["labels"], ["hotfix-review"])


if __name__ == "__main__":
    unittest.main()


class HotfixGateTest(unittest.TestCase):
    def test_hotfix_gate_opens_sdlc_04_and_05_only(self):
        import gates
        from unittest import mock
        signed = {"status": "approved", "signed_by": "Resource 3", "signed_at": "2026-10-16T00:00:00Z",
                  "decision_items": [{"state": "approved", "by": "Resource 3"}]}
        phase = lambda data, gid, story=None: signed if gid == gates.HOTFIX_GATE else {}  # noqa: E731
        with mock.patch.object(gates.session_store, "read_approvals", return_value={"x": 1}), \
                mock.patch.object(gates, "get_phase", side_effect=phase):
            self.assertTrue(gates.is_open("REQ-1", "SDLC_04_ROUTING_APPROVAL", "STORY-1"))
            self.assertTrue(gates.is_open("REQ-1", "SDLC_05_CODE_REVIEW", "STORY-1"))
            self.assertFalse(gates.is_open("REQ-1", "SDLC_06_QA_SIGNOFF", "STORY-1"))
