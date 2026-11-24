---
prompt_id: CTX-0E
title: "Domain context: team, glossary and sources"
kind: prompt
pipeline: context
stage: 0E
version: 2.0.0
shareable: true
requires: []
depends_on: []
placeholders: [PRODUCT_NAME, DOMAIN_CONTEXT_DIR, KB_ROOT, TEAM_ROSTER, RUN_DATE]
outputs: ["{{DOMAIN_CONTEXT_DIR}}/CONTEXT_0E_TEAM_GLOSSARY.md"]
---

# CTX-0E: Domain context: team, glossary and sources

## Purpose

Record who does what on the {{PRODUCT_NAME}} team, what the team's words mean, and which documents the context was built from. Prompts use it to route open questions to the right person and to use terms the way the team does.

## Before you start

1. Collect the team's source documents for this module: design documents, process guides,
   spreadsheets and wiki pages. List each one under Sources read. If a document named in these
   steps isn't supplied, ask for it, and treat what it would hold as `[?]` until it arrives.
2. Read what the knowledge base in `{{KB_ROOT}}` already says. Generated documents can
   confirm facts, but they don't replace the team's own sources.
3. If `{{DOMAIN_CONTEXT_DIR}}/CONTEXT_0E_TEAM_GLOSSARY.md` exists, you're refreshing it. Keep its facts that still
   have a source, and record what changed.

## Steps

1. **Team structure.** Take the roles and names from the roster at `{{TEAM_ROSTER}}`. Don't
   copy the roster. Say which role answers which kind of question: business rules, data, code,
   deployment, testing and security.
2. **Related teams.** Upstream and downstream teams, and what to ask each.
3. **Glossary.** Each business term, acronym and code word, with its meaning and, where it
   helps, the column or code value it maps to. Only include terms seen in a source.
4. **Field vocabulary.** For the main forms, each business field label and its meaning.
5. **Source documents.** Each document, spreadsheet or page the context was built from: its
   title, location (by name, not a private link with a token), date and owner.

## Output

Write `{{DOMAIN_CONTEXT_DIR}}/CONTEXT_0E_TEAM_GLOSSARY.md`, starting with:

```yaml
---
document: Domain context: team, glossary and sources
product: {{PRODUCT_NAME}}
updated_date: {{RUN_DATE}}
layer: meaning
prompt_id: CTX-0E
prompt_version: 2.0.0
---
```

Sections:

1. Team structure
2. Related teams
3. Glossary
4. Field vocabulary
5. Source documents

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
