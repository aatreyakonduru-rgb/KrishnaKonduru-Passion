---
prompt_id: APP-05
title: Module user manual
kind: prompt
pipeline: app
stage: 5
version: 2.0.0
shareable: true
requires: []
depends_on: [APP-02, APP-03]
placeholders: [PRODUCT_NAME, DOMAIN_CONTEXT, KB_MODULE_DOCS, MODULE_NAME, MODULE_SOURCE, RUN_DATE]
outputs: ["{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/04_USER_MANUAL.md"]
---

# APP-05: Module user manual

## Purpose

Write the guide a new {{PRODUCT_NAME}} user reads on their first day. For each screen or feature
it covers what it's for, who uses it, how to use it step by step, and what can go wrong. The
manual contains no code, APIs, database names or JSON.

## Before you start

1. Render with the module: `prompts.py render PROMPT_5_USER_MANUAL.md --set MODULE_NAME=<name> --set MODULE_SOURCE=<folder>`. The module's source is in `{{MODULE_SOURCE}}`.
2. Read the domain context at `{{DOMAIN_CONTEXT}}`: the glossary, the roles, the navigation, and
   any field lists or user-guide extracts it holds.
3. Read `{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/01_BUSINESS_REQUIREMENTS.md` (roles and
   capabilities) and `02_FUNCTIONAL_REQUIREMENTS.md` (behaviour, fields and messages). If
   either is missing, stop.

## Steps

1. **Pick the audience from the module type:**

| What the module is | Who the manual is for | Focus |
|---|---|---|
| Screens with grids, dashboards and forms | business users | each screen, from start to finish |
| Backend for those screens | business users, through the screens it supports | the capabilities, not the mechanics |
| Batch or ETL scripts | operations staff | what each process does, when it runs, and what to check when it fails |
| Admin screens | administrators | setup tasks and their effects |

2. **Getting started.** How to log in (the identity provider, by name only, from config), how to
   get around, and what each access level sees.
3. **One section per capability.** For each screen or feature: what it does, who uses it, and
   numbered steps with the exact labels from the code or the domain context. Also give each
   field's meaning, whether it's required, and its options. Give the messages the user sees, and
   what to do when something goes wrong.
4. **Reuse the domain context's field lists in full.** If the domain context or a user guide it
   cites lists every field, dropdown option and condition for a screen, reproduce that list. Don't
   summarise it.
5. **Shared UI patterns.** Explain any pattern that repeats across screens once, such as a clear
   icon, a multi-value pop-up, a nested-data pop-up or a save message. Then refer back to it.
6. **Glossary.** Define each business term the first time it's used, using the domain context
   glossary.
7. **Style.** Plain English, present tense ("Users select…"), short numbered steps.

## Output

Write `{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/04_USER_MANUAL.md`, starting with:

```yaml
---
document: User manual
product: {{PRODUCT_NAME}}
module: {{MODULE_NAME}}
version: <n>
audience: <from step 1>
generated_date: {{RUN_DATE}}
layer: meaning
prompt_id: APP-05
prompt_version: 2.0.0
---
```

Sections:

1. Introduction (purpose, who uses it, key concepts)
2. Getting started (logging in, navigation, access levels)
3. One section for each capability
4. Shared screen patterns
5. Troubleshooting and messages
6. Glossary

Then Open questions, Assumptions, Don't know and Sources used. Sources go at the end, not in the
steps.

## Evidence rules

- Each section ends with a source note: `[E: <file>]`, `[E: FRD FR-<id>]` or `[E: domain context §<n>]`.
- A label, option or message that you haven't seen in code or the domain context is `[?]`. Never write a likely label.
- Anything taken as true without a source is `[A]` and goes on the Assumptions list.
- Screenshots aren't made up. If a screenshot would help, mark the spot `[screenshot needed]`.

## Self-check

- [ ] Every capability in the BRD has a section, or is listed as not user-facing.
- [ ] Every label and message matches the code or the domain context.
- [ ] There are no code, API, table or column names in the steps.
- [ ] Every `[A]` and `[?]` is on its list.

## Open questions, assumptions and unknowns

End with three lists:

- **Open questions:** each with an owner by role (business analyst, product owner, a trainer).
- **Assumptions:** each `[A]`, and what changes if it's wrong.
- **Don't know:** each `[?]`, with who could answer.
