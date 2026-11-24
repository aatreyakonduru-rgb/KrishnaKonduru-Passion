---
prompt_id: ETL-04
title: ETL technical requirements (TRD)
kind: prompt
pipeline: etl
stage: 4
version: 2.0.0
shareable: true
requires: []
depends_on: [ETL-01, ETL-03]
placeholders: [PRODUCT_NAME, DOMAIN_CONTEXT, KB_ETL_DOCS, MODULE_NAME, MODULE_SOURCE, RUN_DATE]
outputs: ["{{KB_ETL_DOCS}}/{{MODULE_NAME}}/03_ETL_TECHNICAL_REQUIREMENTS.md"]
---

# ETL-04: ETL technical requirements (TRD)

## Purpose

Describe how `{{MODULE_NAME}}` is built and run, so a developer can change it safely: the stack,
how it connects to the database, the SQL patterns, credentials, error handling, logging,
concurrency, deployment and scheduling. Each section points back to the FRs it supports.

## Before you start

1. Render with the module: `prompts.py render ETL_PROMPT_4_TECHNICAL_REQUIREMENTS.md --set MODULE_NAME=<name> --set MODULE_SOURCE=<folder>`.
2. Read the domain context at `{{DOMAIN_CONTEXT}}`.
3. Read `00_ETL_DISCOVERY_REPORT.md` and `02_ETL_FUNCTIONAL_REQUIREMENTS.md` in
   `{{KB_ETL_DOCS}}/{{MODULE_NAME}}/`. Stop if either is missing.
4. Read the scripts, the shared helpers and the job or deploy config under `{{MODULE_SOURCE}}`.

## Steps

1. **Stack.** Language and version, libraries and their versions, and the runtime (a container,
   a serverless function, a managed job service), all from files.
2. **Architecture.** The components, how they call each other, and the data flow.
3. **Database connection.** The driver, how the connection is opened, where credentials come from
   (by name only, never the value), the role or warehouse settings, and any session settings.
4. **SQL patterns.** How SQL is loaded (from the repo, from storage, or inline), how parameters
   are passed, and the transaction and commit handling. Include the standard header columns and
   filters.
5. **Security.** Credential storage, access control, encryption settings and certificate checks,
   from the code and config.
6. **Error handling.** Which exceptions are caught, the retries (count and delay, from code),
   the exit codes, and the alerts.
7. **Logging.** What's logged and where it goes. Name the destination only if a file says so.
8. **Concurrency.** Locks, control files, and parallel steps.
9. **Deployment and scheduling.** How jobs are packaged and started, what's in the repo, and
   what's only held elsewhere. For anything held elsewhere, write `[?]` and say who holds it.
10. **Technical debt**, with file and line.
11. **FR traceability.**

For each of these topics, only write what you read in this session: log destination, retry
behaviour, pool or connection sizes, schedule, service levels and error formats. If you didn't
read it, write `Not found in source [?]`.

## Output

Write `{{KB_ETL_DOCS}}/{{MODULE_NAME}}/03_ETL_TECHNICAL_REQUIREMENTS.md`, starting with:

```yaml
---
document: ETL technical requirements
product: {{PRODUCT_NAME}}
module: {{MODULE_NAME}}
version: <n>
status: Draft
generated_date: {{RUN_DATE}}
layer: design
prompt_id: ETL-04
prompt_version: 2.0.0
---
```

Sections 1 to 11, following the steps. Then Open questions, Assumptions, Don't know and Files read.

## Evidence rules

- Every technical fact is tagged `[E: <file>:<line>]`.
- Secret values are never copied. Name the key, and say where it's read.
- Anything taken as true without a source is `[A]` and goes on the Assumptions list.
- A general best-practice statement is never a stand-in for a missing source.

## Self-check

- [ ] Every script in the discovery report appears in some section.
- [ ] Retry, logging and schedule facts have sources, or are marked `[?]`.
- [ ] No secret values appear anywhere.
- [ ] Every FR is in the traceability table.
- [ ] Every `[A]` and `[?]` is on its list.

## Open questions, assumptions and unknowns

End with three lists:

- **Open questions:** each with an owner by role (ETL developer, DevOps, database engineer).
- **Assumptions:** each `[A]`, and what changes if it's wrong.
- **Don't know:** each `[?]`, with who could answer.
