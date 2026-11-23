import datetime
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import notify  # noqa: E402


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def rmtree(path):
    def onerror(func, p, _):
        os.chmod(p, 0o700)
        func(p)
    shutil.rmtree(path, onerror=onerror)


class Fake(object):
    """A local webhook receiver: records every request; `code` is what it answers."""
    def __init__(self, code=200):
        self.got, self.code = [], code
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                outer.got.append({"path": self.path, "body": json.loads(self.rfile.read(n).decode("utf-8")),
                                  "ctype": self.headers.get("Content-Type")})
                self.send_response(outer.code)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"ok")

            def log_message(self, *a):
                pass

        self.srv = HTTPServer(("127.0.0.1", 0), H)
        self.url = "http://127.0.0.1:%d/hook/SECRETPART" % self.srv.server_address[1]
        self.t = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.t.start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.t.join(5)


class FakeSMTP(object):
    instances = []

    def __init__(self, host, port, security, timeout):
        self.args, self.log, self.messages = (host, port, security), [], []
        FakeSMTP.instances.append(self)

    def starttls(self):
        self.log.append("starttls")

    def login(self, user, password):
        self.log.append(("login", user, password))

    def send_message(self, msg):
        self.messages.append(msg)

    def quit(self):
        self.log.append("quit")


PROFILE = {"product": {"name": "Pets"}, "owners": {"kb_owner": "Ana Lead"}, "notify": {
    "base_url": "http://metis.local:8765",
    "channels": [
        {"name": "slack", "kind": "slack", "url_env": "T_SLACK", "events": ["pending_certification", "open_question_raised"],
         "min_interval": 60},
        {"name": "teams", "kind": "teams", "url_env": "T_TEAMS", "events": ["devin_task_queued"], "min_interval": 0},
        {"name": "hook", "kind": "webhook", "url_env": "T_HOOK", "min_interval": 0},
        {"name": "mail", "kind": "email", "url_env": "T_SMTP_PW", "host": "smtp.example.com", "port": 587, "user": "metis@example.com",
         "from": "metis@example.com", "to": ["leads@example.com", "second@example.com"], "events": ["pending_certification"],
         "min_interval": 0},
    ]}}


