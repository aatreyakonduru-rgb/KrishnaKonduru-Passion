import json
import os
import shutil
import sys
import tempfile
import unittest

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import dash_jira  # noqa: E402
import gen_dashboard  # noqa: E402


def I(key, status, cat, who=None, sprint="S1", state="ACTIVE", pts=3, upd="2020-01-01T00:00:00.000+0000"):
    return {"key": key, "summary": "s " + key, "type": "Story", "status": status, "status_category": cat,
            "assignee": who, "priority": "Medium", "points": pts, "sprint": sprint, "sprint_state": state,
            "created": upd, "updated": upd, "resolved": None, "labels": []}


class Dashboard(unittest.TestCase):
    def setUp(self):
        self.kb = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.kb, ".metis"))
        yaml.safe_dump({"product": {"name": "T"}, "owners": {"roles": {"manager": "Ann Lee"}}},
                       open(os.path.join(self.kb, ".metis", "kb-profile.yaml"), "w"))
        self.ann = {"display": "Ann Lee", "email": "ann@x.com"}
        self.bob = {"display": "Bob Ray", "email": "bob@x.com"}
        self.jira = {"base_url": "https://j", "read_at": "t", "jql_open": "o", "jql_done": "d", "done_days": 14,
                     "issues": [I("A-1", "In Progress", "indeterminate", self.bob), I("A-2", "On Hold", "indeterminate", self.bob),
                                I("A-3", "To Do", "new", {"display": "Zed", "email": "z@y.com"})]}
        self.members = [{"name": "Ann Lee", "email": "ann@x.com"}, {"name": "Bob Ray", "email": "bob@x.com"}]

    def tearDown(self):
        shutil.rmtree(self.kb)

    def test_role_picks_manager_view(self):
        h = gen_dashboard.build(self.kb, "ann@x.com", self.jira, self.members, None)
        self.assertIn("manager view", h)
        self.assertIn("data-t='team'", h)
        self.assertIn("Jira assignees not on the team list", h)
        self.assertIn("https://j/browse/A-1", h)

    def test_unknown_person_gets_default_view_no_role_guessed(self):
        h = gen_dashboard.build(self.kb, "bob@x.com", self.jira, self.members, None)
        self.assertIn("developer view", h)
        self.assertNotIn("data-t='team'", h)
        self.assertIn("not named", gen_dashboard.build(self.kb, "ann@x.com", self.jira, self.members, None))

    def test_counts_no_judgement(self):
        h = gen_dashboard.build(self.kb, "ann@x.com", self.jira, self.members, None)
        self.assertIn("<b>3</b>open Jira issues", h)
        self.assertIn("<b>1</b>waiting", h)
        self.assertNotIn("overloaded", h.lower())

    def test_without_jira(self):
        h = gen_dashboard.build(self.kb, "ann@x.com", None, [], None, "manager")
        self.assertIn("No Jira snapshot was given", h)

    def test_sprint_field_forms(self):
        self.assertEqual(dash_jira.sprint_of(["x@1[id=1,state=CLOSED,name=S0]", "x@2[id=2,state=ACTIVE,name=S1,goal=]"])["name"], "S1")
        self.assertEqual(dash_jira.sprint_of([{"name": "C1", "state": "active"}])["state"], "ACTIVE")
        self.assertIsNone(dash_jira.sprint_of(None)["name"])


if __name__ == "__main__":
    unittest.main()
