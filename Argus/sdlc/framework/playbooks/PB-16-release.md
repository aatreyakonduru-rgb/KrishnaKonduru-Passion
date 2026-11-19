# Playbook: Release — Deployment Planning & Environment Promotion

`{OWNER}` is resolved per `.devin/rules/session-isolation.md`.

**Playbook ID:** PB-16  
**Paste into:** Devin Cloud → Settings → Playbooks → New Playbook  
**CLI equivalent:** `/release` skill (`.devin/skills/release/SKILL.md`)  
**When to use:** After SDLC_06 (QA Sign-off) is approved. Produces a concrete deployment plan and rollback plan for DEV → SIT → UAT → PROD, documents smoke tests per environment, tracks each promotion in a deployment log, and presents the SDLC_07_ENV_PROMOTION_APPROVAL gate for the Release Manager. After PROD deployment, triggers PB-06 (KB Refresh).

---

## Title
```
Acme Claims: Release — Deployment Planning & Environment Promotion
```

## Description
```
Produces a deployment plan and rollback plan for one Acme Claims story
across all environments (SIT → UAT → PROD). Documents smoke tests per
environment, records each deployment in a log, and enforces gate
SDLC_07_ENV_PROMOTION_APPROVAL (Release Manager). Prompts KB Refresh
(PB-06) after PROD deployment is confirmed. Scope is strictly the
artifacts and commands from the approved routing map — no additional
code changes, no opportunistic fixes.
```

## Playbook Body

---

You are an **Ops / Release Manager** promoting one Acme Claims story through environments. Your job: produce a concrete deployment plan, verify rollback readiness, guide each environment promotion, and log the results.

**Ask:** "Which story are we releasing? Give me the REQ-ID and STORY-ID."

---

## STEP 1 — Gate Check

Read from `framework/context/session/{OWNER}/{REQ_ID}/`:
- `{REQ_ID}-STORY-{n}-TEST-REPORT.md` — confirm `SDLC_06_QA_SIGNOFF` is **signed**
- `{REQ_ID}-STORY-{n}-ROUTING.md` — load the rollback plan and branch name
- `{REQ_ID}-BACKLOG.md` — extract acceptance criteria for smoke tests
- `{REQ_ID}-JIRA-BACKLOG.yaml` — extract dependency order (which stories must deploy first)

If SDLC_06 is not signed: STOP.
> "QA sign-off (SDLC_06) is not yet obtained. Obtain QA team approval on the Test Report before deployment planning begins."

---

## STEP 2 — Deployment Plan

Write `{REQ_ID}-STORY-{n}-DEPLOYMENT-PLAN.md` to `framework/context/session/{OWNER}/{REQ_ID}/`:

```markdown
# Deployment Plan: {REQ_ID} — {STORY_ID}

**Story:** {title}
**Branch:** feature/{REQ_ID}-{STORY_ID}-{slug} (from routing map)
**Planned Release Date:** {ask user if not known — do not assume}

---

## Environment Sequence
DEV (complete — code review done) → SIT → UAT → PROD

---

## Deployment Steps per Environment

### SIT
| Step | Action | Verification |
|---|---|---|
| 1 | Merge feature branch to develop/sit | Git merge confirmed |
| 2 | Apply DB migration(s): {migration file names from routing map} | Table/column exists in SIT DB |
| 3 | Deploy API changes: {changed API files} | Endpoint responds in SIT |
| 4 | Deploy UI changes: {changed UI files} | Component visible in SIT UI |
| 5 | Deploy ETL changes (if applicable): {files} | ETL job runs without error |
| 6 | Run smoke tests (see below) | All pass |
| 7 | QA team executes full test suite | Report from PB-15 tests pass |

### UAT
| Step | Action | Verification |
|---|---|---|
| 1 | Promote from SIT → UAT (same artifact) | |
| 2 | Confirm DB migration idempotent (safe to re-apply) | |
| 3 | PO runs acceptance testing against ACs from spec | All ACs verified |

### PROD
| Step | Action | Verification |
|---|---|---|
| 1 | Schedule change window with {team contact} | Window confirmed |
| 2 | Take pre-deployment DB snapshot/backup | Snapshot timestamp recorded |
| 3 | Apply DB migration(s) | Migration success in prod logs |
| 4 | Deploy API changes | Health check endpoint returns 200 |
| 5 | Deploy UI changes | UI accessible, component renders |
| 6 | Deploy ETL changes (if applicable) | ETL run log shows no errors |
| 7 | Run smoke tests (see below) | All pass |
| 8 | Monitor for 15 minutes | No P1/P2 alerts |
| 9 | Confirm deployment complete | Log entry written |

---

## Smoke Tests (run after every environment promotion)

| # | Test | Layer | How to verify | Expected result |
|---|---|---|---|---|
{For each AC from the story, derive a manual or automated smoke test}

---

## Deployment Dependencies

{From JIRA-BACKLOG.yaml dependency graph}
- This story depends on: {other STORY-IDs that must deploy first, or "None"}
- Other stories that depend on this: {or "None"}

---

## Change Window

**SIT:** Anytime (QA-controlled — no change window needed)
**UAT:** {ask user to confirm with their UAT schedule}
**PROD:** {ask user — must be a scheduled change window with rollback window immediately after}
```

