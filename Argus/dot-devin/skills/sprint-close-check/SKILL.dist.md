---
name: sprint-close-check
description: >
  Before the sprint closes, checks every story and sub-task in the Acme Claims active sprint and lists each
  one that is not ready: sub-tasks still open, no time logged, no AI-Used or AI-NA label (or the wrong
  case), no original estimate, and status not Ready for Approval or done. One row per story or sub-task
  with everything it is missing and who owns it. The same view is the "Sprint close" tab on the Scrum
  Master dashboard. Reading only. Say "/sprint-close-check".
argument-hint: "[cache]"
visibility: internal
triggers:
  - user
  - model
invocations:
  - /sprint-close-check
  - is the sprint ready to close
  - sprint close check
  - which stories are not ready to close
allowed-tools:
  - read
  - grep
  - glob
  - exec
---

# /sprint-close-check — is every story ready for the sprint to close?

Resource 2 (Scrum Master) runs this before closing the sprint. It only reads Jira; nothing is changed.

## What it checks

For each story in the active sprint (`scrum_metrics.close_rows`):

- every sub-task is closed;
- time is logged. Hours go on sub-tasks, never on the story (`jira-ticket-standards.yaml`), so the story
  passes when its sub-tasks have time;
- it carries exactly one of `AI-Used` / `AI-NA`, in that case;
- it has an original estimate;
- its status is Ready for Approval or a done status.

For each of its sub-tasks: hours logged, the AI label, an original estimate, and a Ready for Approval or done status.

Acme Claims has no "Completed" status. Until Resource 2 answers learn-more L-029, any done-category status counts as
completed: Ready For Release, Closed, Approved and Production Validation on stories, and Resolved, Closed and
Abandoned on sub-tasks. The list is `sprint_close` in `.devin/rules/scrum-master-metrics.yaml`.

## Steps

1. Build the Scrum Master dashboard with the requester's name; it reads Jira live with the team service account:

   ```bash
   /usr/bin/python3 sdlc/framework/tools/gen_dashboard.py --user "<requester>" --lens scrum_master -o ~/sprint-close.html
   ```

   Offline, or to try it: add `--cache sdlc/framework/tools/fixtures/<scrum master fixture>.json`.
2. Open the **Sprint close** tab (show the page with the Devin Window preview if the requester wants it).
3. In chat, give the headline first: stories in the sprint, how many are ready to close, how many exceptions.
   Then the exceptions grouped by owner, with the ticket key, its story, and what is missing.
4. If Jira refused the queries, say so; never report the sprint as clean.

Offer, without doing it, the follow-ups the requester may want: a reminder to each owner through the normal
question flow, or a re-run after the fixes. Nothing is written to Jira from this skill.
