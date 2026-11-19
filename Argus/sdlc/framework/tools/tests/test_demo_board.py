"""Tests for the dashboard's demo_board tab (Ready to demo) and demo_needed.recorded(). Stdlib unittest, no Jira."""
import os
import re
import sys
import tempfile
import unittest

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)

import demo_needed  # noqa: E402
import gen_dashboard  # noqa: E402

FIXTURE = os.path.join(TOOLS, "fixtures", "dashboard-demo.json")
SPEC = {"id": "demo_ready", "title": "Demos", "columns": ["key", "summary", "status", "sprint"]}


def row(key, sprint, recorded=False):
    return {"key": key, "summary": "s " + key, "status": "Open", "sprint": sprint, "recorded": recorded}


class FakeConf:
    base = "https://conf"

    def __init__(self, titles):
        self.titles = titles

    def get(self, path, **params):
        start, limit = params.get("start", 0), params.get("limit", 200)
        page = self.titles[start:start + limit]
        return {"results": [{"title": t, "id": str(i + start)} for i, t in enumerate(page)]}


class RecordedTests(unittest.TestCase):
    def test_story_with_ac_pages_is_recorded_and_links_to_story_page(self):
        conf = FakeConf(["EPIC-1", "ACME-1", "ACME-1_AC1_demo", "ACME-1_AC2_demo", "ACME-12"])
        found = demo_needed.recorded(conf, root="9")
        self.assertEqual(list(found), ["ACME-1"])
        self.assertEqual(found["ACME-1"], {"url": "https://conf/pages/viewpage.action?pageId=1", "acs": 2})

    def test_demos_suffix_story_page_and_paging(self):
        titles = ["filler-%d" % i for i in range(200)] + ["ACME-7 (demos)", "ACME-7_AC1_demo"]
        found = demo_needed.recorded(FakeConf(titles), root="9")
        self.assertEqual(found["ACME-7"]["url"], "https://conf/pages/viewpage.action?pageId=200")


class RenderTests(unittest.TestCase):
    def test_groups_by_sprint_newest_open_and_no_sprint_last(self):
        rows = [row("ACME-1", "Acme Claims Sprint 26.4.1(9/16-10/6)"), row("ACME-2", ""),
                row("ACME-3", "Acme Claims Sprint 26.4.2(10/7-10/27)", {"url": "u", "acs": 2}),
                row("ACME-4", "Acme Claims Sprint 26.3.4(8/26-9/15)")]
        tab = gen_dashboard.render_demo_board(SPEC, rows, "")
        heads = re.findall(r"<details class=\"demo-sprint\"( open)?><summary><strong>([^<]*)</strong>", tab["body"])
        self.assertEqual([h[1] for h in heads], ["Acme Claims Sprint 26.4.2(10/7-10/27)", "Acme Claims Sprint 26.4.1(9/16-10/6)",
                                                 "Acme Claims Sprint 26.3.4(8/26-9/15)", "Not in a sprint"])
        self.assertEqual([h[0] for h in heads], [" open", "", "", ""])
        self.assertEqual(tab["count"], 4)
        self.assertIn("1 story · 1 recorded", tab["body"])
        self.assertIn("Recorded · 2 AC", tab["body"])
        self.assertIn("Not recorded", tab["body"])
        self.assertNotIn("<th>Sprint</th>", tab["body"])
        self.assertIn("<th>Demo recorded</th>", tab["body"])

    def test_unknown_when_confluence_not_read(self):
        tab = gen_dashboard.render_demo_board(SPEC, [row("ACME-1", "", None)], "")
        self.assertIn("demo-unknown", tab["body"])

    def test_empty(self):
        self.assertEqual(gen_dashboard.render_demo_board(SPEC, [], "")["count"], 0)

    def test_po_dashboard_renders_the_tab_from_the_fixture(self):
        config = gen_dashboard.lens_config()
        self.assertEqual(config["panels"]["demo_ready"]["kind"], "demo_board")
        with tempfile.TemporaryDirectory() as out:
            path = os.path.join(out, "d.html")
            gen_dashboard.main(["--cache", FIXTURE, "--user", "demo", "--lens", "po_office", "-o", path])
            html = open(path, encoding="utf-8").read()
        self.assertIn("Acme Claims Sprint 26.4.2(10/7-10/27)", html)
        self.assertIn("Expand all", html)


class WithRecordingsTests(unittest.TestCase):
    def test_story_without_page_is_not_recorded_and_unread_is_unknown(self):
        found = {"ACME-1": {"url": "u", "acs": 1}}
        orig_rec, orig_conf = demo_needed.recorded, demo_needed.confluence
        try:
            demo_needed.confluence = lambda: None
            demo_needed.recorded = lambda conf: found
            rows, note = gen_dashboard.with_recordings([{"key": "ACME-1"}, {"key": "ACME-2"}])
            self.assertEqual((rows[0]["recorded"], rows[1]["recorded"], note), (found["ACME-1"], {}, ""))
            self.assertIn("Not recorded", gen_dashboard.recorded_cell(rows[1]["recorded"]))

            def boom(conf):
                raise RuntimeError("HTTP 403")
            demo_needed.recorded = boom
            rows, note = gen_dashboard.with_recordings([{"key": "ACME-1"}])
            self.assertIsNone(rows[0]["recorded"])
            self.assertIn("HTTP 403", note)
        finally:
            demo_needed.recorded, demo_needed.confluence = orig_rec, orig_conf


if __name__ == "__main__":
    unittest.main()
