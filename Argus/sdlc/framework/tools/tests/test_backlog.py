"""Backlog tab: reads through Argus's Jira object, every write planned and shown, nothing sent
unless writes are on AND the ticket is allow-listed."""
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from unittest import mock
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

HOME = tempfile.mkdtemp(prefix="sdlc-backlog-test-")
os.environ.setdefault("SDLC_CONSOLE_HOME", HOME)
os.environ["SDLC_WORKBENCH_READ_REMOTE"] = "0"
CONSOLE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "console")

JS_PARTS = ("console.js", "console-run.js", "console-pc.js", "console-backlog.js", "console-auto.js", "console-main.js", "console-feedback.js")


def workbench_js():
    """Argus page script: its parts, in the order index.html loads them."""
    out = []
    for name in JS_PARTS:
        with open(os.path.join(CONSOLE, "static", name), encoding="utf-8") as fh:
            out.append(fh.read())
    return "\n".join(out)
sys.path.insert(0, CONSOLE)

import backlog  # noqa: E402
import pctest  # noqa: E402
import server as wb  # noqa: E402

STORY = {"key": "ACME-90201", "fields": {
    "summary": "Approval stamp columns - DEV", "description": "desc", "issuetype": {"name": "Story"},
    "labels": ["AI-Used", "requested-by-someone"], "priority": {"name": "P2"}, backlog.F_ACCEPTANCE: "1. a\n2. b",
    backlog.F_EPIC_LINK: "ACME-90100", backlog.F_PRIORITY: {"value": "P2"}, backlog.F_POINTS: 3,
    "subtasks": [{"key": "ACME-90202", "fields": {"summary": "DEV- grid column", "issuetype": {"name": "Sub-task"}}}]}}


class RecordingJira:
    """Direct-Jira shape: get() answers searches and issues, request() records writes."""
    token = "t"
    via = "here"

    def __init__(self):
        self.writes = []
        self.gets = []

    def get(self, path, **params):
        self.gets.append((path, params))
        if path.startswith("/agile/1.0/board/"):
            return {"values": [{"id": 7, "name": "26.4.3", "state": params["state"],
                                "startDate": "2026-10-20T00:00:00Z"}]}
        if path.startswith("/api/2/issue/"):
            return STORY
        return {"issues": [STORY]}

    def stories(self, scope, jira_user="", with_description=False):
        return {"jql": wb.JQL[scope], "stories": [{"key": "ACME-90201", "summary": "x", "sprint": ""}]}

    def request(self, method, path, payload=None):
        self.writes.append((method, path, payload))
        return {"key": "ACME-99999"}


class PrecheckTests(unittest.TestCase):
    def test_story_draft_checks(self):
        draft = {"type": "Story", "summary": "Thing", "acceptance": "do it", "labels": []}
        checks = {c["check"] for c in backlog.precheck(draft)}
        self.assertEqual(checks, {"AC_UNNUMBERED", "EPIC_LINK_MISSING", "PHASE_SUFFIX_MISSING", "PRIORITY_MISSING",
                                  "AI_LABEL_MISSING", "SPECIALTY_MISSING"})
        clean = backlog.precheck({"type": "Story", "summary": "EOC - Thing - DEV", "acceptance": "1. a\n2. b", "epic": "ACME-1",
                                  "priority": "P2", "labels": ["AI-Used"]})
        self.assertEqual(clean, [])

    def test_placeholder_and_case(self):
        checks = {c["check"] for c in backlog.precheck({"type": "Story", "summary": "T - dev", "epic": "ACME-1", "priority": "P1",
                                                        "acceptance": "Please Enter Acceptance Criteria", "labels": ["ai-used"]})}
        self.assertIn("AC_PLACEHOLDER", checks)
        self.assertIn("PHASE_SUFFIX_CASE", checks)
        self.assertIn("LABEL_CASE", checks)

    def test_epic_checks(self):
        checks = {c["check"] for c in backlog.precheck({"type": "Epic", "summary": "ProgramC Q3 2026", "description": "short"})}
        self.assertEqual(checks, {"EPIC_DESCRIPTION_THIN", "EPIC_TITLE_DATED", "SPECIALTY_MISSING",
                                  "EPIC_SOURCE_LINK_MISSING", "EPIC_OUTCOMES_MISSING"})
        ok = backlog.precheck({"type": "Epic", "summary": "Threshold overrides", "description": "x" * 90,
                               "specialty": "Foundational", "brd": "https://confluence.example/pages/1",
                               "acceptance": "1. a\n2. b"})
        self.assertEqual(ok, [])


class SpecialtyTests(unittest.TestCase):
    def test_specialty_list_and_precheck(self):
        names = backlog.specialties()
        self.assertIn("EOC", names)
        self.assertEqual(names[-1], "Platform")
        base = {"type": "Story", "acceptance": "1. a", "epic": "ACME-1", "priority": "P2", "labels": ["AI-Used"]}
        bad = backlog.precheck(dict(base, summary="Threshold override screen - DEV"))
        self.assertIn("SPECIALTY_MISSING", [c["check"] for c in bad])
        good = backlog.precheck(dict(base, summary="EOC - Threshold override screen - DEV"))
        self.assertNotIn("SPECIALTY_MISSING", [c["check"] for c in good])
        epic = dict(base, type="Epic", summary="EOC Threshold overrides", description="x" * 90, specialty="EOC",
                    acceptance="1. a\n2. b", brd="https://confluence.example/pages/1")
        self.assertEqual(backlog.precheck(epic), [])


