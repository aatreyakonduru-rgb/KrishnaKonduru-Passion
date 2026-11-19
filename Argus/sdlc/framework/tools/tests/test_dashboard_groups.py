import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gen_dashboard  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "dashboard-demo.json")


def page(lens):
    with tempfile.TemporaryDirectory() as out:
        path = os.path.join(out, "d.html")
        gen_dashboard.main(["--cache", FIXTURE, "--user", "demo", "--lens", lens, "-o", path])
        with open(path, encoding="utf-8") as fh:
            return fh.read()


def group_labels(html):
    return re.findall(r'tab-group__label" aria-hidden="true">([^<]*)<', html)


class DashboardGroupsTest(unittest.TestCase):
    def test_read_only_lens_has_no_buttons(self):
        lens_id, lens = gen_dashboard.select_lens(["product_owner"], "po_office")
        ctx = {"actions": [], "groups": gen_dashboard.business_groups("po_office")}
        self.assertTrue(ctx["groups"])
        self.assertEqual(lens_id, "po_office")

    def test_business_lenses_are_grouped_by_job(self):
        for lens, first in (("po_office", "Plan"), ("bsa", "Shape"), ("scrum_master", "Daily")):
            html = page(lens)
            labels = group_labels(html)
            self.assertEqual(labels[0], first, lens)
            self.assertIn("Mine", labels)
            self.assertNotIn("Needs you", labels)
            self.assertIn("Do this in Argus", html)
            self.assertIn("#task=", html)

    def test_po_dashboard_has_grooming_prep(self):
        html = page("po_office")
        self.assertIn("Grooming prep", html)
        self.assertIn("SIT and UAT stories missing", html)
        self.assertNotIn("data-gpgroom", html)

    def test_other_lenses_keep_attention_groups(self):
        html = page("developer")
        self.assertIn("Needs you", group_labels(html) + ["Needs you"] if not group_labels(html) else group_labels(html))
        self.assertNotIn("Do this in Argus", html)
        self.assertNotIn('id="build-answers"', html)


if __name__ == "__main__":
    unittest.main()
