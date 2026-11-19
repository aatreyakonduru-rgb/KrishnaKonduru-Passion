# Workflow: Eval — Test Generation, Execution, Coverage Analysis

## Goal
Generate tests, execute in test environment, verify coverage, and obtain QA sign-off.

## Agent
**Eval Agent** (role: QA Engineer)

## Prerequisites
- Code review approved by Developer
- PR merged to main
- Test environment available (DEV, SIT, UAT)

## Steps

### 1. Load Acceptance Criteria
**Action**: Load acceptance criteria from requirement spec and story
- Files:
  - `REQ-{id}-SPEC.md` (overall acceptance criteria)
  - `REQ-{id}-BACKLOG.md` (story-specific acceptance criteria)

### 2. Generate Tests
**Skill**: `test-gen`
- Input: Acceptance criteria, code changes
- Output: Test files (test_*.py, *.test.tsx)
- Action:
  - For each acceptance criterion: Generate acceptance test
  - For each new function: Generate unit test
  - For cross-layer changes: Generate integration test

### 3. Execute Tests
**Skill**: `test-exec`
- Input: Test files, test environment
- Output: Test results JSON, coverage report HTML
- Action:
  - Set up test environment (DEV, SIT, UAT)
  - Execute all tests (pytest, jest)
  - Collect test results (passed, failed, skipped)
  - Generate coverage report (pytest-cov, jest --coverage)

### 4. Analyze Coverage
**Skill**: `coverage-analyzer`
- Input: Coverage report
- Output: Coverage analysis section in test report
- Action:
  - Verify coverage >= 80%
  - Identify uncovered lines
  - Recommend additional tests (if coverage < 80%)

### 5. Track Defects (if any)
**Skill**: `defect-tracker`
- Input: Test results
- Output: Defect list in test report
- Action:
  - For each failed test: Document defect
  - Assign severity (critical, high, medium, low)
  - Link to requirement and story

### 6. Submit for Approval
**Human Gate**: `SDLC_06_QA_SIGNOFF`
- Required Role: QA Engineer
- Artifacts to Review: Test report, coverage report, test execution logs
- Approval Criteria:
  - Test coverage >= 80%
  - All acceptance criteria validated
  - No critical defects
  - Regression tests passed
- Timeout: 24 hours

## Outputs
- Test files (test_*.py, *.test.tsx)
- `REQ-{id}-STORY-{n}-TEST-REPORT.md` (approved by QA)
- `REQ-{id}-STORY-{n}-TEST-RESULTS.json`
- `REQ-{id}-STORY-{n}-COVERAGE-REPORT.html`
- Provenance log entry

## Next Workflow
**Release** (`workflows/release.md`)

## Example
**Input**: STORY-001 (Add LOCATION_CD column), PR #123 (merged)

**Step 1: Load Acceptance Criteria**
From `REQ-001-BACKLOG.md`:
- Column added with VARCHAR(10) type
- Default value: NULL
- Migration script created and tested in DEV

**Step 2: Generate Tests**
File: `test_location_cd_migration.py`
```python
import pytest
from snowflake_connector import execute_query

def test_location_cd_column_exists():
    """Verify LOCATION_CD column exists in VBC_UI_PRVDR_GRP"""
    result = execute_query("DESCRIBE TABLE VBC_UI_PRVDR_GRP")
    columns = [col['name'] for col in result]
    assert "LOCATION_CD" in columns, "LOCATION_CD column not found"

def test_location_cd_column_type():
    """Verify LOCATION_CD is VARCHAR(10)"""
    result = execute_query("DESCRIBE TABLE VBC_UI_PRVDR_GRP")
    location_col = [col for col in result if col['name'] == 'LOCATION_CD'][0]
    assert location_col['type'] == 'VARCHAR(10)', f"Expected VARCHAR(10), got {location_col['type']}"

def test_location_cd_nullable():
    """Verify LOCATION_CD is nullable"""
    result = execute_query("DESCRIBE TABLE VBC_UI_PRVDR_GRP")
    location_col = [col for col in result if col['name'] == 'LOCATION_CD'][0]
    assert location_col['null?'] == 'Y', "LOCATION_CD should be nullable"

def test_location_cd_default_null():
    """Verify LOCATION_CD default is NULL"""
    result = execute_query("SELECT LOCATION_CD FROM VBC_UI_PRVDR_GRP LIMIT 1")
    assert result[0]['LOCATION_CD'] is None, "Default value should be NULL"
```

**Step 3: Execute Tests**
```bash
pytest test_location_cd_migration.py --cov --cov-report=html
```

Output:
```json
{
  "total_tests": 4,
  "passed": 4,
  "failed": 0,
  "skipped": 0,
  "duration": 2.45,
  "failures": []
}
```

Coverage: 85%

**Step 4: Analyze Coverage**
- Coverage: 85% ✅ (>= 80%)
- Uncovered lines: None
- Recommendation: Coverage meets threshold

**Step 5: Track Defects**
No defects found ✅

**Step 6: Test Report**
File: `REQ-001-STORY-001-TEST-REPORT.md`
```markdown
# Test Report: STORY-001 (Add LOCATION_CD column)

## Summary
- **Total tests**: 4
- **Passed**: 4 ✅
- **Failed**: 0
- **Skipped**: 0
- **Coverage**: 85% ✅
- **Duration**: 2.45 seconds

## Test Results
✅ test_location_cd_column_exists - PASSED (0.5s)
✅ test_location_cd_column_type - PASSED (0.5s)
✅ test_location_cd_nullable - PASSED (0.5s)
✅ test_location_cd_default_null - PASSED (0.95s)

## Coverage Analysis
- **Overall**: 85%
- **V001__add_location_cd.sql**: 100%
- **DB_TABLE_REGISTRY.yaml**: N/A (config file)

## Acceptance Criteria Validation
✅ Column added with VARCHAR(10) type
✅ Default value: NULL
✅ Migration script created and tested in DEV

## Defects
None

## Regression Tests
✅ All existing provider group tests passed

## Recommendation
✅ All tests passed. Coverage meets threshold. Ready for environment promotion.

## Approver
QA Engineer: Resource 24

## Approval Timestamp
2026-09-03T13:00:00Z
```

## Hooks
- **Pre-check**: Verify code review is approved
- **Provenance log**: Record eval session (tests generated, results, coverage, approval)
- **Approval gate**: Enforce QA approval before proceeding to Release
