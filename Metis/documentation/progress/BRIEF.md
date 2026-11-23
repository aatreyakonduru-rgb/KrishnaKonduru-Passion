# Worker brief (read first, every worker)

Project: Metis 2.0.0 plugin in `metis-1.2.5-team (1)/` (call it `$METIS`). Tools are in `$METIS/tools/`, UI in
`$METIS/tools/ui/`, tests in `$METIS/tools/tests/`. Read `$METIS/tools/ui/screens_golden.py` as the model for a screen
module, and `$METIS/tools/golden.py` or `$METIS/tools/trust.py` as the model for a tool.
Plan source: `documentation/Metis-vs-Commercial-KB-Builders.md` and section 9 of `documentation/Metis-2.0.0-manual.md`.

## Hard rules
1. Python standard library only. An optional third-party package may be used ONLY behind a guarded import with a
   working pure-Python fallback or a clear "not installed" message (see how `sql_links.py` treats sqlglot).
2. Write ONLY the files named for your workstream (new files). Do NOT edit shared files: `ui/server.py`,
   `ui/ui_common.py`, `ui/views.py`, `CHANGELOG.md`, the manual, the Release Record, `templates/kb-profile.yaml`,
   or any existing tool another worker may need. Exception: you may make a small, backwards-compatible edit to an
   existing file that is listed under your workstream as "may edit". If you need any other shared change, write it into
   your notes file under "Hooks for the integrator" (exact file, exact text) and do not make it.
3. New screens go in `ui/screens_<name>.py` defining `SCREENS`, `ACTIONS`, `NAV` (auto-loaded by `server.py`).
   Use the helpers in `ui_common.py` (`page`, `form`, `field`, `esc`, `left_pane`, `right_pane`, `pane_item`).
   No JavaScript. Use the existing session user (`ctx.user`) and role rules (`kb_gate`) for anything that writes.
4. Metis rules still apply: every KB line carries an `[E: ...]` source; Metis never writes to Jira, Confluence or
   Bitbucket unless your workstream says so, and then only with an explicit flag and a dry-run default; nothing writes
   into a locked KB except through `_PENDING` staging (`kb_gate`); no secrets or question text in telemetry.
5. Each tool: a CLI (`python tool.py <command> <KB>`), importable functions, and `tools/tests/test_<name>.py`
   (unittest, temp dirs, no network, no model call). Do not weaken or delete existing tests.
6. Be honest in code and docs. If something needs an external system (identity provider, Bitbucket, a model,
   an embedding service), build the working client behind a small interface, test it against a mock or fake, and
   state "needs your environment to verify" in your notes. Never claim it works against the real system.
7. Run only YOUR tests: `python -m unittest tests.test_<name> -v` from `$METIS/tools`. Another worker is editing other
   files at the same time; a failure in a file you do not own is not yours to fix, report it.
8. Windows + PowerShell host. Use forward slashes in stored paths. Open files with `encoding="utf-8"`.

## Notes file (progress + hand-off)
Keep `documentation/progress/<WORKSTREAM>.md` updated as you go: status per item (not started / in progress / done /
done with limits / blocked), files created, how to run, test result (counts), limits, "Hooks for the integrator".
Update it after each item, so a new chat can pick up from it if you stop. Final reply: a short summary only
(items done, files, test counts, limits, hooks). Do not paste code in the reply.
