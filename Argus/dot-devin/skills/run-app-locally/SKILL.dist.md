---
name: run-app-locally
description: Run the SDLC app (api Django API and web Next.js front end) in a Devin Cloud session, with Snowflake through the acme-snowflake MCP relay, and send back the two preview links. Uses the org skill sdlc-local-run. Say "/run-app-locally" or "/run-app-locally <branch>".
argument-hint: "[branch, e.g. feature/BACKEND_SERVICE]"
visibility: internal
triggers:
  - user
  - model
invocations:
  - /run-app-locally
  - run the app locally
allowed-tools:
  - read
  - bash
---

# /run-app-locally — the SDLC app in one click

Argus item "Run the app locally" starts this in its own Devin Cloud session.

1. Invoke the org skill `sdlc-local-run` and follow it exactly: setup, start the backend and the front end,
   start the MCP relay, expose ports 3100 and 8000 with a browser preview.
2. Branch: the one given after the command, else the branch `sdlc-local-run` names.
3. Send both links in the first reply: the front end (`/acme/` on 3100) and the API docs (`/acme/api/docs` on 8000).
   Then say whether the Snowflake MCP sign-in is still needed and give its link if it is.
4. Nothing is committed. If `git status` shows the override files, stop and say so.
