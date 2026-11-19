import io
import os
import stat
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import build_check  # noqa: E402
import promote_check  # noqa: E402

FILES = {
    "origin/develop:api/values-dev.yaml":
        "configmap:\n  data:\n    DEBUG: 'True'\n    NEW_KEY: x\nsecret:\n  keys:\n    secretkey: SECRETKEY\n",
    "origin/sit:api/values-sit.yaml":
        "configmap:\n  data:\n    DEBUG: 'False'\n    SIT_ONLY: y\n",
    "origin/sit:api/tekton-values-sit.yaml":
        "container:\n  image: quay-nonprod.acme.example/claims/crln-shared-sit-img-api:abc123\n",
}


def fake_git(repo, *args, check=False):
    if args[0] == "show":
        return FILES.get(args[1], "")
    return ""


class PromoteCheckTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(promote_check, "git", side_effect=fake_git)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_config_key_diff_reports_names_only(self):
        src = promote_check.config_keys("deploy", "dev", "api")
        dst = promote_check.config_keys("deploy", "sit", "api")
        self.assertEqual(sorted(src - dst), ["NEW_KEY", "secret:SECRETKEY"])
        self.assertEqual(sorted(dst - src), ["SIT_ONLY"])

    def test_image_tag_is_split_from_repository(self):
        repo, tag = promote_check.image_of("deploy", "sit", "api")
        self.assertTrue(repo.endswith("crln-shared-sit-img-api"))
        self.assertEqual(tag, "abc123")

    def test_missing_values_file_is_none(self):
        self.assertIsNone(promote_check.config_keys("deploy", "uat", "api"))

    def test_unverified_environment_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(SystemExit):
            with redirect_stdout(io.StringIO()), mock.patch("sys.stderr", io.StringIO()):
                promote_check.main(["--from", "uat", "--to", "preprod", "--deploy-repo", tmp])

    def test_environments_come_from_the_team_settings(self):
        prod = promote_check.ENVIRONMENTS["prod"]
        self.assertEqual((prod["app_branch"], prod["values"]), ("master", "prod"))
        self.assertTrue(prod["tag_branch"])
        self.assertEqual(promote_check.ORDER[0], "dev")
        self.assertEqual(promote_check.ORDER[-1], "prod")

    def test_skipping_an_environment_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(SystemExit):
            with redirect_stdout(io.StringIO()), mock.patch("sys.stderr", io.StringIO()):
                promote_check.main(["--from", promote_check.ORDER[0], "--to", promote_check.ORDER[-1],
                                    "--deploy-repo", tmp])


class SampleWorkflowTest(unittest.TestCase):
    """The Acme example promotes dev -> qa -> prod: the order and branches are settings, not code."""

    def setUp(self):
        import team_links
        acme = os.path.join(promote_check.ROOT, "sdlc", "kb", "examples", "acme", "sdlc-profile.json")
        if not os.path.exists(acme):
            acme = os.path.join(promote_check.ROOT, "sdlc", "kb", "examples", "acme", "sdlc-profile.json")
        envs, order = promote_check.load_workflow(team_links.load(acme))
        for name, value in (("ENVIRONMENTS", envs), ("ORDER", order)):
            patcher = mock.patch.object(promote_check, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_main(self, *args):
        with redirect_stdout(io.StringIO()) as out, mock.patch("sys.stderr", io.StringIO()) as err:
            try:
                code = promote_check.main(list(args))
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue() + err.getvalue()

    def test_order_is_dev_qa_prod(self):
        self.assertEqual(promote_check.ORDER, ["dev", "qa", "prod"])
        code, out = self.run_main("--list")
        self.assertEqual(code, 0)
        self.assertIn("dev -> qa -> prod", out)

    def test_qa_to_prod_is_the_next_step_and_needs_the_gate(self):
        self.assertEqual(promote_check.ENVIRONMENTS["prod"]["gate"], "SDLC_07_ENV_PROMOTION_APPROVAL")
        self.assertIsNone(promote_check.ENVIRONMENTS["qa"]["gate"])
        with mock.patch.object(promote_check, "git", return_value=""):
            result = promote_check.report("app", "deploy", "qa", "prod", ["web"])
        self.assertEqual(result["gate"], "SDLC_07_ENV_PROMOTION_APPROVAL")
        self.assertNotIn("unmerged_tag_updates", result)
        self.assertEqual(result["app_branches"], ["release/qa", "release/prod"])

    def test_dev_to_prod_skips_qa(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out = self.run_main("--from", "dev", "--to", "prod", "--deploy-repo", tmp)
        self.assertEqual(code, 2)
        self.assertIn("not the next step in dev -> qa -> prod", out)

    def test_an_environment_needs_a_name(self):
        import team_links
        with self.assertRaises(team_links.LinksError):
            promote_check.load_workflow({"workflow": {"environments": [{"app_branch": "x"}]}})
        with self.assertRaises(team_links.LinksError):
            promote_check.load_workflow({})


class BuildCheckTest(unittest.TestCase):
    def test_no_token_skips(self):
        with mock.patch.dict(os.environ, {"ARTIFACTORY_TOKEN": ""}), redirect_stdout(io.StringIO()) as out:
            self.assertEqual(build_check.main(["--component", "api-portal"]), 5)
        self.assertIn("SKIP: artifactory", out.getvalue())

    def test_placeholder_token_skips(self):
        with mock.patch.dict(os.environ, {"ARTIFACTORY_TOKEN": "PLACEHOLDER - not set"}):
            self.assertEqual(build_check.credentials(), (None, None))

    def test_dry_run_needs_no_token(self):
        with mock.patch.dict(os.environ, {"ARTIFACTORY_TOKEN": ""}), redirect_stdout(io.StringIO()) as out:
            self.assertEqual(build_check.main(["--dry-run"]), 0)
        for comp in build_check.PLAN:
            self.assertIn(f"## {comp}", out.getvalue())

    @unittest.skip('checks the knowledge base or application folders of the team that built the copy')
    def test_plan_directories_exist(self):
        for comp, steps in build_check.PLAN.items():
            for _, cwd, _, _ in steps:
                self.assertTrue(os.path.isdir(os.path.join(build_check.ROOT, cwd)), cwd)

    @unittest.skipIf(os.name == "nt", "Windows has no POSIX file modes")
    def test_npmrc_is_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = build_check.npm_userconfig("", "s3cr3t", tmp)
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)

    def test_token_is_masked(self):
        self.assertEqual(build_check.mask("x s3cr3t y", ["s3cr3t"]), "x **** y")


if __name__ == "__main__":
    unittest.main()
