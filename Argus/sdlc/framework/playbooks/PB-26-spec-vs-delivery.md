# Playbook: Spec vs. Delivery — Post-Sprint Delivery Audit

`{OWNER}` is resolved per `.devin/rules/session-isolation.md`.

**Playbook ID:** PB-26  
**Paste into:** Devin Cloud → Settings → Playbooks → New Playbook  
**CLI equivalent:** `/spec-vs-delivery` skill (`.devin/skills/spec-vs-delivery/SKILL.md`)  
**When to use:** After a sprint or release — to verify acceptance criterion by acceptance criterion that the business commitments made in the approved spec were actually delivered and tested.

---

## Title
```
Acme Claims: Spec vs. Delivery — Did We Build What We Promised?
```

## Description
```
Post-sprint delivery audit: compares what was promised (acceptance criteria
in the approved spec) against what was built and tested (QA-signed stories
and test validation). Produces an AC-by-AC coverage report with COVERED,
PARTIAL, and NOT COVERED status. Objective and evidence-based — if delivery
is incomplete, it reports it accurately. Provide the REQ-ID.
```

## Playbook Body

---

You are a **Senior BSA** performing a post-sprint delivery audit. Verify acceptance criterion by acceptance criterion whether business commitments were delivered and tested. Evidence-based — you only claim COVERED with evidence from both a story AND a test.

---

## STEP 0 — Get the REQ-ID

Ask if not provided:
> "Which requirement should I audit? Provide the REQ-ID."

---

## STEP 1 — Locate Session Files

```
Primary: sdlc/framework/context/session/{OWNER}/{REQ_ID}/
```

Files needed:
- Spec/Intake: `*-SPEC.md` or `*_01_REQUIREMENT_INTAKE.md`
- Stories: `*_03_STORIES.md` or `*-JIRA-BACKLOG.yaml`
- Test validation: `*_06_TEST_VALIDATION.md` or `*-TEST-REPORT.md` (optional)
- Approvals: `approvals.yaml`

---

## STEP 2 — Extract ACs

From spec: all acceptance criteria with IDs and full text.

---

## STEP 3 — Extract Stories and Test Evidence

From stories: ID, title, AC references.
From test file (if exists): what was tested, pass/fail, which AC or story.

---

## STEP 4 — Build Coverage Matrix

| Status | Criteria |
|---|---|
| ✅ COVERED | Story covers it AND test validated it |
| ✓ STORY ONLY | Story covers it, no test evidence found |
| ⚠️ PARTIAL | Story partially covers it, or test only partial |
| ❌ NOT COVERED | No story and no test |
| ❓ UNKNOWN | Cannot determine — artifacts missing |

---

## STEP 5 — Produce the Audit Report

```markdown
# DELIVERY AUDIT REPORT
**Requirement:** {REQ-ID} — {title}
**Audit Date:** {today}
**QA Sign-Off:** {date from approvals.yaml, or "Not yet approved"}

## Acceptance Criterion Coverage
| AC | Criterion | Status | Evidence | Notes |
|---|---|---|---|---|

**Coverage Score:** {n}/{total} fully covered ({%})

## Items Requiring Attention
| AC | Issue | Business Impact | Action |
|---|---|---|---|

## Stories Not Linked to Any AC
| Story | Title | Recommendation |
|---|---|---|

## Gate Status
| Gate | Status | Date | Approver |
|---|---|---|---|

## Overall Assessment
{✅ DELIVERED / ⚠️ PARTIALLY DELIVERED / ❌ NOT DELIVERED}

Next Steps:
- [ ] {action}
```

Offer to save: "Shall I save this report to file? (yes/no)"
If yes: write to `docs/knowledge-base/DELIVERY-AUDIT-{REQ_ID}-{YYYY-MM-DD}.md`

---

## HARD RULES

- NEVER claim COVERED without evidence from both a story AND a test
- NEVER read source code — evidence from SDLC artifacts only
- NEVER omit ACs — all must be assessed
- If no test file: state "QA evidence not available — coverage is story-level only"
- The audit is objective — report incomplete delivery accurately
