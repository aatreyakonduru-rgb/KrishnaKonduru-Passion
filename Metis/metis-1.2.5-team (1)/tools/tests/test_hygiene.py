import os
import shutil
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import questions  # noqa: E402
import tag_audit  # noqa: E402
import verify_kb  # noqa: E402


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


class Hygiene(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.kb = os.path.join(self.d, "kb")
        self.profile = {"owners": {"kb_owner": "Ana Lead", "roles": {"product owner": "Pia Owner", "dev lead": "Raj Dev"}}}
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump(self.profile))
        write(os.path.join(self.kb, "_EVIDENCE", "files", "r.txt"), "Claims are paid within 30 days.\nAppeals take 60 days.\n")
        write(os.path.join(self.kb, "context", "a.md"), "# A\n\n- Paid in 30 days [E: file:r.txt]\n- Appeals [E: file:r.txt \"Appeals take 60 days\"]\n"
              "- Again [E: kb:context/a.md]\n")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def check(self, strict=False, text=None):
        if strict:
            write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump(dict(self.profile, verify={"strict_tags": True})))
        return [p["problem"] for p in verify_kb.Checker(self.kb).run()["problems"]]

    def test_loose_by_default_and_quote_checked_when_given(self):
        self.assertEqual(self.check(), [])
        write(os.path.join(self.kb, "context", "b.md"), '- Wrong [E: file:r.txt "Appeals take 90 days"]\n')
        self.assertEqual(self.check(), ["quoted text not found in _EVIDENCE/files/r.txt"])

    def test_strict_mode_wants_a_quote_on_file_and_kb_tags(self):
        probs = self.check(strict=True)
        self.assertEqual(len(probs), 2)  # the bare file tag and the bare kb tag; the quoted one passes
        self.assertTrue(all("strict mode" in p for p in probs))

    def test_answers_are_always_strict(self):
        ans = os.path.join(self.d, "ans.md")
        write(ans, "- Paid [E: kb:context/a.md]\n")
        self.assertEqual(len(verify_kb.Checker(self.kb).check_answer(ans)["problems"]), 1)
        write(ans, '- Paid [E: kb:context/a.md "Paid in 30 days"]\n')
        self.assertEqual(verify_kb.Checker(self.kb).check_answer(ans)["problems"], [])

    def test_raise_a_question_in_one_step_and_reuse_it(self):
        qid, _ = questions.cmd_raise(self.kb, "What is the appeal window for member claims?", "business", "Pat Lee",
                                     blocks=["context/a.md"], context=['[E: file:r.txt "Appeals take 60 days"]'])
        again, _ = questions.cmd_raise(self.kb, "What is the appeal window for member claims?", "business", "Pat Lee", blocks=["context/a.md"])
        self.assertEqual((qid, again), ("Q-0001", "Q-0001"))
        reg = questions.load(questions.reg_path(self.kb))["questions"]
        self.assertEqual((len(reg), reg[0]["answer_role"], reg[0]["status"]), (1, "product owner", "open"))
        for bad in (("", "business", "Pat"), ("q?", "nonsense", "Pat"), ("q?", "business", "")):
            with self.assertRaises(ValueError):
                questions.cmd_raise(self.kb, bad[0], bad[1], bad[2])

    def test_sheet_lists_open_questions_for_a_role(self):
        questions.cmd_raise(self.kb, "Business question?", "business", "Pat Lee", priority="P1")
        questions.cmd_raise(self.kb, "App question?", "application", "Pat Lee")
        text, n = questions.cmd_sheet(self.kb, "product owner")
        self.assertEqual(n, 1)
        self.assertIn("Business question?", text)
        self.assertNotIn("App question?", text)
        self.assertIn("(Pia Owner)", text)
        self.assertEqual(questions.cmd_sheet(self.kb)[1], 2)

    def test_audit_sample_is_repeatable_and_shows_the_source(self):
        rows, total = tag_audit.sample(self.kb, 2, seed=7)
        self.assertEqual((len(rows), total), (2, 3))
        self.assertEqual(rows, tag_audit.sample(self.kb, 2, seed=7)[0])
        text = tag_audit.render(tag_audit.sample(self.kb, 10)[0], total)
        self.assertIn("Claims are paid within 30 days.", text)
        self.assertIn("Verdict:", text)


if __name__ == "__main__":
    unittest.main()
