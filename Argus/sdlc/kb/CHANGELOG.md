# Change log

## 2.1.0 (unreleased)

- **Onboarding page on a fresh install:** `/page/onboarding` opens with an empty state and the `/onboarding-guide` step when the onboarding folder is not there yet.
- **Integration health:** `/api/config` and `/api/health` report Jira and Devin Cloud as `not_configured`, `not_checked`, `connected` or `failing`. A key or setting alone is configured, not connected; the Workbench checks each system once at start and after a key is saved, and the last real call sets the state. The Workbench names a failing system on the welcome page and in Test on my PC.
- **Refused local address:** when a call to 127.0.0.1 or localhost gets no answer, the error names the setting that points there (`SDLC_JIRA_BASE`, `SDLC_SANDBOX_URL` or `DEVIN_API_BASE`).
- **Shared copy v2.4.102926:** `sdlc/kb/v2.4.102926/` and `v2.4.102926.zip` hold the latest framework, Argus, the install window and the sandbox, with an empty knowledge base. Older dated copies stay as they are. In this copy:
  - the gate check before `/implement`, `/eval`, `/release` and `/kb-refresh` reads the story named in the command (`/implement REQ-x STORY-1`), so a story whose SDLC_04 to SDLC_07 gate is signed is no longer blocked; with no story named, every story that has the gate must be signed;
  - Argus remembers a rejected gate, and a run is not complete while its last gate decision is a rejection, so a rejected SDLC_08 never shows the run as done;
  - SDLC_08 is required: the KB refresh, and so the SDLC run, is not complete until it is signed;
  - Help → About reads the version from `sdlc/framework/tools/VERSION` in a shared copy.
- **Shared copy v2.3.102726:** `sdlc/kb/v2.3.102726/` and `v2.3.102726.zip` hold the latest framework, Argus, the install window and the sandbox, with an empty knowledge base. Older dated copies stay as they are. In this copy:
  - the install window's first step offers UEP Devin Cloud, other Devin Cloud and Devin Local, and picks UEP when the session already has the Jira and Confluence secrets;
  - outside UEP the window lists what the team needs before it can use Argus (MCP servers for Jira and Confluence, its own Jira and Confluence API tokens, git access to its repo, and optionally a Snowflake MCP server), asks for the MCP server names and has Devin check each one (`MCP_CHECK`); Install points the skills at those servers and saves them under `mcp` in `sdlc-profile.json`;
  - the sandbox's sample app runs: `run.py setup` and `run.py` start its Django API and Next.js front end over a copy of `sample.db`, so Devin can change the sample code and test it in the browser; the Check step says whether pip and npm can fetch its packages.
- **Shared copy v2.2.102626:** `sdlc/kb/v2.2.102626/` and `v2.2.102626.zip` hold the latest framework, Argus, the install window and the sandbox, with an empty knowledge base. Older dated copies stay as they are. In this copy:
  - the framework's tests sit in `sdlc/framework/tools/tests/`, where the installer runs them;
  - the install window and its start page call the product Argus;
  - the architecture still picture ships as its SVG only (the PNG is made from it with the steps in `architecture/README.md`);
  - `learn-more.yaml` has ice-breaker questions for the automation engineer role;
  - Help → About and the shared copy status read the version from `sdlc/framework/tools/VERSION`.
- **Shared copy v2.1.101826:** `sdlc/kb/v2.1.101826/` and `v2.1.101826.zip` are the latest framework with the install window and the sandbox. `v2.101826/` stays as it is. The sandbox (`tools/sandbox/`) is a made-up company to try the framework on without a real Jira, Confluence or database:
  - `make_sandbox.py` builds a folder with a sample Jira (`jira.yaml`: 22 people, 3 sprints, 3 epics, 15 stories, 30 sub-tasks, 6 defects), Confluence pages (`confluence/`), a SQLite database (`sample.db`), the sample app repo with a local remote and its ETL repo (`claims-etl/`), and the hand-kept part of the sample knowledge base: routing map, table and entity registries, semantic layer, lineage, curated impact chains and the domain context Intake reads;
  - `sample_app.py` holds the sample app (claims, contracts and payments, in the `api/apps`, `web/src` and `scripts/` layout the KB generators read); after a sandbox install, `build_kb` runs the generators, so the endpoint, component and ETL registries, the cross-layer matrix, the ontology and the link graph are built from the sample code and Intake and Research have a full KB to read;
  - `sandbox_server.py` answers the framework's Jira and Confluence calls from those files and writes changes back to them;
  - `switch.py` prints the shell settings; while `SDLC_SANDBOX_URL` is set every Jira and Confluence call goes to the sandbox, and the database skills query `sample.db` with `sandbox_db.py`;
  - the install window offers the sandbox on Devin Local, and on Devin Cloud when the session has no Jira or Confluence secrets.
