---
prompt_id: APP-09
title: Module security review
kind: prompt
pipeline: app
stage: 9
version: 2.1.0
shareable: true
requires: []
depends_on: [APP-01]
placeholders: [PRODUCT_NAME, DOMAIN_CONTEXT, KB_MODULE_DOCS, MODULE_NAME, MODULE_SOURCE, TEAM_ROSTER, RUN_DATE]
outputs: ["{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/08_SECURITY_REVIEW.md"]
---

# APP-09: Module security review

## Purpose

Find and rank the security problems in `{{MODULE_NAME}}`: auth, secrets, injection, input
checks, handling of sensitive data, frontend exposure, and batch scripts. Each finding has a
file and line, a severity, and a suggested fix. This is a code review. It doesn't test anything
live and never tries an exploit.

## Before you start

1. Render with the module: `prompts.py render PROMPT_9_SECURITY_REVIEW.md --set MODULE_NAME=<name> --set MODULE_SOURCE=<folder>`. The module's source is in `{{MODULE_SOURCE}}`.
2. Read the domain context at `{{DOMAIN_CONTEXT}}`, including any security findings already known.
3. Read `{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/00_DISCOVERY_REPORT.md` section 10 (flags), and
   `03_TECHNICAL_REQUIREMENTS.md` if it exists.
4. If `08_SECURITY_REVIEW.md` exists, read it. Carry each finding forward with its current state
   (open, fixed or accepted).

## Steps

Work through these batches. Only do the batches that apply to this module type.

1. **Authentication and authorization.** Read the token checks, the auth decorators or guards,
   the key fetching and caching, and any switch or test flag that turns auth off. Also check
   the frontend auth gate and any local-only bypass. List every open path.
2. **Secrets.** Look for hard-coded keys, passwords, tokens, tenant IDs and environment URLs in
   config, code and client bundles. Look for classes or files named like cipher, key or secret.
   Check dependency versions against known advisories, if you have a source for them.
3. **SQL injection.** Look for any SQL built with string joins, f-strings or `%` formatting from
   request data. Check that any helper meant to make SQL safe covers every such path.
4. **Input validation.** Check that request bodies are typed and checked, and look for raw body
   reads. For file uploads, check the type, size and content checks.
5. **Sensitive data.** Check what gets logged, and whether sensitive fields can reach logs. Check
   which schemas or views hold sensitive data, and how the code picks between them. Check any
   access or region flags and whether the code applies them.
6. **Frontend.** Look for ignored build or type errors, turned-off strict modes, mock data or
   bypasses in local mode, and environment URLs in the client bundle.
7. **Batch scripts.** Look for SQL built from parameters, files loaded from storage at run time,
   and emails or messages built from query output.
8. **Record what you checked.** For each batch, list what you looked at and what you found,
   including "checked, nothing found". Give credentials, CORS and cross-origin settings, and data
   classification (which data is sensitive and where it sits) their own entries.
9. **Rank each finding:**

| Severity | Meaning |
|---|---|
| Critical | Can be exploited without logging in, or exposes credentials or sensitive data directly |
| High | A logged-in user can reach data they shouldn't, or get round a control |
| Medium | Gets round a control only under certain conditions |
| Low | Weakens defence in depth, but can't be exploited directly |
| Info | Worth a look, but not a vulnerability |

## Output

Write `{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/08_SECURITY_REVIEW.md`, starting with:

```yaml
---
document: Security review
product: {{PRODUCT_NAME}}
module: {{MODULE_NAME}}
version: <n>
status: Draft, pending security lead acknowledgment
generated_date: {{RUN_DATE}}
layer: design
prompt_id: APP-09
prompt_version: 2.1.0
---
```

Sections:

1. Summary: counts by severity, and the top three to fix
2. Findings carried forward, with their current state
3. New findings. Each has an ID (`SEC-<AREA>-<nnn>`), a title, the severity, the file and line, what's wrong, the impact, and the fix.
4. Sensitive-data observations
5. Auth flow assessment
6. Fix priority
7. Technical debt found along the way (not security)
8. Areas checked: one row per batch, with what was looked at and the result, including "checked, nothing found"
9. Credentials, CORS and data classification

Then Open questions, Assumptions, Don't know and Files read. Take the security lead's name from
the roster at `{{TEAM_ROSTER}}`.

## Evidence rules

- Every finding is tagged `[E: <file>:<line>]`. A finding without a line number is `[?]`.
- A known finding you couldn't see in the code this time is `[?]`, with a note. Never mark it fixed without a source.
- Anything taken as true without a source is `[A]` and goes on the Assumptions list.
- Never copy a secret value into the report. Write `<redacted>` and give its location.

## Self-check

- [ ] Every batch that applies was done, or skipped with a reason.
- [ ] Every flag from the discovery report is a finding or is explained.
- [ ] Every finding has a severity and a fix.
- [ ] No secret values appear anywhere.
- [ ] Every `[A]` and `[?]` is on its list.

## Open questions, assumptions and unknowns

End with three lists:

- **Open questions:** each with an owner by role (security lead, tech lead, DevOps).
- **Assumptions:** each `[A]`, and what changes if it's wrong.
- **Don't know:** each `[?]`, with who could answer.
