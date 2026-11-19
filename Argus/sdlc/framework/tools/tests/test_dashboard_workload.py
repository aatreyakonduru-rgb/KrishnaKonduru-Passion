"""The workload panel reads the active sprint that belongs to the team board, not a same-named
sprint another board shares with it."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import gen_dashboard as g  # noqa: E402
import sprint_sheet  # noqa: E402

ACTIVE = [
    {"id": 1, "originBoardId": 247285, "name": "Acme Claims Sprint 26.4.2", "startDate": "2026-10-07",
     "endDate": "2026-10-27"},
    {"id": 2, "originBoardId": 247317, "name": "Acme Claims Sprint 26.4.2", "startDate": "2026-10-07",
     "endDate": "2026-10-27"},
]


class FakeClient:
    def __init__(self):
        self.searched = []

    def live_get(self, path, **params):
        if path.endswith("/sprint"):
            return {"values": ACTIVE}
        self.searched.append(params["jql"])
        return {"issues": [], "total": 0}


class WorkloadSprintTests(unittest.TestCase):
    def test_prefers_the_sprint_owned_by_the_team_board(self):
        src = g.LiveSource.__new__(g.LiveSource)
        src.client = FakeClient()
        g.team_board = lambda: "247285"
        sprint, issues = src.workload({})
        self.assertEqual(sprint["name"], "Acme Claims Sprint 26.4.2")
        self.assertIn("sprint = 1", src.client.searched[0])
        self.assertEqual(issues, [])

    def test_falls_back_to_the_last_active_sprint(self):
        src = g.LiveSource.__new__(g.LiveSource)
        src.client = FakeClient()
        g.team_board = lambda: "999"
        src.workload({})
        self.assertIn("sprint = 2", src.client.searched[0])


SPRINT = {"name": "Acme Claims Sprint 26.4.2(10/7-10/27)", "start": "2026-10-07T11:03:00.000-04:00",
          "end": "2026-10-27T20:03:00.000-04:00"}
ROSTER = {"people": [{"jira_user": "U1", "name": "Resource 9", "allocation": 50},
                     {"jira_user": "U2", "name": "Resource 11"}]}


def item(key, who, hours, parent=""):
    return {"key": key, "parent": parent, "username": who, "display": who, "category": "new",
            "estimate_hours": hours}


class WorkloadCountTests(unittest.TestCase):
    def setUp(self):
        self.people = g.people
        g.people = lambda: ROSTER

    def tearDown(self):
        g.people = self.people

    def rows(self, issues, sheet=None):
        return {r["person"]: r for r in g.workload_rows({"hours_per_day": 6}, SPRINT, issues, sheet)}

    def test_story_with_sub_tasks_is_counted_through_them_only(self):
        rows = self.rows([item("S-1", "U1", 144), item("T-1", "U1", 40, "S-1"), item("T-2", "U1", 30, "S-1"),
                          item("D-1", "U1", 8)])
        self.assertEqual(rows["Resource 9"]["hours"], 78)
        self.assertEqual(rows["Resource 9"]["items"], 3)

    def test_sub_task_whose_story_is_not_in_the_sprint_still_counts(self):
        rows = self.rows([item("T-1", "U1", 40, "S-9")])
        self.assertEqual(rows["Resource 9"]["hours"], 40)

    def test_capacity_comes_from_the_planning_sheet(self):
        sheet = {sprint_sheet.norm("Resource 9"): {"name": "Resource 9", "allocation": 100.0, "hours": 90.0}}
        rows = self.rows([item("T-1", "U1", 45, "S-1")], sheet)
        self.assertEqual(rows["Resource 9"]["capacity"], 90)
        self.assertEqual(rows["Resource 9"]["allocation"], 100)
        self.assertEqual(rows["Resource 9"]["capacity_from"], "sheet")
        self.assertAlmostEqual(rows["Resource 9"]["load"], 0.5)

    def test_people_not_on_the_sheet_fall_back_to_the_roster(self):
        rows = self.rows([], {})
        self.assertEqual(rows["Resource 9"]["capacity"], 15 * 6 * 0.5)
        self.assertEqual(rows["Resource 11"]["capacity"], 15 * 6)
        self.assertEqual(rows["Resource 11"]["capacity_from"], "roster")

    def test_finds_the_sheet_by_sprint_number(self):
        token, people = g.sprint_capacity(SPRINT)
        self.assertEqual(token, "26.4.2")
        self.assertIn(sprint_sheet.norm("Resource 9"), people)

    def test_no_sheet_for_the_sprint(self):
        self.assertEqual(g.sprint_capacity({"name": "Acme Claims Sprint 20.1.1", "start": "2020-01-01"}), ("", {}))


if __name__ == "__main__":
    unittest.main()
