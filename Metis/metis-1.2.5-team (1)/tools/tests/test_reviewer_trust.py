import contextlib
import io
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

import yaml

TOOLS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
for _p in (TOOLS, os.path.join(TOOLS, "ui")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import feedback  # noqa: E402
import kb_gate  # noqa: E402
import page_suggest as PS  # noqa: E402
import review_queue  # noqa: E402
import reviewer_stats as RS  # noqa: E402
import screens_owners as OWN  # noqa: E402
import screens_review as REV  # noqa: E402
import screens_suggest as SUG  # noqa: E402
import ui_common as C  # noqa: E402

PROFILE = {"owners": {"kb_owner": "Ana Lead", "app_owner": "Raj Dev"},
           "gate": {"teams": [{"name": "Claims Team", "owns": ["claims/*"], "approvers": ["Cleo Claims"]}]}}
GOOD = '# P\n\n- Pay in 30 days [E: file:rules.txt "pay in 30 days"]\n'
NO_QUOTE = "# P\n\n- Pay in 30 days [E: file:rules.txt]\n"
CLEAN = {"disliked": {}, "stale": set(), "contradicted": set(), "notes": []}


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def rmtree(path):
    def onerror(func, p, _):
        os.chmod(p, 0o700)
        func(p)
    shutil.rmtree(path, onerror=onerror)


def tree(root):
    return {(os.path.relpath(os.path.join(d, f), root), kb_gate.sha_file(os.path.join(d, f))) for d, _, fs in os.walk(root) for f in fs}


class F(dict):
    def getall(self, k):
        return [self[k]] if k in self else []


class Base(unittest.TestCase):
    trust = None  # the review.trust profile block, or None for absent

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.kb = os.path.join(self.d, "kb")
        prof = dict(PROFILE)
        if self.trust is not None:
            prof["review"] = {"trust": self.trust}
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump(prof))
        write(os.path.join(self.kb, "_EVIDENCE", "files", "rules.txt"), "pay in 30 days\n")
        write(os.path.join(self.kb, "context", "a.md"), GOOD)

    def tearDown(self):
        rmtree(self.d)

    def profile(self):
        with open(os.path.join(self.kb, ".metis", "kb-profile.yaml"), encoding="utf-8") as fh:
            return yaml.safe_load(fh)

    def certs(self, who, n, area="claims", role="kb owner", start=0):
        for i in range(start, start + n):
            kb_gate.log(self.kb, "certify", who, role, "b1", "%s/x%02d.md" % (area, i))

    def stage(self, files, name="docs"):
        src = os.path.join(self.d, "src-" + name)
        for rel, text in files.items():
            write(os.path.join(src, rel), text)
        batch = kb_gate.new_batch(self.kb, name)
        kb_gate.propose(self.kb, batch, src)
        return batch

    def row(self, table, who, area):
        return next(r for r in table["rows"] if r["reviewer"] == who and r["area"] == area)


class WilsonAndPolicy(Base):
    def test_wilson_known_values(self):
        self.assertEqual(RS.wilson(0, 0), (None, None))
        low, high = RS.wilson(0, 10)
        self.assertEqual(low, 0.0)
        self.assertAlmostEqual(high, 0.2775, places=3)
        low, high = RS.wilson(5, 10)
        self.assertAlmostEqual(low, 0.2366, places=3)
        self.assertAlmostEqual(high, 0.7634, places=3)

    def test_policy_absent_means_defaults_and_advisory_only(self):
        pol = RS.policy(self.kb)
        self.assertFalse(pol["active"])
        self.assertEqual((pol["min_decisions"], pol["lookback_days"], pol["floor_files"], pol["floor_share"]), (20, 365, 3, 0.10))
        self.assertIsNone(pol["sample_share"])


class PolicyKeys(Base):
    trust = {"min_decisions": 5, "max_problem_rate": 0.2, "lookback_days": "bad", "sample_share": 3}

    def test_policy_present_overrides_and_bad_values_fall_back_with_a_note(self):
        pol = RS.policy(self.kb)
        self.assertTrue(pol["active"])
        self.assertEqual((pol["min_decisions"], pol["max_problem_rate"]), (5, 0.2))
        self.assertEqual(pol["lookback_days"], 365)
        self.assertIsNone(pol["sample_share"])
        self.assertEqual(len(pol["notes"]), 2)
        self.assertTrue(any("lookback_days" in n for n in RS.trust_table(self.kb, signals=CLEAN)["notes"]))


