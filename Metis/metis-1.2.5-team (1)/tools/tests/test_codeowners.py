import os
import shutil
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import codeowners  # noqa: E402
import kb_gate  # noqa: E402


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


class CodeownersTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.repo = os.path.join(self.tmp, "my-repo")
        self.kb = os.path.join(self.tmp, "kb")
        os.makedirs(self.repo, exist_ok=True)
        os.makedirs(self.kb, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_parse_codeowners_rules(self):
        content = """
        # Comments are ignored
        *                   @global-lead
        /docs/              @docs-team
        src/claims/*.py     @claims-team @cleo
        *.sql               @db-lead
        """
        rules = codeowners.parse_codeowners(content)
        self.assertEqual(len(rules), 4)

    def test_last_match_wins_and_glob_rules(self):
        content = """
        *                   @global-owner
        /docs/              @docs-team
        /docs/special.md    @specialist
        *.py                @python-dev
        src/billing/        @billing-team
        """
        rules = codeowners.parse_codeowners(content)
        self.assertEqual(codeowners.owners_for_path(rules, "docs/other.md"), ["@docs-team"])
        self.assertEqual(codeowners.owners_for_path(rules, "docs/special.md"), ["@specialist"])
        self.assertEqual(codeowners.owners_for_path(rules, "src/claims/calc.py"), ["@python-dev"])
        self.assertEqual(codeowners.owners_for_path(rules, "src/billing/invoice.py"), ["@billing-team"])
        self.assertEqual(codeowners.owners_for_path(rules, "random.txt"), ["@global-owner"])

    def test_find_codeowners_file(self):
        # GitHub location
        gh_path = os.path.join(self.repo, ".github", "CODEOWNERS")
        write(gh_path, "* @team-gh\n")
        self.assertEqual(codeowners.find_codeowners_file(self.repo), gh_path)
        self.assertEqual(codeowners.owners_for_path(self.repo, "main.go"), ["@team-gh"])

    def test_bitbucket_location(self):
        bb_path = os.path.join(self.repo, ".bitbucket", "CODEOWNERS")
        write(bb_path, "* @team-bb\n")
        self.assertEqual(codeowners.find_codeowners_file(self.repo), bb_path)
        self.assertEqual(codeowners.owners_for_path(self.repo, "main.go"), ["@team-bb"])

    def test_suggest_owner_from_gate_teams_fallback(self):
        prof = {
            "owners": {"kb_owner": "Ana Lead"},
            "gate": {"teams": [
                {"name": "Claims Team", "owns": ["claims/*"], "approvers": ["Cleo Claims"]},
            ]},
        }
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump(prof))
        write(os.path.join(self.kb, "claims", "page.md"), "# Claims\n")

        suggested = codeowners.suggest_owner_for_page(self.kb, "claims/page.md")
        self.assertEqual(suggested, "Claims Team")

    def test_suggest_owner_for_question(self):
        prof = {
            "owners": {"kb_owner": "Ana Lead"},
            "gate": {"teams": [
                {"name": "Billing Team", "owns": ["billing/*"], "approvers": ["Bo Billing"]},
            ]},
        }
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump(prof))
        q = {
            "id": "Q-001",
            "question": "What is billing cycle?",
            "blocks": ["billing/cycle.md"],
        }
        suggested = codeowners.suggest_owner_for_question(self.kb, q)
        self.assertEqual(suggested, "Billing Team")

    def test_suggest_owner_for_review_item(self):
        prof = {
            "owners": {"kb_owner": "Ana Lead"},
            "gate": {"teams": [
                {"name": "Claims Team", "owns": ["claims/*"], "approvers": ["Cleo Claims"]},
            ]},
        }
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump(prof))
        item = {"batch": "b1", "file": "claims/adjudication.md"}
        suggested = codeowners.suggest_owner_for_review_item(self.kb, item)
        self.assertEqual(suggested, "Claims Team")

    def test_cli_commands(self):
        cf = os.path.join(self.repo, "CODEOWNERS")
        write(cf, "* @default-lead\n")
        self.assertEqual(codeowners.main(["parse", self.repo]), 0)
        self.assertEqual(codeowners.main(["owners", self.repo, "src/app.py"]), 0)


if __name__ == "__main__":
    unittest.main()
