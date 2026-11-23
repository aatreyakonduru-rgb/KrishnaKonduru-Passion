---
name: etl-run-pipeline
description: ETL documentation pipeline for one batch/ETL repo. Runs the ETL stage skills (ETL-01 to ETL-13) into a staging folder, with the review gates.
argument-hint: "[<module>] [--stage <dir>] [--rebuild]"
allowed-tools:
  - read
  - write
  - edit
  - grep
  - glob
  - exec
visibility: internal
triggers:
  - model
---

# Skill: ETL run pipeline

`$METIS` below is the Mētis plugin folder: the folder two levels above this SKILL.md. `<KB>` is the knowledge-base folder named in the Mētis settings (`<KB>/.metis/kb-profile.yaml`). Follow `$METIS/rules/metis-evidence.md` and `$METIS/rules/metis-writes.md` throughout.

This skill runs in the main session (no `subagent: true`), so each stage skill it starts keeps
its own `agent:` profile. The order follows `$METIS/kb-prompts/KB_RUNNER_ETL.md` (RUN-ETL),
and every stage is listed in `<KB>/.metis/kb-prompt-wiring.yaml`.

**Invocation:** `etl-run-pipeline [<module>] [--stage <dir>] [--rebuild]`

## Step 0 — set up

1. `<module>` is the argument, else each entry of `etl.modules` in `<KB>/.metis/kb-profile.yaml`.
2. The source is the ETL clone at `etl.clone_dir` (next to this repo). Clone `etl.source_repo`
   there if it's missing, else pull it without overwriting local changes. Record the commit
   (`git -C <clone> rev-parse --short HEAD`) in `<stage>/BUILD.md`.
3. `<stage>` is the `--stage` argument, else `<KB>/_REGEN/<YYYY-MM-DD>`.
4. Run `python3 $METIS/tools/prompts.py lint`. Stop if it reports an error.
5. The domain context must exist. If it doesn't, run `kb-context-build` first.

## Stages

Pass `<module> --stage <stage>` to each, plus `--rebuild` when this run has it.

```
Stage 1  `etl-discovery`         ETL-01 → 00_ETL_DISCOVERY_REPORT.md
Stage 2  `etl-brd`               ETL-02 → 01_ETL_BUSINESS_REQUIREMENTS.md
           │ Gate: BSA review
Stage 3  `etl-frd`               ETL-03 → 02_ETL_FUNCTIONAL_REQUIREMENTS.md
           │ Gate: BSA and ETL lead review
Stage 4  `etl-trd`               ETL-04 → 03_ETL_TECHNICAL_REQUIREMENTS.md     (can run in parallel)
         `etl-operator-manual`   ETL-05 → 04_ETL_USER_MANUAL.md
         `etl-diagrams`          ETL-07 → 06_ETL_ARCHITECTURE_DIAGRAMS.md
         `etl-security-review`   ETL-09 → 08_SECURITY_REVIEW.md
           │ Gate: security lead acknowledgment
Stage 5  `etl-runbooks`          ETL-06 → 05_ETL_PROCESS_DOCUMENTATION.md
           │ Gate: operations checks every runbook step
Stage 6  `etl-validation-log`    ETL-08 → VALIDATION_LOG.md, SESSION_STATE.md
Stage 7  `etl-module-io`         ETL-10 → 10_ETL_MODULE_IO_SUMMARY.md
Stage 8  `etl-integration`       ETL-11 → 11_ETL_INTEGRATION_SCENARIOS.md
Stage 9  `etl-sql-patterns`      ETL-12 → 12_ETL_SQL_PATTERNS.yaml
Stage 10 `etl-table-contract`    ETL-13 → 13_ETL_TABLE_IO_CONTRACT.yaml          (after ETL-12)
Stage 11 `etl-validation-log`    ETL-08 again, for the open items from stages 7 to 10
```

`<KB>/.metis/kb-output-names.yaml` maps the prompt names to them for `kb-compare`.

**ETL-13** is run by `etl-table-contract`, from its prompt (`$METIS/kb-prompts/ETL_PROMPT_13_TABLE_IO_CONTRACT.md`). It runs after ETL-12, as its `depends_on` header requires. Every table a job reads or writes cites the file and line.

## Gates

⛔ A normal run stops at each gate above. Present it as `$METIS/rules/metis-approvals.md`
describes, record the decision in `SESSION_STATE.md`, and don't start the next stage until it is
approved. Don't approve on anyone's behalf.

With `--rebuild` (a side-by-side rebuild of documents that already exist, started by `kb-build`),
the stages run straight through and each gate is recorded as `deferred to kb-compare review`.
A new ETL module always runs with the gates.

## When done

Report the module, the source commit, the files written, the gates signed or deferred, and the
self-check items still open. After all ETL modules are done, `db-cross-module` picks up the ETL
tables. Next step: `kb-compare <stage>`.

## Hard rules

- Never write into the live knowledge base or into the ETL repo.
- Start every stage skill with its own `agent:` profile.
