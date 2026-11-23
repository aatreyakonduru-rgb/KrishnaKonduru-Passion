---
prompt_id: APP-18
title: API response field lineage (YAML)
kind: prompt
pipeline: app
stage: 18
version: 1.0.0
shareable: true
requires: []
depends_on: [APP-10, APP-11]
placeholders: [PRODUCT_NAME, KB_MODULE_DOCS, KB_DB_DOCS, MODULE_NAME, MODULE_SOURCE, RUN_DATE]
outputs: ["{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/18_RESPONSE_FIELD_LINEAGE.yaml"]
---

# APP-18: API response field lineage (YAML)

## Purpose

For each field in the response of the {{PRODUCT_NAME}} API module `{{MODULE_NAME}}`, record the full
path back to the database: the table and column, the joins that bring it in, any transformation
or derived value, and any filter that changes which rows it comes from. APP-11 lists the
db_source of each field. This prompt shows the path an agent needs to answer "where does this
response field come from, and can it change under me?"

## Before you start

1. Render with the module: `prompts.py render PROMPT_18_RESPONSE_FIELD_LINEAGE.md --set MODULE_NAME=<name> --set MODULE_SOURCE=<folder>`.
2. Read these in `{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/`:
   - `10_ENDPOINT_REGISTRY.yaml` and `11_API_DATA_CONTRACTS.yaml`. Stop if either is missing.
3. Read `{{KB_DB_DOCS}}/21_DB_OBJECT_LOGIC.md` and `{{KB_DB_DOCS}}/23_DB_COLUMN_LINEAGE.yaml` if they
   exist. A view in the response path is read from there first.
4. Read the query code under `{{MODULE_SOURCE}}` for each endpoint. The code is the record. Don't
   guess from field names.

## Steps

For each endpoint in `11_API_DATA_CONTRACTS.yaml`, for each response field:

1. **Find the query.** Open the handler and service, and find the SQL or ORM query that builds the
   response. Record the file and line.
2. **Trace the field.** Record:
   - the response field name and type (copy from APP-11);
   - the source expression as written in the query (for example `o.ORDER_STATUS` or `CASE ...`);
   - the table and column it reads, with alias resolved;
   - each join needed to reach that table, from the query, with its join condition;
   - any filter in the `WHERE` clause that affects which rows the field can show (current-row,
     status, tenant or permission filters);
   - any transformation in code after the query (formatting, rounding, mapping a code to a label);
   - whether the value is cached, computed or read live, if the code says so.
3. **Mark derived fields.** A field computed from several columns is `derived`. List every source column.
4. **Mark mock or test data.** If the code returns fixed or test data for a field, say so. Don't
   record the data as a source.
5. **Unsourced fields.** A field with no query path found is `[?]` with the reason.

## Output

Write `{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/18_RESPONSE_FIELD_LINEAGE.yaml`:

```yaml
metadata:
  product: {{PRODUCT_NAME}}
  module: {{MODULE_NAME}}
  generated_date: {{RUN_DATE}}
  prompt_id: APP-18
  prompt_version: 1.0.0
endpoints:
  - endpoint: <EP id from APP-10>
    path: "<METHOD> <path>"
    fields:
      - response_field: <name>
        type: <from APP-11>
        kind: <direct | derived | constant | unsourced>
        expression: <as written in the query, or null>
        sources: [{table: <TABLE>, column: <COLUMN>, alias: <alias>}]
        joins: [{table: <TABLE>, on: <condition as written>}]
        row_filters: [<condition as written>]
        post_processing: <text or null>
        data_origin: <live | cached | mock | unknown>
        source: [<"path:line">]
        confidence: <1.0 | 0.8 | 0.6 | 0.3>
open_questions: []
assumptions: []
unknowns: []
```

## Evidence rules

- Every expression, join and filter is copied from code and cited with `path:line`. `1.0`.
- A field whose path is taken from the registry or the FRD only is `0.8`.
- A table or column guessed from a name is `0.6` and an assumption.
- A field with no path is `0.3` and an unknown.
- Use only table and column names that exist in the DB docs (`00_DB_DISCOVERY_REPORT.md` Q5 or the semantic layer).

## Self-check

- [ ] Every field in APP-11 for every endpoint has an entry.
- [ ] Every source table and column exists in the DB docs, or is marked `0.6` with an assumption.
- [ ] Every row filter is copied from code, with its line.
- [ ] Mock or test data is marked and never used as a source.
- [ ] The file parses as YAML.

## Open questions, assumptions and unknowns

- `open_questions`: fields whose source differs between code and the registry, with the API developer who can answer.
- `assumptions`: each name-based table or column, and what changes if it's wrong.
- `unknowns`: unsourced fields, with who could confirm them.
