import json
import os
import shutil
import sys
import tempfile
import unittest

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import dash_usage  # noqa: E402
import gen_dashboard  # noqa: E402
import usage_view  # noqa: E402

SESS = """Found 3 sessions:
- s1 | Fix login | a | status=exit | created=1000 | updated=1001 | user_id=u-ann | origin=webapp | category=bug_fixing | subcategory=x | pull_requests=https://b/pr/1[merged] | acus_consumed=10.5
- s2 | Add page | status=suspended | created=1100 | updated=1101 | user_id=u-bob | origin=slack | category=feature_development | pull_requests=https://b/pr/2[open] | acus_consumed=4
- s3 | Other team | status=exit | created=1200 | updated=1201 | user_id=u-zed | origin=webapp | category=bug_fixing | acus_consumed=7
- s4 | Too old | status=exit | created=10 | updated=11 | user_id=u-ann | origin=webapp | category=bug_fixing | acus_consumed=99
"""
INS = """- s1 | Fix login | status=exit | created=2026-01-01 00:00:00 UTC
  acus_consumed=10.5 | num_user_messages=4 | num_devin_messages=9 | session_size=s | analysis_status=completed
  classification: bug_fixing | confidence=0.8 | languages=Python | tools=Jira
  analysis: (classification only)
- s2 | Add page | status=suspended | created=2026-01-01 00:00:00 UTC
  acus_consumed=4 | num_user_messages=2 | num_devin_messages=3 | session_size=xs | analysis_status=completed
"""
MEM = """- u-ann | Ann@x.com | Ann Lee
- u-bob | bob@x.com | Bob Ray
- u-zed | zed@y.com | Zed
"""


def issue(key, board, a, r):
    return {"key": key, "summary": "s", "type": "Story", "status": "To Do", "status_category": "new", "boards": [board],
            "assignee": a, "reporter": r, "points": None, "sprint": None, "sprint_state": None, "updated": None}


def person(n, e):
    return {"display": n, "email": e, "name": n}


