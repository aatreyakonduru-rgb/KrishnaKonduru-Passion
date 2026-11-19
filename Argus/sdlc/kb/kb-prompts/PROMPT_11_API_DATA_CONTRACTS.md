---
prompt_id: APP-11
title: API data contracts (YAML)
kind: prompt
pipeline: app
stage: 11
version: 2.0.0
shareable: true
requires: []
depends_on: [APP-10]
placeholders: [PRODUCT_NAME, KB_MODULE_DOCS, MODULE_NAME, MODULE_SOURCE, RUN_DATE]
outputs: ["{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/11_API_DATA_CONTRACTS.yaml"]
---

# APP-11: API data contracts (YAML)

## Purpose

Give the request and response shape of each endpoint in `{{MODULE_NAME}}`: field types,
required flags, limits, allowed values, the database column each field maps to, the validation
rules, the error cases and the side effects. An AI agent uses it to write client code, tests and
changes without breaking the contract. Run it after APP-10.

## Before you start

1. Render with the module: `prompts.py render PROMPT_11_API_DATA_CONTRACTS.md --set MODULE_NAME=<name> --set MODULE_SOURCE=<folder>`.
2. Read `10_ENDPOINT_REGISTRY.yaml`, `02_FUNCTIONAL_REQUIREMENTS.md` and
   `03_TECHNICAL_REQUIREMENTS.md` in `{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/`. Stop if the
   registry is missing.
3. For each endpoint, read the schema classes, the handler and the SQL it uses, under
   `{{MODULE_SOURCE}}`.

## Steps

For each endpoint in the registry:

1. **Request.** For each query parameter and body field: its type, whether it's required, its
   default, its maximum length, its allowed values, and a short description. Copy the types from
   the schema classes.
2. **Response.** The response type and each field's type. Map each field to its source column
   (`TABLE.COLUMN`), using the SQL. Note joins that bring in fields from other tables.
3. **Where writes land.** For each body field that gets saved, the table and column it lands in.
4. **Validation.** Each rule, with where it's enforced: schema, handler, service or database.
5. **Errors.** Each status code and the condition that causes it, taken from the code.
6. **Side effects.** Status changes, sync flags, emails, trigger files and audit rows.
7. **Confidence.** 1.0 if taken from the schema classes and SQL, 0.8 if taken from the FRD only.
   If you took a value from the FRD rather than code, say so.

## Output

Write `{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/11_API_DATA_CONTRACTS.yaml`:

```yaml
metadata:
  product: {{PRODUCT_NAME}}
  module: {{MODULE_NAME}}
  generated_date: {{RUN_DATE}}
  prompt_id: APP-11
  prompt_version: 2.0.0
contracts:
  - endpoint: <EP id from APP-10>
    path: "<METHOD> <path>"
    request:
      query_params: [{name: <n>, type: <t>, required: <b>, default: <v>, choices: [<v>], description: <text>}]
      body: [{name: <n>, type: <t>, required: <b>, max_length: <n>, choices: [<v>], db_target: <TABLE.COLUMN or null>}]
    response:
      type: <type>
      fields: [{name: <n>, type: <t>, db_source: <TABLE.COLUMN or null>, note: <text>}]
    validation_rules: [{rule: <text>, where: <schema|handler|service|db>, source: <"path:line">}]
    error_responses: [{status: <code>, condition: <text>, source: <"path:line">}]
    side_effects: [<text>]
    source: [<"path:line">]
    confidence: <1.0 | 0.8>
open_questions: []
assumptions: []
dont_know: []
```

## Evidence rules

- Each type, limit, rule and error has a `source` of `[E: <file>:<line>]`.
- A column mapping you can't see in SQL is `null`, and goes in `dont_know` as `[?]`.
- Anything taken as true without a source is `[A]` and goes in `assumptions`.
- Allowed values are copied from the code or schema, never listed from memory.

## Self-check

- [ ] Every registry endpoint has a contract.
- [ ] Every saved body field has a `db_target` or is listed as unknown.
- [ ] Every error has a condition and a source.
- [ ] The file parses as YAML.
- [ ] Every `[A]` and `[?]` is in its list.

## Open questions, assumptions and unknowns

Fill the three lists at the end of the YAML:

- **Open questions:** each with an owner by role (API developer, tech lead).
- **Assumptions:** each `[A]`, and what changes if it's wrong.
- **Don't know:** each `[?]`, with who could answer.
