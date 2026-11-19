# Agentic SDLC framework (shared copy)

Everything one team uses to run its software delivery with Devin: skills (slash commands),
Devin Cloud playbooks, agent profiles, rules, templates, hooks, workflows, the approval
gates, the tools behind them and Argus (a local web console). Every team value in
it (people, Jira, Confluence, repos, hosts, ids) is a made-up "Acme Claims" example. You
replace those with your own in a few settings files; you don't change the code.

| Folder here | Goes to, in your repo | What it is |
|---|---|---|
| `dot-devin/` | `.devin/` | Skills, agents, rules, templates, hooks, Devin config |
| `sdlc/framework/` | `sdlc/framework/` | Playbooks, workflows, tools, Argus (`console/`), tests |
| `sdlc/kb/` | `sdlc/kb/` | Knowledge-base prompts, their tools, and the Acme example settings (`examples/acme/`) |
| `docs/knowledge-base/` | `docs/knowledge-base/` | Where your knowledge base goes; holds Argus manual |
| `AGENTS.dist.md` | `AGENTS.md` | What Devin reads first in your repo |
| `MANUALS/` | (not installed) | The user manual (with Argus guide) and the presentations, to read before installing |

Skills are stored as `SKILL.dist.md` and `.devin/` as `dot-devin/`, so that this folder isn't
picked up as live skills by whoever keeps it. Installing puts the real names back.

## Install

Needs Python 3.8+ with PyYAML (`pip install pyyaml`), git, and Devin (Cloud or CLI). On Windows
the hooks and their tests run in bash, so use Git for Windows and have its bash on PATH.
The folder also comes as one zip of the same name (`v<version>.zip`).

**Where it runs:** UEP Devin Cloud (the organisation's service accounts reach Jira,
Confluence, Snowflake and the repos), other Devin Cloud, or Devin Local. Outside UEP the team
needs MCP servers for Jira and Confluence, its own Jira and Confluence API tokens and git
access to its repo before it can use Argus; a Snowflake MCP server is optional. The window's
first step asks where, and the install points the skills at those MCP servers.

**In Devin Cloud:** upload the zip into a new session and type "install this". Devin follows
`START-HERE.md` and opens the install window (`install_ui.py`) as a preview: ten steps (check,
team, Jira, Confluence, repositories, environments, roster, review, install, next steps), with
"Save and finish later" on each. On Install it makes a `devin/` branch from your work branch,
copies the framework in, writes your roster, Jira statuses and fields, environments and KB
folders, creates the roster, sprint leave, demo recordings and manual pages under your parent
page, runs the checks, pushes, and Devin opens the pull request. It then prepares the Devin
Cloud blueprint and knowledge note for you to approve.

**From a terminal:** from this folder,

    python3 install.py --target /path/to/your-repo

It asks for your values (Enter keeps the Acme one), or reads them from a file with
`--values mine.yaml` (keys: product_name, company_name, jira_host, jira_project,
jira_token_env, wiki_host, wiki_space, confluence_token_env, git_host, repo_slug,
deploy_slug, qa_repo_slug, work_branch, devin_host, email_domain, sdlc_dir, kb_dir, and
the window's `settings:`; see `templates/values-template.yaml`). `sdlc_dir` (default
`sdlc`) and `kb_dir` (default `docs/knowledge-base`) are where the framework and the
knowledge base go in your repo; the paths below use the defaults. Then it:

1. copies everything in, with the real names back, and refuses to overwrite your files
   unless you pass `--force`;
2. swaps every Acme value for yours, in every skill, rule, playbook and setting
   (`sdlc/kb/examples/acme/` stays as the example), and saves your values in
   `.devin/rules/sdlc-install.yaml`;
3. checks: Python, PyYAML, git; your values; Jira and Confluence with the tokens in the
   environment variables you named (never printed) and your `origin` remote (skip these
   three with `--offline`); framework validation; prompt lint; the unit, prompt-kit and
   hook tests; and that no Acme value you replaced is left.

Later, in your repo, `/sdlc-install` (or `python3 sdlc/install.py --check`) runs the checks
again and `/sdlc-install reconfigure` (`--reconfigure`) changes values.

## After installing

