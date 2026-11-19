"""Framework tests — stdlib unittest only, no Snowflake, Artifactory, Jira or Confluence needed.

    python3 -m unittest discover -s sdlc/framework/tools/tests -v

Every test runs against a throw-away SDLC_SESSION_HOME with SDLC_OWNER fixed, so nothing touches
~/.sdlc or the repo's context/session tree.
"""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.abspath(os.path.join(TOOLS, "..", "..", ".."))
sys.path.insert(0, TOOLS)

import access_guard  # noqa: E402
import gates  # noqa: E402
import gate_timeouts  # noqa: E402
import gen_dashboard  # noqa: E402
import metrics  # noqa: E402
import roster_sync  # noqa: E402
import session_store  # noqa: E402

OWNER_NAME = "Resource 3"      # on the roster; slug of resource3@acme.example
OWNER_SLUG = "resource3"
NOT_OWNER_NAME = "Resource 1"


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class Sandbox(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="sdlc-test-")
        self._env = dict(os.environ)
        os.environ.update({"SDLC_SESSION_HOME": self.home, "SDLC_OWNER": OWNER_SLUG,
                           "SDLC_SESSION_STRATEGY": "local", "SDLC_GATE_MODE": "dev"})
        self._verify_roster = access_guard.verify_roster
        access_guard.verify_roster = lambda *a, **k: (True, "verified (test)")

    def tearDown(self):
        access_guard.verify_roster = self._verify_roster
        os.environ.clear()
        os.environ.update(self._env)
        shutil.rmtree(self.home, ignore_errors=True)

    def quiet(self, fn, *a, **kw):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = fn(*a, **kw)
        return rc, buf.getvalue()


class SessionStoreTests(Sandbox):
    def test_session_dir_is_owner_scoped_and_outside_repo(self):
        path = session_store.session_dir("REQ-100", create=True)
        self.assertTrue(path.startswith(self.home))
        self.assertIn(os.path.join(OWNER_SLUG, "REQ-100"), path)
        self.assertFalse(path.startswith(ROOT))

    def test_rejects_non_requirement_ids(self):
        with self.assertRaises(ValueError):
            session_store.session_dir("../etc")

    def test_restore_takes_windows_names(self):
        import base64
        data = base64.b64encode(b"x").decode()
        base = session_store.restore("REQ-103", {"files": {"sub\\note.md": data}})
        self.assertTrue(os.path.isfile(os.path.join(base, "sub", "note.md")))
        for name in ("..\\..\\escaped.txt", "C:\\escaped.txt", "C:/escaped.txt"):
            with self.assertRaises(ValueError):
                session_store.restore("REQ-103", {"files": {name: data}})

    def test_restore_refuses_names_outside_the_session(self):
        import base64
        data = base64.b64encode(b"x").decode()
        outside = os.path.join(self.home, "escaped.txt")
        for name in ("../../escaped.txt", outside, "a/../../../escaped.txt", "."):
            with self.assertRaises(ValueError):
                session_store.restore("REQ-102", {"files": {"ok.txt": data, name: data}})
            self.assertFalse(os.path.exists(outside))
        self.assertFalse(os.path.exists(os.path.join(session_store.session_dir("REQ-102"), "ok.txt")))
        base = session_store.restore("REQ-102", {"files": {os.path.join("notes", "ok.txt"): data}})
        with open(os.path.join(base, "notes", "ok.txt"), "rb") as fh:
            self.assertEqual(fh.read(), b"x")

    def test_other_owner_sessions_are_invisible_but_sweepable(self):
        os.makedirs(os.path.join(self.home, "someone-else", "REQ-200"))
        with open(os.path.join(self.home, "someone-else", "REQ-200", "approvals.yaml"), "w") as fh:
            fh.write("requirement_id: REQ-200\n")
        self.assertNotIn("REQ-200", session_store.list_sessions())
        self.assertIn(("someone-else", "REQ-200"), [(o, r) for o, r, _ in session_store.all_session_records()])

    def test_snapshot_drops_secrets_and_message_bodies(self):
        session_store.session_dir("REQ-101", create=True)
        session_store.write_approvals("REQ-101", {
            "requirement_id": "REQ-101",
            "token": "abc", "phases": {"intake": {"gate_id": "SDLC_01_INTAKE_CLARIFICATION", "status": "pending",
                                                  "body": "long chat text", "approval_words": "approved"}}})
        import base64
        snap = session_store.snapshot("REQ-101")
        text = base64.b64decode(snap["files"]["approvals.yaml"]).decode()
        self.assertNotIn("abc", text)
        self.assertNotIn("long chat text", text)
        self.assertIn("SDLC_01_INTAKE_CLARIFICATION", text)
        self.assertIn("approval_words", text)


