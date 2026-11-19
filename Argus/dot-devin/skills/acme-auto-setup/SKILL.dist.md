---
name: acme-auto-setup
description: >
  Get a Devin Cloud session ready to write and run Acme Claims automation (ACME/claims-qa, Python Behave +
  Selenium + Snowflake checks) against the SDLC app running on the same machine: clone claims-qa, check out
  the base branch the tester picked, build the venv, start the app with Snowflake through the MCP relay,
  and pass the smoke scenario. Nothing is committed.
  Invoke with: /acme-auto-setup [base=<branch>]  e.g. /acme-auto-setup base=Test_Bamboo
argument-hint: "[base=<branch>]"
visibility: internal
triggers:
  - user
  - model
invocations:
  - /acme-auto-setup
  - "!auto_setup"
  - set up acme automation
allowed-tools:
  - bash
  - read
---

# /acme-auto-setup — ready to write and run Acme Claims automation

Used by the Acme Claims Automation playbooks (`!auto_setup`, and the setup step of `!auto_story`, `!auto_run`,
`!auto_fix`) and by the Automation screen of Argus. The repo map, branches and environments are
in the "claims-qa (Acme Claims automation) - repo map, branches, environments" knowledge note; settings are under
`automation` in `.devin/rules/sdlc-profile.json`.

## Progress lines

Argus Automation screen and the run page show the eight steps (Setup, Scan & plan, Gate 1,
Write, Run, Triage, Coverage & AC matrix, Push & PR) from these lines. Print each on its own line in a
chat message as the step starts and ends, with `started`, `waiting for you`, `done` or `failed` after the dash:

- `[SDLC] step setup — started` before STEP 1; `[SDLC] step setup — done` after the smoke test passes,
  `[SDLC] step setup — failed: <why>` if it does not.

## Input

- `base=<branch>`: the base branch the tester picked in Argus (one of `automation.base_branches`,
  or their own `ACME_Automation_<domain ID>`). When it is missing, ask once which of
  `automation.base_branches` to use. Never pick one silently.
- The tester's domain ID comes from the session's requesting user, else the relay
  `SELECT CURRENT_USER()`. Never ask for it and never use someone else's.

## STEP 1 — Repo and branch

```bash
mkdir -p ~/repos && cd ~/repos
[ -d claims-qa/.git ] || git -c http.sslVerify=false clone https://git.acme.example/ACME/claims-qa.git claims-qa
cd claims-qa && git -c http.sslVerify=false fetch origin
git checkout <base> && git pull --ff-only origin <base>
```

- Do not check out or commit to `master` (stale).
- If the tester's own branch `ACME_Automation_<domain ID>` exists on origin, say how far it is behind
  `<base>` (`git rev-list --count <tester-branch>..origin/<base>`); do not merge without asking.

## STEP 2 — Python environment

```bash
python3.12 -m venv ~/claims-qa_venv
~/claims-qa_venv/bin/pip install -r <(git show origin/Test_Bamboo:requirements.txt) chromedriver-py
```

Install from Artifactory (the VM's pip.conf already points there). If `requirements.txt` on `<base>` has
its lines commented out, use the Test_Bamboo copy as above and say so. Link the `chromedriver-py`
binary into `~/claims-qa_venv/bin/chromedriver`.

## STEP 3 — The SDLC app on this machine

Start api and web with the `sdlc-local-run` skill: frontend `http://localhost:3100/acme/`, no
login, Snowflake D01 through the MCP relay. Keep the relay running for the whole session; a message from
the tester cancels the running relay call, so restart it after each message.

No claims-qa branch carries local-run support yet, so make these four working-tree changes, never commit
them, and list them in the report:

1. `features/environment.py` `before_scenario`: when `ACME_ENV=LOCAL`, open
   `ACME_LOCAL_URL` (default `http://localhost:3100/acme/`) and return before the Okta login.
2. `functionalComponent/CommonFunctions.py` `get_data_from_snowflake`: when `ACME_DB_MODE=mcp`, write
   `{id, sql}` to `~/sdlc_mcp_bridge/req/<id>.json` with bare `FROM`/`JOIN` tables prefixed by
   `ACME_MCP_SCHEMA` (default `DEV01_CLAIMS.CLAIMS_UI_DATA`), wait for `~/sdlc_mcp_bridge/res/<id>.json` and
   build the DataFrame from `result_set` (`rowType` names, `data` rows). The `sdlc-local-run` relay
   answers these files.
3. `CommonFunctions.upload_the_downloaded_file`: use `os.path.normpath(filepath)`; the backslash path
   breaks uploads on Linux.
4. `features/Pages/ACME_Finance_Configuration_Page.py`: tile locators `contains(@href,'acme/...')`; the
   local app writes full URLs into the tile links.

Run behave with `PATH=$HOME/claims-qa_venv/bin:$PATH` so Selenium finds `chromedriver`. With these, `@Local`
(bulk upload, download) scenarios run on this machine too.

## STEP 4 — Smoke test

```bash
cd ~/repos/claims-qa
PATH=$HOME/claims-qa_venv/bin:$PATH ACME_ENV=LOCAL ACME_DB_MODE=mcp HEADLESS=true ~/claims-qa_venv/bin/python -m behave features --dry-run --tags @ACME_Parallel_Execution_01 -f plain
PATH=$HOME/claims-qa_venv/bin:$PATH ACME_ENV=LOCAL ACME_DB_MODE=mcp HEADLESS=true ~/claims-qa_venv/bin/python -m behave features --tags @ACME_Parallel_Execution_01
git checkout -- pretty.output scenario_execution_history.json 2>/dev/null || true
```

## Report

One short block: base branch and commit, the tester's branch state, app URL, which helpers were copied,
smoke result (pass/fail with the failing step). Print `[SDLC] skill acme-auto-setup — finished` last.

## Never

- Commit, push, or check out `master`.
- Print or change credentials (`PropertiesFiles/DatabaseConfig.properties`, `Utils/GCP_SF_Connection.py`
  hold hardcoded passwords: never echo them).
