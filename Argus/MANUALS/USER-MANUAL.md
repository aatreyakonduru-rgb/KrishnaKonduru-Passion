# Argus — user manual

Everything this framework can do, in one place. Type `/help` in any session to get a short version of
this list; type `/help <topic>` (for example `/help bsa`, `/help sdlc`, `/help db`) for one section.

- **Skills** are slash commands you type in a session — 126 of them, listed below. `/catalogue skills` prints
  the whole list from the repository itself.
- **Playbooks** are the same capabilities registered in Devin Cloud, each with a `!pb_..` macro, so you
  can start a fresh session already loaded with the instructions. `/catalogue playbooks` lists them.
- **Agents** are role profiles (BSA, PO planner, discoverer, documenter, DB analyst, ETL specialist,
  validator, migration analyst) that the stage skills adopt; you do not invoke them directly.
  `/catalogue agents` lists them.
- **Gates** are human approvals. Anything that changes code or ships stops and waits for a named person.

---

This manual is the one place to read about the framework. The Help page in Argus is built from it, and the
Confluence page "Argus User Manual" is its published copy. Argus guide and the guide for
Product Owners, BSAs and Scrum Masters are its last two chapters.

## Where do I start?

| You are a… | Start with |
|---|---|
| Not sure what Devin Cloud thinks you are | `/identify-requester` (or `/whoami`) — your roles, defaults and first-choice commands |
| Anyone, any morning | `/dashboard` — your role's queues, questions, approvals and branches in one page |
| BSA | `/dashboard` every morning, then `/intake` (a sentence, a Jira key or your notes) |
| Product Owner | `/epics-from-roadmap` to raise epics from the roadmap sheet, `/feasibility-check` for a new idea, `/po-story-review` before ticketing |
| Finance / business partner | `/explain-capability`, `/what-if`, `/migration-status` |
| Developer | `/investigate`, `/impact-radar`, then `/plan` and `/implement` |
| Tech Lead | `/grooming-assistant`, `/story-splitter`, `/pr-readiness`, `/security-audit` |
| New joiner | `/onboarding-guide <BSA \| PO \| finance-user \| developer>` |
| Just browsing | `/help` for the menu, `/catalogue` for the full lists |
| Presenting this to a team | `/presentation` |

---

## 0. Finding your way around

| Command | What it does |
|---|---|
| `/help` | The menu above, short form; `/help <topic>` or `/help <command>` for one part |
| `/catalogue [skills\|playbooks\|agents] [filter]` | The full inventory — every slash command, every registered Devin Cloud playbook (macro + skill equivalent) and every role profile, one line each. `/skills`, `/playbooks`, `/agents` still work as shortcuts |
| `/dashboard` | Your own landing page: the lens of your main role (`primary_role` in `.devin/rules/people.yaml`, the same one Argus opens), with forms to answer questions, hand work over and raise observations. `--lens <id>` shows another role's view |
| `/presentation [section]` | Architecture and flow diagrams — the stack, the SDLC pipeline, the BSA/PO flow, KB creation and refresh |
| `/identify-requester` · `/whoami` | Who Devin Cloud thinks you are, which hat applies to this request, and the commands that go with it |
| `/roster-check [--offline\|--add]` | Roster drift against Jira and the routing config, as a pull request for the roster owner |

Those three read `sdlc/framework/CATALOGUE.md`, regenerated from the repository by
`python3 sdlc/framework/tools/gen_catalogue.py` so the lists cannot drift.

## 1. Business & Product (no code, plain English)

| Command | What it does |
|---|---|
| `/feasibility-check "<idea>"` | Five-minute assessment of a new idea: what exists, what changes, T-shirt size, risks |
| `/explain-capability "<question>"` | Sourced, jargon-free answer about what the product does and who can do what |
| `/what-if "<proposed rule change>"` | Business impact memo: who is affected, which downstream systems see different data |
| `/po-story-review <REQ-ID>` | Checks every acceptance criterion has a story, flags orphans and oversized stories |
| `/epics-from-roadmap <sheet>` | Reads the PO roadmap spreadsheet, drafts an epic per row against the epic contract, asks the PO what is missing (Confluence read with the service account, or the document uploaded — and re-uploaded when the page changes); Jira preview by default, created only on "approved" with writes on |
| `/migration-status [area]` | What has moved off OldClaims/OldBilling/OldCare and what has not |
| `/compliance-view [HIPAA\|HEDIS\|SOX\|all]` | Which features touch protected health data, quality measures, or financial controls |
| `/spec-vs-delivery <REQ-ID>` | Post-sprint audit: did we build what the spec promised |
| `/release-notes [REQ-IDs\|all]` | Executive-readable summary of what changed |
| `/sprint-review-summary <REQ-IDs>` | Slide-ready sprint review pack |
| `/vacation` | The vacation planner: everyone's time off with their backups; add or change your own (the Scrum Master can change anyone's); anyone can report a sick day or ad hoc leave |
| `/sprint-close-check` | Scrum Master: every story and sub-task in the sprint that is not ready to close, and what it is missing |
| `/pi-plan "<REQ-IDs and ideas>"` | Program increment board: sizing, dependencies, capacity warnings |
| `/onboarding-guide <role>` | Role-specific learning guide for a new team member |

## 2. Requirement intake

| Command | What it does |
|---|---|
| `/intake "<requirement>"` | Stage 1: clarifying Q&A → a complete `REQ-{id}-SPEC.md` + the BSA approval block |
| `/intake notes "<meeting notes>"` | Turns messy notes into a spec draft, asking only what is genuinely unclear |
| `/intake <JIRA-ID>` | Expands a thin Jira ticket into a full spec, marking gaps for the reporter |
| `/start "<what you need>"` | The front door: works out the kind of ask and routes it, then says where it is and who acts next |

## 3. The SDLC pipeline (each stage stops at a human gate)

| Command | Stage | Gate that follows |
|---|---|---|
| `/sdlc "<requirement>"` | Master orchestrator — runs every stage below in order | all of them |
| `/intake <…>` | 1 — Intake & clarification | `SDLC_01_INTAKE_CLARIFICATION` (BSA) |
| `/research <REQ-ID> <top-down\|bottom-up>` | 2+3 — Gap analysis, stories, estimates | `SDLC_02_GAP_ANALYSIS_REVIEW`, `SDLC_02b_STORY_CANDIDATE_REVIEW`, `SDLC_03_BACKLOG_APPROVAL`, `SDLC_03a_STORY_ESTIMATION_REVIEW` |
| `/plan <REQ-ID> <STORY-ID>` | 4 — Routing map and real insertion points | `SDLC_04_ROUTING_APPROVAL` (Tech Lead) |
| `/implement <REQ-ID> <STORY-ID>` | 5 — Code, tests, PR, AI verification | `SDLC_05_CODE_REVIEW` (Dev) |
| `/eval <REQ-ID> <STORY-ID>` | 6 — Test execution, coverage, defects | `SDLC_06_QA_SIGNOFF` (QA) |
| `/qa-scenarios <REQ-ID> <STORY-ID>` | 6 — Draft Behave scenarios for ACME/claims-qa from the acceptance criteria, reusing existing steps; lists missing steps, queries and test data | `SDLC_06_QA_SIGNOFF` (QA) reviews the draft |
| `/demo-needed [ACME-key]` | 5–6 — For a story labelled DEMO-NEEDED whose PR is approved and not merged: Devin runs every acceptance criterion in the browser with on-screen captions, saves one video per criterion in Confluence (Acme Claims Demo Recordings > epic > story > `<story>_AC1_demo`, …) and adds one Jira comment with the link. A fixed linked defect (Blocks or Linked CNR) gets a new version of each criterion's video beside the first, with v1 vs v2 on its page. Labels are never changed | — (no sign-off for the demo pages, videos or comment) |
| `/build-check [component ...]` | 5–6 — Install, lint, test and build the components locally (needs `ARTIFACTORY_TOKEN`) | — |
| `/release <REQ-ID> <STORY-ID>` | 7 — Deployment and rollback plan, promotion | `SDLC_07_ENV_PROMOTION_APPROVAL` (Release Manager) |
| `/promote <from> <to> [service ...]` | 7 — Raise the app and deploy-repo PRs for the next environment, wait for the Tekton tag; never merges | `SDLC_07_ENV_PROMOTION_APPROVAL` for uat and prod |
| `/kb-refresh` | 8 — Bring the knowledge base back in line with shipped code | `SDLC_08_KB_REFRESH_VALIDATION` (Tech Lead) |
| `/resume-session <REQ-ID>` | Picks an interrupted requirement up where it stopped | — |
| `/handover <person> [REQ-ID] [ACME-keys]` | Passes a Devin session to a roster teammate: handover note in your session directory, Jira items reassigned, session link and `/resume-session` pointer for them. The `/dashboard` sessions tab drafts the block | — |
| `/export-jira` | Writes the final `REQ-{id}-JIRA-BACKLOG.yaml` once the backlog gates are signed | — |

## Hotfix fast lane

A production incident (a Defect whose summary ends "- PROD" and that has an incident-INC label) can go through one Tech Lead
gate, **HOTFIX_PLAN_CODE_APPROVAL**, in place of SDLC_04 and SDLC_05: the routing and the code are read and approved together,
within 4 hours. The independent verifier always runs for a hotfix, whatever the risk tier. Once approved, Devin raises a
follow-up review sub-task, due in 2 working days, so the full review still happens (`tools/hotfix.py`). QA sign-off, release
and KB refresh are the same as for any story.

The question comes at the start. When `/sdlc` or Argus's Start SDLC begins on a Jira key, Devin runs
`hotfix.py check` first. If the ticket passes, it asks: "This is a production incident. Use the hotfix lane?" Yes takes
the one Tech Lead gate; no keeps the normal gates. If the ticket doesn't pass and you say it is a hotfix, Devin says what
is missing (for example the incident-INC label) and the normal gates run. Nothing else skips a gate.

## 4. Investigation & change safety

| Command | What it does |
|---|---|
| `/investigate "<question>"` | Deep search across source, registries, session artifacts — sourced answers |
| `/adr "<decision>"` | Write down a design decision in `DECISIONS/`: context, options turned down, consequences, who accepted it |
| `/gate-review` | Rank the manual SDLC work we could automate (share-drive copies, hand-run tests, status chasing). Approval gates stay |
| `/impact-radar "<thing you want to change>"` | If I change X, what breaks? Traces database → API → screen → ETL |
| Acme Claims ontology | Not a command: a page and a YAML file in the knowledge base (`CROSS-LAYER/ACME_ONTOLOGY.html` / `.yaml`). It ties the business side (Provider Group, Contract, Run Request and the rest, with their statuses and rules) to the screens, the API endpoints behind them, the tables and columns, the jobs that move the data and the systems that read it. Pick an object to see what writes into its tables and what they feed. Open it from the Ontology tab on the Tech Lead dashboard; `python3 sdlc/framework/tools/kbgen/gen_ontology.py` rebuilds it. The SDLC stages read it through `tools/ontology_lookup.py` (below) |
| `/security-audit <file\|story\|full>` | Hardcoded secrets, SQL injection, protected data in logs, missing filters |
| `security_scans.py` (run by `/implement`) | Checkmarx, Wiz and GovRAMP checks before the PR: scan, fix, re-run the tests, scan again, at most 3 rounds; what is left goes to the developer. Settings in `.devin/rules/security-scans.yaml` |
| `/pr-readiness <REQ-ID> <STORY-ID>` | Pre-merge checklist: criteria covered, tests present, docs updated |
| `/document-validation` | Every open knowledge-base question as an HTML form for the Tech Lead; applies his answers back into the KB |
| `/source-staleness-check` | Documentation vs. actual code drift (runs automatically before gap analysis) |
| `/app-staleness-check [module]` | Older name for `/source-staleness-check` |
| `/grooming-assistant <REQ-ID> <STORY-ID>` | Resolves stories too uncertain to estimate |
| `/story-splitter <REQ-ID> <STORY-ID>` | Breaks an oversized story into sprint-sized pieces |

## Risk and dependency register

Each epic can carry risks (what could stop it, likelihood and impact low/medium/high, owner, mitigation) and dependencies on
other teams (which team, what is needed, by when, owner). They are kept in the knowledge base, in
`SHARED/risk-register.yaml`, not Jira, and written with `tools/risk_register.py` after the person says approved.
`/epics-from-roadmap` asks for them when an epic is drafted. The PO office dashboard's **Risks** tab lists the open ones:
late dependencies first, then risks by likelihood times impact.

## 5. Documentation pipeline (12 documents per module)

`/app-run-pipeline <module> <source-path>` runs the whole chain; each step can also be run alone.

| Command | Produces |
|---|---|
| `/app-domain-context` | Loads shared domain context (always first) |
| `/app-discovery <module> <path>` | `00_DISCOVERY_REPORT.md` |
| `/app-brd <module>` | `01_BUSINESS_REQUIREMENTS.md` — gate `BSA_BRD_REVIEW` |
| `/app-frd <module>` | `02_FUNCTIONAL_REQUIREMENTS.md` — gate `BSA_FRD_REVIEW` |
| `/app-trd <module>` | `03_TECHNICAL_REQUIREMENTS.md` — gate `BSA_TRD_REVIEW` |
| `/app-user-manual <module>` | `04_USER_MANUAL.md` |
| `/app-process-docs <module>` | `05_PROCESS_DOCUMENTATION.md` |
| `/app-diagrams <module>` | `06_ARCHITECTURE_DIAGRAMS.md` |
| `/app-ui-spec <module>` | `07_UI_SPECIFICATION.md` (frontend only) |
| `/app-security-review <module>` | `08_SECURITY_REVIEW.md` — gate `SECURITY_REVIEW_SIGNOFF` |
| `/app-module-io <module>` | `10_MODULE_IO_SUMMARY.md` |
| `/app-integration <module>` | `11_INTEGRATION_SCENARIOS.md` |
| `/app-validation-log <module>` | Validation log entry closing the run |
| `/app-cross-pipeline <scope>` | Coordinates the UI, database and ETL pipelines end to end |
| `/app-gap-fill <session> <files>` | Exhaustive read of files the pipeline flagged as unread |
| `/app-knowledge-sync`, `/app-runtime-sync` | After a merge: which documents are now stale |

## Cost per story

The Scrum Master and delivery lead dashboards have a **Cost** tab for the active sprint. For each story it shows the story
points, the hours logged on the story and its sub-tasks in Jira, how many of those were on AI-Used sub-tasks, and hours per
point. A money figure appears only when the delivery lead sets `cost.hourly_rate` in `.devin/rules/scrum-master-metrics.yaml`;
until then the tab shows hours. Stories with no time logged are counted separately, because their cost is not known.

