import contextlib
import io
import os
import shutil
import sys
import tempfile
import unittest

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
for _p in (TOOLS, os.path.join(TOOLS, "ui")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import kb_gate  # noqa: E402
import kb_summaries as M  # noqa: E402


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


TAG_PETS = '[E: file:r.txt "pets have owners"]'
TAG_VISIT = '[E: file:r.txt "visits"]'
TAG_ETL = '[E: file:r.txt "nightly"]'


def make_kb(root):
    kb = os.path.join(root, "KB")
    write(os.path.join(kb, ".metis", "kb-profile.yaml"), yaml.safe_dump({"owners": {"kb_owner": "Ana Lead"}}))
    write(os.path.join(kb, "_EVIDENCE", "files", "r.txt"), "pets have owners\nvisits\nnightly\n")
    write(os.path.join(kb, "db", "PETS.md"), "# PETS\n\nThe pets table references owners. %s\n" % TAG_PETS)
    write(os.path.join(kb, "db", "OWNERS.md"), "# OWNERS\n\nOwners are people. %s\n" % TAG_PETS)
    write(os.path.join(kb, "db", "VISITS.md"), "# VISITS\n\nVisits are recorded. %s\nBilling is unknown. [?: Q-0001]\n" % TAG_VISIT)
    write(os.path.join(kb, "etl", "LOAD.md"), "# LOAD\n\nThe load job copies visits nightly. %s\n" % TAG_ETL)
    write(os.path.join(kb, "etl", "NOTES.md"), "# Notes\n\nRuns at night. %s\n" % TAG_ETL)
    write(os.path.join(kb, "_QUESTIONS", "VALIDATE_KB.yaml"), yaml.safe_dump({"questions": [
        {"id": "Q-0001", "question": "billing?", "type": "business", "priority": "P2", "answer_role": "product owner", "status": "open",
         "context": [], "possible_answers": []}]}))
    write(os.path.join(kb, "CROSS-LAYER", "LINK_GRAPH.yaml"), yaml.safe_dump({
        "nodes": [{"id": "table:PETS", "type": "table", "name": "PETS"}, {"id": "table:OWNERS", "type": "table", "name": "OWNERS"},
                  {"id": "table:VISITS", "type": "table", "name": "VISITS"}, {"id": "job:LOAD", "type": "job", "name": "LOAD"}],
        "edges": [{"from": "table:PETS", "rel": "references", "to": "table:OWNERS", "source": TAG_PETS},
                  {"from": "job:LOAD", "rel": "reads", "to": "table:VISITS", "source": TAG_ETL},
                  {"from": "table:VISITS", "rel": "references", "to": "table:PETS", "source": TAG_VISIT}]}))
    return kb


GOOD = {
    "area-db": "# Summary: db\n\n- Pets reference owners. %s\n- Visits are recorded. %s\n\n## Not in the KB\n\n- Billing is unknown. [?: Q-0001]\n" % (TAG_PETS, TAG_VISIT),
    "area-etl": "# Summary: etl\n\n- The load job copies visits nightly. %s\n" % TAG_ETL,
    "root": '# Summary: KB\n\n- The KB covers pets and visits. [E: file:r.txt "pets have owners"; file:r.txt "visits"]\n- A nightly job loads visits. %s\n' % TAG_ETL,
}


class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.kb = make_kb(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def out_dir(self):
        return os.path.join(self.kb, ".metis", "summaries", "out")

    def write_out(self, files):
        for aid, text in files.items():
            write(os.path.join(self.out_dir(), aid + ".md"), text)

    def test_tree_has_folder_areas_pages_objects_and_questions(self):
        r = M.build(self.kb)
        self.assertEqual(r["pages"], 5)
        tree = M.load_tree(self.kb)
        self.assertEqual(sorted(tree["areas"]), sorted(["area-db", "area-etl"] + [a for a in tree["areas"] if a.startswith("cluster-")]))
        db = tree["areas"]["area-db"]
        self.assertEqual(db["pages"], ["db/OWNERS.md", "db/PETS.md", "db/VISITS.md"])
        self.assertEqual(db["open_questions"], ["Q-0001"])
        self.assertTrue(any("table:PETS" in o for o in db["key_objects"]))
        self.assertEqual(db["tag_count"], 3)  # tags per page, summed over the area's three pages

    def test_graph_connectivity_makes_a_cross_folder_cluster(self):
        M.build(self.kb)
        tree = M.load_tree(self.kb)
        clusters = [a for k, a in tree["areas"].items() if k.startswith("cluster-")]
        self.assertEqual(len(clusters), 1)
        self.assertIn("etl/LOAD.md", clusters[0]["pages"])
        self.assertIn("db/VISITS.md", clusters[0]["pages"])
        self.assertEqual(clusters[0]["folders"], ["db", "etl"])
        self.assertIn(list(tree["areas"])[-1], tree["root"]["children"])

    def test_deterministic(self):
        M.build(self.kb)
        with open(M.tree_path(self.kb), encoding="utf-8") as fh:
            a = fh.read()
        M.build(self.kb)
        with open(M.tree_path(self.kb), encoding="utf-8") as fh:
            self.assertEqual(a, fh.read())

    def test_no_graph_still_gives_folder_areas(self):
        os.remove(os.path.join(self.kb, "CROSS-LAYER", "LINK_GRAPH.yaml"))
        M.build(self.kb)
        self.assertEqual(sorted(M.load_tree(self.kb)["areas"]), ["area-db", "area-etl"])

    def test_large_folder_is_split_by_subfolder(self):
        for i in range(14):
            write(os.path.join(self.kb, "big", "sub%d" % (i % 2), "P%d.md" % i), "# P%d\n\nx %s\n" % (i, TAG_PETS))
        M.build(self.kb)
        tree = M.load_tree(self.kb)
        self.assertEqual(sorted(tree["areas"]["area-big"]["children"]), ["area-big-sub0", "area-big-sub1"])
        self.assertEqual(tree["areas"]["area-big-sub0"]["parent"], "area-big")
        self.assertLess(M.order(tree).index("area-big-sub0"), M.order(tree).index("area-big"))
        self.assertEqual(len(M.descendants(tree, "area-big")), 14)

    def test_summaries_and_sensitive_pages_are_not_summarised(self):
        write(os.path.join(self.kb, "summaries", "area-x.md"), "---\ntype: area-summary\n---\n# S\n\nx %s\n" % TAG_PETS)
        write(os.path.join(self.kb, "db", "SECRET.md"), "# S\n\npassword: hunter2hunter2 %s\n" % TAG_PETS)
        write(os.path.join(self.kb, "db", "GEN.md"), "# Generated by gen_x.py\n\nx\n")
        M.build(self.kb)
        pages = [p for a in M.load_tree(self.kb)["areas"].values() for p in a["pages"]]
        self.assertNotIn("summaries/area-x.md", pages)
        self.assertNotIn("db/SECRET.md", pages)
        self.assertNotIn("db/GEN.md", pages)

    def test_prompt_lists_areas_rules_and_children_first(self):
        M.build(self.kb)
        with open(os.path.join(self.kb, ".metis", "summaries", M.PROMPT), encoding="utf-8") as fh:
            p = fh.read()
        for needle in ("area-db", "area-etl", "db/PETS.md", "[E: ...]", "character for character", "Do not write into the KB folders", "root.md",
                       "kb_summaries.py verify", "Open questions on these pages: Q-0001"):
            self.assertIn(needle, p)

    def test_verify_accepts_good_summaries(self):
        M.build(self.kb)
        self.write_out(GOOD)
        rep = M.verify(self.kb)
        self.assertEqual(rep["problems"], [])
        self.assertTrue(rep["ok"])
        self.assertEqual(sorted(rep["files"]), ["area-db", "area-etl", "root"])
        self.assertTrue(any(m.startswith("cluster-") for m in rep["missing"]))

    def test_verify_rejects_line_without_tag(self):
        M.build(self.kb)
        self.write_out({"area-etl": "# S\n\n- The load job runs. \n"})
        rep = M.verify(self.kb)
        self.assertFalse(rep["ok"])
        self.assertIn("no [E: ...] tag", rep["problems"][0]["problem"])

    def test_verify_rejects_invented_tag(self):
        M.build(self.kb)
        self.write_out({"area-etl": '# S\n\n- The load job runs. [E: file:r.txt "pets have owners"]\n'})  # resolves, but not a tag of this area
        rep = M.verify(self.kb)
        self.assertFalse(rep["ok"])
        self.assertIn("is not a tag of any page in area-etl", rep["problems"][0]["problem"])

    def test_verify_rejects_tag_that_does_not_resolve(self):
        M.build(self.kb)
        write(os.path.join(self.kb, "etl", "NOTES.md"), '# Notes\n\nRuns. [E: file:missing.txt "x"]\n')
        M.build(self.kb)
        self.write_out({"area-etl": '# S\n\n- Runs. [E: file:missing.txt "x"]\n'})
        rep = M.verify(self.kb)
        self.assertTrue(any("supplied file missing" in p["problem"] for p in rep["problems"]))

    def test_verify_rejects_shortened_quote_and_unknown_area_and_secret(self):
        M.build(self.kb)
        self.write_out({"area-etl": '# S\n\n- Runs. [E: file:r.txt "nightl"]\n', "area-nope": "# S\n\n- x %s\n" % TAG_ETL,
                        "area-db": "# S\n\n- password: hunter2hunter2 %s\n" % TAG_PETS})
        probs = {(p["file"], p["problem"].split(" ")[0]) for p in M.verify(self.kb)["problems"]}
        files = {f for f, _ in probs}
        self.assertEqual(files, {"area-etl.md", "area-nope.md", "area-db.md"})

    def test_parent_may_use_tags_of_children_but_child_not_siblings(self):
        for i in range(14):
            write(os.path.join(self.kb, "big", "sub%d" % (i % 2), "P%d.md" % i), "# P%d\n\nx [E: file:r.txt \"t%d\"]\n" % (i, i))
        write(os.path.join(self.kb, "_EVIDENCE", "files", "r.txt"), "pets have owners\nvisits\nnightly\n" + "".join("t%d\n" % i for i in range(14)))
        M.build(self.kb)
        self.write_out({"area-big": '# S\n\n- a [E: file:r.txt "t0"]\n- b [E: file:r.txt "t1"]\n',
                        "area-big-sub0": '# S\n\n- a [E: file:r.txt "t0"]\n- b [E: file:r.txt "t1"]\n'})
        probs = M.verify(self.kb)["problems"]
        self.assertEqual({p["file"] for p in probs}, {"area-big-sub0.md"})
        self.assertEqual(len(probs), 1)

    def test_stage_goes_through_pending_and_never_into_the_kb(self):
        M.build(self.kb)
        self.write_out(GOOD)
        kb_gate.lock(self.kb, "Ana Lead")
        r = M.stage(self.kb, "Devin")
        self.assertEqual(sorted(r["staged"]), ["summaries/area-db.md", "summaries/area-etl.md", "summaries/root.md"])
        self.assertFalse(os.path.exists(os.path.join(self.kb, "summaries")))
        staged = os.path.join(self.kb, "_PENDING", r["batch"], "summaries", "area-db.md")
        with open(staged, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("type: area-summary", text)
        self.assertIn(TAG_PETS, text)
        self.assertIn(r["batch"], kb_gate.batches(self.kb))
        # the lead can certify it like any other change, and the summary is then in the KB with its tags
        kb_gate.certify(self.kb, r["batch"], "Ana Lead")
        self.assertTrue(os.path.isfile(os.path.join(self.kb, "summaries", "area-db.md")))
        M.build(self.kb)  # a certified summary is not summarised again
        self.assertNotIn("summaries/area-db.md", [p for a in M.load_tree(self.kb)["areas"].values() for p in a["pages"]])

    def test_stage_refuses_everything_when_one_page_fails(self):
        M.build(self.kb)
        self.write_out(dict(GOOD, **{"area-etl": "# S\n\n- no tag here\n"}))
        with self.assertRaises(M.SummaryError):
            M.stage(self.kb, "Devin")
        self.assertFalse(os.path.isdir(os.path.join(self.kb, "_PENDING")))

    def test_stage_needs_a_name_and_pages(self):
        M.build(self.kb)
        with self.assertRaises(M.SummaryError):
            M.stage(self.kb, " ")
        with self.assertRaises(M.SummaryError):
            M.stage(self.kb, "Devin")  # out folder is empty

    def test_status_flags_pages_changed_since_build(self):
        M.build(self.kb)
        self.write_out(GOOD)
        self.assertEqual(M.status(self.kb)["pages_changed_since_build"], [])
        write(os.path.join(self.kb, "db", "PETS.md"), "# PETS\n\nChanged. %s\n" % TAG_PETS)
        st = M.status(self.kb)
        self.assertEqual(st["pages_changed_since_build"], ["db/PETS.md"])
        self.assertIn("area-db", st["written"])

    def test_verify_needs_a_tree(self):
        with self.assertRaises(M.SummaryError):
            M.verify(self.kb)

    def test_cli(self):
        def run(*argv):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                code = M.main(list(argv))
            return code, buf.getvalue()
        self.assertEqual(run("build", self.kb)[0], 0)
        self.assertEqual(run("status", self.kb)[0], 0)
        self.write_out(GOOD)
        code, out = run("verify", self.kb)
        self.assertEqual(code, 0, out)
        self.assertIn("0 problems", out)
        self.write_out({"area-etl": "# S\n\n- no tag\n"})
        self.assertEqual(run("verify", self.kb)[0], 1)
        self.assertEqual(run("stage", self.kb, "--by", "Devin")[0], 2)
        self.assertEqual(run("verify", os.path.join(self.tmp, "nope"))[0], 2)


if __name__ == "__main__":
    unittest.main()
