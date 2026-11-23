---
prompt_id: ETL-13
title: ETL table input/output contract (YAML)
kind: prompt
pipeline: etl
stage: 13
version: 2.0.0
shareable: true
requires: []
depends_on: [ETL-10, ETL-12]
placeholders: [PRODUCT_NAME, KB_ETL_DOCS, KB_DB_DOCS, MODULE_NAME, MODULE_SOURCE, SNOWFLAKE_DB, DB_SCHEMA, RUN_DATE]
outputs: ["{{KB_ETL_DOCS}}/{{MODULE_NAME}}/13_ETL_TABLE_IO_CONTRACT.yaml"]
---

# ETL-13: ETL table input/output contract (YAML)

## Purpose

For every script in `{{MODULE_NAME}}`, record exactly which tables and columns it reads and
writes, with what filters, operations and triggers. Add a reverse index from each table to the
scripts that touch it. An AI agent uses this to route a change: which scripts must change when a
table does, and which tables a script change can affect.

## Before you start

1. Render with the module: `prompts.py render ETL_PROMPT_13_TABLE_IO_CONTRACT.md --set MODULE_NAME=<name> --set MODULE_SOURCE=<folder>`.
2. Read `10_ETL_MODULE_IO_SUMMARY.md` and `12_ETL_SQL_PATTERNS.yaml` in
   `{{KB_ETL_DOCS}}/{{MODULE_NAME}}/`, and the schema catalog in `{{KB_DB_DOCS}}`.
3. Read every SQL file and script under `{{MODULE_SOURCE}}`.

## Steps

For each SQL file or script:

1. Record its process, its trigger (with a source, or `[?]`) and the pattern ID it follows.
2. **Source tables:** each schema and table, the operation (read), the filters and the join keys.
3. **Target tables:** each schema and table, and the operation (insert, merge, update or delete).
   Record whether history is kept, the columns written (required and optional), and whether the
   header columns are included.
4. Any conditions that limit the rows, such as a code value or a status.
5. Its dependencies: which scripts must run first, and what it waits on.
6. How it handles failure.
7. Its source and confidence.

Then build the reverse index: for each table, the scripts that read it and the scripts that
write it. Check each table name against the schema catalog. List any tables not in the catalog.

## Output

Write `{{KB_ETL_DOCS}}/{{MODULE_NAME}}/13_ETL_TABLE_IO_CONTRACT.yaml`:

```yaml
metadata:
  product: {{PRODUCT_NAME}}
  module: {{MODULE_NAME}}
  database: {{SNOWFLAKE_DB}}
  schema: {{DB_SCHEMA}}
  generated_date: {{RUN_DATE}}
  prompt_id: ETL-13
  prompt_version: 2.0.0
scripts:
  - file: <path>
    process: <process>
    trigger: <trigger or null>
    pattern: <PAT id or null>
    source_tables: [{schema: <s>, table: <t>, operation: READ, filter: <SQL or null>, join_keys: [<col>]}]
    target_tables:
      - schema: <s>
        table: <t>
        operation: <INSERT | MERGE | UPDATE | DELETE>
        keeps_history: <bool>
        columns_written: {mandatory: [<col>], optional: [<col>]}
        header_columns: <bool>
    conditions: [<SQL>]
    dependencies: [<file or job>]
    failure_handling: <text or null>
    source: [<"path:line">]
    confidence: <1.0 | 0.8 | 0.6>
reverse_lookup:
  <TABLE>: {read_by: [<file>], written_by: [<file>]}
not_in_catalog: [<table>]
open_questions: []
assumptions: []
dont_know: []
```

## Evidence rules

- Every table and column comes from a SQL statement, cited as `[E: <file>:<line>]`.
- A trigger or dependency not in code is `null`, and goes in `dont_know` as `[?]`.
- Anything taken as true without a source is `[A]` and goes in `assumptions`.
- The reverse index is built from the `scripts` list only.

## Self-check

- [ ] Every SQL file and script has an entry.
- [ ] Every target table lists its columns.
- [ ] Every table in `scripts` appears in `reverse_lookup`.
- [ ] Tables are checked against the catalog.
- [ ] The file parses as YAML.
- [ ] Every `[A]` and `[?]` is in its list.

## Open questions, assumptions and unknowns

Fill the three lists at the end of the YAML:

- **Open questions:** each with an owner by role (ETL developer, database engineer).
- **Assumptions:** each `[A]`, and what changes if it's wrong.
- **Don't know:** each `[?]`, with who could answer.
