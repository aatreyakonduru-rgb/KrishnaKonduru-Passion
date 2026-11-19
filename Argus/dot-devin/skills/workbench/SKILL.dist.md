---
name: workbench
description: Older name for /argus. Starts, restarts, stops or checks Argus exactly as /argus does — "/workbench", "/workbench stop", "/workbench status".
argument-hint: "[start|stop|status] [port]"
visibility: internal
triggers:
  - user
  - model
invocations:
  - /workbench
allowed-tools:
  - bash
  - browser_preview
---

# /workbench — older name for /argus

`/workbench` is the name the Argus command had before it was renamed. It does exactly what
`/argus` does, with the same arguments.

Open `.devin/skills/argus/SKILL.md` and follow it step by step, treating the user's `/workbench`
as `/argus`. When you hand back the link, mention once that the command is now `/argus`.
