---
prompt_id: ETL-01
title: ETL module discovery
kind: prompt
pipeline: etl
stage: 1
version: 2.1.0
shareable: true
requires: []
depends_on: []
placeholders: [PRODUCT_NAME, DOMAIN_CONTEXT, KB_ETL_DOCS, MODULE_NAME, MODULE_SOURCE, RUN_DATE]
outputs: ["{{KB_ETL_DOCS}}/{{MODULE_NAME}}/00_ETL_DISCOVERY_REPORT.md"]
---

# ETL-01: ETL module discovery

## Purpose

Take stock of one {{PRODUCT_NAME}} ETL or batch module: its scripts, the SQL they run, how
they're grouped into processes, what they connect to, and what looks risky. Every later ETL
document starts from this report. Read the script files (they're usually short) and the config
files in full, but list the SQL files by name only.

## Before you start

1. Render with the module: `prompts.py render ETL_PROMPT_1_DISCOVERY.md --set MODULE_NAME=<name> --set MODULE_SOURCE=<folder>`.
2. Read the domain context at `{{DOMAIN_CONTEXT}}`: its process names, schedules and known issues.
3. Check that `{{MODULE_SOURCE}}` exists and has files. If it doesn't, stop and ask.
4. If `{{KB_ETL_DOCS}}/{{MODULE_NAME}}/00_ETL_DISCOVERY_REPORT.md` exists, read it. You're
   refreshing it, so record what changed.

## Steps

1. **Map the folders.** List the folder tree with a file count for each folder. Note where the
   scripts, SQL, config and tests live.
2. **Read every script in full** (Python, shell and so on). For each one, record:
   - its path and what it does, from its docstring or main function;
   - its key imports (database driver, cloud SDK, mail library);
   - what it connects to;
   - the environment variables and parameters it reads, and any hard-coded values;
   - how it handles errors (exceptions, retries, alerts, exit codes).
3. **List every SQL file** by name. Group the files by their naming prefix or folder, and give
   each group's count. For each file, list the tables it reads and writes, from a quick scan of
   `FROM`, `JOIN`, `INSERT`, `MERGE`, `UPDATE` and `DELETE`.
4. **Group the files into processes.** For example: sync jobs, request or batch generation,
   triggers, alerts, ad hoc fixes and refreshes. Use the script names, the folders and the domain
   context. Tie each process to its scripts and SQL.
5. **Config.** Parameter files, job definitions, and any schedule found in the repo. A schedule
   that isn't in the repo is `[?]`.
6. **External dependencies.** Object storage, queues, mail servers, other databases and APIs,
   each with the config key or import that shows it.
7. **Flags**, each with a file and line:
   - SQL built from parameters with string formatting;
   - secrets in code;
   - hard-coded tenant or environment values;
   - broad exception catches that hide failures;
   - no retry or alert on failure;
   - files loaded from storage at run time without checks;
   - messages built from query output.
8. **Tests.** List any tests, and what they cover.
9. **Purpose.** What the repository is for, in two or three sentences, from its README, the
   domain context or the main scripts. Say which source you used.
10. **Script detail.** For each script: its entry point, its steps in order, the tables it reads
    and writes, and its exit and failure behaviour.
11. **Database reference.** The schemas and tables the ETL touches, grouped by schema, with read
    or write. If the team has a DB table registry, list the tables the ETL uses that aren't in it.
12. **Design patterns.** Patterns repeated across jobs, such as control tables, locks,
    incremental loads, merge-then-flag or trigger files, each with an example file.

## Output

Write `{{KB_ETL_DOCS}}/{{MODULE_NAME}}/00_ETL_DISCOVERY_REPORT.md`, starting with:

```yaml
---
document: ETL discovery report
product: {{PRODUCT_NAME}}
module: {{MODULE_NAME}}
source: {{MODULE_SOURCE}}
generated_date: {{RUN_DATE}}
prompt_id: ETL-01
prompt_version: 2.1.0
---
```

Sections, each with a Source column:

1. Repository purpose
2. Technology stack
3. Folder structure
4. Script inventory
5. Script detail
6. SQL inventory by group
7. Database reference, including tables missing from the DB table registry
8. Processes
9. Design patterns
10. Config and schedules
11. External dependencies
12. Flags
13. Tests
14. Reading order for later steps
15. What changed since the last run

Then Open questions, Assumptions, Don't know and Files read.

## Evidence rules

- Every value is tagged `[E: <file>:<line>]` or `[E: <file>]`. Every count is tagged with the folder it came from.
- A table name comes from a SQL statement you saw. A purpose guessed from a file name is `[?]`.
- A value you looked for and didn't find is `Not found in source [?]`.
- Anything taken as true without a source is `[A]` and goes on the Assumptions list.

## Self-check

- [ ] Every script is in the inventory.
- [ ] Every SQL file is in a group.
- [ ] Every process lists its scripts and SQL.
- [ ] Every flag has a file and line.
- [ ] Every `[A]` and `[?]` is on its list.

## Open questions, assumptions and unknowns

End with three lists:

- **Open questions:** each with an owner by role (ETL developer, DevOps, operations).
- **Assumptions:** each `[A]`, and what changes if it's wrong.
- **Don't know:** each `[?]`, with who could answer.
