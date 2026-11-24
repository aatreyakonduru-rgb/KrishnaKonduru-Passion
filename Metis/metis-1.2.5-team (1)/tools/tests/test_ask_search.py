"""Ask uses the KB search to rank pages: a one-word line on a top page qualifies, a broken search never stops the answer."""
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)
sys.path.insert(0, os.path.join(TOOLS, "ui"))
import answers  # noqa: E402


def write(p, text):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


SQL = "CREATE TABLE invoices (\n  invoice_id INT,\n  due_date DATE,\n  amount INT\n);\n"
Q = "when is the invoice payment settled by the customer"   # 4 content words; the best page shares only one of them


class AskSearch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = tempfile.mkdtemp()
        cls.kb = os.path.join(cls.d, "kb")
        write(os.path.join(cls.d, "repo", "schema.sql"), SQL)
        write(os.path.join(cls.kb, ".metis", "kb-profile.yaml"),
              yaml.safe_dump({"sources": {"workspace_root": cls.d, "repos": {"repo": "repo"}}}))
        write(os.path.join(cls.kb, "db", "INVOICES.md"),
              '# Invoices\n\n- The invoices table has a due_date column of type DATE. [E: repo/schema.sql:3-3 "due_date DATE"]\n'
              '- The invoices table has an amount column. [E: repo/schema.sql:4-4 "amount INT"]\n')
        write(os.path.join(cls.kb, "CROSS-LAYER", "LINK_GRAPH.yaml"), "nodes: []\nedges: []\n")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.d, ignore_errors=True)

    def lines(self, **kw):
        text, n, _ = answers.compose(self.kb, Q, **kw)
        return [ln for ln in text.splitlines() if ln.startswith("- ") and "[E:" in ln]

    def test_top_page_lets_a_one_word_line_in(self):
        info = {}
        got = self.lines(info=info)
        self.assertTrue(got, "the search should have let a line from the best page in")
        self.assertEqual(info["search"]["pages"][0], "db/INVOICES.md")

    def test_search_off_in_profile_keeps_the_old_matcher(self):
        prof = os.path.join(self.kb, ".metis", "kb-profile.yaml")
        old = open(prof, encoding="utf-8").read()
        try:
            write(prof, yaml.safe_dump({"sources": {"workspace_root": self.d, "repos": {"repo": "repo"}}, "ask": {"search": False}}))
            info = {}
            self.assertEqual(self.lines(info=info), [])
            self.assertNotIn("search", info)
        finally:
            write(prof, old)

    def test_broken_search_falls_back_and_says_so(self):
        info = {}
        with mock.patch("kb_search.search", side_effect=RuntimeError("index is broken")):
            self.assertEqual(self.lines(info=info), [])     # same as the old matcher
        self.assertIn("index is broken", info["search_note"])

    def test_admitted_lines_still_pass_the_source_check(self):
        text, _, _ = answers.compose(self.kb, Q)
        out = os.path.join(self.d, "answer.md")
        write(out, text)
        rep = answers.check(self.kb, out)
        self.assertEqual(rep['problems'], [])

class SummaryDrill(unittest.TestCase):
    """A summary page that matches sends the search down to the full pages it covers."""

    @classmethod
    def setUpClass(cls):
        cls.d = tempfile.mkdtemp()
        cls.kb = os.path.join(cls.d, "kb")
        write(os.path.join(cls.d, "repo", "schema.sql"), SQL)
        write(os.path.join(cls.kb, ".metis", "kb-profile.yaml"),
              yaml.safe_dump({"sources": {"workspace_root": cls.d, "repos": {"repo": "repo"}}}))
        write(os.path.join(cls.kb, "db", "INVOICES.md"),
              '# Tables\n\n- The invoices table has a due_date column of type DATE. [E: repo/schema.sql:3-3 "due_date DATE"]\n')
        write(os.path.join(cls.kb, "summaries", "db.md"),
              '---\ntype: area-summary\narea: db\nsummarises: [db/INVOICES.md]\n---\n# Billing and payment settlement overview\n\n'
              '- Billing, payment settlement and customer invoices live in one table. [E: repo/schema.sql:1-1 "CREATE TABLE invoices"]\n')
        write(os.path.join(cls.kb, "CROSS-LAYER", "LINK_GRAPH.yaml"), "nodes: []\nedges: []\n")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.d, ignore_errors=True)

    def test_drill_pages_reads_only_area_summaries(self):
        import kb_summaries
        text = open(os.path.join(self.kb, "summaries", "db.md"), encoding="utf-8").read()
        self.assertEqual(kb_summaries.drill_pages(text), ["db/INVOICES.md"])
        self.assertEqual(kb_summaries.drill_pages("---\ntype: other\nsummarises: [x.md]\n---\n# x\n"), [])
        self.assertEqual(kb_summaries.drill_pages("# no front matter"), [])

    def test_pack_adds_the_pages_under_a_matching_summary(self):
        import context_pack
        r = context_pack.build(self.kb, task="billing payment settlement overview", budget=4000, signals=False, stale_marks=False)
        self.assertIn("summaries/db.md", r["files"])
        self.assertIn("db/INVOICES.md", r["files"])
        self.assertIn("under summary summaries/db.md", r["text"])

    def test_ask_ranks_the_covered_page_with_its_summary(self):
        info = {}
        answers.page_ranks(self.kb, "billing payment settlement overview", info=info)
        self.assertIn("db/INVOICES.md", info["search"]["pages"])


if __name__ == "__main__":
    unittest.main()
