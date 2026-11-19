"""Bridge transport (console/bridge.py): Argus in Devin Cloud reaches Devin through its host session."""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "console"))

import bridge  # noqa: E402

GET = """Session abc:
  session_id: 0000000000000000000000000000708d
  title: Argus /dashboard — Gate config change
  status: running
  status_detail: waiting_for_user
  created_at: 2026-10-22 17:16:29 UTC
  tags: action, sdlc-workbench, live
  pull_requests: https://bitbucket.example/projects/A/repos/b/pull-requests/12[open]
"""
MESSAGES = """Messages for session 0000000000000000000000000000708d:
Showing 2
More results available. Pass after=CURSOR1 to fetch the next page.

[user: Resource 3, (api)] @ 1792689389 (event-01)
[SDLC] request 1
Do it.
[devin] @ 1792689400 (event-02)
[SDLC] reply 1
Done.
"""
SEARCH = """Found 1 sessions
- 0000000000000000000000000000708d | Argus run | status=suspended (inactivity) | created=1792689389 | tags=sdlc-workbench,live | user_id=user-1
"""


class Host(threading.Thread):
    """Plays the host session's loop: answers each outbox request with canned tool output."""

    def __init__(self, folder, answer):
        super().__init__(daemon=True)
        self.dir, self.answer, self.seen, self.stop = folder, answer, [], False

    def run(self):
        while not self.stop:
            open(os.path.join(self.dir, "alive"), "w").close()
            for name in os.listdir(os.path.join(self.dir, "outbox")):
                if not name.endswith(".json"):
                    continue
                path = os.path.join(self.dir, "outbox", name)
                req = json.load(open(path))
                self.seen.append(req)
                out = [self.answer(c["tool"], c["args"]) for c in req["calls"]]
                json.dump({"id": req["id"], "results": out}, open(os.path.join(self.dir, "inbox", name), "w"))
                os.remove(path)
            time.sleep(0.02)


