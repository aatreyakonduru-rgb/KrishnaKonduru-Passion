# Mētis 2.0.0 Feature Gap Analysis

**Date:** 14 November 2026  
**Scope:** Evaluation of intended capabilities ("Wanted") versus verified implementation ("Built") across all Mētis 2.0.0 artifacts.

---

## 1. Executive Summary & Evaluation Methodology

This document provides a grounded, evidence-backed feature comparison between what Mētis 2.0.0 was designed to deliver versus what currently exists in the codebase.

### Sources of "Wanted" Requirements
1. **Release Record (`Metis-2.0.0-Release-Record.md`):** Core MVP commitments, new 2.0 MVP features, 17 built screens, and explicitly deferred roadmap items.
2. **Interactive Mockups (`mockups/metis-ui-mockups.html` & `mockups/build/screens_*.py`):** Visual design specifications and UX behavior for 21 screens.
3. **Screen Reference Images (`Metis-2.0.0-screens/01-home.webp` to `21-detected-setup.webp`):** Rendered visual target specifications.
4. **Product Manual (`documentation/Metis-2.0.0-manual.md`):** End-user documentation, architecture descriptions, and Section 9 ("Coming Soon" future improvements table).

### Sources of "Built" Implementation Evidence
1. **UI Application (`metis-1.2.5-team (1)/tools/ui/`):** `server.py`, `views.py`, `ui_common.py`, `answers.py`, `setup_ops.py`, `builds.py`, `tasks.py`, `glossary.py`, `calibration.py`, and modular screens (`screens_pack.py`, `screens_golden.py`, `screens_admin.py`, `screens_review.py`, `screens_compare.py`, `screens_glossary.py`, `screens_usage.py`).
2. **Core CLI Tools (`metis-1.2.5-team (1)/tools/`):** `verify_kb.py`, `kb_gate.py`, `questions.py`, `feedback.py`, `golden.py`, `context_pack.py`, `mcp_server.py`, `telemetry.py`, `trust.py`, `review_queue.py`, `sql_links.py`, `gen_graph.py`, `graph_store.py`, `gen_matrix.py`, `kb_coverage.py`, `doc_intake.py`, `doc_kb.py`, `doc_images.py`, `sensitive.py`, `site_paths.py`, `build_plan.py`, `build_outputs.py`.
3. **Test Suite (`metis-1.2.5-team (1)/tools/tests/`):** 391 automated test cases (1 skipped) verifying behavior without network dependencies.
4. **Changelog (`metis-1.2.5-team (1)/CHANGELOG.md`):** Chronological log of released and unreleased features.

---

## 2. 21 Mockup Screens Gap Analysis

