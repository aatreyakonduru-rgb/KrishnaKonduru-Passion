# Workflow: Plan — Routing, Change Drafter, Insertion Locator

## Goal
Create detailed implementation plan with routing map, change ownership, and insertion points.

## Agent
**Plan Agent** (role: Technical Architect)

## Prerequisites
- `REQ-{id}-BACKLOG.md` approved by Product Owner
- KB context loaded (cross-module matrix, registries, coding patterns)
- Story selected from backlog

## Steps

### 1. Select Story
**Action**: Choose story from approved backlog
- Input: `REQ-{id}-BACKLOG.md`
- Output: Selected story (e.g., STORY-001)

### 2. Load KB Context
**Action**: Load canonical knowledge base artifacts
- Files:
  - `CROSS_LAYER_IMPACT_MATRIX.yaml`
  - `API_ENDPOINT_REGISTRY.yaml`
  - `FE_COMPONENT_REGISTRY.yaml`
  - `CODING_PATTERNS.yaml`

### 3. Generate Routing Map
**Skill**: `routing-map-generator`
- Input: Story, KB context
- Output: `REQ-{id}-STORY-{n}-ROUTING.md`
- Action:
  - Identify affected layers (DB, API, UI, ETL, etc.)
  - List affected files/functions
  - Define dependency order (DB → API → UI)
  - Choose branch strategy (single vs. multi-branch)
  - Document rollback plan
  - Determine if feature flag needed

### 4. Draft Change Plan
**Skill**: `change-drafter`
- Input: Routing map
- Output: Change plan section in `REQ-{id}-STORY-{n}-ROUTING.md`
- Action:
  - Assign change owner (developer)
  - Draft implementation steps
  - Estimate duration
  - Identify risks

### 5. Identify Insertion Points
**Skill**: `insertion-locator`
- Input: Routing map, codebase
- Output: `insertion-points.yaml`
- Action:
  - For each affected file:
    - If new file: Document file path and template
    - If existing file: Find exact line number, extract code snippet
  - Identify dependencies (imports, callers, etc.)

### 6. Select Coding Patterns
**Skill**: `coding-patterns-selector`
- Input: Routing map, coding patterns KB
- Output: Coding patterns section in `REQ-{id}-STORY-{n}-ROUTING.md`
- Action:
  - Select reusable patterns (SQL parameterization, API error handling, etc.)
  - Reference pattern examples from KB

### 7. Submit for Approval
**Human Gate**: `SDLC_04_ROUTING_APPROVAL`
- Required Role: Tech Lead
- Artifacts to Review: `REQ-{id}-STORY-{n}-ROUTING.md`, `insertion-points.yaml`
- Approval Criteria:
  - All touched files exist and are linkable
  - No prod mutations without feature flag
  - Branch strategy documented
  - Dependency order clear
  - Rollback plan included
- Timeout: 24 hours

## Outputs
- `REQ-{id}-STORY-{n}-ROUTING.md` (approved by Tech Lead)
- `insertion-points.yaml`
- Provenance log entry

## Next Workflow
**Implement** (`workflows/implement.md`)

## Example
**Input**: STORY-001 (Add LOCATION_CD column to VBC_UI_PRVDR_GRP)

**Output 1**: `REQ-001-STORY-001-ROUTING.md`
```markdown
# Routing Map: STORY-001 (Add LOCATION_CD column)

## Affected Layers
- Database Layer

## Affected Files
- `claims-etl/scripts/sql/migrations/V001__add_location_cd.sql` (new)
- `docs/knowledge-base/DB-DOCS/DB_TABLE_REGISTRY.yaml` (existing)

## Dependency Order
1. Create migration script
2. Run migration in DEV
3. Update DB_TABLE_REGISTRY.yaml
4. Promote to SIT/UAT/PROD

## Branch Strategy
Single branch: `feature/REQ-001-STORY-001-add-location-cd`

## Rollback Plan
- Revert migration: `ALTER TABLE VBC_UI_PRVDR_GRP DROP COLUMN LOCATION_CD;`
- Restore previous DB_TABLE_REGISTRY.yaml

## Feature Flag
Not needed (additive schema change, no prod mutation)

## Change Owner
Database Administrator: [Name]

## Coding Patterns
- SQL DDL: Use ALTER TABLE for schema changes
- Versioning: Use Flyway naming convention (V001__description.sql)
```

**Output 2**: `insertion-points.yaml`
```yaml
insertion_points:
  - file_path: claims-etl/scripts/sql/migrations/V001__add_location_cd.sql
    file_type: new
    change_type: add
    code_snippet: |
      -- Migration: Add LOCATION_CD column to VBC_UI_PRVDR_GRP
      ALTER TABLE VBC_UI_PRVDR_GRP ADD COLUMN LOCATION_CD VARCHAR(10);
    dependencies: []
  
  - file_path: docs/knowledge-base/DB-DOCS/DB_TABLE_REGISTRY.yaml
    file_type: existing
    function_name: VBC_UI_PRVDR_GRP.columns
    line_number: 245
    change_type: modify
    code_snippet: |
      # Line 240-250
      columns:
        - name: PG_ID
          type: NUMBER(38,0)
        - name: TIN
          type: VARCHAR(20)
        # INSERT HERE: LOCATION_CD column
    dependencies:
      - DB_SCHEMA_SUMMARY.md
      - CROSS_LAYER_IMPACT_MATRIX.yaml
```

## Hooks
- **Pre-check**: Verify `REQ-{id}-BACKLOG.md` is approved
- **Provenance log**: Record planning session (KB artifacts consulted, routing decisions, approval)
- **Approval gate**: Enforce Tech Lead approval before proceeding to Implement
