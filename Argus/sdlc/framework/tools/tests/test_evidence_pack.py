import json
import os
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import evidence_pack  # noqa: E402

STORY = "REQ-T-1-STORY-1"


class EvidencePackTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        with open(os.path.join(self.dir, "approvals.yaml"), "w") as fh:
            yaml.safe_dump({"approvals": [
                {"gate_id": "SDLC_01_INTAKE_CLARIFICATION", "requirement_id": "REQ-T-1", "approver_name": "Resource 16",
                 "approver_role": "bsa", "decision": "approved", "timestamp": "2026-10-01T10:00:00Z"},
                {"gate_id": "SDLC_04_ROUTING_APPROVAL", "requirement_id": "REQ-T-1", "story_id": "STORY-2",
                 "approver_name": "Resource 3", "decision": "approved"},
                {"gate_id": "SDLC_01_INTAKE_CLARIFICATION", "requirement_id": "REQ-OTHER"}]}, fh)
        with open(os.path.join(self.dir, "checkmarx.json"), "w") as fh:
            json.dump({"tool": "checkmarx", "status": "pass", "findings": [{}], "blocking": []}, fh)
        with open(os.path.join(self.dir, STORY + "-verifier.yaml"), "w") as fh:
            yaml.safe_dump({"verdict": "pass", "rounds": [{"verdict": "fail"}, {"verdict": "pass"}]}, fh)

    def test_pack_keeps_only_this_story_and_lists_what_is_missing(self):
        pack = evidence_pack.build(self.dir, STORY)
        self.assertEqual([g["gate"] for g in pack["gates"]], ["SDLC_01_INTAKE_CLARIFICATION"])
        self.assertEqual(pack["verifier"], {"verdict": "pass", "rounds": 2, "rework": 1})
        self.assertEqual(pack["scans"][0]["findings"], 1)
        for m in ("SDLC_05_CODE_REVIEW sign-off (not signed yet)", "wiz.json", "PR link", STORY + "-claims.yaml"):
            self.assertIn(m, pack["missing"])

    def test_render_shows_status_from_pr_readiness(self):
        with open(os.path.join(self.dir, STORY + "-AI-VERIFICATION.md"), "w") as fh:
            fh.write("# x\n\n## Overall Status: PASS\n")
        text = evidence_pack.render(evidence_pack.build(self.dir, STORY, pr="https://example/pr/1"))
        self.assertIn("/pr-readiness status: PASS", text)
        self.assertIn("| SDLC_01_INTAKE_CLARIFICATION | Resource 16 | bsa | approved |", text)
        self.assertIn("PR: https://example/pr/1", text)


if __name__ == "__main__":
    unittest.main()
