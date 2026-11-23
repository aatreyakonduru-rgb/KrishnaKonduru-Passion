import json
import os
import shutil
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import feedback  # noqa: E402
import kb_manifest  # noqa: E402
import telemetry  # noqa: E402
import telemetry_lines as TL  # noqa: E402

PROFILE = {"owners": {"kb_owner": "Ana Lead"}}
PAGE = ("# Rules\n\n"
        "- Claims are paid within 30 days. [E: file:r.txt]\n"
        "- Appeals close after 60 days. [E: file:r.txt]\n"
        "- Fraud flags go to the SIU. [E: file:r.txt]\n")


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def slurp(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def answer(*tags):
    return "# Answer\n\n" + "".join("- A line. [E: %s]\n" % t for t in tags)


class Lines(unittest.TestCase):
    def setUp(self):
        self.kb = tempfile.mkdtemp()
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump(PROFILE))
        write(os.path.join(self.kb, "_EVIDENCE", "files", "r.txt"), "x\n")
        write(os.path.join(self.kb, "context", "rules.md"), PAGE)
        write(os.path.join(self.kb, "context", "b.md"), "# B\n\n- Other. [E: file:r.txt]\n")
        self.n = 0

    def tearDown(self):
        shutil.rmtree(self.kb, ignore_errors=True)

    def rate(self, text, rating, **kw):
        self.n += 1
        p = os.path.join(self.kb, "ans%d.md" % self.n)
        write(p, text)
        return feedback.record(self.kb, p, "Question number %d about claims?" % self.n, "Pat Lee", rating, **kw)

    def test_cited_lines_from_line_range_and_quote_forms(self):
        t = answer('kb:context/rules.md:3', 'kb:context/rules.md:4-5', 'kb:context/rules.md "appeals close after 60 days"',
                   'kb:context/b.md', 'kb:context/rules.md:99', 'kb:context/rules.md "not in the page"', 'kb:context/gone.md:2',
                   'file:r.txt "x"')
        self.assertEqual(TL.cited_lines(self.kb, t), ["context/rules.md:3", "context/rules.md:4", "context/rules.md:5"])

    def test_quote_is_located_across_a_line_break(self):
        write(os.path.join(self.kb, "context", "wrap.md"), "# W\n\nClaims are paid\nwithin 30 days of approval.\n")
        self.assertEqual(TL.cited_lines(self.kb, answer('kb:context/wrap.md "paid within 30 days"')),
                         ["context/wrap.md:3", "context/wrap.md:4"])

    def test_a_long_range_is_capped(self):
        write(os.path.join(self.kb, "context", "long.md"), "\n".join("line %d" % i for i in range(1, 80)) + "\n")
        self.assertEqual(len(TL.cited_lines(self.kb, answer("kb:context/long.md:1-70"))), TL.MAX_RANGE)

    def test_record_stores_lines_but_no_text(self):
        ev = TL.record_answer(self.kb, answer('kb:context/rules.md "paid within 30 days"'), by="Pat Lee")
        self.assertEqual(ev["lines"], ["context/rules.md:3"])
        self.assertEqual(ev["files"], ["context/rules.md"])
        folder = os.path.join(self.kb, ".metis", "usage")
        raw = "".join(slurp(os.path.join(folder, n)) for n in os.listdir(folder) if n.endswith(".jsonl"))
        self.assertNotIn("paid within", raw)
        self.assertNotIn("A line.", raw)
        self.assertEqual(slurp(os.path.join(folder, ".gitignore")).strip(), "*")
        self.assertEqual(TL.used_counts(self.kb), {"context/rules.md:3": 1})

    def test_answer_citing_no_kb_file_records_nothing(self):
        self.assertIsNone(TL.record_answer(self.kb, answer("file:r.txt")))
        self.assertEqual(telemetry.events(self.kb), [])

    def test_manifest_still_ignores_usage_records(self):
        kb_manifest.main(["generate", self.kb])
        TL.record_answer(self.kb, answer("kb:context/rules.md:3"))
        self.assertEqual(kb_manifest.main(["validate", self.kb]), 0)

    def test_look_first_joins_dislikes_to_lines(self):
        self.rate(answer("kb:context/rules.md:3", "kb:context/rules.md:4"), "up")
        self.rate(answer("kb:context/rules.md:3"), "down", why="old", redirect="look at the batch job")
        self.rate(answer("kb:context/rules.md:3", "kb:context/rules.md:5"), "down", why="old", redirect="look at the other job")
        TL.record_answer(self.kb, answer("kb:context/rules.md:3"))
        rep = TL.report(self.kb)
        rows = {r["line"]: r for r in rep["look_first"]}
        self.assertEqual([r["line"] for r in rep["look_first"]], ["context/rules.md:3", "context/rules.md:5"])
        self.assertEqual((rows["context/rules.md:3"]["down"], rows["context/rules.md:3"]["up"], rows["context/rules.md:3"]["used"]), (2, 1, 1))
        self.assertEqual(rows["context/rules.md:3"]["text"], "- Claims are paid within 30 days. [E: file:r.txt]")
        self.assertNotIn("context/rules.md:4", rows)
        self.assertEqual(rep["lines_rated"], 3)

    def test_declined_dislike_is_counted_apart(self):
        self.rate(answer("kb:context/rules.md:4"), "down", why="no", redirect="elsewhere")
        reg = feedback.load(self.kb)
        reg["feedback"][0]["status"] = "declined"
        feedback.save(self.kb, reg)
        rep = TL.report(self.kb)
        self.assertEqual(rep["look_first"], [])
        self.assertEqual(TL.rated_lines(self.kb)[0]["context/rules.md:4"]["declined"], 1)

    def test_a_line_that_no_longer_exists_is_said_so(self):
        self.rate(answer("kb:context/rules.md:5"), "down", why="no", redirect="elsewhere")
        write(os.path.join(self.kb, "context", "rules.md"), "# Rules\n")
        row = TL.report(self.kb)["look_first"][0]
        self.assertEqual((row["text"], row["status"]), (None, "line no longer exists"))

    def test_rated_answer_without_lines_is_counted(self):
        self.rate(answer("kb:context/b.md"), "up")
        self.assertEqual(TL.report(self.kb)["rated_answers_without_lines"], 1)

    def test_cli_record_and_report(self):
        p = os.path.join(self.kb, "a.md")
        write(p, answer("kb:context/rules.md:3"))
        self.assertEqual(TL.main(["record", self.kb, "--answer", p, "--by", "Pat Lee"]), 0)
        self.assertEqual(TL.main(["report", self.kb]), 0)
        write(p, "# nothing\n")
        self.assertEqual(TL.main(["record", self.kb, "--answer", p]), 0)


