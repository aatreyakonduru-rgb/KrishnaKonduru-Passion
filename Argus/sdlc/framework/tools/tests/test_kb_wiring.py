"""Every shared KB prompt is wired to exactly one skill, script or pipeline, with no loops."""
import re
import subprocess
import sys
import unittest
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[4]
SKILLS = REPO / ".devin" / "skills"
PROMPTS = REPO / "sdlc" / "kb" / "kb-prompts"
KB = REPO / "docs" / "knowledge-base"
WIRING = yaml.safe_load((REPO / ".devin" / "rules" / "kb-prompt-wiring.yaml").read_text())
ENVS = yaml.safe_load((REPO / ".devin" / "rules" / "snowflake-environments.yaml").read_text())["environments"]
ARCHIVE = KB / "Archive" / "PROMPTS" / "2026-09-30-superseded"

RUN_REF = re.compile(r"prompts\.py (?:render|outputs) ([A-Za-z0-9_.\-]+\.md)")
DIST_REF = re.compile(r"sdlc/kb/kb-prompts/([A-Za-z0-9_.\-]+\.md)")
# An executable call: a verb, then a slash command, on one line; or a stage line in a pipeline map.
CALL = re.compile(r"(?i)\b(runs?|calls?|invokes?|then|delegates? to|hands? off to)\b[^.\n]{0,40}?`?/([a-z0-9][a-z0-9-]+)")
STAGE = re.compile(r"^\s*(?:Stage|Optional|Step)\b[^\n]*?──\s*/([a-z0-9-]+)", re.M)
NOT_A_CALL = re.compile(r"(?i)\b(never|don't|doesn't|do not|not|next step|suggest|redirect|tell the user|"
                        r"ask the user|instead|if you want|user can|parallel|say \")")


def skills():
    return {p.parent.name: p.read_text(encoding="utf-8") for p in SKILLS.glob("*/SKILL.md")}


def frontmatter(path):
    text = path.read_text(encoding="utf-8")
    return yaml.safe_load(text.split("---", 2)[1]) if text.startswith("---") else {}


def shared_prompts():
    out = {}
    for path in PROMPTS.glob("*.md"):
        meta = frontmatter(path)
        if meta.get("prompt_id"):
            out[meta["prompt_id"]] = (path.name, meta)
    return out


def call_graph(texts):
    edges = {}
    for name, text in texts.items():
        body = text.split("---", 2)[-1]
        targets = set(STAGE.findall(body))
        for line in body.splitlines():
            if not NOT_A_CALL.search(line):
                targets.update(m.group(2) for m in CALL.finditer(line))
        edges[name] = {t for t in targets if t in texts and t != name}
    return edges


def find_cycle(edges):
    state = {}

    def visit(node, path):
        state[node] = 1
        for nxt in sorted(edges.get(node, ())):
            if state.get(nxt) == 1:
                return path[path.index(nxt):] + [nxt]
            if nxt not in state:
                found = visit(nxt, path + [nxt])
                if found:
                    return found
        state[node] = 2
        return None

    for node in sorted(edges):
        if node not in state:
            found = visit(node, [node])
            if found:
                return found
    return None


