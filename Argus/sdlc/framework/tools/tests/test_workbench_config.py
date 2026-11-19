"""Argus config tab (tools/workbench_config.py): how Test on my PC runs per person."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import workbench_config as wc  # noqa: E402

PEOPLE = {"people": [{"name": "Resource 3", "jira_user": "resource3", "email": "k@x.com",
                      "devin_user_id": "user-31"}, {"name": "Resource 6", "jira_user": "resource6"}]}
SETTINGS = {"default": {"test_on_pc": "devin_local"}, "people": {"resource6": {"test_on_pc": "local_hands"}}}


class WorkbenchConfigTest(unittest.TestCase):
    def test_mode_for_any_identity_falls_back_to_default(self):
        self.assertEqual(wc.mode_for("user-31", SETTINGS, PEOPLE), "devin_local")
        self.assertEqual(wc.mode_for("k@x.com", SETTINGS, PEOPLE), "devin_local")
        self.assertEqual(wc.mode_for("resource6", SETTINGS, PEOPLE), "local_hands")
        self.assertEqual(wc.mode_for("nobody", {}, PEOPLE), "devin_local")

    def test_grid(self):
        dflt, rows = wc.grid(SETTINGS, PEOPLE)
        self.assertEqual(dflt, "devin_local")
        self.assertEqual([(r["own"], r["applies"]) for r in rows], [("", "devin_local"), ("local_hands", "local_hands")])

    def test_apply_and_block(self):
        block = ("SDLC-DASHBOARD-WORKBENCH-CONFIG v1\n- person: default | test_on_pc: cloud_vm\n"
                 "- person: resource3 | test_on_pc: off\n- person: resource6 | test_on_pc: default\nEND")
        settings, said = wc.apply(wc.parse_block(block), SETTINGS, PEOPLE)
        self.assertEqual(settings["default"]["test_on_pc"], "cloud_vm")
        self.assertEqual(settings["people"], {"resource3": {"test_on_pc": "off"}})
        self.assertEqual(len(said), 3)
        self.assertEqual(SETTINGS["people"], {"resource6": {"test_on_pc": "local_hands"}})

    def test_refuses_unknown_person_or_mode(self):
        with self.assertRaises(ValueError):
            wc.apply([("ZZ1", "off")], SETTINGS, PEOPLE)
        with self.assertRaises(ValueError):
            wc.apply([("resource3", "laptop")], SETTINGS, PEOPLE)
        with self.assertRaises(ValueError):
            wc.parse_block("SDLC-DASHBOARD-WORKBENCH-CONFIG v1\n- nonsense\nEND")

    def test_write_keeps_the_header(self):
        d = tempfile.mkdtemp()
        try:
            path = os.path.join(d, "s.yaml")
            open(path, "w").write("# header\n# more\ndefault:\n  test_on_pc: devin_local\npeople: {}\n")
            wc.write(path, {"default": {"test_on_pc": "off"}, "people": {"AM1": {"test_on_pc": "cloud_vm"}}})
            text = open(path).read()
            self.assertTrue(text.startswith("# header\n# more\n"))
            self.assertEqual(wc.load(path)["people"]["AM1"]["test_on_pc"], "cloud_vm")
        finally:
            shutil.rmtree(d)

    def test_repo_file_is_valid(self):
        s = wc.load(wc.SETTINGS)
        self.assertIn(wc.default_mode(s), wc.MODES)


if __name__ == "__main__":
    unittest.main()
