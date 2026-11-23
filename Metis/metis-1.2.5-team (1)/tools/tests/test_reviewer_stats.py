import os
import shutil
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import feedback  # noqa: E402
import kb_gate  # noqa: E402
import reviewer_stats  # noqa: E402


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


class ReviewerStatsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.kb = os.path.join(self.tmp, "kb")
        prof = {
            "owners": {"kb_owner": "Ana Lead", "app_owner": "Raj Dev"},
            "gate": {"teams": [
                {"name": "Claims Team", "owns": ["claims/*"], "approvers": ["Cleo Claims"]},
            ]},
        }
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump(prof))
        write(os.path.join(self.kb, "_EVIDENCE", "files", "f.txt"), "sample\n")
        write(os.path.join(self.kb, "claims", "p1.md"), "# P1\n\n- Fact [E: file:f.txt]\n")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_parse_log_and_reviewer_stats(self):
        kb_gate.log(self.kb, "certify", "Ana Lead", "kb owner", "b1", "claims/p1.md")
        kb_gate.log(self.kb, "certify", "Ana Lead", "kb owner", "b1", "claims/p2.md")
        kb_gate.log(self.kb, "reject", "Raj Dev", "app owner", "b2", "3 files", "Contains bad syntax")
        kb_gate.log(self.kb, "review", "Cleo Claims", "Claims approver", "page-review", "claims/p1.md", "Approved")

        stats = reviewer_stats.reviewer_stats(self.kb)
        self.assertIn("ana lead", stats)
        self.assertIn("raj dev", stats)
        self.assertIn("cleo claims", stats)

        ana = stats["ana lead"]
        self.assertEqual(ana["certified_count"], 2)
        self.assertEqual(ana["rejected_count"], 0)
        self.assertEqual(set(ana["certified_files"]), {"claims/p1.md", "claims/p2.md"})

        raj = stats["raj dev"]
        self.assertEqual(raj["certified_count"], 0)
        self.assertEqual(raj["rejected_count"], 1)

    def test_later_disliked_pages_join(self):
        kb_gate.log(self.kb, "certify", "Ana Lead", "kb owner", "b1", "claims/p1.md")
        # Create an answer file citing kb:claims/p1.md
        ans_path = os.path.join(self.tmp, "ans1.md")
        write(ans_path, "# Answer\n\n- Claim fact [E: kb:claims/p1.md \"Fact\"]\n")

        # Record dislike on this answer
        feedback.record(self.kb, ans_path, "What is p1?", "User1", "down",
                        why="Wrong rule", correct="Rule 12")

        stats = reviewer_stats.reviewer_stats(self.kb, "Ana Lead")
        self.assertEqual(stats["certified_count"], 1)
        self.assertEqual(stats["later_disliked_count"], 1)
        self.assertEqual(stats["later_disliked_pages"][0]["file"], "claims/p1.md")

    def test_suggest_routing(self):
        kb_gate.log(self.kb, "certify", "Cleo Claims", "Claims approver", "b1", "claims/p1.md")
        kb_gate.log(self.kb, "certify", "Ana Lead", "kb owner", "b2", "context/x.md")

        routes = reviewer_stats.suggest_routing(self.kb, "Claims Team")
        self.assertTrue(len(routes) >= 2)
        # Cleo has 1 area certification in claims, so should rank first
        self.assertEqual(routes[0]["name"], "Cleo Claims")
        self.assertEqual(routes[0]["area_certifications"], 1)

    def test_cli(self):
        kb_gate.log(self.kb, "certify", "Ana Lead", "kb owner", "b1", "claims/p1.md")
        self.assertEqual(reviewer_stats.main(["stats", self.kb]), 0)
        self.assertEqual(reviewer_stats.main(["stats", self.kb, "--reviewer", "Ana Lead"]), 0)
        self.assertEqual(reviewer_stats.main(["route", self.kb, "Claims Team"]), 0)


if __name__ == "__main__":
    unittest.main()