The Cost tab also has **Devin sessions per story and stage**: the team's Devin Cloud sessions grouped by the story
key in their title and by stage (intake to KB refresh, plus the independent verifier's extra session), with the
number of sessions and their hours (`tools/devin_usage.py`). The Devin API does not report ACUs per session, so no
ACU figure is shown. `cost.devin_usage_export` in `.devin/rules/scrum-master-metrics.yaml` can name a CSV from
Devin's usage page (session_id, acus) to add them.

![The Cost tab on the Scrum Master dashboard: Jira hours per story, then Devin sessions per story and stage (demo data).](manual-images/dash-cost.jpg)

*The Cost tab on the Scrum Master dashboard: Jira hours per story, then Devin sessions per story and stage (demo data).*

## Sprint close check

![The Sprint close tab on the Scrum Master dashboard: every story and sub-task not ready to close, with what is missing (demo data).](manual-images/dash-sprint-close.jpg)

*The Sprint close tab on the Scrum Master dashboard: every story and sub-task not ready to close, with what is missing (demo data).*

Before the sprint closes, `/sprint-close-check` and the **Sprint close** tab on the Scrum Master dashboard list every
story and sub-task in the active sprint that is not ready. A story needs all its sub-tasks closed, time logged on its
sub-tasks, `AI-Used` or `AI-NA`, an original estimate and status Ready for Approval or done. A sub-task needs hours
logged, the AI label, an original estimate and the same statuses. Each row names the ticket, its story, the owner
and everything missing. It only reads Jira. Acme Claims has no "Completed" status, so any done status counts as completed;
the list is `sprint_close` in `.devin/rules/scrum-master-metrics.yaml`.

## 6. Database documentation (needs Snowflake — Devin Desktop)

| Command | Produces |
|---|---|
| `/db-discovery <schema>` | Live schema inventory — **requires Snowflake access** |
| `/db-brd <schema>` | Database business requirements |
| `/db-trd <schema>` | Database technical requirements |
| `/db-security <schema>` | Database security review |
| `/db-diagrams <schema>` | Entity and lineage diagrams |
| `/db-supporting <schema>` | Supporting documentation set |
| `/db-change-analysis "<change>"` | Change impact analysis on the schema |
| `/db-validation <schema>` | Validation log and refresh protocol |
| `/app-knowledge-refresh` | Detects schema drift and regenerates only affected documents |

---

## Accessibility and performance checks

`/eval` opens each page the story changes in Chrome on the Devin machine and checks it (`tools/a11y_perf.py`). For
accessibility it looks for images with no alt text, form fields with no label, buttons and links with no name, a missing
page language (these fail the check), and heading jumps, duplicate ids and a missing title (listed as warnings). For
performance it reads largest contentful paint, load time, requests and transfer size against the limits in
`.devin/rules/a11y-perf.yaml`. The result, `{story}-A11Y-PERF.md`, goes with the test report to the QA sign-off (SDLC_06).

## Playbook macros (Devin Cloud)

Thirty-four of the capabilities above are also registered as org playbooks, so a new session can be
started pre-loaded. In Devin, type the macro (for example `!pb_18_bsa_dashboard`) or pick the playbook
from the session composer. The full list lives at Settings → Playbooks; each macro follows
`!pb_<nn>_<name>`, matching the file names under `sdlc/framework/playbooks/`.

`PLAYBOOK-GUIDE.md` and `PB-VALIDATION-multi-environment.md` in that folder are documentation, not
runnable playbooks.

### The playbooks guide

`{OWNER}` is resolved per `.devin/rules/session-isolation.md`.

### What This Folder Contains

This folder (`agentic/playbooks/`) contains **Devin Cloud Playbook** definitions derived from every workflow, skill, and agent in the `agentic/` system.

Each file is a self-contained instruction document ready to paste into the Devin Cloud web interface at **app.devin.ai → Settings → Playbooks**.

---

### Important: Cloud Playbooks vs CLI Skills

These are two parallel systems that do the same jobs in different environments:

| | Devin Cloud Playbooks | Devin CLI Skills |
|---|---|---|
| **Where it lives** | app.devin.ai — web UI, account-wide | `.devin/skills/` in this repo |
| **How you invoke** | Devin Cloud session, type "run [playbook name]" or it triggers automatically | CLI session, type `/skill-name` |
| **Who has access** | Entire Devin account (all team members) | Whoever has this repo checked out |
| **Supports Secrets?** | Yes (Devin Cloud Secrets Manager) | No (use env vars manually) |
| **Supports Knowledge?** | Yes (Devin Cloud Knowledge base) | No |
| **Current status** | Fully supported | Fully supported |
| **Shared state?** | Via files in this repo | Via files in this repo |

**Both systems write to and read from the same owner-scoped session directories** (`framework/context/session/{OWNER}/{REQ_ID}/`). This means you can start a session in Devin Cloud and continue it in Devin CLI, or vice versa.

---

### How to Paste a Playbook into Devin Cloud

1. Open **[app.devin.ai](https://app.devin.ai)**
2. Go to **Settings → Playbooks** (or your team's Playbooks section)
3. Click **+ New Playbook**
4. Fill in:
   - **Title** field: copy the text under `## Title` in the playbook file
   - **Description** field: copy the text under `## Description`
   - **Instructions / Body** field: copy everything under `## Playbook Body`
5. Save

The playbook will then be available to all Devin Cloud sessions in your account.

> **Note:** Do not paste the file's header metadata (Playbook ID, "Paste into", "CLI equivalent" lines) into the Devin Cloud UI — those are documentation for you. Only paste the Title, Description, and Body sections.

---

### Playbook Inventory

> **Devin Cloud naming convention (confirmed from UI):**
> - **Name field:** Use the "Cloud Name" column — no `Acme Claims:` prefix, no colon, so the macro stays short and typeable.
> - **Macro:** Auto-generated from the name (spaces → underscores, `!` prefix). The short names below produce clean macros like `!Implement`, `!Eval`, `!Release`.
> - **Body:** Paste everything under `## Playbook Body` in each `.md` file. Skip the file header lines and the `## Title` / `## Description` blocks — those are repo documentation only.

| File | Cloud Name (paste in name field) | Macro | When to Use |
|---|---|---|---|
| `PB-01-start.md` | `Start` | `!Start` | **Always start here.** Say what you need — a sentence, a Jira key or notes — and it routes to the right stage. |
| `PB-02-top-down-intake-and-research.md` | `Top Down Pipeline` | `!Top_Down_Pipeline` | PO/BSA describing a brand-new business feature. No existing code for this. |
| `PB-03-bottom-up-research.md` | `Bottom Up Research` | `!Bottom_Up_Research` | Changing existing code, bug fix, regulatory change, or any case where gaps must be found in source first. |
| `PB-04-plan-and-routing.md` | `Plan and Routing` | `!Plan_and_Routing` | Per-story, after Jira export is done and the team is ready to implement a specific story. |
| `PB-05-source-staleness-check.md` | `Staleness Check` | `!Staleness_Check` | Any time you want to verify KB docs before using them. Auto-runs at the start of PB-03. |
| `PB-06-kb-refresh.md` | `KB Refresh` | `!KB_Refresh` | After every PROD deployment to keep KB docs in sync with deployed code. |
| `PB-07-resume-session.md` | `Resume Session` | `!Resume_Session` | When a Devin Cloud session was interrupted and you want to pick up exactly where it stopped. |
| `PB-08-investigate.md` | `Investigate` | `!Investigate` | Ask any question about the system — tables, endpoints, components, ETL, past requirements, rules. |
| `PB-09-impact-radar.md` | `Impact Radar` | `!Impact_Radar` | Before touching any code: "if I change X, what breaks?" Traces all downstream dependencies. |
| `PB-10-security-audit.md` | `Security Audit` | `!Security_Audit` | Scans a file, story, or full codebase for security/PII violations. 10 checks, prioritised findings. |
| `PB-11-story-splitter.md` | `Story Splitter` | `!Story_Splitter` | Splits a `needs_split=true` story into child stories ≤8pts using the complexity matrix. |
| `PB-12-pr-readiness.md` | `PR Readiness` | `!PR_Readiness` | Pre-merge checklist: all ACs covered, security clean, tests present, KB updated. Produces AI-VERIFICATION.md. |
| `PB-13-grooming-assistant.md` | `Grooming Assistant` | `!Grooming_Assistant` | Resolves `needs_grooming=true` stories: investigates unknowns from source, asks targeted questions, re-estimates. |
| `PB-14-implement.md` | `Implement` | `!Implement` | After SDLC_04 (routing map approved). Writes code, tests, and KB updates for one story. Produces AI-VERIFICATION.md. |
| `PB-15-eval.md` | `Eval` | `!Eval` | After SDLC_05 (code review approved). Verifies AC coverage, writes missing tests, assesses defects. Produces Test Report for SDLC_06. |
| `PB-16-release.md` | `Release` | `!Release` | After SDLC_06 (QA sign-off). Produces deployment plan, rollback plan, smoke tests, and deployment log for SIT → UAT → PROD. Triggers KB Refresh after PROD. |

---

### Recommended Playbook Order for a Full SDLC Cycle

```
                    ┌─────────────────────────────────────┐
                    │  PB-09 Impact Radar                  │ ← Run FIRST for any change
                    │  "if I change X, what breaks?"       │   to shared tables/endpoints
                    └──────────────┬──────────────────────┘
                                   │
                    ┌──────────────▼──────────────────────┐
                    │  PB-01 Start — say what you need     │ ← Entry point for all work
                    └──────────────┬──────────────────────┘
                                   │
              ┌────────────────────┴────────────────────┐
              │                                         │
   ┌──────────▼──────────┐               ┌─────────────▼─────────────┐
   │ PB-02 Top-Down      │               │ PB-03 Bottom-Up Research   │
   │ (new capability)    │               │ (code-first, gaps)         │
   └──────────┬──────────┘               └─────────────┬─────────────┘
              │                                         │
              └──────────────┬──────────────────────────┘
                             │
              ┌──────────────▼──────────────────────────┐
              │  [Story issues? Run these as needed]     │
              │  PB-11 Story Splitter (needs_split)      │
              │  PB-13 Grooming Assistant (needs_grooming)│
              └──────────────┬──────────────────────────┘
                             │
              ┌──────────────▼──────────────────────────┐
              │  PB-04 Plan & Routing                    │ ← Once per impl story
              └──────────────┬──────────────────────────┘  (SDLC_04 gate)
                             │
              ┌──────────────▼──────────────────────────┐
              │  PB-14 Implement                         │ ← Code + tests (SDLC_05 gate)
              │  PB-10 Security Audit (during/after)    │
              │  PB-12 PR Readiness (before raising PR) │
              └──────────────┬──────────────────────────┘
                             │
              ┌──────────────▼──────────────────────────┐
              │  PB-15 Eval — Test Execution & QA       │ ← Tests verified (SDLC_06 gate)
              └──────────────┬──────────────────────────┘
                             │
              ┌──────────────▼──────────────────────────┐
              │  PB-16 Release — Deployment Planning     │ ← SIT → UAT → PROD (SDLC_07)
              └──────────────┬──────────────────────────┘
                             │
              ┌──────────────▼──────────────────────────┐
              │  PB-06 KB Refresh                        │ ← After every PROD deploy (SDLC_08)
              └─────────────────────────────────────────┘
```

**Use PB-05** (Staleness Check) any time you suspect the KB docs have drifted.
**Use PB-07** (Resume) any time you start a new session and want to continue a previous requirement.
**Use PB-08** (Investigate) for any ad-hoc question about the system — tables, APIs, flows, rules.

---

### Playbooks vs CLI Skills — Which to Use When?

**Use Devin Cloud Playbooks when:**
- You want the entire team to have access without repo setup
- You are working in a Devin Cloud session (not your local terminal)
- You want to leverage Devin Cloud Secrets and Knowledge features
- You want account-wide governance (one place to update, everyone gets it)

**Use Devin CLI Skills when:**
- You are working locally in your IDE (Windsurf / VS Code with Devin CLI)
- You want project-level skills committed in version control
- You want the skill to trigger automatically from the model without user invocation
- You want hooks to run alongside the skill

**Use both together when:**
- You start a requirement in a Cloud session, then continue implementation locally
- You want the Cloud playbook for research/backlog and the CLI skills for code generation
- Both read/write to the same `framework/context/session/{OWNER}/{REQ_ID}/` directory, so handoff is seamless

---

### Keeping Playbooks in Sync With CLI Skills

When you update a CLI skill (`.devin/skills/{name}/SKILL.md`), update the corresponding playbook here:

| CLI Skill | Corresponding Playbook |
|---|---|
| `/start` | PB-01 |
| `/intake` | PB-02 (Phase 1) and PB-03 (Phase 1) |
| `/research` (top-down) | PB-02 (Phases 2A–2C) |
| `/research` (bottom-up) | PB-03 (Phases 2A–2D) |
| `/source-staleness-check` | PB-05 |
| `/export-jira` | End of PB-02 and PB-03 (Phase 3) |
| `/kb-refresh` | PB-06 |
| `/resume-session` | PB-07 |
| `/investigate` | PB-08 |
| `/impact-radar` | PB-09 |
| `/security-audit` | PB-10 |
| `/story-splitter` | PB-11 |
| `/pr-readiness` | PB-12 |
| `/grooming-assistant` | PB-13 |
| `/implement` | PB-14 |
| `/eval` | PB-15 |
| `/release` | PB-16 |

---

### Key Paths (Referenced in All Playbooks)

#### Session Directory
```
framework/context/session/{OWNER}/ plus legacy unscoped `context/session/REQ-*`
```

#### Source Code (always ground truth)
| Layer | Path |
|---|---|
| API — Django | `api/` |
| Frontend — Next.js | `web/` |
| SQL / DB | `claims-etl/scripts/sql/` |
| ETL — Glue | `claims-etl-glue/` |
| ETL — Lambda | `claims-etl-lambda/` |

> **Note:** claims-etl-* repos are separate GitHub repositories and must be cloned independently.

#### KB Documentation (AI-generated — verify before using)
| Artifact | Path |
|---|---|
| DB Table Registry | `docs/knowledge-base/DB-DOCS/DB_TABLE_REGISTRY.yaml` |
| DB Schema Summary | `docs/knowledge-base/DB-DOCS/DB_SCHEMA_SUMMARY.md` |
| DB Cross-Module Matrix | `docs/knowledge-base/CROSS-LAYER/CROSS_LAYER_IMPACT_MATRIX.yaml` |
| API Endpoint Registry | `docs/knowledge-base/MODULES/claims-web/api/10_ENDPOINT_REGISTRY.yaml` |
| FE Component Registry | `docs/knowledge-base/MODULES/claims-web/web/12_COMPONENT_REGISTRY.yaml` |
| ETL IO Contract | `docs/knowledge-base/ETL/claims-etl/13_ETL_TABLE_IO_CONTRACT.yaml` |

#### Templates
| Template | Path |
|---|---|
| Complexity Matrix | `.devin/templates/complexity-matrix.yaml` |
| Jira Backlog Schema | `.devin/templates/jira-backlog-schema.yaml` |
| Gap Analysis | `.devin/templates/gap-analysis.md` |
| Routing Map | `.devin/templates/routing-map.md` |

---

## Argus (`/argus`)

`/argus` starts Argus (`/console` is its older name and still works), a web page for the same work you do in chat. It knows who
you are from the chat that started it, so you never pick yourself, and its menus follow your role.
Every menu item opens in its own browser tab, and what happens depends on the kind of item.

**Pages that are already written.** Help, Catalogue, Onboarding guide and Presentation open straight
away and do not start a Devin session. They are built from files in the repository (this manual,
`CATALOGUE.md`, the onboarding guides and `ARCHITECTURE.html`) and checked into
`sdlc/framework/reference/`. When a source file changes, `tools/gen_reference_pages.py`
rebuilds them in the same pull request; the framework check fails if someone forgets.

**Onboarding guides.** There is one guide per role (BSA, PO, finance user, developer), stored in the
knowledge base as `ONBOARDING-<role>-<date>.md`. The Onboarding page shows the newest one for each
role. `/onboarding-guide <role>` rewrites one, which is worth doing when the knowledge base changes
(`/kb-refresh` after a release), not every time someone wants to read it.

**Who is on the roster.** Roster check first opens a page listing everyone on the roster, grouped by
job role: name, Jira user, the other hats they wear, which gates they can sign, sprint time, who
covers for them when they are away, and whether Devin already knows their Devin user id. Its button
runs `/roster-check` for the drift check against Jira. The page only reads the roster; changes still
go through the Confluence roster page and a reviewed pull request.

**Forms.** Settle open questions opens the knowledge-base question form. Devin only starts when you
press Send my answers.

**Work.** Everything else starts one Devin session and opens its result page: what Devin said, the
documents it produced (Markdown opens as a formatted page, with a download of the original),
questions for you, any gate waiting on your sign-off, and a reply box. Skills that only read run for
real; skills that can write start as a dry run with a "Run it for real" button. If you ask for the
same thing within 24 hours you get the earlier answer back, with "Run again now" if you want a fresh
one.

**Sessions close when they are done.** A menu item's session is closed as soon as Devin has posted
its finished line and is not waiting on a question or a sign-off. The answer stays on the result
page, marked "finished · session closed", with Run again instead of a reply box. SDLC pipeline runs
are never closed automatically, because they stop at gates for days. You can also close any run
yourself with Close session on its result page. Closing a chat closes its card only: your Argus
assistant session for the day keeps running for your other requests.

**Close versus archive.** Close ends the Devin session for good: it stops using resources and cannot
be woken again, though its transcript can still be read in Devin. Archive only hides a session from
the lists, and it can still be resumed. Argus closes; it does not archive.

**My sessions on the dashboard.** The dashboard's Sessions tab lists your open Devin sessions, most
urgent first. Tick the ones you are finished with and press Close sessions. When Argus opened
the dashboard it closes them directly; otherwise the button gives you a block to paste into chat, and
Devin closes them there (never the session you are talking to). Closed sessions drop off the list.

**Roadmap and Ontology on the Tech Lead dashboard.** Both tabs carry a page the knowledge base already has and open it
in a new browser tab: Roadmap is the delivery roadmap `/roadmap` last wrote, Ontology is the Acme Claims ontology. Column
details in the ontology that the production documents do not cover come from SIT (T01), and say so.

**Independent verifier and Change confidence.** A story whose `estimation_basis` scores RISK=1/2 (medium) or
RISK=2/2 (high), or that uses a matrix chain with change_impact HIGH or CRITICAL (high), gets a second check
before SDLC_05. `/pr-readiness` starts a separate, read-only Devin session that did not write the code
(`tools/verifier.py start`). It gets the acceptance criteria, the diff and the claims file, and answers pass or
fail with its findings. The answer is kept in `{STORY}-verifier.yaml` in the session folder, and SDLC_05 needs a
pass there. The Change confidence tab on the Tech Lead dashboard shows claims verified against unverified, each
verifier verdict, the failed rounds before a pass, and missed impacts: files changed by the fix of a defect linked
to the story in Jira that the link-graph walk from the story's own files did not predict
(`tools/verifier.py missed ACME-n --defect ACME-m`).

**How the SDLC uses the ontology.** The stages look things up in the ontology through
`python3 sdlc/framework/tools/ontology_lookup.py`, then check the answer in the registries
and the code. The registries and the code decide.

| Command | What it gives | Used by |
|---|---|---|
| `find "<words>"` | the objects, business phrases, tables, columns, screens, endpoints, jobs and status codes that match, each with its source ("TIN group" finds Provider Group) | `/start`, `/intake`, `/research`, `/investigate`, `/explain`, `/ask` |
| `context <name>` | one item and what is around it: tables, columns (PHI marked), screens, endpoints, jobs, systems, states, rules, chains, open questions | `/intake`, `/research`, `/plan`, `/investigate`, `/explain`, `/ask` |
| `impact <table, column, endpoint, screen or object>` | who writes and reads it, the jobs, the tables downstream and upstream through those jobs, the column lineage seen in T01, the systems and the curated chains; direct (depth 1) and transitive | `/impact`, `/research`, `/plan`, `/investigate` |
| `scenarios <object, table or status>` | edge cases to test: each status value, the allowed flow and the skips it forbids, phrases, rules, mandatory columns, downstream readers | `/qa-scenarios` |
| `touches --base origin/<branch>` | the endpoints, screens, jobs and tables a branch touches, and whether the ontology must be rebuilt in the same PR | `/pr-readiness`, `/implement` |
| `check` | whether the committed ontology still matches its KB sources; `/kb-refresh` rebuilds it, the framework validator warns when it is out of date | `/kb-refresh`, validator |
| `walk <item> --hops N [--types …]` | everything within N links of a table, column, endpoint, screen, code file or story in the link graph (`CROSS-LAYER/ACME_LINK_GRAPH.yaml`): screens, jobs, code files, test files and earlier stories, each with the file:line, KB entry or commit that proves the link | `/research`, `/plan`, `/impact-radar`, `/investigate` |
| `drift [--base origin/<branch>] [--item <name>]` | re-reads the file:line each link cites and says current, moved or stale; a stale link is not trusted | `/research`, `/plan`, `/pr-readiness` |

**The link graph and keeping it current.** `tools/kbgen/gen_link_graph.py` builds `CROSS-LAYER/ACME_LINK_GRAPH.yaml` from the ontology, the cross-module matrix, the test files' imports, the commits that name a Acme Claims story and the Behave scenarios of the QA repository `ACME/claims-qa` (read only, from `~/repos/claims-qa` or `CLAIMS_QA_REPO`). A scenario covers the screen whose tile its steps click and checks the tables its database steps query; when the QA repository is not on the machine, the committed scenario links are kept. Picked Behave scenarios carry `run_by: QA`: QA runs them in SIT, so `confidence.py required` lists them for QA instead of failing. `python3 sdlc/framework/tools/kb_sync.py --base origin/<branch>` rebuilds the matrix, the ontology, the link graph and the KB manifest in that order; `/implement` runs it before every PR and commits the result, and `/pr-readiness` runs it with `--check` and fails when any of them is stale. Documents that need Snowflake are reported `not run` and rebuilt after deployment by `/kb-refresh`.

**Evidence, tests and data contract.** `tools/confidence.py` checks that a change rests on evidence. `/plan` writes `{STORY}-claims.yaml` in the session folder, one claim per fact the routing map relies on, each citing a `path:line`, a KB file, a link-graph node or link, or a matrix chain; `confidence.py claims` checks each one and SDLC_04 shows how many were verified. Until the date in `.devin/rules/confidence.yaml` (two sprints) an unverified or missing claim only warns; after it, SDLC_04 is blocked. `confidence.py tests --base origin/<branch> --pack <test pack>` walks the link graph from the changed files to the tests that cover them and writes them into the test pack as `selected_tests`; `confidence.py required --pack <test pack>` fails `/eval` and `/pr-readiness` while any of them is `not run` or `failed`. `confidence.py contract --base origin/<branch>` checks table and column names and literal types in the changed SQL against `DB-DOCS/DB_TABLE_REGISTRY.yaml` and the ontology; the live Snowflake check is always reported `not run`. Each command prints its `[SDLC] evidence`, `[SDLC] tests` or `[SDLC] contract` line for Argus Trace.

**The screen follows your role.** Which ticket list the left column opens on, and whether the side
columns are open, depends on your role's dashboard lens (`workbench_layouts` in
`.devin/rules/role-routing.yaml`). Developers open on their own sprint tickets with documents and diffs
on the right. Tech leads open on the whole sprint with a wider right column for diffs, PRs and gates. The right
column's **Trace** tab shows, per stage, what the session loaded and decided — agents, skills and why,
rules loaded or deferred, knowledge-base files loaded or skipped with the reason, matrix chains used,
ontology lookups with why the stage used them and what each gained,
link-graph walks, drift checks of the lines the graph cites and the KB sync result of each artefact,
what was read from the claims-qa QA suite (QA suite), the evidence, picked tests and contract checks,
the waiting gate and its owner (`.devin/rules/workbench-trace.md`). **Your name ▾ → Trace** opens the same
view in a floating window you can drag aside, minimise or close while you work in the columns.
BSAs and the PO office open on all open team tickets, and their right column stays folded until a run
is open. QA and UAT open on their queues. The « and » buttons fold a column to a thin bar and the bar
opens it again; Argus remembers your choice per role in this browser, and remembers a different
ticket list if you pick one. The Backlog screen always uses the full width, in two columns: the
ticket list on the left and one wide working column on the right.

### Backlog tab and logging hours

Everyone has a **Log hours** button on the ticket they are working on: pick the sub-task, type the hours
and what you did, and it becomes a Jira worklog in your name. Product owners, tech leads, delivery leads,
BSAs and solution leads see the full **Backlog** button in the top bar. It is the day-to-day Jira work
from buttons. The list reads every groomable story, page by page, up to 1,000 (the count above the list says when
Jira holds more). Above the list, **needs attention** chips count the stories that need grooming (no real AC,
not sized, or over 13 points), are unassigned, have no AC, no points, no epic, no release, no specialty (read
from the story and epic titles with the words in `.devin/rules/defect-specialties.yaml`) or no update in 30
days; click one to filter the list to it. **My tools → Plan the sprint** (PO office, tech lead and Scrum Master) shows the
active and next sprint against velocity, the not-started stories to push out when the sprint is over,
the ready backlog stories that fit the space left, the load per person and the stories to split.
**Select these to move** ticks them and picks the sprint, ready for Preview move. Pick a story and the wide column shows its title, description and acceptance criteria
(flagged when Jira still holds the placeholder text), then set its points or run a planning-poker
round (everyone votes blind, show the votes, agree a number). **Team poker** runs the same round across everyone's Argus, with Devin at the table: the PO or BSA (only those roles) ticks who is on the call from the people on Argus now (Devin is ticked too) picks a **Timer** (no timer, the default, or 30 s to 10 min; Argus remembers the choice) and presses **Notify & start**; each person gets a "point ACME-nnnn" bar (with the countdown when there is a timer) at the top of their own Argus and votes 1–13 or ? on their PC. Devin starts scoring when the PO or BSA presses **Ask Devin for its estimate** (or **Suggest acceptance criteria**) on the story, or starts the round with Devin ticked; opening a story never starts a Devin session on its own, so press it while explaining the story and the card is usually in before the timer starts; it scores the story with `.devin/templates/complexity-matrix.yaml` (story-type rules first, then SCOPE, RISK, UNKNOWNS, DEPENDENCY and TESTABILITY 0–2 with a reason each, the lookup, then at most two risk-modifier bumps; Argus recomputes the number from the scores so it follows the rule book) and plays ? when the matrix says groom first and 13 when it says split. Until she presses **End vote** (or the timer runs out) the starter sees only who has voted; then her Argus shows the votes (anyone who did not vote shows as no vote). **Re-vote** starts a new round with the same people and the timer picked now. If every card matches she presses **Save N as story points**. If not, a discussion box opens on her shared screen (drag it by its title to move it out of the way; the page behind stays usable). Devin's card shows in red, and its reasoning stays hidden until someone presses **Show Devin's reasoning**: then Devin explains each dimension and challenges each person whose number differs by name ("I'd only go up to 8 if the export changes too"); if everyone accepts Devin's number she saves it, and if someone disagrees she ticks them, types their reason and saves their number. Saving makes two previews: the points, and a ticket comment with every vote, Devin's working and each dissent with its reason. The team's number is always the one saved. The round, votes and timer are kept as tags on each Argus's own Devin Cloud session (in Devin Cloud the host session Argus runs in, tagged `sdlc-workbench-seat`; on a PC its Jira reader session): no Jira write until the previews are approved, hidden on screen but not encrypted. **Suggest acceptance criteria** appears on a story with no AC or only Jira's placeholder: the same read-only Devin session also returns numbered AC, shown under the story as *Suggested acceptance criteria* in an edit box the PO changes on the call; **Use as AC** makes the usual preview (the Jira write adds the `suggested-acceptance-criteria` label). Tick stories and move them to a sprint or
back to the backlog, clone a ticket, drop meeting notes on a ticket, or paste notes to draft a new epic or
story — the page writes the numbered acceptance criteria, phase suffix and labels the rule book asks for
and tells you what is still missing before anything is created. **My tools → New epic or story** opens
that drafting form in the wide column. Above it, **With Devin** takes a typed need, uploaded files (Word, PDF, Excel,
CSV, PowerPoint, text or images; up to 10 files, 25 MB) or both: pick Epic, Story, Epic with stories or Epics from a roadmap (the PO's spreadsheet, .xlsx/.csv) and
press Start intake. A Devin session reads the files, asks the BSA numbered questions on the run screen
(forward one to the PO when it is theirs), presents SDLC_01 and then the epic and stories at SDLC_02b.
**Dry run** (ticked by default) gives the result as a Markdown file and writes nothing to Jira. Untick it
for a live run: after the PO approves, the session creates the tickets in Jira and attaches the uploaded
files. A live run needs Backlog writes switched on (`SDLC_BACKLOG_WRITES=1`); otherwise the box stays
ticked. Product owners, the PO office and tech leads also get
**My tools → Sprint calendar**: each sprint's dates, the active sprint and the days left, stories and
points committed against the velocity in the roadmap year plan, release dates from fix versions, and
the next sprints projected on the 21-day cadence. Click a sprint to filter the list to it.
**My tools → Scrum Master follow-ups** (the same people as the Sprint calendar) covers the two things the Scrum Master
otherwise chases by hand. **Leave** has one row per person and one column per working day of the sprint: click a day to
mark it off, tick **No leave** when someone has said they take none, and add a note if needed. It lists who hasn't
answered yet, and works out the team's hours and points as you type (days in × 6 hours × % on project, hours ÷ 8 = points).
**Save to Confluence** writes that sprint to the "Acme Claims Sprint Leave" page next to the roster; the other sprints on
the page stay as they are, and people can also edit the page directly. The same page has a **Time off and backups**
table, the one place with everyone's time off. Once a week, in their first Devin Cloud session, everyone on the roster
(the Product Owners and the Scrum Master too) is asked whether they have time off coming up. A yes brings four more
questions: who covers their stories, whether their In Progress stories go On Hold, where questions for them go and who
approves in their place. The answers go into the table, and the days into the sprint sections, after they say
approved (`tools/time_off.py`). While someone is away, question and approval sub-tasks for them go to their backup,
or to their `delegate_to` in the roster when they named none. **Download capacity sheet** gives the same numbers
as an Excel file in the usual layout. **Sprint planning sheet** opens the sprint's planning workbook as it is kept in the
repo (one file per sprint in `context/sprint-sheets/`): the Capacity, Carry forward and Previous sprint AI savings
tabs, every cell a text box, worked out with the workbook's formulas. A day cell is 1, 0, 0.5 for a half day or H
for a holiday; the totals show team hours, story points (hours ÷ 8) and story points with AI (points × the AI factor).
**Save** shows the cells that change, and **Approved, save** writes the repo file and the Sprint Leave page. When
someone records time off with `/vacation`, the same days change on the sheet. **In progress: one story at a time** lists anyone with more than one story In
Progress, stories with no change on them or their sub-tasks for 2 working days (`cycle_time.idle_working_days`), stories
waiting on an open Question or Approval sub-task that should be On Hold, and On Hold stories with nothing left open that
can go back to In Progress. A story On Hold doesn't count as In Progress, so starting the next story while you wait is fine.
**Before stand-up: what is missing in the sprint** lists each gap in the active sprint with the person to ask: a story
with no sub-tasks, a story or sub-task with no AI label (or the wrong case), an AI-Used sub-task with no original estimate,
closed with no hours or logged over its estimate, a story In Progress with no time logged on it or its sub-tasks, a story
still open when every sub-task is closed, and a story closed while sub-tasks are still open. Where the label is missing,
**Add AI-Used** and **Add AI-NA** set it (a wrong-case label comes off); where the estimate is missing, type the hours and
**Set estimate**. Every gap has **Draft nudge**, a comment for the owner that you can edit before it goes on the ticket.
**More points than their capacity after leave** compares each person's story points in the sprint with their hours from
the leave page ÷ 8, and drafts "You have X story points against Y points of capacity after leave. How do you plan to
handle it?" on their first story. **Not answered about leave yet** lists who has marked neither a day off nor No leave,
with a message to send them in Teams. Label, estimate and comment changes are previews until Backlog writes are on.
**Draft nudge** writes a comment to the person; **Put on hold** and **Resume** move the story with a comment saying what it
waits on. Each one is a preview first and needs Backlog writes switched on.
Give the story points and the page defaults the standard sub-tasks for the story's phase (DEV, or SIT / UAT when the title ends "- SIT" / "- UAT") with Original Estimates that add up
to the story's estimate (hours from the complexity matrix); edit any line and the rest rebalance.
Pick the specialty and it goes at the front of the title (EOC - … - DEV). When the business needs
A before B before C, select them in that order and press **Set order**: the page previews the
"blocks" links and an "Order: A → B → C — why" line on each ticket, and from then on it will not let a
story be moved into a sprint earlier than the one that blocks it.
**Raise** on the selected ticket is for QA, UAT and anyone else: a question or clarification becomes a
Question sub-task under the story assigned to the person who must answer (it shows in their "waiting on
you" list); an observation, defect or risk becomes its own ticket linked back to the story, with severity
and the environment it was seen in. All previews until writes are switched on.

**`/vacation`** shows the planner from today on: who is away when, and who covers their stories, questions and approvals. Anyone can add, change or remove their own time off and name their backups; the Scrum Master can change anyone's. Nothing is written until the person types "approved". Every dashboard has the same planner as a **Vacation planner** tab. It starts with this sprint's leave calendar: one row per team member, one column per day, with each day coloured by type — planned time off (P, blue), sick day (S, yellow), ad hoc leave (A, purple), holiday (H, orange) and weekend (grey); a half day is half coloured. Under it are each person's backups and who is away now, then this sprint's unplanned leave (the dated sick and ad hoc days, and each person's count for the sprint and the year), then this sprint's planning sheet, read only. Recording time off also sets that person's days on the sprint's planning sheet in the repo (0 off, 0.5 half day, H holiday), and the hours, points and points with AI follow.

**Sick days.** Anyone on the team can tell Devin that someone is out sick, for example in the team channel: `@Devin Ravi is sick today`. Devin adds a one-day row with Type **Sick day** to the planner and the day to the sprint's section of the Sprint Leave page, straight away, with no questions. A sick day names no backups, puts nothing On Hold and changes no Jira tickets. If it runs past a day, the Scrum Master and the tech leads move the work. The planning sheet in the repo stays as it is. Ad hoc leave works the same way: `@Devin Ravi is on ad hoc leave today` gives Type **Ad hoc leave**.

**Unplanned leave counter.** The Scrum Master dashboard has an **Unplanned leave** tab next to the Vacation planner. It shows the Scrum Master's leave tracker: one row per team member, one column per sprint, with totals, the days in this sprint and this year, the latest days reported, and a read-only copy of every tab of the tracker workbook. Every sick day or ad hoc leave reported to Devin adds one day to the count, and Devin's reply says the new count. The days are kept in the **Unplanned leave** table on the Sprint Leave page.

![Vacation planner](manual-images/dash-vacation-planner.jpg)

*The Vacation planner tab, on every dashboard: who is away and who covers their stories, questions and approvals (demo data).*

**Group by.** Next to the chips, Group by puts the list under headings: Specialty or Epic. Specialty uses the same keyword rules as Defects by specialty, read from the story and its epic name. A story that matches no specialty goes under Foundational when it is work on Acme Claims itself that serves every specialty (a PostgreSQL upgrade, say): its epic or the story has the Foundational, CORE or Platform label, or a word from `.devin/rules/foundational-work.yaml`. Everything else goes under Misc, last. Epic shows the epic key and name, including closed epics and other teams' epics; stories with no epic go last. Pick Needs grooming first to see what still needs work per specialty or per epic. The choice is remembered in this browser. Each heading has **−** to fold its stories away and **+** to open them again, and **Expand all** / **Collapse all** above the list do every heading at once.

Every change is shown first as a **preview** of exactly what would be sent to Jira, with your name on it.
Nothing is written until Argus owner switches writes on (`SDLC_BACKLOG_WRITES=1`) and lists the
tickets it may touch (`SDLC_BACKLOG_TICKETS=ACME-…,ACME-…`); anything outside that list stays a preview
even then. Written changes carry a `requested-by-<you>` label and a comment, so the service account never
hides who asked.

## Devin Window: Argus in your own browser (`/devin-window`)

`/devin-window` runs Argus and your dashboard on the Devin Cloud machine and shows them in your
own browser, the way an X display used to put a remote program's window on your desk. Nothing is
installed on your PC and you need no key of your own: Jira and Confluence go through the team service
accounts that are already set up in Devin Cloud.

Type `/devin-window` in a Devin session. It starts Argus as you, builds your dashboard, and
gives you two preview links, one for Argus and one for the dashboard. They open in your
browser after you sign in to Devin. Anyone else needs write access to your session to open them.
Everything else you type into the same chat, as usual; the chat is your command box and Agent/Ask is
Devin's own switch.

The pages stay up while that session is awake. When it has gone to sleep, say `/devin-window` again;
Argus keeps its runs, so nothing is lost. `/devin-window status` and `/devin-window stop` do
what they say.

## Sharing the framework with another team

The framework can be handed to another team as one shared copy, with every team value (people, Jira,
Confluence, repos, hosts, ids) swapped for a made-up "Acme" example. `tools/build_distribution.py`
builds it from `tools/distribution_map.yaml` into `sdlc/kb/v<major>.<MMDDYY>/` (the major version and
the build date, for example `v2.101826` for 18 October 2026) and the same folder as `sdlc/kb/v<major>.<MMDDYY>.zip`.
Older dated folders stay as they are. The copy is not rebuilt with every PR: the tech lead rebuilds it by
hand once a month (a Devin reminder goes out on the 1st), so between rebuilds `--check` reports it out of date.
`--check` fails when the copy or the zip is out of date or a leak
scan finds a team value; `--test` installs the copy into a scratch repo and runs its own checks and tests.
The copy holds the skills, agents, playbooks, rules, templates, hooks, workflows, tools, Argus,
the KB prompts and this manual, Argus manual and the presentations (also together in `MANUALS/`).
It has no application code and no knowledge base: the other team builds its own with `/kb-build`.

The other team unzips it and runs `python3 install.py --target <their repo>` (in a Devin session or on a
PC). It asks for their values or reads them from a file, puts the skills, agents, rules and hooks into
`.devin/`, and runs the checks; they commit the result. Then
`python3 sdlc/framework/tools/register_playbooks.py` lists the playbooks as `!pb_<nn>_<name>` macros, and
with `--apply` and a service-user `DEVIN_API_KEY` creates them in Devin Cloud, or updates the ones that are
already there. The Jira and Confluence secrets are added by hand in Devin Cloud. The copy's `README.md`
has the full steps.

## Defect root cause and escape

The **Root cause** tab on the QA and Tech Lead dashboards lists every SIT and UAT defect open or closed in the last 30 days:
the story it is linked to, the stage that should have caught it (a SIT defect should have been caught by unit tests and code
review, a UAT defect by SIT), the root cause, and the files its fix changed that the link graph did not predict from the
story's files (the same measure as "Impacts missed" on the Change confidence tab). When someone closes a defect, Devin Cloud
asks them for the root cause, one of requirement, design, code, data, environment or test gap, and puts it on the defect as
a "Root cause:" comment after they say approved (`tools/defect_rca.py`).

## Feedback on the framework

After a gate brief or an artefact, Devin Cloud asks the person who read it one line: was this useful, yes or no, and why.
The answer goes into `SHARED/framework-feedback.yaml` after they say approved (`tools/framework_feedback.py`), never into
Jira. The Tech Lead dashboard's **Framework feedback** tab shows the yes and no counts per gate brief or artefact, the
least useful first, with the latest notes.

Anyone can also press **Feedback** on Argus top bar, next to Help. The form asks what kind it is (something went
wrong, an idea, or something that worked well), what it is about, and what happened. Nothing else is typed: the
Argus adds what it already knows, shown under *Sent with your feedback*. That is the page and ticket, the person's
open and recent runs (session link, stage, status, last error and what Devin last said), the status light, the problems
it noticed in the last day and its version. Send starts a short Devin run. The run adds one file under
`SHARED/workbench-feedback/` and raises a pull request into the working branch, then merges it straight away with no
review. If Bitbucket refuses the merge, the pull request stays open.

Argus also watches itself while people use it. It writes down failed Jira, Devin Cloud or Bitbucket calls,
requests the page sent and the server refused or failed, runs that ended in error or got no answer for 30 minutes,
Wake pressed three times on one run, the same action started twice in a few minutes, and script errors on the page.
The same problem again counts on the same line. Each line has a suggested fix (`console/observer.py`); one it does not
recognise says *needs a look*. These go with the next feedback, or once a day on their own.

The group shows both: **Team feedback** has what people sent, each with its session details. **Argus noticed** has
each problem with how often it happened, how many people hit it, their roles (no names), first and last seen, and how
to fix it.

The same group has a **Recommended changes** tab: framework changes the monthly Team Insights run recommends from how
the team uses Devin. Each one says what to change, why, how many sessions and people it comes from, the expected gain and
the skill, command or file it touches. It starts as *new*; you accept, reject or mark it done with
`python3 sdlc/framework/tools/team_insights.py recommend decide R-001 accepted --by "<your name>" --write`, and
only accepted changes go to the backlog.

## Team Insights

Once a month `/team-insights` (run by the monthly automation) reads every Devin session of the month, the team's and the
rest of the org's, with Devin's analysis of each one. The Tech Lead dashboard shows it in the **👥☁️ Team Devin Cloud Usage** group:

| Tab | What it shows |
|---|---|
| Overview | Sessions, people, ACUs, PRs and merged PRs, ACUs per merged PR, where sessions start and the kinds of work |
| Usage | Per person: sessions, PRs, messages per session, where and what. Tick the people you want to see; the choice is kept in this browser and applies to every tab |
| Cost | ACUs by kind of work, role and person. With `cost.usd_per_acu` set in `.devin/rules/scrum-master-metrics.yaml`, a **Show $** box adds the dollars; without it the tab shows ACUs only |
| Prompts | Prompting patterns with a better way to write each, and per person their prompt next to a better one |
| Skill gaps | Gaps with the lesson and the command to try, and repeated work a command, playbook or automation could do |
| Doing well | Wins, with the person's name |
| Learning plan | One file per person and month, by year › month › person: their learning list (open, taught, better), tips to give, questions for your one-on-one and a better prompt |
| Ask the team | This month's check-in answers: what helped and what got in the way |

Team numbers and the nameless findings are in the knowledge base (`SHARED/team-insights/<YYYY-MM>.yaml`). Each
person's learning plan is a file in the knowledge base too, `SHARED/team-insights/people/<YYYY>/<MM>/<devin user id>.md`.
It is named by the person's Devin user id and holds no name; the Learning plan tab shows the name from `people.yaml`
(people off the roster by their code name). Each month's plan carries over last month's list with its statuses and adds
the new gaps as open.

Devin teaches the list one item at a time: at the start of a session with someone on the roster it gives a short
lesson on their next open item (`team_insights.py teach next --person "<name>"`). When they say "got it" the item is
marked taught in their plan file. You can mark an item yourself with
`team_insights.py learned --person "<name>" --gap "<gap>" --status taught|better --write`.

Usage and ACUs per person stay off the repo: the monthly run attaches them to its session, and you bring them to your
PC with `python3 sdlc/framework/tools/team_insights.py import <file>`. Without that file the Usage and Cost
tabs show team numbers only.

The monthly deck, `REPORTS/team-insights/TEAM-INSIGHTS-<YYYY-MM>.html`, names the people behind the wins and nobody
behind the gaps: the month in numbers, well done, better prompts, what to learn next, repeated work to stop, and the
framework changes made from your feedback.

In Argus, **My tools → Team Insights** (Tech Lead) opens the decks page: the latest month's deck, every earlier
month, a link to the dashboard tabs and a button to run the month now.

## Audit evidence pack

At SDLC_05, `/pr-readiness` writes `{REQ}-STORY-{n}-EVIDENCE.md` to the session folder (`tools/evidence_pack.py`). It is one
file an auditor can read without the session: each gate with who signed it, their role, the decision and the time; the
claims and whether their evidence checked out; the test report and the /pr-readiness status; the Checkmarx, Wiz and GovRAMP
results; the independent verifier verdict; and the PR link. Anything it cannot find is listed under "Not found".

## Roles and routing

Devin Cloud's own roles (administrator, member, read-only) are permissions. The delivery roles the team
actually uses — delivery lead, solution lead, architect, UI/API/ETL developer, reviewer, QA lead, QA
engineer, UAT lead, UAT participant, BSA, BSA lead, product owner, manager, Scrum Master, release manager — live in
`.devin/rules/role-routing.yaml`, and who holds them lives in `.devin/rules/people.yaml`.

`/identify-requester` resolves who is asking, picks the right hat for the request (people wear several,
and the hat is chosen per request), then applies that role's dashboard lens, first-choice skills and
playbooks, and the shape the answer should take. It never grants or denies anything: authority stays
with Devin Cloud roles, Bitbucket branch protection, secret scoping and the approval gates.

`/roster-check` keeps the roster honest by reconciling it against Jira weekly and raising a pull
request when it drifts. The same drift appears on `/dashboard` for the roster resolver and the
backups, so nobody has to remember to look. Ownership, cadence and the change process are in
`sdlc/framework/ROSTER-GOVERNANCE.md`.

---

## Commands for every role: My commands, Skill config and Role config

Every skill is in one place, `.devin/rules/role-routing.yaml`, and every one is counted. A role's `default_skills` are its
first commands: the top of `/help` and of Argus's **My tools** menu, at most eight. Its `more_skills` are the
rest of its My tools, and `everyone_skills` are on everyone's. A skill that another skill or an automation runs is
internal to the system: the `internal_skills` list, the app-, db- and etl- documentation stages and the two older
names, `/console` and `/app-staleness-check`. Nobody is given those.

- **My commands**, on every dashboard: your first commands, the rest for your role, the ones for everyone, the
  pipelines with their stages, the internal ones and every other command, so nothing is buried.
- **Skill config**, on the Tech Lead dashboard: one row per skill, one column per role (Developer, Tech lead, Architect,
  QA, UAT, BSA, PO, Scrum Master, Delivery lead / manager, Release manager, Everyone). ★ is a first command, ✓ is in My
  tools, ◐ means some of the roles under that heading. A skill nobody has been given has every box empty; an internal
  one says why and has no boxes. The top line counts assigned, not assigned and internal.
- **Role config**, next to it: one row per person on the roster, one column per role. ● is the main role, ✓ another
  hat, and the last column shows the gates the person can sign.

![My commands on a developer dashboard: the first commands for the role, then the rest (demo data).](manual-images/dash-my-commands.jpg)

*My commands on a developer dashboard: the first commands for the role, then the rest (demo data).*

![Skill config on the Tech Lead dashboard: every skill against every role column (demo data).](manual-images/dash-skill-config.jpg)

*Skill config on the Tech Lead dashboard: every skill against every role column (demo data).*

Both tabs are on Argus actions page (My tools → **Answer, approve, hand over, change config**); the dashboard shows
the same tables read only. Click the boxes, press **Preview change**, then **Save**. Save sends the block to a Devin
run, which shows the change (`tools/skill_homes.py apply` or `tools/role_config.py apply`) and waits for you under Waiting on me. After you say
approved it raises a pull request from a `devin/` branch into `feature/devin-sdlc` on role-routing.yaml or
people.yaml. Save shows only on the actions page Argus opened; in a saved or
attached copy, paste the block into Devin instead. A people.yaml change is reviewed by the roster owner or a backup, and nobody
approves their own row. After it merges, `/roster-sync` copies it to the Confluence roster page. Once a session, after
the learn-more question, Devin adds a `Tip:` line with one of your role's commands, a different one each day
(`tools/skill_homes.py tip`), and it names the command when you ask for something a skill already does.

![Role config on the Tech Lead dashboard: the main role and the other hats per person, and the gates each can sign (demo data).](manual-images/dash-role-config.jpg)

*Role config on the Tech Lead dashboard: the main role and the other hats per person, and the gates each can sign (demo data).*

## Who signs each gate

Every gate in `.devin/rules/approval-gates.yaml` names the people who sign it, from the roster: Resource 16, Resource 5 Reddy
Resource 5 and Resource 17 for the BSA gates and the release gate, Resource 16 and Resource 17 for the PO gates, Resource 4 and Resource 5 Reddy
Resource 5 for the Tech Lead gates, with Resource 3 and Resource 6 as their backups. While someone is away, their
approval backup from the Time off and backups table signs in their place; when they named none, the next person named
on the gate does, then the gate's backups (`tools/gates.py approver_route`). The gate brief says who was routed and
why. The framework check fails a name that is not on the roster unless it is under `not_on_roster`, and those names
are a question for the roster owner.

The **Gate config** tab on the Tech Lead dashboard, next to Role config, shows this as a grid: one row per gate with its
timeout and what it blocks, one column per person on the roster. ● signs the gate and ✓ is a backup. Click the boxes,
press **Preview change**, then **Save** (in a saved copy, paste the block into Devin). The run shows the change
(`tools/gate_config.py apply`) and, after you say approved, raises a pull request on approval-gates.yaml. Every gate keeps at least one ●, and names that
are not on the roster are left as they are.

![Gate config: who signs each gate and who backs them up](manual-images/dash-gate-config.jpg)

## Where tests run for each person

The Acme Claims team tests in Devin Cloud only, so the team default in `.devin/rules/workbench-settings.yaml` is
**Devin Cloud VM**: the test pack runs on the Cloud VM, nothing runs on your PC, and Test on my PC is hidden. The
**Argus config** tab on the Tech Lead dashboard, next to Gate config, shows the setting for each person; pick a
choice, press **Preview change**, then **Save**, and after you say approved the run raises a pull request on
workbench-settings.yaml.

## Save instead of copy and paste

Opened from Argus, every page that makes a block for Devin has a **Save**
button: the dashboard's config tabs, Answers, Handovers, Approvals, Observations and Session handovers, the Backlog
grid, the review pages and the intake form. Save starts a run (or replies to the run the page came from). The run
shows the change and waits for your approval. Each Save has a **Dry run** tick, on by default: a dry run only shows
the change. Untick it to have the run write after you approve: repo files go through a reviewed pull request; Jira is
written only when Jira writes are on. A saved or attached copy of a page calls nothing, so it keeps the copy and paste text.

For a tech lead, a real Save (Dry run unticked) on Skill config, Role config, Gate config or Argus config is the
approval: the run doesn't wait for `approved` and raises the pull request straight away. The pull request is still
reviewed and merged in Bitbucket.

## Running Argus in Devin Cloud

Type `!argus` or `/argus` in a Devin Cloud session. Devin starts a separate host session titled
**RESERVED – do not type · Argus host · <your name>**, and gives you its preview link. Keep chatting in your own
session; the reserved one only hosts the page. The dashboard and the actions page open in a panel on the right;
Documentation opens in a new tab. Every session whose title starts with **RESERVED – do not type** is machine-only, such
as the Jira reader.

Open Argus in its own browser tab. Each run you start (Start SDLC, a tool, intake) is a new Devin session, and
the Devin page switches to that session, so Argus inside the Devin page's Preview tab goes with it. While Argus is
inside the Devin page, a bar at the top says so; **Open in its own tab** opens Argus in a new tab at the same
place, and starting a run from there opens that tab for you. In its own tab Argus stays where you are, and the
run's questions and approvals come to you there.

A run's **Messages** show only what Devin says to you and what you send. The step-by-step lines Devin reports
(`[SDLC] rule …`, `kb …`, `route …`) are under **Trace**.

If someone types in the host session anyway, Devin answers in one line and starts the bridge again in the same turn.
Meanwhile the status light turns amber and the page says **Devin Cloud is reconnecting**: your requests wait and go
through when it's back, so nothing is lost. Only if the bridge stays down for more than 5 minutes does the page say
it isn't running; then send the host session any message and Devin starts it again.

## Rules that always apply

- A stage never proceeds past an unsigned gate — gates are defined in `.devin/rules/approval-gates.yaml`.
- Nothing is inferred silently: unknowns are written as `[REQUIRES STAKEHOLDER INPUT]`.
- Business-facing skills (`/explain-capability`, `/feasibility-check`, `/what-if`, `/dashboard --lens bsa`,
  `/po-story-review`) never inspect code and never print file names, table names or SQL.
- Database discovery and the PowerShell hooks need Devin Desktop; everything else runs in Devin Cloud.

---
*Type `/help` for the short version of this catalogue.*

---

## Argus user guide

### 1. In short

Argus runs inside your own Devin Cloud session: type `!argus` or `/argus` and open the preview
link. Every Start SDLC, menu item, approval, answer and handover is a Devin Cloud session under your name, and the
page shows its result, its questions and the gate waiting on someone. Tests run in Devin Cloud too, so nothing runs
on your PC and nobody needs a Devin API key. Jira, Bitbucket and Confluence are reached only through the team's
service accounts.

**What it doesn't do.** It doesn't approve or merge pull requests. You do that in Bitbucket. Argus only
shows whether a PR is open, merged or declined.

#### What's in this manual

2. Find your way around
3. Work a ticket with Devin Cloud
4. Wrap up a ticket
5. My sessions: find, continue, archive, close
6. Pull requests
7. Approvals and questions in Jira
8. Backlog: groom, point, poker and sprints
9. Scrum Master follow-ups: leave, capacity, one story at a time, stand-up gaps
10. Trace: what a run loaded and decided
11. Help, settings, updates and pop-ups
12. How it works
13. If something goes wrong
14. Limits today
15. Future improvements
16. Decisions behind it
17. Open questions, assumptions, unknowns and sources

### 2. Find your way around

The page has a top bar and three columns. On the left are your Jira tickets (**My work**) or your role's tools (**What I do**), with **+ New requirement** at the bottom, which opens the box for a new requirement. The middle shows whatever you've opened: a run, a ticket or Test on my PC. With nothing open it shows **Today**: one line on top with how many things need you and how old the oldest approval is, then what is waiting on you (a run's questions can be answered on the card with **Answer here**), what to approve (an approval past its time limit in approval-gates.yaml is marked overdue), your running sessions (with the runs that finished or fell asleep since you last looked), and sprint health: the tickets in your list by status, and how many have no points, nobody assigned or no change for 5 days or more. Product owners, BSAs and Scrum Masters get the same cards, with sprint health from their ticket list or the Backlog. On the right is **To approve**, with the run's documents, diffs, PR, skills and chat underneath. The right column folds to a thin rail with an arrow, and the number of approvals waiting, when it has nothing in it, and on screens up to 1200 px wide; it opens by itself when a gate is waiting, and the rail opens it.

The home page fits on one screen with no scrolling; a card with more rows than fit scrolls inside itself. The **help bar** along the bottom says what to do first, and when you point at something (or move to it with the keyboard) it explains what that thing does: a menu, a card, the ticket list, + New requirement or the right column. The **?** at its end opens this section.

![Argus home: My work and What I do tabs with the ticket list on the left, the Today cards Waiting on you, To approve, Your sessions and sprint health in the middle, and the folded To approve · Documents rail on the right](manual-images/workbench-02-workbench-home-ticket-list-on-the-left-w.jpg)

*The home page. Waiting on you shows "–" because Jira has not been checked yet; Check now reads it.*

**Top bar**

| In the top bar | What it's for |
|---|---|
| **Backlog** | Groom, point, play planning poker, move stories between sprints, clone, add notes, log hours, and draft epics and stories. Every Jira change is a preview first. Section 8. |
| **Dashboard** | Your role's dashboard. It's built by a short Cloud session, so it takes a minute or two. |
| **My tools ▾** | The single tasks your role uses most, under plain names such as Plan a story or Run the test stage, each with its command beside it. Type in the box at the top to find one, or press **Ctrl+K** for quick search. Tools about you and Argus itself are last, under **About you and this Argus**. What's on offer depends on your role. For PO office, BSA and Scrum Master roles, **On the Backlog screen** opens **New epic or story**, **Plan the sprint**, **Sprint calendar** and **Scrum Master follow-ups** (section 8, section 9). |
| **Knowledge base ▾** | **Look things up** (Ask a question, Explain a capability) for everyone. **Keep it current** (refresh after a release, find drift, settle open questions) for solution leads, architects and managers. **Reference → Delivery teams** opens the page of the other Acme Claims delivery teams (`SHARED/ACME_DELIVERY_TEAMS.html`, built by `tools/delivery_teams.py` from `SHARED/delivery-teams.yaml`); the same page is the Delivery teams tab on the Tech Lead and PO office dashboards. |
| **Waiting on me ▾** (with a count) | Your inbox: your runs that are waiting on you, the Approval and Question sub-tasks assigned to you in Jira, session updates (a run that finished, failed, fell asleep or got a reply from Devin Cloud since you last opened it) and your Reminders (hours, one story at a time, idle stories, due dates). The count covers what needs an action from you, not session updates; the browser tab title shows the same number; it shows a dash until Jira has been read once, and … while Devin Cloud is reading it. Section 7. |
| **My sessions ▾** (with a count) | Your Argus runs and chats, their stage and PR state, archived ones too. Section 5. |
| **Status light** (the dot left of Help) | Green when Jira and Devin Cloud both answer, red when one doesn't, grey before the first check. When one fails, a bar under the top bar says which in plain words, with **Show details** for the exact error and **Retry**. Click the dot to show or hide the bar. |
| **Help ▾** | This manual, the tour, keyboard shortcuts, the words used on the page, and About. Section 11. |
| **Your name and role ▾** (top right) | Who you are, the look (Acme Claims, earth, dark), What I sent today and the settings: the floating Trace window, updates, desktop pop-ups, and, folded, which role to view Argus as. Section 11. |
| **Menu ▾** (screens up to 1200 px wide) | The same menus as above, folded under one button. |
| **Back with Cloud: ACME-…** (only when needed) | A test has finished, but you were typing, so the page didn't switch on its own. Click it when you're ready. |

#### Ticket lists

The list at the top left picks which Jira tickets you see. Cloud reads them from Jira, and Argus keeps the result until you ask for a fresh read with Refresh or Check now. Type in the filter box to narrow the list by key or words. Under the list it says how long ago Jira was read, for example "updated 2 min ago"; the Backlog, Waiting on me and My sessions show the same.

**Ticket lists**

| List | Shows |
|---|---|
| Assigned to me · this sprint | Acme Claims tickets assigned to you in an open sprint, in any status. |
| Assigned to me | Your unresolved Acme Claims tickets in any sprint, most recently updated first. |
| All current sprint tickets · Acme-Claims-Web | The team's stories, bugs and tasks in the open sprint. |
| All open · Acme-Claims-Web | The team's unresolved stories, bugs and tasks in any sprint. |
| Ready for QA · Test Ready, Testing | Team tickets in those statuses, for QA testers. |
| Ready for UAT · Ready for UAT, UAT, Staging | Team tickets in those statuses, for UAT testers. |
| Automation tickets assigned to me | Your unresolved Acme Claims tickets with "Automation" in the title, the same list as the Automation queue on the dashboard. The Automation engineer role opens on this list. |
| All open automation tickets | Every unresolved Acme Claims ticket with "Automation" in the title, whoever it is assigned to. |

#### What else is on the page

- **When Jira can't be read**, My work keeps the last list this browser read, marked "As of <time>, Jira not reachable". Only the bar under the top bar explains the outage; the panels say "Jira isn't reachable right now" in grey. The status light also covers **Bitbucket** (checked when Argus looks for updates).
- **Waiting on me → History** (folded at the bottom) lists every approval, question, finished run, reply and team chat message from before, with its time, even if the desktop pop-up was missed. **Clear** empties it. Only things that need you are counted and get a pop-up: "Approval needed · ACME-…", "Question for you · ACME-…" and team chat. A plain reply from Devin Cloud goes to History quietly.
- **Search** (top bar, or Ctrl+K) finds any tool, ticket key or session.
- **Answer, approve, hand over, change config** (top of My tools and of Waiting on me) opens every action in one panel on the right: questions, approvals, Jira and session handovers, observations, and the Skill, Role, Gate and Argus config tabs. Generate a block, tick or untick Dry run, and press **Save**; the run shows the change and waits for your "approved". For a Solution lead, a real Save on a config tab is the approval and the run raises the PR, which is still reviewed and merged in Bitbucket. **Close** shuts the panel; **Open in a new tab** gives it its own tab.
- **Everything for this ticket**: an opened ticket has one row of buttons for all its work: **Approve** or **Answer questions** when its run is waiting on you, **Continue the last run**, **Groom, point or poker** (the Backlog screen on that ticket), **Hand over or answer** (the actions panel) and, for leads, **LOE estimate**.
- **My tools** shows the first six tools for your role, then **All tools (N more)**. Typing in its box searches every tool, by name or by command.
- **LOE estimate** (My tools, for the Delivery lead and Solution lead roles): give a Jira key, a Confluence link or the requirement text. Devin runs the org's LOE playbook (`!loe`): requirement, gap and impact analysis, epics and stories, story points per layer with a 10% buffer, a staffing plan and a timeline, in one HTML report. It only reads; nothing is written to Jira or code.
- **My sessions** has filters (All, Needs you, Running, Finished), a **Find a run** box, the ACUs each run used, the total for this week, and **Close N finished or idle sessions**, which ends finished sessions and ones asleep for more than a day after you confirm.
- **My tools → Dashboard** opens your role's dashboard in the panel on the right. On the What I do screen (Product Owners, BSAs, Scrum Masters and Managers) it is the **Dashboard** button in the top bar. The dashboard only reads: it pulls everything together and has no buttons that change anything; every action is in Argus. **My tools → Stand-up summary** lists yesterday's runs, today's tickets In Progress and what is waiting on you, with **Copy**.
- **Pin** (the star on a ticket) keeps it at the top of My work.
- **Getting started** on the home screen lists the first steps (who you are, Jira answering, one dry run, the Dashboard) until they're done or hidden.
- **Help → Search the manual** opens this manual at the first match.
- Team chat folds to a **Chat** button until you open it or a message arrives. The hint bar shows for your first five days, or until you close it with **×**. Test on my PC is hidden when your mode is Off or Cloud VM.

#### Quick search and keyboard shortcuts

**Ctrl+K** opens quick search on any screen. Type part of a tool's or knowledge base item's name, a ticket key or title, a session or a person, and press Enter to open it. A person starts a team chat message to them; a green dot means their Argus is open. Up and down move through the results; Esc closes the box. Tickets come from your ticket list and, once it has been opened, the Backlog.

![Quick search: the box with acme-19 typed and the matching tickets listed under Tickets](manual-images/workbench-22-quick-search-tools-tickets-sessions.jpg)

*Quick search with part of a ticket key typed.*

| Key | What it does |
|---|---|
| **Ctrl+K** | Quick search: tools, knowledge base, tickets, sessions and people |
| **/** | Puts the cursor in the filter of the list on screen |
| **↑ ↓** | Move through a list: tickets, the Backlog, tools or a menu |
| **Enter** | Open the ticket, session or tool |
| **Esc** | Close a menu or a box |
| **?** | Shows this list |

#### Help on each screen and the tour

The **?** next to a screen's title opens this manual at that screen's chapter. The first time Argus opens on a PC, and for the New joiner role, a five-step tour shows the top bar, My work, the middle, To approve and the menu under your name. **Your name ▾ → Take the tour** shows it again.

### 3. Work a ticket with Devin Cloud

1. **Start.** Pick a ticket on the left and press **Start SDLC**, or type a new requirement in the box at the bottom left. Leave **Dry run** ticked to see what would happen without pushing anything. Each run is its own Devin Cloud session working in the background, and you stay on the ticket: a note confirms the start, and the ticket shows **This ticket's run** with a progress bar, the current stage and anything waiting for you. Argus never switches you to the session. Devin tests the story in Devin Cloud; leave **Bring to local** unticked. Before the PR, `/implement` runs the security scans: GovRAMP access-control checks, plus Checkmarx and Wiz once their access works (until then they show as not run).
2. **Follow it.** **Open the run** on the ticket shows a progress bar, the stage rail (intake → research → plan → implement → test → release → KB refresh), the questions waiting for you at the top, Devin's messages and **Open in Devin**. The step-by-step lines (stage, agent, skill, gate) are not shown there; **Trace** has them. Replies show within seconds while the page is open.
3. **Answer its questions.** When the session asks numbered questions, they appear as a form on the ticket and at the top of the run page, outside the scrolling messages. Fill it in and send it, and the session carries on.
   **The ticket's text stays as it is.** Once SDLC has started on a ticket, nothing in Argus or the run changes its description or acceptance criteria. On the ticket a run only moves its status (In Progress), adds sub-tasks, logs hours, adds comments and asks for approvals; a proposed change to the description or acceptance criteria goes on the ticket as a comment for the PO or BSA.
4. **Approve or forward a gate.** When a stage needs a human decision, the gate shows under **To approve** on the right, with the documents to read. Approve it, send it back with reasons, or press **Forward…** to send it to someone else as a Jira Approval sub-task (section 7).
   **Sub-tasks before coding.** The last gate before code changes (SDLC_04, or HOTFIX_PLAN_CODE_APPROVAL for a hotfix) shows **Add sub-tasks to <story> before coding starts** when the run has a Jira story. Tick it to see the sub-tasks Devin suggests from the routing map (the standard DEV set until Devin has posted its suggestions). Each row has a title, an original estimate in hours and a technical description: the files and functions to change, what changes in each, the tests, and the acceptance criteria it covers. You can edit all three, add rows with **+ Add sub-task** and remove them with ×; the total is underneath. When the story already has sub-tasks, each one shows as a row with Devin's suggested change, if any; tick **Update <key> in Jira** on the ones you want changed, and the rest are left as they are. When you approve, a box lists what will be created and what will be updated, with each estimate, and asks **Update Jira?**; nothing is written until you press **Yes, update Jira**. New sub-tasks are created under the story with the original estimate, the description, the AI-Used label and you as assignee; ticked ones get the new title, estimate and description. This happens before any code is changed. In a dry run Devin only lists them and writes nothing to Jira. Leave the box unticked to approve without adding sub-tasks.
5. **Wake it.** A session that has gone to sleep does no harm. Answering, approving or pressing **Wake** starts it again from where it stopped.
6. **Archive, close or delete it.** These are under **More ▾** next to Refresh on the run page. Each one asks first, in a box that names what it does; Delete is in red.

**Roles.** What the menus offer depends on your role in the team roster. QA and UAT testers get Test on my PC as well as developers. Roles only change what you're offered by default. What you're actually allowed to do still comes from Devin Cloud, Bitbucket and the approval gates.

The Automation engineer's `/dashboard` shows, loudest first: automation tickets assigned to you, the ones that have not
moved for a week, your branches in the test automation repo (your `ACME_Automation_<your Jira user>` branch and any
branch you last committed to, with commits to merge and how far `Test_Bamboo` has moved on, red when a branch needs
updating or conflicts), what is queued for test, every open automation ticket on the team, the defects you raised and
those waiting for your retest, and defect root cause.

#### Automation screen (automation engineers)

People whose role is Automation engineer get **Automation** in the top bar. It writes and runs test automation for a ticket in the test automation repo, in Devin Cloud: the app and the browsers run on the Cloud machine, so nothing is installed on your PC.

- **Ticket, or what to automate**: the story or its automation sub-task; picking a ticket in My work fills it in. With no ticket, describe the work instead, for example `Contract screen – bulk upload negative cases`. An **Acceptance criteria** box then opens: type one check per line, or leave it empty and Devin drafts them from the screen, the existing tests and the app code for you to confirm at Gate 1. A run with no ticket works on branch `feature/AUTO-<short name>`, writes nothing to Jira, and puts its summary in the pull request. Set up and Run tests never need a ticket: Set up needs only the base branch, and Run tests needs only the tags.
- **Base branch**: the branch new automation starts from and its pull request goes back into. The list is `automation.base_branches` in `.devin/rules/sdlc-profile.json` plus your own `ACME_Automation_<your Jira user>`. Argus remembers your choice.
- **Tags to run** and **Browsers at once**: what Run tests runs, and how many browsers run side by side on the Cloud machine (1 to 4). No Selenium Grid is needed, and `@Local` scenarios (bulk upload, download) run there too.
- **Steps**: eight boxes show where the ticket stands: 1 Setup, 2 Scan & plan, 3 Gate 1, 4 Write, 5 Run, 6 Triage, 7 Coverage & AC matrix, 8 Push & PR. Each box says not started, working (with a pulsing dot), waiting for you, done (✓) or failed (✕), and moves on as the Cloud session reports progress; the screen checks every few seconds. Gate 1 and Push & PR have dashed borders: they wait for you. Click a box to open the session doing that step, or, for a step nobody has started, to start it. The same boxes are at the top of each automation session's page.
- **Buttons**, one Devin Cloud session each:

| Button | Skill | What it does |
|---|---|---|
| Set up | `/acme-auto-setup` | Repo on the base branch, Python, the app with Snowflake through MCP, smoke test |
| Automate this story | `/acme-auto-story` | Reads the ticket or your description, answers the automation template's questions from the code, the app and Snowflake, stops at **Gate 1** ("Can I start writing the automation?"), then writes, runs and reports an AC traceability matrix |
| Run tests | `/acme-auto-run` | Runs the tags, one browser or several |
| Triage failures | `/acme-auto-fix` | Finds why scenarios failed; fixes the test, or drafts a defect when the app is wrong |

Nothing is committed until you say **push**; Jira defects are only drafted unless you ask. The same four skills are behind the `!auto_setup`, `!auto_story`, `!auto_run` and `!auto_fix` playbooks. **Sessions for this ticket** lists the automation sessions you started for it.

### 4. Wrap up a ticket

Development, QA and UAT each have their own story in Jira, so "done" means done for this story. The wrap-up box appears on the test card after Return to Cloud. It never moves anything on its own.

#### Cloud checks nothing is left

The check starts by itself after Return to Cloud. You can also press **Check everything is done**. The ticket's Cloud session looks at four things: the newest evidence has 0 failed, and a reason for every not-run item; the PR exists and nothing has been pushed since the tested commit; there's no open question, unsigned gate or waiting step in the session; and which statuses the Jira ticket can move to next. It only reads during this check, so nothing changes yet.

The box then says either **Ready** with a short summary, or **Not ready** with the reason. When it's not ready, there's no Jira move on offer. Fix the reason and press the check again.

#### Pick the next Jira status, or leave it

Each button is one of the ticket's real Jira transitions, as Jira reported them, for example Ready for Review, Ready for Testing or Ready for Approval. **Leave as is** changes nothing. When you click a status, Argus asks you to confirm, and then Cloud makes exactly that one move with the team service account. The box then shows "moved to …".

![Wrap-up box: Ready, evidence passed, PR 2779 open, nothing waiting; Jira buttons Ready for Review, Ready for Testing, Ready for Approval and Leave as is](manual-images/workbench-11-wrap-up-box-ready-evidence-passed-pr-277.jpg)

*Cloud says the ticket is ready and offers the ticket's own Jira transitions.*

#### Decide what happens to the session

- **Continue** keeps the session as it is, for example when Cloud still has release work to do for the story.
- **Archive** hides it from your lists. It can still be woken up and continued later (section 5).
- **Close** ends the Cloud session for good. You can still read it in Devin, and its run record and evidence stay in Argus.

You confirm Archive and Close before they happen.

![Wrap-up box after the Jira move: moved to Ready for Review; Session buttons Continue, Archive and Close](manual-images/workbench-12-wrap-up-box-after-the-jira-move-moved-to.jpg)

*After the Jira move, the box offers what to do with the session.*

### 5. My sessions: find, continue, archive, close

**My sessions ▾** lists your Argus runs and chats. Each one shows its stage, whether it's waiting for you, and its PR state once that's been checked. **Reload from Devin** reads the list again.

**Continuing a session.** Open it and reply, answer, sign or press **Wake**. It carries on from where it stopped, with everything it had. If a session has ended, start a new one with `/resume-session REQ-…`. It rebuilds where the requirement is from its gate records, and `/status` tells you what's next and who acts.

**Archive** is in the wrap-up box and on the run page. It tags the session `sdlc-archived` and hides it. **Show archived (n)** at the bottom of the menu brings archived sessions back into the list, marked "archived". Open one and press **Unarchive** to return it to normal. Archive doesn't end the session in Devin.

**Close** is in the wrap-up box and on the run page. It ends the session in Devin, after you confirm.

**Exit** is at the far right of the top bar. It lists the Devin Cloud sessions Argus started for you that are still open. Ticked ones are ended for good, then Argus stops and the tab shows "Argus is closed". Sessions waiting on your answer or approval start unticked, because an ended session can't be woken again. **Exit, keep sessions open** stops only Argus. If a session can't be ended, Argus stays open and says which one. Closing the tab without Exit ends nothing.

**Delete** is on the run page, and as **×** next to each of a story's Previous runs. After you confirm, it ends the Devin session if it is still running and removes the run from Previous runs and from My sessions for good.

The SDLC sessions for a story never close or archive by themselves. The short helper sessions Argus starts close themselves when they're done. Those are the Jira list reads, PR state checks, Dashboard builds and sub-task replies, plus one-shot menu actions.

![My sessions menu with Reload from Devin and a run with its stage, dry run and start time](manual-images/workbench-13-sessions-menu-with-reload-from-devin-run.jpg)

*My sessions with one run. Archived runs stay listed with their stage under Show archived, so they can be continued.*

### 6. Pull requests

**My sessions ▾ → Check PR state** starts a short, read-only Cloud session that looks up the PR of each of your sessions in Bitbucket. It takes under a minute: four PRs took about 25 seconds. Each session row then shows **PR #n open**, **merged** or **declined**, and so does the **PR** tab on the run page.

Reviewing, approving and merging happen in Bitbucket. Argus has no Merge or Approve button and holds no Bitbucket token. It doesn't show a PR's approvals or merge conflicts either.

To have someone approve the SDLC code-review gate (SDLC_05), use **Forward…** on the gate (section 7). That approves the gate in the SDLC. They still approve the PR itself in Bitbucket.

### 7. Approvals and questions in Jira

#### 7.1 Send an approval or a question to someone

When a run waits on a gate, press **Forward…** on it, pick the person and add a note. The session runs `/send-approval`. That creates a Jira Approval sub-task under the story and assigns it to them. The sub-task carries the brief, the documents, the numbered decision items and the PR link. The session then waits for their decision.

Questions for a reviewer go the same way through `/ask-question`, as a Jira Question sub-task.

#### 7.2 See what's assigned to you

**Team chat** is the row at the bottom right of Argus. Type `@` and pick a name from the roster (or type the first name or AD ID), then the message, and press **Send**. `@everyone` sends it to everyone on the roster. It reaches that person's Argus within a few seconds, and their reply pops up in the window above the row; **Chat** shows or hides today's messages, and clicking a message starts a reply. While the window is hidden, or the tab is in the background, **Chat (N)** and the tab title count the unread messages, and a desktop pop-up shows them if pop-ups are on. In the name list, a green dot marks people whose Argus is open now; they are listed first. Both people need their Argus open in Devin Cloud. A message is up to 200 characters and is kept for 12 hours, the last 8 per person. It goes on as a tag on the sender's own Devin Cloud session, like team poker: no Devin agent wakes, and nothing goes to Jira or Teams. Tags are not private, so keep anything sensitive for Teams.

**Waiting on me ▾** has four parts. At the top are your runs that are waiting on you. Under **Assigned to you in Jira** are your open Approval and Question sub-tasks, oldest first. Under **Session updates** are the runs that finished, failed, fell asleep or got a reply from Devin Cloud since you last opened them; opening a run clears it, and **Mark all read** clears them all. Each one shows its key, whether it's an Approval or a Question, the parent story, who raised it, its Jira status and a link to Jira. Under **Reminders** are the gaps on your own tickets in the active sprint, read once a day with the Jira service account (Check now reads again): hours not logged on a story In Progress or on a closed AI-Used sub-task, more than one story In Progress at a time, a story with no change for `idle_working_days` working days (`.devin/rules/scrum-master-metrics.yaml`), a story In Progress past `story_days_hint` days with no due date, and a story whose sub-tasks are all closed. Each has **Open in Jira** and **Dismiss for today**; the due-date and close-story ones also take an answer, which **Send** puts on the ticket as a comment (and the due date) when Backlog writes are on (`SDLC_BACKLOG_WRITES=1`), otherwise it shows the Jira change only. The same reminders show on the landing screen. The badge on the menu counts the parts that need an action: your runs, Jira sub-tasks and Reminders.

The list is read through Devin Cloud when Argus opens and then every 30 minutes, but only while you are using the page: a hidden tab or a PC left idle for an hour is not checked. Press **Check now** to read it straight away, which takes about a minute. The header shows how long ago it was checked. A new sub-task gives a desktop pop-up if pop-ups are on.

![Waiting on me menu: Assigned to you in Jira, checked time and Check now; an Approval ACME-18820 and a Question ACME-18821, each with its story, reporter and status](manual-images/workbench-14-waiting-on-me-menu-assigned-to-you-in-ji.jpg)

*Two sub-tasks waiting: an Approval with **Approve or reject…**, and a Question with **Answer…**. Jira was stubbed out for this screen.*

#### 7.3 Answer a question

1. Press **Answer…**. The box shows the question in full, with **Open in Jira**.
2. Type your answer and press **Send answer**, then confirm.
3. A short Cloud session writes your answer on the sub-task with the team service account. It records you as the person who answered. The row then shows "answered".

![Question box: the question text, Open in Jira, Your answer field and Send answer](manual-images/workbench-15-question-box-the-question-text-open-in-j.jpg)

*Answering a Question sub-task from Argus.*

#### 7.4 Approve or reject

1. Press **Approve or reject…**. The box shows the brief and the link to Jira.
2. Press **Approve**, or **Reject** with a note saying why. A rejection needs a note. Then confirm.
3. Cloud records your decision on the sub-task, and the run that sent it carries on or goes back for changes. The row shows "approved" or "rejected".

![Approval box: the brief, Open in Jira, a note field and Approve, Reject and Cancel buttons](manual-images/workbench-16-approval-box-the-brief-open-in-jira-a-no.jpg)

*Deciding an Approval sub-task. This approves the SDLC gate, not the Bitbucket PR.*

**Nothing is answered or decided for you.** Every answer, approval and rejection is something you typed or clicked, and then confirmed. Argus only sends it if the sub-task is in your own latest list from Jira, which stops anyone answering a sub-task that isn't theirs.

### 8. Backlog: groom, point, poker and sprints

The **Backlog** tab in the top bar is where Product Owners, BSAs and Scrum Masters do their day-to-day Jira work from buttons. It shows the team's groomable stories, read page by page from Jira (up to 1,000), with the count, and says when Jira holds more.

**Every change is a preview first.** The header says **previews only**. Each button shows the exact Jira change it would make, and nothing is sent unless Backlog writes are switched on for Argus and the ticket is on its allow-list (section 14). Every change names the person who asked for it, with a `requested-by-<user>` label and a comment, so the shared service account never hides who did what.

#### 8.1 The list

- **Filter** by key, title, sprint or epic. **Refresh** reads Jira again.
- **Needs-attention chips** narrow the list: Needs grooming, Unassigned, No AC, No points, Over 13 points, No epic, No release, Misc (no specialty) and No update 30 days.
- **Group by** Nothing, Specialty or Epic. Stories without a specialty fall under Misc, and foundational work has its own Foundational group. Epics outside the open list still show their names.
- Every story shows its specialty and epic.
- **Bulk actions** show once at least one story is ticked.
- **Sprint moves.** Tick stories, pick **Move to…** a sprint and press **Preview move**. **Set order** records the order the selected tickets must ship in, as Jira "Blocks" links.
- **Change on all selected.** Tick stories, pick Points, Sprint, Epic or Assignee and its new value, and press **Preview for N**. One box lists the change for every ticket. **Send to Jira** (or **Record preview** while writes are off) makes it one change in the Previews list, with a comment on each ticket.
- **View ▾** holds Saved views, Group by and Sort.
- **Saved views.** Set a filter, chip, grouping and sort, type a name such as "No AC in next sprint" and press **Save view**. Saved views are kept in this browser and picked from **Saved views…**. **Copy link** copies a link that opens the Backlog with the same view, to share in a grooming call.
- **What I sent today** (menu under your name) lists the changes you made from the Backlog screens since midnight, each with its Jira links and whether it was written to Jira or kept as a preview.

![Backlog: three stories ticked, Points chosen with 3, and the combined preview listing the change for each ticket with Record preview and Cancel](manual-images/workbench-23-backlog-change-on-all-selected-preview.jpg)

*Change on all selected, while Backlog writes are off.*

#### 8.2 Groom a story

- Pick a story to see its description and acceptance criteria next to the grooming tools. Both are boxes you can edit in place; what you type stays while the list refreshes.
- **Rewrite AC.** Devin rewrites the acceptance criteria as numbered business outcomes, and lists the build steps, table names and test steps that belong on sub-tasks, the description or QA's scenarios instead. When the ticket doesn't say something an outcome needs (who the user is, which screen, how it is confirmed), Devin asks first: the questions open in a window, and your answers go back for the final AC. **Use this AC** puts it in the box, where you edit it. It is one read-only Devin session; nothing goes to Jira from it.
- **Suggest acceptance criteria.** For a story with no AC, Devin drafts acceptance criteria and its own estimate. **Use as AC** puts the draft in the box. Devin's estimate stays hidden until the reveal, and the team's number is the one that stands.
- Pick the points (or type another number), and change the **Sprint** or **Fix Version** if they should move. The Fix Version box offers the releases already on the team's stories. Changes are one story at a time.
- **Save this story.** **Preview changes** lists what you changed: description, acceptance criteria, points, sprint and Fix Version. **Save to Jira** sends them in one update with a comment in your name; AC from Devin also get the `suggested-acceptance-criteria` label. A sprint change is moved on the board with the same Save. In practice mode (Backlog writes off for the story) **Save to Jira** shows grayed out; **Preview changes** still shows what would change.
- Clone the story or add notes, each as a preview. Sub-task estimates default to add up to the story's estimate.
- **Raise** a question or clarification (a sub-task under the story), an observation, a defect (linked to the story) or a risk, and **Log hours**, are on the story for QA, UAT and developers. Grooming roles (PO, BSA, solution lead, lead, manager) don't see them here. What you can raise follows your role: QA and UAT raise defects too. TennCare SIT and UAT defect titles get their prefix on the preview, for example `SIT-TC-PCMH: …`.

#### 8.3 Planning poker

- The PO or BSA starts a round on a story and names the voters, or leaves the list blank for anyone. Invited people vote from their own Argus.
- Devin plays its own card from the complexity matrix, shown in red. Its reasoning sits behind **Show Devin's reasoning**.
- The facilitator picks a timer, or none (the default), and can press **End vote** at any time. Then they reveal the votes.
- When the votes differ, a discussion box shows Devin's challenges. The team agrees a number, and any dissent is recorded next to it.

#### 8.4 New epic or story, and the sprint screens

These open from **My tools ▾ → On the Backlog screen**. Each has **Back to grooming**.

Default sub-tasks follow the story's phase. A DEV story gets DEV- Analysis of the story, Design, Backend implementation, Frontend implementation, Unit and integration testing, Code review and PR, Deployment readiness and Documentation / KB update, plus DEV- Performance validation when the story names a performance target. A title ending “- SIT” gets QA's seven SIT sub-tasks, and “- UAT” gets UAT- Demo and sign-off.

**Backlog screens**

| Screen | What it does |
|---|---|
| **New epic or story** | Pick Epic with stories, Epic, Story or Epics from a roadmap. Type what is needed, or upload Word, PDF, Excel, CSV, PowerPoint, text or images, then press **Start intake**. Devin asks its intake questions first. With **Dry run** ticked you get the epics and stories as a Markdown file and nothing is written to Jira. Untick it to create them in Jira with the files attached. Epics from a roadmap runs `/epics-from-roadmap` on the PO's spreadsheet. You can also paste meeting notes and press **Draft from notes**. The title, description and numbered acceptance criteria are drafted, and **Rule-book check** checks them against the Jira rule book before **Preview create**. A specialty, or Foundational, is required on an epic. |
| **Plan the sprint** | Capacity against velocity, what to pull in from the backlog, what to push out, the load per person, and stories to split. |
| **Sprint calendar** | Sprint dates, the active sprint, points committed against velocity, and release dates. Click a sprint to go back to grooming it. |
| **Scrum Master follow-ups** | Sprint leave and the capacity it leaves, the stories in progress, what is missing before stand-up, and who is over capacity. Section 9. |

### 9. Scrum Master follow-ups: leave, capacity, one story at a time, stand-up gaps

#### 9.1 Sprint leave and capacity

- Leave is kept on the Confluence page **Acme Claims Sprint Leave**, one table per sprint. Pick the sprint at the top.
- The grid has one row per team member, with their **% on project** and one box per working day. Click a day to mark it off. Tick **No leave** when someone has said they take none, and add a **Note** for a half day or a public holiday.
- Each row works out **Days in** and **Hours**: days in × productive hours × % on project. The totals give the team's hours and points (hours ÷ 8).
- **Not answered yet** lists who hasn't given their leave for the sprint. A sprint that isn't on the page yet starts from the roster.
- **Save to Confluence** writes the sprint's table to the leave page. **Download capacity sheet** gives the same numbers as an Excel sheet in the Scrum Master's capacity format.
- The Scrum Master dashboard's Commitment panel reads the same leave page.

#### 9.2 In progress: one story at a time

- **More than one story In Progress**: each person with more than one, with a nudge asking them to finish one first and move the others back to To Do, or raise a Question sub-task if one is waiting on someone.
- **In Progress, nothing changed for N working days or more**: stories that aren't moving.
- **Waiting on a question or approval, should be On Hold**: stories with an open Question or Approval sub-task that are still In Progress.
- **On Hold**: stories on hold, and **On Hold, nothing left to wait on**, with **Back to In Progress** once the last question or approval is closed.
- A story moves to On Hold while it has an open Question or Approval sub-task, and back to In Progress when the last one closes. On Hold stories don't count against "one story at a time". Each move is a preview, like the rest of the Backlog tab.

#### 9.3 Before stand-up: what is missing in the sprint

- Each gap in the active sprint, with the owner: a story with no sub-tasks; a story or sub-task with no AI label, or the wrong case; an AI-Used sub-task with no original estimate, closed with no hours, or logged over its estimate; a story In Progress with no time logged; a story still open when every sub-task is closed; a story closed while sub-tasks are still open.
- **Add AI-Used** or **Add AI-NA** sets the label in the exact case and takes a wrong-case one off. **Set estimate** sets the original estimate in hours.
- **Draft nudge** opens a comment for the owner that you can edit, then **Add as a comment**.

#### 9.4 Capacity: who is over, who hasn't answered

- **More points than their capacity after leave**: each person whose story points in the sprint are more than their hours from the leave page ÷ 8, with a nudge asking how they plan to handle it.
- **Not answered about leave yet**: who has marked neither a day off nor No leave, with a message to send them in Teams.
- Labels, estimates and comments are previews until Backlog writes are on.

![Scrum Master dashboard, Over-committed tab: each person's sprint points against their capacity after leave](manual-images/workbench-17-scrum-master-dashboard-over-committed-ta.jpg)

*Over-committed**: sprint points against each person's capacity after leave.*

![Scrum Master dashboard, Leave tab: a grid of team members by sprint day, with Off on the days they are away](manual-images/workbench-18-scrum-master-dashboard-leave-tab-a-grid-.jpg)

*Leave**: who is off which day this sprint, read from the Sprint Leave page, and who hasn't answered yet.*

### 10. Trace: what a run loaded and decided

The **Trace** tab in the right column shows, stage by stage, what the open run loaded and decided. It's built from the `[SDLC]` lines the session prints, and each line stays under the stage that printed it.

**What the trace shows per stage**

| Branch | What it shows |
|---|---|
| Agents, skills, playbooks | Which ones the stage ran. |
| Routing | Which routing-map entry the requirement matched. |
| Knowledge base | The KB files the stage read, and the ones it skipped. |
| Rules | The rules it applied. |
| Matrix chains | The cross-layer impact chains it followed. |
| Ontology | Each lookup in the Acme Claims ontology: the command and the term, what it found, **why** the stage used the ontology, and the **gain**. The gain is something you can check, such as registries not opened, ETL tables the matrix doesn't list, or open questions found. Example: `find "TIN group" — Provider Group → CL_PG, 7 screens; why: the requirement says "TIN group", not a table; gain: one lookup instead of the four registries, no question to the BSA`. |
| Decisions | What the stage decided and why, including where the code didn't match what the ontology said. |
| Link graph | Each `walk` through `ACME_LINK_GRAPH.yaml` from a changed table, endpoint, screen or file: what it reached in N hops, why, and the gain, such as a screen the routing map didn't name. |
| Drift checks | The cited file:line lines the stage re-read, and whether each link is **current**, **moved** or **stale**. A stale link is flagged, not trusted. |
| KB sync | `kb_sync.py` before the PR: the matrix, ontology, link graph, QA-suite coverage and KB manifest, each **current**, **updated** or **not run**. |
| QA suite | What was read from the QA repository `ACME/claims-qa` (read only), with its branch and commit: feature files, scenarios, step definitions, query keys and TestData sets. For a drafted scenario, how many of its steps match the suite's step library. |
| Evidence | The plan's claims and how many are verified against the file:line, graph id or KB path they cite. An unverified claim warns until 2026-12-08 and blocks SDLC_04 from 2026-12-09. |
| Tests picked | The tests the graph walk picked for the test pack, and whether each one ran. Behave scenarios are marked for QA. |
| Contract checks | The columns in the changed SQL checked against the table registry, the data contracts and the validation rules. The live Snowflake check shows **not run** in Devin Cloud. |
| Gates | The gates the stage presented. |

![Argus with a run at Plan; the Trace tab lists Agents, Skills, Knowledge base, Matrix chains, Ontology, Link graph, Drift checks, QA suite, Evidence and Tests picked](manual-images/workbench-19-workbench-with-a-run-at-plan-the-trace-t.jpg)

*The Trace tab for a run at Plan: each branch says what was read, why, and the result.*

- **Download trace (all stages, .txt)** saves the whole trace as plain text.
- **Your name ▾ → Trace → Open the trace window** opens the same trace in a floating window. You can drag it aside, minimise it or close it while you work on the run.

### 11. Help, settings, updates and pop-ups

**Help ▾** is on the top bar, next to the menu under your name and role, which holds the settings.

- **Help → Documentation** opens this manual in a new tab, served by Argus itself from `sdlc/framework/reference/HELP.html`, which is built from this file. It shows the copy on `feature/devin-sdlc` when Bitbucket can be reached, and the copy in your checkout when it can't.
- **What I sent today** lists your Backlog changes from today, with their Jira links (section 8.1).
- **Help → Take the tour** shows the five-step tour of the page again.
- **Help → Keyboard shortcuts** lists the shortcuts (section 2).
- **Help → Words used on this page** explains run, Start SDLC, approval (gate), Waiting on me, dry run, Bring to local and preview.
- **Help → About** shows the framework version and the date of the last commit. `/help about` in a session says the same.
- **Trace → Open the trace window** shows the open run's trace in a window you can drag aside, minimise or close (section 10).
- **Check for updates now** asks Bitbucket straight away and offers the update if there's something new. Argus also checks on its own every 2 minutes while the tab is open, after Return to Cloud and when you come back to the tab.
- **Build shared copy** (only for the people on `act_as.allowed` in `.devin/rules/sdlc-profile.json`) builds the copy of the framework for other teams. Type the version (for example 2.2.110126). **Check here** builds it in a temporary folder on your PC with `build_distribution.py --scratch`, runs the leak scan and gives you the zip to try; your checkout doesn't change. **Build and open PR** starts a Devin Cloud session that runs `build_distribution.py --version <v>` on a devin/ branch, shows the leak count and the copy's checks, and opens the PR into `feature/devin-sdlc` after you type approved. Nothing builds on its own.
- **Background refresh.** The page keeps itself current with one clock: one call every 5 seconds for runs and PC tests while you use it, every 30 seconds while the tab is in the background, and three times slower after ten minutes without a click or key. None of it reads Jira or starts a Devin Cloud session; the ticket lists are read from Jira only the first time, on Refresh and on Check now.
- **Desktop notifications** turns the Windows pop-ups on or off (section 6.4).
- **View Argus as** makes the whole Argus work as the role you pick, as if someone in that role had opened it: the ticket list in the left column opens on that role's list (for example Automation tickets assigned to me for Automation engineer, Ready for QA for QA), and the screens, menus, dashboard, gate checks and the Devin sessions you start from the page follow that role. Each session is told the person and role picked. "My own role" is the default, and the roles marked "yours" are the ones the roster gives you. Picking another person under **Who are you** goes back to that person's own role.

![Your name menu, lower part: Trace, Argus updates with Check for updates now, Desktop notifications, and View Argus as with a list of roles](manual-images/workbench-20-settings-menu-workbench-updates-with-che.jpg)

*The settings part of the menu under your name.*

![Your name menu, upper part: Who you are, Switch look, What I sent today, Help with Documentation, Take the tour, Keyboard shortcuts and Words used on this page, and About](manual-images/workbench-21-help-menu-with-documentation.jpg)

*Help. Documentation opens this manual.*

### 12. How it works

1. **You** use one browser page, served by Argus inside your own Devin Cloud session (`!argus` or `/argus`). [E: console/server.py]
2. **Argus** starts runs, chats and short helper sessions, sends messages, uploads evidence and reads each session's messages. In Devin Cloud it does this through your host session: each call goes to `~/.sdlc/console/bridge/outbox`, the bridge loop in that session runs it with the session's own tools, and the sessions it starts are child sessions under your name, with no API key. Every 5 seconds one search asks Devin Cloud which of your open runs changed, and those runs are read straight away, whatever their status, so a new question or gate shows within about 5–10 seconds. A run with no change is read again once a minute at most. [E: console/bridge.py, console/server.py Poller]
3. **Cloud** pushes the PR branch and the test pack to Bitbucket. It's the only part that touches Jira, through the team service account. [E: console/server.py CLOUD_JIRA_TAG, TASK_REPLY_TAG]

#### 12.2 The sessions Argus starts

**Session tags**

| Tag | What it is | Ends |
|---|---|---|
| `sdlc-workbench` | An SDLC run or a single task started from Argus | Only when you press Close |
| `workbench-chat` | A plain chat from the chat panel | When you close it |
| `workbench-assistant` | One session a day, "Argus assistant — <you> <date>", that answers your chats and menu questions | When you end it; closing a chat closes only its card |
| `sdlc-workbench-seat` | Your host session in Devin Cloud. Team poker votes and team chat messages are tags on it | When that session ends |
| `sdlc-jira-read` | One session a day, "Argus Jira reader · <you> · <date>". Each read of a ticket list or your sub-tasks is a message to it, and one read brings all your own lists. Results are kept until you press Refresh or Check now | By itself, when the day changes |
| `sdlc-pr-state` | Looks up PR state, read-only | By itself |
| `sdlc-dashboard-build` | Builds the Dashboard | By itself |
| `sdlc-task-reply` | Writes one answer or decision on one Jira sub-task | By itself |
| `sdlc-archived` | Added by Archive; hides a session in Argus | Doesn't end it |
| `closed` | Added by Close, which ends the session in Devin | Ended |

[E: console/server.py lines 108–131, 640, 792, 901, 1030]

#### 12.3 Where things are kept

**Where things are kept**

| What | Where |
|---|---|
| Bridge calls in Devin Cloud | `~/.sdlc/console/bridge/` (`outbox`, `inbox`, `alive`, `host`) on your session's machine |
| Evidence runs and zips | `~/.sdlc/evidence/{REQ}-{STORY}/{commit}/` |
| Run records, cached lists, sub-task replies | `~/.sdlc/console/`, for example `task-replies.json` |
| SDLC session state and gate records | `~/.sdlc/sessions/{OWNER}/{REQ_ID}/` |
| Jira and Bitbucket service credentials | Devin Cloud secrets only; never in the page |

### 13. If something goes wrong

**Troubleshooting**

| You see | What it means and what to do |
|---|---|
| Amber bar: Devin Cloud is reconnecting | Someone typed in the host session; it starts the bridge again by itself. Wait: requests go through when it's back. |
| Red bar: the bridge is not running | The host session has been down for more than 5 minutes. Send any message to the RESERVED Argus host session (or type `/argus` there); the page picks up again on its own. |
| A ticket list or Approvals says "Devin Cloud is reading Jira…" | A short Cloud session is reading Jira. It takes about a minute. The session link shows what it's doing. |
| Ready for QA or Ready for UAT is empty when it shouldn't be | The Jira status names in the list may not match the board. Tell Argus owner which statuses your tickets are in. |
| "Check out the PR branch" fails | Your git can't fetch from Bitbucket. Run **Check my PC** and fix the Bitbucket line first. |
| "Open the evidence run" says the commit doesn't match | Cloud pushed code after writing the test pack. Ask Cloud in the chat to refresh the pack, then start again. |
| "Check nothing is left unpushed" stops | The ticket folder has local commits. Push them or ask Cloud to take them, then press Return to Cloud again. |
| "Devin session still initializing" | Argus retries for about two minutes by itself. If it still fails, press **Hand back only** once the evidence is in. |
| **Update Argus** refuses | A test is running, or your checkout has local changes. Finish the test or clear the changes, then try again. |
| Wrap-up says Not ready | Read the reason: a failed check, a missing PR, a push after the test, or an open question or gate. Deal with it, then press **Check everything is done**. |
| "ACME-n is not in your Jira list; click Check now" | The sub-task wasn't in your latest Jira list, for example because it was reassigned. Press **Check now**. |
| No desktop pop-ups | Turn them on in the menu under your name, and allow notifications for the page in the browser. Pop-ups only show while the page is in the background. |

### 14. Limits today

- **One APM.** The ticket lists, the repo and the Jira service account are all APM0000000 (Acme Claims, Acme-Claims-Web). [E: console/server.py] [?4]
- **Jira lists are as old as the last read.** A list is read once and kept until you press Refresh or Check now, because each read goes through the day's Cloud reader session and takes about a minute. [E: CLOUD_JIRA_TTL = 0]
- **PR state only.** The PR panel shows open, merged or declined. It doesn't show approvals or conflicts, and each check is a short Cloud session. [E: console/server.py CLOUD_PR_TAG]
- **Cloud replies are read, not pushed.** While a page is open on a session, or waiting for an answer to something you sent, Argus reads that session every few seconds. [E: WATCHED_SECONDS, REPLY_WAIT_SECONDS]
- **Backlog writes are off by default.** The Backlog tab shows every change as a preview. It only writes to Jira when `SDLC_BACKLOG_WRITES=1` is set and the ticket (or its epic) is in `SDLC_BACKLOG_TICKETS`. [E: console/backlog.py]
- **The Jira writes are new.** Post to Jira, the wrap-up Jira move, and answering or deciding a sub-task were tested with Devin Cloud and Jira stubbed out. Watch the first real use of each. [A3]
- **Archive is Argus's own.** Archive is a tag and a filter. The session still shows as normal on the Devin website. [E: v3 archive call returned 403]

### 15. Future improvements

None of these are built. The first group can be built with code and data the repo already has. The second needs access or a decision from someone else first.

#### 15.1 Ready to build

**Ready to build**

| Idea | What it would do | Why we think it's buildable |
|---|---|---|
| **Environments view** | Show what's running in dev, SIT, UAT and prod, and flag a prod image-tag PR that's waiting for the Release Manager. | `promote_check.py` already reads the deploy repo. `manual-steps.yaml` lists both RELEASE-ENV-REPORT and PROD-TAG-PR-WATCH as "nothing new" needed. |
| **Release readiness per fix version** | One page per release: every ticket, its PR state, evidence, gates and open defects, ending in go or no-go. | The PR panel, evidence history, gates and `gen_release_tests.py` each exist; nothing groups them by fix version yet. |
| **Raise a defect from a failed check** | A **Raise defect** button on a failed evidence row that fills in the defect from that check's evidence. | **Raise → Defect** on a Backlog ticket already creates a defect linked to the story (section 8); the evidence row only needs to fill it in. |
| **Tidy old sessions** | A view of sessions that have waited a long time, with Close and Archive on each. | Close and Archive exist; the Dashboard's "Stale" panel only looks at Jira tickets. |
| **Continue from the stage** | A Continue button that sends the next step from `gates.py next` into the same session, or starts `/resume-session` if the session has ended. | Both pieces exist and are run by hand today. |
| **Review view** | A PR's commits and diff, read with your own git login, with an Open in Bitbucket link to approve and merge there. | Argus already fetches the branch with your git. |
| **The `devin_implemented` label** | Add the team's label to a Jira ticket once Devin has implemented it. | The convention is in the team's notes; nothing applies it yet. |
| **APM switch** | Pick the APM, and the ticket lists, Jira project, IT team, repo, Devin org and service accounts follow. Left out of this build by Resource 3's decision. | Needs APM0000001's details, which aren't written down anywhere the work can read. [?4] |

#### 15.2 Needs something from someone first

**Needs something first**

| Idea | What's needed | From whom |
|---|---|---|
| **Run the tests in Cloud** (SIT-TEST-RUN) | An `ARTIFACTORY_TOKEN` secret and browser access to SIT from Devin Cloud | Platform team |
| **Share-drive to KB sync** | SharePoint read access for Devin Cloud | SharePoint owners |
| **Batch job status** | A network route to the DataLake RDS reader and a read-only service ID | Platform and DBA teams |
| **SonarQube and Checkmarx next to each PR** | Service accounts that can read both | DevSecOps |
| **Change request for prod** | Whether prod releases need a change ticket, and in which tool | Release Manager |
| **PR approvals and conflicts in the PR panel** | A Bitbucket API route that works from Cloud or the PC | Bitbucket admins |
| **Scheduled sweeps** | Confirm `/gate-timeout-check` really runs daily as a Devin automation. `/roster-sync` is run by hand by the tech lead when the roster changes | Resource 3 |

### 16. Decisions behind it

**Jira goes through Cloud.** The PC never holds a Jira key. Reads and writes are short Cloud sessions with the team service account. That costs about a minute each time.

**Bitbucket stays in charge of PRs.** No Merge or Approve in Argus, so Bitbucket's approval and branch rules always apply, and the merge is recorded under the person who did it.

**Nothing happens by itself.** Jira moves, closing, archiving, answers and approvals are always a click and a confirm. Helper sessions are the only ones that end on their own.

**Archive and Close are different.** Archive hides a session but keeps it resumable. Close ends it.

**One folder per ticket, one zip per run, one Cloud session per ticket.** The evidence goes back to the session that wrote the code, so Cloud can check it against the PR head.

**Control is passed as plain messages.** Anyone can read who had the branch and when.

### 17. Open questions, assumptions, unknowns and sources

#### Open questions

**Open questions**

| Question | Owner |
|---|---|
| Which future improvements should be built first? The suggestion is the environments view, release readiness and raising a defect from a failed check. | Resource 3 |
| Keep "All open" in the ticket list? | Resource 3 |
| The UAT participant role is marked read-only, but sending evidence writes to the Cloud session. Is that acceptable? | Resource 3 |

#### Assumptions

**Assumptions**

| ID | Assumption and why | If it's wrong |
|---|---|---|
| A2 | Each tester's git can fetch the repo from Bitbucket with their own login. | "Check out the PR branch" fails until git access is set up. |
| A3 | The Jira writes behave against real Jira as they did against the stub, because they use the same service account and scripts as the rest of the framework. | The first real use shows an error in Argus and in the Cloud session. |

#### Don't know

**Unknowns**

| ID | Unknown | Who can answer |
|---|---|---|
| ?4 | APM0000001's Jira project, team, repo, Devin org and service accounts | APM0000001 owner |

#### Sources read

- Code at `feature/devin-sdlc` `0bea3c98`: `sdlc/framework/console/server.py`, `console/pctest.py`, `console/static/index.html`, `console.js`, `console.css`, `tools/evidence.py`, `tools/tests/test_workbench.py`, `.devin/config.json`, `.devin/rules/`, `.devin/skills/test-on-pc`, `send-approval`, `ask-question`, `resume-session`.
- For the Backlog, Scrum Master follow-ups and Trace sections: `console/backlog.py`, `console/static/index.html`, `console.js`, `console/server.py` and `tools/sprint_leave.py` at `feature/devin-sdlc` `a6410096`.
- Git history of `feature/devin-sdlc` since it was cut from `develop`, read with `git log --first-parent` and `git diff --numstat`.
- The Cloud session devin-0000000000000000000000000000e7c1: the `[SDLC]` messages and Resource 3's decisions, 1–3 October.

### Appendix: how much work went into this

All of this was built on one branch, `feature/devin-sdlc`, by Devin working with Resource 3. The branch was cut from `develop` on 15 September 2026. The figures come from its git history at `0bea3c98`.

| Measure | Number | What it means |
|---|---|---|
| Pull requests merged | 79 | 17 Sep to 3 Oct, plus 39 direct commits such as roster syncs |
| Code | ~23,000 | lines of Python, JavaScript, CSS and scripts |
| Unit tests | 195 | about 4,000 lines |
| Knowledge base | 596 files | about 448,000 generated lines |

#### Lines added, by kind

**Lines of code**

| What | Lines added | Files |
|---|---|---|
| Code: Python | 18,468 | 43 |
| Code: JavaScript, CSS, shell, cmd | 4,459 | 14 |
| Tests | 3,970 | 20 |
| Skills, agents, playbooks and docs (Markdown) | 35,381 | 274 |
| Rules and config (YAML, JSON) | 6,815 | 42 |
| HTML pages (exec deck, presentation and others) | 8,280 | 7 |
| Templates and other | about 1,100 | 6 |
| **Written by hand** | **about 78,500** | **406** |
| Knowledge base and generated files | 447,555 | 598 |

#### What the framework holds

**Framework inventory**

| Part | Count |
|---|---|
| Skills (slash commands) | 111 |
| Agents | 15 |
| Playbooks | 38 runnable, plus 2 docs |
| Human approval gates | 11 |
| Rule files (gates, roster, roles, dashboard, Jira, security and more) | 18 |
| Dashboard panels | 33 |
| People on the roster | 22 |
| Shared KB prompt files | 63 |
| Templates / workflows / hooks | 12 / 10 / 7 |

#### Pull requests per day

September: 17th 5, 18th 2, 19th 6, 21st 2, 22nd 1, 23rd 5, 24th 6, 25th 5, 28th 3, 29th 10, 30th 9. October: 1st 2, 2nd 17, 3rd 6. That's 79 PRs on 14 days, with commits on 18 days in all.

## Guide for Product Owners, BSAs and Scrum Masters

### Getting started

*Devin does the legwork in Jira, Confluence and the team's documents. Product Owners, BSAs and Scrum Masters get to spend their time on the decisions.*

#### The first session

1. Log in to Devin Cloud and start a new session. Everything is already set up.
2. Type a command such as `/dashboard`, or just ask a question in plain English. Devin knows who each person is from the team roster.
3. Read the answer and ask follow-up questions. When Devin needs a decision, it asks.

#### Where the work happens

Product Owners, BSAs, Scrum Masters and Managers work from the **Argus** (`/argus`, or `/devin-window` to open it from Devin Cloud). Their screen shows a **What I do** list on the left, grouped by job:

| Role | Groups |
|---|---|
| Product Owner | Plan, Groom, Sprint, Demo and release, Mine |
| BSA | Shape, Groom, Answer, Mine |
| Scrum Master | Daily, Sprint, Health, Mine |

Each task opens a screen with buttons: the Backlog, Grooming prep, Plan the sprint, the sprint calendar, the Scrum Master follow-ups, or a single-task Devin Cloud session such as the roadmap or a sprint review summary. Developer controls (Test on my PC, Start SDLC, the stage rail, diffs, PRs and the trace) are not on these screens. **Dashboard** in the top bar opens the role's dashboard, read only, in the panel on the right. Someone with several roles sees the buttons, menus and approvals of every role they have, each item once. With only business roles, for example Product Owner and BSA, the tasks of each role are in one What I do list. With a business role and a delivery role, for example Manager and Reviewer, the tickets and developer controls stay, and the What I do tab lists the business tasks above the tools.

The **dashboard** (`/dashboard`) groups its tabs the same way as Argus list, with **Reference** for anything else, and each tab has a **Do this in Argus** link that opens the matching task. Its buttons still work; a lens with `read_only: true` in `.devin/rules/dashboard-roles.yaml` shows the same tabs without them. The groups and tasks are kept in `.devin/rules/business-screens.json`, so the two always match.

#### Three ways to ask

**Say what is needed** (Everyone). Type:

```
/start "The care coordinators want to change thresholds themselves"
```

Devin returns: Devin works out what kind of request it is, starts the right step, and says what happens next and who has to act.

**A command** (Everyone). Type:

```
/dashboard
```

Devin returns: The dashboard for the requester's role: the backlog, the approvals and questions waiting on them, and how the sprint is going.

**A plain-English question** (Everyone). Type:

```
Which stories in this sprint are still waiting on a business answer?
```

Devin returns: A short list from Jira, with a link to each story.

#### How the pages work

Some answers come as a page attached in the chat: the dashboard, the Backlog grid, intake questions, epic plans and reports. Every page works the same way: look it over, change anything that is wrong, then select **Approve and send**. The page gives a short block of text with a **Copy** button; paste it into the chat. Devin then shows exactly what will change and waits for the word `approved`.

Trying things out is safe. Nothing reaches Jira or the knowledge base until the requester replies **approved**.

### Plan the year and quarter

*Product Owners turn the roadmap into epics and test ideas before the team commits to them.*

#### Examples

**See the roadmap** (Product Owner). Type:

```
/product-roadmap
```

Devin returns: The year plan (what was delivered, what is due this year, what moved to next year) next to a live sprint grid of the stories each epic has planned.

**Turn a roadmap sheet into epics** (Product Owner). Type:

```
/epics-from-roadmap roadmap-2027.xlsx
```

Devin returns: A review page with one card per roadmap row. Each card shows Devin's open questions and has Upload document, Edit and Approve buttons. The ready epics are created in Jira once the Product Owner replies **approved**.

**Test an idea** (Product Owner). Type:

```
/feasibility-check "Add a program year filter to the Member Journey page"
```

Devin returns: What Acme Claims already does, what is missing, a T-shirt size, the main risks and a recommendation.

**Think through a rule change** (Product Owner). Type:

```
/what-if "ProgramA members with fewer than two visits leave the program"
```

Devin returns: A short memo: what would change, who is affected, which downstream systems would see different data, and whether it needs a sprint or only a configuration change.

#### Risks and dependencies

**Risks and dependencies for an epic** (Product Owner). Type:

```
/dashboard
```

Devin returns: The **Risks** tab on the PO office dashboard: the open risks for each epic (likelihood, impact, owner, mitigation) and the dependencies on other teams (which team, what is needed, by when, owner), late dependencies first, then risks by likelihood times impact. `/epics-from-roadmap` asks for them when an epic is drafted. A risk or dependency named in the chat is saved to the knowledge base, not Jira, once the requester replies **approved**.

### Shape a requirement

*BSAs and Product Owners turn a request, an email or a document into epics, stories and sub-tasks that are ready for the team.*

#### The New flow, step by step

1. **Source.** In Argus, pick **New epic or story** under Groom. Choose a new epic, stories under the selected epic, or sub-tasks under the selected story. Drop documents into the chat, add a Confluence link, or paste the request.
2. **Questions.** Devin reads the source and how Acme Claims works today, then asks only about what is still unclear, one question at a time. With each question it shows **What Devin found** and **Your answer affects**, in business terms: members, programs, thresholds, reports, approvals.
3. **Draft.** Devin lays out the epic, its stories with acceptance criteria and points, and the team's standard sub-tasks. Each item shows whether it passes the Jira rule book. Any field can be changed, stories can be added or removed, and a story that is too big can be split.
4. **Approve.** Send the draft, check the exact Jira changes Devin shows, and reply **approved**.

#### Other examples

**Start a requirement in the chat** (BSA). Type:

```
/intake "Coordinators need to override a practice threshold with a reason"
```

Devin returns: The business questions, then a specification with acceptance criteria for sign-off.

**Understand a capability** (Everyone). Type:

```
/explain-capability "How are program thresholds set today?"
```

Devin returns: A plain answer about what Acme Claims does today, with where the answer came from.

**Check compliance** (BSA). Type:

```
/compliance-view HIPAA
```

Devin returns: Which Acme Claims features touch protected health information (HIPAA), quality measures (HEDIS) or financial controls (SOX), in plain English.

#### Two enterprise playbooks for BRDs

Two playbooks shared across Acme help with a Business Requirements Document. Start a Devin session and type the macro.

**Write a BRD by talking it through** (PO, BSA). Type:

```
!brd_helper
```

Devin returns: Devin reads the project's documentation, asks you to describe the need in your own words, sums up what it heard and asks a few simple questions at a time: who uses it, what done looks like, why it is needed and by when. It then writes the BRD and publishes it to the team's Confluence space.

**Turn a BRD into Jira tickets** (PO, BSA). Type:

```
!brd_to_jira
```

Devin returns: Epics, one to five stories per epic and the sub-tasks for each story, checked against a definition of ready and shown for review before anything is created. Every ticket carries the BRD link and the `devin_created` label.

For Acme Claims, take the finished BRD into the New flow above: drop its Confluence link in as the source. The New flow builds the tickets the Acme Claims way (DEV, SIT and UAT stories, the team's standard sub-tasks, the AI-Used or AI-NA label and the Jira rule-book checks) and writes a **Source BRD** line on the epic, its stories and their sub-tasks. `!brd_to_jira` and the New flow use the same 8-step sub-task pattern. Acme Claims spreads it over the three stories: Analysis, Design, Development, Unit and integration testing, Performance validation (when there is a performance target) and Deployment readiness on the DEV story; QA's seven sub-tasks, regression included, on the SIT story; Demo and sign-off on the UAT story. Tickets made by `!brd_to_jira` still need grooming against the Acme Claims rule book before they go into a sprint.

The business intake uses business language only. The development team adds the technical detail later, once the story reaches them.

### Groom the backlog

*The Backlog screen in Argus (Groom → Backlog) is one screen for grooming and everyday ticket work. Select a ticket on the left and its details open in the middle. The dashboard's Backlog tab lists the same tickets, read only.*

#### Ready for a sprint

Before an epic's stories go into a sprint, check the epic has:

- two or three sentences on who benefits and what changes for them;
- a link to the BRD or Confluence page with the detail;
- two to six measurable business outcomes as its acceptance criteria;
- its specialty, or Foundational;
- dependencies on other teams named, with a contact;
- stories for what the user sees and for performance, security and access needs;
- open questions answered, or listed with who will answer them.

The Groom view flags the first three. Whether Acme Claims also needs business impact, a due date, cost of delay, a t-shirt size, WSJF priority and a funded Work ID on every epic is an open question for the Product Owners and Scrum Master.

Devin stops and asks about a story, rather than deciding, when the acceptance criteria are vague, a dependency has no contact, the story can be read more than one way, it looks too big for one sprint, it contradicts its epic or a linked ticket, or it is unclear which screen, report or feed changes. `/po-story-review` and `/grooming-assistant` list these as questions for you.

#### On the screen

| Part | What it does |
|---|---|
| Filters | Choose stories, epics or defects, show only what needs grooming or only stories flagged for a demo, and group by specialty or epic. Search by ticket key or title. |
| Tick boxes | Select several tickets to move together. Move lists the current and upcoming sprints and the backlog. |
| Groom | Shows how the ticket measures up to the Jira rule book, with the description and acceptance criteria open for editing. |
| Point / poker | Shows the points Devin suggests from the team's complexity matrix. Set the points straight away, or start planning poker with chosen team members. |
| Edit | Change the title, description, acceptance criteria or epic. |
| Move, Clone, Hold | Move to another sprint or the backlog, copy a ticket with the standard sub-tasks, or put a story on hold with a reason. |
| Split | Appears on stories of 13 points or more. Devin suggests smaller stories to approve. |
| Demo | Appears on stories labelled DEMO-NEEDED, marked 🎤. Book the demo with a date and audience, or record it as given, which takes the label off. Once the story's PR is approved, Devin also records the demo by itself: it runs each acceptance criterion with captions on screen, saves one video per criterion in Confluence under Acme Claims Demo Recordings > epic > story (`ACME-123_AC1_demo` and so on) and adds one Jira comment with the link. When a defect linked to the story is fixed, it records v2 beside v1 so you can see what changed. It never changes the label. |
| Add note | Adds a comment to the ticket, plus any files dropped into the chat. |
| + New ticket | The New flow described under Shape a requirement. |

#### Grooming prep

**Groom → Grooming prep** in Argus (Product Owner and BSA) gets everything ready for the next grooming call. It reads the backlog, the year plan (`context/roadmap/year-plan.yaml`) and the teams in `SHARED/delivery-teams.yaml`, and shows six steps:

| Step | What it shows | Button |
|---|---|---|
| 1. Roadmap: this sprint and next | Stories and points per epic in the current and next sprint | |
| 2. Roadmap items with no story yet | Year-plan rows due this year that no open story or epic matches by title words, with up to three similar stories | Copy the similar story, or Write new |
| 3. Not ready to groom | Next-sprint stories, and stories labelled needs_grooming or needs_split, with what is missing: acceptance criteria, points, or a split at 13 points or more | Groom |
| 4. SIT and UAT stories missing | DEV stories in the current sprint with no SIT story (due next sprint) or no UAT story (due the sprint after), and SIT stories not yet in a sprint | Create SIT story, Create UAT story, Move |
| 5. Who to invite | The UI team core (Product Owner, Scrum Master, Dev lead, Solution Lead, testers), the reporter and assignee of each story, and partner teams the story or its epic names, with their contacts and DLs | |
| 6. Agenda, group chat and backup plan | An agenda for the invite, a must-attend message for Teams, and the stories that need only the UI team | Copy |

Every button shows the Jira change as a preview first. Devin Cloud cannot send the invite or start the Teams chat, so the agenda and message are drafts to paste. The rules behind steps 2 and 5 (how close a title must be, which words bring in a partner team, the DLs) are in `SHARED/grooming.yaml` and are listed on the screen as assumptions until the Product Owner confirms them; her questions are in **Learn about who you serve**. The dashboard's **Grooming prep** tab shows the same six steps without buttons.

#### Examples

**Groom before refinement** (Everyone). In Argus, pick **Groom → Backlog**, filter to Needs grooming, open a story, select Groom, fix the acceptance criteria and preview the change.

**Run planning poker** (Product Owner). Do:

```
Open ACME-18710, select Point / poker, then Start poker and choose who votes
```

Devin returns: Each person picks a card and sends it to the facilitator. Nobody sees the cards until the reveal, and then the agreed points are saved.

**Move work between sprints** (Everyone). Do:

```
Tick three stories, select Move, pick the sprint from the list
```

Devin returns: The Jira change for all three stories, made once the requester replies **approved**.

**Book a demo with the business** (Product Owner). Type:

```
/dashboard
```

Devin returns: The **Ready to demo** tab lists every story labelled DEMO-NEEDED, grouped by sprint. Each sprint is a collapsible group showing how many stories it has and how many are recorded; the newest sprint is open, and Expand all / Collapse all open or close every group. The **Demo recorded** column links to the story's demo page on Confluence "Acme Claims Demo Recordings" once /demo-needed has published it, otherwise it says Not recorded. **Demos coming up** lists the flagged stories still in progress. On the Backlog tab, open the story, select Demo, give the date and audience, and send. Devin adds a comment to the story once the requester replies **approved**. After the demo, Demo given takes the label off with a comment naming the date and audience. The invite itself is still sent from Outlook.

Devin always shows the exact Jira update before making it, and each ticket records who asked for the change.

### Check progress

*Everyone can see where the work stands without building a report by hand.*

#### Examples

**Start the day** (Everyone). Type:

```
/dashboard
```

Devin returns: A view made for the person's role: approvals waiting, the current sprint, open SIT and UAT defects, items waiting on a business answer, work that has stalled, and the Backlog.

**Prepare for stand-up** (Scrum Master). Type:

```
/dashboard
```

Devin returns: The Scrum Master view: what to raise at stand-up, cycle time, commitment against capacity, defect removal efficiency, and AI adoption and efficiency. The **Scrum Master's day** tab explains each one and its target.

**Find tickets that need tidying** (Everyone). Type:

```
/jira-hygiene
```

Devin returns: Tickets that don't yet meet the Jira rule book, grouped by what is missing, with the owner of each.

**Defects by specialty** (Product Owner). Type:

```
/defects-by-specialty
```

Devin returns: Open SIT and UAT defects grouped by specialty (EOC, Maternity, CHF, THL, ProgramA, ProgramB, ProgramC, PCMH), with who is working on each and when it is planned to ship.

**Legacy migration** (Product Owner). Type:

```
/migration-status
```

Devin returns: A review page showing how much of OldClaims, OldBilling and OldCare has moved into Acme Claims, module by module, with Edit, Download PDF and Approve buttons.

### Scrum Master's day

*The Scrum Master view on the dashboard shows what to raise at stand-up each morning and how the sprint is tracking against the team's targets. Devin Cloud reads every number from Jira, so it can be checked first thing in the morning. The Boost view in Tableau remains the number of record. Targets are as of 13 October 2026.*

#### Before stand-up

**What to raise at stand-up** (Scrum Master). Type:

```
/dashboard
```

Devin returns: The **Stand-up check** tab: one row per gap, with the person to ask. It lists stories with no sub-tasks, sub-tasks with no AI label or the label in the wrong case (for example AI-USED), and AI-Used sub-tasks that have no estimate, were closed with no time logged, or logged more time than estimated.

**Who is carrying the sprint** (Scrum Master). Type:

```
/dashboard
```

Devin returns: The **Workload** tab: each person's hours in the active sprint against the hours they have, marked light, heavy or overloaded.

**Who is working on what** (Solution lead, Manager, Delivery lead). Type:

```
/dashboard
```

Devin returns: The **Team activity** tab: one row per person on the roster with their Jira stories, bugs and sub-tasks in progress in the active sprint, how many are still to do or done, and the Devin Cloud sessions they used in the last 7 days, each with its state and the story it belongs to. People with no Devin Cloud id in people.yaml are marked instead of guessed. Product Owners on the PO office view do not get this tab.

**Work that has stopped moving** (Scrum Master). Type:

```
/dashboard
```

Devin returns: The **Not moving** tab: anything in progress that hasn't been updated for two weeks. Work on hold and items waiting on a question are left out.

**Stories in progress** (Scrum Master). Type:

```
/dashboard
```

Devin returns: The **Cycle time** tab: every story in progress and how many days it has been open, the stories on hold and for how long, and anyone with more than one story in progress at once.

**Gaps Argus can fix** (Scrum Master). Type:

```
/dashboard
```

Devin returns: The stand-up check also lists stories and sub-tasks with no AI label (or the wrong case), stories In Progress with no time logged on them or their sub-tasks, and stories whose status does not match their sub-tasks. In Argus, **Add AI-Used** or **Add AI-NA** sets the label, **Set estimate** sets the hours, and **Draft nudge** writes a comment for the owner that you can edit first. Each one is a preview until Backlog writes are switched on.

**Reminders asked to the ticket owner** (Scrum Master). Type:

```
/dashboard
```

Devin returns: The Stand-up check gaps are also asked straight to the person who owns the ticket, at the start of their Devin Cloud session, two at most: for example "ACME-123 has been In Progress 10 days. When do you expect to close it?" or "Defect ACME-456 has no fix version. Which release will the fix ship in?". The answer goes on the ticket after they reply **approved**, so the gap drops off the list.

#### During the sprint

**Commitment against capacity** (Scrum Master). Type:

```
/dashboard
```

Devin returns: The **Commitment** tab: story points taken into the sprint against the team's capacity and the throughput floor, plus any stories with no points. When the Scrum Master attaches this sprint's capacity sheet (.xlsx) in the chat, capacity comes from the sheet, with each person's days in, days off and hours. Without it, Devin uses the leave on the Confluence page "Acme Claims Sprint Leave".

**Who is over capacity after leave** (Scrum Master). Type:

```
/dashboard
```

Devin returns: The **Leave calendar** tab shows who is off on which day of the sprint, from the "Acme Claims Sprint Leave" page. The **Over-committed** tab compares each person's story points with their capacity after leave. Argus Scrum Master follow-ups draft the question for them ("You have X story points against Y points of capacity after leave. How do you plan to handle it?") and list who has not answered about leave yet, with a message to send them.

**Move stories to another sprint** (Everyone). Do:

```
On the Backlog tab, tick the stories, select Move and pick the sprint
```

Devin returns: A preview of the move. Nothing changes in Jira until the Scrum Master types `approved`.

**Tidy the board** (Scrum Master). Type:

```
/jira-hygiene
```

Devin returns: Tickets that don't yet meet the Jira rule book, grouped by what is missing, with the owner of each. The same list is the **Jira hygiene** tab on the dashboard.

**Stories not ready to estimate** (Scrum Master). Type:

```
/dashboard
```

Devin returns: The **Grooming** tab: stories flagged for grooming or splitting, and open stories with no points. The **Triage** tab lists observations still waiting to be triaged.

**Who is away and who covers** (Everyone). Type:

```
/vacation
```

Devin returns: The **Time off and backups** table from today on: who is away when, and who covers their stories, questions and approvals. Everyone can add, change or remove their own time off; the Scrum Master can change anyone's. The same planner is the **Vacation planner** tab on every dashboard, with who is away now. While someone is away, question and approval sub-tasks for them go to their backup.

**Someone is out sick** (Everyone). Type:

```
@Devin <name> is sick today
```

Devin returns: One line saying the person is down as a sick day on that date, and one with the unplanned leave count for them and the team this sprint. The row shows on the **Vacation planner** tab with Type **Sick day**, and the day is counted on the Scrum Master's **Unplanned leave** tab; nothing is reassigned. For ad hoc leave type `@Devin <name> is on ad hoc leave today`.

**Give your time off** (Everyone). Type:

```
I am off on 3 and 4 November
```

Devin returns: Four questions: who covers the stories, whether In Progress stories go On Hold, where questions go and who approves in the requester's place. Devin shows the planner row and writes it after the reply **approved**. Once a week the first session also asks whether any time off is coming up.

#### End of the sprint and the month

**Defect removal efficiency** (Scrum Master). Type:

```
/dashboard
```

Devin returns: The **DRE** tab: the share of defects caught before production, with the count for each environment and the production defects listed.

**AI adoption and efficiency** (Scrum Master). Type:

```
/dashboard
```

Devin returns: The **AI this month** tab for the month: how many closed sub-tasks carry AI-Used or AI-NA, the wrong-case and missing labels, the hours saved on AI-Used sub-tasks, and the exempted ones that logged more than their estimate.

**Is the sprint ready to close?** (Scrum Master). Type:

```
/sprint-close-check
```

Devin returns: The **Sprint close** tab: every story and sub-task in the active sprint that is not ready, with its owner and everything missing: sub-tasks still open, no time logged, no AI-Used or AI-NA label, no original estimate, or a status other than Ready for Approval or done. It only reads Jira.

**What the sprint cost** (Scrum Master). Type:

```
/dashboard
```

Devin returns: The **Cost** tab: for each story the points, the hours logged on it and its sub-tasks, the hours on AI-Used sub-tasks and hours per point, then the Devin Cloud sessions per story and stage with their hours. It shows hours, not money, until the delivery lead sets an hourly rate. There are no ACU figures, because the Devin API does not report them per session.

#### Targets and how each is measured

| Measure | Target | How Devin works it out |
|---|---|---|
| Cycle time | 2025 baseline 12.8 days; a story should close in about 8 days | Days from In Progress to Ready For Release or Closed. Days On Hold don't count, as in the Boost view. The average covers stories finished in the last 90 days. |
| Throughput | Not below 185.7 story points | Story points of the stories taken into the sprint. |
| Capacity | 181 story points, unless the capacity sheet or Sprint Leave page gives the sprint's hours | Team hours for the sprint divided by 8 hours a point. |
| Defect removal efficiency | Higher is better | 1 − (production defects ÷ all defects) for defects raised this year. Production means PRODUCTION, PRODUCTION - Warranty and PRODUCTION - Dark Release. |
| AI adoption | 100%, every month | Every closed sub-task carries AI-Used or AI-NA, in exactly that case. |
| AI efficiency | At least 30%, every month | (estimated hours − logged hours) ÷ estimated hours, over AI-Used sub-tasks closed in the month. A sub-task's estimate is its share of the story's first estimate. Sub-tasks that logged more than their estimate are left out and listed. |

**Still to agree with the Scrum Master.** The dashboard marks these "To confirm" rather than guessing: where each sprint's capacity sheet is kept; which defects the DRE counts (this year, this PI or this month); whether those three values are the full list for production; whether Dev defects count; and whether cycle time is calendar days or working days.

### Answer and approve

*Questions and sign-offs all land in one place, and each answer is recorded with who gave it and when.*

#### How it works

1. Questions and approvals appear on the dashboard under **Questions for me** and **Approvals awaiting me**, and as sub-tasks on the Jira story.
2. Each one shows a short brief of what is being asked.
3. Then reply in the chat:
```
approved
```

3. or
```
rejected the scope leaves out Medicaid members
```

4. To hand it to a colleague instead:
```
send this to Resource 17 "covering while I am out"
```

### Report to stakeholders

*Stakeholder updates come from the work already recorded in Jira and the team's documents.*

#### Examples

**Release notes** (Product Owner). Type:

```
/release-notes all
```

Devin returns: A review page with an executive summary and a feature-by-feature list of changes and who they affect, in plain words. Approving it saves it to the knowledge base.

**Monthly status** (Product Owner). Type:

```
/status-report
```

Devin returns: The monthly program status report built from Jira.

### Hand over work

*Work can change hands without anything getting lost.*

#### Examples

**Hand over before leave** (Everyone). Type:

```
/handover Resource 16 ACME-18710
```

Devin returns: A handover note, the Jira items reassigned with a comment, and a message telling the colleague how to pick it up.

### What can be changed

*Product Owners and BSAs can update the team's knowledge base directly. Application code stays with the development team.*

#### By role

| Area | Product Owner | BSA | Scrum Master |
|---|---|---|---|
| Jira tickets from the Backlog tab, after approval | Yes | Yes | Yes |
| Knowledge base | Yes | Yes | No |
| Architecture decisions, knowledge base staging | Yes | Yes | Yes |
| Own session folder | Yes | Yes | Yes |
| Application code, framework and test packs | No | No | No |

#### Updating the knowledge base

1. Ask for the change in plain English, for example: `Add the 2027 ProgramB program year to the risk program glossary`.
2. Devin makes the change and shows exactly what is different.
3. Reply `approved`. Devin stamps the change with the approver's name and the time, and opens a pull request.
4. A team member with merge rights merges it.

#### Example

**Validate the knowledge base** (Product Owner, BSA). Type:

```
/document-validation
```

Devin returns: A form with every open question the knowledge base cannot settle from its own sources. Each one shows the context, what is understood today and a proposed answer. The answers go into the knowledge base once the requester replies **approved**.

A change to application code goes to the development team as a Jira story.

### Help

*Help is always one command away.*

#### In Devin Cloud

| Type | To see |
|---|---|
| `/help` | The start-here menu, with your role's first commands at the top |
| `/help po` | Everything for Product Owners |
| `/help bsa` | Everything for BSAs |
| `/help intake` | Detail on one command |
| **My commands** tab on `/dashboard` | Every command for your role: your first commands, then the rest, then the ones for everyone |

#### Teach Devin how you work

When Devin gets something wrong about how a role works, or should do something differently next time, tell it in plain words and ask it to remember. For example:

**Learn about who you serve.** At the end of Devin's first reply in a session, it asks you one question about your work, or one of the open questions only you can answer. You can answer it or say skip. Devin shows your answer as a knowledge-base change and saves it only after you type "approved", and when your answer also settles other open questions it closes those too. The same questions are on the **Learn about who you serve** tab of your dashboard. Type `/learn-about-who-you-serve` to answer them all at once.

```
Remember: a demo is booked when the dev story reaches In Review
```

```
Remember: my business counterparts for Scorecard are the provider reporting team
```

Devin shows exactly what it would save and where, and saves it only after the reply **approved**. From then on every Devin Cloud session reads it. Changes to who is on the team are made on the Confluence page "Acme Claims Team Roster" and approved there by its owner.

#### Contact

For questions about these commands, roster additions or database access: Resource 3, Solution Lead, Acme Claims (resource3@acme.example).