class TrustTable(Base):
    def test_not_enough_history_below_the_default_minimum(self):
        self.certs("Ana Lead", 19)
        r = self.row(RS.trust_table(self.kb, signals=CLEAN), "Ana Lead", "Claims Team")
        self.assertIsNone(r["weight"])
        self.assertEqual(r["status"], "not enough history")
        self.assertEqual((r["decisions"], r["min_decisions"]), (19, 20))
        self.assertIn("minimum is 20", r["explain"])
        self.assertFalse(r["eligible"])

    def test_weight_is_one_minus_wilson_upper_and_counts_are_shown_without_policy(self):
        self.certs("Ana Lead", 20)
        t = RS.trust_table(self.kb, signals=CLEAN)
        r = self.row(t, "Ana Lead", "Claims Team")
        low, high = RS.wilson(0, 20)
        self.assertEqual(r["weight"], round(1 - high, 3))
        self.assertEqual((r["pages_held"], r["problem_pages"], r["certifications"]), (20, 0, 20))
        self.assertIn("0 of 20 held pages", r["explain"])
        self.assertIn("Wilson", r["explain"])
        self.assertFalse(t["policy"]["active"])
        self.assertIn("advisory only", r["status"])
        self.assertFalse(r["eligible"])  # without review.trust nothing is ever eligible for anything
        self.assertIn("weight = 1 - Wilson upper bound", t["formula"])

    def test_area_is_the_owning_team_else_the_top_folder(self):
        self.certs("Ana Lead", 2, area="claims")
        self.certs("Ana Lead", 2, area="billing")
        areas = {r["area"] for r in RS.trust_table(self.kb, signals=CLEAN)["rows"]}
        self.assertEqual(areas, {"Claims Team", "billing"})


