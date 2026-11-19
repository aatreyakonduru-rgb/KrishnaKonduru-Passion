---
name: acme-auto-fix
description: >
  Find why Acme Claims automation scenarios failed (ACME/claims-qa) and fix the test when the test is wrong,
  or draft a defect when the application is wrong. Every failure gets a cause with evidence (error,
  screenshot, DOM or query result) and a rerun result. No Jira defect is created and nothing is
  committed unless the tester asks.
  Invoke with: /acme-auto-fix [tag expression | Bamboo log or report path]
argument-hint: "[tag expression | log or report path]"
visibility: internal
triggers:
  - user
  - model
invocations:
  - /acme-auto-fix
  - "!auto_fix"
  - why did the automation fail
allowed-tools:
  - bash
  - read
  - edit
---

# /acme-auto-fix — triage Acme Claims automation failures

Used by `!auto_fix`, by `/acme-auto-story` and by the Triage button on Argus Automation screen.

## Progress lines

Argus Automation screen and the run page show the eight steps (Setup, Scan & plan, Gate 1,
Write, Run, Triage, Coverage & AC matrix, Push & PR) from these lines. Print each on its own line in a
chat message as the step starts and ends, with `started`, `waiting for you`, `done` or `failed` after the dash:

- `[SDLC] step triage — started` before STEP 1; `[SDLC] step triage — done` when every failure has a cause
  and a rerun result.

## Input

Nothing when `/acme-auto-run` ran in this session (use its results). Otherwise the failing tag (run it
first with `/acme-auto-run <tag>`) or a Bamboo log / report path.

## STEP 1 — Collect

For each failed scenario: the failing step, the error and traceback (`logs/`, or
`reports/parallel/<ts>/workers/<id>/console.log`), the screenshot, and the step, page object and query it
uses (`features/steps`, `features/Pages`, `features/databaseQueries`).

## STEP 2 — Find the cause

Check against the live facts, never memory:

- Locator: open the screen in the local app (`http://localhost:3100/acme/`) and read the element from the DOM.
- Data: run the scenario's query read-only through the Snowflake MCP; check the table and columns exist.
- Behaviour: read the SDLC app code behind the screen.
- Timing: is it a wait problem (element present later)? Use the waits in `functionalComponent/CommonFunctions.py`.

Classify each failure: **test defect** (locator, data, wait, wrong step) · **app defect** (the app does
not do what the AC says) · **environment** (relay down, app not started, local-only limit such as
multi-statement saves over MCP). Tag every fact [E] evidence with its source, [A] assumption, [?] don't know.

## STEP 3 — Act

- Test defect: fix it in the repo's patterns (locators only in `features/Pages`, SQL only in
  `features/databaseQueries/*.txt`), then rerun that scenario.
- App defect: leave the scenario as it is and draft the defect (summary, steps, expected, actual,
  evidence, environment). Do not create it in Jira unless the tester asks.
- Environment: fix the environment and rerun, or say what cannot run here.

Never change a test only to hide an application bug.

## Report

A cause table (scenario, class, cause, evidence, action, rerun result), the diff of any test fixes, and
the drafted defects. Revert run artifacts (`pretty.output`, `scenario_execution_history.json`). Print
`[SDLC] skill acme-auto-fix — finished` last.

## Never

- Commit or push before the tester says "push". Create Jira defects unasked. Print credentials.
