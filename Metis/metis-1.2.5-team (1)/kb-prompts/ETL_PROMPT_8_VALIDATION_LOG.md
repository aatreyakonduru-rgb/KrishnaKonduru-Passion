---
prompt_id: ETL-08
title: ETL validation log and session state update
kind: prompt
pipeline: etl
stage: 8
version: 2.0.0
shareable: true
requires: []
depends_on: []
placeholders: [PRODUCT_NAME, DOMAIN_CONTEXT, KB_ETL_DOCS, MODULE_NAME, MODULE_SOURCE, TEAM_ROSTER, RUN_DATE]
outputs: ["{{KB_ETL_DOCS}}/{{MODULE_NAME}}/VALIDATION_LOG.md", "{{KB_ETL_DOCS}}/{{MODULE_NAME}}/SESSION_STATE.md"]
---

# ETL-08: ETL validation log and session state update

## Purpose

Keep the review record for `{{MODULE_NAME}}` current after any ETL document is created or
patched. The record shows the document versions, the open items and their owners, the reviewer
feedback, and the security finding states. Run it after every generation, patch or gap-fill session.

## Before you start

1. Render with the module: `prompts.py render ETL_PROMPT_8_VALIDATION_LOG.md --set MODULE_NAME=<name> --set MODULE_SOURCE=<folder>`. The module's source is in `{{MODULE_SOURCE}}`.
2. Read the domain context at `{{DOMAIN_CONTEXT}}` and the roster at `{{TEAM_ROSTER}}`.
3. Read `VALIDATION_LOG.md` and `SESSION_STATE.md` in `{{KB_ETL_DOCS}}/{{MODULE_NAME}}/`. If
   they don't exist, create them from the layout below.

## Steps

1. **Document versions.** For each ETL document, record its version, status and date, and the
   count of `[?]` and `[A]` tags still in it. Version rules:
   - `1.0` is the first generation.
   - `1.1` means the domain context was loaded or a patch was applied.
   - `1.2` and up are later patches.
2. **Open items.** For each open question, check whether a fact in the domain context, a later
   document (give the section) or a code reading (give the file and line) now answers it.
   Move answered items to Resolved, with their source. Keep the rest, with an owner from the
   roster and what would close each one.
3. **Reviewer feedback.** Record each piece of feedback, and the document change it led to.
4. **Security findings.** Mark a finding resolved only if the code shows it's fixed, and give the
   file and line.
5. **Metrics.** For each document, record its open-tag count and the number of items resolved
   this session.
6. **Next steps.** Which prompt to run next, and why.

## Output

Update `VALIDATION_LOG.md` in place, with these sections:

1. Document version history
2. Open items
3. Validation items
4. Reviewer feedback
5. Security finding status
6. Metrics
7. Next steps

Update `SESSION_STATE.md` in place, with the current session, previous sessions, and the
resolved and open items. Both files start with:

```yaml
---
document: <Validation log | Session state>
product: {{PRODUCT_NAME}}
module: {{MODULE_NAME}}
updated_date: {{RUN_DATE}}
prompt_id: ETL-08
prompt_version: 2.0.0
---
```

## Evidence rules

- Each resolution cites `[E: <doc> §<n>]`, `[E: <file>:<line>]` or `[E: domain context §<n>]`.
- An item you think is answered but can't source stays open, marked `[?]`.
- Anything taken as true without a source is `[A]` and goes on the Assumptions list.
- Owners come from the roster.

## Self-check

- [ ] Every ETL document is in the version table.
- [ ] Every resolved item has a source.
- [ ] Every open item has an owner.
- [ ] Every `[A]` and `[?]` is on its list.

## Open questions, assumptions and unknowns

End the log with three lists:

- **Open questions:** each with an owner from the roster.
- **Assumptions:** each `[A]`, and what changes if it's wrong.
- **Don't know:** each `[?]`, with who could answer.
