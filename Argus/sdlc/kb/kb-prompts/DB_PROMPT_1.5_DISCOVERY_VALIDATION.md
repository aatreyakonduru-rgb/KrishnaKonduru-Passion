---
prompt_id: DB-01A
title: Discovery validation gate
kind: prompt
pipeline: db
stage: 1.5
version: 2.0.0
shareable: true
requires: []
depends_on: [DB-01]
placeholders: [PRODUCT_NAME, KB_DB_DOCS, DOMAIN_CONTEXT, TEAM_ROSTER, SNOWFLAKE_DB, DB_SCHEMA, DB_ENV,
               DB_SCHEMA_LIST, DB_ACTIVE_FILTER_COLUMN, DB_ACTIVE_FILTER_VALUE, DB_KNOWN_JOINS,
               DB_PRIORITY_CODE_COLUMNS, RUN_DATE]
outputs: ["{{KB_DB_DOCS}}/DISCOVERY_VALIDATION_LOG.md"]
---

# DB-01A: Discovery validation gate

## Purpose

Check what the team *believes* about the {{PRODUCT_NAME}} database against what discovery found,
before anything is written on top of it. The beliefs live in the team profile and the domain
context: the schemas, the current-row filter, the known joins, the code columns and the business
code values. Every mismatch becomes a question a reviewer can answer on its own, without opening
any other file. Nothing moves to DB-02 while a blocking question is open.

## Before you start

1. Render this prompt: `prompts.py render DB_PROMPT_1.5_DISCOVERY_VALIDATION.md --env <env>`.
2. Read `{{KB_DB_DOCS}}/00_DB_DISCOVERY_REPORT.md` and the domain context at `{{DOMAIN_CONTEXT}}`.
   If either is missing, stop and ask.
3. Read the team roster at `{{TEAM_ROSTER}}` to assign questions. If no roster is set, assign by
   role only (DBA, data engineer, business analyst) and say so.
4. This stage runs no queries.

## Steps

Compare each belief below with the discovery report. Record a result for every one, even when
it matches.

1. **Schemas.** The profile expects: {{DB_SCHEMA_LIST}}. Check each one against Q1. Report any
   that are missing, and any extra schema Q1 found.
2. **Header columns.** Does Q6 show shared header columns? Do later prompts or the domain context
   name header columns that Q6 didn't find?
3. **Current-row filter.** The profile says current rows have
   `{{DB_ACTIVE_FILTER_COLUMN}} = '{{DB_ACTIVE_FILTER_VALUE}}'`. Using Q14, list the tables that keep
   history some other way or don't keep it at all. Using Q7, check the column's default matches
   the value, including its type.
4. **Known joins.** The profile lists:

{{DB_KNOWN_JOINS}}

   Using Q13, report each join's orphan rate. Flag any join over 5% orphans, and any listed
   column that doesn't exist.
5. **Where status lives.** For each status or code column the domain context talks about, find
   which table actually holds it (Q5, Q12). A status held on a separate table changes every
   query that reads it.
6. **Priority code columns.** The profile lists:

{{DB_PRIORITY_CODE_COLUMNS}}

   Check each one exists and has values (Q12).
7. **Code values.** Compare the values in Q12 with the values the domain context defines. List
   values found but not defined, and values defined but not found.
8. **Keys.** Using Q8, note which main tables have no declared key. Those rely on the Q13 orphan
   checks alone.
9. **Access.** Using Q10, do row access policies exist? If the domain context says rows are
   filtered in the application, and policies also exist, ask which one is authoritative.
10. **Empty tables.** Using Q3, list the empty tables that the domain context describes as in
    use. Ask whether they're cleared after processing or not used yet.
11. **Row counts.** Say that row counts are metadata estimates. Flag any count that later stages
    use as a threshold.

Sort each mismatch into a class:

| Class | Meaning | Blocks |
|---|---|---|
| P1 | Wrong structure would follow in the business document | DB-02 |
| P2 | Wrong technical detail would follow in DB-03 to DB-06 | DB-03 |
| P3 | A minor inaccuracy | Nothing. Carry on with a note. |
| Fix | A factual correction to the profile or domain context, such as a renamed column. No human input is needed. | Nothing. Record the correction. |

## Output

Write `{{KB_DB_DOCS}}/DISCOVERY_VALIDATION_LOG.md`, starting with:

```yaml
---
document: DB discovery validation log
product: {{PRODUCT_NAME}}
source_db: {{SNOWFLAKE_DB}}
schema: {{DB_SCHEMA}}
environment: {{DB_ENV}}
generated_date: {{RUN_DATE}}
prompt_id: DB-01A
prompt_version: 2.0.0
status: <open, with the number of blocking items | clear>
---
```

Then, in order:

1. **About this database.** Five to ten plain sentences so a reviewer with no other file
   understands the schema: what it is for, how many tables, and the main patterns found.
2. **How to answer.** Write under each item's "Answer" line. A one-line answer is fine.
3. **Summary table:** item, class, topic, assigned to, status.
4. **One block per mismatch:**

   ```markdown
   ## DV-<n> · <class> · <short title>

   **Question:** <one clear question>
   **What we found:** <the facts, stated in full: table and column names, values, counts>
   **What the team profile or domain context says:** <the belief it contradicts>
   **What the schema can't tell us:** <the gap>
   **What we need from you:**
   1. <an answer that fits in one or two sentences>
   **Assigned to:** <name and role from the roster, or role only>
   **If this is wrong:** <which later documents are affected>
   **Status:** Open
   **Answer:**
   ```

5. **Gate decision:** tick boxes for each P1 item before DB-02, and each P2 item before DB-03.
6. **Fixes made:** each Fix item and the file it changes.
7. Open questions, Assumptions, Don't know.

If nothing mismatches, write a short log that says the gate is clear and lists the checks done.

## Evidence rules

- Each "What we found" fact carries its query tag, such as `[E: DB-01 Q14]`, and states the fact in
  full. Never write only "see Q14", because the reviewer won't have the report.
- Each belief cites where it came from: `[E: team profile db.known_joins]` or `[E: domain context §<n>]`.
- Anything taken as true without a source is `[A]` and goes on the Assumptions list.
- Anything not known is `[?]` and goes on the Don't know list.

## Self-check

- [ ] All eleven checks have a result.
- [ ] Every block can be answered without opening another file.
- [ ] Every block has a class and an owner.
- [ ] Every P1 and P2 item is in the gate decision.
- [ ] No data values, people's details beyond the roster or credentials were copied.
- [ ] Every `[A]` and `[?]` is on its list.

## Open questions, assumptions and unknowns

The DV blocks are the open questions. End with:

- **Assumptions:** each `[A]`, and what changes if it's wrong.
- **Don't know:** each `[?]`, with who could answer.
