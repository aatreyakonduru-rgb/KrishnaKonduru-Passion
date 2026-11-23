---
prompt_id: APP-10
title: API endpoint registry (YAML)
kind: prompt
pipeline: app
stage: 10
version: 2.0.0
shareable: true
requires: []
depends_on: [APP-01, APP-03, APP-04, APP-09]
placeholders: [PRODUCT_NAME, KB_MODULE_DOCS, MODULE_NAME, MODULE_SOURCE, RUN_DATE]
outputs: ["{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/10_ENDPOINT_REGISTRY.yaml"]
---

# APP-10: API endpoint registry (YAML)

## Purpose

A machine-readable map from each endpoint of the {{PRODUCT_NAME}} API module `{{MODULE_NAME}}`
to the files that implement it and the tables it touches. An AI agent uses it to find the code
for an endpoint, or the endpoints behind a table, without searching the repo. Run it for API
modules only.

## Before you start

1. Render with the module: `prompts.py render PROMPT_10_ENDPOINT_REGISTRY.md --set MODULE_NAME=<name> --set MODULE_SOURCE=<folder>`.
2. Read these files in `{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/`:
   - `00_DISCOVERY_REPORT.md` for the file list;
   - `02_FUNCTIONAL_REQUIREMENTS.md` for the endpoints;
   - `03_TECHNICAL_REQUIREMENTS.md` for the patterns;
   - `08_SECURITY_REVIEW.md` and `VALIDATION_LOG.md` for known issues.
3. Read the route declarations under `{{MODULE_SOURCE}}`. The code is the list of record. The
   FRD is only a cross-check.

## Steps

For each route declared in code:

1. Record the path, method and a one-line description.
2. Trace it to its files: the handler, the service, the schema, the SQL and the tests.
3. List the tables it reads and writes, taken from its SQL files or service code. If it writes to
   a staging or UI table that a sync job copies on, say so.
4. Record which schema or view the query uses, if it picks one (for example, a masked view).
5. Record whether auth is required, and name the decorator or guard.
6. List the query parameters and the response fields, taken from the schema classes.
7. Link known issues from the security review or the validation log, using their IDs.
8. Set the confidence: 1.0 if confirmed in code, 0.8 if from the FRD only, 0.6 if pieced
   together from names.
9. List routes that are in the FRD but not in code, and routes that are in code but not in the
   FRD, separately.

## Output

Write `{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/10_ENDPOINT_REGISTRY.yaml`:

```yaml
metadata:
  product: {{PRODUCT_NAME}}
  module: {{MODULE_NAME}}
  framework: <name and version, from discovery>
  base_url: <from routing config>
  auth: <how auth is applied, and the exceptions>
  generated_date: {{RUN_DATE}}
  prompt_id: APP-10
  prompt_version: 2.0.0
endpoints:
  - id: EP-<nnn>
    path: <path>
    method: <GET|POST|PUT|PATCH|DELETE>
    description: <one line>
    app: <app or package>
    files: {api: <path>, service: <path>, schema: <path>, sql: [<path>], tests: <path or null>}
    db_tables_read: [<table>]
    db_tables_write: [<table>]
    db_schema: <schema or view, or null>
    auth_required: <true|false>
    query_params: [{name: <name>, type: <type>, required: <bool>}]
    response_fields: [<name>]
    known_issues: [{id: <ID>, description: <text>}]
    fr_ids: [<FR-...>]
    source: [<"path:line">, <"FRD FR-...">]
    confidence: <1.0 | 0.8 | 0.6>
not_in_code: [<FRD route>]
not_in_frd: [<code route>]
open_questions: []
assumptions: []
dont_know: []
```

## Evidence rules

- Each endpoint's `source` lists the route line and the FR, like `[E: <file>:<line>]`.
- A table name comes from SQL or service code only. A table you guessed from a name gets confidence 0.6, with `[?]` in the list.
- Anything taken as true without a source is `[A]` and goes in `assumptions`.
- No endpoint is added unless it appears in code or the FRD.

## Self-check

- [ ] Every route in code has an entry.
- [ ] Each entry has its files, tables, auth and confidence filled in.
- [ ] Known issues are linked by ID.
- [ ] The file parses as YAML.
- [ ] Every `[A]` and `[?]` is in its list.

## Open questions, assumptions and unknowns

Fill the three lists at the end of the YAML:

- **Open questions:** each with an owner by role (tech lead, API developer).
- **Assumptions:** each `[A]`, and what changes if it's wrong.
- **Don't know:** each `[?]`, with who could answer.
