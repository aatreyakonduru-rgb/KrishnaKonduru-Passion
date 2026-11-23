import os
import shutil
import sys
import tempfile
import unittest

import yaml

TOOLS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
UI_DIR = os.path.join(TOOLS_DIR, "ui")
for _p in (TOOLS_DIR, UI_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import answers  # noqa: E402
import calibration  # noqa: E402
import screens_usage  # noqa: E402
import telemetry  # noqa: E402
import ui_common as C  # noqa: E402


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def fake_ask(kb, n, band, rating=None, on="2026-03-02T10:00:00"):
    """An ask record as answers.py keeps it, without running an answer."""
    answers.save(kb, {"id": "A-%04d" % n, "question": "q%d" % n, "by": "Pat Lee", "on": on, "mode": "local", "status": "answered",
                      "answer_file": "A-%04d.md" % n, "files": [], "rating": rating, "feedback": None,
                      "confidence": {"score": 50, "band": band, "reasons": ["x"]}})


class Base(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.kb = os.path.join(self.d, "kb")
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump({"owners": {"kb_owner": "Ana Lead"}}))
        write(os.path.join(self.kb, "_EVIDENCE", "files", "r.txt"), "pets have owners\n")
        write(os.path.join(self.kb, "db", "PETS.md"), '# PETS\n\nThe pets table has a foreign key to owners. [E: file:r.txt "pets have owners"]\n')
        write(os.path.join(self.kb, "db", "UNUSED.md"), '# UNUSED\n\nNobody asks about this. [E: file:r.txt "pets have owners"]\n')
        write(os.path.join(self.kb, "_QUESTIONS", "VALIDATE_KB.yaml"), yaml.safe_dump({"questions": []}))
        self.ctx = C.Ctx(self.kb, "tok", "Pat Lee")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)


class TestWilson(unittest.TestCase):
    def test_no_trials_has_no_interval(self):
        self.assertIsNone(calibration.wilson(0, 0))

    def test_known_values(self):
        lo, hi = calibration.wilson(5, 10)
        self.assertAlmostEqual(lo, 0.2366, places=3)
        self.assertAlmostEqual(hi, 0.7634, places=3)
        lo, hi = calibration.wilson(10, 10)
        self.assertAlmostEqual(lo, 0.7225, places=3)
        self.assertEqual(hi, 1.0)
        lo, hi = calibration.wilson(0, 10)
        self.assertEqual(lo, 0.0)
        self.assertAlmostEqual(hi, 0.2775, places=3)

    def test_small_sample_is_wide_and_large_is_narrow(self):
        small = calibration.wilson(3, 3)
        large = calibration.wilson(300, 300)
        self.assertGreater(small[1] - small[0], 0.5)  # 3 of 3 liked still says very little
        self.assertLess(large[1] - large[0], 0.02)


def rows(high, low):
    """bands() rows from (liked, disliked) for High and Low."""
    out = []
    for b, (up, down) in (("High", high), ("Medium", (0, 0)), ("Low", low), ("None", (0, 0))):
        n = up + down
        out.append({"band": b, "answers": n, "rated": n, "liked": up, "disliked": down, "ci": calibration.wilson(up, n)})
        out[-1]["liked_share"] = up / n if n else None
    return out


class TestVerdict(unittest.TestCase):
    def test_small_samples_say_not_enough_ratings(self):
        v = calibration.verdict(rows((9, 0), (0, 9)))  # perfect split, but 9 each is below 10
        self.assertTrue(v.startswith("Not enough ratings yet"))
        self.assertIn("Rated answers: High 9, Low 9", v)
        self.assertNotIn("95% range", v)  # no result is offered

    def test_one_band_short_is_still_not_enough(self):
        self.assertTrue(calibration.verdict(rows((30, 0), (1, 2))).startswith("Not enough ratings yet"))
        self.assertTrue(calibration.verdict(rows((0, 0), (0, 0))).startswith("Not enough ratings yet"))

    def test_clear_difference(self):
        v = calibration.verdict(rows((20, 0), (2, 18)))
        self.assertTrue(v.startswith("High is better than Low."))
        self.assertIn("do not overlap", v)

    def test_overlap_makes_no_claim(self):
        v = calibration.verdict(rows((8, 2), (6, 4)))
        self.assertTrue(v.startswith("No clear difference"))
        self.assertNotIn("is better than Low", v)

    def test_low_better_than_high_is_reported(self):
        v = calibration.verdict(rows((2, 18), (20, 0)))
        self.assertTrue(v.startswith("Low did better than High"))


