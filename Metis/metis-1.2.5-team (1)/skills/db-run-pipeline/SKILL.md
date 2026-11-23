---
name: db-run-pipeline
description: Database documentation pipeline for each database (any engine) of one environment. Runs the DB stage skills (DB-01 to DB-23, in the RUN-DB order) into a staging folder, with the review gates.
argument-hint: "[--env <env>] [--db <label>] [--stage <dir>] [--rebuild] [--skip-cross-module]"
allowed-tools:
  - read
  - write
  - edit
  - grep
  - glob
  - exec
  - mcp__snowflake__sql_exec_tool
visibility: internal
triggers:
  - model
---

# Skill: DB run pipeline

`$METIS` below is the Mētis plugin folder: the folder two levels above this SKILL.md. `<KB>` is the knowledge-base folder named in the Mētis settings (`<KB>/.metis/kb-profile.yaml`). Follow `$METIS/rules/metis-evidence.md` and `$METIS/rules/metis-writes.md` throughout.

This skill runs in the main session (no `subagent: true`), so each stage skill it starts keeps
its own `agent:` profile. Each stage skill renders its shared prompt from
`$METIS/kb-prompts/` with `<KB>/.metis/kb-profile.yaml`; this skill only sets the order,
the environment, the staging folder and the gates. The order follows
`$METIS/kb-prompts/KB_RUNNER_DB.md` (RUN-DB), and every stage is listed in
`<KB>/.metis/kb-prompt-wiring.yaml`.

**Invocation:** `db-run-pipeline [--env <env>] [--db <label>] [--stage <dir>] [--rebuild]`

## Step 0 — set up

1. `<env>` is the `--env` argument, else `reference_environment` in `<KB>/.metis/db-environments.yaml`; `<db>`: the `--db` label, else each database of that environment in turn (render prompts with `METIS_DB=<label>`). Tables are named `<database>.<schema>.<table>`; cover every schema of the database. Each environment's documents live in their own folder (`docs_dir` in `<KB>/.metis/db-environments.yaml`).
   Pass the same `--env` to every stage. Never fall back to another environment.
2. Check the connection and read the databases as below. **Database access.** Read only: SELECT, SHOW and DESCRIBE. Use the Devin connection named for this database in `<KB>/.metis/db-environments.yaml`, one statement per call, and check it first with the read-only identity query for its engine (Snowflake `SELECT CURRENT_USER(), CURRENT_ROLE();`, PostgreSQL `SELECT current_user, current_database();`). Run the catalogue queries `db_catalog.py plan` wrote. For `engine: schema-files` the CREATE TABLE files are the only source. Where this step names a Snowflake-only feature (warehouses, masking policies, Cortex) and the engine is not Snowflake, write that section as "not applicable: <engine>". If the database isn't reachable, say so in BUILD.md and carry on. Don't switch to another environment unless asked; that environment's output goes to its own folder.
3. `<stage>` is the `--stage` argument, else `<KB>/_REGEN/<YYYY-MM-DD>`.
4. Run `python3 $METIS/tools/prompts.py lint`. Stop if it reports an error.
5. The domain context (`product.domain_context` in the profile) must exist. If it doesn't, run
   `kb-context-build` first.

Every query in every stage is read-only: SELECT, SHOW and DESCRIBE only.

## Stages

Pass `--env <env> --stage <stage>` to each, plus `--rebuild` when this run has it.

