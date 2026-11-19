---
prompt_id: DB-SD
title: Database staleness check
kind: prompt
pipeline: db
stage: maintenance
version: 2.0.0
shareable: true
requires: [snowflake]
depends_on: [DB-01]
placeholders: [PRODUCT_NAME, KB_DB_DOCS, SNOWFLAKE_DB, DB_SCHEMA, DB_SCHEMA_LIST, DB_ENV, RUN_DATE]
outputs: ["{{KB_DB_DOCS}}/STALENESS_DELTA_REPORT.md"]
---

# DB-SD: Database staleness check

## Purpose

Find out, cheaply, whether the {{PRODUCT_NAME}} database documents are still true. Compare the
schema today with the stored discovery report, list what changed, and say which documents need
to be regenerated. Run it weekly or at the start of a sprint. It changes nothing and doesn't
rerun the pipeline.

## Before you start

1. Render this prompt: `prompts.py render DB_PROMPT_STALENESS_DETECTION.md --env <env>`.
2. Read `{{KB_DB_DOCS}}/00_DB_DISCOVERY_REPORT.md`. From it, take:
   - the baseline date (its `generated_date`);
   - the table and column totals (Q3, Q4);
   - the empty-table list;
   - the policy counts (Q10).

   If the report is missing, stop: there's no baseline.
3. You need read-only access to `{{SNOWFLAKE_DB}}` ({{DB_ENV}}). Run SELECT statements only.

## Steps

Replace `<BASELINE_DATE>` with the report's `generated_date`. Run each query. If one fails, record
the error and carry on.

```sql
-- SD-Q1: table count now
SELECT COUNT(*) AS TABLE_COUNT
FROM {{SNOWFLAKE_DB}}.INFORMATION_SCHEMA.TABLES
WHERE TABLE_SCHEMA = '{{DB_SCHEMA}}' AND TABLE_TYPE = 'BASE TABLE';

-- SD-Q2: every table now, to compare names with the report (new and dropped)
SELECT TABLE_NAME, CREATED, LAST_ALTERED, ROW_COUNT
FROM {{SNOWFLAKE_DB}}.INFORMATION_SCHEMA.TABLES
WHERE TABLE_SCHEMA = '{{DB_SCHEMA}}' AND TABLE_TYPE = 'BASE TABLE'
ORDER BY TABLE_NAME;

-- SD-Q3: column count now
SELECT COUNT(*) AS COLUMN_COUNT
FROM {{SNOWFLAKE_DB}}.INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = '{{DB_SCHEMA}}';

-- SD-Q4: column count per table, for tables altered since the baseline
SELECT c.TABLE_NAME, COUNT(*) AS COLUMN_COUNT, MAX(t.LAST_ALTERED) AS LAST_ALTERED
FROM {{SNOWFLAKE_DB}}.INFORMATION_SCHEMA.COLUMNS c
JOIN {{SNOWFLAKE_DB}}.INFORMATION_SCHEMA.TABLES t
  ON t.TABLE_SCHEMA = c.TABLE_SCHEMA AND t.TABLE_NAME = c.TABLE_NAME
WHERE c.TABLE_SCHEMA = '{{DB_SCHEMA}}'
  AND t.LAST_ALTERED > '<BASELINE_DATE>'::TIMESTAMP
GROUP BY c.TABLE_NAME
ORDER BY c.TABLE_NAME;

-- SD-Q5: row counts now. Compare with the report's empty-table list.
SELECT TABLE_NAME, ROW_COUNT
FROM {{SNOWFLAKE_DB}}.INFORMATION_SCHEMA.TABLES
WHERE TABLE_SCHEMA = '{{DB_SCHEMA}}' AND TABLE_TYPE = 'BASE TABLE'
ORDER BY TABLE_NAME;

-- SD-Q6: policy references now, scoped exactly like DB-01 Q10 so the counts compare.
SELECT POLICY_KIND, COUNT(*) AS REFERENCES
FROM SNOWFLAKE.ACCOUNT_USAGE.POLICY_REFERENCES
WHERE REF_DATABASE_NAME = '{{SNOWFLAKE_DB}}'
  AND REF_SCHEMA_NAME IN ({{DB_SCHEMA_LIST}})
  AND POLICY_KIND IN ('ROW_ACCESS_POLICY', 'MASKING_POLICY')
GROUP BY POLICY_KIND;
```

Then:

1. **Deltas.** Compare each result with the baseline: new tables, dropped tables, changed column
   counts, empty tables that now have rows, tables that became empty, and policy count changes.
   Note that account-usage views lag by up to a few hours, and row counts are metadata estimates.
2. **Mark stale documents.** Apply this table:

| Change | Regenerate | From stage |
|---|---|---|
| New or dropped table | all DB documents | DB-01 |
| New or changed column on a table in 9B | 02, 07, 09, 9B, 10, 16 | DB-03 |
| New or changed column elsewhere | 02, 07 | DB-03 |
| New code value (found by a rerun of DB-01 Q12) | 05, 09, 13 | DB-05 |
| Empty table now has rows | 02, 09 | DB-03 |
| Policy count change | 06, 12 | DB-06 |

3. **Recommend actions** in order: the lowest stage that must rerun first, then the rest.

## Output

Write `{{KB_DB_DOCS}}/STALENESS_DELTA_REPORT.md`, starting with:

```yaml
---
document: DB staleness report
product: {{PRODUCT_NAME}}
source_db: {{SNOWFLAKE_DB}}
schema: {{DB_SCHEMA}}
environment: {{DB_ENV}}
baseline_date: <from the discovery report>
check_date: {{RUN_DATE}}
status: <current | drift found>
prompt_id: DB-SD
prompt_version: 2.0.0
---
```

Then these sections:

1. A summary table: tables, columns, empty tables and policy references, each with baseline, now,
   delta and status.
2. New tables, dropped tables, changed tables, and tables that now have rows or are now empty.
3. Document staleness: each DB document, whether it's stale, why, and the stage to rerun.
4. Recommended actions.
5. Failed queries.
6. Open questions, Assumptions, Don't know.

## Evidence rules

- Every "now" value is tagged with its query, `[E: SD-Q3]`. Every baseline value is tagged with the
  report, `[E: 00_DB_DISCOVERY_REPORT Q4]`.
- A document is only marked stale because of a delta in this run. Never mark one stale on a hunch.
- Anything taken as true without a source is `[A]` and goes on the Assumptions list.
- Anything not known is `[?]` and goes on the Don't know list.

## Self-check

- [ ] All six queries were run, or their failure is recorded.
- [ ] The baseline values match the discovery report exactly.
- [ ] Every delta equals now minus baseline.
- [ ] Every DB document has a staleness row.
- [ ] Nothing but SELECT was run.

## Open questions, assumptions and unknowns

End with three lists:

- **Open questions:** changes that need an explanation (for example, a dropped table), each with an owner.
- **Assumptions:** each `[A]`, and what changes if it's wrong.
- **Don't know:** each `[?]`, with who could answer.