class TestBands(Base):
    def test_counts_per_band(self):
        for i, (band, rating) in enumerate([("High", "up"), ("High", "up"), ("High", "down"), ("High", None), ("Low", "down"),
                                            ("Low", None), ("None", None), ("Medium", "up")], 1):
            fake_ask(self.kb, i, band, rating)
        answers.save(self.kb, {"id": "A-0009", "question": "waiting", "by": "Pat Lee", "on": "2026-03-02T10:00:00", "status": "waiting",
                               "answer_file": None})
        answers.save(self.kb, {"id": "A-0010", "question": "no band", "by": "Pat Lee", "on": "2026-03-02T10:00:00", "status": "answered",
                               "answer_file": "A-0010.md"})
        rep = calibration.bands(self.kb)
        by = {r["band"]: r for r in rep["rows"]}
        self.assertEqual((by["High"]["answers"], by["High"]["rated"], by["High"]["liked"], by["High"]["disliked"]), (4, 3, 2, 1))
        self.assertAlmostEqual(by["High"]["liked_share"], 2 / 3)
        self.assertAlmostEqual(by["High"]["disliked_share"], 1 / 3)
        self.assertEqual((by["Low"]["answers"], by["Low"]["rated"], by["Low"]["liked"]), (2, 1, 0))
        self.assertEqual((by["None"]["answers"], by["None"]["rated"]), (1, 0))
        self.assertIsNone(by["None"]["liked_share"])
        self.assertIsNone(by["None"]["ci"])
        self.assertEqual((rep["waiting"], rep["unscored"], rep["golden"]), (1, 1, 0))
        self.assertTrue(rep["verdict"].startswith("Not enough ratings yet"))

    def test_empty_kb(self):
        rep = calibration.bands(self.kb)
        self.assertEqual([r["answers"] for r in rep["rows"]], [0, 0, 0, 0])
        self.assertEqual(calibration.per_week(self.kb), [])

    def test_per_week_includes_empty_weeks(self):
        fake_ask(self.kb, 1, "High", on="2026-03-02T10:00:00")  # a Monday
        fake_ask(self.kb, 2, "High", on="2026-03-04T10:00:00")
        fake_ask(self.kb, 3, "Low", on="2026-03-18T10:00:00")  # two weeks on
        self.assertEqual(calibration.per_week(self.kb), [("2026-03-02", 2), ("2026-03-09", 0), ("2026-03-16", 1)])

    def test_real_asks_and_ratings(self):
        ids = [answers.ask(self.kb, "Which table does pets reference?", "Pat Lee")["id"] for _ in range(4)]
        answers.rate(self.kb, ids[0], "Pat Lee", "up")
        answers.rate(self.kb, ids[1], "Pat Lee", "down", why="wrong table", correct="owners")
        rep = calibration.bands(self.kb)
        total = sum(r["answers"] for r in rep["rows"])
        self.assertEqual(total, 4)
        self.assertEqual(sum(r["rated"] for r in rep["rows"]), 2)
        self.assertEqual(sum(r["liked"] for r in rep["rows"]), 1)
        self.assertEqual(sum(r["disliked"] for r in rep["rows"]), 1)


class TestScreen(Base):
    def test_empty_screen(self):
        html = screens_usage.usage(self.ctx, {})
        self.assertIn("<h1>Usage</h1>", html)
        self.assertIn("Not enough ratings yet", html)
        self.assertIn("No answers yet.", html)
        self.assertIn("A dislike names an answer, not a page", html)
        self.assertIn("No disliked answer has cited a page yet.", html)
        self.assertIn("no golden result is used here", html)

    def test_screen_with_real_data(self):
        ids = [answers.ask(self.kb, "Which table does pets reference?", "Pat Lee")["id"] for _ in range(3)]
        answers.rate(self.kb, ids[0], "Pat Lee", "down", why="not what I meant", redirect="look at owners")
        answers.rate(self.kb, ids[1], "Pat Lee", "up")
        html = screens_usage.usage(self.ctx, {})
        self.assertIn("db/PETS.md", html)
        self.assertIn("db/UNUSED.md", html)  # never used
        self.assertIn("Look first", html)
        self.assertIn("Answers per week", html)
        self.assertIn("Most disliked cited pages", html)
        self.assertIn("<td>High</td>", html)
        self.assertIn("not enough ratings yet", html)
        self.assertEqual(telemetry.report(self.kb)["answers"], len(answers.all_asks(self.kb)))

    def test_user_text_is_escaped(self):
        bad = "db/<script>alert(1)</script>.md"
        answers.save(self.kb, {"id": "A-0001", "question": "<b>q</b>", "by": "<i>x</i>", "on": "2026-03-02T10:00:00", "status": "answered",
                               "answer_file": "A-0001.md", "files": [bad], "rating": "down",
                               "confidence": {"score": 90, "band": "High", "reasons": []}})
        write(os.path.join(self.kb, "_FEEDBACK", "FEEDBACK.yaml"), yaml.safe_dump({"feedback": [
            {"id": "F-0001", "rating": "down", "status": "open", "cited_files": [bad]}]}))
        telemetry.record(self.kb, "answer", [bad])
        html = screens_usage.usage(self.ctx, {})
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_module_contract(self):
        self.assertEqual(list(screens_usage.SCREENS), ["/usage"])
        self.assertEqual(screens_usage.ACTIONS, {})
        self.assertEqual(screens_usage.NAV, [("/usage", "Usage")])

    def test_cli(self):
        fake_ask(self.kb, 1, "High", "up")
        self.assertEqual(calibration.main([self.kb]), 0)


if __name__ == "__main__":
    unittest.main()
