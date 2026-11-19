---
prompt_id: CTX-00
title: Domain context index and assembly
kind: prompt
pipeline: context
stage: 0
version: 2.0.0
shareable: true
requires: []
depends_on: [CTX-0A, CTX-0B, CTX-0C, CTX-0D, CTX-0E]
placeholders: [PRODUCT_NAME, DOMAIN_CONTEXT, DOMAIN_CONTEXT_DIR, TEAM_ROSTER, RUN_DATE]
outputs: ["{{DOMAIN_CONTEXT_DIR}}/CONTEXT_INDEX.md", "{{DOMAIN_CONTEXT}}"]
---

# CTX-00: Domain context index and assembly

## Purpose

Join the five domain-context modules for {{PRODUCT_NAME}} (business, technology, data, jobs,
and team) into the one domain-context document every prompt reads at `{{DOMAIN_CONTEXT}}`.
Then write an index that says which modules each prompt family needs, so a session can load
only those. Run it after any module changes.

## Before you start

1. Check that all five modules exist in `{{DOMAIN_CONTEXT_DIR}}`:
   - `CONTEXT_0A_BUSINESS_MODEL.md`
   - `CONTEXT_0B_TECHNOLOGY_STACK.md`
   - `CONTEXT_0C_DATA_ARCHITECTURE.md`
   - `CONTEXT_0D_JOB_ORCHESTRATION.md`
   - `CONTEXT_0E_TEAM_GLOSSARY.md`

   If one is missing, list it and ask whether to go ahead without it.
2. Read each module's closing lists.

## Steps

1. **Assemble.** Write `{{DOMAIN_CONTEXT}}` as the five modules in order (0A to 0E), each under
   its own numbered top-level section. Copy the content as it is, with its tags. Don't reword it.
2. **Merge the closing lists.** Combine the Open questions, Assumptions, Don't know and Sources
   read lists from all five modules at the end of the document. Remove exact duplicates, and
   keep each item's owner.
3. **Check for clashes.** Where two modules say different things about the same fact, keep both,
   tag the clash `[?]`, and add it to Open questions with an owner from `{{TEAM_ROSTER}}`.
4. **Write the index**, `{{DOMAIN_CONTEXT_DIR}}/CONTEXT_INDEX.md`. It has a module table (file,
   sections, line count) and this load table:

| Prompt family | Load | Also useful |
|---|---|---|
| DB discovery and schema (DB-01 to DB-08) | 0A, 0C | 0D |
| DB semantic, queries, lineage (DB-09 to DB-11) | 0A, 0C, 0D | 0E |
| DB guardrails, entities, tests (DB-12 to DB-15) | 0A, 0C, 0D, 0E | — |
| DB cross-module matrix (DB-16) | all | — |
| API modules (APP-01 to APP-11) | 0A, 0B, 0C | 0D |
| UI modules (APP-01 to APP-09, APP-12 to APP-14) | 0A, 0B | 0E |
| ETL modules (ETL-01 to ETL-13) | 0C, 0D | 0B |

## Output

Two files, each starting with:

```yaml
---
document: <Domain context | Domain context index>
product: {{PRODUCT_NAME}}
updated_date: {{RUN_DATE}}
prompt_id: CTX-00
prompt_version: 2.0.0
modules: [0A, 0B, 0C, 0D, 0E]
---
```

- `{{DOMAIN_CONTEXT}}`: the assembled context, followed by the merged lists.
- `{{DOMAIN_CONTEXT_DIR}}/CONTEXT_INDEX.md`: the module and load tables.

## Evidence rules

- Content is copied from the modules with its `[E: ...]`, `[A]` and `[?]` tags unchanged.
- A clash between modules is tagged `[?]`, never settled by choosing one side.
- Nothing is added that isn't in a module.

## Self-check

- [ ] All five modules are in the assembled file, or their absence is noted.
- [ ] Every `[A]` and `[?]` in the body is on the merged lists.
- [ ] Every clash is on Open questions.
- [ ] The index lists every module, with its line count.

## Open questions, assumptions and unknowns

The assembled file ends with the merged lists:

- **Open questions:** each with an owner.
- **Assumptions:** each `[A]`, and what changes if it's wrong.
- **Don't know:** each `[?]`, with who could answer.
- **Sources read:** from all modules.
