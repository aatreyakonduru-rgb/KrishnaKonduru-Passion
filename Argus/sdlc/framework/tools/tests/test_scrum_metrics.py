"""The Scrum Master tabs: stand-up gaps, cycle time, commitment, DRE and AI use (scrum_metrics.py)."""
import datetime
import json
import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import capacity_sheet  # noqa: E402
import scrum_metrics as sm  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures",
                       "scrum-master-demo.json")
TODAY = datetime.date(2026, 10, 12)


def data():
    with open(FIXTURE, encoding="utf-8") as fh:
        return json.load(fh)


def capacity_xlsx(folder):
    """A two-person capacity sheet in the SharePoint layout: Wed 7 to Tue 13, weekend 10-11."""
    def col(i):
        return chr(65 + i) if i < 26 else "A" + chr(65 + i - 26)

    def cell(r, c, v):
        ref = "%s%d" % (col(c), r)
        if isinstance(v, str):
            return '<c r="%s" t="inlineStr"><is><t>%s</t></is></c>' % (ref, v)
        return '<c r="%s"><v>%s</v></c>' % (ref, v)
    rows = {1: {0: "Productive Hours =6", 1: 6, 2: "Sprint Days = 5"},
            2: {2: " Team  Member", 3: "PTO Plan", 5: "Office Location", 6: "%age of time on Project", 15: "Available hours"},
            3: {2: "Dev One", 4: "Dev", 5: "Offshore", 6: 1},
            4: {2: "Lead One", 4: "Dev", 5: "Onshore", 6: 0.5, 3: "13th"},
            5: {2: "unassigned", 6: 1}}
    for i, (day, wd) in enumerate(zip(range(7, 14), "WTFSSMT")):
        rows[1][8 + i] = day
        rows[2][8 + i] = wd
        rows[3][8 + i] = 0 if wd == "S" else 1
        rows[4][8 + i] = 0 if wd == "S" or day == 13 else 1
        rows[5][8 + i] = 1
    sheet = "".join('<row r="%d">%s</row>' % (r, "".join(cell(r, c, v) for c, v in sorted(cs.items())))
                    for r, cs in sorted(rows.items()))
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    path = os.path.join(folder, "capacity.xlsx")
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("xl/workbook.xml", '<workbook %s xmlns:r="%s"><sheets><sheet name="Notes" sheetId="1" '
                    'r:id="rId1"/><sheet name="Capacity " sheetId="2" r:id="rId2"/></sheets></workbook>' % (ns, rel))
        zf.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/'
                    '2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml"/><Relationship '
                    'Id="rId2" Target="worksheets/sheet2.xml"/></Relationships>')
        zf.writestr("xl/worksheets/sheet1.xml", '<worksheet %s><sheetData/></worksheet>' % ns)
        zf.writestr("xl/worksheets/sheet2.xml", '<worksheet %s><sheetData>%s</sheetData></worksheet>' % (ns, sheet))
    return path


