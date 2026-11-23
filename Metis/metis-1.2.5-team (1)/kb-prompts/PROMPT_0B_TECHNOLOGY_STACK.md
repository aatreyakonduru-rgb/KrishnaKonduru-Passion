---
prompt_id: CTX-0B
title: "Domain context: technology and infrastructure"
kind: prompt
pipeline: context
stage: 0B
version: 2.0.0
shareable: true
requires: []
depends_on: []
placeholders: [PRODUCT_NAME, DOMAIN_CONTEXT_DIR, KB_ROOT, TEAM_ROSTER, RUN_DATE]
outputs: ["{{DOMAIN_CONTEXT_DIR}}/CONTEXT_0B_TECHNOLOGY_STACK.md"]
---

# CTX-0B: Domain context: technology and infrastructure

## Purpose

Describe how {{PRODUCT_NAME}} is built and where it runs: the stack, the environments, access control, compliance rules and known technical debt. The application and ETL prompts use it to check what they find in code.

## Before you start

1. Collect the team's source documents for this module: design documents, process guides,
   spreadsheets and wiki pages. List each one under Sources read. If a document named in these
   steps isn't supplied, ask for it, and treat what it would hold as `[?]` until it arrives.
2. Read what the knowledge base in `{{KB_ROOT}}` already says. Generated documents can
   confirm facts, but they don't replace the team's own sources.
3. If `{{DOMAIN_CONTEXT_DIR}}/CONTEXT_0B_TECHNOLOGY_STACK.md` exists, you're refreshing it. Keep its facts that still
   have a source, and record what changed.

## Steps

1. **Stack.** Each layer (frontend, API, batch, database, messaging), with its language,
   framework and version. Take them from the repos' dependency files, or cite the KB discovery
   reports.
2. **Environments.** Each environment, what it's for, how code is promoted, and the region or
   platform. Use role names, not hosts. Account numbers and hosts belong in the team's own
   secure notes, not in the context.
3. **Build and deploy.** The CI/CD tool, the pipeline stages, and who approves each promotion.
4. **Access control.** Each role or group, what it can do, and where it's enforced (the identity
   provider, the API, the UI).
5. **Monitoring and logging.** The tools, and what they watch.
6. **Disaster recovery.** Recovery targets and failover steps, only if a document states them.
7. **Compliance rules.** Rules the product must never break, such as data privacy or retention
   rules, each with its source.
8. **Known technical debt.** Each item with its source and its owner.

## Output

Write `{{DOMAIN_CONTEXT_DIR}}/CONTEXT_0B_TECHNOLOGY_STACK.md`, starting with:

```yaml
---
document: Domain context: technology and infrastructure
product: {{PRODUCT_NAME}}
updated_date: {{RUN_DATE}}
prompt_id: CTX-0B
prompt_version: 2.0.0
---
```

Sections:

1. Stack
2. Environments
3. Build and deploy
4. Access control
5. Monitoring and logging
6. Disaster recovery
7. Compliance rules
8. Known technical debt

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
