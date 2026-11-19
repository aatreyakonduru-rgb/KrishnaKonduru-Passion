---
name: devin-window
description: Devin Window — run Argus and the dashboard on the Devin Cloud machine and show them in the user's own browser through Devin's preview links, like pointing an X display at your desk. Nothing is installed on the user's PC and no personal key is needed; Jira and Confluence go through the team service accounts already set in Devin Cloud. Say "/devin-window" to open it (or reopen it), "/devin-window stop" to close it, "/devin-window status" to see whether it is up.
argument-hint: "[start|stop|status]"
visibility: internal
triggers:
  - user
  - model
invocations:
  - /devin-window
  - /window
  - open devin window
  - show the workbench in my browser
allowed-tools:
  - bash
  - browser_preview
---

# /devin-window — Argus and dashboard on Devin Cloud, shown in your browser

The work runs on the Devin Cloud machine of this session; only the pages travel to the user. They
open them from the preview links in the chat, in their own browser, after signing in to Devin. Other
people can open the links only if they have write access to this session.

Everything else the user wants to do, they type into this session's chat as usual — that chat is the
command box, and the Agent/Ask switch is Devin's own. The pages stay up while this session is awake;
after it sleeps the user says `/devin-window` again and Argus picks up its saved runs from
`~/.sdlc/console`.

Secrets come from the Devin Cloud environment, never from the user: `DEVIN_API_KEY` and the Jira
service account `ACME_JIRA_TOKEN` (org secret). Never print either, and never ask the user for
the Jira token. Do not retry Jira on 401/403 — report it.

If you also start the app itself, it connects to Snowflake as the nonprod service account, never as
the user's own ID: see "Snowflake Connection Identity" in `.devin/rules/data-access.md`.

## STEP 1 — Work out who is asking

Exactly as STEP 1 of `.devin/skills/argus/SKILL.md`: the requester's Devin user id first, then
their chat e-mail, matched against `.devin/rules/people.yaml`. Use that id as `<user>` below.

## STEP 2 — Start Argus on this machine

```bash
sdlc/framework/console/run.sh restart --user <user>    # /devin-window
sdlc/framework/console/run.sh status                   # /devin-window status
sdlc/framework/console/run.sh stop                     # /devin-window stop
curl -s http://127.0.0.1:8787/api/config
```

`jira_ok` and `devin_ok` must both be true and `default_jira_user` must be the requester's Jira
username. If `run.sh` says a secret is missing, tell the user which one and stop. For `stop` and
`status` there is nothing more to do than report the result.

## STEP 3 — Build the dashboard into it

```bash
curl -s -X POST -H 'Content-Type: application/json' -d '{"user":"<user>"}' \
  http://127.0.0.1:8787/api/dashboard
```

Argus runs `tools/gen_dashboard.py` for the requester's lens and serves the page at
`/dashboard`. If it fails, say so in the reply and still hand back Argus link; the
Argus's Dashboard button can rebuild it later.

## STEP 4 — Hand back the window

Open two browser previews on port 8787: "Devin Window - Argus" (no path) and
"Devin Window - Dashboard" (path `/dashboard`). Reply in two or three lines: click a preview chip to
open the page in your browser, and open Argus in its own tab (**Open in its own tab** on Argus's top bar) so
the Devin page switching to each new run session doesn't take Argus away; type anything else here in the chat; the
links work while this session is awake.
