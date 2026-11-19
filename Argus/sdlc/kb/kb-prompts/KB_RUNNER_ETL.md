---
prompt_id: RUN-ETL
title: ETL module knowledge-base runner
kind: runner
pipeline: etl
version: 2.0.0
shareable: true
requires: []
depends_on: []
placeholders: [PRODUCT_NAME, DOMAIN_CONTEXT, KB_ETL_DOCS]
outputs: []
---

# RUN-ETL: ETL module knowledge-base runner

## Purpose

Run the ETL prompts for each {{PRODUCT_NAME}} batch or ETL module, in order and with review gates. Output goes to `{{KB_ETL_DOCS}}/<module>/`.

## Before you start

1. Render each prompt with the team profile before running it. For example:
   `python3 sdlc/kb/tools/prompts.py render <prompt file> --env <env>`.
   Run `python3 sdlc/kb/tools/prompts.py lint` first. If lint fails, stop.
2. The domain context at `{{DOMAIN_CONTEXT}}` must exist. If it doesn't, build it first by
   running CTX-0A to CTX-0E, then CTX-00.
3. Render every prompt for a module with `--set MODULE_NAME=<name> --set MODULE_SOURCE=<folder>`.
4. The domain context should include the jobs module (CTX-0D). ETL prompts rely on it for
   triggers and schedules.

## Stages

For each module:

| Stage | Prompts | Runs after | Gate |
|---|---|---|---|
| 1 | ETL-01 discovery | domain context | — |
| 2 | ETL-02 BRD | 1 | **Review:** a business analyst signs off. |
| 3 | ETL-03 FRD | 2 | **Review:** a business analyst and the ETL lead sign off. |
| 4 | ETL-04 TRD, ETL-05 operator manual, ETL-07 diagrams, ETL-09 security | 3 | Can run in parallel. The security review needs the security lead's acknowledgment. |
| 5 | ETL-06 runbooks | 4 | **Review:** operations checks every runbook step. |
| 6 | ETL-08 validation log | 5, and after every later stage | — |
| 7 | ETL-10 input/output summary | 5 | — |
| 8 | ETL-11 integration scenarios | 7, and the app module docs | — |
| 9 | ETL-12 SQL patterns, then ETL-13 table contract | 8 | — |

After all modules are done, run DB-16 so the cross-module matrix picks up the ETL tables.

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
- [ ] Every module went through stages 1 to 6.
- [ ] Every gate has a named reviewer's sign-off.
- [ ] ETL-08 ran after each stage.
- [ ] Re-runs went through the staging and comparison steps.
