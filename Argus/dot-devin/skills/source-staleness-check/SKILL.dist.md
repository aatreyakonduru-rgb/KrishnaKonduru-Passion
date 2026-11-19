---
name: source-staleness-check
description: >
  Compares AI-generated KB documentation against actual source code to detect
  drift. Auto-triggered before any gap analysis and whenever the research phase
  starts. Run manually with "/source-staleness-check". Results are written into
  the gap analysis as a Staleness Check section.
visibility: internal
triggers:
  - user
  - model
allowed-tools:
  - read
  - grep
  - glob
---

# Skill: Source Staleness Check

## Purpose
Compare AI-generated KB documentation (`docs/knowledge-base/**/*.yaml` and `*.md`) against actual source code to detect drift. Run this BEFORE any gap analysis so that stale docs are not used as ground truth.

## When to run
- **Automatically** at the start of every Research phase — before gap analysis begins
- When a KB Refresh has not been done recently
- When you suspect the source code has changed since the last KB generation
- When the user says "/source-staleness-check", "/app-staleness-check" (the older name) or "check if docs are stale"

## Source Code Paths (ground truth)

| Layer | Path |
|---|---|
| API (Django) | `api/` |
| Frontend (Next.js) | `web/` |
| SQL/DB scripts | `../claims-etl/scripts/sql/` |
| ETL (Glue) | `../claims-etl-glue/` |
| ETL (Lambda) | `../claims-etl-lambda/` |

## KB Doc Paths (may be stale)

| Artifact | Path |
|---|---|
| DB Table Registry | `docs/knowledge-base/DB-DOCS/DB_TABLE_REGISTRY.yaml` |
| DB Schema Summary | `docs/knowledge-base/DB-DOCS/DB_SCHEMA_SUMMARY.md` |
| DB Cross-Module Matrix | `docs/knowledge-base/CROSS-LAYER/CROSS_LAYER_IMPACT_MATRIX.yaml` |
| API Endpoint Registry | `docs/knowledge-base/MODULES/claims-web/api/10_ENDPOINT_REGISTRY.yaml` |
| API Data Contracts | `docs/knowledge-base/MODULES/claims-web/api/11_API_DATA_CONTRACTS.yaml` |
| FE Component Registry | `docs/knowledge-base/MODULES/claims-web/web/12_COMPONENT_REGISTRY.yaml` |
| ETL IO Contract | `docs/knowledge-base/ETL/claims-etl/13_ETL_TABLE_IO_CONTRACT.yaml` |
| Module Discovery | `docs/knowledge-base/MODULES/claims-web/{MODULE}/00_DISCOVERY_REPORT.md` |
| Module FRD | `docs/knowledge-base/MODULES/claims-web/{MODULE}/02_FUNCTIONAL_REQUIREMENTS.md` |
| Module TRD | `docs/knowledge-base/MODULES/claims-web/{MODULE}/03_TECHNICAL_REQUIREMENTS.md` |
| DB Schema Catalog | `docs/knowledge-base/DB-DOCS/07_DB_SCHEMA_CATALOG.md` |
| DB Change Impact | `docs/knowledge-base/DB-DOCS/04_DB_CHANGE_IMPACT_MATRIX.md` |

`{MODULE}` is `api` or `web`. The registries are rebuilt from source by `/kb-refresh`; the module documents come from the shared prompts through `/kb-build`.

---

## Staleness Check Instructions

### DB Layer Check
1. Read `DB_TABLE_REGISTRY.yaml` — get the list of tables and their columns
2. For each table mentioned in the requirement:
   - Search `scripts/sql/` for SQL files defining or altering that table
   - Extract column list from source SQL (CREATE TABLE or ALTER TABLE statements)
   - Compare to `DB_TABLE_REGISTRY.yaml`
   - Flag STALE if: columns differ, types differ, or columns exist in source but not in docs (or vice versa)
3. Check `api/apps/*/models.py` for the Django model definition of the table
   - Compare model fields to `DB_TABLE_REGISTRY.yaml`
   - Flag STALE if model fields differ from doc

### API Layer Check
1. Read `10_ENDPOINT_REGISTRY.yaml` — get the list of endpoints
2. For each endpoint relevant to the requirement:
   - Find the Django app: `api/apps/{app_name}/urls.py`
   - Read `views.py` for the view class/function
   - Read `serializers.py` for request/response fields
   - Compare to `10_ENDPOINT_REGISTRY.yaml` and `11_API_DATA_CONTRACTS.yaml`
   - Flag STALE if: endpoints missing, parameters differ, response fields differ

### Frontend Layer Check
1. Read `12_COMPONENT_REGISTRY.yaml` — get the list of components
2. For each component relevant to the requirement:
   - Search `web/src/` for the `.tsx` file
   - Read the component to see actual props and API calls
   - Compare to `12_COMPONENT_REGISTRY.yaml`
   - Flag STALE if: props differ, component doesn't exist, or undocumented components found

### ETL Layer Check
1. Read `13_ETL_TABLE_IO_CONTRACT.yaml` — get input/output table contracts
2. For each ETL process relevant to the requirement:
   - Search `scripts/sql/` for the stored procedure or script
   - Check which tables it reads from and writes to
   - Compare to `13_ETL_TABLE_IO_CONTRACT.yaml`
   - Flag STALE if: IO tables differ, logic has changed

---

## Output Format

Write the staleness check result as a section in the gap analysis:

```markdown
## KB Staleness Check

**Run date**: {today}
**Checked by**: Source code scan

| KB Artifact | Status | Drift Details |
|---|---|---|
| DB_TABLE_REGISTRY.yaml | CURRENT | Matches source SQL and Django models |
| 10_ENDPOINT_REGISTRY.yaml | STALE | Source has `/api/contracts/bulk-search` not in registry |
| 12_COMPONENT_REGISTRY.yaml | STALE | `ProviderGroupTable.tsx` props changed — registry shows old `pgId` prop, source uses `providerGroupId` |
| 13_ETL_TABLE_IO_CONTRACT.yaml | CURRENT | Matches source SQL |

**Action taken**: Where STALE, source code used as ground truth for gap analysis below.
**Recommendation**: Run KB Refresh (workflows/kb-refresh.md) after this change is deployed.
```

---

## Staleness status

| Status | Meaning |
|---|---|
| **CURRENT** | Read both the KB doc and the source; no discrepancies found |
| **STALE** | A discrepancy between the KB doc and the source is confirmed |
| **UNKNOWN** | The source file is not accessible or not found, so it cannot be verified |
| **PARTIALLY_CHECKED** | Some aspects checked (e.g. table names) but not others (e.g. column types). Not CURRENT |
| **AGED** | The KB file was last changed more than 30 days ago; the content looks right but freshness is not guaranteed |

Small drift is still drift: one missing column, one renamed prop or one extra endpoint is STALE.
Always name the specific drift (which column, prop or endpoint), not just "STALE".

---

## Rules
- Mark CURRENT only after actually reading both the doc AND the source — never assume CURRENT without checking
- If source file cannot be found (file doesn't exist), mark as UNKNOWN and note the missing file
- Do not modify KB docs during this check — staleness check is read-only
- After the check, always state which source was used as ground truth for each layer
