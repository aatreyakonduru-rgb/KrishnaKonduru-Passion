---
name: kb-build
description: Build the whole Mētis knowledge base from the team's repos, databases, Confluence and Jira into a staging folder, check every line against its source, collect the open questions in VALIDATE_KB, build the ontology and link graph, and put it all in one pull request. The build never stops for approval; after the first KB is locked, the result is proposed to a named lead, who certifies it before anything enters the KB.
argument-hint: "[all|app|etl|db|context] [--module <name>] [--env <env>]"
allowed-tools:
  - read
  - write
  - edit
  - grep
  - glob
  - exec
triggers:
  - model
---

# Build the knowledge base

`$METIS` is the Mētis plugin folder: the folder two levels above this SKILL.md. `<KB>` is the KB folder in
the team repo, found as the folder holding `.metis/kb-profile.yaml`. If there is no settings file,
run `metis-setup` first. Follow `$METIS/rules/metis-evidence.md`, `$METIS/rules/metis-approvals.md` and
`$METIS/rules/metis-writes.md` throughout.

## 1. Start

1. Read `<KB>/.metis/kb-profile.yaml`. `<run>` is today's date (`YYYY-MM-DD`); `<stage>` is `<KB>/_REGEN/<run>`.
2. Clone or pull every repo under `sources.repos` (read only) into `sources.workspace_root` and record
   each repo's commit in `<stage>/BUILD.md`, with the scope, environment and date.
3. Run `python3 $METIS/tools/prompts.py lint`. If it reports an error, fix the settings file, not the prompt.
4. `python3 $METIS/tools/detect_stack.py detect <KB> --all`, then `show`. If anything is new or no longer found
   since the approval, list it in BUILD.md and in the PR description; the build carries on with the approved
   stack (`<KB>/.metis/stack.yaml`). With no approval yet, run the show-and-approve step of `metis-setup` first.
5. Check each source once and write the result in BUILD.md: each database in `<KB>/.metis/db-environments.yaml`
   (the read-only identity check for its engine),
   Confluence and Jira (one read with the service-account secret named in `sources.confluence.secret` /
   `sources.jira.secret`). A source that fails is skipped and its documents are listed as not built.
   Never print a secret.

## 2. Build, straight through

Pass `--stage <stage> --rebuild` to every stage skill. No step waits for approval (see `$METIS/rules/metis-approvals.md`).

Rebuilds are incremental. `python3 $METIS/tools/build_plan.py stale <KB>` lists the pages whose source commits changed
since the last build (`<KB>/.metis/built-from.yaml`); rebuild those and leave the rest. `build_plan.py run <KB> <name>`
makes a unique run folder (a second run on the same day does not overwrite the first), and `build_plan.py done <run> <stage>`
records a finished stage so a long build can resume where it stopped. A first build has nothing to compare and builds everything.

- context: `kb-context-build --stage <stage> --rebuild` (from Confluence pages under `sources.confluence`
  and the files in `<KB>/_EVIDENCE/files/`).
- app: for each entry in `app.modules` (name and source folder), `app-run-pipeline <module> <source folder>
  --stage <stage> --rebuild`. Back-end and service modules before the front ends that call them, as the approved
  stack shows them. The endpoint registry, API data contracts and component registry are built by their prompts
  (APP-10, APP-11, APP-12) inside that pipeline.
- etl: for each entry in `etl.modules`, `etl-run-pipeline <module> --stage <stage> --rebuild`. The table
  input/output contract is built by its prompt (ETL-13). AWS batch code and any scheduling files in the repos
  are read like any other source; live AWS state is not read.
- db: every database and schema in every environment of `<KB>/.metis/db-environments.yaml`.
  1. `python3 $METIS/tools/db_catalog.py plan <KB>` writes the catalogue queries for each database (from the
     pack for its engine in `$METIS/templates/db-packs/`) to `<KB>/_EVIDENCE/queries/CATALOG-*-<ENV>-<LABEL>.sql`.
     Run each one read only on the connection named in its first line and save the rows as `<id>.json`.
     A database that can't be reached is listed in BUILD.md and its queries stay unrun.
  2. For each database in the reference environment, `db-run-pipeline --env <reference env> --db <label>
     --stage <stage> --rebuild`. Other environments get only the catalogue snapshot and the drift report.
  Table and column names come only from catalogue queries (SELECT, SHOW, DESCRIBE) or schema files. Cite each
  saved query as `[E: query:<id>]`.
- cross-layer: `db-cross-module --env <reference env> --stage <stage> --rebuild`, then `app-cross-pipeline <stage>`.

While writing documents, also write the links you can source to `<stage>/<area>/<module>.links.yaml`
(format at the top of `$METIS/tools/gen_graph.py`): endpoint to handler, handler to table, screen to endpoint,
job to table, column to column. Only links a source shows; never from similar names.

## 3. Questions

Every statement no source supports goes to a question file `<stage>/_new_questions.yaml` (fields in
`$METIS/tools/questions.py`), and its place in the document gets `[?: Q-xxxx]` once the id is known:

```bash
python3 $METIS/tools/questions.py add  <KB> <stage>/_new_questions.yaml --build <run>
python3 $METIS/tools/questions.py html <KB>
```

## 4. Check

```bash
python3 $METIS/tools/verify_kb.py <stage> --settings <KB>/.metis/kb-profile.yaml --report <stage>/VERIFY.json
```

The stage folder uses the KB's `_EVIDENCE` and `_QUESTIONS`; if they are not found from `<stage>`, copy the new
evidence files into `<KB>/_EVIDENCE/` first. Fix every problem: add the missing source, correct the line,
or turn it into a question. Repeat until it reports 0 problems.

