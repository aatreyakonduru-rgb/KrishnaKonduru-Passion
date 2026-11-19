---
prompt_id: APP-06
title: Module process documentation
kind: prompt
pipeline: app
stage: 6
version: 2.1.0
shareable: true
requires: []
depends_on: [APP-01, APP-02, APP-03, APP-04, APP-05]
placeholders: [PRODUCT_NAME, DOMAIN_CONTEXT, KB_MODULE_DOCS, MODULE_NAME, MODULE_SOURCE, RUN_DATE]
outputs: ["{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/05_PROCESS_DOCUMENTATION.md"]
---

# APP-06: Module process documentation

## Purpose

Describe the business processes that `{{MODULE_NAME}}` takes part in, end to end: who does
what, in what order, where it branches, where work is handed off, and what data ends up where.
Processes often cross modules, such as a screen, an API and a batch job. Say which part this
module plays.

## Before you start

1. Render with the module: `prompts.py render PROMPT_6_PROCESS_DOCUMENTATION.md --set MODULE_NAME=<name> --set MODULE_SOURCE=<folder>`. The module's source is in `{{MODULE_SOURCE}}`.
2. Read the domain context at `{{DOMAIN_CONTEXT}}`: its process list, roles, downstream systems
   and schedules.
3. Read this module's documents 00 to 04 in `{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/`. If 00 to 03
   are missing, stop.

## Steps

1. **Find the processes from the code.** Look for these patterns, and note the file for each:

| Code pattern | What it usually means |
|---|---|
| a status column with moves between values | an approval or lifecycle process |
| a submit, approve or reject handler | a review step with a hand-off |
| a job that copies UI tables to core tables | a sync process |
| a job that writes a trigger file or message | a hand-off to a downstream job |
| a scheduled email or alert script | a reminder or service-level process |
| a lock, control file or "in progress" flag | a guard against two runs at once |
| a "rerun" or "regenerate" handler | a manual recovery process |

   Treat each pattern as a lead. Check it in the code before you write it up as a process.
2. **Add the processes the domain context names.** Include the ones that span modules, and say
   which part runs in this module.
3. **For each process, write:**
   - a short overview;
   - a swim-lane diagram in text, one lane per actor or system;
   - a step table (step, actor, action, decision or branch, output);
   - the hand-offs, with what's passed and how;
   - the timing, only where a file or the domain context states it;
   - pain points you actually saw, such as manual steps, missing checks or long waits.
4. **Data written.** For each process step that saves data, add a table with these columns: user
   action, fields captured (as business labels), where the data lands (tables are fine in this
   section), and downstream consumer.
5. **Decision rules.** One table for the whole module: each rule that sends a process down one
   branch or another (condition, outcome, where it's enforced, source).

## Output

Write `{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/05_PROCESS_DOCUMENTATION.md`, starting with:

```yaml
---
document: Process documentation
product: {{PRODUCT_NAME}}
module: {{MODULE_NAME}}
version: <n>
status: Draft
generated_date: {{RUN_DATE}}
prompt_id: APP-06
prompt_version: 2.1.0
---
```

Sections:

1. Process overview: a table of the processes, their actors, their trigger, and this module's part
2. One section per process, with the parts from steps 3 and 4
3. Key decision rules table

Then Open questions, Assumptions, Don't know and Files read.

## Evidence rules

- Each step, hand-off and timing is tagged `[E: <file>:<line>]` or `[E: domain context §<n>]`.
- A schedule or service level that no file states is `[?]`. It's never an estimate written as fact.
- Anything taken as true without a source is `[A]` and goes on the Assumptions list.
- A process found only from a code pattern, with no business confirmation, has its purpose marked `[?]`.

## Self-check

- [ ] Every status lifecycle in the FRD is part of a process.
- [ ] Every save step has a data-written table.
- [ ] Every timing has a source or is marked `[?]`.
- [ ] Every `[A]` and `[?]` is on its list.

## Open questions, assumptions and unknowns

End with three lists:

- **Open questions:** each with an owner by role (business analyst, operations, tech lead).
- **Assumptions:** each `[A]`, and what changes if it's wrong.
- **Don't know:** each `[?]`, with who could answer.
