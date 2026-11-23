---
prompt_id: CTX-0A
title: "Domain context: business model"
kind: prompt
pipeline: context
stage: 0A
version: 2.0.0
shareable: true
requires: []
depends_on: []
placeholders: [PRODUCT_NAME, DOMAIN_CONTEXT_DIR, KB_ROOT, TEAM_ROSTER, RUN_DATE]
outputs: ["{{DOMAIN_CONTEXT_DIR}}/CONTEXT_0A_BUSINESS_MODEL.md"]
---

# CTX-0A: Domain context: business model

## Purpose

Describe what {{PRODUCT_NAME}} is for, who uses it, and how the business works. Every later prompt loads this module, so it can tell business terms from code terms and write requirements in the team's language.

## Before you start

1. Collect the team's source documents for this module: design documents, process guides,
   spreadsheets and wiki pages. List each one under Sources read. If a document named in these
   steps isn't supplied, ask for it, and treat what it would hold as `[?]` until it arrives.
2. Read what the knowledge base in `{{KB_ROOT}}` already says. Generated documents can
   confirm facts, but they don't replace the team's own sources.
3. If `{{DOMAIN_CONTEXT_DIR}}/CONTEXT_0A_BUSINESS_MODEL.md` exists, you're refreshing it. Keep its facts that still
   have a source, and record what changed.

## Steps

1. **What the product is.** One paragraph: what it does, for whom, and what would stop if it
   were switched off.
2. **The business model.** How the business makes decisions or money with it: the programs,
   products or contract types it supports, and how they differ.
3. **Main modules.** Each functional area of the product, what users do in it, and its key
   concepts, one short subsection each.
4. **User roles.** Each kind of user, what they're trying to get done, and which modules they use.
5. **Core workflows.** Each main end-to-end workflow, as numbered steps in business words, with
   its approval points.
6. **Screen patterns.** Patterns shared across screens, such as navigation, grids, filters,
   uploads and confirmations. Include them only if the source documents or the UI show them.
7. **Reference data.** The main lists the business uses, such as types, categories and codes,
   with their meaning. Copy them from a source, never from memory.
8. **Calculations.** Any business formula the product applies, copied from a design document,
   with its source.

## Output

Write `{{DOMAIN_CONTEXT_DIR}}/CONTEXT_0A_BUSINESS_MODEL.md`, starting with:

```yaml
---
document: Domain context: business model
product: {{PRODUCT_NAME}}
updated_date: {{RUN_DATE}}
prompt_id: CTX-0A
prompt_version: 2.0.0
---
```

Sections:

1. What the product is
2. Business model
3. Modules
4. User roles
5. Core workflows
6. Screen patterns
7. Reference data
8. Calculations

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
