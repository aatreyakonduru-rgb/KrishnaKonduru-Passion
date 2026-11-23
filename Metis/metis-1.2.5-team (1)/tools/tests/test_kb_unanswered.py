import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
for _p in (TOOLS, os.path.join(TOOLS, "ui")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import answers  # noqa: E402
import feedback  # noqa: E402
import kb_unanswered as U  # noqa: E402
import questions  # noqa: E402
import telemetry  # noqa: E402


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


class UnansweredTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.kb = os.path.join(self.tmp, "KB")
        self.prof = {"owners": {"kb_owner": "Ana Lead"}}
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump(self.prof))
        write(os.path.join(self.kb, "_EVIDENCE", "files", "r.txt"), "pets have owners\n")
        write(os.path.join(self.kb, "db", "PETS.md"), '# PETS\n\nThe pets table has a foreign key to owners. [E: file:r.txt "pets have owners"]\n')
        write(os.path.join(self.kb, "_QUESTIONS", "VALIDATE_KB.yaml"), yaml.safe_dump({"questions": []}))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def put_ask(self, aid, question, band, by="Pat Lee", **extra):
        r = {"id": aid, "question": question, "by": by, "on": "2026-11-01T10:00:00", "status": "answered", "follows": None,
             "confidence": {"score": 0, "band": band, "reasons": []}, "checked": {"lines": 0 if band == "None" else 1, "problems": []}}
        r.update(extra)
        write(os.path.join(self.kb, ".metis", "asks", aid + ".yaml"), yaml.safe_dump(r))

    def test_empty_kb_says_so_and_telemetry_has_no_question_text(self):
        rep = U.report(self.kb)
        self.assertEqual(rep["items"], [])
        self.assertTrue(rep["notes"])
        self.assertFalse(rep["telemetry"]["has_question_text"])
        self.assertIn("never the question", rep["telemetry"]["note"])

    def test_low_and_none_asks_listed_high_and_medium_not(self):
        self.put_ask("A-0001", "who owns the zebra table", "None")
        self.put_ask("A-0002", "how are claims paid quickly today", "Low")
        self.put_ask("A-0003", "which table has the foreign key", "High")
        self.put_ask("A-0004", "what does the ledger hold", "Medium")
        items = U.report(self.kb)["items"]
        self.assertEqual([i["question"] for i in items], ["who owns the zebra table", "how are claims paid quickly today"])
        self.assertEqual([i["score"] for i in items], [3, 2])

    def test_a_better_second_try_removes_the_first(self):
        self.put_ask("A-0001", "who owns the zebra table", "None")
        self.assertEqual(len(U.report(self.kb)["items"]), 1)
        self.put_ask("A-0002", "who owns the zebra table", "High", follows="A-0001")
        self.assertEqual(U.report(self.kb)["items"], [])

    def test_a_worse_second_try_counts_once(self):
        self.put_ask("A-0001", "who owns the zebra table", "None")
        self.put_ask("A-0002", "who owns the zebra table", "Low", follows="A-0001")
        items = U.report(self.kb)["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["refs"], ["A-0002"])

    def test_waiting_asks_are_not_counted(self):
        self.put_ask("A-0001", "who owns the zebra table", "None", status="waiting", confidence=None)
        self.assertEqual(U.report(self.kb)["items"], [])

    def test_same_question_from_two_people_merges_and_ranks_higher(self):
        self.put_ask("A-0001", "who owns the zebra table", "None", by="Pat Lee")
        self.put_ask("A-0002", "Who owns the zebra table?", "None", by="Sam Roe")
        self.put_ask("A-0003", "what is the yak ledger", "None", by="Pat Lee")
        items = U.report(self.kb)["items"]
        self.assertEqual(items[0]["question"].lower().rstrip("?"), "who owns the zebra table")
        self.assertEqual(items[0]["score"], 3 + 3 + 1)
        self.assertEqual(items[0]["askers"], ["Pat Lee", "Sam Roe"])
        self.assertIn("2 people", items[0]["why"])
        self.assertEqual(items[1]["score"], 3)

    def test_dislikes_and_declined(self):
        a = answers.ask(self.kb, "Which table has the foreign key to owners?", "Pat Lee", mode="local")
        item, _ = answers.rate(self.kb, a["id"], "Pat Lee", "down", why="wrong table", redirect="look at the ETL")
        fb_items = [i for i in U.report(self.kb)["items"] if "dislike" in i["kinds"]]
        self.assertEqual(len(fb_items), 1)
        feedback.decline(self.kb, item["id"], "Ana Lead", "the answer was fine")
        self.assertEqual([i for i in U.report(self.kb)["items"] if "dislike" in i["kinds"]], [])

    def test_open_questions_raised_by_users_not_by_builds(self):
        questions.cmd_raise(self.kb, "What is the retention period for visit records?", "business", "Pat Lee", "P1")
        reg = questions.load(questions.reg_path(self.kb))
        reg["questions"].append({"id": "Q-0900", "question": "Build raised this one", "type": "data", "priority": "P1", "answer_role": "data lead",
                                 "status": "open", "context": [], "possible_answers": [], "raised_by_build": "build 7"})
        questions.save(self.kb, reg)
        items = U.report(self.kb)["items"]
        self.assertEqual([i["question"] for i in items], ["What is the retention period for visit records?"])
        self.assertEqual(items[0]["score"], 3)
        self.assertEqual(items[0]["askers"], ["Pat Lee"])

    def test_answered_question_leaves_the_report(self):
        questions.cmd_raise(self.kb, "What is the retention period for visit records?", "business", "Pat Lee", "P2")
        reg = questions.load(questions.reg_path(self.kb))
        reg["questions"][0].update(status="closed", answer="7 years", answered_by="Ana Lead")
        questions.save(self.kb, reg)
        self.assertEqual(U.report(self.kb)["items"], [])

    def test_stores_no_question_text_of_its_own(self):
        self.put_ask("A-0001", "who owns the zebra table", "None")
        before = sorted(os.listdir(os.path.join(self.kb, ".metis")))
        U.report(self.kb)
        self.assertEqual(sorted(os.listdir(os.path.join(self.kb, ".metis"))), before)

    def test_telemetry_counts_are_reported(self):
        telemetry.record(self.kb, "answer", ["db/PETS.md"], by="Pat Lee")
        t = U.report(self.kb)["telemetry"]
        self.assertEqual((t["events"], t["answers"]), (1, 1))


class CounterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.kb = os.path.join(self.tmp, "KB")
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump({"owners": {"kb_owner": "Ana Lead"}}))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def opt_in(self):
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"),
              yaml.safe_dump({"owners": {"kb_owner": "Ana Lead"}, "search": {"count_misses": True}}))

    def test_off_by_default_writes_nothing(self):
        self.assertIsNone(U.record_miss(self.kb, "zebra ledger"))
        self.assertFalse(os.path.exists(os.path.join(self.kb, U.COUNTER)))
        self.assertFalse(U.counter_status(self.kb)["enabled"])

    def test_opt_in_counts_hash_only(self):
        self.opt_in()
        self.assertEqual(U.record_miss(self.kb, "zebra ledger"), 1)
        self.assertEqual(U.record_miss(self.kb, "Ledger, ZEBRA"), 2)  # same words, any order or case
        self.assertEqual(U.record_miss(self.kb, "yak"), 1)
        with open(os.path.join(self.kb, U.COUNTER), encoding="utf-8") as fh:
            raw = fh.read()
        self.assertNotIn("zebra", raw)
        self.assertNotIn("ledger", raw)
        self.assertNotIn("yak", raw)
        st = U.counter_status(self.kb)
        self.assertEqual((st["enabled"], st["distinct"], st["total"]), (True, 2, 3))
        self.assertEqual(st["top"][0]["count"], 2)
        self.assertTrue(os.path.isfile(os.path.join(self.kb, ".metis", "usage", ".gitignore")))

    def test_salt_is_per_kb(self):
        self.opt_in()
        other = os.path.join(self.tmp, "KB2")
        write(os.path.join(other, ".metis", "kb-profile.yaml"), yaml.safe_dump({"search": {"count_misses": True}}))
        U.record_miss(self.kb, "zebra")
        U.record_miss(other, "zebra")
        self.assertNotEqual(list(U.load_counter(self.kb)), list(U.load_counter(other)))

    def test_empty_query_not_counted(self):
        self.opt_in()
        self.assertIsNone(U.record_miss(self.kb, "  "))

    def test_cli(self):
        self.opt_in()
        for argv in (["miss", self.kb, "zebra"], ["misses", self.kb], ["report", self.kb], ["report", self.kb, "--json"]):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(U.main(argv), 0)
        self.assertEqual(json.loads(buf.getvalue())["total"], 0)


if __name__ == "__main__":
    unittest.main()