## 5. Graph and PR

1. Get the staged files into `<KB>/`:
   - KB not locked yet (first build): move them in. Files on `<KB>/.metis/kb-keep.yaml` are never replaced; put the new
     version beside them as `<name>.NEW.md`.
   - KB locked (every later build): do not write into the KB. Run
     `python3 $METIS/tools/kb_gate.py propose <KB> --batch build-<run> --from <stage>`, then
     `python3 $METIS/tools/kb_gate.py digest <KB> build-<run>`, and tell the lead in chat what is waiting. When the lead
     says approve, ask who is approving and run `kb_gate.py certify <KB> build-<run> --by "<name>"`. Old copies go to
     `<KB>/Archive/build-<run>/`. Go on to the next step only after certification.
2. `python3 $METIS/tools/verify_kb.py <KB>` must report 0 problems.
3. `python3 $METIS/tools/build_outputs.py <KB>` builds every generated output from the sourced files, then
   checks sources again (it must report 0 problems):
   - `<db_docs>/DB_TABLE_REGISTRY.yaml` and `catalog.links.yaml`, from the saved queries `CATALOG-TABLES`,
     `CATALOG-COLUMNS` and `CATALOG-FKEYS` (run the SQL in `$METIS/templates/catalog-queries.sql` read only during
     the db stage and save each as `_EVIDENCE/queries/<ID>.sql` and `.json`)
   - `CROSS-LAYER/ONTOLOGY.yaml` and `LINK_GRAPH.yaml` (only links whose source checks out)
   - `CROSS-LAYER/IMPACT_MATRIX.yaml` (what moves when a table, column, endpoint, screen or job changes, each step
     with its source; hand-written chains in `IMPACT_MATRIX.CURATED.yaml` are kept only if every step checks out)
     and `QA_COVERAGE.yaml` (only `tests` links from the test repo, when one is a source)
   - `<db_docs>/ERD.md` and `CORTEX_SEMANTIC_MODEL.yaml` (relationships only from declared keys and sourced joins)
   - `VISUALIZATION/`: `index.html`, `ONTOLOGY.html` (animated graph, main flows, jobs and lineage, impact paths,
     QA coverage, open questions), `ERD.html`, `KB_HEALTH.html`, `KB_MANIFEST.html`
   - `KNOWLEDGE-MANIFEST.yaml` (every KB file with its hash and source-tag count)
   - `python3 $METIS/tools/graph_store.py build <KB>` (a SQLite copy of the link graph, so impact questions are answered
     on demand and deep walks do not run out of memory), then `python3 $METIS/tools/golden.py static <KB>` (the golden
     questions must still resolve) and `python3 $METIS/tools/build_plan.py record <KB>` (remember the commits this build read)
   Write `tests` links (test → screen, endpoint or job, with file and line) only from a configured test repo.
4. First build only: after the lead accepts the KB, lock it with `python3 $METIS/tools/kb_gate.py lock <KB> --by "<lead>"`
   (ask the lead for their name in chat). From then on nothing enters the KB without a named lead.
5. On branch `metis/<run>-kb`, commit only `<KB>/` and open one pull request to `repo.base_branch`. The PR
   description lists: sources and commits read, documents built, documents not built and why, verify result,
   open questions by priority and by role, and a pointer to `_QUESTIONS/VALIDATE_KB.html`. Request review from
   `owners.kb_owner`. Never merge.

## When done

Report the PR, the counts (documents, sourced lines, links, open questions P1/P2/P3) and the sources that were
skipped.

## 1.1.0 additions (lessons from PCMS-MAGNOLIA-KB)
- Scope: read every repo connected to the Devin org (FE, BE/API, ETL, AEDL, Glue, Lambda, Terraform, orchestration), not one Bitbucket project. List them first and clone all.
- Staging always lives outside the KB folder; run `verify_kb.py` on the staged copy, then on the live KB after promotion.
- `KB_TEAM_ROOT` may be the KB root or its `.metis` folder (both work since 1.1.0).
- Cross-layer: run gen_graph, gen_matrix and gen_visuals as separate steps. Impact depth is `METIS_IMPACT_DEPTH` (default 3; 6 ran out of memory at ~15 GB on a 121k-node graph). Keep `VISUALIZATION/ONTOLOGY.html` out of git when > 100 MB; the gallery replaces it.
- ETL lineage by layer: `python3 $METIS/tools/etl_layer_lineage.py` resolves `${var}` schemas from the ETL param files and draws upstream → staging → target layers, leaving out log/backup/temp tables (LOAD_LOG, *_BKP, TEMP_/TMP_).
- Query index: `python3 $METIS/tools/index/kb_index_build.py` builds a SQLite FTS5 index of every KB file, every repo text file (secrets redacted), the link graph, the catalogue and the ETL loads; `tools/index/kbq.py` answers search/table/flow/columns/node/schemas/sql. Large (~1 GB for a 40-repo org): commit the script, not the database, unless Git LFS is set up.
- Paths for these tools: env `METIS_KB` (required: the KB folder), `METIS_REPOS`, `METIS_WORK`, `METIS_LOGO` (each overrides the profile). Everything else that was once fixed in these scripts (organisation name, dashboard title, logo, colours, source-link pattern, areas, databases, module and story-key patterns, lineage zones and parameter files) is read from the `viz:` section of `<KB>/.metis/kb-profile.yaml` through `tools/site_paths.py`. Every value is optional; an empty one switches that part off. Never put a product or team name in these scripts: `tools/tests/test_site_paths.py` fails if one appears.
