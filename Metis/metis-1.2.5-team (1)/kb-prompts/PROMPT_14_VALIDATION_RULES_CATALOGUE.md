---
prompt_id: APP-14
title: Validation rules catalogue
kind: prompt
pipeline: app
stage: 14
version: 2.0.0
shareable: true
requires: []
depends_on: [APP-03, APP-05, APP-12]
placeholders: [PRODUCT_NAME, DOMAIN_CONTEXT, KB_MODULE_DOCS, MODULE_NAME, MODULE_SOURCE, RUN_DATE]
outputs: ["{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/14_VALIDATION_RULES_CATALOGUE.md"]
---

# APP-14: Validation rules catalogue

## Purpose

Collect every validation rule the `{{MODULE_NAME}}` screens enforce into one list, where each
row can be tested. QA writes test cases from it, requirement intake checks it before changing a
field, and new developers use it to learn how the forms behave. Run it for UI modules.

## Before you start

1. Render with the module: `prompts.py render PROMPT_14_VALIDATION_RULES_CATALOGUE.md --set MODULE_NAME=<name> --set MODULE_SOURCE=<folder>`.
2. Read the domain context at `{{DOMAIN_CONTEXT}}`: its screen field lists and shared UI patterns.
3. Read `02_FUNCTIONAL_REQUIREMENTS.md`, `12_COMPONENT_REGISTRY.yaml`, and
   `07_UI_SPECIFICATION.md` if it exists, in `{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/`.
4. Read the form and validation code under `{{MODULE_SOURCE}}`, such as form schemas, validators
   and submit handlers.

## Steps

Give each rule an ID (`VR-<CAT>-<nnn>`), the screen, the field, the rule, the trigger (on
change, on blur, on save), the message the user sees, and its source. Use these six categories:

1. **Required fields.** Fields that must always be filled in.
2. **Conditionally required fields.** Fields required only when another field has a value, or a
   toggle is on.
3. **Type and format.** Number only, date, list choice, length limits and patterns.
4. **Uniqueness and cross-field rules.** For example: two approvers must be different people, an
   end date comes after the start date, or no duplicate names.
5. **Status changes.** Which actions each status allows, and what's locked.
6. **Success and confirmation messages.** The exact text, and when it shows.

Then check the list against the code:

- Mark each rule found in code, found only in documents, or found in both.
- List every place the code and the documents disagree.

## Output

Write `{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/14_VALIDATION_RULES_CATALOGUE.md`, starting with:

```yaml
---
document: Validation rules catalogue
product: {{PRODUCT_NAME}}
module: {{MODULE_NAME}}
version: <n>
status: Draft
generated_date: {{RUN_DATE}}
layer: rules
prompt_id: APP-14
prompt_version: 2.0.0
---
```

Sections 1 to 6, one per category, each with this table:
`| ID | Screen | Field | Rule | Trigger | Message | Found in | Source |`

Then add a section for code-versus-document disagreements, then Open questions, Assumptions,
Don't know and Files read.

## Evidence rules

- Each rule has `[E: <file>:<line>]`, `[E: FRD FR-<id>]` or `[E: domain context §<n>]`.
- A rule found only in documents, and not seen in code, is marked "docs only". It is `[?]` if the code might differ.
- Anything taken as true without a source is `[A]` and goes on the Assumptions list.
- Messages are copied exactly, never reworded.

## Self-check

- [ ] Every form field in the component registry is covered by at least one rule, or listed as having none.
- [ ] Every conditional FR in the FRD appears in category 2.
- [ ] Every rule has a source.
- [ ] Every `[A]` and `[?]` is on its list.

## Open questions, assumptions and unknowns

End with three lists:

- **Open questions:** each with an owner by role (QA, business analyst, frontend developer).
- **Assumptions:** each `[A]`, and what changes if it's wrong.
- **Don't know:** each `[?]`, with who could answer.
