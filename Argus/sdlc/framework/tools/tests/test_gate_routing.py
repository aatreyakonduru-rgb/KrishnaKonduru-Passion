import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gates  # noqa: E402

ROSTER = [{"jira_user": "resource4", "name": "Resource 4", "delegate_to": "", "primary_role": "solution_lead"},
          {"jira_user": "resource5", "name": "Resource 5", "delegate_to": "", "primary_role": "solution_lead"},
          {"jira_user": "resource3", "name": "Resource 3", "delegate_to": "", "primary_role": "solution_lead"},
          {"jira_user": "resource6", "name": "Resource 6", "delegate_to": "", "primary_role": "solution_lead"}]
GATE = {"id": "SDLC_04_ROUTING_APPROVAL", "approvers": [
    {"role": "tech_lead", "names": ["Resource 4", "Resource 5"],
     "backups": ["Resource 3", "Resource 6"]}]}
DAY = datetime.date(2026, 10, 20)


def away(user, name, approvals_to=""):
    return {"jira_user": user, "name": name, "from": "2026-10-19", "to": "2026-10-23", "approvals_to": approvals_to}


class GateRoutingTests(unittest.TestCase):
    def test_nobody_away_keeps_the_named_approvers(self):
        names, notes = gates.approver_route(GATE, DAY, rows=[], roster=ROSTER)
        self.assertEqual(names, ["Resource 4", "Resource 5"])
        self.assertEqual(notes, [])

    def test_away_with_a_backup_hands_to_that_backup(self):
        rows = [away("resource4", "Resource 4", "Resource 3")]
        names, notes = gates.approver_route(GATE, DAY, rows=rows, roster=ROSTER)
        self.assertEqual(names, ["Resource 3", "Resource 5"])
        self.assertTrue(notes)

    def test_everyone_named_away_falls_to_the_gate_backups(self):
        rows = [away("resource4", "Resource 4"), away("resource5", "Resource 5")]
        names, notes = gates.approver_route(GATE, DAY, rows=rows, roster=ROSTER)
        self.assertEqual(names, ["Resource 3", "Resource 6"])
        self.assertIn("backups", notes[-1])


if __name__ == "__main__":
    unittest.main()