def answer(tool, args):
    if tool == "devin_session_create":
        return {"text": "Created session devin-0000000000000000000000000000cdef: https://app/sessions/0000000000000000000000000000cdef"}
    if tool == "devin_session_search":
        return {"text": SEARCH}
    if tool == "upload_attachment":
        return {"text": "Uploaded: https://app/attachments/x/report.zip"}
    if args.get("action") == "get":
        return {"text": GET}
    if args.get("action") == "get_messages":
        return {"text": MESSAGES if not args.get("after") else "Messages:\nShowing 0\n"}
    return {"text": "ok"}


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.devin = bridge.BridgeDevin(self.dir, "https://app", user_ids=lambda e: ["user-1"] if e else [], timeout=5)
        self.host = Host(self.dir, answer)
        self.host.start()
        time.sleep(0.05)

    def tearDown(self):
        self.host.stop = True
        self.host.join()
        shutil.rmtree(self.dir)

    def test_create_session_returns_the_api_shape(self):
        s = self.devin.create_session("prompt", "title", ["sdlc-workbench"])
        self.assertEqual(s["session_id"], "devin-0000000000000000000000000000cdef")
        self.assertTrue(s["url"].endswith("/sessions/0000000000000000000000000000cdef"))
        self.assertEqual(self.host.seen[0]["calls"][0]["args"]["sessions"][0]["tags"], ["sdlc-workbench"])

    def test_session_maps_status_tags_pr_and_messages(self):
        info = self.devin.session("devin-0000000000000000000000000000708d")
        self.assertEqual(info["status_enum"], "blocked")
        self.assertEqual(info["tags"], ["action", "sdlc-workbench", "live"])
        self.assertIn("pull-requests/12", info["pull_request"]["url"])
        msgs = self.devin.messages(info)
        self.assertEqual([m["source"] for m in msgs], ["user", "devin"])
        self.assertEqual(msgs[1]["message"], "[SDLC] reply 1\nDone.")
        pages = [c["args"].get("after") for r in self.host.seen for c in r["calls"] if c["args"].get("action") == "get_messages"]
        self.assertEqual(pages, [None, "CURSOR1"])

    def test_search_send_tags_terminate_upload(self):
        rows = self.devin.list_sessions("sdlc-workbench")
        self.assertEqual(rows[0]["session_id"], "devin-0000000000000000000000000000708d")
        self.assertEqual(rows[0]["status_enum"], "suspended")
        self.assertEqual(rows[0]["tags"], ["sdlc-workbench", "live"])
        self.assertEqual(len(self.devin.sessions_of("a@b.c")), 1)
        self.assertEqual(self.devin.sessions_of(""), [])
        self.devin.send("0000000000000000000000000000708d", "approved")
        self.devin.set_tags("devin-0000000000000000000000000000708d", ["closed"])
        self.devin.terminate("devin-0000000000000000000000000000708d")
        acts = [c["args"].get("action") for r in self.host.seen for c in r["calls"]]
        self.assertEqual(acts[-3:], ["message", "set_tags", "terminate"])
        self.assertEqual(self.devin.upload(__file__, "x.py"), "https://app/attachments/x/report.zip")

    def test_updated_of_searches_exactly_those_sessions(self):
        rows = self.devin.updated_of(["0000000000000000000000000000708d", "devin-0000000000000000000000000000708d", ""])
        self.assertEqual(rows[0]["session_id"], "devin-0000000000000000000000000000708d")
        call = self.host.seen[-1]["calls"][0]
        self.assertEqual(call["tool"], "devin_session_search")
        self.assertEqual(call["args"]["session_ids"], ["devin-0000000000000000000000000000708d"])
        self.assertEqual(self.devin.updated_of([]), [])

    def test_a_message_cut_short_is_read_in_full_from_the_session_events(self):
        cut = MESSAGES.replace("Done.", "Long intake... [truncated]")
        events = ('Event details (1 events):\n\n--- event-02 ---\n  type: devin_message (message)\n'
                  '  contents: {\n  "type": "devin_message",\n  "message": "[SDLC] reply 1\\nLong intake\\n'
                  '1. Which scope?\\n2. Keep 8?"\n}\n')

        def answer_cut(tool, args):
            if tool == "devin_session_events":
                self.assertEqual(args["event_ids"], ["event-02"])
                return {"text": events}
            if args.get("action") == "get_messages":
                return {"text": cut if not args.get("after") else "Messages:\nShowing 0\n"}
            return answer(tool, args)
        self.host.answer = answer_cut
        msgs = self.devin.messages(self.devin.session("devin-0000000000000000000000000000708d"))
        self.assertEqual(msgs[1]["message"], "[SDLC] reply 1\nLong intake\n1. Which scope?\n2. Keep 8?")
        self.devin.session("devin-0000000000000000000000000000708d")
        reads = [c for r in self.host.seen for c in r["calls"] if c["tool"] == "devin_session_events"]
        self.assertEqual(len(reads), 1)

    def test_a_loop_without_the_events_tool_leaves_the_message_short(self):
        cut = MESSAGES.replace("Done.", "Long intake... [truncated]")

        def answer_old(tool, args):
            if tool == "devin_session_events":
                return {"error": "unknown tool"}
            if args.get("action") == "get_messages":
                return {"text": cut if not args.get("after") else "Messages:\nShowing 0\n"}
            return answer(tool, args)
        self.host.answer = answer_old
        msgs = self.devin.messages(self.devin.session("devin-0000000000000000000000000000708d"))
        self.assertTrue(msgs[1]["message"].endswith("[truncated]"))

    def test_only_the_bridge_tools_run(self):
        with self.assertRaises(bridge.BridgeError):
            self.devin.call(("devin_session_delete_everything", {}))

    def test_a_stopped_loop_fails_at_once_with_the_wake_hint(self):
        self.host.stop = True
        self.host.join()
        os.utime(os.path.join(self.dir, "alive"), (0, 0))
        with self.assertRaises(bridge.BridgeError) as cm:
            self.devin.send("devin-x", "hi")
        self.assertIn("Send any message", str(cm.exception))

    def test_a_loop_that_just_stopped_holds_the_call_until_it_is_back(self):
        self.host.stop = True
        self.host.join()
        with open(os.path.join(self.dir, "host"), "w", encoding="utf-8") as fh:
            fh.write("devin-" + "a" * 32)
        then = time.time() - 30
        os.utime(os.path.join(self.dir, "alive"), (then, then))
        self.assertTrue(self.devin.reconnecting())
        back = Host(self.dir, self.host.answer)
        threading.Timer(0.5, back.start).start()
        self.addCleanup(lambda: setattr(back, "stop", True))
        self.devin.send("devin-x", "hi")
        self.assertEqual(len(back.seen), 1)
        self.assertFalse(self.devin.reconnecting())

    def test_a_loop_gone_past_the_grace_fails_with_the_wake_hint(self):
        self.host.stop = True
        self.host.join()
        with open(os.path.join(self.dir, "host"), "w", encoding="utf-8") as fh:
            fh.write("devin-" + "a" * 32)
        old = time.time() - bridge.GRACE_SECONDS - 5
        os.utime(os.path.join(self.dir, "alive"), (old, old))
        self.assertFalse(self.devin.reconnecting())
        with self.assertRaises(bridge.BridgeError) as cm:
            self.devin.send("devin-x", "hi")
        self.assertIn("RESERVED", str(cm.exception))

    def test_tool_error_is_raised(self):
        self.host.answer = lambda t, a: {"error": "boom"}
        with self.assertRaises(bridge.BridgeError):
            self.devin.send("devin-x", "hi")

    def test_already_ended_session_closes(self):
        self.host.answer = lambda t, a: {"error": "MCP tool error: HTTP 400 Bad Request for DELETE .../sessions/devin-x: Devin session already exited"}
        with self.assertRaises(bridge.BridgeError) as cm:
            self.devin.terminate("devin-x")
        self.assertEqual(cm.exception.status, 400)

    def test_a_later_read_starts_at_the_last_page_it_saw(self):
        sid = "devin-0000000000000000000000000000708d"
        info = self.devin.session(sid)
        self.assertEqual(info["msg_after"], "CURSOR1")
        self.host.seen.clear()
        again = self.devin.session(sid, after=info["msg_after"])
        pages = [c["args"].get("after") for r in self.host.seen for c in r["calls"] if c["args"].get("action") == "get_messages"]
        self.assertEqual(pages, ["CURSOR1"])
        self.assertEqual(again["msg_after"], "CURSOR1")

    def test_a_cursor_the_tools_refuse_reads_the_whole_transcript(self):
        self.host.answer = lambda tool, args: ({"error": "HTTP 400 bad cursor"} if args.get("after") == "OLD"
                                               else answer(tool, args))
        info = self.devin.session("devin-0000000000000000000000000000708d", after="OLD")
        self.assertEqual(len(info["messages"]), 2)

    def test_a_reply_after_the_wait_is_picked_up_and_old_files_are_cleared(self):
        self.host.stop = True
        self.host.join()
        open(os.path.join(self.dir, "alive"), "w").close()
        dev = bridge.BridgeDevin(self.dir, "https://app", timeout=0.3)
        with self.assertRaises(bridge.BridgeError):
            dev.create_session("p", "t", ["sdlc-workbench"])
        rid = next(iter(dev.late))
        with open(os.path.join(self.dir, "inbox", rid + ".json"), "w", encoding="utf-8") as fh:
            json.dump({"id": rid, "results": [{"text": "Created session devin-" + "a" * 32}]}, fh)
        stale = os.path.join(self.dir, "inbox", "old.json")
        open(stale, "w").close()
        os.utime(stale, (0, 0))
        late = dev.collect_late()
        self.assertEqual(late[0][0][0][0], "devin_session_create")
        self.assertIn("a" * 32, late[0][1][0])
        self.assertFalse(os.path.exists(stale))
        self.assertEqual(dev.collect_late(), [])


