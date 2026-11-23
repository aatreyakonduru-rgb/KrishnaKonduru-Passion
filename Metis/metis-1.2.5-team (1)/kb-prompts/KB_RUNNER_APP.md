---
prompt_id: RUN-APP
title: Application module knowledge-base runner
kind: runner
pipeline: app
version: 2.0.0
shareable: true
requires: []
depends_on: []
placeholders: [PRODUCT_NAME, DOMAIN_CONTEXT, KB_MODULE_DOCS, APP_SOURCE_DIRS]
outputs: []
---

# RUN-APP: Application module knowledge-base runner

## Purpose

Run the application prompts for each {{PRODUCT_NAME}} API and UI module, in order and with review gates. Output goes to `{{KB_MODULE_DOCS}}/<module>/`.

## Before you start

1. Render each prompt with the team profile before running it. For example:
   `python3 tools/prompts.py render <prompt file> --env <env>`.
   Run `python3 tools/prompts.py lint` first. If lint fails, stop.
2. The domain context at `{{DOMAIN_CONTEXT}}` must exist. If it doesn't, build it first by
   running CTX-0A to CTX-0E, then CTX-00.
3. List the modules to document. The team's source folders are:

{{APP_SOURCE_DIRS}}

   Give each module a short name. Render every prompt for a module with
   `--set MODULE_NAME=<name> --set MODULE_SOURCE=<folder>`.
4. Pull the latest code, and record the branch and commit in the module's `SESSION_STATE.md`
   (see HELP-SESSION).

## Stages

For each module:

| Stage | Prompts | Runs after | Gate |
|---|---|---|---|
| 1 | APP-01 discovery | domain context | — |
| 2 | APP-02 BRD | 1 | **Review:** a business analyst signs off. |
| 3 | APP-03 FRD | 2 | **Review:** a business analyst and tech lead sign off. |
| 4 | APP-04 TRD, APP-05 user manual, APP-06 process docs, APP-07 diagrams, APP-09 security | 3 | Can run in parallel. The security review needs the security lead's acknowledgment. |
| 4 (UI) | APP-15 UI specification | 3 | Only for modules with screens. |
| 5 | APP-08 validation log | 4, and after every later stage | — |
| 6 (API) | APP-10 endpoint registry, then APP-11 data contracts | 4 | — |
| 6 (UI) | APP-12 component registry | 4, and the API registries it calls | — |
| 7 (UI) | APP-13 UI-to-data mapping, APP-14 validation rules | 6 | Needs the DB docs and ETL docs for full mappings. |
| 8 | APP-16 module I/O summary, then APP-17 integration scenarios | 4, and 6 when it ran | — |
| 8 (API) | APP-18 response field lineage | 6 (API), and DB-21 and DB-23 when they exist | Needs the API contracts. Run per API module. |
| Any time | APP-GAP gap-fill | 1 | For any area still marked `[?]`. Then APP-08. |
| Optional | HELP-CODEDOC detailed code docs | 1 | For modules where agents will change code often. |

Document the API modules before the UI modules that call them.

## Re-runs keep reviewed work

A re-run must not lose corrections people made by hand. Before replacing any output file:

1. Write the new version to a staging folder first, not over the current file.
2. In the current file, find content that can't be rebuilt from source alone: facts tagged
   `[E: stated by ...]`, sourced reviewer notes, and resolved open items.
3. Carry that content into the new version at the same place. Also apply every entry in the
   file's `.PATCHES.md` sidecar, if it has one.
4. Compare the two versions and list what's new, gone and changed. Anything the new version
   drops needs a reason.
5. Replace the current file only after the owner approves the comparison. Keep the old version
   in an archive folder, with the date in its name, so it can be restored.

## Self-check

- [ ] Lint passed before the run.
- [ ] Every module went through stages 1 to 5.
- [ ] Every gate has a named reviewer's sign-off.
- [ ] APP-08 ran after each stage.
- [ ] Re-runs went through the staging and comparison steps.
