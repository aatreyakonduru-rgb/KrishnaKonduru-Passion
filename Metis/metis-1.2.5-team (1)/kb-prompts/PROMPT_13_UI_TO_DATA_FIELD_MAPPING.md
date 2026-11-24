---
prompt_id: APP-13
title: UI-to-data field mapping
kind: prompt
pipeline: app
stage: 13
version: 2.0.0
shareable: true
requires: []
depends_on: [APP-03, APP-05, APP-06, APP-11, APP-12]
placeholders: [PRODUCT_NAME, DOMAIN_CONTEXT, KB_MODULE_DOCS, KB_DB_DOCS, KB_ETL_DOCS, MODULE_NAME, MODULE_SOURCE, RUN_DATE]
outputs: ["{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/13_UI_FIELD_TO_DATA_MAPPING.md"]
---

# APP-13: UI-to-data field mapping

## Purpose

Answer one question for every field in the `{{MODULE_NAME}}` screens: when a user fills it in
and saves, where does the value end up? The path runs from the screen label to the API field,
then to the staging or UI table, through any sync job, to the final table and column, and on to
whoever reads it. Business analysts, database and ETL engineers, and QA use it to check data
end to end. Run it for UI modules, after the API contracts and component registry exist.

## Before you start

1. Render with the module: `prompts.py render PROMPT_13_UI_TO_DATA_FIELD_MAPPING.md --set MODULE_NAME=<name> --set MODULE_SOURCE=<folder>`. The module's source is in `{{MODULE_SOURCE}}`.
2. Read the domain context at `{{DOMAIN_CONTEXT}}`: its screen field lists, sync tables and
   downstream consumers.
3. Read these documents:
   - `02_FUNCTIONAL_REQUIREMENTS.md`, `12_COMPONENT_REGISTRY.yaml`, and the UI specification (`07_UI_SPECIFICATION.md`) if it exists, in `{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/`;
   - the API contracts (`11_API_DATA_CONTRACTS.yaml`) of each API module it calls;
   - the schema catalog and data contracts in `{{KB_DB_DOCS}}`;
   - the ETL process docs in `{{KB_ETL_DOCS}}` for the sync jobs.

## Steps

1. **List the fields**, grouped by screen or form step, using the labels users see. Take them
   from the component registry, the UI spec or the domain context.
2. **Follow each field through**, filling in each hop you can source:
   - the UI label;
   - the API field;
   - the staging or UI table and column;
   - the sync job and its SQL file;
   - the final table and column;
   - the downstream readers.
3. **Stop at the first hop you can't source.** Write `Not found [?]` for it and for every hop
   after it, and add it to the Don't know list. Don't fill the gap with a column that has a
   similar name.
4. **Check the types along the way.** Compare the UI input type, the API type and the column
   type, and note any mismatch, such as a longer limit in one layer or a nullable column behind
   a required field.

## Output

Write `{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/13_UI_FIELD_TO_DATA_MAPPING.md`, starting with:

```yaml
---
document: UI-to-data field mapping
product: {{PRODUCT_NAME}}
module: {{MODULE_NAME}}
version: <n>
status: Draft
generated_date: {{RUN_DATE}}
layer: code
prompt_id: APP-13
prompt_version: 2.0.0
---
```

Sections:

1. Purpose
2. How to read this document
3. One section per screen or form step, each with this table:
   `| UI field | API field | Staging table.column | Sync job / SQL | Final table.column | Downstream | Source |`
4. Type mismatches
5. Fields that couldn't be traced

Then Open questions, Assumptions, Don't know and Files read. In this document, UI fields use
business labels, and the data columns use exact names.

## Evidence rules

- Each row's Source cell lists `[E: ...]` for each hop, citing the file, contract, catalog section or ETL doc.
- A hop without a source is `Not found [?]`.
- Anything taken as true without a source is `[A]` and goes on the Assumptions list.
- A column name is copied from the schema catalog, never pieced together from the label.

## Self-check

- [ ] Every saved field in the component registry has a row.
- [ ] No row fills a gap with a guessed column.
- [ ] Every mismatch has sources on both sides.
- [ ] Every `[A]` and `[?]` is on its list.

## Open questions, assumptions and unknowns

End with three lists:

- **Open questions:** each with an owner by role (database engineer, ETL developer, business analyst).
- **Assumptions:** each `[A]`, and what changes if it's wrong.
- **Don't know:** each `[?]`, with who could answer.
