import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import build_plan  # noqa: E402
import context_pack  # noqa: E402
import kb_gate  # noqa: E402
import trust  # noqa: E402

PROFILE = {"owners": {"kb_owner": "Ana Lead"}}


def rmtree(path):
    def onerror(func, p, _):
        os.chmod(p, 0o700)
        func(p)
    shutil.rmtree(path, onerror=onerror)


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def git(repo, *args):
    subprocess.run(["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@example.com"] + list(args),
                   capture_output=True, text=True, check=True)


class Signals(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.kb = os.path.join(self.d, "kb")
        self.repo = os.path.join(self.d, "src", "api")
        write(os.path.join(self.repo, "A.java"), "line one\nclass Orders reads ORDERS\nline three\n")
        write(os.path.join(self.repo, "B.java"), "other file\n")
        git(self.repo, "init", "-q")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-q", "-m", "first")
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"),
              yaml.safe_dump(dict(PROFILE, sources={"workspace_root": os.path.join(self.d, "src"), "repos": {"api": "api"}})))
        write(os.path.join(self.kb, "CROSS-LAYER", "LINK_GRAPH.yaml"), yaml.safe_dump({
            "nodes": [{"id": "job:LOAD", "type": "job", "name": "LOAD"}, {"id": "table:ORDERS", "type": "table", "name": "ORDERS"}],
            "edges": [{"from": "job:LOAD", "rel": "writes", "to": "table:ORDERS", "source": '[E: api/A.java:2 "class Orders"]',
                       "defined_in": "m/parsed.links.yaml", "origin": "parsed"}]}))
        write(os.path.join(self.kb, "db", "ORDERS.md"), '# ORDERS\n\nHolds orders. [E: api/A.java:2 "class Orders"]\n')
        write(os.path.join(self.kb, "_QUESTIONS", "VALIDATE_KB.yaml"), yaml.safe_dump({"questions": [
            {"id": "Q-0001", "status": "open", "priority": "P1", "question": "Retention of ORDERS?", "blocks": ["db/ORDERS.md"]}]}))
        build_plan.record(self.kb)

    def tearDown(self):
        rmtree(self.d)

    def test_edge_verified_unchanged(self):
        t = trust.Trust(self.kb)
        s = t.edge("parsed", '[E: api/A.java:2 "class Orders"]')
        self.assertEqual((s["origin"], s["quote"], s["source"]), ("parsed", "verified", "unchanged since build"))
        self.assertEqual(t.edge_text(s), "quote verified; source unchanged since build")

    def test_edge_quote_not_in_source_and_no_quote_and_no_tag(self):
        t = trust.Trust(self.kb)
        self.assertTrue(t.edge("ai-proposed", '[E: api/A.java:2 "not there"]')["quote"].startswith("does not resolve"))
        self.assertEqual(t.edge("ai-proposed", "[E: api/A.java:2]")["quote"], "resolves, no quote")
        self.assertEqual(t.edge("ai-proposed", "")["quote"], "no source tag")
        self.assertEqual(t.edge(None, "")["origin"], "unknown")

    def test_source_change_since_build_is_seen(self):
        write(os.path.join(self.repo, "A.java"), "line one\nclass Orders reads ORDERS\nline three changed\n")
        git(self.repo, "commit", "-q", "-am", "edit")
        t = trust.Trust(self.kb)
        self.assertEqual(t.edge("parsed", '[E: api/A.java:2 "class Orders"]')["source"], "changed since build")
        self.assertEqual(t.page("db/ORDERS.md")["sources_changed"], ["api/A.java changed"])
        write(os.path.join(self.repo, "B.java"), "other file changed\n")
        git(self.repo, "commit", "-q", "-am", "edit b")
        t = trust.Trust(self.kb)
        self.assertEqual(t.edge("parsed", '[E: api/B.java:1 "other file"]')["source"], "changed since build")
        self.assertEqual(t.edge("parsed", '[E: api/B.java:1 "other file"; api/A.java:2 "class Orders"]')["source"], "changed since build")

    def test_repo_without_a_recorded_commit_cannot_be_compared(self):
        os.remove(os.path.join(self.kb, ".metis", "built-from.yaml"))
        t = trust.Trust(self.kb)
        self.assertEqual(t.edge("parsed", '[E: api/A.java:2 "class Orders"]')["source"], "cannot compare")

    def test_page_signals(self):
        t = trust.Trust(self.kb)
        p = t.page("db/ORDERS.md")
        self.assertEqual((p["tags"], p["problems"]), (1, 0))
        self.assertEqual(p["sources_changed"], [])
        self.assertEqual(p["blocked_by"], [{"id": "Q-0001", "priority": "P1"}])
        self.assertIsNone(p["certified"])  # gate not locked
        text = t.page_text(p)
        self.assertIn("blocked by Q-0001 (P1)", text)
        self.assertIn("cited sources unchanged since build", text)

    def test_page_with_a_broken_tag_counts_a_problem(self):
        write(os.path.join(self.kb, "db", "BAD.md"), '# BAD\n\nWrong. [E: api/A.java:2 "nope"]\n')
        self.assertEqual(trust.Trust(self.kb).page("db/BAD.md")["problems"], 1)

    def test_certification_state(self):
        write(os.path.join(self.kb, "_EVIDENCE", "files", "x.txt"), "x\n")
        kb_gate.lock(self.kb, "Ana Lead")
        t = trust.Trust(self.kb)
        c = t.page("db/ORDERS.md")["certified"]
        self.assertEqual((c["by"], c["unchanged"]), ("Ana Lead", True))
        write(os.path.join(self.kb, "db", "ORDERS.md"), '# ORDERS\n\nHolds orders and more. [E: api/A.java:2 "class Orders"]\n')
        t = trust.Trust(self.kb)
        self.assertFalse(t.page("db/ORDERS.md")["certified"]["unchanged"])
        self.assertIn("changed since", t.page_text(t.page("db/ORDERS.md")))
        write(os.path.join(self.kb, "db", "NEW.md"), '# NEW\n\nNew. [E: api/A.java:2 "class Orders"]\n')
        self.assertEqual(trust.Trust(self.kb).page_text(trust.Trust(self.kb).page("db/NEW.md")).count("not certified"), 1)

    def test_unknown_page_is_an_error(self):
        with self.assertRaises(ValueError):
            trust.Trust(self.kb).page("nope.md")

    def test_pack_shows_signals_and_can_leave_them_out(self):
        p = context_pack.build(self.kb, seeds=["table:ORDERS"], stale_marks=False)
        self.assertIn("(quote verified; source unchanged since build)", p["text"])
        self.assertIn("blocked by Q-0001 (P1)", p["text"])
        self.assertIn("| Signals |", p["text"])
        q = context_pack.build(self.kb, seeds=["table:ORDERS"], stale_marks=False, signals=False)
        self.assertNotIn("quote verified", q["text"])
        self.assertNotIn("Signals", q["text"])

    def test_cli(self):
        self.assertEqual(trust.main(["page", self.kb, "db/ORDERS.md"]), 0)
        self.assertEqual(trust.main(["edge", self.kb, "table:ORDERS"]), 0)
        self.assertEqual(trust.main(["page", self.kb, "nope.md"]), 2)


if __name__ == "__main__":
    unittest.main()
