---
name: help
description: Show the Acme Claims agentic capability menu — every slash command available in this repository, grouped by role, with what each one does and which human gate follows it. Use whenever the user asks what they can do, what commands/macros exist, how to start, or types /help, /?, --help, help, menu, commands, options, capabilities.
argument-hint: "[all | topic: bsa | po | intake | sdlc | investigate | docs | db | playbooks] or [command name]"
visibility: public
triggers:
  - user
  - model
invocations:
  - /help
  - "/?"
  - --help
  - help
  - menu
  - commands
  - what can I do
  - what are my options
  - show capabilities
  - list macros
allowed-tools:
  - read
  - glob
  - grep
---

# /help — Capability Menu

Print the capability menu. This skill is read-only: never create, edit or commit files, and never
start another workflow without the user asking.

## Usage

```
/help                 the front door: the nine commands anyone can use
/help all             the full menu, every command grouped by role
/help <topic>         one section: bsa | po | intake | sdlc | investigate | docs | db | playbooks
/help <command>       detail for one command, e.g. /help intake
/help about           the framework version and the date of the last commit
```

## STEP 1 — Work out what was asked

- No argument, or an argument you do not recognise → print the **Front door** below. It lists only
  the skills whose frontmatter says `visibility: public`; confirm against `.devin/skills/*/SKILL.md`.
- `all` → print the **Short menu**.
- `about` (or `version`) → print the **About** block in STEP 3c.
- A topic keyword → print only that section from
  `sdlc/framework/USER-MANUAL.md`.
- A command name (with or without the leading `/`) → read
  `.devin/skills/<command>/SKILL.md` and summarise: what it does, its arguments, what it writes,
  and which approval gate follows. If no such directory exists, say so and suggest the closest match.

## STEP 2 — Ground the answer in the repository

The catalogue of record is `sdlc/framework/USER-MANUAL.md`. Read it before answering so the
list reflects the current repository rather than memory. If a command appears in the manual but has no
`.devin/skills/<name>/SKILL.md`, flag it as unavailable rather than offering it.

## STEP 3 — Front door (default)

When the requester's hat is known (`/identify-requester`), print **For your role** first: the
`default_skills` of that hat in `.devin/rules/role-routing.yaml`, one line each with what it does, at
most eight. Then **Also for your role**: that hat's `more_skills`, one line each. Then the front door below,
then one line: "/help all for everything else; the My commands tab on your dashboard lists every command, yours first".

```markdown
# Acme Claims — start here

You do not need to know the pipeline. Nine commands cover almost everything:

| /start "<what you need>"  | say it in your own words; we route it and tell you what happens next |
| /status [REQ-ID]          | where is my requirement, what is next, who has to act |
| /approve REQ-ID           | sign (or send back) the gate that is waiting on you |
| /ask "<question>" to <person> | put a question to a teammate through Jira |
| /explain "<question>"     | what does the product do / who can do what, in plain English |
| /impact "<change>"        | what breaks if we change this |
| /handover <person> [REQ-ID] | give your work to a teammate |
| /dashboard                | everything waiting on you today |
| /help all                 | the full menu for people who run the stages |

Every step that changes code or ships stops for a named person to reply `approved`.
```

## STEP 3b — Short menu (`/help all`)