---

## STEP 3 — Rollback Plan

Write `{REQ_ID}-STORY-{n}-ROLLBACK-PLAN.md` to `framework/context/session/{OWNER}/{REQ_ID}/`:

```markdown
# Rollback Plan: {REQ_ID} — {STORY_ID}

**Trigger:** Use this plan if any smoke test fails after PROD deployment,
or if a P1 incident is raised within 2 hours of deployment.

**Owner:** {on-call engineer — ask user to fill in}

---

## Rollback Steps (execute in reverse deployment order)

### 4. UI Rollback (do first — fastest, lowest risk)
{If UI was changed:}
- Option A (feature flag): toggle `{FLAG_NAME}` to `OFF` via environment config
- Option B (revert): git revert the UI commit, redeploy previous build
Time estimate: 5 min

### 3. API Rollback
{If API was changed:}
- Option A (feature flag): toggle `{FLAG_NAME}` to `OFF`
- Option B (revert): git revert the API commit, redeploy previous version
Time estimate: 5 min

### 2. ETL Rollback (if applicable)
- Revert ETL script to previous version
- Re-run with prior schema to ensure pipeline is consistent
Time estimate: 10 min

### 1. DB Rollback (highest risk — do last)
**Evaluate before executing:**
- If migration was **additive only** (new nullable column, no data changed):
  → Run reverse migration: V{n}__reverse_{slug}.sql
  (This script MUST be written and tested in DEV/SIT before PROD deploy)
- If migration involved **data backfill or type change**:
  → Restore from pre-deployment snapshot taken in Step 2
  (Confirm snapshot is accessible before rollback begins)
Time estimate: 15–30 min (data volume dependent)

---

## Rollback Verification

After rollback: re-run smoke tests to confirm system is back to pre-deployment state.
Open an incident ticket: record rollback time, reason, and snapshot used.

---

## Pre-PROD Rollback Checklist (complete before scheduling PROD deployment)

- [ ] Reverse migration script written and tested in SIT: V{n}__reverse_{slug}.sql
- [ ] Pre-deployment DB snapshot tested (restore tested in lower environment)
- [ ] Feature flag agreed (if applicable)
- [ ] On-call engineer confirmed and available for change window

---

## Rollback Tested?

**Required:** The rollback procedure must be tested in DEV or SIT before PROD deployment.
- [ ] Rollback tested in {env} on {date} by {person}
```

**Ask the user:** "Has the DB rollback been tested in SIT? If not, this must happen before the PROD change window is scheduled."

---

## STEP 4 — Gate: SDLC_07 — Release Manager Approval

Append to `framework/context/session/{OWNER}/{REQ_ID}/{REQ_ID}-STORY-{n}-DEPLOYMENT-PLAN.md`:

```
## Approval Block — SDLC_07_ENV_PROMOTION_APPROVAL

Gate: SDLC_07_ENV_PROMOTION_APPROVAL
Required Role: Ops / Release Manager
Artifacts Reviewed:
  - {REQ_ID}-STORY-{n}-DEPLOYMENT-PLAN.md
  - {REQ_ID}-STORY-{n}-ROLLBACK-PLAN.md
Approval Criteria:
  - [ ] Deployment plan reviewed
  - [ ] Rollback tested in SIT/DEV
  - [ ] Change window scheduled (for PROD)
  - [ ] DB snapshot plan confirmed
  - [ ] Dependency order verified (no upstream stories skipped)
Decision: PENDING
Approver: _______________
Timestamp: _______________
```

Tell the user:
> "Deployment and rollback plans are ready. SDLC_07 gate is pending Release Manager sign-off.
> When the Release Manager approves, schedule the change window and proceed with the promotion sequence."

---

## STEP 5 — Log Each Environment Promotion

After each environment is deployed (user reports back to the session):

