---
name: jira-hygiene
description: >
  The Acme Claims team's Jira tickets that do not yet follow the Jira rule book: epics, recent stories,
  defects and sub-tasks run through the checks in .devin/rules/jira-ticket-standards.yaml plus the
  rule-book additions (epic owner, epic source older than 90 days, sub-task phase prefix, sprint
  carry-over, who-asked label on Approval/Question sub-tasks), grouped by check with the ticket, assignee and what is missing.
  One self-contained page plus a Markdown copy. The same view is the "Jira hygiene" tab on the
  Tech Lead and PO office dashboards. Reading only. Say "/jira-hygiene".
argument-hint: "[cache]"
visibility: internal
triggers:
  - user
  - model
invocations:
  - /jira-hygiene
  - which tickets do not follow the jira standard
  - jira ticket hygiene
  - tickets missing acceptance criteria or labels
allowed-tools:
  - read
  - grep
  - glob
  - exec
---

# /jira-hygiene — tickets that do not yet follow the Jira rule book

The roadmap, the dashboards, approvals, questions and release notes are all read from Jira. They
are only as good as the ticket fields they read. This skill lists the tickets where a field the
tools depend on is missing or in the wrong shape, grouped by check, so the fix is a quick edit in
Jira rather than a hunt.

Tone matters. Most of these patterns were normal practice before the standard existed. The page
says so, and when you summarise it, talk about tickets and checks, not people. No per-person
league table.

## What it reads

- **Epics:** every epic of IT Team Acme-Claims-Web.
- **Stories, defects, bugs and tasks:** the team's, created in the last 120 days.
- **Sub-tasks:** the team's, created in the last 60 days.

## What it checks

From `.devin/rules/jira-ticket-standards.yaml` (`conformance_checks`): placeholder, empty,
unnumbered or vague acceptance criteria; missing Epic Link, story points or Issue Priority;
phase suffix missing or not written exactly `- DEV` / `- SIT` / `- UAT`; SIT/UAT story with no
link back to the earlier phase; hours logged on the story instead of its sub-tasks; missing
`AI-Used` / `AI-NA` label; label spelled in the wrong case; sub-task done with an estimate but no
hours.

From the rule book: epic with no owner, a bare-phrase epic description, a phase/sprint/year in an
epic title, a story carried through three or more sprints, a sub-task title without a
`DEV-` / `SIT-` / `UAT-` prefix, and an Approval/Question sub-task with no `requested-by-` /
`asked-by-` label, and an open TennCare SIT/UAT defect (PCMH, THL, EoC) whose title is not
`SIT-TC-PCMH: …` / `SIT-TC-THL: …` / `SIT-TC-EoC: <Episode> - …` (or `UAT-TC-…`) — the format the
TennCare Scrum Masters asked for on 8 Oct 2026 (`DEFECT_TITLE_PREFIX`). The rule book itself is
`docs/knowledge-base/JIRA-DERIVED/JIRA-HYGIENE-RULEBOOK.html` (Markdown copy beside
it). The list of checks, their severity and the rule they belong to is `CHECKS` in
`sdlc/framework/tools/jira_hygiene.py`; add a check there, not in a dashboard.

A high-severity finding turns the dashboard tab red; anything else amber; nothing, green.

## Run it

```bash
python3 sdlc/framework/tools/jira_hygiene.py
```

- **Live mode** needs `$ACME_JIRA_TOKEN`. It uses bearer auth and checks `/rest/api/2/myself`
  once. On a 401 or 403 it stops and does not retry; report the token problem instead of trying
  again.
- **Offline mode** (`cache` argument) uses sample data:
  `--cache sdlc/framework/tools/fixtures/jira-hygiene-demo.json`.

It writes two files to the git-ignored `sdlc/framework/context/dashboard/` folder:

- `JIRA-HYGIENE.html`: one page in the Acme Claims artifact-kit look — four headline counts, a by-check
  table, then one expandable table per check with a filter box
- `JIRA-HYGIENE.md`: the same content as tables

`--out-html` and `--out-md` change the paths. Attach the HTML to your reply. In the text, give
the per-check counts the tool prints and the three checks with the most tickets. Don't commit
either file: they are a snapshot of live Jira and go stale within days.

## When reporting

- **Evidence:** every row is a field value read from Jira at the time of the run; the ticket link
  shows it.
- **Assumption:** the heuristics — "unnumbered" means fewer than two numbered or bulleted lines,
  "thin description" means under twelve words, "vague" is a short phrase list. Say so if a row is
  disputed, and fix the ticket or the rule, not the report.
- **Don't know:** whether a story *should* have had a sibling link or an epic. The check says the
  link is absent, not that the work was wrong.
- Nothing is written to Jira. The fix is always an edit to the ticket; the row disappears on the
  next run.
