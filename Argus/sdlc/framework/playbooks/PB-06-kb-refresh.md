# Playbook: KB Refresh — Update Docs After Deployment

`{OWNER}` is resolved per `.devin/rules/session-isolation.md`.

**Playbook ID:** PB-06  
**Paste into:** Devin Cloud → Settings → Playbooks → New Playbook  
**CLI equivalent:** `/kb-refresh` skill  
**When to use:** After PROD deployment is confirmed complete. Keeps KB documentation in sync with what was actually built and deployed.

---

## Title

```
Acme Claims: KB Refresh — Update Knowledge Base After Deployment
```

## Description

```
Updates all AI-generated KB artifacts (YAML registries and MD summaries) after
a PROD deployment. Reads deployed source code to detect what changed, updates
each affected registry, writes a provenance log, and enforces gate SDLC_08
(Tech Lead approval). Never deletes KB rows — marks deprecated items instead.
```

## Playbook Body

---

You are performing a **KB Refresh** after a PROD deployment for Acme Claims.

**Ask the user:**
1. "Which REQ-ID and which stories were deployed to PROD?"
2. "Is the deployment log available at `framework/context/session/{OWNER}/{REQ_ID}/{REQ_ID}-STORY-{n}-DEPLOYMENT-LOG.md`?"

---

## STEP 1 — Confirm Deployment Is Complete

Read the deployment log: `framework/context/session/{OWNER}/{REQ_ID}/{REQ_ID}-STORY-{n}-DEPLOYMENT-LOG.md`

Confirm:
- PROD deployment status = complete
- Code changes are merged to `main`
- The merged PR number is recorded

If the deployment log does not exist, ask the user: "Which files were changed in this deployment, and to which layers (DB/API/UI/ETL)?"

---

## STEP 2 — Identify What Changed

Read the routing map: `framework/context/session/{OWNER}/{REQ_ID}/{REQ_ID}-STORY-{n}-ROUTING.md`

Build a list of affected layers and the specific files that were changed.

---

## STEP 3 — Run Staleness Check

Before updating anything, confirm what is actually stale. Follow the same process as **PB-05** for each affected layer — compare KB artifact vs. actual merged source code.

---

## STEP 4 — Refresh KB Artifacts By Layer

### If DB Layer Changed

Read:
- Deployed SQL migration file(s) from `scripts/sql/migrations/`
- `models.py` from affected Django apps

Update **`docs/knowledge-base/DB-DOCS/DB_TABLE_REGISTRY.yaml`**:
- For each new column: add entry with `name`, `type`, `nullable`, `description`, `added_by: {REQ_ID}-STORY-{n}`, `added_date: {date}`
- For each removed column: add `deprecated: true`, `deprecated_by: {REQ_ID}-STORY-{n}`, `deprecated_date: {date}` — **NEVER delete rows**
- For each modified column: update `type`, `nullable`, `description` as appropriate

Update **`docs/knowledge-base/DB-DOCS/DB_SCHEMA_SUMMARY.md`**:
- Update the table's column list
- Mark new columns with `← NEW (added by {REQ_ID}-STORY-{n})`
- Mark deprecated columns with `← DEPRECATED`

Update **`docs/knowledge-base/CROSS-LAYER/CROSS_LAYER_IMPACT_MATRIX.yaml`**:
- Add new column-to-layer dependency chains for each new column
- Trace: DB column → API endpoint → UI component (if applicable)
- Remove chains for deprecated columns (mark as `deprecated: true` in matrix)

### If API Layer Changed

Read:
- `views.py`, `serializers.py`, `urls.py` from affected Django app

Update **`docs/knowledge-base/MODULES/claims-web/api/10_ENDPOINT_REGISTRY.yaml`**:
- Add new endpoints with: method, path, description, parameters, response fields
- Update changed endpoints (modify existing entry)
- Mark removed endpoints as `deprecated: true`

Update **`docs/knowledge-base/MODULES/claims-web/api/11_API_DATA_CONTRACTS.yaml`** (if it exists):
- Update request/response field lists for modified endpoints

### If UI Layer Changed

Read:
- Modified `.tsx` file(s) from `web/src/`

Update **`docs/knowledge-base/MODULES/claims-web/web/12_COMPONENT_REGISTRY.yaml`**:
- Add new components with: file path, props, API calls, description
- Update changed components (update props, API calls)
- Mark removed components as `deprecated: true`

### If ETL Layer Changed

Read:
- Modified Glue or Lambda script(s)

Update **`docs/knowledge-base/ETL/claims-etl/13_ETL_TABLE_IO_CONTRACT.yaml`**:
- Update input/output table lists for modified jobs
- Add new jobs if added
- Mark removed jobs as `deprecated: true`

---

## STEP 5 — Write Provenance Log

Write `{REQ_ID}-KB-REFRESH-PROVENANCE.md` to `framework/context/session/{OWNER}/{REQ_ID}/`:

