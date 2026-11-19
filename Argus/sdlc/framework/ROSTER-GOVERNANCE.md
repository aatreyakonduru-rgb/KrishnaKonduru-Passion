# Users, roles and functionality — how the Acme Claims roster works

This page explains how Devin Cloud knows who someone is on the Acme Claims team, how it decides which of
their roles applies to a given request, and who is responsible for keeping that information right.
It is the human-facing companion to three files in the repository, and it is written to be published
into Confluence space **ACMEWIKI** as *Devin Cloud — Users, Roles and Functionality* without editing.

| File | What it holds |
|---|---|
| `.devin/rules/people.yaml` | the roster: people, their gate roles, primary and secondary hats, hint keywords |
| `.devin/rules/role-routing.yaml` | the role vocabulary and each role's defaults — lens, skills, playbooks, output shape |
| `.devin/rules/dashboard-roles.yaml` | which dashboard panels each lens shows |

---

## 1. Why this exists

Devin Cloud's own roles — administrator, member, read-only — describe what a person is permitted to
do in the platform. They say nothing about what that person does for a living. Without a second layer,
a QA lead, an ETL developer and a product owner all start from the same blank prompt and have to
re-explain who they are and what good output looks like, every session. Playbooks written for a role
go unused because nobody knows which ones apply to them.

The roster closes that gap. It is small, readable, reviewed like code, and it changes only the default
behaviour of a session — never anybody's access.

---

## 2. Permission and role are deliberately separate

This is the most important line in the page: **a role in the roster never grants or denies access.**

| Question | Answered by |
|---|---|
| May this person use Devin Cloud, and see which sessions? | Devin Cloud organisation roles |
| May this change land on master? | Bitbucket branch protection and pull request review |
| May this session read that secret? | secret scoping |
| May this stage proceed? | the approval gates in `.devin/rules/approval-gates.yaml` |
| What should a session default to doing, and in what shape? | the roster and `role-routing.yaml` |
| Which folders may this person change through Devin, and may they sign their own code review? | the `access:` section of `people.yaml`, checked by `tools/access_guard.py` — a guard against mistakes, backed by Bitbucket required approvers. Its `roster_signoff` says whose sign-off of the roster page unlocks the guard in each `gates.mode` (dev: owner or backup; enforced: manager or reviewer) |

If the roster is wrong, someone gets an answer shaped for the wrong job. Nothing is exposed, and
nothing is blocked that would otherwise be allowed. That is the point of keeping the two layers apart.

---

## 3. What is in the roster

Each person has:

| Field | Meaning |
|---|---|
| `name`, `email`, `jira_user`, `devin_user_id` | the identifiers a session can match against |
| `roles` | **gate roles.** These decide who can sign an approval gate, so they are a controlled field |
| `primary_role` | the job role used when nothing else indicates otherwise |
| `secondary_roles` | the other hats the person legitimately wears |
| `role_hints` | keywords that pick one of *that person's own* hats for a particular request |
| `delegate_to` | who receives their approvals while they are away |

The role vocabulary itself lives in `role-routing.yaml`: delivery lead, solution lead, architect, UI
developer, API developer, data/ETL developer, developer, reviewer, QA lead, QA engineer, UAT lead, UAT
participant, BSA, BSA lead, product owner, manager, release manager, new joiner. Each one carries its
dashboard lens, the skills and playbooks to reach for first, the systems to check for evidence, and the
shape the answer should take — a test matrix for a QA lead, a diff and screenshots for a UI developer,
business value and scope for a product owner.

---

## 4. People wear several hats

Most senior people hold more than one role, so the hat is chosen per request rather than fixed per
person. In order:

1. **What the person said.** "I'm wearing the QA lead hat today" always wins.
2. **What they invoked.** A skill or playbook that belongs to exactly one role settles it.
3. **What they asked for.** A hint keyword — "review this", "the design options", "retest" — selects
   between hats *they already hold*. A keyword never invents a role.