- **Roster:** put your people, roles and the `access:` rules (who may change which
  folders) in `.devin/rules/people.yaml`, starting from `sdlc/kb/examples/acme/people.yaml`.
  Set your roster page in `.devin/rules/sdlc-profile.json` (`confluence.pages.roster`),
  publish it with `python3 sdlc/framework/tools/roster_sync.py publish --live`, have its
  owner approve it on the page, then `roster_sync.py pull --write`. Until then gate
  sign-offs and guarded writes are blocked on purpose. Then turn on the same check for
  commits: copy `pre-commit`, `commit-msg` and `pre-push` from `.devin/hooks/git/` into `.git/hooks/`.
- **Your environments and Jira statuses:** set them in `.devin/rules/sdlc-profile.json`
  before the first `/promote` or `/dashboard`. `workflow.environments` lists the
  environments in promotion order with their app and deploy branches, the values-file
  suffix, the gate before each one and, if the pipeline writes the image tag to a branch a
  person merges, that `tag_branch`; `repo.deploy_slug` and `repo.services` name the deploy
  repo and the services in it. `jira.statuses` holds the Jira status names behind each
  queue (`{statuses.qa}` in the JQL), and `jira.phases` the story suffixes (` - DEV`).
  `sdlc/kb/examples/acme/sdlc-profile.json` shows a dev → qa → prod team;
  `python3 sdlc/framework/tools/promote_check.py --list` prints what you have set.
