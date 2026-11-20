# CI for Argus

`.github/workflows/argus.yml` (at the repository root) runs on every push and pull request that touches `Argus/`.

| Job | What it does | Blocks the merge? |
|---|---|---|
| Secrets and PII scan | `content_scan.py range` on the lines the change adds | Yes |
| Install and test (Ubuntu, Windows) | Installs Argus into a scratch repo with `install.py --offline --no-check --values templates/values-ci.yaml`, then runs the checks below | See each row |
| - Framework validation | `validate_framework.py` | Yes, both OS |
| - Prompt lint | `sdlc/kb/tools/prompts.py lint` | Yes, both OS |
| - Argus additions unit tests | `test_content_scan`, `test_runtime_env` | Yes, both OS |
| - Hook tests | `.devin/hooks/tests/run-hook-tests.sh` | Ubuntu only; Windows reports |
| - Prompt-kit tests | `sdlc/kb/tools/tests` | Ubuntu only; Windows reports |
| - Framework unit tests | all of `sdlc/framework/tools/tests` | Ubuntu only; Windows reports |
| Git hooks (content scan) | `dot-devin/hooks/tests/test-content-hooks.sh` | Yes |

## Why `values-ci.yaml`

The shared copy holds made-up "Acme Claims" values, and the install check flags any Acme value left in a file the installer was meant to rewrite. `templates/values-ci.yaml` installs a fictitious company ("Zephyr Orders") so the checks run against a real, fully substituted install. Do not use it for a real team: copy `values-template.yaml` and fill in your own.

## What was measured, and what was not

**On GitHub Actions** (run 44656808736, commit `e54a92d`, 2026-11-20): every job and step passed on `ubuntu-latest`. On `windows-latest` the three steps that are non-blocking there (hook tests, prompt-kit tests, framework unit tests) failed and were allowed to. That run is the first Linux result; it shows the Windows-only failures below are Windows limits and not defects in the framework.

**On a local Windows machine**, with the Zephyr values and the full `install.py` check:

- Framework validation: passes.
- Prompt lint: passes.
- No Acme values left: passes.
- Framework unit tests: 7 failures out of 918 (2 failures, 5 errors, 21 skipped).
- Prompt-kit tests: 8 failures (4 failures, 4 errors). At least some are Windows path separators (`DB\a.md` against `DB/a.md`).
- Hook tests: 8 cases fail. One log line shows `ln` cannot create a symlink under Git Bash on Windows (`Permission denied`), which is a Windows limit.

Not measured: whether the Windows failures can be fixed. The three Windows steps stay non-blocking until someone ports them (for example, path separators in the prompt-kit tests, and the symlink the hook tests create under Git Bash).

One CI run covers one commit; a single green run does not rule out a flaky test. Two framework tests were timing-dependent in local runs, so a Linux failure on a later commit is worth a re-run before treating it as a regression.

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
