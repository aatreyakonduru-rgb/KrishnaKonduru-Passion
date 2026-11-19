"""Review pages (Backlog grid, business intake) and the Cloud block runner behind them."""
import json
import os
import re
import sys
import tempfile
import unittest

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)

import backlog_cli as cli  # noqa: E402
import review_pages as rp  # noqa: E402

FIX = os.path.join(TOOLS, "fixtures")


class FakeJira:
    token = "t"
    via = "here"

    def __init__(self):
        self.writes = []

    def get(self, path, **params):
        if path.endswith("/transitions"):
            return {"transitions": [{"id": "1", "name": "On Hold", "to": {"name": "On Hold"}}]}
        return {"fields": {"summary": "EOC - Override - DEV", "issuetype": {"name": "Story"}, "labels": ["AI-Used"]}}

    def request(self, method, path, payload=None):
        self.writes.append((method, path, payload))
        return {"key": "ACME-99999"}


def scripts(page):
    return re.findall(r"<script>([\s\S]*?)</script>", page)


class PageTests(unittest.TestCase):
    def test_backlog_page_from_fixture(self):
        with open(os.path.join(FIX, "backlog-page-demo.json"), encoding="utf-8") as fh:
            page = rp.backlog_page(json.load(fh))
        self.assertIn("Sample data", page)
        self.assertIn("ACME-18710", page)
        self.assertIn(rp.BLOCK, page)
        self.assertNotIn("<script src", page)

    def test_new_ticket_page_uses_team_subtasks(self):
        with open(os.path.join(FIX, "new-ticket-demo.json"), encoding="utf-8") as fh:
            page = rp.new_ticket_page(json.load(fh))
        self.assertIn("DEV- Analysis of the story", page)
        self.assertIn("What Devin found", page)

    def test_live_page_has_no_sample_badge(self):
        self.assertNotIn("Sample data", rp.backlog_page({"items": []}))

    def test_items_carry_rule_book_checks(self):
        story = {"key": "ACME-1", "fields": {"summary": "Override", "issuetype": {"name": "Story"},
                                             "labels": [], "status": {"name": "To Do"}}}
        epic = {"key": "ACME-2", "fields": {"summary": "Overrides", "issuetype": {"name": "Epic"},
                                            "labels": ["EOC"], "status": {"name": "To Do"}}}
        rows = {r["k"]: r for r in rp.backlog_items([story], [epic])}
        self.assertTrue(rows["ACME-1"]["groom"])
        self.assertTrue(any("Acceptance criteria are empty" in c[1] for c in rows["ACME-1"]["checks"]))
        self.assertEqual(rows["ACME-2"]["t"], "Epic")

    def test_demo_flag_follows_status(self):
        def story(key, status, labels):
            return {"key": key, "fields": {"summary": "s", "issuetype": {"name": "Story"}, "labels": labels,
                                           "status": {"name": status}}}
        rows = {r["k"]: r["demo"] for r in rp.backlog_items(
            [story("ACME-1", "In Review", ["DEMO-NEEDED"]), story("ACME-2", "In Progress", ["Demo"]),
             story("ACME-3", "In Review", [])], [], demo_ready=["In Review", "Ready For Release"])}
        self.assertEqual(rows, {"ACME-1": "ready", "ACME-2": "due", "ACME-3": ""})
        self.assertIn("In Review", rp.demo_ready_statuses())
        self.assertIn('id="f-demo"', rp.backlog_page({"items": []}))

    def test_embedded_json_cannot_close_the_script(self):
        page = rp.backlog_page({"items": [{"k": "ACME-1", "s": "</script><b>x"}]})
        self.assertNotIn("</script><b>x", page)


    def test_epics_and_reports_from_fixtures(self):
        for page, name, text in (("epics", "epics-page-demo.json", "roadmap-2027.xlsx"),
                                 ("report", "release-notes-page-demo.json", "Feature by feature"),
                                 ("report", "migration-status-page-demo.json", "Configure (OldClaims)"),
                                 ("intake", "intake-page-demo.json", "Attach documents")):
            with open(os.path.join(FIX, name), encoding="utf-8") as fh:
                html_ = rp.PAGES[page](json.load(fh))
            self.assertIn(text, html_, name)
            self.assertEqual(len(scripts(html_)), 2, name)

    def test_report_text_is_escaped(self):
        page = rp.report_page({"title": "R", "tabs": [{"title": "T", "blocks": [{"bullets": ["<img src=x>"]}]}]})
        self.assertIn("&lt;img src=x&gt;", page)
        with self.assertRaises(ValueError):
            rp.report_page({"tabs": [{"title": "T", "blocks": [{"html": "<b>"}]}]})


    def test_dashboard_backlog_panel(self):
        import gen_dashboard
        with open(os.path.join(FIX, "backlog-page-demo.json"), encoding="utf-8") as fh:
            data = json.load(fh)
        out = gen_dashboard.render_backlog({"id": "backlog", "title": "Backlog"}, data, "")
        self.assertIn("page-doc-backlog", out["body"])
        self.assertIn("need grooming", out["body"])
        self.assertIn("Nothing open", gen_dashboard.render_backlog({"id": "backlog", "empty": "Nothing open"}, {}, "")["body"])
        lenses = gen_dashboard.lens_config()["lenses"]
        for lens in ("bsa", "po_office", "scrum_master"):
            self.assertIn("backlog", lenses[lens]["panels"], lens)


class BlockTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.jira = FakeJira()

    def backlog(self, env=None):
        return cli.bl.Backlog(self.jira, self.dir, env=env or {})

    def run_block(self, text, env=None):
        return cli.run(self.backlog(env), cli.parse_block(text), "dso")

    def test_parse_lists_and_stories(self):
        blk = cli.parse_block("x\nSDLC-DASHBOARD-BACKLOG\naction: create\nepic: E | owner Resource 17 | EOC\n"
                              "story: S1 | 5 points\n  ac: one\n  ac: two\n  sub-tasks: standard set\n"
                              "answers:\n  Who: leads\nEND\n")
        self.assertEqual(blk["stories"][0], {"title": "S1", "points": 5.0, "ac": ["one", "two"]})
        blk = cli.parse_block("SDLC-DASHBOARD-BACKLOG\naction: groom\nticket: ACME-1\nacceptance criteria:\n  - a\n  - b\nEND")
        self.assertEqual(blk["acceptance criteria"], ["a", "b"])

    def test_preview_by_default(self):
        out = self.run_block("SDLC-DASHBOARD-BACKLOG\naction: point\nticket: ACME-18710\npoints: 5\nEND")
        self.assertEqual(out[0]["status"], "preview")
        self.assertEqual(self.jira.writes, [])

    def test_apply_only_when_on_and_allowed(self):
        env = {cli.bl.WRITES_ENV: "1", cli.bl.TICKETS_ENV: "ACME-18710"}
        out = self.run_block("SDLC-DASHBOARD-BACKLOG\naction: point\nticket: ACME-18710\npoints: 5\nEND", env)
        self.assertEqual(out[0]["status"], "applied")
        out = self.run_block("SDLC-DASHBOARD-BACKLOG\naction: point\nticket: ACME-18711\npoints: 5\nEND", env)
        self.assertEqual(out[0]["status"], "preview")

    def test_groom_numbers_criteria_and_names_requester(self):
        out = self.run_block("SDLC-DASHBOARD-BACKLOG\naction: groom\nticket: ACME-1\nacceptance criteria:\n  - a\n  - b\nEND")
        body = out[0]["calls"][0]["body"]["fields"]
        self.assertEqual(list(body.values())[0], "1. a\n2. b")
        self.assertIn("dso", json.dumps(out[0]["calls"][1]))

    def test_edit_and_poker(self):
        out = self.run_block("SDLC-DASHBOARD-BACKLOG\naction: edit\nticket: ACME-1\ntitle: New title\nEND")
        self.assertEqual(out[0]["calls"][0]["body"]["fields"], {"summary": "New title"})
        rnd = self.run_block("SDLC-DASHBOARD-BACKLOG\naction: poker start\nticket: ACME-1\nmy vote: 5\nvoters: gpo, dmo\nEND")[0]["round"]
        self.assertEqual(rnd["waiting"], ["gpo", "dmo"])
        self.assertEqual(rnd["votes"], {"dso": "\u2713"})

    def test_create_tree_previews_epic_and_stories(self):
        out = self.run_block("SDLC-DASHBOARD-BACKLOG\naction: create\nkind: epic\nepic: Overrides | owner Resource 17 | EOC | 2027.2\n"
                             "story: EOC - Override from the member record - DEV | 5 points\n  ac: saved with reason\nEND")
        self.assertEqual([c["status"] for c in out], ["preview", "preview"])
        self.assertIn("sub-tasks", out[1]["title"])

    def test_unknown_action(self):
        with self.assertRaises(cli.bl.BacklogError):
            self.run_block("SDLC-DASHBOARD-BACKLOG\naction: delete\nEND")


if __name__ == "__main__":
    unittest.main()
