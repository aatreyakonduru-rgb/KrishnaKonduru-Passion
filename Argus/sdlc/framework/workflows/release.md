# Workflow: Release — Environment Promotion, Deployment, Rollback Planning

## Goal
Promote code through environments (DEV → SIT → UAT → PROD) with deployment and rollback plans.
The environments, their order, branches and gates are `workflow.environments` in
`.devin/rules/sdlc-profile.json` (`tools/promote_check.py --list` prints them).

## Agent
**Release Agent** (role: Ops / Release Manager)

## Prerequisites
- QA sign-off complete
- Test report approved
- All tests passed with coverage >= 80%

## Steps

### 1. Create Deployment Plan
**Skill**: `deployment-planner`
- Input: Test report, routing map
- Output: `REQ-{id}-STORY-{n}-DEPLOYMENT-PLAN.md`
- Action:
  - Define deployment steps
  - Identify environments (from `workflow.environments`; ours DEV → SIT → UAT → PROD)
  - Schedule change window (for PROD)
  - List dependencies
  - Define smoke tests

### 2. Create Rollback Plan
**Skill**: `rollback-planner`
- Input: Routing map, deployment plan
- Output: `REQ-{id}-STORY-{n}-ROLLBACK-PLAN.md`
- Action:
  - Define rollback steps
  - Test rollback in lower environment (DEV)
  - Estimate rollback time
  - Document rollback triggers

### 3. Configure Monitoring
**Skill**: `monitoring-configurator`
- Input: Deployment plan
- Output: Monitoring configuration
- Action:
  - Configure alerts (errors, performance)
  - Set up dashboards (Splunk, CloudWatch)
  - Define SLAs

### 4. Submit for Approval
**Human Gate**: `SDLC_07_ENV_PROMOTION_APPROVAL`
- Required Role: Ops / Release Manager
- Artifacts to Review: Deployment plan, rollback plan, monitoring config
- Approval Criteria:
  - Deployment plan reviewed
  - Rollback tested
  - Monitoring/alerting configured
  - Change window scheduled
- Timeout: 24 hours

### 5. Promote to SIT
**Skill**: `promote-env`
- Input: Deployment plan, source_env=DEV, target_env=SIT
- Output: Deployment log (SIT)
- Action:
  - Execute deployment steps
  - Run smoke tests
  - Verify deployment successful

### 6. Promote to UAT
**Skill**: `promote-env`
- Input: Deployment plan, source_env=SIT, target_env=UAT
- Output: Deployment log (UAT)
- Action:
  - Execute deployment steps
  - Run smoke tests
  - Verify deployment successful

### 7. Promote to PROD
**Skill**: `promote-env`
- Input: Deployment plan, source_env=UAT, target_env=PROD
- Output: Deployment log (PROD)
- Action:
  - Execute deployment steps during change window
  - Run smoke tests
  - Verify deployment successful
  - Monitor for issues

## Outputs
- `REQ-{id}-STORY-{n}-DEPLOYMENT-PLAN.md`
- `REQ-{id}-STORY-{n}-ROLLBACK-PLAN.md`
- `REQ-{id}-STORY-{n}-DEPLOYMENT-LOG.md` (approved by Ops)
- Monitoring configuration
- Provenance log entry

## Next Workflow
**KB Refresh** (`workflows/kb-refresh.md`)

## Example
**Input**: `REQ-001-STORY-001-TEST-REPORT.md` (approved)

**Step 1: Deployment Plan**
File: `REQ-001-STORY-001-DEPLOYMENT-PLAN.md`
```markdown
# Deployment Plan: STORY-001 (Add LOCATION_CD column)

## Environments
1. DEV (already deployed)
2. SIT
3. UAT
4. PROD

## Deployment Steps
1. Backup database
2. Run migration V001__add_location_cd.sql
3. Verify LOCATION_CD column exists
4. Update DB_TABLE_REGISTRY.yaml
5. Run smoke tests

## Change Window (PROD)
- Date: 2026-09-04
- Time: 02:00 AM - 04:00 AM UTC
- Duration: 2 hours

## Dependencies
- Snowflake database access
- Migration script V001__add_location_cd.sql

## Smoke Tests
- test_location_cd_column_exists
- test_location_cd_column_type
- test_location_cd_nullable
```

