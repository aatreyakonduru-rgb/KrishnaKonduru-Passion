import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import build_plan  # noqa: E402
import graph_store  # noqa: E402
import kb_manifest  # noqa: E402


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def rmtree(path):
    def onerror(func, p, _):
        os.chmod(p, 0o700)
        func(p)
    shutil.rmtree(path, onerror=onerror)


def git(cwd, *args):
    subprocess.run(["git", "-C", cwd, "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"] + list(args),
                   check=True, capture_output=True)


class Graph(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.kb = os.path.join(self.d, "kb")
        edges = [{"from": "screen:A", "rel": "calls", "to": "endpoint:B", "source": "[E: x/a:1]", "defined_in": "f"},
                 {"from": "endpoint:B", "rel": "reads", "to": "table:T", "source": "[E: x/b:2]", "defined_in": "f"},
                 {"from": "job:J", "rel": "writes", "to": "table:T", "source": "[E: x/c:3]", "defined_in": "f"},
                 {"from": "table:T", "rel": "mentions", "to": "doc:D", "source": "[E: x/d:4]", "defined_in": "f"}]
        nodes = [{"id": i, "type": i.split(":")[0], "name": i.split(":")[1]} for i in
                 ("screen:A", "endpoint:B", "table:T", "job:J", "doc:D")]
        write(os.path.join(self.kb, "CROSS-LAYER", "LINK_GRAPH.yaml"), yaml.safe_dump({"nodes": nodes, "edges": edges}))

    def tearDown(self):
        rmtree(self.d)

    def test_impact_walks_dependents_and_stops_at_depth(self):
        rows, cut = graph_store.impact(self.kb, "table:T")
        self.assertEqual({r["moves"] for r in rows}, {"endpoint:B", "screen:A"})
        self.assertFalse(cut)
        by = {r["moves"]: r for r in rows}
        self.assertEqual(by["screen:A"]["depth"], 2)
        self.assertEqual(by["screen:A"]["via"][-1]["source"], "[E: x/a:1]")
        rows, _ = graph_store.impact(self.kb, "table:T", depth=1)
        self.assertEqual([r["moves"] for r in rows], ["endpoint:B"])

    def test_writes_direction_and_unknown_relations(self):
        rows, _ = graph_store.impact(self.kb, "job:J")
        self.assertEqual([r["moves"] for r in rows], ["table:T", "endpoint:B", "screen:A"])  # the table it writes moves, then what reads it
        self.assertEqual(graph_store.impact(self.kb, "doc:D")[0], [])  # "mentions" has no direction, so it is not followed
        self.assertEqual(len(graph_store.around(self.kb, "table:T")), 3)

    def test_limit_is_reported_and_unknown_node_is_empty(self):
        rows, cut = graph_store.impact(self.kb, "table:T", limit=1)
        self.assertEqual((len(rows), cut), (1, True))
        self.assertEqual(graph_store.impact(self.kb, "table:Nope"), ([], False))

    def test_same_answer_as_the_matrix(self):
        import gen_matrix
        with open(os.path.join(self.kb, "CROSS-LAYER", "LINK_GRAPH.yaml"), encoding="utf-8") as fh:
            g = yaml.safe_load(fh)
        dep, _ = gen_matrix.dependents(g["edges"])
        want = {c["moves"] for c in gen_matrix.chain("table:T", dep, depth=6)}
        got = {r["moves"] for r in graph_store.impact(self.kb, "table:T")[0]}
        self.assertEqual(got, want)


class Plan(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.repo = os.path.join(self.d, "repos", "svc")
        self.kb = os.path.join(self.d, "repo", "kb")
        write(os.path.join(self.repo, "a.py"), "one\ntwo\n")
        write(os.path.join(self.repo, "b.py"), "three\n")
        git(self.repo, "init", "-q")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-q", "-m", "first")
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"),
              yaml.safe_dump({"sources": {"workspace_root": os.path.join(self.d, "repos"), "repos": {"svc": "svc"}}}))
        write(os.path.join(self.kb, "modules", "m1.md"), '# M1\n\n- Uses a [E: svc/a.py:1-2 "one"]\n')
        write(os.path.join(self.kb, "modules", "m2.md"), '# M2\n\n- Uses b [E: svc/b.py:1]\n')
        write(os.path.join(self.kb, "context", "doc.md"), "# D\n\n- from a document [E: doc:x1#p1 \"q\"]\n")

    def tearDown(self):
        rmtree(self.d)

    def test_only_pages_citing_changed_files_are_stale(self):
        self.assertEqual(list(build_plan.record(self.kb)), ["svc"])
        self.assertEqual(build_plan.stale(self.kb), ([], []))
        write(os.path.join(self.repo, "a.py"), "one\nTWO\n")
        git(self.repo, "commit", "-qam", "edit a")
        pages, notes = build_plan.stale(self.kb)
        self.assertEqual([p["page"] for p in pages], ["modules/m1.md"])
        self.assertEqual(pages[0]["reasons"], ["svc/a.py changed"])
        self.assertEqual(notes, [])

    def test_no_recorded_commit_lists_every_page_that_cites_the_repo(self):
        pages, notes = build_plan.stale(self.kb)
        self.assertEqual(sorted(p["page"] for p in pages), ["modules/m1.md", "modules/m2.md"])
        self.assertTrue(notes)

    def test_lost_commit_is_reported_not_crashed(self):
        build_plan.record(self.kb)
        p = os.path.join(self.kb, ".metis", "built-from.yaml")
        write(p, yaml.safe_dump({"repos": {"svc": "0" * 40}}))
        pages, notes = build_plan.stale(self.kb)
        self.assertEqual(len(pages), 2)
        self.assertIn("not in the clone", notes[0])

    def test_run_folders_never_collide_and_checkpoints_resume(self):
        a, b = build_plan.new_run(self.kb, "Full Build"), build_plan.new_run(self.kb, "Full Build")
        self.assertNotEqual(a, b)
        self.assertTrue(os.path.isdir(a) and os.path.isdir(b))
        stages = ["app", "db", "etl"]
        self.assertEqual(build_plan.next_stage(a, stages), "app")
        build_plan.mark(a, "app")
        build_plan.mark(a, "app")
        self.assertEqual(build_plan.next_stage(a, stages), "db")
        build_plan.mark(a, "db")
        build_plan.mark(a, "etl")
        self.assertEqual(build_plan.next_stage(a, stages), "")
        self.assertEqual(build_plan.next_stage(b, stages), "app")

    def test_manifest_reads_commits_in_one_pass(self):
        kbrepo = os.path.join(self.d, "repo")
        git(kbrepo, "init", "-q")
        git(kbrepo, "add", ".")
        git(kbrepo, "commit", "-q", "-m", "kb")
        commits = kb_manifest.last_commits(self.kb)
        self.assertIn("modules/m1.md", commits)
        entries = {e["path"]: e for e in kb_manifest.collect(self.kb)}
        self.assertRegex(entries["modules/m1.md"]["last_commit"], r"^[0-9a-f]+ \d{4}-\d\d-\d\d$")
        self.assertEqual(kb_manifest.last_commits(os.path.join(self.d, "nowhere")), {})


if __name__ == "__main__":
    unittest.main()
