---
name: gate-review
description: >
  Find the manual work in the Acme Claims SDLC that a tool could do instead — copying share-drive files
  into the knowledge base, re-running checks, reporting deployment status by hand, chasing
  waiting PRs — and rank it as an automation backlog. Reads the manual-work register
  (.devin/rules/manual-steps.yaml) and the pipeline metrics. It keeps every approval gate:
  people still make the decisions, and for a slow gate it only suggests automating the
  evidence the approver reads.
  Invoke with: /gate-review [--file metrics.jsonl]
argument-hint: "[--file metrics.jsonl]"
visibility: internal
triggers:
  - user
  - model
invocations:
  - /gate-review
  - what can we automate
  - which manual steps can go
  - automation backlog
allowed-tools:
  - bash
  - read
  - edit
  - git_create_pr
---

# /gate-review — what manual work can we automate?

The point is to take repetitive hand work out of the SDLC, not to take people out of the
decisions. Two kinds of step are kept apart everywhere:

- **Manual work**: copying, checking, re-typing, looking things up, chasing. Automate it.
- **Human decisions**: someone accountable says yes or no (the approval gates, merging a prod
  tag PR). These stay. Automation may only prepare what the approver reads.

## Steps

1. **Run the review.**
   ```bash
   python3 sdlc/framework/tools/gate_review.py --md <session-dir>/GATE-REVIEW.md
   ```
   It validates the register first and stops if an entry is broken (missing evidence, a human
   decision marked automated, a plan that would skip a gate).

2. **Explain the backlog** in a few sentences: what the top items are, what each would take,
   and what blocks the blocked ones (usually access — SharePoint, Artifactory, RDS).
   "Time per month" is only shown when both frequency and minutes are known. Otherwise it is
   `[?]`. Never estimate it yourself.

3. **Ask about the gaps.** The report's *Don't know* list says who does each task, how
   often, and how long it takes. Ask the user and suggest an answer if you have one. To collect
   real numbers, people log a run when they do it:
   ```bash
   python3 sdlc/framework/tools/metrics.py record manual_step --req NONE --task KB-SHAREDRIVE-SYNC --minutes 30
   ```

4. **New manual tasks.** If the user names a manual step that isn't in the register, draft an
   entry with an `[E: source]` for it (a skill line, a KB page, the user's own message with the
   date) and add it to `.devin/rules/manual-steps.yaml` by PR. Don't add entries without evidence.

5. **Next step for an item.** When the user picks an item, propose the concrete build (a
   skill, a tool, or a Devin automation on a schedule) and who owns it. Building it is a
   separate piece of work.

## Don't
- Recommend removing, skipping or auto-approving an approval gate, however often it passes.
- Edit `.devin/rules/approval-gates.yaml` from this skill.
- Mark a `human_decision` entry as automated.
