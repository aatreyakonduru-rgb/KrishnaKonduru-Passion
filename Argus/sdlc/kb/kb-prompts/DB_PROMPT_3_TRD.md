---
prompt_id: DB-03
title: Database technical requirements
kind: prompt
pipeline: db
stage: 3
version: 2.0.0
shareable: true
requires: []
depends_on: [DB-01, DB-02]
placeholders: [PRODUCT_NAME, KB_DB_DOCS, DOMAIN_CONTEXT, SNOWFLAKE_DB, DB_SCHEMA, DB_ENV,
               DB_ACTIVE_FILTER_COLUMN, DB_ACTIVE_FILTER_VALUE, RUN_DATE]
outputs: ["{{KB_DB_DOCS}}/02_DB_TECHNICAL_REQUIREMENTS.md"]
---

# DB-03: Database technical requirements

## Purpose

Describe how the {{PRODUCT_NAME}} database is built: layers, tables, keys, joins, design
patterns, security and volumes. The readers are database developers, data engineers,
architects and DBAs. It is the reference they check before changing a table or writing a query.

## Before you start

1. Render this prompt: `prompts.py render DB_PROMPT_3_TRD.md --env <env>`.
2. Read these inputs. If one is missing, stop and ask.
   - `{{KB_DB_DOCS}}/00_DB_DISCOVERY_REPORT.md` (DB-01)
   - `{{KB_DB_DOCS}}/01_DB_BUSINESS_REQUIREMENTS.md` (DB-02), signed off by the business analyst.
     If the sign-off isn't recorded, ask before going on.
   - The domain context at `{{DOMAIN_CONTEXT}}`, used only for data flows and job descriptions.
3. This stage runs no new queries. If a number you need isn't in the discovery report, tag it
   `[?]` and say which DB-01 query would provide it.

## Steps

1. **Architecture.** Describe the database and its schemas (Q1, Q2): what each schema holds,
   object counts, retention and managed-access settings. Say which schemas are the base layer,
   which are staging and which are restricted views.
2. **Tables by volume.** List every table in `{{DB_SCHEMA}}`, largest first, with estimated rows
   and column counts (Q3, Q4). Say the row counts are metadata estimates. Give full detail for
   the ten largest and one line each for the rest.
3. **Table classes.** Put each table in one class: reference, configuration, transactional,
   workflow staging, result, system or audit, or definition. Base each call on something you can
   point to: the name pattern, the columns or the domain context. If none applies, tag it `[?]`.
4. **Keys and joins.**
   - Declared primary and unique keys (Q8). If there are none, say so. Many warehouses don't
     declare keys.
   - Join paths with their orphan rates (Q13), as a table: left table, right table, key, orphan %.
     A 0% join is confirmed. A join with orphans is confirmed with gaps, and goes on the Open
     questions list.
   - How to pick current rows: `{{DB_ACTIVE_FILTER_COLUMN}} = '{{DB_ACTIVE_FILTER_VALUE}}'`, with the
     active and historical split per table (Q14). List any table that keeps history a different
     way, and any history table where every row is current.
5. **Design patterns.** Only patterns the discovery report shows:
   - the shared header columns, with their positions and defaults (Q6);
   - the history pattern (Q14);
   - workflow staging patterns, where tables share a base name with different stage suffixes (Q3);
   - job or request tables and how they link to each other, using only the columns and code
     values in Q5, Q12 and Q13. Describe the links as the data shows them. Don't call it a
     graph, tree or DAG unless the data shows one;
   - code-set and definition-table patterns (Q12).
6. **Data flow.** How data enters, moves through and leaves the schema, from the domain context
   and, if the team has one, the ETL section of the knowledge base. For each schedule, give its
   source. If no source states it, tag it `[?]`.
7. **Security model.** Restricted view schemas and view counts (Q9), row access and masking
   policies (Q10), and classification header columns (Q6). Detail belongs in DB-06; summarise here.
8. **Naming conventions.** The table prefixes and column suffixes that actually occur, with how
   many tables or columns use each (Q3, Q4). Decode an abbreviation only when the domain context
   defines it.
9. **Volumes.** Total tables, columns and estimated rows, the five largest tables and the five
   widest (Q3, Q4).
10. **Integration points.** Tables that record calls to or from other systems, such as trigger,
    sync or downstream-job tables, found by name or by the domain context. Tag the direction `[?]`
    unless a source shows it.
11. **Empty tables.** List every table with no rows (Q3). Don't say why they're empty.

## Output

Write `{{KB_DB_DOCS}}/02_DB_TECHNICAL_REQUIREMENTS.md`, starting with:

```yaml
---
document: DB technical requirements
product: {{PRODUCT_NAME}}
source_db: {{SNOWFLAKE_DB}}
schema: {{DB_SCHEMA}}
environment: {{DB_ENV}}
generated_date: {{RUN_DATE}}
inputs: [00_DB_DISCOVERY_REPORT.md, 01_DB_BUSINESS_REQUIREMENTS.md, <domain context file>]
prompt_id: DB-03
prompt_version: 2.0.0
review: developer and business analyst review required before DB-04, DB-05 and DB-06
---
```

Sections, in order: Architecture, Tables by volume, Table classes, Keys and joins, Design
patterns, Data flow, Security model, Naming conventions, Volumes, Integration points, Empty
tables, Open questions, Assumptions, Don't know, Files read.

## Evidence rules

- Facts from discovery are tagged with their query, such as `[E: DB-01 Q13]`.
- Facts from the BRD or domain context cite the file and section.
- Anything taken as true without a source is `[A]` and goes on the Assumptions list.
- Anything not known is `[?]` and goes on the Don't know list.
- Every number (count, position, orphan rate) comes from a query result, not from memory or an
  earlier version of this document.

## Self-check

- [ ] Every table in the discovery report appears in Tables by volume and in Table classes.
- [ ] Every join in DB-01 Q13 is in the join table with its orphan rate.
- [ ] Every pattern described points to the query that shows it.
- [ ] No schedule or cadence is stated without a source.
- [ ] Every `[A]` and `[?]` in the body is on its list.

## Open questions, assumptions and unknowns

End with three lists:

- **Open questions:** each names who can answer (DBA, data engineer, data owner). Include every
  join with orphans and every table whose class is `[?]`.
- **Assumptions:** each `[A]`, why it was made and what changes if it's wrong.
- **Don't know:** each `[?]`, with who could answer.

Then add **Files read**.
