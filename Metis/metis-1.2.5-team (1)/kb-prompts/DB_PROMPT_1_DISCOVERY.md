---
prompt_id: DB-01
title: Database discovery
kind: prompt
pipeline: db
stage: 1
version: 2.0.0
shareable: true
requires: [snowflake]
depends_on: []
placeholders: [PRODUCT_NAME, KB_DB_DOCS, DB_ENV, SNOWFLAKE_DB, DB_SCHEMA, DB_SCHEMA_LIST,
               DB_RESTRICTED_VIEW_SCHEMAS, DB_CODE_COLUMN_FILTER, DB_KEY_COLUMN_FILTER,
               DB_PRIORITY_CODE_COLUMNS, DB_ACTIVE_FILTER_COLUMN, DB_ACTIVE_FILTER_VALUE,
               DB_KNOWN_JOINS, RUN_DATE]
outputs: ["{{KB_DB_DOCS}}/00_DB_DISCOVERY_REPORT.md"]
---

# DB-01: Database discovery

## Purpose

Record what is actually in the `{{DB_SCHEMA}}` schema of `{{SNOWFLAKE_DB}}` for {{PRODUCT_NAME}}:
tables, columns, row counts, keys, code values, joins, history columns and access policies.
Every later database document is built from this report, so it holds query results only. Say
what the data *is* here, and leave what it *means* to later stages.

## Before you start

1. Render this prompt with the team's values: `prompts.py render DB_PROMPT_1_DISCOVERY.md --env <env>`.
   If rendering fails, stop and fix the team profile. Don't fill values in by hand.
2. Check the connection and say who you are connected as:
   ```sql
   SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_DATABASE(), CURRENT_WAREHOUSE();
   ```
   Print `Database target: {{SNOWFLAKE_DB}}.{{DB_SCHEMA}} ({{DB_ENV}})` once.
3. Every query below is read-only. If your tool runs one statement per call, run them one at a time.
4. No earlier stage is needed. The domain context is not read here, so it can't colour the results.
5. Discovery reads base tables and runs value queries, so the connected role must be approved for
   that. Record the role in the header. If the role can see only masked views, run Q1 to Q8 on the
   views, mark Q12 and Q14 `[?]`, and say why.

## Steps

Run every query. Record each result under its query id. When a query fails:

1. Record the exact error under that query id, tagged `[?]`.
2. If the query has a fallback, run it.
3. Carry on with the next query. Don't stop the run.
4. List the failure in the Failed queries section and in Don't know.

If a query is slow on a large table, add `LIMIT 10000` and write "partial sample" next to the result.

### Q1: Objects per schema

```sql
SELECT TABLE_SCHEMA, TABLE_TYPE, COUNT(*) AS OBJ_COUNT
FROM {{SNOWFLAKE_DB}}.INFORMATION_SCHEMA.TABLES
WHERE TABLE_SCHEMA IN ({{DB_SCHEMA_LIST}})
GROUP BY TABLE_SCHEMA, TABLE_TYPE
ORDER BY TABLE_SCHEMA, TABLE_TYPE;
```

Also list any schema from the list that returned nothing. It may be misnamed in the team profile.

### Q2: Schema properties

```sql
SHOW SCHEMAS IN DATABASE {{SNOWFLAKE_DB}};
```

Keep the rows for the schemas in Q1. Record the name, comment, retention time and options. Schema
comments often describe masking or filtering rules, so copy them word for word.

### Q3: Table inventory

```sql
SELECT TABLE_NAME, ROW_COUNT, BYTES, CREATED, LAST_ALTERED, COMMENT
FROM {{SNOWFLAKE_DB}}.INFORMATION_SCHEMA.TABLES
WHERE TABLE_SCHEMA = '{{DB_SCHEMA}}' AND TABLE_TYPE = 'BASE TABLE'
ORDER BY TABLE_NAME;
```

`ROW_COUNT` here is Snowflake's metadata estimate, so label it that way. Copy comments word for word;
they often carry change-ticket references. Tables with `ROW_COUNT = 0` form the empty-table list.

### Q4: Columns per table and totals

```sql
SELECT TABLE_NAME, COUNT(*) AS COL_COUNT
FROM {{SNOWFLAKE_DB}}.INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = '{{DB_SCHEMA}}'
GROUP BY TABLE_NAME
ORDER BY COL_COUNT DESC;
```

The totals for the summary (tables, columns, estimated rows) come from Q3 and Q4. Don't query them again.

### Q5: Every column of every table

