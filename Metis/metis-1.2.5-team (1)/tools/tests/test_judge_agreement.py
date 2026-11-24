"""judge_agreement: a reproducible sample, controls that are wrong by construction, and honest scoring of a person's labels."""
import os
import shutil
import sys
import tempfile
import unittest

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import judge_agreement as ja  # noqa: E402
import llm_judge  # noqa: E402


def write(p, text):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


COLS = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel"]
SQL = "".join("CREATE TABLE %s_orders (%s_id INT PRIMARY KEY, %s_status VARCHAR(20));\n" % (c, c, c) for c in COLS)
NOUNS = ["veterinarians", "owners", "animals", "visits", "clinics", "invoices", "vaccines", "drugs"]
SQL2 = "".join("CREATE TABLE %s (id INT);\n" % n for n in NOUNS)


class Agreement(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = tempfile.mkdtemp()
        cls.kb = os.path.join(cls.d, "kb")
        write(os.path.join(cls.d, "repo", "schema.sql"), SQL)
        write(os.path.join(cls.d, "repo", "plain.sql"), SQL2)
        write(os.path.join(cls.kb, ".metis", "kb-profile.yaml"),
              yaml.safe_dump({"sources": {"workspace_root": cls.d, "repos": {"repo": "repo"}}}))
        for k in range(4):
            lines = ["# Page %d\n" % k]
            for j, c in enumerate(COLS):
                lines.append('- The %s_orders table has a %s_status column of type VARCHAR. [E: repo/schema.sql:%d-%d "%s_status VARCHAR(20)"]\n'
                             % (c, c, j + 1, j + 1, c))
            write(os.path.join(cls.kb, "db", "P%d.md" % k), "\n".join(lines))
        cls.kb2 = os.path.join(cls.d, "kb2")
        write(os.path.join(cls.kb2, ".metis", "kb-profile.yaml"),
              yaml.safe_dump({"sources": {"workspace_root": cls.d, "repos": {"repo": "repo"}}}))
        for k in range(4):
            body = ["# Page %d\n" % k] + ["- Records about %s are kept in one place. [E: repo/plain.sql:%d-%d \"%s\"]\n" % (n, j + 1, j + 1, n)
                                          for j, n in enumerate(NOUNS)]
            write(os.path.join(cls.kb2, "db", "Q%d.md" % k), "\n".join(body))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.d, ignore_errors=True)

    def test_same_seed_same_sample_and_pages_are_spread(self):
        a = ja.draw(self.kb, n=8, seed="s1", request_judge=False)
        first = [i["where"] for i in ja.load(self.kb)["items"]]
        ja.draw(self.kb, n=8, seed="s1", request_judge=False)
        self.assertEqual(first, [i["where"] for i in ja.load(self.kb)["items"]])
        self.assertEqual(a["sample"], 8)
        self.assertEqual(len({w.split(":")[0] for w in first}), 4)   # 8 lines over 4 pages: every page is in
        ja.draw(self.kb, n=8, seed="other", request_judge=False)
        self.assertNotEqual(first, [i["where"] for i in ja.load(self.kb)["items"]])

    def test_templated_lines_defeat_the_screen_and_the_controls_show_it(self):
        ja.draw(self.kb, n=6, seed="t", controls=3, request_judge=False)
        rep = ja.score(self.kb)
        c = rep["controls"]
        self.assertGreater(c["lexical_screened"], 0)
        self.assertLess(c["lexical_caught"], c["lexical_screened"])      # a swapped citation on a near-identical line passes

    def test_controls_are_wrong_by_construction_and_the_screen_catches_them(self):
        r = ja.draw(self.kb2, n=6, seed="c", controls=3, request_judge=False)
        self.assertEqual(r["controls"], 3)
        items = ja.load(self.kb2)["items"]
        ctrl = [i for i in items if i["control"]]
        self.assertTrue(all(i["human"] == "unsupported" for i in ctrl))
        self.assertTrue(all(i["human"] is None for i in items if not i["control"]))
        self.assertTrue(all(i["lexical_share"] < 0.2 for i in ctrl), [i["lexical_share"] for i in ctrl])
        rep = ja.score(self.kb2)
        self.assertEqual(rep["controls"]["lexical_caught"], rep["controls"]["lexical_screened"])
        self.assertEqual(rep["labelled"], 0)       # a control is never counted in the sample

    def test_draw_writes_judge_requests_and_score_reads_the_verdicts(self):
        ja.draw(self.kb, n=3, seed="j", request_judge=True)
        data = ja.load(self.kb)
        ids = [i["id"] for i in data["items"]]
        for rid in ids:
            self.assertTrue(os.path.isfile(llm_judge.judge_dir(self.kb, "requests", rid + ".json")))
        vp = llm_judge.judge_dir(self.kb, "verdicts", ids[0] + ".json")
        write(vp, '{"id": "%s", "verdict": "supported", "reason": "it says so", "judged_by": "t"}' % ids[0])
        ja.score(self.kb)
        self.assertEqual([i["judge"] for i in ja.load(self.kb)["items"]], [None, None, None])   # score does not rewrite the sheet
        self.assertEqual(ja.refresh_judge(self.kb, data["items"]), None)
        self.assertEqual(data["items"][0]["judge"], "supported")

    def label(self, wrong_every, n=40):
        ja.draw(self.kb, n=n, seed="L", request_judge=False)
        data = ja.load(self.kb)
        for k, it in enumerate(data["items"]):
            it["human"] = "unsupported" if wrong_every and k % wrong_every == 0 else "supported"
            it["judge"] = it["human"] if k % 7 else "supported"      # the judge misses some wrong lines
        ja.save(self.kb, data)
        return data

    def test_too_few_labels_gives_no_number(self):
        ja.draw(self.kb, n=10, seed="few", request_judge=False)
        data = ja.load(self.kb)
        for it in data["items"]:
            it["human"] = "supported"
        ja.save(self.kb, data)
        rep = ja.score(self.kb)
        self.assertFalse(rep["enough"])
        text = ja.report(rep)
        self.assertIn("TOO SMALL", text)
        self.assertNotIn("agrees with the person", text)

    def test_scores_agreement_catches_and_false_alarms(self):
        self.label(wrong_every=4, n=32)
        rep = ja.score(self.kb)
        self.assertTrue(rep["enough"] and rep["wrong_enough"])
        self.assertEqual(rep["labelled"], 32)
        j = rep["judge"]
        self.assertEqual(j["agree"] + (j["missed"] + j["false_alarms"]), j["n"])
        self.assertGreater(j["missed"], 0)                       # the judge was set up to miss some
        self.assertEqual(j["false_alarms"], 0)
        self.assertLessEqual(j["interval"][0], j["agreement"])
        self.assertGreaterEqual(j["interval"][1], j["agreement"])
        self.assertIn("agrees with the person", ja.report(rep))

    def test_unsure_is_not_counted(self):
        ja.draw(self.kb, n=5, seed="u", request_judge=False)
        data = ja.load(self.kb)
        for it in data["items"]:
            it["human"] = "unsure"
        ja.save(self.kb, data)
        rep = ja.score(self.kb)
        self.assertEqual((rep["labelled"], rep["unsure"]), (0, 5))

    def test_metrics_and_interval(self):
        m = ja.metrics([(True, True), (True, False), (False, True), (False, False), (False, False)])
        self.assertEqual((m["caught"], m["missed"], m["false_alarms"], m["good_passed"]), (1, 1, 1, 2))
        self.assertEqual(m["agreement"], 0.6)
        lo, hi = ja.wilson(3, 5)
        self.assertTrue(0.2 < lo < 0.6 < hi < 0.95)
        self.assertIsNone(ja.wilson(0, 0))

    def test_cli_draw_then_score(self):
        self.assertEqual(ja.main(["draw", self.kb, "--n", "4", "--no-judge"]), 0)
        self.assertEqual(ja.main(["score", self.kb]), 0)
        self.assertEqual(ja.main(["score", os.path.join(self.d, "nothing-here")]), 2)


if __name__ == "__main__":
    unittest.main()