| # | Mockup Screen Name | Status | Built Route / File | Evidence & Implemented Capabilities | Remaining Gaps / Deviations |
|---|---|---|---|---|---|
| **01** | **Home** | **Partly Built** | `/` in `tools/ui/views.py` (`home()`) | Shows readiness checklist ("Where this project stands"), KPI cards (KB pages, Open questions, Questions asked, Waiting for lead, Devin tasks) and a left 'Needs attention' pane (approvals, open questions, Devin tasks, next setup step). There is no right pane. | Source freshness in SIT table with visual progress bars & service account labels is absent; KPI stats differ from mockup (98.7% citations verified, 71% SQL parsed are in Coverage instead). |
| **02** | **KB Files** | **Partly Built** | `/files` in `tools/ui/views.py` (`files()`, `file_view()`) | Left pane file tree grouped by folder with a filter; page reader with source citations and trust signals; right pane properties (folder, size, last changed, citation count) and upstream/downstream links with their origin read from the link graph when `graph_store` has one. | The mockup's 'AI summary' box with confidence and the per-page 'Useful / Not right' buttons are not built. Upstream/downstream shows only when the graph file exists for the page's entity. |
| **03** | **KB Map** | **Built** | `/map` in `tools/ui/screens_map.py` | Dedicated `/map` route in Web UI displaying clustered architecture layers (Sources, Tables, Jobs, APIs, Screens) and interactive SVG radial neighborhood view (1-3 hops, up to 300 nodes) with edge origin styling. | Matches mockup navigation and exploration requirements; capped at 15 folders per layer and 200 links in overview. |
| **04** | **Impact** | **Built** | `/impact` in `tools/ui/screens_map.py`, `tools/gen_matrix.py`, `tools/graph_store.py` | Standalone interactive `/impact` UI screen; traces multi-step upstream dependencies and downstream impacts with edge origins and raw trust signals. | Full multi-hop impact traversal available via UI route and CLI. |
| **05** | **Ask** | **Built** | `/ask` in `tools/ui/views.py` & `tools/ui/answers.py` | Local extractive answerer + Devin reasoning task mode; computed confidence score (0-100) and bands (High 85+, Medium 60+, Low 1+, None 0); the Wilson-interval check of bands against ratings is on `/usage`; miss guidance card with typo corrections and clarify box; Devin 2-question/2-round back-and-forth; pure-CSS dislike reason form (wrong fact vs where to look); left pane recent questions; right pane citations & confidence breakdown. | Matches the mockup layout. The mockup's 'Open impact' and 'Copy as ticket text' buttons are not built. |
| **06** | **Approve** | **Partly Built** | `/approve` in `tools/ui/views.py` & `tools/kb_gate.py` | First-build lock certification (`kb_gate.lock`), pending staging batches review (`kb_gate.certify`, `reject`), and feedback review approvals; plain-language diff digests; strict evidence tag validation; role authorization; left pane pending batches; right pane lists who can approve. | The mockup's per-file old-versus-new line diff with a "quote found" check, the "files in this change" list and the reviewer note box are not built; the digest is shown as text. |
| **07** | **Refresh / Build** | **Partly Built** | `/build` in `tools/ui/views.py` & `tools/ui/builds.py` | Readiness checks; staged build directory orchestration (`_REGEN/<run>`); Devin task dispatch & monitoring (`tasks.py`); manual triggers for verification and output generators; recent build history. | Fine-grained per-source toggle switches (Bitbucket, Jira, Confluence, Snowflake) with estimated ACU cost calculator and recurring weekly scheduler buttons are not built. |
| **08** | **Questions** | **Built** | `/questions` in `tools/ui/views.py` & `tools/questions.py` | Displays `VALIDATE_KB.yaml` open/answered questions; filters by role and priority; form to raise new questions; form to answer questions with mandatory `[E: ...]` citation tags; blocker tracking. | Left list pane and right side pane added in the restyle; not compared against the mockup image line by line. |
| **09** | **Feedback Review** | **Partly Built** (in Approve & Usage) | `/approve` (`views.py`), `/usage` (`screens_usage.py`), `tools/feedback.py` | Feedback register (`_FEEDBACK/FEEDBACK.yaml`), rating captures, lead review/dismiss/convert to question actions, telemetry correlation to ratings with Wilson intervals. | Does not have a dedicated `/feedback` route separate from `/approve`. |
| **10** | **Compare and Promote** | **Built** | `/compare` in `tools/ui/screens_compare.py` & `tools/kb_compare.py` | Compares a staged folder with the KB and promotes a chosen page; a locked KB turns a promote into a proposed batch in `_PENDING`, an unlocked KB writes it and archives the old copy. Refuses no name, no reason, path traversal and files outside the chosen folder. | List and side panes added in the restyle. |
| **11** | **Teams & Rights** | **Built** | `/teams` in `tools/ui/screens_admin.py` | Loads `gate.teams` from `kb-profile.yaml`; shows team file path ownership globs (`owns`), designated approvers, action permission matrix table; allows adding teams and updating approver rosters. | List and side panes added in the restyle. |
| **12** | **Settings** | **Partly Built** | `/settings` in `tools/ui/screens_admin.py` | Views and edits core `kb-profile.yaml` settings (product name, org, lead certifiers, verification parameters, strict tags, storage options). | Multi-tab connection credential tester, schedule manager, and pattern scanner rule toggles from mockup are not present. |
| **13** | **Audit Log** | **Built** | `/audit` in `tools/ui/screens_admin.py` | Parses append-only `.metis/CERTIFICATIONS.log` and `.metis/tasks/`; displays timestamp, actor, action type (lock, certify, reject, task), target files, and details; filterable by action. | Tabbed filtering by environment/category is simplified to single filter. |
| **14** | **Coverage** | **Built** | `/coverage` in `tools/ui/views.py` & `tools/kb_coverage.py` | Reads `CROSS-LAYER/COVERAGE.yaml`; reports unreferenced objects, catalogue tables with no page, rejected links, unparsed SQL files, unsupported relations/node types, blocking questions. | Trend chart across 6 historical refreshes is not stored; list and side panes added in the restyle. |
| **15** | **Golden Questions** | **Built** | `/golden` in `tools/ui/screens_golden.py` & `tools/golden.py` | Golden and competency question register (`golden.yaml`); lexical static verification (`golden.py static`); score evaluation (`golden.py score`); pass/fail/stale status badges; suite runner trigger. | Scoring is lexical (exact word/quote matching), not LLM-judged semantic evaluation; list and side panes added in the restyle. |
| **16** | **Context Pack** | **Built** | `/pack` in `tools/ui/screens_pack.py` & `tools/context_pack.py` | Token-budgeted context bundle generator (default 6,000 tokens); builds from Jira ticket ID, entity objects, or file paths; traverses upstream/downstream graph; includes raw trust signals; excludes sensitive pages; marks stale facts; wraps in `<kb-file>` tags; generates deterministic SHA-256 pack ID; copy/download buttons; in-memory cache of last 20 packs. | List and side panes added in the restyle. |
| **17** | **Ticket to Impact** | **Built** (in `/pack` & `/impact`) | `/pack` (`screens_pack.py`), `/impact` (`screens_map.py`), `tools/context_pack.py` | Inputting Jira ticket ID extracts impacted entities, upstream/downstream components, trust signals, and citations via graph walk. | Integrated into `/pack` and standalone `/impact` exploration screen. |
| **18** | **Onboarding Wizard** | **Partly Built** (in Setup) | `/setup` in `tools/ui/views.py` & `tools/ui/setup_ops.py` | Profile editing, stack auto-detection and approval (`tools/detect_stack.py`), database environment connection checks, and prompt template linting. | Implemented as a single-page accordion form on `/setup` rather than a 6-step guided stepper wizard. |
| **19** | **Live Run View** | **Partly Built** (in Build/Task) | `/build` and `/task?id=T-xxxx` in `tools/ui/views.py` & `tools/ui/tasks.py` | Task detail inspection, status lifecycle (`queued`, `running`, `done`, `failed`, `waiting-user`), round-trip Q&A interaction, log output display. | Real-time WebSocket streaming log viewer and live ACU cost consumption meter are not built. |
| **20** | **Business Glossary** | **Built** | `/glossary` in `tools/ui/screens_glossary.py` & `tools/ui/glossary.py` | Business term dictionary; definition and citation mappings; synonym registration; Ask search query expansion via synonyms; add term and synonym forms. | List and side panes added in the restyle. |
| **21** | **Detected Setup Scan** | **Partly Built** (in Setup) | `team/tools/detect_team.py`, `tools/detect_stack.py`, `/setup` | Backend scanners detect technology stack, repos, and connection configuration; results shown in `/setup` readiness checklist. | Standalone dedicated `/detected-setup` screen is not built. |

