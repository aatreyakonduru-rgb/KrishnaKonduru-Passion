---
name: acme-auto-story
description: >
  Automate a Acme Claims Jira story, or a described piece of work with no ticket, end to end in the Acme Claims
  automation repo (ACME/claims-qa): read the story or the description,
  pre-fill the automation template's questions from the code, the running app and Snowflake, stop at
  Gate 1 for the tester, then write the feature, steps, page objects and queries, run them on this
  machine, triage failures and report an AC traceability matrix. Nothing is committed before "push".
  Invoke with: /acme-auto-story <JIRA_KEY | "what to automate"> base=<branch> [processes=<1-4>]  e.g. /acme-auto-story ACME-20106 base=Test_Bamboo
argument-hint: "<JIRA_KEY | \"what to automate\"> base=<branch> [processes=<1-4>]"
visibility: internal
triggers:
  - user
  - model
invocations:
  - /acme-auto-story
  - "!auto_story"
  - automate this story
allowed-tools:
  - bash
  - read
  - edit
---

# /acme-auto-story — a Jira story to passing automation

Argus "Automate this story" button and the `!auto_story` playbook run this. Repo facts are in the
"claims-qa (Acme Claims automation) - repo map, branches, environments" and "claims-qa screen map" knowledge notes.
The standard is `automation/claims/ACME_UI_SELENIUM_BEHAVE_TEMPLATE.md` in this repository (v2.0), with the
Devin Cloud notes in `automation/claims/README.md`; read both before planning.

## Progress lines

Argus Automation screen and the run page show the eight steps (Setup, Scan & plan, Gate 1,
Write, Run, Triage, Coverage & AC matrix, Push & PR) from these lines. Print each on its own line in a
chat message as the step starts and ends, with `started`, `waiting for you`, `done` or `failed` after the dash:

- `[SDLC] step scan — started` at STEP 1 and `[SDLC] step scan — done` when the template answers are ready.
- `[SDLC] step gate1 — waiting for you` in the Gate 1 message; `[SDLC] step gate1 — done` on "yes".
- `[SDLC] step write — started` / `— done` around STEP 4.
- STEP 5 prints the `run` and `triage` lines through `/acme-auto-run` and `/acme-auto-fix`.
- `[SDLC] step report — started` / `— done` around STEP 6.
- `[SDLC] step push — waiting for you` at the end of the report; `[SDLC] step push — done: <PR link>` after STEP 7.
- When setup runs inside this session it prints the `setup` lines.

## Input

