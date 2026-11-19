import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import delivery_teams  # noqa: E402
import gen_dashboard  # noqa: E402


class DeliveryTeamsTest(unittest.TestCase):
    def test_repo_sheet_is_complete(self):
        data = delivery_teams.load()
        self.assertEqual(delivery_teams.problems(data), [])
        self.assertIn("Acme-Claims-Web", [t["it_team"] for t in data["teams"]])

    def test_find_by_key_name_or_it_team(self):
        data = {"teams": [{"key": "fin", "name": "Financial", "it_team": "EDA-ACME-Financial", "board": 1,
                           "also_called": ["Finance"]}]}
        for name in ("fin", "financial", "Finance", "eda-acme-financial"):
            self.assertEqual(delivery_teams.find(data, name)["key"], "fin")
        self.assertIsNone(delivery_teams.find(data, "scorecard"))

    def test_problems(self):
        found = delivery_teams.problems({"teams": [{"key": "a", "name": "A"}, {"key": "a", "name": "B",
                                                                                "it_team": "x", "board": 2}]})
        self.assertIn("a: no it_team", found)
        self.assertIn("a: key used twice", found)

    def test_copies_render(self):
        data = delivery_teams.load()
        md, page = delivery_teams.markdown(data), delivery_teams.page(data)
        for team in data["teams"]:
            self.assertIn("## " + team["name"], md)
        self.assertTrue(page.startswith("<!doctype html>"))


class LearnPanelTest(unittest.TestCase):
    def test_panel(self):
        empty = gen_dashboard.render_learn({"title": "Questions for you"}, [])
        self.assertEqual((empty["body"], empty["count"]), ("", 0))
        self.assertIn("no questions", empty["empty"])
        full = gen_dashboard.render_learn({}, [{"id": "L-001", "question": "Ready <statuses>?", "update": "f"}])
        self.assertEqual(full["count"], 1)
        self.assertIn("L-001", full["body"])
        self.assertIn("Ready &lt;statuses&gt;?", full["body"])

    def test_every_lens_has_the_tab(self):
        config = gen_dashboard.lens_config()
        self.assertEqual(config["panels"]["learn_questions"]["kind"], "learn")
        for lens_id, lens in config["lenses"].items():
            self.assertIn("learn_questions", lens.get("panels") or [], lens_id)


if __name__ == "__main__":
    unittest.main()
