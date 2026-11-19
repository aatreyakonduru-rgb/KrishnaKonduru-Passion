# Workflow: KB Refresh — Knowledge Base Update Post-Deployment

`{OWNER}` is resolved per `.devin/rules/session-isolation.md`.

## Goal
Update canonical knowledge base (YAML + MD) after production deployment to reflect new code/schema.

## Agent
**KB Refresh Agent** (role: Tech Lead)

## Prerequisites
- PROD deployment complete
- Deployment log available
- Code changes merged to main

## Steps

### 1. Run Staleness Checker
**Skill**: `staleness-checker`
- Input: Deployment log, KB artifacts
- Output: List of stale artifacts
- Action:
  - Compare deployment timestamp vs. KB artifact timestamps
  - Identify stale artifacts (not updated since deployment)
  - Flag artifacts for refresh

### 2. Refresh KB Artifacts
**Skill**: `kb-refresh`
- Input: Deployment log, code changes, routing map
- Output: Updated KB artifacts
- Action:
  - For each affected layer:
    - Update YAML registry (DB_TABLE_REGISTRY.yaml, API_ENDPOINT_REGISTRY.yaml, etc.)
    - Update Markdown docs (DB_SCHEMA_SUMMARY.md, etc.)
  - Maintain provenance (source files, timestamp, approver)

### 3. Update Cross-Module Matrix (if cross-layer changes)
**Skill**: `cross-module-matrix-updater`
- Input: Updated KB artifacts, code changes
- Output: Updated `CROSS_LAYER_IMPACT_MATRIX.yaml`
- Action:
  - Trace new dependencies (DB → API → UI)
  - Update matrix with new column-to-layer chains
  - Verify no broken references

### 4. Log Provenance
**Skill**: `provenance-logger`
- Input: Updated KB artifacts
- Output: `REQ-{id}-KB-REFRESH-PROVENANCE.md`
- Action:
  - Document artifacts updated
  - Document source files
  - Record refresh timestamp
  - Record approver

### 5. Submit for Approval
**Human Gate**: `SDLC_08_KB_REFRESH_VALIDATION`
- Required Role: Tech Lead
- Artifacts to Review: Updated YAML/MD, provenance log
- Approval Criteria:
  - KB artifacts updated with new code/schema
  - Provenance chain intact
  - No stale references
  - Cross-module matrix refreshed
- Timeout: 48 hours

### 6. Archive Session
**Action**: Archive session directory
- Move the owner-scoped session `context/session/{OWNER}/REQ-{id}/` to the root-level `context/session/archive/` only when explicitly archiving.
- Compress to `REQ-{id}.tar.gz`
- Retain for 90 days

## Outputs
- Updated KB artifacts (YAML + MD)
- `REQ-{id}-KB-REFRESH-PROVENANCE.md` (approved by Tech Lead)
- Archived session directory
- Provenance log entry

## Next Workflow
None (end of SDLC cycle)

## Example
**Input**: `REQ-001-STORY-001-DEPLOYMENT-LOG.md` (PROD deployed)

**Step 1: Staleness Checker**
Stale artifacts identified:
- `DB_TABLE_REGISTRY.yaml` (last updated: 2026-09-03T12:00:00Z, deployment: 2026-09-04T02:00:00Z)
- `DB_SCHEMA_SUMMARY.md` (last updated: 2026-09-01T10:00:00Z, deployment: 2026-09-04T02:00:00Z)

**Step 2: Refresh KB Artifacts**

File: `docs/knowledge-base/DB-DOCS/DB_TABLE_REGISTRY.yaml` (updated)
```yaml
tables:
  - name: VBC_UI_PRVDR_GRP
    layer: ui
    module: provider_grouping
    primary_keys:
      - PG_ID
    columns:
      - name: PG_ID
        type: NUMBER(38,0)
        nullable: false
        description: Provider Group ID
      - name: TIN
        type: VARCHAR(20)
        nullable: false
        description: Tax Identification Number
      - name: LOCATION_CD
        type: VARCHAR(10)
        nullable: true
        description: Provider location code (city, state, or ZIP)
        added_by: REQ-001-STORY-001
        added_date: 2026-09-04
```

File: `docs/knowledge-base/DB-DOCS/DB_SCHEMA_SUMMARY.md` (updated)
```markdown
### VBC_UI_PRVDR_GRP (Provider Group UI Table)

**Columns**:
- PG_ID (NUMBER(38,0), NOT NULL): Provider Group ID
- TIN (VARCHAR(20), NOT NULL): Tax Identification Number
- **LOCATION_CD (VARCHAR(10), NULL): Provider location code (city, state, or ZIP)** ← NEW

**Primary Key**: PG_ID

**Row-Level Security**: RP_TNNT_ACCESS (RAW_TNNT_ID, RAW_OFSHR_ACSBL_IND)
```

**Step 3: Update Cross-Module Matrix**
File: `docs/knowledge-base/CROSS-LAYER/CROSS_LAYER_IMPACT_MATRIX.yaml` (updated)
```yaml
columns:
  - column_name: LOCATION_CD
    source_table: VBC_UI_PRVDR_GRP
    dependencies:
      - layer: api
        endpoint: /api/contracts/search
        parameter: location
      - layer: ui
        component: ContractSearch.tsx
        prop: locationFilter
```

**Step 4: Provenance Log**
File: `REQ-001-KB-REFRESH-PROVENANCE.md`
```markdown
# KB Refresh Provenance: REQ-001-STORY-001

## Artifacts Updated
- `docs/knowledge-base/DB-DOCS/DB_TABLE_REGISTRY.yaml`
- `docs/knowledge-base/DB-DOCS/DB_SCHEMA_SUMMARY.md`
- `docs/knowledge-base/CROSS-LAYER/CROSS_LAYER_IMPACT_MATRIX.yaml`

## Source Files
- `claims-etl/scripts/sql/migrations/V001__add_location_cd.sql`
- PR #123 (merged)

## Refresh Timestamp
2026-09-04T03:00:00Z

## Approver
Tech Lead: Resource 4

## Requirement
REQ-001: Add provider location filter to Contract UI search

## Story
STORY-001: Add LOCATION_CD column to VBC_UI_PRVDR_GRP

## Staleness Check
- DB_TABLE_REGISTRY.yaml: Stale (updated)
- DB_SCHEMA_SUMMARY.md: Stale (updated)
- CROSS_LAYER_IMPACT_MATRIX.yaml: Stale (updated)

## Verification
✅ No stale references
✅ Provenance chain intact
✅ Cross-module matrix refreshed
```

**Step 5: Approval**
- Approver: Tech Lead (Resource 4)
- Decision: Approved ✅
- Timestamp: 2026-09-04T04:00:00Z

**Step 6: Archive Session**
```bash
cd sdlc/framework/context/session/{OWNER}/REQ-{id}
tar -czf archive/REQ-001.tar.gz REQ-001/
mv REQ-001/ archive/
```

## Final Status
✅ KB refreshed successfully. SDLC cycle complete.

## Hooks
- **Pre-check**: Verify PROD deployment is complete
- **Provenance log**: Record KB refresh session (artifacts updated, source files, timestamp, approver)
- **Approval gate**: Enforce Tech Lead approval before archiving session
- **Post-action**: Archive session directory for 90-day retention
