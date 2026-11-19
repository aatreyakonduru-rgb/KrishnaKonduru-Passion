"""Local Devin (console/local.py) tests — stdlib only, fake Devin, no network.

    python3 -m unittest discover -s sdlc/framework/tools/tests -v
"""
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from unittest import mock
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

HOME = tempfile.mkdtemp(prefix="sdlc-local-test-")
os.environ["SDLC_LOCAL_HOME"] = HOME
os.environ.setdefault("SDLC_CONSOLE_HOME", tempfile.mkdtemp(prefix="sdlc-workbench-test-"))
os.environ["SDLC_WORKBENCH_READ_REMOTE"] = "0"
CONSOLE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "console")
sys.path.insert(0, CONSOLE)

import local  # noqa: E402
import server as wb  # noqa: E402

ME = "resource3"
ATT = "609b5cae-6426-481a-b1cf-c2412ff3bcee"


class FakeDevin:
    key = "not-a-real-token-123"

    def __init__(self):
        self.created, self.sent, self.terminated, self.tagged = [], [], [], {}
        self.transcript = []
        self.mine = []
        self.tags = []
        self.downloads = []

    def create_session(self, prompt, title, tags):
        self.created.append({"prompt": prompt, "title": title, "tags": tags})
        return {"session_id": "devin-abcdef%02d" % len(self.created), "url": "https://example.invalid/s"}

    def session(self, devin_id):
        return {"status_enum": "working", "title": "t", "url": "https://example.invalid/s",
                "messages": list(self.transcript), "tags": list(self.tags)}

    def download(self, attachment_id, name):
        self.downloads.append((attachment_id, name))
        return b"<h1>dashboard from the cloud</h1>"

    def upload(self, path, name):
        with open(path, encoding="utf-8") as fh:
            self.uploaded = (name, fh.read())
        return "https://example.invalid/attachments/%s/%s" % (ATT, name)

    def send(self, devin_id, text):
        self.sent.append((devin_id, text))

    def sessions_of(self, email, limit=100):
        return list(self.mine)

    def list_sessions(self, tag, limit=50):
        return []

    def terminate(self, devin_id):
        self.terminated.append(devin_id)

    def set_tags(self, devin_id, tags):
        self.tagged[devin_id] = tags


def devin_says(text):
    return {"type": "devin_message", "message": text, "timestamp": "2026-01-01T00:00:00"}


class CommandTests(unittest.TestCase):
    def test_parse_command_splits_local_from_cloud(self):
        self.assertEqual(local.parse_command("/argus stop"), ("argus", "stop"))
        self.assertEqual(local.parse_command("/workbench stop"), ("workbench", "stop"))
        self.assertEqual(local.parse_command("  /dashboard  "), ("dashboard", ""))
        self.assertEqual(local.parse_command("/console"), ("console", ""))
        self.assertEqual(local.parse_command("/status ACME-1"), (None, "/status ACME-1"))
        self.assertEqual(local.parse_command("/workbenches"), (None, "/workbenches"))
        self.assertEqual(local.parse_command("fix the build"), (None, "fix the build"))

    def test_cloud_prompt_keeps_the_command_and_asks_for_artefacts(self):
        p = local.cloud_prompt("/status ACME-1")
        self.assertIn("/status ACME-1", p)
        self.assertIn(wb.REPO_SLUG, p)
        self.assertIn("[SDLC] artefact", p)

    def test_safe_name(self):
        self.assertEqual(local.safe_name("../../etc/passwd"), "etc_passwd")
        self.assertEqual(local.safe_name(""), "artefact")


