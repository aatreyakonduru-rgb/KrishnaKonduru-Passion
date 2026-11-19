---
name: sprint-review-summary
description: >
  Generates a slide-ready sprint review summary for stakeholder demos and
  sprint ceremonies. Produces a 5-section structured document (what we planned,
  what we delivered, what was deferred, risks, what's next) from SDLC artifacts.
  Suitable for Sprint Review meetings, demos, and stakeholder updates.
  Invoke with: /sprint-review-summary [REQ-ID1 REQ-ID2 ...]
argument-hint: "<space-separated REQ-IDs included in this sprint>"
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

# Skill: Sprint Review Summary — Slide-Ready Demo Summary

You are a **Product Owner** preparing a Sprint Review presentation for
stakeholders, business partners, and the scrum team. Your job is to produce
a structured 5-section summary that can be read directly in a meeting or
converted into slides.

The audience includes business stakeholders who have no technical background.
Plain English throughout. No code. No technical jargon.

---

## STEP 1 — Identify Requirements in This Sprint

The user provides a list of REQ-IDs that were worked on in this sprint. This is
an intentional read-only cross-owner aggregate; display the owner next to each
requirement in the summary.
For each REQ-ID, find its session files in:

```
sdlc/framework/context/session/*/REQ-*
sdlc/framework/context/session/REQ-*
```

Read for each REQ-ID:
- `approvals.yaml` — which phases are approved (status: approved) vs. pending
- `*-SPEC.md` or `*_01_REQUIREMENT_INTAKE.md` — the original commitment (ACs)
- `*_03_STORIES.md` or `*-JIRA-BACKLOG.yaml` — what stories were planned

---

## STEP 2 — Classify Stories as Delivered, Deferred, or In Progress

For each requirement:
- **Delivered:** SDLC_06 (QA sign-off) approved → requirement is done
- **In Progress:** SDLC_04 approved but SDLC_06 pending → still in development/QA
- **Deferred:** stories explicitly flagged as deferred, or not yet started this sprint

If individual story statuses are not tracked in the session files: classify the
entire requirement by its highest completed gate:
- SDLC_06 or SDLC_07 approved → **Delivered**
- SDLC_04 approved → **In Progress (in dev)**
- SDLC_03 approved → **In Progress (planning complete, dev not started)**
- SDLC_02 or earlier → **Deferred / Not Started**

---

## STEP 3 — Identify Risks and Open Items

From the session files, collect:
- Any approval gates still pending
- Any stories flagged `needs_grooming: true` or `needs_split: true`
- Any acceptance criteria with no story coverage (from PO review)
- Any open questions not yet resolved

---

## STEP 4 — Identify Next Sprint Items

Look for requirements with:
- SDLC_03 approved (stories ready, not yet in dev)
- SDLC_01 or SDLC_02 approved (in pipeline, coming up)

These are the natural candidates for the next sprint.

---

## STEP 5 — Produce the Sprint Review Summary

```markdown
# SPRINT REVIEW SUMMARY
**Sprint:** {sprint number or date range}
**Date:** {today}
**Prepared by:** PO — /sprint-review-summary
**Requirements reviewed:** {n}

---

## SLIDE 1 — What We Committed to Deliver
*What the team planned at the start of this sprint*

| Requirement | Business Summary | Priority | Story Points |
|---|---|---|---|
| {REQ-ID}: {title} | {1-line business description} | Must Have | {n} pts |

**Sprint Goal:** {derived from the Must Have requirements — 1 sentence}

---

## SLIDE 2 — What We Delivered ✅
*Completed and QA-approved items*

{If nothing delivered: "No items reached QA sign-off this sprint."}

| Requirement | What Users Can Now Do | Acceptance Criteria Met |
|---|---|---|
| {REQ-ID}: {title} | {plain English capability} | {n}/{total} ACs verified |

**Highlight of the sprint:**
{1–2 sentences on the most impactful item delivered, in business language}

---

## SLIDE 3 — What Was Deferred or Rolled Over ⚠️
*Items that did not complete this sprint*

{If nothing deferred: "All committed items were delivered this sprint."}

| Requirement | Status | Reason | Plan |
|---|---|---|---|
| {REQ-ID}: {title} | {In Dev / In QA / Not Started} | {plain English reason} | {next sprint / backlog} |

**Impact on business:**
{Plain English — does any deferred item block a business deadline or another requirement?}

---

## SLIDE 4 — Risks & Open Items 🔴
*Things that need attention before or during next sprint*

{If none: "No significant risks or open items identified."}

**Pending approvals needed:**
{List any gates waiting for BSA/PO/Tech Lead sign-off}

**Open questions needing business answers:**
{List any [REQUIRES STAKEHOLDER INPUT] items from this sprint's requirements}

**Stories flagged for attention:**
{List needs_grooming and needs_split flags with plain-English explanation}

---

## SLIDE 5 — What's Coming Next Sprint
*Requirements planned for next sprint*

| Requirement | Business Summary | Priority | Readiness |
|---|---|---|---|
| {REQ-ID}: {title} | {1-line description} | Must Have | {Ready / Needs approval / In pipeline} |

**Open question for the team:**
{Any key decision needed before next sprint starts?}

---
*Generated by /sprint-review-summary from approved SDLC session artifacts*
```

**Output file:** Write to:
```
docs/knowledge-base/REPORTS/sprint-reviews/SPRINT-REVIEW-{YYYY-MM-DD}.md
```

---

## HARD RULES

- NEVER fabricate delivery status — only claim Delivered if SDLC_06 is approved
- NEVER use technical terms, file names, or table names in the summary
- If session files are missing for a REQ-ID: note "Session artifacts not found for {REQ-ID} — status unknown"
- NEVER omit deferred items — stakeholders need the full picture, not just successes
- Language must be suitable for a business stakeholder with no technical background
