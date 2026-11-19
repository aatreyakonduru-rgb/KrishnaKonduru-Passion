"""The weekly time-off question, the planner table and routing to backups."""
import datetime
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

import sprint_leave as L  # noqa: E402
import time_off as T  # noqa: E402

ROSTER = [{"jira_user": "AA1", "name": "Example, Ann", "delegate_to": "CC3"},
          {"jira_user": "BB2", "name": "Example, Ben", "delegate_to": ""},
          {"jira_user": "CC3", "name": "Example, Cy", "delegate_to": ""}]
MON = datetime.date(2026, 10, 12)


class TimeOffTest(unittest.TestCase):
    def test_question_is_due_once_a_calendar_week(self):
        ann = ROSTER[0]
        self.assertTrue(T.due([], ann, MON))
        rows = T.record_none([], ann, MON + datetime.timedelta(days=2))
        self.assertFalse(T.due(rows, ann, MON + datetime.timedelta(days=6)))
        self.assertTrue(T.due(rows, ann, MON + datetime.timedelta(days=7)))
        self.assertEqual(rows[0]["note"], "No time off planned")

    def test_time_off_with_backups_replaces_the_no_time_off_row(self):
        ann = ROSTER[0]
        rows = T.record_none([], ann, MON)
        rows = T.record_off(rows, ROSTER, ann, "2026-10-19", "2026-10-21", MON, stories_to="Ben Example",
                            questions_to="BB2", hold=True)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["stories_to"], "Example, Ben")
        self.assertTrue(rows[0]["hold"])
        with self.assertRaises(T.TimeOffError):
            T.record_off(rows, ROSTER, ann, "2026-10-21", "2026-10-19", MON)
        with self.assertRaises(T.TimeOffError):
            T.record_off(rows, ROSTER, ann, "2026-10-19", "2026-10-20", MON, stories_to="Ann Example")

    def test_routing_goes_to_the_backup_then_delegate_while_away(self):
        ann = ROSTER[0]
        rows = T.record_off([], ROSTER, ann, "2026-10-19", "2026-10-21", MON, questions_to="BB2")
        self.assertFalse(T.route(rows, ROSTER, ann, "question", MON)["away"])
        q = T.route(rows, ROSTER, ann, "question", datetime.date(2026, 10, 20))
        self.assertEqual((q["to"], q["away"]), ("Example, Ben", True))
        a = T.route(rows, ROSTER, ann, "approval", datetime.date(2026, 10, 20))
        self.assertEqual(a["jira_user"], "CC3")
        ben = ROSTER[1]
        rows = T.record_off(rows, ROSTER, ben, "2026-10-19", "2026-10-19", MON)
        self.assertIn("named no backup", T.route(rows, ROSTER, ben, "story", datetime.date(2026, 10, 19))["why"])

    def test_page_keeps_the_planner_and_fills_sprint_days_off(self):
        rows = T.record_off([], ROSTER, ROSTER[0], "2026-10-16", "2026-10-20", MON, stories_to="BB2")
        sprint = L.new_sprint({"start": "2026-10-07", "end": "2026-10-27"},
                              [{"jira_user": "AA1", "name": "Example, Ann", "allocation": 100}])
        L.apply_time_off(sprint, rows)
        self.assertEqual(sprint["people"][0]["off"], ["2026-10-16", "2026-10-19", "2026-10-20"])
        page = L.render_page({"26.4.2": sprint}, rows)
        self.assertEqual(L.parse_time_off(page)[0]["stories_to"], "Example, Ben")
        self.assertEqual(L.parse_page(page)["26.4.2"]["people"][0]["off"], sprint["people"][0]["off"])
        self.assertEqual(L.parse_time_off(L.render_page({"26.4.2": sprint})), [])

    def test_hold_blocks_are_backlog_previews(self):
        row = {"from": "2026-10-19", "to": "2026-10-21", "stories_to": "Example, Ben"}
        text = T.hold_blocks(["ACME-1", "ACME-2"], ROSTER[0], row)
        self.assertEqual(text.count("SDLC-DASHBOARD-BACKLOG"), 2)
        self.assertIn("why: Example, Ann is away 2026-10-19 to 2026-10-21; backup Example, Ben", text)

    def test_leave_tab_lists_who_is_away_soon_and_who_was_not_asked(self):
        import scrum_metrics
        rows = T.record_off([], ROSTER, ROSTER[0], "2026-10-19", "2026-10-21", MON, stories_to="BB2")
        data = {"time_off": rows, "capacity": {"people": [{"name": "Example, Ann"}, {"name": "Example, Ben"}]}}
        upcoming, not_asked = scrum_metrics.time_off_rows(data, MON + datetime.timedelta(days=2))
        self.assertEqual([r["name"] for r in upcoming], ["Example, Ann"])
        self.assertEqual(not_asked, ["Example, Ben"])



