---
name: kb-refresh
description: >
  Updates the canonical knowledge base (YAML + MD) after a production deployment
  to reflect new code and schema. Run after PROD deployment to keep KB docs
  in sync with source code. Say "/kb-refresh" or "refresh the KB after deployment" to invoke.
visibility: internal
triggers:
  - user
  - model
allowed-tools:
  - read
  - write
  - edit
  - grep
  - glob
---

# Skill: Knowledge Base Refresh

Background reading: `sdlc/framework/workflows/kb-refresh.md` (the longer stage procedure; where it and this skill differ, this skill is the one to follow).

## Purpose
After a production deployment, the KB documentation (YAML registries and MD summaries)
must be updated to reflect what was actually deployed. This skill runs after PROD
deployment and updates all stale KB artifacts based on the deployment log and
merged source code.

## When to Invoke
- After PROD deployment is confirmed complete
- User says "/kb-refresh" or "update the KB" or "refresh docs after deployment"
- At the end of the release workflow (`workflows/release.md`)
- When `source-staleness-check` reports STALE artifacts after a deployment

---

## Pre-flight Check

**Trace lines (Argus):** print `[SDLC] kb <path> — loaded: <why>` / `skipped: <why>`, `[SDLC] rule <path> — loaded|deferred: <why>`, `[SDLC] chain DC-… — …` and `[SDLC] decision … — …` as each file is opened, skipped or each choice made, per `.devin/rules/workbench-trace.md` — here: a `kb` line for the deployment log and each routing map read; one `kb` line per KB artifact checked, `loaded` when its layer was deployed and `skipped` with the reason when it was not ("no ETL layer in this release"); a `chain` line for each `DC-` chain in `CROSS_LAYER_IMPACT_MATRIX.yaml` that the deployed change touches; and a `decision` line for each artifact's verdict, CURRENT or STALE with the drift in a few words, and each one updated or left for a person; and an `ontology check` line with its verdict (current or stale) and whether the ontology was rebuilt.

Before refreshing, verify:
1. The deployment log exists: `sdlc/framework/context/session/{OWNER}/{REQ_ID}/{REQ_ID}-STORY-{n}-DEPLOYMENT-LOG.md`
   - If missing, ask: "Which REQ-ID and which stories were deployed to PROD?"
2. Code changes are merged to main in the source repositories
3. The session directory exists at: `sdlc/framework/context/session/{OWNER}/{REQ_ID}/`
`{OWNER}` is resolved per `.devin/rules/session-isolation.md`.

---

## Source Code Paths (ground truth — always read these)

| Layer | Path |
|-------|------|
| API (Django) | `api/` |
| Frontend (Next.js) | `web/` |
| SQL/DB scripts | `../claims-etl/scripts/sql/` |
| ETL (Glue) | `../claims-etl-glue/` |
| ETL (Lambda) | `../claims-etl-lambda/` |

## KB Artifact Paths (these get updated)

| Artifact | Path |
|----------|------|
| DB Table Registry | `docs/knowledge-base/DB-DOCS/DB_TABLE_REGISTRY.yaml` |
| DB Schema Summary | `docs/knowledge-base/DB-DOCS/DB_SCHEMA_SUMMARY.md` |
| DB Cross-Module Matrix | `docs/knowledge-base/CROSS-LAYER/CROSS_LAYER_IMPACT_MATRIX.yaml` |
| DB AI Guardrails | `docs/knowledge-base/DB-DOCS/12_DB_AI_GUARDRAILS.yaml` |
| API Endpoint Registry | `docs/knowledge-base/MODULES/claims-web/api/10_ENDPOINT_REGISTRY.yaml` |
| API Data Contracts | `docs/knowledge-base/MODULES/claims-web/api/11_API_DATA_CONTRACTS.yaml` |
| FE Component Registry | `docs/knowledge-base/MODULES/claims-web/web/12_COMPONENT_REGISTRY.yaml` |
| ETL IO Contract | `docs/knowledge-base/ETL/claims-etl/13_ETL_TABLE_IO_CONTRACT.yaml` |

---

## Refresh Steps (run in order)

### Step 1 — Identify What Changed

Read the deployment log and the routing maps for all deployed stories:
- `{REQ_ID}-STORY-{n}-ROUTING.md` — lists every file that changed
- `{REQ_ID}-STORY-{n}-DEPLOYMENT-LOG.md` — confirms what was deployed

Build a list: for each story, which layer was affected (DB / API / UI / ETL)?

### Step 2 — Staleness Check (read-only)

For each affected layer, run the staleness check logic from `source-staleness-check` skill:
- Read the current KB artifact
- Read the deployed source files
- Identify what differs
- Mark each artifact as CURRENT or STALE with specific drift details

### Step 3 — Refresh DB Artifacts (if DB layer deployed)

For each new or modified table:
1. Read the actual SQL migration file from `scripts/sql/migrations/`
2. Read the Django `models.py` for the affected app
3. Update `DB_TABLE_REGISTRY.yaml`:
   - Add new columns with: `name`, `type`, `nullable`, `description`, `added_by: {REQ_ID}-{STORY_ID}`, `added_date: {date}`
   - Mark removed columns as `deprecated: true` (NEVER delete from registry)
