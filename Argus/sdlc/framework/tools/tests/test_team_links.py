"""Team links (tools/team_links.py): Confluence pages and document paths come from the team settings."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)

import team_links  # noqa: E402
import roster_sync  # noqa: E402

SAMPLE = os.path.join(team_links.ROOT, "sdlc", "kb", "examples", "acme", "sdlc-profile.json")
OURS = os.path.join(team_links.ROOT, ".devin", "rules", "sdlc-profile.json")


def shape(node):
    return {k: shape(v) for k, v in node.items()} if isinstance(node, dict) else None


class TeamLinksTests(unittest.TestCase):
    def test_our_documents_exist(self):
        for name, path in team_links.docs(team_links.load(OURS)).items():
            self.assertTrue(os.path.exists(os.path.join(team_links.ROOT, path)), "docs.%s: %s is missing" % (name, path))

    def test_acme_has_the_same_settings_as_ours(self):
        ours, acme = team_links.load(OURS), team_links.load(SAMPLE)
        for key in ("confluence", "docs", "workflow"):
            self.assertEqual(shape(acme[key]), shape(ours[key]), key)
        self.assertEqual(shape(acme["jira"]["statuses"]), shape(ours["jira"]["statuses"]))

    def test_every_status_slot_has_a_status_list(self):
        import yaml
        with open(os.path.join(team_links.ROOT, ".devin", "rules", "dashboard-roles.yaml")) as fh:
            panels = yaml.safe_load(fh)["panels"]
        jql = [p["jql"] for p in panels.values() if isinstance(p, dict) and p.get("jql")]
        self.assertTrue(any("{statuses." in q for q in jql))
        for path in (OURS, SAMPLE):
            data = team_links.load(path)
            for text in jql + list(data["jira"]["queries"].values()):
                self.assertNotIn("{statuses.", team_links.fill_statuses(text, data), path)
            self.assertTrue(data["jira"]["phases"], path)

    def test_statuses_are_quoted(self):
        data = {"jira": {"statuses": {"qa": ["In QA", 'Say "done"']}}}
        self.assertEqual(team_links.fill_statuses("status in ({statuses.qa})", data),
                         'status in ("In QA", "Say \\"done\\"")')
        with self.assertRaises(team_links.LinksError):
            team_links.fill_statuses("status in ({statuses.nope})", data)

    def test_roster_sync_reads_the_roster_page_from_the_settings(self):
        c = team_links.confluence(team_links.load(OURS))
        self.assertEqual(roster_sync.PAGE_TITLE, c["pages"]["roster"]["title"])
        self.assertEqual(roster_sync.CONFLUENCE, c["host"])
        self.assertEqual(roster_sync.TOKEN_ENV, c["token_env"])

    # shared-copy sample: begin (install.py leaves these lines as Acme: they test the Acme example)
    def test_page_urls(self):
        self.assertEqual(team_links.page_url("roster", team_links.load(SAMPLE)),
                         "https://wiki.acme.example/pages/viewpage.action?pageId=100002")
    # shared-copy sample: end

    def test_tools_hold_no_confluence_host(self):
        for name in ("roster_sync.py", "gen_reference_pages.py"):
            with open(os.path.join(TOOLS, name), encoding="utf-8") as fh:
                self.assertNotIn("wiki.acme.example", fh.read(), name)

    def test_a_missing_page_is_named(self):
        data = team_links.load(SAMPLE)
        del data["confluence"]["pages"]["roster"]["title"]
        with self.assertRaises(team_links.LinksError) as e:
            team_links.confluence(data)
        self.assertIn("confluence.pages.roster", str(e.exception))

    def test_roster_sync_without_settings_stops_in_one_line(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "p.json")
            with open(path, "w") as fh:
                json.dump({"jira": {}}, fh)
            r = subprocess.run([sys.executable, os.path.join(TOOLS, "roster_sync.py"), "check"], capture_output=True,
                               text=True, env=dict(os.environ, SDLC_PROFILE=path), timeout=60)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no confluence.host", r.stderr)
        self.assertNotIn("Traceback", r.stderr)


if __name__ == "__main__":
    unittest.main()
