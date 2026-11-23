---
name: app-gap-fill
description: 'Gap-fill reading for one module, for areas still marked [?]: runs shared prompt APP-GAP
  with the team profile into a staging folder.'
argument-hint: <module> [<session_id>] [<file_list>] [--stage <dir>]
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

# Module gap-fill

`$METIS` below is the Mētis plugin folder: the folder two levels above this SKILL.md. `<KB>` is the knowledge-base folder named in the Mētis settings (`<KB>/.metis/kb-profile.yaml`). Follow `$METIS/rules/metis-evidence.md` and `$METIS/rules/metis-writes.md` throughout.
Work as the discoverer agent: read `$METIS/agents/discoverer/AGENT.md` first and follow it.

This skill runs the shared prompt **APP-GAP** (`$METIS/kb-prompts/PROMPT_GAP_FILL.md`) with the team values from `<KB>/.metis/kb-profile.yaml`. The prompt holds the instructions. This skill fills it in, runs it and handles the gate.

## 1. Fill in the prompt

```bash
python3 $METIS/tools/prompts.py lint      # stop if it reports an error
python3 $METIS/tools/prompts.py render PROMPT_GAP_FILL.md --env <env> --set MODULE_NAME=<module> --set MODULE_SOURCE=<source-folder> --stage <stage> --out /tmp/kb-APP-GAP.md
python3 $METIS/tools/prompts.py outputs PROMPT_GAP_FILL.md --env <env> --set MODULE_NAME=<module> --set MODULE_SOURCE=<source-folder> --stage <stage>
```

- `<env>`: the `--env` argument, else `reference_environment` in `<KB>/.metis/db-environments.yaml`; `<db>`: the `--db` label, else each database of that environment in turn (render prompts with `METIS_DB=<label>`). Tables are named `<database>.<schema>.<table>`; cover every schema of the database. App prompts only use it to name the database in the document header.
- `<module>` and `<source-folder>`: the module argument, e.g. `api` or `web`. It must be one of `app.source_dirs` in `<KB>/.metis/kb-profile.yaml`, or a sub-folder of one. Use the folder name as the module name unless the caller gives another.
- `<stage>`: the folder the caller passes (for example `kb-build`), else `<KB>/_REGEN/<YYYY-MM-DD>` with today's date. Output never goes straight into the live knowledge base. `kb-compare` moves it there after the owner approves the comparison.
- Read the rendered prompt from `/tmp/kb-<id>.md`. Scratch files stay outside the repo.

If `lint` or `render` fails (a missing profile value, an unknown environment), stop and report the message. Don't fill values in by hand.

## 2. Run it

Read the rendered prompt in full and follow it: its steps, output files, evidence tags (`[E: source]` and `[?: Q-xxxx]`, as `$METIS/rules/metis-evidence.md` sets out; no `[A]`), self-check and closing lists. Write only the files that `outputs` listed. When a staged input doesn't exist yet, the prompt tells you to read the live copy instead.

**Session and files.** Use the session ID from the argument where the prompt's output name has `<SESSION_ID>`. If none is given, use today's date. When a file list is given, read those files; otherwise take the areas marked `[?]` in the module's documents. Run `app-validation-log` afterwards.

## 3. Gate

No gate at this stage.

## When done

State: "Gap-fill session COMPLETE". Then list the files written, the environment used and the self-check items still open.