class TrustTableWithPolicy(Base):
    trust = {"min_decisions": 20, "max_problem_rate": 0.10, "lookback_days": 365}

    def test_later_problems_dislike_stale_contradiction_and_limit(self):
        self.certs("Ana Lead", 20)
        self.certs("Raj Dev", 20, area="billing", role="app owner")
        sig = {"disliked": {"claims/x00.md": ["2999-01-01"], "claims/x05.md": ["2000-01-01"]}, "stale": {"claims/x01.md"},
               "contradicted": {"claims/x02.md"}, "notes": []}
        t = RS.trust_table(self.kb, signals=sig)
        ana = self.row(t, "Ana Lead", "Claims Team")
        self.assertEqual((ana["disliked"], ana["stale"], ana["contradicted"], ana["problem_pages"]), (1, 1, 1, 3))  # the 2000 dislike predates the certification
        self.assertAlmostEqual(ana["problem_rate"], 0.15)
        self.assertEqual(ana["weight"], round(1 - RS.wilson(3, 20)[1], 3))
        self.assertFalse(ana["within_limits"])
        self.assertFalse(ana["eligible"])
        self.assertIn("problem rate above 10%", ana["status"])
        self.assertIn("3 of 20", ana["explain"])
        raj = self.row(t, "Raj Dev", "billing")
        self.assertTrue(raj["eligible"])
        self.assertTrue(raj["within_limits"])
        self.assertGreater(raj["weight"], ana["weight"])

    def test_reversal_by_a_different_person_counts_against_the_certifier(self):
        self.certs("Ana Lead", 4)
        kb_gate.log(self.kb, "certify-removal", "Raj Dev", "app owner", "b2", "claims/x00.md")
        r = self.row(RS.trust_table(self.kb, signals=CLEAN), "Ana Lead", "Claims Team")
        self.assertEqual((r["reversals"], r["certifications"], r["pages_held"]), (1, 4, 3))
        self.assertAlmostEqual(r["reversal_rate"], 0.25)
        self.assertEqual(self.row(RS.trust_table(self.kb, signals=CLEAN), "Raj Dev", "Claims Team")["removals"], 1)

    def test_own_removal_is_not_a_reversal(self):
        self.certs("Ana Lead", 2)
        kb_gate.log(self.kb, "certify-removal", "Ana Lead", "kb owner", "b2", "claims/x00.md")
        self.assertEqual(self.row(RS.trust_table(self.kb, signals=CLEAN), "Ana Lead", "Claims Team")["reversals"], 0)

    def test_lookback_leaves_old_events_out(self):
        p = os.path.join(self.kb, ".metis", "CERTIFICATIONS.log")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="\n") as fh:
            for i in range(30):
                fh.write("2020-01-01 10:00\tcertify\tAna Lead\tkb owner\tb0\tclaims/old%02d.md\n" % i)
        self.certs("Ana Lead", 2)
        r = self.row(RS.trust_table(self.kb, signals=CLEAN), "Ana Lead", "Claims Team")
        self.assertEqual(r["certifications"], 2)

    def test_rejections_are_counted_per_reviewer_only(self):
        kb_gate.log(self.kb, "reject", "Raj Dev", "app owner", "b3", "4 files", "no")
        self.certs("Ana Lead", 1)
        t = RS.trust_table(self.kb, signals=CLEAN)
        self.assertEqual(t["rejections"], {"Raj Dev": 1})
        self.assertFalse([r for r in t["rows"] if r["reviewer"] == "Raj Dev"])

    def test_missing_sources_degrade_gracefully(self):
        self.certs("Ana Lead", 2)
        with mock.patch.object(feedback, "load", side_effect=RuntimeError("boom")), \
                mock.patch("page_owners.stale_report", side_effect=RuntimeError("no git")):
            t = RS.trust_table(self.kb)
        self.assertTrue(any("dislikes not available" in n for n in t["notes"]))
        self.assertTrue(any("stale check not available" in n for n in t["notes"]))
        self.assertEqual(self.row(t, "Ana Lead", "Claims Team")["certifications"], 2)

    def test_real_dislike_is_joined_from_feedback(self):
        self.certs("Ana Lead", 1)
        kb_gate.log(self.kb, "certify", "Ana Lead", "kb owner", "b1", "context/a.md")
        ans = os.path.join(self.d, "ans.md")
        write(ans, '# Answer\n\n- Fact [E: kb:context/a.md "Pay in 30 days"]\n')
        feedback.record(self.kb, ans, "What?", "User1", "down", why="Wrong", correct="45")
        sig = RS.problem_signals(self.kb)
        self.assertIn("context/a.md", sig["disliked"])
        r = self.row(RS.trust_table(self.kb, signals=sig), "Ana Lead", "context")
        self.assertEqual(r["disliked"], 1)

    def test_cli(self):
        self.certs("Ana Lead", 3)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(RS.main(["trust", self.kb]), 0)
            self.assertEqual(RS.main(["trust", self.kb, "--reviewer", "Nobody"]), 0)
        self.assertIn("Formula:", out.getvalue())
        self.assertIn("not enough history", out.getvalue())
        self.assertIn("no certification events", out.getvalue())