class Usage(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        raw = os.path.join(self.d, "raw")
        os.makedirs(raw)
        for n, t in (("sessions-001.txt", SESS), ("insights-001.txt", INS), ("members-direct-001.txt", MEM)):
            open(os.path.join(raw, n), "w").write(t)
        self.u = dash_usage.parse(raw, 500, 2000, "https://devin/sessions")
        self.kb = os.path.join(self.d, "kb")
        os.makedirs(os.path.join(self.kb, ".metis"))
        yaml.safe_dump({"product": {"name": "T"}, "owners": {"roles": {"manager": "Ann Lee"}}},
                       open(os.path.join(self.kb, ".metis", "kb-profile.yaml"), "w"))
        self.dash = yaml.safe_load(open(os.path.join(HERE, "..", "..", "templates", "dashboard.yaml")))
        self.save()
        self.jira = {"base_url": "https://j", "read_at": "t", "jql_open": "o", "jql_done": "d", "boards": ["Iris", "Nyx"],
                     "service_account": {"name": "svc", "email": "svc@x.com"},
                     "issues": [issue("P-1", "Iris", person("Ann Lee", "ann@x.com"), person("svc", "svc@x.com")),
                                issue("P-2", "Nyx", person("Bob Ray", "bob@x.com"), person("Cat Kim", "cat@x.com"))]}

    def save(self):
        yaml.safe_dump(self.dash, open(os.path.join(self.kb, ".metis", "dashboard.yaml"), "w"))

    def tearDown(self):
        shutil.rmtree(self.d)

    def page(self, user="ann@x.com", lens="manager", findings=None, jira="x"):
        return gen_dashboard.build(self.kb, user, self.jira if jira == "x" else jira, [], None, lens, self.u, findings)

    def test_parse_as_read(self):
        self.assertEqual([s["session_id"] for s in self.u["sessions"]], ["s1", "s2", "s3"])
        s1 = self.u["sessions"][0]
        self.assertEqual((s1["title"], s1["acus"], s1["prs"][0]["state"]), ("Fix login | a", 10.5, "merged"))
        self.assertEqual(self.u["insights"]["s1"]["num_user_messages"], 4)
        self.assertEqual(self.u["insights"]["s1"]["tools"], ["Jira"])
        self.assertEqual(self.u["members"][0]["email"], "ann@x.com")

    def test_team_from_jira_stories_only(self):
        how, people = usage_view.team(self.dash["usage"], self.dash, self.jira, self.u)
        self.assertEqual(how, "jira")
        self.assertEqual(sorted(p["email"] for p in people), ["ann@x.com", "bob@x.com", "cat@x.com"])
        h = self.page()
        self.assertIn("Teams Devin Usage", h)
        self.assertIn("1 sessions (7.0 ACUs) by Devin users who are not on the team list are left out", h)
        self.assertIn("<b>14.5</b>ACUs", h)
        self.assertIn("no Devin user found", h)
        self.assertNotIn("svc@x.com", h)

    def test_boards_grouped(self):
        h = self.page()
        self.assertIn("<h3>By board</h3>", h)
        self.assertIn("<td>Iris</td><td>1</td><td>1</td><td>1</td><td>10.5</td>", h)

    def test_no_dollars_without_price(self):
        h = self.page()
        self.assertNotIn("$", h.split("<section id='usage'")[1].split("</section>")[0])
        self.assertIn("No price per ACU is set", h)

    def test_dollars_with_price(self):
        self.dash["usage"]["usd_per_acu"] = 2
        self.dash["usage"]["usd_per_acu_source"] = "Finance"
        self.save()
        h = self.page()
        self.assertIn("<b>$29.00</b>cost", h)
        self.assertIn("given by Finance", h)

    def test_developer_sees_own_row_only(self):
        h = self.page("bob@x.com", "developer")
        sec = h.split("<section id='usage'")[1].split("</section>")[0]
        self.assertIn("Bob Ray", sec)
        self.assertNotIn("Ann Lee", sec)
        self.assertIn("your own row only", sec)
        self.assertNotIn("Who could show whom", sec)

    def test_needs_jira_and_boards(self):
        self.assertIn("No Jira snapshot was read", self.page(jira=None))
        self.jira["boards"] = []
        self.assertIn("No Jira boards are listed", self.page())
        self.assertIn("Not read yet", gen_dashboard.build(self.kb, "ann@x.com", self.jira, [], None, "manager", None, None))

    def test_findings_checked(self):
        f = {"prompt_patterns": [{"pattern": "one-line asks", "sessions": ["s1", "s2"], "before": "fix it", "better": "fix X in file Y"},
                                 {"pattern": "single", "sessions": ["s1"]}],
             "gaps": [{"gap": "made up", "sessions": ["s1", "nope"]}],
             "wins": [{"user_id": "u-ann", "what": "clear steps", "sessions": ["s2"]}],
             "people": {"u-ann": {"sessions": ["s1"], "gaps": ["tests"], "tips": ["name the file"], "prompt_before": "fix it",
                                  "prompt_after": "fix login in auth.py"},
                        "u-bob": {"sessions": ["s1"]}}}
        probs = dash_usage.check(self.u, f)
        self.assertTrue(any(p.startswith("prompt_patterns[1]") for p in probs))
        self.assertTrue(any("gaps[0]: sessions not in usage.json: nope" in p for p in probs))
        self.assertTrue(any(p.startswith("wins[0]") for p in probs))
        self.assertTrue(any("people[u-bob]: session s1 is not theirs" in p for p in probs))
        h = self.page(findings=f)
        self.assertIn("one-line asks", h)
        self.assertIn("https://devin/sessions/s1", h)
        self.assertIn("fix login in auth.py", h)
        self.assertIn("Findings left out", h)
        self.assertNotIn("made up", h.split("Findings left out")[0])

    def test_no_findings_says_so(self):
        self.assertIn("No findings file was given", self.page())

    def test_cli_check(self):
        up, fp = os.path.join(self.d, "u.json"), os.path.join(self.d, "f.json")
        json.dump(self.u, open(up, "w"))
        json.dump({"gaps": [{"gap": "g", "sessions": ["s1", "s2"]}]}, open(fp, "w"))
        self.assertEqual(dash_usage.main(["check", up, fp]), 0)


if __name__ == "__main__":
    unittest.main()
