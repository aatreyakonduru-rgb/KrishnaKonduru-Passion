---
prompt_id: APP-04
title: Module technical requirements (TRD)
kind: prompt
pipeline: app
stage: 4
version: 2.1.0
shareable: true
requires: []
depends_on: [APP-01, APP-03]
placeholders: [PRODUCT_NAME, DOMAIN_CONTEXT, KB_MODULE_DOCS, MODULE_NAME, MODULE_SOURCE, RUN_DATE]
outputs: ["{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/03_TECHNICAL_REQUIREMENTS.md"]
---

# APP-04: Module technical requirements (TRD)

## Purpose

Describe how `{{MODULE_NAME}}` is built, so a developer can change it safely: the stack, the
config, the API surface, how it reads and writes data, auth, pooling, concurrency, deployment
and known technical debt. Each section points back to the functional requirements it supports.

## Before you start

1. Render with the module: `prompts.py render PROMPT_4_TECHNICAL_REQUIREMENTS.md --set MODULE_NAME=<name> --set MODULE_SOURCE=<folder>`. The module's source is in `{{MODULE_SOURCE}}`.
2. Read the domain context at `{{DOMAIN_CONTEXT}}`, including any known technical-debt list.
3. Read `{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/00_DISCOVERY_REPORT.md` (sections 1, 4, 10 and 12)
   and `02_FUNCTIONAL_REQUIREMENTS.md` (FR IDs). If either is missing, stop.
4. Read source in batches of about ten files, in the discovery reading order. After each batch,
   write a short checkpoint of what you confirmed.

## Steps

1. **Check the facts that get made up most often.** Only write these from source you read in
   this session. If you didn't find it, write `Not found in source [?]`:

| Topic | Common invented answer | What to do |
|---|---|---|
| Log destination | a named log platform | Write what the logging config does, such as stdout. Say where the platform takes it only if a file says so. |
| Database driver | a generic driver name | Name the library that's actually imported. |
| ORM use | "uses the ORM" | Check whether model files hold real models or empty stubs, and where the queries really run. |
| Retry and backoff | "retries with backoff" | Point to the retry code, or write "no retry logic found". |
| Connection pool | typical sizes | Read the pool code or config and copy the numbers. |
| Startup command | a production server | Read the Dockerfile or entrypoint and copy the command. |
| Sync or job timing | a fixed interval | Give the timing only if a file sets it. Otherwise say it's scheduled outside this repo. |
| Audit tables | "writes an audit log" | Name only the tables the code writes to. |
| Error response shape | typical JSON fields | Copy it from the error schema classes. |
| Performance targets | response-time promises | Give these only if a config or comment states them. |

2. **Stack and config.** Give exact versions, settings for each environment, environment
   variables and feature flags.
3. **API surface.** For each route: the method, the path, the handler, the auth decorator or
   guard, the request and response types, and the `FR` it serves.
4. **Data access.** How queries are built (raw SQL files, query builders, ORM), whether they use
   parameters, the tables read and written, the transaction handling and any cache.
5. **Auth.** The token check, where the keys come from, role checks, open paths, and any switch
   that turns auth off.
6. **Pooling and concurrency.** Pool sizes, async handlers, workers, websockets or streams, and
   any locks.
7. **Cross-cutting code.** Shared libraries, and what each one does.
8. **Deployment.** Base image, port, startup command, health checks, and config maps or secrets
   by name. Never copy their values.
9. **Technical debt.** Each item, with file and line. Take items from the domain context only if
   you checked them in code; mark the rest `[?]`.
10. **Traceability.** An FR-to-component table.
11. **Dependencies.** Each direct dependency from the package or requirements file, with its
    version and what the module uses it for.
12. **SQL safety.** For each way SQL is built, say whether values are bound as parameters or
    joined into the string, with file and line. List every place request data reaches SQL text.
13. **Streams and background work.** WebSocket, server-sent events, queues and scheduled tasks:
    where each is defined, and whether it is wired into the running app.
14. **Frontend modules only.** The HTTP client (base URL, headers, token handling, retries and
    error handling); how endpoints are registered or looked up; state management (stores,
    contexts, caches); the reusable component library; and an inventory table of routes, services
    and components.
15. **Internal dependency map.** Which packages or folders in the module import which others,
    as a table or Mermaid diagram.

## Output

Write `{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/03_TECHNICAL_REQUIREMENTS.md`, starting with:

```yaml
---
document: Technical requirements
product: {{PRODUCT_NAME}}
module: {{MODULE_NAME}}
version: <n>
status: Draft
generated_date: {{RUN_DATE}}
prompt_id: APP-04
prompt_version: 2.1.0
---
```

Sections A1 to A11:

- A1 Technology stack
- A2 Environment configuration
- A3 API surface
- A4 Data access
- A5 Authentication and authorization
- A6 Connection pooling
- A7 Cross-cutting code
- A8 Concurrency
- A9 Deployment and container config
- A10 Technical debt
- A11 FR traceability matrix
- A12 Dependencies
- A13 SQL construction and safety
- A14 Streams and background work
- A15 Frontend architecture (frontend modules only): HTTP client, endpoint registry, state, component library, route/service/component inventory
- A16 Internal dependency map

Then Open questions, Assumptions, Don't know and Files read.

## Evidence rules

- Every technical fact is tagged `[E: <file>:<line>]`.
- A topic in the step 1 table without a source is `Not found in source [?]`, never a general best-practice answer.
- Anything taken as true without a source is `[A]` and goes on the Assumptions list.
- Secret values are never copied. Name the key, and say where it's read.

## Self-check

- [ ] Each row of the step 1 table was checked and has a source or `[?]`.
- [ ] Every route in the discovery report is in A3.
- [ ] Every FR is in A11.
- [ ] A13 names every place request data reaches SQL text, or says none was found.
- [ ] No secret values appear anywhere.
- [ ] Every `[A]` and `[?]` is on its list.

## Open questions, assumptions and unknowns

End with three lists:

- **Open questions:** each with an owner by role (tech lead, DevOps, architect).
- **Assumptions:** each `[A]`, and what changes if it's wrong.
- **Don't know:** each `[?]`, with who could answer.
