"""Devin's suggested acceptance criteria and estimate: one read-only session per story, advice only."""
import json
import os
import shutil
import sys
import tempfile
import unittest

HOME = tempfile.mkdtemp(prefix="sdlc-insight-test-")
os.environ.setdefault("SDLC_CONSOLE_HOME", HOME)
os.environ["SDLC_WORKBENCH_READ_REMOTE"] = "0"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "console"))
import backlog  # noqa: E402
import server as wb  # noqa: E402

ANSWER = {"acceptance": "1. The grid shows the stamp.\n2. Export includes it.", "points": 3,
          "why": "one React component and one API field", "files": ["web/src/Grid.tsx"]}


class FakeDevin:
    def __init__(self):
        self.created, self.ended, self.reply, self.status = [], [], None, "working"

    def create_session(self, prompt, title, tags):
        self.created.append({"prompt": prompt, "title": title, "tags": tags})
        return {"session_id": "devin-ins1", "url": "https://x/sessions/ins1"}

    def session(self, sid):
        msgs = [{"type": "devin_message", "message": self.reply}] if self.reply else []
        return {"status_enum": self.status, "messages": msgs}

    def terminate(self, sid):
        self.ended.append(sid)


class StoryInsightTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="sdlc-ins-")
        self.t = [1000.0]
        self.devin = FakeDevin()
        self.ins = wb.StoryInsight(self.devin, path=os.path.join(self.dir, "ins.json"), clock=lambda: self.t[0])

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_one_read_only_session_then_parsed_answer(self):
        r = self.ins.start({"key": "acme-90201", "summary": "Approval stamp", "description": "d", "acceptance": ""})
        self.assertEqual(r["state"], "working")
        self.assertEqual(len(self.devin.created), 1)
        c = self.devin.created[0]
        self.assertIn("ACME-90201", c["tags"])
        self.assertIn("Read-only", c["prompt"])
        self.assertIn("Do not change code", c["prompt"])
        self.assertIn("complexity-matrix.yaml", c["prompt"])
        self.assertIn("TESTABILITY", c["prompt"])
        self.ins.start({"key": "ACME-90201"})
        self.assertEqual(len(self.devin.created), 1, "a second press reuses the running session")
        self.t[0] += 10
        self.assertEqual(self.ins.get("ACME-90201")["state"], "working")
        self.devin.reply = "[SDLC] story-insight ACME-90201\n```json\n%s\n```" % json.dumps(ANSWER)
        self.t[0] += 10
        r = self.ins.get("ACME-90201")
        self.assertEqual((r["state"], r["points"]), ("done", 3))
        self.assertIn("Export includes it", r["acceptance"])
        self.assertEqual(r["files"], ["web/src/Grid.tsx"])
        self.assertEqual(self.devin.ended, ["devin-ins1"], "the session is ended once it answered")

    def test_matrix_answer_is_scored_by_the_rule_book(self):
        self.ins.start({"key": "ACME-5"})
        ans = dict(ANSWER, points=2, story_type="code", modifiers=["MOD_PERFORMANCE_SENSITIVE", "MOD_MADE_UP"],
                   scores={"SCOPE": [1, "grid and API"], "RISK": [0, "read-only"], "UNKNOWNS": [1, "sort order"],
                           "DEPENDENCY": [0, ""], "TESTABILITY": [1, "seeded data"]}, bigger_if="the export changes too")
        self.devin.reply = "[SDLC] story-insight ACME-5\n```json\n%s\n```" % json.dumps(ans)
        self.t[0] += 10
        r = self.ins.get("ACME-5")
        self.assertEqual((r["total"], r["base"], r["points"], r["claimed"]), (3, 2, 3, 2),
                         "3/10 looks up to 2, one known modifier bumps it to 3, whatever Devin claimed")
        self.assertEqual(r["modifiers"], ["MOD_PERFORMANCE_SENSITIVE"])
        self.assertEqual(self.ins.card("ACME-5"), "3")
        self.assertIn("UNKNOWNS 1 (sort order)", wb.insight_basis(r))
        self.assertEqual(r["bigger_if"], "the export changes too")

    def test_matrix_rules_for_grooming_split_and_story_types(self):
        dims = lambda *v: dict(zip(wb.MATRIX_DIMENSIONS, v))  # noqa: E731
        g = wb.matrix_points({"scores": dims(1, 2, 2, 0, 1)})
        self.assertTrue(g["needs_grooming"])
        self.assertEqual(wb.insight_card(dict(g, state="done")), "?")
        s = wb.matrix_points({"scores": dims(2, 2, 1, 2, 1), "modifiers": ["MOD_DATA_MIGRATION", "MOD_BREAKING_CHANGE"]})
        self.assertEqual((s["base"], s["points"], s["needs_split"]), (8, 13, True))
        self.assertEqual(wb.insight_card(dict(s, state="done")), "13")
        self.assertEqual(wb.matrix_points({"story_type": "uat", "points": 5})["points"], 1)
        self.assertEqual(wb.matrix_points({"story_type": "spike", "points": 9})["points"], 5)
        self.assertEqual(wb.matrix_rules()[0][-1], (10, 13), "the lookup is read from complexity-matrix.yaml")

    def test_poker_keeps_a_finished_answer(self):
        self.ins.start({"key": "ACME-6"})
        self.devin.reply = "[SDLC] story-insight ACME-6\n```json\n%s\n```" % json.dumps(ANSWER)
        self.t[0] += 10
        self.ins.get("ACME-6")
        self.ins.start({"key": "ACME-6"}, keep_done=True)
        self.assertEqual(len(self.devin.created), 1)

    def test_failure_and_bad_key(self):
        self.ins.start({"key": "ACME-1"})
        self.devin.reply = "[SDLC] note story-insight ACME-1 — failed: repo not readable"
        self.t[0] += 10
        r = self.ins.get("ACME-1")
        self.assertEqual(r["state"], "failed")
        self.assertIn("repo not readable", r["error"])
        with self.assertRaises(wb.ApiError):
            self.ins.start({"key": "not a key"})
        self.assertEqual(self.ins.get("ACME-404"), {})

    def test_gives_up_when_the_session_stops(self):
        self.ins.start({"key": "ACME-2"})
        self.devin.status = "exit"
        self.t[0] += 10
        self.assertEqual(self.ins.get("ACME-2")["state"], "failed")


class SuggestedAcceptanceTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="sdlc-bl-ac-")
        self.b = backlog.Backlog(object(), self.dir, env={})

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_preview_only_with_suggested_label(self):
        c = self.b.set_acceptance("acme-90201", "1. edited on the call", "po.user", suggested=True)
        self.assertEqual(c["status"], "preview")
        put = c["calls"][0]
        self.assertEqual(put["body"]["fields"], {backlog.F_ACCEPTANCE: "1. edited on the call"})
        self.assertEqual(put["body"]["update"], {"labels": [{"add": backlog.SUGGESTED_AC_LABEL}]})
        self.assertIn("Devin's suggestion", c["calls"][1]["body"]["body"])
        plain = self.b.set_acceptance("ACME-90201", "1. typed", "po.user")
        self.assertNotIn("update", plain["calls"][0]["body"])

    def test_empty_or_placeholder_rejected(self):
        for text in ("", "  ", "Please enter Acceptance Criteria"):
            with self.assertRaises(backlog.BacklogError):
                self.b.set_acceptance("ACME-90201", text, "po.user")


class AcRewriteTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="sdlc-acr-")
        self.t = [1000.0]
        self.devin = FakeDevin()
        self.acr = wb.AcRewrite(self.devin, path=os.path.join(self.dir, "acr.json"), clock=lambda: self.t[0])

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def reply(self, key, out):
        self.devin.reply = "[SDLC] ac-rewrite %s\n```json\n%s\n```" % (key, json.dumps(out))
        self.t[0] += 10

    def test_questions_then_answers_then_numbered_outcomes(self):
        story = {"key": "acme-11886", "summary": "EOC TIN Management", "description": "d",
                 "acceptance": "Development to be Covered: design the wireframe"}
        self.assertEqual(self.acr.start(story)["state"], "working")
        first = self.devin.created[0]
        self.assertIn("ACME-11886", first["tags"])
        self.assertIn("Read-only", first["prompt"])
        self.assertIn("Do not guess", first["prompt"])
        self.assertIn("Development to be Covered", first["prompt"])
        self.reply("ACME-11886", {"questions": ["Who signs off the wireframe?", "Which fields can be overridden?"]})
        r = self.acr.get("ACME-11886")
        self.assertEqual((r["state"], len(r["questions"])), ("questions", 2))
        self.assertEqual(self.devin.ended, ["devin-ins1"])
        answers = [{"question": "Who signs off the wireframe?", "answer": "The EOC business lead"}, {"question": ""}]
        self.assertEqual(self.acr.start(story, answers)["state"], "working")
        second = self.devin.created[1]["prompt"]
        self.assertIn("A: The EOC business lead", second)
        self.reply("ACME-11886", {"acceptance": "1. The EOC business lead approves the wireframe.",
                                  "moved": ["field list -> description"], "notes": "build steps moved out"})
        r = self.acr.get("ACME-11886")
        self.assertEqual(r["state"], "done")
        self.assertTrue(r["acceptance"].startswith("1. "))
        self.assertEqual(r["moved"], ["field list -> description"])
        self.assertEqual(r["answers"], [{"question": "Who signs off the wireframe?", "answer": "The EOC business lead"}])

    def test_running_session_is_reused_and_failures_reported(self):
        self.acr.start({"key": "ACME-7"})
        self.acr.start({"key": "ACME-7"})
        self.assertEqual(len(self.devin.created), 1)
        self.devin.reply = "[SDLC] note ac-rewrite ACME-7 — failed: ticket not readable"
        self.t[0] += 10
        self.assertEqual(self.acr.get("ACME-7")["state"], "failed")
        with self.assertRaises(wb.ApiError):
            self.acr.start({"key": "nope"})


class GroomSaveTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="sdlc-bl-groom-")
        self.b = backlog.Backlog(type("CloudJira", (), {"via": "cloud", "token": ""})(), self.dir, env={})

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_one_update_for_description_ac_and_points(self):
        c = self.b.groom("acme-11886", {"description": "As a user…", "acceptance": "1. Shown", "points": "5",
                                        "suggested": True}, "po.user")
        self.assertEqual(c["status"], "preview")
        put = c["calls"][0]
        self.assertEqual(put["path"], "/api/2/issue/ACME-11886")
        self.assertEqual(put["body"]["fields"], {"description": "As a user…", backlog.F_ACCEPTANCE: "1. Shown",
                                                 backlog.F_POINTS: 5})
        self.assertEqual(put["body"]["update"], {"labels": [{"add": backlog.SUGGESTED_AC_LABEL}]})
        self.assertIn("Groomed: description, acceptance criteria, 5 points", c["calls"][1]["body"]["body"])
        only = self.b.groom("ACME-11886", {"points": 3, "suggested": True}, "po.user")
        self.assertEqual(only["calls"][0]["body"], {"fields": {backlog.F_POINTS: 3}})

    def test_sprint_and_fix_version_for_one_story(self):
        c = self.b.groom("ACME-11886", {"sprint": {"id": 501, "name": "Acme Claims Sprint 26.4.3"}, "fix_version": "11/20 Release"},
                         "po.user")
        put, move, note = c["calls"]
        self.assertEqual(put["body"]["fields"], {"fixVersions": [{"name": "11/20 Release"}]})
        self.assertEqual((move["path"], move["body"]), ("/agile/1.0/sprint/501/issue", {"issues": ["ACME-11886"]}))
        self.assertIn("moved to Acme Claims Sprint 26.4.3", note["body"]["body"])
        back = self.b.groom("ACME-11886", {"sprint": "backlog"}, "po.user")
        self.assertEqual([x["path"] for x in back["calls"]], ["/agile/1.0/backlog/issue", "/api/2/issue/ACME-11886/comment"])

    def test_nothing_or_placeholder_rejected(self):
        for changes in ({}, {"acceptance": "Please enter Acceptance Criteria"}, {"points": "0"}):
            with self.assertRaises(backlog.BacklogError):
                self.b.groom("ACME-11886", changes, "po.user")


if __name__ == "__main__":
    unittest.main()
