"""The KB skills are thin wrappers over sdlc/kb/kb-prompts/ and keep their gates."""
import os
import re
import unittest
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[4]
SKILLS = REPO / ".devin" / "skills"
PROMPTS = REPO / "sdlc" / "kb" / "kb-prompts"
KB = REPO / "docs" / "knowledge-base"
REF = re.compile(r"sdlc/kb/kb-prompts/([A-Za-z0-9_.\-]+\.md)")

WRAPPERS = ["db-discovery", "db-brd", "db-trd", "db-diagrams", "db-supporting", "db-security",
            "db-validation", "db-change-analysis", "app-knowledge-refresh", "app-discovery",
            "app-brd", "app-frd", "app-trd", "app-user-manual", "app-process-docs",
            "app-diagrams", "app-validation-log", "app-security-review", "app-gap-fill",
            "app-ui-spec", "app-module-io", "app-integration"]
GATED = ["db-discovery", "db-brd", "db-trd", "app-knowledge-refresh", "app-brd", "app-frd",
         "app-security-review", "app-run-pipeline", "kb-compare"]


def skill(name):
    return (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")


def frontmatter(text):
    return yaml.safe_load(text.split("---", 2)[1])


class WrapperTest(unittest.TestCase):
    def test_wrappers_load_existing_shared_prompts(self):
        for name in WRAPPERS:
            text = skill(name)
            refs = REF.findall(text)
            self.assertTrue(refs, "%s names no shared prompt" % name)
            for ref in refs:
                self.assertTrue((PROMPTS / ref).is_file(), "%s: missing %s" % (name, ref))
            self.assertIn("prompts.py render", text, name)
            self.assertIn("--stage", text, name)

    def test_no_skill_runs_the_old_prompt_copies(self):
        old = re.compile(r"(PROMPTS|DB-DOCS/Prompts)/[A-Za-z0-9_]*PROMPT[A-Za-z0-9_.]*\.md")
        for path in SKILLS.glob("*/SKILL.md"):
            self.assertIsNone(old.search(path.read_text(encoding="utf-8")), path.parent.name)
        self.assertFalse((KB / "DB-DOCS" / "Prompts").exists())

    def test_gates_are_kept(self):
        for name in GATED:
            text = skill(name)
            self.assertIn("⛔", text, name)
            self.assertIn(".devin/rules/gate-presentation.md", text, name)
            self.assertIn("on anyone's behalf", text, name)

    def test_rebuild_defers_gates_only_to_the_comparison(self):
        for name in GATED:
            if name == "kb-compare":
                continue
            text = skill(name)
            self.assertIn("deferred to /kb-compare review", text, name)
            self.assertIn("--rebuild", frontmatter(text).get("argument-hint", ""), name)

    def test_frontmatter(self):
        for name in WRAPPERS + ["kb-build", "kb-compare", "app-run-pipeline"]:
            meta = frontmatter(skill(name))
            self.assertEqual(meta["name"], name)
            self.assertIn("user", meta["triggers"])
            self.assertIn("model", meta["triggers"])

    @unittest.skip('checks the knowledge base or application folders of the team that built the copy')
    def test_output_name_map_points_at_live_files(self):
        mapping = yaml.safe_load((REPO / ".devin" / "rules" / "kb-output-names.yaml").read_text())
        for staged, live in mapping.items():
            if isinstance(live, list):
                self.assertTrue((KB / live[0]).is_file(), live[0])
                for dup in live[1:]:
                    self.assertFalse((KB / dup).exists(), "duplicate not merged yet: %s" % dup)
            else:
                self.assertTrue((KB / live).is_file(), live)
                self.assertNotEqual(staged, live)


if __name__ == "__main__":
    unittest.main()
