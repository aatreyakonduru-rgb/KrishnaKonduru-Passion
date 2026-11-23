import os
import shutil
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import kb_contradict as K  # noqa: E402
import kb_gate  # noqa: E402
import questions  # noqa: E402
import verify_kb  # noqa: E402

PROFILE = {"owners": {"kb_owner": "Ana Lead"}}


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def slurp(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class Extract(unittest.TestCase):
    def one(self, text):
        return K.extract("p.md", text)

    def test_key_value_with_subject_and_tag(self):
        cs = self.one("# Jobs\n\n- ORDERS_LOAD schedule: nightly at 02:00 [E: file:r.txt]\n")
        self.assertEqual(len(cs), 1)
        c = cs[0]
        self.assertEqual((c["subject"], c["attr"], c["value"], c["line"]), ("orders load", "schedule", "nightly at 02:00", 3))
        self.assertEqual(c["evidence"], ["file:r.txt"])

    def test_table_rows_use_the_header_as_attribute(self):
        t = "| Job | Schedule | Owner |\n|---|---|---|\n| LOAD_A | nightly | Etl Team |\n| LOAD_B | hourly | |\n"
        got = {(c["subject"], c["attr"], c["value"]) for c in self.one(t)}
        self.assertEqual(got, {("load a", "schedule", "nightly"), ("load a", "owner", "etl team"), ("load b", "schedule", "hourly")})

    def test_attribute_value_table_under_heading(self):
        t = "## Claims Job\n\n| Attribute | Value |\n|---|---|\n| Schedule | nightly |\n| Type | batch |\n"
        got = {(c["subject"], c["attr"], c["value"]) for c in self.one(t)}
        self.assertEqual(got, {("claims job", "schedule", "nightly"), ("claims job", "type", "batch")})

    def test_sentence_patterns(self):
        t = ("The claim table is owned by the Data Team.\nThe nightly load runs at 02:00.\nCLAIM_HDR has 12 columns.\n"
             "The portal is a web application.\nThe adjuster service runs on Linux.\n")
        got = {(c["subject"], c["attr"], c["value"]) for c in self.one(t)}
        self.assertIn(("claim table", "owner", "data team"), got)
        self.assertIn(("nightly load", "schedule", "at 02:00"), got)
        self.assertIn(("claim hdr", "count of column", "12"), got)
        self.assertIn(("portal", "type", "web application"), got)
        self.assertIn(("adjuster service", "platform", "linux"), got)

    def test_exempt_sections_code_and_front_matter_are_skipped(self):
        t = ("---\nschedule: weekly\n---\n# Open questions\n\n- LOAD schedule: weekly\n\n# Facts\n\n```\nLOAD schedule: daily\n```\n"
             "> LOAD schedule: monthly\n")
        self.assertEqual(self.one(t), [])

    def test_empty_and_unknown_values_are_not_claims(self):
        self.assertEqual(self.one("- LOAD schedule: TBD\n- LOAD owner: n/a\n"), [])


class Compat(unittest.TestCase):
    def test_equal_and_contained_values_agree(self):
        self.assertTrue(K.compatible("nightly", "nightly at 02:00"))
        self.assertTrue(K.compatible("12", "12"))
        self.assertTrue(K.compatible("1000", "1000"))

    def test_different_values_and_negations_disagree(self):
        self.assertFalse(K.compatible("nightly", "hourly"))
        self.assertFalse(K.compatible("12", "14"))
        self.assertFalse(K.compatible("batch", "not batch"))

    def test_numbers_compare_as_numbers(self):
        self.assertEqual(K.norm_value("1,200"), "1200")
        self.assertTrue(K.compatible(K.norm_value("12.0"), K.norm_value("12")))


class Scan(unittest.TestCase):
    def setUp(self):
        self.kb = tempfile.mkdtemp()
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump(PROFILE))
        write(os.path.join(self.kb, "etl", "jobs.md"), "# Jobs\n\n- CLAIM_LOAD schedule: nightly at 02:00 [E: file:r.txt]\n"
              "- CLAIM_LOAD owner: Etl Team [E: file:r.txt]\n")
        write(os.path.join(self.kb, "context", "ops.md"), "# Ops\n\n| Job | Schedule |\n|---|---|\n| claim load | hourly [E: file:r.txt] |\n")
        write(os.path.join(self.kb, "db", "claims.md"), "# Claims\n\n- CLAIM_HDR has 12 columns. [E: file:r.txt]\n")
        write(os.path.join(self.kb, "db", "other.md"), "# Other\n\n- CLAIM_HDR has 14 columns. [E: file:r.txt]\n"
              "- CLAIM_LOAD owner: Etl Team [E: file:r.txt]\n")
        write(os.path.join(self.kb, "_EVIDENCE", "files", "r.txt"), "x\n")

    def tearDown(self):
        shutil.rmtree(self.kb, ignore_errors=True)

    def test_flags_different_schedule_and_count_but_not_same_owner(self):
        rep = K.build(self.kb)
        got = {(K.norm_subject(e["subject"]), e["attribute"]) for e in rep["contradictions"]}
        self.assertEqual(got, {("claim load", "schedule"), ("claim hdr", "count of column")})
        sched = [e for e in rep["contradictions"] if e["attribute"] == "schedule"][0]
        self.assertEqual(sched["confidence"], "high")
        self.assertEqual({sched["a"]["page"], sched["b"]["page"]}, {"etl/jobs.md", "context/ops.md"})
        self.assertEqual(sched["status"], "open")

    def test_same_page_is_not_a_cross_page_pair(self):
        write(os.path.join(self.kb, "etl", "jobs.md"), "# Jobs\n\n- CLAIM_LOAD schedule: nightly\n- CLAIM_LOAD schedule: hourly\n")
        rep = K.build(self.kb)
        self.assertFalse([e for e in rep["contradictions"] if e["attribute"] == "schedule" and e["a"]["page"] == e["b"]["page"]])

    def test_generated_pages_and_other_folders_are_not_read(self):
        write(os.path.join(self.kb, "db", "gen.md"), "# Generated by gen_x.py\n\n- CLAIM_HDR has 99 columns.\n")
        write(os.path.join(self.kb, "_EVIDENCE", "x.md"), "- CLAIM_HDR has 77 columns.\n")
        text = yaml.safe_dump(K.build(self.kb))
        self.assertNotIn("99", text)
        self.assertNotIn("77", text)

    def test_report_is_written_and_passes_the_source_check(self):
        rep = K.build(self.kb)
        path = K.write_report(self.kb, rep)
        self.assertTrue(path.replace("\\", "/").endswith("CROSS-LAYER/CONTRADICTIONS.yaml"))
        res = verify_kb.Checker(self.kb).run()
        self.assertEqual([p for p in res["problems"] if p["file"].endswith("CONTRADICTIONS.yaml")], [])
        self.assertEqual(len(K.load_report(self.kb)["contradictions"]), rep["pairs"])

    def test_scan_never_edits_pages_or_raises_questions(self):
        before = slurp(os.path.join(self.kb, "db", "claims.md"))
        self.assertEqual(K.main(["scan", self.kb]), 0)
        self.assertEqual(slurp(os.path.join(self.kb, "db", "claims.md")), before)
        self.assertFalse(os.path.exists(questions.reg_path(self.kb)))

    def test_raise_adds_questions_once(self):
        self.assertEqual(K.main(["scan", self.kb, "--raise"]), 2)  # --by is required
        self.assertEqual(K.main(["scan", self.kb, "--raise", "--by", "Ana Lead"]), 0)
        qs = questions.load(questions.reg_path(self.kb))["questions"]
        self.assertEqual(len(qs), 2)
        self.assertTrue(all(q["status"] == "open" for q in qs))
        self.assertIn("disagree", qs[0]["question"])
        self.assertEqual(questions.problems(self.kb, {"questions": qs}), [])
        K.main(["scan", self.kb, "--raise", "--by", "Ana Lead"])
        self.assertEqual(len(questions.load(questions.reg_path(self.kb))["questions"]), 2)

    def test_raise_by_id(self):
        K.write_report(self.kb, K.build(self.kb))
        cid = K.load_report(self.kb)["contradictions"][0]["id"]
        qid, added = K.raise_by_id(self.kb, cid, "Pat Lee")
        self.assertTrue(added)
        self.assertRegex(qid, r"^Q-\d{4}$")
        with self.assertRaises(K.ContradictError):
            K.raise_by_id(self.kb, "C-00000000", "Pat Lee")


