"""Feedback on the framework: one line per gate brief or artefact, summed per thing."""
import datetime
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

import framework_feedback as F  # noqa: E402


class FrameworkFeedbackTest(unittest.TestCase):
    def test_summary_puts_the_least_useful_first(self):
        data = {"feedback": []}
        day = datetime.date(2026, 10, 14)
        F.add(data, "Example, Ann", "SDLC_04 brief", "yes", today=day)
        F.add(data, "Example, Ben", "Gap analysis", "no", "too long", today=day)
        rows = F.summary(data)
        self.assertEqual(rows[0]["on"], "Gap analysis")
        self.assertEqual(rows[0]["notes"], ["Example, Ben (2026-10-14): too long"])
        with self.assertRaises(ValueError):
            F.add(data, "A", "x", "maybe")

    def test_the_shipped_file_loads(self):
        self.assertEqual(F.load()["feedback"], [])


if __name__ == "__main__":
    unittest.main()
