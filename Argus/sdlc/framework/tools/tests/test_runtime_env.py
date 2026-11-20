"""runtime_env.py tests: injected env and platform, no network, no real secrets."""
import json
import os
import sys
import tempfile
import unittest
import unittest.mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import runtime_env as rt  # noqa: E402


def write(root, rel, data):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)


class Detect(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()  # no sdlc-profile.json, so the default token name applies

    def d(self, env, system):
        return rt.detect(env=env, system=system, root=self.root)

    def test_explicit_cloud_wins_over_windows(self):
        r = self.d({"SDLC_RUNTIME": "cloud"}, "Windows")
        self.assertEqual((r["runtime"], r["source"], r["confidence"]), ("cloud", "SDLC_RUNTIME", "high"))

    def test_explicit_local_wins_over_linux_secrets(self):
        env = {"SDLC_RUNTIME": "LOCAL", "DEVIN_API_KEY": "x", "ACME_JIRA_TOKEN": "y"}
        self.assertEqual(self.d(env, "Linux")["runtime"], "local")

    def test_bad_explicit_value_is_unknown_not_a_guess(self):
        r = self.d({"SDLC_RUNTIME": "clod"}, "Windows")
        self.assertEqual(r["runtime"], "unknown")
        self.assertIn("clod", r["reason"])

    def test_transport_bridge_is_cloud_api_is_local(self):
        self.assertEqual(self.d({"SDLC_DEVIN_TRANSPORT": "bridge"}, "Windows")["runtime"], "cloud")
        self.assertEqual(self.d({"SDLC_DEVIN_TRANSPORT": "api"}, "Linux")["runtime"], "local")

    def test_windows_and_mac_are_local(self):
        for system in ("Windows", "Darwin"):
            r = self.d({}, system)
            self.assertEqual((r["runtime"], r["confidence"]), ("local", "medium"))

    def test_linux_with_org_secrets_is_low_confidence_cloud(self):
        r = self.d({"DEVIN_API_KEY": "x", "ACME_JIRA_TOKEN": "y"}, "Linux")
        self.assertEqual((r["runtime"], r["confidence"]), ("cloud", "low"))

    def test_linux_with_one_secret_is_unknown(self):
        self.assertEqual(self.d({"DEVIN_API_KEY": "x"}, "Linux")["runtime"], "unknown")

    def test_bare_linux_is_unknown(self):
        self.assertEqual(self.d({}, "Linux")["runtime"], "unknown")

    def test_token_name_comes_from_the_profile(self):
        write(self.root, ".devin/rules/sdlc-profile.json", {"jira": {"token_env": "MY_JIRA"}})
        self.assertEqual(self.d({"DEVIN_API_KEY": "x", "MY_JIRA": "y"}, "Linux")["runtime"], "cloud")
        self.assertEqual(self.d({"DEVIN_API_KEY": "x", "ACME_JIRA_TOKEN": "y"}, "Linux")["runtime"], "unknown")

    def test_is_cloud_only_for_cloud(self):
        self.assertFalse(rt.is_cloud(env={}, system="Linux", root=self.root))
        self.assertTrue(rt.is_cloud(env={"SDLC_RUNTIME": "cloud"}, system="Linux", root=self.root))


class EffectiveConfig(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        write(self.root, ".devin/config.json", {
            "session_state": {"storage_strategy": "local", "retention_days": 90},
            "git": {"commit_frequency": "milestone"}})
        write(self.root, ".devin/config.cloud.json", {
            "environment": "devin-cloud",
            "session_state": {"storage_strategy": "repository"},
            "git": {"auto_push": True}})

    def cfg(self, env, system="Linux"):
        return rt.effective_config(env=env, system=system, root=self.root)

    def test_local_ignores_cloud_overlay(self):
        c = self.cfg({}, "Windows")
        self.assertEqual(c["session_state"]["storage_strategy"], "local")
        self.assertNotIn("environment", c)

    def test_cloud_overlay_merges_over_base_keeping_the_rest(self):
        c = self.cfg({"SDLC_RUNTIME": "cloud"})
        self.assertEqual(c["session_state"], {"storage_strategy": "repository", "retention_days": 90})
        self.assertEqual(c["git"], {"commit_frequency": "milestone", "auto_push": True})

    def test_unknown_is_not_cloud(self):
        self.assertEqual(self.cfg({})["session_state"]["storage_strategy"], "local")

    def test_local_file_overrides_last(self):
        write(self.root, ".devin/config.local.json", {"session_state": {"storage_strategy": "repo"}})
        self.assertEqual(self.cfg({"SDLC_RUNTIME": "cloud"})["session_state"]["storage_strategy"], "repo")

    def test_underscore_keys_are_comments_not_settings(self):
        write(self.root, ".devin/config.cloud.json", {"_comment": "note", "git": {"auto_push": True}})
        self.assertNotIn("_comment", self.cfg({"SDLC_RUNTIME": "cloud"}))

    def test_missing_files_give_empty_config(self):
        self.assertEqual(rt.effective_config(env={}, system="Linux", root=tempfile.mkdtemp()), {})


class SessionStoreFollowsRuntime(unittest.TestCase):
    """session_store reads the runtime-aware config: the same repo behaves per environment."""

    def strategy(self, env):
        import session_store
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            return session_store.strategy()

    def test_cloud_stores_session_state_in_the_repo(self):
        self.assertEqual(self.strategy({"SDLC_RUNTIME": "cloud"}), "repo")

    def test_local_keeps_the_config_default(self):
        self.assertEqual(self.strategy({"SDLC_RUNTIME": "local"}), "local")  # config.json ships "local"

    def test_explicit_env_still_wins(self):
        self.assertEqual(self.strategy({"SDLC_RUNTIME": "cloud", "SDLC_SESSION_STRATEGY": "local"}), "local")


class Outputs(unittest.TestCase):
    def test_profile_flips_with_runtime(self):
        self.assertTrue(rt.profile("cloud")["auto_commit_push"])
        for r in ("local", "unknown"):
            self.assertFalse(rt.profile(r)["auto_commit_push"])

    def test_probe_has_names_and_booleans_never_values(self):
        out = rt.probe(env={"DEVIN_API_KEY": "super-secret-value", "DEVIN_X": "other-secret"}, system="Linux")
        text = json.dumps(out)
        self.assertNotIn("super-secret-value", text)
        self.assertNotIn("other-secret", text)
        self.assertTrue(out["set"]["DEVIN_API_KEY"])
        self.assertIn("DEVIN_X", out["devin_like_vars"])

    def test_hook_output_is_session_start_context(self):
        out = rt.hook_output(env={"SDLC_RUNTIME": "cloud"}, system="Linux")["hookSpecificOutput"]
        self.assertEqual(out["hookEventName"], "SessionStart")
        self.assertIn("Argus runtime: cloud", out["additionalContext"])
        self.assertIn("Auto commit and push: yes", out["additionalContext"])


if __name__ == "__main__":
    unittest.main()
