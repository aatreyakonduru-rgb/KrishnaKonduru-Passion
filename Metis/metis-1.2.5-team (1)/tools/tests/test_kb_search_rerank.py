"""kb_search optional re-ranking: team boost and bounded, thresholded feedback nudge. Both are off by default."""
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
for _p in (TOOLS, os.path.join(TOOLS, "ui")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import kb_search as S  # noqa: E402
import telemetry  # noqa: E402

PROFILE = {"owners": {"kb_owner": "Ana Lead"},
           "gate": {"teams": [{"name": "Data", "owns": ["data/*"], "approvers": ["Dee Data"]},
                              {"name": "App", "owns": ["app/*"], "approvers": ["Al App"]}]}}


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


class Rerank(unittest.TestCase):
    def setUp(self):
        self.kb = os.path.join(tempfile.mkdtemp(), "KB")
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump(PROFILE))
        write(os.path.join(self.kb, "_EVIDENCE", "files", "r.txt"), "refund window\n")
        # the app page is slightly the better match; the data page is close behind
        write(os.path.join(self.kb, "app", "refund.md"), '# Refund\n\nThe refund window is 30 days. [E: file:r.txt "refund window"]\n')
        write(os.path.join(self.kb, "data", "refund.md"), '# Refund data\n\nThe refund window column is a number. [E: file:r.txt "refund window"]\n')

    def tearDown(self):
        shutil.rmtree(os.path.dirname(self.kb), ignore_errors=True)

    def order(self, **kw):
        return [(r["path"], r) for r in S.search(self.kb, "refund window", **kw)["results"]]

    def test_default_is_unchanged_and_has_no_adjustment(self):
        for _, r in self.order():
            self.assertNotIn("adjusted", r)
            self.assertNotIn("base_score", r)

    def test_team_boost_is_bounded_and_explained(self):
        base = dict((p, r["score"]) for p, r in self.order())
        got = dict(self.order(team="Data"))
        self.assertAlmostEqual(got["data/refund.md"]["score"], base["data/refund.md"] * 1.15, places=3)
        self.assertEqual(got["data/refund.md"]["base_score"], base["data/refund.md"])
        self.assertIn("team Data +15%", got["data/refund.md"]["adjusted"][0])
        self.assertEqual(got["app/refund.md"]["score"], base["app/refund.md"])
        self.assertNotIn("adjusted", got["app/refund.md"])
        self.assertEqual(len(got), len(base))  # nothing hidden

    def test_team_auto_uses_the_approvers_team(self):
        got = dict(self.order(team="auto", who="Dee Data"))
        self.assertIn("adjusted", got["data/refund.md"])
        rep = S.search(self.kb, "refund window", team="auto", who="Pat Nobody")
        self.assertTrue(any("not an approver" in n for n in rep["notes"]))
        self.assertTrue(all("adjusted" not in r for r in rep["results"]))

    def test_feedback_needs_three_ratings_and_is_capped(self):
        marks = {"app/refund.md": {"up": 1, "down": 1, "declined": 0},          # 2 ratings: ignored
                 "data/refund.md": {"up": 0, "down": 40, "declined": 0}}        # capped at -10%
        base = dict((p, r["score"]) for p, r in self.order())
        with mock.patch.object(telemetry, "rated", return_value=marks):
            got = dict(self.order(feedback=True))
        self.assertNotIn("adjusted", got["app/refund.md"])
        self.assertAlmostEqual(got["data/refund.md"]["score"], base["data/refund.md"] * 0.9, places=3)
        self.assertIn("-10%", got["data/refund.md"]["adjusted"][0])

    def test_feedback_follows_profile_key_and_explicit_false_wins(self):
        prof = dict(PROFILE, search={"feedback_rank": True})
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump(prof))
        marks = {"data/refund.md": {"up": 5, "down": 0, "declined": 0}}
        with mock.patch.object(telemetry, "rated", return_value=marks):
            self.assertIn("adjusted", dict(self.order())["data/refund.md"])
            self.assertNotIn("adjusted", dict(self.order(feedback=False))["data/refund.md"])

    def test_cli_flags(self):
        self.assertEqual(S.main(["query", self.kb, "refund window", "--team", "Data"]), 0)


if __name__ == "__main__":
    unittest.main()
