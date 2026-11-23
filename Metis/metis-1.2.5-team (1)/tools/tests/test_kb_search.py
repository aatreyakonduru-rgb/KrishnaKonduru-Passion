import json
import os
import shutil
import sys
import tempfile
import time
import unittest

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
for _p in (TOOLS, os.path.join(TOOLS, "ui")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import kb_search as S  # noqa: E402


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def make_kb(root):
    kb = os.path.join(root, "KB")
    write(os.path.join(kb, ".metis", "kb-profile.yaml"), yaml.safe_dump({"owners": {"kb_owner": "Ana Lead"}}))
    write(os.path.join(kb, "db", "PETS.md"),
          '# PETS\n\nThe pets table has a foreign key to owners. [E: file:r.txt "pets have owners"]\n\n'
          '## Columns\n\n- OWNER_ID links each pet to its owner. [E: file:r.txt "owner id"]\n')
    write(os.path.join(kb, "db", "VISITS.md"),
          '---\ntype: table\nreview_due: 2020-01-01\n---\n# VISITS\n\nVisits record the vet appointment date. [E: file:r.txt "visit"]\n'
          'Billing is unknown. [?: Q-0001]\n')
    write(os.path.join(kb, "context", "rules.md"),
          '---\ntype: rule\n---\n# Rules\n\nClaims are paid within 30 days. [E: file:r.txt "30 days"]\n')
    write(os.path.join(kb, "context", "SECRETS.md"), '# Secrets\n\npassword: hunter2hunter2 for the zebra system [E: file:r.txt "x"]\n')
    write(os.path.join(kb, "_PENDING", "b1", "context", "pending.md"), "# Pending\n\nzebra pending text\n")
    write(os.path.join(kb, "_FEEDBACK", "answers", "F-0001.md"), "# Answer\n\nzebra feedback text\n")
    write(os.path.join(kb, ".metis", "notes.md"), "# Hidden\n\nzebra hidden text\n")
    write(os.path.join(kb, "_EVIDENCE", "files", "r.txt"), "pets have owners\n")
    return kb


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.kb = make_kb(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def paths(self, rep):
        return [r["path"] for r in rep["results"]]

    def test_basic_hit_and_snippet_keeps_tag(self):
        rep = S.search(self.kb, "foreign key owners")
        self.assertEqual(self.paths(rep)[0], "db/PETS.md")
        top = rep["results"][0]
        self.assertIn('[E: file:r.txt "pets have owners"]', top["snippet"])
        self.assertEqual(top["line"], 3)

    def test_long_line_cut_in_prose_not_in_tag(self):
        long = "The pets table " + "has many words " * 40 + 'zebrafish. [E: file:r.txt "pets have owners"] [E: kb:db/PETS.md "pets"]'
        write(os.path.join(self.kb, "db", "LONG.md"), "# Long\n\n" + long + "\n")
        r = S.search(self.kb, "zebrafish")["results"][0]
        self.assertTrue(r["snippet"].endswith('[E: file:r.txt "pets have owners"] [E: kb:db/PETS.md "pets"]'))
        self.assertLess(len(r["snippet"]), len(long))

    def test_skips_pending_feedback_metis_and_sensitive(self):
        rep = S.search(self.kb, "zebra")
        self.assertEqual(rep["total"], 0)
        st = S.status(self.kb)
        self.assertEqual(st["skipped"].get("sensitive"), 1)

    def test_heading_boost(self):
        write(os.path.join(self.kb, "a", "H.md"), "# Alpha\n\n## Gizmo\n\nplain words here. [E: file:r.txt \"x\"]\n")
        write(os.path.join(self.kb, "a", "B.md"), "# Beta\n\nA gizmo is mentioned once among many other words. [E: file:r.txt \"x\"]\n")
        self.assertEqual(self.paths(S.search(self.kb, "gizmo"))[0], "a/H.md")

    def test_engines_agree_on_top_result(self):
        py = S.search(self.kb, "appointment", engine="python")
        self.assertEqual(py["engine"], "python")
        self.assertEqual(self.paths(py)[0], "db/VISITS.md")
        if S.has_fts5():
            fts = S.search(self.kb, "appointment", engine="fts5")
            self.assertEqual(fts["engine"], "fts5")
            self.assertEqual(self.paths(fts)[0], "db/VISITS.md")

    def test_pure_python_when_no_fts5(self):
        real = S.has_fts5
        S.has_fts5 = lambda: False
        try:
            S.sync(self.kb, rebuild=True)
            rep = S.search(self.kb, "appointment")
            self.assertEqual(rep["engine"], "python")
            self.assertEqual(self.paths(rep)[0], "db/VISITS.md")
            with self.assertRaises(ValueError):
                S.search(self.kb, "appointment", engine="fts5")
        finally:
            S.has_fts5 = real

    def test_glossary_synonym(self):
        write(os.path.join(self.kb, ".metis", "glossary.yaml"),
              yaml.safe_dump({"entries": [{"term": "client", "synonyms": ["owner"], "meaning": "the pet owner"}]}))
        rep = S.search(self.kb, "client", engine="python")
        self.assertIn("db/PETS.md", self.paths(rep))
        self.assertIn("owner", rep["synonyms"])

    def test_facets_folder_type_open_question_stale(self):
        rep = S.search(self.kb, "visits table pets rules claims", limit=50)
        self.assertEqual(rep["facets"]["folder"]["db"], 2)
        self.assertEqual(self.paths(S.search(self.kb, "claims", folder="context")), ["context/rules.md"])
        self.assertEqual(self.paths(S.search(self.kb, "claims", ptype="rule")), ["context/rules.md"])
        self.assertEqual(self.paths(S.search(self.kb, "claims", ptype="table")), [])
        self.assertEqual(self.paths(S.search(self.kb, "visits", open_question="yes")), ["db/VISITS.md"])
        self.assertEqual(self.paths(S.search(self.kb, "pets", open_question="yes")), [])
        stale = S.search(self.kb, "visits", stale="yes")
        self.assertEqual(self.paths(stale), ["db/VISITS.md"])
        self.assertIn("2020-01-01", stale["results"][0]["stale_why"])
        self.assertEqual(self.paths(S.search(self.kb, "visits", stale="no")), [])

    def test_owner_facet_needs_page_meta(self):
        self.assertEqual(S.search(self.kb, "pets")["facets"]["owner"], {})
        write(os.path.join(self.kb, ".metis", "page_meta.yaml"), yaml.safe_dump(
            {"pages": {"db/PETS.md": {"owner": "Dana", "review_due": "2999-01-01"}, "db/VISITS.md": {"owner": "Eli"}}}))
        rep = S.search(self.kb, "pets visits", limit=10)
        self.assertEqual(rep["facets"]["owner"], {"Dana": 1, "Eli": 1})
        self.assertEqual(self.paths(S.search(self.kb, "pets visits", owner="dana")), ["db/PETS.md"])

    def test_open_question_from_register(self):
        write(os.path.join(self.kb, "_QUESTIONS", "VALIDATE_KB.yaml"), yaml.safe_dump({"questions": [
            {"id": "Q-0002", "question": "q", "status": "open", "blocks": ["context/rules.md"]}]}))
        self.assertEqual(self.paths(S.search(self.kb, "claims", open_question="yes")), ["context/rules.md"])

    def test_index_refreshes_when_files_change(self):
        S.search(self.kb, "pets")
        self.assertEqual(S.search(self.kb, "quokka")["total"], 0)
        time.sleep(0.02)
        write(os.path.join(self.kb, "db", "NEW.md"), "# New\n\nThe quokka table. [E: file:r.txt \"x\"]\n")
        self.assertEqual(self.paths(S.search(self.kb, "quokka")), ["db/NEW.md"])
        write(os.path.join(self.kb, "db", "NEW.md"), "# New\n\nThe wombat table. [E: file:r.txt \"x\"]\n")
        self.assertEqual(S.search(self.kb, "quokka")["total"], 0)
        self.assertEqual(self.paths(S.search(self.kb, "wombat")), ["db/NEW.md"])
        os.remove(os.path.join(self.kb, "db", "NEW.md"))
        self.assertEqual(S.search(self.kb, "wombat")["total"], 0)

    def test_unchanged_files_are_not_reindexed(self):
        S.sync(self.kb)
        self.assertEqual(S.sync(self.kb)["indexed"], 0)

    def test_damaged_cache_is_rebuilt(self):
        S.sync(self.kb)
        with open(S.db_path(self.kb), "wb") as fh:
            fh.write(b"not a database at all" * 50)
        self.assertEqual(self.paths(S.search(self.kb, "appointment"))[0], "db/VISITS.md")

    def test_empty_query_lists_pages_for_browsing(self):
        rep = S.search(self.kb, "", limit=50)
        self.assertEqual(sorted(self.paths(rep)), ["context/rules.md", "db/PETS.md", "db/VISITS.md"])

    def test_identifier_splitting(self):
        self.assertIn("owner", S.tokens("OWNER_ID"))
        self.assertIn("order", S.tokens("OrderItem"))
        self.assertEqual(self.paths(S.search(self.kb, "owner_id"))[0], "db/PETS.md")

    def test_hybrid_off_by_default_and_failure_is_a_note(self):
        rep = S.search(self.kb, "pets")
        self.assertFalse(rep["hybrid"])
        rep = S.search(self.kb, "pets", hybrid=True)  # builds the built-in hashing vectors on first use
        self.assertTrue(rep["hybrid"])
        self.assertTrue(rep["total"] >= 1)

    def test_rrf(self):
        fused = S.reciprocal_rank_fusion([[(1, 0), (2, 0), (3, 0)], [(3, 0), (2, 0)]])
        self.assertEqual({c for c, _ in fused}, {1, 2, 3})
        scores = dict(fused)
        self.assertGreater(scores[2], scores[1])
        self.assertEqual(fused[0][0], 3)

    def test_cli(self):
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = S.main(["query", self.kb, "appointment", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(buf.getvalue())["results"][0]["path"], "db/VISITS.md")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(S.main(["query", self.kb, "appointment"]), 0)
        self.assertIn("db/VISITS.md", buf.getvalue())
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(S.main(["status", self.kb]), 0)
            self.assertEqual(S.main(["facets", self.kb]), 0)
            self.assertEqual(S.main(["index", self.kb, "--rebuild"]), 0)


if __name__ == "__main__":
    unittest.main()
