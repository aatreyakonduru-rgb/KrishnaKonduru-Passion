---
prompt_id: DB-14
title: Application verified answers
kind: prompt
pipeline: db
stage: 14
version: 2.0.0
shareable: true
requires: []
depends_on: [DB-09, DB-11, DB-12, DB-13]
placeholders: [PRODUCT_NAME, KB_DB_DOCS, DOMAIN_CONTEXT, SNOWFLAKE_DB, DB_SCHEMA, DB_ENV,
               DB_DEFAULT_VIEW_SCHEMA, RUN_DATE]
outputs: ["{{KB_DB_DOCS}}/14_DB_APP_VERIFIED_QUERIES.md"]
---

# DB-14: Application verified answers

## Purpose

DB-10 covers "write me SQL". This prompt covers the questions people actually ask about
{{PRODUCT_NAME}}: how do I do something, what happens if something changes, why is something
stuck, and is something healthy. Each answer is SQL, steps, an impact trace or a mix, and cites
the lineage, guardrails and entity registry it rests on. Agents answering application
questions use these as their reference.

## Before you start

1. Render this prompt: `prompts.py render DB_PROMPT_14_APP_VERIFIED_QUERIES.md --env <env>`.
2. Read in full: `09_DB_SEMANTIC_LAYER.yaml`, `11_DB_DATA_LINEAGE.yaml`, `12_DB_AI_GUARDRAILS.yaml`
   and `13_DB_ENTITY_REGISTRY.yaml` in `{{KB_DB_DOCS}}`. If any is missing, stop and ask.
3. Read the domain context at `{{DOMAIN_CONTEXT}}` for how users describe their work. Use
   `10_DB_VERIFIED_QUERIES.md` only to avoid repeating a query.
4. Don't query the database.

## Steps

1. **Write at least 30 answers.** Take the questions from the entities, lineage flows and
   guardrails.

| Category | At least | Draw from |
|---|---|---|
| Status and health | 6 | entity statuses, pending or in-progress work, sync or load records, empty tables |
| How-to | 8 | internal flows in the lineage, such as staging to base, approvals and requests |
| Impact | 6 | outbound flows: "if this value changes, what downstream is affected, and when?" |
| Troubleshooting | 6 | forbidden patterns: why a count differs, why a join duplicates, why something is stuck |
| Cross-module | 4 | flows that span the UI, API, ETL and database |

2. **Answer types:**
   - **SQL:** follows every mandatory filter and uses `{{DB_DEFAULT_VIEW_SCHEMA}}`.
   - **Steps:** numbered, and each step cites a lineage flow or entity.
   - **Impact trace:** follows lineage ids from the change to each consumer. It says when the effect
     appears, only if a source gives the timing.
   - **Hybrid:** SQL plus how to read the result.
3. **Honesty.** If the answer depends on a flow at confidence 0.3, or on an unknown schedule, say so
   in the answer and list it. Never fill the gap with a likely answer.

## Output

Write `{{KB_DB_DOCS}}/14_DB_APP_VERIFIED_QUERIES.md`, starting with:

```yaml
---
document: DB application verified answers
product: {{PRODUCT_NAME}}
source_db: {{SNOWFLAKE_DB}}
schema: {{DB_SCHEMA}}
environment: {{DB_ENV}}
generated_date: {{RUN_DATE}}
answer_count: <n>
prompt_id: DB-14
prompt_version: 2.0.0
---
```

Each answer uses this block:

```markdown
## AVQR-<nnn>: <short title>

**Type:** <SQL | Steps | Impact trace | Hybrid> · **Category:** <category> · **Difficulty:** <level>
**Question:**
> <as a user would ask it>

**Answer:**
<SQL, steps or trace>

**Sources:** <lineage ids, guardrail ids, entity ids>
**Guardrails applied:** <ids>
**Caveats:** <any 0.3 flow or unknown the answer depends on, or "none">
```

Then a summary table, Open questions, Assumptions, Don't know, and Files read.

## Evidence rules

- Every answer cites its source ids (`[E: 11_DB_DATA_LINEAGE OUT-2]`, `[E: 12_DB_AI_GUARDRAILS FP-003]`).
- Any timing, schedule or owner without a source is `[?]` and goes on the Don't know list.
- Anything taken as true without a source is `[A]` and goes on the Assumptions list.

## Self-check

- [ ] At least 30 answers, and every category meets its minimum.
- [ ] Every SQL answer applies the mandatory filters and the default schema.
- [ ] Every answer has sources and caveats.
- [ ] No answer invents a schedule, owner or downstream effect.
- [ ] Every `[A]` and `[?]` is on its list.

## Open questions, assumptions and unknowns

End with three lists:

- **Open questions:** each gap that stopped an answer, with an owner.
- **Assumptions:** each `[A]`, and what changes if it's wrong.
- **Don't know:** each `[?]`, with who could answer.
