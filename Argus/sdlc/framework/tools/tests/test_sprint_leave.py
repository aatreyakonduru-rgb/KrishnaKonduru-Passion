"""Sprint leave page, capacity from it, the capacity-sheet export, and the Scrum Master follow-up lists."""
import datetime
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "..", "console"))

import capacity_sheet  # noqa: E402
import sprint_leave as L  # noqa: E402
import backlog  # noqa: E402

PEOPLE = [{"jira_user": "AA1", "name": "Ann Example", "allocation": 100},
          {"jira_user": "BB2", "name": "Ben Example", "allocation": 50},
          {"jira_user": "CC3", "name": "Cy Example", "allocation": 100}]


def sprint():
    s = L.new_sprint({"start": "2026-10-07", "end": "2026-10-27"}, PEOPLE)
    s["people"][0]["off"] = ["2026-10-12", "2026-10-13"]
    s["people"][1]["no_leave"] = True
    s["people"][2]["note"] = "half day & <b>"
    return s


class SprintLeaveTest(unittest.TestCase):
    def test_sprint_dates_come_from_jira_or_the_sprint_name(self):
        self.assertEqual(L.sprint_of("Acme Claims Sprint 26.4.3(10/28-11/17"),
                         {"token": "26.4.3", "start": "2026-10-28", "end": "2026-11-17"})
        self.assertEqual(L.sprint_of("Acme Claims Sprint 26.4.5(12/9-1/5/27")["end"], "2027-01-05")
        self.assertEqual(L.sprint_of("26.4.2", "2026-10-07T00:00", "2026-10-27")["start"], "2026-10-07")
        self.assertEqual(len(L.working_days("2026-10-07", "2026-10-27")), 15)

    def test_page_round_trips_and_keeps_answered_apart_from_silent(self):
        back = L.parse_page(L.render_page({"26.4.2": sprint()}))["26.4.2"]
        self.assertEqual(back["people"][0]["off"], ["2026-10-12", "2026-10-13"])
        self.assertTrue(back["people"][1]["no_leave"])
        self.assertFalse(back["people"][2]["no_leave"])
        self.assertEqual(back["people"][2]["note"], "half day & <b>")
        cap = L.capacity("26.4.2", back)
        self.assertEqual([p["answered"] for p in cap["people"]], [True, True, False])

    def test_capacity_is_days_in_times_six_times_share(self):
        cap = L.capacity("26.4.2", sprint())
        self.assertEqual([p["hours"] for p in cap["people"]], [78, 45, 90])
        self.assertEqual(cap["total_hours"], 213)
        self.assertEqual(capacity_sheet.day_label(cap, cap["people"][0]["off_days"][0]), "Mon 12 Oct")

    def test_holidays_and_dates_outside_the_sprint_are_dropped(self):
        s = sprint()
        s["holidays"] = ["2026-10-26"]
        s["people"][2]["off"] = ["2026-11-30", "2026-10-08"]
        clean = L.clean_sprint(s)
        self.assertEqual(clean["people"][2]["off"], ["2026-10-08"])
        self.assertEqual(L.capacity("26.4.2", clean)["sprint_days"], 14)
        with self.assertRaises(L.LeaveError):
            L.clean_sprint(dict(s, start=""))

    def test_capacity_sheet_export_reads_back_the_same(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = L.xlsx("26.4.2", sprint(), os.path.join(tmp, "c.xlsx"))
            read = capacity_sheet.read(path, "2026-10-07")
        self.assertEqual(read["total_hours"], 213)
        self.assertEqual(read["sprint_days"], 15)
        self.assertEqual([p["off_days"] for p in read["people"]], [[3, 4], [], []])


class FakeJira:
    via = ""
    token = "test"

    def __init__(self):
        self.sent = []

    def get(self, path, **params):
        if path.endswith("/transitions"):
            return {"transitions": [{"id": "221", "to": {"name": "On Hold"}}, {"id": "31", "to": {"name": "In Progress"}}]}
        if "sprint =" in params.get("jql", ""):
            def story(key, who, status, updated, subs):
                return {"key": key, "fields": {"summary": key, "status": {"name": status}, "updated": updated,
                                               "assignee": {"displayName": who}, "subtasks": [{"key": k} for k in subs]}}
            return {"issues": [story("ACME-1", "Ann", "In Progress", "2026-10-12", ["ACME-11"]),
                               story("ACME-2", "Ann", "In Progress", "2026-10-02", []),
                               story("ACME-3", "Ben", "In Progress", "2026-10-12", ["ACME-13"]),
                               story("ACME-4", "Cy", "On Hold", "2026-10-12", ["ACME-14"])]}

        def sub(key, parent, labels, done):
            return {"key": key, "fields": {"parent": {"key": parent}, "labels": labels, "updated": "2026-10-12",
                                           "assignee": {"displayName": "Resource 5"},
                                           "status": {"statusCategory": {"key": "done" if done else "new"}}}}
        return {"issues": [sub("ACME-11", "ACME-1", [], False), sub("ACME-13", "ACME-3", ["Question"], False),
                           sub("ACME-14", "ACME-4", ["Question"], True)]}

    def request(self, method, path, body):
        self.sent.append((method, path, body))
        return {}


class FollowupsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.jira = FakeJira()
        self.b = backlog.Backlog(self.jira, self.tmp.name, env={})

    def tearDown(self):
        self.tmp.cleanup()

    def test_lists_side_by_side_idle_waiting_and_answered(self):
        f = self.b.followups(1, 2, today=datetime.date(2026, 10, 12))
        self.assertEqual([(g["owner"], [r["key"] for r in g["stories"]]) for g in f["parallel"]], [("Ann", ["ACME-2", "ACME-1"])])
        self.assertEqual([r["key"] for r in f["idle"]], ["ACME-2"])
        self.assertEqual([(r["key"], r["waits"][0]["on"]) for r in f["hold"]], [("ACME-3", "Resource 5")])
        self.assertEqual([r["key"] for r in f["resume"]], ["ACME-4"])

    def test_hold_and_resume_are_previews_until_writes_are_on(self):
        c = self.b.hold("ACME-3", "waiting on Resource 5", "AA1")
        self.assertEqual(c["status"], "preview")
        self.assertEqual(c["calls"][0]["body"], {"transition": {"id": "221"}})
        self.assertEqual(self.b.resume("ACME-4", "AA1")["calls"][0]["body"], {"transition": {"id": "31"}})
        self.assertEqual(self.jira.sent, [])


    def test_ai_label_and_estimate_fixes_are_previews_until_writes_are_on(self):
        c = self.b.set_ai_label("ACME-11", "AI-Used", "AA1")
        self.assertEqual((c["status"], c["kind"]), ("preview", "ai_label"))
        self.assertEqual(c["calls"][0]["body"], {"update": {"labels": [{"add": "AI-Used"}]}})
        e = self.b.set_estimate("ACME-11", "4", "AA1")
        self.assertEqual(e["calls"][0]["body"], {"fields": {"timetracking": {"originalEstimate": "4h"}}})
        self.assertEqual(self.jira.sent, [])
        with self.assertRaises(backlog.BacklogError):
            self.b.set_ai_label("ACME-11", "AI-USED", "AA1")
        with self.assertRaises(backlog.BacklogError):
            self.b.set_estimate("ACME-11", "0", "AA1")

if __name__ == "__main__":
    unittest.main()
