---
name: app-staleness-check
description: Older name for /source-staleness-check. Compares the KB documents with the source code and reports drift exactly as /source-staleness-check does — "/app-staleness-check [module]".
argument-hint: "[module_name]"
visibility: internal
triggers:
  - user
  - model
invocations:
  - /app-staleness-check
allowed-tools:
  - read
  - grep
  - glob
---

# /app-staleness-check — older name for /source-staleness-check

The two staleness checks were merged so there is one set of paths and one status vocabulary.
Open `.devin/skills/source-staleness-check/SKILL.md` and follow it step by step, treating a module
argument as the `{MODULE}` to check. When you report, mention once that the command is now
`/source-staleness-check`.
