"""The link graph keeps a source on every link, walks by hops, and re-reads the lines it cites."""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)
sys.path.insert(0, os.path.join(TOOLS, "kbgen"))
import gen_link_graph  # noqa: E402
import kb_sync  # noqa: E402
import link_graph  # noqa: E402
import ontology_lookup as ol  # noqa: E402


def tiny(path_a, path_b):
    return {"metadata": {"gaps": ["g"]},
            "nodes": {"table:CL_X": {"type": "table", "name": "CL_X"},
                      "column:CL_X.COL_A": {"type": "column", "name": "CL_X.COL_A"},
                      "file:%s" % path_a: {"type": "file", "name": path_a},
                      "file:%s" % path_b: {"type": "file", "name": path_b},
                      "screen:/x": {"type": "screen", "name": "/x"},
                      "story:ACME-1": {"type": "story", "name": "ACME-1"}},
            "edges": [{"from": "file:%s" % path_a, "type": "reads", "to": "table:CL_X", "source": path_a + ":2"},
                      {"from": "file:%s" % path_a, "type": "names", "to": "column:CL_X.COL_A", "source": path_a + ":9"},
                      {"from": "file:%s" % path_b, "type": "writes", "to": "table:CL_X", "source": path_b + ":1"},
                      {"from": "screen:/x", "type": "page", "to": "file:%s" % path_a, "source": path_a},
                      {"from": "story:ACME-1", "type": "tested_on", "to": "screen:/x", "source": "catalogue"}]}


class CommittedGraphTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = link_graph.load()
        cls.g = link_graph.Graph(cls.data)

    def test_every_link_has_a_source_and_known_nodes(self):
        for e in self.g.edges:
            self.assertTrue(e["source"], e)
            self.assertIn(e["from"], self.g.nodes)
            self.assertIn(e["to"], self.g.nodes)

    @unittest.skip('checks the knowledge base or application folders of the team that built the copy')
    def test_is_current_with_its_sources(self):
        res = gen_link_graph.check()
        if res["fresh"] is None:
            self.skipTest(res["error"])
        self.assertTrue(res["fresh"], res.get("fix"))

    @unittest.skip('checks the knowledge base or application folders of the team that built the copy')
    def test_walk_from_a_table_reaches_jobs_screens_and_keeps_sources(self):
        r = self.g.walk("CL_PG_LOB", hops=2)
        self.assertEqual(r["start"], "table:CL_PG_LOB")
        self.assertIn("job:PG_syncup.sql", [x["id"] for x in r["reached"]["job"]])
        self.assertTrue(r["reached"]["screen"])
        for rows in r["reached"].values():
            for x in rows:
                self.assertEqual(len(x["sources"]), x["hops"])
        self.assertFalse(self.g.walk("nothing like this")["found"])

    @unittest.skip('checks the knowledge base or application folders of the team that built the copy')
    def test_lookup_cli_walk_and_drift(self):
        self.assertEqual(ol.main(["walk", "CL_PG_LOB", "--hops", "1", "--types", "job"]), 0)
        self.assertEqual(ol.main(["walk", "no such thing"]), 3)
        self.assertEqual(ol.main(["drift", "--item", "CL_CNTRCT_PARM"]), 0)


class WalkAndDriftTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(dir=link_graph.REPO, prefix=".lg-test-")
        rel = os.path.relpath(self.dir, link_graph.REPO)
        self.a, self.b = rel + "/a.py", rel + "/b.py"
        with open(os.path.join(link_graph.REPO, self.a), "w") as fh:
            fh.write("x = 1\nq = 'select * from cl_x'\n" + "\n" * 10 + "col_a = 2\n")
        with open(os.path.join(link_graph.REPO, self.b), "w") as fh:
            fh.write("nothing here\n")
        self.g = link_graph.Graph(tiny(self.a, self.b))

    def tearDown(self):
        for f in (self.a, self.b):
            p = os.path.join(link_graph.REPO, f)
            if os.path.exists(p):
                os.remove(p)
        os.rmdir(self.dir)

    def test_walk_respects_hops_and_types(self):
        r = self.g.walk("ACME-1", hops=2)
        self.assertEqual(r["counts"], {"file": 1, "screen": 1})
        r = self.g.walk("ACME-1", hops=3, types=["table"])
        self.assertEqual([x["id"] for x in r["reached"]["table"]], ["table:CL_X"])
        self.assertEqual(r["reached"]["table"][0]["path"][-1], "file:%s -reads-> table:CL_X" % self.a)

    def test_drift_current_moved_stale_missing(self):
        rows = {r["source"]: r["status"] for r in self.g.drift(files=[self.a, self.b])["rows"]}
        self.assertEqual(rows[self.a + ":2"], "current")
        self.assertEqual(rows[self.a + ":9"], "moved")
        self.assertEqual(rows[self.b + ":1"], "stale")
        self.assertNotIn(self.a, rows)
        os.remove(os.path.join(link_graph.REPO, self.b))
        res = self.g.drift(refs=["CL_X"])
        self.assertEqual(res["verdict"], "stale")
        self.assertIn("missing", res["summary"])


class KbSyncTraceTest(unittest.TestCase):
    def test_lines_follow_the_trace_format(self):
        res = {"check": True, "base": "origin/x", "files": ["a.py"],
               "rows": [{"artifact": "ACME_LINK_GRAPH.yaml", "result": "stale", "detail": "d", "why": "w"}],
               "drift": {"checked": 3, "summary": {"current": 3}, "verdict": "current"}}
        lines = kb_sync.trace_lines(res)
        self.assertEqual(lines[0], "[SDLC] sync ACME_LINK_GRAPH.yaml — compared with a fresh build: d; why: w; result: stale")
        self.assertTrue(lines[1].startswith("[SDLC] drift ACME_LINK_GRAPH.yaml — re-read 3 cited lines in 1 changed files"))
        self.assertTrue(lines[1].endswith("result: current"))
        lines = kb_sync.trace_lines(dict(res, base=None, files=[], drift=None))
        self.assertTrue(lines[-1].endswith("result: not run"))


if __name__ == "__main__":
    unittest.main()
