---
prompt_id: APP-15
title: Module UI specification
kind: prompt
pipeline: app
stage: 4
version: 2.0.0
shareable: true
requires: []
depends_on: [APP-01, APP-03]
placeholders: [PRODUCT_NAME, DOMAIN_CONTEXT, KB_MODULE_DOCS, MODULE_NAME, MODULE_SOURCE, RUN_DATE]
outputs: ["{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/07_UI_SPECIFICATION.md"]
---

# APP-15: Module UI specification

## Purpose

Describe every screen of a {{PRODUCT_NAME}} front-end module as it is built today: the layout,
the components on it, what each control does, and the rules for validation, loading, errors and
access. Designers, testers and developers use it to change a screen without re-reading the code.
It describes the code as it is, not a redesign.

## Before you start

1. Render with the module: `prompts.py render PROMPT_15_UI_SPECIFICATION.md --set MODULE_NAME=<name> --set MODULE_SOURCE=<folder>`. The module's source is in `{{MODULE_SOURCE}}`.
2. This prompt is only for modules that have screens. If `{{MODULE_SOURCE}}` has no pages,
   routes or screen components, write nothing, say so, and stop.
3. Read `{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/00_DISCOVERY_REPORT.md` (the route and component
   inventory) and `02_FUNCTIONAL_REQUIREMENTS.md` (behaviour, fields and messages). If either
   is missing, stop.
4. Read the domain context at `{{DOMAIN_CONTEXT}}` for screen names, roles and any user-guide
   extracts. If a component registry exists at `{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/12_COMPONENT_REGISTRY.yaml`,
   use it to find components; don't copy it.

## Steps

1. **Application shell.** The parts every screen shares: header, navigation, layout wrapper,
   notifications, and how the current user and their access are shown. Give the file for each.
2. **One section per screen.** Group screens by business area. For each screen, from the page or
   route file and the components it renders:
   - the route or entry point, and who can reach it (the access check in code);
   - the layout, top to bottom, naming each region;
   - each control: its label as written in code, type, whether it's required, default value,
     options and where the options come from (a constant, an API call or the domain context);
   - grids and tables: columns in order, sorting, filtering, paging and row actions;
   - validation: each rule and its message, as written in code;
   - loading, empty and error states, and what the user sees in each;
   - the service or API call behind each action, by function name.
3. **Shared components and patterns.** Components used on more than one screen, such as pop-ups,
   upload widgets or confirmation dialogs. Describe each once and refer back to it.
4. **Accessibility and responsiveness.** Only what the code shows: labels, roles, keyboard
   handling, breakpoints. Anything not in code is `[?]`, not a recommendation.
5. **Differences from the FRD.** Where the screen and the FRD disagree, list both with sources.
   Don't pick a winner.

## Output

Write `{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/07_UI_SPECIFICATION.md`, starting with:

```yaml
---
document: UI specification
product: {{PRODUCT_NAME}}
module: {{MODULE_NAME}}
version: <n>
status: Draft
generated_date: {{RUN_DATE}}
prompt_id: APP-15
prompt_version: 2.0.0
---
```

Sections:

1. Overview (framework and UI libraries from the package manifest, how screens are organised)
2. Application shell
3. One section per business area, with a sub-section per screen
4. Shared components and patterns
5. Accessibility and responsiveness
6. Differences from the FRD

Then Open questions, Assumptions, Don't know and Files read.

## Evidence rules

- Every screen, control, rule and message carries `[E: <file>:<line>]`.
- A label, option or message you haven't seen in code or the domain context is `[?]`. Never write
  a likely label.
- Anything taken as true without a source is `[A]` and goes on the Assumptions list.
- Don't describe screenshots you haven't seen. Mark the spot `[screenshot needed]` instead.

## Self-check

- [ ] Every route or page in the discovery report has a section, or is listed as not a screen.
- [ ] Every control label, option and message has a file and line.
- [ ] Every action names the service or API function it calls.
- [ ] Every `[A]` and `[?]` is on its list.

## Open questions, assumptions and unknowns

End with three lists:

- **Open questions:** each with an owner by role (business analyst, UX lead, front-end lead).
- **Assumptions:** each `[A]`, and what changes if it's wrong.
- **Don't know:** each `[?]`, with who could answer.
