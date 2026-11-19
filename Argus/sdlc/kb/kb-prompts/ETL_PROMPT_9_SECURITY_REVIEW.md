---
prompt_id: ETL-09
title: ETL security review
kind: prompt
pipeline: etl
stage: 9
version: 2.1.0
shareable: true
requires: []
depends_on: [ETL-01]
placeholders: [PRODUCT_NAME, DOMAIN_CONTEXT, KB_ETL_DOCS, MODULE_NAME, MODULE_SOURCE, TEAM_ROSTER, RUN_DATE]
outputs: ["{{KB_ETL_DOCS}}/{{MODULE_NAME}}/08_SECURITY_REVIEW.md"]
---

# ETL-09: ETL security review

## Purpose

Find and rank the security problems in the ETL module `{{MODULE_NAME}}`. That covers
credentials, encryption, access, SQL injection, handling of sensitive data, audit logging,
network settings and compliance. Each finding has a file and line, a severity and a fix. This is
a code review. It doesn't touch live systems.

## Before you start

1. Render with the module: `prompts.py render ETL_PROMPT_9_SECURITY_REVIEW.md --set MODULE_NAME=<name> --set MODULE_SOURCE=<folder>`.
2. Read the domain context at `{{DOMAIN_CONTEXT}}`, including any known findings.
3. Read `00_ETL_DISCOVERY_REPORT.md` (the flags), and `03_ETL_TECHNICAL_REQUIREMENTS.md` if it
   exists, in `{{KB_ETL_DOCS}}/{{MODULE_NAME}}/`.
4. If `08_SECURITY_REVIEW.md` exists, carry each finding forward with its current state.

## Steps

Review the code under `{{MODULE_SOURCE}}`, one area at a time:

1. **Credentials.** Where they're read from, whether any are in code or config, and whether
   they're logged.
2. **Encryption.** Certificate checks turned off, plain-text connections, and unencrypted file
   writes.
3. **Access.** The database role and scope the jobs use, and write access wider than they need.
4. **SQL injection.** SQL built from parameters or file contents with string formatting.
5. **Sensitive data.** What's selected, logged, emailed or written to files, and whether masked
   views are used.
6. **Audit logging.** Whether each run and data change is recorded, and where.
7. **Network.** Hard-coded hosts, open endpoints, and proxy or TLS settings.
8. **Compliance.** Rules the domain context names, such as data residency or data retention,
   and whether the code follows them.
9. **Record what you checked.** For each area, what you looked at and the result, including
   "checked, nothing found". Add a data classification: which tables and files hold sensitive
   data, and how the jobs read and write them.
10. **Rank each finding** as Critical, High, Medium, Low or Info, using the same scale as APP-09.

## Output

Write `{{KB_ETL_DOCS}}/{{MODULE_NAME}}/08_SECURITY_REVIEW.md`, starting with:

```yaml
---
document: ETL security review
product: {{PRODUCT_NAME}}
module: {{MODULE_NAME}}
version: <n>
status: Draft, pending security lead acknowledgment
generated_date: {{RUN_DATE}}
prompt_id: ETL-09
prompt_version: 2.1.0
---
```

Sections:

1. Summary by severity
2. Findings carried forward
3. New findings, one per area. Each has an ID (`SEC-ETL-<nnn>`), the severity, the file and line, what's wrong, the impact and the fix.
4. Fix priority
5. Areas checked: one row per area, with what was looked at and the result
6. Data classification

Then Open questions, Assumptions, Don't know and Files read. Take the security lead's name from
the roster at `{{TEAM_ROSTER}}`.

## Evidence rules

- Every finding is tagged `[E: <file>:<line>]`.
- A known finding not seen this time is `[?]`. Never mark it fixed without a source.
- Anything taken as true without a source is `[A]` and goes on the Assumptions list.
- Secret values are never copied. Write `<redacted>` and give the location.

## Self-check

- [ ] All eight areas were reviewed, or skipped with a reason.
- [ ] Every discovery flag is a finding or is explained.
- [ ] No secret values appear.
- [ ] Every `[A]` and `[?]` is on its list.

## Open questions, assumptions and unknowns

End with three lists:

- **Open questions:** each with an owner by role (security lead, ETL developer, DevOps).
- **Assumptions:** each `[A]`, and what changes if it's wrong.
- **Don't know:** each `[?]`, with who could answer.
