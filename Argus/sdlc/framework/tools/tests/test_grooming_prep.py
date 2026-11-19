import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import grooming_prep as gp  # noqa: E402

CUR, NXT, AFTER = "Acme Claims Sprint 26.4.2(10/7-10/27)", "Acme Claims Sprint 26.4.3(10/28-11/17)", "Acme Claims Sprint 26.4.4(11/18-12/8)"
TODAY = datetime.date(2026, 10, 15)
TEAMS = {"teams": [
    {"key": "ui", "name": "TechNinjas", "people": [{"role": "Product Owner", "who": "Resource 17"},
                                                   {"role": "Scrum Master", "who": "D. Resource 2"},
                                                   {"role": "Testing (QA/SIT sub-tasks)", "who": "Resource 19, Resource 18"}]},
    {"key": "scorecard", "name": "Acme Claims Scorecard", "people": [{"role": "Product Owner", "who": "Score Owner"}]},
]}
CFG = {"partner_teams": {"scorecard": ["scorecard"]}, "dls": {}, "assumptions": ["A guess"]}


def story(key, summary, sprint="", points=5, ac="1. It works", labels=None, parent="ACME-1", reporter="Rita", assignee="Asha"):
    return {"key": key, "summary": summary, "sprint": sprint, "points": points, "acceptance": ac,
            "labels": labels or [], "parent": parent, "reporter": reporter, "assignee": assignee, "type": "Story"}


class SprintsTest(unittest.TestCase):
    def test_board_sprints_win(self):
        sprints = [{"name": CUR, "state": "active"}, {"name": AFTER, "state": "future", "start": "2026-11-18"},
                   {"name": NXT, "state": "future", "start": "2026-10-28"}]
        self.assertEqual(gp.order_sprints(sprints, [], TODAY), (CUR, NXT, AFTER))

    def test_names_on_stories_when_the_board_is_not_read(self):
        stories = [story("A", "x", AFTER), story("B", "y", CUR), story("C", "z", NXT)]
        self.assertEqual(gp.order_sprints([], stories, TODAY), (CUR, NXT, AFTER))

    def test_sprint_across_new_year(self):
        self.assertEqual(gp.sprint_dates("26.4.5(12/9-1/5)")[1], datetime.date(2027, 1, 5))


class TitlesTest(unittest.TestCase):
    def test_phase_and_base(self):
        self.assertEqual(gp.phase("Contract sync - DEV"), "DEV")
        self.assertEqual(gp.phase("SIT- Contract sync"), "SIT")
        self.assertEqual(gp.base("Contract Sync - UAT"), gp.base("SIT - contract sync"))
        self.assertEqual(gp.phase("Contract sync"), "")