Lists every column, not only the first few. The semantic layer needs all of them to map business
words to columns.

```sql
SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, ORDINAL_POSITION, IS_NULLABLE, COLUMN_DEFAULT
FROM {{SNOWFLAKE_DB}}.INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = '{{DB_SCHEMA}}'
ORDER BY TABLE_NAME, ORDINAL_POSITION;
```

### Q6: Shared header columns

Many schemas start every table with the same audit or header columns. This query finds them. A
column counts as a header column if at least 90% of base tables have it at the same position.

```sql
WITH t AS (
    SELECT COUNT(*) AS N
    FROM {{SNOWFLAKE_DB}}.INFORMATION_SCHEMA.TABLES
    WHERE TABLE_SCHEMA = '{{DB_SCHEMA}}' AND TABLE_TYPE = 'BASE TABLE'
)
SELECT c.ORDINAL_POSITION, c.COLUMN_NAME, COUNT(*) AS TABLES_WITH_IT,
       ROUND(COUNT(*) * 100.0 / t.N, 1) AS PCT_OF_TABLES
FROM {{SNOWFLAKE_DB}}.INFORMATION_SCHEMA.COLUMNS c
JOIN {{SNOWFLAKE_DB}}.INFORMATION_SCHEMA.TABLES b
  ON b.TABLE_SCHEMA = c.TABLE_SCHEMA AND b.TABLE_NAME = c.TABLE_NAME AND b.TABLE_TYPE = 'BASE TABLE'
CROSS JOIN t
WHERE c.TABLE_SCHEMA = '{{DB_SCHEMA}}'
GROUP BY c.ORDINAL_POSITION, c.COLUMN_NAME, t.N
HAVING COUNT(*) >= 0.9 * t.N
ORDER BY c.ORDINAL_POSITION;
```

The header block is the run of positions from 1 with no gap. For each table, record the first
business column: the first column after the header block, taken from Q5. If no header block is
found, say so, and use position 1 as the first business column.

### Q7: Full column detail for wide tables

```sql
SELECT c.TABLE_NAME, c.COLUMN_NAME, c.DATA_TYPE, c.ORDINAL_POSITION, c.IS_NULLABLE,
       c.COLUMN_DEFAULT, c.CHARACTER_MAXIMUM_LENGTH, c.NUMERIC_PRECISION, c.NUMERIC_SCALE, c.COMMENT
FROM {{SNOWFLAKE_DB}}.INFORMATION_SCHEMA.COLUMNS c
JOIN (
    SELECT TABLE_NAME
    FROM {{SNOWFLAKE_DB}}.INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = '{{DB_SCHEMA}}'
    GROUP BY TABLE_NAME
    HAVING COUNT(*) > 20
) wide ON c.TABLE_NAME = wide.TABLE_NAME
WHERE c.TABLE_SCHEMA = '{{DB_SCHEMA}}'
ORDER BY c.TABLE_NAME, c.ORDINAL_POSITION;
```

### Q8: Declared keys

```sql
SELECT tc.TABLE_NAME, tc.CONSTRAINT_TYPE, tc.CONSTRAINT_NAME, kc.COLUMN_NAME, kc.ORDINAL_POSITION
FROM {{SNOWFLAKE_DB}}.INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
JOIN {{SNOWFLAKE_DB}}.INFORMATION_SCHEMA.KEY_COLUMN_USAGE kc
  ON tc.CONSTRAINT_NAME = kc.CONSTRAINT_NAME AND tc.TABLE_SCHEMA = kc.TABLE_SCHEMA
WHERE tc.TABLE_SCHEMA = '{{DB_SCHEMA}}'
ORDER BY tc.TABLE_NAME, tc.CONSTRAINT_TYPE, kc.ORDINAL_POSITION;
```

Snowflake stores primary, unique and foreign keys but doesn't enforce most of them. Record what is
declared, and say that it isn't enforced. If nothing comes back, record "no keys declared
[E: Q8]", and base joins on Q13 only.

### Q9: Restricted view schemas

Restricted view schemas for this team: `{{DB_RESTRICTED_VIEW_SCHEMAS}}`. If that is `NULL`, record
"none configured in the team profile" and skip to Q10.

```sql
SELECT TABLE_SCHEMA, TABLE_NAME
FROM {{SNOWFLAKE_DB}}.INFORMATION_SCHEMA.VIEWS
WHERE TABLE_SCHEMA IN ({{DB_RESTRICTED_VIEW_SCHEMAS}})
ORDER BY TABLE_NAME, TABLE_SCHEMA;
```