class ApprovalParsingTests(Sandbox):
    def present(self, req="REQ-300", gate="SDLC_01_INTAKE_CLARIFICATION", story=None):
        session_store.session_dir(req, create=True)
        return gates.present(req, gate, story_id=story)

    def test_only_approved_word_counts(self):
        self.present()
        for reply in ("ok", "yes", "approve", "go ahead", "looks good", "continue"):
            rc, out = self.quiet(gates.decide, "REQ-300", "SDLC_01_INTAKE_CLARIFICATION", OWNER_NAME, reply)
            self.assertEqual(rc, 3, reply)
            self.assertIn("NOT AN APPROVAL", out)
        self.assertFalse(gates.is_open("REQ-300", "SDLC_01_INTAKE_CLARIFICATION"))

    def test_approved_any_case_opens_gate(self):
        self.present()
        rc, _ = self.quiet(gates.decide, "REQ-300", "SDLC_01_INTAKE_CLARIFICATION", OWNER_NAME, "APPROVED looks fine")
        self.assertEqual(rc, 0)
        self.assertTrue(gates.is_open("REQ-300", "SDLC_01_INTAKE_CLARIFICATION"))

    def test_rejected_records_rework(self):
        self.present()
        rc, _ = self.quiet(gates.decide, "REQ-300", "SDLC_01_INTAKE_CLARIFICATION", OWNER_NAME, "rejected: AC 3 wrong")
        self.assertEqual(rc, 0)
        rec = gates.get_phase(session_store.read_approvals("REQ-300"), "SDLC_01_INTAKE_CLARIFICATION")
        self.assertEqual(rec["decision"], "rejected")
        self.assertFalse(gates.is_open("REQ-300", "SDLC_01_INTAKE_CLARIFICATION"))

    def test_partial_items_leave_gate_pending(self):
        self.present()
        rc, _ = self.quiet(gates.decide, "REQ-300", "SDLC_01_INTAKE_CLARIFICATION", OWNER_NAME, "approved", items=[1])
        rec = gates.get_phase(session_store.read_approvals("REQ-300"), "SDLC_01_INTAKE_CLARIFICATION")
        if len(rec["decision_items"]) > 1:
            self.assertEqual(rec["decision"], "needs_revision")
            self.assertFalse(gates.is_open("REQ-300", "SDLC_01_INTAKE_CLARIFICATION"))

    def test_item_by_item_reply_one_rejected_rejects_the_gate(self):
        self.present(gate="SDLC_02_GAP_ANALYSIS_REVIEW")
        data = session_store.read_approvals("REQ-300")
        rec = gates.get_phase(data, "SDLC_02_GAP_ANALYSIS_REVIEW")
        rec["decision_items"] = [{"n": n, "text": "item %d" % n, "state": "pending", "by": None, "note": None} for n in (1, 2, 3, 4)]
        session_store.write_approvals("REQ-300", data)
        rc, _ = self.quiet(gates.decide, "REQ-300", "SDLC_02_GAP_ANALYSIS_REVIEW", OWNER_NAME,
                           "rejected SDLC_02_GAP_ANALYSIS_REVIEW — approved 1,2,4; rejected 3 — gap missing")
        self.assertEqual(rc, 0)
        rec = gates.get_phase(session_store.read_approvals("REQ-300"), "SDLC_02_GAP_ANALYSIS_REVIEW")
        self.assertEqual([i["state"] for i in rec["decision_items"]], ["approved", "approved", "rejected", "approved"])
        self.assertEqual(rec["decision"], "rejected")
        self.assertIsNone(rec["next_gate"])
        self.assertFalse(gates.is_open("REQ-300", "SDLC_02_GAP_ANALYSIS_REVIEW"))

    def test_item_decisions_reads_each_item(self):
        self.assertEqual(gates.item_decisions("rejected SDLC_02_X — approved 1,2 and 4; rejected 3 — no"),
                         {1: "approved", 2: "approved", 4: "approved", 3: "rejected"})
        self.assertEqual(gates.item_decisions("approved SDLC_01_INTAKE_CLARIFICATION"), {})


class GateModeTests(Sandbox):
    GATE = "SDLC_06_QA_SIGNOFF"   # the requester is neither QA nor a lead

    def setUp(self):
        super().setUp()
        gate = gates.gate_defs()[self.GATE]
        self.owner = next(p for p in gates.people() if p.get("email") and p["name"] != NOT_OWNER_NAME
                          and not gates.holds_role(p, gate))
        os.environ["SDLC_OWNER"] = session_store.slug(self.owner["email"])
        session_store.session_dir("REQ-400", create=True)
        gates.present("REQ-400", self.GATE, story_id="STORY-1")

    def test_dev_mode_owner_self_signs_and_is_recorded(self):
        rc, out = self.quiet(gates.decide, "REQ-400", self.GATE, self.owner["name"], "approved", story_id="STORY-1")
        self.assertEqual(rc, 0)
        self.assertIn("self-signed", out)
        rec = gates.get_phase(session_store.read_approvals("REQ-400"), self.GATE, "STORY-1")
        self.assertTrue(rec["self_signed"])
        self.assertTrue(rec["role_mismatch"])

    def test_dev_mode_non_owner_without_role_is_refused(self):
        rc, out = self.quiet(gates.decide, "REQ-400", self.GATE, NOT_OWNER_NAME, "approved", story_id="STORY-1")
        self.assertEqual(rc, 4)
        self.assertIn("NOT ALLOWED", out)

    def test_dev_mode_unknown_person_is_refused(self):
        rc, _ = self.quiet(gates.decide, "REQ-400", self.GATE, "Nobody, Real", "approved", story_id="STORY-1")
        self.assertEqual(rc, 4)

    def test_enforced_mode_owner_cannot_self_sign(self):
        os.environ["SDLC_GATE_MODE"] = "enforced"
        rc, _ = self.quiet(gates.decide, "REQ-400", self.GATE, self.owner["name"], "approved", story_id="STORY-1")
        self.assertEqual(rc, 4)

    def test_enforced_mode_role_holder_signs(self):
        os.environ["SDLC_GATE_MODE"] = "enforced"
        gate = gates.gate_defs()[self.GATE]
        holder = next((p for p in gates.people() if gates.holds_role(p, gate)), None)
        self.assertIsNotNone(holder, "roster has nobody for %s" % self.GATE)
        rc, _ = self.quiet(gates.decide, "REQ-400", self.GATE, holder["name"], "approved", story_id="STORY-1")
        self.assertEqual(rc, 0)
        rec = gates.get_phase(session_store.read_approvals("REQ-400"), self.GATE, "STORY-1")
        self.assertFalse(rec["self_signed"])

    def test_enforced_mode_lead_signs_any_gate(self):
        os.environ["SDLC_GATE_MODE"] = "enforced"
        lead = gates.find_person(OWNER_NAME)
        self.assertTrue(any("lead" in r for r in lead["roles"]))
        rc, _ = self.quiet(gates.decide, "REQ-400", self.GATE, OWNER_NAME, "approved", story_id="STORY-1")
        self.assertEqual(rc, 0)
        self.assertTrue(gates.is_open("REQ-400", self.GATE, story_id="STORY-1"))


