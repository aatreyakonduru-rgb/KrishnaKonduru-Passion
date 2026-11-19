"""Defect root cause and escape analysis."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

import defect_rca as D  # noqa: E402


def issue(detected, resolved, comments=()):
    return {"key": "ACME-9", "fields": {"summary": "x", D.dbs.F_DETECTED: {"value": detected},
            "resolution": {"name": "Done"} if resolved else None,
            "issuelinks": [{"outwardIssue": {"key": "ACME-1", "fields": {"summary": "story"}}}],
            "comment": {"comments": [{"body": b} for b in comments]}}}


class DefectRcaTest(unittest.TestCase):
    def test_escape_stage_and_story(self):
        r = D.row(issue("TEST - User Acceptance Test (UAT)", False))
        self.assertEqual((r["stage"], r["should_catch"], r["story"], r["ask"]), ("UAT", "SIT testing (SDLC_06)", "ACME-1", False))

    def test_closed_without_cause_is_asked_and_cause_is_read_back(self):
        self.assertTrue(D.row(issue("TEST - System Integration Test (SIT)", True))["ask"])
        call = D.cause_call("ACME-9", "Example, Ann", "code", "null check missing")
        r = D.row(issue("TEST - System Integration Test (SIT)", True, [call["body"]["body"]]))
        self.assertEqual((r["cause"], r["cause_note"], r["ask"]), ("code", "null check missing", False))
        with self.assertRaises(ValueError):
            D.cause_call("ACME-9", "A", "luck")


if __name__ == "__main__":
    unittest.main()
