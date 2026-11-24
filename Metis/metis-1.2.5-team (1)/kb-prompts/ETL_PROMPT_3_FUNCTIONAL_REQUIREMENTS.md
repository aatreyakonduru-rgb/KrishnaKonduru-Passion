---
prompt_id: ETL-03
title: ETL functional requirements (FRD)
kind: prompt
pipeline: etl
stage: 3
version: 2.1.0
shareable: true
requires: []
depends_on: [ETL-01, ETL-02]
placeholders: [PRODUCT_NAME, DOMAIN_CONTEXT, KB_ETL_DOCS, MODULE_NAME, MODULE_SOURCE, RUN_DATE]
outputs: ["{{KB_ETL_DOCS}}/{{MODULE_NAME}}/02_ETL_FUNCTIONAL_REQUIREMENTS.md"]
---

# ETL-03: ETL functional requirements (FRD)

## Purpose

State what each process in `{{MODULE_NAME}}` must do, one testable requirement at a time. Each
requirement gives the trigger, the inputs, the selection rules, the outputs, the failure
handling, and the `BR` it serves. A tester can write a check from it, and a developer can find
the script and SQL behind it.

## Before you start

1. Render with the module: `prompts.py render ETL_PROMPT_3_FUNCTIONAL_REQUIREMENTS.md --set MODULE_NAME=<name> --set MODULE_SOURCE=<folder>`.
2. Read the domain context at `{{DOMAIN_CONTEXT}}`.
3. Read `00_ETL_DISCOVERY_REPORT.md` and `01_ETL_BUSINESS_REQUIREMENTS.md` in
   `{{KB_ETL_DOCS}}/{{MODULE_NAME}}/`. Stop if either is missing.
4. Read the scripts and SQL for each process, under `{{MODULE_SOURCE}}`.

## Steps

For each process, write one or more requirements, `FR-<nnn>`. Number them in blocks per
process, such as 001–009 and 010–019. Name each after its business function, not its file.
Each requirement has these parts:

1. **Trigger.** A schedule, an event, an upstream job or a manual run, with its source.
2. **Inputs.** The source tables and files, and the filters used, such as tenant, current-row
   and status.
3. **Processing rules.** Selection, joins, calculations, de-duplication, and the order of steps.
4. **Outputs.** The target tables and the operation (insert, merge, update, delete), plus the
   status values it sets and any trigger files or messages it sends.
5. **Concurrency.** Locks, control files, and what happens if two runs overlap.
6. **Failure handling.** What's caught, what's retried, who's alerted, and what state it leaves.
7. **Acceptance check.** A query or observation that proves the requirement was met.
8. **Links.** The `BR-<n>` it serves, and the files behind it.

Before the per-process sections, write a short overview and the coverage boundary (what this
repository does and what other jobs or systems do). After them, list the data-quality checks
and guard-rails the code applies (row counts, null checks, duplicate checks, thresholds), and
any non-functional constraints a file states, such as run windows, volumes or time limits.
A constraint no file states is `[?]`.

## Output

Write `{{KB_ETL_DOCS}}/{{MODULE_NAME}}/02_ETL_FUNCTIONAL_REQUIREMENTS.md`, starting with:

```yaml
---
document: ETL functional requirements
product: {{PRODUCT_NAME}}
module: {{MODULE_NAME}}
version: <n>
status: Draft
generated_date: {{RUN_DATE}}
layer: rules
prompt_id: ETL-03
prompt_version: 2.1.0
---
```

Sections:

1. Overview and coverage boundary
2. One section per process, with its requirements
3. Data-quality checks and guard-rails
4. Non-functional constraints
5. Cross-process dependencies and run order
6. BR-to-FR traceability

Then Open questions, Assumptions, Don't know and Files read.

## Evidence rules

- Each requirement has `[E: <file>:<line>]` for its trigger, inputs, rules and outputs.
- A trigger or schedule not in the repo or the domain context is `[?]`.
- Anything taken as true without a source is `[A]` and goes on the Assumptions list.
- Status and code values are copied from the SQL.

## Self-check

- [ ] Every process has at least one FR.
- [ ] Every FR has a trigger, inputs, outputs and failure handling, or says each is unknown.
- [ ] Every FR has an acceptance check.
- [ ] Every `BR-<n>` is covered.
- [ ] Every `[A]` and `[?]` is on its list.

## Open questions, assumptions and unknowns

End with three lists:

- **Open questions:** each with an owner by role (ETL developer, business analyst, operations).
- **Assumptions:** each `[A]`, and what changes if it's wrong.
- **Don't know:** each `[?]`, with who could answer.
