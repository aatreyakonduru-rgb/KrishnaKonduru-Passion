"""Team Insights: numbers from the sessions, nameless findings and learning plans by user id in the repo, usage only on the PC."""
import datetime
import html as html_mod
import json
import os
import re
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

import gen_dashboard  # noqa: E402
import team_insights as T  # noqa: E402

FIXTURE = os.path.join(HERE, "..", "fixtures", "dashboard-demo.json")
DAY = datetime.date(2026, 10, 31)
RAW = {
    "month": "2026-10",
    "names": {"user-org": "Org, Person"},
    "sessions": [
        {"session_id": "a", "user_id": "user-ann", "origin": "webapp", "category": "feature_development", "acus": 10,
         "prs": [{"url": "u1", "state": "merged"}]},
        {"session_id": "b", "user_id": "user-ann", "origin": "api", "category": "bug_fixing", "acus": 4.5, "prs": []},
        {"session_id": "c", "user_id": "user-org", "origin": "webapp", "category": "feature_development", "acus": 2},
    ],
    "analyses": {"a": {"num_user_messages": 3}, "b": {"num_user_messages": 9}},
}
FINDINGS = {
    "prompt_patterns": [{"pattern": "No acceptance criteria", "sessions": 2, "people": 1, "before": "fix it",
                         "better": "Fix X; done when Y", "person": "Example, Ann"}],
    "gaps": [{"gap": "Doesn't run /impact-radar first", "sessions": 2, "people": 1, "command": "/impact-radar",
              "person": "Example, Ann"}],
    "repetitive": [{"task": "Same weekly report by hand", "sessions": 4, "people": 2, "suggestion": "/status-report"}],
    "wins": [{"person": "Example, Ann", "what": "Merged a PR in one short session"}],
    "recommendations": [{"what": "Add a /weekly-report command", "why": "asked 4 times", "sessions": 4, "people": 2,
                         "gain": "about an hour a week", "touches": ".devin/skills/status-report"}],
    "people": {"Example, Ann": {"gaps": ["Doesn't run /impact-radar first"], "tips": ["Start with /impact-radar"],
                                "questions": ["What slowed the bug fix down?"], "prompt_before": "fix it",
                                "prompt_after": "Fix X; done when Y"}},
}
PEOPLE = {"user-ann": ("Example, Ann", "developer")}


class TeamInsightsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = self.tmp.name
        self.patches = [
            mock.patch.object(T, "TEAM_DIR", os.path.join(base, "team-insights")),
            mock.patch.object(T, "RECS_PATH", os.path.join(base, "recs.yaml")),
            mock.patch.object(T, "CHECKINS_PATH", os.path.join(base, "checkins.yaml")),
            mock.patch.object(T, "PLANS_DIR", os.path.join(base, "team-insights", "people")),
            mock.patch.object(T, "roster", lambda path=None: PEOPLE),
            mock.patch.dict(os.environ, {"SDLC_SESSION_HOME": os.path.join(base, "home")}),
        ]
        for p in self.patches:
            p.start()
        if hasattr(gen_dashboard._insights, "cache"):
            del gen_dashboard._insights.cache

    def tearDown(self):
        for p in self.patches:
            p.stop()
        if hasattr(gen_dashboard._insights, "cache"):
            del gen_dashboard._insights.cache
        self.tmp.cleanup()

    def write_month(self, private=True):
        shared, priv, recs = T.build(RAW, FINDINGS, PEOPLE, today=DAY)
        data = {"recommendations": []}
        T.merge_recommendations(data, recs, shared["month"])
        T.dump_yaml(os.path.join(T.TEAM_DIR, "2026-10.yaml"), shared)
        T.dump_yaml(T.RECS_PATH, data)
        plans, _ = T.learning_plans(FINDINGS, "2026-10", PEOPLE, today=DAY)
        for plan in plans.values():
            T.write_plan(plan)
        if private:
            T.dump_yaml(os.path.join(T.private_dir(), "2026-10.yaml"), priv)
        return shared, priv

    def test_numbers_come_from_the_sessions(self):
        team, people = T.stats(RAW, PEOPLE)
        self.assertEqual((team["sessions"], team["people"], team["on_roster"], team["acus"]), (3, 2, 1, 16.5))
        self.assertEqual((team["merged_prs"], team["acus_per_merged_pr"], team["analysed"]), (1, 16.5, 2))
        ann = people[0]
        self.assertEqual((ann["person"], ann["sessions"], ann["median_messages"]), ("Example, Ann", 2, 6.0))
        self.assertEqual(people[1]["person"], "Org, Person")
        self.assertFalse(people[1]["on_roster"])

    def test_the_shared_file_names_only_the_wins(self):
        shared, private, _ = T.build(RAW, FINDINGS, PEOPLE, today=DAY)
        text = json.dumps({k: v for k, v in shared.items() if k != "wins"})
        self.assertNotIn("Example, Ann", text)
        self.assertNotIn("user-ann", text)
        self.assertEqual(shared["wins"][0]["person"], "Example, Ann")
        self.assertEqual(private["people"][0]["person"], "Example, Ann")

    def test_recommendations_get_ids_and_are_not_repeated(self):
        data = {"recommendations": []}
        _, _, recs = T.build(RAW, FINDINGS, PEOPLE, today=DAY)
        self.assertEqual(T.merge_recommendations(data, recs, "2026-10")[0]["id"], "R-001")
        self.assertEqual(T.merge_recommendations(data, recs, "2026-11"), [])
        self.assertEqual(T.decide(data, "R-001", "accepted", "Lead, Tech", today=DAY)["status"], "accepted")
        with self.assertRaises(ValueError):
            T.decide(data, "R-001", "maybe", "x")

    def test_learning_plan_file_is_named_by_user_id_and_holds_no_name(self):
        self.write_month()
        path = os.path.join(T.PLANS_DIR, "2026", "10", "user-ann.md")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertNotIn("Example, Ann", text)
        self.assertIn("- [ ] Doesn't run /impact-radar first (open, since 2026-10)", text)
        plan = T.read_plan(path)
        self.assertEqual((plan["devin_user_id"], plan["tips"]), ("user-ann", ["Start with /impact-radar"]))
        self.assertEqual(list(T.all_plans()), ["2026-10"])

    def test_findings_people_need_a_devin_user_id(self):
        plans, skipped = T.learning_plans({"people": {"Nobody, Known": {"gaps": ["x"]}, "user-zz": {"gaps": ["y"]}}},
                                          "2026-10", PEOPLE, today=DAY)
        self.assertEqual((list(plans), skipped), (["user-zz"], ["Nobody, Known"]))

    def test_learning_list_carries_over_months(self):
        self.write_month()
        month, plan = T.latest_plan("user-ann")
        T.mark_learned(plan, "Doesn't run /impact-radar first", "taught", DAY)
        T.write_plan(plan)
        nov = {"people": {"user-ann": {"gaps": ["Doesn't run /impact-radar first", "Skips the test plan"]}}}
        plans, _ = T.learning_plans(nov, "2026-11", PEOPLE, today=DAY)
        rows = plans["user-ann"]["learning"]
        self.assertEqual([(r["gap"], r["status"]) for r in rows],
                         [("Doesn't run /impact-radar first", "taught"), ("Skips the test plan", "open")])
        self.assertEqual(rows[0]["seen_again"], "2026-11")

    def test_teach_next_gives_one_open_item_at_a_time(self):
        self.write_month()
        lesson = T.teach_next("Example, Ann", PEOPLE)
        self.assertEqual((lesson["due"], lesson["gap"], lesson["command"], lesson["left"]),
                         (True, "Doesn't run /impact-radar first", "/impact-radar", 1))
        self.assertTrue(lesson["file"].endswith(os.path.join("2026", "10", "user-ann.md")))
        _, plan = T.latest_plan("user-ann")
        T.mark_learned(plan, lesson["gap"], "taught", DAY)
        T.write_plan(plan)
        self.assertFalse(T.teach_next("Example, Ann", PEOPLE)["due"])
        self.assertFalse(T.teach_next("Nobody, Known", PEOPLE)["due"])

    def test_checkin_once_a_month(self):
        data = {"checkins": []}
        self.assertTrue(T.checkin_due(data, "Example, Ann", DAY))
        T.checkin_add(data, "Example, Ann", "quick search", "slow Jira", DAY)
        self.assertFalse(T.checkin_due(data, "Example, Ann", DAY))
        self.assertTrue(T.checkin_due(data, "Example, Ann", datetime.date(2026, 11, 2)))

    def test_no_dollars_without_a_rate(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as fh:
            fh.write("cost:\n  usd_per_acu:\n")
        self.assertIsNone(T.usd_per_acu(fh.name))
        with open(fh.name, "w") as out:
            out.write("cost:\n  usd_per_acu: 2.25\n")
        self.assertEqual(T.usd_per_acu(fh.name), 2.25)
        os.unlink(fh.name)

    def page(self):
        with tempfile.TemporaryDirectory() as out:
            path = os.path.join(out, "d.html")
            gen_dashboard.main(["--cache", FIXTURE, "--user", "demo", "--lens", "tech_lead", "-o", path])
            with open(path, encoding="utf-8") as fh:
                return html_mod.unescape(fh.read())

    def test_tech_lead_dashboard_has_team_insights_and_recommended_changes(self):
        self.write_month()
        html = self.page()
        labels = re.findall(r'tab-group__label" aria-hidden="true">([^<]*)<', html)
        self.assertEqual(labels[-2:], ["Framework feedback", "👥☁️ Team Devin Cloud Usage"])
        for tab in ("Overview", "Usage", "Cost", "Prompts", "Skill gaps", "Doing well", "Learning plan",
                    "Ask the team", "Recommended changes"):
            self.assertIn('<span class="tab-label">%s</span>' % tab, html)
        self.assertIn('class="ti-person" value="Example, Ann"', html)
        self.assertIn('data-person="Example, Ann"', html)
        self.assertNotIn('id="ti-usd"', html)
        self.assertNotIn("<th>$</th>", html)
        self.assertIn("Add a /weekly-report command", html)
        self.assertIn("What slowed the bug fix down?", html)

    def test_learning_plan_tab_shows_year_month_and_the_name(self):
        self.write_month(private=False)
        html = self.page()
        self.assertIn("Usage and ACUs per person aren't on this PC", html)
        self.assertNotIn('class="ti-person"', html)
        self.assertIn('<details class="ti-year" open><summary>2026</summary>', html)
        self.assertIn('<details class="ti-month" open><summary>October 2026 · 1 people</summary>', html)
        self.assertIn('<details class="ti-plan" data-person="Example, Ann"><summary><strong>Example, Ann</strong> · 1 open', html)
        self.assertIn("people/2026/10/user-ann.md", html)
        self.assertIn("What slowed the bug fix down?", html)

    def test_deck_names_wins_not_gaps(self):
        shared, _ = self.write_month()
        page = T.deck(shared, [])
        self.assertIn("Example, Ann</b>: Merged a PR", page)
        self.assertIn("Doesn't run /impact-radar first", html_mod.unescape(page))
        self.assertIn("Acme Claims artifact kit", page)


if __name__ == "__main__":
    unittest.main()


class LinkIdsTest(unittest.TestCase):
    def test_fills_only_empty_ids_whose_email_is_on_the_roster(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "people.yaml")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("# roster\npeople:\n"
                         "- jira_user: AX1\n  name: One, Person\n  email: One.Person@x.com\n  devin_user_id: null\n  roles: []\n"
                         "- jira_user: AX2\n  name: Two, Person\n  email: two@x.com\n  devin_user_id: user-aaa\n  roles: []\n")
            text, report = T.link_ids({"user-111": ["one.person@x.com"], "user-bbb": ["two@x.com"],
                                       "user-999": ["nobody@x.com"]}, path)
        self.assertIn("  devin_user_id: user-111\n", text)
        self.assertIn("  devin_user_id: user-aaa\n", text)
        self.assertTrue(text.startswith("# roster\n"))
        self.assertEqual(report["filled"], ["One, Person user-111"])
        self.assertEqual(len(report["clash"]), 1)
        self.assertEqual(report["not_on_roster"], ["user-999 nobody@x.com"])
