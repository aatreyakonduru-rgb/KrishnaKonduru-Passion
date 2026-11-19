---
name: release
description: >
  SDLC Stage 7 — Deployment Planning, Rollback Planning, Environment Promotion,
  Monitoring Configuration. Orchestrates the full release pipeline for one story
  after QA sign-off: produces a deployment plan per environment (DEV→SIT→UAT→PROD),
  documents a tested rollback plan, guides smoke test verification, writes a
  deployment log, and presents the SDLC_07_ENV_PROMOTION_APPROVAL block for the
  Release Manager. After PROD deployment, prompts to run /kb-refresh.
  Invoke with: /release REQ-{id} STORY-{n}
  Source agent: .devin/agents/release.agent.yaml
argument-hint: "<REQ-ID> <STORY-ID>  e.g. REQ-TIN-001 STORY-003"
visibility: internal
triggers:
  - user
  - model
subagent: true
allowed-tools:
  - read
  - write
  - edit
  - glob
---

# Skill: Release Orchestrator (SDLC Stage 7)

Background reading: `sdlc/framework/workflows/release.md` (the longer stage procedure; where it and this skill differ, this skill is the one to follow).

You are an **Ops / Release Manager** promoting a Acme Claims story through
environments. Your job is to produce a concrete deployment plan, verify rollback
readiness, guide the promotion sequence, and log each environment deployment.

Source agent spec:
```
.devin/agents/release.agent.yaml
```
Child steps — executed inline by this skill, they are not separate skill files:
```
promote-env  ```

---

## INPUTS

Parse arguments: `REQ_ID` and `STORY_ID`.

---

## SESSION DIRECTORY

```
sdlc/framework/context/session/{OWNER}/{REQ_ID}/
`{OWNER}` is resolved per `.devin/rules/session-isolation.md`.
```

---

## STEP 0 — Gate Check

**Trace lines (Argus):** print `[SDLC] kb <path> — loaded: <why>` / `skipped: <why>`, `[SDLC] rule <path> — loaded|deferred: <why>`, `[SDLC] chain DC-… — …` and `[SDLC] decision … — …` as each file is opened, skipped or each choice made, per `.devin/rules/workbench-trace.md` — here: a `kb` line for `approvals.yaml`, the test report, the routing map and the backlog; a `kb` line for each deploy-repo file read to see what an environment runs now (`values-<env>.yaml`, image tags); a `rule` line for `approval-gates.yaml`; and a `decision` line for the environment sequence, each layer's deploy order, the rollback plan chosen, the change window, and anything held back from an environment and why.

Read owner-scoped `approvals.yaml` and `{REQ_ID}-{STORY_ID}-TEST-REPORT.md`.
Confirm:
- `SDLC_06_QA_SIGNOFF` phase is approved and has a real recorded signer
- `Overall QA Assessment` status is PASS or PASS_WITH_WARNINGS
- No CRITICAL or HIGH defects are open

Read `{REQ_ID}-{STORY_ID}-ROUTING.md` for the rollback plan and affected layers.
Read `{REQ_ID}-JIRA-BACKLOG.yaml` for the story's branch name and dependency order.

If QA status is FAIL: STOP.
> "QA sign-off has not been obtained or the QA report shows FAIL.
> Resolve all CRITICAL and HIGH defects before release."

---

## STEP 1 — Deployment Plan

Produce `{REQ_ID}-{STORY_ID}-DEPLOYMENT-PLAN.md`:

```markdown
# Deployment Plan: {REQ_ID} — {STORY_ID}

**Story**: {title}
**Branch**: feature/{REQ_ID}-{STORY_ID}-{slug}
**Planned Date**: {target date — ask user if not known}

---

## Environment Sequence
DEV (already done — code review passed) → SIT → UAT → PROD
(the sequence is `workflow.environments` in `.devin/rules/sdlc-profile.json`;
`python3 sdlc/framework/tools/promote_check.py --list` prints it — plan for the
environments listed there)
Each promotion is carried out with `/promote <from> <to>` (see `.devin/skills/promote/SKILL.md`),
which raises the PRs and waits for the Tekton tag; a person merges.

## Deployment Steps per Environment

### SIT
1. Merge `feature/{branch}` to `develop` (or `sit` branch per team convention)
2. Run DB migration(s): {list migration file names from routing map}
3. Deploy API changes: {list changed API files}
4. Deploy UI changes: {list changed UI files}
5. Deploy ETL changes (if applicable): {list}
6. Run smoke tests (see list below)
7. QA team executes SIT test suite from test report and from
   `dev-unit-test-cases/{release}/RELEASE-TEST-CASES.md` (see "Release test cases" below)

### UAT
1. Promote from SIT → UAT (same artifact, no code changes)
2. Confirm DB migration is idempotent (safe to skip if already applied)
3. PO runs UAT acceptance testing against ACs from spec

### PROD
1. Schedule change window: {ask user}
2. Take DB snapshot / backup before migration
3. Run DB migration(s) in PROD
4. Deploy API changes
5. Deploy UI changes
6. Deploy ETL changes (if applicable)
7. Run smoke tests
8. Monitor for 15 min before declaring success

## Smoke Tests (run after each environment promotion)

| Test | What to verify | How |
|---|---|---|
{For each AC from the story, derive a quick manual or automated smoke test}

## Dependencies
{Any other stories that must deploy before this one (from backlog dependency graph)}

## Change Window
**SIT**: anytime (QA-controlled)
**UAT**: {user to confirm}
**PROD**: {user to confirm — must be scheduled}
```

