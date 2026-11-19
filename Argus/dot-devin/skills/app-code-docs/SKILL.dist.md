---
name: app-code-docs
description: 'Detailed function-level code documentation for a module (DETAILED_CODE_DOCUMENTATION.md):
  runs shared prompt HELP-CODEDOC with the team profile into a staging folder.'
argument-hint: <module> [--stage <dir>]
subagent: true
agent: documenter
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

# Detailed function-level code documentation for a module

This skill runs the shared prompt **HELP-CODEDOC** (`sdlc/kb/kb-prompts/DETAILED_CODE_DOCUMENTATION.md`) with our team values from `.devin/rules/kb-profile.yaml`. The prompt holds the instructions. This skill fills it in, runs it and handles the gate. The stage order is in `.devin/rules/kb-prompt-wiring.yaml`.

## 1. Fill in the prompt

```bash
python3 sdlc/kb/tools/prompts.py lint      # stop if it reports an error
python3 sdlc/kb/tools/prompts.py render DETAILED_CODE_DOCUMENTATION.md --env <env> --set MODULE_NAME=<module> --set MODULE_SOURCE=<source-folder> --stage <stage> --out /tmp/kb-HELP-CODEDOC.md
python3 sdlc/kb/tools/prompts.py outputs DETAILED_CODE_DOCUMENTATION.md --env <env> --set MODULE_NAME=<module> --set MODULE_SOURCE=<source-folder> --stage <stage>
```

- `<env>`: the `--env` argument, else `SNOWFLAKE_ENV`, else `db.kb_environment` in `.devin/rules/kb-profile.yaml` (prod). App prompts only use it to name the database in the document header.
- `<module>` and `<source-folder>`: the module argument, e.g. `api` or `web`. It must be one of `app.source_dirs` in `.devin/rules/kb-profile.yaml`, or a sub-folder of one. Use the folder name as the module name unless the caller gives another.
- `<stage>`: the folder the caller passes (for example `/kb-build`), else `docs/knowledge-base/_REGEN/<YYYY-MM-DD>` with today's date. Output never goes straight into the live knowledge base. `/kb-compare` moves it there after the owner approves the comparison.
- Read the rendered prompt from `/tmp/kb-<id>.md`. Scratch files stay outside the repo.

If `lint` or `render` fails (a missing profile value, an unknown environment), stop and report the message. Don't fill values in by hand.

## 2. Run it

Read the rendered prompt in full and follow it: its steps, output files, evidence tags (`[E: source]`, `[A]`, `[?]`), self-check and closing lists. Write only the files that `outputs` listed. When a staged input doesn't exist yet, the prompt tells you to read the live copy instead.

Optional. Run it for modules where agents will change code often. It needs the module's discovery report (APP-01) first.

## 3. Gate

No gate at this stage.

## When done

State: "Detailed Code Documentation COMPLETE". Then list the files written, the environment used and the self-check items still open.
