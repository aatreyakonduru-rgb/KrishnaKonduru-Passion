---
prompt_id: HELP-SESSION
title: Session start, hand-off and change detection
kind: prompt
pipeline: helper
stage: any
version: 2.0.0
shareable: true
requires: []
depends_on: []
placeholders: [PRODUCT_NAME, KB_MODULE_DOCS, MODULE_NAME, MODULE_SOURCE, RUN_DATE]
outputs: ["{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/SESSION_STATE.md"]
---

# HELP-SESSION: Session start, hand-off and change detection

## Purpose

Keep work on a {{PRODUCT_NAME}} module consistent across sessions. Start each session from
the latest code, pick up where the last one stopped, and find out which documents are out of
date because the code changed. Run it at the start and end of every documentation session.
For ETL modules, render with `KB_MODULE_DOCS` pointing at the ETL docs folder, or use the same
steps in that folder.

## Before you start

1. Render with the module: `prompts.py render SESSION_MANAGER.md --set MODULE_NAME=<name> --set MODULE_SOURCE=<folder>`.
2. Read `{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/SESSION_STATE.md`, if it exists.

## Steps

**At the start of a session:**

1. Pull the latest code for the repo that holds `{{MODULE_SOURCE}}`. Don't pull over local
   changes. If there are any, stop and ask.
2. Record the branch and commit (`git rev-parse --abbrev-ref HEAD` and `git rev-parse --short HEAD`).
3. If `SESSION_STATE.md` has a last commit, list the files changed since then:
   `git diff --name-only <last commit> HEAD -- {{MODULE_SOURCE}}`.
4. Map each changed file to the documents it affects, using the discovery report's file layers.
   For example: route or handler files affect the FRD, the TRD and the endpoint registry;
   service files affect business rules; SQL files affect the TRD, the data contracts and the
   ETL table contract; screen and form files affect the user manual, the component registry and
   the validation rules; config files affect the TRD's environment section.
5. List those documents as stale in `SESSION_STATE.md`, and plan to rerun their prompts, or
   APP-GAP for small changes.

**During a session:** keep to one stage or one gap-fill scope. For large modules, split the
work by package or app, and track each part separately.

**At the end of a session:**

6. Update `SESSION_STATE.md` with the commit, the stages done, the documents touched, the open
   blockers and the next step.
7. Write a short hand-off note that the next session can start from: module, commit, last stage
   done, next stage, and blockers.

## Output

Update `{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/SESSION_STATE.md`:

```yaml
---
document: Session state
product: {{PRODUCT_NAME}}
module: {{MODULE_NAME}}
updated_date: {{RUN_DATE}}
prompt_id: HELP-SESSION
prompt_version: 2.0.0
branch: <branch>
commit: <short hash>
---
```

Sections:

1. Code state
2. Pipeline progress (stage, status, date, document version)
3. Parts of the module and their progress, if the module was split
4. Stale documents and why
5. Last session summary
6. Hand-off note
7. Open blockers

## Evidence rules

- The commit and changed-file list come from git output in this session, tagged `[E: git <command>]`.
- A document is only marked stale if a changed file maps to it, and the file is named.
- Anything taken as true without a source is `[A]` and goes on the Assumptions list.
- An unknown next step or owner is `[?]`.

## Self-check

- [ ] The commit was recorded at the start.
- [ ] Every changed file is mapped to a document, or listed as not mapped.
- [ ] The hand-off note names the next stage.
- [ ] Every `[A]` and `[?]` is on its list.

## Open questions, assumptions and unknowns

End `SESSION_STATE.md` with three lists:

- **Open questions:** each with an owner by role.
- **Assumptions:** each `[A]`, and what changes if it's wrong.
- **Don't know:** each `[?]`, with who could answer.
