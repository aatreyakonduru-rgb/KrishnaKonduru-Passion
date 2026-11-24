---
prompt_id: DB-08
title: Database change impact analysis
kind: prompt
pipeline: db
stage: operational
version: 2.0.0
shareable: true
requires: []
depends_on: [DB-01, DB-03, DB-05, DB-06]
placeholders: [PRODUCT_NAME, KB_DB_DOCS, DOMAIN_CONTEXT, TEAM_ROSTER, SNOWFLAKE_DB, DB_SCHEMA, DB_ENV,
               DB_RESTRICTED_VIEW_SCHEMAS, RUN_DATE]
outputs: ["{{KB_DB_DOCS}}/CHANGE_IMPACT_<REQUIREMENT_ID>_<DATE>.md"]
---

# DB-08: Database change impact analysis

## Purpose

When a new requirement arrives, answer one question from the knowledge base: which
{{PRODUCT_NAME}} tables and columns must change, be added or be retired, and what else that
touches. The readers are developers, the DBA and whoever sizes the work. This prompt writes
no new reference documents and never touches the database.

## Before you start

1. Render this prompt: `prompts.py render DB_PROMPT_8_CHANGE_ANALYSIS.md --env <env>`.
2. Get the requirement text and its id (a ticket key or work id). If either is missing, stop and ask.
3. Read these, in this order. If one is missing, say so and carry on with the rest.
   - the domain context at `{{DOMAIN_CONTEXT}}`;
   - `{{KB_DB_DOCS}}/04_DB_CHANGE_IMPACT_MATRIX.md`, in full;
   - `{{KB_DB_DOCS}}/02_DB_TECHNICAL_REQUIREMENTS.md`, in full;
   - `{{KB_DB_DOCS}}/07_DB_SCHEMA_CATALOG.md`, only the tables the matrix points to;
   - `{{KB_DB_DOCS}}/00_DB_DISCOVERY_REPORT.md`, only the code values, keys, joins and history sections;
   - `{{KB_DB_DOCS}}/06_DB_SECURITY_REVIEW.md`, the masking inventory.
4. If the requirement touches more than five capabilities, read the catalog as summary lines only,
   and pull full detail only for the tables that step 3 marks as changing.
5. Don't query the database. If the documents can't answer something, tag it `[?]`.

## Steps

1. **Restate the requirement** in one paragraph. List anything ambiguous that changes the answer.
2. **Capabilities affected.** From the matrix, each capability with an impact level: high (changes
   certain), medium (depends on an answer), low (read-only or minor) or none. Give a reason for each.
3. **Tables affected.** For each table under an affected capability: its current state (rows and
   columns, from the catalog), the change needed, the change type and the source. The change types are:
   - new column, new table, or changed column (all need DDL);
   - new configuration rows only (no DDL);
   - read only;
   - no change.

   Every DDL change cites the catalog or TRD section it changes.
4. **Column changes.** For each DDL change: table, column, add, change or drop, proposed type,
   nullable, default, and reason. Follow the naming conventions in DB-03. If there are no DDL
   changes, say so.
5. **Sensitive-data impact.** For each new or changed column, say whether it holds sensitive data,
   using the masking inventory in DB-06, or tag it `[?]`. A new sensitive column needs a masking
   decision in each restricted view schema ({{DB_RESTRICTED_VIEW_SCHEMAS}}). A new table needs a
   view in each. Both go to the DBA.
6. **Job and code impact.** Does the requirement need a new code value, a new job or request type,
   a new detail table or a scheduling change? Only use values that appear in the discovery report
   or DB-03. A value that doesn't exist yet is "new", not assumed.
7. **Blocking questions.** Each question that must be answered before work starts, with its owner
   from the roster at `{{TEAM_ROSTER}}` (or a role) and whether it blocks. Also append each one to
   `{{KB_DB_DOCS}}/VALIDATION_LOG_DRAFT.md`.
8. **Suggested sub-tasks.** Split the work into tasks: DDL, view updates, configuration data,
   and knowledge-base updates. Give each a relative size and what it depends on. The sizes are:
   - XS: one object;
   - S: 2 to 5 objects, one team;
   - M: 6 to 15 objects, or two teams;
   - L: a new area, or more than 15 objects.

   Never estimate hours or days.
9. **After it ships.** List the refresh steps from `08_DB_REFRESH_PROTOCOL.md` that apply, and the
   validation-log items this change should close.

## Output

Write `{{KB_DB_DOCS}}/CHANGE_IMPACT_<REQUIREMENT_ID>_<DATE>.md`, starting with:

```yaml
---
document: DB change impact analysis
product: {{PRODUCT_NAME}}
requirement_id: <id>
source_db: {{SNOWFLAKE_DB}}
schema: {{DB_SCHEMA}}
environment: {{DB_ENV}}
generated_date: {{RUN_DATE}}
inputs: [<every KB file read>]
layer: design
prompt_id: DB-08
prompt_version: 2.0.0
---
```

Sections, in order: Requirement, Capabilities affected, Tables affected, Column changes,
Sensitive-data impact, Job and code impact, Blocking questions, Suggested sub-tasks, After it
ships, Open questions, Assumptions, Don't know, Files read.

## Evidence rules

- Every claim cites the KB document and section it came from, such as `[E: 02_DB_TECHNICAL_REQUIREMENTS §4]`.
- A table the requirement plainly doesn't touch is marked out of scope. It doesn't need a tag.
- Anything taken as true without a source is `[A]` and goes on the Assumptions list.
- Anything not known is `[?]` and goes on the Don't know list.

## Self-check

- [ ] The requirement id is in the file name and frontmatter.
- [ ] Every DDL change cites a catalog or TRD section.
- [ ] Every new column has a sensitive-data answer or a `[?]`.
- [ ] No code value, job type or table is assumed to exist without a source.
- [ ] No hours or days are estimated.
- [ ] Every blocking question has an owner and was appended to the draft validation log.

## Open questions, assumptions and unknowns

End with three lists:

- **Open questions:** the blocking questions, each with its owner.
- **Assumptions:** each `[A]`, and what changes in the impact if it's wrong.
- **Don't know:** each `[?]`, with who could answer.

Then add **Files read**.
