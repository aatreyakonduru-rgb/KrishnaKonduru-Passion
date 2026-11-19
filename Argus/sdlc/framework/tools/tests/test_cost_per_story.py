import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scrum_metrics as sm  # noqa: E402


def data():
    return {"sprint": {"name": "S1"},
            "stories": [{"key": "ACME-1", "fields": {"summary": "a", sm.F_POINTS: 3, "subtasks": [{"key": "ACME-2"}]}},
                        {"key": "ACME-3", "fields": {"summary": "b", sm.F_POINTS: 2}}],
            "subtasks": [{"key": "ACME-2", "fields": {"parent": {"key": "ACME-1"}, "labels": ["AI-Used"],
                                                      "timespent": 6 * 3600}}]}


class CostPerStoryTest(unittest.TestCase):
    def test_hours_from_subtasks_and_no_cost_without_rate(self):
        rows = sm.cost_rows(data(), {"cost": {"hourly_rate": None}})
        self.assertEqual(rows[0]["hours"], 6.0)
        self.assertEqual(rows[0]["ai_hours"], 6.0)
        self.assertEqual(rows[0]["per_point"], 2.0)
        self.assertIsNone(rows[0]["cost"])
        self.assertEqual(rows[1]["hours"], 0.0)

    def test_cost_with_rate(self):
        self.assertEqual(sm.cost_rows(data(), {"cost": {"hourly_rate": 50}})[0]["cost"], 300)

    def test_render_says_no_rate(self):
        body, count, attention = sm.render("cost", data(), {"cost": {}, "targets": {}})
        self.assertIn("no hourly rate set", body)
        self.assertEqual((count, attention), (1, "watch"))


if __name__ == "__main__":
    unittest.main()
