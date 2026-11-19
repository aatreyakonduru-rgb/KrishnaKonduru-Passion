---
name: roster-check
description: Check the Acme Claims roster for drift — Jira usernames that no longer exist, inactive accounts, missing emails, people working on Acme Claims who are absent from the roster, roles that are not in the vocabulary, and gate roles nobody can sign — then raise a pull request with the corrections. Use weekly, when someone joins or leaves, and whenever a session discovers that the roster has the wrong role for someone.
argument-hint: "[nothing] | --offline | --add \"<name>, <role>\" | --write"
visibility: internal
triggers:
  - user
  - model
invocations:
  - /roster-check
  - /roster
  - check the roster
  - roster drift
  - add me to the roster
  - my role is wrong
allowed-tools:
  - read
  - glob
  - grep
  - bash
---

# /roster-check — keep the roster honest

The roster (`.devin/rules/people.yaml`) drives who Devin Cloud thinks you are and therefore how
every session behaves. It is only useful while it is accurate, so this skill exists to find drift
and turn it into a reviewable pull request — never a silent edit.

## STEP 0 — Show who is on the roster

Before the drift report, show the current roster so the reader can see who is who: one table per
`primary_role` with name, Jira user, other hats (`secondary_roles`), gate roles (`roles`), sprint time
(`allocation`, or "no sprint work" when `delivery: false`), away cover (`delegate_to`) and whether
`devin_user_id` is set. Say which Confluence page and version it was synced from. In Argus,
Roster check opens this as `/page/roster` (`tools/gen_reference_pages.py`) without starting a session.

## STEP 1 — Run the reconciliation

```bash
python3 sdlc/framework/tools/reconcile_roster.py                 # live Jira
python3 sdlc/framework/tools/reconcile_roster.py --offline       # no Jira access
python3 sdlc/framework/tools/reconcile_roster.py --write         # apply the safe fixes
```

The tool needs `ACME_JIRA_TOKEN` for the live checks. If Jira returns 401 or 403, stop: the
service account is locked or its token needs rotating, and retrying makes it worse
(`.devin/rules/approval-gates.yaml` aside, this is the one place the run may end early). Report that
and fall back to `--offline` so the configuration checks still happen.

It exits `0` when there is no drift and `1` when there is, so a scheduled run can branch on it.

## STEP 2 — Read what it found

| Finding | What to do with it |
|---|---|
| Entries missing a field | add the field; the schema is documented at the top of `people.yaml` |
| Roles not in the vocabulary | either fix the spelling or add the role to `.devin/rules/role-routing.yaml` |
| Hint keywords for hats the person does not hold | drop the hint, or give the person that hat deliberately |
| Routing pointing at something missing | a skill or playbook was renamed; repoint it |
| Entries that cannot be matched | ask the person for their Jira username; never guess between two candidates |
| Gate roles with nobody to sign | a real delivery risk — the gate cannot be signed; escalate to the roster resolver |
| Leavers | confirm with the resolver before removing, and move `delegate_to` off them first |
| Joiners | propose an entry with `primary_role` left as a question for the resolver |
| Likely Jira match for an unresolved entry | record it as a `TODO: confirm <username>` comment; only the person or the resolver turns it into a value |
| Email disagreements | Jira wins for work email |

## STEP 3 — Propose, do not impose

1. `--write` applies only what cannot be wrong: an email Jira holds for a username already in the
   roster, and the `last_reviewed` date.
2. Everything else becomes a proposed edit in the same pull request, each entry commented with why.
3. A discipline that cannot be inferred stays as `developer` with the TODO comment intact. Guessing
   that someone is a UI rather than an API developer is worse than leaving the question open.
4. Open one pull request per run, titled `roster: weekly reconciliation <date>`, and request review
   from the `owner.primary` named in `people.yaml` — the roster resolver — adding the people under
   `owner.backups` as reviewers so the pull request is not blocked while one person is away. Never
   commit to master.

## STEP 4 — `--add` (self-healing at the point of use)

When a session meets someone the roster does not know, or someone says their role is wrong, capture
it here: add or amend the single entry, leave every other entry untouched, and raise the same kind of
pull request. The requester's own statement is enough evidence for `primary_role`; it is not enough
to change `roles`, because those decide who can sign a gate — route that to the roster resolver.

When the requester cannot be identified at all, say who can settle it: the `owner.primary` and
`owner.backups` from `people.yaml`, by name rather than by Jira username.

## HARD RULES

- Never edit `roles` (gate roles) on someone's behalf. That is an authority change and belongs to the
  roster owner, reviewed in a pull request.
- Never remove a person because Jira looks quiet. Only the resolver confirms a leaver.
- Never write anyone's personal data beyond name, work email, Jira username and Devin Cloud user id.
- One Jira pre-flight call per session; no retries after a 401 or 403.

## Related

- `/identify-requester` — uses the roster to route a session
- `sdlc/framework/ROSTER-GOVERNANCE.md` — ownership, cadence and the change process
- `.devin/rules/role-routing.yaml` — the role vocabulary and per-role defaults
