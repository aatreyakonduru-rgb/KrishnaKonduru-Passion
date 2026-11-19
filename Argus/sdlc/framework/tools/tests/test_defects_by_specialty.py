"""Tests for defects_by_specialty.py and the dashboard's defect_matrix tab. Stdlib unittest, no Jira.

    python3 -m unittest sdlc/framework/tools/tests/test_defects_by_specialty.py -v
"""
import datetime
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)

import defects_by_specialty as dbs  # noqa: E402
import gen_dashboard  # noqa: E402

FIXTURE = os.path.join(TOOLS, "fixtures", "defects-by-specialty-demo.json")
TODAY = datetime.date(2026, 10, 6)


def load_fixture():
    with open(FIXTURE, encoding="utf-8") as fh:
        return json.load(fh)


class ClassifyTests(unittest.TestCase):
    def setUp(self):
        self.rules = dbs.load_rules()
        self.compiled = dbs.compile_rules(self.rules)

    def classify(self, *texts):
        return dbs.classify(list(texts), self.compiled, self.rules["unassigned"])

    def test_every_agreed_specialty_is_in_the_rules(self):
        self.assertEqual(dbs.specialty_names(self.rules),
                         ["EOC", "Maternity", "CHF", "THL", "ProgramA", "ProgramB", "ProgramC", "PCMH", "Unassigned"])

    def test_summary_keyword_wins_and_is_shown_as_evidence(self):
        self.assertEqual(self.classify(("summary", "CHF- Cohort export"))[:2], ("CHF", 'summary: "CHF"'))
        self.assertEqual(self.classify(("summary", "TJR U01 SIT look back"))[0], "EOC")

    def test_keywords_are_whole_words_but_patterns_catch_glued_codes(self):
        self.assertEqual(self.classify(("summary", "CHFX job"))[0], "Unassigned")
        self.assertEqual(self.classify(("summary", "MSKFD0101 retro file"))[0], "ProgramA")

    def test_first_specialty_in_list_order_wins_and_the_rest_are_reported(self):
        specialty, _, also = self.classify(("summary", "Perinatal TennCare Episode Of Care"))
        self.assertEqual((specialty, also), ("EOC", ["Maternity"]))

    def test_falls_back_to_epic_then_links_then_unassigned(self):
        self.assertEqual(self.classify(("summary", "Grid sorts wrong"), ("epic ACME-1", "ProgramB work-UI"))[:2],
                         ("ProgramB", 'epic ACME-1: "ProgramB"'))
        self.assertEqual(self.classify(("summary", "Grid sorts wrong"), ("linked ACME-2", "ProgramC VA roster"))[0], "ProgramC")
        self.assertEqual(self.classify(("summary", "Grid sorts wrong")),
                         ("Unassigned", "no keyword matched", []))


class RowTests(unittest.TestCase):
    def setUp(self):
        self.rules = dbs.load_rules()
        self.rows = {r["key"]: r for r in dbs.defect_rows(load_fixture(), self.rules, today=TODAY)}

    def test_assignee_release_and_sprint_are_read(self):
        row = self.rows["ACME-90001"]
        self.assertEqual((row["assignee"], row["release_name"], row["release_date"]),
                         ("Resource 13", "2026-11-13", "2026-11-13"))
        self.assertEqual(self.rows["ACME-90002"]["sprint_state"], "active")
        self.assertEqual(dbs.release_text(self.rows["ACME-90002"]), "sprint ends 2026-10-06")

    def test_flags_point_at_decisions(self):
        self.assertEqual(self.rows["ACME-90001"]["flags"], [])
        self.assertEqual(self.rows["ACME-90003"]["flags"], ["unassigned", "no_release", "not_moving"])  # NA = placeholder
        self.assertIn("release_passed", self.rows["ACME-90004"]["flags"])
        self.assertEqual(self.rows["ACME-90007"]["team"], dbs.NO_TEAM)
        self.assertTrue(dbs.needs_attention(self.rows["ACME-90003"]))
        self.assertEqual(dbs.attention(list(self.rows.values())), "hot")
        self.assertEqual(dbs.attention([]), "clear")

    def test_passed_sprint_end_counts_as_release_passed(self):
        self.assertNotIn("release_passed", self.rows["ACME-90002"]["flags"])
        later = {r["key"]: r for r in dbs.defect_rows(load_fixture(), self.rules,
                                                     today=TODAY + datetime.timedelta(days=1))}
        self.assertIn("release_passed", later["ACME-90002"]["flags"])
        self.assertIn('data-state="blocked">sprint ends 2026-10-06', dbs.render_fragment(list(later.values()), self.rules))

    def test_rows_are_grouped_by_specialty_then_team(self):
        ordered = dbs.defect_rows(load_fixture(), self.rules, today=TODAY)
        names = dbs.specialty_names(self.rules)
        positions = [names.index(r["specialty"]) for r in ordered]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(ordered[-1]["specialty"], "Unassigned")

    def test_greenhopper_sprint_string_is_parsed(self):
        raw = load_fixture()["issues"][1]["fields"]["customfield_10002"][0]
        sprint = dbs.parse_sprint(raw)
        self.assertEqual((sprint["state"], sprint["end"]), ("ACTIVE", datetime.date(2026, 10, 6)))


