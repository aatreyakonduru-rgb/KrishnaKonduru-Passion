---
name: db-run-pipeline
description: Database documentation pipeline for one Snowflake environment. Runs the DB stage skills (DB-01 to DB-16, in the RUN-DB order) into a staging folder, with the review gates.
argument-hint: "[--env dev|sit|uat|prod] [--stage <dir>] [--rebuild] [--skip-cross-module]"
allowed-tools:
  - read
  - write
  - edit
  - grep
  - glob
  - exec
  - mcp__acme-snowflake__sql_exec_tool
visibility: internal
triggers:
  - user
  - model
---

# Skill: DB run pipeline

This skill runs in the main session (no `subagent: true`), so each stage skill it starts keeps
its own `agent:` profile. Each stage skill renders its shared prompt from
`sdlc/kb/kb-prompts/` with `.devin/rules/kb-profile.yaml`; this skill only sets the order,
the environment, the staging folder and the gates. The order follows
`sdlc/kb/kb-prompts/KB_RUNNER_DB.md` (RUN-DB), and every stage is listed in
`.devin/rules/kb-prompt-wiring.yaml`.

**Invocation:** `/db-run-pipeline [--env dev|sit|uat|prod] [--stage <dir>] [--rebuild]`

## Step 0 — set up

1. `<env>` is the `--env` argument, else `SNOWFLAKE_ENV`, else `db.kb_environment` in
   `.devin/rules/kb-profile.yaml` (prod). Our DB knowledge base is built from prod; the dev and
   SIT sets live in their own folders (`docs_dir` in `.devin/rules/snowflake-environments.yaml`).
   Pass the same `--env` to every stage. Never fall back to another environment.
2. Check the connection with `SELECT CURRENT_USER(), CURRENT_ROLE();` and
   `SELECT CURRENT_DATABASE();` against the environment's database. The Devin nonprod MCP reaches
   dev and SIT only; prod needs a read-only prod connection (Devin Desktop). If the database
   can't be reached, stop and say so.
3. `<stage>` is the `--stage` argument, else `docs/knowledge-base/_REGEN/<YYYY-MM-DD>`.
4. Run `python3 sdlc/kb/tools/prompts.py lint`. Stop if it reports an error.
5. The domain context (`product.domain_context` in the profile) must exist. If it doesn't, run
   `/kb-context-build` first.

Every query in every stage is read-only: SELECT, SHOW and DESCRIBE only.

## Stages

Pass `--env <env> --stage <stage>` to each, plus `--rebuild` when this run has it.

```
Stage 1   /db-discovery          DB-01 + DB-01A → 00_DB_DISCOVERY_REPORT.md, DISCOVERY_VALIDATION_LOG.md
            │ Gate: DB_DISCOVERY_REVIEW (database engineer)
Stage 2   /db-brd                DB-02 → 01_DB_BUSINESS_REQUIREMENTS.md
            │ Gate: BSA review
Stage 3   /db-trd                DB-03 → 02_DB_TECHNICAL_REQUIREMENTS.md
            │ Gate: tech lead review
Stage 4   /db-diagrams           DB-04 → 03_DB_ARCHITECTURE_DIAGRAMS.md        (4a-4c can run in parallel)
          /db-supporting         DB-05 → 04_DB_CHANGE_IMPACT_MATRIX.md, 05_DB_GLOSSARY.md, 07_DB_SCHEMA_CATALOG.md
          /db-security           DB-06 → 06_DB_SECURITY_REVIEW.md
Stage 5   /db-validation         DB-07 → VALIDATION_LOG.md, SESSION_STATE.md, 08_DB_REFRESH_PROTOCOL.md
Stage 6   /db-semantic-layer     DB-09 → 09_DB_SEMANTIC_LAYER.yaml
          /db-data-contracts     DB-09B → 9B_DB_DATA_CONTRACTS.yaml (ours: 11_DB_DATA_CONTRACTS.yaml)
Stage 7   /db-verified-queries   DB-10 → 10_DB_VERIFIED_QUERIES.md
Stage 8   /db-lineage            DB-11 → 11_DB_DATA_LINEAGE.yaml               (8a-8c can run in parallel)
          /db-guardrails         DB-12 → 12_DB_AI_GUARDRAILS.yaml
          /db-entity-registry    DB-13 → 13_DB_ENTITY_REGISTRY.yaml
Stage 9   /db-app-queries        DB-14 → 14_DB_APP_VERIFIED_QUERIES.md
Stage 10  /db-ai-tests           DB-15 → 15_DB_AI_VALIDATION_TESTS.yaml
Stage 11  /db-cross-module       DB-16 → 16_DB_CROSS_MODULE_DEPENDENCY_MATRIX.yaml (ours: CROSS_LAYER_IMPACT_MATRIX.yaml)
Stage 12  /db-validation         DB-07 again, so the log holds the open items from stages 6 to 11
```

Skip stage 11 with `--skip-cross-module` when the app and ETL documents for this run aren't
built yet; `/kb-build all` runs it last for that reason.

Two DB prompts are not build stages. Run them on their own when needed:
- DB-08 change impact, per requirement: `/db-change-analysis <requirement>`.
- DB-SD staleness check, before a refresh: `/app-knowledge-refresh`. It decides which of the
  stages above to rerun.

## Gates

⛔ A normal run stops at each gate above. Present it with its files and criteria, as
`.devin/rules/gate-presentation.md` describes. Record the decision in the stage folder's
`SESSION_STATE.md`, and don't start the next stage until it is approved. Don't approve on
anyone's behalf.

With `--rebuild` (a side-by-side rebuild of documents that already exist, started by `/kb-build`),
the stages run straight through, because nothing is replaced. Each gate is recorded as
`deferred to /kb-compare review`. A first build of an environment always runs with the gates.

## When done

Report the environment, the files written, the gates signed or deferred, and the self-check items
still open. Next step: `/kb-compare <stage>`.

## Hard rules

- Never write into the live knowledge base, and never write a prod file from a lower-region run.
- Never run a statement that changes data or objects.
- Start every stage skill with its own `agent:` profile.
