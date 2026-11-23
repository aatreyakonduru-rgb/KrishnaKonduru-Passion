import os
import sys
import tempfile
import unittest

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import verify_kb  # noqa: E402


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


class Ask(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.kb = os.path.join(self.tmp, "repo", "kb")
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump({"product": {"name": "S"}}))
        write(os.path.join(self.kb, "app", "ORDERS.md"),
              "# Orders [E: kb:app]\n\n- The Orders screen reads   SALES.MART.ORDERS.\n- Totals are daily.\n")
        self.ans = os.path.join(self.tmp, "answer.md")

    def check(self, text):
        write(self.ans, text)
        return [p["problem"] for p in verify_kb.Checker(self.kb).check_answer(self.ans)["problems"]]

    def test_quote_found(self):
        self.assertEqual(self.check('# Answer\n\n- Orders screen uses it [E: kb:app/ORDERS.md "reads SALES.MART.ORDERS"]\n'), [])

    def test_quote_with_lines(self):
        self.assertEqual(self.check('- x [E: kb:app/ORDERS.md:4 "Totals are daily"]\n'), [])
        self.assertIn("quoted text not found", self.check('- x [E: kb:app/ORDERS.md:3 "Totals are daily"]\n')[0])
        self.assertIn("outside KB file", self.check('- x [E: kb:app/ORDERS.md:40 "x"]\n')[0])

    def test_quote_missing(self):
        self.assertIn("quoted text not found", self.check('- x [E: kb:app/ORDERS.md "reads SALES.MART.CLAIMS"]\n')[0])
        self.assertIn("KB file missing", self.check('- x [E: kb:app/NOPE.md "x"]\n')[0])

    def test_untagged_and_not_in_kb(self):
        self.assertIn("no source tag", self.check("# Answer\n\n- It runs at 2am\n")[0])
        self.assertEqual(self.check("# Answer\n\n## Not in the KB\n\n- What time does the job run?\n"), [])

    def test_cli(self):
        write(self.ans, "- untagged\n")
        self.assertEqual(verify_kb.main([self.kb, "--answer", self.ans]), 1)
        write(self.ans, '- ok [E: kb:app/ORDERS.md "Totals are daily"]\n')
        self.assertEqual(verify_kb.main([self.kb, "--answer", self.ans]), 0)


if __name__ == "__main__":
    unittest.main()
