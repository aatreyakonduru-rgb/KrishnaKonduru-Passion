---
name: db-diagrams
description: 'Database architecture diagrams: runs shared prompt DB-04 with the team profile into a staging
  folder.'
argument-hint: '[--env <env>] [--db <label>] [--stage <dir>]'
allowed-tools:
- read
- grep
- glob
- edit
- exec
visibility: internal
triggers:
- model
---

# Database architecture diagrams

`$METIS` below is the Mētis plugin folder: the folder two levels above this SKILL.md. `<KB>` is the knowledge-base folder named in the Mētis settings (`<KB>/.metis/kb-profile.yaml`). Follow `$METIS/rules/metis-evidence.md` and `$METIS/rules/metis-writes.md` throughout.
Work as the db-analyst agent: read `$METIS/agents/db-analyst/AGENT.md` first and follow it.

This skill runs the shared prompt **DB-04** (`$METIS/kb-prompts/DB_PROMPT_4_DIAGRAMS.md`) with the team values from `<KB>/.metis/kb-profile.yaml`. The prompt holds the instructions. This skill fills it in, runs it and handles the gate.

## 1. Fill in the prompt

```bash
python3 $METIS/tools/prompts.py lint      # stop if it reports an error
python3 $METIS/tools/prompts.py render DB_PROMPT_4_DIAGRAMS.md --env <env> --stage <stage> --out /tmp/kb-DB-04.md
python3 $METIS/tools/prompts.py outputs DB_PROMPT_4_DIAGRAMS.md --env <env> --stage <stage>
```

- `<env>`: the `--env` argument, else `reference_environment` in `<KB>/.metis/db-environments.yaml`; `<db>`: the `--db` label, else each database of that environment in turn (render prompts with `METIS_DB=<label>`). Tables are named `<database>.<schema>.<table>`; cover every schema of the database. Print `Database: <label> <database> (<engine>, <env>)` once. The output folder follows the environment: `docs_dir` in `<KB>/.metis/db-environments.yaml` gives each environment its own folder under `DB-DOCS/`. `render` and `outputs` already apply it, so a run for one environment never writes over another's files.
- `<stage>`: the folder the caller passes (for example `kb-build`), else `<KB>/_REGEN/<YYYY-MM-DD>` with today's date. Output never goes straight into the live knowledge base. `kb-compare` moves it there after the owner approves the comparison.
- Read the rendered prompt from `/tmp/kb-<id>.md`. Scratch files stay outside the repo.

If `lint` or `render` fails (a missing profile value, an unknown environment), stop and report the message. Don't fill values in by hand.

## 2. Run it

Read the rendered prompt in full and follow it: its steps, output files, evidence tags (`[E: source]` and `[?: Q-xxxx]`, as `$METIS/rules/metis-evidence.md` sets out; no `[A]`), self-check and closing lists. Write only the files that `outputs` listed. When a staged input doesn't exist yet, the prompt tells you to read the live copy instead.

## 3. Gate

No gate at this stage.

## When done

State: "DB Architecture Diagrams COMPLETE". Then list the files written, the environment used and the self-check items still open.
