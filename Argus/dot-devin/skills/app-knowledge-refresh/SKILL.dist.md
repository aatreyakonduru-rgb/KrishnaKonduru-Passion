---
name: app-knowledge-refresh
description: 'Knowledge base refresh: runs shared prompt DB-SD (staleness check), reruns only the DB stages
  it names into a staging folder, and compares them with the live KB. Needs read-only Snowflake access
  (prod by default).'
argument-hint: '[trigger: post-pr|scheduled|manual] [--env dev|sit|uat|prod] [--stage <dir>] [--rebuild]'
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

# Knowledge base refresh

This skill runs the shared prompt **DB-SD** (`sdlc/kb/kb-prompts/DB_PROMPT_STALENESS_DETECTION.md`) with our team values from `.devin/rules/kb-profile.yaml`. The prompt holds the instructions. This skill fills it in, runs it and handles the gate. The older ACME-specific copies are archived under `docs/knowledge-base/Archive/PROMPTS/`; don't use them.

## 1. Fill in the prompt

```bash
python3 sdlc/kb/tools/prompts.py lint      # stop if it reports an error
python3 sdlc/kb/tools/prompts.py render DB_PROMPT_STALENESS_DETECTION.md --env <env> --stage <stage> --out /tmp/kb-DB-SD.md
python3 sdlc/kb/tools/prompts.py outputs DB_PROMPT_STALENESS_DETECTION.md --env <env> --stage <stage>
```

- `<env>`: the `--env` argument, else `SNOWFLAKE_ENV`, else `db.kb_environment` in `.devin/rules/kb-profile.yaml`. Our DB knowledge base is built from **prod**, so that is the default. Print `Snowflake target: <database> (<env>)` once. The output folder follows the environment: `docs_dir` in `.devin/rules/snowflake-environments.yaml` puts prod at the `DB-DOCS/` root and the lower regions in `DB-DOCS/SIT/`, `DB-DOCS/DEV/` and `DB-DOCS/UAT/`. `render` and `outputs` already apply it, so a lower-region run never writes a prod file.
- `<stage>`: the folder the caller passes (for example `/kb-build`), else `docs/knowledge-base/_REGEN/<YYYY-MM-DD>` with today's date. Output never goes straight into the live knowledge base. `/kb-compare` moves it there after the owner approves the comparison.
- Read the rendered prompt from `/tmp/kb-<id>.md`. Scratch files stay outside the repo.

If `lint` or `render` fails (a missing profile value, an unknown environment), stop and report the message. Don't fill values in by hand.

## 1a. Decide what else to re-run

The drift report says what changed. `refresh_cascade` in `.devin/rules/kb-prompt-wiring.yaml`
gives the smallest set of stages to re-run for each kind of change (new table, new column, new
code value, new endpoint, new screen component, new ETL script). List those stages in the report
as the suggested follow-up; this skill doesn't run them.

## 2. Run it

Read the rendered prompt in full and follow it: its steps, output files, evidence tags (`[E: source]`, `[A]`, `[?]`), self-check and closing lists. Write only the files that `outputs` listed. When a staged input doesn't exist yet, the prompt tells you to read the live copy instead.

**Snowflake.** Run SELECT statements only. Prefer the nonprod MCP (`sql_exec_tool`, one statement per call; check with `SELECT CURRENT_USER(), CURRENT_ROLE();`). It reaches dev and sit only. For prod, use a prod connection on Devin Desktop (`snowsql`). If the target database isn't reachable, stop and say so. Don't switch to another environment unless asked. If asked, the output goes to that environment's own folder, never over the prod set.

**Refreshing.** The trigger (`post-pr`, `scheduled` or `manual`) comes from the argument. For
`post-pr`, ask for the PR and its CTASK reference if they aren't given.

1. Run DB-SD, as above. It compares today's schema with the stored discovery report and names
   the documents to rebuild. If its report says nothing changed, say "No schema changes detected
   since last refresh. KB is current." and stop.
2. The stored report is the environment's own: `DB-DOCS/` for prod, `DB-DOCS/SIT/` for
   sit, `DB-DOCS/DEV/` for dev. If that folder has no discovery report yet, this is a first
   run for the environment: use `/db-discovery --env <env>` instead. If the report names a
   different database than the target, stop: it's the wrong folder.
3. Rerun only the stages the report points to, by invoking their skills (`/db-discovery`,
   `/db-trd`, `/db-supporting`, `/db-diagrams`, `/db-security` and so on). Pass the same
   `--env` and `--stage`. Then run `/db-validation`.
4. Run `/kb-compare` on the stage folder. Its report goes with the refresh for review.

## 3. Gate

⛔ Stop here. A tech lead must review and approve before any staged file replaces the live copy through `/kb-compare`. Present it as `.devin/rules/gate-presentation.md` describes. Record who approved and when. Don't approve on anyone's behalf.

With `--rebuild` (a side-by-side rebuild of documents that already exist, started by `/kb-build`), don't stop: record the gate as `deferred to /kb-compare review` and carry on. The staged files replace nothing until the owner approves the comparison. A first build always stops here.

## When done

State: "Knowledge refresh COMPLETE — awaiting tech lead review of the comparison". Then list the files written, the environment used and the self-check items still open.