class AnalyseTest(unittest.TestCase):
    def run_it(self, stories, plan=None):
        sprints = [{"name": CUR, "state": "active"}, {"name": NXT, "state": "future", "start": "2026-10-28"},
                   {"name": AFTER, "state": "future", "start": "2026-11-18"}]
        return gp.analyse(stories, [{"key": "ACME-1", "summary": "Scorecard export"}], sprints, plan, TEAMS, CFG, TODAY)

    def test_dev_story_without_sit_or_uat(self):
        d = self.run_it([story("ACME-10", "Bulk upload - DEV", CUR)])
        self.assertEqual([(r["phase"], r["sprint"]) for r in d["phases"]], [("SIT", NXT), ("UAT", AFTER)])
        self.assertEqual(d["phases"][0]["title"], "Bulk upload - SIT")

    def test_sit_story_found_but_not_in_a_sprint(self):
        d = self.run_it([story("ACME-10", "Bulk upload - DEV", CUR), story("ACME-11", "SIT - Bulk upload"),
                         story("ACME-12", "Bulk upload - UAT", AFTER)])
        self.assertEqual(len(d["phases"]), 1)
        self.assertIn("ACME-11 is not in a sprint", d["phases"][0]["problem"])

    def test_complete_phases_give_nothing(self):
        d = self.run_it([story("ACME-10", "Bulk upload - DEV", CUR), story("ACME-11", "Bulk upload - SIT", NXT),
                         story("ACME-12", "Bulk upload - UAT", AFTER)])
        self.assertEqual(d["phases"], [])

    def test_not_ready_lists_what_is_missing(self):
        d = self.run_it([story("ACME-20", "Filter - DEV", NXT, points="", ac="TBD"),
                         story("ACME-21", "Big one - DEV", NXT, points=21),
                         story("ACME-22", "Fine - DEV", NXT),
                         story("ACME-23", "Later", "", labels=["needs_grooming"])])
        got = {r["key"]: r["missing"] for r in d["not_ready"]}
        self.assertEqual(got["ACME-20"], ["no acceptance criteria", "no points"])
        self.assertEqual(got["ACME-21"], ["21 points: split it"])
        self.assertNotIn("ACME-22", got)
        self.assertIn("labelled needs_grooming", got["ACME-23"])

    def test_unknown_acceptance_is_not_flagged(self):
        s = story("ACME-20", "Filter - DEV", NXT)
        del s["acceptance"]
        self.assertEqual(self.run_it([s])["not_ready"], [])

    def test_roadmap_gaps_and_similar_stories(self):
        plan = {"foundational": [{"capability": "Contract Config", "stories": [
            {"name": "Template Bulk Upload", "status": "this_year"},
            {"name": "Contract Bulk Upload", "status": "this_year"},
            {"name": "Approval Flow", "status": "delivered"}]}],
            "speciality": {"programs": [{"name": "ProgramC VA", "status": "this_year", "jira": ["ACME-9"]}]}}
        d = self.run_it([story("ACME-30", "Contract Bulk Upload - DEV", CUR)], plan)
        self.assertEqual([g["name"] for g in d["gaps"]], ["Template Bulk Upload"])
        self.assertEqual(d["gaps"][0]["similar"][0]["key"], "ACME-30")
        self.assertEqual(d["found"], 2)

    def test_invitees_partner_team_and_backup(self):
        d = self.run_it([story("ACME-40", "Export - DEV", NXT, points=""),
                         story("ACME-41", "Grid - DEV", NXT, points="", parent="ACME-2")])
        people = {p["key"]: p for p in d["people"]}
        self.assertEqual(people["ACME-40"]["partners"][0]["team"], "Acme Claims Scorecard")
        self.assertEqual(people["ACME-41"]["partners"], [])
        self.assertEqual(d["backup"], ["ACME-41"])
        self.assertIn("Score Owner", d["chat"])
        self.assertIn("Resource 18", d["chat"])
        self.assertIn("1. ACME-40", d["agenda"])
        self.assertEqual([c["who"] for c in d["core"]], ["Resource 17", "D. Resource 2", "Resource 19, Resource 18"])

    def test_render_read_only_has_no_buttons(self):
        d = self.run_it([story("ACME-10", "Bulk upload - DEV", CUR), story("ACME-20", "Filter - DEV", NXT, points="")])
        self.assertNotIn("gp-act", gp.render(d))
        live = gp.render(d, actions=True)
        self.assertIn('data-gpgroom="ACME-20"', live)
        self.assertIn('data-gpnew="Bulk upload - SIT"', live)
        self.assertIn("A guess", live)

    def test_missing_files_are_said(self):
        d = gp.analyse([], [], [], None, None, None, TODAY)
        self.assertEqual(len(d["notes"]), 2)

    @unittest.skip('checks the knowledge base or application folders of the team that built the copy')
    def test_repo_files_read(self):
        plan, teams, cfg = gp.context()
        self.assertTrue(gp.plan_items(plan))
        self.assertTrue(gp.core_people(teams, gp.settings(cfg)))
        self.assertIn("scorecard", gp.settings(cfg)["partner_teams"])

    def test_rows_from_issues(self):
        issue = {"key": "ACME-1", "fields": {"summary": "A - DEV", "issuetype": {"name": "Story"},
                 "s": ["com...Sprint@1[id=1,name=Acme Claims Sprint 26.4.2(10/7-10/27),state=ACTIVE]"], "p": 3, "a": "1. x", "e": "ACME-9"}}
        row = gp.rows_from_issues([issue], {"points": "p", "sprint": "s", "acceptance": "a", "epic_link": "e"})[0]
        self.assertEqual((row["sprint"], row["points"], row["parent"], row["acceptance"]),
                         ("Acme Claims Sprint 26.4.2(10/7-10/27)", 3, "ACME-9", "1. x"))


if __name__ == "__main__":
    unittest.main()


class SprintRoadmapTest(unittest.TestCase):
    ROWS = {2: {2: "10/7-10/27", 3: "10/28-11/17"}, 3: {2: "26.4.2", 3: "26.4.3", 4: "26.4.4", 5: "Notes"},
            4: {0: "ACME-1\nCHF-UI Phase 1", 1: "PG config", 2: "SIT Automation Testing", 3: "UAT e2e testing", 5: "Need model"},
            5: {1: "SWIFT Report", 3: "Analysis"},
            6: {0: "Distant Future"}, 7: {0: "ACME-9", 2: "Dev"}}

    def test_tab_is_read_by_epic_and_sprint(self):
        sheet = gp.parse_roadmap(self.ROWS, "test")
        self.assertEqual(sheet["sprints"]["26.4.2"], "10/7-10/27")
        self.assertEqual([e["key"] for e in sheet["epics"]], ["ACME-1", ""])
        self.assertEqual(sheet["epics"][0]["plan"], {"26.4.2": "SIT Automation Testing", "26.4.3": "UAT e2e testing"})
        self.assertEqual(sheet["epics"][0]["note"], "Need model")

    def test_planned_phase_without_a_story_is_a_gap(self):
        sheet = gp.parse_roadmap(self.ROWS, "Resource 17's sheet")
        stories = [story("ACME-10", "CHF PG config - SIT", CUR, parent="ACME-1")]
        d = gp.analyse(stories, [], [{"name": CUR, "state": "active"}, {"name": NXT, "state": "future", "start": "2026-10-28"}],
                       None, TEAMS, CFG, TODAY, sheet=sheet)
        got = [(p["token"], p["epic"], p["problem"]) for p in d["planned"]]
        self.assertEqual(got, [("26.4.3", "ACME-1", "no UAT story in 26.4.3"), ("26.4.3", "", "no epic in Jira")])
        self.assertEqual(d["gaps"], [])
        self.assertIn("On the roadmap with no story yet", d["agenda"])
        self.assertIn("no UAT story in 26.4.3", gp.render(d))
