---
prompt_id: DB-09B
title: Database data contracts
kind: prompt
pipeline: db
stage: 9B
version: 2.0.0
shareable: true
requires: []
depends_on: [DB-01, DB-09]
placeholders: [PRODUCT_NAME, KB_DB_DOCS, DOMAIN_CONTEXT, APP_SOURCE_DIRS, SNOWFLAKE_DB, DB_SCHEMA,
               DB_ENV, DB_ACTIVE_FILTER_COLUMN, DB_ACTIVE_FILTER_VALUE, RUN_DATE]
outputs: ["{{KB_DB_DOCS}}/9B_DB_DATA_CONTRACTS.yaml"]
---

# DB-09B: Database data contracts

## Purpose

For the {{PRODUCT_NAME}} columns that matter, record the full chain of types: the database type,
how the API carries it, and how the UI shows and checks it. Then a story that says "add a field"
or "widen a column" can list every layer to change, and a reviewer can catch a UI length that
no longer matches the column. The output is YAML for tools. A developer must review it before
anything relies on it.

## Before you start

1. Render this prompt: `prompts.py render DB_PROMPT_9B_DATA_CONTRACTS.md --env <env>`.
2. Read these.
   - Required: `{{KB_DB_DOCS}}/00_DB_DISCOVERY_REPORT.md` (column detail Q7, header columns Q6, code values Q12).
   - Required: `{{KB_DB_DOCS}}/09_DB_SEMANTIC_LAYER.yaml` (tables and value dictionaries).
   - Required: the domain context at `{{DOMAIN_CONTEXT}}`, for business field names and screen rules.
3. The application source is in these folders. Read the code directly. Don't guess from names.

{{APP_SOURCE_DIRS}}

4. If a folder doesn't exist or you can't read it, record its API or UI fields as `[?]` and carry on.

## Steps

1. **Standard patterns.** Document once: the shared header columns (Q6), and the history columns
   with the current-row value `{{DB_ACTIVE_FILTER_COLUMN}} = '{{DB_ACTIVE_FILTER_VALUE}}'`. For each,
   give the type, nullability and default from Q7, and say whether the API or UI ever sets it.
   Search the source to find out.
2. **Choose the columns.** Contract a column if any of these is true:
   - it's a table's business key;
   - a screen sets it;
   - it's a code column with values in Q12;
   - it's a sentinel date;
   - it's an amount, rate or percent;
   - its layers disagree.

   Leave out the header columns, columns on empty tables, and columns nothing reads.
3. **Database side.** From Q7 only: type with length or precision, nullability, default and position.
4. **API side.** Find the model, serializer or query that reads the column. Record the file,
   field name, type, max length and allowed choices as written in code, with `[E: <file>:<line>]`.
   If no code touches it, say so.
5. **UI side.** Find the form or grid field. Record the file, label, input type, required flag,
   max length and options, with `[E: <file>:<line>]`.
6. **Rules.** Record validation rules from code, the domain context or answered validation-log
   items only. A rule described only in a manual you can't see is `[?]`.
7. **Gaps.** Flag each mismatch between layers, such as:
   - the column is nullable, but the UI requires it;
   - the API max length is less than the column length;
   - the API choices are missing a Q12 value, or have extra ones.

   Each mismatch is an open question for a developer.

Use this table as a check, not a source:

| Database type | Usual API type | Usual UI input |
|---|---|---|
| VARCHAR(n) | string, max n | text, max n |
| NUMBER(p,0) | integer | number, no decimals |
| NUMBER(p,s), s > 0 | decimal | number, step 10^-s |
| DATE | date | date picker |
| TIMESTAMP | datetime | read-only display |
| one-character indicator | boolean | checkbox |
| code column | string with choices | single select |

## Output

Write `{{KB_DB_DOCS}}/9B_DB_DATA_CONTRACTS.yaml`. Start with comment lines for the product, source
(`{{SNOWFLAKE_DB}}.{{DB_SCHEMA}}`), environment ({{DB_ENV}}), the date ({{RUN_DATE}}),
`prompt_id: DB-09B`, prompt version 2.0.0 and `review: developer sign-off required`. Then these
sections: `metadata`, `standard_patterns`, `tables` (each with `contracts`), `gaps`,
`open_questions`, `assumptions`, `unknowns`.

Each contract entry has these fields, with `null` where a layer doesn't use the column:

```yaml
- column: <name>
  db: {type: <from Q7>, nullable: <bool>, default: <value or null>, position: <n>}
  api: {file: <path or null>, field: <name>, type: <type>, max_length: <n>, choices: [<...>]}
  ui: {file: <path or null>, label: <text>, input: <type>, required: <bool>, max_length: <n>}
  rules: [<rule>]
  source: [<"DB-01 Q7">, <"path:line">]
  confidence: <1.0 | 0.8 | 0.6 | 0.3>
```

## Evidence rules

- Database types come from Q7 only (`confidence: 1.0`). Never write a type Q7 doesn't show.
- API and UI facts need a file and line (`confidence: 1.0`), or a KB document section (`0.8`).
- A value taken from a naming pattern is `0.6`. It is also listed under `assumptions`.
- Anything not found is `0.3` with `null` values. It is also listed under `unknowns`.

## Self-check

- [ ] The file parses as YAML.
- [ ] Every contracted column has a database type from Q7.
- [ ] Every API or UI fact has a file and line, or is `null` and listed as unknown.
- [ ] Every code column's API choices were compared with Q12.
- [ ] Every layer mismatch is in `gaps` and in `open_questions`.
- [ ] No data values, credentials or people were copied.

## Open questions, assumptions and unknowns

End the file with three lists:

- `open_questions`: each gap, with the developer role who can answer.
- `assumptions`: each 0.6 item, and what changes if it's wrong.
- `unknowns`: each 0.3 item, and who could answer.
