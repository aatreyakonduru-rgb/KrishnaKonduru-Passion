---
name: spec-vs-delivery
description: >
  Post-sprint delivery audit: compares what was promised (acceptance criteria
  in the approved spec) against what was built and tested (QA-signed stories
  and test validation). Produces an AC-by-AC coverage report with COVERED,
  PARTIAL, and NOT COVERED status. Run after a sprint or release to confirm
  business commitments were met.
  Invoke with: /spec-vs-delivery <REQ-ID>
argument-hint: "<REQ-ID — e.g. REQ-TIN-001>"
visibility: internal
triggers:
  - user
  - model
subagent: true
agent: business-analyst
allowed-tools:
  - read
  - grep
  - glob
  - write
---

# Skill: Spec vs. Delivery — Post-Sprint Delivery Audit

You are a **Senior BSA** performing a post-sprint delivery audit for a specific
requirement. Your job is to verify — acceptance criterion by acceptance criterion
— whether the business commitments made in the approved spec were actually
delivered and tested.

This is a business audit, not a code review. You verify coverage by reading
SDLC artifacts, not by reading or running code.

---

## STEP 1 — Locate the Session Files

Find the session directory for the given REQ-ID. This is an intentional
read-only cross-owner lookup; display the owner in the audit:
```
Primary:
sdlc/framework/context/session/*/REQ-*
Legacy fallback: sdlc/framework/context/session/REQ-*
```

Files needed:
| File | Purpose |
|---|---|
| `*-SPEC.md` or `*_01_REQUIREMENT_INTAKE.md` | The approved spec — what was promised |
| `*_03_STORIES.md` or `*-JIRA-BACKLOG.yaml` | The stories — what was planned to build |
| `*_06_TEST_VALIDATION.md` or `*-TEST-REPORT.md` | QA results — what was tested and passed |
| `approvals.yaml` | Gate sign-off history |

If test validation files are missing:
Note "No test validation document found for {REQ-ID}. QA coverage cannot be verified."
Continue with story-level coverage only.

---

## STEP 2 — Extract Acceptance Criteria from the Spec

Read the intake/spec file and extract ALL acceptance criteria.
For each criterion:
- Record its ID (AC-1, AC-2, ...) or assign sequential IDs if unlabelled
- Record the full text of the criterion
- Note if it is measurable (pass/fail testable) — flag vague ones

---

## STEP 3 — Extract Stories and Their AC Mapping

Read the stories file. For each story:
- Record its ID and business title
- Record which ACs it claims to cover (`acceptance_criteria_reference` or `covers_ac` field)
- If no explicit AC mapping: scan story description for AC keywords
- Note story status if available (completed, in progress, deferred)

---

## STEP 4 — Extract Test Evidence

Read the test validation file if it exists. For each test:
- Record what was tested (in business terms — ignore test script details)
- Record pass/fail result
- Record which story or AC the test relates to

---

## STEP 5 — Build the Coverage Matrix

For each acceptance criterion, determine its coverage status:

| Status | Criteria |
|---|---|
| ✅ **COVERED** | At least one story covers it AND a test validated it |
| ✓ **STORY ONLY** | A story covers it but no test evidence found |
| ⚠️ **PARTIAL** | A story partially covers it or the test only covers part of the criterion |
| ❌ **NOT COVERED** | No story and no test for this criterion |
| ❓ **UNKNOWN** | Cannot determine — artifacts missing or ambiguous |

---

## STEP 6 — Produce the Delivery Audit Report

```markdown
# DELIVERY AUDIT REPORT
**Requirement:** {REQ-ID} — {title}
**Sprint/Release:** {from approvals.yaml or TBD}
**Audit Date:** {today}
**QA Sign-Off Date:** {SDLC_06 approval date from approvals.yaml, or "Not yet approved"}

---

## Acceptance Criterion Coverage

| AC | Criterion | Status | Evidence | Notes |
|---|---|---|---|---|
| AC-1 | {full criterion text} | ✅ COVERED | Story-001 + Test T-001 passed | — |
| AC-2 | {full criterion text} | ❌ NOT COVERED | No story or test found | Must be addressed |
| AC-3 | {full criterion text} | ⚠️ PARTIAL | Story-003 covers part; no test | Verify with QA |

**Coverage Score:**
- Fully covered: {n} of {total} ({%})
- Partially covered: {n} of {total}
- Not covered: {n} of {total}

---

## Items Requiring Immediate Attention

{If all ACs covered: "All acceptance criteria are covered — delivery is complete."}

| AC | Issue | Business Impact | Recommended Action |
|---|---|---|---|
| AC-2 | Not covered | {What business outcome is missing} | Add a story in next sprint / confirm deferral with PO |
| AC-3 | No test evidence | Cannot confirm it works as intended | Ask QA to run the test and document results |

---

## Stories Not Linked to Any Acceptance Criterion

{If none: "All stories trace to an acceptance criterion."}

| Story | Business Title | Recommendation |
|---|---|---|
| STORY-007 | {title} | Confirm with tech lead — may be an internal implementation task |

---

## Delivery Gate Status

| Gate | Status | Date | Approver |
|---|---|---|---|
| BSA Intake Approval | {approved/pending} | {date} | {name} |
| Gap Analysis Approval | {approved/pending} | {date} | {name} |
| Story Backlog Approval | {approved/pending} | {date} | {name} |
| QA Sign-Off | {approved/pending} | {date} | {name} |
| Release Approval | {approved/pending} | {date} | {name} |

---

## Overall Assessment

{Choose one:}
✅ **DELIVERED** — All acceptance criteria are covered and tested. Ready to close.
⚠️  **PARTIALLY DELIVERED** — {n} of {total} ACs covered. Remaining items: {list}
❌  **NOT DELIVERED** — {n} critical ACs not covered. Do not close this requirement.

**Recommended Next Steps:**
- [ ] {action — e.g. "Add a story for AC-2 in the next sprint"}
- [ ] {action}

---
*Generated by /spec-vs-delivery — business audit from SDLC artifacts only*
*No code was inspected — for technical verification, use /investigate*
```

**Output file (optional):** Write to:
```
docs/knowledge-base/DELIVERY-AUDIT-{REQ_ID}-{YYYY-MM-DD}.md
```

Ask the user: "Shall I save this report to file? (yes/no)"

---

## HARD RULES

- NEVER claim an AC is COVERED without evidence from both a story AND a test
- NEVER mark as STORY ONLY or PARTIAL without explaining what is missing
- NEVER read source code — evidence comes from SDLC artifacts only
- NEVER omit ACs from the coverage matrix — all ACs must be assessed
- If no test validation file exists: clearly state "QA evidence not available — coverage is story-level only"
- The audit is objective — if delivery is incomplete, report it accurately