- **Settings you may still change by hand:** `.devin/rules/sdlc-profile.json` (Jira
  fields, Confluence pages, document links), `.devin/rules/kb-profile.yaml`
  (knowledge-base folders and database), `.devin/rules/snowflake-environments.yaml`,
  `.devin/rules/jira-ticket-standards.yaml`, and `.devin/rules/DOMAIN_CONTEXT.md` (your
  product's domain; `/kb-context-build` can draft it).
- **Playbooks:** `python3 sdlc/framework/tools/register_playbooks.py` lists the playbooks in
  `sdlc/framework/playbooks/` and the `!pb_<nn>_<name>` macro each gets. With `--apply` it
  creates them in Devin Cloud, or updates them if they are already there. It needs
  `DEVIN_API_KEY`, a key of a service user in your organization that may manage playbooks.
  You can also paste them in by hand under Settings → Playbooks. Then add the secrets you
  named for Jira and Confluence.
- Start with `/help`.

## What to expect

Read this before you decide to use it. It says what you need, what is tied to one tool or one
tech stack, what has been tested, and what hasn't.

### What you need

| Need | Used by | Without it |
|---|---|---|
| Python 3.8+, PyYAML, git, bash | every tool, hook and test | nothing runs |
| An AI coding agent that can read the repo, run shell commands and write files | every skill, playbook and knowledge-base prompt | only the Python tools run (gates, roster, promotion check, validation) |
| Jira (Data Center, REST API v2, personal access token) | intake, research, export, dashboard, Argus, question sub-tasks, approvals queue | the Jira steps stop with a message; the rest still runs |
| Confluence (Data Center, personal access token) and a roster page | roster check, `/roster-sync`, guarded writes, gate sign-offs | gate sign-offs and guarded writes stay blocked, on purpose |
| A git host with pull requests and branch protection | `/implement`, `/promote`, `/release`, PR links in Argus | no PRs; the hard control (required approvers) is missing |
| Snowflake, read-only | the `db-*` and ETL knowledge-base prompts, Snowflake checks in `/eval` and `/qa-scenarios` | the database and ETL documents can't be built |
| A package registry login (npm and pip) | `/build-check` | `/build-check` stops with "credential not yet provisioned" |
| A deploy repo plus a pipeline that builds images and writes the image tag | `/promote` and `/release` | promotion can still be planned; the "did it deploy" checks can't run |
| Devin Cloud and an API key | Argus's Start SDLC and stage buttons, Test on my PC, playbook macros | Argus shows Jira and pages only |

Tokens are read from the environment variables you named when installing. Nothing prints,
logs or commits them.

Jira Cloud and Confluence Cloud use other API paths and sign-in, and this copy hasn't been
tried against them. The tools were built and tested against Jira and Confluence Data Center.

### Using an AI tool other than Devin

| Part | Works without Devin? |
|---|---|
| Knowledge-base prompts (`sdlc/kb/kb-prompts/`) and `sdlc/kb/tools/prompts.py` (`lint`, `render`, `outputs`) | Yes. They're plain Markdown filled in by Python, so any agent can follow a rendered prompt. |
| Python tools in `sdlc/framework/tools/` (`gates.py`, `access_guard.py`, `roster_sync.py`, `promote_check.py`, `validate_framework.py`, the dashboard generators) | Yes, from a terminal. |
| The git pre-commit access check (`.devin/hooks/git/pre-commit`) | Yes, it's a normal git hook. |
| Rules, templates, workflows, playbook text | Yes, as Markdown and YAML to read. Registering playbooks as `!pb_` macros is Devin Cloud only. |
| Skills (`.devin/skills/*/SKILL.md`) | Partly. The file format and the `/command` names are Devin's. Each skill is written steps plus commands, so another agent can follow one if you point it at the file. It won't find them as commands by itself. |
| Agent profiles (`.devin/agents/`) | No, Devin only. |
| Hooks in `.devin/hooks.v1.json`: stage-gate check on each prompt, write-access guard, PII guard, secrets guard | Partly. The file uses Devin's documented hook format (`PreToolUse`, `UserPromptSubmit`), which Devin describes as Claude Code compatible, and the scripts read the event as JSON on stdin. Claude Code would need the same entries in its own settings file; that has not been tried. Other tools need their own hook wiring. |
| Argus (`sdlc/framework/console/`) | Partly. The Jira panels and pages work. Starting and steering work goes through the Devin API. |

With another tool, nothing forces the approval gates. In Devin a hook stops a stage until
its gate is signed. Elsewhere the agent (or a person) has to run
`python3 sdlc/framework/tools/gates.py precheck "<prompt>" <REQ-ID>` before each stage and
`gates.py decide` to sign. Install the three git hooks (`pre-commit`, `commit-msg`, `pre-push`)
in every checkout so that the roster `access:` rules still apply to commits and pushes.

### If your tech stack is different

The framework was built for one team's stack: web front ends, Python and Node APIs,
Snowflake, Jira and Confluence Data Center, a Bitbucket-style git host, an image pipeline
that writes the image tag to a deploy repo, and a GitOps deploy. The table shows what
carries over.

| Area | Carries over? | What to change if yours differs |
|---|---|---|
| Approval gates, roster, access rules, session folders, handover, dashboard lenses | Yes | Gate names and roles: `.devin/rules/approval-gates.yaml`, `.devin/rules/role-routing.yaml` |
| Jira projects, fields, statuses, phases, issue shapes | Through settings | `.devin/rules/sdlc-profile.json` (`jira.*`), `.devin/rules/jira-ticket-standards.yaml` (custom field ids) |
| Environments, promotion order, gates per environment | Through settings | `workflow.environments` in `.devin/rules/sdlc-profile.json` |
| Knowledge-base folders, source folders, database names | Through settings | `.devin/rules/kb-profile.yaml`, `.devin/rules/snowflake-environments.yaml` |
| Knowledge-base generators in `sdlc/framework/tools/kbgen/` (API, UI and data-flow extractors behind the generated reference pages) | No | They parse the original layout: a Python API in `api/apps/app/api.py` and React micro-front ends under `web/`. Another layout makes `extract_api.py` stop with "No such file". The KB prompts don't need them; rewrite or skip the generators. |
| Application knowledge-base prompts (BRD, FRD, TRD, UI spec, security review and so on) | Mostly | The prompts read your code. Some examples and checks mention Python, SQL or a web UI; check the output for the first module. |
| Database and ETL prompts | Snowflake only | They use Snowflake SQL and its information schema. Another database means rewriting the `DB_PROMPT_*` and `ETL_PROMPT_*` files and `snowflake-environments.yaml`. |
| `/build-check` | No | `sdlc/framework/tools/build_check.py` has one recipe per component (npm with lint, jest and build; pip with pytest). Write your own: Maven, Gradle, .NET, Go and so on. |
| `/eval` test runs and coverage | Partly | The 80% rule and the acceptance-criteria check carry over. The test commands it runs (jest, pytest, Behave) are your own. |
| `/qa-scenarios` | No | It writes Behave/Gherkin for a separate QA repo (`qa_repo_slug`). Other test tools need their own step library. |
| `/promote`, `/release`, `promote_check.py` | Partly | They assume app branches per environment, a deploy repo with `values-<env>.yaml` per service, and a pipeline that writes `tekton-values-<env>.yaml` (or a tag branch). Helm/Argo-style GitOps fits after changing the settings. A push-button or release-train pipeline needs `promote_check.py` and the two skills rewritten. |
| PR links and PR flow in Argus | Bitbucket Data Center URLs | `sdlc/framework/console/server.py` recognises `/projects/<P>/repos/<R>/pull-requests/<n>`. GitHub or GitLab need that pattern and the link templates in `sdlc-profile.json` changed. |
| Secure-coding and PII rules | Mostly | `.devin/rules/secure-coding.md` and `.devin/rules/pii-handling.md` are general, with some Python and SQL examples. Add the rules for your languages and your data. |
| Domain context | Yours to write | `.devin/rules/DOMAIN_CONTEXT.md` is empty on purpose. `/kb-context-build` can draft it from your knowledge base. |
| Argus launch | Windows and Linux/macOS | `start-workbench.cmd` and the saved Devin key (Windows Credential Manager) are for Windows. `run.sh` starts it elsewhere, with `DEVIN_API_KEY` in the environment. |

### What has been tested, and what hasn't

Tested, every time this copy is built: it installs into an empty repo with another made-up
company's values; then framework validation, prompt lint, the unit tests, the prompt-kit
tests and the hook tests pass there; and no private or Acme value is left. The unit tests
use fake Jira, Confluence and Devin, with no network.

Not tested from this copy:
- a full knowledge-base build, or a full SDLC run from intake to release, with a real agent
  on a real repo;
- Jira Cloud, Confluence Cloud, GitHub or GitLab;
- any AI tool other than Devin;
- the database prompts, `/build-check` and the deploy checks against a real Snowflake,
  package registry or pipeline.

Seven tests that check the original team's own repository (its application folders and
knowledge base) are switched off in this copy, with the reason in the test.

