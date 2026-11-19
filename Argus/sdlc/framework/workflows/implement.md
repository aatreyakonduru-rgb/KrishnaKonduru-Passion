# Workflow: Implement — Code Generation, Dev Environment Testing

## Goal
Generate code, execute in dev environment, create PR, and obtain code review approval.

## Agent
**Implement Agent** (role: Developer)

## Prerequisites
- `REQ-{id}-STORY-{n}-ROUTING.md` approved by Tech Lead
- `insertion-points.yaml` created
- Coding patterns selected

## Steps

### 1. Create Feature Branch
**Action**: Create feature branch from main
```bash
git checkout -b feature/REQ-{id}-STORY-{n}-{description}
```

### 2. Generate Code
**Skill**: `code-gen-dev`
- Input: Routing map, insertion points, coding patterns
- Output: Code files (SQL, Python, TypeScript, etc.)
- Action:
  - For each insertion point:
    - If new file: Create file from template
    - If existing file: Insert code at specified line number
  - Follow secure coding standards (`rules/secure-coding.md`)
  - Follow PII handling rules (`rules/pii-handling.md`)
  - Use coding patterns from KB

### 3. Run in Dev Environment
**Skill**: `dev-env-test`
- Input: Generated code
- Output: Dev test results
- Action:
  - Deploy code to DEV environment
  - Run smoke tests
  - Verify functionality
  - Fix any issues

### 4. Update KB Artifacts (if schema/API changes)
**Action**: Update KB artifacts to reflect changes
- Files to update:
  - `DB_TABLE_REGISTRY.yaml` (if DB changes)
  - `API_ENDPOINT_REGISTRY.yaml` (if API changes)
  - `FE_COMPONENT_REGISTRY.yaml` (if UI changes)

### 5. Create Pull Request
**Skill**: `pr-creator`
- Input: Code changes, routing map
- Output: Pull Request
- Action:
  - Commit code changes
  - Push feature branch
  - Create PR with template (`templates/pr-template.md`)
  - Link to requirement and story
  - Add reviewers (Tech Lead, Developer)

### 6. Run AI Verification
**Skill**: `ai-verification`
- Input: Code changes, secure coding rules
- Output: `REQ-{id}-STORY-{n}-AI-VERIFICATION.md`
- Action:
  - Check for hardcoded secrets
  - Check for PII in logs
  - Check for SQL injection vulnerabilities
  - Check for secure coding violations
  - Generate verification report

### 7. Submit for Approval
**Human Gate**: `SDLC_05_CODE_REVIEW`
- Required Role: Developer
- Artifacts to Review: PR, AI verification report, code diff
- Approval Criteria:
  - Code follows secure coding standards
  - No hardcoded secrets or PII exposure
  - Tests included
  - Documentation updated
  - AI verification passed
- Timeout: 48 hours

## Outputs
- Feature branch with code changes
- Pull Request
- `REQ-{id}-STORY-{n}-AI-VERIFICATION.md`
- Updated KB artifacts (if schema/API changes)
- Provenance log entry

## Next Workflow
**Eval** (`workflows/eval.md`)

## Example
**Input**: `REQ-001-STORY-001-ROUTING.md` (Add LOCATION_CD column)

**Step 1: Create Feature Branch**
```bash
git checkout -b feature/REQ-001-STORY-001-add-location-cd
```

**Step 2: Generate Code**
File: `claims-etl/scripts/sql/migrations/V001__add_location_cd.sql`
```sql
-- Migration: Add LOCATION_CD column to VBC_UI_PRVDR_GRP
-- Author: [Developer Name]
-- Date: 2026-09-03
-- Requirement: REQ-001
-- Story: STORY-001

ALTER TABLE VBC_UI_PRVDR_GRP 
ADD COLUMN LOCATION_CD VARCHAR(10);

-- Verify column added
SELECT COUNT(*) 
FROM INFORMATION_SCHEMA.COLUMNS 
WHERE TABLE_NAME = 'VBC_UI_PRVDR_GRP' 
  AND COLUMN_NAME = 'LOCATION_CD';
```

**Step 3: Run in DEV**
```bash
snowsql -c acme-edaprod -f V001__add_location_cd.sql
# Output: Column added successfully
```

**Step 4: Update KB Artifacts**
File: `docs/knowledge-base/DB-DOCS/DB_TABLE_REGISTRY.yaml`
```yaml
tables:
  - name: VBC_UI_PRVDR_GRP
    columns:
      - name: LOCATION_CD
        type: VARCHAR(10)
        nullable: true
        description: Provider location code (city, state, or ZIP)
```

**Step 5: Create PR**
```bash
git add .
git commit -m "REQ-001-STORY-001: Add LOCATION_CD column to VBC_UI_PRVDR_GRP"
git push origin feature/REQ-001-STORY-001-add-location-cd
# Create PR on GitHub/GitLab
```

**Step 6: AI Verification Report**
File: `REQ-001-STORY-001-AI-VERIFICATION.md`
```markdown
# AI Verification Report: STORY-001

## Secure Coding Checks
✅ No hardcoded secrets
✅ No PII in logs
✅ SQL parameterized (N/A for DDL)
✅ No security violations

## Code Quality
✅ Follows SQL DDL best practices
✅ Includes verification query
✅ Documented with comments

## Recommendation
✅ Code is safe to merge. Proceed to code review.
```

**Step 7: Approval**
- Reviewer: Tech Lead (Resource 4)
- Decision: Approved ✅
- Timestamp: 2026-09-03T12:00:00Z

## Hooks
- **Pre-check**: Verify routing map is approved
- **Provenance log**: Record implementation session (files changed, tests run, approval)
- **Approval gate**: Enforce Developer approval before proceeding to Eval
