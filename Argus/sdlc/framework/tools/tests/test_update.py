"""Argus self-update (console/update.py) tests: a local bare repo as Bitbucket, no restart for real.

    python3 -m unittest discover -s sdlc/framework/tools/tests -v
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

CONSOLE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "console")
sys.path.insert(0, CONSOLE)

import pctest  # noqa: E402
import update  # noqa: E402

BRANCH = "devin/ACME-1-workbench"


def git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid"] + list(args),
                          cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class UpdaterTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        origin, self.dev, self.pc = (os.path.join(self.dir, n) for n in ("origin.git", "dev", "pc"))
        git(self.dir, "init", "-q", "--bare", origin)
        git(self.dir, "clone", "-q", origin, self.dev)
        git(self.dev, "checkout", "-q", "-b", BRANCH)
        self.commit("one")
        git(self.dir, "clone", "-q", "-b", BRANCH, origin, self.pc)
        self.restarts, self.busy = [], ""
        self.up = update.Updater(self.pc, busy=lambda: self.busy, restart=lambda: self.restarts.append(1), delay=0)

    def commit(self, text):
        with open(os.path.join(self.dev, "server.py"), "w") as fh:
            fh.write(text)
        git(self.dev, "add", "server.py")
        git(self.dev, "commit", "-q", "-m", text)
        git(self.dev, "push", "-q", "origin", BRANCH)

    def test_up_to_date_does_nothing(self):
        st = self.up.status()
        self.assertEqual((st["ok"], st["branch"], st["behind"], st["why"]), (True, BRANCH, 0, ""))
        self.assertFalse(self.up.apply()["updated"])
        self.assertEqual(self.restarts, [])

    def test_new_commit_on_bitbucket_is_pulled_and_the_server_restarts(self):
        self.commit("two")
        st = self.up.status(fresh=True)
        self.assertEqual(st["behind"], 1)
        out = self.up.apply()
        self.up.timer.join(5)
        self.assertTrue(out["updated"])
        self.assertEqual((out["was"], out["head"], out["behind"]), (st["head"], st["remote"], 0))
        with open(os.path.join(self.pc, "server.py")) as fh:
            self.assertEqual(fh.read(), "two")
        self.assertEqual(self.restarts, [1])

    def test_refuses_while_a_test_runs_or_the_checkout_has_changes(self):
        self.commit("two")
        self.busy = "A test of ACME-1 is running."
        st = self.up.status(fresh=True)
        self.assertTrue(st["busy"])
        self.assertEqual(st["behind"], 1)
        with self.assertRaises(pctest.PcError) as err:
            self.up.apply()
        self.assertEqual(err.exception.status, 409)
        self.busy = ""
        with open(os.path.join(self.pc, "server.py"), "w") as fh:
            fh.write("edited on the PC")
        with self.assertRaises(pctest.PcError) as err:
            self.up.apply()
        self.assertIn("local changes", str(err.exception))
        git(self.pc, "checkout", "-q", "--", "server.py")
        git(self.pc, "commit", "-q", "--allow-empty", "-m", "local only")
        self.assertIn("not on Bitbucket", self.up.status(fresh=True)["why"])
        self.assertEqual(self.restarts, [])

    def test_about_shows_the_version_and_the_last_commit(self):
        os.makedirs(os.path.join(self.dev, "tools"))
        prompts = os.path.join(self.dev, "sdlc/kb/VERSION")
        os.makedirs(os.path.dirname(prompts))
        with open(os.path.join(self.dev, "tools", "distribution_map.yaml"), "w") as fh:
            fh.write('# map\nversion: "1.2345"\noutput: sdlc/kb/v1.2345\n')
        with open(prompts, "w") as fh:
            fh.write("2.1.0\n")
        git(self.dev, "add", "-A")
        git(self.dev, "commit", "-q", "-m", "versions")
        a = update.about(self.dev, tools=os.path.join(self.dev, "tools"))
        self.assertEqual((a["version"], a["prompts_version"], a["branch"]), ("1.2345", "2.1.0", BRANCH))
        self.assertEqual(a["commit"], git(self.dev, "log", "-1", "--format=%h"))
        self.assertEqual(a["commit_date"], git(self.dev, "log", "-1", "--format=%cI"))

    def test_about_in_a_shared_copy_reads_tools_version(self):
        os.makedirs(os.path.join(self.dev, "tools"))
        with open(os.path.join(self.dev, "tools", "VERSION"), "w") as fh:
            fh.write("1.2345\n")
        self.assertEqual(update.about(self.dev, tools=os.path.join(self.dev, "tools"))["version"], "1.2345")

    def test_about_without_version_files_still_shows_the_commit(self):
        a = update.about(self.pc, tools=os.path.join(self.pc, "tools"))
        self.assertEqual((a["version"], a["prompts_version"]), ("", ""))
        self.assertTrue(a["commit"] and a["commit_date"])

    def test_detached_checkout_cannot_update(self):
        git(self.pc, "checkout", "-q", "--detach")
        self.assertFalse(self.up.status()["ok"])


if __name__ == "__main__":
    unittest.main()
