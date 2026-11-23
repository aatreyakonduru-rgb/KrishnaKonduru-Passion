---
name: db-column-lineage
description: 'Database column-level lineage (stage 8.7): runs shared prompt DB-23 with the team profile into a staging folder. Extends table lineage (DB-11) down to the column level, with impact of a rename or drop. Needs table lineage and object logic.'
argument-hint: '[--env <env>] [--db <label>] [--stage <dir>]'
allowed-tools:
- read
- grep
- glob
- exec
- edit
visibility: internal
triggers:
- model
---

# Database column-level lineage

`$METIS` below is the Mētis plugin folder: the folder two levels above this SKILL.md. `<KB>` is the knowledge-base folder named in the Mētis settings (`<KB>/.metis/kb-profile.yaml`). Follow `$METIS/rules/metis-evidence.md` and `$METIS/rules/metis-writes.md` throughout.
Work as the db-analyst agent: read `$METIS/agents/db-analyst/AGENT.md` first and follow it.

This skill runs the shared prompt **DB-23** (`$METIS/kb-prompts/DB_PROMPT_23_COLUMN_LINEAGE.md`) with the team values from `<KB>/.metis/kb-profile.yaml`. The prompt holds the instructions. This skill fills it in and runs it.

## 1. Fill in the prompt

```bash
python3 $METIS/tools/prompts.py lint      # stop if it reports an error
python3 $METIS/tools/prompts.py render DB_PROMPT_23_COLUMN_LINEAGE.md --env <env> --stage <stage> --out /tmp/kb-DB-23.md
python3 $METIS/tools/prompts.py outputs DB_PROMPT_23_COLUMN_LINEAGE.md --env <env> --stage <stage>
```

- `<env>` and `<stage>` as in the other DB skills. `<stage>` defaults to `<KB>/_REGEN/<YYYY-MM-DD>`.
- Read the rendered prompt from `/tmp/kb-DB-23.md`. Scratch files stay outside the repo.

If `lint` or `render` fails, stop and report the message. Don't fill values in by hand.

## 2. Run it

**Preconditions.** `11_DB_DATA_LINEAGE.yaml` (DB-11), `21_DB_OBJECT_LOGIC.md` (DB-21) and `09_DB_SEMANTIC_LAYER.yaml` (DB-09) must exist. If one is missing, stop and report it.

Run the prompt in full: its steps, output files, evidence tags (`[E: source]` and `[?: Q-xxxx]`; no `[A]`), self-check and closing lists. Write only the files that `outputs` listed.

**Database access.** None needed. The prompt works from the files above and the ETL knowledge-base documents. Never run DDL, DML or a COMMENT ON script.

## 3. Gate

No gate at this stage.

## When done

State: "DB Column lineage COMPLETE". Then list the files written, the environment used, the count of column-level flows, the count of flows with an unknown source, and the self-check items still open.