For each view, record whether a base table of the same name exists in Q3. A matching name is not
proof the view reads that table. Tag the pairing `[?]` unless the view definition (Q10 or
`GET_DDL`) shows it.

### Q10: Access policies

Row access policies and masking policies, across every schema in Q1:

```sql
SELECT POLICY_KIND, POLICY_NAME, POLICY_DB, POLICY_SCHEMA,
       REF_SCHEMA_NAME, REF_ENTITY_NAME, REF_ENTITY_DOMAIN, REF_COLUMN_NAME
FROM SNOWFLAKE.ACCOUNT_USAGE.POLICY_REFERENCES
WHERE REF_DATABASE_NAME = '{{SNOWFLAKE_DB}}'
  AND REF_SCHEMA_NAME IN ({{DB_SCHEMA_LIST}})
  AND POLICY_KIND IN ('ROW_ACCESS_POLICY', 'MASKING_POLICY')
ORDER BY POLICY_KIND, REF_SCHEMA_NAME, REF_ENTITY_NAME, REF_COLUMN_NAME;
```

`ACCOUNT_USAGE` can lag by up to two hours, so note that.

**Fallback** if `ACCOUNT_USAGE` is not granted: check the five largest tables from Q3, then one view
from each restricted view schema, one call per object:

```sql
SELECT *
FROM TABLE({{SNOWFLAKE_DB}}.INFORMATION_SCHEMA.POLICY_REFERENCES(
    REF_ENTITY_NAME => '{{SNOWFLAKE_DB}}.{{DB_SCHEMA}}.<TABLE_NAME>',
    REF_ENTITY_DOMAIN => 'TABLE'));
```

Use `REF_ENTITY_DOMAIN => 'VIEW'` for views. If both routes fail, record that a role with more
access is needed, and say who could run it `[?]`.

### Q11: Sequences, streams and tasks

```sql
SELECT SEQUENCE_NAME, DATA_TYPE, START_VALUE, INCREMENT
FROM {{SNOWFLAKE_DB}}.INFORMATION_SCHEMA.SEQUENCES
WHERE SEQUENCE_SCHEMA = '{{DB_SCHEMA}}';

SHOW STREAMS IN SCHEMA {{SNOWFLAKE_DB}}.{{DB_SCHEMA}};
SHOW TASKS IN SCHEMA {{SNOWFLAKE_DB}}.{{DB_SCHEMA}};
```

An empty result is a finding, so record it: "no sequences / streams / tasks [E: Q11]".

### Q12: Code values

**Step A: find the coded columns in non-empty tables.**

```sql
SELECT c.TABLE_NAME, c.COLUMN_NAME, c.DATA_TYPE, t.ROW_COUNT
FROM {{SNOWFLAKE_DB}}.INFORMATION_SCHEMA.COLUMNS c
JOIN {{SNOWFLAKE_DB}}.INFORMATION_SCHEMA.TABLES t
  ON t.TABLE_SCHEMA = c.TABLE_SCHEMA AND t.TABLE_NAME = c.TABLE_NAME
WHERE c.TABLE_SCHEMA = '{{DB_SCHEMA}}'
  AND t.TABLE_TYPE = 'BASE TABLE' AND t.ROW_COUNT > 0
  AND {{DB_CODE_COLUMN_FILTER}}
  AND c.COLUMN_NAME NOT IN (<header columns from Q6>)
ORDER BY t.ROW_COUNT DESC, c.TABLE_NAME, c.COLUMN_NAME;
```

Replace `<header columns from Q6>` with the quoted header column names. If Q6 found none, drop that line.
Also leave out every column that Q10 shows has a masking policy. Its values are never read.

**Step A2: find coded columns that the name filter misses.** Some code columns have names the
filter doesn't match. For each non-empty base table, count the distinct values of every column that
is not in Step A, not a header column and not masked. One query per table:

```sql
SELECT APPROX_COUNT_DISTINCT(<COLUMN_A>) AS COL_A, APPROX_COUNT_DISTINCT(<COLUMN_B>) AS COL_B
FROM {{SNOWFLAKE_DB}}.{{DB_SCHEMA}}.<TABLE_NAME>;
```

A column with 50 or fewer distinct values is a code candidate. Record the candidates as
"name-missed code candidates [E: Q12A2]". Their values are read in Step B like the others.

**Step B: list the values.** Do the team's priority columns first:

{{DB_PRIORITY_CODE_COLUMNS}}

Then do the rest from Step A, largest tables first.

