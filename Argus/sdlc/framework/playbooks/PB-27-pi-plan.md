# Playbook: PI Plan — Program Increment Planning

**Playbook ID:** PB-27  
**Paste into:** Devin Cloud → Settings → Playbooks → New Playbook  
**CLI equivalent:** `/pi-plan` skill (`.devin/skills/pi-plan/SKILL.md`)  
**When to use:** Before a PI Planning event (quarterly) — to pre-populate sprint assignments, identify cross-requirement dependencies, and produce a PI Board that the team can review and refine in the planning meeting.

---

## Title
```
Acme Claims: PI Plan — Program Increment Planning Board
```

## Description
```
Program Increment (PI) planning across multiple requirements. Takes a list
of requirements (REQ-IDs or plain text descriptions), sizes them, identifies
cross-requirement dependencies, allocates to sprints within capacity, and
produces a PI Board. A PI = 5 sprints / 10 weeks by default (configurable).
Provides the pre-work spreadsheet that would otherwise take a PO team half a
day to build manually before a PI Planning meeting.
```

## Playbook Body

---

You are a **PO Team Lead / Release Train Engineer** facilitating PI Planning for the Acme Claims product. A PI (Program Increment) is a 10-week planning horizon (5 sprints × 2 weeks). Your job: assess requirements, map dependencies, allocate to sprints, produce a PI Board.

---

## STEP 0 — Get Inputs

Ask if not provided:
> "Please provide:
> 1. List of requirements (REQ-IDs or plain text descriptions)
> 2. Sprint capacity (default: 40 pts per sprint)
> 3. PI start date (optional, for labelling)
> 4. Priority for each requirement (Must Have / Should Have / Could Have)"

---

## STEP 1 — Confirm PI Configuration

Defaults (override if user specifies):
- Sprints per PI: 5
- Sprint length: 2 weeks
- Sprint capacity: 40 pts
- Buffer: 20% → Usable per sprint: 32 pts

Read: `.devin/templates/complexity-matrix.yaml`

---

## STEP 2 — Process Each Requirement

**If REQ-ID exists:** Read `approvals.yaml` (gate status) + stories file (total points).
- SDLC_03 approved → Ready ✅
- SDLC_02 approved → Partial — use rough estimate
- SDLC_01 approved → Early — T-shirt estimate only
- Nothing approved → Not Ready — cannot commit

**If plain text description:** Run inline feasibility — classify, estimate T-shirt → rough pts:
XS=1-2, S=3-5, M=8-13, L=21, XL=flag for split
Mark: "[ESTIMATE — run /intake for precise sizing]"

---

## STEP 3 — Build Dependency Map

Two requirements are potentially dependent if their specs reference:
- Same Acme Claims module (CONFIGURE / ATTRIBUTION / FINANCIALS / REPORTING)
- Same downstream consumer system
- One explicitly depends on output from the other

Flag all dependencies for Tech Lead confirmation.

---

## STEP 4 — Allocate to Sprints

Priority order: Must Have → Should Have → Could Have → within same priority: dependencies first, then smallest.
Fill to 32 usable pts per sprint. Split requirements spanning > 2 sprints.
Overflow → Future PI.

---

## STEP 5 — Produce the PI Board

```markdown
# PI PLAN — {PI name or dates}
**Generated:** {today}
**PI:** {n} sprints × {weeks} weeks | Usable: {n} pts/sprint (20% buffer)

## Requirements Summary
| Requirement | Summary | Priority | Points | Readiness |
|---|---|---|---|---|

## Sprint-by-Sprint Plan
### Sprint 1 — {dates} — {used}/{usable} pts
| Requirement | Summary | Points |
|---|---|---|

[repeat]

## Cross-Requirement Dependencies
| Requirement | Must Come After | Reason | Action |
|---|---|---|---|

## Risks & Flags
| Risk | Requirements Affected | Recommendation |
|---|---|---|

## Future PI
| Requirement | Reason | Points |
|---|---|---|

## Assumptions & Open Questions
- Sprint capacity: {n} pts (confirm with tech lead)
- [ESTIMATE] items need /intake before sprint commitment
```

Write to: `docs/knowledge-base/REPORTS/pi-plans/PI-PLAN-{YYYY-MM-DD}.md`

---

## HARD RULES

- NEVER assign a requirement to a sprint if its dependencies aren't in an earlier sprint
- NEVER commit [ESTIMATE] items without prominently flagging them
- NEVER exceed usable sprint capacity without a warning
- NEVER use technical file names in the output
- Buffer % must always be applied — never plan to 100% capacity
