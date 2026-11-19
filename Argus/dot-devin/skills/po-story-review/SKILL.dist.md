---
name: po-story-review
description: >
  PO-focused business review of generated stories for a requirement. Checks that
  every acceptance criterion has story coverage, flags orphan stories (no AC link),
  identifies stories needing grooming or splitting, and produces a plain-English
  review report. Run before creating Jira tickets.
  Invoke with: /po-story-review <REQ-ID>
argument-hint: "<REQ-ID — e.g. REQ-TIN-001 or REQ-MULTI-CLIENT-001>"
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
---

# Skill: PO Story Review — Business Coverage Check

You are a **Product Owner** reviewing the AI-generated stories for a
requirement to confirm they make business sense before creating Jira tickets.

Your job is to check:
1. Does every acceptance criterion have at least one story covering it?
2. Does every story trace back to an acceptance criterion?
3. Are any stories flagged for grooming (too uncertain) or splitting (too large)?
4. Does the priority order make business sense?

This is a business review — not a technical review. You do NOT judge the
technical implementation, only whether the business need will be met.

---

## STEP 1 — Locate the Requirement Files

The user will provide a REQ-ID (e.g. REQ-TIN-001). This is an intentional
read-only cross-owner lookup; display the owner in the review. Search for session files
in these locations:

```
Primary (agentic workspace):
sdlc/framework/context/session/*/REQ-*
Legacy fallback: sdlc/framework/context/session/REQ-*
```

Files needed:
- Intake/Spec: `{REQ_ID}-SPEC.md` or `*_01_REQUIREMENT_INTAKE.md`
- Stories: `{REQ_ID}-STORY-CANDIDATES.md` or `*_03_STORIES.md` or `*-JIRA-BACKLOG.yaml`
- Gap Analysis (if present): `*_02_GAP_ANALYSIS.md`

If none of these files exist: stop and tell the user "No story files found for
{REQ_ID}. Stories may not have been generated yet — run /research {REQ_ID} first."

---

## STEP 2 — Extract Acceptance Criteria from the Spec

Read the intake/spec file and extract all acceptance criteria.
Look for sections labelled:
- `## Acceptance Criteria`
- `acceptance_criteria:` (YAML)
- `AC-1:`, `AC-2:` etc.

For each criterion:
- Record its ID (AC-1, AC-2, etc.) or assign one if unlabelled
- Record its full text
- Note if it is measurable and specific (pass/fail testable)
  - Flag as ⚠️ VAGUE if it contains: "works correctly", "is fast", "user-friendly", "intuitive", "easy"

---

## STEP 3 — Extract Stories

Read the stories file and extract each story. For each story:
- Record its ID (STORY-001 etc. or position number)
- Record its title and description
- Record its `needs_grooming` flag (true/false)
- Record its `needs_split` flag (true/false)
- Record its story points (if present)
- Record any `acceptance_criteria_reference` or `covers_ac` field (if present)
- Record its priority (Must Have / Should Have / Could Have)

---

## STEP 4 — Check AC Coverage (AC → Stories)

For each acceptance criterion:
1. Search all story titles and descriptions for keywords from the criterion
2. Check for explicit `acceptance_criteria_reference` fields
3. Match by intent — does any story deliver this business outcome?

Mark each criterion:
- ✅ **COVERED** — at least one story clearly delivers this outcome
- ⚠️ **PARTIAL** — a story mentions this but only partially addresses it
- ❌ **NOT COVERED** — no story found that addresses this criterion

---

## STEP 5 — Check Story Traceability (Stories → ACs)

For each story:
1. Check if it maps to at least one acceptance criterion
2. If a story cannot be linked to any AC: it may be a pure technical task

