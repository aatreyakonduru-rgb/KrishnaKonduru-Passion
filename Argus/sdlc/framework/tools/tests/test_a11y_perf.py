import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import a11y_perf  # noqa: E402

RULES = {"accessibility": {"blocking": ["img-alt"], "warning": ["heading-order"]},
         "performance": {"lcp_ms": 2500, "requests": 80}}


def page(findings=(), lcp=1200):
    return {"url": "http://x/p", "findings": list(findings), "perf": {"lcp_ms": lcp, "requests": 10}}


class A11yPerfTest(unittest.TestCase):
    def test_clean_page_passes(self):
        self.assertEqual(a11y_perf.grade(page(), RULES)["status"], "PASS")

    def test_blocking_finding_fails_warning_does_not(self):
        warn = {"rule": "heading-order", "element": "<h3>", "message": "jump"}
        self.assertEqual(a11y_perf.grade(page([warn]), RULES)["status"], "PASS")
        alt = {"rule": "img-alt", "element": "<img>", "message": "no alt"}
        self.assertEqual(a11y_perf.grade(page([alt]), RULES)["status"], "FAIL")

    def test_slow_page_fails(self):
        self.assertEqual(a11y_perf.grade(page(lcp=4000), RULES)["status"], "FAIL")

    def test_unread_page_is_never_passed(self):
        pages = [a11y_perf.grade({"url": "u", "error": "timeout"}, RULES), a11y_perf.grade(page(), RULES)]
        self.assertEqual(a11y_perf.overall(pages), "INCOMPLETE")
        self.assertIn("Could not be read: timeout", a11y_perf.render("S-1", pages))

    def test_shipped_rules_load(self):
        self.assertIn("lcp_ms", a11y_perf.load_rules()["performance"])


if __name__ == "__main__":
    unittest.main()
