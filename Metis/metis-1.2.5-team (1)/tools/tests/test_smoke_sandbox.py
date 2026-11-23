"""Smoke test on real repos: a copy of sandbox/DEMO-KB (built from jaffle-shop and spring-petclinic).

Runs the source check against the real repo files, builds a context pack from a task, and searches. It is skipped
when the sandbox is not there. It shows the tools work on real code and a real KB, not that CI, a real MCP client or
a live Confluence/Jira/Snowflake would: those still need your environment.
"""
import os
import shutil
import sys
import tempfile
import unittest

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
SANDBOX = os.path.join(ROOT, "sandbox")
DEMO = os.path.join(SANDBOX, "DEMO-KB")
REPOS = os.path.join(SANDBOX, "repos")

import verify_kb  # noqa: E402
import context_pack  # noqa: E402
import kb_search  # noqa: E402


@unittest.skipUnless(os.path.isdir(DEMO) and os.path.isdir(os.path.join(REPOS, "jaffle-shop"))
                     and os.path.isdir(os.path.join(REPOS, "spring-petclinic")), "sandbox repos or DEMO-KB not present")
class SandboxSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.kb = os.path.join(cls.tmp, "kb")
        shutil.copytree(DEMO, cls.kb)
        prof = os.path.join(cls.kb, ".metis", "kb-profile.yaml")
        with open(prof, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        data["sources"]["workspace_root"] = REPOS
        with open(prof, "w", encoding="utf-8") as fh:
            yaml.safe_dump(data, fh)
        for f in ("search.sqlite", "graph.sqlite", "shared.sqlite"):  # rebuilt from the pages, not trusted from the copy
            p = os.path.join(cls.kb, ".metis", f)
            if os.path.exists(p):
                os.remove(p)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_pages_cite_real_repo_lines(self):
        rep = verify_kb.Checker(self.kb).run()
        self.assertGreater(rep["tags"], 0, "the demo KB should carry source tags")
        self.assertEqual(rep["problems"], [], rep["problems"][:5])

    def test_search_finds_a_page(self):
        kb_search.sync(self.kb)
        res = kb_search.search(self.kb, "customers", limit=5)
        self.assertTrue(res["results"], "search over the demo KB returned nothing")

    def test_pack_from_task_has_pages_and_tags(self):
        pack = context_pack.build(self.kb, task="which dbt models read the customers table", budget=6000)
        self.assertTrue(pack["files"], "the pack named no KB page")
        self.assertIn("[E:", pack["text"])
        self.assertLessEqual(pack["tokens"], pack["budget"])


if __name__ == "__main__":
    unittest.main()
