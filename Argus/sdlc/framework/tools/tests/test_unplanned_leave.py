"""The unplanned leave counter: the leave tracker workbook in the repo, the Unplanned leave log and the dashboard tab."""
import datetime
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

import gen_dashboard as G  # noqa: E402
import sprint_leave as L  # noqa: E402
import time_off as T  # noqa: E402
import unplanned_leave as U  # noqa: E402

ANN = {"jira_user": "AA1", "name": "Example, Ann", "delegate_to": ""}


def tracker():
    cells = {"A1": "Team  Member", "B1": "26.4.1", "C1": "26.4.2", "A2": "Example, Ann", "B2": 1, "C2": 0,
             "A3": "Example, Ben", "B3": 0, "C3": 2, "B4": "=SUM(B2:B3)", "C4": "=SUM(C2:C3)"}
    return {"source": "leave.xlsx", "imported_on": "2026-10-19",
            "tabs": [{"name": "Team Capacity", "cells": {"A1": "Name", "A2": "Example, Ann"}},
                     {"name": "Unplanned leaves", "cells": cells}]}


def entry(name, date, sprint="26.4.2", kind=L.SICK):
    return {"date": date, "sprint": sprint, "jira_user": "", "name": name, "kind": kind, "by": "Example, Cy"}


class CounterTest(unittest.TestCase):
    def test_the_tracker_numbers_are_the_starting_count(self):
        c = U.counts(tracker(), [])
        self.assertEqual(c["sprints"], ["26.4.1", "26.4.2"])
        self.assertEqual(c["totals"], {"26.4.1": 1, "26.4.2": 2})
        self.assertEqual((c["total"], c["reported"]), (3, 0))
        self.assertEqual([p["name"] for p in c["people"]], ["Example, Ann", "Example, Ben"])

    def test_each_reported_day_from_the_import_date_adds_one(self):
        log = [entry("Example, Ann", "2026-10-19"), entry("example, ann", "2026-10-20", kind=L.ADHOC),
               entry("Example, Ann", "2026-10-01")]
        c = U.counts(tracker(), log)
        ann = c["people"][0]
        self.assertEqual(ann["days"], {"26.4.1": 1, "26.4.2": 2})
        self.assertEqual((ann["total"], c["totals"]["26.4.2"], c["reported"]), (3, 4, 2))

    def test_a_new_person_and_a_new_sprint_get_a_row_and_a_column(self):
        c = U.counts(tracker(), [entry("Example, Dee", "2026-11-03", sprint="26.4.3")])
        self.assertEqual(c["sprints"][-1], "26.4.3")
        self.assertEqual(c["people"][-1]["days"], {"26.4.3": 1})

    def test_counter_line_names_the_person_the_sprint_and_the_team(self):
        line = U.counter_line("Example, Ann", "2026-10-19", [entry("Example, Ann", "2026-10-19")], tracker())
        self.assertEqual(line, "Unplanned leave: Example, Ann has 1 day in sprint 26.4.2 (2 days this year); "
                               "the team has 3 days in sprint 26.4.2.")

    def test_the_tracker_needs_sprint_columns(self):
        t = tracker()
        t["tabs"][1]["cells"] = {"A1": "Team  Member", "B1": "April"}
        with self.assertRaises(U.TrackerError):
            U.counts(t, [])

    @unittest.skip('checks the knowledge base or application folders of the team that built the copy')
    def test_the_kept_workbook_reads(self):
        c = U.counts(U.load(), [])
        self.assertIn("26.4.4", c["sprints"])
        self.assertTrue(c["people"])


class LogTest(unittest.TestCase):
    def test_the_log_survives_the_page_and_keeps_each_day_once(self):
        sprints = {"26.4.2": {"start": "2026-10-14", "end": "2026-10-27"}}
        log = L.merge_unplanned([], sprints, add=[dict(entry("Example, Ann", "2026-10-19"), sprint="",
                                                       jira_user="AA1")])
        self.assertEqual(log[0]["sprint"], "26.4.2")
        log = L.merge_unplanned(log, sprints, add=[dict(log[0])])
        self.assertEqual(len(log), 1)
        page = L.render_page(sprints={}, time_off=[], unplanned=log)
        self.assertEqual(L.parse_unplanned(page), log)
        self.assertEqual(L.merge_unplanned(log, sprints, drop=[("AA1", "Example, Ann", "2026-10-19")]), [])

    def test_a_page_with_no_log_reads_as_empty(self):
        self.assertEqual(L.parse_unplanned(L.render_page(sprints={}, time_off=[])), [])

    def test_ad_hoc_leave_is_an_unplanned_row_that_reroutes_nothing(self):
        rows = T.record_sick([], ANN, "2026-10-19", datetime.date(2026, 10, 19), kind=T.ADHOC)
        self.assertEqual(rows[0]["kind"], "Ad hoc leave")
        got = T.route(rows, [ANN], ANN, "question", datetime.date(2026, 10, 19))
        self.assertEqual((got["to"], got["away"]), ("Example, Ann", False))


class TabTest(unittest.TestCase):
    def test_the_tab_shows_the_counters_the_grid_and_the_workbook_copy(self):
        log = [entry("Example, Ann", "2026-10-19")]
        out = G.render_unplanned({"id": "unplanned_leave", "title": "Unplanned leave"}, log, "",
                                 datetime.date(2026, 10, 19), tracker())
        body = out["body"]
        self.assertIn("This year <b>4 days</b>", body)
        self.assertIn("Example, Ben", body)
        self.assertIn("Latest reported", body)
        self.assertIn("Team Capacity", body)
        self.assertIn("is sick today", body)

    def test_the_tab_says_why_when_the_tracker_is_missing(self):
        bad = {"source": "x", "imported_on": "2026-10-19", "tabs": [{"name": "Other", "cells": {}}]}
        out = G.render_unplanned({"id": "unplanned_leave", "title": "Unplanned leave"}, [], "",
                                 datetime.date(2026, 10, 19), bad)
        self.assertEqual(out["body"], "")
        self.assertIn("Leave tracker not read", out["note"])

    def test_the_scrum_master_has_the_tab_next_to_the_vacation_planner(self):
        import yaml
        with open(os.path.join(U.ROOT, ".devin", "rules", "dashboard-roles.yaml"), encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh)
        lens = next(v for k, v in cfg.items() if isinstance(v, dict) and "scrum_master" in v)["scrum_master"]
        i = lens["panels"].index("vacation_planner")
        self.assertEqual(lens["panels"][i + 1], "unplanned_leave")


if __name__ == "__main__":
    unittest.main()