class NoSelfApprovalTests(Sandbox):
    GATE = "SDLC_05_CODE_REVIEW"

    def setUp(self):
        super().setUp()
        session_store.session_dir("REQ-410", create=True)
        gates.present("REQ-410", self.GATE, story_id="STORY-1")
        self.assertIn(self.GATE, access_guard.no_self_approval(gates.load_yaml(gates.PEOPLE_PATH)))

    def test_requester_cannot_sign_code_review_even_in_dev_mode(self):
        rc, out = self.quiet(gates.decide, "REQ-410", self.GATE, OWNER_NAME, "approved", story_id="STORY-1")
        self.assertEqual(rc, 4)
        self.assertIn("asked for this change", out)

    def test_owner_given_as_email_cannot_sign_code_review(self):
        owner = gates.find_person(OWNER_NAME)
        os.environ["SDLC_OWNER"] = owner["email"]
        session_store.session_dir("REQ-411", create=True)
        gates.present("REQ-411", self.GATE, story_id="STORY-1")
        rc, out = self.quiet(gates.decide, "REQ-411", self.GATE, OWNER_NAME, "approved", story_id="STORY-1")
        self.assertEqual(rc, 4)
        self.assertIn("asked for this change", out)

    def test_recorded_requester_cannot_sign_code_review_in_cloud(self):
        # Devin Cloud: the session owner is the service account; /identify-requester names the person.
        owner = gates.find_person(OWNER_NAME)
        os.environ["SDLC_OWNER"] = "devin-service-account"
        session_store.session_dir("REQ-412", create=True)
        gates.present("REQ-412", self.GATE, story_id="STORY-1")
        recorded = os.path.join(self.home, "requester.json")
        with open(recorded, "w", encoding="utf-8") as fh:
            json.dump({"email": owner["email"]}, fh)
        with mock.patch.object(access_guard, "_requester_path", lambda: recorded):
            rc, out = self.quiet(gates.decide, "REQ-412", self.GATE, OWNER_NAME, "approved", story_id="STORY-1")
        self.assertEqual(rc, 4)
        self.assertIn("asked for this change", out)

    def test_another_developer_signs_code_review(self):
        gate = gates.gate_defs()[self.GATE]
        holder = next(p for p in gates.people() if gates.holds_role(p, gate) and p["name"] != OWNER_NAME)
        rc, _ = self.quiet(gates.decide, "REQ-410", self.GATE, holder["name"], "approved", story_id="STORY-1")
        self.assertEqual(rc, 0)

    def test_unverified_roster_blocks_every_sign_off(self):
        access_guard.verify_roster = lambda *a, **k: (False, "cannot read the roster page")
        rc, out = self.quiet(gates.decide, "REQ-410", self.GATE, NOT_OWNER_NAME, "approved", story_id="STORY-1")
        self.assertEqual(rc, 5)
        self.assertIn("roster is not verified", out)


