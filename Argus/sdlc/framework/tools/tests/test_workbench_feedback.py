"""Argus self-observation (console/observer.py), the feedback batch files (framework_feedback.py import)
and the Leads dashboard tabs that read them."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "console"))
sys.path.insert(0, os.path.join(HERE, ".."))

import observer  # noqa: E402
import framework_feedback as ff  # noqa: E402


class ObserverTests(unittest.TestCase):
    def setUp(self):
        self.obs = observer.Observer(tempfile.mkdtemp(prefix="sdlc-observer-"))

    def test_known_problems_get_their_fix_and_unknown_ones_need_a_look(self):
        self.assertEqual(observer.suggest("jira", "HTTP Error 401: Unauthorized")[0], "Jira refused the key")
        self.assertEqual(observer.suggest("devin", "the bridge is not running")[0], "The Devin bridge stopped")
        self.assertEqual(observer.suggest("nowhere", "odd")[0], observer.NEEDS_A_LOOK[0])

    def test_repeats_are_counted_on_one_line(self):
        self.obs.note("jira", "timed out reading ACME-12", now=1000)
        self.obs.note("jira", "timed out reading ACME-99", now=1100)  # within the quiet time: not counted again
        self.obs.note("jira", "timed out reading ACME-7", now=1000 + observer.QUIET_SECONDS + 5)
        lines = list(self.obs.lines.values())
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["count"], 2)

    def test_a_batch_sends_each_thing_once_and_survives_a_restart(self):
        self.obs.note("api", "500 on POST /api/actions: boom", now=1000)
        self.obs.add_feedback("Ann", "Developer", "idea", "Dashboard", "More colour", {"page": "home"})
        block, batch = self.obs.batch("Ann", "Developer", {"version": "1"}, now=2000)
        self.assertTrue(block.startswith(observer.BLOCK + " v1\n"))
        self.obs.mark_sent(block, now=2000)
        self.assertEqual(self.obs.batch("Ann", "Developer", {}), ("", ""))
        again = observer.Observer(self.obs.dir)
        self.assertEqual((again.pending, again.unsent()), ([], []))
        self.assertFalse(again.daily_due(24, now=2000 + 3600))

    def test_a_repeat_only_moves_last_seen_and_is_written_at_most_every_save_seconds(self):
        self.obs.note("jira", "timed out", now=1000)
        with mock.patch.object(self.obs, "_write", wraps=self.obs._write) as w:
            self.obs.note("jira", "timed out", now=1010)
            w.assert_not_called()
            self.obs.note("jira", "timed out", now=1000 + observer.SAVE_SECONDS + 1)
            self.assertEqual([c[0][0] for c in w.call_args_list], [self.obs.noticed_path])
        self.assertEqual(observer.Observer(self.obs.dir).lines[next(iter(self.obs.lines))]["last"],
                         1000 + observer.SAVE_SECONDS + 1)

    def test_noticing_never_raises(self):
        self.obs.noticed_path = "/proc/no/such/dir/noticed.json"
        self.assertIsNone(self.obs.note("api", "x"))


class BatchFileTests(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="sdlc-wbfb-")
        obs = observer.Observer(tempfile.mkdtemp(prefix="sdlc-observer-"))
        obs.note("run_stuck", "action /intake: no answer from Devin for 41 minutes", now=1000)
        obs.add_feedback("Ann", "Developer", "problem", "Argus page", "Stuck after design; SSN 123-45-6789",
                         {"page": "run", "runs": [{"session": "https://example.invalid/s", "this_one": True}]})
        self.block, self.batch = obs.batch("Ann", "Developer", {"version": "1"}, now=1700000000)

    def test_import_writes_one_new_file_and_refuses_it_twice(self):
        path, body = ff.import_block(self.block, write=True, base=self.base)
        self.assertTrue(path.endswith(self.batch + ".yaml"))
        self.assertIn("<removed>", body["feedback"][0]["text"])
        with self.assertRaises(ValueError):
            ff.import_block(self.block, write=True, base=self.base)
        with self.assertRaises(ValueError):
            ff.parse_block("SDLC-WORKBENCH-FEEDBACK v1\n{}")

    def test_dashboard_tabs_read_the_files(self):
        ff.import_block(self.block, write=True, base=self.base)
        batches = ff.load_batches(self.base)
        noticed = ff.noticed_summary(batches)
        self.assertEqual((noticed[0]["title"], noticed[0]["people"]), ("A Devin run went quiet", 1))
        self.assertEqual(ff.form_feedback(batches)[0]["by"], "Ann")
        import gen_dashboard
        real = ff.BATCH_DIR
        ff.BATCH_DIR = self.base
        try:
            orig = ff.load_batches.__defaults__
            ff.load_batches.__defaults__ = (self.base,)
            html = json.dumps([gen_dashboard.render_team_feedback({}), gen_dashboard.render_workbench_noticed({})])
        finally:
            ff.load_batches.__defaults__ = orig
            ff.BATCH_DIR = real
        self.assertIn("Session details", html)
        self.assertIn("https://example.invalid/s", html)
        self.assertIn("Press Wake once", html)


if __name__ == "__main__":
    unittest.main()
