---
name: loe
description: >
  LOE (level of effort) estimate for a requirement: requirement, gap and impact analysis, epics and
  stories, story points per layer (UI, API, DTL/Database, ETL, Integration, Infrastructure, QA/SIT, UAT)
  with a 10% buffer, a staffing plan and a timeline, in one tabbed HTML report. Read only: no code, no
  Jira writes. Runs the org playbook "Acme Claims: LOE Estimate — Requirement to Sized Backlog & Plan" (!loe).
  Invoke with: /loe <ACME-nnnn | Confluence page link | requirement text>
argument-hint: "<ACME-nnnn | Confluence page link | requirement text>"
visibility: internal
triggers:
  - user
  - model
invocations:
  - /loe
  - "!loe"
  - LOE estimate
  - level of effort
  - size this requirement
allowed-tools:
  - bash
  - read
---

# /loe — LOE estimate for a requirement

For leads (Delivery lead, Solution lead). Argus lists it under My tools as **LOE estimate**; it
starts a Devin Cloud session with `/loe <input>`.

## Input

One of: a Jira key (`ACME-nnnn`), a Confluence page link, an attached document, or plain requirement text.
If nothing is given, ask for it once and stop.

## Steps

1. Follow the org playbook **Acme Claims: LOE Estimate — Requirement to Sized Backlog & Plan** (macro `!loe`,
   `playbook-e7aed840992a4d7cabf05297ff85123c`) on the input. That playbook is the source of the method;
   do not change its scale or buffer here.
2. Read the requirement (Jira through the service account, Confluence through the service account),
   then do the requirement, gap and impact analysis it asks for.
3. Group the work into epics and stories and estimate story points per layer: UI, API, DTL/Database,
   ETL, Integration, Infrastructure, QA/SIT and UAT. Add the 10% buffer.
4. Build the staffing plan and the timeline.
5. Write one tabbed HTML report plus the markdown working files and attach them to the session.
   Anything a source does not say goes in the report's open questions and assumptions, not into a number.

## Rules

- Read only: no code changes, no commits, no Jira or Confluence writes.
- No approval gates: the report is the output; a lead decides what to do with it.
- Print `[SDLC] skill loe` when it starts and `[SDLC] artefact <report path>` when the report is attached.
