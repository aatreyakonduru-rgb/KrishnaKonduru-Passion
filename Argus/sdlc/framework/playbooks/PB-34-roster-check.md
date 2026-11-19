# Playbook: Roster Check — Weekly Drift Reconciliation

**Playbook ID:** PB-34  
**Paste into:** Devin Cloud → Settings → Playbooks → New Playbook  
**CLI equivalent:** `/roster-check` skill (`.devin/skills/roster-check/SKILL.md`)  
**When to use:** On a weekly schedule, when someone joins or leaves the Acme Claims team, and whenever a session discovers that the roster has the wrong role for someone.

---

## Title
```
Acme Claims: Roster Check — Weekly Drift Reconciliation
```

## Description
```
Compares .devin/rules/people.yaml against Jira and against the routing
configuration: usernames that no longer exist, inactive accounts, missing work
emails, people active on Acme Claims who are absent from the roster, roles outside the
vocabulary, and gate roles nobody can sign. Applies only the fixes that cannot
be wrong, and raises everything else as a pull request for the roster owner to
review. Never commits to master.
```

## Playbook Body

---

You are keeping the Acme Claims roster accurate. The roster decides how every session behaves, so drift is
the main risk to the whole mechanism — and the only acceptable output of this run is a reviewable
pull request, never a silent edit.

---

## STEP 1 — Reconcile

```bash
python3 sdlc/framework/tools/reconcile_roster.py               # live Jira
python3 sdlc/framework/tools/reconcile_roster.py --offline     # configuration only
python3 sdlc/framework/tools/reconcile_roster.py --write       # apply the safe fixes
```

Exit code `0` means no drift — say so and stop, without opening a pull request.

The live checks need `ACME_JIRA_TOKEN`. On 401 or 403 stop immediately, report that the service
account is locked or needs a token rotation, and rerun with `--offline` so the configuration checks
still happen. Never retry the call.

---

## STEP 2 — Turn findings into a proposal

`--write` applies only the unarguable fixes: an email Jira already holds for a username in the roster,
and the `last_reviewed` date. Everything else becomes a proposed edit with a comment saying why:

- **Joiners** — propose an entry, leaving `primary_role` as an open question for the resolver.
- **A likely Jira match for an unresolved entry** — record it as `TODO: confirm <username>`. Only the
  person themselves or the resolver turns a candidate into a value; a wrong identity mapped to a gate
  role is worse than an open question.
- **Leavers** — never remove anyone on Jira's word alone; propose it, and move any `delegate_to`
  pointing at them first.
- **Unresolved people** — ask for the Jira username; never choose between two candidates.
- **Gate roles nobody holds** — call this out at the top of the pull request. It is a delivery risk:
  that gate cannot be signed at all.
- **A discipline that cannot be inferred** — leave `developer` and the TODO comment in place. An
  invented specialism is worse than an open question.

---

## STEP 3 — Raise the pull request

Branch from the default branch, commit `.devin/rules/people.yaml` only, and open a pull request:

```
Title: roster: weekly reconciliation <date>
Body:  the reconciliation report, then the proposed edits, then anything needing a decision
Reviewer: owner.primary from the `owner` block of people.yaml — the roster resolver — plus
           everyone under owner.backups, so one absence does not block the change
```

Never push to master. Never edit the `roles` list (gate roles) on anyone's behalf — that changes who
can sign a gate and belongs to the resolver.

---

## HARD RULES

- One Jira pre-flight call, no retries after 401 or 403.
- No personal data beyond name, work email, Jira username and Devin Cloud user id.
- The pull request is the deliverable. A run that silently changed the roster has failed.

---

## Human gate

The pull request review itself, by the roster owner named in `people.yaml`. See
`sdlc/framework/ROSTER-GOVERNANCE.md` for the ownership and cadence model.