class StageGatingTests(Sandbox):
    def test_precheck_reads_story_level_gates_for_the_named_story(self):
        for req, gate, cmd in (("REQ-506", "SDLC_04_ROUTING_APPROVAL", "/implement"),
                               ("REQ-507", "SDLC_07_ENV_PROMOTION_APPROVAL", "/kb-refresh")):
            session_store.session_dir(req, create=True)
            gates.present(req, gate, "STORY-1")
            gates.present(req, gate, "STORY-2")
            self.assertEqual(gates.precheck("%s %s STORY-1" % (cmd, req))[0], 2)
            self.assertEqual(self.quiet(gates.decide, req, gate, OWNER_NAME, "approved", "STORY-1")[0], 0)
            self.assertEqual(gates.precheck("%s %s STORY-1" % (cmd, req)), (0, None))
            self.assertEqual(gates.precheck("%s %s STORY-2" % (cmd, req))[0], 2)
            self.assertEqual(gates.precheck("%s %s" % (cmd, req))[0], 2)
            self.assertEqual(self.quiet(gates.decide, req, gate, OWNER_NAME, "approved", "STORY-2")[0], 0)
            self.assertEqual(gates.precheck("%s %s" % (cmd, req)), (0, None))

    def test_precheck_blocks_then_passes(self):
        session_store.session_dir("REQ-500", create=True)
        gates.present("REQ-500", "SDLC_01_INTAKE_CLARIFICATION")
        rc, msg = gates.precheck("/research REQ-500")
        self.assertNotEqual(rc, 0)
        self.assertIn("GATE-BLOCK", msg)
        self.quiet(gates.decide, "REQ-500", "SDLC_01_INTAKE_CLARIFICATION", OWNER_NAME, "approved")
        rc, msg = gates.precheck("/research REQ-500")
        self.assertEqual((rc, msg), (0, None))

    def test_hand_written_approval_does_not_open_a_gate(self):
        req, gate = "REQ-502", "SDLC_01_INTAKE_CLARIFICATION"
        session_store.session_dir(req, create=True)
        gates.present(req, gate)
        at = "2026-10-16T00:00:00Z"
        for edit in ({"status": "approved"},
                     {"status": "approved", "signed_by": OWNER_NAME, "signed_at": at, "decision_items": []},
                     {"status": "approved", "signed_by": "Nobody, Not On Roster", "signed_at": at,
                      "decision_items": [{"n": 1, "state": "approved", "by": "x"}]},
                     {"status": "approved", "signed_by": OWNER_NAME,
                      "decision_items": [{"n": 1, "state": "approved", "by": OWNER_NAME}]},
                     {"status": "approved", "signed_by": OWNER_NAME, "signed_at": at,
                      "decision_items": [{"n": 1, "state": "approved"}]}):
            data = session_store.read_approvals(req)
            phase = gates.get_phase(data, gate)
            phase.clear()
            phase.update(edit)
            session_store.write_approvals(req, data)
            self.assertFalse(gates.is_open(req, gate), edit)
            self.assertEqual(gates.precheck("/research " + req)[0], 2, edit)
        gates.present(req, gate)
        rc, _ = self.quiet(gates.decide, req, gate, OWNER_NAME, "approved")
        self.assertEqual(rc, 0)
        self.assertTrue(gates.is_open(req, gate))

    def test_signer_must_hold_the_gate_role(self):
        req, gate = "REQ-504", "SDLC_06_QA_SIGNOFF"
        session_store.session_dir(req, create=True)
        gates.present(req, gate)
        defs = gates.gate_defs()[gate]
        holder = next(p["name"] for p in gates.people() if gates.holds_role(p, defs))
        other = next(p["name"] for p in gates.people() if not gates.holds_role(p, defs))

        def write(by, **extra):
            data = session_store.read_approvals(req)
            phase = gates.get_phase(data, gate)
            phase.clear()
            phase.update(status="approved", signed_by=by, signed_at="2026-10-16T00:00:00Z",
                         decision_items=[{"n": 1, "state": "approved", "by": by}], **extra)
            session_store.write_approvals(req, data)
            return gates.is_open(req, gate)

        os.environ["SDLC_GATE_MODE"] = "enforced"
        self.assertFalse(write(other))
        self.assertFalse(write(other, self_signed=True))
        self.assertTrue(write(holder))
        os.environ["SDLC_GATE_MODE"] = "dev"
        self.assertFalse(write(other))
        self.assertTrue(write(other, self_signed=True))

    def test_plan_needs_backlog_and_estimation_gates(self):
        req = "REQ-503"
        session_store.session_dir(req, create=True)
        for gate in ("SDLC_03_BACKLOG_APPROVAL", "SDLC_03a_STORY_ESTIMATION_REVIEW"):
            gates.present(req, gate)
        self.assertEqual(self.quiet(gates.decide, req, "SDLC_03_BACKLOG_APPROVAL", OWNER_NAME, "approved")[0], 0)
        rc, msg = gates.precheck("/plan " + req)
        self.assertEqual(rc, 2)
        self.assertIn("SDLC_03a_STORY_ESTIMATION_REVIEW", msg)
        self.assertEqual(self.quiet(gates.decide, req, "SDLC_03a_STORY_ESTIMATION_REVIEW", OWNER_NAME, "approved")[0], 0)
        self.assertEqual(gates.precheck("/plan " + req), (0, None))

    def test_precheck_blocks_foreign_owner_requirement(self):
        os.makedirs(os.path.join(self.home, "someone-else", "REQ-501"))
        with open(os.path.join(self.home, "someone-else", "REQ-501", "approvals.yaml"), "w") as fh:
            fh.write("phases:\n  intake:\n    gate_id: SDLC_01_INTAKE_CLARIFICATION\n    status: approved\n")
        rc, msg = gates.precheck("/research REQ-501")
        self.assertNotEqual(rc, 0)
        self.assertIn("not a session of owner", msg)

    def test_flatten_handles_both_layouts(self):
        modern = {"phases": {"intake": {"gate_id": "SDLC_01_INTAKE_CLARIFICATION", "status": "approved"},
                             "stories": {"STORY-1": {"code_review": {"gate_id": "SDLC_05_CODE_REVIEW", "status": "pending"}}}}}
        legacy = {"approvals": [{"gate_id": "SDLC_03_BACKLOG_APPROVAL", "status": "approved"}]}
        m = gates.flatten_records(modern)
        self.assertEqual({r["gate_id"] for r in m}, {"SDLC_01_INTAKE_CLARIFICATION", "SDLC_05_CODE_REVIEW"})
        self.assertEqual([r["story_id"] for r in m if r["gate_id"] == "SDLC_05_CODE_REVIEW"], ["STORY-1"])
        self.assertEqual(gates.flatten_records(legacy)[0]["gate_id"], "SDLC_03_BACKLOG_APPROVAL")
        self.assertEqual(gates.flatten_records(None), [])


