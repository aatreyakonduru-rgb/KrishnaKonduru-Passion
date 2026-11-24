---
prompt_id: APP-02
title: Module business requirements (BRD)
kind: prompt
pipeline: app
stage: 2
version: 2.1.0
shareable: true
requires: []
depends_on: [APP-01]
placeholders: [PRODUCT_NAME, DOMAIN_CONTEXT, KB_MODULE_DOCS, MODULE_NAME, MODULE_SOURCE, TEAM_ROSTER, RUN_DATE]
outputs: ["{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/01_BUSINESS_REQUIREMENTS.md"]
---

# APP-02: Module business requirements (BRD)

## Purpose

Describe what the {{PRODUCT_NAME}} module `{{MODULE_NAME}}` does for the business, in words a
business analyst or program manager understands without IT help. It covers the capabilities,
who uses them, the business rules and where the data goes next. The evidence behind each
statement goes in a footnote, so the body stays readable and still traceable.

## Before you start

1. Render with the module: `prompts.py render PROMPT_2_BUSINESS_REQUIREMENTS.md --set MODULE_NAME=<name> --set MODULE_SOURCE=<folder>`.
2. Read the domain context at `{{DOMAIN_CONTEXT}}`: business terms, roles, screens and
   downstream systems.
3. Read `{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/00_DISCOVERY_REPORT.md`, especially sections 1, 3, 4,
   10 and 12. If it's missing, stop and run APP-01 first.
4. Read the source files in the discovery reading order, under `{{MODULE_SOURCE}}`. Read the
   handlers, services, UI pages and forms that carry business rules.

## Steps

1. **Business capabilities.** Group handlers, pages and jobs into what a user can get done,
   such as "set up a contract" or "approve a submission". Give each one an ID (`BR-<n>`), a plain
   description, and the files that show it.
2. **Roles and capabilities.** Build a role-to-screen matrix: each role, what it means in business
   terms, the screens it can reach and the actions it may take. Take the role names from the code
   (role checks, route guards) and the domain context. List access constraints, such as who
   can't approve their own work, only where code or the domain context states them.
3. **Business rules.** Each rule the code enforces (required fields, allowed values, status
   changes, limits, approvals), in business words, with the file behind it.
4. **Data hand-offs.** For each capability, where its data goes next: sync jobs, downstream
   systems and reports. Take these from the domain context or code. Mark unconfirmed ones `[?]`.
5. **Objectives and value.** From the domain context: the business problem, what the product is
   meant to achieve, and the value to the business. Don't write any the context doesn't state.
6. **Key business entities.** The main things the business works with (for example a contract, a
   provider group or an order), what each one means, how they relate, and who may see or change
   each one. Use business labels. Put table names in the footnotes.
7. **Reporting and export.** Each download, report or dashboard, and what it lets a user see or take away.
8. **Integration dependencies.** The systems this module needs (upstream) and the systems that use
   its data (downstream), each with what flows and when. Take these from the domain context or config.
9. **Compliance and security.** The rules the business must meet: sensitive data (such as health
   or personal data), audit trail, sign-in, separation of duties and data retention. Say where each
   is stated. Say where the code meets it, or that no code for it was found.
10. **Data freshness, availability and performance.** How current the data must be (sync timing),
   when the service must be available, and any response-time or volume expectation. Take these
   only from the domain context, config or a named document. Otherwise write `[?]`.
11. **Write for the reader.** In the body, use business labels, not code names. Put file, table,
   column and class names only in the Evidence footnotes. For example, write "measurement period
   start", not the column name, and write "the record is current", not the current-row filter
   value. Tenant and technical filters never appear in the body.
12. **Readability check.** Reread each section.
   - Would a program manager with no IT background follow every sentence? If not, rewrite it.
   - Does any sentence hold a file, table or column name? If so, move it to the footnote.

## Output

Write `{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/01_BUSINESS_REQUIREMENTS.md`, starting with:

```yaml
---
document: Business requirements
product: {{PRODUCT_NAME}}
module: {{MODULE_NAME}}
version: <n>
status: Draft, pending business analyst review
generated_date: {{RUN_DATE}}
layer: meaning
prompt_id: APP-02
prompt_version: 2.1.0
---
```

Sections:

1. Purpose and scope
2. Business context, objectives and value (from the domain context)
3. Business capabilities (one subsection per `BR-<n>`)
4. User roles and capabilities: the matrix and the access constraints
5. Business rules
6. Key business entities and who may see or change them
7. Reporting and export
8. Data hand-offs and integration dependencies
9. Compliance and security requirements
10. Data freshness, availability and performance
11. Out of scope
12. Open questions, Assumptions and Don't know
13. Evidence footnotes and files read

Take the reviewer and approver names from the roster at `{{TEAM_ROSTER}}`, by role. Never invent them.

## Evidence rules

- Each capability, role and rule has a footnote: `[E: <file>:<line>]` or `[E: domain context §<n>]`.
- A business purpose you can't find stated anywhere is `[?]`. Ask, and suggest an answer if you have one.
- Anything taken as true without a source is `[A]` and goes on the Assumptions list.
- Roles, screens and downstream systems are never guessed from names.

## Self-check

- [ ] Every `BR-<n>` has at least one footnote.
- [ ] The role matrix covers every role the code checks.
- [ ] Sections 6 to 10 are all present. Where nothing is known, the section says `[?]` and names who can answer.
- [ ] No code, table or column names appear in the body text.
- [ ] Every `[A]` and `[?]` is on its list.
- [ ] Reviewers come from the roster, by role.

## Open questions, assumptions and unknowns

End with three lists:

- **Open questions:** each with an owner, by role from the roster.
- **Assumptions:** each `[A]`, and what changes if it's wrong.
- **Don't know:** each `[?]`, with who could answer.