```markdown
# Argus — what you can do

**Business & product (plain English, no code)**
| /dashboard | everything waiting on a human today, through the role-aware landing surface |
| /feasibility-check "<idea>" | 5-minute assessment of a new idea |
| /explain-capability "<question>" | sourced answer about what the product does |
| /what-if "<rule change>" | business impact of changing a rule |
| /po-story-review <REQ-ID> | do the stories cover the acceptance criteria |
| /gate-review | which manual SDLC work (share-drive copies, hand-run checks) we could automate; gates stay |
| /migration-status · /compliance-view · /release-notes · /sprint-review-summary · /pi-plan · /spec-vs-delivery · /onboarding-guide <role> |

**Start a requirement**
| /intake "<requirement>" | clarifying Q&A → an approved spec |
| /intake notes "<notes>" | meeting notes → spec draft |
| /intake <JIRA-ID> | thin ticket → full requirement |
| /sdlc "<requirement>" | the whole pipeline, stopping at every human gate |

**Pipeline stages** (each stops for a named approver)
/intake → /research → /plan → /implement → /eval → /release → /kb-refresh
/resume-session <REQ-ID> picks up an interrupted requirement.
/build-check [component] installs, lints, tests and builds locally (needs the Artifactory secret).
/promote <from> <to> raises the PRs to move code to the next environment; a person merges.
/qa-scenarios <REQ-ID> <STORY-ID> drafts Behave scenarios for the claims-qa suite from the acceptance criteria.
/test-on-pc <REQ-ID> <STORY-ID> runs the story's test pack on your own PC (Devin Local) and sends the evidence back to Cloud.

**Investigate before you change anything**
| /investigate "<question>" | sourced answer from code + knowledge base |
| /impact-radar "<change>" | what breaks if I change this |
| /adr "<decision>" | write down a design decision: what, why, options turned down, who signed off |
| /security-audit · /pr-readiness · /source-staleness-check · /story-splitter · /grooming-assistant |

**Team routing**
| /ask "<question>" to <person> [on ACME-1234] | route a developer question to a reviewer |
| /dashboard | your role-aware work, questions and approvals landing surface |
| /identify-requester · /whoami | who Devin Cloud thinks you are, which hat fits this request, what to run |
| /roster-check | roster drift against Jira, raised as a pull request for the roster owner |

**Documentation & database**
| /app-run-pipeline <module> <path> | regenerate the 12 module documents |
| /kb-refresh | realign the knowledge base with shipped code |
| /db-discovery <schema> | live schema inventory — needs Snowflake (Devin Desktop) |

**List everything**
| /catalogue [skills\|playbooks\|agents] [filter] | the full inventory: every command, Devin Cloud macro and role profile, one line each |
| /presentation | architecture + flow diagrams to show a team; `/presentation deck` opens the exec deck full screen |

Type `/help <topic>` (bsa, po, sdlc, investigate, docs, db, playbooks) or `/help <command>` for detail.
Full catalogue: sdlc/framework/USER-MANUAL.md
```

## STEP 3c — About (`/help about`)

Read the version from `version:` in `sdlc/framework/tools/distribution_map.yaml` (a shared copy
has no such file: read the first line of `sdlc/framework/tools/VERSION` instead) and the
shared-prompt version from `sdlc/kb/VERSION`; get the commit with
`git log -1 --format='%h %cI'` and the branch with `git rev-parse --abbrev-ref HEAD` — read-only, and
the only commands this skill runs. Print a missing value as `unknown`:

```markdown
# About Argus
| Version | {version} (shared KB prompts {prompts_version}) |
| Last commit | {commit date and time} ({short hash}) on {branch} |
```

Argus shows the same in Help ▾ → About (`/api/about`).

## STEP 4 — Always close with the caveats that apply

- Every stage that changes code or ships stops at a human approval gate
  (`.devin/rules/approval-gates.yaml`); nothing is auto-approved.
- `/db-*` skills and the PowerShell hooks need Snowflake access via Devin Desktop.
- The same capabilities exist as Devin Cloud playbooks (`!pb_<nn>_<name>` macros) if the user prefers
  to start a fresh pre-loaded session.
- Job roles (`.devin/rules/role-routing.yaml`) shape what a session offers; they never grant or deny
  access. Permissions come from Devin Cloud roles, Bitbucket branch protection and the gates.

## HARD RULES

- Never invent a command. Only list commands that exist as `.devin/skills/<name>/SKILL.md`.
- Never run the command you are describing — describe it and wait.
- Keep the output scannable; do not paste whole skill files back to the user.
- For an exhaustive list rather than a menu, hand off to `/catalogue`; for how
  the pieces connect, hand off to `/presentation`.
