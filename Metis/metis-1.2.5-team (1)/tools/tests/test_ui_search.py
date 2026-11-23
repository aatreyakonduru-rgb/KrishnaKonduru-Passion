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
import kb_unanswered  # noqa: E402
import screens_search as S  # noqa: E402
import ui_common as C  # noqa: E402


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


class SearchUiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.kb = os.path.join(self.tmp, "KB")
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump({"owners": {"kb_owner": "Ana Lead"}}))
        write(os.path.join(self.kb, "_EVIDENCE", "files", "r.txt"), "pets have owners\n")
        write(os.path.join(self.kb, "db", "PETS.md"), '# PETS\n\nThe pets table has a foreign key to owners. [E: file:r.txt "pets have owners"]\n')
        write(os.path.join(self.kb, "db", "VISITS.md"),
              '---\ntype: table\nreview_due: 2020-01-01\n---\n# VISITS\n\nVisits record the appointment date. [E: file:r.txt "pets have owners"]\n')
        write(os.path.join(self.kb, "context", "rules.md"), '# Rules\n\nClaims are paid in 30 days. [E: file:r.txt "pets have owners"]\n')
        write(os.path.join(self.kb, "_QUESTIONS", "VALIDATE_KB.yaml"), yaml.safe_dump({"questions": []}))
        self.ctx = C.Ctx(self.kb, "tok", "Pat Lee")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def view(self, **q):
        return S.search_view(self.ctx, q)

    def test_module_contract(self):
        self.assertIn("/search", S.SCREENS)
        self.assertEqual(S.NAV, [("/search", "Search")])
        self.assertEqual(S.ACTIONS, {})

    def test_empty_search_page(self):
        html = self.view()
        self.assertIn("Type some words above", html)
        self.assertIn("3 pages are indexed", html)
        self.assertIn("db", html)  # folder facet in the left pane

    def test_results_have_snippet_with_tag_and_page_link(self):
        html = self.view(q="foreign key owners")
        self.assertIn("1 page for <b>foreign key owners</b>", html)
        self.assertIn('href="/files?page=db/PETS.md"', html)
        self.assertIn("line 3:", html)
        self.assertIn('<span class="tag" title="source">[E: file:r.txt &quot;pets have owners&quot;]</span>', html)

    def test_get_form_is_search_with_q(self):
        html = self.view()
        self.assertIn('<form method="get" action="/search"', html)
        self.assertIn('name="q"', html)
        self.assertNotIn('name="_t"', html.split('action="/search"')[1].split("</form>")[0])

    def test_facet_filter_links_and_clear(self):
        html = self.view(q="the", folder="db")
        self.assertIn("click to clear", html)
        self.assertIn("Clear all filters", html)
        self.assertNotIn("context/rules.md</span>", html.split("<h2>")[1])
        html = self.view(q="visits", stale="yes")
        self.assertIn("stale", html)
        self.assertIn("review was due 2020-01-01", html)

    def test_no_match_message_and_miss_counter_off_by_default(self):
        html = self.view(q="zebra")
        self.assertIn("No page matches", html)
        self.assertFalse(os.path.exists(os.path.join(self.kb, kb_unanswered.COUNTER)))

    def test_miss_counter_when_opted_in(self):
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"),
              yaml.safe_dump({"owners": {"kb_owner": "Ana Lead"}, "search": {"count_misses": True}}))
        self.view(q="zebra ledger")
        with open(os.path.join(self.kb, kb_unanswered.COUNTER), encoding="utf-8") as fh:
            raw = fh.read()
        self.assertNotIn("zebra", raw)
        self.assertEqual(kb_unanswered.counter_status(self.kb)["total"], 1)

    def test_user_text_is_escaped(self):
        html = self.view(q="<script>alert(1)</script>")
        self.assertNotIn("<script>alert(1)", html)
        self.assertIn("&lt;script&gt;", html)
        html = self.view(q="x", folder='"><img src=x>')
        self.assertNotIn("<img src=x>", html)

    def test_unanswered_tab(self):
        a = answers.ask(self.kb, "who owns the zebra ledger", "Pat Lee", mode="local")
        self.assertIn(a["confidence"]["band"], ("None", "Low"))
        html = self.view(tab="unanswered")
        self.assertIn("Unanswered (1)", html)
        self.assertIn("who owns the zebra ledger", html)
        self.assertIn('href="/ask?question=', html)
        self.assertIn("never the question", html)
        self.assertIn("Unanswered (1)", self.view(q="pets"))  # the tab label shows the count too

    def test_unanswered_tab_empty(self):
        self.assertIn("Nothing is unanswered right now", self.view(tab="unanswered"))

    def test_hybrid_note_does_not_break_page(self):
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"),
              yaml.safe_dump({"owners": {"kb_owner": "Ana Lead"}, "search": {"hybrid": True, "embedder": "sentence-transformers:nope"}}))
        saved = sys.modules.get("sentence_transformers")
        sys.modules["sentence_transformers"] = None
        try:
            html = self.view(q="pets")
        finally:
            if saved is None:
                sys.modules.pop("sentence_transformers", None)
            else:
                sys.modules["sentence_transformers"] = saved
        self.assertIn("hybrid search skipped", html)
        self.assertIn("db/PETS.md", html)

    def test_works_through_server_wiring(self):
        import server
        self.assertIn("/search", server.SCREENS)
        self.assertIn(("/search", "Search"), C.NAV_MORE)


if __name__ == "__main__":
    unittest.main()
