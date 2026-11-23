import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
for _p in (TOOLS, os.path.join(TOOLS, "ui")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import build_plan  # noqa: E402
import screens_notify as S  # noqa: E402
import tasks  # noqa: E402
import ui_common as C  # noqa: E402


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def rmtree(path):
    def onerror(func, p, _):
        os.chmod(p, 0o700)
        func(p)
    shutil.rmtree(path, onerror=onerror)


def git(repo, *args):
    subprocess.run(["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@example.com"] + list(args), capture_output=True, text=True, check=True)


class Hook(object):
    def __init__(self):
        self.got = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                outer.got.append(json.loads(self.rfile.read(n).decode("utf-8")))
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"ok")

            def log_message(self, *a):
                pass

        self.srv = HTTPServer(("127.0.0.1", 0), H)
        self.url = "http://127.0.0.1:%d/hooks/PRIVATEPART" % self.srv.server_address[1]
        self.t = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.t.start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.t.join(5)


class NotifyUiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.kb = os.path.join(self.tmp, "kb")
        self.repo = os.path.join(self.tmp, "src", "api")
        write(os.path.join(self.repo, "A.java"), "one\nclass Orders\n")
        git(self.repo, "init", "-q")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-q", "-m", "first")
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump({
            "product": {"name": "Pets"}, "owners": {"kb_owner": "Ana Lead"},
            "sources": {"workspace_root": os.path.join(self.tmp, "src"), "repos": {"api": "api"}},
            "notify": {"channels": [{"name": "hook", "kind": "webhook", "url_env": "UI_T_HOOK", "min_interval": 0},
                                    {"name": "bad", "kind": "slack", "url_env": "https://hooks.slack.com/services/T/B/X"}]},
            "bitbucket": {"flavor": "server", "base_url": "http://127.0.0.1:1", "project": "P", "repo": "api", "token_env": "UI_T_BB"}}))
        write(os.path.join(self.kb, "db", "ORDERS.md"), '# ORDERS\n\nOrders. [E: api/A.java:2 "class Orders"]\n')
        write(os.path.join(self.kb, "_QUESTIONS", "VALIDATE_KB.yaml"), yaml.safe_dump({"questions": [
            {"id": "Q-0001", "status": "open", "priority": "P1", "type": "data", "question": "PRIVATE QUESTION WORDS", "blocks": ["db/ORDERS.md"]}]}))
        build_plan.record(self.kb)
        write(os.path.join(self.repo, "A.java"), "one\nclass Orders changed\n")
        git(self.repo, "commit", "-q", "-am", "edit")
        self.lead = C.Ctx(self.kb, "tok", "Ana Lead")
        self.pat = C.Ctx(self.kb, "tok", "Pat Lee")
        self.anon = C.Ctx(self.kb, "tok", "")
        os.environ.pop("UI_T_HOOK", None)
        os.environ.pop("UI_T_BB", None)
        self.addCleanup(lambda: (os.environ.pop("UI_T_HOOK", None), os.environ.pop("UI_T_BB", None)))

    def tearDown(self):
        rmtree(self.tmp)

    def test_module_contract(self):
        self.assertIn("/notify", S.SCREENS)
        self.assertEqual(S.NAV, [("/notify", "Notifications")])
        self.assertEqual(set(S.ACTIONS), {"/notify/send", "/notify/refresh"})
        for screen, _ in S.ACTIONS.values():
            self.assertIn(screen, S.SCREENS)

    def test_page_shows_channels_events_and_never_a_url_or_question_text(self):
        os.environ["UI_T_HOOK"] = "http://127.0.0.1:9/hooks/PRIVATEPART"
        html = S.notify_view(self.lead, {})
        self.assertIn("<code>UI_T_HOOK</code>", html)
        self.assertIn("set</span>", html)
        self.assertNotIn("PRIVATEPART", html)
        self.assertNotIn("hooks.slack.com", html)
        self.assertIn("NAME of an environment variable", html)  # the bad channel's problem
        self.assertIn("Q-0001 (P1, data) is open", html)
        self.assertNotIn("PRIVATE QUESTION WORDS", html)
        self.assertIn("Send a test for real", html)

    def test_non_lead_sees_no_real_send_button(self):
        html = S.notify_view(self.pat, {})
        self.assertNotIn("Send a test for real", html)
        self.assertNotIn("Send new events for real", html)
        self.assertIn("Send test message (dry run)", html)
        self.assertIn("Only a lead can send for real", html)

    def test_dry_run_test_message_sends_nothing(self):
        hook = Hook()
        try:
            os.environ["UI_T_HOOK"] = hook.url
            html = S.notify_view(self.pat, {"test": "hook"})
            self.assertIn("dry run, nothing was sent", html)
            self.assertIn("Test message from channel hook", html)
            self.assertEqual(hook.got, [])
            self.assertNotIn("PRIVATEPART", html)
            self.assertIn("No channel called nope", S.notify_view(self.pat, {"test": "nope"}))
        finally:
            hook.close()

    def test_real_send_is_for_leads_only(self):
        hook = Hook()
        try:
            os.environ["UI_T_HOOK"] = hook.url
            for ctx in (self.pat, self.anon):
                with self.assertRaises(C.UiError):
                    S.act_send(ctx, {"channel": "hook", "what": "test"})
            self.assertEqual(hook.got, [])
            where, msg = S.act_send(self.lead, {"channel": "hook", "what": "test"})
            self.assertEqual(where, "/notify")
            self.assertEqual(len(hook.got), 1)
            self.assertIn("Test message from channel hook", hook.got[0]["message"])
            self.assertNotIn("PRIVATEPART", msg)
            where, msg = S.act_send(self.lead, {"channel": "hook", "what": "events"})
            self.assertIn("Sent", msg)
            self.assertGreaterEqual(len(hook.got), 2)
            n = len(hook.got)
            S.act_send(self.lead, {"channel": "hook", "what": "events"})  # same events are not sent again
            self.assertEqual(len(hook.got), n)
        finally:
            hook.close()

    def test_real_send_refuses_bad_channels_and_unset_env(self):
        with self.assertRaises(C.UiError) as e:
            S.act_send(self.lead, {"channel": "bad", "what": "test"})
        self.assertIn("problems", str(e.exception))
        with self.assertRaises(C.UiError) as e:
            S.act_send(self.lead, {"channel": "hook", "what": "test"})
        self.assertIn("UI_T_HOOK is not set", str(e.exception))
        with self.assertRaises(C.UiError):
            S.act_send(self.lead, {"channel": "nope", "what": "test"})

    def test_refresh_plan_viewer_and_trigger(self):
        self.assertIn("No refresh plan yet", S.notify_view(self.pat, {}))
        with self.assertRaises(C.UiError):
            S.act_refresh(self.anon, {})
        where, msg = S.act_refresh(self.pat, {})
        self.assertIn("1 stale page", msg)
        html = S.notify_view(self.pat, {})
        self.assertIn("db/ORDERS.md", html)
        self.assertIn("api/A.java changed", html)
        self.assertEqual(tasks.all_tasks(self.kb), [])
        self.assertNotIn('name="task"', html)  # only a lead sees the task box
        self.assertIn('name="task"', S.notify_view(self.lead, {}))

    def test_task_is_for_leads_only_and_uses_the_queue(self):
        with self.assertRaises(C.UiError):
            S.act_refresh(self.pat, {"task": "1"})
        self.assertEqual(tasks.all_tasks(self.kb), [])
        where, msg = S.act_refresh(self.lead, {"task": "1"})
        self.assertIn("task T-0001", msg)
        t = tasks.get(self.kb, "T-0001")
        self.assertEqual((t["kind"], t["status"], t["created_by"]), ("build-stage", "queued", "Ana Lead"))
        self.assertIn("Task <code>T-0001</code>", S.notify_view(self.lead, {}))

    def test_pr_preview_is_a_dry_run(self):
        html = S.notify_view(self.pat, {"pr": "12", "files": "src/A.java"})
        self.assertIn("dry run", html)
        self.assertIn("Metis impact review for PR 12", html)
        self.assertIn("metis-pr-impact", html)
        self.assertNotIn("PRIVATE QUESTION WORDS", html)
        self.assertFalse(os.path.exists(os.path.join(self.kb, ".metis", "bb_pr_log.json")))
        self.assertIn("Needs your Bitbucket to verify", html)

    def test_pr_preview_without_token_and_files_explains(self):
        html = S.notify_view(self.pat, {"pr": "12"})
        self.assertIn("UI_T_BB is not set", html)

    def test_page_escapes_input(self):
        html = S.notify_view(self.pat, {"pr": "<script>alert(1)</script>", "test": "<b>x</b>"})
        self.assertNotIn("<script>alert(1)", html)
        self.assertNotIn("<b>x</b>", html)


if __name__ == "__main__":
    unittest.main()