class Notify(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.kb = os.path.join(self.d, "kb")
        self.profile(PROFILE)
        write(os.path.join(self.kb, "_PENDING", "2026-01-01-docs", "claims", "x.md"), "# X\n")
        write(os.path.join(self.kb, "_PENDING", "2026-01-01-docs", "claims", "y.md.DELETE"), "")
        write(os.path.join(self.kb, "_PENDING", "2026-01-01-docs", "DIGEST.md"), "digest")
        write(os.path.join(self.kb, "_QUESTIONS", "VALIDATE_KB.yaml"), yaml.safe_dump({"questions": [
            {"id": "Q-0001", "status": "open", "priority": "P1", "type": "data", "answer_role": "data lead",
             "question": "SECRET QUESTION TEXT about retention?", "blocks": ["db/A.md"]},
            {"id": "Q-0002", "status": "answered", "priority": "P2", "type": "data", "question": "done", "answer": "x", "answered_by": "y"}]}))
        write(os.path.join(self.kb, ".metis", "tasks", "T-0001.yaml"), yaml.safe_dump(
            {"id": "T-0001", "kind": "build-stage", "status": "queued", "title": "Build", "instructions": "TASK TEXT"}))
        write(os.path.join(self.kb, ".metis", "tasks", "T-0002.yaml"), yaml.safe_dump(
            {"id": "T-0002", "kind": "ask", "status": "done", "title": "x", "instructions": "y"}))
        self.env = {}

    def tearDown(self):
        rmtree(self.d)

    def profile(self, prof):
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump(prof))

    def chan(self, name):
        return next(c for c in notify.channels(self.kb, self.env) if c["name"] == name)

    # ---- config
    def test_channels_read_profile_and_env_state_never_the_value(self):
        self.env = {"T_SLACK": "https://hooks.slack.com/services/T0/B0/XYZ"}
        rows = {c["name"]: c for c in notify.channels(self.kb, self.env)}
        self.assertEqual(set(rows), {"slack", "teams", "hook", "mail"})
        self.assertTrue(rows["slack"]["env_set"])
        self.assertFalse(rows["teams"]["env_set"])
        self.assertNotIn("hooks.slack.com", json.dumps(rows))
        self.assertEqual(rows["slack"]["events"], ["pending_certification", "open_question_raised"])
        self.assertEqual(rows["hook"]["events"], list(notify.EVENTS))

    def test_url_in_url_env_is_refused(self):
        prof = json.loads(json.dumps(PROFILE))
        prof["notify"]["channels"] = [{"name": "bad", "kind": "slack", "url_env": "https://hooks.slack.com/services/T0/B0/XYZ"},
                                      {"name": "odd", "kind": "fax", "url_env": "X", "events": ["nope"]}]
        self.profile(prof)
        bad, odd = notify.channels(self.kb, {})
        self.assertTrue(any("NAME of an environment variable" in p for p in bad["problems"]))
        self.assertEqual(bad["url_env"], "")
        self.assertTrue(any("kind must be" in p for p in odd["problems"]))
        self.assertTrue(any("unknown event" in p for p in odd["problems"]))
        r = notify.send(bad, "hello", dry_run=False, env={})
        self.assertFalse(r["sent"])
        self.assertNotIn("hooks.slack.com", json.dumps(r))

    # ---- events
    def test_events_from_existing_files(self):
        evs = notify.events_since(self.kb)
        by = {}
        for e in evs:
            by.setdefault(e["event"], []).append(e)
        self.assertEqual(len(by["pending_certification"]), 1)
        self.assertIn("2 files", by["pending_certification"][0]["text"])
        self.assertEqual(sorted(by["pending_certification"][0]["files"]), ["claims/x.md", "claims/y.md"])
        self.assertEqual([e["key"] for e in by["open_question_raised"]], ["question:Q-0001"])
        self.assertEqual([e["key"] for e in by["devin_task_queued"]], ["task:T-0001"])
        self.assertNotIn("review_overdue", by)
        self.assertNotIn("SECRET QUESTION TEXT", json.dumps(evs))
        self.assertNotIn("TASK TEXT", json.dumps(evs))

    def test_review_overdue_from_page_meta_when_present(self):
        write(os.path.join(self.kb, ".metis", "page_meta.yaml"), yaml.safe_dump({"pages": {
            "db/A.md": {"review_due": "2026-01-05"}, "db/B.md": {"review_due": "2999-01-01"}}}))
        evs = [e for e in notify.all_events(self.kb, datetime.date(2026, 2, 1)) if e["event"] == "review_overdue"]
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]["files"], ["db/A.md"])
        write(os.path.join(self.kb, ".metis", "page_meta.yaml"), yaml.safe_dump([{"page": "db/C.md", "review_by": "2026-01-01"}]))
        self.assertEqual(notify.overdue_pages(self.kb, datetime.date(2026, 2, 1))[0][0], "db/C.md")

    def test_build_failed_and_pr_events(self):
        write(os.path.join(self.kb, ".metis", "builds", "r1.yaml"), yaml.safe_dump(
            {"run": "2026-01-01-kb", "status": "running", "stages": [{"name": "db", "status": "failed"}, {"name": "etl:a", "status": "done"}]}))
        write(os.path.join(self.kb, ".metis", "tasks", "T-0003.yaml"), yaml.safe_dump(
            {"id": "T-0003", "kind": "build-stage", "status": "failed", "title": "x", "instructions": "y"}))
        write(os.path.join(self.kb, ".metis", "bb_pr_log.json"), json.dumps([{"pr": "42", "at": "2026-01-01T10:00:00", "action": "created",
                                                                                "files": 3, "objects": 5}]))
        evs = notify.all_events(self.kb)
        failed = [e["text"] for e in evs if e["event"] == "build_failed"]
        self.assertEqual(len(failed), 2)
        self.assertTrue(any("failed stage: db" in t for t in failed))
        self.assertTrue(any("T-0003" in t for t in failed))
        self.assertIn("PR 42", [e for e in evs if e["event"] == "pr_impact_posted"][0]["text"])

    def test_dedupe_state_and_dry_run_leaves_it_alone(self):
        self.env = {"T_SLACK": "http://127.0.0.1:9/x"}
        notify.run(self.kb, False, env=self.env)
        self.assertFalse(os.path.exists(os.path.join(self.kb, notify.STATE)))
        state = {"sent": {"slack": {"question:Q-0001": "t"}}, "last_sent": {}}
        keys = [e["key"] for e in notify.events_since(self.kb, state, "slack", wanted={"open_question_raised"})]
        self.assertEqual(keys, [])
        self.assertEqual(len(notify.events_since(self.kb, state, "other", wanted={"open_question_raised"})), 1)

    # ---- messages and the sensitive screen
    def test_messages_hold_names_counts_links_only(self):
        e = [x for x in notify.all_events(self.kb) if x["event"] == "open_question_raised"][0]
        m = notify.event_message(self.kb, e)
        self.assertIn("Q-0001 (P1, data) is open; blocks db/A.md", m)
        self.assertIn("http://metis.local:8765/questions", m)
        self.assertNotIn("SECRET QUESTION TEXT", m)

    def test_secret_in_message_is_withheld(self):
        text, kinds = notify.clean_message("fine line\npassword = hunter2hunter2\ncontact bob@example.com")
        self.assertNotIn("hunter2", text)
        self.assertNotIn("bob@example.com", text)
        self.assertIn("fine line", text)
        self.assertEqual(kinds, ["credential", "email address"])
        r = notify.send(self.chan("hook"), "password = hunter2hunter2", dry_run=True, env={})
        self.assertNotIn("hunter2", r["message"])
        self.assertEqual(r["withheld"], ["credential"])

    def test_digest_message(self):
        evs = notify.all_events(self.kb)
        m = notify.digest_message(self.kb, evs)
        self.assertTrue(m.startswith("[Metis Pets] 3 things need attention"))
        self.assertIn("Waiting for certification: 1", m)
        self.assertIn("Open questions: 1", m)
        self.assertEqual(m.count("\n[Metis"), 0)

    # ---- sending to a fake server
    def test_dry_run_sends_nothing(self):
        fake = Fake()
        try:
            self.env = {"T_SLACK": fake.url}
            rows = notify.run(self.kb, False, env=self.env)
            self.assertEqual(fake.got, [])
            slack = next(r for r in rows if r["channel"] == "slack")
            self.assertTrue(all(r["dry_run"] and not r["sent"] and r["ok"] for r in slack["results"]))
            self.assertIn("dry run", slack["results"][0]["status"])
            self.assertNotIn("SECRETPART", json.dumps(rows))
        finally:
            fake.close()

    def test_send_slack_teams_and_generic_webhook(self):
        fake = Fake()
        try:
            self.env = {"T_SLACK": fake.url, "T_TEAMS": fake.url + "t", "T_HOOK": fake.url + "h"}
            rows = {r["channel"]: r for r in notify.run(self.kb, True, env=self.env, now=1000.0)}
            by_path = {}
            for g in fake.got:
                by_path.setdefault(g["path"].rsplit("/", 1)[-1], []).append(g["body"])
            self.assertEqual(len(by_path["SECRETPART"]), 2)  # slack: pending + question, one message each
            self.assertTrue(all(set(b) == {"text"} for b in by_path["SECRETPART"]))
            teams = by_path["SECRETPARTt"][0]
            self.assertEqual(teams["type"], "message")
            self.assertEqual(teams["attachments"][0]["content"]["type"], "AdaptiveCard")
            self.assertIn("T-0001", teams["attachments"][0]["content"]["body"][0]["text"])
            hook = by_path["SECRETPARTh"]
            self.assertEqual(len(hook), 3)
            self.assertEqual({b["source"] for b in hook}, {"metis"})
            self.assertTrue(all(r["sent"] for r in rows["slack"]["results"]))
            self.assertNotIn("SECRETPART", json.dumps(rows))
            # a second run sends nothing: the keys are remembered
            n = len(fake.got)
            notify.run(self.kb, True, env=self.env, now=2000.0)
            self.assertEqual(len(fake.got), n)
            # a new question is a new event, but slack's min_interval (60 s) holds it back
            write(os.path.join(self.kb, "_QUESTIONS", "VALIDATE_KB.yaml"), yaml.safe_dump({"questions": [
                {"id": "Q-0001", "status": "open", "priority": "P1", "type": "data"},
                {"id": "Q-0003", "status": "open", "priority": "P2", "type": "data"}]}))
            held = {r["channel"]: r for r in notify.run(self.kb, True, env=self.env, now=1010.0)}
            self.assertIn("min_interval", held["slack"]["held"])
            self.assertEqual(len(fake.got), n + 1)  # the hook channel (no interval) sent it, slack did not
            again = {r["channel"]: r for r in notify.run(self.kb, True, env=self.env, now=1100.0)}
            self.assertEqual(again["slack"]["held"], "")
            self.assertEqual(len(fake.got), n + 2)
        finally:
            fake.close()

    def test_digest_mode_is_one_message(self):
        fake = Fake()
        try:
            self.env = {"T_HOOK": fake.url}
            rows = notify.run(self.kb, True, digest=True, only="hook", env=self.env)
            self.assertEqual(len(fake.got), 1)
            self.assertIn("3 things need attention", fake.got[0]["body"]["message"])
            self.assertEqual(len(fake.got[0]["body"]["events"]), 3)
            self.assertEqual(len(rows[0]["results"]), 1)
        finally:
            fake.close()

    def test_server_error_is_reported_and_not_remembered(self):
        fake = Fake(code=500)
        try:
            self.env = {"T_HOOK": fake.url}
            rows = notify.run(self.kb, True, only="hook", env=self.env)
            self.assertTrue(all(not r["ok"] and "HTTP 500" in r["status"] for r in rows[0]["results"]))
            self.assertNotIn("SECRETPART", json.dumps(rows))
            self.assertEqual(notify.load_state(self.kb)["sent"], {})
        finally:
            fake.close()

    def test_unset_env_and_unsafe_url(self):
        r = notify.send(self.chan("hook"), "hi", dry_run=False, env={})
        self.assertFalse(r["ok"])
        self.assertIn("T_HOOK is not set", r["status"])
        r = notify.send(self.chan("hook"), "hi", dry_run=False, env={"T_HOOK": "http://hooks.example.com/x"})
        self.assertIn("must be https", r["status"])
        self.assertNotIn("hooks.example.com", r["status"])
        r = notify.send(self.chan("hook"), "hi", dry_run=False, env={"T_HOOK": "http://127.0.0.1:1/x"})  # closed port
        self.assertFalse(r["ok"])
        self.assertNotIn("127.0.0.1", r["status"])

    # ---- email
    def test_email_through_fake_smtp(self):
        FakeSMTP.instances = []
        self.env = {"T_SMTP_PW": "s3cretpw"}
        rows = notify.run(self.kb, True, only="mail", env=self.env, smtp_factory=FakeSMTP)
        self.assertEqual(len(FakeSMTP.instances), 1)
        s = FakeSMTP.instances[0]
        self.assertEqual(s.args, ("smtp.example.com", 587, "starttls"))
        self.assertEqual(s.log[:2], ["starttls", ("login", "metis@example.com", "s3cretpw")])
        self.assertEqual(s.log[-1], "quit")
        msg = s.messages[0]
        self.assertEqual(msg["To"], "leads@example.com, second@example.com")
        self.assertIn("2 files waiting", msg.get_content())
        self.assertNotIn("s3cretpw", msg.as_string())
        self.assertNotIn("s3cretpw", json.dumps(rows))
        self.assertTrue(rows[0]["results"][0]["sent"])

    def test_email_dry_run_and_missing_password(self):
        FakeSMTP.instances = []
        r = notify.send(self.chan("mail"), "hi", dry_run=True, env={}, smtp_factory=FakeSMTP)
        self.assertTrue(r["ok"] and not r["sent"])
        self.assertEqual(FakeSMTP.instances, [])
        r = notify.send(self.chan("mail"), "hi", dry_run=False, env={}, smtp_factory=FakeSMTP)
        self.assertIn("T_SMTP_PW", r["status"])
        self.assertFalse(r["sent"])

    # ---- cli
    def test_cli(self):
        self.assertEqual(notify.main(["channels", self.kb]), 0)
        self.assertEqual(notify.main(["events", self.kb, "--channel", "slack"]), 0)
        self.assertEqual(notify.main(["run", self.kb]), 0)
        self.assertEqual(notify.main(["test", self.kb, "--channel", "nope"]), 2)
        self.assertEqual(notify.main(["test", self.kb, "--channel", "hook"]), 0)  # dry run, env not set: ok


if __name__ == "__main__":
    unittest.main()
