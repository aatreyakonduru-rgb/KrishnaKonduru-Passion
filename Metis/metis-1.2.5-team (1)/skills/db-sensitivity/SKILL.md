---
name: db-sensitivity
description: 'Database sensitivity classification (stage 1.6): runs shared prompt DB-22 with the team profile into a staging folder. Classifies columns from policies, tags, comments and names. Reads no data values. Run it before any stage that reads values.'
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

# Database sensitivity classification

`$METIS` below is the Mētis plugin folder: the folder two levels above this SKILL.md. `<KB>` is the knowledge-base folder named in the Mētis settings (`<KB>/.metis/kb-profile.yaml`). Follow `$METIS/rules/metis-evidence.md` and `$METIS/rules/metis-writes.md` throughout.
Work as the db-analyst agent: read `$METIS/agents/db-analyst/AGENT.md` first and follow it.

This skill runs the shared prompt **DB-22** (`$METIS/kb-prompts/DB_PROMPT_22_SENSITIVITY.md`) with the team values from `<KB>/.metis/kb-profile.yaml`. The prompt holds the instructions. This skill fills it in and runs it.

## 1. Fill in the prompt

```bash
python3 $METIS/tools/prompts.py lint      # stop if it reports an error
python3 $METIS/tools/prompts.py render DB_PROMPT_22_SENSITIVITY.md --env <env> --stage <stage> --out /tmp/kb-DB-22.md
python3 $METIS/tools/prompts.py outputs DB_PROMPT_22_SENSITIVITY.md --env <env> --stage <stage>
```

- `<env>`: the `--env` argument, else `reference_environment` in `<KB>/.metis/db-environments.yaml`; `<db>`: the `--db` label, else each database of that environment in turn (render prompts with `METIS_DB=<label>`). Tables are named `<database>.<schema>.<table>`; cover every schema of the database. Print `Database: <label> <database> (<engine>, <env>)` once.
- `<stage>`: the folder the caller passes, else `<KB>/_REGEN/<YYYY-MM-DD>` with today's date. Output never goes straight into the live knowledge base.
- Read the rendered prompt from `/tmp/kb-DB-22.md`. Scratch files stay outside the repo.

If `lint` or `render` fails, stop and report the message. Don't fill values in by hand.

## 2. Run it

Run the prompt in full: its steps, output files, evidence tags (`[E: source]` and `[?: Q-xxxx]`, as `$METIS/rules/metis-evidence.md` sets out; no `[A]`), self-check and closing lists. Write only the files that `outputs` listed.

**Database access.** Read only: SELECT, SHOW and DESCRIBE. Use the connection named for this database in `<KB>/.metis/db-environments.yaml`, one statement per call. Check it first with the read-only identity query for its engine (Snowflake `SELECT CURRENT_USER(), CURRENT_ROLE();`, PostgreSQL `SELECT current_user, current_database();`). This prompt reads policies, tags, comments and column names. It must not read data values. Never run DDL, DML or a COMMENT ON script.

Save every catalogue query as `<KB>/_EVIDENCE/queries/DB-22-Q<n>.sql` and its result as `.json`, and cite it as `[E: query:DB-22-Q<n>]`.

## 3. Gate

No gate at this stage. The `skip_value_sampling` flags it writes are read by every later value-reading stage, so `db-run-pipeline` runs stage 1.6 straight after discovery validation.

## When done

State: "DB Sensitivity COMPLETE". Then list the files written, the environment used and the self-check items still open. Record any column the prompt couldn't classify as `[?]`, for the database engineer to decide.