**Step 2: Rollback Plan**
File: `REQ-001-STORY-001-ROLLBACK-PLAN.md`
```markdown
# Rollback Plan: STORY-001

## Rollback Steps
1. Restore database backup
2. OR: Run rollback migration
   ```sql
   ALTER TABLE VBC_UI_PRVDR_GRP DROP COLUMN LOCATION_CD;
   ```
3. Restore previous DB_TABLE_REGISTRY.yaml

## Rollback Tested
✅ Tested in DEV on 2026-09-03
- Rollback time: 30 seconds
- No data loss

## Rollback Triggers
- Migration fails
- Smoke tests fail
- Critical errors in PROD

## Rollback Time Estimate
- SIT/UAT: 1 minute
- PROD: 2 minutes
```

**Step 3: Monitoring Configuration**
- Alert: "LOCATION_CD column missing" (critical)
- Dashboard: "Provider Group Schema Changes"
- SLA: 99.9% uptime

**Step 4: Approval**
- Approver: Ops / Release Manager
- Decision: Approved ✅
- Timestamp: 2026-09-03T14:00:00Z

**Step 5-7: Environment Promotions**
File: `REQ-001-STORY-001-DEPLOYMENT-LOG.md`
```markdown
# Deployment Log: STORY-001

## SIT Deployment
**Timestamp**: 2026-09-03T15:00:00Z

### Steps
1. ✅ Backup SIT database (30s)
2. ✅ Run migration V001__add_location_cd.sql (5s)
3. ✅ Verify LOCATION_CD column exists (2s)
4. ✅ Update DB_TABLE_REGISTRY.yaml (1s)

### Smoke Tests
✅ test_location_cd_column_exists - PASSED
✅ test_location_cd_column_type - PASSED
✅ test_location_cd_nullable - PASSED

### Status
✅ SIT deployment successful

---

## UAT Deployment
**Timestamp**: 2026-09-03T16:00:00Z

### Steps
1. ✅ Backup UAT database (30s)
2. ✅ Run migration V001__add_location_cd.sql (5s)
3. ✅ Verify LOCATION_CD column exists (2s)
4. ✅ Update DB_TABLE_REGISTRY.yaml (1s)

### Smoke Tests
✅ test_location_cd_column_exists - PASSED
✅ test_location_cd_column_type - PASSED
✅ test_location_cd_nullable - PASSED

### Status
✅ UAT deployment successful

---

## PROD Deployment
**Timestamp**: 2026-09-04T02:00:00Z (Change Window)

### Steps
1. ✅ Backup PROD database (60s)
2. ✅ Run migration V001__add_location_cd.sql (10s)
3. ✅ Verify LOCATION_CD column exists (5s)
4. ✅ Update DB_TABLE_REGISTRY.yaml (2s)

### Smoke Tests
✅ test_location_cd_column_exists - PASSED
✅ test_location_cd_column_type - PASSED
✅ test_location_cd_nullable - PASSED

### Monitoring
✅ No alerts triggered
✅ Dashboard shows healthy status

### Status
✅ PROD deployment successful

## Rollback Readiness
✅ Rollback tested in DEV
✅ Rollback plan documented
✅ Rollback time: 2 minutes

## Final Status
✅ All environments deployed successfully. Ready for KB refresh.
```

## Hooks
- **Pre-check**: Verify QA sign-off is complete
- **Provenance log**: Record release session (environments, deployments, smoke tests, approval)
- **Approval gate**: Enforce Ops approval before PROD deployment
