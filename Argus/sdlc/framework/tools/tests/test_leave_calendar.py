"""The leave calendar and unplanned leave on the Vacation planner tab."""
import datetime
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

import gen_dashboard as G  # noqa: E402
import leave_calendar as C  # noqa: E402
import sprint_leave as L  # noqa: E402
import sprint_sheet as S  # noqa: E402
import unplanned_leave as U  # noqa: E402
from test_unplanned_leave import entry, tracker  # noqa: E402

MON = datetime.date(2026, 10, 19)


class FakeSheet:
    """A sprint sheet stand-in: sprint 26.4.2 from Wed 14 to Tue 20 October."""
    def __init__(self, test, people):
        self.sheet = {"sprint": "26.4.2", "start": "2026-10-14", "end": "2026-10-20"}
        orig = S.people
        S.people = lambda sheet: [dict(p, off=list(p.get("off", [])), half=list(p.get("half", [])),
                                       holiday=list(p.get("holiday", []))) for p in people]
        test.addCleanup(setattr, S, "people", orig)


def kinds(g, name):
    p = next(p for p in g["people"] if p["name"] == name)
    return {k: v["kind"] + ("/half" if v["half"] else "") for k, v in p["days"].items()}


class GridTest(unittest.TestCase):
    def test_each_kind_of_day_gets_its_own_type(self):
        sh = FakeSheet(self, [{"name": "Example, Ann", "off": ["2026-10-14"], "half": ["2026-10-15"],
                               "holiday": ["2026-10-16"]},
                              {"name": "Example, Ben"}]).sheet
        rows = [{"from": "2026-10-19", "to": "2026-10-19", "name": "Example, Ben", "kind": L.SICK},
                {"from": "2026-10-20", "to": "2026-10-20", "name": "Example, Ben", "kind": "Time off"}]
        log = [entry("Example, Ann", "2026-10-19", kind=L.ADHOC)]
        g = C.grid(sh, rows, log)
        self.assertEqual(len(g["days"]), 7)
        ann, ben = kinds(g, "Example, Ann"), kinds(g, "Example, Ben")
        self.assertEqual(ann["2026-10-14"], C.PLANNED)
        self.assertEqual(ann["2026-10-15"], C.PLANNED + "/half")
        self.assertEqual(ann["2026-10-16"], C.HOLIDAY)
        self.assertEqual(ann["2026-10-17"], C.WEEKEND)
        self.assertEqual(ann["2026-10-19"], C.ADHOC)
        self.assertEqual(ben["2026-10-18"], C.WEEKEND)
        self.assertEqual(ben["2026-10-19"], C.SICK)
        self.assertEqual(ben["2026-10-20"], C.PLANNED)

    def test_a_sick_day_wins_over_planned_time_off_on_the_same_day(self):
        sh = FakeSheet(self, [{"name": "Example, Ann", "off": ["2026-10-19"]}]).sheet
        g = C.grid(sh, [], [entry("Example, Ann", "2026-10-19")])
        self.assertEqual(kinds(g, "Example, Ann")["2026-10-19"], C.SICK)

    def test_days_outside_the_sprint_and_people_not_on_the_sheet(self):
        sh = FakeSheet(self, [{"name": "Example, Ann"}]).sheet
        g = C.grid(sh, [], [entry("Example, Ann", "2026-11-02"), entry("Example, Cy", "2026-10-19")])
        self.assertNotIn("2026-11-02", kinds(g, "Example, Ann"))
        self.assertEqual(kinds(g, "Example, Cy")["2026-10-19"], C.SICK)

    def test_the_page_has_a_legend_and_a_class_per_type(self):
        sh = FakeSheet(self, [{"name": "Example, Ann", "holiday": ["2026-10-16"]}]).sheet
        out = C.render(C.grid(sh, [], [entry("Example, Ann", "2026-10-19")]), MON)
        for label in ("Planned time off", "Sick day", "Ad hoc leave", "Holiday", "Weekend", "Half day"):
            self.assertIn(label, out)
        self.assertIn('class="lc-sick lc-today"', out)
        self.assertIn('class="lc-holiday"', out)
        self.assertIn("Sick day, reported by Example, Cy", out)


class SprintViewTest(unittest.TestCase):
    def test_the_sprint_s_days_and_each_person_s_counts(self):
        log = [entry("Example, Ann", "2026-10-19"), entry("Example, Ben", "2026-10-20", kind=L.ADHOC),
               entry("Example, Ann", "2026-10-02", sprint="26.4.1")]
        v = U.sprint_view(tracker(), log, "26.4.2")
        self.assertEqual([e["date"] for e in v["days"]], ["2026-10-19", "2026-10-20"])
        self.assertEqual(v["team"], 4)
        ann = next(p for p in v["people"] if p["name"] == "Example, Ann")
        self.assertEqual((ann["sprint"], ann["year"]), (1, 2))
        html = U.render_sprint_view(v)
        self.assertIn("Unplanned leave, sprint 26.4.2", html)
        self.assertIn("Ad hoc leave", html)

    def test_no_days_this_sprint(self):
        html = U.render_sprint_view(U.sprint_view(tracker(), [], "26.4.2"))
        self.assertIn("No sick days or ad hoc leave reported to Devin this sprint", html)


class PlannerTabTest(unittest.TestCase):
    def test_the_vacation_planner_shows_the_calendar_and_unplanned_leave(self):
        rows = [{"from": "2026-10-19", "to": "2026-10-19", "jira_user": "AA1", "name": "Example, Ann", "kind": L.SICK}]
        orig = U.load
        U.load = lambda path=U.JSON_PATH: tracker()
        self.addCleanup(setattr, U, "load", orig)
        body = G.render_vacation({"id": "vacation_planner", "title": "Vacation planner"}, rows, "", "", MON,
                                 unplanned=[entry("Example, Ann", "2026-10-19")])["body"]
        self.assertIn('class="lc"', body)
        self.assertIn("Who is out, sprint", body)
        self.assertIn("Unplanned leave, sprint", body)
        self.assertLess(body.index("Who is out"), body.index("Stories go to"))

    def test_without_the_log_the_planner_has_no_unplanned_section(self):
        body = G.render_vacation({"id": "vacation_planner", "title": "Vacation planner"}, [], "", "", MON)["body"]
        self.assertNotIn("Unplanned leave, sprint", body)


if __name__ == "__main__":
    unittest.main()