```sql
SELECT '<TABLE_NAME>' AS TABLE_NAME, '<COLUMN_NAME>' AS COLUMN_NAME,
       <COLUMN_NAME> AS VALUE, COUNT(*) AS CNT
FROM {{SNOWFLAKE_DB}}.{{DB_SCHEMA}}.<TABLE_NAME>
WHERE <COLUMN_NAME> IS NOT NULL
GROUP BY <COLUMN_NAME>
ORDER BY CNT DESC
LIMIT 25;
```

For each column, record the number of distinct values and the values. If it has more than 25,
show the top 25 and say so. A priority column that doesn't exist, or sits in an empty table, is
recorded as "not observable" `[E: Q3]`. Don't leave it out.

Only record code values. If a column holds people's names, identifiers or free text, record its
cardinality and skip its values.

### Q13: Joins

**Step A: candidate keys.** Key-like columns that appear in more than one table, leaving out the
header columns from Q6. Header columns such as load or run ids sit in every table, so they aren't joins.

```sql
SELECT COLUMN_NAME, COUNT(DISTINCT TABLE_NAME) AS TABLES_WITH_IT,
       ARRAY_SLICE(ARRAY_AGG(DISTINCT TABLE_NAME) WITHIN GROUP (ORDER BY TABLE_NAME), 0, 20) AS FIRST_TABLES
FROM {{SNOWFLAKE_DB}}.INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = '{{DB_SCHEMA}}' AND {{DB_KEY_COLUMN_FILTER}}
  AND COLUMN_NAME NOT IN (<header columns from Q6>)
GROUP BY COLUMN_NAME
HAVING COUNT(DISTINCT TABLE_NAME) > 1
ORDER BY TABLES_WITH_IT DESC;
```

**Step B: pick the joins to check.** Start with the joins the team already knows about:

{{DB_KNOWN_JOINS}}

Leave out columns that record who created or changed a row (created-by and updated-by user ids).
They point at people, not parent rows. List them once as audit columns.

Test every candidate from Step A, with no limit on the number. For each key column, the parent is a
table where the column is a declared key (Q8) or the first business column (Q6). Every other table
with that column is a child. Include self-joins, such as a parent-id column pointing back to its own table.

**Step B2: joins with different names.** Some joins use different column names. Take the key-like
columns that sit in the most tables, and test value overlap between each pair from different tables.
Use distinct values, not names:

```sql
SELECT '<LEFT_COL>' AS LEFT_COL, '<RIGHT_COL>' AS RIGHT_COL,
       COUNT(DISTINCT a.V) AS LEFT_KEYS,
       COUNT(DISTINCT CASE WHEN b.V IS NOT NULL THEN a.V END) AS MATCHED_KEYS
FROM (SELECT DISTINCT <LEFT_COL> AS V FROM {{SNOWFLAKE_DB}}.{{DB_SCHEMA}}.<LEFT_TABLE>
      WHERE <LEFT_COL> IS NOT NULL) a
LEFT JOIN (SELECT DISTINCT <RIGHT_COL> AS V FROM {{SNOWFLAKE_DB}}.{{DB_SCHEMA}}.<RIGHT_TABLE>) b
  ON a.V = b.V;
```

A pair with a match rate of 90% or more is a candidate join. Run Step C on it. Record every
candidate that fails, with its rate, as rejected.

**Step C: count orphans for each join.** Current-row filter for tables that keep history:
`{{DB_ACTIVE_FILTER_COLUMN}} = '{{DB_ACTIVE_FILTER_VALUE}}'`. Apply it to each side that has the
column. If it shows `(not set)`, leave it out.

```sql
SELECT '<CHILD> -> <PARENT>' AS JOIN_PATH, '<KEY>' AS JOIN_KEY,
       COUNT(*) AS CHILD_ROWS,
       COUNT(DISTINCT c.<KEY>) AS CHILD_KEYS,
       SUM(CASE WHEN p.<KEY> IS NULL THEN 1 ELSE 0 END) AS ORPHAN_ROWS,
       ROUND(SUM(CASE WHEN p.<KEY> IS NULL THEN 1 ELSE 0 END) * 100.0 / NULLIF(COUNT(*), 0), 2) AS ORPHAN_PCT
FROM {{SNOWFLAKE_DB}}.{{DB_SCHEMA}}.<CHILD> c
LEFT JOIN {{SNOWFLAKE_DB}}.{{DB_SCHEMA}}.<PARENT> p ON c.<KEY> = p.<KEY>
WHERE c.<KEY> IS NOT NULL;
```

