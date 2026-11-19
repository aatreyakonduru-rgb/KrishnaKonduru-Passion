# Playbook: Identify Requester — Role-Aware Session Routing

**Playbook ID:** PB-33  
**Paste into:** Devin Cloud → Settings → Playbooks → New Playbook  
**CLI equivalent:** `/identify-requester` skill (`.devin/skills/identify-requester/SKILL.md`)  
**When to use:** As the default opener for any Acme Claims session with a person behind it — it works out who is asking, which of their hats applies to the request, and routes the session to that role's lens, skills and output shape.

---

## Title
```
Acme Claims: Identify Requester — Role-Aware Session Routing
```

## Description
```
Resolves who is asking from their Devin Cloud identity, email, Jira username
or git author, picks the right hat for this particular request (people wear
several), and applies that role's defaults: dashboard lens, first-choice
skills, the systems to check, and the shape the answer should take. Roles are
behavioural routing only — permissions stay with Devin Cloud roles, Bitbucket
branch protection and the approval gates.
```

## Playbook Body

---

You are opening a Acme Claims session. Before planning any work, find out who is asking and which of their
delivery roles applies to this request.

Read both configuration files first — never answer from memory of another session:

```
Roster:  .devin/rules/people.yaml
Routing: .devin/rules/role-routing.yaml
```

---

## STEP 1 — Resolve the person

Stop at the first match:

1. `devin_user_id` against the requester's Devin Cloud user id
2. `email` against the chat identity email
3. `jira_user`, when a Jira username was given
4. the git author email of the checkout (`git config user.email`)
5. a name fragment, only when exactly one person matches

No match, or more than one → **STEP 5**.

---

## STEP 2 — Pick the hat for this request

Follow `selection.precedence` in `role-routing.yaml`:

| Order | Signal |
|---|---|
| 1 | The requester said which hat ("I'm the QA lead today") — always wins |
| 2 | The invoked skill or playbook belongs to exactly one role |
| 3 | A `role_hints` keyword for one of **this person's** hats appears in the request |
| 4 | `primary_role` |
| 5 | Two held hats match equally with different `action_class` → ask which |

Legacy role names (`tech_lead`, `test_lead`, `po`, …) map through `role_aliases`.

---

## STEP 3 — Apply the defaults

From the role entry: `action_class` (how far this session may go), `dashboard_lens`,
`default_skills` and `default_playbooks` (what to reach for, at most three suggested),
`systems` (where to look for evidence), `output` (the shape of the answer).

When held hats disagree on `action_class`, take the most restrictive until told otherwise.

---

## STEP 4 — Open with one line, then do the work

```
<Name> — treating this as <role label> work (<action_class>). Say so if you have a different hat on.
```

Then answer the actual request, shaped by `output`. A QA lead gets a test matrix; a UI developer gets
a diff and screenshots; a product owner gets business value and scope; a manager gets status then
risks. If the requester only said hello, offer the three most useful commands for that role.

---

## STEP 5 — Nobody matched

Answer the request anyway, behaving as `read_only`. Ask **one** question — which role applies, offering
the role labels — and close by offering a roster pull request through `/roster-check --add`.

---

## HARD RULES

- A role never grants or denies permission. Authority comes from Devin Cloud roles, Bitbucket branch
  protection, secret scoping and `.devin/rules/approval-gates.yaml`. If the request needs authority the
  requester lacks, name who has it rather than refusing.
- Only ever select a hat the person already holds. Hint keywords choose between someone's own hats.
- Announce the hat once, in one line. Never open with a paragraph about identity.
- Never edit the roster from this playbook — that is `/roster-check`, and it goes through review.

---

## Human gate

None. This playbook only routes; every gate belongs to the stage the session goes on to run.
