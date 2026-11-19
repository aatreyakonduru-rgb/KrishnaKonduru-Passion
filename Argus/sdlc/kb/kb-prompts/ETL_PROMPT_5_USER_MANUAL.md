---
prompt_id: ETL-05
title: ETL operator manual
kind: prompt
pipeline: etl
stage: 5
version: 2.1.0
shareable: true
requires: []
depends_on: [ETL-03, ETL-04]
placeholders: [PRODUCT_NAME, DOMAIN_CONTEXT, KB_ETL_DOCS, MODULE_NAME, MODULE_SOURCE, RUN_DATE]
outputs: ["{{KB_ETL_DOCS}}/{{MODULE_NAME}}/04_ETL_USER_MANUAL.md"]
---

# ETL-05: ETL operator manual

## Purpose

Write the guide for the people who run and support `{{MODULE_NAME}}`. For each process it covers
how to start it by hand, how to tell it worked, how to check its status, and what to do when it
fails. The reader is an operator or support engineer, not a developer.

## Before you start

1. Render with the module: `prompts.py render ETL_PROMPT_5_USER_MANUAL.md --set MODULE_NAME=<name> --set MODULE_SOURCE=<folder>`. The module's source is in `{{MODULE_SOURCE}}`.
2. Read the domain context at `{{DOMAIN_CONTEXT}}`: its schedules, consoles and contacts.
3. Read `02_ETL_FUNCTIONAL_REQUIREMENTS.md` and `03_ETL_TECHNICAL_REQUIREMENTS.md` in
   `{{KB_ETL_DOCS}}/{{MODULE_NAME}}/`. Stop if either is missing.

## Steps

1. **Getting started.** The access an operator needs, by role (never real credentials). The
   config they may need to set, and where to find it.
2. **One section per process:**
   - what it does, in one sentence;
   - when it runs;
   - how to run it by hand, with the exact command or console action from the repo or the
     domain context;
   - its parameters;
   - how to check it worked, with a read-only status query and what a good result looks like;
   - common failures and what to do about each.
3. **Monitoring.** Where to look for logs, alerts and status tables, and what "normal" looks like.
4. **Troubleshooting.** A table: symptom, likely cause, check, fix, and who to escalate to.
5. **Job inventory.** A table of every job: name, what starts it, schedule (with source, or
   `[?]`), and the scripts it runs.
6. **Request or run lifecycle.** The status values a run or request moves through, as an
   operator sees them, and the read-only query that shows the current state.
7. **Schedules and alerts.** Where schedules are set and how to change one, and which alerts
   exist, who gets them, and what to do when one arrives.
8. **Extending a job.** How to add a new SQL file or step to an existing job, from how the
   current ones are wired up.
9. **Style.** Short numbered steps, exact commands in code blocks, and read-only checks first.

## Output

Write `{{KB_ETL_DOCS}}/{{MODULE_NAME}}/04_ETL_USER_MANUAL.md`, starting with:

```yaml
---
document: ETL operator manual
product: {{PRODUCT_NAME}}
module: {{MODULE_NAME}}
version: <n>
generated_date: {{RUN_DATE}}
prompt_id: ETL-05
prompt_version: 2.1.0
---
```

Sections:

1. Getting started
2. Job inventory
3. Run and request lifecycle
4. One section per process, including how to trigger a manual rerun
5. Schedules and alerts
6. Monitoring
7. Troubleshooting: common issues and fixes
8. Adding a new SQL file or step to a job

Then Open questions, Assumptions, Don't know and Sources used.

## Evidence rules

- Each command, query and status value is tagged `[E: <file>:<line>]` or `[E: domain context §<n>]`.
- A console, command or contact without a source is `[?]`, never a typical one.
- Anything taken as true without a source is `[A]` and goes on the Assumptions list.
- Status queries are read-only.

## Self-check

- [ ] Every process has a run, check and failure section.
- [ ] Every command and query has a source.
- [ ] No credentials appear.
- [ ] Every `[A]` and `[?]` is on its list.

## Open questions, assumptions and unknowns

End with three lists:

- **Open questions:** each with an owner by role (operations, ETL developer, DevOps).
- **Assumptions:** each `[A]`, and what changes if it's wrong.
- **Don't know:** each `[?]`, with who could answer.
