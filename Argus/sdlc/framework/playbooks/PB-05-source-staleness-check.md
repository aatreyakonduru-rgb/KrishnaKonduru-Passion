# Playbook: Source Staleness Check

**Playbook ID:** PB-05  
**Paste into:** Devin Cloud → Settings → Playbooks → New Playbook  
**CLI equivalent:** `/source-staleness-check` skill (auto-triggers before any gap analysis)  
**When to use:** Any time you want to know if the AI-generated KB documentation is still accurate. Also runs automatically at the start of every bottom-up research phase — never skip it.

---

## Title

```
Acme Claims: Source Staleness Check — Verify KB Docs vs Source Code
```

## Description

```
Compares AI-generated KB documentation (YAML registries and MD summaries)
against actual source code to detect drift. Produces a staleness table:
CURRENT / STALE / UNKNOWN per artifact with specific drift details. Where
STALE, source code becomes the ground truth for all downstream analysis.
Run this before any gap analysis or code inspection task.
```

## Playbook Body

---

You are performing a **source staleness check** for the Acme Claims system. Your job is to compare AI-generated knowledge base documentation against actual source code and produce a definitive staleness report.

**Golden rule:** The source code is always ground truth. KB docs are an index that may be out of date.

---

## STEP 1 — Identify Layers to Check

Ask the user (or infer from context):
- Which layers are relevant to the current task? (DB / API / UI / ETL)
- Or: check all layers (takes longer but ensures nothing is missed)

---

## STEP 2 — Run the Staleness Check Per Layer

### DB Layer

**KB artifact:** `docs/knowledge-base/DB-DOCS/DB_TABLE_REGISTRY.yaml`

**Source code ground truth:**
```
claims-etl/scripts/sql/
```

**What to compare:**
- Every table listed in `DB_TABLE_REGISTRY.yaml` — does it still exist in SQL?
- Every column listed — does it exist with the same name, type, nullability?
- Are there tables or columns in the SQL migration files NOT in the registry?
- Check `models.py` files in `api/` for any ORM model additions/changes

**Mark as STALE if:** any discrepancy exists. Note the specific columns/tables that differ.

---

### API Layer

**KB artifact:** `docs/knowledge-base/MODULES/claims-web/api/10_ENDPOINT_REGISTRY.yaml`

**Source code ground truth:**
```
api/
```

**What to compare:**
- Every endpoint in the registry — does it exist in `urls.py`?
- HTTP method (GET/POST/PUT/DELETE) — does it match `views.py`?
- Request parameters and response fields — do they match `serializers.py`?
- Are there endpoints in `urls.py` NOT in the registry?

**Mark as STALE if:** any discrepancy found.

---

### UI (Frontend) Layer

**KB artifact:** `docs/knowledge-base/MODULES/claims-web/web/12_COMPONENT_REGISTRY.yaml`

**Source code ground truth:**
```
web/src/
```

**What to compare:**
- Every component in the registry — does the `.tsx` file exist?
- Component props — do they match the actual TypeScript interface?
- API calls — does the component call the endpoints listed?
- Are there components in `src/` NOT in the registry?

**Mark as STALE if:** any discrepancy found.

---

### ETL Layer

**KB artifact:** `docs/knowledge-base/ETL/claims-etl/13_ETL_TABLE_IO_CONTRACT.yaml`

**Source code ground truth:**
```
claims-etl-glue/
claims-etl-lambda/
```

> **Note:** claims-etl-* repos are separate GitHub repositories and must be cloned independently.

**What to compare:**
- Every ETL job in the registry — does the script file exist?
- Input and output tables — do they match what the script actually reads/writes?
- Are there ETL scripts NOT in the registry?

**Mark as STALE if:** any discrepancy found.

---

## STEP 3 — Produce the Staleness Report

Write a staleness report table. Embed this as the first section of any `{REQ_ID}-GAP-ANALYSIS.md`, or output standalone if called directly.

```markdown
## KB Staleness Check
**Run date:** {ISO8601 today}
**Checked by:** Devin (source staleness check playbook)

| KB Artifact | Status | Drift Details | Ground Truth Used |
|---|---|---|---|
| DB_TABLE_REGISTRY.yaml | CURRENT | No drift detected | KB doc |
| DB_TABLE_REGISTRY.yaml | STALE | Missing: TIN_CTGRY_CD on CL_UI_BSNS_PG_PROV_HRCHY | Source: V002__add_tin_columns.sql |
| 10_ENDPOINT_REGISTRY.yaml | STALE | Endpoint /api/tin/classify not in registry | Source: api/apps/tin/urls.py |
| 12_COMPONENT_REGISTRY.yaml | CURRENT | No drift detected | KB doc |
| 13_ETL_TABLE_IO_CONTRACT.yaml | UNKNOWN | ETL source files not accessible | [source path] |

**Summary:**
- CURRENT: {n} artifacts
- STALE: {n} artifacts (list them)
- UNKNOWN: {n} artifacts (cannot verify)

**Action:** For STALE artifacts, use source code as ground truth for all downstream analysis.
Do NOT use stale KB doc values to generate gaps, stories, or insertion points.
```

---

## STEP 4 — Recommend Next Action

Based on the staleness results:

**If all CURRENT:**
> "KB docs are current. Safe to use for gap analysis. No KB refresh needed."

**If any STALE:**
> "⚠️ {n} KB artifact(s) are stale. I will use source code as ground truth for gap analysis.
> After deployment, run the KB Refresh playbook (PB-06) to bring docs back in sync."

**If any UNKNOWN (source file inaccessible):**
> "⚠️ Could not verify {artifact} — source path not accessible. I will treat this artifact as UNKNOWN and will not rely on it. Please verify the source path is correct."

---

---

## Advice & Pointers

- **CURRENT does not mean perfect.** A KB doc can be CURRENT (matches source) and still be incomplete if the source itself has dead code or orphaned references. Report what the source says — that is all you can confirm.
- **UNKNOWN is the honest answer when you cannot verify.** If the source path is inaccessible or the directory is empty, mark the artifact UNKNOWN and say why. Do not mark it CURRENT just because you could not find a discrepancy — absence of evidence is not evidence of absence.
- **Small drift is still drift.** A single missing column, a renamed endpoint parameter, one extra `.tsx` file not in the registry — all are STALE. Do not round up to CURRENT.
- **Run this per-layer, not per-artifact.** The cross-module matrix is the most complex artifact. Check it last, after individual layers are confirmed, so you can trace the correct dependency chains.
- **If you notice something wrong in a file you are reading** (a bug, dead code, unused function), note it in an `## Observations` section at the end of the staleness report. **Do not change it.** Example: "api/views.py line 203: `get_provider_list()` has a commented-out `filter(active=True)` that appears to be dead code. Recommend raising a cleanup story."

---

## Forbidden Actions

- **DO NOT mark any artifact CURRENT without reading both the KB artifact AND the source code.** Checking only one side is not a staleness check.
- **DO NOT modify any KB artifact or source file.** This playbook is read-only. Updating KB artifacts is done in PB-06 (KB Refresh), not here.
- **DO NOT skip layers.** If the user says "just check the DB", still complete the check for any layer that the current requirement touches.
- **DO NOT use a STALE artifact as ground truth for any downstream analysis.** Once marked STALE, that artifact is excluded — source code is used instead.
- **DO NOT mark a partially-checked artifact as CURRENT.** If you checked table names but not column types: mark as PARTIALLY_CHECKED, not CURRENT.
- **DO NOT fix staleness issues found during this check.** Flag them. The fix runs in PB-06 after PROD deployment.
