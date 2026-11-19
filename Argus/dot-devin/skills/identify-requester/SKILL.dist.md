---
name: identify-requester
description: Work out who is asking and which of their delivery roles applies to this request, then route the session to that role's defaults — lens, skills, playbooks and the shape of the answer. Run this first in any session that has a person behind it, and whenever the requester says the assumed role is wrong or changes hats. Also answers "who am I", "what can I do in my role", /whoami and /myrole.
argument-hint: "[nothing] or [role to assume, e.g. qa_lead] or [a name, email or Jira username to look up]"
visibility: internal
triggers:
  - user
  - model
invocations:
  - /identify-requester
  - /whoami
  - /who-am-i
  - /myrole
  - who am I
  - what is my role
  - what can I do in my role
  - I am the QA lead
  - treat me as a developer
allowed-tools:
  - read
  - glob
  - grep
  - bash
---

# /identify-requester — who is asking, and with which hat on

Two files do the work here:

| File | What it holds |
|---|---|
| `.devin/rules/people.yaml` | the roster: people, their gate roles, primary and secondary hats, hint keywords |
| `.devin/rules/role-routing.yaml` | per-role defaults: dashboard lens, skills, playbooks, systems, output shape, action class |

Read both before answering. Never answer from memory of a previous session — the roster changes.

## HARD RULES

- A role never grants or denies permission. Permission comes from Devin Cloud roles, Bitbucket
  branch protection, secret scoping and `.devin/rules/approval-gates.yaml`. The exception is the
  `access:` section of `people.yaml` (which roles may change which folders), which the write guard
  enforces — this skill only records who is asking. If a request needs
  authority the requester does not have, say who does — do not silently proceed, and do not refuse
  on the basis of the roster either.
- Only ever select a hat the person already holds in the roster. Hint keywords choose between
  someone's own hats; they never invent one.
- Say which hat is being used, once, in a single short line. Do not open with a paragraph about
  identity when someone asked a question — answer the question in the same reply.
- "su - <name>" or "act as <name>" (answer as that roster person, with their role, lens and What I do list, until "as me") works only when the requester's own `jira_user` is in `act_as.allowed` of `.devin/rules/sdlc-profile.json`. For anyone else reply "That isn't available." and carry on as them. Never list it in /help, menus or tips.
- Never write the roster from this skill. Roster changes go through a pull request (`/roster-check`).

## STEP 1 — Resolve the person

In this order, stopping at the first match:

1. `devin_user_id` against the requester's Devin Cloud user id.
2. `email` against the requester's chat identity email (case-insensitive).
3. `jira_user` against an explicitly supplied Jira username.
4. `email` against the git author email of the current checkout
   (`git config user.email`), then its local part against roster emails.
5. `name` against a supplied name fragment — only when exactly one person matches.

Ambiguous or no match → go to STEP 5.

When the match came from the chat identity (1 or 2), record it for the write guard, which cannot
see who is chatting and otherwise falls back to the git author (a service account in Devin Cloud):

```bash
python3 sdlc/framework/tools/access_guard.py whoami --set <roster email>
```

Only ever record the person the chat identity matched — never a name the requester asks you to use.
Set `SDLC_OWNER` only to that same person. The guard refuses a `SDLC_OWNER` that names someone else
unless the recorded requester holds a lead role (`su - <name>`).

When the match came from the email (2) and that roster entry has no `devin_user_id`, the monthly Team Insights
run fills it from the same pairing (`team_insights.py link-ids`); this skill still does not write the roster.

## STEP 2 — Choose the hat for *this* request

Follow `selection.precedence` in `.devin/rules/role-routing.yaml`:

1. **Explicit** — the requester named the hat in the session ("I'm wearing the QA lead hat today",
   `/identify-requester qa_lead`). This always wins, including a hat the roster does not list; note
   in one clause that the roster does not show it and offer `/roster-check` at the end.
2. **Invoked** — the request came in through a skill or playbook that belongs to exactly one role
   in `default_skills` / `default_playbooks`. Use that role.
