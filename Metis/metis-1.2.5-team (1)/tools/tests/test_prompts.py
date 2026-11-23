"""Tests for prompts.py (shared prompt lint and render) — stdlib unittest only.

    python3 -m unittest discover -s sdlc/kb/tools/tests -v
"""
import os
import shutil
import sys
import tempfile
import textwrap
import unittest

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)

import prompts  # noqa: E402

REG = {
    "PRODUCT_NAME": {"sources": ["profile:product.name"], "type": "text", "required": True},
    "DB_SCHEMA": {"sources": ["env:schema"], "type": "text", "required": True},
    "SCHEMAS": {"sources": ["env:schema", "profile:db.related_schemas"], "type": "sql_list"},
    "CODES": {"sources": ["profile:db.code_column_suffixes"], "type": "sql_endswith_any"},
    "JOINS": {"sources": ["profile:db.known_joins"], "type": "bullets"},
    "FILTER": {"sources": ["profile:db.active_record_filter.column"], "type": "text"},
}

PROFILE = {
    "product": {"name": "Acme Orders"},
    "paths": {"kb_root": "acme/kb"},
    "db": {"engine": "snowflake", "related_schemas": ["ACME_STG"], "code_column_suffixes": ["_CD"],
           "known_joins": ["ORD_LINE.ORD_ID -> ORD.ORD_ID"]},
    "lint": {"leak_terms": ["Acme"], "leak_patterns": [r"\bORD_[A-Z]+"]},
}

GOOD = textwrap.dedent("""\
    ---
    prompt_id: T-01
    title: Test
    kind: prompt
    pipeline: db
    version: 1.0.0
    shareable: true
    placeholders: [PRODUCT_NAME, DB_SCHEMA]
    outputs: [x.md]
    ---
    ## Purpose
    Document {{PRODUCT_NAME}} in {{DB_SCHEMA}}. List tables with more than 20 columns.
    ## Before you start
    Render it.
    ## Steps
    Run it.
    ## Output
    x.md
    ## Evidence rules
    Tag [E: Q1].
    ## Self-check
    - [ ] done
    ## Open questions, assumptions and unknowns
    Lists.
    """)


def issues(text, **kw):
    return prompts.lint_text(text, "t.md", REG, prompts.leak_rules(PROFILE, base="/nonexistent"), **kw)


def errors(text, **kw):
    return [i[3] for i in issues(text, **kw) if i[2] == "error"]