class NextActionTests(Sandbox):
    def test_unknown_requirement(self):
        info = gates.next_action("REQ-999")
        self.assertEqual(info["state"], "unknown")
        self.assertIn("/start", info["message"])

    def test_waiting_ready_and_rework(self):
        session_store.session_dir("REQ-600", create=True)
        self.assertEqual(gates.next_action("REQ-600")["state"], "started")
        gates.present("REQ-600", "SDLC_01_INTAKE_CLARIFICATION")
        info = gates.next_action("REQ-600")
        self.assertEqual(info["state"], "waiting")
        self.assertEqual(info["stage"], "intake")
        self.assertIn("dev mode", info["owner"])
        self.quiet(gates.decide, "REQ-600", "SDLC_01_INTAKE_CLARIFICATION", OWNER_NAME, "approved")
        info = gates.next_action("REQ-600")
        self.assertEqual(info["state"], "ready")
        self.assertEqual(info["stage"], "research")
        gates.present("REQ-600", "SDLC_03_BACKLOG_APPROVAL")
        self.quiet(gates.decide, "REQ-600", "SDLC_03_BACKLOG_APPROVAL", OWNER_NAME, "rejected scope too wide")
        info = gates.next_action("REQ-600")
        self.assertEqual(info["state"], "rework")
        self.assertIn("/research", info["message"])


class MetricsTests(Sandbox):
    def test_summary_counts_waits_rework_and_escalations(self):
        t0 = datetime(2026, 9, 1, 8, tzinfo=timezone.utc)
        metrics.record("stage_started", "REQ-700", stage="intake", at=iso(t0))
        metrics.record("gate_presented", "REQ-700", gate="SDLC_01_INTAKE_CLARIFICATION", at=iso(t0))
        metrics.record("gate_decided", "REQ-700", gate="SDLC_01_INTAKE_CLARIFICATION", decision="rejected",
                       approver="x", rework=True, at=iso(t0 + timedelta(hours=6)))
        metrics.record("gate_presented", "REQ-700", gate="SDLC_01_INTAKE_CLARIFICATION", at=iso(t0 + timedelta(hours=7)))
        metrics.record("gate_escalated", "REQ-700", gate="SDLC_01_INTAKE_CLARIFICATION", at=iso(t0 + timedelta(hours=40)))
        summ = metrics.summary(metrics.load())
        g = summ["gates"]["SDLC_01_INTAKE_CLARIFICATION"]
        self.assertEqual(g["presented"], 2)
        self.assertEqual(g["rejected"], 1)
        self.assertEqual(g["rework"], 1)
        self.assertEqual(g["escalated"], 1)
        self.assertAlmostEqual(g["avg_wait_hours"], 6.0, places=1)
        self.assertEqual(len(summ["waiting_now"]), 1)
        self.assertIn("REQ-700", summ["requirements"])
        self.assertIn("SDLC_01", metrics.render(summ))

    def test_metrics_file_is_owner_scoped(self):
        metrics.record("stage_started", "REQ-701", stage="intake")
        self.assertTrue(os.path.exists(os.path.join(self.home, OWNER_SLUG, "metrics.jsonl")))


class TimeoutTests(Sandbox):
    def test_overdue_gate_escalated_once_per_day_dry_run(self):
        session_store.session_dir("REQ-800", create=True)
        gates.present("REQ-800", "SDLC_04_ROUTING_APPROVAL", story_id="STORY-1")
        data = session_store.read_approvals("REQ-800")
        rec = gates.get_phase(data, "SDLC_04_ROUTING_APPROVAL", "STORY-1")
        rec["presented_at"] = iso(datetime.now(timezone.utc) - timedelta(hours=500))
        rec["approval_subtask"] = "ACME-1"
        session_store.write_approvals("REQ-800", data)

        (esc, skipped, _owner), out = self.quiet(gate_timeouts.sweep, live=False)
        self.assertIn("ACME-1/comment", out)
        self.assertEqual([e["gate"] for e in esc], ["SDLC_04_ROUTING_APPROVAL"])
        self.assertEqual(skipped, [])
        (esc2, skipped2, _), _ = self.quiet(gate_timeouts.sweep, live=False)
        self.assertEqual(esc2, [])
        self.assertEqual(len(skipped2), 1)
        rows = [r for r in metrics.load() if r["event"] == "gate_escalated"]
        self.assertEqual(len(rows), 1)

    def test_fresh_gate_not_escalated(self):
        session_store.session_dir("REQ-801", create=True)
        gates.present("REQ-801", "SDLC_01_INTAKE_CLARIFICATION")
        (esc, _, _), _ = self.quiet(gate_timeouts.sweep, live=False)
        self.assertEqual(esc, [])

    def test_jira_side_dry_run_writes_nothing(self):
        stamp = (datetime.now(timezone.utc) - timedelta(hours=400)).strftime("%Y-%m-%dT%H:%M:%S.000+0000")
        issues = [{"key": "ACME-77", "fields": {"created": stamp, "resolution": None,
                                                "labels": ["Approval", "gate-SDLC_05_CODE_REVIEW"],
                                                "summary": "Approve", "assignee": {"displayName": "Someone"}}}]
        calls = []

        class FakeClient:
            def live(self, method, path, payload=None, **params):
                calls.append((method, path))
                return {"issues": issues} if method == "GET" else {}

        (esc, skipped), out = self.quiet(gate_timeouts.sweep_jira, live=False, client=FakeClient())
        self.assertEqual([e["subtask"] for e in esc], ["ACME-77"])
        self.assertEqual(calls, [("GET", "/api/2/search")], "dry run must only read")
        self.assertIn("ACME-77/comment", out)
        self.assertEqual([r for r in metrics.load() if r["event"] == "gate_escalated"], [])

        calls.clear()
        (esc, _), _ = self.quiet(gate_timeouts.sweep_jira, live=True, client=FakeClient())
        self.assertEqual([c[0] for c in calls], ["GET", "POST", "PUT"])

        issues[0]["fields"]["labels"].append(gate_timeouts.ESCALATED_LABEL_PREFIX + datetime.now(timezone.utc).date().isoformat())
        (esc, skipped), _ = self.quiet(gate_timeouts.sweep_jira, live=True, client=FakeClient())
        self.assertEqual(esc, [])
        self.assertEqual(len(skipped), 1)