class BoxTests(unittest.TestCase):
    def setUp(self):
        self.devin = FakeDevin()
        self.box = local.Box(self.devin, wb.find_person(ME), open_browser=False)
        self.box.seen = {}
        self.opened = []
        self.box.open_page = self.opened.append

    def test_other_commands_start_a_tagged_cloud_session_then_follow_up(self):
        r = self.box.command("/status ACME-1", "", "http://x")
        self.assertEqual(r["kind"], "created")
        self.assertEqual(self.devin.created[0]["tags"], [local.LOCAL_TAG])
        self.assertTrue(self.devin.created[0]["prompt"].startswith("Repository:"))
        r = self.box.command("and ACME-2", r["session_id"], "http://x")
        self.assertEqual(r["kind"], "sent")
        self.assertEqual(self.devin.sent, [("devin-abcdef01", "and ACME-2")])

    def test_local_commands_never_reach_devin(self):
        self.box.run_local = lambda name, arg, base: {"kind": "local", "name": name, "arg": arg}
        self.assertEqual(self.box.command("/dashboard tech_lead", "devin-abcdef01", "http://x")["arg"], "tech_lead")
        self.assertEqual(self.devin.created + self.devin.sent, [])

    def test_help_lists_local_commands(self):
        text = self.box.run_local("help", "", "http://x")["text"]
        for name in local.LOCAL_COMMANDS:
            self.assertIn("/" + name, text)

    def test_new_artefacts_open_once_in_the_local_browser(self):
        sid = self.box.command("make me a page", "", "http://x")["session_id"]
        self.devin.transcript = [devin_says("[SDLC] artefact report.html — ready\n```html\n<h1>hi</h1>\n```")]
        d = self.box.session(sid, "http://x")
        self.assertEqual(len(d["artefacts"]), 1)
        self.assertEqual(self.opened, [d["artefacts"][0]["url"]])
        path = os.path.join(local.ARTEFACT_DIR, sid, "00-report.html")
        with open(path, encoding="utf-8") as fh:
            self.assertIn("<h1>hi</h1>", fh.read())
        self.box.session(sid, "http://x")
        self.assertEqual(len(self.opened), 1)

    def test_old_sessions_do_not_pop_pages_when_first_viewed(self):
        self.devin.transcript = [devin_says("[SDLC] artefact a.md — ready\n```markdown\n# A\n```")]
        d = self.box.session("devin-oldsession1", "http://x")
        self.assertEqual(self.opened, [])
        self.assertEqual(d["opened"], [])
        self.devin.transcript.append(devin_says("[SDLC] artefact b.md — ready\n```markdown\n# B\n```"))
        self.box.session("devin-oldsession1", "http://x")
        self.assertEqual(len(self.opened), 1)
        self.assertTrue(self.opened[0].endswith("01-b.md"))

    def test_sessions_list_comes_from_devin_by_email(self):
        self.devin.mine = [{"session_id": "devin-a", "title": "A", "status_enum": "finished", "updated_at": "1",
                            "tags": ["closed"]},
                           {"session_id": "devin-b", "title": "B", "status_enum": "working", "updated_at": "2",
                            "tags": [local.LOCAL_TAG]}]
        out = self.box.sessions()
        self.assertEqual([s["session_id"] for s in out], ["devin-b", "devin-a"])
        self.assertTrue(out[0]["local"])
        self.assertTrue(out[1]["closed"])

    def test_close_terminates_and_tags(self):
        self.assertEqual(self.box.close("abcdef01"), "devin-abcdef01")
        self.assertEqual(self.devin.terminated, ["devin-abcdef01"])
        self.assertIn(wb.CLOSED_TAG, self.devin.tagged["devin-abcdef01"])

    def test_dashboard_needs_to_know_who_you_are(self):
        box = local.Box(self.devin, None, open_browser=False)
        with self.assertRaises(wb.ApiError):
            box.build_dashboard()

    def test_dashboard_is_built_in_devin_cloud_without_a_jira_key(self):
        with mock.patch.dict(os.environ, {local.JIRA_ENV: ""}), mock.patch.object(wb, "DASHBOARD_CACHE", ""):
            r = self.box.command("/dashboard delivery_lead", "", "http://x")
        self.assertEqual(r["kind"], "created")
        self.assertIn("Devin Cloud", r["text"])
        made = self.devin.created[-1]
        self.assertEqual(made["tags"], [local.LOCAL_TAG, local.DASHBOARD_TAG])
        self.assertIn("console/local.py --cloud-dashboard %s --lens delivery_lead" % ME, made["prompt"])
        self.assertNotIn(local.JIRA_ENV + "=", made["prompt"])

    def test_dashboard_is_built_here_with_a_jira_key(self):
        self.box.build_dashboard = lambda lens: local.DASHBOARD_PATH
        with mock.patch.dict(os.environ, {local.JIRA_ENV: "x"}), \
                mock.patch.object(local.importlib.util, "find_spec", return_value=object()):
            r = self.box.run_local("dashboard", "", "http://x")
        self.assertEqual(r["kind"], "local")
        self.assertEqual(self.devin.created, [])
        self.assertEqual(self.opened, ["http://x/dashboard"])

    def test_cloud_dashboard_opens_here_and_its_session_closes(self):
        with mock.patch.dict(os.environ, {local.JIRA_ENV: ""}), mock.patch.object(wb, "DASHBOARD_CACHE", ""):
            sid = self.box.command("/dashboard", "", "http://x")["session_id"]
        self.devin.tags = [local.LOCAL_TAG, local.DASHBOARD_TAG]
        self.devin.transcript = [devin_says("working on it")]
        self.box.session(sid, "http://x")
        self.assertEqual((self.opened, self.devin.terminated), ([], []))
        self.devin.transcript.append(devin_says(
            "[SDLC] attachment dashboard-%s.html — https://example.invalid/attachments/%s/dashboard-%s.html" % (ME, ATT, ME)))
        d = self.box.session(sid, "http://x")
        self.assertEqual(self.opened, ["http://x/attachment/%s/%s/dashboard-%s.html" % (sid, ATT, ME)])
        self.assertEqual(d["opened"], self.opened)
        self.assertEqual(self.devin.terminated, [sid])
        self.assertIn(wb.CLOSED_TAG, self.devin.tagged[sid])

    def test_attachments_are_found_in_both_message_forms(self):
        text = ('ATTACHMENT:{"url":"https://h/attachments/%s/ss_1.png","fileSize":1}\n'
                "[SDLC] attachment d.html — https://h/attachments/%s/d.html." % (ATT, ATT))
        self.assertEqual(local.attachments_in(text), [(ATT, "ss_1.png"), (ATT, "d.html")])
        self.assertEqual(local.attachments_in("https://h/attachments/not-a-uuid/x.html"), [])

    def test_attachment_is_downloaded_once(self):
        first = self.box.attachment("devin-abcdef01", ATT, "d.html")
        again = self.box.attachment("devin-abcdef01", ATT, "d.html")
        self.assertEqual(first, again)
        self.assertEqual(self.devin.downloads, [(ATT, "d.html")])
        with open(first, "rb") as fh:
            self.assertIn(b"from the cloud", fh.read())

    def test_cloud_side_builds_uploads_and_prints_the_line(self):
        def fake_build(box_self, lens=""):
            os.makedirs(local.STATE_DIR, exist_ok=True)
            with open(local.DASHBOARD_PATH, "w", encoding="utf-8") as fh:
                fh.write("<h1>%s</h1>" % lens)
            return local.DASHBOARD_PATH
        with mock.patch.object(local.Box, "build_dashboard", fake_build), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            self.assertEqual(local.cloud_dashboard(ME, "tech_lead", self.devin), 0)
        name = "dashboard-%s-tech_lead.html" % ME
        self.assertEqual(self.devin.uploaded, (name, "<h1>tech_lead</h1>"))
        self.assertEqual(local.attachments_in(out.getvalue()), [(ATT, name)])
        self.assertTrue(out.getvalue().startswith("[SDLC] attachment " + name))
        self.assertEqual(local.cloud_dashboard("nobody-on-the-roster", "", self.devin), 2)


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.devin = FakeDevin()
        local.Handler.box = local.Box(cls.devin, wb.find_person(ME), open_browser=False)
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), local.Handler)
        cls.base = "http://127.0.0.1:%d" % cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def call(self, method, path, body=None, header=True):
        req = urllib.request.Request(self.base + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None)
        req.add_header("Content-Type", "application/json")
        if header:
            req.add_header(local.CSRF_HEADER, "1")
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    def test_page_and_config(self):
        code, body = self.call("GET", "/")
        self.assertEqual(code, 200)
        self.assertIn(b"Local Devin", body)
        code, body = self.call("GET", "/api/config")
        cfg = json.loads(body)
        self.assertTrue(cfg["devin_configured"])
        self.assertEqual(cfg["user"]["jira_user"], ME)
        self.assertNotIn(FakeDevin.key, body.decode())

    def test_post_needs_the_local_header(self):
        before = len(self.devin.created)
        code, _ = self.call("POST", "/api/command", {"text": "hi"}, header=False)
        self.assertEqual(code, 403)
        self.assertEqual(len(self.devin.created), before)

    def test_command_round_trip(self):
        code, body = self.call("POST", "/api/command", {"text": "hello"})
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)["kind"], "created")
        code, _ = self.call("POST", "/api/command", {"text": "x", "session_id": "../../bad"})
        self.assertEqual(code, 400)

    def test_attachment_route_serves_the_download(self):
        code, body = self.call("GET", "/attachment/devin-abcdef01/%s/dash.html" % ATT)
        self.assertEqual(code, 200)
        self.assertIn(b"from the cloud", body)
        code, _ = self.call("GET", "/attachment/devin-abcdef01/not-a-uuid/dash.html")
        self.assertEqual(code, 404)
        code, _ = self.call("GET", "/attachment/devin-abcdef01/%s/..%%2Fseen.json" % ATT)
        self.assertEqual(code, 404)

    def test_view_rejects_path_tricks(self):
        code, _ = self.call("GET", "/view/devin-x/..%2F..%2Fseen.json")
        self.assertEqual(code, 404)
        code, _ = self.call("GET", "/repo?path=.devin/rules/people.yaml")
        self.assertEqual(code, 404)


if __name__ == "__main__":
    unittest.main()
