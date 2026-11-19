---
prompt_id: DB-16
title: Cross-module dependency matrix
kind: prompt
pipeline: db
stage: 16
version: 2.0.0
shareable: true
requires: []
depends_on: [DB-09B, DB-11, DB-13]
placeholders: [PRODUCT_NAME, KB_ROOT, KB_DB_DOCS, DOMAIN_CONTEXT, APP_SOURCE_DIRS, SNOWFLAKE_DB,
               DB_SCHEMA, DB_ENV, RUN_DATE]
outputs: ["{{KB_DB_DOCS}}/16_DB_CROSS_MODULE_DEPENDENCY_MATRIX.yaml"]
---

# DB-16: Cross-module dependency matrix

## Purpose

For each important {{PRODUCT_NAME}} column and table, list everything that writes it and
everything that reads it: the UI, the API, ETL jobs and downstream systems. Then "widen this
column" or "add this field" turns into a complete list of stories, one per layer, with nothing
forgotten. It's the last DB stage, and it pulls the earlier ones together. An architect must
review it before anything relies on it.

## Before you start

1. Render this prompt: `prompts.py render DB_PROMPT_16_CROSS_MODULE_MATRIX.md --env <env>`.
2. Read these.
   - Required in `{{KB_DB_DOCS}}`: `13_DB_ENTITY_REGISTRY.yaml`, `9B_DB_DATA_CONTRACTS.yaml` and
     `11_DB_DATA_LINEAGE.yaml`.
   - Required: the domain context at `{{DOMAIN_CONTEXT}}`, for downstream systems and who owns each layer.
   - If present under `{{KB_ROOT}}`: the API, UI and ETL knowledge-base documents, such as endpoint
     registries, component registries and ETL table input/output contracts.
3. Check claims against the source code in these folders:

{{APP_SOURCE_DIRS}}

4. Don't query the database.

## Steps

1. **Choose the columns.** Take every contracted column in 9B, plus every key column used by more
   than one table.
2. **Dependency chains.** For each column, record:
   - its **writers**: each layer that sets it (UI form, API endpoint, ETL job or sync), with the file
     or job and the source;
   - its **readers**: each layer that reads it, including downstream systems from the lineage;
   - **if changed**: what must change in each layer for a type, length or meaning change;
   - an **impact rating**:
     - critical: used by many tables, or read downstream;
     - high: crosses layers;
     - medium: one layer plus the database;
     - low: database only.
3. **Table summary.** For each table: its writer and reader layers, its downstream consumers, and
   its highest column impact. Sort by the number of consumers.
4. **Change scenarios.** At least four templates:
   - add a column;
   - widen or retype a column;
   - add a code value;
   - add a table.

   Each one lists the layers touched, the owner by role from the domain context, and the KB
   documents to refresh afterwards.
5. **Gaps.** Every link you couldn't confirm goes on a separate list for follow-up.

## Output

Write `{{KB_DB_DOCS}}/16_DB_CROSS_MODULE_DEPENDENCY_MATRIX.yaml`. Start with comment lines for the
product, source (`{{SNOWFLAKE_DB}}.{{DB_SCHEMA}}`), environment ({{DB_ENV}}), the date ({{RUN_DATE}}),
`prompt_id: DB-16`, prompt version 2.0.0 and `review: architecture sign-off required`. Then
these sections: `metadata`, `dependency_chains`, `table_impact_summary`, `change_scenarios`,
`unconfirmed_links`, `open_questions`, `assumptions`, `unknowns`.

Each chain has these fields:

```yaml
- id: DC-<nnn>
  table: <table>
  column: <column>
  writers: [{layer: <ui|api|etl|sync|external>, where: <file, job or system>, source: <ref>}]
  readers: [{layer: <...>, where: <...>, source: <ref>}]
  if_changed: [{layer: <...>, change: <what to update>}]
  impact: <critical | high | medium | low>
  confidence: <1.0 | 0.8 | 0.6 | 0.3>
```

## Evidence rules

- `1.0`: source code (file and line), a query result or an answered validation-log item.
- `0.8`: a KB document.
- `0.6`: a pattern repeated elsewhere but not checked here. It also goes under `assumptions`.
- `0.3`: not confirmed. It also goes under `unconfirmed_links` and `unknowns`.
- Never assume every staging table has a matching sync step, or every column a matching form field.
  Check each one.

## Self-check

- [ ] The file parses as YAML.
- [ ] Every chain has writers, readers, if_changed and a rating.
- [ ] Every writer and reader has a source.
- [ ] At least four change scenarios, each with owners by role.
- [ ] Every 0.3 link is in `unconfirmed_links`.

## Open questions, assumptions and unknowns

End the file with three lists:

- `open_questions`: text, and the owner who can answer.
- `assumptions`: text, and what changes if it's wrong.
- `unknowns`: text, and who could answer.
