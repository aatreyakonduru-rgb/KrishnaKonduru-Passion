# Playbook: QA Scenarios — Acceptance Criteria to Behave Scenarios

**Playbook ID:** PB-39  
**Paste into:** Devin Cloud → Settings → Playbooks → New Playbook  
**CLI equivalent:** `/qa-scenarios` skill (`.devin/skills/qa-scenarios/SKILL.md`)  
**When to use:** When a story's acceptance criteria are agreed and QA needs automation scenarios for the ACME/claims-qa suite.

---

## Title
```
Acme Claims: QA scenarios — draft Behave scenarios from acceptance criteria
```

## Description
```
Drafts Gherkin scenarios for ACME/claims-qa using the step sentences the suite already has,
names the Snowflake query keys and TestData sets each scenario needs, lists what is missing,
and shows which ACs are covered. A draft for QA to review; nothing is run or pushed.
```

## Playbook Body

---

Run `/qa-scenarios {REQ-ID} {STORY-ID}` and follow `.devin/skills/qa-scenarios/SKILL.md` step by step.

1. Read the story's ACs from `{REQ_ID}-BACKLOG.md` / `{REQ_ID}-SPEC.md`, or number the pasted ones.
2. Clone or pull `ACME/claims-qa`; run `qa_scenarios.py inventory`.
3. Search reusable steps with `qa_scenarios.py steps --grep`; take a new tag from `next-tag`.
4. Draft the feature; mark new steps `# NEW STEP`; put `# covers: AC-n` above each scenario.
5. `qa_scenarios.py check {draft}.feature --ac AC-1 ...` until only deliberate NEW items remain.
6. Write `{REQ_ID}-{STORY_ID}-QA-SCENARIOS.md` with coverage, new steps, new queries, new test data and the three lists.
7. Hand to QA. A PR to claims-qa only if QA asks.

## Forbidden actions
- Presenting a new step, query key, table or column as one that exists.
- Real member, provider or TIN data in Examples tables.
- Pushing to ACME/claims-qa's main branch, or saying the scenarios pass.