class DashboardTests(Sandbox):
    def test_pipeline_health_renders_from_fixture(self):
        session_store.session_dir("REQ-900", create=True)
        gates.present("REQ-900", "SDLC_05_CODE_REVIEW", story_id="STORY-1")
        summ = gen_dashboard.health_summary()
        self.assertIn("SDLC_05_CODE_REVIEW", summ["gates"])
        rows = gen_dashboard.load_session_records()
        self.assertTrue(any("REQ-900" in path for path, _ in rows))
        html = gen_dashboard.render_health({"kind": "health", "title": "Pipeline health"}, summ)["body"]
        self.assertIn("SDLC_05_CODE_REVIEW", html)
        self.assertIn("REQ-900", html)

    def test_roadmap_tab_opens_the_generated_roadmap_in_a_new_page(self):
        lens = gen_dashboard.lens_config()["lenses"]["tech_lead"]
        self.assertIn("roadmap", lens["panels"])
        page_path = os.path.join(self.home, "roadmap.html")
        with open(page_path, "w", encoding="utf-8") as fh:
            fh.write('<html><head><title>r</title></head><body>'
                     '<p>generated 2026-09-28</p><a href="x">Year plan</a></body></html>')
        spec = {"kind": "roadmap", "title": "Roadmap", "path": page_path}
        tab = gen_dashboard.render_roadmap(spec, gen_dashboard.roadmap_page(spec))
        self.assertEqual(tab["attention"], "info")
        self.assertNotIn("<iframe", tab["body"])
        self.assertIn("data-roadmap-open", tab["body"])
        self.assertIn("data-roadmap-refresh hidden", tab["body"])   # shown only on Argus's /dashboard
        self.assertIn('<script type="application/json" id="roadmap-doc">', tab["body"])
        self.assertIn("Year plan", tab["body"])
        self.assertNotIn("</body>", tab["body"])
        self.assertIn("as of 2026-09-28", tab["note"])
        missing = dict(spec, path=os.path.join(self.home, "absent.html"))
        empty = gen_dashboard.render_roadmap(missing, gen_dashboard.roadmap_page(missing))
        self.assertEqual(empty["attention"], "clear")
        self.assertIn("data-roadmap-refresh", empty["body"])
        self.assertIn("No roadmap has been generated yet", empty["body"])

    def test_tab_strip_groups_tabs_with_icon_and_short_label(self):
        hot = gen_dashboard.labelled(gen_dashboard.panel("Questions for me", "<p>q</p>", attention="hot"),
                                     "?", "Questions")
        clear = gen_dashboard.panel("Knowledge base behind the code", "")
        strip = gen_dashboard.render_tab_strip([hot, clear])
        self.assertLess(strip.index("Needs you"), strip.index("All clear"))
        self.assertIn('class="tab-switch"', strip)
        self.assertIn('aria-controls="tabgroup-1" aria-pressed="false"', strip)
        self.assertIn('id="tabgroup-1" role="none" data-attention="clear" hidden', strip)
        self.assertNotIn("a-dot", strip.split('role="tablist"')[1])
        self.assertNotIn("Waiting", strip)
        self.assertIn('<span class="tab-label">Questions</span>', strip)
        self.assertIn('aria-label="Questions for me"', strip)
        self.assertIn('<span class="tab-label">Knowledge base behind the code</span>', strip)
        panels = gen_dashboard.lens_config()["panels"]
        self.assertEqual([p for p, spec in panels.items() if not spec.get("tab") or not spec.get("icon")], [])


