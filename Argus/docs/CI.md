# CI for Argus

`.github/workflows/argus.yml` (at the repository root) runs on every push and pull request that touches `Argus/`.

| Job | What it does | Blocks the merge? |
|---|---|---|
| Secrets and PII scan | `content_scan.py range` on the lines the change adds | Yes |
| Install and test (Ubuntu, Windows) | Installs Argus into a scratch repo with `install.py --offline --no-check --values templates/values-ci.yaml`, then runs the checks below | See each row |
| - Framework validation | `validate_framework.py` | Yes |
| - Prompt lint | `sdlc/kb/tools/prompts.py lint` | Yes |
| - Argus additions unit tests | `test_content_scan`, `test_runtime_env` | Yes |
| - Hook tests | `.devin/hooks/tests/run-hook-tests.sh` | No, report only |
| - Prompt-kit tests | `sdlc/kb/tools/tests` | No, report only |
| - Framework unit tests | all of `sdlc/framework/tools/tests` | No, report only |
| Git hooks (content scan) | `dot-devin/hooks/tests/test-content-hooks.sh` | Yes |

## Why `values-ci.yaml`

The shared copy holds made-up "Acme Claims" values, and the install check flags any Acme value left in a file the installer was meant to rewrite. `templates/values-ci.yaml` installs a fictitious company ("Zephyr Orders") so the checks run against a real, fully substituted install. Do not use it for a real team: copy `values-template.yaml` and fill in your own.

## What was measured, and what was not

Measured on Windows only, with the Zephyr values and the full `install.py` check:

- Framework validation: passes.
- Prompt lint: passes.
- No Acme values left: passes.
- Framework unit tests: 7 failures out of 918 (2 failures, 5 errors, 21 skipped).
- Prompt-kit tests: 8 failures (4 failures, 4 errors). At least some are Windows path separators (`DB\a.md` against `DB/a.md`).
- Hook tests: 8 cases fail. One log line shows `ln` cannot create a symlink under Git Bash on Windows (`Permission denied`), which is a Windows limit.

Not measured: any of these checks on Ubuntu. They have not run on a Linux runner yet, so the first CI run is the first Linux result. The three report-only rows stay report-only until that run shows which failures remain on Linux; then remove `continue-on-error: true` from the ones that pass.

The `test_content_scan`, `test_runtime_env` and `test-content-hooks.sh` checks pass locally (Windows, Git Bash) and are blocking.

## Running the same checks locally

```bash
python install.py --target /path/to/scratch-repo --offline --no-check --values templates/values-ci.yaml
cd /path/to/scratch-repo
python sdlc/framework/tools/validate_framework.py
python sdlc/kb/tools/prompts.py lint
python -m unittest sdlc.framework.tools.tests.test_content_scan sdlc.framework.tools.tests.test_runtime_env
bash /path/to/Argus/dot-devin/hooks/tests/test-content-hooks.sh /path/to/Argus
```

`install.py --check` runs the full set against the scratch repo, including the example-roster copy that the hook tests need.
