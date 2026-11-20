# Argus changelog

Changes to the framework as a whole. The knowledge-base prompt kit keeps its own log in `sdlc/kb/CHANGELOG.md`.

## Unreleased (branch `argus/review-fixes`)

### Added
- `sdlc/framework/tools/content_scan.py`: scans the lines a change adds for secrets and personal data. Subcommands `staged`, `range` and `text`. Never prints a matched value. Files under `tests/` and `fixtures/`, and lines marked `argus:allow`, are exempt.
- `sdlc/framework/tools/runtime_env.py`: works out whether Argus is running in Devin Cloud or Devin Local. `SDLC_RUNTIME=cloud|local` overrides detection. When it cannot tell, it reports `unknown` and the session is treated as Local, so nothing is pushed automatically. Heuristic: run `runtime_env.py probe` in a real Cloud session and a real Local session to confirm.
- `dot-devin/hooks/runtime-context.sh` and a `SessionStart` entry in `hooks.v1.json`: tell the agent where it is running at the start of a session.
- `.github/workflows/argus.yml`, `docs/CI.md`, `templates/values-ci.yaml`: CI that installs Argus with fictitious values and runs validation, prompt lint, the new unit tests and the hook tests.
- `sdlc/framework/tools/sandbox_fallback.py` and a call in the console's `main()`: on a first run in Devin Local with no Jira token, no Devin key and no Jira host set, the console makes the built-in "Zephyr Orders" sandbox (Jira, Confluence, SQLite, sample repo) under its state folder and points itself at it. A banner on the page says so, and `/api/config` returns a `sandbox` block. It is off when `SDLC_SANDBOX_FALLBACK=off`, when `SDLC_RUNTIME` is `cloud` or cannot be told, or when any real credential or host is set (a wrong token still shows its own error).
- `sdlc/framework/tools/kb_scan.py`: a stdlib-only scan of the repo Argus is installed in. Writes `docs/knowledge-base/REPO-SCAN/` (overview, endpoint registry, data model, dependencies, UI routes), each entry with file and line. Reads FastAPI, Flask, django-ninja, Django `urls.py`, Express and Next.js routes, SQL `CREATE TABLE` and Django models. Only overwrites files it wrote itself; `--check` exits 1 when stale. In the console: `GET` and `POST /api/kb-scan` and a "Repo scan" box. It is a first pass; `/kb-build` still produces the BRD, TRD and the rest.
- `sdlc/framework/tools/tests/test_kb_scan_and_fallback.py`: 31 tests for the two tools.

### Changed
- `dot-devin/hooks/git/pre-commit` runs the content scan on staged changes. `dot-devin/hooks/git/pre-push` runs it on each pushed range, so a commit made with `--no-verify` is still caught.
- `session_store.py` reads the layered config (`config.json`, then `config.cloud.json` in Cloud only, then `config.local.json`) and understands `"storage_strategy": "repository"`, which `config.cloud.json` already used.
- `AGENTS.dist.md` says `gates.mode` is `enforced`, which is what `config.json` ships, and describes the Cloud and Local differences.
- `dot-devin/agents/implement.agent.yaml`: `decision_policy` follows the steps in the `implement` skill; `coding_patterns` applies only when a change touches ETL or SQL.

### Known gaps
- On GitHub Actions, every check passed on Ubuntu (run 44656808736). Hook tests, prompt-kit tests and the full framework unit tests fail in part on Windows and only report there.
- Skills that mention Cloud or Local (for example the Snowflake login guidance) do not read `runtime_env` yet.

## 2.4.102926

Baseline: the original shared copy, unchanged.
