---
name: metis-setup
description: First-time Mētis setup for a team - reads every repo connected to the team's Devin org, detects the tech stack and databases from the code and config files, shows them for approval and changes, asks only what the code can't show, checks each connection read only, and writes the settings into <KB>/.metis/ in one PR. Use when someone says "set up Mētis" or when `kb-build` finds no settings.
allowed-tools: [read, write, edit, grep, glob, exec]
triggers:
  - model
---

# Set up Mētis

`$METIS` is the Mētis plugin folder: two levels above this SKILL.md. Follow `$METIS/rules/metis-writes.md`.
Never guess a value: what nobody knows stays empty and becomes a VALIDATE_KB question.
Evidence rule (`$METIS/rules/metis-evidence.md`): every detected value names the file it came from; an unknown stays empty.

## 1. Ask what the code can't show

1. Team repo: clone URL, the branch the KB PR should go to, and the KB folder (for example `docs/kb`).
2. Product name and short name, as the team writes them.
3. People: the KB owner (approves the PR) and who fills each answer role (dev lead, ETL lead, data lead,
   architect, manager, product owner, business analyst, security lead, operations; add any role the team uses).
   These people are also the leads who certify changes once the first KB is locked. Ask: "Who may certify changes to the
   KB?" and put anyone extra under `gate.certifiers`. Tell them that after the first KB, nothing enters it without
   a named lead, and suggest putting `<KB>/.metis/certified.yaml` under CODEOWNERS and running
   `kb_gate.py check <KB>` in CI.
4. Confluence and Jira (optional): spaces or root pages, project keys, and the names of the Devin secrets that
   hold the service-account tokens. The team's Jira boards are found in step 5, not asked for.

## 2. Read every repo and detect the stack

1. The source repos are every repo connected to the team's Devin org, as cloned by the org's environment setup
   into `sources.workspace_root` (for example `/home/ubuntu/repos`). List them; leave out the team repo only if the
   team says so.
2. Copy `$METIS/templates/kb-profile.yaml`, `db-environments.yaml` and `kb-keep.yaml` to `<KB>/.metis/` and set
   `sources.workspace_root`.
3. `python3 $METIS/tools/detect_stack.py detect <KB> --all` then `python3 $METIS/tools/detect_stack.py show <KB>`.
   Detection uses only the rules in `$METIS/templates/stack-rules.yaml` (build files, drivers, connection
   settings, AWS and job files). Every line it shows names the file and line. Secret values are never read
   into the output. A connection setting that is a placeholder (`${DB_URL}`) is raised as a question.

## 3. Show it, take approval, offer changes

Show the person the `show` output as a plain list, grouped by area: repos read; languages and build tools;
frameworks and UIs; databases by type and environment; each database, schema and warehouse setting by
environment; ETL, batch and AWS files; test tools; settings set outside the repos. Then ask:
"Is this right? You can approve it, or tell me what to add or remove."

- Approve as is: `detect_stack.py approve <KB> --by "<their name>"`.
- Changes: write them to `<KB>/.metis/stack-changes.yaml` as
  `{add: [{category, name, repo, engine, env, value, note}], remove: [{category, name, repo, note}]}`, then
  `detect_stack.py approve <KB> --by "<their name>" --changes <KB>/.metis/stack-changes.yaml`. Each change is
  recorded as an answered VALIDATE_KB question with their name, and the approved item cites it.
- This writes `<KB>/.metis/stack.yaml` and `<KB>/context/TECH_STACK.yaml`.

## 4. Databases, schemas and environments

From the approved stack, fill `<KB>/.metis/db-environments.yaml`: for each environment, every database the
stack shows (engine, database name, schemas, warehouse for Snowflake, and the Devin connection the read-only
role uses). Values come from the approved stack or from the person; an empty `schemas` list means every schema
the role can see. Ask which environment is the reference environment (the full database documents are built
from it; every other environment gets a catalogue snapshot and is compared in the drift report). A database
with no Devin connection uses `engine: schema-files` with the repo and the paths of its CREATE TABLE files.

Then fill `app.modules` and `etl.modules` in kb-profile.yaml from the approved stack: one module per repo
folder that has its own build file, named as the person confirms.

## 5. Check each connection (read only) and show a table: source, result, what to do if it failed

- Each repo: `git -C <folder> log -1 --format=%h`.
- Each database in each environment: the read-only identity check for its engine (Snowflake
  `SELECT CURRENT_USER(), CURRENT_ROLE();`, PostgreSQL `SELECT current_user, current_database();`), then list
  its schemas. A database that fails is shown with what is needed and stays in the settings.
- Confluence: one GET of a root page with `Authorization: Bearer $<secret>`; Jira: one GET of `/rest/api/2/myself`.
  Never print the token. On 401/403 stop and say the token needs to be rotated; don't retry.
- Jira boards: for each project key, `python3 $METIS/tools/dash_jira.py <KB> --list-boards <KEY>` lists every board
  of the project the service account can see (id, type, name). Show the list and ask which boards are the team's
  ("these are the boards I found; which ones does the team work on? You can add a board by its link"). A board
  link's `rapidView=` number is its id. Save the chosen ones as `sources.jira.boards: [{id, name}]`. The dashboard
  takes the team from the people on those boards' stories. Also ask for the price per ACU and who gave it
  (`usage.usd_per_acu`, `usage.usd_per_acu_source` in dashboard.yaml); if nobody knows, leave it empty, and only
  ACUs are shown.
- When a source fails, say what is needed in plain words (for example "the org needs a read-only connection to
  this database; the org admin requests it") and carry on with the others.

## 6. Write the settings

1. Create `<KB>/_EVIDENCE/{queries,confluence,jira,files,documents}/` and `<KB>/_QUESTIONS/` with a `.gitkeep` each.
2. `KB_PROFILE=<KB>/.metis/kb-profile.yaml python3 $METIS/tools/prompts.py lint`. Fix the settings until it passes.
3. Branch `metis/<YYYY-MM-DD>-setup`, commit only `<KB>/`, open one PR, review from the KB owner. Never merge.

## When done

List the approved stack, the databases per environment, what is still empty, and the failed connections.
Next: `kb-build`.
