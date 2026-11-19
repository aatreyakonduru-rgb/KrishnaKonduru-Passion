# Playbook: Migration Validation Check

**Playbook ID:** PB-VALIDATION-migration-check  
**Paste into:** Devin Cloud → Settings → Playbooks → New Playbook  
**CLI equivalent:** none — run this playbook body directly (no skill file backs it)  
**Scope:** Repository-wide validation of migrated agentic system

---

## Title (paste into Devin Cloud "Title" field)

```
Acme Claims Agentic System Migration Validation
```

## Description (paste into Devin Cloud "Description" field)

```
Comprehensive validation of the migrated Acme Claims agentic system. Checks all file structures, path references, skill accessibility, agent availability, playbook integrity, template accessibility, rule accessibility, and knowledge base completeness. Run this after migration to verify all components are properly configured for Devin Cloud deployment.
```

## Playbook Body (paste into the main instruction area)

---

You are validating the Acme Claims agentic system migration to ensure all components are properly configured and accessible.

## VALIDATION CHECKLIST

### STEP 1 — Directory Structure Validation

Check that both target directories exist and have the correct structure:

```
Expected structure:
.devin/                      (repository root - required for Devin discovery)
  agents/
  skills/<skill-name>/SKILL.md
  templates/
  rules/
  config.json
  config.cloud.json
  hooks.v1.json

sdlc/framework/
  context/
    session/
    kb/
  playbooks/
  workflows/
  archive/deprecated-skills/
  README.md

docs/knowledge-base/
  PROMPTS/
  DB-DOCS/
  DOCUMENTATION/
  MODULES/
  ETL/
  SHARED/
  OPEN_QUESTIONS.md
  README.md
```

**Action:** Use `ls` commands to verify directory structure exists and matches expected layout.

### STEP 2 — Skills Validation

Skills must live one level deep at the repository root so Devin can discover them:
`.devin/skills/<skill-name>/SKILL.md`. Category sub-directories break discovery and
are not used; deprecated skills are kept out of the discovery path in
`sdlc/framework/archive/deprecated-skills/`.

**Action:**
1. Count `.devin/skills/*/SKILL.md` (64 active skills)
2. Verify every skill has YAML frontmatter with `name` matching its directory, a
   non-empty `description`, and `triggers` containing both `user` and `model`
   (`model` is required for Devin to invoke a skill automatically)
3. Check that no absolute paths remain in skill files

### STEP 3 — Agents Validation

Check that all agents are accessible in dual format:

**Expected agents:**
- YAML format: intake.agent.yaml, research.agent.yaml, plan.agent.yaml, etc.
- AGENT.md format: discoverer, documenter, validator, db-analyst, etc.

**Action:**
1. Verify 19 agents total
2. Check each agent has both YAML and AGENT.md format where applicable
3. Verify agent paths reference correct knowledge base location

### STEP 4 — Playbooks Validation

Check that all 30 playbooks are present and have correct path references:

**Expected playbooks:** PB-01 through PB-30 plus PLAYBOOK-GUIDE.md

**Action:**
1. Verify all 30 playbooks exist
2. Check that playbooks use repository-relative paths (no absolute or machine-local paths)
3. Verify skill references use the flat root layout (`/intake`, `/research`, i.e. `.devin/skills/<name>/SKILL.md`)
4. Check no absolute paths remain in playbooks

### STEP 5 — Templates Validation

Check that all templates are accessible:

**Expected templates:**
- complexity-matrix.yaml
- jira-backlog-schema.yaml
- gap-analysis.md
- routing-map.md
- pr-template.md

**Action:**
1. Verify the templates listed above exist in `.devin/templates/`
2. Check templates are accessible from playbooks

### STEP 6 — Rules Validation

Check that all rules are accessible:

**Expected rules:**
- DOMAIN_CONTEXT.md
- approval-gates.yaml
- data-access.md
- pii-handling.md
- secure-coding.md

**Action:**
1. Verify all 5 rules exist in `.devin/rules/`
2. Check that rules are referenced correctly in skills and hooks

### STEP 7 — Configuration Files Validation

Check that configuration files are properly configured:

**Expected files:**
- config.json
- hooks.v1.json
- config.local.json (if present)

**Action:**
1. Verify config.json exists and is valid JSON
2. Verify hooks.v1.json exists and is valid JSON
3. Check that hooks use dynamic path resolution (no absolute paths)
4. Verify session directory path in hooks uses relative resolution

### STEP 8 — Knowledge Base Validation

Check that all knowledge base components are present:

**Expected components:**
- `sdlc/kb/kb-prompts/` (repo root) - the shared KB prompts: context (CTX), app (APP), DB, ETL, runners and helpers
- `PROMPTS/` - `README.md` and `Archive/` only: the older ACME-specific prompts, kept for history
- `DB-DOCS/` - Database documentation
- `DOCUMENTATION/` - HTML presentations, status reports
- `MODULES/` - Generated module documentation
- `ETL/` - ETL documentation
- `SHARED/DOMAIN_CONTEXT.md` - Core domain context
- `OPEN_QUESTIONS.md` - Open questions tracker

**Action:**
1. Verify all prompt categories exist
2. Check that PROMPT_0 variants are present (critical for shared context generation)
3. Verify SHARED/DOMAIN_CONTEXT.md exists
4. Check that no absolute paths remain in knowledge base files

### STEP 9 — Path Reference Validation

Check that all path references are repository-relative:

**Action:**
1. Search for any remaining absolute paths (C:\Users\, /Users/, etc.)
2. Verify all skills reference `docs/knowledge-base/` instead of `AI-Generated-Docs/`
3. Check that all hooks use dynamic path resolution
4. Verify no username-specific paths remain

### STEP 10 — Linkage Validation

Check that all system linkages work correctly:

**Action:**
1. Verify skills can reference knowledge base files
2. Check that playbooks can reference skills and templates
3. Verify agents can reference knowledge base
4. Check that hooks can access session directory
5. Test that rules are accessible from skills

## VALIDATION REPORT

After completing all checks, generate a validation report with the following structure:

```
# Acme Claims Agentic System Migration Validation Report

## ✅ PASSED CHECKS
- Directory structure: [PASS/FAIL]
- Skills count and categorization: [PASS/FAIL] (89+ skills expected)
- Agents dual format: [PASS/FAIL] (19 agents expected)
- Playbooks count and paths: [PASS/FAIL] (30 playbooks expected)
- Templates accessibility: [PASS/FAIL] (7 templates expected)
- Rules accessibility: [PASS/FAIL] (5 rules expected)
- Configuration files: [PASS/FAIL]
- Knowledge base completeness: [PASS/FAIL]
- Path references (relative only): [PASS/FAIL]
- System linkages: [PASS/FAIL]

## ⚠️ ISSUES FOUND
[List any issues discovered during validation]

## 🔧 RECOMMENDED FIXES
[List any recommended fixes for issues found]

## 📊 SUMMARY
[Overall assessment: READY FOR DEPLOYMENT / NEEDS FIXES]
```

## CRITICAL SUCCESS CRITERIA

The migration is considered successful only if:
1. All 89+ skills are present and properly categorized
2. All 19 agents are present in dual format
3. All 30 playbooks are present with correct path references
4. All 7 templates are accessible
5. All 5 rules are accessible
6. Configuration files are valid and use relative paths
7. Knowledge base is complete with PROMPT_0 variants
8. No absolute paths remain in any files
9. All system linkages work correctly

## OUTPUT

Provide the validation report and indicate whether the system is ready for Devin Cloud deployment or requires fixes.