---

## STEP 1a — Release test cases for QA

When the branch is promoted to QA/SIT, build the QA index of the tests written for every story
in that release. The tests themselves stay in the application test files; the index tells QA
which of them belong to this release and which acceptance criterion each one covers.

```bash
python3 sdlc/framework/tools/gen_release_tests.py \
    --release {fix version or release date, e.g. 2026-11-13} \
    --story ACME-nnnn --story ACME-mmmm        # every story going to QA in this release
```

It reads `phases.code_review.jira_key` and `tests` from each story's session `approvals.yaml`
(written by `/implement`), checks the test files and test names still exist in source, and
writes `dev-unit-test-cases/{release}/RELEASE-TEST-CASES.md`. Commit that file with the
release. If a story is pulled from the release, re-run without it — the manifest is
regenerated, never edited by hand. Any "missing" row or "no tests recorded" story goes into
the SDLC_07 gate message as a risk; `--strict` refuses to write the file in that case.

---

## STEP 2 — Rollback Plan

Produce `{REQ_ID}-{STORY_ID}-ROLLBACK-PLAN.md` from the routing map's rollback section:

```markdown
# Rollback Plan: {REQ_ID} — {STORY_ID}

**Trigger**: Use this plan if any smoke test fails after PROD deployment,
or if a P1 incident is raised within 2 hours of deployment.

## Rollback Steps (execute in reverse deployment order)

### 1. UI Rollback
{If UI was changed: revert commit or toggle feature flag}
Time estimate: 5 min

### 2. API Rollback
{Revert API commit or toggle feature flag}
Time estimate: 5 min

### 3. DB Rollback
{CRITICAL: DB rollback is the highest-risk step}
If the migration was additive (new nullable column only):
  → Run reverse migration: {V{n}__reverse_{slug}.sql — must be written before PROD deploy}
If the migration was destructive (column rename/removal, data backfill):
  → Restore from pre-deployment snapshot: {snapshot name/timestamp}
Time estimate: 15–30 min depending on data volume

### 4. ETL Rollback
{Revert ETL script changes}
Time estimate: 10 min

## Rollback Verification
After rollback: re-run smoke tests to confirm system is back to pre-deployment state.

## Rollback Contact
{On-call engineer contact — ask user to fill in}

## Rollback Tested?
[ ] Rollback tested in DEV/SIT before PROD deployment (REQUIRED)
```

**Ask the user:** "Has the rollback been tested in DEV or SIT?
If not, please do so before scheduling PROD deployment."

---

## STEP 3 — Environment Promotion Log

For each environment that is deployed, append to `{REQ_ID}-{STORY_ID}-DEPLOYMENT-LOG.md`.
Ask the user to report what happened after each deployment. Record:

```markdown
# Deployment Log: {REQ_ID} — {STORY_ID}

## DEV → SIT
**Timestamp**: {ISO8601}
**Deployed by**: {name}
**Steps**:
  1. {step} → SUCCESS / FAILED
  2. {step} → SUCCESS / FAILED
**Smoke Tests**:
  | Test | Status |
  |---|---|
  | {test} | PASSED / FAILED |
**Status**: SUCCESS / FAILED (+ rollback taken: yes/no)

## SIT → UAT
{same structure}

## UAT → PROD
{same structure — also record: snapshot taken before migration, change window observed}
```

---

## STEP 4 — Gate: SDLC_07 (Release Manager Approval)

Present SDLC_07 with the deployment plan, rollback plan, and environment
configuration paths using `.devin/rules/gate-presentation.md`. Load the
canonical artifact list and checklist from `.devin/rules/approval-gates.yaml`
instead of writing a divergent approval block.

Tell the user:
```
Release plan complete for {STORY_ID}.

Files written:
  {REQ_ID}-{STORY_ID}-DEPLOYMENT-PLAN.md
  {REQ_ID}-{STORY_ID}-ROLLBACK-PLAN.md

SDLC_07 gate is pending Release Manager sign-off.

When PROD deployment is complete, run:
  /kb-refresh {REQ_ID} {STORY_ID}
  (to update the Knowledge Base with the deployed changes)
```

---

## STEP 5 — Post-PROD Monitoring Checklist

After PROD deployment, prompt the user to confirm:
- [ ] API response times within SLA (< 2s for standard queries)
- [ ] Error rate unchanged (check CloudWatch / application logs)
- [ ] DB query counts stable (no runaway queries from new code)
- [ ] Snowflake RLS policy still applying correctly (spot-check a tenant-filtered query)
- [ ] 15-minute observation window completed with no P1/P2 alerts

If any check fails: trigger rollback procedure.

---

## HARD RULES
- NEVER deploy to PROD without a tested rollback plan
- NEVER skip the environment sequence (`workflow.environments`; ours DEV → SIT → UAT → PROD)
- NEVER mark a DB rollback as "easy" if it involves data backfill — that is always HIGH RISK
- NEVER proceed to PROD without SDLC_07 approval from the Release Manager,
  recorded using `.devin/rules/gate-presentation.md`
- ALWAYS write the reverse migration SQL before the PROD deployment window
- After PROD: always prompt to run /kb-refresh — the KB must stay in sync with deployed code
