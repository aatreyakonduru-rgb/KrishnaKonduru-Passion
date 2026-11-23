import os
import shutil
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import kb_gate  # noqa: E402
import page_suggest as P  # noqa: E402
import questions  # noqa: E402

PROFILE = {"owners": {"kb_owner": "Ana Lead"},
           "gate": {"teams": [{"name": "Dev", "owns": ["context/dev/*"], "approvers": ["Raj Dev"]}]}}
PAGE = "context/orders.md"
LINE_TEXT = '- Claims are paid within 30 days. [E: kb:context/policy.md "paid within 30 days"]'
EVIDENCE = '[E: kb:context/policy.md "paid within 45 days"]'


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def rmtree(path):
    def onerror(func, p, _):
        os.chmod(p, 0o700)
        func(p)
    shutil.rmtree(path, onerror=onerror)


class PageSuggest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.kb = os.path.join(self.d, "kb")
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump(PROFILE))
        write(os.path.join(self.kb, PAGE), "# Orders\n\n" + LINE_TEXT + "\n- Orders ship in 2 days. [E: kb:context/policy.md]\n")
        write(os.path.join(self.kb, "context", "dev", "api.md"), "# API\n\n- The API is v2. [E: kb:context/policy.md]\n")
        write(os.path.join(self.kb, "context", "policy.md"), "# Policy\n\n- Claims are paid within 30 days; later paid within 45 days. [E: file:policy.txt]\n")
        write(os.path.join(self.kb, "_EVIDENCE", "files", "policy.txt"), "Policy: claims are paid within 30 days; later paid within 45 days.\n")

    def tearDown(self):
        rmtree(self.d)

    def sug(self, **over):
        a = dict(page=PAGE, by="Pat Lee", wrong="It is 45 days now.", proposed="Claims are paid within 45 days.",
                 evidence=EVIDENCE, line=3)
        a.update(over)
        return P.suggest(self.kb, **a)

    # ---- validation
    def test_stored_in_register(self):
        s = self.sug()
        self.assertEqual((s["id"], s["status"], s["page"], s["by"], s["line"]), ("S-0001", "open", PAGE, "Pat Lee", 3))
        self.assertEqual(s["line_text"], LINE_TEXT)
        reg = yaml.safe_load(read(os.path.join(self.kb, "_FEEDBACK", "suggestions.yaml")))
        self.assertEqual(reg["suggestions"][0]["evidence"], ['kb:context/policy.md "paid within 45 days"'])
        self.assertEqual(self.sug(proposed="Another text.")["id"], "S-0002")

    def test_name_required(self):
        for who in ("", "  ", "<name>"):
            with self.assertRaises(P.SuggestError):
                self.sug(by=who)

    def test_page_must_exist_and_be_a_page(self):
        for page in ("", "context/none.md", "../x.md", "_FEEDBACK/suggestions.yaml", ".metis/kb-profile.yaml", "context/policy.txt"):
            with self.assertRaises(P.SuggestError, msg=page):
                self.sug(page=page)

    def test_wrong_and_proposed_required(self):
        with self.assertRaises(P.SuggestError):
            self.sug(wrong="")
        with self.assertRaises(P.SuggestError):
            self.sug(proposed=" ")

    def test_exactly_one_source(self):
        with self.assertRaises(P.SuggestError):
            self.sug(evidence=None, look=None)
        with self.assertRaises(P.SuggestError):
            self.sug(evidence=EVIDENCE, look="the policy page")
        s = self.sug(evidence=None, look="the policy page")
        self.assertEqual(s["look"], "the policy page")
        self.assertNotIn("evidence", s)

    def test_bad_evidence_is_refused(self):
        for ev in ('[E: kb:context/missing.md]', '[E: kb:context/policy.md "not in the file"]', "[E: nonsense]", "[?: Q-0001]"):
            with self.assertRaises(P.SuggestError, msg=ev):
                self.sug(evidence=ev)

    def test_bare_evidence_without_brackets_is_accepted(self):
        s = self.sug(evidence='kb:context/policy.md "paid within 45 days"')
        self.assertEqual(s["evidence"], ['kb:context/policy.md "paid within 45 days"'])

    def test_secret_text_is_refused(self):
        with self.assertRaises(P.SuggestError):
            self.sug(proposed="Use key AKIAIOSFODNN7EXAMPLE for it.")

    def test_long_text_is_refused(self):
        with self.assertRaises(P.SuggestError):
            self.sug(wrong="x" * 3000)

    def test_line_must_exist(self):
        with self.assertRaises(P.SuggestError):
            self.sug(line=99)
        with self.assertRaises(P.SuggestError):
            self.sug(line="abc")

    def test_duplicate_open_suggestion_is_refused(self):
        self.sug()
        with self.assertRaises(P.SuggestError):
            self.sug()
        self.sug(by="Sam Roe")

    # ---- approve
    def test_approve_as_question(self):
        self.sug()
        s = P.approve(self.kb, "S-0001", "Ana Lead", "question", note="good catch")
        self.assertEqual((s["status"], s["action"], s["decided_by"], s["note"]), ("approved", "question", "Ana Lead", "good catch"))
        qs = questions.load(questions.reg_path(self.kb))["questions"]
        self.assertEqual([q["id"] for q in qs], [s["question_id"]])
        self.assertIn("Pat Lee", qs[0]["question"])
        self.assertEqual(qs[0]["blocks"], [PAGE])
        self.assertTrue(all("[E:" in c for c in qs[0]["context"]))
        self.assertEqual(read(os.path.join(self.kb, PAGE)).count("45"), 0)

    def test_approve_twice_is_refused(self):
        self.sug()
        P.approve(self.kb, "S-0001", "Ana Lead", "question")
        with self.assertRaises(P.SuggestError):
            P.approve(self.kb, "S-0001", "Ana Lead", "question")

    def test_approve_as_stage_writes_pending_only(self):
        self.sug()
        before = read(os.path.join(self.kb, PAGE))
        kb_gate.lock(self.kb, "Ana Lead")
        s = P.approve(self.kb, "S-0001", "Ana Lead", "stage")
        self.assertEqual(s["action"], "stage")
        self.assertEqual(read(os.path.join(self.kb, PAGE)), before)
        self.assertEqual(kb_gate.pending_files(self.kb, s["batch"]), [PAGE])
        self.assertTrue(os.path.isfile(os.path.join(kb_gate.pending_dir(self.kb, s["batch"]), "DIGEST.md")))
        staged = read(os.path.join(kb_gate.pending_dir(self.kb, s["batch"]), PAGE)).splitlines()
        self.assertEqual(staged[2], "- Claims are paid within 45 days. " + EVIDENCE)
        self.assertEqual(staged[3], "- Orders ship in 2 days. [E: kb:context/policy.md]")
        kb_gate.certify(self.kb, s["batch"], "Ana Lead")
        self.assertIn("45 days", read(os.path.join(self.kb, PAGE)))

    def test_stage_keeps_annotation_groups(self):
        write(os.path.join(self.kb, PAGE), "# Orders\n\n" + LINE_TEXT + " {valid-from: 2026-01-01}\n")
        self.sug()
        kb_gate.lock(self.kb, "Ana Lead")
        s = P.approve(self.kb, "S-0001", "Ana Lead", "stage")
        staged = read(os.path.join(kb_gate.pending_dir(self.kb, s["batch"]), PAGE)).splitlines()
        self.assertEqual(staged[2], "- Claims are paid within 45 days. " + EVIDENCE + " {valid-from: 2026-01-01}")

    def test_stage_needs_locked_kb(self):
        self.sug()
        with self.assertRaises(P.SuggestError):
            P.approve(self.kb, "S-0001", "Ana Lead", "stage")
        self.assertEqual(P.suggestions(self.kb, "open")[0]["id"], "S-0001")

    def test_stage_refused_when_line_changed(self):
        self.sug()
        kb_gate.lock(self.kb, "Ana Lead")
        write(os.path.join(self.kb, PAGE), read(os.path.join(self.kb, PAGE)).replace("30 days. [E", "31 days. [E"))
        with self.assertRaises(P.SuggestError):
            P.approve(self.kb, "S-0001", "Ana Lead", "stage")
        self.assertFalse(os.path.isdir(kb_gate.pending_dir(self.kb)) and kb_gate.batches(self.kb))

    def test_stage_refused_for_look_only_or_no_line(self):
        kb_gate.lock(self.kb, "Ana Lead")
        self.sug(evidence=None, look="the policy page")
        with self.assertRaises(P.SuggestError):
            P.approve(self.kb, "S-0001", "Ana Lead", "stage")
        self.sug(line=None, proposed="No line given.")
        with self.assertRaises(P.SuggestError):
            P.approve(self.kb, "S-0002", "Ana Lead", "stage")
        P.approve(self.kb, "S-0001", "Ana Lead", "question")

    def test_stage_refused_for_heading_line(self):
        self.sug(line=1)
        kb_gate.lock(self.kb, "Ana Lead")
        with self.assertRaises(P.SuggestError):
            P.approve(self.kb, "S-0001", "Ana Lead", "stage")

    # ---- decline and who decides
    def test_decline_needs_reason(self):
        self.sug()
        with self.assertRaises(P.SuggestError):
            P.decline(self.kb, "S-0001", "Ana Lead", " ")
        s = P.decline(self.kb, "S-0001", "Ana Lead", "The 30 days rule still applies.")
        self.assertEqual((s["status"], s["note"], s["decided_by"]), ("declined", "The 30 days rule still applies.", "Ana Lead"))
        with self.assertRaises(P.SuggestError):
            P.decline(self.kb, "S-0001", "Ana Lead", "again")

    def test_non_lead_cannot_decide(self):
        self.sug()
        for fn in (lambda: P.approve(self.kb, "S-0001", "Pat Lee", "question"), lambda: P.decline(self.kb, "S-0001", "Pat Lee", "no")):
            with self.assertRaises(kb_gate.GateError):
                fn()
        self.assertEqual(P.suggestions(self.kb, "open")[0]["id"], "S-0001")

    def test_team_approver_only_on_own_pages(self):
        self.sug()
        self.sug(page="context/dev/api.md", proposed="The API is v3.", line=3)
        with self.assertRaises(kb_gate.GateError):
            P.decline(self.kb, "S-0001", "Raj Dev", "not mine")
        self.assertEqual(P.decline(self.kb, "S-0002", "Raj Dev", "still v2")["decided_by"], "Raj Dev")

    def test_inbox_lists_what_a_person_may_decide(self):
        self.sug()
        self.sug(page="context/dev/api.md", proposed="The API is v3.", line=3)
        P.comment(self.kb, PAGE, "Pat Lee", "Is this current?")
        P.comment(self.kb, "context/dev/api.md", "Pat Lee", "Which version?")
        sug, com = P.inbox(self.kb, "Ana Lead")
        self.assertEqual((len(sug), len(com)), (2, 2))
        sug, com = P.inbox(self.kb, "Raj Dev")
        self.assertEqual(([s["page"] for s in sug], [c["page"] for c in com]), (["context/dev/api.md"], ["context/dev/api.md"]))
        self.assertEqual(P.inbox(self.kb, "Pat Lee"), ([], []))

    def test_no_lead_named_refuses_decisions(self):
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump({}))
        self.sug()
        with self.assertRaises(kb_gate.GateError):
            P.decline(self.kb, "S-0001", "Ana Lead", "x")

    # ---- comments
    def test_comment_thread_is_append_only(self):
        c1 = P.comment(self.kb, PAGE, "Pat Lee", "Is the 30 days from the claim date?")
        c2 = P.comment(self.kb, PAGE, "Sam Roe", "Also wondering.", reply_to=c1["id"])
        self.assertEqual((c1["id"], c1["status"], c2["reply_to"]), ("C-0001", "open", "C-0001"))
        self.assertNotIn("status", c2)
        ids = [c["id"] for c in P.thread(self.kb, PAGE)]
        self.assertEqual(ids, ["C-0001", "C-0002"])
        P.comment(self.kb, "context/dev/api.md", "Pat Lee", "Other page.")
        self.assertEqual(len(P.thread(self.kb, PAGE)), 2)
        self.assertEqual(P.thread(self.kb, PAGE)[0]["text"], "Is the 30 days from the claim date?")

    def test_comment_validation(self):
        with self.assertRaises(P.SuggestError):
            P.comment(self.kb, PAGE, "", "text")
        with self.assertRaises(P.SuggestError):
            P.comment(self.kb, PAGE, "Pat Lee", " ")
        with self.assertRaises(P.SuggestError):
            P.comment(self.kb, PAGE, "Pat Lee", "hi", reply_to="C-0042")
        c = P.comment(self.kb, PAGE, "Pat Lee", "hi")
        with self.assertRaises(P.SuggestError):
            P.comment(self.kb, "context/dev/api.md", "Pat Lee", "wrong page", reply_to=c["id"])

    def test_answer_marks_comment_answered(self):
        c = P.comment(self.kb, PAGE, "Pat Lee", "Is it calendar days?")
        with self.assertRaises(kb_gate.GateError):
            P.answer(self.kb, c["id"], "Pat Lee", "yes")
        with self.assertRaises(P.SuggestError):
            P.answer(self.kb, c["id"], "Ana Lead", " ")
        r = P.answer(self.kb, c["id"], "Ana Lead", "Calendar days.")
        self.assertEqual((r["kind"], r["reply_to"], r["by"]), ("answer", c["id"], "Ana Lead"))
        th = P.thread(self.kb, PAGE)
        self.assertEqual([c["id"] for c in th], ["C-0001", "C-0002"])
        self.assertEqual(th[0]["status"], "answered")
        self.assertEqual(th[0]["text"], "Is it calendar days?")
        self.assertEqual(P.inbox(self.kb, "Ana Lead")[1], [])

    def test_pages_lists_only_kb_pages(self):
        write(os.path.join(self.kb, "_FEEDBACK", "answers", "F-0001.md"), "x\n")
        write(os.path.join(self.kb, "_PENDING", "b", "x.md"), "x\n")
        got = P.pages(self.kb)
        self.assertIn(PAGE, got)
        self.assertIn("context/dev/api.md", got)
        self.assertFalse([p for p in got if p.startswith(("_", "."))])

    def test_live_pages_never_change(self):
        snap = {p: read(os.path.join(self.kb, p)) for p in P.pages(self.kb)}
        self.sug()
        P.comment(self.kb, PAGE, "Pat Lee", "hi")
        P.approve(self.kb, "S-0001", "Ana Lead", "question")
        self.sug(proposed="Other.")
        P.decline(self.kb, "S-0002", "Ana Lead", "no")
        self.assertEqual(snap, {p: read(os.path.join(self.kb, p)) for p in P.pages(self.kb)})

    # ---- CLI
    def cli(self, *args):
        out, err = [], []
        old = sys.stdout, sys.stderr
        import io
        sys.stdout, sys.stderr = io.StringIO(), io.StringIO()
        try:
            rc = P.main(list(args))
            return rc, sys.stdout.getvalue(), sys.stderr.getvalue()
        finally:
            sys.stdout, sys.stderr = old

    def test_cli_round_trip(self):
        rc, out, _ = self.cli("suggest", self.kb, "--page", PAGE, "--by", "Pat Lee", "--wrong", "old", "--proposed", "Claims are paid within 45 days.",
                              "--evidence", EVIDENCE, "--line", "3")
        self.assertEqual((rc, out.strip()), (0, "S-0001 recorded on " + PAGE))
        rc, out, _ = self.cli("comment", self.kb, "--page", PAGE, "--by", "Pat Lee", "--text", "hello")
        self.assertEqual(rc, 0)
        self.assertIn("C-0001", self.cli("thread", self.kb, "--page", PAGE)[1])
        self.assertIn("S-0001", self.cli("list", self.kb, "--status", "open")[1])
        self.assertIn("S-0001", self.cli("inbox", self.kb, "--by", "Ana Lead")[1])
        rc, out, _ = self.cli("approve", self.kb, "S-0001", "--by", "Ana Lead", "--question")
        self.assertEqual(rc, 0)
        self.assertIn("raised in VALIDATE_KB", out)
        self.assertEqual(self.cli("answer", self.kb, "C-0001", "--by", "Ana Lead", "--text", "hi")[0], 0)

    def test_cli_errors_exit_2(self):
        rc, _, err = self.cli("suggest", self.kb, "--page", PAGE, "--by", "Pat Lee", "--wrong", "a", "--proposed", "b")
        self.assertEqual(rc, 2)
        self.assertIn("exactly one", err)
        rc, _, err = self.cli("decline", self.kb, "S-0001", "--by", "Pat Lee", "--reason", "no")
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