class Staged(unittest.TestCase):
    def setUp(self):
        self.kb = tempfile.mkdtemp()
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump(PROFILE))
        write(os.path.join(self.kb, "etl", "jobs.md"), "# Jobs\n\n- CLAIM_LOAD schedule: nightly\n")
        write(os.path.join(self.kb, "db", "a.md"), "# A\n\n- CLAIM_HDR has 12 columns.\n")
        write(os.path.join(self.kb, "db", "b.md"), "# B\n\n- CLAIM_HDR has 14 columns.\n")

    def tearDown(self):
        shutil.rmtree(self.kb, ignore_errors=True)

    def test_batch_is_checked_against_live_and_reports_only_pairs_with_a_staged_side(self):
        kb_gate.stage_text(self.kb, "b1", "context/ops.md", "# Ops\n\n- CLAIM_LOAD schedule: hourly\n")
        rep = K.build(self.kb, "b1")
        self.assertEqual([(K.norm_subject(e["subject"]), e["attribute"]) for e in rep["contradictions"]], [("claim load", "schedule")])
        e = rep["contradictions"][0]
        self.assertEqual(sorted([e["a"]["where"], e["b"]["where"]]), ["live", "staged:b1"])
        self.assertEqual(K.kb_path(e["b"] if e["b"]["where"] != "live" else e["a"]), "_PENDING/b1/context/ops.md")
        path = K.write_report(self.kb, rep, "b1")
        self.assertIn(os.path.join(".metis", "contradict"), path)
        self.assertFalse(os.path.exists(os.path.join(self.kb, "CROSS-LAYER", "CONTRADICTIONS.yaml")))

    def test_staged_page_replaces_the_live_page_of_the_same_path(self):
        kb_gate.stage_text(self.kb, "b2", "db/b.md", "# B\n\n- CLAIM_HDR has 12 columns.\n")
        self.assertEqual(K.build(self.kb, "b2")["contradictions"], [])

    def test_delete_marker_removes_the_live_page(self):
        kb_gate.stage_text(self.kb, "b3", "db/b.md.DELETE", "")
        kb_gate.stage_text(self.kb, "b3", "context/x.md", "# X\n\n- nothing here\n")
        self.assertEqual(K.build(self.kb, "b3")["contradictions"], [])

    def test_missing_batch(self):
        with self.assertRaises(K.ContradictError):
            K.build(self.kb, "nope")


