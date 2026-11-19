---
prompt_id: APP-17
title: Module integration scenarios
kind: prompt
pipeline: app
stage: 8
version: 2.1.0
shareable: true
requires: []
depends_on: [APP-16]
placeholders: [PRODUCT_NAME, DOMAIN_CONTEXT, KB_MODULE_DOCS, MODULE_NAME, MODULE_SOURCE, RUN_DATE]
outputs: ["{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/11_INTEGRATION_SCENARIOS.md"]
---

# APP-17: Module integration scenarios

## Purpose

Walk through how a {{PRODUCT_NAME}} module works with the other layers, one business flow at a
time: the screen, the API, the database, files and batch jobs. Testers use it to plan
end-to-end tests, and developers use it to see what else a change touches.

## Before you start

1. Render with the module: `prompts.py render PROMPT_17_INTEGRATION_SCENARIOS.md --set MODULE_NAME=<name> --set MODULE_SOURCE=<folder>`. The module's source is in `{{MODULE_SOURCE}}`.
2. Read `{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/10_MODULE_IO_SUMMARY.md` from APP-16. If it's
   missing, stop.
3. Read `02_FUNCTIONAL_REQUIREMENTS.md` and `03_TECHNICAL_REQUIREMENTS.md` in the same folder,
   and the matching documents of the modules this one calls or is called by.
4. Read the domain context at `{{DOMAIN_CONTEXT}}` for the business flows, the batch jobs and
   the identity provider.

## Steps

1. **Architecture overview.** The layers this module talks to, as a Mermaid diagram, with the
   protocol or mechanism on each edge (HTTP, database driver, file drop, queue, schedule).
2. **Choose the scenarios.** One per main business flow through this module, plus the failure
   paths the code handles (a rejected upload, a failed call, a timeout).
3. **For each scenario, write:**
   - its business purpose and the actors (users, jobs, systems);
   - the preconditions;
   - numbered steps across the layers, naming the screen, function, endpoint, table or job at
     each step;
   - the expected result, and what the user sees;
   - the validation points, each with a read-only query or check;
   - the test data needed, described by shape and never as real records.
4. **Authentication.** How identity and access pass between layers, from code and config, per
   environment where they differ.
5. **Files and async work.** Uploads, downloads, exports and anything that finishes later, and
   how the user learns the result.
6. **Test matrix.** Rows are scenarios, columns are layers, and each cell says what's checked.
7. **Gaps and risks.** Integration points with no error handling, no retry, no timeout or no
   test, each with file and line.
8. **Environment differences.** Where hosts, auth, schedules or data differ between
   environments, from config. Name the setting, never its secret value.

## Output

Write `{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/11_INTEGRATION_SCENARIOS.md`, starting with:

```yaml
---
document: Integration scenarios
product: {{PRODUCT_NAME}}
module: {{MODULE_NAME}}
version: <n>
status: Draft
generated_date: {{RUN_DATE}}
prompt_id: APP-17
prompt_version: 2.1.0
---
```

Sections:

1. Purpose
2. Architecture overview
3. Scenarios, one sub-section each
4. Authentication
5. Files and async work
6. Test matrix
7. Test data needs
8. Integration gaps and risks
9. Environment-specific notes

Then Open questions, Assumptions, Don't know and Files read.

## Evidence rules

- Every step carries `[E: <file>:<line>]` or `[E: <KB document> §<n>]`.
- A step the code doesn't show, such as a downstream job picking up a record, is `[?]` unless a
  source says it happens.
- Anything taken as true without a source is `[A]` and goes on the Assumptions list.
- No real member, provider or customer data in test data. Describe the shape only.

## Self-check

- [ ] Every feature row in the I/O summary is covered by at least one scenario.
- [ ] Every step names a real function, endpoint, table or job with a source.
- [ ] Every validation point is read-only.
- [ ] Every `[A]` and `[?]` is on its list.

## Open questions, assumptions and unknowns

End with three lists:

- **Open questions:** each with an owner by role (tech lead, QA lead, business analyst).
- **Assumptions:** each `[A]`, and what changes if it's wrong.
- **Don't know:** each `[?]`, with who could answer.