4. Update `DB_SCHEMA_SUMMARY.md` — update the table's column list, mark new columns with `← NEW`
5. Update `CROSS_LAYER_IMPACT_MATRIX.yaml` — add new column-to-layer dependency chains

### Step 4 — Refresh API Artifacts (if API layer deployed)

Regenerate rather than hand-edit — the endpoint surface is extracted from source so that
handler names and line numbers stay exact:

```bash
cd sdlc/framework/tools/kbgen
python3 extract_api.py > api.json && python3 gen_api_kb.py api.json
```

This rewrites `10_ENDPOINT_REGISTRY.yaml` and `11_API_DATA_CONTRACTS.yaml` from
`api/apps/**/api.py` (Django Ninja routers — not `views.py`/`urls.py`) and
`api/apps/**/schema.py`. Review the diff; add business description text by hand
where the generated description is thin.

### Step 5 — Refresh FE Artifacts (if UI layer deployed)

```bash
cd sdlc/framework/tools/kbgen && python3 gen_ui_kb.py
```

Rewrites `12_COMPONENT_REGISTRY.yaml` from `web/src/`. Run it after Step 4 — it
resolves each frontend endpoint symbol against the endpoint registry and records misses
under `unmatched_against_api_registry`, which is where frontend/backend drift shows up.

### Step 6 — Refresh ETL Artifacts (if ETL layer deployed)

```bash
cd sdlc/framework/tools/kbgen && python3 gen_etl_kb.py
```

Rewrites `13_ETL_TABLE_IO_CONTRACT.yaml` from the sibling `claims-etl`
checkout (override with `SDLC_ETL_REPO`). Glue and Lambda pipelines are not covered by
the generator — for those, read the script and edit the contract by hand.

See `sdlc/framework/tools/kbgen/README.md` for what each generator reads.

### Step 6a — Rebuild the ontology (always, last of the generators)

```bash
python3 sdlc/framework/tools/kbgen/gen_ontology.py
python3 sdlc/framework/tools/ontology_lookup.py check
python3 sdlc/framework/tools/kb_sync.py --check
```

`kb_sync.py` (without `--check`) rebuilds the matrix, the ontology, the link graph
(`CROSS-LAYER/ACME_LINK_GRAPH.yaml`) and the KB manifest in one go; with `--check` it changes
nothing and exits 1 when any of them is behind. Print the `[SDLC] sync` lines it prints.

It reads the registries, matrix and ETL contract the steps above rewrote, so it runs after them.
Commit `CROSS-LAYER/ACME_ONTOLOGY.yaml` and `.html` with the rest of the refresh, and note in the
provenance log which objects, tables or lineage rows changed.

### Step 6b — Reference pages and onboarding guides

Argus's Help, Catalogue and Onboarding pages are built from Markdown, not written per click.
- If any KB document an `ONBOARDING-<role>-<date>.md` guide cites changed in this refresh, list the
  guide as stale in the provenance log and ask the user whether to rewrite it with
  `/onboarding-guide <role>`.
- Run `python3 sdlc/framework/tools/gen_reference_pages.py` and commit anything it rewrites
  under `sdlc/framework/reference/`.

### Step 7 — Write Provenance Log

Write `{REQ_ID}-KB-REFRESH-PROVENANCE.md` to the session directory:

```markdown
# KB Refresh Provenance: {REQ_ID}

## Refresh Date
{ISO8601 timestamp}

## Artifacts Updated
{list of KB files updated}

## Source Files Consulted
{list of source files read}

## Staleness Summary
| Artifact | Was | Now |
|----------|-----|-----|
| DB_TABLE_REGISTRY.yaml | STALE | CURRENT |
...

## Requirement
{REQ_ID}: {title}

## Stories Deployed
{story list}

## Approval Required
Tech Lead must review and approve this KB refresh (gate: SDLC_08_KB_REFRESH_VALIDATION).
```

### Step 8 — Gate: SDLC_08

Present the provenance log to the Tech Lead and ask:
> "KB refresh complete. The SDLC_08 gate is ready for review."

Use `.devin/rules/gate-presentation.md` to show the provenance log and
decision-relevant KB summaries with the canonical SDLC_08 checklist. Record the
real signer and approval record; rejection or needs-revision leaves the phase
unapproved and must not archive the session.

### Step 9 — Archive Session (only after gate SDLC_08 is approved)

Instructions for archiving (do NOT execute automatically — print the commands for the user to run):
```bash
cd "sdlc/framework/context/session/{OWNER}/{REQ_ID}"
# Move session to archive after 90 days
# mkdir archive (if not exists)
# Move {REQ_ID}/ to archive/{REQ_ID}/
```

Note: Session is retained in the active directory for 90 days, then moved to archive.

---

## Rules
- NEVER delete rows from KB YAML files — mark as `deprecated: true` instead
- NEVER assume CURRENT — read both the KB artifact AND the source before marking
- NEVER modify source code during this skill — KB refresh is documentation-only
- ALWAYS cite the source file for every change made to a KB artifact
- If a source file cannot be found, mark the KB artifact as UNKNOWN and log the missing file