class SubtaskEstimateTests(unittest.TestCase):
    def test_hours_reference_from_matrix(self):
        self.assertEqual(backlog.story_hours(3), 16.0)
        self.assertEqual(backlog.story_hours(5), 32.0)
        self.assertIsNone(backlog.story_hours(""))
        self.assertEqual(backlog.jira_duration(6.5), "6h 30m")
        self.assertEqual(backlog.split_estimate(16, 6), [3.0, 3.0, 2.5, 2.5, 2.5, 2.5])

    def test_defaults_sum_to_story(self):
        rows = backlog.default_subtasks({"points": 3, "subtasks": []})
        self.assertEqual([r["summary"] for r in rows], list(backlog.DEV_SUBTASKS))
        self.assertEqual(sum(r["hours"] for r in rows), 16.0)
        rows = backlog.default_subtasks({"points": 2,
                                         "subtasks": [{"summary": "DEV- a", "hours": 5}, "DEV- b", "DEV- c"]})
        self.assertEqual([r["hours"] for r in rows], [5.0, 1.5, 1.5])
        self.assertEqual(backlog.default_subtasks({"points": 2}), [], "no sub-tasks asked for")

    def test_standard_set_follows_phase(self):
        def names(**d):
            return [r["summary"] for r in backlog.default_subtasks(dict(d, points=3, subtasks=[]))]
        self.assertEqual(names(summary="EOC - Stamp - DEV"), list(backlog.DEV_SUBTASKS))
        self.assertEqual(len(backlog.DEV_SUBTASKS), 8)
        self.assertEqual(names(summary="EOC - Stamp - SIT"), list(backlog.SIT_SUBTASKS))
        self.assertEqual(names(summary="EOC - Stamp - uat"), list(backlog.UAT_SUBTASKS))
        perf = names(summary="EOC - Stamp - DEV", acceptance="1. The grid loads within 3 seconds")
        self.assertEqual(perf[perf.index("DEV- Unit and integration testing") + 1], backlog.PERF_SUBTASK)
        self.assertEqual(len(perf), 9)
        self.assertNotIn(backlog.PERF_SUBTASK, names(summary="EOC - Stamp - SIT", acceptance="1. within 3 seconds"))

    def test_standard_sets_match_rule_book(self):
        import yaml
        with open(os.path.join(backlog.team.ROOT, ".devin", "rules", "jira-ticket-standards.yaml"), encoding="utf-8") as fh:
            sets = yaml.safe_load(fh)["subtask"]["standard_sets"]
        self.assertEqual(sets["dev"], list(backlog.DEV_SUBTASKS))
        self.assertEqual(sets["dev_when_performance_targets"], [backlog.PERF_SUBTASK])
        self.assertEqual(sets["sit"], list(backlog.SIT_SUBTASKS))
        self.assertEqual(sets["uat"], list(backlog.UAT_SUBTASKS))
        bad = backlog.precheck({"type": "Story", "summary": "EOC - S - DEV", "acceptance": "1. a", "epic": "ACME-1",
                                "priority": "P2", "labels": ["AI-Used"], "points": 2,
                                "subtasks": [{"summary": "DEV- a", "hours": 5}]})
        self.assertEqual([c["check"] for c in bad], ["SUBTASK_ESTIMATE_SUM"])


class BacklogTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="sdlc-bl-")
        self.jira = RecordingJira()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def make(self, env=None):
        return backlog.Backlog(self.jira, self.dir, env=env or {})

    def test_previews_only_by_default(self):
        b = self.make()
        c = b.set_points("acme-90201", "5", "dev.user")
        self.assertEqual(c["status"], "preview")
        self.assertEqual(c["calls"][0], {"method": "PUT", "path": "/api/2/issue/ACME-90201",
                                         "body": {"fields": {backlog.F_POINTS: 5}}})
        self.assertIn("dev.user", c["calls"][1]["body"]["body"])
        self.assertIn(backlog.WRITES_ENV, c["note"])
        self.assertEqual(self.jira.writes, [])
        self.assertEqual(b.list_previews()[0]["id"], c["id"])
        again = backlog.Backlog(self.jira, self.dir, env={})
        self.assertEqual(again.list_previews()[0]["id"], c["id"], "previews survive a restart")

    def test_bulk_draft_lists_every_ticket_and_records_nothing(self):
        b = self.make()
        d = b.bulk(["acme-90201", "ACME-90202", "ACME-90201"], "points", "3", "dev.user")
        self.assertEqual(d["status"], "draft")
        self.assertEqual(d["keys"], ["ACME-90201", "ACME-90202"])
        self.assertEqual(d["lines"], ["ACME-90201 \u2192 3 points", "ACME-90202 \u2192 3 points"])
        self.assertEqual(b.list_previews(), [])
        self.assertEqual(self.jira.writes, [])

    def test_bulk_send_is_one_change_and_stays_preview_while_writes_off(self):
        b = self.make()
        c = b.bulk(["ACME-90201", "ACME-90202"], "assignee", "dev.two", "dev.user", send=True)
        self.assertEqual(c["status"], "preview")
        self.assertEqual(c["kind"], "bulk")
        self.assertEqual(c["calls"][0], {"method": "PUT", "path": "/api/2/issue/ACME-90201",
                                         "body": {"fields": {"assignee": {"name": "dev.two"}}}})
        self.assertEqual(len(c["calls"]), 4)
        self.assertEqual(len(b.list_previews()), 1)
        self.assertEqual(self.jira.writes, [])
        e = b.bulk(["ACME-90201"], "epic", "acme-1", "dev.user", send=True)
        self.assertEqual(e["calls"][0]["body"]["fields"], {backlog.F_EPIC_LINK: "ACME-1"})

    def test_bulk_rejects_unknown_field_and_bad_points(self):
        b = self.make()
        with self.assertRaises(backlog.BacklogError):
            b.bulk(["ACME-90201"], "status", "Done", "dev.user")
        with self.assertRaises(backlog.BacklogError):
            b.bulk(["ACME-90201"], "points", "lots", "dev.user")
        with self.assertRaises(backlog.BacklogError):
            b.bulk([], "points", "3", "dev.user")

    def test_writes_on_but_ticket_not_allowed_stays_preview(self):
        b = self.make({backlog.WRITES_ENV: "1", backlog.TICKETS_ENV: "ACME-1"})
        c = b.move(["ACME-90201"], {"id": 7, "name": "26.4.3"}, "dev.user")
        self.assertEqual(c["status"], "preview")
        self.assertIn("allow-list", c["note"])
        self.assertEqual(self.jira.writes, [])

    def test_writes_on_and_allowed_sends(self):
        b = self.make({backlog.WRITES_ENV: "1", backlog.TICKETS_ENV: "acme-90201, ACME-2"})
        c = b.move(["ACME-90201"], 7, "dev.user")
        self.assertEqual(c["status"], "applied")
        self.assertEqual(self.jira.writes[0], ("POST", "/agile/1.0/sprint/7/issue", {"issues": ["ACME-90201"]}))
        self.assertEqual(self.jira.writes[1][1], "/api/2/issue/ACME-90201/comment")
        back = b.move(["ACME-90201"], "backlog", "dev.user")
        self.assertEqual(back["calls"][0]["path"], "/agile/1.0/backlog/issue")

    def test_create_blocked_by_rule_book_unless_forced(self):
        b = self.make()
        with self.assertRaises(backlog.BacklogError) as cm:
            b.create({"type": "Story", "summary": "No AC", "labels": []}, "dev.user")
        self.assertEqual(cm.exception.status, 422)
        c = b.create({"type": "Story", "summary": "No AC", "labels": [], "force": True}, "dev.user")
        self.assertEqual(c["status"], "preview")
        fields = c["calls"][0]["body"]["fields"]
        self.assertIn("requested-by-dev-user", fields["labels"])
        self.assertEqual(fields[backlog.F_IT_TEAM], [{"value": backlog.IT_TEAM}])
        self.assertTrue(any(k["check"] == "AC_MISSING" for k in c["checks"]))

    def test_create_gated_on_parent_epic(self):
        b = self.make({backlog.WRITES_ENV: "1", backlog.TICKETS_ENV: "ACME-90100"})
        draft = {"type": "Story", "summary": "EOC - Stamp - DEV", "acceptance": "1. a", "epic": "ACME-90100", "priority": "P2",
                 "labels": ["AI-Used"]}
        c = b.create(draft, "dev.user")
        self.assertEqual(c["status"], "applied")
        self.assertEqual(c["created"], "ACME-99999")
        other = b.create(dict(draft, epic="ACME-5"), "dev.user")
        self.assertEqual(other["status"], "preview")

    def test_create_with_subtasks_previews_parent_and_estimates(self):
        b = self.make()
        c = b.create({"type": "Story", "summary": "EOC - Stamp - DEV", "acceptance": "1. a", "epic": "ACME-90100",
                      "priority": "P2", "labels": ["AI-Used"], "points": 2, "subtasks": []}, "dev.user")
        self.assertEqual(len(c["calls"]), 9)
        self.assertEqual(c["calls"][0]["body"]["fields"]["timetracking"], {"originalEstimate": "8h"})
        sub = c["calls"][1]["body"]["fields"]
        self.assertEqual((sub["issuetype"], sub["parent"]), ({"name": "Sub-task"}, {"key": "<new story>"}))
        self.assertEqual(sub["labels"], ["AI-Used", backlog.DEVIN_CREATED_LABEL])
        self.assertIn(backlog.DEVIN_CREATED_LABEL, c["calls"][0]["body"]["fields"]["labels"])
        self.assertEqual([x["body"]["fields"]["timetracking"]["originalEstimate"] for x in c["calls"][1:]],
                         ["1h"] * 8)
        self.assertIn("8 sub-tasks (8h)", c["title"])
        self.assertEqual(self.jira.writes, [])
        live = self.make({backlog.WRITES_ENV: "1", backlog.TICKETS_ENV: "ACME-90100"})
        c = live.create({"type": "Story", "summary": "EOC - Stamp - DEV", "acceptance": "1. a", "epic": "ACME-90100",
                         "priority": "P2", "labels": ["AI-Used"], "points": 1, "subtasks": ["DEV- only"]}, "dev.user")
        self.assertEqual(c["status"], "applied")
        self.assertEqual(self.jira.writes[1][2]["fields"]["parent"], {"key": "ACME-99999"})

    def test_add_subtasks_needs_an_estimate_on_every_row(self):
        with self.assertRaises(backlog.BacklogError):
            backlog.clean_subtasks([{"summary": "DEV- Backend", "hours": ""}])
        with self.assertRaises(backlog.BacklogError):
            backlog.clean_subtasks([{"summary": "DEV- Backend", "hours": 0}])
        with self.assertRaises(backlog.BacklogError):
            backlog.clean_subtasks([{"summary": "a", "hours": 1}, {"summary": "A ", "hours": 2}])
        with self.assertRaises(backlog.BacklogError):
            backlog.clean_subtasks([{"summary": " ", "hours": 1}])
        self.assertEqual(backlog.clean_subtasks([{"summary": "  DEV-  Backend ", "hours": "2.6"}]),
                         [{"key": "", "summary": "DEV- Backend", "hours": 2.5, "description": ""}])
        with self.assertRaises(backlog.BacklogError):
            backlog.clean_subtasks([{"key": "not a key", "summary": "a", "hours": 1}])

    def test_add_subtasks_previews_then_writes_under_the_story(self):
        rows = [{"summary": "DEV- Backend implementation", "hours": 4}, {"summary": "DEV- Unit tests", "hours": 1.5}]
        c = self.make().add_subtasks("acme-90201", rows, "dev.user", "dev.user")
        self.assertEqual(c["status"], "preview")
        self.assertEqual(len(c["calls"]), 3)
        sub = c["calls"][0]["body"]["fields"]
        self.assertEqual((sub["issuetype"], sub["parent"]), ({"name": "Sub-task"}, {"key": "ACME-90201"}))
        self.assertEqual(sub["timetracking"], {"originalEstimate": "4h"})
        self.assertEqual(c["calls"][1]["body"]["fields"]["timetracking"], {"originalEstimate": "1h 30m"})
        self.assertEqual(sub["labels"], ["AI-Used", backlog.DEVIN_CREATED_LABEL])
        self.assertEqual(sub["assignee"], {"name": "dev.user"})
        self.assertIn("2 sub-tasks added (5h 30m", c["calls"][2]["body"]["body"])
        self.assertEqual(self.jira.writes, [])
        live = self.make({backlog.WRITES_ENV: "1", backlog.TICKETS_ENV: "ACME-90201"})
        c = live.add_subtasks("ACME-90201", rows, "dev.user")
        self.assertEqual(c["status"], "applied")
        self.assertEqual(c["created"], ["ACME-99999", "ACME-99999"])
        self.assertEqual(len(self.jira.writes), 3)

    def test_add_subtasks_updates_only_the_storys_own_sub_tasks(self):
        b = self.make()
        b.subtasks = lambda key: [{"key": key}, {"key": "ACME-90210"}]
        rows = [{"key": "acme-90210", "summary": "DEV- Backend implementation", "hours": 3,
                 "description": "server.py:_gate_subtasks; add the PUT; AC 2"},
                {"summary": "DEV- Unit tests", "hours": 1, "description": "test_backlog.py"}]
        c = b.add_subtasks("ACME-90201", rows, "dev.user", why="Added at SDLC_04.")
        self.assertEqual(c["calls"][0], {"method": "PUT", "path": "/api/2/issue/ACME-90210", "body": {"fields": {
            "summary": "DEV- Backend implementation", "timetracking": {"originalEstimate": "3h"},
            "description": "server.py:_gate_subtasks; add the PUT; AC 2"}}})
        self.assertEqual(c["calls"][1]["body"]["fields"]["description"], "test_backlog.py\n\nAdded at SDLC_04.")
        self.assertIn("1 sub-tasks added, 1 updated (4h", c["calls"][2]["body"]["body"])
        self.assertEqual(c["keys"], ["ACME-90201", "ACME-90210"])
        with self.assertRaises(backlog.BacklogError):
            b.add_subtasks("ACME-90201", [{"key": "ACME-1", "summary": "x", "hours": 1}], "dev.user")

    def test_order_links_and_move_guard(self):
        b = self.make()
        c = b.order(["acme-1", "ACME-2", "ACME-3"], "finance needs 1 live first", "dev.user")
        links = [x["body"] for x in c["calls"] if x["path"] == "/api/2/issueLink"]
        self.assertEqual([(ln["inwardIssue"]["key"], ln["outwardIssue"]["key"]) for ln in links],
                         [("ACME-1", "ACME-2"), ("ACME-2", "ACME-3")])
        self.assertTrue(c["title"].startswith("Order: ACME-1 \u2192 ACME-2 \u2192 ACME-3 \u2014 finance"))
        self.assertEqual(c["status"], "preview")
        with self.assertRaises(backlog.BacklogError):
            b.order(["ACME-1"], "", "k")
        blocked = dict(STORY, fields=dict(STORY["fields"], issuelinks=[{
            "type": {"name": "Blocks"}, "inwardIssue": {"key": "ACME-90100", "fields": {
                "summary": "first", "status": {"statusCategory": {"key": "indeterminate"}}}}}]))
        blocker = {"fields": {"summary": "first", backlog.F_SPRINT: ["com.atlassian...[id=9,name=26.4.4,state=FUTURE]"]}}
        self.jira.get = lambda path, **kw: blocker if path.endswith("ACME-90100") else blocked
        with self.assertRaises(backlog.BacklogError) as cm:
            b.move(["ACME-90201"], {"id": 7, "name": "26.4.3"}, "k")
        self.assertEqual(cm.exception.status, 409)
        self.assertEqual(b.move(["ACME-90201"], {"id": 8, "name": "26.4.4"}, "k")["status"], "preview")
        self.assertEqual(b.move(["ACME-90201"], "backlog", "k")["status"], "preview")
        self.assertEqual(backlog.sprint_rank({"start": "2026-11-03"}), ("d", "2026-11-03"))

    def test_blockers_for_many_tickets_take_two_searches(self):
        b = self.make()

        def link(key, cat="new"):
            return {"type": {"name": "Blocks"}, "inwardIssue": {"key": key, "fields": {
                "summary": key, "status": {"statusCategory": {"key": cat}}}}}

        gets = []

        def get(path, **kw):
            gets.append(path)
            if kw.get("fields") == "issuelinks":
                return {"issues": [{"key": "ACME-1", "fields": {"issuelinks": [link("ACME-3"), link("ACME-5", "done")]}},
                                   {"key": "ACME-2", "fields": {"issuelinks": [link("ACME-3"), link("ACME-4")]}}]}
            return {"issues": [{"key": "ACME-3", "fields": {"summary": "three", backlog.F_SPRINT: [
                "com.atlassian...[id=9,name=26.4.4,state=FUTURE]"]}},
                {"key": "ACME-4", "fields": {"summary": "four", backlog.F_SPRINT: [{"name": "26.4.3"}]}}]}

        self.jira.get = get
        found = b.blockers_of(["ACME-1", "ACME-2"])
        self.assertEqual(gets, ["/api/2/search", "/api/2/search"])
        self.assertEqual(found["ACME-1"], [{"key": "ACME-3", "summary": "three", "sprint": "26.4.4"}])
        self.assertEqual([x["sprint"] for x in found["ACME-2"]], ["26.4.4", "26.4.3"])
        self.assertEqual(b.blockers("ACME-1"), found["ACME-1"])

    def test_raise_question_and_defect(self):
        b = self.make()
        q = b.raise_item("acme-90201", "clarification", "Is the threshold inclusive?", "", "qa.user", assignee="dev.user")
        f = q["calls"][0]["body"]["fields"]
        self.assertEqual(f["parent"], {"key": "ACME-90201"})
        self.assertIn("asked-by-qa.user", f["labels"])
        self.assertTrue(f["summary"].startswith("Clarification from qa.user:"))
        self.assertEqual(q["status"], "preview")
        with self.assertRaises(backlog.BacklogError):
            b.raise_item("ACME-90201", "question", "x", "", "qa.user")
        d = b.raise_item("ACME-90201", "defect", "Saves twice", "1. click save", "qa.user",
                         severity="High", environment="TEST - User Acceptance Test (UAT)")
        f = d["calls"][0]["body"]["fields"]
        self.assertEqual(f["issuetype"], {"id": "11"})
        self.assertEqual(f["customfield_10013"], {"value": "High"})
        self.assertEqual(d["calls"][1]["body"]["type"], {"name": "Defect"})
        with self.assertRaises(backlog.BacklogError):
            b.raise_item("ACME-90201", "defect", "x", "", "qa.user", severity="Huge", environment="Dev")
        with self.assertRaises(backlog.BacklogError):
            b.raise_item("ACME-90201", "gripe", "x", "", "qa.user")

    def test_create_blocked_by(self):
        b = self.make()
        c = b.create({"type": "Story", "summary": "EOC - C - DEV", "acceptance": "1. a", "epic": "ACME-90100",
                      "priority": "P2", "labels": ["AI-Used"], "blocked_by": ["ACME-1", "ACME-2"],
                      "order_why": "after the API"}, "dev.user")
        self.assertTrue(c["calls"][0]["body"]["fields"]["description"].startswith(
            "Order: ACME-1 \u2192 ACME-2 \u2192 this \u2014 after the API"))
        self.assertEqual(c["calls"][-1]["body"]["outwardIssue"], {"key": "<new story>"})

    def test_source_brd_line_on_story_and_subtasks(self):
        b = self.make()
        brd = "https://confluence.example/pages/1"
        c = b.create({"type": "Story", "summary": "EOC - Stamp - DEV", "acceptance": "1. a", "epic": "ACME-90100",
                      "priority": "P2", "labels": ["AI-Used"], "points": 2, "brd": brd, "description": "As a PO",
                      "subtasks": []},
                     "dev.user")
        self.assertEqual(c["calls"][0]["body"]["fields"]["description"], "Source BRD: %s\n\nAs a PO" % brd)
        self.assertEqual(c["calls"][1]["body"]["fields"]["description"], "Source BRD: " + brd)
        same = backlog.with_source({"brd": brd, "description": "See %s" % brd})
        self.assertEqual(same, "See %s" % brd)

    def test_epic_precheck_wants_link_and_outcomes(self):
        thin = {"type": "Epic", "summary": "Stamp", "specialty": "EOC", "description": "x" * 90}
        codes = {k["check"] for k in backlog.precheck(thin)}
        self.assertIn("EPIC_SOURCE_LINK_MISSING", codes)
        self.assertIn("EPIC_OUTCOMES_MISSING", codes)
        ready = dict(thin, brd="https://confluence.example/pages/1", acceptance="1. a\n2. b")
        codes = {k["check"] for k in backlog.precheck(ready)}
        self.assertFalse(codes & {"EPIC_SOURCE_LINK_MISSING", "EPIC_OUTCOMES_MISSING"})

    def test_clone_clears_sprint_and_requester_labels(self):
        b = self.make()
        c = b.clone("ACME-90201", "dev.user")
        f = c["calls"][0]["body"]["fields"]
        self.assertEqual(f["summary"], "CLONE - Approval stamp columns - DEV")
        self.assertNotIn(backlog.F_SPRINT, f)
        self.assertNotIn("fixVersions", f)
        self.assertEqual(f["labels"], ["AI-Used", "devin_created", "requested-by-dev-user"])
        self.assertEqual(f[backlog.F_EPIC_LINK], "ACME-90100")
        self.assertEqual(c["source"], "clone:ACME-90201")
        self.assertEqual(self.jira.writes, [])

    def test_note_and_attachment(self):
        b = self.make()
        c = b.note("ACME-90201", "Decided in grooming: ship in 26.4.3", "dev.user")
        self.assertEqual(c["calls"][0]["path"], "/api/2/issue/ACME-90201/comment")
        self.assertIn("Decided in grooming", c["calls"][0]["body"]["body"])
        a = b.note("ACME-90201", "file body", "dev.user", filename="notes.txt")
        self.assertEqual(a["calls"][0]["path"], "/api/2/issue/ACME-90201/attachments")
        self.assertEqual(a["calls"][0]["body"]["filename"], "notes.txt")
        with self.assertRaises(backlog.BacklogError):
            b.note("ACME-90201", "   ", "dev.user")

    def test_demo_scheduled_and_given(self):
        b = self.make()
        c = b.demo_scheduled("ACME-90201", "21 Oct 2026", "care coordinators", "dev.user")
        self.assertEqual([x["path"] for x in c["calls"]], ["/api/2/issue/ACME-90201/comment"])
        self.assertIn("Demo scheduled for 21 Oct 2026 with care coordinators", c["calls"][0]["body"]["body"])
        g = b.demo_given("ACME-90201", "21 Oct 2026", "care coordinators", "dev.user")
        self.assertEqual(g["calls"][0]["method"], "PUT")
        self.assertEqual(g["calls"][0]["body"]["update"]["labels"], [{"remove": "DEMO-NEEDED"}, {"remove": "Demo"}])
        self.assertIn("Demo given on 21 Oct 2026 to care coordinators", g["calls"][1]["body"]["body"])
        self.assertEqual(self.jira.writes, [])
        with self.assertRaises(backlog.BacklogError):
            b.demo_given("ACME-90201", "21 Oct 2026", "", "dev.user")
        with self.assertRaises(backlog.BacklogError):
            b.demo_scheduled("ACME-90201", " ", "", "dev.user")
        with self.assertRaises(backlog.BacklogError):
            b.demo_scheduled("ACME-90201", "21 Oct 2026", "  ", "dev.user")

    def test_hours(self):
        b = self.make()
        rows = b.subtasks("ACME-90201")
        self.assertEqual([(r["key"], r["hours_ok"]) for r in rows], [("ACME-90201", False), ("ACME-90202", True)])
        c = b.log_hours("ACME-90202", "1.5", "grid column", "dev.user", started="2026-10-07")
        self.assertEqual(c["status"], "preview")
        self.assertEqual(c["calls"][0]["path"], "/api/2/issue/ACME-90202/worklog")
        self.assertEqual(c["calls"][0]["body"]["timeSpentSeconds"], 5400)
        self.assertTrue(c["calls"][0]["body"]["started"].startswith("2026-10-07T"))
        self.assertIn("dev.user", c["calls"][0]["body"]["comment"])
        for bad in (lambda: b.log_hours("ACME-1", "x", "", "k"), lambda: b.log_hours("ACME-1", 25, "", "k"),
                    lambda: b.log_hours("ACME-1", 1, "", "k", started="7/10")):
            with self.assertRaises(backlog.BacklogError):
                bad()
        self.assertEqual(self.jira.writes, [])

    def test_poker_round(self):
        b = self.make()
        r = b.poker_start("ACME-90201", "dev.user", ["a", "b"])
        b.poker_vote(r["id"], "a", 3)
        r = b.poker_vote(r["id"], "b", 5)
        self.assertEqual(r["votes"], {"a": "✓", "b": "✓"}, "hidden until shown")
        self.assertEqual(r["waiting"], [])
        with self.assertRaises(backlog.BacklogError):
            b.poker_vote(r["id"], "a", 4)
        with self.assertRaises(backlog.BacklogError):
            b.poker_agree(r["id"], 5, "dev.user")
        r = b.poker_reveal(r["id"])
        self.assertEqual(r["spread"], {"low": 3, "high": 5, "median": 5, "agree": False})
        done = b.poker_agree(r["id"], 5, "dev.user")
        self.assertEqual(done["agreed"], 5)
        self.assertEqual(done["change"]["status"], "preview")
        self.assertEqual(self.jira.writes, [])
        self.assertTrue(b.poker_start("ACME-90201", "dev.user", [])["id"] != r["id"])
        self.assertTrue(b.poker_for("ACME-90201")[1]["closed"] is False)

    def test_sprints_cached_and_only_direct(self):
        b = self.make()
        self.assertEqual(b.sprints("247285")[0]["name"], "26.4.3")
        self.assertEqual(len(b.sprints("247285")), 2)
        n = len(self.jira.gets)
        b.sprints("247285")
        self.assertEqual(len(self.jira.gets), n, "cached")
        self.jira.via = "cloud"
        self.assertEqual(backlog.Backlog(self.jira, self.dir).sprints("247285"), [])

    def test_bad_input(self):
        b = self.make()
        for bad in (lambda: b.set_points("ABC-1", 3, "k"), lambda: b.set_points("ACME-1", "x", "k"),
                    lambda: b.set_points("ACME-1", 0, "k"), lambda: b.move([], 7, "k"), lambda: b.move(["ACME-1"], "zz", "k")):
            with self.assertRaises(backlog.BacklogError):
                bad()


