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

import kb_gate  # noqa: E402
import page_suggest  # noqa: E402
import screens_suggest as S  # noqa: E402
import ui_common as C  # noqa: E402

PAGE = "context/orders.md"
EVIDENCE = '[E: kb:context/policy.md "paid within 45 days"]'
PROFILE = {"owners": {"kb_owner": "Ana Lead"}, "gate": {"teams": [{"name": "Dev", "owns": ["context/dev/*"], "approvers": ["Raj Dev"]}]}}


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class SuggestUiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.kb = os.path.join(self.tmp, "KB")
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump(PROFILE))
        write(os.path.join(self.kb, PAGE), "# Orders\n\n- Claims are paid within 30 days. [E: kb:context/policy.md]\n")
        write(os.path.join(self.kb, "context", "dev", "api.md"), "# API\n\n- The API is v2. [E: kb:context/policy.md]\n")
        write(os.path.join(self.kb, "context", "policy.md"), "# Policy\n\n- Claims are paid within 30 days; later paid within 45 days. [E: file:p.txt]\n")
        write(os.path.join(self.kb, "_EVIDENCE", "files", "p.txt"), "Claims are paid within 30 days; later paid within 45 days.\n")
        self.lead = C.Ctx(self.kb, "tok", "Ana Lead")
        self.pat = C.Ctx(self.kb, "tok", "Pat Lee")
        self.anon = C.Ctx(self.kb, "tok", "")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def submit(self, ctx=None, **over):
        f = {"page": PAGE, "wrong": "It is 45 days now.", "proposed": "Claims are paid within 45 days.", "evidence": EVIDENCE, "line": "3"}
        f.update(over)
        return S.act_submit(ctx or self.pat, f)

    def test_module_contract(self):
        self.assertIn("/suggest", S.SCREENS)
        self.assertEqual(S.NAV, [("/suggest", "Suggest an edit")])
        self.assertEqual(set(S.ACTIONS), {"/suggest/submit", "/suggest/comment", "/suggest/approve", "/suggest/decline", "/suggest/answer"})
        self.assertTrue(all(v[0] == "/suggest" for v in S.ACTIONS.values()))

    def test_picker_lists_pages_and_no_internal_folders(self):
        write(os.path.join(self.kb, "_FEEDBACK", "answers", "F-0001.md"), "x\n")
        html = S.suggest_view(self.pat, {})
        self.assertIn("Pick a page on the left", html)
        self.assertIn("/suggest?page=context%2Forders.md", html)
        self.assertNotIn("_FEEDBACK/answers", html)
        self.assertNotIn("Inbox", html)

    def test_page_query_preselects_the_page(self):
        html = S.suggest_view(self.pat, {"page": PAGE})
        self.assertIn("<h2>context/orders.md</h2>", html)
        self.assertIn('name="page" value="context/orders.md"', html)
        self.assertIn("/suggest/submit", html)
        self.assertIn("/suggest/comment", html)
        self.assertNotIn("Pick a page on the left", html)

    def test_bad_page_query_shows_an_error_not_a_form(self):
        html = S.suggest_view(self.pat, {"page": "../secret.md"})
        self.assertIn("not a KB page", html)
        self.assertIn("Pick a page on the left", html)

    def test_submit_stores_with_session_name(self):
        where, msg = self.submit()
        self.assertEqual(where, "/suggest?page=context%2Forders.md")
        self.assertIn("S-0001", msg)
        s = page_suggest.load(self.kb)["suggestions"][0]
        self.assertEqual((s["by"], s["page"], s["line"], s["status"]), ("Pat Lee", PAGE, 3, "open"))
        self.assertIn("It is 45 days now.", S.suggest_view(self.pat, {"page": PAGE}))

    def test_submit_needs_name_and_valid_source(self):
        with self.assertRaises(C.UiError):
            self.submit(ctx=self.anon)
        with self.assertRaises(C.UiError):
            self.submit(evidence="", look="")
        with self.assertRaises(C.UiError):
            self.submit(evidence=EVIDENCE, look="somewhere")
        with self.assertRaises(C.UiError):
            self.submit(evidence='[E: kb:context/policy.md "not there"]')
        with self.assertRaises(C.UiError):
            self.submit(page="nothing.md")
        self.assertEqual(page_suggest.load(self.kb)["suggestions"], [])

    def test_look_hint_is_accepted_without_line(self):
        self.submit(evidence="", look="the policy page", line="")
        s = page_suggest.load(self.kb)["suggestions"][0]
        self.assertEqual(s["look"], "the policy page")
        self.assertNotIn("line", s)

    def test_comment_and_reply_thread(self):
        S.act_comment(self.pat, {"page": PAGE, "text": "Is this still right?"})
        S.act_comment(self.pat, {"page": PAGE, "text": "Asking again.", "reply_to": "C-0001"})
        html = S.suggest_view(self.pat, {"page": PAGE})
        self.assertIn("Is this still right?", html)
        self.assertIn("reply to C-0001", html)
        with self.assertRaises(C.UiError):
            S.act_comment(self.anon, {"page": PAGE, "text": "x"})
        with self.assertRaises(C.UiError):
            S.act_comment(self.pat, {"page": PAGE, "text": " "})

    def test_inbox_only_for_leads(self):
        self.submit()
        self.assertNotIn("Inbox", S.suggest_view(self.pat, {}))
        self.assertNotIn("/suggest/approve", S.suggest_view(self.pat, {"page": PAGE}))
        lead = S.suggest_view(self.lead, {})
        self.assertIn("Inbox (1 suggestion", lead)
        self.assertIn("/suggest/approve", lead)
        self.assertIn("/suggest/decline", lead)

    def test_team_approver_sees_only_own_pages(self):
        self.submit()
        self.submit(page="context/dev/api.md", proposed="The API is v3.")
        raj = C.Ctx(self.kb, "tok", "Raj Dev")
        html = S.suggest_view(raj, {})
        self.assertIn("Inbox (1 suggestion", html)
        self.assertIn("context/dev/api.md", html)

    def test_approve_as_question_through_ui(self):
        self.submit()
        where, msg = S.act_approve(self.lead, {"id": "S-0001", "how": "question", "note": "thanks"})
        self.assertIn("raised in VALIDATE_KB", msg)
        s = page_suggest.load(self.kb)["suggestions"][0]
        self.assertEqual((s["status"], s["action"]), ("approved", "question"))
        self.assertIn("approved", S.suggest_view(self.lead, {"page": PAGE}))
        self.assertIn("Nothing is waiting", S.suggest_view(self.lead, {}))

    def test_approve_as_stage_through_ui_leaves_live_page(self):
        self.submit()
        before = read(os.path.join(self.kb, PAGE))
        kb_gate.lock(self.kb, "Ana Lead")
        where, msg = S.act_approve(self.lead, {"id": "S-0001", "how": "stage"})
        self.assertIn("_PENDING", msg)
        self.assertEqual(read(os.path.join(self.kb, PAGE)), before)
        self.assertTrue(kb_gate.batches(self.kb))

    def test_stage_error_is_a_ui_error(self):
        self.submit()
        with self.assertRaises(C.UiError):
            S.act_approve(self.lead, {"id": "S-0001", "how": "stage"})

    def test_non_lead_cannot_approve_or_decline_or_answer(self):
        self.submit()
        S.act_comment(self.pat, {"page": PAGE, "text": "hello"})
        with self.assertRaises(C.UiError):
            S.act_approve(self.pat, {"id": "S-0001", "how": "question"})
        with self.assertRaises(C.UiError):
            S.act_decline(self.pat, {"id": "S-0001", "reason": "no"})
        with self.assertRaises(C.UiError):
            S.act_answer(self.pat, {"id": "C-0001", "text": "yes"})
        with self.assertRaises(C.UiError):
            S.act_decline(self.anon, {"id": "S-0001", "reason": "no"})

    def test_decline_needs_reason_and_shows_it(self):
        self.submit()
        with self.assertRaises(C.UiError):
            S.act_decline(self.lead, {"id": "S-0001", "reason": ""})
        S.act_decline(self.lead, {"id": "S-0001", "reason": "Policy says 30 days."})
        html = S.suggest_view(self.pat, {"page": PAGE})
        self.assertIn("Declined by Ana Lead: Policy says 30 days.", html)

    def test_answer_comment_through_ui(self):
        S.act_comment(self.pat, {"page": PAGE, "text": "Calendar days?"})
        html = S.suggest_view(self.lead, {"page": PAGE})
        self.assertIn("/suggest/answer", html)
        where, msg = S.act_answer(self.lead, {"id": "C-0001", "text": "Yes, calendar days."})
        self.assertIn("C-0001", msg)
        html = S.suggest_view(self.pat, {"page": PAGE})
        self.assertIn("Yes, calendar days.", html)
        self.assertIn("answered", html)
        self.assertNotIn("/suggest/answer", S.suggest_view(self.lead, {"page": PAGE}))

    def test_user_text_is_escaped(self):
        self.submit(wrong="<script>alert(1)</script>", proposed="<b>bold</b> within 45 days")
        S.act_comment(self.pat, {"page": PAGE, "text": "<img src=x onerror=alert(2)>"})
        html = S.suggest_view(self.lead, {"page": PAGE, "find": '"><script>x</script>'})
        for bad in ("<script>alert(1)", "<b>bold</b>", "<img src=x", '"><script>x'):
            self.assertNotIn(bad, html)
        self.assertIn("&lt;script&gt;alert(1)", html)

    def test_forms_carry_the_token_and_no_script(self):
        html = S.suggest_view(self.lead, {"page": PAGE})
        self.assertIn('name="_t" value="tok"', html)
        self.assertNotIn("<script", html.split("</head>")[-1])

    def test_unnamed_session_sees_a_prompt(self):
        self.assertIn("Say who you are", S.suggest_view(self.anon, {"page": PAGE}))

    def test_filter_narrows_the_picker(self):
        html = S.suggest_view(self.pat, {"find": "dev/"})
        self.assertIn("context/dev/api.md", html)
        self.assertNotIn("page=context%2Forders.md", html)


if __name__ == "__main__":
    unittest.main()
