---
name: app-brd
description: 'Module business requirements (BRD): runs shared prompt APP-02 with the team profile into
  a staging folder.'
argument-hint: <module> [--stage <dir>] [--rebuild]
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

# Module business requirements

This skill runs the shared prompt **APP-02** (`sdlc/kb/kb-prompts/PROMPT_2_BUSINESS_REQUIREMENTS.md`) with our team values from `.devin/rules/kb-profile.yaml`. The prompt holds the instructions. This skill fills it in, runs it and handles the gate. The older ACME-specific copies are archived under `docs/knowledge-base/Archive/PROMPTS/`; don't use them.

## 1. Fill in the prompt

```bash
python3 sdlc/kb/tools/prompts.py lint      # stop if it reports an error
python3 sdlc/kb/tools/prompts.py render PROMPT_2_BUSINESS_REQUIREMENTS.md --env <env> --set MODULE_NAME=<module> --set MODULE_SOURCE=<source-folder> --stage <stage> --out /tmp/kb-APP-02.md
python3 sdlc/kb/tools/prompts.py outputs PROMPT_2_BUSINESS_REQUIREMENTS.md --env <env> --set MODULE_NAME=<module> --set MODULE_SOURCE=<source-folder> --stage <stage>
```

- `<env>`: the `--env` argument, else `SNOWFLAKE_ENV`, else `db.kb_environment` in `.devin/rules/kb-profile.yaml` (prod). App prompts only use it to name the database in the document header.
- `<module>` and `<source-folder>`: the module argument, e.g. `api` or `web`. It must be one of `app.source_dirs` in `.devin/rules/kb-profile.yaml`, or a sub-folder of one. Use the folder name as the module name unless the caller gives another.
- `<stage>`: the folder the caller passes (for example `/kb-build`), else `docs/knowledge-base/_REGEN/<YYYY-MM-DD>` with today's date. Output never goes straight into the live knowledge base. `/kb-compare` moves it there after the owner approves the comparison.
- Read the rendered prompt from `/tmp/kb-<id>.md`. Scratch files stay outside the repo.

If `lint` or `render` fails (a missing profile value, an unknown environment), stop and report the message. Don't fill values in by hand.

## 2. Run it

Read the rendered prompt in full and follow it: its steps, output files, evidence tags (`[E: source]`, `[A]`, `[?]`), self-check and closing lists. Write only the files that `outputs` listed. When a staged input doesn't exist yet, the prompt tells you to read the live copy instead.

## 3. Gate

⛔ Stop here. A business analyst (BSA) must review and approve before `/app-frd` runs. Present it as `.devin/rules/gate-presentation.md` describes. Record who approved and when. Don't approve on anyone's behalf.

With `--rebuild` (a side-by-side rebuild of documents that already exist, started by `/kb-build`), don't stop: record the gate as `deferred to /kb-compare review` and carry on. The staged files replace nothing until the owner approves the comparison. A first build always stops here.

## When done

State: "BRD COMPLETE — awaiting BSA review". Then list the files written, the environment used and the self-check items still open.
