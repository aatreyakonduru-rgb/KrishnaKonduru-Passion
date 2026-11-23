---
prompt_id: DB-05
title: Database supporting documents
kind: prompt
pipeline: db
stage: 5
version: 2.0.0
shareable: true
requires: [snowflake]
depends_on: [DB-01, DB-03]
placeholders: [PRODUCT_NAME, KB_DB_DOCS, DOMAIN_CONTEXT, SNOWFLAKE_DB, DB_SCHEMA, DB_ENV, RUN_DATE]
outputs: ["{{KB_DB_DOCS}}/04_DB_CHANGE_IMPACT_MATRIX.md", "{{KB_DB_DOCS}}/05_DB_GLOSSARY.md",
          "{{KB_DB_DOCS}}/07_DB_SCHEMA_CATALOG.md"]
---

# DB-05: Database supporting documents

## Purpose

Produce three reference documents for the {{PRODUCT_NAME}} database: a matrix of which tables each
business capability uses, a glossary of the domain terms, and a column-level schema catalog.
Developers and analysts use them to size a change, look up a term or find a column. This stage
can run at the same time as DB-04 and DB-06.

## Before you start

1. Render this prompt: `prompts.py render DB_PROMPT_5_SUPPORTING.md --env <env>`.
2. Read `{{KB_DB_DOCS}}/00_DB_DISCOVERY_REPORT.md`, `{{KB_DB_DOCS}}/02_DB_TECHNICAL_REQUIREMENTS.md`
   and the domain context at `{{DOMAIN_CONTEXT}}`. If any is missing, stop and ask.
3. Only step 3c may run a query, and only if the wide-table detail is missing from the discovery report.

## Steps

### 1. Change impact matrix

1. Take the business capabilities from the domain context. Add a last row, "Cross-cutting", for
   tables that support every capability (audit, sync, users, job control) and for tables no
   capability claims.
2. Assign each table in `{{DB_SCHEMA}}` (Q3) to one or more capabilities. Base each assignment on
   something you can point to:
   - the domain context names the table or its prefix;
   - DB-02 lists the table under that business area;
   - the table name carries a prefix or token the domain context maps to the capability.
3. A table with no match goes under Cross-cutting, tagged `[?]`, and on the Open questions list.
   Never leave a table out.
4. Mark association only. Don't mark read or write. Schema metadata can't show direction.

### 2. Glossary

1. List every business term the domain context defines, plus every abbreviation that appears in
   three or more table or column names (Q3, Q4) and that the domain context also defines.
2. For each term, give a plain-English definition from the domain context and the tables or
   columns where it appears.
3. Summarise definitions instead of copying them. An abbreviation the domain context doesn't
   define goes under a separate "Not yet defined" list, tagged `[?]`.

### 3. Schema catalog

1. A summary line for every table: estimated rows, column count and first business column
   (Q3, Q4, Q5).
2. The shared header columns once, with positions and defaults (Q6), instead of repeating them per table.
3. The full column list for every table with more than 20 columns (Q7): name, type, position,
   nullable and default. If Q7 is missing or incomplete, run it now:
   ```sql
   SELECT c.TABLE_NAME, c.COLUMN_NAME, c.DATA_TYPE, c.ORDINAL_POSITION, c.IS_NULLABLE,
          c.COLUMN_DEFAULT, c.CHARACTER_MAXIMUM_LENGTH, c.NUMERIC_PRECISION
   FROM {{SNOWFLAKE_DB}}.INFORMATION_SCHEMA.COLUMNS c
   JOIN (SELECT TABLE_NAME FROM {{SNOWFLAKE_DB}}.INFORMATION_SCHEMA.COLUMNS
         WHERE TABLE_SCHEMA = '{{DB_SCHEMA}}' GROUP BY TABLE_NAME HAVING COUNT(*) > 20) w
     ON c.TABLE_NAME = w.TABLE_NAME
   WHERE c.TABLE_SCHEMA = '{{DB_SCHEMA}}'
   ORDER BY c.TABLE_NAME, c.ORDINAL_POSITION;
   ```
   If it fails, put the query in the catalog as a "run to complete" note and tag the gap `[?]`.
4. A decoded name for a column only where every part of it is defined in the glossary.

## Output

Write three files. Each starts with this frontmatter, with its own `document` name:

```yaml
---
document: <DB change impact matrix | DB glossary | DB schema catalog>
product: {{PRODUCT_NAME}}
schema: {{DB_SCHEMA}}
environment: {{DB_ENV}}
generated_date: {{RUN_DATE}}
inputs: [00_DB_DISCOVERY_REPORT.md, 02_DB_TECHNICAL_REQUIREMENTS.md, <domain context file>]
prompt_id: DB-05
prompt_version: 2.0.0
---
```

- `{{KB_DB_DOCS}}/04_DB_CHANGE_IMPACT_MATRIX.md`: the matrix, then a list of how each table was assigned.
- `{{KB_DB_DOCS}}/05_DB_GLOSSARY.md`: terms A to Z, then Not yet defined.
- `{{KB_DB_DOCS}}/07_DB_SCHEMA_CATALOG.md`: summary table, header columns, then one section per wide table.

Each file ends with Open questions, Assumptions, Don't know and Files read.

## Evidence rules

- Query facts are tagged `[E: DB-01 Q<n>]`, and domain facts `[E: domain context §<n>]`.
- A capability assignment cites its rule: the domain context section, the DB-02 area or the prefix mapping.
- Anything taken as true without a source is `[A]` and goes on the Assumptions list.
- Anything not known is `[?]` and goes on the Don't know list.

## Self-check

- [ ] Every table in Q3 appears in at least one matrix row.
- [ ] Every glossary definition cites the domain context.
- [ ] Every table with more than 20 columns has a full column section, or a "run to complete" note.
- [ ] No column is decoded from a guess.
- [ ] Every `[A]` and `[?]` in each file is on that file's lists.

## Open questions, assumptions and unknowns

End each file with three lists:

- **Open questions:** each names who can answer. Include every table placed in Cross-cutting by default.
- **Assumptions:** each `[A]`, and what changes if it's wrong.
- **Don't know:** each `[?]`, with who could answer. Include every undefined abbreviation.
