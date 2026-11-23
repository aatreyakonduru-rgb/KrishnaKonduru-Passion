import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import facts_time  # noqa: E402
import verify_kb  # noqa: E402


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def rmtree(path):
    def onerror(func, p, _):
        os.chmod(p, 0o700)
        func(p)
    shutil.rmtree(path, onerror=onerror)


RULES = """# Rules

- Claims are paid within 30 days [E: file:rules.txt "30 days"] {valid-from: 2026-01-01; valid-to: 2026-02-28}
- Claims are paid within 45 days [E: file:rules.txt "45 days"] {valid-from: 2026-03-01; superseded-by: context/rules.md:5}
- Claims are paid within 60 days [E: file:rules.txt "60 days"] {valid-from: 2026-06-01; valid-to: 2026-09-30}
- Appeals take 10 days [E: file:rules.txt "10 days"]
"""


class FactsTime(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.kb = os.path.join(self.d, "kb")
        write(os.path.join(self.kb, "_EVIDENCE", "files", "rules.txt"), "30 days 45 days 60 days 10 days\n")
        write(os.path.join(self.kb, "context", "rules.md"), RULES)

    def tearDown(self):
        rmtree(self.d)

    def ids(self, rows):
        return [r["id"] for r in rows]

    def test_verify_kb_ignores_the_annotation(self):
        rep = verify_kb.Checker(self.kb).run()
        self.assertEqual(rep["problems"], [])
        self.assertEqual(rep["tags"], 4)

    def test_verify_kb_still_flags_bad_tag_beside_annotation(self):
        write(os.path.join(self.kb, "context", "bad.md"), '- x [E: file:nope.txt "x"] {valid-from: 2026-01-01}\n')
        probs = verify_kb.Checker(self.kb).run()["problems"]
        self.assertEqual([p["file"].replace("\\", "/") for p in probs], ["context/bad.md"])

    def test_build_counts(self):
        n, ann, probs = facts_time.build(self.kb)
        self.assertEqual((n, ann), (4, 3))
        self.assertEqual(probs, [])
        self.assertTrue(os.path.isfile(os.path.join(self.kb, ".metis", "facts.sqlite")))

    def test_as_of(self):
        self.assertEqual(self.ids(facts_time.as_of(self.kb, "2026-02-10")), ["context/rules.md:3"])
        self.assertEqual(facts_time.as_of(self.kb, "2026-02-10", True)[-1]["id"], "context/rules.md:6")
        # the 45-day line is superseded by line 5 (valid-from 2026-06-01): valid 2026-03-01 .. 2026-05-31
        self.assertEqual(self.ids(facts_time.as_of(self.kb, "2026-04-15")), ["context/rules.md:4"])
        self.assertEqual(self.ids(facts_time.as_of(self.kb, "2026-05-31")), ["context/rules.md:4"])
        self.assertEqual(self.ids(facts_time.as_of(self.kb, "2026-06-01")), ["context/rules.md:5"])
        self.assertEqual(facts_time.as_of(self.kb, "2026-10-01"), [])
        self.assertEqual(facts_time.as_of(self.kb, "2025-12-31"), [])

    def test_boundaries_inclusive(self):
        self.assertEqual(self.ids(facts_time.as_of(self.kb, "2026-02-28")), ["context/rules.md:3"])
        self.assertEqual(facts_time.as_of(self.kb, "2026-03-01")[0]["id"], "context/rules.md:4")

    def test_bad_date_refused(self):
        with self.assertRaises(ValueError):
            facts_time.as_of(self.kb, "03/01/2026")
        with self.assertRaises(ValueError):
            facts_time.as_of(self.kb, "2026-02-30")

    def test_history(self):
        rows = facts_time.history(self.kb, "Claims are paid")
        self.assertEqual([r["id"] for r in rows], ["context/rules.md:3", "context/rules.md:4", "context/rules.md:5"])
        self.assertEqual(facts_time.history(self.kb, "appeals")[0]["status"], "no dates")
        with self.assertRaises(ValueError):
            facts_time.history(self.kb, " ")

    def test_expired(self):
        got = facts_time.expired(self.kb, "2026-10-15")
        self.assertEqual(self.ids(got), ["context/rules.md:3", "context/rules.md:5"])
        self.assertEqual(self.ids(facts_time.expired(self.kb, "2026-07-01")), ["context/rules.md:3"])

    def test_superseded_line_is_not_expired(self):
        write(os.path.join(self.kb, "context", "rules.md"),
              '- old [E: file:rules.txt "30 days"] {valid-to: 2026-01-31; superseded-by: context/new.md}\n')
        write(os.path.join(self.kb, "context", "new.md"), '- new [E: file:rules.txt "30 days"] {valid-from: 2026-02-01}\n')
        self.assertEqual(facts_time.expired(self.kb, "2027-01-01"), [])

    def test_superseded_without_usable_end(self):
        write(os.path.join(self.kb, "context", "rules.md"),
              '- old [E: file:rules.txt "30 days"] {superseded-by: context/new.md}\n')
        write(os.path.join(self.kb, "context", "new.md"), '- new [E: file:rules.txt "30 days"]\n')
        got = facts_time.expired(self.kb, "2027-01-01")
        self.assertEqual(got[0]["why"], "superseded, no end date")
        self.assertEqual(facts_time.as_of(self.kb, "2026-01-01"), [])

    def test_annotation_problems_reported(self):
        write(os.path.join(self.kb, "context", "rules.md"),
              '- a [E: file:rules.txt "30 days"] {valid-from: 2026-13-01}\n'
              '- b [E: file:rules.txt "30 days"] {valid-from: 2026-05-01; valid-to: 2026-04-01}\n'
              '- c [E: file:rules.txt "30 days"] {superseded-by: context/missing.md}\n')
        _, _, probs = facts_time.build(self.kb)
        text = " | ".join(p[2] for p in probs)
        self.assertIn("must be a date", text)
        self.assertIn("before valid-from", text)
        self.assertIn("not a page in the KB", text)

    def test_other_brace_groups_are_left_alone(self):
        line = '- a [E: file:rules.txt "30 days"] {env: prod; sensitivity: restricted} {valid-from: 2026-01-01}'
        vals, probs = facts_time.line_annotation(line)
        self.assertEqual(vals, {"valid-from": "2026-01-01"})
        self.assertEqual(probs, [])
        self.assertEqual(facts_time.line_annotation("- x [E: file:a] {env: prod}")[0], {})

    def test_underscore_keys_and_code_spans(self):
        vals, _ = facts_time.line_annotation("- x [E: file:a] {valid_from: 2026-01-01}")
        self.assertEqual(vals, {"valid-from": "2026-01-01"})
        vals, _ = facts_time.line_annotation("- use `{valid-from: 2026-01-01}` [E: file:a]")
        self.assertEqual(vals, {})

    def test_code_blocks_and_front_matter_skipped(self):
        write(os.path.join(self.kb, "context", "c.md"),
              '---\nnote: "{valid-from: 2026-01-01}"\n---\n```\n- x [E: file:rules.txt] {valid-from: 2026-01-01}\n```\n')
        n, _, _ = facts_time.build(self.kb)
        self.assertEqual(n, 4)

    def test_as_of_edges(self):
        edges = [{"from": "table:A", "rel": "reads", "to": "table:B", "source": "s", "origin": "parsed"},
                 {"from": "table:A", "rel": "writes", "to": "table:C", "source": "s", "origin": "parsed", "valid_to": "2026-03-31"},
                 {"from": "table:A", "rel": "feeds", "to": "table:D", "source": "s", "origin": "parsed"}]
        write(os.path.join(self.kb, "CROSS-LAYER", "LINK_GRAPH.yaml"), yaml.safe_dump({"nodes": [], "edges": edges}))
        write(os.path.join(self.kb, "CROSS-LAYER", "edge_validity.yaml"), yaml.safe_dump(
            {"edges": [{"from": "table:A", "rel": "feeds", "to": "table:D", "valid_from": "2026-05-01"}]}))
        names = lambda d: sorted(e["rel"] for e in facts_time.as_of_edges(self.kb, d))  # noqa: E731
        self.assertEqual(names("2026-02-01"), ["reads", "writes"])
        self.assertEqual(names("2026-04-15"), ["reads"])
        self.assertEqual(names("2026-05-01"), ["feeds", "reads"])
        # nothing built, nothing breaks
        self.assertEqual(facts_time.as_of_edges(os.path.join(self.d, "empty"), "2026-01-01"), [])

    def test_page_at_with_git(self):
        def git(*a):
            return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com"] + list(a), cwd=self.kb,
                                  capture_output=True, text=True)
        if git("init").returncode:
            self.skipTest("git not available")
        git("add", "-A")
        self.assertEqual(git("commit", "-m", "one").returncode, 0)
        old = facts_time.page_at(self.kb, "HEAD", "context/rules.md")
        self.assertIn("within 30 days", old)
        write(os.path.join(self.kb, "context", "rules.md"), "# changed\n")
        git("add", "-A")
        git("commit", "-m", "two")
        self.assertIn("within 30 days", facts_time.page_at(self.kb, "HEAD~1", "context/rules.md"))
        self.assertEqual(facts_time.page_at(self.kb, "HEAD", "context/rules.md"), "# changed\n")
        with self.assertRaises(ValueError):
            facts_time.page_at(self.kb, "HEAD", "context/none.md")
        with self.assertRaises(ValueError):
            facts_time.page_at(self.kb, "HEAD", "../x.md")
        with self.assertRaises(ValueError):
            facts_time.page_at(self.kb, "--output=x", "context/rules.md")

    # ---- section annotations --------------------------------------------------------------------
    SECTIONED = """# Rules

## Claim rules {as of: 2026-03-01; valid-until: 2026-09-30}

- Claims are paid within 30 days [E: file:rules.txt "30 days"]
- Appeals take 10 days [E: file:rules.txt "10 days"] {valid-to: 2026-05-31}
- Fraud goes to SIU [E: file:rules.txt "30 days"] {valid-from: 2026-04-01}

### Edge cases {valid-to: 2026-06-30}

- Late claims need approval [E: file:rules.txt "45 days"]

## Other

- Plain line [E: file:rules.txt "60 days"]
"""

    def sectioned(self, text=None):
        write(os.path.join(self.kb, "context", "rules.md"), text or self.SECTIONED)
        return {r["id"]: r for r in facts_time.as_of(self.kb, "2026-05-15", True)}

    def test_section_annotation_applies_to_lines_below(self):
        got = self.sectioned()
        self.assertEqual((got["context/rules.md:5"]["valid_from"], got["context/rules.md:5"]["valid_to"]),
                         ("2026-03-01", "2026-09-30"))
        self.assertEqual(got["context/rules.md:5"]["from_section"], "context/rules.md:3")
        self.assertEqual(self.ids(facts_time.as_of(self.kb, "2026-02-28")), [])           # before the section starts
        self.assertEqual(self.ids(facts_time.as_of(self.kb, "2026-10-01")), [])           # after valid-until

    def test_line_annotation_overrides_the_section_per_key(self):
        got = self.sectioned()
        self.assertEqual((got["context/rules.md:6"]["valid_from"], got["context/rules.md:6"]["valid_to"]), ("2026-03-01", "2026-05-31"))
        self.assertNotIn("context/rules.md:6", self.ids(facts_time.as_of(self.kb, "2026-06-01")))   # its own valid-to won
        # line 7 gives its own valid-from and takes valid-to from the section
        self.assertNotIn("context/rules.md:7", self.ids(facts_time.as_of(self.kb, "2026-03-15")))
        self.assertIn("context/rules.md:7", self.ids(facts_time.as_of(self.kb, "2026-04-01")))
        self.assertEqual(self.sectioned()["context/rules.md:7"]["valid_to"], "2026-09-30")

    def test_subsection_inherits_and_overrides_its_parent(self):
        got = self.sectioned()
        row = got["context/rules.md:11"]
        self.assertEqual((row["valid_from"], row["valid_to"]), ("2026-03-01", "2026-06-30"))
        self.assertEqual(row["from_section"], "context/rules.md:9")
        self.assertIn("context/rules.md:11", self.ids(facts_time.as_of(self.kb, "2026-06-30")))
        self.assertNotIn("context/rules.md:11", self.ids(facts_time.as_of(self.kb, "2026-07-01")))

    def test_section_ends_at_next_heading_of_same_or_higher_level(self):
        got = self.sectioned()
        row = got["context/rules.md:15"]                      # under "## Other": no dates, so undated
        self.assertEqual((row["valid_from"], row["valid_to"], row["from_section"]), (None, None, None))
        n, ann, _ = facts_time.build(self.kb)
        self.assertEqual(ann, 6)                              # heading, heading, and the four dated lines; "Plain line" is undated
        # a `#` heading also closes a `##` section
        write(os.path.join(self.kb, "context", "rules.md"), "## A {valid-to: 2026-01-31}\n- a [E: file:rules.txt]\n# B\n- b [E: file:rules.txt]\n")
        facts_time.build(self.kb)
        got = {r["id"]: r for r in facts_time.as_of(self.kb, "2026-01-15", True)}
        self.assertEqual(got["context/rules.md:2"]["valid_to"], "2026-01-31")
        self.assertIsNone(got["context/rules.md:4"]["valid_to"])

    def test_aliases_valid_until_and_as_of(self):
        vals, probs = facts_time.line_annotation("- x [E: file:a] {as of: 2026-01-01; valid-until: 2026-02-01}")
        self.assertEqual((vals, probs), ({"valid-from": "2026-01-01", "valid-to": "2026-02-01"}, []))
        self.assertEqual(facts_time.line_annotation("- x [E: file:a] {as_of: 2026-01-01}")[0], {"valid-from": "2026-01-01"})
        self.assertIn("twice", " ".join(facts_time.line_annotation("- x {valid-from: 2026-01-01; as-of: 2026-02-01}")[1]))

    def test_section_contradiction_is_a_problem(self):
        write(os.path.join(self.kb, "context", "rules.md"),
              "## S {valid-from: 2026-06-01}\n- x [E: file:rules.txt] {valid-to: 2026-05-01}\n")
        _, _, probs = facts_time.build(self.kb)
        self.assertEqual([(p[0], p[1]) for p in probs], [("context/rules.md", 2)])
        self.assertIn("from the section", probs[0][2])

    def test_section_headings_in_code_blocks_and_other_groups_are_ignored(self):
        got = self.sectioned("```\n## S {valid-to: 2026-01-01}\n```\n- x [E: file:rules.txt]\n"
                             "## T {env: prod; sensitivity: restricted}\n- y [E: file:rules.txt]\n")
        self.assertEqual((got["context/rules.md:4"]["valid_to"], got["context/rules.md:6"]["valid_to"]), (None, None))

    def test_section_dates_reach_expired_and_history(self):
        self.sectioned("## S {valid-until: 2026-01-31}\n- old rule [E: file:rules.txt]\n")
        self.assertIn("context/rules.md:2", self.ids(facts_time.expired(self.kb, "2026-03-01")))
        self.assertEqual(facts_time.history(self.kb, "old rule")[0]["valid_to"], "2026-01-31")

    def test_old_index_without_section_column_is_rebuilt(self):
        facts_time.build(self.kb)
        import sqlite3
        con = sqlite3.connect(facts_time.db_path(self.kb))
        con.executescript("drop table facts; create table facts (id integer primary key, path text, line integer, text text, "
                          "valid_from text, valid_to text, superseded_by text, annotated integer);")
        con.commit()
        con.close()
        self.assertEqual(self.ids(facts_time.as_of(self.kb, "2026-02-10")), ["context/rules.md:3"])

    def test_cli_shows_the_section(self):
        write(os.path.join(self.kb, "context", "rules.md"), "## S {valid-from: 2026-01-01}\n- x [E: file:rules.txt]\n")
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(facts_time.main(["as-of", self.kb, "2026-02-01"]), 0)
        self.assertIn("[section context/rules.md:1]", buf.getvalue())

    def test_cli(self):
        self.assertEqual(facts_time.main(["build", self.kb]), 0)
        self.assertEqual(facts_time.main(["as-of", self.kb, "2026-02-10"]), 0)
        self.assertEqual(facts_time.main(["history", self.kb, "Appeals"]), 0)
        self.assertEqual(facts_time.main(["expired", self.kb, "--today", "2026-10-15"]), 1)
        self.assertEqual(facts_time.main(["as-of", self.kb, "nope"]), 2)


if __name__ == "__main__":
    unittest.main()