class VacationTest(unittest.TestCase):
    SM = {"jira_user": "SM9", "name": "Example, Sam", "delegate_to": "", "primary_role": "scrum_master"}

    def test_people_change_their_own_rows_and_the_scrum_master_anyones(self):
        ann, ben = ROSTER[0], ROSTER[1]
        T.may_edit(ann, ann)
        T.may_edit(self.SM, ann)
        with self.assertRaises(T.TimeOffError):
            T.may_edit(ben, ann)

    def test_upcoming_and_remove(self):
        ann = ROSTER[0]
        rows = T.record_off([], ROSTER, ann, "2026-10-19", "2026-10-21", MON, stories_to="BB2")
        rows = T.record_off(rows, ROSTER, ann, "2026-11-02", "2026-11-03", MON)
        self.assertEqual([r["from"] for r in T.upcoming(rows, MON)], ["2026-10-19", "2026-11-02"])
        self.assertEqual([r["from"] for r in T.upcoming(rows, datetime.date(2026, 10, 22))], ["2026-11-02"])
        left = T.remove(rows, ann, "2026-10-19", MON)
        self.assertEqual([r["from"] for r in left], ["2026-11-02"])
        with self.assertRaises(T.TimeOffError):
            T.remove(left, ann, "2026-10-19", MON)

    def test_vacation_planner_tab_shows_backups(self):
        import gen_dashboard as G
        rows = [{"jira_user": "AA1", "name": "Example, Ann", "from": "2026-10-12", "to": "2026-10-14",
                 "stories_to": "Example, Ben", "questions_to": "Example, Cy", "approvals_to": "", "hold": True},
                {"jira_user": "BB2", "name": "Example, Ben", "from": "2026-09-01", "to": "2026-09-02"}]
        out = G.render_vacation({"id": "vacation_planner", "title": "Vacation planner"}, rows, "", "aa1", MON)["body"]
        self.assertIn("Example, Ben", out)
        self.assertIn("Example, Cy", out)
        self.assertIn("not named", out)
        self.assertIn("(you)", out)
        self.assertIn("away now", out)
        self.assertNotIn("2026-09-01", out)

class SickDayTest(unittest.TestCase):
    def test_sick_day_is_one_day_with_no_backups_and_keeps_the_weekly_answer(self):
        ann = ROSTER[0]
        rows = T.record_none([], ann, MON)
        rows = T.record_sick(rows, ann, "2026-10-13", MON, by="Example, Ben")
        sick = [r for r in rows if r.get("kind") == T.SICK]
        self.assertEqual(len(rows), 2)
        self.assertEqual((sick[0]["from"], sick[0]["to"], sick[0]["note"]), ("2026-10-13", "2026-10-13",
                                                                             "Reported by Example, Ben"))
        self.assertEqual((sick[0]["stories_to"], sick[0]["hold"], sick[0]["asked"]), ("", False, ""))
        self.assertFalse(T.due(rows, ann, MON + datetime.timedelta(days=3)))

    def test_sick_day_reroutes_nothing(self):
        ann = ROSTER[0]
        rows = T.record_sick([], ann, "2026-10-13", MON)
        got = T.route(rows, ROSTER, ann, "question", datetime.date(2026, 10, 13))
        self.assertEqual((got["to"], got["away"]), ("Example, Ann", False))
        self.assertEqual([r["name"] for r in T.away(rows, datetime.date(2026, 10, 13))], ["Example, Ann"])

    def test_sick_day_refuses_weekends_and_days_already_off(self):
        ann = ROSTER[0]
        with self.assertRaises(T.TimeOffError):
            T.record_sick([], ann, "2026-10-17", MON)
        rows = T.record_off([], ROSTER, ann, "2026-10-12", "2026-10-14", MON)
        with self.assertRaises(T.TimeOffError):
            T.record_sick(rows, ann, "2026-10-13", MON)
        rows = T.record_sick([], ann, "2026-10-13", MON)
        with self.assertRaises(T.TimeOffError):
            T.record_sick(rows, ann, "2026-10-13", MON)

    def test_sick_day_survives_the_page_and_stays_off_the_planning_sheet(self):
        import sprint_sheet
        rows = T.record_sick([], ROSTER[0], "2026-10-13", MON, by="Someone Outside")
        self.assertEqual(L.parse_time_off(L.render_page({}, rows))[0]["kind"], T.SICK)
        name = sprint_sheet.people(sprint_sheet.load(sprint_sheet.sprints()[0]))[0]["name"]
        sick = [dict(rows[0], name=name, jira_user="")]
        self.assertEqual(sprint_sheet.apply_time_off([], sick), {})
        off = [dict(sick[0], kind="")]
        self.assertTrue(sprint_sheet.apply_time_off([], off))

    def test_planner_tab_marks_sick_days(self):
        import gen_dashboard as G
        rows = T.record_sick([], ROSTER[0], "2026-10-12", MON)
        out = G.render_vacation({"id": "vacation_planner", "title": "Vacation planner"}, rows, "", "", MON)["body"]
        self.assertIn("Sick day", out)
        self.assertNotIn("not named", out)


if __name__ == "__main__":
    unittest.main()
