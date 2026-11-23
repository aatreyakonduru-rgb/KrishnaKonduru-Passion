---
prompt_id: DB-20
title: Database query history mining
kind: prompt
pipeline: db
stage: 2.6
version: 1.0.0
shareable: true
requires: [snowflake]
depends_on: [DB-01]
placeholders: [PRODUCT_NAME, KB_DB_DOCS, SNOWFLAKE_DB, DB_SCHEMA, DB_ENV, DB_QUERY_HISTORY_DAYS, DB_DEFAULT_VIEW_SCHEMA, RUN_DATE]
outputs: ["{{KB_DB_DOCS}}/20_DB_USAGE_PATTERNS.md"]
---

# DB-20: Database query history mining

## Purpose

Find out how {{PRODUCT_NAME}} data is actually queried: which tables and columns are read most, which
filters people apply, which joins they use and which questions they ask. The results seed the
verified queries (DB-10) and the business-term map (DB-19). Real usage is better evidence than a
prompt writer's guess about what users need.

## Before you start

1. Render this prompt: `prompts.py render DB_PROMPT_20_QUERY_HISTORY.md --env <env>`.
2. Read `{{KB_DB_DOCS}}/00_DB_DISCOVERY_REPORT.md` for the table and column list.
3. Read `{{KB_DB_DOCS}}/22_DB_SENSITIVITY.yaml`. Query text may contain literal values. Never copy a
   literal from a sensitive column into the output.
4. Use `{{DB_QUERY_HISTORY_DAYS}}` days of history. If the value is `(not set)`, stop and ask the owner.
5. `ACCOUNT_USAGE` lags by up to two hours. Record the run time with the results.

## Steps

### U1: Queries that ran in this schema

```sql
SELECT QUERY_ID, QUERY_TYPE, USER_NAME, ROLE_NAME, START_TIME, TOTAL_ELAPSED_TIME,
       ROWS_PRODUCED, DATABASE_NAME, SCHEMA_NAME, QUERY_TEXT
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE START_TIME >= DATEADD(day, -{{DB_QUERY_HISTORY_DAYS}}, CURRENT_TIMESTAMP())
  AND DATABASE_NAME = '{{SNOWFLAKE_DB}}'
  AND SCHEMA_NAME = '{{DB_SCHEMA}}'
  AND QUERY_TYPE = 'SELECT'
  AND EXECUTION_STATUS = 'SUCCESS';
```

`SCHEMA_NAME` is the session's default schema. It misses queries that read this schema from a
different default. U2 covers them, because `ACCESS_HISTORY` lists every object read. Record this
limit as an assumption.

### U2: Tables and columns used

Use `ACCESS_HISTORY` for column-level use:

```sql
SELECT b.value:objectName::STRING AS OBJECT_NAME,
       c.value:columnName::STRING AS COLUMN_NAME,
       COUNT(*) AS USES
FROM SNOWFLAKE.ACCOUNT_USAGE.ACCESS_HISTORY h,
     LATERAL FLATTEN(input => h.BASE_OBJECTS_ACCESSED) b,
     LATERAL FLATTEN(input => b.value:columns) c
WHERE h.QUERY_START_TIME >= DATEADD(day, -{{DB_QUERY_HISTORY_DAYS}}, CURRENT_TIMESTAMP())
  AND b.value:objectDomain::STRING IN ('Table', 'View')
  AND b.value:objectName::STRING LIKE '{{SNOWFLAKE_DB}}.{{DB_SCHEMA}}.%'
GROUP BY 1, 2
ORDER BY USES DESC;
```

Record the most-used columns, up to the top 100. Columns that DB-22 marks with
`skip_value_sampling: true` are listed by name only.

### U3: Filters people apply

From the `QUERY_TEXT` of the U1 results, extract the `WHERE` predicates that compare a column to a
literal. Count each column-and-operator pair. Report column names and counts only. Don't report the
literal value when the column is sensitive.

### U4: Joins people use

From the `QUERY_TEXT`, list each pair of tables joined on equal columns, with a count. A pair that
doesn't appear in DB-01 Q13 is a candidate join, not a confirmed one. Record it as one.

### U5: Questions as users ask them

Group the query shapes (same tables, same filters, different literals) into patterns. Give each
pattern a short plain-English description of what it answers. Keep the 30 patterns with the most
queries. Don't name a person who ran a query. Use roles only.

### U6: Views and base tables

Count how many queries read `{{DB_DEFAULT_VIEW_SCHEMA}}` and how many read base tables directly.
A large number of base-table reads is a finding for the owner.

## Output

Write `{{KB_DB_DOCS}}/20_DB_USAGE_PATTERNS.md`, starting with:

```yaml
---
document: DB usage patterns
product: {{PRODUCT_NAME}}
source_db: {{SNOWFLAKE_DB}}
schema: {{DB_SCHEMA}}
environment: {{DB_ENV}}
generated_date: {{RUN_DATE}}
history_days: {{DB_QUERY_HISTORY_DAYS}}
prompt_id: DB-20
prompt_version: 1.0.0
---
```

Sections, in order: Summary (query count, user count by role, run time), Most-read columns (U2),
Filters in use (U3), Joins in use and whether confirmed (U4), Query patterns (U5), Reads by schema
(U6), Open questions, Assumptions, Don't know.

## Evidence rules

- Every number is tagged `[E: U1]`, `[E: U2]` and so on.
- Query text is quoted only for the shape. Replace every literal with a placeholder such as
  `:value`, whether or not the column is sensitive. Literals are data, and the output doesn't
  keep them.
- Before saving, scan the document for quoted strings, long numbers, e-mail addresses, IP
  addresses and credential patterns. Replace each hit with a placeholder and record the
  replacement in the Assumptions section.
- A pattern without a count from the query results is `[?]`.

## Self-check

- [ ] The history window is recorded in the header.
- [ ] No literal is written: sensitive or not. The scan above ran.
- [ ] No person's name appears; roles only.
- [ ] Every candidate join not in DB-01 Q13 is labelled candidate.
- [ ] Every `[A]` and `[?]` is in its list.

## Open questions, assumptions and unknowns

- `open_questions`: heavy base-table readers and unconfirmed joins, with the platform owner who can answer.
- `assumptions`: the session-schema limit in U1, and what changes if it's wrong.
- `unknowns`: columns never seen in the window (not the same as unused).
