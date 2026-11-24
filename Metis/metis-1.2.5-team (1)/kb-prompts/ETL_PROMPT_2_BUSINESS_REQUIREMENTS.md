---
prompt_id: ETL-02
title: ETL business requirements (BRD)
kind: prompt
pipeline: etl
stage: 2
version: 2.1.0
shareable: true
requires: []
depends_on: [ETL-01]
placeholders: [PRODUCT_NAME, DOMAIN_CONTEXT, KB_ETL_DOCS, MODULE_NAME, MODULE_SOURCE, TEAM_ROSTER, RUN_DATE]
outputs: ["{{KB_ETL_DOCS}}/{{MODULE_NAME}}/01_ETL_BUSINESS_REQUIREMENTS.md"]
---

# ETL-02: ETL business requirements (BRD)

## Purpose

Explain what the {{PRODUCT_NAME}} ETL module `{{MODULE_NAME}}` does for the business, in words
a business analyst understands: what data moves, why, when, and who relies on it. Script, table
and column names go in the Evidence footnotes, not the body.

## Before you start

1. Render with the module: `prompts.py render ETL_PROMPT_2_BUSINESS_REQUIREMENTS.md --set MODULE_NAME=<name> --set MODULE_SOURCE=<folder>`. The module's source is in `{{MODULE_SOURCE}}`.
2. Read the domain context at `{{DOMAIN_CONTEXT}}`.
3. Read `{{KB_ETL_DOCS}}/{{MODULE_NAME}}/00_ETL_DISCOVERY_REPORT.md` in full. If it's missing,
   stop and run ETL-01.

## Steps

1. **One business process per ETL process** from the discovery report. Give each an ID
   (`BR-<n>`), and describe what it achieves, who benefits, what starts it, and what happens if it
   doesn't run.
2. **Translate code into business terms.** Some examples:

| When the code shows | Write something like |
|---|---|
| a lock or control file around a job | "Only one copy of this process can run at a time." |
| a status table the job updates | "The system records the progress of each run, so failures can be spotted." |
| a job copying staging tables to core tables | "Changes made in the application are copied to the main tables on a schedule." Give the timing only if it has a source. |
| a job that creates request rows after another job | "Requests are created automatically when the earlier calculation finishes." |
| an alert script on failure | "Operations staff are emailed when the process fails." |
| a current-row filter value | "The record is currently active." |
| a status column that moves through values | "Each request moves through set processing stages." |

3. **Business rules.** For each process: what it includes and leaves out, its thresholds, and
   its order of runs. Give its dependencies on other processes.
4. **Who relies on it.** The downstream systems, reports and teams, taken from the domain
   context or code.
5. **Coverage boundary.** What this repository does and what it leaves to other systems or jobs
   (for example, a calculation done upstream, or a schedule held in another tool).
6. **Glossary.** The business terms a reader meets in this document, each with a one-line meaning.
7. **Readability check.** Would a program manager follow every sentence? Does any sentence hold
   a file, table or column name? If so, move it to the footnote.

## Output

Write `{{KB_ETL_DOCS}}/{{MODULE_NAME}}/01_ETL_BUSINESS_REQUIREMENTS.md`, starting with:

```yaml
---
document: ETL business requirements
product: {{PRODUCT_NAME}}
module: {{MODULE_NAME}}
version: <n>
status: Draft, pending business analyst review
generated_date: {{RUN_DATE}}
layer: meaning
prompt_id: ETL-02
prompt_version: 2.1.0
---
```

Sections:

1. Summary
2. Coverage boundary
3. Business objectives
4. Processes (one subsection per `BR-<n>`)
5. Business rules
6. Dependencies and downstream users
7. Out of scope
8. Glossary

Then Open questions, Assumptions, Don't know, and Evidence footnotes. Take the reviewers from
the roster at `{{TEAM_ROSTER}}`, by role.

## Evidence rules

- Each process and rule has a footnote: `[E: <file>:<line>]` or `[E: domain context §<n>]`.
- A schedule, frequency or service level without a source is `[?]`.
- Anything taken as true without a source is `[A]` and goes on the Assumptions list.

## Self-check

- [ ] Every process in the discovery report has a `BR-<n>`.
- [ ] No file, table or column names appear in the body.
- [ ] Every timing has a source or is marked `[?]`.
- [ ] Every `[A]` and `[?]` is on its list.

## Open questions, assumptions and unknowns

End with three lists:

- **Open questions:** each with an owner from the roster, by role.
- **Assumptions:** each `[A]`, and what changes if it's wrong.
- **Don't know:** each `[?]`, with who could answer.
