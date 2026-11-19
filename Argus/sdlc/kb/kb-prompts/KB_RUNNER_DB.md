---
prompt_id: RUN-DB
title: Database knowledge-base runner
kind: runner
pipeline: db
version: 2.0.0
shareable: true
requires: []
depends_on: []
placeholders: [PRODUCT_NAME, DOMAIN_CONTEXT, KB_DB_DOCS, SNOWFLAKE_DB]
outputs: []
---

# RUN-DB: Database knowledge-base runner

## Purpose

Run the DB prompts for {{PRODUCT_NAME}} in the right order, with a review gate at each point where a person must check the results before the next stage builds on them. Output goes to `{{KB_DB_DOCS}}`.

## Before you start

1. Render each prompt with the team profile before running it. For example:
   `python3 sdlc/kb/tools/prompts.py render <prompt file> --env <env>`.
   Run `python3 sdlc/kb/tools/prompts.py lint` first. If lint fails, stop.
2. The domain context at `{{DOMAIN_CONTEXT}}` must exist. If it doesn't, build it first by
   running CTX-0A to CTX-0E, then CTX-00.
3. You need read-only access to `{{SNOWFLAKE_DB}}` for the environment you render with. Every
   query in the DB prompts is read-only. If a prompt seems to need a write, stop and ask.

## Stages

| Stage | Prompts | Runs after | Gate |
|---|---|---|---|
| 1 | DB-01 discovery | domain context | — |
| 1.5 | DB-01A discovery check | 1 | **Review:** a database engineer confirms the discovery before anything builds on it. |
| 2 | DB-02 BRD | 1.5 | **Review:** a business analyst signs off. |
| 3 | DB-03 TRD | 2 | **Review:** a tech lead signs off. |
| 4 | DB-04 diagrams, DB-05 supporting docs, DB-06 security | 3 | Can run in parallel. |
| 5 | DB-07 validation log | 4 | Collects open questions from stages 1 to 4. |
| 6 | DB-09 semantic layer, then DB-09B data contracts | 5 | — |
| 7 | DB-10 verified queries | 6 | Each query must run cleanly before it's marked verified. |
| 8 | DB-11 lineage, DB-12 guardrails, DB-13 entity registry | 7 | Can run in parallel. |
| 9 | DB-14 application queries | 8 | — |
| 10 | DB-15 AI validation tests | 9 | — |
| 11 | DB-16 cross-module matrix | 9, and the app and ETL runners | — |
| Any time | DB-08 change impact | 3 | Run per requirement. |
| Any time | DB-SD staleness check | 1 | Run before a refresh, to see what changed. |

**Refreshing.** Run DB-SD first. Rerun only the stages its report points to, then DB-07.

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
- [ ] Every gate has a named reviewer's sign-off before the next stage.
- [ ] No query changed data.
- [ ] Re-runs went through the staging and comparison steps.
- [ ] DB-07 ran last and holds every open item.
