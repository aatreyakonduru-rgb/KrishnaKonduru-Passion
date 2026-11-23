import os
import shutil
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import feedback  # noqa: E402
import golden  # noqa: E402
import kb_gate  # noqa: E402
import questions  # noqa: E402
import verify_kb  # noqa: E402

PROFILE = {"owners": {"kb_owner": "Ana Lead", "roles": {"dev lead": "Raj Dev", "data lead": "Dee Data"}}}
ANSWER = ('# Answer\n\n- Claims are paid in 30 days [E: kb:context/rules.md "paid within 30 days"]\n'
          '- Appeals take 60 days [E: kb:context/rules.md "Appeals take 60 days"]\n')


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def rmtree(path):
    def onerror(func, p, _):
        os.chmod(p, 0o700)
        func(p)
    shutil.rmtree(path, onerror=onerror)


class Base(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.kb = os.path.join(self.d, "kb")
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump(PROFILE))
        write(os.path.join(self.kb, "_EVIDENCE", "files", "r.txt"), "x\n")
        write(os.path.join(self.kb, "context", "rules.md"),
              "# Rules\n\n- Claims are paid within 30 days. Appeals take 60 days. [E: file:r.txt]\n")
        self.answer = os.path.join(self.d, "answer.md")
        write(self.answer, ANSWER)
        self.rec = lambda **kw: feedback.record(self.kb, self.answer, kw.pop("question", "How fast are claims paid?"),
                                                kw.pop("by", "Pat Lee"), kw.pop("rating"), **kw)

    def tearDown(self):
        rmtree(self.d)


class Feedback(Base):
    def test_like_is_stored_with_cited_files(self):
        f = self.rec(rating="up")
        self.assertEqual((f["id"], f["status"], f["cited_files"]), ("F-0001", "open", ["context/rules.md"]))
        self.assertTrue(os.path.isfile(os.path.join(self.kb, "_FEEDBACK", "answers", "F-0001.md")))

    def test_dislike_needs_why_and_one_direction(self):
        for kw in ({}, {"why": "wrong"}, {"why": "wrong", "correct": "45 days", "redirect": "look at ETL"},
                   {"correct": "45 days"}):
            with self.assertRaises(feedback.FeedbackError):
                self.rec(rating="down", **kw)
        self.assertEqual(feedback.load(self.kb)["feedback"], [])

    def test_dislike_with_correct_answer_raises_a_question_for_the_lead(self):
        f = self.rec(rating="down", why="the policy changed in 2025", correct="Claims are paid within 45 days")
        self.assertEqual(f["action"], "question")
        reg = questions.load(questions.reg_path(self.kb))["questions"]
        q = [x for x in reg if x["id"] == f["question_id"]][0]
        self.assertEqual((q["status"], q["answer_role"]), ("open", "product owner"))
        self.assertIn("45 days", q["question"])
        self.assertIn("the policy changed in 2025", q["question"])
        self.assertEqual(q["blocks"], ["context/rules.md"])
        self.assertTrue(any('kb:context/rules.md "paid within 30 days"' in c for c in q["context"]))
        self.assertEqual(questions.problems(self.kb, {"questions": reg}), [])
        self.assertEqual(verify_kb.Checker(self.kb).run()["problems"], [])
        # the correction is not in the KB until the question is answered and certified
        with open(os.path.join(self.kb, "context", "rules.md"), encoding="utf-8") as fh:
            self.assertIn("30 days", fh.read())

    def test_second_dislike_of_same_line_reuses_the_question(self):
        a = self.rec(rating="down", why="old", correct="45 days")
        b = self.rec(rating="down", why="old", correct="45 days", by="Pat Lee")
        self.assertEqual(a["question_id"], b["question_id"])

    def test_redirect_is_kept_for_the_asker_until_a_lead_approves_it(self):
        f = self.rec(rating="down", why="this is the app, I meant the batch jobs", redirect="look in the ETL job docs, not the app modules")
        self.assertEqual(f["action"], "ask again with this direction")
        self.assertEqual(feedback.hints(self.kb, "How fast are claims paid?"), [])
        with self.assertRaises(kb_gate.GateError):
            feedback.approve(self.kb, f["id"], "Pat Lee")
        feedback.approve(self.kb, f["id"], "Raj Dev")
        h = feedback.hints(self.kb, "how fast are claims paid by the batch?")
        self.assertEqual(h[0]["direction"], "look in the ETL job docs, not the app modules")
        self.assertEqual(h[0]["approved_by"], "Raj Dev")
        self.assertEqual(feedback.hints(self.kb, "list all database tables for members"), [])

    def test_decline_and_resolve(self):
        f = self.rec(rating="down", why="w", redirect="look in db docs")
        with self.assertRaises(feedback.FeedbackError):
            feedback.resolve(self.kb, f["id"], "Someone Else")
        self.assertEqual(feedback.resolve(self.kb, f["id"], "pat lee")["status"], "resolved")
        with self.assertRaises(feedback.FeedbackError):
            feedback.decline(self.kb, f["id"], "Ana Lead", "")
        self.assertEqual(feedback.decline(self.kb, f["id"], "Ana Lead", "not a general rule")["status"], "declined")

    def test_feedback_folder_is_outside_the_source_check_and_gate(self):
        self.rec(rating="up")
        kb_gate.lock(self.kb, "Ana Lead")
        self.assertEqual(kb_gate.check(self.kb)[0], [])

    def test_cli(self):
        self.assertEqual(feedback.main(["record", self.kb, "--answer", self.answer, "--question", "q?", "--by", "Pat", "--rating", "down", "--why", "w"]), 2)
        self.assertEqual(feedback.main(["record", self.kb, "--answer", self.answer, "--question", "q?", "--by", "Pat", "--rating", "up"]), 0)
        self.assertEqual(feedback.main(["list", self.kb]), 0)


