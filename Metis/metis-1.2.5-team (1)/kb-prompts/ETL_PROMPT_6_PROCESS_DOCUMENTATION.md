---
prompt_id: ETL-06
title: ETL runbooks and process documentation
kind: prompt
pipeline: etl
stage: 6
version: 2.0.0
shareable: true
requires: []
depends_on: [ETL-03, ETL-04, ETL-05]
placeholders: [PRODUCT_NAME, DOMAIN_CONTEXT, KB_ETL_DOCS, MODULE_NAME, MODULE_SOURCE, TEAM_ROSTER, RUN_DATE]
outputs: ["{{KB_ETL_DOCS}}/{{MODULE_NAME}}/05_ETL_PROCESS_DOCUMENTATION.md"]
---

# ETL-06: ETL runbooks and process documentation

## Purpose

Give support staff a runbook for each process in `{{MODULE_NAME}}`. Each runbook covers normal
operation, failure recovery, escalation, change handling and daily monitoring. It's the page
someone opens during an incident, so every step must be one they can actually do.

## Before you start

1. Render with the module: `prompts.py render ETL_PROMPT_6_PROCESS_DOCUMENTATION.md --set MODULE_NAME=<name> --set MODULE_SOURCE=<folder>`. The module's source is in `{{MODULE_SOURCE}}`.
2. Read the domain context at `{{DOMAIN_CONTEXT}}` and the roster at `{{TEAM_ROSTER}}`.
3. Read documents 02 to 04 in `{{KB_ETL_DOCS}}/{{MODULE_NAME}}/`. Stop if any is missing.

## Steps

1. **Process landscape.** A table of the processes: trigger, frequency, owner by role, and what
   depends on each. Include service levels only if a source states them.
2. **A runbook for each process.**
   - Normal operation: the trigger, the expected duration (with a source, or `[?]`), what
     success looks like, and the steps to watch it.
   - Failure recovery: the signs of failure (alerts, status values, log lines), then numbered
     recovery steps. Read-only checks come first, then safe retries, then data fixes that need
     approval.
   - Escalation: the condition, who to escalate to by role (names from the roster), and when.
3. **Change handling.** What counts as a change to a process, what to test first, and the
   deployment checklist, taken from the repo's deploy config and the domain context.
4. **Monitoring.** Daily and weekly checks, with read-only queries.

## Output

Write `{{KB_ETL_DOCS}}/{{MODULE_NAME}}/05_ETL_PROCESS_DOCUMENTATION.md`, starting with:

```yaml
---
document: ETL runbooks and process documentation
product: {{PRODUCT_NAME}}
module: {{MODULE_NAME}}
version: <n>
status: Draft
generated_date: {{RUN_DATE}}
layer: rules
prompt_id: ETL-06
prompt_version: 2.0.0
---
```

Sections:

1. Process landscape
2. Runbooks
3. Change handling
4. Monitoring

Then Open questions, Assumptions, Don't know and Files read.

## Evidence rules

- Each trigger, duration, signal and step is tagged `[E: <file>:<line>]` or `[E: domain context §<n>]`.
- A duration, service level or escalation contact without a source is `[?]`.
- Anything taken as true without a source is `[A]` and goes on the Assumptions list.
- Steps that change data are marked "needs approval" and name the approver role.

## Self-check

- [ ] Every process has a runbook with recovery and escalation.
- [ ] Every check query is read-only.
- [ ] Every timing has a source or is marked `[?]`.
- [ ] Every `[A]` and `[?]` is on its list.

## Open questions, assumptions and unknowns

End with three lists:

- **Open questions:** each with an owner from the roster.
- **Assumptions:** each `[A]`, and what changes if it's wrong.
- **Don't know:** each `[?]`, with who could answer.
