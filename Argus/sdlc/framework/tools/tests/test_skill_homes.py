import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import skill_homes  # noqa: E402


def sk(name, desc):
    return {"name": name, "what": skill_homes.first_sentence(desc), "description": desc}


KNOWN = {n: sk(n, d) for n, d in {
    "dashboard": "Role dashboard.", "intake": "Stage 1.", "research": "Stage 2.", "start": "Front door.",
    "app-brd": "Module BRD: runs shared prompt APP-02 with the team profile.", "app-run-pipeline": "Runs the stages.",
    "console": "Older name for /workbench. Starts it.", "workbench": "Start the Workbench.", "orphan": "Nobody's.",
}.items()}
CONFIG = {"everyone_skills": ["start", "workbench"],
          "roles": {"bsa": {"default_skills": ["dashboard", "intake"], "more_skills": ["research"]},
                    "architect": {"default_skills": ["dashboard"], "more_skills": ["app-run-pipeline"]}}}


class SkillHomeTests(unittest.TestCase):
    def test_only_the_orphan_is_not_assigned(self):
        self.assertEqual(skill_homes.unhomed(known=KNOWN, config=CONFIG), ["orphan"])
        self.assertEqual(skill_homes.counts(known=KNOWN, config=CONFIG),
                         {"skills": 9, "assigned": 6, "not_assigned": 1, "internal": 2})

    def test_stage_and_alias_count_as_homes(self):
        h = skill_homes.homes(known=KNOWN, config=CONFIG)
        self.assertEqual(h["app-brd"]["pipeline"], "app-run-pipeline")
        self.assertEqual(h["console"]["alias_of"], "workbench")

    def test_unknown_names_are_reported(self):
        cfg = dict(CONFIG, everyone_skills=["start", "nope"])
        self.assertEqual(skill_homes.unknown_names(known=KNOWN, config=cfg), ["nope"])

    def test_for_roles_puts_the_persons_commands_first_and_hides_none(self):
        got = skill_homes.for_roles(["bsa"], known=KNOWN, config=CONFIG)
        self.assertEqual([s["name"] for s in got["first"]], ["dashboard", "intake"])
        self.assertEqual([s["name"] for s in got["more"]], ["research"])
        self.assertEqual([s["name"] for s in got["everyone"]], ["start", "workbench"])
        self.assertEqual([s["name"] for s in got["pipelines"]["app-run-pipeline"]], ["app-brd"])
        self.assertEqual(got["aliases"], [("console", "workbench")])
        listed = {s["name"] for k in ("first", "more", "everyone", "internal", "other") for s in got[k]}
        listed |= {s["name"] for v in got["pipelines"].values() for s in v} | {a for a, _ in got["aliases"]}
        self.assertEqual(listed, set(KNOWN))

    def test_tip_turns_daily_and_skips_the_dashboard(self):
        days = [datetime.date(2026, 10, 15) + datetime.timedelta(d) for d in range(4)]
        tips = [skill_homes.tip(["bsa"], d, known=KNOWN, config=CONFIG)["name"] for d in days]
        self.assertNotIn("dashboard", tips)
        self.assertEqual(sorted(set(tips)), ["intake", "research", "start", "workbench"])

    def test_grid_shows_ticks_internal_rows_and_empty_rows(self):
        rows = {r["name"]: r for r in skill_homes.grid(known=KNOWN, config=CONFIG)}
        self.assertEqual(rows["intake"]["cells"]["BSA"], "first")
        self.assertEqual(rows["research"]["cells"]["BSA"], "tick")
        self.assertEqual(rows["start"]["cells"]["Everyone"], "tick")
        self.assertIn("a stage of /app-run-pipeline", rows["app-brd"]["internal"])
        self.assertIn("older name for /workbench", rows["console"]["internal"])
        self.assertEqual(set(rows["orphan"]["cells"].values()), {"none"})

    def test_apply_moves_ticks_and_refuses_internal_skills(self):
        cfg = {"everyone_skills": ["start"], "roles": {"bsa": {"default_skills": ["intake"], "more_skills": []},
                                                     "bsa_lead": {"default_skills": [], "more_skills": []}}}
        block = ("SDLC-DASHBOARD-SKILL-CONFIG v1\n- skill: orphan | BSA: tick\n- skill: intake | BSA: none\n"
                 "- skill: start | Everyone: none\nEND\n")
        new, said = skill_homes.apply(skill_homes.parse_block(block), cfg, known=KNOWN)
        self.assertEqual(new["roles"]["bsa"], {"default_skills": [], "more_skills": ["orphan"]})
        self.assertEqual(new["roles"]["bsa_lead"]["more_skills"], ["orphan"])
        self.assertEqual(new["everyone_skills"], [])
        self.assertEqual(len(said), 3)
        with self.assertRaises(ValueError):
            skill_homes.apply([("app-brd", "BSA", "tick")], cfg, known=KNOWN)
        with self.assertRaises(ValueError):
            skill_homes.apply([("orphan", "Nobody", "tick")], cfg, known=KNOWN)

    def test_write_lists_keeps_comments(self):
        import tempfile
        text = ("# who gets what\neveryone_skills: [start]\nroles:\n  bsa:\n    label: BSA\n"
                "    default_skills: [intake]\n    gate_roles: [bsa]\n")
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as fh:
            fh.write(text)
        cfg = {"everyone_skills": [], "roles": {"bsa": {"default_skills": ["intake"], "more_skills": ["research"]}}}
        skill_homes.write_lists(fh.name, cfg)
        out = open(fh.name).read()
        os.unlink(fh.name)
        self.assertIn("# who gets what", out)
        self.assertIn("everyone_skills: []", out)
        self.assertIn("    default_skills: [intake]\n    more_skills: [research]\n    gate_roles: [bsa]", out)

    def test_the_repository_names_only_installed_skills(self):
        self.assertEqual(skill_homes.unknown_names(), [])


if __name__ == "__main__":
    unittest.main()