class Golden(Base):
    def test_add_promote_static_and_score(self):
        with self.assertRaises(kb_gate.GateError):
            golden.add(self.kb, "How fast are claims paid?", ["context/rules.md"], ["30 days"], "Pat Lee")
        with self.assertRaises(golden.GoldenError):
            golden.add(self.kb, "q", ["context/nope.md"], [], "Ana Lead")
        g = golden.add(self.kb, "How fast are claims paid?", ["context/rules.md"], ["30 days"], "Ana Lead", "competency")
        self.assertEqual(g["id"], "G-0001")
        with self.assertRaises(golden.GoldenError):
            golden.add(self.kb, "How fast are claims paid?", ["context/rules.md"], [], "Ana Lead")
        like = self.rec(rating="up", question="What does appeals take?")
        with self.assertRaises(golden.GoldenError):
            golden.promote(self.kb, like["id"], "Ana Lead")
        feedback.approve(self.kb, like["id"], "Ana Lead")
        self.assertEqual(golden.promote(self.kb, like["id"], "Ana Lead")["from_feedback"], like["id"])
        self.assertEqual(golden.static(self.kb), [])
        ans = os.path.join(self.d, "ans")
        write(os.path.join(ans, "G-0001.md"), ANSWER)
        write(os.path.join(ans, "G-0002.md"), "# A\n\n- Appeals are quick [E: kb:context/rules.md \"Appeals take 60 days\"]\n")
        rows = {r["id"]: r for r in golden.score(self.kb, ans)}
        self.assertEqual(rows["G-0001"]["result"], "pass")
        self.assertEqual(rows["G-0002"]["result"], "pass")  # cites the file; no include words required
        write(os.path.join(ans, "G-0001.md"), "# A\n\n- Fast [E: kb:context/rules.md \"made up words\"]\n")
        r = golden.score(self.kb, ans)[0]
        self.assertEqual(r["result"], "fail")
        os.remove(os.path.join(self.kb, "context", "rules.md"))
        self.assertEqual(len(golden.static(self.kb)), 2)


if __name__ == "__main__":
    unittest.main()
