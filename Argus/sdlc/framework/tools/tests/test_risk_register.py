import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import risk_register as rr  # noqa: E402

TODAY = datetime.date(2026, 10, 15)


class RiskRegisterTest(unittest.TestCase):
    def test_late_dependency_first_then_highest_risk(self):
        d = {"items": []}
        rr.add(d, "ACME-1", "risk", "Snowflake view late", "Resource 17", "Resource 16", "low", "medium", today=TODAY)
        rr.add(d, "ACME-1", "risk", "No test data", "Resource 16", "Resource 16", "high", "high", today=TODAY)
        rr.add(d, "ACME-2", "dependency", "ETL feed", "Resource 3", "Resource 16", team="DataLake", needed_by="2026-10-10",
               today=TODAY)
        self.assertEqual([r["id"] for r in rr.rows(d, TODAY)], ["D-1", "R-2", "R-1"])

    def test_closed_items_drop_off(self):
        d = {"items": []}
        rr.add(d, "ACME-1", "risk", "x", "Resource 17", "Resource 16", "low", "low", today=TODAY)
        rr.close(d, "R-1", "Resource 17", "mitigated", today=TODAY)
        self.assertEqual(rr.rows(d, TODAY), [])

    def test_bad_input_is_refused(self):
        with self.assertRaises(ValueError):
            rr.add({"items": []}, "ACME-1", "risk", "x", "Resource 17", "Resource 16", "huge", "low")
        with self.assertRaises(ValueError):
            rr.add({"items": []}, "ACME-1", "dependency", "x", "Resource 17", "Resource 16", needed_by="2026-10-10")

    def test_shipped_register_loads(self):
        self.assertEqual(rr.load()["items"], [])


if __name__ == "__main__":
    unittest.main()