Before relying on it, run one requirement and one knowledge-base module through by hand and
check each output.

### Limits to know about

- **The guards inside the agent are a soft layer.** The write-access hook, the PII and
  secrets hooks and the gate check stop mistakes. Anyone who can edit the repo can switch
  them off. The real control is your git host: branch protection and required approvers per
  folder (code reviewers for code, PO or BSA for the knowledge base, roster owner for
  `.devin/rules/people.yaml`).
- **The in-agent hooks watch the file tools** (`write`, `edit`, `apply_patch`,
  `notebook_edit`). A change made through a shell command (`sed -i`, `>` and so on) is
  only stopped at commit time, by the pre-commit hook, and only if you installed it in that
  checkout. The pre-commit hook checks the access rules only, not PII or secrets.
- **The hooks are tested with sample events, not live.** The hook tests feed each script
  events in the documented shape. Field names for `apply_patch` and `notebook_edit` were
  not confirmed against a live session; if a file tool sends a shape the scripts don't
  know, they block it (fail closed). To see real events, add a temporary `PostToolUse`
  hook with `matcher: ""` that logs stdin.
- **Your folder names.** The sample `access:` rules in `people.yaml` and
  `app.source_dirs` in `kb-profile.yaml` name the original team's folders (`web/`, `api/`
  and so on). Until you change them, developers are blocked from code folders no rule
  lists, and the KB build skips folders that aren't there. `install.py --check` lists
  the ones your repo doesn't have.
- **Who is asking.** In Devin Cloud the git author is a service account. `/identify-requester`
  records the person from the chat, and nothing checks it further. That is another reason
  the git host's approvals matter.
- **Self-approval.** The requester can't sign the code review gate. In `dev` gate mode the
  owner may sign other gates; set `gates.mode` to `enforced` before production use.
- **Skills are instructions to an AI.** Results depend on the agent following them, and the
  gates are where a person checks the result. Don't skip the gates.
- **Promotion never merges.** `/promote` raises pull requests and checks the result; a
  person merges.
