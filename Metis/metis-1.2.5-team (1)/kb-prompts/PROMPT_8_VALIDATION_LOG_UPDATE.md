---
prompt_id: APP-08
title: Validation log and session state update
kind: prompt
pipeline: app
stage: 8
version: 2.0.0
shareable: true
requires: []
depends_on: []
placeholders: [PRODUCT_NAME, DOMAIN_CONTEXT, KB_MODULE_DOCS, MODULE_NAME, MODULE_SOURCE, TEAM_ROSTER, RUN_DATE]
outputs: ["{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/VALIDATION_LOG.md", "{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/SESSION_STATE.md"]
---

# APP-08: Validation log and session state update

## Purpose

Keep the review record for `{{MODULE_NAME}}` current after any document is created or patched.
The record shows which version of each document exists, what's still unanswered, who owns each
open item, and the state of each security finding. Run it after every generation, patch or
gap-fill session. A stale log is how reviewers end up approving old content.

## Before you start

1. Render with the module: `prompts.py render PROMPT_8_VALIDATION_LOG_UPDATE.md --set MODULE_NAME=<name> --set MODULE_SOURCE=<folder>`. The module's source is in `{{MODULE_SOURCE}}`.
2. Read the domain context at `{{DOMAIN_CONTEXT}}` and the roster at `{{TEAM_ROSTER}}`.
3. Read `VALIDATION_LOG.md` and `SESSION_STATE.md` in `{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/`.
   If they don't exist, create them from the layout below.
4. List every document in the module folder.

## Steps

1. **Document versions.** For each document, read its header and record its version, status
   and date. Count the `[?]` and `[A]` tags still in it. Version rules:
   - `1.0` is the first generation.
   - `1.1` means the domain context was loaded, or a patch was applied.
   - `1.2` and up are later content patches.
2. **Open items.** For each open question in `SESSION_STATE.md`, check whether it's now
   answered. It's answered only if one of these settles it: a fact in the domain context, a
   value in a document generated since (give the document and section), or a code reading (give
   the file and line). Move each answered item to Resolved, with a one-line answer and its
   source. Keep the others open, with an owner by role. Take the name from the roster, and
   never invent one.
3. **Why items are still open.** For each open item, say what would close it: a stakeholder
   decision, a file nobody has read yet (name it), or infrastructure details.
4. **Security findings.** For each finding in the log, check the code again. Mark it
   `Resolved <date>` only if the code shows it's fixed, and give the file and line. Otherwise
   keep it open, and check that its severity still fits the rules in APP-09. A severity change
   needs a stated reason and a source.
5. **Patch history.** Add one row: date, documents touched, what changed, and which prompt or
   session did it.

## Output

Update `VALIDATION_LOG.md` in place, with these sections:

1. Document review status: document, version, status, date, open-tag count and reviewer
2. Open items: item, owner by role, and what would close it
3. Security finding status: ID, severity, state, and source
4. Patch history

Update `SESSION_STATE.md` in place. Add a Resolved section above the open items, and keep the
open items grouped by priority. Both files start with:

```yaml
---
document: <Validation log | Session state>
product: {{PRODUCT_NAME}}
module: {{MODULE_NAME}}
updated_date: {{RUN_DATE}}
prompt_id: APP-08
prompt_version: 2.0.0
---
```

## Evidence rules

- Each resolution cites its source: `[E: <doc> §<n>]`, `[E: <file>:<line>]` or `[E: domain context §<n>]`.
- An item you think is answered but can't source stays open. Add a note to it, marked `[?]`.
- Anything taken as true without a source is `[A]` and goes on the Assumptions list.
- Owners come from the roster by role.

## Self-check

- [ ] Every document in the folder is in the status table.
- [ ] Every resolved item has a source.
- [ ] Every open item has an owner and a way to close it.
- [ ] No finding was marked resolved without a code source.
- [ ] Every `[A]` and `[?]` is on its list.

## Open questions, assumptions and unknowns

End the log with three lists:

- **Open questions:** each with an owner from the roster.
- **Assumptions:** each `[A]`, and what changes if it's wrong.
- **Don't know:** each `[?]`, with who could answer.
