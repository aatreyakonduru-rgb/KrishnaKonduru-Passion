---
prompt_id: ETL-12
title: ETL SQL pattern library (YAML)
kind: prompt
pipeline: etl
stage: 12
version: 2.0.0
shareable: true
requires: []
depends_on: [ETL-04, ETL-11]
placeholders: [PRODUCT_NAME, KB_ETL_DOCS, MODULE_NAME, MODULE_SOURCE, SNOWFLAKE_DB, DB_SCHEMA, DB_GLOBAL_FILTERS, RUN_DATE]
outputs: ["{{KB_ETL_DOCS}}/{{MODULE_NAME}}/12_ETL_SQL_PATTERNS.yaml"]
---

# ETL-12: ETL SQL pattern library (YAML)

## Purpose

Record the SQL and script patterns `{{MODULE_NAME}}` already uses, such as sync merges, request
inserts, alerts and locks, as templates with their required parts and their known mistakes. An
AI agent writing new ETL code copies these, rather than inventing a new style.

## Before you start

1. Render with the module: `prompts.py render ETL_PROMPT_12_SQL_PATTERN_LIBRARY.md --set MODULE_NAME=<name> --set MODULE_SOURCE=<folder>`.
2. Read `03_ETL_TECHNICAL_REQUIREMENTS.md` and `11_ETL_INTEGRATION_SCENARIOS.md` in
   `{{KB_ETL_DOCS}}/{{MODULE_NAME}}/`.
3. Read the SQL and scripts under `{{MODULE_SOURCE}}`.
4. The team's filters that every query must apply:

{{DB_GLOBAL_FILTERS}}

## Steps

1. **Group the files by shape.** Group similar SQL files and script functions, such as merges,
   inserts, alerts and locks. Each group with two or more members becomes a pattern.
2. **For each pattern, record:**
   - the name, a description and the files that use it;
   - a template, written from one real file, with parameters in the style the code uses;
   - the mandatory elements: standard header columns, the global filters above, current-row
     handling, and audit or status updates;
   - anti-patterns, meaning mistakes seen in the repo or ruled out by its conventions, each with
     the reason;
   - the source and confidence.
3. **Standard header columns.** Check that the header block is the same in every pattern. List
   the files where it differs.
4. **Parameters.** Record how the code passes parameters. If some files use string formatting
   instead, list them as anti-pattern examples.

## Output

Write `{{KB_ETL_DOCS}}/{{MODULE_NAME}}/12_ETL_SQL_PATTERNS.yaml`:

```yaml
metadata:
  product: {{PRODUCT_NAME}}
  module: {{MODULE_NAME}}
  database: {{SNOWFLAKE_DB}}
  schema: {{DB_SCHEMA}}
  generated_date: {{RUN_DATE}}
  prompt_id: ETL-12
  prompt_version: 2.0.0
patterns:
  - id: PAT-<nnn>
    name: <name>
    description: <one line>
    used_by: [<file>]
    template: |
      <SQL or code, based on a real file>
    mandatory_elements: [<element>]
    anti_patterns: [{bad: <text>, why: <reason>, seen_in: <file or null>}]
    source: [<"path:line">]
    confidence: <1.0 | 0.8 | 0.6>
header_differences: [<file>]
open_questions: []
assumptions: []
dont_know: []
```

## Evidence rules

- Each template names the real file it came from, in `source`, as `[E: <file>:<line>]`.
- A pattern seen in only one file gets confidence 0.6, and a note.
- Anything taken as true without a source is `[A]` and goes in `assumptions`.
- Templates never contain real credentials, hosts or record values.

## Self-check

- [ ] Every SQL group in the discovery report either has a pattern or is explained.
- [ ] Every pattern includes the global filters where they apply.
- [ ] Parameter style matches the code.
- [ ] The file parses as YAML.
- [ ] Every `[A]` and `[?]` is in its list.

## Open questions, assumptions and unknowns

Fill the three lists at the end of the YAML:

- **Open questions:** each with an owner by role (ETL developer, database engineer).
- **Assumptions:** each `[A]`, and what changes if it's wrong.
- **Don't know:** each `[?]`, with who could answer.