class Contributors(Base):
    def setUp(self):
        super().setUp()
        write(os.path.join(self.kb, "context", "policy.md"), "# Policy\n\n- Claims paid within 30 days; later 45. [E: file:rules.txt]\n")
        write(os.path.join(self.kb, "_EVIDENCE", "files", "rules.txt"), "pay in 30 days; claims paid within 30 days; later 45 days\n")
        write(os.path.join(self.kb, "context", "a.md"), "# A\n\n- Claims are paid within 30 days. [E: kb:context/policy.md]\n")

    def sug(self, n, by="Pat Lee"):
        return PS.suggest(self.kb, "context/a.md", by, "wrong %d" % n, "Claims are paid within %d days." % (40 + n),
                          '[E: kb:context/policy.md "within 30 days"]', None, 3)

    def test_record_counts_approved_declined_open_and_later_disliked(self):
        s1, s2, s3 = self.sug(1), self.sug(2), self.sug(3)
        PS.approve(self.kb, s1["id"], "Ana Lead", "question")
        PS.decline(self.kb, s2["id"], "Ana Lead", "not right")
        self.assertEqual(PS.contributor_record(self.kb)["pat lee"]["approved_later_disliked"], 0)
        ans = os.path.join(self.d, "ans.md")
        write(ans, '# Answer\n\n- Fact [E: kb:context/a.md "Claims are paid"]\n')
        feedback.record(self.kb, ans, "What?", "User1", "down", why="Wrong", correct="45")
        r = PS.contributor_record(self.kb)["pat lee"]
        self.assertEqual((r["suggested"], r["approved"], r["declined"], r["open"], r["approved_later_disliked"]), (3, 1, 1, 1, 1))
        self.assertEqual(r["disliked_pages"], ["context/a.md"])
        self.assertIn("3 suggested; 1 approved, 1 declined, 1 open; 1 approved on a page disliked afterwards", PS.contributor_line(self.kb, "pat lee"))
        self.assertIn("no earlier suggestions", PS.contributor_line(self.kb, "Sam New"))
        self.assertEqual(s3["status"], "open")

    def test_since_leaves_out_older_suggestions(self):
        self.sug(1)
        self.assertEqual(PS.contributor_record(self.kb, since="2999-01-01"), {})

    def test_reviewer_stats_contributors_text_and_cli(self):
        self.sug(1)
        recs = RS.contributor_records(self.kb)
        self.assertIn("Pat Lee: 1 suggested; 0 approved, 0 declined, 1 open", recs["pat lee"]["text"])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(RS.main(["contributors", self.kb]), 0)
        self.assertIn("Pat Lee", out.getvalue())

    def test_inbox_shows_the_track_record_next_to_the_suggestion(self):
        PS.approve(self.kb, self.sug(1)["id"], "Ana Lead", "question")
        self.sug(2)
        html = SUG.suggest_view(C.Ctx(self.kb, "tok", "Ana Lead"), {})
        self.assertIn("Track record (facts, not a score)", html)
        self.assertIn("Pat Lee: 2 suggested; 1 approved, 0 declined, 1 open", html)
        # a reader without decision rights does not get the inbox card
        self.assertNotIn("Track record", SUG.suggest_view(C.Ctx(self.kb, "tok", "Pat Lee"), {"page": "context/a.md"}))


