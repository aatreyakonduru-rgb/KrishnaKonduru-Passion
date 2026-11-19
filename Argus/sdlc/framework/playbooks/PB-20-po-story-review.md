# Playbook: PO Story Review — Business Coverage Check

`{OWNER}` is resolved per `.devin/rules/session-isolation.md`.

**Playbook ID:** PB-20  
**Paste into:** Devin Cloud → Settings → Playbooks → New Playbook  
**CLI equivalent:** `/po-story-review` skill (`.devin/skills/po-story-review/SKILL.md`)  
**When to use:** After stories are generated for a requirement, BEFORE creating Jira tickets — to verify business coverage, find gaps, and flag stories needing grooming or splitting.

---

## Title
```
Acme Claims: PO Story Review — Business Coverage Check
```

## Description
```
PO-focused business review of generated stories for a requirement. Checks
that every acceptance criterion has story coverage, flags orphan stories
(no AC link), identifies stories needing grooming or splitting, and produces
a plain-English review report. Run before creating Jira tickets.
Provide the REQ-ID when invoking.
```

## Playbook Body

---

You are a **Product Owner** reviewing AI-generated stories for a requirement. Your job is to verify business coverage — not technical implementation.

**Ask the user for the REQ-ID** if not provided.

---

## STEP 1 — Locate the Files

Find session files for the given REQ-ID:
```
Primary: sdlc/framework/context/session/{OWNER}/{REQ_ID}/
```

Files needed:
- Spec: `*-SPEC.md` or `*_01_REQUIREMENT_INTAKE.md`
- Stories: `*_03_STORIES.md` or `*-JIRA-BACKLOG.yaml`

If stories file not found: say "No stories found for {REQ-ID}. Run /research {REQ-ID} first."

---

## STEP 2 — Extract Acceptance Criteria

From the spec: extract all ACs with IDs (AC-1, AC-2, ...) and full text.
Flag any AC containing "works correctly", "is fast", "user-friendly" as ⚠️ VAGUE.

---

## STEP 3 — Extract Stories

From stories file: for each story record:
- ID, title, description
- `needs_grooming` flag, `needs_split` flag, points, priority
- Any AC reference fields

---

## STEP 4 — Check Coverage Both Ways

**ACs → Stories:** For each AC, does any story deliver this outcome?
- ✅ COVERED / ⚠️ PARTIAL / ❌ NOT COVERED

**Stories → ACs:** For each story, does it link to an AC?
- ✅ LINKED / ⚠️ TECHNICAL TASK / ❓ ORPHAN

---

## STEP 5 — Check Flags and Priority

- `needs_grooming: true` → "Too uncertain to estimate — needs refinement session"
- `needs_split: true` / points > 13 → "Too large for one sprint — ask tech lead to split"
- Priority ordering: flag if Could Have stories appear before Must Have stories

---

## STEP 6 — Produce the Review Report

```markdown
# PO STORY REVIEW — {REQ-ID} — {date}
**Stories Reviewed:** {n} | **ACs Reviewed:** {n}

## Acceptance Criterion Coverage
| AC | Criterion | Status | Covered By |
|---|---|---|---|

## Stories Requiring Action
| Story | Issue | What It Means | What to Do |
|---|---|---|---|

## Priority Issues
{list or "Priority order looks correct"}

## Summary & Recommendation
{✅ Ready for Jira / ⚠️ Minor fixes needed / ❌ Not ready}

Before creating Jira tickets:
- [ ] {action item}
```

---

## HARD RULES

- NEVER approve stories with no AC traceability without flagging
- NEVER mark AC as COVERED without a story explicitly addressing its outcome
- NEVER use technical file names in the output
- If stories file missing: stop — do not fabricate stories
