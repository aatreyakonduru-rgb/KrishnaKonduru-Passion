---
name: gate-timeout-check
description: Daily sweep for approval gates that have waited longer than their timeout_hours in .devin/rules/approval-gates.yaml. Escalates each overdue gate once per day to the roster owner, records a gate_escalated metric, and (with --live) comments on the open Jira approval sub-task. Also asks Jira for open approval sub-tasks, so it works on a fresh Devin Cloud VM with no local session state. Run by the "Acme Claims gate timeout escalation" automation; say "/gate-timeout-check" to run it by hand.
argument-hint: "[--live] [--jira] [--hours-grace N]"
visibility: internal
triggers:
  - user
  - model
invocations:
  - /gate-timeout-check
  - which gates are overdue
  - escalate overdue gates
allowed-tools:
  - read
  - bash
---

# /gate-timeout-check — nobody should wait on a gate in silence

Every gate in `.devin/rules/approval-gates.yaml` has a `timeout_hours`. This skill finds gates that
have been `pending` longer than that and makes sure someone hears about it.

## STEP 1 — Run the sweep

```bash
python3 sdlc/framework/tools/gate_timeouts.py --jira            # dry run: report only
python3 sdlc/framework/tools/gate_timeouts.py --jira --live     # post the Jira comments
```

- Without `--live` nothing leaves the machine; the Jira requests are printed as DRY-RUN.
- `--jira` also searches Jira (`project = ACME AND labels = Approval AND resolution = Unresolved`)
  so gates raised from other people's sessions are covered even when their local session home
  (`~/.sdlc/sessions`) is not on this machine.
- Exit `0` = nothing overdue, `1` = something was escalated, `2` = error.
- Jira uses `ACME_JIRA_TOKEN` (bearer). On 401/403 stop and report; do not retry.

## STEP 2 — What an escalation is

For each overdue gate, once per calendar day:

1. the gate record (or Jira sub-task) is stamped `escalated_at` / label `gate-timeout-escalated-<date>`;
2. `gate_escalated` is written to the owner's `metrics.jsonl` (shows on `/dashboard` → Pipeline health);
3. with `--live`, a comment goes on the approval sub-task naming the gate, wait time, required role,
   the named approvers and the roster owner (`people.yaml` → `owner.primary`).

Nothing is approved, rejected or skipped on anyone's behalf. The gate stays open until a person
replies `approved`, `rejected` or `needs revision`.

## STEP 3 — Report

Paste the tool's summary. If gates are overdue, list requirement, story, gate, hours waited and who
it went to. Snowflake and Artifactory are not involved; this runs in Devin Cloud as-is.
