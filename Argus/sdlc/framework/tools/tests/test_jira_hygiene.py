"""Tests for jira_hygiene.py and the dashboard's hygiene tab. Stdlib unittest, no Jira.

    python3 -m unittest sdlc/framework/tools/tests/test_jira_hygiene.py -v
"""
import json
import os
import sys
import tempfile
import unittest

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)

import gen_dashboard  # noqa: E402
import jira_hygiene as jh  # noqa: E402

FIXTURE = os.path.join(TOOLS, "fixtures", "jira-hygiene-demo.json")


def load_fixture():
    with open(FIXTURE, encoding="utf-8") as fh:
        return json.load(fh)


def checks_for(rows, key):
    return sorted(r["check"] for r in rows if r["key"] == key)


class CheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = load_fixture()
        cls.rows = jh.finding_rows(cls.data)

    def test_a_clean_story_and_epic_have_no_findings(self):
        self.assertEqual(checks_for(self.rows, "ACME-90201"), [])
        self.assertEqual(checks_for(self.rows, "ACME-90202"), [])
        self.assertEqual(checks_for(self.rows, "ACME-90100"), [])
        self.assertEqual(checks_for(self.rows, "ACME-90304"), [])

    def test_story_with_many_gaps_trips_each_relevant_check(self):
        self.assertEqual(checks_for(self.rows, "ACME-90203"), [
            "AC_VAGUE", "EPIC_LINK_MISSING", "LABEL_CASE", "PHASE_SUFFIX_MISSING", "POINTS_MISSING",
            "PRIORITY_MISSING", "SPRINT_CARRYOVER", "STORY_TIME_LOGGED"])

    def test_lowercase_suffix_and_missing_sibling_link(self):
        self.assertEqual(checks_for(self.rows, "ACME-90204"),
                         ["AC_UNNUMBERED", "AI_LABEL_MISSING", "PHASE_SUFFIX_CASE", "SIBLING_LINK_MISSING"])

    def test_sub_task_checks(self):
        self.assertEqual(checks_for(self.rows, "ACME-90301"), [])
        self.assertEqual(checks_for(self.rows, "ACME-90302"),
                         ["AC_PLACEHOLDER", "AI_LABEL_MISSING", "SUBTASK_PREFIX_MISSING", "WORKLOG_MISSING"])
        self.assertEqual(checks_for(self.rows, "ACME-90303"), ["REQUESTER_LABEL_MISSING"])

    def test_epic_checks(self):
        self.assertEqual(checks_for(self.rows, "ACME-90101"),
                         ["AC_MISSING", "EPIC_DESCRIPTION_THIN", "EPIC_OWNER_MISSING", "EPIC_TITLE_DATED"])

    def test_rows_are_sorted_worst_first_and_every_check_is_documented(self):
        severities = [jh.SEVERITY_ORDER[r["severity"]] for r in self.rows]
        self.assertEqual(severities, sorted(severities))
        for row in self.rows:
            self.assertIn(row["check"], jh.CHECKS)
            self.assertTrue(row["text"] and row["rule"])

    def test_attention(self):
        self.assertEqual(jh.attention([]), "clear")
        self.assertEqual(jh.attention([{"severity": "low"}]), "watch")
        self.assertEqual(jh.attention(self.rows), "hot")

    def test_fragment_links_tickets_and_names_checks(self):
        body = jh.render_fragment(self.rows, self.data)
        self.assertIn(jh.BROWSE + "ACME-90203", body)
        self.assertIn("Epic has no owner", body)
        self.assertIn("not to single anyone out", body)
        self.assertEqual(jh.render_fragment([], self.data), "")

    def test_fetch_pages_and_keeps_the_three_groups(self):
        calls = []

        def get(path, **params):
            calls.append(params)
            return {"issues": [{"key": "ACME-1"}], "total": 1}

        data = jh.fetch(get)
        self.assertEqual(sorted(data), ["epics", "stories", "subtasks"])
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(jh.F_AC in c["fields"] for c in calls))

    def test_main_writes_html_and_markdown_from_cache(self):
        with tempfile.TemporaryDirectory() as out:
            rc = jh.main(["--cache", FIXTURE, "--out-html", os.path.join(out, "h.html"),
                          "--out-md", os.path.join(out, "h.md")])
            self.assertEqual(rc, 0)
            with open(os.path.join(out, "h.md"), encoding="utf-8") as fh:
                self.assertIn("## Epic has no owner (1)", fh.read())
            self.assertTrue(os.path.getsize(os.path.join(out, "h.html")) > 0)


class DashboardTabTests(unittest.TestCase):
    def test_tech_lead_and_po_office_lenses_show_the_tab(self):
        config = gen_dashboard.lens_config()
        self.assertEqual(config["panels"]["jira_hygiene"]["kind"], "hygiene")
        for lens in ("tech_lead", "po_office"):
            self.assertIn("jira_hygiene", config["lenses"][lens]["panels"])

    def test_cache_source_reads_the_linked_fixture_and_renders(self):
        source = gen_dashboard.CacheSource(
            os.path.join(TOOLS, "fixtures", "dashboard-demo-tech-lead.json"), "resource3")
        data, note = source.hygiene({"id": "jira_hygiene"})
        self.assertEqual(len(data["stories"]), 4)
        tab = gen_dashboard.render_hygiene({"id": "jira_hygiene", "title": "Hygiene"}, data, note)
        self.assertEqual(tab["count"], 5)
        self.assertEqual(tab["attention"], "hot")


if __name__ == "__main__":
    unittest.main()
