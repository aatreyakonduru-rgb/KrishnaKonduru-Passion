---
name: build-check
description: >
  Install, lint, test and build the Acme Claims components (web, web-portal, web-admin,
  api, api-portal) on the Devin machine the same way their Dockerfiles do, pulling
  packages from Artifactory, and report a pass/fail table. Use before raising a PR or at the
  end of /implement. Needs the ARTIFACTORY_TOKEN secret. Does not build or push images —
  Tekton does that after the merge.
  Invoke with: /build-check [component ...] [--dry-run]
argument-hint: "[web|web-portal|web-admin|api|api-portal ...] [--dry-run] [--keep-going]"
visibility: internal
triggers:
  - user
  - model
invocations:
  - /build-check
  - does it build
  - run the build
  - run the tests
allowed-tools:
  - bash
  - read
---

# /build-check — does the code install, lint, test and build?

The tool is `sdlc/framework/tools/build_check.py`. It runs, per component:

| Component | Steps |
|---|---|
| web | microfrontend install + build, `npm install --legacy-peer-deps`, lint, jest, `next build` |
| web-portal, web-admin | `npm install --legacy-peer-deps`, lint, `npm run build` |
| api | venv, `pip install -r requirements.txt`, `pip install -e .[dev]`, `manage.py check`, pytest |
| api-portal | venv, `pip install -r requirements.txt`, `compileall app` |

Node builds get `CLIENT_BUSINS_TYPE=acme`, the build arg in `*/tekton/config-*.json`.

## STEP 0 — Credential

The npm and pip registries on the Devin machine point at Artifactory, and both need a login.
The tool reads `ARTIFACTORY_TOKEN` (and `ARTIFACTORY_USER` if the token needs a username).

If the tool prints `SKIP: artifactory — credential not yet provisioned` (exit 5), say that
line to the user and stop. Do not ask for the token in chat; the org admin adds it as a Devin
secret. Never print, log or commit the token.

## STEP 1 — Run

```bash
python3 sdlc/framework/tools/build_check.py --dry-run [--component X ...]   # plan only
python3 sdlc/framework/tools/build_check.py [--component X ...] [--keep-going]
```

Limit it to the components the change touches (`git diff --name-only origin/{base}...HEAD`)
unless the user asks for all of them. A full run of every component can take a long time.

## STEP 2 — Report

Show the table the tool prints. For each failing step, open its log (under
`~/.sdlc/build-check/<timestamp>/`), quote the first real error, and say whether it comes from
the change or was already failing on the base branch (re-run on the base branch to check before
saying so).

## Known gaps

- Whether the api tests need a live database or Snowflake is not known; a failure that
  needs a connection is reported as such, not as a code defect. On the Devin Cloud VM such
  tests use the Snowflake service account, never a personal ID (see
  "Snowflake Connection Identity" in `.devin/rules/data-access.md`).
- The Dockerfile base images live in `quay-nonprod`; this skill does not build images.
- Whether `ARTIFACTORY_TOKEN` alone is enough, or `ARTIFACTORY_USER` is also needed, is not
  known until the secret is provisioned.