```
Stage 1   `db-discovery`          DB-01 + DB-01A → 00_DB_DISCOVERY_REPORT.md, DISCOVERY_VALIDATION_LOG.md
            │ Gate: DB_DISCOVERY_REVIEW (database engineer)
Stage 1.6 `db-sensitivity`        DB-22 → 22_DB_SENSITIVITY.yaml               (no gate; sets skip_value_sampling)
Stage 2   `db-brd`                DB-02 → 01_DB_BUSINESS_REQUIREMENTS.md
            │ Gate: BSA review
Stage 2.5 `db-column-profile`     DB-17 → 17_DB_COLUMN_PROFILE.json             (needs 1.6)
Stage 2.6 `db-query-history`      DB-20 → 20_DB_USAGE_PATTERNS.md               (needs 1.6; can run with 2.5)
Stage 2.7 `db-object-logic`       DB-21 → 21_DB_OBJECT_LOGIC.md                 (needs 1.6)
Stage 3   `db-trd`                DB-03 → 02_DB_TECHNICAL_REQUIREMENTS.md
            │ Gate: tech lead review
Stage 4   `db-diagrams`           DB-04 → 03_DB_ARCHITECTURE_DIAGRAMS.md        (4a-4c can run in parallel)
          `db-supporting`         DB-05 → 04_DB_CHANGE_IMPACT_MATRIX.md, 05_DB_GLOSSARY.md, 07_DB_SCHEMA_CATALOG.md
          `db-security`           DB-06 → 06_DB_SECURITY_REVIEW.md
Stage 5   `db-validation`         DB-07 → VALIDATION_LOG.md, SESSION_STATE.md, 08_DB_REFRESH_PROTOCOL.md
Stage 6   `db-semantic-layer`     DB-09 → 09_DB_SEMANTIC_LAYER.yaml
          `db-data-contracts`     DB-09B → 9B_DB_DATA_CONTRACTS.yaml (sample live name: 11_DB_DATA_CONTRACTS.yaml)
Stage 7   `db-verified-queries`   DB-10 → 10_DB_VERIFIED_QUERIES.md
Stage 8   `db-lineage`            DB-11 → 11_DB_DATA_LINEAGE.yaml               (8a-8c can run in parallel)
          `db-guardrails`         DB-12 → 12_DB_AI_GUARDRAILS.yaml
          `db-entity-registry`    DB-13 → 13_DB_ENTITY_REGISTRY.yaml
Stage 8.5 `db-metrics`            DB-18 → 18_DB_METRICS.yaml                    (needs 6 and 2.7; can run with 8)
Stage 8.6 `db-term-map`           DB-19 → 19_DB_TERM_MAP.yaml                   (needs 8.5, 2.5 and 2.6)
Stage 8.7 `db-column-lineage`     DB-23 → 23_DB_COLUMN_LINEAGE.yaml             (needs 8 and 2.7)
Stage 9   `db-app-queries`        DB-14 → 14_DB_APP_VERIFIED_QUERIES.md
Stage 10  `db-ai-tests`           DB-15 → 15_DB_AI_VALIDATION_TESTS.yaml
Stage 11  `db-cross-module`       DB-16 → 16_DB_CROSS_MODULE_DEPENDENCY_MATRIX.yaml (sample live name: CROSS_LAYER_IMPACT_MATRIX.yaml)
Stage 12  `db-validation`         DB-07 again, so the log holds the open items from stages 6 to 11
```

Skip stage 11 with `--skip-cross-module` when the app and ETL documents for this run aren't
built yet; `kb-build all` runs it last for that reason.

Two DB prompts are not build stages. Run them on their own when needed:
- DB-08 change impact, per requirement: `db-change-analysis <requirement>`.
- DB-SD staleness check, before a refresh: `kb-build` (rebuild). It decides which of the
  stages above to rerun.

## Gates

⛔ A normal run stops at each gate above. Present it with its files and criteria, as
`$METIS/rules/metis-approvals.md` describes. Record the decision in the stage folder's
`SESSION_STATE.md`, and don't start the next stage until it is approved. Don't approve on
anyone's behalf.

With `--rebuild` (a side-by-side rebuild of documents that already exist, started by `kb-build`),
the stages run straight through, because nothing is replaced. Each gate is recorded as
`deferred to kb-compare review`. A first build of an environment always runs with the gates.

## When done

Report the environment, the files written, the gates signed or deferred, and the self-check items
still open. Next step: `kb-compare <stage>`.

## Hard rules

- Never write into the live knowledge base, and never write a prod file from a lower-region run.
- Never run a statement that changes data or objects.
- Start every stage skill with its own `agent:` profile.
