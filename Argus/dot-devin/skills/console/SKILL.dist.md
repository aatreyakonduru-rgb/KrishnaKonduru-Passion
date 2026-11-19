---
name: console
description: Older name for /argus. Starts, restarts, stops or checks Argus exactly as /argus does — "/console", "/console stop", "/console status".
argument-hint: "[start|stop|status] [port]"
visibility: internal
triggers:
  - user
  - model
invocations:
  - /console
allowed-tools:
  - bash
  - browser_preview
---

# /console — older name for /argus

`/console` is the name Argus command had before it was renamed. It does exactly what
`/argus` does, with the same arguments.

Open `.devin/skills/argus/SKILL.md` and follow it step by step, treating the user's `/console`
as `/argus`. When you hand back the link, mention once that the command is now `/argus`.
