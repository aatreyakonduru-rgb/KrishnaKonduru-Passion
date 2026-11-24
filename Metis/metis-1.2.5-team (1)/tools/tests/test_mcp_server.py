import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import mcp_server  # noqa: E402
import telemetry  # noqa: E402

TOOLS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def edge(a, rel, b, line):
    return {"from": a, "rel": rel, "to": b, "source": '[E: file:rules.txt "pay in 30 days"]', "defined_in": "m/x.links.yaml", "origin": "parsed"}


class Mcp(unittest.TestCase):
    def setUp(self):
        self.kb = tempfile.mkdtemp()
        nodes = [{"id": "table:APP.ORDERS", "type": "table", "name": "APP.ORDERS"}, {"id": "job:LOAD_ORDERS", "type": "job", "name": "LOAD_ORDERS"},
                 {"id": "screen:Orders", "type": "screen", "name": "Orders"}]
        write(os.path.join(self.kb, "CROSS-LAYER/LINK_GRAPH.yaml"), yaml.safe_dump({"nodes": nodes, "edges": [edge("job:LOAD_ORDERS", "writes", "table:APP.ORDERS", 1)]}))
        write(os.path.join(self.kb, "_EVIDENCE/files/rules.txt"), "pay in 30 days\n")
        write(os.path.join(self.kb, "db/ORDERS.md"), '# APP.ORDERS\n\nPay in 30 days. [E: file:rules.txt "pay in 30 days"]\n')
        write(os.path.join(self.kb, ".metis/kb-profile.yaml"), yaml.safe_dump({"owners": {"kb_owner": "Ana Lead"}}))
        write(os.path.join(self.kb, "_QUESTIONS/VALIDATE_KB.yaml"), yaml.safe_dump({"questions": []}))
        self.answer = '# A\n\n- Orders are paid in 30 days. [E: kb:db/ORDERS.md "Pay in 30 days"]\n'

    def tearDown(self):
        shutil.rmtree(self.kb, ignore_errors=True)

    def rpc(self, method, params=None, rid=1):
        return mcp_server.handle(self.kb, {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})

    def tool(self, name, **args):
        r = self.rpc("tools/call", {"name": name, "arguments": args})["result"]
        return r["content"][0]["text"], r["isError"]

    def test_initialize_and_list(self):
        r = self.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "x", "version": "1"}})["result"]
        self.assertEqual((r["protocolVersion"], r["serverInfo"]["name"]), ("2025-06-18", "metis-kb"))
        self.assertIn("tools", r["capabilities"])
        self.assertEqual(self.rpc("initialize", {"protocolVersion": "1999-01-01"})["result"]["protocolVersion"], mcp_server.PROTOCOLS[0])
        tools = {t["name"]: t for t in self.rpc("tools/list")["result"]["tools"]}
        self.assertEqual(len(tools), 8)
        for t in tools.values():
            self.assertEqual(t["inputSchema"]["type"], "object")
            self.assertTrue(set(t["inputSchema"]["required"]) <= set(t["inputSchema"]["properties"]))
        self.assertTrue(tools["metis_context_pack"]["annotations"]["destructiveHint"] is False)
        self.assertTrue(tools["metis_find_nodes"]["annotations"]["readOnlyHint"])

    def test_nothing_that_certifies_or_writes_pages_is_offered(self):
        names = {t["name"] for t in self.rpc("tools/list")["result"]["tools"]}
        self.assertFalse(any(w in n for n in names for w in ("certify", "approve", "decline", "publish", "write", "lock")))

    def test_notifications_get_no_reply_and_unknown_methods_error(self):
        self.assertIsNone(mcp_server.handle(self.kb, {"jsonrpc": "2.0", "method": "notifications/initialized"}))
        self.assertEqual(self.rpc("nope")["error"]["code"], -32601)
        self.assertEqual(self.rpc("tools/call", {"name": "nope"})["error"]["code"], -32602)
        self.assertEqual(self.rpc("ping")["result"], {})

    def test_a_message_that_is_not_an_object_gets_an_error_not_silence(self):
        # a client that sends a JSON array or a bare string waits for an answer; silence hangs it
        for bad in ([1, 2, 3], "just a string", 7, None):
            out = mcp_server.handle(self.kb, bad)
            self.assertEqual(out["error"]["code"], -32600)
            self.assertIsNone(out["id"])

    def test_params_that_are_not_an_object_get_an_error_not_a_crash(self):
        for bad in ([1], "x", 5):
            out = mcp_server.handle(self.kb, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": bad})
            self.assertEqual((out["id"], out["error"]["code"]), (3, -32602))
        out = mcp_server.handle(self.kb, {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": ["a"]}})
        self.assertEqual(out["error"]["code"], -32602)
        self.assertEqual(self.rpc("ping")["result"], {})

    def test_find_nodes(self):
        text, bad = self.tool("metis_find_nodes", query="orders")
        self.assertFalse(bad)
        self.assertEqual(set(text.splitlines()), {"table:APP.ORDERS", "job:LOAD_ORDERS", "screen:Orders"})
        self.assertEqual(self.tool("metis_find_nodes", query="orders", type="job")[0], "job:LOAD_ORDERS")
        self.assertIn("no graph object", self.tool("metis_find_nodes", query="zzz")[0])

    def test_context_pack_and_usage_record(self):
        text, bad = self.tool("metis_context_pack", nodes=["table:APP.ORDERS"], by="Pat")
        self.assertFalse(bad)
        self.assertIn("job:LOAD_ORDERS", text)
        self.assertIn("db/ORDERS.md", text)
        self.assertIn("quote verified", text)
        self.assertEqual(telemetry.report(self.kb)["packs"], 1)
        self.tool("metis_context_pack", nodes=["table:APP.ORDERS"], no_telemetry=True)
        self.assertEqual(telemetry.report(self.kb)["packs"], 1)

    def test_pack_errors_come_back_as_tool_errors(self):
        text, bad = self.tool("metis_context_pack")
        self.assertTrue(bad)
        self.assertIn("give --node", text)
        self.assertTrue(self.tool("metis_context_pack", nodes=["table:NOPE"])[1])

    def test_trust(self):
        text, bad = self.tool("metis_trust", pages=["db/ORDERS.md"], node="table:APP.ORDERS")
        self.assertFalse(bad)
        self.assertIn("db/ORDERS.md: 1 tags, 0 source problems", text)
        self.assertIn("[parsed] quote verified", text)
        self.assertTrue(self.tool("metis_trust")[1])
        self.assertTrue(self.tool("metis_trust", pages=["../outside.md"])[1])

    def test_check_answer(self):
        self.assertTrue(self.tool("metis_check_answer", answer=self.answer)[0].startswith("0 problems"))
        text, bad = self.tool("metis_check_answer", answer=self.answer.replace("Pay in 30 days", "Pay in 99 days"))
        self.assertFalse(bad)  # a failed check is a result, not a tool failure
        self.assertTrue(text.startswith("1 problems"))
        self.assertIn("quoted text not found", text)

    def test_record_answer_names_only(self):
        self.assertFalse(self.tool("metis_record_answer", files=["db/ORDERS.md"], by="Pat")[1])
        ev = telemetry.events(self.kb)[0]
        self.assertEqual((ev["kind"], ev["files"]), ("answer", ["db/ORDERS.md"]))
        self.assertTrue(self.tool("metis_record_answer", files=["nope.md"])[1])
        self.assertTrue(self.tool("metis_record_answer", files=["../x"])[1])

    def test_rate_answer_like_dislike_and_hints(self):
        ok = dict(answer=self.answer, question="How long to pay orders?", by="Pat")
        self.assertIn("recorded (up)", self.tool("metis_rate_answer", rating="up", **ok)[0])
        text, bad = self.tool("metis_rate_answer", rating="down", **ok)
        self.assertTrue(bad)
        self.assertIn("reason", text)
        text, bad = self.tool("metis_rate_answer", rating="down", why="wrong", correct="45 days", redirect="batch job", **ok)
        self.assertTrue(bad)
        text, bad = self.tool("metis_rate_answer", rating="down", why="wrong", redirect="look in the load job", **ok)
        self.assertFalse(bad)
        self.assertIn("look in the load job", text)
        self.assertIn("no approved directions", self.tool("metis_feedback_hints", question="How long to pay orders?")[0])  # a lead has not approved it
        text, bad = self.tool("metis_rate_answer", rating="down", why="wrong", correct="45 days", **ok)
        self.assertFalse(bad)
        self.assertIn("raised for a lead", text)

    def test_raise_question(self):
        text, bad = self.tool("metis_raise_question", question="Who owns order retention?", by="Pat", type="business")
        self.assertFalse(bad)
        self.assertIn("Q-0001", text)
        self.assertIn("Q-0001", self.tool("metis_raise_question", question="Who owns order retention?", by="Pat", type="business")[0])
        self.assertTrue(self.tool("metis_raise_question", question="x?", by="Pat", type="bogus")[1])

    def test_missing_required_argument(self):
        text, bad = self.tool("metis_check_answer")
        self.assertTrue(bad)
        self.assertIn("answer is required", text)

    def test_serve_loop_keeps_stdout_clean_and_survives_bad_input(self):
        lines = [json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}), "not json", "",
                 json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
                 json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "metis_find_nodes", "arguments": {"query": "orders"}}})]
        out = io.StringIO()
        mcp_server.serve(self.kb, io.StringIO("\n".join(lines) + "\n"), out)
        msgs = [json.loads(x) for x in out.getvalue().splitlines()]
        self.assertEqual([m.get("id") for m in msgs], [1, None, 2])
        self.assertEqual(msgs[1]["error"]["code"], -32700)
        self.assertIn("table:APP.ORDERS", msgs[2]["result"]["content"][0]["text"])

    def test_real_process_over_stdio(self):
        msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "metis_context_pack", "arguments": {"nodes": ["table:APP.ORDERS"]}}}]
        env = dict(os.environ, METIS_KB=self.kb, PYTHONIOENCODING="utf-8")
        r = subprocess.run([sys.executable, os.path.join(TOOLS_DIR, "mcp_server.py")], input="\n".join(json.dumps(m) for m in msgs) + "\n",
                           capture_output=True, text=True, encoding="utf-8", env=env, timeout=60)
        out = [json.loads(x) for x in r.stdout.splitlines()]  # every stdout line must be a protocol message
        self.assertEqual([m["id"] for m in out], [1, 2])
        self.assertFalse(out[1]["result"]["isError"])
        self.assertIn("job:LOAD_ORDERS", out[1]["result"]["content"][0]["text"])
        self.assertIn("serving", r.stderr)

    def test_needs_a_kb(self):
        self.assertEqual(mcp_server.main(["--kb", os.path.join(self.kb, "missing")]), 2)


if __name__ == "__main__":
    unittest.main()
