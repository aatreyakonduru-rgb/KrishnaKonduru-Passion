# Playbook: Gate Review — Find Manual SDLC Work to Automate

**Playbook ID:** PB-38  
**Paste into:** Devin Cloud → Settings → Playbooks → New Playbook  
**CLI equivalent:** `/gate-review` skill (`.devin/skills/gate-review/SKILL.md`)  
**When to use:** At a retro or PI planning, or whenever someone asks "what can we stop doing by hand?"

---

## Title
```
Acme Claims: Gate review — rank the manual work we could automate
```

## Description
```
Reads .devin/rules/manual-steps.yaml and the pipeline metrics and ranks the manual SDLC
work (copying share-drive files into the KB, running tests by hand, reporting deployment
status, chasing waiting PRs) as an automation backlog. Approval gates stay; people still
make every decision.
```

## Playbook Body

---

Run `/gate-review` and follow `.devin/skills/gate-review/SKILL.md` step by step.

1. `python3 sdlc/framework/tools/gate_review.py --md {session-dir}/GATE-REVIEW.md`
2. Explain the top items and what blocks the blocked ones.
3. Ask about the Don't know list: who does each task, how often, how long.
4. Add any new manual task the user names to `.devin/rules/manual-steps.yaml` by PR, with evidence.
5. For the item the user picks, propose the build and its owner.

## Forbidden actions
- Recommending that an approval gate be removed, skipped or auto-approved.
- Editing `.devin/rules/approval-gates.yaml`.
- Estimating time or frequency that nobody stated.