Record each join's path, key, row counts and orphan percentage.
- 0% orphans: record the join as validated `[E: Q13]`.
- Over 0%: record the rate `[E: Q13]`, and add an open question when it's above 5%.
- A join that exists only because two tables share a column name is not validated until Step C passes.

### Q14: History columns

If the current-row filter is set (`{{DB_ACTIVE_FILTER_COLUMN}}`), count current and historical rows
in every non-empty table that has that column:

```sql
SELECT '<TABLE_NAME>' AS TABLE_NAME, COUNT(*) AS TOTAL_ROWS,
       SUM(CASE WHEN {{DB_ACTIVE_FILTER_COLUMN}} = '{{DB_ACTIVE_FILTER_VALUE}}' THEN 1 ELSE 0 END) AS CURRENT_ROWS,
       SUM(CASE WHEN {{DB_ACTIVE_FILTER_COLUMN}} <> '{{DB_ACTIVE_FILTER_VALUE}}' THEN 1 ELSE 0 END) AS HISTORY_ROWS
FROM {{SNOWFLAKE_DB}}.{{DB_SCHEMA}}.<TABLE_NAME>;
```

Tables where every row is current carry the column but may never keep history. Note them.

If the filter is `(not set)`, list the date and timestamp columns that appear in at least half the
tables. Record them as possible history columns `[?]`, and ask the team which one marks the current
row.

```sql
SELECT COLUMN_NAME, DATA_TYPE, COUNT(DISTINCT TABLE_NAME) AS TABLES_WITH_IT
FROM {{SNOWFLAKE_DB}}.INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = '{{DB_SCHEMA}}' AND (DATA_TYPE LIKE 'TIMESTAMP%' OR DATA_TYPE = 'DATE')
GROUP BY COLUMN_NAME, DATA_TYPE
ORDER BY TABLES_WITH_IT DESC;
```

## Output

Write `{{KB_DB_DOCS}}/00_DB_DISCOVERY_REPORT.md`, starting with:

```yaml
---
document: DB discovery report
product: {{PRODUCT_NAME}}
source_db: {{SNOWFLAKE_DB}}
schema: {{DB_SCHEMA}}
environment: {{DB_ENV}}
generated_date: {{RUN_DATE}}
connected_as: <user and role from Before you start>
prompt_id: DB-01
prompt_version: 2.0.0
---
```

Then these sections, in this order. Every section has results, or says why it has none.

1. Summary: tables, columns, estimated rows, empty tables (Q3, Q4)
2. Schemas and object counts, with comments and retention (Q1, Q2)
3. Table inventory (Q3, Q4)
4. Empty tables (Q3)
5. Header columns and first business column per table (Q5, Q6)
6. Wide-table column detail (Q7)
7. Declared keys (Q8)
8. Restricted views and their likely base tables (Q9)
9. Access policies (Q10)
10. Sequences, streams and tasks (Q11)
11. Code values (Q12)
12. Joins and orphan rates (Q13)
13. History columns (Q14)
14. Failed queries: query id, error, fallback tried, which later stages lose data
15. Open questions
16. Assumptions
17. Don't know

## Evidence rules

- Every fact is tagged `[E: Q<n>]` with the query it came from, such as `[E: Q3]`.
- Discovery makes no assumptions, so `[A]` should not appear. If you had to assume something to
  run a query at all, tag it `[A]` and list it under Assumptions.
- Anything a query couldn't show, including failed queries, is tagged `[?]` and listed under Don't know.
- Record results as returned. No explanations of business meaning, and no guesses at what a code stands for.

## Self-check

- [ ] The header shows the database, schema, environment, date and connected role.
- [ ] Every query Q1 to Q14 has a result, an explicit "no results", or a failure note.
- [ ] Every fact has exactly one tag, and every `[?]` is also in Don't know.
- [ ] Every priority code column is listed, or marked not observable.
- [ ] Every known join and every added join has an orphan rate.
- [ ] No people's names, identifiers or free-text values were copied from data rows.
- [ ] Failed queries are listed with the later stages they affect.

If any box is unticked, the report is incomplete. Don't start the next stage.

## Open questions, assumptions and unknowns

End the report with three lists:

- **Open questions:** each one names who can answer (DBA, data owner, platform team) and why it
  matters. Examples: joins over 5% orphans, a schema from the profile that doesn't exist, a
  priority column that's missing.
- **Assumptions:** each `[A]` from the report, with what changes if it's wrong. Usually empty.
- **Don't know:** each `[?]` from the report, including failed queries and missing access, with
  who could answer.
