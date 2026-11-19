# Workflow: Research — Gap Analysis, Impact Analysis, Enriched Requirements

## Goal
Analyze requirement against existing system to identify gaps, impacts, and generate enriched user stories.

## Agent
**Research Agent** (role: Solution Architect)

## Prerequisites
- `REQ-{id}-SPEC.md` approved by BSA
- KB context loaded (DB, API, UI, ETL registries + cross-module matrix)

## Steps

### 1. Load KB Context
**Action**: Load canonical knowledge base artifacts
- Files:
  - `DB_TABLE_REGISTRY.yaml`
  - `CROSS_LAYER_IMPACT_MATRIX.yaml`
  - `API_ENDPOINT_REGISTRY.yaml`
  - `FE_COMPONENT_REGISTRY.yaml`
  - `ETL_MODULE_IO_SUMMARY.yaml`

### 2. Run Gap Analysis
**Skill**: `requirement-gap-analysis`
- Input: `REQ-{id}-SPEC.md`, KB context
- Output: `REQ-{id}-GAP-ANALYSIS.md`
- Action:
  - Compare current system state vs. target requirement
  - Identify gaps in each layer (DB, API, UI, ETL, etc.)
  - Assess impact (low/medium/high/critical)
  - Estimate effort (hours/days)

### 3. Run Impact Analysis
**Skill**: `impact-analysis`
- Input: `REQ-{id}-GAP-ANALYSIS.md`, KB context
- Output: Affected modules section in `REQ-{id}-GAP-ANALYSIS.md`
- Action:
  - Identify all affected modules and dependencies
  - Assess data migration needs
  - Assess breaking change risks
  - Document rollback considerations

### 4. Generate Enriched Requirements (Stories)
**Skill**: `enriched-requirements-generator`
- Input: `REQ-{id}-GAP-ANALYSIS.md`
- Output: `REQ-{id}-BACKLOG.md`
- Action:
  - Create epic from requirement
  - Break down into user stories (one per layer or logical unit)
  - Define acceptance criteria for each story
  - Estimate effort for each story
  - Prioritize and order stories

### 5. Submit for Approval (Gap Analysis)
**Human Gate**: `SDLC_02_GAP_ANALYSIS_REVIEW`
- Required Role: BSA
- Artifacts to Review: `REQ-{id}-GAP-ANALYSIS.md`
- Approval Criteria:
  - Gap analysis completeness verified
  - All affected modules identified
  - Data/interface impacts documented
  - Risk assessment included
- Timeout: 24 hours

### 6. Submit for Approval (Backlog)
**Human Gate**: `SDLC_03_BACKLOG_APPROVAL`
- Required Role: Product Owner
- Artifacts to Review: `REQ-{id}-BACKLOG.md`
- Approval Criteria:
  - Backlog prioritization agreed
  - Sprint ordering confirmed
  - Story acceptance criteria clear
  - Effort estimates reasonable
- Timeout: 48 hours

## Outputs
- `REQ-{id}-GAP-ANALYSIS.md` (approved by BSA)
- `REQ-{id}-BACKLOG.md` (approved by Product Owner)
- Provenance log entries

## Next Workflow
**Plan** (`workflows/plan.md`) — for each story in the backlog

## Example
**Input**: `REQ-001-SPEC.md` (Add provider location filter)

**Output 1**: `REQ-001-GAP-ANALYSIS.md`
```markdown
## Current State
- DB: VBC_UI_PRVDR_GRP table has TIN, NPI, but no LOCATION_CD column
- API: /api/contracts/search endpoint filters by TIN/NPI only
- UI: ContractSearch.tsx has no location filter dropdown

## Target State
- DB: Add LOCATION_CD column to VBC_UI_PRVDR_GRP
- API: Extend /api/contracts/search to accept location parameter
- UI: Add location dropdown to ContractSearch.tsx

## Gaps Identified
| Gap ID | Layer | Description | Impact | Effort |
|--------|-------|-------------|--------|--------|
| GAP-001 | DB | Missing LOCATION_CD column | Medium | 2 hours |
| GAP-002 | API | Missing location filter | Medium | 4 hours |
| GAP-003 | UI | Missing location dropdown | Low | 3 hours |

## Affected Modules
- VBC_UI_PRVDR_GRP (DB)
- /api/contracts/search (API)
- ContractSearch.tsx (UI)

## Risk Assessment
- Data migration: Need to backfill LOCATION_CD for existing provider groups
- Breaking change: API contract change requires version bump
```

**Output 2**: `REQ-001-BACKLOG.md`
```markdown
## Epic: Add Provider Location Filter to Contract UI Search

### Story 1: Add LOCATION_CD column to VBC_UI_PRVDR_GRP
**Acceptance Criteria**:
- Column added with VARCHAR(10) type
- Default value: NULL
- Migration script created and tested in DEV

**Effort**: 2 hours

### Story 2: Extend /api/contracts/search to accept location parameter
**Acceptance Criteria**:
- API accepts location parameter (city, state, ZIP)
- API filters results by location
- API returns results within 2 seconds for up to 10,000 providers

**Effort**: 4 hours

### Story 3: Add location dropdown to ContractSearch.tsx
**Acceptance Criteria**:
- Dropdown shows city, state, ZIP options
- Dropdown integrates with existing TIN/NPI filters
- Search updates dynamically when location filter is applied

**Effort**: 3 hours

## Sprint Ordering
1. Story 1 (DB schema change) — Sprint 1
2. Story 2 (API endpoint) — Sprint 1
3. Story 3 (UI component) — Sprint 2
```

## Hooks
- **Pre-check**: Verify `REQ-{id}-SPEC.md` is approved
- **Provenance log**: Record research session (KB artifacts consulted, gaps identified, approvals)
- **Approval gates**: Enforce BSA + PO approvals before proceeding to Plan