---

## 3. Detailed Functional Area Gap Analysis

### Area 1: Q&A, Answering & Feedback Loop

| Feature / Capability | Wanted Behavior | Current Built State | Status | Evidence File / Route |
|---|---|---|---|---|
| **Extractive Local Answering** | Keyword & heading search over KB files with verbatim line and quote extraction. | Fully functional; extracts matching lines, formats with `[E: kb:...]` citations, builds miss guidance when no matches found. | **Built** | `tools/ui/answers.py`, `tools/ui/views.py` |
| **Devin Reasoning Mode** | Queues task `T-xxxx` for remote Devin worker to reason, cite sources, and answer. | Fully functional; creates YAML task in `.metis/tasks/`, monitors status, renders result on completion. | **Built** | `tools/ui/tasks.py`, `skills/metis-tasks` |
| **Computed Confidence Score & Bands** | Exact formula: 100 for direct line match, 92 cap for joined lines, 80 cap for inferred, 84 cap for missing parts/open questions; Bands: High (85+), Medium (60+), Low (1+), None (0). | Implemented exactly per specification in `answers.confidence()`; bands displayed with color-coded pills. | **Built** | `tools/ui/answers.py` (`confidence()`) |
| **Miss Guidance & Typos** | When score is below High or no lines found: show query terms, known/unknown words, typo corrections, nearest pages, and clarify prompt. | Fully implemented; computes Levenshtein-like distance against glossary/KB words, offers clickable typo substitutions and clarification box. | **Built** | `tools/ui/answers.py` (`miss_guidance()`) |
| **Devin User Clarification Round Trip** | Devin worker can ask user up to 2 questions per round, max 2 rounds; pauses task in `waiting-user` state. | Implemented in `tasks.py` (`ask-user`, `wait`, `reply`) and UI task page with reply form. | **Built** | `tools/ui/tasks.py`, `metis-1.2.5-team (1)/tools/ui/views.py` |
| **Feedback Capture (Thumbs Up / Down)** | Thumbs up records positive rating; thumbs down opens a pure CSS form (the mockup shows reason buttons; the rule is why plus exactly one of the right answer or where to look). | Implemented without JavaScript using a CSS checkbox toggle. The form asks for why plus exactly one of the right answer or where to look (not the mockup's category buttons); recorded through `feedback.py`. | **Built** | `tools/ui/answers.py`, `tools/feedback.py` |
| **Chat-First Interactive Interface** | Full-screen interactive conversational workspace for iterative Q&A. | Implemented in `screens_chat.py` (`/chat`); multi-turn extractive Q&A with citation side panels, like/dislike ratings, and in-memory threads. | **Built** | `tools/ui/screens_chat.py` |

---

### Area 2: Review, Approvals & Governance

| Feature / Capability | Wanted Behavior | Current Built State | Status | Evidence File / Route |
|---|---|---|---|---|
| **First-Build Lock Gate** | First KB build must be certified by a named lead; creates cryptographic baseline. | Implemented via `kb_gate.lock`; creates `.metis/certified.yaml` and logs to `.metis/CERTIFICATIONS.log`. | **Built** | `tools/kb_gate.py` |
| **Lead Certification Gate** | Changes to locked KB must stage in `_PENDING/<batch>/` and be certified by authorized lead. | Implemented; validates author identity against `owners` and `gate.certifiers`; re-checks all citations upon certification. | **Built** | `tools/kb_gate.py`, `tools/ui/views.py` (`approve()`) |
| **Review Queue & Risk Ranking** | Pending files grouped by owning team (`gate.teams`) and sorted riskiest first based on citation status and dependency depth. | Implemented in `review_queue.py` and `/review` screen; outputs team review plans and branch names. | **Built** | `tools/review_queue.py`, `tools/ui/screens_review.py` |
| **One PR per Owning Team** | Generates dedicated pull request review digest and branch per team (`metis/<date>-review-<team>`). | `review_queue.py plan` writes PR bodies under `_PENDING/_QUEUE/`; does not invoke git push or Bitbucket API. | **Built** (Local plan generation) | `tools/review_queue.py` |
| **Bulk Approve with Sampling** | For batches >10 files, allows certifying representative sample with confidence threshold. | Sampling logic implemented in `screens_review.py` for batches over 10 files. | **Built** | `tools/ui/screens_review.py` |
| **Audit Logging** | Append-only tamper-evident log of all certifications, locks, rejections, and tasks. | Implemented via `.metis/CERTIFICATIONS.log` and displayed with filtering on `/audit`. | **Built** | `tools/kb_gate.py`, `tools/ui/screens_admin.py` (`audit()`) |
| **Teams & Rights Management** | Define teams, path ownership globs, and role-based permissions matrix. | Implemented in `screens_admin.py` (`/teams`); updates `gate.teams` in `kb-profile.yaml`. | **Built** | `tools/ui/screens_admin.py` (`teams_view()`) |

---

### Area 3: Parsing, Lineage & Graph Modeling

| Feature / Capability | Wanted Behavior | Current Built State | Status | Evidence File / Route |
|---|---|---|---|---|
| **SQLglot SQL Parsing** | Table-level DDL/DML dependency extraction from `.sql` files with `[E: file:line]` citation tags. | Implemented in `sql_links.py`; parses INSERT, CREATE, MERGE, UPDATE, dbt models (`ref`, `source`), foreign keys; lists unparsed SQL. | **Built** | `tools/sql_links.py` (optional `sqlglot` dependency) |
| **Edge Origin Tagging** | Strict classification of every graph edge as `parsed`, `catalogue`, or `ai-proposed`. | Implemented in `gen_graph.py` and `graph_store.py`; origin derived from link filename so hand-written files cannot claim `parsed`. | **Built** | `tools/gen_graph.py`, `tools/graph_store.py` |
| **SQLite Graph Store** | Fast local SQLite property graph caching for instant upstream/downstream traversals. | Implemented in `graph_store.py` (`.metis/graph.sqlite`); supports depth-bounded upstream and downstream walks. | **Built** | `tools/graph_store.py` |
| **Impact Matrix Normalization** | Normalizes relation variants (`handled_by`, `handled-by`, `handled by`) and reports unparsed relations/node types. | Implemented in `gen_matrix.py`; outputs `CROSS-LAYER/IMPACT_MATRIX.yaml` and warns on incomplete edges. | **Built** | `tools/gen_matrix.py` |
| **Tree-Sitter Code Parsing** | AST dependency parsing for Java, TypeScript, and Python codebases. | Implemented in `code_links.py`; parses Spring, NestJS, Express, TypeORM, Flask, FastAPI, Django with tree-sitter or pure-Python AST fallback. | **Built** | `tools/code_links.py` |
| **Column-Level Lineage** | Column-to-column data flow tracking through SQL queries and ETL transformations. | Implemented in `column_lineage.py`; traces SELECT, CTEs, JOINs, aggregates, CASE, INSERT, CREATE AS, dbt models, with multi-hop `column_impact` walk. | **Built** | `tools/column_lineage.py` |
| **Whole-KB Visual Graph** | Visual graph explorer for system architecture and entity relationships. | Implemented in `screens_map.py` (`/map`, `/impact`); clustered layer overview and SVG radial neighborhood view up to 300 nodes. | **Built** | `tools/ui/screens_map.py` |

---

### Area 4: Verification, Quality & Safety

| Feature / Capability | Wanted Behavior | Current Built State | Status | Evidence File / Route |
|---|---|---|---|---|
| **Evidence Rule (`verify_kb.py`)** | Strict verification that all `[E: ...]` tags resolve to exact source files and verbatim quotes; zero errors required for build completion. | Fully functional; checks `repo:file:line "quote"`, `kb:<path> "quote"`, and `doc:<name>#anchor "quote"`; validates strict tags. | **Built** | `tools/verify_kb.py` |
| **Raw Trust Signals** | Page and edge-level verifiable facts: origin, quote verified, source modified since build (git check), blocking open questions. | Implemented in `trust.py` (`page()`, `edge()`); included in context pack and review queue. | **Built** | `tools/trust.py` |
| **Sensitive Data Scanner** | Blocks credentials, secrets, tokens, SSNs, and Luhn-valid credit card numbers; warns on PII. | Implemented in `sensitive.py`; regex and Luhn validation applied during document intake and promotion. | **Built** | `tools/sensitive.py` |
| **Golden Question Verification** | Automated re-asking and scoring of competency questions across builds. | Implemented in `golden.py` and `/golden`; static syntax check and lexical token matching. | **Built** (Lexical scoring) | `tools/golden.py`, `tools/ui/screens_golden.py` |
| **Build-Time Contradiction Finder** | Automated detection of conflicting statements across KB pages during staging. | Implemented in `kb_contradict.py` and `/quality`; scans pairwise claims across tables and key-values into `CONTRADICTIONS.yaml`. | **Built** | `tools/kb_contradict.py`, `tools/ui/screens_quality.py` |
| **LLM-Judged Semantic Evaluation** | Model-based evaluation of semantic citation correctness and golden question answers. | Implemented in `llm_judge.py` and `/quality`; evaluates citation support via file exchange or HTTP chat completions. | **Built** | `tools/llm_judge.py`, `tools/ui/screens_quality.py` |

---

### Area 5: Knowledge Context & Agents

| Feature / Capability | Wanted Behavior | Current Built State | Status | Evidence File / Route |
|---|---|---|---|---|
| **Context Pack Builder** | Token-budgeted context bundle with ranked pages, graph impact list, raw trust signals, and deterministic SHA-256 pack ID. | Fully functional via CLI (`context_pack.py`) and UI (`/pack`); keeps citations intact, excludes secrets, marks stale facts. | **Built** | `tools/context_pack.py`, `tools/ui/screens_pack.py` |
| **MCP Server** | Model Context Protocol server over stdio using standard library only (no Node build required). | Implemented in `tools/mcp_server.py`; tools: `metis_find_nodes`, `metis_context_pack`, `metis_trust`, `metis_feedback_hints`, `metis_check_answer`, `metis_record_answer`, `metis_rate_answer`, `metis_raise_question`. | **Built** | `tools/mcp_server.py` |
| **Consumption Telemetry** | Log which KB files are cited in packs and answers; join usage to user ratings. | Implemented in `telemetry.py` and `/usage`; computes Wilson confidence intervals, identifies most-disliked pages and unread pages. | **Built** | `tools/telemetry.py`, `tools/ui/screens_usage.py`, `tools/ui/calibration.py` |
| **Per-Line Consumption Attribution** | Sentence-level attribution tracking of exact lines that drove answers or caused dislikes. | Implemented in `telemetry_lines.py` and `/quality`; logs exact `path:line` attribution for cited answers without question text. | **Built** | `tools/telemetry_lines.py`, `tools/ui/screens_quality.py` |

---

### Area 6: Ingestion & Document Processing

| Feature / Capability | Wanted Behavior | Current Built State | Status | Evidence File / Route |
|---|---|---|---|---|
| **Multi-Format Document Intake** | Recursive intake of Word (.docx), Excel (.xlsx), PowerPoint (.pptx), PDF (.pdf), plain text, markdown, and .zip archives. | Implemented in `doc_intake.py`; extracts structured text with paragraph/cell/slide anchors; generates `INTAKE.yaml`. | **Built** | `tools/doc_intake.py` |
| **Image & Picture Text Extraction** | Extracts embedded images and scans, stages for model inspection, and merges extracted text back at anchor points (`slide4/image1`). | Implemented in `doc_images.py`; formats picture metadata in `IMAGES.yaml` and merges approved text into document representation. | **Built** | `tools/doc_images.py` |
| **Document KB Publishing** | Classifies ingested documents into categories (`templates/doc-categories.yaml`), writes KB pages, generates `context/DOC_INDEX.md`. | Implemented in `doc_kb.py`; stages into `_PENDING/` if KB is locked; validates source quote tags against extracted docs. | **Built** | `tools/doc_kb.py` |
| **Confluence & SharePoint Connectors** | Live HTTP/API fetching of Confluence spaces and SharePoint document libraries. | Implemented in `doc_intake.py` with TLS verification, session token support, and read-restriction capture. | **Built** | `tools/doc_intake.py` |

---

### Area 7: Multi-Environment & Promotion

| Feature / Capability | Wanted Behavior | Current Built State | Status | Evidence File / Route |
|---|---|---|---|---|
| **Multi-Environment Configuration** | Declarative specification of database environments (DEV, SIT, UAT, PREPROD, PROD) in `db-environments.yaml`. | Implemented; defines connection parameters, catalog queries, and reference environment. | **Built** | `templates/db-environments.yaml`, `tools/db_catalog.py` |
| **Catalog Snapshots & Schema Drift** | Snapshot extraction of table schemas and drift comparison between environments. | Implemented in `db_catalog.py` and `gen_registry.py`; outputs `DB_DRIFT.yaml`. | **Built** | `tools/db_catalog.py`, `tools/gen_registry.py` |
| **Compare and Promote Pipeline** | Compares KB definitions between environments and promotes validated changes. | Implemented in `kb_compare.py`, `kb_promote.py`, and `/compare` screen; automatically enforces lead certification gate when locked. | **Built** | `tools/kb_compare.py`, `tools/kb_promote.py`, `tools/ui/screens_compare.py` |
| **Environment Switcher in UI Header** | Dropdown/switcher in top bar to switch active environment view across all screens. | Implemented in `server.py` and `ui_common.py`; top-bar dropdown allows switching active database environment via `metis_env` cookie. | **Built** | `tools/ui/server.py`, `tools/ui/ui_common.py` |

---

### Area 8: Project Setup, Discovery & Configuration

| Feature / Capability | Wanted Behavior | Current Built State | Status | Evidence File / Route |
|---|---|---|---|---|
| **Profile & Settings Management** | Web UI form to view and edit `kb-profile.yaml` settings. | Implemented in `/setup` and `/settings`. | **Built** | `tools/ui/setup_ops.py`, `tools/ui/screens_admin.py` |
| **Technology Stack Auto-Detection** | Automatic discovery of languages, frameworks, databases, and build tools from source repos. | Implemented in `tools/detect_stack.py` and integrated into `/setup`. | **Built** | `tools/detect_stack.py`, `tools/ui/setup_ops.py` |
| **Database Connection Verification** | Live verification of database and MCP catalog connectivity. | Implemented in `setup_ops.py` connection check runner. | **Built** | `tools/ui/setup_ops.py` |
| **Prompt Template Linting** | Verification of required variables and formatting in prompt templates. | Implemented in `setup_ops.py` prompt check runner. | **Built** | `tools/ui/setup_ops.py` |
| **6-Step Onboarding Stepper Wizard** | Guided multi-step stepper UI for new APMs joining Mētis. | Consolidated into accordion/form layout on `/setup`. | **Partly Built** | `tools/ui/views.py` (`setup()`) |

---

### Area 9: Integrations & Enterprise Standards

| Feature / Capability | Wanted Behavior | Current Built State | Status | Evidence File / Route |
|---|---|---|---|---|
| **Bitbucket PR Impact Comments** | Automated posting of impact matrix and risk analysis comments onto Bitbucket pull requests. | Implemented in `bb_pr.py` and `/notify`; formats and posts PR comments to Bitbucket Server and Cloud with dry-run default. | **Built** (with limits) | `tools/bb_pr.py`, `tools/ui/screens_notify.py` |
| **Slack / Teams Webhook Notifications** | Push alerts for queued Devin tasks, open questions, and pending lead certifications. | Implemented in `notify.py` and `/notify`; dispatches deduplicated alerts to Slack, Teams, generic webhooks, and email. | **Built** | `tools/notify.py`, `tools/ui/screens_notify.py` |
| **Single Sign-On (SSO) & OIDC** | Enterprise SAML/OIDC identity integration binding approvals to corporate IDs. | Implemented in `auth_oidc.py` and `server.py`; OIDC PKCE flow with RS256 token verification, signed session cookies, and role mapping. | **Built** (with limits) | `tools/auth_oidc.py`, `tools/ui/server.py` |
| **OKF v0.2 Bundle Packaging** | Open Knowledge Format bundle export with formal compliance certification. | Implemented in `okf_bundle.py` and `/federation`; packages OKF-shaped bundle with frontmatter, `index.md`, and `okf-manifest.yaml` with local validation. | **Built** (with limits) | `tools/okf_bundle.py`, `tools/ui/screens_federation.py` |
| **RDF / SPARQL / OWL Export** | Semantic web graph export for enterprise triplestores. | Implemented in `export_rdf.py` and `/federation`; exports Turtle, N-Triples, JSON-LD, OWL 2, with built-in pure-Python SPARQL query engine. | **Built** | `tools/export_rdf.py`, `tools/ui/screens_federation.py` |
| **W3C PROV & OpenTelemetry Export** | Export build provenance and tracing in W3C PROV / OTel standard schemas. | Implemented in `export_prov.py` and `/federation`; exports PROV-O Turtle/JSON and OTLP JSON traces and logs with optional `--post`. | **Built** | `tools/export_prov.py`, `tools/ui/screens_federation.py` |

---

## 4. Summary Totals & Metrics

| Status Category | 21 Mockup Screens Count | Functional Capabilities Count | Summary Assessment |
|---|---|---|---|
| **Built** | **12** (57.1%) | **49** (98%) | All core and second-pass functional capabilities are implemented and covered by the automated tests counted in the block below. "Built" includes items tested against fakes or with local validators, as noted in the rows. Nothing here has been tried end to end against real Bitbucket, Slack, SMTP, OIDC, OTLP, sentence-transformers or an MCP client. |
| **Partly Built** | **9** (42.9%) | **1** (2%) | Nine of the 21 mockup screens are built in a different shape from the mockup: consolidated into multi-pane or accordion views (e.g. Setup is an accordion rather than a 6-step wizard; Ticket impact is integrated into Context pack and Impact views). Their missing parts are listed per row above. |
| **Not Built / Deferred** | **0** mockup screens, **0** planned capabilities | **0** (0%) | No mockup screen is wholly missing and every planned capability from W1–W8 is built. "0" does not mean the nine partly built screens are complete: they lack the parts named in their rows. External enterprise additions (SCIM, live ACL sync, auto-approval scoring) remain deferred in the Release Record. |

Counts below come from the code, not from this prose:

<!-- metrics:begin -->
Counted from the code by `tools/doc_metrics.py`; run `python3 doc_metrics.py write` to refresh.
- Tests discovered: 1203
- UI screens (paths in `server.SCREENS`): 29
- Tools (`tools/*.py`): 76
- Skills: 74
<!-- metrics:end -->

---

*Gap analysis produced for Mētis 2.0.0.*
