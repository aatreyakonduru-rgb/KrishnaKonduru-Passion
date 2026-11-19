---
name: kb-build
description: Rebuild knowledge-base documents side by side from the shared prompts in sdlc/kb/kb-prompts/ and the kbgen scripts, into a staging folder (_REGEN/<date>) that never touches the live KB. Use before /kb-compare when checking the KB for staleness or after changing a shared prompt.
argument-hint: "<app|etl|db|context|all> [--module <name>] [--env dev|sit|uat|prod]... [--stage <dir>] [--with-context]"
allowed-tools:
  - read
  - write
  - edit
  - grep
  - glob
  - exec
visibility: internal
triggers:
  - user
  - model
---

# KB build (side-by-side rebuild)

Runs the knowledge-base pipelines into a staging folder so the result can be compared with the
live KB. Nothing under the live KB changes. `/kb-compare` does the comparison, and replaces
files only after the owner approves it.

This skill runs in the main session (no `subagent: true`), so the stage skills it starts keep
their own `agent:` profiles.

## Step 0 — set up

1. `<stage>` is the `--stage` argument, else `docs/knowledge-base/_REGEN/<YYYY-MM-DD>`
   with today's date. Pass `--stage <stage> --rebuild` to every stage skill below.
2. Run `python3 sdlc/kb/tools/prompts.py lint`. Stop if it reports an error.
3. Record the branch and commit (`git rev-parse --short HEAD`) in `<stage>/BUILD.md`, with the
   scope, the environment and today's date. Add a line per step as it finishes.
4. `--rebuild` lets stage skills run past their review gates, recorded as
   `deferred to /kb-compare review`. That is only for documents that already exist. If a module or
   environment has no live documents yet, stop and run its pipeline normally, with the gates.

## app — API and UI modules

1. Deterministic registries first. They come from the source, exactly:
   ```bash
   cd sdlc/framework/tools/kbgen
   python3 extract_api.py > /tmp/kb-api.json
   SDLC_KB_OUT=../../../../<stage> python3 gen_api_kb.py /tmp/kb-api.json   # endpoint registry, API contracts
   SDLC_KB_OUT=../../../../<stage> python3 gen_ui_kb.py                     # component registry
   ```
   `SDLC_KB_OUT` is relative to the kbgen folder here; an absolute path works too.
2. The narrative documents: for each module (`--module`, else each live folder under
   `paths.module_docs` in `.devin/rules/kb-profile.yaml`), run
   `/app-run-pipeline <module> <source folder> --stage <stage> --rebuild`. The source folder must
   be one of `app.source_dirs`. Do the API modules before the UI modules that call them.
3. Check the three registries against the self-check lists in their prompts: APP-10
   (`PROMPT_10_ENDPOINT_REGISTRY.md`), APP-11 (`PROMPT_11_API_DATA_CONTRACTS.md`) and APP-12
   (`PROMPT_12_COMPONENT_REGISTRY.md`) in `sdlc/kb/kb-prompts/`. The prompts describe the same files for teams without the scripts;
   don't run them to write the files.

## etl — batch and ETL modules

For each module (`--module`, else each entry of `etl.modules` in `.devin/rules/kb-profile.yaml`),
run `/etl-run-pipeline <module> --stage <stage> --rebuild`. It clones or pulls the ETL repo,
records its commit, runs ETL-01 to ETL-12 and builds the ETL-13 table contract with
`gen_etl_kb.py`.

## db — Snowflake documents

`<env>` is the `--env` argument, else `db.kb_environment` in `kb-profile.yaml`. Our DB knowledge
base is built from **prod**, at the `DB-DOCS/` root. The dev, SIT and UAT sets live in their own
folders (`docs_dir` in `.devin/rules/snowflake-environments.yaml`), and a run for one of them
never writes a prod file. The Devin Cloud Snowflake connection only reaches dev and SIT, so a prod
rebuild has to run where there is read-only prod access, such as Devin Desktop. If `--env` isn't
given and prod can't be reached, stop and say so. Don't fall back to another environment without
being asked.

With the connection confirmed (`SELECT CURRENT_USER(), CURRENT_ROLE();`):

1. **Lower regions only (dev, sit, uat): the script-built set.** Take a fresh
   `INFORMATION_SCHEMA` snapshot and render it into the stage folder:
   ```bash
   cd sdlc/framework/tools/kbgen
   python3 extract_db_snapshot.py --env <env>          # prints the read-only SELECTs; run each one, save the JSON it names
   python3 extract_db_snapshot.py --check <snapshot>   # stop if a file is missing
   python3 gen_db_kb.py           --env <env> --snapshot <snapshot> --out-root ../../../../<stage>
   python3 gen_semantic_assets.py --env <env> --snapshot <snapshot> --out-root ../../../../<stage>
   python3 gen_ui_field_map.py    --env <env> --snapshot <snapshot> --out-root ../../../../<stage>
   ```
   Don't pass `--register` in a rebuild; that writes to the live question register.
2. **The prompt-built set:** `/db-run-pipeline --env <env> --stage <stage> --rebuild --skip-cross-module`.

Every query is read-only: SELECT, SHOW and DESCRIBE only.

## context — the domain context

`/kb-context-build --stage <stage> --rebuild`. Only when asked (`all --with-context`): our
context is hand-maintained and on the keep list, so a rebuild is for comparison only.

## all

1. `context`, if `--with-context` was given.
2. `app`, then `etl`, then `db` for each environment asked for (`--env` can be given more than once).
3. `/db-cross-module --env <env> --stage <stage> --rebuild` for each of those environments. It goes
   last because it reads the app, ETL and DB documents.
4. `/app-cross-pipeline <stage>`: the cross-checks between the three sets.

Every stage skill and script in this run is listed in `.devin/rules/kb-prompt-wiring.yaml`.

## When done

Report the stage folder, what was built, what was skipped and why, the gates deferred, and the
self-check items still open. Next step: `/kb-compare <stage>`.
