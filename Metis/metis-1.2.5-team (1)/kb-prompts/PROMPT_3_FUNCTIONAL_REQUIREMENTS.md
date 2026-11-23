---
prompt_id: APP-03
title: Module functional requirements (FRD)
kind: prompt
pipeline: app
stage: 3
version: 2.1.0
shareable: true
requires: []
depends_on: [APP-01, APP-02]
placeholders: [PRODUCT_NAME, DOMAIN_CONTEXT, KB_MODULE_DOCS, MODULE_NAME, MODULE_SOURCE, RUN_DATE]
outputs: ["{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/02_FUNCTIONAL_REQUIREMENTS.md"]
---

# APP-03: Module functional requirements (FRD)

## Purpose

State what `{{MODULE_NAME}}` must do, one testable requirement at a time, in "the system shall"
form. A tester should be able to write a test from each requirement, and a developer should be
able to find the code behind it. Each requirement traces back to a business requirement in the
BRD, and forward to the files that implement it.

## Before you start

1. Render with the module: `prompts.py render PROMPT_3_FUNCTIONAL_REQUIREMENTS.md --set MODULE_NAME=<name> --set MODULE_SOURCE=<folder>`. The module's source is in `{{MODULE_SOURCE}}`.
2. Read the domain context at `{{DOMAIN_CONTEXT}}`.
3. Read `{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/00_DISCOVERY_REPORT.md` (sections 10 and 12) and
   `01_BUSINESS_REQUIREMENTS.md` (the `BR-<n>` IDs and role names). If either is missing, stop.
4. Before writing a section, look up the discovery report's confirmed values for that area, and
   use those rather than re-deriving them.

## Steps

1. **One requirement per behaviour.** For each handler, page action or job step, write
   `FR-<AREA>-<nnn>`: what the system does (not how the code does it), the inputs, the outputs,
   the checks, and the `BR-<n>` it serves.
2. **Validation and errors.** From the service and form code: what each check rejects, the
   message or status code, and any uniqueness rule.
3. **Status and lifecycle.** For each entity with a status, give the allowed states and moves,
   and who may make each move. Use the values in the code. Don't use a list you'd expect to find.
4. **Multi-step workflows.** For wizards, steppers and approval chains, give the steps in order.
   For each step, give its fields, its save behaviour and what moves it on. Use the code, the
   domain context and any user guide it cites.
5. **Field rules.** For each form field: its type (free text, number, single or multi select,
   date, toggle), whether it's required, its limits, and its clear or default behaviour.
6. **Conditional rules as requirements.** Write each "required when" rule as its own requirement:
   `FR-<AREA>-COND-<n>`: "The system shall make <field> required when <other field> is <value>. If
   it's empty on save, the system shall show an error on <field>."
7. **Role access as requirements.** For each role the code checks, write `FR-RBAC-<n>`. It says
   which screens and actions the role gets, and that users without the role can't see them.
8. **Downstream effects.** In each area header, say whether its changes feed a sync job, a
   downstream system or a report, and cite where that's stated. Write `none found` if there are
   none.
9. **Module-wide conventions.** Write these once, for the whole module, from the shared code:
   the request and response conventions (base path, paging, date formats, the error body); the
   sign-in flow as numbered steps; how queries are run (which helper, where SQL lives, how values
   are passed); how errors map to status codes or on-screen messages; and what is logged or
   audited, and where. Cite each one.

## Output

Write `{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/02_FUNCTIONAL_REQUIREMENTS.md`, starting with:

```yaml
---
document: Functional requirements
product: {{PRODUCT_NAME}}
module: {{MODULE_NAME}}
version: <n>
status: Draft
generated_date: {{RUN_DATE}}
prompt_id: APP-03
prompt_version: 2.1.0
---
```

Sections:

1. Functional requirements by area (A1, A2 and so on). Each requirement has: ID, statement,
   inputs, outputs, checks and errors, `BR` link, and evidence.
2. Status lifecycles
3. Workflows
4. Field and conditional rules
5. Role access
6. Module-wide conventions: request and response rules, sign-in flow, query execution, error handling, logging and audit
7. BR-to-FR traceability table
8. Open questions, Assumptions and Don't know
9. Files read

## Evidence rules

- Each requirement has `[E: <file>:<line>]`, `[E: domain context §<n>]` or `[E: BRD BR-<n>]`.
- A rule taken from a user guide or the domain context and not seen in code says so. Mark it `[?]` if the code seems to disagree.
- Anything taken as true without a source is `[A]` and goes on the Assumptions list.
- A status value, field or role name is copied from the source, never made up.

## Self-check

- [ ] Every `BR-<n>` maps to at least one FR, or is listed as having none yet.
- [ ] Every handler or page action from the discovery report has an FR.
- [ ] Each FR can be tested: it has a clear input, a clear result and a failure case.
- [ ] Every conditional rule and role has its own FR.
- [ ] Section 6 covers all five conventions, or marks the missing ones `[?]`.
- [ ] Every `[A]` and `[?]` is on its list.

## Open questions, assumptions and unknowns

End with three lists:

- **Open questions:** each with an owner by role (business analyst, tech lead, product owner).
- **Assumptions:** each `[A]`, and what changes if it's wrong.
- **Don't know:** each `[?]`, with who could answer.
