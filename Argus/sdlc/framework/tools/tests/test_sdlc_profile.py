"""Argus team settings (console/sdlc_profile.py) — stdlib unittest, no network.

Argus code holds no team values: our own come from .devin/rules/sdlc-profile.json, and
sdlc/kb/examples/acme/ shows another team's made-up ones. These tests run Argus on the
acme settings and check none of ours leak through.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

CONSOLE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "console")
sys.path.insert(0, CONSOLE)

import sdlc_profile as team  # noqa: E402

SAMPLE = os.path.join(team.ROOT, "sdlc", "kb", "examples", "acme")
OUR_TERMS = ()  # add your own words: the sample settings must not contain any of them
CODE = ("server.py", "bridge.py", "pctest.py", "local.py", "doctor.py", "launcher.py", "update.py", "sdlc_profile.py", "run.sh",
        "start-workbench.cmd", "make-shortcut.cmd", "static/console.js", "static/console-run.js", "static/console-pc.js", "static/console-backlog.js", "static/console-auto.js", "static/console-main.js", "static/console-feedback.js", "observer.py", "static/run.js", "static/index.html",
        "static/run.html", "static/local.html")

# Imports Argus with the settings in SDLC_PROFILE and prints what a person would see.
PROBE = r'''
import json, sys
sys.path.insert(0, sys.argv[1])
import server as wb, pctest, local, sdlc_profile as team
pages = {n: team.fill_page(open(wb.STATIC + "/" + n, "rb").read(), wb.PAGE_VALUES).decode() for n in ("index.html", "run.html")}
print(json.dumps({
    "jql": wb.JQL, "fields": wb.STORY_FIELDS, "title": wb.WORKBENCH_TITLE, "repo": wb.REPO_SLUG, "jira": wb.JIRA_HOST,
    "org": wb.DEVIN_ORG, "branch": wb.KB_BRANCH, "token_env": wb.JIRA_TOKEN_ENV, "no_key_env": pctest.NO_KEY_ENV,
    # shared-copy sample: begin (install.py leaves these lines as Acme: they test the Acme example)
    "read": wb.cloud_read_command(["mine", "qa"], "u1"), "ticket_ok": bool(wb.TICKET_RE.match("ACME-12")),
    "pc_ticket_ok": bool(pctest.JIRA_TICKET.match("ACME-12")), "local_jira_env": local.JIRA_ENV,
    # shared-copy sample: end
    "pr": wb.PR_NUMBER_RE.pattern, "pages": pages,
}))
'''


def run_on(profile):
    with tempfile.TemporaryDirectory() as home:
        env = dict(os.environ, SDLC_PROFILE=profile, HOME=home, SDLC_CONSOLE_HOME=os.path.join(home, "console"))
        for k in ("SDLC_JIRA_BASE", "DEVIN_APP_BASE", "DEVIN_ORG_ID"):
            env.pop(k, None)
        r = subprocess.run([sys.executable, "-c", PROBE, CONSOLE], env=env, capture_output=True, text=True, timeout=60)
    if r.returncode:
        raise AssertionError(r.stderr[-2000:])
    return json.loads(r.stdout.strip().splitlines()[-1])


class ProfileTests(unittest.TestCase):
    def test_acme_json_and_yaml_say_the_same(self):
        as_json = team.load(os.path.join(SAMPLE, "sdlc-profile.json"))
        as_json.pop("_about")
        self.assertEqual(team.load(os.path.join(SAMPLE, "sdlc-profile.yaml")), as_json)

    def test_yaml_without_pyyaml_says_what_to_do(self):
        with mock.patch.object(team, "_yaml", return_value=None):
            with self.assertRaises(team.ProfileError) as e:
                team.load(os.path.join(SAMPLE, "sdlc-profile.yaml"))
        self.assertIn("PyYAML", str(e.exception))
        self.assertIn("sdlc-profile.json", str(e.exception))

    def test_a_missing_setting_is_named(self):
        with self.assertRaises(team.ProfileError) as e:
            team.get({"jira": {"host": ""}}, "jira.host")
        self.assertIn("jira.host", str(e.exception))
        with self.assertRaises(team.ProfileError):
            team.queries({"jira": {"queries": {"sprint": "x"}}})

    def test_missing_file_points_at_the_example(self):
        with self.assertRaises(team.ProfileError) as e:
            team.load(os.path.join(tempfile.gettempdir(), "no-such-sdlc-profile.json"))
        self.assertIn("examples/acme", str(e.exception))

    def test_user_marker_becomes_the_workbench_placeholder(self):
        q = team.queries({"jira": {"queries": dict.fromkeys(team.QUERY_SCOPES, 'assignee = "{user}" AND x ~ "50%"')}})
        self.assertEqual(q["mine"] % "u1", 'assignee = "u1" AND x ~ "50%"')

    def test_pages_are_filled_and_escaped(self):
        self.assertEqual(team.fill_page(b"<b>{{BRAND}}</b>", {"BRAND": "A&B"}), b"<b>A&amp;B</b>")

    def test_workbench_code_holds_no_team_values(self):
        for name in CODE:
            with open(os.path.join(CONSOLE, name), encoding="utf-8") as fh:
                text = fh.read()
            for term in OUR_TERMS:
                self.assertNotIn(term, text, "%s still names %s; move it to sdlc-profile.json" % (name, term))

    def test_our_profile_keeps_todays_values(self):
        self.assertEqual(team.PROJECT, "ACME")
        self.assertEqual(team.WORKBENCH_TITLE, "Argus")
        self.assertEqual(team.FRAMEWORK, "sdlc/framework")

    def test_a_bad_settings_file_stops_the_workbench_in_one_line(self):
        with tempfile.TemporaryDirectory() as d:
            broken = os.path.join(d, "sdlc-profile.json")
            data = team.load(os.path.join(SAMPLE, "sdlc-profile.json"))
            del data["jira"]["project"]
            with open(broken, "w") as fh:
                json.dump(data, fh)
            for path, says in ((os.path.join(d, "missing.json"), "no team settings at"), (broken, "has no jira.project")):
                env = dict(os.environ, SDLC_PROFILE=path, HOME=d, SDLC_CONSOLE_HOME=os.path.join(d, "console"))
                r = subprocess.run([sys.executable, os.path.join(CONSOLE, "server.py"), "--port", "0"], env=env,
                                   capture_output=True, text=True, timeout=60)
                self.assertEqual(r.returncode, 1, r.stderr)
                self.assertIn(says, r.stderr)
                self.assertNotIn("Traceback", r.stderr)


# shared-copy sample: begin (install.py leaves these lines as Acme: they test the Acme example)
class AcmeWorkbenchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = run_on(os.path.join(SAMPLE, "sdlc-profile.json"))

    def test_acme_values_reach_the_workbench(self):
        o = self.out
        self.assertEqual(o["title"], "Acme Claims Argus")
        self.assertEqual(o["repo"], "ACME/claims-web")
        self.assertEqual(o["jira"], "https://jira.acme.example")
        self.assertEqual(o["token_env"], "ACME_JIRA_TOKEN")
        self.assertEqual(o["local_jira_env"], "ACME_JIRA_TOKEN")
        self.assertIn("ACME_JIRA_TOKEN", o["no_key_env"])
        self.assertEqual(o["jql"]["mine"] % "u1", 'project = ACME AND assignee = "u1" AND resolution = Unresolved ORDER BY updated DESC')
        self.assertIn("customfield_10001", o["fields"])
        self.assertTrue(o["ticket_ok"] and o["pc_ticket_ok"])
        self.assertRegex("https://git.acme.example/projects/ACME/repos/claims-web/pull-requests/7", o["pr"])
        self.assertEqual(o["read"], "python3 %s/console/server.py --cloud-stories mine,qa --user u1" % team.FRAMEWORK)
        self.assertIn("<title>Acme Claims Argus</title>", o["pages"]["index.html"])
        self.assertIn("· Acme-Claims-Web</option>", o["pages"]["index.html"])

    def test_none_of_our_values_leak_into_acme(self):
        # The framework folder is wherever the copy sits (here, our repo), so only profile values are checked.
        text = json.dumps(dict(self.out, read=""))
        for term in OUR_TERMS:
            self.assertNotIn(term, text)
        self.assertNotIn("{{", text)

    def test_yaml_twin_runs_the_same(self):
        self.assertEqual(run_on(os.path.join(SAMPLE, "sdlc-profile.yaml")), self.out)

# shared-copy sample: end


if __name__ == "__main__":
    unittest.main()