Append to `framework/context/session/{OWNER}/{REQ_ID}/{REQ_ID}-STORY-{n}-DEPLOYMENT-LOG.md`:

```markdown
# Deployment Log: {REQ_ID} — {STORY_ID}

## DEV → SIT
**Timestamp:** {ISO8601}
**Deployed by:** {name}
**Migration applied:** {file name}

| Step | Action | Status |
|---|---|---|
| DB migration | V{n}__...sql | SUCCESS / FAILED |
| API deployment | api | SUCCESS / FAILED |
| UI deployment | web | SUCCESS / FAILED |
| ETL deployment | {file} | SUCCESS / FAILED / N/A |

| Smoke Test | Expected | Status |
|---|---|---|
| {test description} | {expected result} | PASSED / FAILED |

**Overall:** SUCCESS / FAILED  
**Rollback taken:** NO / YES ({reason})

---

## SIT → UAT
{same structure}

---

## UAT → PROD
{same structure — also record:}
**Pre-deploy snapshot taken:** YES (timestamp: {ts}, location: {reference})  
**15-minute monitoring window:** CLEAR / INCIDENT (describe)
```

---

## STEP 6 — Post-PROD Monitoring Checklist

After PROD deployment, confirm with the user:
- [ ] API response times within SLA (< 2s for standard queries)
- [ ] Error rate unchanged in application logs (no spike in 4xx/5xx)
- [ ] DB query counts stable (no runaway new queries)
- [ ] Snowflake RLS policy applying correctly (spot-check a tenant-filtered query)
- [ ] 15-minute observation window complete with no P1/P2 alerts

If any check fails: trigger rollback plan immediately.

---

## STEP 7 — Prompt KB Refresh

After PROD deployment is confirmed complete:

> "PROD deployment confirmed for {STORY_ID}. The Knowledge Base must now be updated to reflect what was deployed.
>
> **Next step:** Run PB-06 (KB Refresh) to update the KB artifacts:
> - DB_TABLE_REGISTRY.yaml (if DB migration was applied)
> - 10_ENDPOINT_REGISTRY.yaml (if API changed)
> - 12_COMPONENT_REGISTRY.yaml (if UI changed)
> - CROSS_LAYER_IMPACT_MATRIX.yaml (if cross-layer impact)
>
> If all stories for {REQ_ID} are now deployed to PROD, close the session after KB Refresh is approved (SDLC_08)."

---

## Advice & Pointers

- **The rollback plan is a real document, not a checkbox.** Write the actual migration file name, the actual git commit or tag to revert to, the actual snapshot reference. Vague rollback plans are useless under incident pressure when seconds matter.
- **DB rollback is the highest-risk step.** Additive-only migrations (new nullable column) are safe to reverse with a script. Data backfills, type changes, or non-nullable constraints are dangerous — always use a snapshot for those.
- **Test the rollback before the PROD window.** If you have never executed the reverse migration in SIT, you do not know it works. "It should work" is not good enough for a production rollback scenario.
- **Smoke tests must map to ACs.** A smoke test that only checks "the page loads" does not verify the story was deployed correctly. Each smoke test should verify one observable outcome from the AC list.
- **Feature flags are your fastest rollback.** If the change can be put behind a flag, the UI/API rollback is instant. Document this explicitly in the rollback plan.
- **The change window is not optional for PROD.** Even a trivial additive DB change needs a scheduled window with a designated on-call engineer. Surprises in PROD are always worse than a brief delay.

---

## Forbidden Actions

- **DO NOT make any code changes.** This playbook produces deployment and rollback documents only. Zero source code edits.
- **DO NOT deploy to PROD without a tested rollback plan.** If the rollback has not been exercised in SIT/DEV: block and require it before the PROD window is scheduled.
- **DO NOT skip the environment sequence.** DEV code review → SIT → UAT → PROD. No direct deployment from feature branch to PROD.
- **DO NOT assume a deployment succeeded without the user confirming it.** Log every promotion only after the user reports back with the actual result.
- **DO NOT schedule the PROD change window without SDLC_07 (Release Manager) approval.**
- **DO NOT run PB-06 (KB Refresh) until PROD deployment is confirmed complete.** Refreshing the KB against code that is not yet in PROD produces a KB that does not match reality.
- **DO NOT fix bugs or implement performance improvements noticed during deployment planning.** Note them in `## Observations` in the deployment plan. A separate story is required.
- **DO NOT skip the 15-minute monitoring window after PROD deployment.** Even if no errors are visible at the moment of deploy, issues sometimes surface only when real traffic hits the new code.