```markdown
# KB Refresh Provenance: {REQ_ID}

## Refresh Date
{ISO8601 timestamp}

## Requirement
{REQ_ID}: {title from SPEC}

## Stories Deployed
{story list with PROD deployment date}

## Artifacts Updated
| KB Artifact | Change Made |
|---|---|
| DB_TABLE_REGISTRY.yaml | Added column {col} to {table} |
| DB_SCHEMA_SUMMARY.md | Updated column list for {table} |
| CROSS_LAYER_IMPACT_MATRIX.yaml | Added {col} → API → UI chain |
| 10_ENDPOINT_REGISTRY.yaml | Added endpoint {path} |
| 12_COMPONENT_REGISTRY.yaml | Updated {Component} props |

## Source Files Consulted
{list of every source file read to produce this update, with verified paths}

## Staleness Summary Before Refresh
| Artifact | Was | Now |
|---|---|---|
| DB_TABLE_REGISTRY.yaml | STALE | CURRENT |
| 10_ENDPOINT_REGISTRY.yaml | STALE | CURRENT |

## PR Reference
PR #{number} merged to main on {date}

## Verification
- [ ] No stale references remain
- [ ] Provenance chain intact
- [ ] Cross-module matrix refreshed
- [ ] No rows deleted (deprecated only)
```

---

## STEP 6 — Gate: SDLC_08 — Tech Lead KB Refresh Validation

Present the provenance log and ask:
> "KB refresh complete. Please review `{REQ_ID}-KB-REFRESH-PROVENANCE.md`.
> Confirm the updated KB accurately reflects what was deployed.
> Tech Lead: type **APPROVED** to archive the session, or give me feedback."

When APPROVED: update `approvals.yaml` (add `kb_refresh.status: approved`).

---

## STEP 7 — Session Archive (instructions only — do not auto-execute)

After SDLC_08 is approved, tell the user:
> "Session is ready for archiving after 90 days. To archive manually:
> Move `framework/context/session/{OWNER}/{REQ_ID}/` to `framework/context/session/archive/{REQ_ID}/`"

---

## OUTPUT FILES

```
docs/knowledge-base/DB-DOCS/DB_TABLE_REGISTRY.yaml          ← updated
docs/knowledge-base/DB-DOCS/DB_SCHEMA_SUMMARY.md            ← updated
docs/knowledge-base/CROSS-LAYER/CROSS_LAYER_IMPACT_MATRIX.yaml  ← updated (if cross-layer changes)
docs/knowledge-base/MODULES/claims-web/api/10_ENDPOINT_REGISTRY.yaml       ← updated (if API changed)
docs/knowledge-base/MODULES/claims-web/web/12_COMPONENT_REGISTRY.yaml       ← updated (if UI changed)
docs/knowledge-base/ETL/claims-etl/13_ETL_TABLE_IO_CONTRACT.yaml ← updated (if ETL changed)
framework/context/session/{OWNER}/{REQ_ID}/{REQ_ID}-KB-REFRESH-PROVENANCE.md
```

---

## Advice & Pointers

- **The cross-module matrix is the hardest artifact to keep current — and the most important.** A new column in `DB_TABLE_REGISTRY.yaml` is straightforward. But did that column flow through to the API response? Did the UI component start rendering it? Did an ETL job start writing it? Trace the full chain before closing the refresh.
- **`deprecated: true` is a fact, not a judgment.** When a column or endpoint is removed in deployment, mark it deprecated with the requirement ID and date. This preserves audit trail and prevents future code-inspection confusion.
- **Always re-run the staleness check (PB-05) at the start of KB Refresh** even if you believe you know what changed. The deployment may have touched adjacent files not in the routing map.
- **Cite the source file for every change.** The provenance log is not useful if it says "updated column list" — it must say "read V004__add_tin_category.sql line 3, added TIN_CTGRY_CD column to CL_UI_BSNS_PG_PROV_HRCHY entry in DB_TABLE_REGISTRY.yaml."
- **SDLC_08 is not a formality.** The Tech Lead review of the KB refresh is the final quality gate. If the refresh is wrong, the next requirement built on this KB will produce incorrect gap analysis and routing maps.

---

## Forbidden Actions

- **DO NOT modify source code.** This playbook updates KB documentation only — zero changes to `api/`, `web/`, `scripts/sql/`, or any Glue/Lambda file.
- **DO NOT delete rows from any KB YAML file.** Removed columns, endpoints, components, and ETL jobs must be marked `deprecated: true` with the date and REQ-ID. Deletion destroys the audit trail.
- **DO NOT run KB Refresh before PROD deployment is confirmed.** Refreshing against code that is not yet deployed produces a KB that does not reflect reality.
- **DO NOT skip the Tech Lead approval (SDLC_08).** The refresh is not complete until the gate is signed.
- **DO NOT update a KB artifact based on what you think the source file says.** Read the actual file. Every update must be grounded in something you read in Step 4.
- **DO NOT archive the session directory yourself.** Step 7 provides instructions for the user to archive manually — Devin does not move or delete session directories.
- **DO NOT fix bugs or implement performance improvements noticed while reading source files.** Note them in `## Observations` in the provenance log. A separate requirement handles them.
