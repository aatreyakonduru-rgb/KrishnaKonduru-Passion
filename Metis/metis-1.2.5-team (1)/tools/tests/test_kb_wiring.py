"""Checks that the shared prompts, the wiring file, the skills and the pipelines agree.

    python3 -m unittest tools.tests.test_kb_wiring -v

Stdlib only. The wiring file is templates/kb-prompt-wiring.yaml. Each entry is read with a small
line parser, because the file uses one flow mapping per line and no YAML library is assumed.
"""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KB_PROMPTS = os.path.join(ROOT, "kb-prompts")
SKILLS = os.path.join(ROOT, "skills")
WIRING = os.path.join(ROOT, "templates", "kb-prompt-wiring.yaml")

ENTRY = re.compile(r"^\s{2}([A-Z][A-Z0-9-]*[A-Z0-9]):\s*\{(.*)\}\s*(#.*)?$")
FIELD = re.compile(r"(\w+):\s*([^,}]+)")
SKILL_NAME = re.compile(r"^name:\s*(\S+)\s*$", re.MULTILINE)
STAGE_SKILL = re.compile(r"`([a-z0-9-]+)`")
RUNNER_FILES = {"RUN-APP": "KB_RUNNER_APP.md", "RUN-DB": "KB_RUNNER_DB.md", "RUN-ETL": "KB_RUNNER_ETL.md"}


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def parse_wiring():
    entries = {}
    for line in read(WIRING).splitlines():
        m = ENTRY.match(line)
        if not m:
            continue
        fields = {k: v.strip() for k, v in FIELD.findall(m.group(2))}
        entries[m.group(1)] = fields
    return entries


NON_PROMPTS = {"PROMPT_STANDARD.md"}


def prompt_files():
    """Prompt files: those with a `prompt_id:` frontmatter line. The standard is a rule document."""
    return sorted(
        f for f in os.listdir(KB_PROMPTS)
        if f.endswith(".md") and f not in NON_PROMPTS
        and re.search(r"^prompt_id:", read(os.path.join(KB_PROMPTS, f)), re.MULTILINE)
    )


def skill_names():
    names = {}
    for d in os.listdir(SKILLS):
        path = os.path.join(SKILLS, d, "SKILL.md")
        if os.path.isfile(path):
            m = SKILL_NAME.search(read(path))
            names[d] = m.group(1) if m else None
    return names


def pipeline_stage_skills(pipeline):
    """Skill names in backticks on the stage lines of a pipeline's SKILL.md (the lines that start with 'Stage')."""
    text = read(os.path.join(SKILLS, pipeline, "SKILL.md"))
    names = set()
    for line in text.splitlines():
        if re.match(r"^\s*(Stage\s*\d|Optional\b)", line) or re.match(r"^\s{5,}`[a-z0-9-]+`", line):
            names.update(STAGE_SKILL.findall(line))
    return names


class WiringTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.wiring = parse_wiring()

    def test_wiring_parses(self):
        self.assertGreater(len(self.wiring), 50, "wiring parsed too few entries")

    def test_every_prompt_file_is_listed_once(self):
        listed = [e["file"] for e in self.wiring.values() if "file" in e]
        self.assertEqual(len(listed), len(set(listed)), "a prompt file is listed twice")
        missing = [f for f in prompt_files() if f not in listed and f not in ("PROMPT_STANDARD.md", "placeholders.yaml")]
        self.assertEqual(missing, [], "prompt files with no wiring entry")

    def test_every_wired_file_exists(self):
        for pid, e in self.wiring.items():
            if "file" in e:
                self.assertTrue(os.path.isfile(os.path.join(KB_PROMPTS, e["file"])), f"{pid}: {e['file']} not found")

    def test_class_is_known(self):
        for pid, e in self.wiring.items():
            self.assertIn(e.get("class"), {"stage", "on_demand", "runner", "helper"}, f"{pid}: unknown class")

    def test_stage_entries_name_skill_and_pipeline(self):
        for pid, e in self.wiring.items():
            if e.get("class") == "stage":
                self.assertIn("skill", e, f"{pid}: stage has no skill")
                self.assertIn("pipeline", e, f"{pid}: stage has no pipeline")

    def test_every_named_skill_exists(self):
        skills = skill_names()
        for pid, e in self.wiring.items():
            if e.get("class") in ("stage", "on_demand") and e.get("skill") not in ("kb-build",):
                self.assertIn(e["skill"], skills, f"{pid}: skill {e['skill']} has no folder")
                self.assertEqual(skills[e["skill"]], e["skill"], f"{pid}: skill name does not match its folder")

    def test_every_skill_name_is_valid(self):
        for folder, name in skill_names().items():
            self.assertIsNotNone(name, f"{folder}/SKILL.md has no name")
            self.assertEqual(name, folder, f"{folder}: name must equal the folder name")
            self.assertRegex(name, r"^[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?$", f"{folder}: invalid skill name")

    def test_every_stage_is_in_its_pipeline(self):
        for pid, e in self.wiring.items():
            if e.get("class") != "stage" or "pipeline" not in e:
                continue
            if e["skill"] == e["pipeline"]:
                # kb-context-build runs its own prompts; it is its own pipeline and has no stage table.
                continue
            stages = pipeline_stage_skills(e["pipeline"])
            self.assertIn(e["skill"], stages, f"{pid}: {e['skill']} is not a stage of {e['pipeline']}")

    def test_entry_points_name_pipelines(self):
        # Every pipeline named as a stage's pipeline is a real skill folder.
        skills = skill_names()
        for pid, e in self.wiring.items():
            if e.get("class") == "stage":
                self.assertIn(e["pipeline"], skills, f"{pid}: pipeline {e['pipeline']} has no folder")

    def test_runner_files_exist(self):
        for rid, f in RUNNER_FILES.items():
            self.assertIn(rid, self.wiring)
            self.assertEqual(self.wiring[rid]["file"], f)
            self.assertTrue(os.path.isfile(os.path.join(KB_PROMPTS, f)))

    def test_no_two_prompts_write_the_same_output(self):
        # Shared outputs are declared in the wiring file's shared_outputs section. Any other
        # output path written by two prompts is a silent clash.
        out_re = re.compile(r'outputs:\s*\[\s*"([^"]+)"')
        shared = set(re.findall(r'-\s*path:\s*"([^"]+)"', read(WIRING)))
        writers = {}
        for f in prompt_files():
            m = out_re.search(read(os.path.join(KB_PROMPTS, f)))
            if not m:
                continue
            writers.setdefault(m.group(1), []).append(f)
        clashes = {o: fs for o, fs in writers.items() if len(fs) > 1 and o not in shared}
        self.assertEqual(clashes, {}, "outputs written by more than one prompt and not declared shared")


if __name__ == "__main__":
    unittest.main()
