---
name: db-metrics
description: 'Database metrics dictionary (stage 8.5): runs shared prompt DB-18 with the team profile into a staging folder. Records each business metric with its formula, source columns and owner. Needs the semantic layer, column profile and object logic.'
argument-hint: '[--env <env>] [--db <label>] [--stage <dir>]'
allowed-tools:
- read
- grep
- glob
- exec
- edit
- mcp__snowflake__sql_exec_tool
visibility: internal
triggers:
- model
---

# Database metrics dictionary

`$METIS` below is the Mētis plugin folder: the folder two levels above this SKILL.md. `<KB>` is the knowledge-base folder named in the Mētis settings (`<KB>/.metis/kb-profile.yaml`). Follow `$METIS/rules/metis-evidence.md` and `$METIS/rules/metis-writes.md` throughout.
Work as the db-analyst agent: read `$METIS/agents/db-analyst/AGENT.md` first and follow it.

This skill runs the shared prompt **DB-18** (`$METIS/kb-prompts/DB_PROMPT_18_METRICS.md`) with the team values from `<KB>/.metis/kb-profile.yaml`. The prompt holds the instructions. This skill fills it in and runs it.

## 1. Fill in the prompt

```bash
python3 $METIS/tools/prompts.py lint      # stop if it reports an error
python3 $METIS/tools/prompts.py render DB_PROMPT_18_METRICS.md --env <env> --stage <stage> --out /tmp/kb-DB-18.md
python3 $METIS/tools/prompts.py outputs DB_PROMPT_18_METRICS.md --env <env> --stage <stage>
```

- `<env>` and `<stage>` as in the other DB skills. `<stage>` defaults to `<KB>/_REGEN/<YYYY-MM-DD>`.
- Read the rendered prompt from `/tmp/kb-DB-18.md`. Scratch files stay outside the repo.

If `lint` or `render` fails, stop and report the message. Don't fill values in by hand.

## 2. Run it

**Preconditions.** These must exist in the stage folder or the live copy: `09_DB_SEMANTIC_LAYER.yaml` (DB-09), `17_DB_COLUMN_PROFILE.json` (DB-17) and `21_DB_OBJECT_LOGIC.md` (DB-21). If one is missing, stop and report it.

Run the prompt in full: its steps, output files, evidence tags (`[E: source]` and `[?: Q-xxxx]`; no `[A]`), self-check and closing lists. Write only the files that `outputs` listed.

**Database access.** Read only, if the prompt needs it to confirm a formula. SELECT, SHOW and DESCRIBE. A metric's formula is taken from the logic files first. Never read a sensitive column's values. Never run DDL, DML or a COMMENT ON script.

## 3. Gate

No gate at this stage. The metrics dictionary is reviewed with the semantic layer at the next gate.

## When done

State: "DB Metrics COMPLETE". Then list the files written, the environment used, the count of metrics, the count with an unknown owner, and the self-check items still open.
