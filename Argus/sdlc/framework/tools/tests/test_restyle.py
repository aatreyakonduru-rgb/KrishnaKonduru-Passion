import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from artifact_kit import restyle  # noqa: E402

KIT = '<meta name="generator" content="Acme Claims artifact kit" />'


def page(css, subtitle='<p class="a-header__subtitle">Plan &amp; <b>sprint</b></p>'):
    return '%s<style>%s old */\n%s</style>%s' % (KIT, restyle.START, restyle.END, subtitle) if css is None else \
        '%s<style>%s</style>%s' % (KIT, css, subtitle)


class RestyleTests(unittest.TestCase):
    NEW = restyle.START + " new */\n" + restyle.END

    def test_swaps_css_and_adds_the_details_tooltip(self):
        out, status = restyle.restyle(page(None), self.NEW, [])
        self.assertEqual(status, "updated")
        self.assertIn(" new */", out)
        self.assertNotIn(" old */", out)
        self.assertIn('<p class="a-header__subtitle" title="Plan &amp; sprint">Plan &amp; <b>sprint</b></p>', out)

    def test_current_page_is_left_alone(self):
        done, _ = restyle.restyle(page(None), self.NEW, [])
        self.assertEqual(restyle.restyle(done, self.NEW, []), (done, "current"))

    def test_skips_pages_outside_the_kit(self):
        self.assertEqual(restyle.restyle("<html></html>", self.NEW, [])[1], "not a kit page")
        self.assertEqual(restyle.restyle(KIT + "<style></style>", self.NEW, [])[1], "no Acme Claims styles found")


if __name__ == "__main__":
    unittest.main()
