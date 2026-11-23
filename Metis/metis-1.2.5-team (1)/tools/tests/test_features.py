import os
import shutil
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ui"))
import features  # noqa: E402
import ui_common as C  # noqa: E402


class Features(unittest.TestCase):
    def setUp(self):
        self.kb = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.kb)

    def profile(self, data):
        os.makedirs(os.path.join(self.kb, ".metis"), exist_ok=True)
        with open(os.path.join(self.kb, ".metis", "kb-profile.yaml"), "w", encoding="utf-8") as fh:
            yaml.safe_dump(data, fh)

    def test_every_feature_names_real_files_and_the_evidence_that_ends_it(self):
        self.assertEqual(features.check(), [])

    def test_off_by_default_on_when_listed_or_all(self):
        self.assertFalse(features.enabled(self.kb, "notify"))
        self.profile({"experimental": {"enable": ["notify"]}})
        self.assertTrue(features.enabled(self.kb, "notify"))
        self.assertFalse(features.enabled(self.kb, "federation"))
        self.profile({"experimental": {"enable": "all"}})
        self.assertTrue(features.enabled(self.kb, "federation"))

    def test_a_feature_that_is_not_experimental_is_always_on(self):
        self.assertTrue(features.enabled(self.kb, "verify_kb"))

    def test_hidden_screens_follow_the_switches(self):
        self.assertIn("/notify", features.hidden_screens(self.kb))
        self.profile({"experimental": {"enable": ["notify", "federation"]}})
        self.assertEqual(features.hidden_screens(self.kb) & {"/notify", "/federation"}, set())

    def test_rail_hides_an_experimental_screen_but_keeps_it_when_open(self):
        saved = list(C.NAV_MORE)
        C.NAV_MORE[:] = [("/notify", "Notifications"), ("/pack", "Context pack")]
        try:
            ctx = C.Ctx(self.kb, "tok", "")
            html = C.rail(ctx, "/", {})
            self.assertNotIn('href="/notify"', html)
            self.assertIn('href="/pack"', html)
            self.assertIn('href="/notify"', C.rail(ctx, "/notify", {}))
            self.profile({"experimental": {"enable": ["notify"]}})
            self.assertIn('href="/notify"', C.rail(ctx, "/", {}))
        finally:
            C.NAV_MORE[:] = saved


if __name__ == "__main__":
    unittest.main()