4. **Their primary role.**
5. **Ask.** If two of their hats fit equally and would behave differently, the session asks rather
   than guessing.

The chosen hat is stated in one line at the start ("treating this as QA lead work") so it can be
corrected in seconds. Correcting it changes behaviour immediately; it changes no permissions. Where
hats disagree on how far a session may go, the most cautious one applies until the person says
otherwise.

---

## 5. Who owns it, and how it stays accurate

Accuracy is the whole risk, so ownership is explicit in the `owner` block at the top of
`people.yaml`.

| | |
|---|---|
| **Owner** | the person named in `owner.primary` — the roster resolver, who settles an unknown or disputed identity |
| **Backups** | everyone listed under `owner.backups`; any one of them can approve a roster change while the owner is unavailable |
| **How it changes** | a pull request against `people.yaml`, reviewed by the owner or a backup. Nobody edits their own entry unaided |
| **Weekly** | `/roster-check` reconciles the roster against Jira and raises a pull request when it finds drift |
| **Every time they open `/dashboard`** | the resolver and the backups see a roster panel listing incomplete entries, unmatched people, unknown roles and gates nobody can sign. It is read-only; the fix is still the pull request |
| **At the point of use** | a session that meets an unknown person, or is told a role is wrong, offers to raise that same pull request for the resolver to settle |
| **Quarterly** | the owner walks the whole file and updates `last_reviewed` |
| **Joining and leaving** | adding or removing a roster entry is a step on the team's onboarding and offboarding checklist |

The weekly check reports usernames that no longer exist, inactive accounts, missing work emails,
people demonstrably working on Acme Claims who are absent from the roster, roles outside the vocabulary,
routing that points at a renamed skill, and — most importantly — **gate roles that nobody can sign**,
which is a delivery risk rather than a documentation one.

Only two kinds of change are ever applied automatically: a work email Jira already holds for a
username already in the roster, and the review date. Everything else waits for a human, including any
guess about someone's discipline. Leaving "developer" with an open question is better than inventing
"UI developer".

An open drift pull request older than two weeks is the signal that this process has stopped working —
treat it the same way as a failing build.

---

## 6. Why Jira is not the source of truth

Jira knows who touches Acme Claims issues, and that is genuinely useful as a cross-check. It cannot be the
source of the roster:

- Acme Claims's assignable-user search returns the whole Jira instance, not the Acme Claims team.
- Project role configuration is not readable by the service account.
- Even where project roles are readable, they distinguish "developer" from "administrator" — never UI
  from API from ETL, or QA lead from QA engineer.

So the direction of the comparison is deliberate: source control holds the roster, and Jira is used to
confirm that the people in it still exist, are still active, and that nobody obviously active on Acme Claims
has been forgotten.

The disciplines themselves — Dev, ETL-Dev, UX, Test Lead, SIT manual, SIT automation — come from the
Acme Claims resource list kept by the delivery manager. That list is what a roster pull request is checked
against, and each person carries the role it gives them as a `# roster:` note next to their entry.

---

## 7. What to do as a team member

| Situation | Do this |
|---|---|
| Devin Cloud assumed the wrong role | say so — it switches immediately; if it is a lasting change, ask for `/roster-check --add` |
| You are new and not in the roster | ask any session for `/roster-check --add`, or ask the owner |
| You want to see your own defaults | `/identify-requester` (also `/whoami`) |
| You want your queues, approvals and branches | `/dashboard` |
| You want to know what your role can run | `/help` for the menu, `/catalogue` for everything |
| Someone left the team | tell the owner; the roster change is part of offboarding |

---

## 8. Publishing this page

Publish into Confluence space **ACMEWIKI** as *Devin Cloud — Users, Roles and Functionality*, and link it
from the Acme Claims team home page. Keep this file as the master copy so the page and the configuration
change together in the same pull request.
