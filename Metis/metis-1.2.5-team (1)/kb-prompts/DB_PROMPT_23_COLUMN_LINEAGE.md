---
prompt_id: DB-23
title: Database column lineage
kind: prompt
pipeline: db
stage: 11.5
version: 1.0.0
shareable: true
requires: []
depends_on: [DB-11, DB-21]
placeholders: [KB_DB_DOCS, DOMAIN_CONTEXT, SNOWFLAKE_DB, DB_SCHEMA, DB_ENV, DB_RELATED_SCHEMAS, RUN_DATE]
outputs: ["{{KB_DB_DOCS}}/23_DB_COLUMN_LINEAGE.yaml"]
---

# DB-23: Database column lineage

## Purpose

Extend DB-11 from the table level to the column level. For each column that matters, record where its values come from
(the source column in another table, schema or file), what transformation changes them, and which
columns and reports read it. "Where does `ORDER_STATUS` come from?" and "what breaks if I rename
`AMT_NET`?" need this level. DB-11 answers only the table-level version.

## Before you start

1. Render this prompt: `prompts.py render DB_PROMPT_23_COLUMN_LINEAGE.md --env <env>`.
2. Read these:
   - Required: `{{KB_DB_DOCS}}/11_DB_DATA_LINEAGE.yaml`, the table-level flows.
   - Required: `{{KB_DB_DOCS}}/21_DB_OBJECT_LOGIC.md`, the output-to-source map for views.
   - Required: `{{KB_DB_DOCS}}/09_DB_SEMANTIC_LAYER.yaml`, the tables and entities.
   - Optional: the ETL knowledge-base documents that name column mappings, and `{{DOMAIN_CONTEXT}}`.
3. Related schemas are {{DB_RELATED_SCHEMAS}}. Their columns can be sources.
4. Don't query the database. Every hop needs a source document.

## Steps

1. **Start from the target columns.** Use the semantic-layer tables. For each measure, time
   dimension and key, trace its source.
2. **Trace each hop.** For one column, write each hop until a source table is reached, with:
   - the source table and column;
   - the transformation (copy, rename, cast, expression, lookup, aggregate), as written in the source;
   - the process that does it (view, procedure, task, ETL job), with its file or object id;
   - the trigger, only if a source says so.
3. **Use the view map first.** When DB-21 maps an output column to a source column, use that.
   Cite `[E: DB-21 <object>]`.
4. **Stop at the first hop you can't source.** Write it as `[?]` with the owner who can confirm it.
   Don't fill the gap with a column that has a similar name.
5. **Impact.** For each source column in scope, list the columns and objects that read it, with
   their source. Use DB-21 view definitions and DB-11 outbound flows. A reader not found in any
   source is not listed.

## Output

Write `{{KB_DB_DOCS}}/23_DB_COLUMN_LINEAGE.yaml`. Start with comment lines for the product, source
(`{{SNOWFLAKE_DB}}.{{DB_SCHEMA}}`), environment ({{DB_ENV}}), date ({{RUN_DATE}}), `prompt_id: DB-23`
and `prompt_version: 1.0.0`. Then:

```yaml
metadata:
  generated_date: {{RUN_DATE}}
  columns_traced: <n>
  hops_unsourced: <n>
columns:
  - target: <TABLE.COLUMN>
    hops:
      - from: <TABLE.COLUMN or system>
        to: <TABLE.COLUMN>
        transform: <as written, or copy>
        process: <object id or ETL file>
        trigger: <text or null>
        source: <"DB-21 <object>" | "ETL <file> §<n>" | "unknown">
        confidence: <1.0 | 0.8 | 0.6 | 0.3>
    readers: [{object: <name>, source: <text>}]
    breaking_change_impact: <one line, or null when there are no readers>
open_questions: []
assumptions: []
unknowns: []
```

## Evidence rules

- Every hop has a source file or object. A hop without one is `0.3`, and it's an unknown.
- A transformation is copied from the source, not described from its name.
- A reader needs a source. A column name match is `0.6`, and an assumption.
- A column is never linked to another because the names match.

## Self-check

- [ ] The file parses as YAML.
- [ ] Every target column appears under `columns`.
- [ ] Every hop has a source and confidence.
- [ ] Every `TABLE.COLUMN` exists in DB-09 or DB-17.
- [ ] Every 0.3 hop is in `unknowns`, with an owner.

## Open questions, assumptions and unknowns

- `open_questions`: unsourced hops and conflicting mappings, with the data engineer who can answer.
- `assumptions`: each name-based reader, and what changes if it's wrong.
- `unknowns`: unsourced hops, with who could confirm them.
