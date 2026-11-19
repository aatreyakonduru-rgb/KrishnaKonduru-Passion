"""Who is working on what: one row per roster person with their sprint items and recent Devin Cloud sessions."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "console"))
import gen_dashboard as g  # noqa: E402
import bridge  # noqa: E402
import server  # noqa: E402

ROSTER = [
    {"jira_user": "AA1", "name": "Ann", "primary_role": "developer", "devin_user_id": "user-a"},
    {"jira_user": "BB2", "name": "Bob", "primary_role": "qa_staff", "devin_user_id": None},
    {"jira_user": "CC3", "name": "Cy", "primary_role": "solution_lead", "devin_user_id": "user-c"},
]
ISSUES = [
    {"key": "ACME-1", "summary": "Story one", "status": "In Progress", "category": "indeterminate", "username": "AA1"},
    {"key": "ACME-2", "summary": "Task", "status": "In Progress", "category": "indeterminate", "username": "AA1",
     "parent": "ACME-9"},
    {"key": "ACME-3", "summary": "Later", "status": "To Do", "category": "new", "username": "AA1"},
    {"key": "ACME-4", "summary": "Shipped", "status": "Done", "category": "done", "username": "BB2"},
]
SESSIONS = [
    {"session_id": "devin-aaa", "title": "Work on ACME-1", "status": "blocked", "updated": 200, "user_id": "user-a"},
    {"session_id": "devin-bbb", "title": "Older", "status": "suspended", "updated": 100, "user_id": "user-a",
     "tags": ["work_id:ACME-2"]},
    {"session_id": "devin-zzz", "title": "Not on the roster", "status": "working", "updated": 300, "user_id": "user-z"},
]


class TeamActivityRowsTests(unittest.TestCase):
    def rows(self, sessions=SESSIONS):
        return {r["person"]: r for r in g.team_activity_rows(ISSUES, sessions, ROSTER)}

    def test_every_roster_person_gets_a_row(self):
        self.assertEqual(set(self.rows()), {"Ann", "Bob", "Cy"})

    def test_jira_work_is_split_by_status(self):
        ann = self.rows()["Ann"]
        self.assertEqual([i["key"] for i in ann["doing"]], ["ACME-1", "ACME-2"])
        self.assertEqual((ann["todo"], ann["done"]), (1, 0))
        self.assertEqual(self.rows()["Bob"]["done"], 1)

    def test_sessions_match_by_devin_user_id_newest_first(self):
        ann = self.rows()["Ann"]
        self.assertEqual([s["id"] for s in ann["sessions"]], ["aaa", "bbb"])
        self.assertEqual(ann["sessions"][0]["state"], "Waiting on them")
        self.assertEqual(ann["sessions"][0]["story"], "ACME-1")
        self.assertEqual(ann["sessions"][1]["story"], "ACME-2")

    def test_people_without_a_devin_id_are_flagged_not_guessed(self):
        bob = self.rows()["Bob"]
        self.assertFalse(bob["known_in_devin"])
        self.assertEqual(bob["sessions"], [])

    def test_busy_people_sort_first(self):
        order = [r["person"] for r in g.team_activity_rows(ISSUES, SESSIONS, ROSTER)]
        self.assertEqual(order[0], "Ann")


class TeamActivityRenderTests(unittest.TestCase):
    def setUp(self):
        self.people = g.people
        g.people = lambda: {"people": ROSTER}

    def tearDown(self):
        g.people = self.people

    def test_renders_tickets_sessions_and_missing_ids(self):
        html = str(g.render_team_activity({"days": 7}, {"name": "Sprint 1"}, ISSUES, {"sessions": SESSIONS}))
        self.assertIn("ACME-1", html)
        self.assertIn("/sessions/aaa", html)
        self.assertIn("No Devin Cloud id on the roster", html)
        self.assertIn("None in the last 7 days", html)
        self.assertIn("Sprint 1: 1 of 3 people", html)
        self.assertNotIn("Not on the roster", html)

    def test_sessions_not_collected_says_so(self):
        html = str(g.render_team_activity({}, {"name": "Sprint 1"}, ISSUES, None))
        self.assertIn("were not collected", html)

    def test_only_own_sessions_points_at_the_permission(self):
        own = [dict(SESSIONS[0], user_id="user-c")]
        html = str(g.render_team_activity({}, {"name": "Sprint 1"}, ISSUES, {"sessions": own}, "user-c"))
        self.assertIn("View sessions", html)


class TeamActivityAudienceTests(unittest.TestCase):
    def test_audience_lists_the_lead_and_manager_roles(self):
        spec = g.lens_config()["panels"]["team_activity"]
        self.assertTrue({"solution_lead", "manager"} <= set(spec["audience"]))
        lenses = g.lens_config()["lenses"]
        for lens in ("tech_lead", "po_office", "delivery_lead"):
            self.assertIn("team_activity", lenses[lens]["panels"])

    def test_argus_collects_team_sessions_only_where_the_panel_is(self):
        self.assertIn("manager", server.team_activity_audience("po_office"))
        self.assertIn("solution_lead", server.team_activity_audience("tech_lead"))
        self.assertIsNone(server.team_activity_audience("developer"))


class BridgeTeamSessionsTests(unittest.TestCase):
    def test_one_search_for_every_known_devin_id(self):
        calls = []
        dev = bridge.BridgeDevin.__new__(bridge.BridgeDevin)
        dev.call = lambda *req: calls.append(req[0]) or [
            "- 3c6f11bb265148f2bcf107a9c1e2708d | Run | status=running | updated=1792689389 | user_id=user-a"]
        rows = dev.team_sessions(ROSTER, 1000)
        self.assertEqual(calls[0][1], {"user_ids": ["user-a", "user-c"], "updated_after": 1000, "first": 100})
        self.assertEqual(rows[0]["user_id"], "user-a")
        self.assertEqual(dev.team_sessions([ROSTER[1]], 1000), [])


if __name__ == "__main__":
    unittest.main()