class WiringTest(unittest.TestCase):
    def setUp(self):
        self.skills = skills()
        self.prompts = shared_prompts()
        self.wiring = WIRING["prompts"]

    def test_every_prompt_is_wired_once(self):
        self.assertEqual(set(self.prompts), set(self.wiring))
        for pid, entry in self.wiring.items():
            self.assertEqual(entry["file"], self.prompts[pid][0], pid)

    def test_each_class_has_a_real_caller(self):
        for pid, e in self.wiring.items():
            cls, f = e["class"], e["file"]
            if cls in ("stage", "on_demand", "helper"):
                text = self.skills.get(e["skill"])
                self.assertIsNotNone(text, "%s: no skill %s" % (pid, e["skill"]))
                self.assertIn(f, text, "%s: %s doesn't name %s" % (pid, e["skill"], f))
                self.assertIn("prompts.py render", text, pid)
                if e.get("pipeline") and e["pipeline"] != e["skill"]:
                    self.assertIn("/" + e["skill"], self.skills[e["pipeline"]],
                                  "%s: %s doesn't list /%s" % (pid, e["pipeline"], e["skill"]))
                if cls == "stage":
                    self.assertTrue(e.get("pipeline"), pid)
            elif cls == "generator":
                self.assertTrue((REPO / e["generator"]).is_file(), pid)
                self.assertIn(f, self.skills[e["checked_by"]], pid)
            elif cls == "runner":
                self.assertIn(f, self.skills[e["followed_by"]], pid)
            else:
                self.fail("%s: unknown class %s" % (pid, cls))

    def test_no_skill_writes_a_script_built_file_from_its_prompt(self):
        generated = {e["file"] for e in self.wiring.values() if e["class"] == "generator"}
        for name, text in self.skills.items():
            for ref in RUN_REF.findall(text):
                self.assertNotIn(ref, generated, "%s renders the script-built %s" % (name, ref))

    def test_no_dangling_prompt_references(self):
        roots = list(SKILLS.glob("*/SKILL.md")) + list((REPO / ".devin" / "rules").glob("*"))
        for path in roots:
            text = path.read_text(encoding="utf-8")
            for ref in set(RUN_REF.findall(text)) | set(DIST_REF.findall(text)):
                self.assertTrue((PROMPTS / ref).is_file(), "%s: missing %s" % (path, ref))

    def test_each_output_has_one_writer_or_a_merge_rule(self):
        shared = {s["path"]: set(s["writers"]) for s in WIRING.get("shared_outputs", [])}
        writers = {}
        for pid, (_, meta) in self.prompts.items():
            for out in meta.get("outputs") or []:
                writers.setdefault(out, set()).add(pid)
        for out, who in writers.items():
            if len(who) > 1:
                self.assertEqual(shared.get(out), who, "%s is written by %s" % (out, sorted(who)))

    def test_entry_points_and_cascade(self):
        for entry, called in WIRING["entry_points"].items():
            for name in called:
                self.assertIn("/" + name, self.skills[entry], "%s doesn't call /%s" % (entry, name))
        for change, ids in WIRING["refresh_cascade"].items():
            for pid in ids:
                self.assertIn(pid, self.prompts, change)

    def test_no_call_cycles(self):
        edges = call_graph(self.skills)
        self.assertIsNone(find_cycle(edges))
        self.assertIn("app-runtime-sync", edges["app-knowledge-sync"])
        self.assertNotIn("app-knowledge-sync", edges["app-runtime-sync"])

    def test_cycle_detector_finds_a_loop(self):
        self.assertEqual(find_cycle({"a": {"b"}, "b": {"a"}}), ["a", "b", "a"])
        edges = call_graph({"a": "---\n---\nThen run `/b`.", "b": "---\n---\nCan run in parallel with `/a`."})
        self.assertIsNone(find_cycle(edges))

    @unittest.skip('checks the knowledge base or application folders of the team that built the copy')
    def test_active_files_use_no_retired_prompt_paths(self):
        retired = re.compile(r"Prompts/Acme Claims-API-FE|DB-DOCS/Prompts|Knowledgebase/PROMPTS/[A-Za-z0-9_\-/ ]+\.md")
        for path in list(SKILLS.glob("*/SKILL.md")) + [REPO / "AGENTS.md"]:
            self.assertIsNone(retired.search(path.read_text(encoding="utf-8")), path)
        live = [p for p in (KB / "PROMPTS").rglob("*") if p.is_file() and p.name != "README.md"]
        self.assertEqual([p.name for p in live], [])

    @unittest.skip('checks the knowledge base or application folders of the team that built the copy')
    def test_every_archived_prompt_is_in_the_report(self):
        report = (ARCHIVE / "README.md").read_text(encoding="utf-8")
        for path in ARCHIVE.rglob("*.md"):
            if path.name != "README.md":
                self.assertIn(str(path.relative_to(ARCHIVE)), report, path.name)
        self.assertNotIn("| ? |", report)

    @unittest.skip('checks the knowledge base or application folders of the team that built the copy')
    def test_kb_paths_in_the_framework_exist(self):
        ref = re.compile(r"docs/knowledge-base/[^\s`\"'|)]+")
        output_only = re.compile(r"\{(DATE|REQ_ID|req_id|OWNER)\}|YYYY|_REGEN|Archive/|<|,|\.\.\.")
        files = [p for d in (".devin/skills", ".devin/agents", ".devin/rules") for p in (REPO / d).rglob("*")
                 if p.suffix in (".md", ".yaml")]
        files += list((REPO / "sdlc/framework/playbooks").glob("*.md"))
        files += list((REPO / "sdlc/framework/workflows").glob("*.md"))
        missing = []
        for path in files:
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("Outputs\\Acme Claims", text, path)
            for m in ref.finditer(text):
                target = re.sub(r"(:\d+(-\d+)?|#.*)$", "", m.group(0).rstrip(".,:;"))
                if output_only.search(target):
                    continue
                pattern = re.sub(r"\{[^}]*\}|\*", "*", target[len("docs/knowledge-base/"):])
                if not list(KB.glob(pattern.rstrip("/") or ".")):
                    missing.append("%s: %s" % (path.relative_to(REPO), target))
        self.assertEqual(missing, [])

    def test_lower_region_runs_never_write_prod(self):
        prod_dir = ENVS["prod"]["docs_dir"]
        self.assertEqual(prod_dir, ".")
        for env in ("dev", "sit"):
            docs_dir = ENVS[env]["docs_dir"]
            self.assertNotEqual(docs_dir, ".")
            for pid, (f, meta) in self.prompts.items():
                if meta.get("pipeline") != "db" or not meta.get("outputs") or "<" in str(meta["outputs"]):
                    continue
                out = subprocess.run([sys.executable, str(REPO / "sdlc/kb/tools/prompts.py"), "outputs", f,
                                      "--env", env, "--stage", "_REGEN/test"],
                                     cwd=REPO, capture_output=True, text=True, check=True).stdout.split()
                for p in out:
                    self.assertIn("/DB-DOCS/%s/" % docs_dir, p, "%s %s -> %s" % (pid, env, p))
                    self.assertTrue(p.startswith("_REGEN/test/"), p)
        for script in ("gen_db_kb.py", "gen_semantic_assets.py", "gen_ui_field_map.py"):
            text = (REPO / "sdlc/framework/tools/kbgen" / script).read_text()
            self.assertIn("refusing to write", text, script)
            self.assertIn("--out-root", text, script)


if __name__ == "__main__":
    unittest.main()
