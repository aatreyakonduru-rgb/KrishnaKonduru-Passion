---
name: db-column-profile
description: 'Database column catalogue and profile (stage 2.5): runs shared prompt DB-17 with the team profile into a staging folder. Profiles every column, and gives sensitive columns a null count only. Needs DB-22 to have run.'
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

# Database column catalogue and profile

`$METIS` below is the Mētis plugin folder: the folder two levels above this SKILL.md. `<KB>` is the knowledge-base folder named in the Mētis settings (`<KB>/.metis/kb-profile.yaml`). Follow `$METIS/rules/metis-evidence.md` and `$METIS/rules/metis-writes.md` throughout.
Work as the db-analyst agent: read `$METIS/agents/db-analyst/AGENT.md` first and follow it.

This skill runs the shared prompt **DB-17** (`$METIS/kb-prompts/DB_PROMPT_17_COLUMN_PROFILE.md`) with the team values from `<KB>/.metis/kb-profile.yaml`. The prompt holds the instructions. This skill fills it in and runs it.

## 1. Fill in the prompt

```bash
python3 $METIS/tools/prompts.py lint      # stop if it reports an error
python3 $METIS/tools/prompts.py render DB_PROMPT_17_COLUMN_PROFILE.md --env <env> --stage <stage> --out /tmp/kb-DB-17.md
python3 $METIS/tools/prompts.py outputs DB_PROMPT_17_COLUMN_PROFILE.md --env <env> --stage <stage>
```

- `<env>`: the `--env` argument, else `reference_environment` in `<KB>/.metis/db-environments.yaml`; `<db>`: the `--db` label, else each database of that environment in turn (render prompts with `METIS_DB=<label>`). Cover every schema of the database.
- `<stage>`: the folder the caller passes, else `<KB>/_REGEN/<YYYY-MM-DD>`. Output never goes straight into the live knowledge base.
- Read the rendered prompt from `/tmp/kb-DB-17.md`. Scratch files stay outside the repo.

If `lint` or `render` fails, stop and report the message. Don't fill values in by hand.

## 2. Run it

**Precondition.** Stage 1.6 (`db-sensitivity`, DB-22) must have written `22_DB_SENSITIVITY.yaml`. Read its `skip_value_sampling` flags. If the file is missing, stop and report it. Don't profile without it.

Run the prompt in full: its steps, output files, evidence tags (`[E: source]` and `[?: Q-xxxx]`; no `[A]`), self-check and closing lists. Write only the files that `outputs` listed.

**Database access.** Read only: SELECT, SHOW and DESCRIBE. Use the connection named for this database in `<KB>/.metis/db-environments.yaml`, one statement per call. Check it first with the read-only identity query for its engine. A column flagged `skip_value_sampling` gets a null count and nothing else. Never run DDL, DML or a COMMENT ON script.

Save every query as `<KB>/_EVIDENCE/queries/DB-17-Q<n>.sql` and its result as `.json`, and cite it as `[E: query:DB-17-Q<n>]`. Page long results and check the row count on every page.

## 3. Gate

No gate at this stage.

## When done

State: "DB Column profile COMPLETE". Then list the files written, the environment used, the number of columns profiled and the number skipped as sensitive, and the self-check items still open.
