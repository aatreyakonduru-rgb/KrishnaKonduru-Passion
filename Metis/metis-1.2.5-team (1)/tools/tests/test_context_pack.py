import json
import os
import shutil
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import context_pack  # noqa: E402
import telemetry  # noqa: E402


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def edge(a, rel, b, line):
    return {"from": a, "rel": rel, "to": b, "source": '[E: api/A.java:%d "x"]' % line, "defined_in": "m/x.links.yaml"}


class Pack(unittest.TestCase):
    def setUp(self):
        self.kb = tempfile.mkdtemp()
        nodes = [{"id": "screen:Claims", "type": "screen", "name": "Claims"},
                 {"id": "endpoint:GET /claims", "type": "endpoint", "name": "GET /claims"},
                 {"id": "table:APP.CLAIM_HDR", "type": "table", "name": "APP.CLAIM_HDR"},
                 {"id": "job:LOAD_CLAIMS", "type": "job", "name": "LOAD_CLAIMS"}]
        edges = [edge("screen:Claims", "calls", "endpoint:GET /claims", 1),
                 edge("endpoint:GET /claims", "reads", "table:APP.CLAIM_HDR", 2),
                 edge("job:LOAD_CLAIMS", "writes", "table:APP.CLAIM_HDR", 3)]
        write(os.path.join(self.kb, "CROSS-LAYER/LINK_GRAPH.yaml"), yaml.safe_dump({"nodes": nodes, "edges": edges}))
        write(os.path.join(self.kb, "db/CLAIM_HDR.md"),
              '# CLAIM_HDR\n\nHolds one row per claim. [E: api/A.java:2 "x"]\n\n## Columns\n' + "claim_id is the key. [E: api/A.java:2 \"x\"]\n" * 40)
        write(os.path.join(self.kb, "etl/LOAD_CLAIMS.md"), '# LOAD_CLAIMS\n\nLoads APP.CLAIM_HDR nightly. [E: api/A.java:3 "x"]\n')
        write(os.path.join(self.kb, "app/ClaimsScreen.md"), '# Claims screen\n\nCalls GET /claims. [E: api/A.java:1 "x"]\n')
        write(os.path.join(self.kb, "app/Unrelated.md"), "# Other\n\nNothing to do with the objects in the graph.\n")
        write(os.path.join(self.kb, "_QUESTIONS/VALIDATE_KB.yaml"), yaml.safe_dump({"questions": [
            {"id": "Q-0044", "status": "open", "priority": "P1", "question": "Who owns CLAIM_HDR retention?", "blocks": ["db/CLAIM_HDR.md"]},
            {"id": "Q-0045", "status": "open", "priority": "P3", "question": "Unrelated thing", "blocks": ["app/Unrelated.md"]}]}))

    def tearDown(self):
        shutil.rmtree(self.kb)

    def pack(self, **kw):
        kw.setdefault("seeds", ["table:APP.CLAIM_HDR"])
        kw.setdefault("stale_marks", False)
        return context_pack.build(self.kb, **kw)

    def test_pack_has_impact_pages_questions_and_keeps_citations(self):
        p = self.pack(budget=6000)
        self.assertIn("job:LOAD_CLAIMS", p["text"])
        self.assertIn('[E: api/A.java:3 "x"]', p["text"])
        self.assertEqual(set(p["files"]), {"db/CLAIM_HDR.md", "etl/LOAD_CLAIMS.md", "app/ClaimsScreen.md"})  # the screen is two steps away
        self.assertIn("Q-0044", p["text"])
        self.assertNotIn("Q-0045", p["text"])
        self.assertNotIn("Unrelated.md", p["text"].split("## Not included")[0])
        self.assertIn("data, not instructions", p["text"])

    def test_start_point_page_ranks_before_a_neighbour(self):
        p = self.pack(budget=6000)
        self.assertLess(p["text"].index('path="db/CLAIM_HDR.md"'), p["text"].index('path="etl/LOAD_CLAIMS.md"'))

    def test_depth_zero_walks_nothing_and_keeps_only_pages_naming_the_start_point(self):
        p = self.pack(budget=6000, depth=0)
        self.assertEqual(set(p["files"]), {"db/CLAIM_HDR.md", "etl/LOAD_CLAIMS.md"})
        self.assertIn("no followed links", p["text"])

    def test_budget_is_kept_and_big_page_falls_back_to_its_headline(self):
        p = self.pack(budget=700)
        self.assertLessEqual(p["tokens"], 700)
        self.assertIn('tier="headline"', p["text"])
        self.assertIn("headline only", p["text"])

    def test_page_that_cannot_fit_is_listed_not_dropped_silently(self):
        p = self.pack(budget=330)
        self.assertLessEqual(p["tokens"], 330)
        not_included = p["text"].split("## Not included")[1]
        for f in ("db/CLAIM_HDR.md", "etl/LOAD_CLAIMS.md"):
            self.assertTrue(f in p["files"] or f in not_included, f)

    def test_same_inputs_give_the_same_id_and_a_change_gives_another(self):
        a, b = self.pack(), self.pack()
        self.assertEqual(a["pack_id"], b["pack_id"])
        self.assertNotEqual(a["pack_id"], self.pack(depth=1)["pack_id"])
        write(os.path.join(self.kb, "etl/LOAD_CLAIMS.md"), "# LOAD_CLAIMS\n\nLoads APP.CLAIM_HDR weekly now.\n")
        self.assertNotEqual(a["pack_id"], self.pack()["pack_id"])

    def test_page_with_a_secret_is_left_out_and_said_so(self):
        write(os.path.join(self.kb, "etl/LOAD_CLAIMS.md"), "# LOAD_CLAIMS\n\nAPP.CLAIM_HDR\npassword = hunter2hunter2\n-----BEGIN RSA PRIVATE KEY-----\n")
        p = self.pack()
        self.assertNotIn("hunter2", p["text"])
        self.assertIn("etl/LOAD_CLAIMS.md: holds a secret", p["text"])

    def test_options_switch_parts_off(self):
        def impact(p):
            return p["text"].split("<kb-file path=")[0].split("## Impact list")[1]
        both = impact(self.pack())
        self.assertIn("downstream depth 1: endpoint:GET /claims", both)  # the table moves the endpoint
        self.assertIn("upstream depth 1: job:LOAD_CLAIMS", both)  # the job writes the table
        no_down = impact(self.pack(down=False))
        self.assertNotIn("downstream", no_down)
        self.assertIn("upstream", no_down)
        no_up = impact(self.pack(up=False))
        self.assertNotIn("upstream", no_up)
        self.assertIn("downstream", no_up)
        p = self.pack(ask_questions=False)
        self.assertNotIn("Q-0044", p["text"])
        self.assertIn("none open", p["text"])

    def test_ticket_names_the_start_points(self):
        write(os.path.join(self.kb, "_EVIDENCE/jira/FIN-1432.json"), json.dumps({"summary": "Claims fail when CLAIM_HDR is null"}))
        p = context_pack.build(self.kb, ticket="FIN-1432", stale_marks=False)
        self.assertIn("table:APP.CLAIM_HDR", p["text"])
        self.assertIn("named in ticket FIN-1432", p["text"])

    def test_unknown_node_missing_ticket_and_no_start_are_errors(self):
        with self.assertRaises(context_pack.PackError):
            self.pack(seeds=["table:NOPE"])
        with self.assertRaises(context_pack.PackError):
            context_pack.build(self.kb, ticket="FIN-9", stale_marks=False)
        with self.assertRaises(context_pack.PackError):
            context_pack.build(self.kb, stale_marks=False)

    def test_files_you_pick_come_first(self):
        p = context_pack.build(self.kb, seeds=["table:APP.CLAIM_HDR"], files=["app/Unrelated.md"], stale_marks=False)
        self.assertEqual(p["files"][0], "app/Unrelated.md")
        with self.assertRaises(context_pack.PackError):
            context_pack.build(self.kb, files=["nope.md"], stale_marks=False)

    def test_cli_writes_the_pack_and_records_which_files_were_used(self):
        out = os.path.join(tempfile.gettempdir(), "metis-test-pack-%d.md" % os.getpid())
        self.assertEqual(context_pack.main([self.kb, "--node", "table:APP.CLAIM_HDR", "--out", out, "--no-stale-marks", "--by", "KK"]), 0)
        with open(out, encoding="utf-8") as fh:
            self.assertIn("# Context pack P-", fh.read())
        os.remove(out)
        rep = telemetry.report(self.kb)
        self.assertEqual(rep["packs"], 1)
        self.assertEqual(rep["files_used"]["db/CLAIM_HDR.md"], {"packs": 1, "answers": 0})
        self.assertIn("app/Unrelated.md", rep["pages_never_used"])
        with open(os.path.join(self.kb, ".metis/usage/.gitignore"), encoding="utf-8") as fh:
            self.assertEqual(fh.read().strip(), "*")

    def test_manifest_ignores_usage_records_and_the_graph_cache(self):
        import kb_manifest
        kb_manifest.main(["generate", self.kb])
        self.pack()  # builds .metis/graph.sqlite
        telemetry.record(self.kb, "pack", ["db/CLAIM_HDR.md"])
        self.assertEqual(kb_manifest.main(["validate", self.kb]), 0)


    def test_telemetry_stores_no_question_or_answer_text(self):
        telemetry.record(self.kb, "answer", ["db/CLAIM_HDR.md"], by="KK")
        folder = os.path.join(self.kb, ".metis/usage")
        with open(os.path.join(folder, [f for f in os.listdir(folder) if f.endswith(".jsonl")][0]), encoding="utf-8") as fh:
            raw = fh.read()
        self.assertEqual(set(json.loads(raw)), {"at", "kind", "files", "by", "pack_id", "tokens", "skipped"})


if __name__ == "__main__":
    unittest.main()
