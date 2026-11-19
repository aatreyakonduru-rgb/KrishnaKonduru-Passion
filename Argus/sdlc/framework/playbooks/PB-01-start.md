# Playbook: Start — say what you need

**Playbook ID:** PB-01
**Paste into:** Devin Cloud → Settings → Playbooks → New Playbook
**CLI equivalent:** `/start` skill (`.devin/skills/start/SKILL.md`)
**Scope:** Account-wide (applies to all Acme Claims sessions)
**Replaces:** the former PB-01 New Requirement, PB-21 Intake from Notes and PB-22 Ticket to Spec — `/intake` now takes a sentence, a Jira key or pasted notes and detects which.

---

## Title (paste into Devin Cloud "Title" field)

```
Acme Claims: Start — say what you need
```

## Description (paste into Devin Cloud "Description" field)

```
The front door for anything you need from the Acme Claims product. Type what you
need in your own words, a Jira key (ACME-1234) or your meeting notes. Devin works
out who you are and what kind of ask it is, opens a requirement if one is needed,
and tells you where it is, what happens next and who has to act.
```

## Playbook Body (paste into the main instruction area)

---

Run `/start` with whatever the user typed. That skill:

1. identifies the requester from `.devin/rules/people.yaml` (guests get read-only paths only);
2. classifies the ask — new requirement, idea to size, question, change-impact check,
   story review, an existing REQ-ID, or a Jira key — and hands it to the right skill
   (`/intake`, `/feasibility-check`, `/explain-capability`, `/impact-radar`,
   `/po-story-review`, `/status` + `/resume-session`);
3. for a new requirement, `/intake` runs the clarifying questions (in chat, or through the
   generated HTML form for an off-chat stakeholder), writes `REQ-{id}-SPEC.md` and presents
   gate SDLC_01_INTAKE_CLARIFICATION;
4. closes with three plain lines — where it is, what happens next, who has to act.

### RULES (always enforce, no exceptions)
- A gate closes only on the word `approved` (or the dashboard Approve action). "ok", "yes",
  "continue" leave it open.
- Do not read source code during intake; the spec is business language.
- Never fabricate a file path or a Jira field — verify before citing.
- Never write to Jira during intake; proposed ticket changes become SDLC_01 decision items.
- All session artefacts go to the owner-scoped session directory per
  `.devin/rules/session-isolation.md`.

---

## Advice & Pointers

- If the ask is genuinely ambiguous, ask one question with two options; do not ask the user to
  pick a stage name.
- A thin Jira ticket is normal: the ticket's gaps become the intake questions, marked for the
  reporter.
- Meeting notes usually hold more than one requirement — list them and ask which to do first.

## Forbidden Actions

- Do not skip SDLC_01 because there were no questions.
- Do not proceed to `/research` without a written, approved spec.
