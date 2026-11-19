---
name: status-report
description: 'Monthly program/area status report from Jira, read-only: runs one of the team''s report prompts in REPORTS/status-reports/prompts/ and writes the HTML report next to the earlier ones.'
argument-hint: '<area, e.g. ProgramB | ProgramA | ProgramC | CHF_Maternity | Contract_PG | EOC | CareBridge | TennCare_PCMH_THL | AWS_Automation | Amin_Report> [--release <fix version>]'
allowed-tools:
- read
- grep
- glob
- write
- mcp__acme-jira__search_issues
- mcp__acme-jira__get_issue
visibility: internal
triggers:
- user
- model
---

# Skill: Status report

Builds one area's status report from live Jira data, using the team's own report prompt for that
area. The prompts were written by Resource 3 for director- and area-level readers.

## Read-only

Never create, update, transition or comment on a Jira issue, sprint or fix version. Only search
and read. Use the Jira tools above; without them, call `https://jira.acme.example` with the
team's Jira service account (`ACME_JIRA_TOKEN`, bearer token from the org secret of that
name). If the secret is missing or its note starts with `PLACEHOLDER`, say
`SKIP: Jira — credential not yet provisioned` and stop; don't ask for a password or use anyone
else's credentials.

## Steps

1. Find the prompt: `docs/knowledge-base/REPORTS/status-reports/prompts/<area>_Prompt.md`.
   The folder's `README.md` lists every prompt and its audience. If the area doesn't match a
   file, list the files and ask which one.
2. Follow the prompt's sections, epics and JQL exactly. Where it says "Bob" or "IBM Bob", that is
   whoever runs it; the instructions are the same.
3. Every number in the report comes from a Jira query you ran. Put the JQL for each section in an
   HTML comment above it. A value Jira doesn't hold (an owner, a target date) is shown as "not in
   Jira" and listed at the end, not filled in.
4. Write the HTML to
   `docs/knowledge-base/REPORTS/status-reports/<area>_<release>_<MMDDYY>.html`,
   the same naming as the earlier reports. Don't overwrite an earlier report; the folder is on the
   keep list.
   Build the page with the Acme Claims page shell, `render_page` in
   `sdlc/framework/tools/artifact_kit` (purple header, light and dark, print), with the
   report body inside `<div class="sr">` as in the earlier reports. Every ticket key is a Jira link
- An older report with its own look can be moved onto the shared look with `python3 sdlc/framework/tools/status_report_page.py <report.html>`.
   (`https://jira.acme.example/browse/<key>`, class `key-link`) that doesn't wrap.
5. Tell the user the file, the date the data was pulled, and anything marked "not in Jira".