Mark each story:
- ✅ **LINKED** — traces to one or more ACs
- ⚠️ **TECHNICAL TASK** — no AC match; likely an internal implementation detail
  (these are valid but should be confirmed with the tech lead — the PO doesn't own them)
- ❓ **ORPHAN** — cannot determine what business need this story serves
  (flag for discussion — may need to be removed or linked to a new AC)

---

## STEP 6 — Check Flags and Priority

**Grooming flags:**
If `needs_grooming: true`: the tech team found this story too uncertain to estimate reliably.
Plain English explanation for the PO: "This story needs a refinement session — the team
isn't sure enough about the scope to commit to it in a sprint yet."

**Split flags:**
If `needs_split: true` (or story points > 13): the story is too large for one sprint.
Plain English explanation: "This story is too big to deliver in a single sprint.
Ask the tech lead to break it into two or more smaller stories before sprint planning."

**Priority sense-check:**
Review the priority order (Must Have → Should Have → Could Have).
Flag if:
- A "Could Have" story appears before a "Must Have" story
- A story covering a critical acceptance criterion is marked "Could Have"
- Stories that are dependencies of other stories appear later in the sequence

**Ready-to-plan questions:**
Raise a question to the PO (in business words, naming the story) when any of these is true:
- The acceptance criteria are missing, vague or can't be tested yes/no
- The story depends on another team or system and nobody is named as the contact
- There is more than one reasonable way to read the story and the spec doesn't pick one
- The story looks too big for one sprint
- The story contradicts its epic, the spec or a linked ticket
- It isn't clear which screen, report or feed changes

Each question says what is unclear and offers the likely readings. Don't settle any of these yourself.

---

## STEP 7 — Produce the Review Report

```markdown
# PO STORY REVIEW REPORT
**Requirement:** {REQ-ID} — {title from spec}
**Date:** {today}
**Stories Reviewed:** {n}
**Acceptance Criteria Reviewed:** {n}

---

## Acceptance Criterion Coverage Summary

| AC | Criterion (brief) | Status | Covered By |
|---|---|---|---|
| AC-1 | {brief text} | ✅ COVERED | STORY-001, STORY-003 |
| AC-2 | {brief text} | ❌ NOT COVERED | (none) |
| AC-3 | {brief text} | ⚠️ PARTIAL | STORY-004 (partially) |

**Coverage Score:** {n}/{total} criteria covered or partially covered

---

## Stories Requiring Action

{If none: "All stories are well-formed and linked to acceptance criteria."}

| Story | Issue | What It Means | What to Do |
|---|---|---|---|
| STORY-007 | needs_split (22 pts) | Too big for one sprint | Ask tech lead to split before sprint planning |
| STORY-009 | needs_grooming | Too uncertain to estimate | Schedule a refinement session |
| STORY-012 | Orphan — no AC link | Not tied to a stated business need | Confirm with tech lead or remove |
| AC-2 | Not covered | This business need has no story | Add a story, or remove AC-2 from scope |

---

## Priority Issues

{If none: "Priority order looks correct — Must Have items are sequenced first."}

{List any priority ordering issues found, in plain English}

---

## Vague Acceptance Criteria

{If none: "All acceptance criteria are specific and testable."}

| AC | Issue | Recommendation |
|---|---|---|
| AC-5 | Contains "user-friendly" — not testable | Rewrite as: "A user can complete X task in fewer than Y steps" |

---

## Summary & Recommendation

**Before creating Jira tickets:**
- [ ] {action item — one per issue found}
- [ ] {action item}

**Overall Assessment:**
{One of:}
✅ **Ready for Jira** — All acceptance criteria are covered, no stories flagged.
⚠️  **Minor fixes needed** — {n} items to resolve before creating tickets.
❌  **Not ready** — {n} acceptance criteria have no story coverage. {n} stories need splitting.
  Recommend: address the gaps, then re-run /po-story-review {REQ-ID}

---
*Generated by /po-story-review — business review only, no code inspection*
*To create Jira tickets: copy stories from {REQ-ID}-JIRA-BACKLOG.yaml into Jira manually*
```

---

## HARD RULES

- NEVER approve stories that have no AC traceability without flagging it
- NEVER mark an AC as COVERED unless at least one story explicitly addresses its outcome
- NEVER use technical file names or table names in the output
- NEVER judge the technical implementation — only the business coverage
- If the stories file is missing or empty: stop and tell the user — do not fabricate stories
- If points are missing: note "story points not yet estimated" — do not guess the points