class RosterSyncTests(unittest.TestCase):
    OWNER = {"primary": "resource1", "backups": ["resource3"]}

    @staticmethod
    def comment(user, text, date):
        return {"body": {"storage": {"value": "<p>%s</p>" % text}},
                "history": {"createdBy": {"username": user}, "createdDate": date + "T10:00:00.000Z"}}

    def test_signoff_status_follows_who_signed(self):
        self.assertEqual(roster_sync.signoff_for(self.OWNER, "resource1", "2026-09-26")["status"], "signed")
        self.assertEqual(roster_sync.signoff_for(self.OWNER, "resource3", "2026-09-25")["status"], "interim")
        self.assertEqual(roster_sync.signoff_for(self.OWNER, "resource7", "2026-09-25"),
                         {"status": "pending", "signed_by": None, "signed_on": None})

    def test_confirmation_comment_names_signer_and_commit_and_is_not_reposted(self):
        data = {"people": [{"jira_user": "resource1", "name": "Resource 1"}]}
        signoff = {"status": "signed", "signed_by": "resource1", "signed_on": "2026-09-26"}
        text = roster_sync.confirmation_text(signoff, data, "abc1234", "feature/devin-sdlc")
        for needle in ("signed", "Resource 1", "resource1", "2026-09-26", "abc1234", "feature/devin-sdlc"):
            self.assertIn(needle, text)
        posted = [self.comment("ACME_CONFLUENCE_TOKEN", text, "2026-09-26")]
        self.assertTrue(roster_sync.already_confirmed(posted, "abc1234"))
        self.assertFalse(roster_sync.already_confirmed(posted, "def5678"))

    def test_owner_approved_comment_signs_the_roster(self):
        got = roster_sync.signoff_from_comments(self.OWNER, [
            self.comment("resource7", "approved", "2026-09-24"),          # not owner/backup: ignored
            self.comment("resource3", "Approved from my side", "2026-09-25"),
            self.comment("resource1", "looks good", "2026-09-26"),        # wrong word: ignored
        ])
        self.assertEqual((got["status"], got["signed_by"], got["signed_on"]), ("interim", "resource3", "2026-09-25"))
        got = roster_sync.signoff_from_comments(self.OWNER, [
            self.comment("resource3", "approved", "2026-09-25"),
            self.comment("resource1", "<strong>Approved</strong> - thanks", "2026-09-26"),
        ])
        self.assertEqual((got["status"], got["signed_by"], got["signed_via"]), ("signed", "resource1", "comment"))
        table = roster_sync.signoff_for(self.OWNER, "resource3", "2026-09-25")
        self.assertEqual(roster_sync.best_signoff(table, got)["status"], "signed")
        self.assertEqual(roster_sync.best_signoff(table, roster_sync.signoff_from_comments(self.OWNER, []))["status"],
                         "interim")

    def page(self, editor, when, signed_by):
        data, _text = roster_sync.load_people_file()
        owner = dict(data["owner"], primary="resource1", backups=["resource3"],
                     signoff={"status": "signed" if signed_by else "pending", "signed_by": signed_by,
                              "signed_on": "2026-09-25" if signed_by else None})
        return {"version": {"by": {"username": editor}, "when": when},
                "body": {"storage": {"value": roster_sync.render_page(dict(data, owner=owner))}}}

    def signed(self, page, comments=()):
        return roster_sync.page_signoff(page, roster_sync.parse_page(page["body"]["storage"]["value"]),
                                        list(comments))["status"]

    def test_signed_by_rows_count_only_when_the_signer_made_the_latest_edit(self):
        self.assertEqual(self.signed(self.page("resource1", "2026-09-25T11:42:25.000-04:00", "resource1")), "signed")
        self.assertEqual(self.signed(self.page("ACME_CONFLUENCE_TOKEN", "2026-10-05T09:00:00.000-04:00", "resource1")),
                         "pending")

    def test_an_approval_comment_counts_only_for_the_version_it_was_written_on(self):
        approve = self.comment("resource1", "Approve", "2026-09-25")      # 10:00Z = 06:00-04:00
        later = self.page("resource3", "2026-09-25T05:00:00.000-04:00", None)
        self.assertEqual(self.signed(later, [approve]), "signed")
        republished = self.page("ACME_CONFLUENCE_TOKEN", "2026-10-05T09:00:00.000-04:00", None)
        self.assertEqual(self.signed(republished, [approve]), "pending")
        self.assertEqual(self.signed(dict(republished, version={}), [approve]), "pending")

    def test_publish_resets_the_sign_off_on_the_page(self):
        args = roster_sync.argparse.Namespace(people=roster_sync.PEOPLE_PATH, live=False, page_id=None, parent="1")
        out = io.StringIO()
        with mock.patch.dict(os.environ, {roster_sync.TOKEN_ENV: "test-token"}), \
                mock.patch.object(roster_sync.ConfluenceClient, "find_page", return_value=None), \
                redirect_stdout(out):
            roster_sync.cmd_publish(args)
        printed = out.getvalue()
        self.assertIn("pending until the owner signs", printed)
        self.assertNotIn("<th>Owner sign-off</th><td>signed", printed)
        self.assertIn("<th>Owner sign-off</th><td>pending", printed)

    def test_render_parse_round_trip_preserves_local_fields(self):
        data, _text = roster_sync.load_people_file()
        page = roster_sync.render_page(data)
        parsed = roster_sync.parse_page(page)
        self.assertEqual(len(parsed["people"]), len(data["people"]))
        merged = roster_sync.merge(parsed, data)
        for local, back in zip(data["people"], merged["people"]):
            self.assertEqual(local.get("devin_user_id"), back.get("devin_user_id"))
            self.assertEqual(local.get("role_hints"), back.get("role_hints"))
            self.assertEqual(local["jira_user"], back["jira_user"])
        self.assertEqual(roster_sync.diff(parsed["people"], data["people"]), [])
        self.assertEqual(merged["owner"]["primary"], data["owner"]["primary"])

    def test_page_names_owner_and_signoff(self):
        data, _text = roster_sync.load_people_file()
        page = roster_sync.render_page(data)
        self.assertIn(roster_sync.name_of(data, data["owner"]["primary"]), page)
        self.assertIn("sign", page.lower())


