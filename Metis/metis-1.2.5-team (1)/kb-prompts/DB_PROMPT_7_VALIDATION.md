---
prompt_id: DB-07
title: Validation log, session state and refresh protocol
kind: prompt
pipeline: db
stage: 7
version: 2.0.0
shareable: true
requires: []
depends_on: [DB-02, DB-03, DB-04, DB-05, DB-06]
placeholders: [PRODUCT_NAME, KB_DB_DOCS, TEAM_ROSTER, SNOWFLAKE_DB, DB_SCHEMA, DB_ENV, RUN_DATE]
outputs: ["{{KB_DB_DOCS}}/VALIDATION_LOG.md", "{{KB_DB_DOCS}}/SESSION_STATE.md",
          "{{KB_DB_DOCS}}/08_DB_REFRESH_PROTOCOL.md"]
---

# DB-07: Validation log, session state and refresh protocol

## Purpose

Close out the first pass of the {{PRODUCT_NAME}} database documents with three working files:
one list of every open question for reviewers, a record of which stages have run, and the
steps and queries for keeping the documents current.

## Before you start

1. Render this prompt: `prompts.py render DB_PROMPT_7_VALIDATION.md --env <env>`.
2. Read the outputs of DB-02 to DB-06 in `{{KB_DB_DOCS}}`. If one is missing, record that stage as
   not run. Don't make up its questions.
3. If `{{KB_DB_DOCS}}/VALIDATION_LOG_DRAFT.md` exists, read it too. Earlier stages may have
   appended questions to it.
4. Read the roster at `{{TEAM_ROSTER}}`. If none is set, assign by role only.

## Steps

### 1. Validation log

1. Collect every item on the Open questions and Don't know lists of DB-02 to DB-06, plus the draft log.
2. Merge items that ask the same thing. Keep a note of every document each item came from.
3. Rewrite each item so it stands alone. The reviewer won't have any other document. Put table
   and column names, values and counts in the item itself. Never write "see TRD section 5".
4. Give each item a priority:
   - P1: the documents are wrong until it's answered;
   - P2: it improves quality;
   - P3: nice to have.
5. Assign each one from the roster, by role. Don't guess a person the roster doesn't list.

Each item uses this block:

```markdown
## Q<n> · P<priority> · <short title>

**Question:** <one clear question>
**What we found:** <the facts, stated in full>
**What the schema can't tell us:** <the gap>
**What we need from you:**
1. <an answer that fits in one or two sentences>
**Raised in:** <document names>
**Assigned to:** <name and role, or role only>
**Status:** Open
**Answer:**
```

Put a summary table at the top (number, priority, topic, assigned to, status) and a total line.
Order the items by priority, then by business area.

### 2. Session state

A table of the database stages: stage, prompt id, status, output file, date and who ran it. Fill
it from the output files' frontmatter. Then the review gates (business analyst sign-off of DB-02,
developer and analyst review of DB-03) with their recorded status. End with a handoff note: where
the last run stopped, and which files the next session must read first.

### 3. Refresh protocol

1. **When to refresh:** after any deployment that changes the schema, at least monthly, before a
   new design phase, and whenever someone reports drift.
2. **Steps:** rerun DB-01, compare it with the stored report, rerun only the stages a change
   affects (table below), update the frontmatter dates and the session state, and commit with
   the change ticket.
3. **Drift queries.** Include these, with `<LAST_REFRESH_DATE>` explained as the `generated_date`
   of the stored discovery report:

```sql
-- R1: tables created since the last refresh
SELECT TABLE_NAME, ROW_COUNT, CREATED, COMMENT
FROM {{SNOWFLAKE_DB}}.INFORMATION_SCHEMA.TABLES
WHERE TABLE_SCHEMA = '{{DB_SCHEMA}}' AND TABLE_TYPE = 'BASE TABLE'
  AND CREATED > '<LAST_REFRESH_DATE>'::TIMESTAMP
ORDER BY CREATED DESC;

-- R2: tables altered since the last refresh (DDL or data)
SELECT TABLE_NAME, LAST_ALTERED, ROW_COUNT
FROM {{SNOWFLAKE_DB}}.INFORMATION_SCHEMA.TABLES
WHERE TABLE_SCHEMA = '{{DB_SCHEMA}}' AND TABLE_TYPE = 'BASE TABLE'
  AND LAST_ALTERED > '<LAST_REFRESH_DATE>'::TIMESTAMP
ORDER BY LAST_ALTERED DESC;

-- R3: tables that were empty and now have rows
-- Fill the list from the stored report's "Empty tables" section.
SELECT TABLE_NAME, ROW_COUNT, LAST_ALTERED
FROM {{SNOWFLAKE_DB}}.INFORMATION_SCHEMA.TABLES
WHERE TABLE_SCHEMA = '{{DB_SCHEMA}}' AND TABLE_TYPE = 'BASE TABLE'
  AND ROW_COUNT > 0
  AND TABLE_NAME IN (<empty tables from the stored report>);

-- R4: column counts now, to compare with the stored report
SELECT TABLE_NAME, COUNT(*) AS COLUMN_COUNT
FROM {{SNOWFLAKE_DB}}.INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = '{{DB_SCHEMA}}'
GROUP BY TABLE_NAME
ORDER BY TABLE_NAME;
```

   Tables that disappeared show up as names in the stored report that R4 no longer returns.

4. **What to rerun:**

| Change | Found by | Rerun |
|---|---|---|
| New table | R1 | DB-01, DB-03, DB-05 |
| Dropped table | R4 against the stored report | DB-03, DB-05 |
| Columns added or changed | R2 and R4 | DB-03, DB-05 (wide-table detail for that table) |
| Empty table now has rows | R3 | DB-03, DB-05 |
| Row counts changed only | R2 with the same column count | DB-03 volumes; DB-04 if a table crosses the diagram threshold |
| New code value | DB-01 Q12 | DB-02, DB-04 lifecycles, DB-05 glossary |
| New or changed policy | DB-01 Q10 | DB-06 |

## Output

Write three files in `{{KB_DB_DOCS}}`: `VALIDATION_LOG.md`, `SESSION_STATE.md` and
`08_DB_REFRESH_PROTOCOL.md`. Each starts with:

```yaml
---
document: <DB validation log | DB session state | DB refresh protocol>
product: {{PRODUCT_NAME}}
source_db: {{SNOWFLAKE_DB}}
schema: {{DB_SCHEMA}}
environment: {{DB_ENV}}
generated_date: {{RUN_DATE}}
prompt_id: DB-07
prompt_version: 2.0.0
---
```

## Evidence rules

- In the validation log, each "What we found" fact keeps the tag it had in its source document.
- Session state takes its facts from the output files' frontmatter, `[E: <file> frontmatter]`.
  A stage with no output file is marked not run, not guessed.
- Anything taken as true without a source is `[A]` and goes on the Assumptions list.
- Anything not known is `[?]` and goes on the Don't know list.

## Self-check

- [ ] Every open question and unknown from DB-02 to DB-06 is in the validation log, or merged into an item.
- [ ] Every item can be answered without opening another file.
- [ ] Every item has a priority and an owner from the roster, or a role.
- [ ] Session state matches the files actually present.
- [ ] Every drift query uses the team's database and schema, with no hard-coded table list.

## Open questions, assumptions and unknowns

The validation log is the open-questions list. Each of the three files still ends with:

- **Assumptions:** each `[A]`, and what changes if it's wrong.
- **Don't know:** each `[?]`, with who could answer.
