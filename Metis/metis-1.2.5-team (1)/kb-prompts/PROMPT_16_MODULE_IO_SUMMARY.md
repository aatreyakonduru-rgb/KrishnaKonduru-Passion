---
prompt_id: APP-16
title: Module input/output summary
kind: prompt
pipeline: app
stage: 8
version: 2.0.0
shareable: true
requires: []
depends_on: [APP-03, APP-04]
placeholders: [PRODUCT_NAME, DOMAIN_CONTEXT, KB_MODULE_DOCS, MODULE_NAME, MODULE_SOURCE, RUN_DATE]
outputs: ["{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/10_MODULE_IO_SUMMARY.md"]
---

# APP-16: Module input/output summary

## Purpose

Give one page per {{PRODUCT_NAME}} module that says what goes in, what comes out, and what each
feature depends on. A developer or analyst reads it to see the blast radius of a change: which
features read or write which tables, files and services, and in what order things must exist.

## Before you start

1. Render with the module: `prompts.py render PROMPT_16_MODULE_IO_SUMMARY.md --set MODULE_NAME=<name> --set MODULE_SOURCE=<folder>`. The module's source is in `{{MODULE_SOURCE}}`.
2. Read, from `{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/`: `02_FUNCTIONAL_REQUIREMENTS.md`,
   `03_TECHNICAL_REQUIREMENTS.md`, and `05_PROCESS_DOCUMENTATION.md` if it exists. If the FRD or
   TRD is missing, stop.
3. Read `10_ENDPOINT_REGISTRY.yaml` and `11_API_DATA_CONTRACTS.yaml` in the same folder if they
   exist. For a front-end module, read the registries of the API module it calls.
4. Read the domain context at `{{DOMAIN_CONTEXT}}` for business names and upstream and downstream
   systems.
5. This is a summary. Check each row against the code in `{{MODULE_SOURCE}}`, but don't
   re-document what the TRD already covers in detail. Point to it.

## Steps

1. **Summary table.** One row per feature or sub-module: its inputs (user entry, uploaded files,
   API requests, tables read), its outputs (tables written, files produced, responses, messages),
   and the endpoint or screen that starts it.
2. **Inbound contracts.** For each input that crosses a boundary (an uploaded file, a request
   body, a message), the shape in brief and where its full definition lives.
3. **Outbound operations.** For each table or external system the module writes to: the
   operation (insert, update, merge, delete, call), the trigger, and the code that does it.
4. **Prerequisites.** What must exist before a feature works, such as reference data, a parent
   record or an upstream job. Show the order as a Mermaid flowchart.
5. **After an action.** What happens next: a downstream job, a status change, a notification,
   a cache refresh.
6. **Open I/O questions.** Inputs or outputs the code doesn't settle, such as a table written
   by something outside the module.

## Output

Write `{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/10_MODULE_IO_SUMMARY.md`, starting with:

```yaml
---
document: Module input/output summary
product: {{PRODUCT_NAME}}
module: {{MODULE_NAME}}
version: <n>
status: Draft
generated_date: {{RUN_DATE}}
layer: code
prompt_id: APP-16
prompt_version: 2.0.0
---
```

Sections:

1. Overview
2. Summary table
3. Inbound contracts
4. Outbound operations
5. Prerequisites (with the flowchart)
6. After an action
7. Open I/O questions

Then Open questions, Assumptions, Don't know and Files read.

## Evidence rules

- Every row carries `[E: <file>:<line>]` or `[E: TRD §<n>]`. A table or file name must come from
  code, config or a KB document, never from a naming pattern.
- A flow the code doesn't show end to end is `[?]`.
- Anything taken as true without a source is `[A]` and goes on the Assumptions list.

## Self-check

- [ ] Every feature in the FRD has a row, or is listed as having no inputs or outputs.
- [ ] Every table, file and external system named has a source.
- [ ] The prerequisite flowchart matches the summary table.
- [ ] Every `[A]` and `[?]` is on its list.

## Open questions, assumptions and unknowns

End with three lists:

- **Open questions:** each with an owner by role (tech lead, data engineer, business analyst).
- **Assumptions:** each `[A]`, and what changes if it's wrong.
- **Don't know:** each `[?]`, with who could answer.
