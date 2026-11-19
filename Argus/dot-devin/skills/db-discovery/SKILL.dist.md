---
name: db-discovery
description: 'Database discovery for our Snowflake schema: runs shared prompts DB-01 (discovery) and DB-01A
  (discovery check) with the team profile into a staging folder. Needs read-only Snowflake access to the
  target environment (prod by default).'
argument-hint: '[--env dev|sit|uat|prod] [--stage <dir>] [--rebuild]'
subagent: true
agent: db-analyst
allowed-tools:
- read
- grep
- glob
- exec
- edit
- mcp__acme-snowflake__sql_exec_tool
visibility: internal
triggers:
- user
- model
---

# Database discovery

This skill runs the shared prompts **DB-01** (`sdlc/kb/kb-prompts/DB_PROMPT_1_DISCOVERY.md`), **DB-01A** (`sdlc/kb/kb-prompts/DB_PROMPT_1.5_DISCOVERY_VALIDATION.md`) with our team values from `.devin/rules/kb-profile.yaml`. The prompt holds the instructions. This skill fills it in, runs it and handles the gate. The older ACME-specific copies are archived under `docs/knowledge-base/Archive/PROMPTS/`; don't use them.

## 1. Fill in the prompt

```bash
python3 sdlc/kb/tools/prompts.py lint      # stop if it reports an error
python3 sdlc/kb/tools/prompts.py render DB_PROMPT_1_DISCOVERY.md --env <env> --stage <stage> --out /tmp/kb-DB-01.md
python3 sdlc/kb/tools/prompts.py outputs DB_PROMPT_1_DISCOVERY.md --env <env> --stage <stage>
python3 sdlc/kb/tools/prompts.py render DB_PROMPT_1.5_DISCOVERY_VALIDATION.md --env <env> --stage <stage> --out /tmp/kb-DB-01A.md
python3 sdlc/kb/tools/prompts.py outputs DB_PROMPT_1.5_DISCOVERY_VALIDATION.md --env <env> --stage <stage>
```

- `<env>`: the `--env` argument, else `SNOWFLAKE_ENV`, else `db.kb_environment` in `.devin/rules/kb-profile.yaml`. Our DB knowledge base is built from **prod**, so that is the default. Print `Snowflake target: <database> (<env>)` once. The output folder follows the environment: `docs_dir` in `.devin/rules/snowflake-environments.yaml` puts prod at the `DB-DOCS/` root and the lower regions in `DB-DOCS/SIT/`, `DB-DOCS/DEV/` and `DB-DOCS/UAT/`. `render` and `outputs` already apply it, so a lower-region run never writes a prod file.
- `<stage>`: the folder the caller passes (for example `/kb-build`), else `docs/knowledge-base/_REGEN/<YYYY-MM-DD>` with today's date. Output never goes straight into the live knowledge base. `/kb-compare` moves it there after the owner approves the comparison.
- Read the rendered prompt from `/tmp/kb-<id>.md`. Scratch files stay outside the repo.

If `lint` or `render` fails (a missing profile value, an unknown environment), stop and report the message. Don't fill values in by hand.

## 2. Run it

Run the prompts in the order listed. Read the rendered prompt in full and follow it: its steps, output files, evidence tags (`[E: source]`, `[A]`, `[?]`), self-check and closing lists. Write only the files that `outputs` listed. When a staged input doesn't exist yet, the prompt tells you to read the live copy instead.

**Snowflake.** Run SELECT statements only. Prefer the nonprod MCP (`sql_exec_tool`, one statement per call; check with `SELECT CURRENT_USER(), CURRENT_ROLE();`). It reaches dev and sit only. For prod, use a prod connection on Devin Desktop (`snowsql`). If the target database isn't reachable, stop and say so. Don't switch to another environment unless asked. If asked, the output goes to that environment's own folder, never over the prod set.

**Shortcut for the metadata-only documents** (discovery report, schema catalogue, code values,
security inventory, delta against prod, table registry): run the queries printed by
`python3 sdlc/framework/tools/kbgen/extract_db_snapshot.py --env <env>` read-only, save
the results as JSON, then run
`python3 sdlc/framework/tools/kbgen/gen_db_kb.py --env <env> --snapshot <folder>`.
For the AI-facing assets (ERD, COMMENT ON script, Cortex Analyst model, code-value questions), run
`extract_app_joins.py` once, then `gen_semantic_assets.py --env <env> --snapshot <folder> --register`
and `python3 sdlc/framework/tools/gen_validation_form.py docs/knowledge-base/VALIDATION/KB_OPEN_QUESTIONS.yaml`.
These scripts write into the environment's `docs_dir` in the live KB, not the stage folder, and
they run no SQL. Use them for a lower region's metadata set. The COMMENT ON script is for DBA
review; never run it.

## 3. Gate

⛔ Stop here. A tech lead named on the gate must review and approve (`DB_02_DISCOVERY_VALIDATION` in `.devin/rules/approval-gates.yaml`) before `/db-brd` runs. Present it as `.devin/rules/gate-presentation.md` describes. Record who approved and when. Don't approve on anyone's behalf.

With `--rebuild` (a side-by-side rebuild of documents that already exist, started by `/kb-build`), don't stop: record the gate as `deferred to /kb-compare review` and carry on. The staged files replace nothing until the owner approves the comparison. A first build always stops here.

## When done

State: "DB Discovery COMPLETE — awaiting discovery validation". Then list the files written, the environment used and the self-check items still open.