class Anchors(unittest.TestCase):
    """Per-line telemetry keyed by a stable content fingerprint."""
    setUp, tearDown, rate = Lines.setUp, Lines.tearDown, Lines.rate

    def edit_top(self):
        write(os.path.join(self.kb, "context", "rules.md"),
              "# Rules\n\nA new intro line.\nAnother new line.\n" + PAGE.split("\n", 2)[2])

    def test_event_carries_anchors_without_text(self):
        ev = TL.record_answer(self.kb, answer("kb:context/rules.md:3"), by="Pat Lee")
        self.assertEqual(len(ev["anchors"]), 1)
        self.assertTrue(ev["anchors"][0].startswith("context/rules.md:3#"))
        raw = json.dumps(ev)
        self.assertNotIn("paid", raw)
        self.assertNotIn("30 days", raw)
        self.assertEqual(TL.used_counts(self.kb), {"context/rules.md:3": 1})   # the old view is unchanged

    def test_fingerprint_ignores_tag_bullet_case_spacing_and_is_per_page(self):
        fp = lambda rel, t: TL.fingerprint(rel, t, "s")  # noqa: E731
        a = fp("p.md", "- Claims are paid within 30 days. [E: file:r.txt]")
        self.assertEqual(a, fp("p.md", "*   claims  ARE paid within 30 days. [E: file:other.txt] {sensitivity: internal}"))
        self.assertNotEqual(a, fp("q.md", "- Claims are paid within 30 days."))
        self.assertNotEqual(a, fp("p.md", "- Claims are paid within 31 days."))
        self.assertIsNone(fp("p.md", "   "))
        self.assertNotEqual(a, TL.fingerprint("p.md", "- Claims are paid within 30 days.", "other salt"))

    def test_counts_follow_a_line_after_an_edit_above_it(self):
        TL.record_answer(self.kb, answer("kb:context/rules.md:3"))
        TL.record_answer(self.kb, answer("kb:context/rules.md:3"))
        self.edit_top()                                           # the line is now line 5
        rep = TL.reanchor(self.kb)
        self.assertEqual((rep["moved"], rep["gone"]), ([{"from": "context/rules.md:3", "to": "context/rules.md:5", "used": 2}], []))
        self.assertEqual(TL.used_now(self.kb), {"context/rules.md:5": 2})
        self.assertEqual(TL.report(self.kb)["most_used"], [{"line": "context/rules.md:5", "used": 2}])

    def test_a_removed_or_reworded_line_is_reported_gone(self):
        TL.record_answer(self.kb, answer("kb:context/rules.md:3", "kb:context/rules.md:4"))
        write(os.path.join(self.kb, "context", "rules.md"),
              "# Rules\n\n- Claims are paid within 45 days. [E: file:r.txt]\n- Appeals close after 60 days. [E: file:r.txt]\n")
        rep = TL.reanchor(self.kb)
        self.assertEqual([g["line"] for g in rep["gone"]], ["context/rules.md:3"])
        self.assertEqual((rep["unchanged"], rep["checked"]), (1, 2))
        self.assertEqual(TL.used_now(self.kb), {"context/rules.md:4": 1})

    def test_rating_given_through_anchor_rated_follows_the_line(self):
        item = self.rate(answer("kb:context/rules.md:4"), "down", why="old", redirect="look elsewhere")
        self.assertEqual(TL.anchor_rated(self.kb, item["id"]), 1)
        TL.record_answer(self.kb, answer("kb:context/rules.md:4"))
        self.edit_top()                                           # line 4 -> 6
        row = TL.report(self.kb)["look_first"][0]
        self.assertEqual((row["line"], row["moved_from"], row["status"], row["used"]), ("context/rules.md:6", "context/rules.md:4", "current", 1))
        self.assertIn("Appeals close", row["text"])
        write(os.path.join(self.kb, "context", "rules.md"), "# Rules\n")
        row = TL.report(self.kb)["look_first"][0]
        self.assertEqual((row["text"], row["status"]), (None, "line no longer exists"))
        self.assertEqual(TL.reanchor(self.kb)["gone"][0]["line"], "context/rules.md:4")

    def test_old_records_without_anchors_fall_back_to_line_numbers(self):
        telemetry.record(self.kb, "answer", ["context/rules.md"], lines=["context/rules.md:3", "context/rules.md:99"], anchors=[])
        # `anchors=[]` still means "none given", so this event is a legacy one
        self.assertNotIn("anchors", telemetry.events(self.kb)[0])
        self.assertEqual(TL.used_now(self.kb), {"context/rules.md:3": 1})
        rep = TL.reanchor(self.kb)
        self.assertEqual([g["line"] for g in rep["gone"]], ["context/rules.md:99"])

    def test_anchor_files_hold_no_text_and_stay_in_the_ignored_usage_folder(self):
        item = self.rate(answer("kb:context/rules.md:3"), "up")
        TL.anchor_rated(self.kb, item["id"])
        TL.record_answer(self.kb, answer("kb:context/rules.md:3"))
        folder = os.path.join(self.kb, ".metis", "usage")
        for name in os.listdir(folder):
            if name != ".gitignore":
                self.assertNotIn("paid within", slurp(os.path.join(folder, name)).lower())
                self.assertNotIn("Question number", slurp(os.path.join(folder, name)))
        self.assertTrue(os.path.isfile(os.path.join(folder, "line-anchors.json")))
        self.assertFalse(os.path.exists(os.path.join(folder, "line-anchors.json.tmp")))
        kb_manifest.main(["generate", self.kb])
        self.assertEqual(kb_manifest.main(["validate", self.kb]), 0)

    def test_cli_reanchor(self):
        TL.record_answer(self.kb, answer("kb:context/rules.md:3"))
        self.edit_top()
        self.assertEqual(TL.main(["reanchor", self.kb]), 0)


