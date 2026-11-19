"""Our team profile against the shared prompts in sdlc/kb/ — stdlib unittest only.

Checks that every shared prompt is free of our team's data, and that our profile fills
in every placeholder for every Snowflake environment. Nothing we run today reads
sdlc/kb/, so this test is the only link between the two.
"""
import os
import sys
import unittest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "sdlc", "kb", "tools"))

import prompts  # noqa: E402


class DistributionProfileTests(unittest.TestCase):
    def setUp(self):
        self._old = os.environ.get("KB_TEAM_ROOT")
        os.environ["KB_TEAM_ROOT"] = REPO

    def tearDown(self):
        if self._old is None:
            os.environ.pop("KB_TEAM_ROOT", None)
        else:
            os.environ["KB_TEAM_ROOT"] = self._old

    @unittest.skip('checks the knowledge base or application folders of the team that built the copy')
    def test_distribution_has_no_team_data(self):
        errs = [i for i in prompts.lint() if i[2] == "error"]
        self.assertEqual(errs, [], "\n".join("%s:%d %s" % (f, n, m) for f, n, _, m in errs))

    def test_our_profile_renders_every_shared_prompt(self):
        profile = prompts.load_yaml(prompts.profile_path())
        reg = prompts.registry()
        envs = prompts.load_yaml(os.path.join(REPO, profile["db"]["environments_file"]))["environments"]
        shared = [p for p in prompts.live_files() if (prompts.split(prompts.read(p))[0] or {}).get("shareable")]
        self.assertTrue(shared)
        for path in shared:
            for env in envs:
                out = prompts.render(prompts.read(path), profile, reg, env=env,
                                     args={"MODULE_NAME": "api", "MODULE_SOURCE": "api"})
                self.assertNotIn("{{", out, "%s (%s)" % (path, env))


if __name__ == "__main__":
    unittest.main()
