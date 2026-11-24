---
prompt_id: ETL-07
title: ETL architecture diagrams
kind: prompt
pipeline: etl
stage: 7
version: 2.0.0
shareable: true
requires: []
depends_on: [ETL-01, ETL-03, ETL-04]
placeholders: [PRODUCT_NAME, DOMAIN_CONTEXT, KB_ETL_DOCS, MODULE_NAME, MODULE_SOURCE, RUN_DATE]
outputs: ["{{KB_ETL_DOCS}}/{{MODULE_NAME}}/06_ETL_ARCHITECTURE_DIAGRAMS.md"]
---

# ETL-07: ETL architecture diagrams

## Purpose

Draw `{{MODULE_NAME}}` as Mermaid diagrams. Show where it sits in {{PRODUCT_NAME}}, then give
each process's data flow, its components, its triggers, its alerts and its status lifecycles.
Every box and arrow comes from a document or file.

## Before you start

1. Render with the module: `prompts.py render ETL_PROMPT_7_ARCHITECTURE_DIAGRAMS.md --set MODULE_NAME=<name> --set MODULE_SOURCE=<folder>`. The module's source is in `{{MODULE_SOURCE}}`.
2. Read the domain context at `{{DOMAIN_CONTEXT}}`.
3. Read documents 00, 02 and 03 in `{{KB_ETL_DOCS}}/{{MODULE_NAME}}/`. Stop if any is missing.

## Steps

Draw each diagram that applies. Skip the ones that don't, and give the reason.

1. **System context.** The source systems, this module, the target tables and systems, and the
   schedulers and alert channels.
2. **Components.** The scripts, the shared helpers and the SQL groups, and how they call each other.
3. **One data flow per process.** Source tables, then transforms, then targets. Label each
   arrow with the operation.
4. **Triggers and run order.** A diagram of which job starts which, by trigger file, message,
   schedule or dependency.
5. **Alerts.** What sends each alert, and who gets it.
6. **Status lifecycles.** A state diagram for each status column the module sets, using the
   exact values from the SQL.
7. **Check each diagram.** It must parse as Mermaid, every node must appear in a source, and
   every edge must have a label or a source note.

## Output

Write `{{KB_ETL_DOCS}}/{{MODULE_NAME}}/06_ETL_ARCHITECTURE_DIAGRAMS.md`, starting with:

```yaml
---
document: ETL architecture diagrams
product: {{PRODUCT_NAME}}
module: {{MODULE_NAME}}
version: <n>
generated_date: {{RUN_DATE}}
layer: design
prompt_id: ETL-07
prompt_version: 2.0.0
---
```

For each diagram, give a heading, one sentence on what it shows, the Mermaid block, and a list
of its sources. Then Open questions, Assumptions, Don't know and Files read.

## Evidence rules

- Each node or edge group is backed by `[E: <file>]`, `[E: <doc> §<n>]` or `[E: domain context §<n>]`.
- A link you can't source is drawn dashed, labelled `[?]`, and listed.
- Anything taken as true without a source is `[A]` and goes on the Assumptions list.
- Hosts, bucket names, account IDs and secrets never appear. Use role names.

## Self-check

- [ ] Every diagram parses.
- [ ] Every process has a data-flow diagram.
- [ ] Every status value matches the SQL.
- [ ] Every `[A]` and `[?]` is on its list.

## Open questions, assumptions and unknowns

End with three lists:

- **Open questions:** each with an owner by role (architect, ETL developer, DevOps).
- **Assumptions:** each `[A]`, and what changes if it's wrong.
- **Don't know:** each `[?]`, with who could answer.