class Routing(Base):
    trust = {"min_decisions": 3}

    def setUp(self):
        super().setUp()
        kb_gate.lock(self.kb, "Ana Lead")

    def by_file(self, rt):
        return {it["file"]: it for it in rt["items"]}

    def test_best_reviewer_by_area_weight_and_the_giver_is_excluded(self):
        self.certs("Cleo Claims", 3, role="Claims Team approver")
        given = "---\ntitle: B\ndocuments:\n- {id: d1, name: r.docx, given_by: Cleo Claims}\n---\n" + GOOD
        self.stage({"claims/a.md": GOOD, "claims/b.md": given, "context/c.md": GOOD})
        it = self.by_file(review_queue.route(self.kb))
        names = [c["name"] for c in it["claims/a.md"]["suggested"]]
        self.assertEqual(names[0], "Cleo Claims")  # a weight in this area comes first
        self.assertIsNotNone(it["claims/a.md"]["suggested"][0]["weight"])
        # the giver of claims/b.md cannot certify it, and the reason is shown
        self.assertNotIn("Cleo Claims", [c["name"] for c in it["claims/b.md"]["suggested"]])
        self.assertEqual([x["name"] for x in it["claims/b.md"]["excluded"]], ["Cleo Claims"])
        self.assertIn("another approver must certify", it["claims/b.md"]["excluded"][0]["reason"])
        # and that is the gate's own rule: certify refuses it too
        with self.assertRaises(kb_gate.GateError):
            kb_gate.certify(self.kb, kb_gate.batches(self.kb)[0], "Cleo Claims", ["claims/b.md"])
        # a file with no owning team is routed to the leads only
        self.assertEqual({c["name"] for c in it["context/c.md"]["suggested"]}, {"Ana Lead", "Raj Dev"})

    def test_self_certify_setting_lifts_the_exclusion(self):
        prof = self.profile()
        prof["gate"]["allow_self_certify"] = True
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump(prof))
        self.stage({"claims/b.md": "---\ntitle: B\ndocuments:\n- {id: d1, name: r.docx, given_by: Cleo Claims}\n---\n" + GOOD})
        self.assertEqual(review_queue.route(self.kb)["items"][0]["excluded"], [])

    def test_load_spreads_items_and_assigned_counts(self):
        self.stage({"context/c%d.md" % i: GOOD for i in range(4)})
        rt = review_queue.route(self.kb)
        firsts = [it["suggested"][0]["name"] for it in rt["items"]]
        self.assertEqual(sorted(set(firsts)), ["Ana Lead", "Raj Dev"])
        self.assertEqual(firsts.count("Ana Lead"), 2)
        batch = kb_gate.batches(self.kb)[0]
        busy = review_queue.route(self.kb, assigned={"%s/x%d" % (batch, i): "Ana Lead" for i in range(5)})
        self.assertTrue(all(it["suggested"][0]["name"] == "Raj Dev" for it in busy["items"][:2]))

    def test_fast_lane_is_a_label_only_and_needs_every_check(self):
        self.stage({"claims/ok.md": GOOD, "claims/noquote.md": NO_QUOTE, "claims/bad.md": GOOD + "- Secret: ana@example.com\n",
                    "claims/big.md": "# Big\n\n" + "".join('- Line %d [E: file:rules.txt "pay in 30 days"]\n' % i for i in range(30)),
                    "context/c.md": GOOD})
        it = self.by_file(review_queue.route(self.kb))
        self.assertTrue(it["claims/ok.md"]["fast_lane"])
        self.assertEqual(it["claims/ok.md"]["fast_lane_label"], "suitable for sampling review")
        self.assertIn("certifies nothing", it["claims/ok.md"]["note"])
        for rel, why in (("claims/noquote.md", "every source tag verified"), ("claims/big.md", "small change"),
                         ("claims/bad.md", "no sensitive-data hits"), ("context/c.md", "an owning team with a named approver")):
            self.assertFalse(it[rel]["fast_lane"], rel)
            self.assertTrue(any(why in f for f in it[rel]["fast_lane_failed"]), (rel, it[rel]["fast_lane_failed"]))

    def test_fast_lane_off_for_open_question_and_removal_and_ai_links(self):
        write(os.path.join(self.kb, "_QUESTIONS", "VALIDATE_KB.yaml"), yaml.safe_dump({"questions": [
            {"id": "Q-0001", "question": "x?", "priority": "P1", "status": "open", "blocks": ["claims/q.md"]}]}))
        self.stage({"claims/q.md": GOOD, "claims/x/ai.links.yaml": "links: []\n"})
        batch = kb_gate.new_batch(self.kb, "rm")
        kb_gate.propose(self.kb, batch, None, ["context/a.md"])
        it = self.by_file(review_queue.route(self.kb))
        self.assertFalse(it["claims/q.md"]["fast_lane"])
        self.assertIn("no open question blocks it", it["claims/q.md"]["fast_lane_failed"])
        self.assertFalse(it["claims/x/ai.links.yaml"]["fast_lane"])
        self.assertFalse(it["context/a.md"]["fast_lane"])

    def test_route_changes_nothing_and_certifies_nothing(self):
        self.stage({"claims/ok.md": GOOD})
        before = tree(self.kb)
        review_queue.route(self.kb)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(review_queue.main(["route", self.kb]), 0)
        self.assertEqual(tree(self.kb), before)
        self.assertTrue(os.path.isfile(os.path.join(self.kb, "_PENDING", kb_gate.batches(self.kb)[0], "claims", "ok.md")))
        self.assertFalse(os.path.isfile(os.path.join(self.kb, "claims", "ok.md")))
        self.assertIn("suitable for sampling review", out.getvalue())
        self.assertIn("Routing suggests only", out.getvalue())
        # a person still has to act, through the gate, and only a named lead or the team's approver can
        with self.assertRaises(kb_gate.GateError):
            kb_gate.certify(self.kb, kb_gate.batches(self.kb)[0], "Pat Lee")
        self.assertEqual(kb_gate.certify(self.kb, kb_gate.batches(self.kb)[0], "Cleo Claims"), 1)


