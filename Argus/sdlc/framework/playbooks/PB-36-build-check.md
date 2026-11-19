# Playbook: Build Check — Install, Lint, Test and Build the Acme Claims Components

**Playbook ID:** PB-36  
**Paste into:** Devin Cloud → Settings → Playbooks → New Playbook  
**CLI equivalent:** `/build-check` skill (`.devin/skills/build-check/SKILL.md`)  
**When to use:** Before raising a PR, at the end of `/implement`, or whenever someone asks whether the code builds.

---

## Title
```
Acme Claims: Build Check — does it install, lint, test and build
```

## Description
```
Runs the same install and build steps as the component Dockerfiles, plus lint
and unit tests, for web, web-portal, web-admin, api and api-portal,
pulling packages from Artifactory. Reports a pass/fail table with a log per
step. Needs the ARTIFACTORY_TOKEN secret; without it, reports SKIP and stops.
Does not build or push images.
```

## Playbook Body

---

Run `/build-check [components]` and follow `.devin/skills/build-check/SKILL.md`.

1. Work out which components the change touches from `git diff --name-only`.
2. Run `python3 sdlc/framework/tools/build_check.py --component {X}` for each.
3. If it prints `SKIP: artifactory`, report that line and stop.
4. For each failure, quote the first real error from its log and check whether the base branch fails the same way.

## Forbidden actions
- Printing, logging or committing the Artifactory token.
- Changing dependencies to make a build pass (no new npm or pip packages).
