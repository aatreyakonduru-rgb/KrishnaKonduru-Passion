---
prompt_id: DB-02
title: Database business requirements
kind: prompt
pipeline: db
stage: 2
version: 2.0.0
shareable: true
requires: []
depends_on: [DB-01]
placeholders: [PRODUCT_NAME, KB_DB_DOCS, DOMAIN_CONTEXT, SNOWFLAKE_DB, DB_SCHEMA, DB_ENV, RUN_DATE]
outputs: ["{{KB_DB_DOCS}}/01_DB_BUSINESS_REQUIREMENTS.md"]
---

# DB-02: Database business requirements

## Purpose

Explain, in plain business English, what the {{PRODUCT_NAME}} database holds and why. The
readers are product owners, business analysts, operations leads and compliance staff. They
should come away knowing which business areas the data supports, how work moves through it,
and what rules and controls it enforces. No SQL, no data types.

## Before you start

1. Render this prompt with the team's values: `prompts.py render DB_PROMPT_2_BRD.md --env <env>`.
2. Read these two inputs in full. If either is missing, stop and ask for it.
   - `{{KB_DB_DOCS}}/00_DB_DISCOVERY_REPORT.md` from DB-01. Check it covers `{{SNOWFLAKE_DB}}.{{DB_SCHEMA}}`
     in `{{DB_ENV}}` and has no unticked self-check items.
   - The domain context at `{{DOMAIN_CONTEXT}}`. It holds the business names, program or contract
     types, workflows, downstream consumers and team roles. If no path is set, stop and ask.
3. Use only the parts of the domain context that concern data. Skip screen layouts, API design
   and front-end details. This document is about the database.
4. This stage runs no queries.

## Steps

1. **Executive summary.** Two or three short paragraphs: what the system is, the business problem
   it solves, and who uses it. Users and roles come from the domain context.
2. **Business objectives.** List the objectives the data design visibly supports, each with the
   evidence that shows it. For example, history columns (DB-01 Q14) support auditability, and
   restricted view schemas (Q9, Q10) support protecting sensitive data. Don't list an objective
   that has no evidence.
3. **Business areas.** Take the business areas from the domain context. For each one:
   - describe it in one or two sentences;
   - list the tables that hold it, from the discovery report, with their estimated row counts;
   - list its coded values (Q12) with their business meaning. Take the meaning from the domain
     context only. If a code isn't explained there, show the raw code, tag it `[?]` and list it
     under Don't know. Never decode a code from its spelling.

   A table no area claims goes under "Not yet placed", tagged `[?]`.
4. **Business process flows.** For each workflow the domain context describes (for example
   onboarding, configuring, approving, running a calculation, bulk upload), list the steps and
   the tables each step touches. Say whether a step reads or writes only if a source shows it.
   Otherwise tag the direction `[?]`.
5. **What happens downstream.** List the systems and teams that consume this data, what each
   reads and why it matters, all from the domain context. For each schedule, cadence or SLA,
   give the source that states it. If the only source is someone's estimate, write it as an
   estimate, tag it `[A]` and name who should confirm it.
6. **Data relationships in business terms.** Use the joins from Q13. Describe a join with a 0%
   orphan rate as a confirmed link. A join with orphans is a link that has gaps, with the rate
   shown. A column name the tables merely share is not a relationship; tag it `[?]`.
7. **Compliance and security.** State what the discovery report shows: restricted view schemas
   and their comments (Q2, Q9), access policies (Q10), and data-classification or
   offshore-access header columns if Q6 found any. Don't describe how masking works unless a
   source shows it.
8. **Business rules.** Only rules evidenced by a column default, a code value or a statement in
   the domain context. Give each rule its source.
9. **Other supporting KB files.** If the team's knowledge base has other catalogues of these
   tables, such as a table catalogue or a requirement routing map, read them. Use them to
   confirm names and descriptions, and cite them by path.

## Output

Write `{{KB_DB_DOCS}}/01_DB_BUSINESS_REQUIREMENTS.md`, starting with:

```yaml
---
document: DB business requirements
product: {{PRODUCT_NAME}}
source_db: {{SNOWFLAKE_DB}}
schema: {{DB_SCHEMA}}
environment: {{DB_ENV}}
generated_date: {{RUN_DATE}}
inputs: [00_DB_DISCOVERY_REPORT.md, <domain context file>]
prompt_id: DB-02
prompt_version: 2.0.0
review: business analyst sign-off required before DB-03
---
```

Sections, in order: Executive summary, Business objectives, Business areas, Business process
flows, What happens downstream, Data relationships, Compliance and security, Business rules,
Open questions, Assumptions, Don't know, Files read.

## Evidence rules

- A fact from the discovery report is tagged with its query, such as `[E: DB-01 Q12]`.
- A fact from the domain context is tagged with the file and section, such as `[E: domain context §4]`.
- Anything taken as true without a source is `[A]`. It also goes on the Assumptions list.
- Anything not known is `[?]`. It also goes on the Don't know list.
- Words like "likely", "probably" or "about" with no source don't belong in this document.

## Self-check

- [ ] Both inputs were read, and both are listed under Files read.
- [ ] Every table in the discovery report is in a business area or under "Not yet placed".
- [ ] Every code shown has a meaning from the domain context, or is tagged `[?]`.
- [ ] Every schedule, cadence or SLA has a source, or is tagged `[A]` with who should confirm it.
- [ ] There's no SQL, no data types and no screen or API detail.
- [ ] Every `[A]` and `[?]` in the body is on its list.

## Open questions, assumptions and unknowns

End with three lists:

- **Open questions:** each names who can answer (business analyst, product owner, data owner).
- **Assumptions:** each `[A]`, why it was made and what changes if it's wrong.
- **Don't know:** each `[?]`, with who could answer.

Then add **Files read**: every input file actually opened.

The business analyst reviews this document before DB-03 starts.
