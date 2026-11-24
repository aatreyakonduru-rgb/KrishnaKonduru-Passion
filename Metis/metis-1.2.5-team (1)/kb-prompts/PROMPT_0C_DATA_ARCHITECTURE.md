---
prompt_id: CTX-0C
title: "Domain context: data architecture"
kind: prompt
pipeline: context
stage: 0C
version: 2.0.0
shareable: true
requires: []
depends_on: []
placeholders: [PRODUCT_NAME, DOMAIN_CONTEXT_DIR, KB_ROOT, TEAM_ROSTER, RUN_DATE]
outputs: ["{{DOMAIN_CONTEXT_DIR}}/CONTEXT_0C_DATA_ARCHITECTURE.md"]
---

# CTX-0C: Domain context: data architecture

## Purpose

Describe how {{PRODUCT_NAME}}'s data is organised: the databases and schemas, how data moves between layers, the main tables, the naming patterns, and who reads the data downstream. The DB and ETL prompts load it before they touch the database.

## Before you start

1. Collect the team's source documents for this module: design documents, process guides,
   spreadsheets and wiki pages. List each one under Sources read. If a document named in these
   steps isn't supplied, ask for it, and treat what it would hold as `[?]` until it arrives.
2. Read what the knowledge base in `{{KB_ROOT}}` already says. Generated documents can
   confirm facts, but they don't replace the team's own sources.
3. If `{{DOMAIN_CONTEXT_DIR}}/CONTEXT_0C_DATA_ARCHITECTURE.md` exists, you're refreshing it. Keep its facts that still
   have a source, and record what changed.

## Steps

1. **Layers.** Each database or schema, what it holds (raw, staging, core, reporting,
   restricted views), and how data moves between layers.
2. **Application write path.** How a change made in the application reaches the core tables:
   directly, or through staging tables and a sync job. Give the timing only if a source says it.
3. **Main tables.** For each main table: what one row represents, its key, and its owner.
   Group the tables by business area.
4. **Naming and design patterns.** Table prefixes, column suffixes, standard header columns,
   current-row markers, history handling and tenant filters.
5. **Sensitive data.** Which data is restricted, and how: masked views, access policies or
   separate schemas.
6. **Business rules seen in the data.** Rules confirmed by data or DB documents, each with its
   source.
7. **Downstream users.** Each system or team that reads the data, and what it reads.

## Output

Write `{{DOMAIN_CONTEXT_DIR}}/CONTEXT_0C_DATA_ARCHITECTURE.md`, starting with:

```yaml
---
document: Domain context: data architecture
product: {{PRODUCT_NAME}}
updated_date: {{RUN_DATE}}
layer: design
prompt_id: CTX-0C
prompt_version: 2.0.0
---
```

Sections:

1. Layers
2. Application write path
3. Main tables
4. Naming and design patterns
5. Sensitive data
6. Business rules seen in the data
7. Downstream users

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
