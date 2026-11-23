---
prompt_id: DB-21
title: Database object logic extraction
kind: prompt
pipeline: db
stage: 2.7
version: 1.0.0
shareable: true
requires: [snowflake]
depends_on: [DB-01, DB-22]
placeholders: [PRODUCT_NAME, KB_DB_DOCS, SNOWFLAKE_DB, DB_SCHEMA, DB_ENV, DB_RESTRICTED_VIEW_SCHEMAS, RUN_DATE]
outputs: ["{{KB_DB_DOCS}}/21_DB_OBJECT_LOGIC.md"]
---

# DB-21: Database object logic extraction

## Purpose

Record the logic inside {{PRODUCT_NAME}} database objects: views, stored procedures, functions and
tasks. Business rules for statuses, amounts and derived fields usually live here, not in tables.
For each object, the output shows which source column feeds each output column and what
transformation applies. The semantic layer and the lineage prompt (DB-11, DB-23) read this.

## Before you start

1. Render this prompt: `prompts.py render DB_PROMPT_21_OBJECT_LOGIC.md --env <env>`.
2. Read `{{KB_DB_DOCS}}/00_DB_DISCOVERY_REPORT.md` for the object list (Q1, Q9, Q11).
3. Read `{{KB_DB_DOCS}}/22_DB_SENSITIVITY.yaml`. Object definitions can contain literal values
   such as account numbers or test data. Copy the logic, not any literal from a sensitive column.
4. Read-only: `GET_DDL` and `INFORMATION_SCHEMA` only.

## Steps

### L1: Object inventory

```sql
SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE, IS_SECURE
FROM {{SNOWFLAKE_DB}}.INFORMATION_SCHEMA.VIEWS
WHERE TABLE_SCHEMA = '{{DB_SCHEMA}}';

SHOW PROCEDURES IN SCHEMA {{SNOWFLAKE_DB}}.{{DB_SCHEMA}};
SHOW USER FUNCTIONS IN SCHEMA {{SNOWFLAKE_DB}}.{{DB_SCHEMA}};
SHOW TASKS IN SCHEMA {{SNOWFLAKE_DB}}.{{DB_SCHEMA}};
```

Record each object. A secure view (`IS_SECURE = YES`) hides its definition. Record it as
`definition: hidden (secure view)` and mark `[?]`. Don't try to read it another way.

### L2: Definition of each view

```sql
SELECT GET_DDL('VIEW', '{{SNOWFLAKE_DB}}.{{DB_SCHEMA}}.<VIEW_NAME>');
```

For each procedure, function and task, use `GET_DDL` with the matching type (`'PROCEDURE'`,
`'FUNCTION'`, `'TASK'`). Take the arguments from `SHOW` output.

### L3: Output-to-source column map

For each view, list each output column and its source:

| Output column | Source table.column | Expression | Notes |
|---|---|---|---|

Read the `SELECT` list from the definition. Use exact names. An expression that combines several
columns is recorded as written. A column whose source can't be traced is `[?]`.

### L4: Business rules inside logic

From `CASE` expressions, `WHERE` clauses and joins in the definitions, record each rule that
decides a value. Quote the rule. Give the object and line. Don't name the business meaning of a code
unless DB-01 Q12 or the domain context says it.

### L5: Restricted views

For each view in `{{DB_RESTRICTED_VIEW_SCHEMAS}}`, record which base table it reads and which
columns it masks or filters. This is the evidence the guardrails (DB-12) need.

### L6: Procedures and tasks

For each procedure and task, record: what it reads, what it writes (table and column), its trigger
or schedule (from `SHOW TASKS`, schedule `[E: SHOW TASKS]`), and whether it changes data. Don't call
a procedure to see what it does.

## Output

Write `{{KB_DB_DOCS}}/21_DB_OBJECT_LOGIC.md`, starting with:

```yaml
---
document: DB object logic
product: {{PRODUCT_NAME}}
source_db: {{SNOWFLAKE_DB}}
schema: {{DB_SCHEMA}}
environment: {{DB_ENV}}
generated_date: {{RUN_DATE}}
prompt_id: DB-21
prompt_version: 1.0.0
---
```

Sections: Object inventory (L1), Views and their output-to-source map (L2, L3), Business rules in
logic (L4), Restricted views (L5), Procedures and tasks (L6), Hidden or unreadable objects,
Open questions, Assumptions, Don't know.

## Evidence rules

- Every definition is tagged `[E: GET_DDL <object>]`. Every rule carries the object and line.
- A secure view or an unreadable object is `[?]`.
- Logic is copied as written. Never rewrite it into a simpler form.

## Self-check

- [ ] Every object from L1 has an entry or a `[?]`.
- [ ] Every view output column has a source or `[?]`.
- [ ] Every restricted view is in L5.
- [ ] No literal from a sensitive column is copied.
- [ ] No procedure was executed.

## Open questions, assumptions and unknowns

- `open_questions`: rules that look wrong or conflict with the domain context, with the owner who can answer.
- `assumptions`: any expression read as a rule without a comment confirming it.
- `unknowns`: hidden objects and untraceable columns, with who could share the definition.