class FetchTests(unittest.TestCase):
    def test_reads_every_page_and_never_adds_a_team_clause(self):
        calls = []

        def get(path, **params):
            calls.append(params)
            if params["jql"].startswith("key in"):
                return {"issues": [{"key": "ACME-7", "fields": {"summary": "ProgramA work-UI"}}]}
            start = params["startAt"]
            batch = [{"key": "ACME-%d" % n, "fields": {"customfield_10010": "ACME-7"}}
                     for n in range(start, min(start + params["maxResults"], 130))]
            return {"issues": batch, "total": 130}

        data = dbs.fetch(get)
        self.assertEqual(len(data["issues"]), 130)
        self.assertEqual(data["epics"], {"ACME-7": "ProgramA work-UI"})
        self.assertNotIn("IT Team", calls[0]["jql"])
        self.assertIn('"Defect Detected In"', calls[0]["jql"])
        self.assertIn("resolution = Unresolved", calls[0]["jql"])


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.rules = dbs.load_rules()
        self.rows = dbs.defect_rows(load_fixture(), self.rules, today=TODAY)

    def test_fragment_has_matrix_filters_and_jira_links(self):
        body = dbs.render_fragment(self.rows, self.rules, dom_id="t")
        self.assertIn("By specialty", body)
        self.assertIn("Specialty by team", body)
        self.assertIn('data-dm-filter="team"', body)
        self.assertIn('<a href="https://jira.acme.example/browse/ACME-90001">', body)
        self.assertIn('data-dm-team-head="EDA-ACME-MBR-EOC"', body)
        self.assertNotIn("http://", body)
        self.assertEqual(dbs.render_fragment([], self.rules), "")

    def test_page_and_markdown(self):
        page = dbs.render_page(self.rows, self.rules, "2026-10-06", sample=True)
        self.assertIn("sample data", page)
        self.assertNotIn("<link ", page)
        text = dbs.render_markdown(self.rows, self.rules, "2026-10-06")
        self.assertIn("| EOC | 3 |", text)
        self.assertIn("### EDA-ACME-Financial (1)", text)

    def test_cli_writes_both_files_from_cache(self):
        out = tempfile.mkdtemp(prefix="dbs-")
        with redirect_stdout(io.StringIO()):
            rc = dbs.main(["--cache", FIXTURE, "--out-html", os.path.join(out, "d.html"),
                           "--out-md", os.path.join(out, "d.md")])
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.getsize(os.path.join(out, "d.html")) > 0)


class DashboardTabTests(unittest.TestCase):
    def test_tech_lead_and_po_office_lenses_show_the_tab(self):
        config = gen_dashboard.lens_config()
        self.assertEqual(config["panels"]["specialty_defects"]["kind"], "defect_matrix")
        for lens in ("tech_lead", "po_office"):
            self.assertIn("specialty_defects", config["lenses"][lens]["panels"])

    def test_cache_source_reads_the_linked_fixture_and_renders(self):
        source = gen_dashboard.CacheSource(
            os.path.join(TOOLS, "fixtures", "dashboard-demo-tech-lead.json"), "resource3")
        data, note = source.defect_matrix({"id": "specialty_defects"})
        self.assertEqual(len(data["issues"]), 9)
        tab = gen_dashboard.render_defect_matrix(
            {"id": "specialty_defects", "title": "Defects"}, data, note)
        self.assertEqual(tab["count"], 9)
        self.assertIn(tab["attention"], ("hot", "watch"))


if __name__ == "__main__":
    unittest.main()