class ValidatorTests(unittest.TestCase):
    def test_validator_and_manifest_pass(self):
        for cmd in (["validate_framework.py"], ["kb_manifest.py", "validate"]):
            r = subprocess.run([sys.executable, os.path.join(TOOLS, cmd[0])] + cmd[1:], cwd=ROOT,
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout[-2000:] + r.stderr[-2000:])



class KbManifestPortabilityTests(unittest.TestCase):
    def test_crlf_checkout_hashes_like_lf(self):
        import kb_manifest
        tmp = tempfile.mkdtemp(prefix="sdlc-kbm-test-")
        try:
            lf, crlf = os.path.join(tmp, "lf.md"), os.path.join(tmp, "crlf.md")
            with open(lf, "wb") as fh:
                fh.write(b"# Title\nline\n")
            with open(crlf, "wb") as fh:
                fh.write(b"# Title\r\nline\r\n")
            self.assertEqual(kb_manifest.sha256(lf), kb_manifest.sha256(crlf))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class HookConfigTests(unittest.TestCase):
    """.devin/hooks.v1.json must use Devin's documented format, or the guards never run."""
    EVENTS = {"PreToolUse", "PostToolUse", "PermissionRequest", "UserPromptSubmit", "Stop",
              "PostCompaction", "SessionStart", "SessionEnd"}

    def setUp(self):
        with open(os.path.join(ROOT, ".devin", "hooks.v1.json"), encoding="utf-8") as fh:
            self.config = json.load(fh)

    def test_events_and_entries_have_the_documented_shape(self):
        self.assertTrue(set(self.config) <= self.EVENTS, set(self.config) - self.EVENTS)
        for event, entries in self.config.items():
            for entry in entries:
                self.assertIsInstance(entry.get("matcher", ""), str, event)
                for hook in entry["hooks"]:
                    self.assertEqual(hook["type"], "command", event)
                    script = re.search(r"\.devin/hooks/[\w.-]+\.sh", hook["command"]).group(0)
                    self.assertTrue(os.path.isfile(os.path.join(ROOT, script)), script)

    def test_file_guards_cover_every_file_tool_but_not_reads(self):
        guards = [e for e in self.config["PreToolUse"]
                  if any("write-access-guard" in h["command"] for h in e["hooks"])]
        self.assertEqual(len(guards), 1)
        matcher = re.compile(guards[0]["matcher"])
        for tool in ("write", "edit", "apply_patch", "notebook_edit"):
            self.assertTrue(matcher.search(tool), tool)
        for tool in ("read", "exec", "grep", "glob", "notebook_read"):
            self.assertFalse(matcher.search(tool), tool)
        commands = " ".join(h["command"] for h in guards[0]["hooks"])
        for script in ("pii-guard.sh", "no-hardcoded-secrets.sh"):
            self.assertIn(script, commands)

    def test_shell_guard_covers_shell_tools_only(self):
        guards = [e for e in self.config["PreToolUse"]
                  if any("shell-bypass-guard" in h["command"] for h in e["hooks"])]
        self.assertEqual(len(guards), 1)
        matcher = re.compile(guards[0]["matcher"])
        for tool in ("exec", "Bash"):
            self.assertTrue(matcher.search(tool), tool)
        for tool in ("write", "edit", "read", "exec_output"):
            self.assertFalse(matcher.search(tool), tool)

    def test_stage_gate_check_runs_on_every_prompt(self):
        commands = [h["command"] for e in self.config["UserPromptSubmit"] for h in e["hooks"]]
        self.assertTrue(any("gate-phase-advance-check.sh" in c for c in commands))


class LineEndingTests(unittest.TestCase):
    """A Windows checkout gets CRLF line endings unless .gitattributes says otherwise; bash fails on them."""

    def test_bash_scripts_check_out_with_lf(self):
        import shutil
        import subprocess
        framework = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        if not shutil.which("git") or subprocess.run(["git", "-C", ROOT, "rev-parse"], capture_output=True).returncode:
            self.skipTest("not a git checkout")
        files = []
        for top in (os.path.join(ROOT, ".devin", "hooks"), framework):
            for base, _, names in os.walk(top):
                files += [os.path.join(base, n) for n in names
                          if n.endswith(".sh") or os.path.basename(base) == "git" and "hooks" in base]
        self.assertTrue(files)
        out = subprocess.run(["git", "check-attr", "eol", "--"] + files, cwd=ROOT, capture_output=True,
                             text=True).stdout.splitlines()
        self.assertEqual(len(out), len(files))
        for line in out:
            self.assertTrue(line.endswith(": eol: lf"), line)


if __name__ == "__main__":
    unittest.main()
