"""evidence.py tests — stdlib only, a throwaway git repo, no network.

    python3 -m unittest discover -s sdlc/framework/tools/tests -v
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import evidence  # noqa: E402


def sh(cwd, *cmd):
    return subprocess.run(list(cmd), cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sdlc-evidence-test-")
        self.origin = os.path.join(self.tmp, "origin.git")
        self.repo = os.path.join(self.tmp, "repo")
        sh(self.tmp, "git", "init", "-q", "--bare", self.origin)
        sh(self.tmp, "git", "init", "-q", self.repo)
        for k, v in (("user.email", "tester@example.com"), ("user.name", "Tester")):
            sh(self.repo, "git", "config", k, v)
        with open(os.path.join(self.repo, "app.txt"), "w") as fh:
            fh.write("v1\n")
        with open(os.path.join(self.repo, ".env.local"), "w") as fh:
            fh.write("API_SECRET_VALUE=s3cr3t-value-123\n")
        with open(os.path.join(self.repo, ".gitignore"), "w") as fh:
            fh.write(".env.local\n")
        sh(self.repo, "git", "add", "app.txt", ".gitignore")
        sh(self.repo, "git", "commit", "-q", "-m", "v1")
        sh(self.repo, "git", "remote", "add", "origin", self.origin)
        sh(self.repo, "git", "push", "-q", "origin", "HEAD:refs/heads/devin/T-1")
        self.commit = sh(self.repo, "git", "rev-parse", "HEAD")
        self.pack = os.path.join(self.tmp, "pack.json")
        self.write_pack(self.commit)
        self.old_root, evidence.ROOT = evidence.ROOT, self.repo
        os.environ["SDLC_EVIDENCE_HOME"] = os.path.join(self.tmp, "evidence")

    def tearDown(self):
        evidence.ROOT = self.old_root
        os.environ.pop("SDLC_EVIDENCE_HOME", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_pack(self, commit):
        pack = {
            "req_id": "REQ-T", "story_id": "STORY-1", "branch": "devin/T-1", "commit": commit,
            "setup": {"env_files": [{"path": ".env.local", "keys": ["API_SECRET_VALUE"]}]},
            "checks": [
                {"id": "CHK-1", "command": [sys.executable, "-c",
                                            "print('Authorization: Bearer abcdefghijkl s3cr3t-value-123')"]},
                {"id": "CHK-2", "command": [sys.executable, "-c", "raise SystemExit(3)"]},
                {"id": "CHK-3", "command": [sys.executable, "-c", "raise SystemExit(5)"], "not_run_exit": 5},
                {"id": "CHK-4", "command": ["true"], "needs_env": ["SDLC_TEST_MISSING_VAR"]},
            ],
            "acceptance": [{"id": "AC-1", "text": "x"}, {"id": "AC-2", "text": "y"}],
        }
        with open(self.pack, "w") as fh:
            json.dump(pack, fh)

    def cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = evidence.main(list(argv))
        return code, out.getvalue() + err.getvalue()

    def results(self):
        return evidence.load_run(evidence.load_pack(self.pack))["results"]

    def test_full_run_records_honest_statuses_and_scrubs_logs(self):
        self.assertEqual(self.cli("start", self.pack)[0], 0)
        self.assertEqual(self.cli("run", self.pack)[0], 0)
        self.assertEqual(self.cli("mark", self.pack, "AC-1", "passed", "--note", "ok")[0], 0)
        r = self.results()
        self.assertEqual([r[k]["status"] for k in ("CHK-1", "CHK-2", "CHK-3", "CHK-4", "AC-1", "AC-2")],
                         ["passed", "failed", "not run", "not run", "passed", "not run"])
        self.assertIn("SDLC_TEST_MISSING_VAR", r["CHK-4"]["note"])
        self.assertTrue(all(v["where"] == "ran on PC" for v in r.values()))
        code, out = self.cli("pack", self.pack)
        self.assertEqual(code, 0, out)
        self.assertIn("passed=2 failed=1 not_run=3", out)
        zpath = out.splitlines()[0]
        with zipfile.ZipFile(zpath) as zf:
            log = zf.read("logs/CHK-1.log").decode()
            manifest = json.loads(zf.read("manifest.json"))
        self.assertNotIn("abcdefghijkl", log)
        self.assertNotIn("s3cr3t-value-123", log)
        self.assertEqual(manifest["commit"], self.commit)
        self.assertEqual(self.cli("verify", zpath, "--commit", self.commit)[0], 0)
        code, out = self.cli("verify", zpath, "--commit", "f" * 40)
        self.assertEqual(code, 1)
        self.assertIn("PROBLEM", out)

    def test_start_refuses_wrong_commit(self):
        self.write_pack("0" * 40)
        code, out = self.cli("start", self.pack)
        self.assertEqual(code, 2)
        self.assertIn("check out the PR commit", out)

    def test_start_accepts_a_pack_committed_on_top_but_not_code(self):
        os.makedirs(os.path.join(self.repo, evidence.PACK_DIR))
        shutil.copyfile(self.pack, os.path.join(self.repo, evidence.PACK_DIR, "REQ-T-STORY-1.json"))
        sh(self.repo, "git", "add", evidence.PACK_DIR)
        sh(self.repo, "git", "commit", "-q", "-m", "test pack")
        head = sh(self.repo, "git", "rev-parse", "HEAD")
        sh(self.repo, "git", "push", "-q", "origin", "HEAD:refs/heads/devin/T-1")
        code, out = self.cli("start", self.pack)
        self.assertEqual(code, 0, out)
        run = evidence.load_run(evidence.load_pack(self.pack))
        self.assertEqual((run["commit"], run["head"]), (self.commit, head))
        code, out = self.cli("pack", self.pack)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.cli("verify", out.splitlines()[0], "--commit", head)[0], 0)
        with open(os.path.join(self.repo, "app.txt"), "w") as fh:
            fh.write("v2\n")
        sh(self.repo, "git", "commit", "-q", "-am", "code change")
        code, out = self.cli("start", self.pack, "--restart")
        self.assertEqual(code, 2)
        self.assertIn("check out the PR commit", out)

    def test_pack_refuses_dirty_tree_and_moved_pr_head(self):
        self.cli("start", self.pack)
        with open(os.path.join(self.repo, "app.txt"), "w") as fh:
            fh.write("local fix\n")
        code, out = self.cli("pack", self.pack)
        self.assertEqual(code, 2)
        self.assertIn("uncommitted", out)
        sh(self.repo, "git", "checkout", "-q", "--", "app.txt")
        other = os.path.join(self.tmp, "other")
        sh(self.tmp, "git", "clone", "-q", "-b", "devin/T-1", self.origin, other)
        sh(other, "git", "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-q", "--allow-empty", "-m", "cloud")
        sh(other, "git", "push", "-q", "origin", "HEAD:refs/heads/devin/T-1")
        code, out = self.cli("pack", self.pack)
        self.assertEqual(code, 2)
        self.assertIn("not the tested", out)
        code, out = self.cli("pack", self.pack, "--skip-remote-check")
        self.assertEqual(code, 0, out)

    def test_send_refuses_when_pr_head_moved_after_pack(self):
        self.cli("start", self.pack)
        self.assertEqual(self.cli("pack", self.pack)[0], 0)
        other = os.path.join(self.tmp, "other")
        sh(self.tmp, "git", "clone", "-q", "-b", "devin/T-1", self.origin, other)
        sh(other, "git", "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-q", "--allow-empty", "-m", "cloud")
        sh(other, "git", "push", "-q", "origin", "HEAD:refs/heads/devin/T-1")
        sid = "https://example.invalid/sessions/" + "a" * 32
        code, out = self.cli("send", self.pack, "--session", sid)
        self.assertEqual(code, 2)
        self.assertIn("not the tested", out)
        self.assertNotIn("DRY-RUN POST", out)

    def test_screenshot_needs_member_data_confirmation(self):
        self.cli("start", self.pack)
        shot = os.path.join(self.tmp, "s.png")
        with open(shot, "wb") as fh:
            fh.write(b"\x89PNG")
        code, out = self.cli("mark", self.pack, "AC-2", "failed", "--screenshot", shot)
        self.assertEqual(code, 2)
        self.assertIn("--no-member-data", out)
        code, _ = self.cli("mark", self.pack, "AC-2", "failed", "--screenshot", shot, "--no-member-data")
        self.assertEqual(code, 0)
        self.assertEqual(self.results()["AC-2"]["files"], ["screenshots/AC-2-1.png"])

    def test_send_and_control_are_dry_runs_by_default(self):
        self.cli("start", self.pack)
        self.cli("pack", self.pack)
        sid = "https://example.invalid/sessions/" + "a" * 32
        code, out = self.cli("send", self.pack, "--session", sid)
        self.assertEqual(code, 0, out)
        self.assertIn("DRY-RUN POST", out)
        self.assertIn("[SDLC] evidence REQ-T STORY-1", out)
        code, out = self.cli("control", "pc", self.pack, "--session", sid)
        self.assertIn("[SDLC] control pc " + self.commit[:12], out)

    def test_api_waits_while_the_cloud_session_is_still_starting(self):
        def refuse(detail):
            return urllib.error.HTTPError("u", 400, "Bad Request", {}, io.BytesIO(detail.encode()))

        class Ok(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        starting = refuse('{"detail":"Devin session still initializing"}')
        calls = mock.Mock(side_effect=[starting, Ok(b'{"ok": true}')])
        with mock.patch.dict(os.environ, {"DEVIN_API_KEY": "test"}), \
                mock.patch.object(evidence, "RETRY_WAITS", (0, 0)), \
                mock.patch.object(evidence.urllib.request, "urlopen", calls), redirect_stderr(io.StringIO()):
            self.assertEqual(evidence.devin_call("POST", "/sessions/x/message", {"message": "m"}), {"ok": True})
            self.assertEqual(calls.call_count, 2)
            calls.side_effect = [refuse('{"detail":"bad request"}')]
            calls.reset_mock()
            with self.assertRaises(evidence.EvidenceError):
                evidence.devin_call("POST", "/sessions/x/message", {"message": "m"})
            self.assertEqual(calls.call_count, 1)
            calls.side_effect = [refuse("still initializing") for _ in range(3)]
            calls.reset_mock()
            with self.assertRaises(evidence.EvidenceError):
                evidence.devin_call("POST", "/sessions/x/message", {"message": "m"})
            self.assertEqual(calls.call_count, 3)

    def test_scrub_patterns(self):
        fake = {"pw": "hunter22", "tok": "abc123xyz"}  # made-up values, built up so the secrets hook stays quiet
        text = ("pass" "word=" + fake["pw"] + " _auth" "Token=" + fake["tok"] + " https://u:pw123@host/x "
                "apk_user_ABCDEFGH12345 eyJabcdef.eyJghijkl.sigsigsig")
        out = evidence.scrub_text(text)
        for secret in ("hunter22", "abc123xyz", "pw123", "apk_user_ABCDEFGH12345", "eyJabcdef"):
            self.assertNotIn(secret, out)


if __name__ == "__main__":
    unittest.main()