- **Shared copy v2.101826:** `sdlc/kb/v2.101826/` and `v2.101826.zip` hold the latest framework and the install window. The older dated copies stay as they are. The copy adds:
  - the install window in `tools/installer/` (`install_ui.py`, `install_steps.py`, `START-HERE.md`, the templates and the `sdlc-install` skill): ten steps, a first choice of Devin Cloud or Devin Local, the SDLC and KB folders of the team's choice, the roster typed or uploaded, the roster, sprint leave, demo recordings and manual pages under a named Confluence parent, and Save and finish later;
  - on Devin Local, checks for Python, git and, on Windows, Git Bash for the hook checks; the tokens come from environment variables, and the Devin Cloud blueprint step is skipped;
  - an empty knowledge base: the module, database, ETL, shared, cross-layer, validation and reports folders with a README each, the empty `SHARED/` files and link graph the tools read, and a `KNOWLEDGE-MANIFEST.yaml`;
  - name matching that keeps the number in placeholder names (Resource 6 and Resource 17 are different people), so the copy passes its own checks after install.
- **Shared copy v1.1-bugfix.101326:** `sdlc/kb/v1.1-bugfix.101326/` and its zip are v1.101326 with the gate, restore, `/plan`, API KB, install-check and Windows fixes, listed in its `BUGFIX-NOTES.md`. `v1.101326/` stays as it was.
- **Shared copy v1.101326:** the shared copy is now in `sdlc/kb/v1.101326/`. The folder name is 1 plus the build date (MMDDYY). `v1.1026/` stays as it was. The copy adds:
  - the `/jira-hygiene`, `/defects-by-specialty` and `/epics-from-roadmap` skills;
  - the Workbench Backlog and planning poker (`console/backlog.py`, `console/poker_room.py`);
  - the Scrum Master tools (`scrum_metrics.py`, `sprint_leave.py`, `capacity_sheet.py`);
  - the ontology generator and lookup (`kbgen/gen_ontology.py`, `ontology_lookup.py`) and the cross-module matrix generator;
  - the rules `scrum-master-metrics.yaml`, `foundational-work.yaml`, `defect-specialties.yaml` and `workbench-trace.md`;
  - the `commit-msg` git hook, and the tests for all of the above.
- **One zip to share:** the build also writes `sdlc/kb/v1.101326.zip`, the same folder as one file. `--check` fails if the zip is out of date.
- **MANUALS/ at the top of the copy:** the user manual, the Workbench manual and the two presentations, the same files as elsewhere in the copy, in one place to read before installing. The user manual has a section on sharing the framework with another team.
- **Playbook registration:** `sdlc/framework/tools/register_playbooks.py` creates the playbooks in Devin Cloud as `!pb_<nn>_<name>` macros, or updates them by macro. It does a dry run unless given `--apply`, and needs `DEVIN_API_KEY`. The installer names it as the next step.
- **About in a shared copy:** Help → About shows the copy's version, read from `sdlc/framework/tools/VERSION`, which the build writes.
- **Tests left out of the copy:** the matrix and ontology tests (`test_cross_module_matrix.py`, `test_ontology.py`, `test_ontology_lookup.py`) check our own generated KB, so they are not in the copy.
- **examples/acme/people.yaml:** a sample SDLC roster. 22 placeholder people (Resource 1 to Resource 22) keep the roles, secondary roles, role hints, allocation and delegates of a real team; names, emails, user ids and the roster page are placeholders.

Coverage fixes found by rebuilding our own KB and comparing it section by section.

- **APP-01 discovery:** a security section (routes with no sign-in, the auth flow, settings that switch it off), a named table list with reads and writes, and a UI section for frontend modules.
- **APP-02 BRD:** objectives and value, key business entities, reporting and export, integration dependencies, compliance and security, and data freshness, availability and performance.
- **kb_compare:** headings match regardless of case, numbering and punctuation; renamed sections are paired; a gone section reports how much of its content survives elsewhere. `--keep` takes a list of live files no prompt builds, reports them as kept, and flags a staged file that would replace one.
- **kb_promote:** `--keep` refuses to replace a file on the keep list.

## 2.0.0 (unreleased)

The first shareable version. Every prompt was rewritten from our own team's prompt set, with
team data taken out and read from a team profile at render time.

- **DB (19):** DB-01 to DB-16, plus DB-01A (the discovery check), DB-09B (data contracts) and DB-SD (staleness).
- **Application (15):** APP-01 to APP-14, and APP-GAP. Each renders per module, with `--set MODULE_NAME=... --set MODULE_SOURCE=...`.
- **ETL (13):** ETL-01 to ETL-13.
- **Domain context (6):** CTX-0A to CTX-0E build a team's own context, and CTX-00 joins them and writes the load index.
- **Runners and helpers (5):** RUN-DB, RUN-APP, RUN-ETL, HELP-SESSION and HELP-CODEDOC.
- **Evidence:** every prompt uses `[E: source]`, `[A]` and `[?]`, and ends with Open questions, Assumptions and Don't know lists.
- **Re-runs:** the runners write to a staging folder and compare before replacing reviewed documents.
- **Tool:** `prompts.py` gains `--set` for run-time values, and `lint` now reports bad frontmatter YAML.

Not carried over:

- The old "paste the domain context" prompts (UI and ETL `PROMPT_0`). CTX-00 replaces them.
- The separate code-documentation plan, which is now the batch-plan step of HELP-CODEDOC.
