import json
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

import feedback  # noqa: E402
import kb_contradict  # noqa: E402
import kb_dupes  # noqa: E402
import kb_links  # noqa: E402
import kb_trend  # noqa: E402
import llm_judge  # noqa: E402
import questions  # noqa: E402
import screens_quality as S  # noqa: E402
import telemetry_lines  # noqa: E402
import ui_common as C  # noqa: E402

BASE = ("The claims intake service receives a claim from the portal, checks the policy number against the policy table, "
        "assigns an adjuster by region and queue depth, and writes the claim header row with status open. "
        "Every night the load job copies new headers to the reporting schema and clears the staging area. ")


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


class QualityUiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.kb = os.path.join(self.tmp, "KB")
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump({"owners": {"kb_owner": "Ana Lead"}}))
        write(os.path.join(self.kb, "_EVIDENCE", "files", "r.txt"), "x\n")
        write(os.path.join(self.kb, "db", "a.md"), "# A\n\n- CLAIM_HDR has 12 columns. [E: file:r.txt]\n\n" + BASE + "\n")
        write(os.path.join(self.kb, "db", "b.md"), "# B\n\n- CLAIM_HDR has 14 columns. [E: file:r.txt]\n\n" + BASE + "\n\n[gone](missing.md)\n")
        self.lead = C.Ctx(self.kb, "tok", "Ana Lead")
        self.pat = C.Ctx(self.kb, "tok", "Pat Lee")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def build_reports(self):
        kb_contradict.write_report(self.kb, kb_contradict.build(self.kb))
        kb_dupes.write_report(self.kb, kb_dupes.build(self.kb))
        kb_links.write_report(self.kb, kb_links.check(self.kb))

    def view(self, tab, ctx=None):
        return S.quality(ctx or self.lead, {"tab": tab})

    def test_module_contract(self):
        self.assertIn("/quality", S.SCREENS)
        self.assertEqual(S.NAV, [("/quality", "Quality")])
        self.assertEqual(S.ACTIONS["/quality/raise"][0], "/quality")
        self.assertEqual([k for k, _ in S.TABS], ["contradictions", "duplicates", "links", "trend", "lines", "judge"])

    def test_every_tab_renders_empty_without_error(self):
        for k, _ in S.TABS:
            html = self.view(k)
            self.assertIn("<h1>Quality</h1>", html)
            self.assertNotIn("could not be read", html, k)
        self.assertIn("Not built yet", self.view("contradictions"))
        self.assertIn("No line is cited in a disliked answer", self.view("lines"))

    def test_unknown_tab_falls_back_to_contradictions(self):
        self.assertIn("Contradictions</h2>", S.quality(self.lead, {"tab": "<script>"}))

    def test_contradictions_tab_shows_pairs_and_raise_button_for_leads_only(self):
        self.build_reports()
        html = self.view("contradictions")
        self.assertIn("count of column", html)
        self.assertIn("db/a.md", html)
        self.assertIn("Raise as question", html)
        self.assertNotIn("Raise as question", self.view("contradictions", self.pat))
        self.assertIn("leads only", self.view("contradictions", self.pat))

    def test_raise_action_adds_one_question_and_is_repeatable(self):
        self.build_reports()
        cid = kb_contradict.load_report(self.kb)["contradictions"][0]["id"]
        where, msg = S.act_raise(self.lead, {"id": cid})
        self.assertEqual(where, "/quality?tab=contradictions")
        self.assertIn("Raised as Q-0001", msg)
        self.assertEqual(len(questions.load(questions.reg_path(self.kb))["questions"]), 1)
        _, msg = S.act_raise(self.lead, {"id": cid})
        self.assertIn("already holds", msg)
        self.assertEqual(len(questions.load(questions.reg_path(self.kb))["questions"]), 1)

    def test_raise_action_refuses_non_leads_nameless_and_unknown(self):
        self.build_reports()
        cid = kb_contradict.load_report(self.kb)["contradictions"][0]["id"]
        with self.assertRaises(C.UiError) as e:
            S.act_raise(self.pat, {"id": cid})
        self.assertIn("not a lead", str(e.exception))
        with self.assertRaises(C.UiError) as e:
            S.act_raise(C.Ctx(self.kb, "tok", ""), {"id": cid})
        self.assertIn("Say who you are first", str(e.exception))
        with self.assertRaises(C.UiError):
            S.act_raise(self.lead, {"id": "C-00000000"})
        self.assertFalse(os.path.exists(questions.reg_path(self.kb)))

    def test_viewing_never_edits_pages_or_writes_questions(self):
        self.build_reports()
        before = {}
        for r in ("db/a.md", "db/b.md"):
            with open(os.path.join(self.kb, r), encoding="utf-8") as fh:
                before[r] = fh.read()
        for k, _ in S.TABS:
            self.view(k)
        for r, t in before.items():
            with open(os.path.join(self.kb, r), encoding="utf-8") as fh:
                self.assertEqual(fh.read(), t)
        self.assertFalse(os.path.exists(questions.reg_path(self.kb)))

    def test_duplicates_and_links_tabs(self):
        self.build_reports()
        d = self.view("duplicates")
        self.assertIn("Pages (1)", d)
        self.assertIn("db/a.md", d)
        self.assertIn("Nothing is merged or deleted", d)
        links = self.view("links")
        self.assertIn("missing-file", links)
        self.assertIn("missing.md", links)

    def test_trend_tab_draws_sparklines(self):
        kb_trend.record(self.kb)
        kb_trend.record(self.kb)
        html = self.view("trend")
        self.assertIn("<svg", html)
        self.assertIn("Problems the source check finds", html)
        self.assertIn("2 builds", html)

    def test_lines_tab_lists_lines_from_disliked_answers(self):
        ans = os.path.join(self.kb, "ans.md")
        write(ans, '# A\n\n- X. [E: kb:db/a.md:3]\n')
        feedback.record(self.kb, ans, "How many columns?", "Pat Lee", "down", why="wrong", redirect="look at the registry")
        html = self.view("lines")
        self.assertIn("db/a.md", html)
        self.assertIn("CLAIM_HDR has 12 columns", html)
        self.assertIn("not as a verdict", html)

    def test_judge_tab_lists_requests_and_verdicts(self):
        fj = llm_judge.FileJudge(self.kb)
        llm_judge.judge_citations(self.kb, "- CLAIM_HDR has 12 columns. [E: file:r.txt]\n", fj, "db/a.md")
        self.assertIn("waiting for a verdict", self.view("judge"))
        req = llm_judge.list_requests(self.kb)[0]
        write(os.path.join(self.kb, ".metis", "judge", "verdicts", req["id"] + ".json"),
              json.dumps({"id": req["id"], "verdict": "partial", "reason": "<b>only</b> part", "judged_by": "Devin"}))
        html = self.view("judge")
        self.assertIn("partly supported by the quoted source text", html)
        self.assertIn("&lt;b&gt;only&lt;/b&gt; part", html)
        self.assertNotIn("<b>only</b>", html)

    def test_escapes_report_text(self):
        write(os.path.join(self.kb, "CROSS-LAYER", "CONTRADICTIONS.yaml"), yaml.safe_dump(
            {"as_of": "x", "scope": "live KB", "pairs": 1, "claims_read": 2, "pages_read": 2, "contradictions": [
                {"id": "C-1", "subject": "<script>alert(1)</script>", "attribute": "type", "confidence": "low", "status": "open",
                 "a": {"page": "a.md", "line": 1, "value": "<i>x</i>", "text": "<b>t</b>"},
                 "b": {"page": "b.md", "line": 2, "value": "y", "text": "u"}}]}))
        html = self.view("contradictions")
        self.assertNotIn("<script>alert(1)", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertNotIn("<i>x</i>", html)

    def test_a_corrupt_report_shows_a_message_not_a_crash(self):
        write(os.path.join(self.kb, "CROSS-LAYER", "CONTRADICTIONS.yaml"), "contradictions: [{id: C-1}]\npairs: 1\n")
        self.assertIn("could not be read", self.view("contradictions"))


if __name__ == "__main__":
    unittest.main()
