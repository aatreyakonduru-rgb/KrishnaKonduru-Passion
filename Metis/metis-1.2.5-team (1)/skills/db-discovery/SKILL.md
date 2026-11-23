---
name: db-discovery
description: 'Database discovery for one database and all its schemas (any engine): runs shared prompts DB-01 (discovery) and DB-01A
  (discovery check) with the team profile into a staging folder. Needs read-only access to the database, or its schema files.'
argument-hint: '[--env <env>] [--db <label>] [--stage <dir>] [--rebuild]'
allowed-tools:
- read
- grep
- glob
- exec
- edit
- mcp__snowflake__sql_exec_tool
visibility: internal
triggers:
- model
---

# Database discovery

`$METIS` below is the Mētis plugin folder: the folder two levels above this SKILL.md. `<KB>` is the knowledge-base folder named in the Mētis settings (`<KB>/.metis/kb-profile.yaml`). Follow `$METIS/rules/metis-evidence.md` and `$METIS/rules/metis-writes.md` throughout.
Work as the db-analyst agent: read `$METIS/agents/db-analyst/AGENT.md` first and follow it.

This skill runs the shared prompts **DB-01** (`$METIS/kb-prompts/DB_PROMPT_1_DISCOVERY.md`), **DB-01A** (`$METIS/kb-prompts/DB_PROMPT_1.5_DISCOVERY_VALIDATION.md`) with the team values from `<KB>/.metis/kb-profile.yaml`. The prompt holds the instructions. This skill fills it in, runs it and handles the gate.

## 1. Fill in the prompt

```bash
python3 $METIS/tools/prompts.py lint      # stop if it reports an error
python3 $METIS/tools/prompts.py render DB_PROMPT_1_DISCOVERY.md --env <env> --stage <stage> --out /tmp/kb-DB-01.md
python3 $METIS/tools/prompts.py outputs DB_PROMPT_1_DISCOVERY.md --env <env> --stage <stage>
python3 $METIS/tools/prompts.py render DB_PROMPT_1.5_DISCOVERY_VALIDATION.md --env <env> --stage <stage> --out /tmp/kb-DB-01A.md
python3 $METIS/tools/prompts.py outputs DB_PROMPT_1.5_DISCOVERY_VALIDATION.md --env <env> --stage <stage>
```

- `<env>`: the `--env` argument, else `reference_environment` in `<KB>/.metis/db-environments.yaml`; `<db>`: the `--db` label, else each database of that environment in turn (render prompts with `METIS_DB=<label>`). Tables are named `<database>.<schema>.<table>`; cover every schema of the database. Print `Database: <label> <database> (<engine>, <env>)` once. The output folder follows the environment: `docs_dir` in `<KB>/.metis/db-environments.yaml` gives each environment its own folder under `DB-DOCS/`. `render` and `outputs` already apply it, so a run for one environment never writes over another's files.
- `<stage>`: the folder the caller passes (for example `kb-build`), else `<KB>/_REGEN/<YYYY-MM-DD>` with today's date. Output never goes straight into the live knowledge base. `kb-compare` moves it there after the owner approves the comparison.
- Read the rendered prompt from `/tmp/kb-<id>.md`. Scratch files stay outside the repo.

If `lint` or `render` fails (a missing profile value, an unknown environment), stop and report the message. Don't fill values in by hand.

## 2. Run it

Run the prompts in the order listed. Read the rendered prompt in full and follow it: its steps, output files, evidence tags (`[E: source]` and `[?: Q-xxxx]`, as `$METIS/rules/metis-evidence.md` sets out; no `[A]`), self-check and closing lists. Write only the files that `outputs` listed. When a staged input doesn't exist yet, the prompt tells you to read the live copy instead.

**Database access.** Read only: SELECT, SHOW and DESCRIBE. Use the Devin connection named for this database in `<KB>/.metis/db-environments.yaml`, one statement per call, and check it first with the read-only identity query for its engine (Snowflake `SELECT CURRENT_USER(), CURRENT_ROLE();`, PostgreSQL `SELECT current_user, current_database();`). Run the catalogue queries `db_catalog.py plan` wrote. For `engine: schema-files` the CREATE TABLE files are the only source. Where this step names a Snowflake-only feature (warehouses, masking policies, Cortex) and the engine is not Snowflake, write that section as "not applicable: <engine>". If the database isn't reachable, say so in BUILD.md and carry on. Don't switch to another environment unless asked; that environment's output goes to its own folder.

Save every catalogue query as `<KB>/_EVIDENCE/queries/<prompt id>-Q<n>.sql` and its result as `.json`, and cite it as `[E: query:<prompt id>-Q<n>]`. Never run DDL, DML or a COMMENT ON script.

## 3. Gate

⛔ Stop here. A tech lead named on the gate must review and approve (the owner for this step named under `owners` in the Mētis settings) before `db-brd` runs. Present it as `$METIS/rules/metis-approvals.md` describes. Record who approved and when. Don't approve on anyone's behalf.

With `--rebuild` (a side-by-side rebuild of documents that already exist, started by `kb-build`), don't stop: record the gate as `deferred to kb-compare review` and carry on. The staged files replace nothing until the owner approves the comparison. A first build always stops here.

## When done

State: "DB Discovery COMPLETE — awaiting discovery validation". Then list the files written, the environment used and the self-check items still open.

## 1.1.0 additions
- Catalogue every schema of every database in every environment (dev and SIT at least), not only the schemas the apps use: GBD/NOGBD, PHI tiers (ALLPHI/NOPHI/NOHAPHI/FEPNOHAPHI/HANOFEPPHI/DETOK), ACTV/PSSV, UI/PLAIN, BKP, STG, RAWZ, SEMANTIC, APPCODE, INTERAPP. Group them by schema family + variant.
- Snowflake MCP results are silently truncated on large result sets. Page `INFORMATION_SCHEMA` queries with `ORDER BY ... LIMIT 1500 OFFSET n`, check `len(data) == resultSetMetaData.numRows` on every page, save each page to disk and resume from saved pages (long tool scripts get cancelled whenever the user sends a message).
- The MCP returns a `result_set` envelope; convert `data` + `rowType` to row dicts before the generators read it (1.0.0 crashed with `'str' object has no attribute 'items'`).
