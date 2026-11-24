import os
import shutil
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import verify_kb  # noqa: E402


def write(p, text):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


SRC = ("CREATE TABLE owners (\n"
       "  owner_id INT PRIMARY KEY,\n"
       "  first_name VARCHAR(30),\n"
       "  telephone VARCHAR(20)\n"
       ");\n")


class Support(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.kb = os.path.join(self.d, "kb")
        write(os.path.join(self.d, "repo", "schema.sql"), SRC)
        self.set(strict=True)

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def set(self, strict=False, support=None):
        v = {"strict_tags": strict}
        if support is not None:
            v["support_min"] = support
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"),
              yaml.safe_dump({"sources": {"workspace_root": self.d, "repos": {"repo": "repo"}}, "verify": v}))

    def problems(self, line, answer=False):
        p = os.path.join(self.kb, "db", "T.md")
        write(p, "# T\n\n" + line + "\n")
        chk = verify_kb.Checker(self.kb)
        rep = chk.check_answer(p) if answer else chk.run()
        return [x["problem"] for x in rep["problems"] if x["file"].endswith("T.md")]

    def test_line_tag_without_quote_fails_in_strict_mode_only(self):
        line = "- The owners table has an owner id. [E: repo/schema.sql:1-2]"
        self.assertTrue(any("needs a quote" in p for p in self.problems(line)))
        self.set(strict=False)
        self.assertEqual(self.problems(line), [])

    def test_line_tag_with_quote_passes(self):
        self.assertEqual(self.problems('- The owners table has an owner id. [E: repo/schema.sql:1-2 "owner_id INT PRIMARY KEY"]'), [])

    def test_claim_unrelated_to_its_quote_is_caught(self):
        self.set(strict=True, support=0.2)
        bad = '- The invoices ledger stores encrypted payment tokens nightly. [E: repo/schema.sql:2-2 "owner_id INT PRIMARY KEY"]'
        got = self.problems(bad)
        self.assertTrue(any("shares" in p for p in got), got)

    def test_claim_about_its_quote_passes(self):
        self.set(strict=True, support=0.2)
        ok = '- Each owner has an owner id as primary key. [E: repo/schema.sql:2-2 "owner_id INT PRIMARY KEY"]'
        self.assertEqual(self.problems(ok), [])

    def test_off_by_default_for_the_kb_but_on_for_answers(self):
        bad = '- The invoices ledger stores encrypted payment tokens nightly. [E: repo/schema.sql:2-2 "owner_id INT PRIMARY KEY"]'
        self.assertEqual(self.problems(bad), [])
        self.assertTrue(any("shares" in p for p in self.problems(bad, answer=True)))

    def test_inferred_line_and_short_lines_are_not_screened(self):
        self.set(strict=True, support=0.5)
        inf = '- Inferred: every owner is reachable by telephone. [E: repo/schema.sql:2-4 "owner_id INT PRIMARY KEY"]'
        self.assertEqual(self.problems(inf), [])
        short = '- Owners. [E: repo/schema.sql:2-2 "owner_id INT PRIMARY KEY"]'
        self.assertEqual(self.problems(short), [])

    def test_tag_with_no_quote_is_not_screened_for_support(self):
        self.set(strict=False, support=0.5)
        self.assertEqual(self.problems("- The invoices ledger stores encrypted payment tokens nightly. [E: repo/schema.sql:2-2]"), [])


if __name__ == "__main__":
    unittest.main()
