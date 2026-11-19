import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import role_config  # noqa: E402

ROUTING = {"roles": {"solution_lead": {"label": "Solution lead", "gate_roles": ["tech_lead"]},
                     "developer": {"label": "Developer", "gate_roles": ["developer"]},
                     "reviewer": {"label": "Reviewer", "gate_roles": ["tech_lead", "developer"]}}}
PEOPLE = {"people": [{"jira_user": "resource6", "name": "Resource 6", "primary_role": "solution_lead",
                      "secondary_roles": ["developer"]},
                     {"jira_user": "resource3", "name": "Resource 3", "primary_role": "solution_lead",
                      "secondary_roles": []}]}


class RoleConfigTests(unittest.TestCase):
    def test_grid_marks_main_role_hats_and_gates(self):
        cols, rows = role_config.grid(PEOPLE, ROUTING)
        self.assertEqual([c for c, _ in cols], ["solution_lead", "developer", "reviewer"])
        self.assertEqual(rows[0]["cells"], {"solution_lead": "primary", "developer": "secondary", "reviewer": "none"})
        self.assertEqual(rows[0]["gates"], ["developer", "tech_lead"])

    def test_apply_moves_the_main_role_and_keeps_the_old_one_as_a_hat(self):
        block = "SDLC-DASHBOARD-ROLE-CONFIG v1\n- person: resource6 | reviewer: primary\nEND\n"
        new, said = role_config.apply(role_config.parse_block(block), PEOPLE, ROUTING, editor="resource3")
        p = new["people"][0]
        self.assertEqual(p["primary_role"], "reviewer")
        self.assertEqual(p["secondary_roles"], ["solution_lead", "developer"])
        self.assertEqual(len(said), 1)

    def test_apply_refuses_own_row_clearing_the_main_role_and_unknown_people(self):
        with self.assertRaises(ValueError):
            role_config.apply([("resource3", "developer", "secondary")], PEOPLE, ROUTING, editor="resource3")
        with self.assertRaises(ValueError):
            role_config.apply([("resource6", "solution_lead", "none")], PEOPLE, ROUTING)
        with self.assertRaises(ValueError):
            role_config.apply([("user3", "developer", "secondary")], PEOPLE, ROUTING)

    def test_write_changes_only_the_role_lines(self):
        text = ("people:\n- jira_user: resource6\n  name: Resource 6\n  primary_role: solution_lead\n  secondary_roles:\n"
                "  - developer\n  role_hints: {}\n- jira_user: resource3\n  name: Resource 3\n"
                "  primary_role: solution_lead\n  secondary_roles: []\n  delegate_to: null\n")
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as fh:
            fh.write(text)
        new, _ = role_config.apply([("resource3", "reviewer", "secondary")], PEOPLE, ROUTING)
        role_config.write(fh.name, new)
        out = open(fh.name).read()
        os.unlink(fh.name)
        self.assertIn("  primary_role: solution_lead\n  secondary_roles:\n  - developer\n  role_hints: {}", out)
        self.assertIn("  secondary_roles:\n  - reviewer\n  delegate_to: null", out)


if __name__ == "__main__":
    unittest.main()
