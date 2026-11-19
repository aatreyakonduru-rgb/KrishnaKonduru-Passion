import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gate_config  # noqa: E402

GATES = {"gates": [
    {"id": "G1", "name": "One", "timeout_hours": 24, "blocks_if_failed": "Code generation",
     "approvers": [{"role": "tech_lead", "names": ["Resource 16"], "backups": []}]},
    {"id": "G2", "name": "Two", "approvers": [{"role": "qa", "names": ["Resource 6"]}]},
]}
PEOPLE = {"people": [{"name": "Resource 16", "jira_user": "AB1"}, {"name": "Resource 6", "jira_user": "AM2"}]}
TEXT = """gates:
  - id: G1
    name: One
    timeout_hours: 24
    approvers:
      - role: tech_lead
        names: [Resource 16]
        backups: []

  - id: G2
    name: Two
    approvers:
      - role: qa
        names: [Resource 6]
"""


class GateConfigTest(unittest.TestCase):
    def test_grid_marks_named_and_backup(self):
        people, rows = gate_config.grid(GATES, PEOPLE)
        self.assertEqual(rows[0]["cells"], {"AB1": "named", "AM2": "none"})
        self.assertEqual(rows[0]["blocks"], "Code generation")
        self.assertEqual(rows[1]["cells"]["AM2"], "named")

    def test_parse_block(self):
        text = "x\n%s\n- gate: G1 | AM2: backup\nEND\n" % gate_config.BLOCK
        self.assertEqual(gate_config.parse_block(text), [("G1", "AM2", "backup")])
        with self.assertRaises(ValueError):
            gate_config.parse_block("%s\n- gate: G1 | AM2: boss\nEND" % gate_config.BLOCK)

    def test_apply_adds_backup_and_moves_named(self):
        gates, said = gate_config.apply([("G1", "AM2", "backup"), ("G2", "AB1", "named")], GATES, PEOPLE)
        self.assertEqual(gates["gates"][0]["approvers"][0]["backups"], ["Resource 6"])
        self.assertEqual(gates["gates"][1]["approvers"][0]["names"], ["Resource 6", "Resource 16"])
        self.assertEqual(len(said), 2)
        self.assertEqual(GATES["gates"][0]["approvers"][0]["backups"], [])

    def test_apply_leaves_a_person_already_in_that_place_where_they_are(self):
        gates = {"gates": [{"id": "G1", "approvers": [{"role": "tech_lead", "names": ["Resource 16"],
                                                        "backups": ["Resource 6", "Other One"]}]}]}
        out, said = gate_config.apply([("G1", "AM2", "backup"), ("G1", "AB1", "named")], gates, PEOPLE)
        self.assertEqual(out, gates)
        self.assertTrue(all("no change" in line for line in said))

    def test_apply_refuses_gate_without_named_approver_or_unknown_person(self):
        with self.assertRaises(ValueError):
            gate_config.apply([("G1", "AB1", "none")], GATES, PEOPLE)
        with self.assertRaises(ValueError):
            gate_config.apply([("G1", "ZZ9", "named")], GATES, PEOPLE)
        with self.assertRaises(ValueError):
            gate_config.apply([("G9", "AB1", "named")], GATES, PEOPLE)

    def test_write_changes_only_the_lists(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        path = os.path.join(d, "g.yaml")
        with open(path, "w") as fh:
            fh.write(TEXT)
        gates, _ = gate_config.apply([("G1", "AM2", "backup"), ("G2", "AB1", "backup")], GATES, PEOPLE)
        gate_config.write(path, gates)
        out = open(path).read()
        self.assertIn("        backups: [Resource 6]\n\n  - id: G2", out)
        self.assertIn("        names: [Resource 6]\n        backups: [Resource 16]\n", out)
        self.assertEqual(out.count("\n"), TEXT.count("\n") + 1)

    def test_names_that_differ_only_by_number_are_different_people(self):
        self.assertNotEqual(gate_config.norm("Resource 6"), gate_config.norm("Resource 17"))
        self.assertEqual(gate_config.norm("Resource 16"), gate_config.norm("Resource 16"))


if __name__ == "__main__":
    unittest.main()