class SampleFloor(Base):
    trust = {"min_decisions": 3, "sample_share": 0.01, "floor_files": 3, "floor_share": 0.10}

    def test_floor_is_the_larger_of_three_files_or_ten_percent(self):
        self.certs("Ana Lead", 3)
        # 100 files: the standard draw is 20, the floor is 10 percent = 10, so a 1 percent share cannot go below 10
        s = review_queue.sample_size(self.kb, 100, "Ana Lead", "Claims Team", base=20)
        self.assertEqual((s["size"], s["base"], s["floor"], s["reduced"]), (10, 20, 10, True))
        # 14 files: 10 percent is 2, so the floor is 3 files
        s = review_queue.sample_size(self.kb, 14, "Ana Lead", "Claims Team", base=5)
        self.assertEqual((s["size"], s["floor"], s["reduced"]), (3, 3, True))
        # a batch smaller than the floor: the floor is the whole batch
        s = review_queue.sample_size(self.kb, 2, "Ana Lead", "Claims Team", base=2)
        self.assertEqual((s["size"], s["floor"], s["reduced"]), (2, 2, False))

    def test_never_larger_than_the_standard_draw(self):
        self.certs("Ana Lead", 3)
        prof = self.profile()
        prof["review"]["trust"]["sample_share"] = 1
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump(prof))
        s = review_queue.sample_size(self.kb, 14, "Ana Lead", "Claims Team", base=5)
        self.assertEqual((s["size"], s["reduced"]), (5, False))

    def test_no_reduction_without_enough_history_or_above_a_limit_or_unknown_reviewer(self):
        self.certs("Ana Lead", 2)
        for who in ("Ana Lead", "Cleo Claims", "Nobody", ""):
            s = review_queue.sample_size(self.kb, 100, who, "Claims Team", base=20)
            self.assertEqual((s["size"], s["reduced"]), (20, False), who)
        self.assertIn("not enough history", review_queue.sample_size(self.kb, 100, "Ana Lead", "Claims Team", base=20)["reason"])
        self.certs("Raj Dev", 4, role="app owner")
        kb_gate.log(self.kb, "certify-removal", "Ana Lead", "kb owner", "b2", "claims/x00.md")  # Ana (not Raj) removes Raj's page
        self.assertEqual(self.reduced("Raj Dev"), 20)  # a reversal rate of 1 of 4 is above the 10 percent limit
        self.assertEqual(self.reduced("Ana Lead"), 20)  # Ana: 2 certifications + 1 removal = 3 decisions, still has a weight
        self.assertFalse(self.row(RS.trust_table(self.kb, signals=CLEAN), "Raj Dev", "Claims Team")["within_limits"])

    def reduced(self, who):
        return review_queue.sample_size(self.kb, 100, who, "Claims Team", base=20)["size"]

    def test_no_policy_or_no_sample_share_means_the_standard_draw(self):
        for trust in (None, {"min_decisions": 3}):
            prof = dict(PROFILE)
            if trust:
                prof["review"] = {"trust": trust}
            write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump(prof))
            self.certs("Ana Lead", 5)
            s = review_queue.sample_size(self.kb, 100, "Ana Lead", "Claims Team", base=20)
            self.assertEqual((s["size"], s["reduced"]), (20, False))
            self.assertIn("standard sample applies", s["reason"])


