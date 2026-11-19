# Devin hook scripts

The four hooks configured in `.devin/hooks.v1.json` delegate to the scripts in
this directory. The JSON uses Devin's documented hook format
(https://docs.devin.ai/cli/extensibility/hooks/overview): `UserPromptSubmit` runs the
gate check on every prompt; `PreToolUse` with the matcher
`^(write|edit|apply_patch|notebook_edit|Write|Edit|MultiEdit|NotebookEdit)$` runs the
three file guards before every file tool (the capitalised names are Claude Code's).

Devin passes the event as JSON on stdin (`tool_name`, `tool_input`, or `prompt`);
`lib/hook_input.py` reads the file paths, the new text and the prompt from it. It knows
`file_path`/`path`/`notebook_path`, `content`/`new_string`/`new_source`/`edits[]` and
`apply_patch` patches (`*** Update File:` lines, `+` lines). With nothing on stdin it falls
back to `DEVIN_TOOL_FILE_PATH`, `DEVIN_TOOL_CONTENT` and `DEVIN_USER_PROMPT`. A hook blocks by
exiting 2 with the reason on stderr; Devin treats any other non-zero exit as a hook error and
lets the action through, so every failure path exits 2.

- `gate-phase-advance-check.sh` blocks a prompt that starts a stage (research, `/plan`,
  `/implement`, `/eval`, `/release`, `/kb-refresh`) while that stage's opening gate is not
  approved (`tools/gates.py precheck`).
- `write-access-guard.sh` blocks a file change (every file an `apply_patch` touches)
  the requester's roster roles do not allow, using the `access:` section of `.devin/rules/people.yaml`
  (`sdlc/framework/tools/access_guard.py`). It first checks `people.yaml`
  against the Confluence roster page and blocks when they differ or the page
  cannot be read.
- `shell-bypass-guard.sh` (shell tools: `exec`, `Bash`) blocks a command that skips or switches
  off the git hooks (`--no-verify`, `git commit -n`, `core.hooksPath`) or writes `.git/hooks` or
  the guard's records in `~/.sdlc/` by hand (`access_guard.py shell-check`). It fails open, since a
  broken check would stop every shell command and the git hooks still run at commit.
- `pii-guard.sh` blocks common SSN, DOB, and raw member-ID patterns.
- `no-hardcoded-secrets.sh` blocks common AWS key, password, and token patterns.

Bash is required (Linux, macOS, or Git Bash). The previous PowerShell
implementations are available in git history. The four file and prompt guards fail closed: missing content
or an unexpected error blocks the action (see `lib/content.sh`).

Shell commands are not checked for the files they change. `git/pre-commit` applies the same access rules
to every staged file, so changes made with a shell command or outside Devin are checked at
commit time (access only, not PII or secrets). Git does not install hooks
from the repository. In Devin Cloud the repo blueprint installs a small stub for each of the
three git hooks that runs the copy in `.devin/hooks/git/` when the checked-out branch has one.
On any other checkout copy them once:

```bash
cp .devin/hooks/git/pre-commit .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
cp .devin/hooks/git/commit-msg .git/hooks/commit-msg && chmod +x .git/hooks/commit-msg
cp .devin/hooks/git/pre-push .git/hooks/pre-push && chmod +x .git/hooks/pre-push
```

The access rules are read from `people.yaml` as committed on `origin/<repo.kb_branch>` (else `HEAD`),
never from an edited copy in the checkout. A pull-request build can check every commit on the branch:

```bash
python3 sdlc/framework/tools/access_guard.py pr-audit --base origin/feature/devin-sdlc \
  --pr-requester "<email of the person who opened the PR>"
```

It exits 2 when a commit has no `Requested-by` (made with `--no-verify` or without the hooks), names
someone off the roster or someone whose roles do not allow the commit's files, is a PO/BSA commit
with no `Approved-by`, or names someone other than the PR's author (a lead may open for others).
It reads git only, so it needs no `~/.sdlc` state or Confluence access.

`git/commit-msg` records who asked for each commit. Commits made by Devin or a service ID
carry that account as author, so the hook adds one trailer naming the person, found the same
way as the access check (`SDLC_OWNER`, then `/identify-requester`, then the git author email):

```text
Requested-by: Resource 3 <resource3@acme.example>
```

If nobody on `people.yaml` matches, the commit is blocked. Find a person's commits later with
`git log --grep='^Requested-by: .*first.last' -i`.

Product Owners and BSAs may change the knowledge base but not code (`access_guard.kb_only`). Their
knowledge-base changes go out as the service ID, so their approval is stamped on each commit:

1. Devin stages only knowledge-base files and shows them the change.
2. They type "approved"; Devin runs `access_guard.py approve`, which records the approval against
   exactly the staged files (`git write-tree`). Anything staged afterwards needs a new approval.
3. `git/commit-msg` adds the stamp, and blocks their commit when there is no approval:

   ```text
   Requested-by: Resource 17 <resource17@acme.example>
   Approved-by: Resource 17 (product_owner) <resource17@acme.example> 2026-10-13T20:40Z
   ```

4. `git/pre-push` (`access_guard.py pr-check`) refuses their push when the branch changes any file
   outside the knowledge base, or has a commit without `Approved-by`, against
   `origin/<repo.kb_branch>`. The pull request is then knowledge-base only, and whoever has merge
   rights on the branch merges it. Code stays blocked for them by the write guard and pre-commit.

Developers, tech leads and everyone else are not affected by steps 2 to 4.

These guards stop mistakes inside Devin. Anyone can edit their own checkout or skip a
local hook, so the hard control is Bitbucket: branch permissions and required approvers
for the paths in `access:`.

Run the test harness from anywhere in the repository:

```bash
bash .devin/hooks/tests/run-hook-tests.sh
```

The `(password|passwd|pwd)` pattern is deliberately broad and also fires on
documentation containing a literal `password: something`. Use a placeholder
such as `password: <redacted>` in documentation.
