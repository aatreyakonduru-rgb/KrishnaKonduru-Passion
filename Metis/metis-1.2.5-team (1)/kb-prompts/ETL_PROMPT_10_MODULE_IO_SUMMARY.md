---
prompt_id: ETL-10
title: ETL module input/output summary
kind: prompt
pipeline: etl
stage: 10
version: 2.0.0
shareable: true
requires: []
depends_on: [ETL-03, ETL-04]
placeholders: [PRODUCT_NAME, DOMAIN_CONTEXT, KB_ETL_DOCS, KB_DB_DOCS, MODULE_NAME, MODULE_SOURCE, RUN_DATE]
outputs: ["{{KB_ETL_DOCS}}/{{MODULE_NAME}}/10_ETL_MODULE_IO_SUMMARY.md"]
---

# ETL-10: ETL module input/output summary

## Purpose

One page that shows what `{{MODULE_NAME}}` reads, what it writes, what it changes on the way,
and how it hands data to other systems. Someone asking "what feeds this table?" or "what
breaks if this source changes?" should find the answer here.

## Before you start

1. Render with the module: `prompts.py render ETL_PROMPT_10_MODULE_IO_SUMMARY.md --set MODULE_NAME=<name> --set MODULE_SOURCE=<folder>`. The module's source is in `{{MODULE_SOURCE}}`.
2. Read the domain context at `{{DOMAIN_CONTEXT}}`.
3. Read documents 02 to 05 in `{{KB_ETL_DOCS}}/{{MODULE_NAME}}/`, and the schema catalog in
   `{{KB_DB_DOCS}}`.

## Steps

1. **Sources.** Each input: application tables, other systems, files and feeds. For each, record
   the owner, the tables or files involved, how often it arrives, and the process that reads it.
2. **Targets.** Each output: core tables, downstream systems, files and messages. For each,
   record the consumer and the process that writes it.
3. **Transforms.** For each process: the main changes it makes, such as joins, calculations,
   de-duplication, history handling and status changes.
4. **Hand-off methods.** Trigger files, messages, status tables and schedules, as found in code.
5. **Quality checks.** The checks the module runs on its inputs and outputs, from code.
6. **Change impact.** For each source, what breaks downstream if its shape changes.

## Output

Write `{{KB_ETL_DOCS}}/{{MODULE_NAME}}/10_ETL_MODULE_IO_SUMMARY.md`, starting with:

```yaml
---
document: ETL module input/output summary
product: {{PRODUCT_NAME}}
module: {{MODULE_NAME}}
version: <n>
status: Draft
generated_date: {{RUN_DATE}}
layer: code
prompt_id: ETL-10
prompt_version: 2.0.0
---
```

Sections:

1. Overview
2. Sources
3. Targets
4. Transforms
5. Hand-off methods
6. Quality checks
7. Change impact

Then Open questions, Assumptions, Don't know and Files read.

## Evidence rules

- Each source, target and hand-off is tagged `[E: <file>:<line>]`, `[E: <doc> §<n>]` or `[E: domain context §<n>]`.
- A consumer or frequency without a source is `[?]`.
- Anything taken as true without a source is `[A]` and goes on the Assumptions list.
- Table names match the schema catalog.

## Self-check

- [ ] Every table in the discovery SQL inventory is a source or a target.
- [ ] Every target has a consumer, or is marked `[?]`.
- [ ] Every `[A]` and `[?]` is on its list.

## Open questions, assumptions and unknowns

End with three lists:

- **Open questions:** each with an owner by role (ETL developer, data owner, downstream team).
- **Assumptions:** each `[A]`, and what changes if it's wrong.
- **Don't know:** each `[?]`, with who could answer.