class StartedStoryTextTests(unittest.TestCase):
    """Once SDLC has started on a ticket, Argus never changes its description or acceptance criteria."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="sdlc-bl-")
        self.jira = RecordingJira()
        self.b = backlog.Backlog(self.jira, self.dir, env={backlog.WRITES_ENV: "1", backlog.TICKETS_ENV: "ACME-90100"})
        self.b.started = lambda key: "SDLC started on it 2026-10-25" if key == "ACME-90100" else ""

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_description_and_acceptance_are_refused(self):
        for call in (lambda: self.b.set_acceptance("ACME-90100", "1. A\n2. B\n3. C", "x"),
                     lambda: self.b.edit("ACME-90100", {"description": "new"}, "x"),
                     lambda: self.b.edit("ACME-90100", {"acceptance": "1. A"}, "x"),
                     lambda: self.b.groom("ACME-90100", {"description": "new", "points": 3}, "x")):
            with self.assertRaises(backlog.BacklogError) as e:
                call()
            self.assertEqual(e.exception.status, 409)
            self.assertIn("SDLC started", str(e.exception))
        self.assertEqual(self.jira.writes, [])

    def test_other_writes_still_work(self):
        self.b.set_points("ACME-90100", 5, "x")
        self.b.edit("ACME-90100", {"summary": "New title"}, "x")
        self.assertTrue(self.jira.writes)

    def test_not_started_ticket_can_be_groomed(self):
        self.b.started = lambda key: ""
        self.b.edit("ACME-90100", {"description": "new"}, "x")
        self.assertTrue(any(w[0] == "PUT" for w in self.jira.writes))


class CloudSubtaskTests(unittest.TestCase):
    def test_cloud_mode_lists_the_ticket_from_the_cached_lists(self):
        class Cloud:
            via = "cloud"

            def story(self, key):
                return {"key": key, "summary": "Cached", "type": "Story", "parent": "ACME-1"}
        d = tempfile.mkdtemp(prefix="sdlc-bl-cloud-")
        self.addCleanup(shutil.rmtree, d, True)
        rows = backlog.Backlog(Cloud(), d, env={}).subtasks("ACME-9192")
        self.assertEqual(rows, [{"key": "ACME-9192", "summary": "Cached", "type": "Story", "hours_ok": False}])


class BacklogHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.jira = RecordingJira()
        wb.Handler.store = wb.Store()
        wb.Handler.devin = object()
        wb.Handler.jira = cls.jira
        wb.Handler.backlog = backlog.Backlog(cls.jira, tempfile.mkdtemp(prefix="sdlc-bl-http-"), env={})
        wb.Handler.pc = pctest.PcTests(key_source=lambda: "", threaded=False)
        wb.Handler.log_message = lambda *a: None
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), wb.Handler)
        cls.base = "http://127.0.0.1:%d" % cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, method=method, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_backlog_read(self):
        code, d = self.call("GET", "/api/backlog?user=dev.user")
        self.assertEqual(code, 200)
        self.assertEqual(d["stories"][0]["key"], "ACME-90201")
        self.assertEqual(d["sprints"][0]["id"], 7)
        self.assertFalse(d["mode"]["writes"])
        self.assertIn("openSprints()", d["jql"])

    def test_specialties_are_read_with_get(self):
        code, d = self.call("GET", "/api/backlog/specialties")
        self.assertEqual(code, 200)
        self.assertIn(backlog.CROSS_CUTTING, d["specialties"])

    def test_write_routes_preview_and_errors(self):
        code, c = self.call("POST", "/api/backlog/points", {"key": "ACME-90201", "points": 8, "user": "dev.user"})
        self.assertEqual((code, c["status"], c["points"]), (200, "preview", 8))
        code, c = self.call("POST", "/api/backlog/points", {"key": "nope", "points": 8})
        self.assertEqual(code, 400)
        code, c = self.call("POST", "/api/backlog/create", {"draft": {"type": "Story", "summary": "x"}, "user": "k"})
        self.assertEqual(code, 422)
        code, c = self.call("POST", "/api/backlog/precheck", {"draft": {"type": "Story", "summary": "x"}})
        self.assertEqual(code, 200)
        self.assertTrue(c["checks"])
        code, c = self.call("POST", "/api/backlog/poker/start", {"key": "ACME-90201", "user": "k", "voters": ["a"]})
        self.assertEqual(code, 200)
        code, v = self.call("POST", "/api/backlog/poker/vote", {"round": c["id"], "voter": "a", "points": 3})
        self.assertEqual(v["voted"], 1)
        code, h = self.call("POST", "/api/backlog/hours", {"key": "ACME-90201", "hours": 2, "note": "n", "user": "k"})
        self.assertEqual((code, h["hours"]), (200, 2))
        code, st = self.call("GET", "/api/backlog/subtasks?key=ACME-90201")
        self.assertEqual(len(st["tickets"]), 2)
        code, p = self.call("GET", "/api/backlog/previews")
        self.assertEqual(p["previews"][0]["kind"], "hours")
        code, c = self.call("GET", "/api/backlog/nothing")
        self.assertEqual(code, 404)
        self.assertEqual(self.jira.writes, [])

    def test_page_has_backlog_tab(self):
        with urllib.request.urlopen(self.base + "/") as r:
            html = r.read().decode()
        self.assertIn('id="navBacklog"', html)
        self.assertIn('id="backlogView"', html)


class BacklogScreenTests(unittest.TestCase):
    def test_story_read_brings_description_acceptance_and_releases(self):
        jira, seen = wb.Jira(), {}

        def get(path, **params):
            seen.update(params)
            return {"issues": [{"key": "ACME-1", "fields": {
                "summary": "s", "description": "why", wb.F_ACCEPTANCE: "1. a\n2. b",
                "fixVersions": [{"name": "R26.10", "releaseDate": "2026-10-20"}]}}]}
        jira.get = get
        story = jira.stories("backlog", with_description=True)["stories"][0]
        self.assertIn(wb.F_ACCEPTANCE, seen["fields"])
        self.assertEqual((story["description"], story["acceptance"]), ("why", "1. a\n2. b"))
        self.assertEqual(story["releases"], [{"name": "R26.10", "date": "2026-10-20"}])
        self.assertNotIn("acceptance", jira.stories("backlog")["stories"][0])

    def test_story_read_pages_past_one_hundred(self):
        jira, starts = wb.Jira(), []

        def get(path, **params):
            starts.append(params["startAt"])
            n = min(params["maxResults"], 230 - params["startAt"])
            return {"total": 230, "issues": [{"key": "ACME-%d" % (params["startAt"] + i), "fields": {}}
                                             for i in range(n)]}
        jira.get = get
        data = jira.stories("backlog")
        self.assertEqual(starts, [0, 100, 200])
        self.assertEqual((len(data["stories"]), data["total"], data["truncated"]), (230, 230, False))

    def test_story_read_stops_at_the_cap_and_says_so(self):
        jira = wb.Jira()
        jira.get = lambda path, **p: {"total": 5000, "issues": [{"key": "ACME-%d" % (p["startAt"] + i), "fields": {}}
                                                               for i in range(p["maxResults"])]}
        with mock.patch.object(wb, "STORY_READ_CAP", 250):
            data = jira.stories("backlog")
        self.assertEqual((len(data["stories"]), data["truncated"]), (250, True))

    def test_epic_comes_from_the_epic_link_field(self):
        jira = wb.Jira()
        jira.get = lambda path, **p: {"total": 1, "issues": [{"key": "ACME-2", "fields": {wb.F_EPIC_LINK: "ACME-100"}}]}
        self.assertTrue(wb.F_EPIC_LINK)
        self.assertEqual(jira.stories("backlog")["stories"][0]["parent"], "ACME-100")

    def test_specialty_is_read_from_the_story_then_its_epic(self):
        rules = backlog.specialty_rules()
        self.assertEqual(backlog.specialty_of(["CHF- claims screen", ""], rules), "CHF")
        self.assertEqual(backlog.specialty_of(["Add a filter", "Maternity programme"], rules), "Maternity")
        self.assertEqual(backlog.specialty_of(["MSKX load"], rules), "ProgramA")
        self.assertEqual(backlog.specialty_of(["CHFX report"], rules), "")

    def test_bucket_is_specialty_then_foundational_then_misc(self):
        rules, found = backlog.specialty_rules(), backlog.foundational_rules()
        self.assertEqual(backlog.bucket_of({"summary": "CHF- claims screen"}, None, rules, found), "CHF")
        self.assertEqual(backlog.bucket_of({"summary": "PostgreSQL upgrade to 16"}, None, rules, found), "Foundational")
        self.assertEqual(backlog.bucket_of({"summary": "Fix header", "labels": []},
                                           {"summary": "UI hardening", "labels": ["CORE"]}, rules, found), "Foundational")
        self.assertEqual(backlog.bucket_of({"summary": "Fix header"}, {"summary": "UI hardening"}, rules, found), "Misc")

    def test_parent_epics_outside_the_open_epic_list_are_looked_up(self):
        class Jira(RecordingJira):
            def stories(self, scope, jira_user="", with_description=False):
                if scope == "epics":
                    return {"stories": [{"key": "ACME-1", "summary": "CHF programme"}]}
                return {"stories": [{"key": "ACME-10", "summary": "Add a filter", "parent": "ACME-1"},
                                    {"key": "ACME-11", "summary": "Add a filter", "parent": "ACME-64"}]}

            def get(self, path, **params):
                self.gets.append((path, params))
                return {"issues": [{"key": "ACME-64", "fields": {"summary": "Platform work", "labels": ["Platform"]}}]}

        jira = Jira()
        import tempfile
        data = backlog.Backlog(jira, tempfile.mkdtemp()).issues()
        self.assertEqual(data["parents"], {"ACME-64": "Platform work"})
        self.assertEqual([s["specialty"] for s in data["stories"]], ["CHF", "Foundational"])
        self.assertEqual(jira.gets[0][1]["jql"], "key in (ACME-64)")

    def test_plan_pane_and_attention_chips_are_wired(self):
        with open(os.path.join(wb.HERE, "static", "index.html"), encoding="utf-8") as fh:
            html = fh.read()
        self.assertIn('id="blChips"', html)
        self.assertIn('data-blview="plan"', html)
        js = workbench_js()
        self.assertIn('data-blpane="plan"', js)
        for flag in ("groom", "unassigned", "noac", "nopts", "split", "noepic", "norelease", "nospecialty", "stale"):
            self.assertIn('id: "%s"' % flag, js)

    def test_velocity_comes_from_the_year_plan(self):
        folder = tempfile.mkdtemp(prefix="sdlc-plan-")
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "plan.yaml")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("plan_year: 2026\nvelocity_points_per_sprint: 130   # sheet\n")
        self.assertEqual(wb.plan_velocity(path), 130)
        self.assertIsNone(wb.plan_velocity(os.path.join(folder, "missing.yaml")))

    def test_backlog_is_two_columns_with_switchable_panes(self):
        with open(os.path.join(wb.HERE, "static", "index.html"), encoding="utf-8") as fh:
            html = fh.read()
        grid = html[html.index('class="bl-grid"'):html.index('id="blErr"')]
        self.assertEqual(grid.count('<div class="bl-col'), 2)
        for pane in ("groom", "create", "calendar"):
            self.assertIn('data-blview="%s"' % pane, grid)
        self.assertNotIn("data-pane=", grid, "data-pane belongs to the right column's tabs; setRightTab would hide these")
        js = workbench_js()
        self.assertIn('data-blpane="create"', js)
        self.assertIn('data-blpane="calendar"', js)
        click = js[js.index('$("blCalendar").addEventListener("click"'):]
        self.assertIn('openBlPane("groom")', click[:click.index("});")])
        self.assertIn('(s.sprint || "backlog")', js, "the calendar's Backlog row filters on 'backlog'")


class CreateEpicStoryTests(unittest.TestCase):
    def req(self, **kw):
        return {"create": dict({"kind": "Epic with stories", "text": "EOC needs a threshold override screen for PCMH"}, **kw)}

    def test_live_run_needs_backlog_writes(self):
        self.assertTrue(wb.create_request(self.req(dry_run=False), writes=False)[3])
        self.assertIn("writes are off", wb.create_request(self.req(dry_run=False), writes=False)[4])
        self.assertFalse(wb.create_request(self.req(dry_run=False), writes=True)[3])
        self.assertTrue(wb.create_request(self.req(), writes=True)[3])

    def test_files_are_checked(self):
        import base64
        ok = {"name": "../notes.md", "data": base64.b64encode(b"# notes").decode()}
        _, _, files, _, _ = wb.create_request(self.req(text="", files=[ok]), writes=False)
        self.assertEqual(files, [("notes.md", b"# notes")])
        for bad in ({"name": "run.exe", "data": ""}, {"name": "a.pdf", "data": "not base64!"}):
            with self.assertRaises(wb.ApiError):
                wb.create_request(self.req(files=[bad]), writes=False)
        with self.assertRaises(wb.ApiError):
            wb.create_request(self.req(files=[ok] * 11), writes=False)
        with self.assertRaises(wb.ApiError):
            wb.create_request({"create": {"kind": "Epic", "text": "short"}}, writes=False)
        with self.assertRaises(wb.ApiError):
            wb.create_request(self.req(kind="Bug"), writes=False)

    def test_prompts(self):
        files = [("brd.docx", "https://x/attachments/1/brd.docx")]
        dry = wb.build_create_prompt("Epic with stories", "need", files, True, "REQ-1")
        self.assertIn("/intake notes", dry)
        self.assertIn("REQ-1-EPIC-STORIES.md", dry)
        self.assertIn("do not write to Jira", dry)
        self.assertIn("brd.docx — https://x/attachments/1/brd.docx", dry)
        live = wb.build_create_prompt("Story", "need", files, False, "REQ-1")
        self.assertIn("only then", live)
        self.assertIn("Attach every source file", live)
        self.assertIn("never retry", live)


if __name__ == "__main__":
    unittest.main()


class TennCareDefectTitleTest(unittest.TestCase):
    SIT = "TEST - System Integration Test (SIT)"
    UAT = "TEST - User Acceptance Test (UAT)"

    def test_prefixes(self):
        self.assertEqual(backlog.defect_title("Grid loses filter", "PCMH", self.SIT), "SIT-TC-PCMH: Grid loses filter")
        self.assertEqual(backlog.defect_title("Saves twice", "EOC", self.UAT, "TJR"), "UAT-TC-EoC: TJR - Saves twice")
        self.assertEqual(backlog.defect_title("Saves twice", "CHF", self.UAT), "CHF - Saves twice - UAT")
        self.assertEqual(backlog.defect_title("Saves twice", "PCMH", "PRODUCTION - Warranty"),
                         "PCMH - Saves twice - PROD")
        self.assertEqual(backlog.defect_title("SIT-TC-THL: already right", "THL", self.SIT), "SIT-TC-THL: already right")

    def test_precheck_flags_wrong_prefix(self):
        checks = backlog.precheck({"type": "Defect", "summary": "EOC - Saves twice - SIT", "specialty": "EOC",
                                   "environment": self.SIT, "epic": "ACME-1", "priority": "P2",
                                   "acceptance": "1. x\n2. y", "labels": ["AI-Used"]})
        self.assertIn("DEFECT_TITLE_PREFIX", [c["check"] for c in checks])
        ok = backlog.precheck({"type": "Defect", "summary": "SIT-TC-EoC: TJR - Saves twice", "specialty": "EOC",
                               "environment": self.SIT, "epic": "ACME-1", "priority": "P2",
                               "acceptance": "1. x\n2. y", "labels": ["AI-Used"]})
        self.assertNotIn("DEFECT_TITLE_PREFIX", [c["check"] for c in ok])
        self.assertNotIn("SPECIALTY_MISSING", [c["check"] for c in ok])
