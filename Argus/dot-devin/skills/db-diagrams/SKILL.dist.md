---
name: db-diagrams
description: 'Database architecture diagrams: runs shared prompt DB-04 with the team profile into a staging
  folder.'
argument-hint: '[--env dev|sit|uat|prod] [--stage <dir>]'
subagent: true
agent: db-analyst
allowed-tools:
- read
- grep
- glob
- edit
- exec
visibility: internal
triggers:
- user
- model
---

# Database architecture diagrams

This skill runs the shared prompt **DB-04** (`sdlc/kb/kb-prompts/DB_PROMPT_4_DIAGRAMS.md`) with our team values from `.devin/rules/kb-profile.yaml`. The prompt holds the instructions. This skill fills it in, runs it and handles the gate. The older ACME-specific copies are archived under `docs/knowledge-base/Archive/PROMPTS/`; don't use them.

## 1. Fill in the prompt

```bash
python3 sdlc/kb/tools/prompts.py lint      # stop if it reports an error
python3 sdlc/kb/tools/prompts.py render DB_PROMPT_4_DIAGRAMS.md --env <env> --stage <stage> --out /tmp/kb-DB-04.md
python3 sdlc/kb/tools/prompts.py outputs DB_PROMPT_4_DIAGRAMS.md --env <env> --stage <stage>
```

- `<env>`: the `--env` argument, else `SNOWFLAKE_ENV`, else `db.kb_environment` in `.devin/rules/kb-profile.yaml`. Our DB knowledge base is built from **prod**, so that is the default. Print `Snowflake target: <database> (<env>)` once. The output folder follows the environment: `docs_dir` in `.devin/rules/snowflake-environments.yaml` puts prod at the `DB-DOCS/` root and the lower regions in `DB-DOCS/SIT/`, `DB-DOCS/DEV/` and `DB-DOCS/UAT/`. `render` and `outputs` already apply it, so a lower-region run never writes a prod file.
- `<stage>`: the folder the caller passes (for example `/kb-build`), else `docs/knowledge-base/_REGEN/<YYYY-MM-DD>` with today's date. Output never goes straight into the live knowledge base. `/kb-compare` moves it there after the owner approves the comparison.
- Read the rendered prompt from `/tmp/kb-<id>.md`. Scratch files stay outside the repo.

If `lint` or `render` fails (a missing profile value, an unknown environment), stop and report the message. Don't fill values in by hand.

## 2. Run it

Read the rendered prompt in full and follow it: its steps, output files, evidence tags (`[E: source]`, `[A]`, `[?]`), self-check and closing lists. Write only the files that `outputs` listed. When a staged input doesn't exist yet, the prompt tells you to read the live copy instead.

## 3. Gate

No gate at this stage.

## When done

State: "DB Architecture Diagrams COMPLETE". Then list the files written, the environment used and the self-check items still open.
