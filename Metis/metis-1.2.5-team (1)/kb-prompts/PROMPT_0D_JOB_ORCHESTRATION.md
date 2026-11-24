---
prompt_id: CTX-0D
title: "Domain context: jobs and orchestration"
kind: prompt
pipeline: context
stage: 0D
version: 2.0.0
shareable: true
requires: []
depends_on: []
placeholders: [PRODUCT_NAME, DOMAIN_CONTEXT_DIR, KB_ROOT, TEAM_ROSTER, RUN_DATE]
outputs: ["{{DOMAIN_CONTEXT_DIR}}/CONTEXT_0D_JOB_ORCHESTRATION.md"]
---

# CTX-0D: Domain context: jobs and orchestration

## Purpose

Describe the batch side of {{PRODUCT_NAME}}: which jobs run, what starts them, how they depend on each other, how their requests and statuses are tracked, and how operators check on them. The ETL prompts load it first.

## Before you start

1. Collect the team's source documents for this module: design documents, process guides,
   spreadsheets and wiki pages. List each one under Sources read. If a document named in these
   steps isn't supplied, ask for it, and treat what it would hold as `[?]` until it arrives.
2. Read what the knowledge base in `{{KB_ROOT}}` already says. Generated documents can
   confirm facts, but they don't replace the team's own sources.
3. If `{{DOMAIN_CONTEXT_DIR}}/CONTEXT_0D_JOB_ORCHESTRATION.md` exists, you're refreshing it. Keep its facts that still
   have a source, and record what changed.

## Steps

1. **Job inventory.** Each job or process: what it does, its script folder, what starts it
   (a schedule, an event or an upstream job), and its frequency. A schedule is only given if a
   scheduler export or document shows it.
2. **Scheduler and runtime.** The tool that runs the jobs, and where. Say plainly if it isn't
   known.
3. **Dependencies.** Which jobs start which, and by what hand-off: a trigger file, a message, a
   status row or a schedule. Include a Mermaid diagram if the chain has more than three steps.
4. **Request and run tracking.** Any table that queues or tracks runs: its columns, its type
   codes and its status lifecycle, with the exact values.
5. **Job IDs.** How jobs are identified in each system. If a job has more than one ID (for
   example during a platform move), give both.
6. **Checking a job.** Read-only queries or console steps an operator uses to see if a job ran
   and how it did.
7. **Alerts and failure handling.** Who gets alerted, how, and the rerun steps.

## Output

Write `{{DOMAIN_CONTEXT_DIR}}/CONTEXT_0D_JOB_ORCHESTRATION.md`, starting with:

```yaml
---
document: Domain context: jobs and orchestration
product: {{PRODUCT_NAME}}
updated_date: {{RUN_DATE}}
layer: design
prompt_id: CTX-0D
prompt_version: 2.0.0
---
```

Sections:

1. Job inventory
2. Scheduler and runtime
3. Dependencies
4. Request and run tracking
5. Job IDs
6. Checking a job
7. Alerts and failure handling

Keep it short and factual. Other prompts load it into their context, so every line costs space.

## Evidence rules

- Every fact is tagged `[E: <document, page or slide>]`, `[E: <file>:<line>]` or `[E: <KB doc> §<n>]`.
- A fact the team told you in this session is `[E: stated by <role>, {{RUN_DATE}}]`. Ask for a document to back it, if one exists.
- A fact you couldn't source is `[?]`, never filled from general knowledge of the industry.
- Anything taken as true without a source is `[A]` and goes on the Assumptions list.
- Secrets, passwords, personal contact details beyond name and role, and real member or patient data never go in.

## Self-check

- [ ] Every section in the layout is filled in, or says `[?]` and who can answer.
- [ ] Every fact has a tag.
- [ ] Nothing was carried over from another team's context.
- [ ] Every `[A]` and `[?]` is on its list.

## Open questions, assumptions and unknowns

End the module with four lists:

- **Open questions:** each with an owner from the roster at `{{TEAM_ROSTER}}`.
- **Assumptions:** each `[A]`, and what changes if it's wrong.
- **Don't know:** each `[?]`, with who could answer.
- **Sources read:** every document, page and file used.