class StatusTests(unittest.TestCase):
    def test_v1_words(self):
        self.assertEqual(bridge.v1_status("running", ""), "working")
        self.assertEqual(bridge.v1_status("running", "waiting_for_user"), "blocked")
        self.assertEqual(bridge.v1_status("exit", ""), "exit")
        self.assertEqual(bridge.v1_status("suspended", "inactivity"), "suspended")
        self.assertEqual(bridge.v1_status("running", "finished"), "finished")

    def test_transport_switch(self):
        old = os.environ.pop("SDLC_DEVIN_TRANSPORT", None)
        try:
            self.assertEqual(bridge.transport(), "bridge")
            os.environ["SDLC_DEVIN_TRANSPORT"] = "api"
            self.assertEqual(bridge.transport(), "api")
            os.environ["SDLC_DEVIN_TRANSPORT"] = "bridge"
            self.assertEqual(bridge.transport(), "bridge")
        finally:
            os.environ.pop("SDLC_DEVIN_TRANSPORT", None)
            if old is not None:
                os.environ["SDLC_DEVIN_TRANSPORT"] = old


if __name__ == "__main__":
    unittest.main()


class WakeHintTests(unittest.TestCase):
    def test_cloud_users_get_the_host_step_only(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        dev = bridge.BridgeDevin(d, "https://app", user_ids=lambda e: [], timeout=1)
        self.assertIn("SDLC_DEVIN_TRANSPORT=api", dev.wake_hint())
        with open(os.path.join(d, "host"), "w", encoding="utf-8") as fh:
            fh.write("devin-" + "a" * 32)
        self.assertNotIn("SDLC_DEVIN_TRANSPORT", dev.wake_hint())
        self.assertIn("/argus", dev.wake_hint())

