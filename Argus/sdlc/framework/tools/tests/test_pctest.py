"""Test on my PC (console/pctest.py) tests — stdlib only, a local bare repo as origin, a fake ACP agent.

    python3 -m unittest discover -s sdlc/framework/tools/tests -v
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from unittest import mock

CONSOLE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "console")
sys.path.insert(0, CONSOLE)

import pctest  # noqa: E402

BRANCH = "devin/ACME-1-trial"
SESSION = "https://example.invalid/sessions/" + "ab" * 16
FAKE_KEY = "-".join(["fake", "devin", "key", "for", "tests", "only"])

FAKE_ACP = textwrap.dedent('''
    import json, sys
    def out(m):
        sys.stdout.write(json.dumps(m) + "\\n"); sys.stdout.flush()
    prompt_id = None
    for line in sys.stdin:
        m = json.loads(line)
        if m.get("method") == "initialize":
            out({"jsonrpc": "2.0", "id": m["id"], "result": {"protocolVersion": 1}})
        elif m.get("method") == "session/new":
            out({"jsonrpc": "2.0", "id": m["id"], "result": {"sessionId": "s-1"}})
        elif m.get("method") == "session/prompt":
            prompt_id = m["id"]
            out({"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": "s-1", "update": {
                "sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "Checking "}}}})
            out({"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": "s-1", "update": {
                "sessionUpdate": "tool_call", "toolCallId": "t1", "title": "git status", "status": "pending"}}})
            out({"jsonrpc": "2.0", "id": 99, "method": "session/request_permission", "params": {
                "sessionId": "s-1", "toolCall": {"toolCallId": "t1", "title": "git status"},
                "options": [{"optionId": "allow_once", "name": "Allow once", "kind": "allow_once"},
                            {"optionId": "reject_once", "name": "No", "kind": "reject_once"}]}})
        elif m.get("id") == 99:
            picked = m["result"]["outcome"].get("optionId")
            out({"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": "s-1", "update": {
                "sessionUpdate": "tool_call_update", "toolCallId": "t1", "status": "completed"}}})
            out({"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": "s-1", "update": {
                "sessionUpdate": "agent_message_chunk",
                "content": {"type": "text", "text": "you picked " + picked + ". Ready to return to Cloud"}}}})
            out({"jsonrpc": "2.0", "id": prompt_id, "result": {"stopReason": "end_turn"}})
''')


def git(cwd, *args):
    return subprocess.run(["git"] + list(args), cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def wait_for(fn, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        if fn():
            return True
        time.sleep(0.05)
    return False


class AcpAgentTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="sdlc-acp-")
        script = os.path.join(self.dir, "fake_acp.py")
        with open(script, "w") as fh:
            fh.write(FAKE_ACP)
        self.agent = pctest.AcpAgent(self.dir, command=[sys.executable, script])

    def tearDown(self):
        self.agent.stop()
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_prompt_permission_and_ready(self):
        self.assertEqual(self.agent.start(timeout=10), "s-1")
        self.agent.prompt("/test-on-pc pack.yaml", who="workbench")
        self.assertTrue(wait_for(lambda: self.agent.permissions))
        snap = self.agent.snapshot()
        self.assertTrue(snap["busy"])
        self.assertFalse(snap["ready"])
        perm = snap["permissions"][0]
        self.assertEqual(perm["title"], "git status")
        self.assertNotIn("rpc_id", perm)
        with self.assertRaises(pctest.PcError):
            self.agent.answer(perm["id"], "allow_always")
        self.agent.answer(perm["id"], "allow_once")
        self.assertTrue(wait_for(self.agent.ready))
        snap = self.agent.snapshot()
        self.assertEqual(snap["stop_reason"], "end_turn")
        self.assertEqual(snap["permissions"], [])
        devin = [t for t in snap["transcript"] if t["role"] == "devin"]
        self.assertIn("you picked allow_once", devin[-1]["text"])
        tool = [t for t in snap["transcript"] if t["role"] == "tool"][0]
        self.assertEqual(tool["status"], "completed")
        with self.assertRaises(pctest.PcError):
            self.agent.answer(perm["id"], "allow_once")

    def test_busy_agent_refuses_a_second_prompt(self):
        self.agent.start(timeout=10)
        self.agent.prompt("first")
        with self.assertRaises(pctest.PcError):
            self.agent.prompt("second")

    def test_missing_cli_is_a_clear_error(self):
        agent = pctest.AcpAgent(self.dir, command=[""])
        with self.assertRaises(pctest.PcError) as err:
            agent.start()
        self.assertIn("not installed", str(err.exception))


class FakeAgent:
    made = []

    def __init__(self, cwd, env=None):
        self.cwd, self.env = cwd, env
        self.prompts, self.busy, self.stopped, self.session_id = [], False, False, "s-1"
        FakeAgent.made.append(self)

    def start(self):
        return self.session_id

    def prompt(self, text, who="you"):
        self.prompts.append((who, text))

    def answer(self, request_id, option_id):
        self.answered = (request_id, option_id)

    def cancel(self):
        pass

    def stop(self):
        self.stopped = True

    def snapshot(self):
        return {"busy": self.busy, "prompts": len(self.prompts)}


class RecordingPcTests(pctest.PcTests):
    def __init__(self, key=FAKE_KEY):
        super().__init__(key_source=lambda: key, agent_factory=FakeAgent, threaded=False)
        self.calls = []

    def _evidence(self, t, *args):
        self.calls.append(args[:2] if args[0] == "control" else args[:1])
        return "ok %s" % args[0]


class PcTestsTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="sdlc-pctest-")
        self.origin = os.path.join(self.dir, "origin.git")
        seed = os.path.join(self.dir, "seed")
        git(self.dir, "init", "--bare", "-q", self.origin)
        git(self.dir, "init", "-q", seed)
        git(seed, "config", "user.email", "t@example.invalid")
        git(seed, "config", "user.name", "t")
        os.makedirs(os.path.join(seed, *pctest.PACK_DIR.split("/")))
        with open(os.path.join(seed, "app.txt"), "w") as fh:
            fh.write("v1\n")
        git(seed, "add", ".")
        git(seed, "commit", "-q", "-m", "code")
        code = git(seed, "rev-parse", "HEAD")
        pack = {"req_id": "REQ-1", "story_id": "STORY-1", "jira_key": "ACME-1", "branch": BRANCH, "commit": code,
                "cloud_session": SESSION, "acceptance": [{"id": "AC-1", "text": "works"}]}
        with open(os.path.join(seed, *pctest.PACK_DIR.split("/"), "REQ-1-STORY-1.json"), "w") as fh:
            json.dump(pack, fh)
        git(seed, "add", ".")
        git(seed, "commit", "-q", "-m", "pack")
        git(seed, "push", "-q", self.origin, "HEAD:refs/heads/" + BRANCH)
        git(seed, "push", "-q", self.origin, "HEAD~1:refs/heads/no-pack")
        self.env = mock.patch.dict(os.environ, {"SDLC_REPO_URL": self.origin,
                                                "SDLC_WORK_ROOT": os.path.join(self.dir, "work"),
                                                "SDLC_EVIDENCE_HOME": os.path.join(self.dir, "evidence"),
                                                "DEVIN_API_KEY": FAKE_KEY})
        self.env.start()
        FakeAgent.made = []
        self.pc = RecordingPcTests()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.dir, ignore_errors=True)

    def start(self, ticket="ACME-1", branch=BRANCH):
        return self.pc.start(ticket, branch, SESSION)

    def test_start_makes_the_folder_checks_out_and_starts_devin_local(self):
        t = self.start()
        self.assertEqual(t["state"], "testing", t)
        folder = os.path.join(self.dir, "work", "ACME-1", pctest.REPO_NAME)
        self.assertEqual(t["folder"], folder)
        self.assertEqual(git(folder, "branch", "--show-current"), BRANCH)
        self.assertEqual(t["pack"], pctest.PACK_DIR + "/REQ-1-STORY-1.json")
        self.assertEqual(t["session"], "devin-" + "ab" * 16)
        self.assertEqual(self.pc.calls, [("start",), ("control", "pc")])
        self.assertEqual(t["control"], "pc")
        agent = FakeAgent.made[0]
        who, text = agent.prompts[0]
        self.assertEqual(who, "workbench")
        self.assertTrue(text.startswith("/test-on-pc " + t["pack"]))
        self.assertIn("Do not run `pack`, `send` or `control`", text)
        self.assertNotIn("DEVIN_API_KEY", agent.env)
        self.assertNotIn("ACME_JIRA_TOKEN", agent.env)
        self.assertTrue(all(s["status"] == "done" for s in t["steps"]), t["steps"])

    def test_progress_follows_the_run(self):
        t = self.start()
        self.assertEqual(t["progress"]["phase"], "answers", t["progress"])
        self.assertEqual(t["progress"]["answers"], {"done": 0, "total": 1})
        self.assertIn("Waiting for you", t["progress"]["now"])
        self.assertNotIn("run_file", t)
        run_file = self.pc.tests[t["id"]]["run_file"]
        self.assertTrue(run_file.startswith(os.path.join(self.dir, "evidence")))
        os.makedirs(os.path.dirname(run_file))
        with open(run_file, "w") as fh:
            json.dump({"results": {"AC-1": {"status": "passed", "note": ""}}}, fh)
        self.assertEqual(self.pc.public(t["id"])["progress"]["answers"], {"done": 1, "total": 1})
        out = self.pc.return_to_cloud(t["id"])
        self.assertEqual(out["progress"]["phase"], "back")

    def test_progress_counts_checks_and_names_the_failure(self):
        t = {"state": "testing", "control": "pc", "check_ids": ["CHK-1", "CHK-2"], "ac_ids": ["AC-1"],
             "steps": [{"name": "Start Devin Local with /test-on-pc"}],
             "agent": {"busy": True, "transcript": [{"role": "tool", "text": "Ran py", "status": "in_progress"}]}}
        results = {"CHK-1": {"status": "passed", "note": "exit 0"},
                   "CHK-2": {"status": "not run", "note": "not attempted"}}
        p = pctest.progress(t, results)
        self.assertEqual((p["phase"], p["checks"]), ("checks", {"done": 1, "total": 2}))
        self.assertIn("Ran py", p["now"])
        results["CHK-2"] = {"status": "not run", "note": "missing on this PC: X"}
        self.assertEqual(pctest.progress(t, results)["phase"], "answers")
        t.update(state="failed", control="cloud", error="no pack\nmore", steps=[{"name": "Find the test pack"}])
        p = pctest.progress(t, {})
        self.assertEqual((p["phase"], p["failed"], p["now"]), ("code", True, "Stopped: no pack"))

    def test_return_to_cloud_packs_sends_and_hands_back(self):
        t = self.start()
        out = self.pc.return_to_cloud(t["id"])
        self.assertEqual(out["state"], "returned", out)
        self.assertEqual(out["control"], "cloud")
        self.assertEqual(self.pc.calls[2:], [("pack",), ("send",), ("control", "cloud")])
        self.assertTrue(FakeAgent.made[0].stopped)
        with self.assertRaises(pctest.PcError):
            self.pc.return_to_cloud(t["id"])

    def test_unpushed_commit_stops_the_return_and_keeps_control(self):
        t = self.start()
        git(t["folder"], "config", "user.email", "t@example.invalid")
        git(t["folder"], "config", "user.name", "t")
        with open(os.path.join(t["folder"], "app.txt"), "w") as fh:
            fh.write("v2\n")
        git(t["folder"], "commit", "-q", "-am", "local fix")
        out = self.pc.return_to_cloud(t["id"])
        self.assertEqual(out["state"], "failed")
        self.assertIn("not pushed", out["error"])
        self.assertEqual(out["control"], "pc")
        self.assertNotIn(("send",), self.pc.calls)
        released = self.pc.return_to_cloud(t["id"], release_only=True)
        self.assertEqual(released["state"], "returned")
        self.assertNotIn(("send",), self.pc.calls)

    def test_uncommitted_change_in_an_existing_folder_is_refused(self):
        t = self.start()
        self.pc.return_to_cloud(t["id"])
        with open(os.path.join(t["folder"], "app.txt"), "w") as fh:
            fh.write("edited\n")
        again = self.start()
        self.assertEqual(again["state"], "failed")
        self.assertIn("uncommitted changes", again["error"])

    def test_branch_without_a_pack_asks_cloud_for_one(self):
        t = self.start(branch="no-pack")
        self.assertEqual(t["state"], "failed")
        self.assertIn("/eval", t["error"])
        self.assertEqual(self.pc.calls, [])

    def test_inputs_are_checked_before_anything_runs(self):
        with self.assertRaises(pctest.PcError):
            self.pc.start("not a ticket", BRANCH, SESSION)
        with self.assertRaises(pctest.PcError):
            self.pc.start("ACME-1", "bad..branch", SESSION)
        with self.assertRaises(pctest.PcError):
            self.pc.start("ACME-1", "--upload-pack=x", SESSION)
        with self.assertRaises(pctest.PcError):
            self.pc.start("ACME-1", BRANCH, "no session here")
        with self.assertRaises(pctest.PcError) as err:
            RecordingPcTests(key="").start("ACME-1", BRANCH, SESSION)
        self.assertIn("API key", str(err.exception))
        self.assertEqual(self.pc.tests, {})

    def test_sibling_url_keeps_the_url_form(self):
        self.assertEqual(
            pctest.sibling_url("https://bitbucket.example/scm/ACME/claims-web.git", "ACME", "claims-qa"),
            "https://bitbucket.example/scm/ACME/claims-qa.git")
        self.assertEqual(pctest.redact_url("https://u:p@host/x"), "https://***@host/x")

    def test_key_comes_from_the_environment_first(self):
        self.assertEqual(pctest.load_key(), FAKE_KEY)
        if os.name != "nt":
            with self.assertRaises(pctest.PcError):
                pctest.save_key(FAKE_KEY)

    def test_lookup_fills_branch_session_and_pack_from_the_ticket(self):
        seed = os.path.join(self.dir, "seed")
        git(seed, "push", "-q", self.origin, "HEAD~1:refs/heads/devin/ACME-1-old-try")
        git(seed, "push", "-q", self.origin, "HEAD~1:refs/heads/devin/ACME-12-other")
        git(seed, "push", "-q", self.origin, "HEAD:refs/heads/devin/ACME-1-later")
        found = pctest.lookup("acme-1", sessions=lambda t: [])
        self.assertEqual([b["branch"] for b in found["branches"]],
                         ["devin/ACME-1-later", "devin/ACME-1-old-try", BRANCH])
        later = [b for b in found["branches"] if b["branch"] == "devin/ACME-1-later"][0]
        self.assertEqual(later["packs"], [], "a pack for another branch rode along and must not count")
        self.assertEqual(found["pick"]["branch"], BRANCH)
        self.assertEqual(found["pick"]["session"], SESSION)
        self.assertEqual(found["pick"]["session_from"], "test pack")
        packs = [b for b in found["branches"] if b["branch"] == BRANCH][0]["packs"]
        self.assertEqual(packs[0]["name"], "REQ-1-STORY-1.json")

    def test_lookup_falls_back_to_cloud_sessions_without_a_pack(self):
        seed = os.path.join(self.dir, "seed")
        git(seed, "push", "-q", self.origin, "HEAD~1:refs/heads/devin/ACME-7-x")
        cloud = [{"url": "https://example.invalid/sessions/" + "cd" * 16, "title": "ACME-7"}]
        found = pctest.lookup("ACME-7", sessions=lambda t: cloud)
        self.assertEqual(found["pick"]["branch"], "devin/ACME-7-x")
        self.assertEqual(found["pick"]["session"], cloud[0]["url"])
        self.assertEqual(found["pick"]["session_from"], "Devin Cloud")
        self.assertEqual(pctest.lookup("ACME-99")["branches"], [])
        with self.assertRaises(pctest.PcError):
            pctest.lookup("not a ticket")


if __name__ == "__main__":
    unittest.main()
