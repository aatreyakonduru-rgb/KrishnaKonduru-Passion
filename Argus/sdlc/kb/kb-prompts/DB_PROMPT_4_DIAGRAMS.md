---
prompt_id: DB-04
title: Database architecture diagrams
kind: prompt
pipeline: db
stage: 4
version: 2.0.0
shareable: true
requires: []
depends_on: [DB-01, DB-03]
placeholders: [PRODUCT_NAME, KB_DB_DOCS, DB_SCHEMA, DB_ENV, RUN_DATE]
outputs: ["{{KB_DB_DOCS}}/03_DB_ARCHITECTURE_DIAGRAMS.md"]
---

# DB-04: Database architecture diagrams

## Purpose

Draw the {{PRODUCT_NAME}} database as Mermaid diagrams: how the schemas are layered, how the main
tables join, how records move through workflow and status stages, and how jobs link to each
other. The readers are anyone who needs the picture before the detail. Every box and arrow must
trace back to a query result. This stage can run at the same time as DB-05 and DB-06.

## Before you start

1. Render this prompt: `prompts.py render DB_PROMPT_4_DIAGRAMS.md --env <env>`.
2. Read `{{KB_DB_DOCS}}/00_DB_DISCOVERY_REPORT.md` and `{{KB_DB_DOCS}}/02_DB_TECHNICAL_REQUIREMENTS.md`.
   If either is missing, stop and ask.
3. This stage runs no queries.

## Steps

Draw each diagram below that the data supports. If the discovery report has nothing to draw
(for example, no status codes), leave the diagram out and say why in one line.

1. **Entity relationships** (`erDiagram`). Include tables with more than 100 estimated rows (Q3),
   plus any smaller table that is one end of a Q13 join. Show the join columns. Draw a solid line
   for a 0% orphan join, and note the rate on a join with orphans. Leave out links based only on
   a shared column name, or draw them dotted and label them unconfirmed.
2. **Schema layers** (`flowchart TD`). Staging or raw schemas, the base schema `{{DB_SCHEMA}}`,
   restricted view schemas and consumers, with object counts (Q1) and retention (Q2). Consumers
   come from DB-03's data flow section. Leave them out if it has none.
3. **Workflow staging** (`flowchart LR`). One chain per group of tables that share a base name
   with stage suffixes (DB-03 Design patterns). Label each arrow with its direction status: it's
   unconfirmed unless DB-03 cites a source.
4. **Status lifecycles** (`stateDiagram-v2`). One diagram per status column in Q12. The states are
   the observed values. Transitions are unconfirmed unless a source gives the order. If so, add a
   note saying where the order comes from.
5. **Job links** (`flowchart TD`). Job or request tables and the columns that link one job to
   another (DB-03 Design patterns). Show only the levels the data shows. Don't draw recursion
   unless the data has it.

Check each diagram against these rules before saving, and fix any failure:

1. Wrap node labels with spaces or symbols in quotes: `A["ORDERS (1,204 rows)"]`.
2. Use only these arrows: `||--o{`, `||--|{`, `-->`, `-.->`.
3. Entity names use underscores, not spaces.
4. State names have no hyphens. Write `IN_PROGRESS`, not `IN-PROGRESS`.
5. Split a diagram with more than 50 nodes and add `%% continued in diagram <n>b`.
6. In an ERD, use exactly-one cardinality only where Q8 shows a declared unique key.
7. Put every node in a relationship or a labelled subgraph.

## Output

Write `{{KB_DB_DOCS}}/03_DB_ARCHITECTURE_DIAGRAMS.md`, starting with:

```yaml
---
document: DB architecture diagrams
product: {{PRODUCT_NAME}}
schema: {{DB_SCHEMA}}
environment: {{DB_ENV}}
generated_date: {{RUN_DATE}}
inputs: [00_DB_DISCOVERY_REPORT.md, 02_DB_TECHNICAL_REQUIREMENTS.md]
prompt_id: DB-04
prompt_version: 2.0.0
---
```

Put a short paragraph before each diagram saying what it shows and what is unconfirmed. End each
diagram's code block with a sources comment:

```
%% Sources: DB-01 Q3 (row counts), Q13 (joins), Q8 (keys)
```

Then add Open questions, Assumptions, Don't know and Files read.

## Evidence rules

- Every table, column, state and arrow comes from a named query or DB-03 section.
- In the text around a diagram, tag facts `[E: DB-01 Q<n>]` or `[E: DB-03 <section>]`.
- Anything drawn without a source is `[A]` or `[?]`. Draw it dotted, label it and put it on its list.

## Self-check

- [ ] Every diagram passes the seven rules above.
- [ ] Every solid ERD line matches a Q13 join with its orphan rate.
- [ ] Every status value comes from Q12.
- [ ] Every dotted or unconfirmed element is on the Assumptions or Don't know list.
- [ ] Every diagram left out has a one-line reason.

## Open questions, assumptions and unknowns

End with three lists:

- **Open questions:** each names who can answer. Include each unconfirmed transition or direction.
- **Assumptions:** each `[A]`, and what changes in the diagram if it's wrong.
- **Don't know:** each `[?]`, with who could answer.