- `<JIRA_KEY>`: the story, or its automation sub-task (then work from the parent story's ACs).
- Or, when there is no ticket, `"<what to automate>"` in quotes (for example `"Contract screen – bulk upload
  negative cases"`), optionally followed by an `Acceptance criteria:` block, one per line. This is a
  no-ticket run; the differences are marked "No ticket" below.
- `base=<branch>`: the base branch the tester picked in Argus's base-branch list
  (`automation.base_branches` in `.devin/rules/sdlc-profile.json`, or their own `ACME_Automation_<domain ID>`).
  When it is missing, ask once in the Gate 1 message which one to use. Never pick one silently.
- The tester's domain ID: the session's requesting user, else the relay `SELECT CURRENT_USER()`.

## STEP 1 — Story and environment

Read the story with the Jira service account (summary, description, acceptance criteria, linked pages,
sub-tasks). Number the ACs as written. If the story has no acceptance criteria, say so in Gate 1; do not
invent them. Run `/acme-auto-setup base=<branch>` if this session is not set up.

No ticket: there is no Jira read. Number the acceptance criteria given; if none were given, draft numbered
checks from the description, the screen in the local app, the existing feature files and the app code,
each tagged [A], for the tester to confirm or correct at Gate 1. Name the work `AUTO-<short-slug>` from
the description and use that wherever `<JIRA_KEY>` appears below.

Branch: `feature/<JIRA_KEY>-<short-slug>` (no ticket: `feature/AUTO-<short-slug>`) from the latest `origin/<base>`. If a story branch is already
checked out, ask in Gate 1 whether to keep it (merging `origin/<base>` into it) or start a new one.

## STEP 2 — Scan and pre-fill the template

Search `features/FeatureFiles/**`, `features/steps`, `features/Pages/*_Page.py`,
`features/databaseQueries`, `TestData` for the screen and tags. Open the screen in the local app and read
locators from the DOM. Confirm tables and columns with read-only Snowflake MCP queries. Read the SDLC app
code behind each AC.

Answer each of the template's clarification questions yourself, with the source:

| # | Question | Where the answer comes from |
|---|---|---|
| Q0 | Files to create / change | the scan |
| Q1 | Feature area | the screen map |
| Q2 | Test scope | the ACs |
| Q3 | Scenario or Scenario Outline | the ACs' data sets |
| Q4 | Steps to reuse | `features/steps` (file and line) |
| Q5 | Environment | local app in Devin Cloud; SIT only through Bamboo |
| Q6 | Test data source | `TestData/*.json` or a Snowflake pull |
| Q7 | Snowflake validation | MCP queries (schema-qualified) |
| Q8 | Approval workflow | the approver steps and page objects |
| Q9, Q15 | Tag and TestRunner tag | next free number in the area |
| Q10 | Locators for new elements | the DOM of the local app |
| Q11 | Grid/table checks | the DOM |
| Q12 | Bulk upload | the upload code and template |
| Q13 | Export/download | the DOM |
| Q14 | Negative and edge cases | the front-end messages |
| Q16 | Reports and screenshots | default: all reports, screenshot on failure |

Tag every answer [E] evidence (with source), [A] assumption or [?] don't know.

## STEP 3 — Gate 1 (the only question before code)

Post: branch, base, the AC → scenario table (scenario, tag, steps reused / new, locators, DB check), the
Q0–Q16 answers, files, run command, and the three lists (Evidence, Assumptions, Don't know). Then ask
exactly: "Can I start writing the automation?" Write no code before "yes". On "yes", post the approved
plan as one comment on the Jira story ("Approved automation plan", with the session link). No ticket: the
approved plan stays in the session; nothing goes to Jira.

## STEP 4 — Write

Follow the repo's patterns: feature file + tag, steps calling page objects, locators only in
`features/Pages`, SQL only in `features/databaseQueries/*.txt`, data in `TestData`, Selenium calls through
`functionalComponent/CommonFunctions.py`. Reuse steps. Keep the change to the story. Do not commit.

## STEP 5 — Run and triage

`/acme-auto-run <story tag> processes=<n>`, then `/acme-auto-fix` for each failure. Rerun until every
scenario passes or has a drafted defect.

## STEP 6 — Report

Verdict; AC traceability matrix (AC, scenario, Pass / Fail + defect draft / Not tested, proof); the
template's coverage checklist and summary table; diff (`git diff origin/<base> > <JIRA_KEY>.patch`);
run command and result; drafted defects; what could not run here. Add the Jira label `devin_implemented`
(no ticket: skip the label).
Print `[SDLC] skill acme-auto-story — finished` last.

## STEP 7 — On "push"

Commit only the story's files with trailers `Pushed-by: <Full name> (<AD ID>)` and
`Work-ID: <JIRA_KEY>` (no ticket: `Work-ID: none`), push the branch, and open the PR into `<base>`
following the "SDLC PRs: show who pushed + ask for reviewers" knowledge note. Then post one Jira comment:
summary, AC checklist, PR link, run result, drafted defects, what was not tested, "Pushed by", reviewers.
No ticket: put that summary in the PR description instead of a Jira comment.

## Never

- Commit or push before "push"; merge; rebase or force-push; branch from or into `master`.
- Guess a locator, table or column. Change a test to hide an app bug.
- Commit local-run helpers, run artifacts or credentials.
- Create Jira defects or tickets unasked, or change any Jira field other than the label and the two comments.
