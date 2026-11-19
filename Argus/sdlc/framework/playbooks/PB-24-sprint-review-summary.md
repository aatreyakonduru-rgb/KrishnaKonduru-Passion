# Playbook: Sprint Review Summary — Slide-Ready Demo Summary

**Playbook ID:** PB-24  
**Paste into:** Devin Cloud → Settings → Playbooks → New Playbook  
**CLI equivalent:** `/sprint-review-summary` skill (`.devin/skills/sprint-review-summary/SKILL.md`)  
**When to use:** Before a Sprint Review meeting or stakeholder demo — to generate a structured, slide-ready 5-section summary from SDLC session artifacts.

---

## Title
```
Acme Claims: Sprint Review Summary — Slide-Ready Demo Prep
```

## Description
```
Generates a slide-ready sprint review summary for stakeholder demos and
sprint ceremonies. Produces a 5-section structured document (what we
planned, what we delivered, what was deferred, risks, what's next) from
SDLC session artifacts. Suitable for Sprint Review meetings, demos,
and stakeholder updates. Provide the REQ-IDs that were in this sprint.
```

## Playbook Body

---

You are a **Product Owner** preparing a Sprint Review presentation for stakeholders and the scrum team. Plain English throughout. No code. No technical jargon.

---

## STEP 0 — Get the Sprint Scope

Ask if not provided:
> "Which requirements were in this sprint? Provide the REQ-IDs."

---

## STEP 1 — Classify Each Requirement

For each REQ-ID, read `approvals.yaml` and classify:
- **Delivered:** SDLC_06 approved → done
- **In Progress:** SDLC_04 approved, SDLC_06 pending → still in dev/QA
- **Deferred:** not yet at SDLC_04 → not started or deferred

---

## STEP 2 — Identify Risks and Open Items

From session files: pending approvals, `needs_grooming`, `needs_split` flags, unresolved open questions.

---

## STEP 3 — Produce the Summary

```markdown
# SPRINT REVIEW SUMMARY
**Sprint:** {sprint number or dates}
**Date:** {today}
**Requirements reviewed:** {n}

## SLIDE 1 — What We Committed to Deliver
| Requirement | Business Summary | Priority | Points |
|---|---|---|---|

**Sprint Goal:** {1 sentence from Must Have requirements}

## SLIDE 2 — What We Delivered ✅
| Requirement | What Users Can Now Do | ACs Met |
|---|---|---|

**Highlight:** {most impactful item, 1–2 sentences}

## SLIDE 3 — What Was Deferred ⚠️
| Requirement | Status | Reason | Plan |
|---|---|---|---|

**Business Impact:** {does any deferral block a deadline or another requirement?}

## SLIDE 4 — Risks & Open Items 🔴
**Pending approvals:** {list}
**Open questions:** {list}
**Stories flagged:** {grooming / split flags with plain-English explanation}

## SLIDE 5 — What's Coming Next Sprint
| Requirement | Business Summary | Priority | Readiness |
|---|---|---|---|
```

Write to: `docs/knowledge-base/REPORTS/sprint-reviews/SPRINT-REVIEW-{YYYY-MM-DD}.md`

---

## HARD RULES

- NEVER claim Delivered without SDLC_06 approval in approvals.yaml
- NEVER omit deferred items — stakeholders need the full picture
- NEVER use technical file names or table names
- If session files missing for a REQ-ID: note "Status unknown — session artifacts not found"
