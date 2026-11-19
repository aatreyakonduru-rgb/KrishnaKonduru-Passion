"""Fixes from the V2 patch validation: patch drift check and full backup, no fetch when remote reads are off,
the sandbox built like an installed profile, story keys from the profile."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(TOOLS, "installer"))
sys.path.insert(0, os.path.join(TOOLS, "sandbox"))
sys.path.insert(0, os.path.join(TOOLS, "kbgen"))
sys.path.insert(0, os.path.join(os.path.dirname(TOOLS), "console"))
import make_sandbox  # noqa: E402
import update  # noqa: E402

try:
    import patch  # noqa: E402  (tools/installer; a shared copy keeps the installer at its top level)
except ImportError:
    patch = None


def git(cwd, *args):
    subprocess.run(["git", "-C", cwd] + list(args), check=True, capture_output=True,
                   env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@x", GIT_COMMITTER_NAME="t",
                            GIT_COMMITTER_EMAIL="t@x"))


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


@unittest.skipIf(patch is None, "patch.py is not in this copy")
class PatchSafetyTests(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.repo, True)
        write(os.path.join(self.repo, "sdlc", "a.md"), "one\n")
        write(os.path.join(self.repo, "docs", "kb", "b.md"), "two\n")
        git(self.repo, "init", "-q")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "x")
        self.roots = patch.touched_roots({"sdlc_dir": "sdlc", "kb_dir": "docs/kb"})

    def test_clean_repo_has_no_drift(self):
        self.assertEqual(patch.uncommitted(self.repo, self.roots), [])

    def test_local_edit_is_reported(self):
        write(os.path.join(self.repo, "sdlc", "a.md"), "edited\n")
        self.assertEqual(patch.uncommitted(self.repo, self.roots), ["sdlc/a.md"])

    def test_regenerated_and_removed_files_are_backed_up(self):
        backup = os.path.join(self.repo, ".sdlc-patch-backup", "t")
        before = patch.snapshot(self.repo, self.roots, os.path.join(backup, ".before"))
        write(os.path.join(self.repo, "docs", "kb", "b.md"), "regenerated\n")
        os.remove(os.path.join(self.repo, "sdlc", "a.md"))
        self.assertEqual(patch.keep_changed(self.repo, before, backup), 2)
        with open(os.path.join(backup, "docs", "kb", "b.md"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "two\n")
        self.assertTrue(os.path.exists(os.path.join(backup, "sdlc", "a.md")))
        self.assertFalse(os.path.exists(os.path.join(backup, ".before")))


class UpdaterOfflineTests(unittest.TestCase):
    def test_no_fetch_when_remote_reads_are_off(self):
        calls = []

        def fake(repo, *args):
            calls.append(args[0])
            return (0, "main") if args[:2] == ("rev-parse", "--abbrev-ref") else (0, "abc")

        with mock.patch.object(update, "_git", side_effect=fake):
            update.Updater("/nowhere", fetch=False).status(fresh=True)
        self.assertNotIn("fetch", calls)


class SandboxLikeTests(unittest.TestCase):
    def setUp(self):
        self.saved = (make_sandbox.PRODUCT, make_sandbox.PROJECT, make_sandbox.IT_TEAM, make_sandbox.DOMAIN)
        self.addCleanup(self.restore)

    def restore(self):
        make_sandbox.PRODUCT, make_sandbox.PROJECT, make_sandbox.IT_TEAM, make_sandbox.DOMAIN = self.saved

    def test_names_come_from_the_installed_profile(self):
        repo = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, repo, True)
        write(os.path.join(repo, ".devin", "rules", "sdlc-profile.json"),
              json.dumps({"jira": {"project": "LAB", "it_team": "Validation-Lab"}}))
        write(os.path.join(repo, ".devin", "rules", "sdlc-install.yaml"),
              "product_name: Lab Claims\nemail_domain: '@lab.example'\n")
        make_sandbox.like(repo)
        self.assertEqual((make_sandbox.PRODUCT, make_sandbox.PROJECT, make_sandbox.IT_TEAM, make_sandbox.DOMAIN),
                         ("Lab Claims", "LAB", "Validation-Lab", "lab.example"))


class StoryKeyTests(unittest.TestCase):
    def test_story_key_is_the_profile_project(self):
        import gen_link_graph
        import sdlc_profile
        self.assertTrue(gen_link_graph.STORY_RE.search("fix %s-12 now" % sdlc_profile.PROJECT))
        self.assertFalse(gen_link_graph.STORY_RE.search("fix ZZZQ-12 now"))

    def test_other_teams_projects_are_linked_too(self):
        import gen_link_graph
        r = gen_link_graph.story_re(["ACME", "SCRD"])
        self.assertEqual(r.findall("ACME-1 and SCRD-22, not XSCRD-3"), ["ACME-1", "SCRD-22"])


if __name__ == "__main__":
    unittest.main()
