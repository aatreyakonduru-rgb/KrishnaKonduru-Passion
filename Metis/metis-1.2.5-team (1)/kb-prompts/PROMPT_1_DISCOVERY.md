---
prompt_id: APP-01
title: Module discovery
kind: prompt
pipeline: app
stage: 1
version: 2.1.0
shareable: true
requires: []
depends_on: []
placeholders: [PRODUCT_NAME, DOMAIN_CONTEXT, KB_MODULE_DOCS, MODULE_NAME, MODULE_SOURCE, RUN_DATE]
outputs: ["{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/00_DISCOVERY_REPORT.md"]
---

# APP-01: Module discovery

## Purpose

Take stock of one {{PRODUCT_NAME}} module before anyone writes requirements about it: what it's
built with, how it's configured, where each kind of code lives, what it talks to, and what looks
risky. Every later document for this module (BRD, FRD, TRD, manual, diagrams, security review,
registries) starts from this report. This step reads config files in full, but for source files
it reads only names and structure.

## Before you start

1. Render with the module: `prompts.py render PROMPT_1_DISCOVERY.md --set MODULE_NAME=<name> --set MODULE_SOURCE=<folder>`.
2. Read the domain context at `{{DOMAIN_CONTEXT}}`. It gives the business terms, and any
   known issues the team has already recorded for this module.
3. Check that `{{MODULE_SOURCE}}` exists and has files. If it doesn't, stop and ask.
4. If `{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/00_DISCOVERY_REPORT.md` exists, read it. You're
   refreshing it, so record what changed.

## Steps

1. **Work out the module type from its files**, not from its name.

| Signal | Likely type | Read in full |
|---|---|---|
| `manage.py`, a settings package, `requirements.txt` or `pyproject.toml` | Python web backend | settings files (base and per environment), dependency list, URL routing, Dockerfile |
| `package.json` plus a framework config (`next.config.*`, `vite.config.*`, `angular.json`) | JavaScript frontend | `package.json`, framework config, runtime config files, API client and interceptor files, the root layout |
| `pom.xml` or `build.gradle` | Java service | build file, application properties per environment, Dockerfile |
| `.sql` files plus runner scripts, no web framework | SQL or ETL scripts | runner scripts, parameter and config files |
| a handler file (`handler.py`, `lambda_function.py`, `index.js`) | serverless function | handler, dependency list, deployment config |

   If none of these fit, describe what you see and mark the type `[?]`.
2. **Read the config files in full.** Record exact versions from the dependency and lock files.
   Record the port, the context root or base path, and the auth settings. Record each environment
   override and what it changes, and each environment variable the code reads.
3. **List the source files by layer**, using names only: routes or handlers, services, schemas or
   DTOs, data access and SQL, shared libraries, UI pages, UI components, state stores, tests and
   migrations. Count the files in each layer.
4. **Find the functional modules.** Each app, package or route group, with its entry points and
   the business area it serves. Use domain-context terms only where the code or docs support them.
5. **API surface.** For each router or controller: its base path, how many handlers it has, and
   the HTTP methods. Count from the route declarations, not from guesses.
6. **Data access.** List the SQL folders and files for each app, plus any ORM models and
   migrations. List every table the module reads or writes, by name and grouped by app: take the
   names from file and folder names and from a text search of the SQL and code for `FROM`, `JOIN`,
   `INTO`, `UPDATE`, `MERGE` and `DELETE`. Say which of these the module writes. Don't analyse
   the SQL logic yet.
7. **Integrations.** Each external system in config (database, identity provider, queues,
   object storage, other APIs), with the config key that sets it.
8. **Concurrency and caching.** Async handlers, connection pools (their sizes), caches,
   background workers, websockets or server-sent events, each with its config and file.
9. **Flags.** Things that deserve a later look, each with a file and line:
   - auth can be switched off, or is bypassed in some paths;
   - wide-open CORS;
   - secrets or tokens printed or committed;
   - SQL built by joining strings;
   - build or type errors ignored;
   - auth headers commented out;
   - routers turned off;
   - hard-coded tenant or environment values;
   - few or no tests.

   Also carry forward any known issue the domain context lists for this module, and say whether
   you saw it in the code.
10. **Security surface.** List every route or page that needs no sign-in, from the route
    declarations: its path, and whether that is on purpose (health check, redirect) or not stated.
    Say how the other routes are protected, and write the auth flow as numbered steps from the
    code: where the token comes from, how it is checked, which claims or roles are read, and each
    setting that can switch the check off.
11. **User interface, for a frontend module.** The pages or routes and what each is for; the
    shared component library; the layout and startup flow (what loads first, and what the app
    waits for before it shows a page); and any micro-frontend or separately built part. Skip this
    step for a module with no user interface, and say so.
12. **Observability.** Logging setup, health and info endpoints, metrics and tracing, if any.
13. **Reading order.** List the files a later step should read first, and why.

## Output

Write `{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/00_DISCOVERY_REPORT.md`, starting with:

```yaml
---
document: Module discovery report
product: {{PRODUCT_NAME}}
module: {{MODULE_NAME}}
source: {{MODULE_SOURCE}}
module_type: <from step 1>
generated_date: {{RUN_DATE}}
prompt_id: APP-01
prompt_version: 2.1.0
---
```

Sections, each a table with a Source column:

1. Technology stack (framework, language and version, key dependencies, port, base path, auth, database, integrations)
2. Environment configuration
3. Functional modules
4. File inventory by layer, with counts and a complexity note for the largest files
5. API surface
6. Data access and SQL artifacts, with the table list
7. External integrations
8. Shared libraries and cross-cutting code
9. Concurrency and caching
10. Flags
11. Security: open paths and auth config
12. User interface (frontend modules only): pages, shared components, startup flow, micro-frontends
13. Observability
14. Reading order for later steps
15. What changed since the last run, if there was one

Then Open questions, Assumptions, Don't know, and Files read.

## Evidence rules

- Every value is tagged `[E: <file>:<line>]` or `[E: <file>]`. A count is tagged with the folder it came from.
- A value you looked for and didn't find is `Not found in source [?]`. Never fill in a framework default.
- A flag taken from the domain context but not seen in code is `[?]`, with a note.
- Anything taken as true without a source is `[A]` and goes on the Assumptions list.

## Self-check

- [ ] The module type comes from files, and the table in step 1 shows which ones.
- [ ] Every version comes from a dependency or lock file.
- [ ] Every count comes from a listing, not an estimate.
- [ ] Every flag has a file and line, or is marked `[?]`.
- [ ] Every route with no sign-in is listed in the security section, with its source.
- [ ] The table list names each table, not only the SQL folders.
- [ ] No source file bodies were copied into the report.
- [ ] Every `[A]` and `[?]` is on its list.

## Open questions, assumptions and unknowns

End with three lists, and a list of the files you read:

- **Open questions:** each with the role who can answer (tech lead, DevOps, security).
- **Assumptions:** each `[A]`, and what changes if it's wrong.
- **Don't know:** each `[?]`, with who could answer.
