---
prompt_id: ETL-11
title: ETL integration scenarios
kind: prompt
pipeline: etl
stage: 11
version: 2.0.0
shareable: true
requires: []
depends_on: [ETL-10]
placeholders: [PRODUCT_NAME, DOMAIN_CONTEXT, KB_ETL_DOCS, KB_MODULE_DOCS, KB_DB_DOCS, MODULE_NAME, MODULE_SOURCE, RUN_DATE]
outputs: ["{{KB_ETL_DOCS}}/{{MODULE_NAME}}/11_ETL_INTEGRATION_SCENARIOS.md"]
---

# ETL-11: ETL integration scenarios

## Purpose

Write end-to-end scenarios that follow data through the screen, the API, the database and this
ETL module to downstream systems, including what happens when a step fails. QA uses them as
integration tests. Support uses them to see where a problem could sit.

## Before you start

1. Render with the module: `prompts.py render ETL_PROMPT_11_INTEGRATION_SCENARIOS.md --set MODULE_NAME=<name> --set MODULE_SOURCE=<folder>`. The module's source is in `{{MODULE_SOURCE}}`.
2. Read the domain context at `{{DOMAIN_CONTEXT}}`.
3. Read these documents:
   - `10_ETL_MODULE_IO_SUMMARY.md` and `02_ETL_FUNCTIONAL_REQUIREMENTS.md` in `{{KB_ETL_DOCS}}/{{MODULE_NAME}}/`;
   - the process documents of the application modules in `{{KB_MODULE_DOCS}}`;
   - the lineage in `{{KB_DB_DOCS}}`.

## Steps

1. **Choose the scenarios.** Pick one per main business flow that passes through this module,
   plus at least one failure-and-recovery scenario for each process that has an alert or retry.
2. **For each scenario, write:**
   - its business purpose;
   - the actors (users, jobs, systems);
   - the preconditions;
   - numbered steps across the layers, naming the table, job or endpoint at each step;
   - the expected results;
   - the validation points, each with a read-only query or check;
   - the test data needed, described by shape and never as real records.
3. **Cross-layer notes.** For ETL with API, ETL with the database, and ETL with the UI, list the
   contracts each side depends on, such as a status value, a trigger file or a column.
4. **Test matrix.** Rows are scenarios, columns are layers, and each cell says what's checked.

## Output

Write `{{KB_ETL_DOCS}}/{{MODULE_NAME}}/11_ETL_INTEGRATION_SCENARIOS.md`, starting with:

```yaml
---
document: ETL integration scenarios
product: {{PRODUCT_NAME}}
module: {{MODULE_NAME}}
version: <n>
status: Draft
generated_date: {{RUN_DATE}}
prompt_id: ETL-11
prompt_version: 2.0.0
---
```

Sections:

1. Overview
2. Scenarios
3. Cross-layer notes
4. Test matrix
5. Test data needs

Then Open questions, Assumptions, Don't know and Files read.

## Evidence rules

- Each step is tagged `[E: <doc> §<n>]` or `[E: <file>:<line>]`.
- An expected timing, such as "within N minutes", needs a source, or is marked `[?]`.
- Anything taken as true without a source is `[A]` and goes on the Assumptions list.
- Test data never includes real member, patient or provider records.

## Self-check

- [ ] Every process has at least one scenario.
- [ ] Every alerting process has a failure scenario.
- [ ] Every validation point is read-only.
- [ ] Every `[A]` and `[?]` is on its list.

## Open questions, assumptions and unknowns

End with three lists:

- **Open questions:** each with an owner by role (QA, ETL developer, API developer).
- **Assumptions:** each `[A]`, and what changes if it's wrong.
- **Don't know:** each `[?]`, with who could answer.
