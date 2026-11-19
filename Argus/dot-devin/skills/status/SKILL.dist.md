---
name: status
description: Where is my requirement and what happens next? "/status REQ-001" answers in three plain lines — where it is, the next step, and who has to act — then the gate-by-gate table underneath for people who want it. "/status" alone picks your most recent requirement. Works for BSAs, POs and managers who never run a stage themselves.
argument-hint: "[REQ-ID]"
visibility: public
triggers:
  - user
  - model
invocations:
  - /status
  - where is REQ
  - what is the status of
  - what happens next
  - who is it waiting on
allowed-tools:
  - read
  - bash
---

# /status — where is it, what's next, who acts

## STEP 1 — Ask the gate library

```bash
python3 sdlc/framework/tools/gates.py next [REQ-ID]          # the plain-English line
python3 sdlc/framework/tools/gates.py status REQ-ID          # every gate, signed by whom, when
```

`next` with no argument uses the requester's most recently touched requirement. If it says the
requirement is not one of theirs, stop there and repeat its advice (`/start` or `/handover`); do not
go looking in other people's session directories.

## STEP 2 — Answer in this shape

```
Where it is:  REQ-001 — implement, STORY-2 waiting at Code Generation Review (SDLC_05)
Next:         a developer reviews the pull request and replies approved / rejected / needs revision
Who:          any developer on the roster (dev mode: you may sign it yourself) — /approve REQ-001
```

Then the `status` table. If a gate has been waiting longer than its `timeout_hours`
(`.devin/rules/approval-gates.yaml`), say so and that the daily escalation will nudge the owner.

## STEP 3 — Offer the one useful follow-up

- waiting on a gate → `/approve REQ-ID`
- sent back for rework → the stage command to rerun (`/implement REQ-ID STORY-n` etc.)
- ready for the next stage → that stage command
- finished → `/release-notes REQ-ID`

Say nothing about internal file layouts unless asked. Never change a gate from this skill.
