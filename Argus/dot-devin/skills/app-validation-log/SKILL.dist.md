---
name: app-validation-log
description: 'Module validation log and session state: runs shared prompt APP-08 with the team profile
  into a staging folder, after any other module stage.'
argument-hint: <module> [--stage <dir>]
subagent: true
agent: validator
allowed-tools:
- read
- edit
- grep
- glob
- exec
visibility: internal
triggers:
- user
- model
---

# Module validation log

This skill runs the shared prompt **APP-08** (`sdlc/kb/kb-prompts/PROMPT_8_VALIDATION_LOG_UPDATE.md`) with our team values from `.devin/rules/kb-profile.yaml`. The prompt holds the instructions. This skill fills it in, runs it and handles the gate. The older ACME-specific copies are archived under `docs/knowledge-base/Archive/PROMPTS/`; don't use them.

## 1. Fill in the prompt

```bash
python3 sdlc/kb/tools/prompts.py lint      # stop if it reports an error
python3 sdlc/kb/tools/prompts.py render PROMPT_8_VALIDATION_LOG_UPDATE.md --env <env> --set MODULE_NAME=<module> --set MODULE_SOURCE=<source-folder> --stage <stage> --out /tmp/kb-APP-08.md
python3 sdlc/kb/tools/prompts.py outputs PROMPT_8_VALIDATION_LOG_UPDATE.md --env <env> --set MODULE_NAME=<module> --set MODULE_SOURCE=<source-folder> --stage <stage>
```

- `<env>`: the `--env` argument, else `SNOWFLAKE_ENV`, else `db.kb_environment` in `.devin/rules/kb-profile.yaml` (prod). App prompts only use it to name the database in the document header.
- `<module>` and `<source-folder>`: the module argument, e.g. `api` or `web`. It must be one of `app.source_dirs` in `.devin/rules/kb-profile.yaml`, or a sub-folder of one. Use the folder name as the module name unless the caller gives another.
- `<stage>`: the folder the caller passes (for example `/kb-build`), else `docs/knowledge-base/_REGEN/<YYYY-MM-DD>` with today's date. Output never goes straight into the live knowledge base. `/kb-compare` moves it there after the owner approves the comparison.
- Read the rendered prompt from `/tmp/kb-<id>.md`. Scratch files stay outside the repo.

If `lint` or `render` fails (a missing profile value, an unknown environment), stop and report the message. Don't fill values in by hand.

## 2. Run it

Read the rendered prompt in full and follow it: its steps, output files, evidence tags (`[E: source]`, `[A]`, `[?]`), self-check and closing lists. Write only the files that `outputs` listed. When a staged input doesn't exist yet, the prompt tells you to read the live copy instead.

## 3. Gate

No gate at this stage.

## When done

State: "Validation Log updated". Then list the files written, the environment used and the self-check items still open.