3. **Hints** — a `role_hints` keyword for one of *this person's* hats appears in the request.
4. **Primary** — otherwise `primary_role`.
5. **Ask** — two or more held hats match equally *and* their `action_class` differs: ask which one
   applies, offering just those hats as options. Equal hats with the same action class: take the
   primary and mention the other in the same line.

Map legacy role names through `role_aliases` (for example `test_lead` → `qa_lead`) so a roster that
still carries gate-role names routes correctly.

## STEP 3 — Apply the role's defaults

From the role entry:

- `action_class` → how far this session may go by default (`action_classes` in the same file).
  When held hats disagree, take the most restrictive until told otherwise.
- `dashboard_lens` → the lens to pass when the requester wants `/dashboard`.
- `default_skills` / `default_playbooks` → what to suggest, and what to reach for first when the
  request matches one of them. Suggest at most three.
- `output` → the shape of the answer (a test matrix for a QA lead, a diff plus screenshots for a UI
  developer, business value and scope for a product owner). Shape the reply accordingly.
- `systems` → where to look for evidence before answering.

## STEP 4 — Open the session

One line, then the actual work:

```
Resource 3 — treating this as delivery lead work (advisory). Say so if you have a different hat on.
```

If the requester asked a question, answer it in the same reply. After the answer, list up to two of their Scrum Master reminders as questions
(`python3 sdlc/framework/tools/sm_reminders.py for --person "<roster name>"`); an answer is put on the
ticket with `sm_reminders.py answer ... --write` only after they type "approved". If they only said hello, add the
three most useful commands for that role and stop.

Then, for anyone matched on the roster, first run
`python3 sdlc/framework/tools/time_off.py due --person "<roster name>"`. When it says `due`, end the first
reply with its time-off question instead of the ice-breaker: "One quick question, asked once a week: <question>".
A no is recorded with `record --none`; a yes brings its `follow_ups` one or two at a time, then the planner row
(`record --from ... --to ... --stories-to ... --questions-to ... --approvals-to ... [--hold]`) and, with --hold,
the Backlog hold blocks from `time_off.py holds`, shown first and written only after "approved".
Otherwise, end that first reply with one short ice-breaker from
`/learn-more` (`python3 sdlc/framework/tools/learn_more.py next --person "<roster name>" --role <hat> --jira`),
preferably about the story they are working on:
"One quick question while I'm here, about your work: <question> (say skip if now isn't a good time)."
Ask it once per session, never before their own request is answered, and not at all in scheduled or
automated sessions. When they answer, follow `/learn-more`.

Before that question, run `python3 sdlc/framework/tools/team_insights.py teach next --person "<roster name>"`.
When it says `due`, add one short lesson from their learning plan, as `/team-insights` describes under "Teaching the
learning list".

## STEP 5 — Nobody matched

1. Continue as a guest, behaving as `read_only` (`selection.unknown_person`).
2. Say once, at the start of the first reply:
   "I am continuing with you as a guest. You can do all read-only lookups; for more than that, talk to the solution lead."
3. Answer the request with read-only work only. Do not ask which role applies and do not offer a
   roster pull request.

## STEP 6 — When the requester corrects the hat

Switch immediately, acknowledge in a clause, carry on. Behaviour changes; permissions do not. If the
correction is a lasting one ("I'm an API developer now, not UI"), offer the roster pull request.

## Worked examples

| Request | Resolution |
|---|---|
| "what's blocking the sprint?" from Resource 3 | roster match on `devin_user_id` → no hint keyword → `primary_role: lead` → po_office lens, status summary then decisions |
| "review this PR" from Resource 3 | `role_hints.reviewer` matches "review" → reviewer hat → findings by severity |
| "can you plan the changes for ACME-1234?" from a `tech_lead` | `tech_lead` → `solution_lead` → `/plan` is in its `default_skills` → routing map, code_pr |
| "I'm testing this today" from Resource 24 | `role_hints.qa_staff` matches → qa_staff hat, test cases and defects |
| Anyone not in the roster | guest: the one-line guest notice, then a read_only answer; no role question, no roster PR |

## Related

- `/dashboard [--lens <lens>]` — the role's landing surface
- `/roster-check` — drift report and roster pull request
- `/help` — the capability menu; `/catalogue` for the full inventory
