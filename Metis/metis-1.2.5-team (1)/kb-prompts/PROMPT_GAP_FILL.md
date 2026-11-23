---
prompt_id: APP-GAP
title: Gap-fill (read every file in scope)
kind: prompt
pipeline: app
stage: gap
version: 2.0.0
shareable: true
requires: []
depends_on: [APP-01]
placeholders: [PRODUCT_NAME, DOMAIN_CONTEXT, KB_MODULE_DOCS, MODULE_NAME, MODULE_SOURCE, RUN_DATE]
outputs: ["{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/<SESSION_ID>_SUPPLEMENT.md"]
---

# APP-GAP: Gap-fill (read every file in scope)

## Purpose

Fill a known gap in the `{{MODULE_NAME}}` documents by reading every file in a small, named
scope, such as one folder or one group of services, before writing anything. Use it when a
document says `[?]` for an area, or when a pipeline step only skimmed a folder. The result is
a supplement, plus patches to the documents it corrects.

## Before you start

1. Render with the module: `prompts.py render PROMPT_GAP_FILL.md --set MODULE_NAME=<name> --set MODULE_SOURCE=<folder>`. The module's source is in `{{MODULE_SOURCE}}`.
2. Read the domain context at `{{DOMAIN_CONTEXT}}`.
3. Read `{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/SESSION_STATE.md` and `VALIDATION_LOG.md`, to find
   the gap and any earlier gap-fill sessions.
4. Choose one session, and write down three things: a session ID, such as `API-GAP-<n>` or
   `UI-GAP-<n>`; the exact files or folders in scope; and the documents it's meant to fix. Keep
   the scope to what you can read fully in one session.

## Steps

1. **List every file in scope**, with its line count. That list is the session's checklist.
2. **Read each file in full.** After each file, write down what it does, the facts it gives, and
   the lines those facts are on.
3. **Don't write any conclusion until every file on the list is marked read.** If you run out of
   room, stop, record which files are left, and mark the session incomplete.
4. **Write the supplement** from those notes.
5. **Patch the documents it fixes.** Replace each `[?]` it answers with the fact and its
   `[E: file:line]`. Correct anything it proves wrong, and note the old value in the patch history.
6. **Check for drift.** For each patched fact, look for other documents that relied on the old
   value. This includes open requirement specs and gap analyses in the same sprint, and the domain
   context. List each one you find, with what needs to change. Update them, or raise them as
   open items.
7. **Run APP-08** to update the validation log and session state.

## Output

Write `{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/<SESSION_ID>_SUPPLEMENT.md`, starting with:

```yaml
---
document: Gap-fill supplement
product: {{PRODUCT_NAME}}
module: {{MODULE_NAME}}
session_id: <SESSION_ID>
scope: [<file or folder>]
all_files_read: <true|false>
generated_date: {{RUN_DATE}}
prompt_id: APP-GAP
prompt_version: 2.0.0
---
```

Sections:

1. Scope and file checklist (file, lines, read yes or no)
2. Findings by file
3. Patches made (document, section, old value, new value, source)
4. Drift found in other documents
5. Files left, if the session is incomplete

Then Open questions, Assumptions and Don't know.

## Evidence rules

- Every finding is tagged `[E: <file>:<line>]`, and the file must be on the checklist as read.
- A fact about a file you didn't read is `[?]`, and never goes in a patch.
- Anything taken as true without a source is `[A]` and goes on the Assumptions list.
- `all_files_read` is `true` only when every checklist row is read.

## Self-check

- [ ] Every file in scope is on the checklist.
- [ ] No finding cites a file that wasn't read.
- [ ] Every patch lists its old and new values and its source.
- [ ] The drift check was done.
- [ ] Every `[A]` and `[?]` is on its list.

## Open questions, assumptions and unknowns

End with three lists:

- **Open questions:** each with an owner by role (tech lead, module developer).
- **Assumptions:** each `[A]`, and what changes if it's wrong.
- **Don't know:** each `[?]`, with who could answer.
