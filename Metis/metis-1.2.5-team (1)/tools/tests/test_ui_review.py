import os
import shutil
import sys
import tempfile
import unittest

import yaml

TOOLS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
UI_DIR = os.path.join(TOOLS_DIR, "ui")
for _p in (TOOLS_DIR, UI_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import kb_gate  # noqa: E402
import review_queue  # noqa: E402
import screens_review as S  # noqa: E402
import ui_common as C  # noqa: E402

PROFILE = {
    "owners": {"kb_owner": "Ana Lead", "app_owner": "Raj Dev"},
    "gate": {"teams": [
        {"name": "Claims Team", "owns": ["claims/*"], "approvers": ["Cleo Claims"]},
        {"name": "Billing <i>Team</i>", "owns": ["billing"], "approvers": ["Bo Billing"]},
    ]},
}
PAGE = "# P\n\n- Pay in 30 days [E: file:rules.txt]\n"
LINKS = ("links:\n- from: {type: table, name: A}\n  rel: reads\n  to: {type: table, name: B}\n"
         "  source: '[E: file:rules.txt \"pay in 30 days\"]'\n")


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def rmtree(path):
    def onerror(func, p, _):
        os.chmod(p, 0o700)
        func(p)
    shutil.rmtree(path, onerror=onerror)


class F(dict):
    def getall(self, k):
        return [self[k]] if k in self else []


def tree(root):
    return {os.path.relpath(os.path.join(d, f), root) for d, _, fs in os.walk(root) for f in fs}


class ReviewScreens(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.kb = os.path.join(self.d, "kb")
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump(PROFILE))
        write(os.path.join(self.kb, "_EVIDENCE", "files", "rules.txt"), "pay in 30 days\n")
        write(os.path.join(self.kb, "context", "a.md"), PAGE)
        kb_gate.lock(self.kb, "Ana Lead")
        self.lead = C.Ctx(self.kb, "tok", "Ana Lead")
        self.pat = C.Ctx(self.kb, "tok", "Pat Analyst")

    def tearDown(self):
        rmtree(self.d)

    def stage(self, files, name="docs"):
        src = os.path.join(self.d, "src-" + name)
        for rel, text in files.items():
            write(os.path.join(src, rel), text)
        batch = kb_gate.new_batch(self.kb, name)
        kb_gate.propose(self.kb, batch, src)
        return batch

    def big(self, n=14, extra=None):
        files = {"claims/p%02d.md" % i: PAGE for i in range(n)}
        files.update(extra or {})
        return self.stage(files)

    def ask_blocking(self, rel):
        write(os.path.join(self.kb, "_QUESTIONS", "VALIDATE_KB.yaml"), yaml.safe_dump({"questions": [
            {"id": "Q-0001", "question": "x?", "priority": "P1", "status": "open", "blocks": [rel]}]}))

    def show(self, q=None, ctx=None):
        return S.review(ctx or self.lead, q or {})

    def sample(self):
        return S.load_state(self.kb, "Claims Team")

    def mark(self, k, do="reviewed", note="", ctx=None):
        batch, _, rel = k.partition("/")
        return S.act_mark(ctx or self.lead, F(team="Claims Team", batch=batch, file=rel, read="1", do=do, note=note))

    def certify(self, **kw):
        return S.act_certify(self.lead, F(team="Claims Team", **kw))

    # ---- module contract
    def test_contract(self):
        self.assertEqual(set(S.SCREENS), {"/review"})
        self.assertEqual(S.NAV, [("/review", "Review queue")])
        for path, (screen, fn) in S.ACTIONS.items():
            self.assertTrue(path.startswith("/review/"))
            self.assertIn(screen, S.SCREENS)

    # ---- the queue and the trust signals
    def test_sections_per_team_risk_ranked_signals_in_words(self):
        self.ask_blocking("claims/b.md")
        self.stage({"claims/a.md": PAGE, "claims/b.md": PAGE + "\n- Gone [E: file:missing.txt]\n", "billing/c.md": PAGE, "context/d.md": PAGE,
                    "claims/x/ai.links.yaml": LINKS})
        html = self.show()
        self.assertLess(html.index("Claims Team"), html.index("Billing &lt;i&gt;Team&lt;/i&gt;"))
        self.assertLess(html.index("Billing &lt;i&gt;Team&lt;/i&gt;"), html.index("(no owning team)"))
        self.assertNotIn("<i>Team</i>", html)
        self.assertLess(html.index("claims/b.md"), html.index("claims/a.md"))  # the file with a source problem ranks first
        for words in ("AI-proposed", "every quote is found in its source", "a source does not resolve", "blocked by open question Q-0001 (P1)",
                      "no open question blocks it", "source problems", "1 of 1 links"):
            self.assertIn(words, html)
        for banned in ("High", "Medium", "Low"):
            self.assertNotIn(banned, html)

    def test_parsed_origin(self):
        self.stage({"claims/y/parsed.links.yaml": LINKS})
        self.assertIn("parsed: a program read it from the source", self.show())

    def test_not_locked_and_empty(self):
        self.assertIn("Nothing waits for review", self.show())
        os.remove(os.path.join(self.kb, ".metis", "certified.yaml"))
        self.assertIn("not locked yet", self.show())

    def test_item_view_escapes_and_shows_diff(self):
        write(os.path.join(self.kb, "claims", "a.md"), PAGE)  # a live copy, so the proposal is a change
        batch = self.stage({"claims/a.md": PAGE + "\n- <script>alert(1)</script> [E: file:rules.txt]\n"})
        html = S.review(self.lead, {"team": "Claims Team", "batch": batch, "file": "claims/a.md"})
        self.assertIn("Changes against the KB copy", html)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        with self.assertRaises(C.UiError):
            S.review(self.lead, {"team": "Claims Team", "batch": batch, "file": "claims/nope.md"})

    # ---- who may act
    def test_only_a_named_lead_acts(self):
        self.stage({"claims/a.md": PAGE})
        for fn, form in ((S.act_plan, F(team="Claims Team")), (S.act_certify, F(team="Claims Team")),
                         (S.act_reject, F(team="Claims Team", reason="no")), (S.act_draw, F(team="Claims Team"))):
            with self.assertRaises(C.UiError) as cm:
                fn(self.pat, form)
            self.assertIn("not a lead", str(cm.exception))
            with self.assertRaises(C.UiError) as cm:
                fn(C.Ctx(self.kb, "tok", ""), form)
            self.assertIn("Say who you are", str(cm.exception))
        with self.assertRaises(C.UiError):  # a team approver is not a lead, so this page refuses them too
            S.act_certify(C.Ctx(self.kb, "tok", "Cleo Claims"), F(team="Claims Team"))
        self.assertEqual(len(kb_gate.pending_files(self.kb, kb_gate.batches(self.kb)[0])), 1)

    # ---- plan
    def test_plan_in_copy_box_says_no_git(self):
        self.stage({"claims/a.md": PAGE})
        where, msg = S.act_plan(self.lead, F(team="Claims Team"))
        self.assertIn("Nothing was sent to git", msg)
        self.assertTrue(os.path.isfile(os.path.join(self.kb, "_PENDING", "_QUEUE", "claims-team.md")))
        self.assertIn("plan=Claims+Team", where)
        html = self.show({"plan": "Claims Team", "date": C.today()})
        self.assertIn("metis/%s-review-claims-team" % C.today(), html)
        self.assertIn("does not run git or open a pull request", html)
        self.assertIn("<textarea readonly", html)
        self.assertIn("claims/a.md", html)

    # ---- certify and reject, small batch
    def test_certify_small_batch_through_the_tool(self):
        self.stage({"claims/a.md": PAGE, "billing/b.md": PAGE})
        where, msg = self.certify()
        self.assertIn("Certified 1 files for Claims Team by Ana Lead", msg)
        self.assertEqual(kb_gate.load_state(self.kb)["files"]["claims/a.md"]["by"], "Ana Lead")
        self.assertEqual([g["team"] for g in review_queue.queue(self.kb)["teams"]], ["Billing <i>Team</i>"])
        with self.assertRaises(C.UiError):
            self.certify()

    def test_certify_refusal_from_the_gate_is_shown(self):
        self.stage({"claims/a.md": "---\ndocuments:\n- {id: d, name: r.docx, given_by: Raj Dev}\n---\n" + PAGE})
        with self.assertRaises(C.UiError) as cm:
            S.act_certify(C.Ctx(self.kb, "tok", "Raj Dev"), F(team="Claims Team"))
        self.assertIn("gave the document", str(cm.exception))

    def test_reject_needs_reason_and_protects_other_teams(self):
        self.stage({"claims/a.md": PAGE, "billing/b.md": PAGE})
        with self.assertRaises(C.UiError):
            S.act_reject(self.lead, F(team="Claims Team", reason=" "))
        with self.assertRaises(C.UiError) as cm:
            S.act_reject(self.lead, F(team="Claims Team", reason="bad"))
        self.assertIn("also hold files for", str(cm.exception))
        self.assertEqual(len(kb_gate.batches(self.kb)), 1)

    def test_reject_a_teams_own_batch(self):
        self.stage({"claims/a.md": PAGE})
        where, msg = S.act_reject(self.lead, F(team="Claims Team", reason="wrong <b>"))
        self.assertIn("Rejected 1 files", msg)
        self.assertEqual(kb_gate.batches(self.kb), [])

    # ---- approve with sampling
    def test_small_batch_has_no_sampling(self):
        self.stage({"claims/p%d.md" % i: PAGE for i in range(10)})
        self.assertNotIn("Approve with sampling", self.show())
        with self.assertRaises(C.UiError) as cm:
            S.act_draw(self.lead, F(team="Claims Team"))
        self.assertIn("Sampling applies above 10", str(cm.exception))

    def test_large_batch_refused_until_sample_drawn_and_reviewed(self):
        self.big()
        html = self.show()
        self.assertIn("Approve with sampling", html)
        self.assertIn("draw the sample first", html)
        with self.assertRaises(C.UiError) as cm:
            self.certify()
        self.assertIn("draw the sample first", str(cm.exception))
        with self.assertRaises(C.UiError):
            self.mark("x/y")
        S.act_draw(self.lead, F(team="Claims Team"))
        st = self.sample()
        self.assertEqual(len(st["sample"]), 5)  # 20 percent of 14 is 3, so the floor of 5 applies
        with self.assertRaises(C.UiError) as cm:
            self.certify()
        self.assertIn("5 of 5 required items are not marked reviewed", str(cm.exception))
        keys = sorted(st["sample"])
        for k in keys[:-1]:
            self.mark(k)
        with self.assertRaises(C.UiError) as cm:
            self.certify()
        self.assertIn("1 of 5", str(cm.exception))
        self.mark(keys[-1])
        where, msg = self.certify()
        self.assertIn("Certified 14 files", msg)
        self.assertEqual(kb_gate.batches(self.kb), [])

    def test_sample_size_floor_and_share(self):
        self.assertEqual([S.random_share(n) for n in (11, 25, 26, 100)], [5, 5, 6, 20])

    def test_sample_is_reproducible_from_its_seed(self):
        self.big(n=30)
        S.act_draw(self.lead, F(team="Claims Team"))
        st = self.sample()
        self.assertEqual(len(st["sample"]), 6)
        again = S.pick(sorted(st["items"]), st["seed"], 6)
        self.assertEqual(sorted(again), sorted(st["sample"]))
        self.assertEqual(S.pick(sorted(st["items"], reverse=True), st["seed"], 6), again)
        with self.assertRaises(C.UiError) as cm:  # a drawn sample stands; it cannot be redrawn until it suits
            S.act_draw(self.lead, F(team="Claims Team"))
        self.assertIn("already drawn", str(cm.exception))

    def test_open_question_and_ai_proposed_always_in_sample(self):
        self.ask_blocking("claims/p07.md")
        batch = self.big(extra={"claims/x/ai.links.yaml": LINKS, "claims/y/parsed.links.yaml": LINKS})
        S.act_draw(self.lead, F(team="Claims Team"))
        st = self.sample()
        self.assertEqual(st["sample"]["%s/claims/p07.md" % batch], ["blocked by open question Q-0001 (P1)"])
        self.assertEqual(st["sample"]["%s/claims/x/ai.links.yaml" % batch], ["AI-proposed"])
        self.assertEqual(sum(v == ["random draw"] for v in st["sample"].values()), 5)
        html = self.show()
        self.assertIn("must be reviewed", html)
        self.assertIn("not in the sample", html)

    def test_sample_state_written_only_under_metis_review(self):
        self.big()
        before = tree(self.kb)
        S.act_draw(self.lead, F(team="Claims Team"))
        self.mark(sorted(self.sample()["sample"])[0])
        self.assertEqual(tree(self.kb) - before, {os.path.join(".metis", "review", "claims-team.yaml")})
        self.assertTrue(before <= tree(self.kb))

    def test_mark_needs_the_box_and_a_lead(self):
        self.big()
        S.act_draw(self.lead, F(team="Claims Team"))
        k = sorted(self.sample()["sample"])[0]
        batch, _, rel = k.partition("/")
        with self.assertRaises(C.UiError) as cm:
            S.act_mark(self.lead, F(team="Claims Team", batch=batch, file=rel, do="reviewed"))
        self.assertIn("opened and read", str(cm.exception))
        with self.assertRaises(C.UiError):
            self.mark(k, ctx=self.pat)
        self.assertFalse(self.sample().get("reviewed"))
        self.mark(k, note="fine")
        self.assertEqual(self.sample()["reviewed"][k]["by"], "Ana Lead")

    def test_problem_found_means_full_review_and_the_item_is_not_certified(self):
        batch = self.big()
        S.act_draw(self.lead, F(team="Claims Team"))
        keys = sorted(self.sample()["sample"])
        with self.assertRaises(C.UiError):
            self.mark(keys[0], do="problem")  # needs a reason
        self.mark(keys[0], do="problem", note="Claim is <script>wrong</script>")
        html = self.show()
        self.assertIn("A problem was found in 1 item(s)", html)
        self.assertIn("&lt;script&gt;wrong&lt;/script&gt;", html)
        self.assertNotIn("<script>wrong</script>", html)
        for k in keys[1:]:
            self.mark(k)
        with self.assertRaises(C.UiError) as cm:  # the sample is no longer enough: every other item is required
            self.certify()
        self.assertIn("9 of 13 required items are not marked reviewed", str(cm.exception))
        for k in sorted(self.sample()["items"]):
            if k not in self.sample()["rejected"] and k not in self.sample()["reviewed"]:
                self.mark(k)
        with self.assertRaises(C.UiError):
            self.mark(keys[0])  # a rejected item stays rejected
        where, msg = self.certify()
        self.assertIn("Certified 13 files", msg)
        self.assertIn("1 rejected item(s) still wait", msg)
        self.assertEqual(kb_gate.pending_files(self.kb, batch), [keys[0].partition("/")[2]])
        self.assertNotIn(keys[0].partition("/")[2], kb_gate.load_state(self.kb)["files"])

    def test_marks_are_lost_when_the_batch_changes(self):
        batch = self.big()
        S.act_draw(self.lead, F(team="Claims Team"))
        self.mark("%s/claims/p00.md" % batch)
        write(os.path.join(self.kb, "_PENDING", batch, "claims", "p00.md"), PAGE + "\n- more [E: file:rules.txt]\n")
        self.assertIn("the batch changed since the sample was drawn", self.show())
        with self.assertRaises(C.UiError) as cm:
            self.certify()
        self.assertIn("draw a new sample", str(cm.exception))
        S.act_draw(self.lead, F(team="Claims Team"))
        self.assertEqual(len(self.sample()["sample"]), 5)
        self.assertFalse(self.sample()["reviewed"])  # the mark was on the file that changed


if __name__ == "__main__":
    unittest.main()