class Judged(unittest.TestCase):
    def setUp(self):
        self.kb = tempfile.mkdtemp()
        write(os.path.join(self.kb, "db", "a.md"), "# A\n\n- CLAIM_HDR has 12 columns.\n")
        write(os.path.join(self.kb, "db", "b.md"), "# B\n\n- CLAIM_HDR has 14 columns.\n")

    def tearDown(self):
        shutil.rmtree(self.kb, ignore_errors=True)

    def test_prompt_lists_pairs_and_asks_for_answers_file(self):
        path, n = K.write_prompt(self.kb, K.build(self.kb))
        text = slurp(path)
        self.assertEqual(n, 1)
        self.assertIn("db/a.md line 3", text)
        self.assertIn("ANSWERS.yaml", text)
        self.assertIn("Do not decide which line is right", text)

    def test_judged_answers_are_merged_and_compatible_is_dismissed(self):
        cid = K.build(self.kb)["contradictions"][0]["id"]
        write(os.path.join(self.kb, ".metis", "contradict", "ANSWERS.yaml"),
              yaml.safe_dump({"judgements": [{"id": cid, "verdict": "compatible", "reason": "one counts views", "judged_by": "Devin"}]}))
        rep = K.build(self.kb)
        e = rep["contradictions"][0]
        self.assertEqual((e["status"], e["judgement"]["verdict"]), ("dismissed", "compatible"))
        self.assertEqual(K.write_prompt(self.kb, rep)[1], 0)
        self.assertEqual(K.raise_open(self.kb, rep, "Ana Lead"), [])

    def test_bad_answers_are_refused(self):
        p = os.path.join(self.kb, "ans.yaml")
        write(p, yaml.safe_dump({"judgements": [{"id": "C-1", "verdict": "maybe", "reason": "x"}]}))
        with self.assertRaises(K.ContradictError):
            K.load_judged(self.kb, p)
        write(p, yaml.safe_dump({"judgements": [{"id": "C-1", "verdict": "unclear", "reason": ""}]}))
        with self.assertRaises(K.ContradictError):
            K.load_judged(self.kb, p)

    def test_cli_judged_copies_file_and_updates_report(self):
        cid = K.build(self.kb)["contradictions"][0]["id"]
        p = os.path.join(self.kb, "ans.yaml")
        write(p, yaml.safe_dump({"judgements": [{"id": cid, "verdict": "contradiction", "reason": "12 against 14"}]}))
        self.assertEqual(K.main(["judged", self.kb, p]), 0)
        self.assertEqual(K.load_report(self.kb)["contradictions"][0]["status"], "confirmed")


if __name__ == "__main__":
    unittest.main()