class ScrumMetricsTests(unittest.TestCase):
    def setUp(self):
        self.rules = sm.load_rules()
        self.data = data()

    def test_rules_file_has_the_targets_from_the_call(self):
        t = self.rules["targets"]
        self.assertEqual((t["cycle_time_baseline_days"], t["story_throughput_floor"], t["team_capacity"]),
                         (12.8, 185.7, 181))
        self.assertEqual(self.rules["ai_labels"], ["AI-Used", "AI-NA"])

    def test_standup_lists_each_gap_with_its_owner(self):
        checks = {(r["key"], r["check"]) for r in sm.standup_rows(self.data, self.rules)}
        self.assertIn(("ACME-90002", "Story has no sub-tasks"), checks)
        self.assertIn(("ACME-90012", "Sub-task: no AI label"), checks)
        self.assertIn(("ACME-90011", "AI-Used sub-task logged 6.0h against a 4.0h estimate (exempted)"), checks)
        self.assertTrue(any(k == "ACME-90013" and "exact case" in c for k, c in checks))

    def test_standup_checks_the_story_itself(self):
        checks = {(r["key"], r["code"]) for r in sm.standup_rows(self.data, self.rules)}
        self.assertIn(("ACME-90001", "story_label"), checks)
        self.assertNotIn(("ACME-90003", "story_label"), checks)            # carries AI-Used
        self.assertIn(("ACME-90002", "no_time"), checks)                   # In Progress, nothing logged
        self.assertNotIn(("ACME-90001", "no_time"), checks)                # its sub-tasks have hours
        self.assertIn(("ACME-90001", "close_story"), checks)               # every sub-task closed

    def test_closed_story_with_open_sub_tasks_is_flagged(self):
        story = {"key": "ACME-1", "fields": {"summary": "s", "issuetype": {"name": "Story"}, "labels": ["AI-NA"],
                                             "status": {"name": "Closed", "statusCategory": {"key": "done"}},
                                             "subtasks": [{"key": "ACME-2"}]}}
        sub = {"key": "ACME-2", "fields": {"summary": "t", "labels": ["AI-NA"], "parent": {"key": "ACME-1"},
                                           "status": {"name": "Open", "statusCategory": {"key": "new"}}}}
        rows = sm.standup_rows({"stories": [story], "subtasks": [sub]}, self.rules)
        self.assertEqual([(r["code"], r["severity"]) for r in rows], [("open_subtasks", "hot")])

    def test_load_compares_points_with_capacity_after_leave(self):
        rows = {r["owner"]: r for r in sm.load_rows(self.data, self.rules)}
        self.assertEqual((rows["Dev One"]["points"], rows["Dev One"]["capacity"], rows["Dev One"]["over"]), (8, 7.5, 0.5))
        self.assertEqual(rows["Dev Two"]["over"], 0)
        self.assertIn("Dev One (+0.5)", sm.render("load", self.data, self.rules, TODAY)[0])

    def test_load_matches_names_in_either_order(self):
        story = {"key": "ACME-1", "fields": {"issuetype": {"name": "Story"}, "assignee": {"displayName": "Resource 3"},
                                             sm.F_POINTS: 3}}
        data = {"stories": [story], "capacity": {"people": [{"name": "Resource 3", "hours": 16}]}}
        self.assertEqual([(r["owner"], r["points"], r["over"]) for r in sm.load_rows(data, self.rules)],
                         [("Resource 3", 3, 1.0)])

    def test_leave_calendar_marks_days_off_and_who_has_not_answered(self):
        body, off, attention = sm.render("leave", self.data, self.rules, TODAY)
        self.assertEqual((off, attention), (9, "hot"))
        self.assertIn("Lead One <em>(not answered)</em>", body)
        self.assertNotIn("Sat", body)
        self.assertEqual(sm.unanswered(self.data), ["Lead One"])

    def test_cycle_time_runs_from_in_progress_to_ready_for_release_or_closed(self):
        c = sm.cycle_summary(self.data, self.rules, TODAY)
        self.assertEqual((c["average"], c["finished"]), (12.0, 2))
        self.assertEqual([r["key"] for r in c["open"]], ["ACME-90001", "ACME-90002"])
        self.assertEqual(c["open"][0]["days"], 11)
        self.assertEqual(c["parallel"], {"Dev One": ["ACME-90001", "ACME-90002"]})

    def test_time_on_hold_is_left_out_of_cycle_time(self):
        def story(key, now, moves):
            return {"key": key, "fields": {"summary": key, "status": {"name": now}, "assignee": {"displayName": "Dev One"}},
                    "changelog": {"histories": [{"created": d + "T09:00:00", "items": [{"field": "status", "toString": to}]}
                                                for d, to in moves]}}
        done = story("ACME-1", "Closed", [("2026-09-01", "In Progress"), ("2026-09-03", "On Hold"),
                                          ("2026-09-08", "In Progress"), ("2026-09-10", "Closed")])
        waiting = story("ACME-2", "On Hold", [("2026-10-01", "In Progress"), ("2026-10-05", "On Hold")])
        back = story("ACME-3", "In Progress", [("2026-10-01", "In Progress"), ("2026-10-02", "On Hold"),
                                               ("2026-10-09", "In Progress")])
        c = sm.cycle_summary({"finished": [done], "stories": [waiting, back]}, self.rules, TODAY)
        self.assertEqual(c["average"], 4.0)
        self.assertEqual([(r["key"], r["days"], r["held"]) for r in c["open"]], [("ACME-3", 4, 7)])
        self.assertEqual([(r["key"], r["on_hold"], r["days"]) for r in c["on_hold"]], [("ACME-2", 7, 4)])
        self.assertEqual(c["parallel"], {})

    def test_commitment_sums_story_points_and_lists_unpointed(self):
        self.assertEqual(sm.commitment_summary(self.data), {"stories": 3, "points": 8, "unpointed": ["ACME-90003"]})

    def test_dre_is_one_minus_production_over_all_environments(self):
        d = sm.dre_summary(self.data, self.rules)
        self.assertEqual((d["total"], d["production"], d["dre"]), (4, 1, 0.75))

    def test_ai_month_counts_exempted_and_wrong_case_apart(self):
        a = sm.ai_summary(self.data, self.rules)
        self.assertEqual((a["closed"], a["used"], a["na"], a["no_label"], a["wrong_case"], a["exempted"]),
                         (5, 1, 1, 1, 1, 1))
        self.assertEqual(a["labelled_pct"], 60.0)
        self.assertEqual(a["efficiency_pct"], 50.0)   # 4h estimated, 2h logged; the exempted one stays out

    def test_every_view_renders_and_flags_what_is_unsettled(self):
        for view in sm.VIEWS:
            body, _, attention = sm.render(view, self.data, self.rules, TODAY)
            self.assertTrue(body, view)
            if view not in sm.INFO_VIEWS:
                self.assertEqual(attention, "hot", view)
        self.assertIn("To confirm:", sm.render("dre", self.data, self.rules, TODAY)[0])

    def test_empty_data_shows_nothing(self):
        for view in sm.VIEWS:
            self.assertEqual(sm.render(view, {}, self.rules, TODAY), ("", 0, "clear"))

    def test_fetch_only_reads(self):
        calls = []

        def get(path, **params):
            calls.append(path)
            return {"issues": [], "total": 0}
        sm.fetch(get, lambda j: j, {"id": 1, "name": "S"}, self.rules)
        self.assertTrue(calls and all(p == "/api/2/search" for p in calls))

    def test_capacity_sheet_is_read_the_way_its_formulas_work(self):
        with tempfile.TemporaryDirectory() as folder:
            cap = capacity_sheet.read(capacity_xlsx(folder), "2026-10-07")
        self.assertEqual((cap["productive_hours"], cap["sprint_days"]), (6.0, 5))
        one, lead, unassigned = cap["people"]
        self.assertEqual((one["name"], one["role"], one["available_days"], one["hours"]), ("Dev One", "Dev", 5, 30.0))
        self.assertEqual((lead["available_days"], lead["hours"], lead["pto_note"]), (4, 12.0, "13th"))
        self.assertEqual([capacity_sheet.day_label(cap, i) for i in lead["off_days"]], ["Tue 13 Oct"])
        self.assertEqual(unassigned["hours"], 0.0)
        self.assertEqual(cap["total_hours"], 42.0)

    def test_commitment_uses_the_capacity_sheet_when_there_is_one(self):
        body, _, _ = sm.render("commitment", self.data, self.rules, TODAY)
        self.assertIn("33.0", body)            # 264 hours / 8
        self.assertIn("264 team hours", body)
        self.assertIn("Dev Two", body)
        self.assertIn("Mon 19 Oct", body)      # Dev Two's first day off
        self.assertNotIn("To confirm", body)
        no_sheet = dict(self.data)
        no_sheet.pop("capacity")
        body, _, _ = sm.render("commitment", no_sheet, self.rules, TODAY)
        self.assertIn("181", body)
        self.assertIn("To confirm: No capacity sheet", body)


