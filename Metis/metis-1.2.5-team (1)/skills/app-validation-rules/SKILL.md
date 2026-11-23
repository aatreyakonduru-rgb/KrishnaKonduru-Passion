---
name: app-validation-rules
description: 'Module validation rules catalogue (14_VALIDATION_RULES_CATALOGUE.md): runs shared prompt
  APP-14 with the team profile into a staging folder.'
argument-hint: <module> [--stage <dir>]
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

# Module validation rules catalogue

`$METIS` below is the Mētis plugin folder: the folder two levels above this SKILL.md. `<KB>` is the knowledge-base folder named in the Mētis settings (`<KB>/.metis/kb-profile.yaml`). Follow `$METIS/rules/metis-evidence.md` and `$METIS/rules/metis-writes.md` throughout.
Work as the documenter agent: read `$METIS/agents/documenter/AGENT.md` first and follow it.

This skill runs the shared prompt **APP-14** (`$METIS/kb-prompts/PROMPT_14_VALIDATION_RULES_CATALOGUE.md`) with the team values from `<KB>/.metis/kb-profile.yaml`. The prompt holds the instructions. This skill fills it in, runs it and handles the gate. The stage order is in `<KB>/.metis/kb-prompt-wiring.yaml`.

## 1. Fill in the prompt

```bash
python3 $METIS/tools/prompts.py lint      # stop if it reports an error
python3 $METIS/tools/prompts.py render PROMPT_14_VALIDATION_RULES_CATALOGUE.md --env <env> --set MODULE_NAME=<module> --set MODULE_SOURCE=<source-folder> --stage <stage> --out /tmp/kb-APP-14.md
python3 $METIS/tools/prompts.py outputs PROMPT_14_VALIDATION_RULES_CATALOGUE.md --env <env> --set MODULE_NAME=<module> --set MODULE_SOURCE=<source-folder> --stage <stage>
```

- `<env>`: the `--env` argument, else `reference_environment` in `<KB>/.metis/db-environments.yaml`; `<db>`: the `--db` label, else each database of that environment in turn (render prompts with `METIS_DB=<label>`). Tables are named `<database>.<schema>.<table>`; cover every schema of the database. App prompts only use it to name the database in the document header.
- `<module>` and `<source-folder>`: the module argument, e.g. `api` or `web`. It must be one of `app.source_dirs` in `<KB>/.metis/kb-profile.yaml`, or a sub-folder of one. Use the folder name as the module name unless the caller gives another.
- `<stage>`: the folder the caller passes (for example `kb-build`), else `<KB>/_REGEN/<YYYY-MM-DD>` with today's date. Output never goes straight into the live knowledge base. `kb-compare` moves it there after the owner approves the comparison.
- Read the rendered prompt from `/tmp/kb-<id>.md`. Scratch files stay outside the repo.

If `lint` or `render` fails (a missing profile value, an unknown environment), stop and report the message. Don't fill values in by hand.

## 2. Run it

Read the rendered prompt in full and follow it: its steps, output files, evidence tags (`[E: source]` and `[?: Q-xxxx]`, as `$METIS/rules/metis-evidence.md` sets out; no `[A]`), self-check and closing lists. Write only the files that `outputs` listed. When a staged input doesn't exist yet, the prompt tells you to read the live copy instead.

Every rule names where it is enforced: the screen, the API, the database, or more than one. A rule enforced only on the screen is flagged.

## 3. Gate

No gate at this stage.

## When done

State: "Validation Rules Catalogue COMPLETE". Then list the files written, the environment used and the self-check items still open.
