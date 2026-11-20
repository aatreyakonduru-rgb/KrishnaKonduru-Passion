# Argus changelog

Changes to the framework as a whole. The knowledge-base prompt kit keeps its own log in `sdlc/kb/CHANGELOG.md`.

## Unreleased (branch `argus/review-fixes`)

### Added
- `sdlc/framework/tools/content_scan.py`: scans the lines a change adds for secrets and personal data. Subcommands `staged`, `range` and `text`. Never prints a matched value. Files under `tests/` and `fixtures/`, and lines marked `argus:allow`, are exempt.
- `sdlc/framework/tools/runtime_env.py`: works out whether Argus is running in Devin Cloud or Devin Local. `SDLC_RUNTIME=cloud|local` overrides detection. When it cannot tell, it reports `unknown` and the session is treated as Local, so nothing is pushed automatically. Heuristic: run `runtime_env.py probe` in a real Cloud session and a real Local session to confirm.
- `dot-devin/hooks/runtime-context.sh` and a `SessionStart` entry in `hooks.v1.json`: tell the agent where it is running at the start of a session.
- `.github/workflows/argus.yml`, `docs/CI.md`, `templates/values-ci.yaml`: CI that installs Argus with fictitious values and runs validation, prompt lint, the new unit tests and the hook tests.

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
