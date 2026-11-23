---
prompt_id: DB-17
title: Database column catalog and profile
kind: prompt
pipeline: db
stage: 2.5
version: 1.0.0
shareable: true
requires: [snowflake]
depends_on: [DB-01, DB-22]
placeholders: [PRODUCT_NAME, KB_DB_DOCS, SNOWFLAKE_DB, DB_SCHEMA, DB_ENV, DB_ACTIVE_FILTER_COLUMN, DB_ACTIVE_FILTER_VALUE, RUN_DATE]
outputs: ["{{KB_DB_DOCS}}/17_DB_COLUMN_PROFILE.json"]
---

# DB-17: Database column catalog and profile

## Purpose

Profile every column of {{PRODUCT_NAME}} `{{DB_SCHEMA}}`, not only the code columns. The semantic
layer needs to know what each column holds before it can map a business word to it: how often it is
empty, how many distinct values it has, its range, and its length. Amount, date and status meaning
is easier to confirm from a profile than from a name. The output is one JSON file. The
semantic layer reads it.

## Before you start

1. Render this prompt: `prompts.py render DB_PROMPT_17_COLUMN_PROFILE.md --env <env>`.
2. Read `{{KB_DB_DOCS}}/22_DB_SENSITIVITY.yaml`. Every column with `skip_value_sampling: true` gets
   the type and the null count only. No distinct count, value, min, max or length is read for it.
   Stop if the file is missing.
3. Read `{{KB_DB_DOCS}}/00_DB_DISCOVERY_REPORT.md`, Q5 for the column list.
4. Read-only queries only. Run one statement per call if the tool needs it.

## Steps

Batch the work by table. One query per table covers all of its columns. Don't write one query per column.

### P1: Row count and load date

For each base table with rows, read the row count from DB-01 Q3. Don't count again.

### P2: Profile each table (non-sensitive columns)

For each table, build one query that returns one row per non-sensitive column. A column marked
`skip_value_sampling: true` in DB-22 gets only the `NULL_COUNT` line below, with every other
measure left out:

```sql
SELECT '<TABLE>' AS TABLE_NAME, '<COLUMN>' AS COLUMN_NAME,
       COUNT(*) AS ROWS_SEEN,
       COUNT(<COLUMN>) AS NON_NULL,
       APPROX_COUNT_DISTINCT(<COLUMN>) AS DISTINCT_APPROX,
       MIN(<COLUMN>) AS MIN_VALUE,
       MAX(<COLUMN>) AS MAX_VALUE,
       MAX(LENGTH(TO_VARCHAR(<COLUMN>))) AS MAX_LEN
FROM {{SNOWFLAKE_DB}}.{{DB_SCHEMA}}.<TABLE>
<UNION ALL one block per column>;
```

Use `MIN` and `MAX` only for numbers, dates and timestamps. For text columns, record `MAX_LEN` and skip
`MIN_VALUE` and `MAX_VALUE` so no free-text value is copied.

For a wide table, split the query into batches of at most fifty columns per query.

### P3: Top values for low-cardinality columns

For each column with `DISTINCT_APPROX` of 50 or fewer, run:

```sql
SELECT <COLUMN> AS VALUE, COUNT(*) AS CNT
FROM {{SNOWFLAKE_DB}}.{{DB_SCHEMA}}.<TABLE>
GROUP BY <COLUMN>
ORDER BY CNT DESC
LIMIT 25;
```

Don't run this for a column marked sensitive in DB-22. Record "values skipped: sensitive [E: DB-22]".

### P4: Sample rows

Don't sample rows. A row sample can expose personal data, and the profile above answers the
question the semantic layer needs.

### P5: Time coverage

For every date or timestamp column with a non-null count above zero, record `MIN_VALUE` and `MAX_VALUE`.
These show how far back the data goes and whether the table is still loading.

For tables with history (DB-01 Q14), run P2 to P5 on the current rows and the history rows separately,
using `{{DB_ACTIVE_FILTER_COLUMN}} = '{{DB_ACTIVE_FILTER_VALUE}}'`.

## Output

Write `{{KB_DB_DOCS}}/17_DB_COLUMN_PROFILE.json`:

```json
{
  "metadata": {
    "product": "{{PRODUCT_NAME}}",
    "source": "{{SNOWFLAKE_DB}}.{{DB_SCHEMA}}",
    "environment": "{{DB_ENV}}",
    "generated_date": "{{RUN_DATE}}",
    "prompt_id": "DB-17",
    "prompt_version": "1.0.0"
  },
  "columns": [
    {
      "table": "<TABLE>",
      "column": "<COLUMN>",
      "data_type": "<from DB-01 Q5>",
      "rows_seen": 0,
      "null_pct": 0.0,
      "distinct_approx": 0,
      "min": null,
      "max": null,
      "max_len": 0,
      "top_values": [{"value": "<v>", "count": 0}],
      "values_skipped_reason": null,
      "sensitivity": "<from DB-22>",
      "source": "DB-17 P2",
      "confidence": 1.0
    }
  ],
  "open_questions": [],
  "assumptions": [],
  "unknowns": []
}
```

Every column in DB-01 Q5 has one entry. `null_pct` is computed from `NON_NULL` and `ROWS_SEEN`.

## Evidence rules

- Profile values come from queries (`confidence: 1.0`, source `DB-17 P2` or `P3`).
- A column that failed to profile gets `confidence: 0.3` and an unknown with the error.
- Min and max values for text are never recorded.
- No sample rows, no personal data and no free-text values are written.

## Self-check

- [ ] Every Q5 column has one entry.
- [ ] No sensitive column has `top_values` or `min`/`max` for text.
- [ ] No sample rows were read.
- [ ] `null_pct` matches `NON_NULL` and `ROWS_SEEN` for each column.
- [ ] Failed profiles are in `unknowns`.

## Open questions, assumptions and unknowns

- `open_questions`: columns whose profile contradicts their name or comment, with the data owner.
- `assumptions`: any value taken from a name, and what changes if it's wrong.
- `unknowns`: failed or skipped columns, with who could answer.
