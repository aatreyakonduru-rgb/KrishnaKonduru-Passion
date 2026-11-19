"""Check my PC (console/doctor.py): every check reports ok or a fix, and one failure does not hide the rest."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

CONSOLE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "console")
sys.path.insert(0, CONSOLE)

import doctor  # noqa: E402
import pctest  # noqa: E402
import update  # noqa: E402


def git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid"] + list(args),
                   cwd=cwd, check=True, capture_output=True)


class FakeDevin:
    def __init__(self, key="k", error=None):
        self.key, self.error = key, error

    def list_sessions(self, tag, limit=50):
        if self.error:
            raise self.error
        return []


class DoctorTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        origin, self.repo = os.path.join(self.dir, "origin.git"), os.path.join(self.dir, "pc")
        git(self.dir, "init", "-q", "--bare", origin)
        git(self.dir, "clone", "-q", origin, self.repo)
        git(self.repo, "checkout", "-q", "-b", "feature/x")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "one")
        git(self.repo, "push", "-q", "origin", "feature/x")
        self.updater = update.Updater(self.repo)
        patches = [mock.patch.object(pctest, "devin_cli", return_value=sys.executable),
                   mock.patch.object(pctest, "tester_python", return_value=sys.executable),
                   mock.patch.object(pctest, "work_root", return_value=os.path.join(self.dir, "work"))]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def by_name(self, devin):
        return {c["name"]: c for c in doctor.run(self.repo, self.updater, devin)}

    def test_healthy_pc_passes_every_check(self):
        checks = self.by_name(FakeDevin())
        self.assertEqual(len(checks), 9)
        self.assertEqual([n for n, c in checks.items() if not c["ok"]], [])
        self.assertTrue(all(c["fix"] == "" for c in checks.values()))
        self.assertIn("feature/x", checks["This copy of Argus"]["detail"])

    def test_refused_key_and_missing_key_say_what_to_do(self):
        checks = self.by_name(FakeDevin(error=RuntimeError("Devin API 401 on /sessions: bad key")))
        self.assertFalse(checks["Devin Cloud"]["ok"])
        self.assertIn("make a new key", checks["Devin Cloud"]["fix"].lower())
        checks = self.by_name(FakeDevin(key=""))
        self.assertFalse(checks["Devin API key"]["ok"])
        self.assertIn("Not tried", checks["Devin Cloud"]["detail"])

    def test_missing_cli_and_unreachable_bitbucket_are_reported_without_hiding_others(self):
        git(self.repo, "remote", "set-url", "origin", os.path.join(self.dir, "gone.git"))
        with mock.patch.object(pctest, "devin_cli", return_value=""):
            checks = self.by_name(FakeDevin())
        self.assertFalse(checks["Devin Local (CLI)"]["ok"])
        self.assertIn("docs.devin.ai/cli", checks["Devin Local (CLI)"]["fix"])
        self.assertFalse(checks["Bitbucket"]["ok"])
        self.assertTrue(checks["Python"]["ok"])
        self.assertTrue(checks["Ticket folders"]["ok"])


if __name__ == "__main__":
    unittest.main()