if __name__ == "__main__":
    unittest.main()


def issue(key, status, category, **f):
    return {"key": key, "fields": dict({"summary": key, "status": {"name": status, "statusCategory": {"key": category}},
                                        "assignee": {"displayName": "Dev One"}}, **f)}


class SprintCloseTests(unittest.TestCase):
    def setUp(self):
        self.rules = sm.load_rules()
        hour = 3600
        self.data = {"sprint": {"name": "S1"}, "stories": [
            issue("ACME-1", "Ready for Approval", "indeterminate", issuetype={"name": "Story"}, labels=["AI-Used"],
                  timeoriginalestimate=8 * hour, aggregatetimespent=6 * hour, subtasks=[{"key": "ACME-11"}]),
            issue("ACME-2", "In Progress", "indeterminate", issuetype={"name": "Story"}, labels=["AI-USED"],
                  subtasks=[{"key": "ACME-21"}, {"key": "ACME-22"}])],
            "subtasks": [
                issue("ACME-11", "Closed", "done", parent={"key": "ACME-1"}, labels=["AI-Used"],
                      timeoriginalestimate=8 * hour, timespent=6 * hour),
                issue("ACME-21", "Open", "new", parent={"key": "ACME-2"}),
                issue("ACME-22", "Resolved", "done", parent={"key": "ACME-2"}, labels=["AI-NA"],
                      timeoriginalestimate=hour, timespent=hour)]}

    def test_a_story_ready_to_close_has_no_row(self):
        self.assertNotIn("ACME-1", [r["key"] for r in sm.close_rows(self.data, self.rules)])

    def test_each_gap_is_listed_on_the_story_and_the_sub_task(self):
        rows = {r["key"]: r for r in sm.close_rows(self.data, self.rules)}
        self.assertEqual(sorted(rows), ["ACME-2", "ACME-21"])
        story = " | ".join(rows["ACME-2"]["gaps"])
        for gap in ("1 sub-task(s) not closed: ACME-21", "not the exact case",
                    "No original estimate", "Status is In Progress"):
            self.assertIn(gap, story)
        self.assertEqual(rows["ACME-21"]["story"], "ACME-2")
        self.assertEqual(rows["ACME-21"]["gaps"], ["No hours logged", "No AI label", "No original estimate",
                                                   "Status is Open"])

    def test_story_time_is_the_time_on_its_sub_tasks(self):
        self.assertNotIn("No time logged", " ".join(sm.close_rows(self.data, self.rules)[0]["gaps"]))
        none = dict(self.data, subtasks=[dict(t, fields=dict(t["fields"], timespent=0)) for t in self.data["subtasks"]])
        rows = {r["key"]: r for r in sm.close_rows(none, self.rules)}
        self.assertIn("No time logged", rows["ACME-2"]["gaps"])

    def test_only_listed_statuses_count_when_done_category_is_off(self):
        rules = dict(self.rules, sprint_close={"accepted_statuses": ["Ready for Approval"], "done_category_counts": False})
        rows = {r["key"]: r for r in sm.close_rows(self.data, rules)}
        self.assertIn("Status is Resolved", rows["ACME-22"]["gaps"])

    def test_tab_counts_stories_ready_and_exceptions(self):
        body, count, attention = sm.render("close", self.data, self.rules, TODAY)
        self.assertEqual((count, attention), (2, "hot"))
        self.assertIn("Ready to close", body)
        self.assertIn("To confirm:", body)
        clean = dict(self.data, stories=self.data["stories"][:1], subtasks=self.data["subtasks"][:1])
        self.assertEqual(sm.render("close", clean, self.rules, TODAY)[1:], (0, "info"))