class ReviewScreenSampling(Base):
    trust = {"min_decisions": 3, "sample_share": 0.01}

    def setUp(self):
        super().setUp()
        kb_gate.lock(self.kb, "Ana Lead")
        self.certs("Ana Lead", 3, area="claims", start=50)
        self.lead = C.Ctx(self.kb, "tok", "Ana Lead")
        self.raj = C.Ctx(self.kb, "tok", "Raj Dev")

    def draw(self, ctx):
        REV.act_draw(ctx, F(team="Claims Team"))
        return REV.load_state(self.kb, "Claims Team")

    def test_reduced_draw_for_a_reviewer_with_history_but_not_below_the_floor(self):
        self.stage({"claims/p%02d.md" % i: NO_QUOTE for i in range(14)})
        html = REV.review(self.lead, {})
        self.assertIn("By the review.trust policy the draw is 3 items for Ana Lead", html)
        st = self.draw(self.lead)
        self.assertEqual(sum(v == ["random draw"] for v in st["sample"].values()), 3)  # standard is 5; floor is 3

    def test_standard_draw_for_a_reviewer_without_history(self):
        self.stage({"claims/p%02d.md" % i: NO_QUOTE for i in range(14)})
        self.assertNotIn("By the review.trust policy", REV.review(self.raj, {}))
        st = self.draw(self.raj)
        self.assertEqual(sum(v == ["random draw"] for v in st["sample"].values()), 5)

    def test_certifying_still_needs_the_sample_to_be_reviewed(self):
        self.stage({"claims/p%02d.md" % i: NO_QUOTE for i in range(14)})
        self.draw(self.lead)
        with self.assertRaises(C.UiError) as cm:
            REV.act_certify(self.lead, F(team="Claims Team"))
        self.assertIn("not marked reviewed", str(cm.exception))


class ReviewScreenRouting(Base):
    def setUp(self):
        super().setUp()
        kb_gate.lock(self.kb, "Ana Lead")
        self.lead = C.Ctx(self.kb, "tok", "Ana Lead")

    def test_queue_shows_suggested_reviewer_and_the_sampling_label(self):
        self.stage({"claims/ok.md": GOOD, "claims/noquote.md": NO_QUOTE})
        html = REV.review(self.lead, {})
        self.assertIn("Suggested reviewer:", html)
        self.assertEqual(html.count("suitable for sampling review"), 1)
        self.assertIn("certifies nothing", html)

    def test_item_page_shows_routing(self):
        batch = self.stage({"claims/ok.md": GOOD})
        html = REV.review(self.lead, {"team": "Claims Team", "batch": batch, "file": "claims/ok.md"})
        self.assertIn("Routing", html)
        self.assertIn("suitable for sampling review", html)
        self.assertIn("certifying still takes a named lead", html)


class OwnersTrustView(Base):
    trust = {"min_decisions": 3, "max_problem_rate": 0.1, "lookback_days": 90}

    def setUp(self):
        super().setUp()
        kb_gate.lock(self.kb, "Ana Lead")
        self.lead = C.Ctx(self.kb, "tok", "Ana Lead")

    def test_view_shows_table_counts_formula_thresholds_and_routing(self):
        self.certs("Ana Lead", 4)
        self.stage({"claims/ok.md": GOOD})
        html = OWN.owners_view(self.lead, {"view": "trust"})
        for text in ("Reviewer Trust", "Claims Team", "Ana Lead", "Formula", "weight = 1 - Wilson upper bound", "review.trust",
                     "minimum decisions per reviewer and area: <b>3</b>", "lookback: <b>90 days</b>", "Wilson 95% interval", "Reversals",
                     "Routing Suggestions", "claims/ok.md", "suitable for sampling review", "nothing here approves or certifies"):
            self.assertIn(text, html, text)
        self.assertIn("0 of 4 held pages", html)

    def test_not_enough_history_is_shown_as_such(self):
        self.certs("Ana Lead", 2)
        html = OWN.owners_view(self.lead, {"view": "trust"})
        self.assertIn("not enough history", html)
        self.assertIn("<b>none</b>", html)

    def test_policy_absent_is_stated(self):
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump(PROFILE))
        html = OWN.owners_view(self.lead, {"view": "trust"})
        self.assertIn("absent, so weights are advisory only", html)
        self.assertIn("not enabled (sample_share is not set)", html)

    def test_names_are_escaped_and_nav_item_exists(self):
        kb_gate.log(self.kb, "certify", "<b>X</b>", "kb owner", "b1", "claims/z.md")
        html = OWN.owners_view(self.lead, {"view": "trust"})
        self.assertNotIn("<b>X</b></td>", html)
        self.assertIn("&lt;b&gt;X&lt;/b&gt;", html)
        self.assertIn("/owners?view=trust", html)


if __name__ == "__main__":
    unittest.main()
