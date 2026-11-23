"""telemetry.by_team: use counted by owning team and by recorder, with file names only."""
import json
import os
import shutil
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import kb_gate  # noqa: E402
import telemetry  # noqa: E402

PROFILE = {"owners": {"kb_owner": "Ana Lead"},
           "gate": {"teams": [{"name": "Data", "owns": ["data/*"], "approvers": ["Dee Data"]},
                              {"name": "App", "owns": ["app/*"], "approvers": ["Al App"]}]}}


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


class ByTeam(unittest.TestCase):
    def setUp(self):
        self.kb = tempfile.mkdtemp()
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump(PROFILE))

    def tearDown(self):
        shutil.rmtree(self.kb, ignore_errors=True)

    def test_counts_by_owner_team_and_reader(self):
        telemetry.record(self.kb, "pack", ["data/a.md", "app/b.md"], by="Dee Data")
        telemetry.record(self.kb, "answer", ["data/a.md", "data/c.md", "misc/x.md"], by="Pat Lee")
        telemetry.record(self.kb, "answer", ["app/b.md"])
        rep = telemetry.report(self.kb)
        self.assertEqual(rep["by_owner_team"]["Data"], {"packs": 1, "answers": 2, "files": 2})
        self.assertEqual(rep["by_owner_team"]["App"], {"packs": 1, "answers": 1, "files": 1})
        self.assertEqual(rep["by_owner_team"][kb_gate.UNASSIGNED], {"packs": 0, "answers": 1, "files": 1})
        self.assertEqual(rep["by_reader"]["Dee Data"], {"packs": 1, "answers": 0, "team": "Data"})
        self.assertEqual(rep["by_reader"]["Pat Lee"]["team"], "(not in a team)")
        self.assertEqual(rep["by_reader"]["(not recorded)"]["answers"], 1)

    def test_no_teams_everything_unassigned(self):
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump({"owners": {"kb_owner": "Ana Lead"}}))
        telemetry.record(self.kb, "pack", ["data/a.md"])
        self.assertEqual(list(telemetry.report(self.kb)["by_owner_team"]), [kb_gate.UNASSIGNED])

    def test_no_events_is_empty_and_stored_events_have_no_text_fields(self):
        rep = telemetry.report(self.kb)
        self.assertEqual((rep["by_owner_team"], rep["by_reader"]), ({}, {}))
        e = telemetry.record(self.kb, "answer", ["data/a.md"], by="Pat Lee")
        self.assertFalse({"question", "answer", "text"} & set(e))
        month = [f for f in os.listdir(os.path.join(self.kb, ".metis", "usage")) if f.endswith(".jsonl")][0]
        with open(os.path.join(self.kb, ".metis", "usage", month), encoding="utf-8") as fh:
            self.assertFalse({"question", "answer", "text"} & set(json.loads(fh.readline())))


if __name__ == "__main__":
    unittest.main()