class TelemetryBackCompat(unittest.TestCase):
    def setUp(self):
        self.kb = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.kb, ignore_errors=True)

    def test_without_lines_the_event_has_the_old_keys_only(self):
        ev = telemetry.record(self.kb, "answer", ["a.md"], by="KK")
        self.assertEqual(set(ev), {"at", "kind", "files", "by", "pack_id", "tokens", "skipped"})
        self.assertNotIn("lines", json.dumps(telemetry.events(self.kb)))

    def test_with_lines_they_are_sorted_unique_and_old_report_still_works(self):
        telemetry.record(self.kb, "answer", ["a.md"], lines=["a.md:3", "a.md:1", "a.md:3"])
        self.assertEqual(telemetry.events(self.kb)[0]["lines"], ["a.md:1", "a.md:3"])
        self.assertEqual(telemetry.report(self.kb)["files_used"]["a.md"], {"packs": 0, "answers": 1})

    def test_positional_arguments_are_unchanged(self):
        ev = telemetry.record(self.kb, "pack", ["a.md"], "P-1", 10, "Pat", 2)
        self.assertEqual((ev["pack_id"], ev["tokens"], ev["by"], ev["skipped"]), ("P-1", 10, "Pat", 2))


if __name__ == "__main__":
    unittest.main()