class LintTests(unittest.TestCase):
    def test_clean_prompt_passes(self):
        self.assertEqual(errors(GOOD), [])

    def test_bad_frontmatter_yaml_is_an_error(self):
        text = GOOD.replace("title:", "title: Bad: colon\nx:", 1)
        self.assertTrue(any("not valid YAML" in e for e in errors(text)))

    def test_unshared_prompt_skipped_unless_strict(self):
        text = GOOD.replace("shareable: true", "shareable: false")
        self.assertEqual(issues(text), [])
        self.assertTrue(any("shareable" in e for e in errors(text, strict=True)))

    def test_team_term_value_and_pattern_are_caught(self):
        errs = errors(GOOD.replace("Run it.", "Query ACME_STG for Acme orders in ORD_LINE."))
        self.assertTrue(any("team term 'Acme'" in e for e in errs))
        self.assertTrue(any("ACME_STG" in e for e in errs))
        self.assertTrue(any("team pattern" in e for e in errs))

    def test_old_tags_rejected(self):
        self.assertTrue(errors(GOOD.replace("Tag [E: Q1].", "Tag [CONFIRMED — Q1].")))
        self.assertTrue(errors(GOOD.replace("Lists.", "[REQUIRES STAKEHOLDER INPUT]")))

    def test_fixed_counts_rejected_but_thresholds_allowed(self):
        self.assertTrue(any("fixed count" in e for e in errors(GOOD.replace("Run it.", "Include the 28 qualifying tables."))))
        self.assertTrue(any("fixed count" in e for e in errors(GOOD.replace("Run it.", "Cover all 11 business capabilities."))))
        self.assertEqual(errors(GOOD), [])  # "more than 20 columns" is a threshold

    def test_placeholder_rules(self):
        errs = errors(GOOD.replace("Run it.", "Use {{SECRET_THING}}."))
        self.assertTrue(any("not declared" in e for e in errs))
        errs = errors(GOOD.replace("[PRODUCT_NAME, DB_SCHEMA]", "[PRODUCT_NAME, DB_SCHEMA, NOPE]").replace("Run it.", "{{NOPE}}"))
        self.assertTrue(any("not in placeholders.yaml" in e for e in errs))
        warns = [i for i in issues(GOOD.replace("[PRODUCT_NAME, DB_SCHEMA]", "[PRODUCT_NAME, DB_SCHEMA, JOINS]")) if i[2] == "warning"]
        self.assertTrue(warns)

    def test_missing_section_and_empty_self_check(self):
        self.assertTrue(any("## Output" in e for e in errors(GOOD.replace("## Output\n", "## Results\n"))))
        self.assertTrue(any("Self-check" in e for e in errors(GOOD.replace("- [ ] done", "done"))))

    def test_generic_leaks(self):
        self.assertTrue(any("email" in e for e in errors(GOOD.replace("Run it.", "Ask someone@example.org"))))
        self.assertFalse(any("email" in e for e in errors(GOOD.replace("Run it.", "Ask resource1@acme.example"))))
        self.assertTrue(any("email" in e for e in errors(GOOD.replace("Run it.", "Ask someone@acme.example.com"))))
        self.assertTrue(any("account" in e for e in errors(GOOD.replace("Run it.", "Account 123456789012"))))
        self.assertTrue(any("credential" in e for e in errors(GOOD.replace("Run it.", "password: hunter22"))))


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        with open(os.path.join(self.tmp, "envs.yaml"), "w") as fh:
            fh.write("default: sit\nschema: ACME_APP\nenvironments:\n  sit: {database: T_DB}\n  prod: {database: P_DB}\n")
        self.profile = dict(PROFILE, db=dict(PROFILE["db"], environments_file="envs.yaml"))

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def render(self, body, placeholders, env=None):
        text = "---\nplaceholders: [%s]\n---\n%s" % (", ".join(placeholders), body)
        return prompts.render(text, self.profile, REG, env=env, base=self.tmp)

    def test_values_filled(self):
        out = self.render("{{PRODUCT_NAME}} in {{DB_SCHEMA}}: IN ({{SCHEMAS}}) {{CODES}}\n{{JOINS}}",
                          ["PRODUCT_NAME", "DB_SCHEMA", "SCHEMAS", "CODES", "JOINS"])
        self.assertIn("Acme Orders in ACME_APP", out)
        self.assertIn("IN ('ACME_APP', 'ACME_STG')", out)
        self.assertIn("ENDSWITH(COLUMN_NAME, '_CD')", out)
        self.assertIn("- `ORD_LINE.ORD_ID -> ORD.ORD_ID`", out)

    def test_optional_missing_value_says_not_set(self):
        self.assertIn("(not set)", self.render("{{FILTER}}", ["FILTER"]))

    def test_empty_sql_list_is_null(self):
        self.assertEqual(prompts.format_value([], "sql_list"), "NULL")
        self.assertEqual(prompts.format_value(["O'Neil"], "sql_list"), "'O''Neil'")

    def test_unknown_env_and_undeclared_placeholder_fail(self):
        with self.assertRaises(ValueError):
            self.render("{{DB_SCHEMA}}", ["DB_SCHEMA"], env="uat")
        with self.assertRaises(ValueError):
            self.render("{{DB_SCHEMA}} {{PRODUCT_NAME}}", ["DB_SCHEMA"])

    def test_runtime_args(self):
        reg = dict(REG, MOD={"sources": ["runtime:arg.MOD"], "type": "text", "required": True})
        text = "---\nplaceholders: [MOD]\n---\nmodule {{MOD}}"
        out = prompts.render(text, self.profile, reg, base=self.tmp, args={"MOD": "billing"})
        self.assertIn("module billing", out)
        with self.assertRaises(ValueError):
            prompts.render(text, self.profile, reg, base=self.tmp)

    def test_required_value_missing_fails(self):
        self.profile["product"] = {}
        with self.assertRaises(ValueError):
            self.render("{{PRODUCT_NAME}}", ["PRODUCT_NAME"])

    def test_stage_moves_outputs_and_keeps_live_path(self):
        reg = dict(REG, KB={"sources": ["profile:paths.kb_root"], "type": "text", "required": True},
                   DOCS={"sources": ["profile:paths.docs"], "type": "text", "required": True})
        profile = dict(self.profile, paths={"kb_root": "acme/kb", "docs": "acme/kb/DB", "other": "elsewhere"})
        path = os.path.join(self.tmp, "p.md")
        with open(path, "w") as fh:
            fh.write('---\nplaceholders: [KB, DOCS]\noutputs: ["{{DOCS}}/01.md"]\n---\nread {{DOCS}}/00.md\n')
        out = prompts.render_file(path, profile, reg, stage="acme/kb/_REGEN/d1/")
        self.assertEqual(prompts.outputs(out), ["acme/kb/_REGEN/d1/DB/01.md"])
        self.assertIn("read acme/kb/_REGEN/d1/DB/00.md", out)
        self.assertIn("Staging run", out)
        self.assertIn("read the same file from `acme/kb`", out)
        staged, live = prompts.stage_profile(profile, "acme/kb/_REGEN/d1")
        self.assertEqual((live, staged["paths"]["other"]), ("acme/kb", "elsewhere"))
        self.assertEqual(profile["paths"]["docs"], "acme/kb/DB")
        plain = prompts.render_file(path, profile, reg)
        self.assertEqual(prompts.outputs(plain), ["acme/kb/DB/01.md"])
        self.assertNotIn("Staging run", plain)

    def test_env_docs_dir_moves_db_docs(self):
        with open(os.path.join(self.tmp, "envs.yaml"), "w") as fh:
            fh.write("default: sit\nschema: S\nenvironments:\n  sit: {database: T_DB, docs_dir: T-SIT}\n"
                     "  prod: {database: P_DB, docs_dir: .}\n")
        reg = dict(REG, DOCS={"sources": ["profile:paths.db_docs"], "type": "text", "required": True})
        profile = dict(self.profile, paths={"kb_root": "kb", "db_docs": "kb/DB"})
        text = "---\nplaceholders: [DOCS]\n---\n{{DOCS}}"
        self.assertTrue(prompts.render(text, profile, reg, env="sit", base=self.tmp).endswith("kb/DB/T-SIT"))
        self.assertTrue(prompts.render(text, profile, reg, env="prod", base=self.tmp).endswith("kb/DB"))

    def test_stage_needs_kb_root(self):
        with self.assertRaises(ValueError):
            prompts.stage_profile({"paths": {}}, "x")


if __name__ == "__main__":
    unittest.main()
