import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gen_dashboard  # noqa: E402


def run(cwd, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME="Tester, Ann", GIT_AUTHOR_EMAIL="a@x", GIT_COMMITTER_NAME="Tester, Ann",
               GIT_COMMITTER_EMAIL="a@x")
    return subprocess.run(("git",) + args, cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout.strip()


class LensFromPrimaryRoleTest(unittest.TestCase):
    def test_primary_role_wins_over_gate_roles(self):
        self.assertEqual(gen_dashboard.select_lens(["tester"], None, "automation_engineer")[0], "automation")

    def test_lens_flag_still_wins(self):
        self.assertEqual(gen_dashboard.select_lens(["tester"], "qa", "automation_engineer")[0], "qa")

    def test_gate_roles_used_without_a_primary_role(self):
        self.assertEqual(gen_dashboard.select_lens(["tester"])[0], "qa")
        self.assertEqual(gen_dashboard.select_lens(["tester"], None, "no_such_role")[0], "qa")


class AutomationBranchesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        repo = self.repo = self.tmp.name
        run(repo, "init", "-q", "-b", "Test_Bamboo")
        with open(os.path.join(repo, "a.txt"), "w") as fh:
            fh.write("one\n")
        run(repo, "add", "a.txt")
        run(repo, "commit", "-qm", "base")
        run(repo, "update-ref", "refs/remotes/origin/Test_Bamboo", "HEAD")
        run(repo, "checkout", "-qb", "work")
        with open(os.path.join(repo, "b.txt"), "w") as fh:
            fh.write("two\n")
        run(repo, "add", "b.txt")
        run(repo, "commit", "-qm", "ACME-123 automation")
        run(repo, "update-ref", "refs/remotes/origin/ACME_Automation_AB12345", "HEAD")
        run(repo, "update-ref", "refs/remotes/origin/feature/ACME-123-cases", "HEAD")

    def tearDown(self):
        self.tmp.cleanup()

    def test_own_branches_against_the_base(self):
        rows, base, _ = gen_dashboard.automation_branch_rows({"checkout": self.repo}, "AB12345", "Someone Else", fetch=False)
        self.assertEqual(base, "origin/Test_Bamboo")
        self.assertEqual([r["branch"] for r in rows], ["ACME_Automation_AB12345"])
        self.assertEqual((rows[0]["ahead"], rows[0]["behind"], rows[0]["conflicts"]), ("1", "0", False))
        rows, _, _ = gen_dashboard.automation_branch_rows({"checkout": self.repo}, "ZZ0", "Tester, Ann", fetch=False)
        self.assertEqual(sorted(r["key"] for r in rows), ["", "ACME-123"])

    def test_behind_base_is_hot(self):
        state, hot = gen_dashboard.automation_branch_state({"ahead": "2", "behind": "3"}, "origin/Test_Bamboo")
        self.assertTrue(hot)
        self.assertIn("update from it", state)
        self.assertFalse(gen_dashboard.automation_branch_state({"ahead": "0", "behind": "0"}, "origin/Test_Bamboo")[1])

    def test_missing_checkout_says_so(self):
        rows, _, note = gen_dashboard.automation_branch_rows({"checkout": "/no/such/dir"}, "AB12345", "", fetch=False)
        self.assertEqual(rows, [])
        self.assertIn("not checked out", note)


if __name__ == "__main__":
    unittest.main()
