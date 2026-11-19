---
name: acme-auto-run
description: >
  Run Acme Claims automation scenarios (ACME/claims-qa) by tag on the Devin Cloud machine against the local
  SDLC app, one browser or several in parallel (TestRunner.py processes), and report pass/fail per
  scenario with the failing step and screenshots. Run artifacts are reverted, nothing is committed.
  Invoke with: /acme-auto-run <tag expression> [processes=<1-4>] [base=<branch>]  e.g. /acme-auto-run @Contract processes=3
argument-hint: "<tag expression> [processes=<1-4>] [base=<branch>]"
visibility: internal
triggers:
  - user
  - model
invocations:
  - /acme-auto-run
  - "!auto_run"
  - run the acme automation
allowed-tools:
  - bash
  - read
---

# /acme-auto-run — run Acme Claims automation by tag

Used by `!auto_run`, by `/acme-auto-story` and by the Run panel of Argus Automation screen.

## Progress lines

Argus Automation screen and the run page show the eight steps (Setup, Scan & plan, Gate 1,
Write, Run, Triage, Coverage & AC matrix, Push & PR) from these lines. Print each on its own line in a
chat message as the step starts and ends, with `started`, `waiting for you`, `done` or `failed` after the dash:

- `[SDLC] step run — started` before the dry run; `[SDLC] step run — done: <passed>/<total> passed` after the
  run, even when scenarios failed (Triage then shows the failures); `[SDLC] step run — failed: <why>` only when
  the run could not start.

## Input

- A tag expression (`@Contract`, `@ACME_Contract_Configuration_01`, `@ACME_Parallel_Execution`). Required.
- `processes=<n>`: 1 = one browser (`reports/html`); 2 or more = parallel workers, each with its own
  headless Chrome on this machine (`reports/parallel/<timestamp>/`). At most `automation.max_processes`
  in `.devin/rules/sdlc-profile.json` (the machine has 4 CPUs). Default 1.
- `base=<branch>`: only used when setup has not run in this session.

## STEP 1 — Ready?

If `~/repos/claims-qa`, `~/claims-qa_venv` or the app at `http://localhost:3100/acme/` is missing, run
`/acme-auto-setup base=<branch>` first.

## STEP 2 — Dry run

```bash
cd ~/repos/claims-qa
PATH=$HOME/claims-qa_venv/bin:$PATH ACME_ENV=LOCAL ACME_DB_MODE=mcp HEADLESS=true ~/claims-qa_venv/bin/python -m behave features --dry-run --tags <tags> -f plain
```

Stop and list the undefined steps if any.

## STEP 3 — Run

One process:

```bash
PATH=$HOME/claims-qa_venv/bin:$PATH ACME_ENV=LOCAL ACME_DB_MODE=mcp HEADLESS=true ~/claims-qa_venv/bin/python -m behave features --tags <tags>
```

Parallel (no Selenium Grid needed: TestRunner.py starts one worker per process, each driving its own
Chrome on this machine):

```bash
PATH=$HOME/claims-qa_venv/bin:$PATH TAGS="<tags>" PROCESSES=<n> SCHEME=feature HEADLESS=true ACME_ENV=LOCAL ACME_DB_MODE=mcp ~/claims-qa_venv/bin/python TestRunner.py
```

Use `SCHEME=scenario` only for independent scenarios (for example `@ACME_Parallel_Execution`). Leave
`SELENIUM_REMOTE_URL` unset: the app runs on this machine, so remote Grid nodes cannot reach it.
`@Local` scenarios (bulk upload, download) run here.

Keep the MCP relay running during the run.

## STEP 4 — Clean up

```bash
git checkout -- pretty.output scenario_execution_history.json 2>/dev/null || true
git status --short
```

`reports/` and `logs/` stay untracked; never commit them.

## Report

A table: scenario, tag, Pass/Fail, failing step and error line, screenshot path. Then totals, processes
used, duration, and the report folder. If anything failed, offer `/acme-auto-fix`. Print
`[SDLC] skill acme-auto-run — finished` last.

## Never

- Commit or push. Point the run at SIT or a Grid from this skill. Print credentials.
