---
name: etl-discovery
description: 'ETL module discovery (00_ETL_DISCOVERY_REPORT.md): runs shared prompt ETL-01 with the team
  profile into a staging folder.'
argument-hint: '[<module>] [--stage <dir>]'
subagent: true
agent: etl-specialist
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

# ETL module discovery

This skill runs the shared prompt **ETL-01** (`sdlc/kb/kb-prompts/ETL_PROMPT_1_DISCOVERY.md`) with our team values from `.devin/rules/kb-profile.yaml`. The prompt holds the instructions. This skill fills it in, runs it and handles the gate. The stage order is in `.devin/rules/kb-prompt-wiring.yaml`.

## 1. Fill in the prompt

```bash
python3 sdlc/kb/tools/prompts.py lint      # stop if it reports an error
python3 sdlc/kb/tools/prompts.py render ETL_PROMPT_1_DISCOVERY.md --env <env> --set MODULE_NAME=<module> --set MODULE_SOURCE=<source-folder> --stage <stage> --out /tmp/kb-ETL-01.md
python3 sdlc/kb/tools/prompts.py outputs ETL_PROMPT_1_DISCOVERY.md --env <env> --set MODULE_NAME=<module> --set MODULE_SOURCE=<source-folder> --stage <stage>
```

- `<env>`: the `--env` argument, else `SNOWFLAKE_ENV`, else `db.kb_environment` in `.devin/rules/kb-profile.yaml` (prod). ETL prompts only use it to name the database in the document header.
- `<module>` and `<source-folder>`: the module argument, else `etl.modules` in `.devin/rules/kb-profile.yaml` (`claims-etl`). The source folder is the ETL clone at `etl.clone_dir` (`../claims-etl`, next to this repo). If it isn't there, clone `etl.source_repo`, and record its commit in the output header.
- `<stage>`: the folder the caller passes (for example `/kb-build`), else `docs/knowledge-base/_REGEN/<YYYY-MM-DD>` with today's date. Output never goes straight into the live knowledge base. `/kb-compare` moves it there after the owner approves the comparison.
- Read the rendered prompt from `/tmp/kb-<id>.md`. Scratch files stay outside the repo.

If `lint` or `render` fails (a missing profile value, an unknown environment), stop and report the message. Don't fill values in by hand.

## 2. Run it

Read the rendered prompt in full and follow it: its steps, output files, evidence tags (`[E: source]`, `[A]`, `[?]`), self-check and closing lists. Write only the files that `outputs` listed. When a staged input doesn't exist yet, the prompt tells you to read the live copy instead.

## 3. Gate

No gate at this stage.

## When done

State: "ETL Discovery COMPLETE". Then list the files written, the environment used and the self-check items still open.
