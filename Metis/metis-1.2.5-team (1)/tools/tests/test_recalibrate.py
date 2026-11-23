import os
import shutil
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import recalibrate  # noqa: E402
import answers  # noqa: E402


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


class RecalibrateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.kb = os.path.join(self.tmp, "kb")
        os.makedirs(self.kb, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def add_ask(self, aid, band, rating):
        ask_data = {
            "id": aid,
            "question": "Sample question %s?" % aid,
            "answer_file": aid + ".md",
            "rating": rating,
            "confidence": {"score": 90 if band == "High" else 70 if band == "Medium" else 30 if band == "Low" else 0, "band": band},
        }
        answers.save(self.kb, ask_data)
        write(answers.answer_path(self.kb, aid), "# Answer\n\n- Fact line\n")

    def test_not_enough_ratings_default(self):
        for i in range(5):
            self.add_ask("A-%04d" % i, "High", "up")
        ok, res = recalibrate.propose(self.kb, min_volume=30)
        self.assertFalse(ok)
        self.assertEqual(res["status"], "not_enough_ratings")
        self.assertIn("not enough ratings", res["message"])
        self.assertFalse(os.path.isfile(recalibrate.proposal_path(self.kb)))

    def test_propose_generates_proposal_with_volume(self):
        # Add 30 ratings per band for High, Medium, Low, None
        aid = 0
        for band in ("High", "Medium", "Low", "None"):
            for _ in range(30):
                aid += 1
                self.add_ask("A-%04d" % aid, band, "up" if band in ("High", "Medium") else "down")

        ok, prop = recalibrate.propose(self.kb, min_volume=30)
        self.assertTrue(ok)
        self.assertTrue(os.path.isfile(recalibrate.proposal_path(self.kb)))
        self.assertEqual(prop["status"], "proposed_for_review")
        self.assertEqual(prop["min_volume_required"], 30)
        self.assertIn("band_statistics", prop)
        self.assertIn("proposed_weights", prop)

    def test_force_flag_generates_proposal_even_when_small(self):
        self.add_ask("A-0001", "High", "up")
        ok, prop = recalibrate.propose(self.kb, min_volume=30, force=True)
        self.assertTrue(ok)
        self.assertTrue(os.path.isfile(recalibrate.proposal_path(self.kb)))

    def test_cli(self):
        self.add_ask("A-0001", "High", "up")
        # CLI run without volume -> exit 1
        self.assertEqual(recalibrate.main(["run", self.kb, "--min-volume", "30"]), 1)
        # CLI run with force -> exit 0
        self.assertEqual(recalibrate.main(["run", self.kb, "--force"]), 0)
        # CLI show-proposal -> exit 0
        self.assertEqual(recalibrate.main(["show-proposal", self.kb]), 0)


if __name__ == "__main__":
    unittest.main()
