---
name: etl-brd
description: 'ETL business requirements (BRD): runs shared prompt ETL-02 with the team profile into a
  staging folder.'
argument-hint: '[<module>] [--stage <dir>] [--rebuild]'
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

# ETL business requirements

This skill runs the shared prompt **ETL-02** (`sdlc/kb/kb-prompts/ETL_PROMPT_2_BUSINESS_REQUIREMENTS.md`) with our team values from `.devin/rules/kb-profile.yaml`. The prompt holds the instructions. This skill fills it in, runs it and handles the gate. The stage order is in `.devin/rules/kb-prompt-wiring.yaml`.

## 1. Fill in the prompt

```bash
python3 sdlc/kb/tools/prompts.py lint      # stop if it reports an error
python3 sdlc/kb/tools/prompts.py render ETL_PROMPT_2_BUSINESS_REQUIREMENTS.md --env <env> --set MODULE_NAME=<module> --set MODULE_SOURCE=<source-folder> --stage <stage> --out /tmp/kb-ETL-02.md
python3 sdlc/kb/tools/prompts.py outputs ETL_PROMPT_2_BUSINESS_REQUIREMENTS.md --env <env> --set MODULE_NAME=<module> --set MODULE_SOURCE=<source-folder> --stage <stage>
```

- `<env>`: the `--env` argument, else `SNOWFLAKE_ENV`, else `db.kb_environment` in `.devin/rules/kb-profile.yaml` (prod). ETL prompts only use it to name the database in the document header.
- `<module>` and `<source-folder>`: the module argument, else `etl.modules` in `.devin/rules/kb-profile.yaml` (`claims-etl`). The source folder is the ETL clone at `etl.clone_dir` (`../claims-etl`, next to this repo). If it isn't there, clone `etl.source_repo`, and record its commit in the output header.
- `<stage>`: the folder the caller passes (for example `/kb-build`), else `docs/knowledge-base/_REGEN/<YYYY-MM-DD>` with today's date. Output never goes straight into the live knowledge base. `/kb-compare` moves it there after the owner approves the comparison.
- Read the rendered prompt from `/tmp/kb-<id>.md`. Scratch files stay outside the repo.

If `lint` or `render` fails (a missing profile value, an unknown environment), stop and report the message. Don't fill values in by hand.

## 2. Run it

Read the rendered prompt in full and follow it: its steps, output files, evidence tags (`[E: source]`, `[A]`, `[?]`), self-check and closing lists. Write only the files that `outputs` listed. When a staged input doesn't exist yet, the prompt tells you to read the live copy instead.

## 3. Gate

⛔ Stop here. A business analyst (BSA) must review and approve before `/etl-frd` runs. Present it as `.devin/rules/gate-presentation.md` describes. Record who approved and when. Don't approve on anyone's behalf.

With `--rebuild` (a side-by-side rebuild of documents that already exist, started by `/kb-build`), don't stop: record the gate as `deferred to /kb-compare review` and carry on. The staged files replace nothing until the owner approves the comparison. A first build always stops here.

## When done

State: "ETL BRD COMPLETE — awaiting BSA review". Then list the files written, the environment used and the self-check items still open.
