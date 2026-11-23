---
name: db-term-map
description: 'Database business-term map (stage 8.6): runs shared prompt DB-19 with the team profile into a staging folder. Maps business language to tables, columns and metrics, with ambiguity and rejection handling. Needs the entity registry, column profile, metrics and query history.'
argument-hint: '[--env <env>] [--db <label>] [--stage <dir>]'
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

# Database business-term map

`$METIS` below is the Mētis plugin folder: the folder two levels above this SKILL.md. `<KB>` is the knowledge-base folder named in the Mētis settings (`<KB>/.metis/kb-profile.yaml`). Follow `$METIS/rules/metis-evidence.md` and `$METIS/rules/metis-writes.md` throughout.
Work as the db-analyst agent: read `$METIS/agents/db-analyst/AGENT.md` first and follow it.

This skill runs the shared prompt **DB-19** (`$METIS/kb-prompts/DB_PROMPT_19_TERM_MAP.md`) with the team values from `<KB>/.metis/kb-profile.yaml`. The prompt holds the instructions. This skill fills it in and runs it.

## 1. Fill in the prompt

```bash
python3 $METIS/tools/prompts.py lint      # stop if it reports an error
python3 $METIS/tools/prompts.py render DB_PROMPT_19_TERM_MAP.md --env <env> --stage <stage> --out /tmp/kb-DB-19.md
python3 $METIS/tools/prompts.py outputs DB_PROMPT_19_TERM_MAP.md --env <env> --stage <stage>
```

- `<env>` and `<stage>` as in the other DB skills. `<stage>` defaults to `<KB>/_REGEN/<YYYY-MM-DD>`.
- Read the rendered prompt from `/tmp/kb-DB-19.md`. Scratch files stay outside the repo.

If `lint` or `render` fails, stop and report the message. Don't fill values in by hand.

## 2. Run it

**Preconditions.** These must exist in the stage folder or the live copy: `13_DB_ENTITY_REGISTRY.yaml` (DB-13), `17_DB_COLUMN_PROFILE.json` (DB-17), `18_DB_METRICS.yaml` (DB-18), and `20_DB_USAGE_PATTERNS.md` (DB-20). If one is missing, stop and report it.

Run the prompt in full: its steps, output files, evidence tags (`[E: source]` and `[?: Q-xxxx]`; no `[A]`), self-check and closing lists. Write only the files that `outputs` listed.

**Database access.** None. This prompt works from the files above. Never read a data value. Never run DDL, DML or a COMMENT ON script.

Business terms come from the domain context, the team glossary (`CTX-0E`), field labels and query results, as the prompt lists them. Each term needs a source. Record a term with no column as unmapped, and a term that fits two columns as ambiguous. Don't pick one.

## 3. Gate

No gate at this stage.

## When done

State: "DB Term map COMPLETE". Then list the files written, the count of mapped, ambiguous and unmapped terms, and the self-check items still open.
