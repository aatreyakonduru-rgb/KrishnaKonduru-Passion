# Metis vs commercial KB builders: feature list

Date: 14 Nov 2026. Basis: Metis 2.0.0 files in this workspace (Release Record, gap analysis, manual, changelog, tools).
Commercial tools are compared from general product knowledge, not from a live check of each vendor. Verify any
vendor-specific claim before putting it in a business case.

## 1. Which commercial tools are the right comparison

Metis is not a help-centre or wiki product. It builds an engineering knowledge base (code, database, ETL, Jira,
Confluence, documents) with evidence behind every line, and serves it to people and agents. So there are three groups:

| Group | Examples | Overlap with Metis |
|---|---|---|
| Wiki and help-centre KBs | Confluence, Document360, Guru, Helpjuice, Zendesk Guide, Notion, Slite, Tettra, Bloomfire | Authoring, review, search, analytics. Low on content generation. |
| Enterprise search and AI answer tools | Glean, Atlassian Rovo, Microsoft Copilot, Moveworks | Ask, citations, connectors, permissions. |
| Code and data knowledge tools | Swimm, DeepWiki, Sourcegraph Cody, Greptile, Atlan, Collibra, Alation | Closest to Metis: code docs, lineage, catalogues, agent context. |

Where Metis is ahead: every line carries a checked source (`verify_kb.py`), a lead certifies changes, answers are
scored from the KB lines found (never claimed by a model), edges are labelled `parsed`, `catalogue` or
`ai-proposed`, and there is an MCP server and token-budgeted context packs. Most commercial tools do not check a
quote against the source.

Legend: **Yes** = built. **Part** = built but smaller than commercial tools, or CLI only. **No** = not in Metis.
"Can add" is my judgement of whether it fits Metis' design (git folder, standard library, evidence rule, lead gate).

## 2. Feature list

### A. Content creation and authoring

| # | Feature | Commercial tools | In Metis | Can add | Note |
|---|---|---|---|---|---|
| A1 | AI-generated pages from sources | Swimm, DeepWiki, Atlan, Document360 AI | Yes | n/a | `kb-build`, ~60 prompts and skills |
| A2 | Page templates and standard structure | All | Yes | n/a | `kb-prompts/`, `PROMPT_STANDARD.md` |
| A3 | Import of Word, PDF, Excel, PowerPoint, zips | Document360, Guru, Notion | Yes | n/a | `doc_intake.py`, `doc_images.py` |
| A4 | Confluence and SharePoint import | Most | Yes | n/a | `doc_intake.py` |
| A5 | Import from other sources: Google Docs, Notion, ServiceNow, Zendesk, GitHub wiki, Slack, Teams chat | Glean (100+ connectors), Guru, Rovo | Part | Yes | Built: Slack and Teams JSON exports, read by `read_docs.py` with a `msg<n>` anchor per message. Not built: Google Docs, Notion, ServiceNow, Zendesk, GitHub wiki (each needs its own export format or live API). Tested on hand-written fixtures, not real exports |
| A6 | Meeting, video and audio transcript capture | Guru, Notion, Slite, Loom | Part | Yes | Built: WebVTT and SRT transcripts, read by `read_docs.py` with a `t<hh:mm:ss>` anchor per cue and the speaker kept. Not built: speech-to-text, so audio and video need a transcript first. Speaker names are only as reliable as the tool that wrote the file |
| A7 | Browser or Slack "save this as KB" capture | Guru, Tettra, Slite | Part | Yes | Built: `capture.py` turns a pasted note into a page with one sourced line per line given, the exact text kept in `_EVIDENCE/files`, and the page staged in `_PENDING` once the gate is closed. Not built: the browser extension or Slack bot that would call it (needs a hosted endpoint). It records who said it, not that it is true |
| A8 | WYSIWYG rich-text editor in the browser | All wiki tools | No | No (by design) | Pages are markdown in a git folder under a lead gate. An editor would write straight to the KB and bypass staging. A staged "propose edit" form is possible; a live editor is not |
| A9 | Real-time multi-user co-editing | Confluence, Notion, Google Docs | No | No | Needs a server with operational transform or CRDT and a database. It conflicts with git-based review, and Metis runs on the standard library with local state |
| A10 | Propose-an-edit by any reader | Guru ("flag/suggest"), Document360 | Yes | n/a | `page_suggest.py` and `/suggest`; reader proposals with evidence stage into `_FEEDBACK/suggestions.yaml` and batch review |
| A11 | Image and diagram embedding | All | Part | Yes | Diagrams are generated (`db-diagrams`, `etl-diagrams`, `VISUALIZATION/*.html`). No upload or edit UI |
| A12 | Auto-generated diagrams from code and schema | Swimm, Atlan | Yes | n/a | ERD, ontology, lineage, tech stack views |
| A13 | Code-linked docs that update when code changes ("living docs") | Swimm | Part | Yes | `build_plan.py` flags pages whose cited source changed; page rewrite still needs a refresh run. Auto-open a refresh PR from CI is addable |

### B. Search and answers

| # | Feature | Commercial tools | In Metis | Can add | Note |
|---|---|---|---|---|---|
| B1 | Keyword search over pages | All | Yes | n/a | Extractive search in `answers.py` |
| B2 | Semantic or vector search | Glean, Guru, Document360 AI, Cody | Yes | n/a | `kb_embed.py` hybrid RRF search with hashing, sentence-transformers, HTTP adapters; eval command against golden questions. Default off |
| B3 | Synonyms and business glossary | Document360, Guru, Zendesk | Yes | n/a | `/glossary`, widens Ask |
| B4 | Typo tolerance and "did you mean" | All | Yes | n/a | `miss_guidance()` |
| B5 | Cited answers with verbatim quotes | Glean, Rovo, Guru (links only) | Yes | n/a | Ahead of most tools |
| B6 | Computed confidence bands | Few | Yes | n/a | Not yet calibrated against ratings (known) |
| B7 | Generative natural-language summaries over many pages | Glean, Copilot, Rovo | Part | Yes | `kb_summaries.py` builds summary tree structures and prompts; Devin reasoning mode for multi-page answers |
| B8 | Chat-style conversational interface with follow-ups | Glean, Copilot, Rovo, Guru | Yes | n/a | `screens_chat.py` (`/chat`) multi-turn conversational interface with citation side panels and rating capture |
| B9 | Global search box across KB, questions, glossary | All | Yes | n/a | Top-bar search routes to `/search` (`kb_search.py`), searching heading chunks with BM25 and synonym expansion |
| B10 | Faceted filters (folder, owner, type, date, tag) | Document360, Confluence, Glean | Yes | n/a | `/search` supports facets for folder, document type, owner (`page_meta.yaml`), open questions, and stale review due dates |
| B11 | Search result ranking learned from clicks and ratings | Glean, Guru | Part | Yes | Built, off by default: `kb_search.py --feedback` nudges a page by its likes and dislikes, 3% per net rating, capped at +-10%, and only after 3 ratings. Not built: learning from clicks, or any model. The nudge is a fixed rule, not calibrated against your data, so check `adjusted` on results before turning it on in the profile |
| B12 | Personalised results by role or team | Glean, Rovo | Part | Yes | Built, off by default: `kb_search.py --team NAME` (or `auto` for an approver's team) lifts that team's pages by 15%; nothing is hidden. Labels already filter by role. Not built: a per-person history |
| B13 | Permission-trimmed answers (a user sees only what the source system lets them see) | Glean, Rovo, Copilot | Part | Part | `claim_labels.py` filters lines by role clearance (public/internal/confidential/restricted). Live source-system ACL inheritance is not built |
| B14 | Browser extension, Slack bot, Teams bot, in-app widget | Guru, Glean, Moveworks | No | Yes | Built on the MCP server or an HTTP answer endpoint. Needs a hosted endpoint and auth (see I5) |
| B15 | Public or customer-facing help portal with SEO | Document360, Helpjuice, Zendesk | No | No (out of scope) | Metis KBs contain internal code, schema and security facts, and the sensitive-value screen is pattern-based. A public portal needs a separate, human-written, publish-approved layer. A static export of selected pages is possible, but that is a different product |
| B16 | Multi-language and auto-translation | Document360, Helpjuice, Zendesk | No | Part | Translating a page breaks the evidence rule, because the translated line no longer matches the quoted source. Possible only as a separate read-only layer that is not verified. Language-agnostic search of English pages is possible with B2 |
| B17 | Voice / speech query | Few | No | No | No consumer for it |

### C. Quality, trust and governance

| # | Feature | Commercial tools | In Metis | Can add | Note |
|---|---|---|---|---|---|
| C1 | Source citation checked against source | None well | Yes | n/a | Key differentiator |
| C2 | Approval workflow, certification by named lead | Confluence, Document360, Guru | Yes | n/a | `kb_gate.py`, `/approve`, `/review` |
| C3 | Roles and permissions | All | Yes | n/a | `/teams`. Identity is a session name; see I5 |
| C4 | Audit log | Enterprise tiers | Yes | n/a | `/audit`, append-only log |
| C5 | Page owners and per-page review dates ("verify every 90 days") | Guru (verification), Document360, Confluence | Yes | n/a | `page_owners.py` stores owner and review frequency in `.metis/page_meta.yaml`; `codeowners.py` parses CODEOWNERS; managed on `/owners` |
| C6 | Stale-content detection | Guru, Document360 | Yes | n/a | `changed since build`, `build_plan.py`, stale marks in packs |
| C7 | Auto-reminders and expiry when content goes stale | Guru, Confluence | Yes | n/a | `page_owners.py due` tracks expired review dates; `notify.py` dispatches `review_overdue` and `stale_pages` alerts |
| C8 | Broken link and orphan page checker | Document360, Confluence apps | Yes | n/a | `kb_links.py` checks Markdown links, heading anchor slugs, and orphan pages, writing `CROSS-LAYER/LINK_CHECK.yaml` |
| C9 | Duplicate and near-duplicate detection | Guru, Document360, Bloomfire | Yes | n/a | `kb_dupes.py` detects near-duplicate pages and paragraphs using shingle hashing and Jaccard overlap, writing `CROSS-LAYER/DUPLICATES.yaml` |
| C10 | Contradiction detection across pages | Few | Yes | n/a | `kb_contradict.py` scans pairwise contradictory claims across tables, key-values, and sentences into `CONTRADICTIONS.yaml`; viewed on `/quality` |
| C11 | Gap detection: what users asked that the KB cannot answer | Zendesk, Document360, Guru | Yes | n/a | `kb_unanswered.py` reports unanswered asks, unaddressed dislikes, and open questions; opt-in salted hash miss counting on `/search` |
| C12 | Content health score per page and per KB | Guru, Document360 | Part | Yes | Coverage, trust signals, golden questions exist. No single rolled-up score by design ("raw signals, not a score"). Can be shown as a table without a score |
| C13 | Version history, diff, rollback | All | Yes | n/a | Git, plus archived copies on promote |
| C14 | Sensitive-data scanning | Enterprise DLP add-ons | Yes | n/a | `sensitive.py`. Pattern-based; cannot find names or free-text health data |
| C15 | Per-claim sensitivity and environment labels | Few | Yes | n/a | `claim_labels.py` supports `{env: prod; sensitivity: restricted}` line annotations with clearance-based filtering |
| C16 | Time-aware facts (valid from, valid to) | Few (Atlan, graph tools) | Yes | n/a | `facts_time.py` indexes `{valid-from:...; valid-to:...; superseded-by:...}` annotations into `.metis/facts.sqlite` for temporal queries |
| C17 | Regression testing of answer quality | Almost none | Yes | n/a | Golden questions. Scoring is lexical; LLM-judged is deferred |
| C18 | Guarantee that answers are always correct | None | No | No | Not possible. Metis can show that a quote exists in the source, not that the statement is right. State this limit to users |

### D. Analytics

| # | Feature | Commercial tools | In Metis | Can add | Note |
|---|---|---|---|---|---|
| D1 | Views, searches, top pages | All | Yes | n/a | `/usage`, per file |
| D2 | Likes and dislikes with reason | Guru, Zendesk, Document360 | Yes | n/a | Dislike needs a reason |
| D3 | Zero-result and low-confidence searches report | Document360, Zendesk | Yes | n/a | `kb_unanswered.py` aggregates low-confidence asks and unaddressed queries, displayed on `/search` Unanswered tab |
| D4 | Per-user and per-team usage | Glean, Guru | Part | Yes | Built: `telemetry.py report` counts use by the team that owns each page (`gate.teams`) and by who recorded it, with file names only. A reader is placed in a team only when listed as that team's approver, so most readers show "(not in a team)". Not built: a staff directory to map every reader to a team |
| D5 | Time-saved or ROI dashboard | Glean, Guru | Part | Yes | `kb-efficiency-gain` skill exists for CVBC (Jira baseline, Devin ACU). Not general |
| D6 | Trend over time (coverage, health) | Document360 | Yes | n/a | `kb_trend.py` records build-over-build verification and health counts into `.metis/trend.jsonl`; rendered on `/quality` |
| D7 | Cost per build and per answer | Few | No | Yes | Cost view is deferred; ACU data exists |

### E. Lineage, graph and impact (Metis strength)

| # | Feature | Commercial tools | In Metis | Can add | Note |
|---|---|---|---|---|---|
| E1 | Table-level lineage from SQL | Atlan, Collibra, Alation | Yes | n/a | `sql_links.py` (sqlglot) |
| E2 | Column-level lineage | Atlan, Collibra, Alation, dbt Cloud | Yes | n/a | `column_lineage.py` extracts column-to-column lineage using sqlglot and computes multi-hop column impact |
| E3 | Code dependency graph (Java, TS, Python) | Sourcegraph, Swimm | Yes | n/a | `code_links.py` extracts verified dependency links for Java, TypeScript, and Python with tree-sitter or pure-Python AST fallback |
| E4 | Impact analysis for a change | Atlan, Sourcegraph | Yes | n/a | Impact matrix, `/pack`. Impact screen is CLI only |
| E5 | Interactive graph explorer (KB map) | Atlan, Collibra | Yes | n/a | `screens_map.py` provides `/map` clustered architecture overview and interactive SVG radial neighborhood view up to 300 nodes |
| E6 | Ticket to impact | Few | Yes | n/a | Ticket impact extracted in `/pack` and explored interactively on `/impact` |
| E7 | Impact comment on pull requests | Swimm, Cody, CodeRabbit | Yes | n/a | `bb_pr.py` posts PR impact analysis comments to Bitbucket Server and Cloud; dry-run by default, requires `--post` |
| E8 | Cross-team impact | Atlan, Collibra | Yes | n/a | `cross_impact.py` performs upstream and downstream impact walks across registered KBs in `shared.sqlite` on `/federation` |
| E9 | Live metadata sync from catalog / BI tools (Tableau, Power BI, Airflow, dbt Cloud) | Atlan, Collibra | No | Yes | New readers; each tool needs read credentials |
| E10 | Data quality and profiling results | Atlan, Collibra | No | Part | Metis reads metadata, not row data. Profiling needs data access that the evidence rules and the sensitive-value screen are designed to avoid. Ingesting results from a quality tool is possible |

### F. Agent and developer integration

| # | Feature | Commercial tools | In Metis | Can add | Note |
|---|---|---|---|---|---|
| F1 | MCP server | Newer in Glean, Atlan, Sourcegraph | Yes | n/a | Read plus record tools only; no write. Not yet tried against a real agent client |
| F2 | Token-budgeted context pack | Cody, Cursor-style context | Yes | n/a | Ahead of most tools |
| F3 | Rationale: ADRs, incidents, decisions | Swimm, Confluence | Yes | n/a | `adr_ingest.py` ingests Nygard/MADR decision records and post-mortems into `context/decisions/` and `context/incidents/` |
| F4 | Procedural: runbooks, test recipes | Swimm | Yes | n/a | `recipes_ingest.py` ingests runbooks, scripts, and CI pipelines into `context/procedures/` with needs-confirm marks |
| F5 | CODEOWNERS and ownership mapping | Backstage, Cortex, OpsLevel | Yes | n/a | `codeowners.py` parses GitHub and Bitbucket CODEOWNERS to route pages, questions, and review items; `page_owners.py` manages ownership |
| F6 | Public REST API | Most SaaS | Part | Yes | Built: a read-only JSON API under `/api/v1/` (search, page, impact, questions, glossary, onboarding) in `tools/ui/api.py`, behind the UI's own password or OIDC session and the claim-label filter. Not built: API keys, rate limits, CORS, or any auth fit for the public internet. Without OIDC the caller's name is an unproven cookie, so use it on a trusted network only |
| F7 | Export to standard formats: Markdown, PDF, HTML site | Document360, Confluence | Part | Yes | Markdown in git; exports to RDF, PROV, OTel, and OKF bundles on `/federation`. PDF and static site export not built |
| F8 | Export to RDF, SPARQL, OWL, OKF | Atlan, Collibra | Yes | n/a | `export_rdf.py` (Turtle/N-Triples/JSON-LD/OWL, pure-Python SPARQL query engine) and `okf_bundle.py` (OKF-shaped bundle packager/validator) |
| F9 | llms.txt style index, OpenAPI | Newer | Yes | n/a | `/llms.txt` lists the pages the caller may see with their API links, and `/openapi.json` describes the API (`tools/ui/api.py`). The OpenAPI file is hand-built from the endpoint table and has not been run through an external validator |

### G. Collaboration and workflow

| # | Feature | Commercial tools | In Metis | Can add | Note |
|---|---|---|---|---|---|
| G1 | Comments and discussion on a page | All wiki tools | Yes | n/a | `page_suggest.py` and `/suggest` support threaded reader comments and lead replies stored in `_FEEDBACK/suggestions.yaml` |
| G2 | @mentions, assignments | Confluence, Notion | Part | Yes | Questions have a role and priority; no per-person assignment |
| G3 | Slack and Teams notifications | Guru, Document360 | Yes | n/a | `notify.py` dispatches deduplicated alerts to Slack, Teams Adaptive Cards, and generic webhooks for batches, questions, and tasks |
| G4 | Email digests (what changed, what needs review) | Guru, Confluence | Yes | n/a | `notify.py` sends SMTP email alerts and digests for overdue reviews, stale pages, and pending certifications |
| G5 | Jira integration | Confluence, Guru | Part | Yes | Reads Jira (tickets to packs, dashboard). No two-way link; Metis is read-only toward Jira by rule |
| G6 | Onboarding paths and learning tracks | Guru, Bloomfire, Notion | Part | Yes | Built: `onboarding.py` makes a reading path for a team, approver or role from its pages, the graph, the glossary and its open questions. The page order is a count of graph objects named in each page, not a judgement of importance. Not built: tracks, quizzes, or progress tracking |
| G7 | Writing back to source systems (create Jira, edit Confluence) | Many | No | No (by design) | Metis is read-only against sources (`metis-writes` rule). Changing that removes a core safety property |

### H. Operations and deployment

| # | Feature | Commercial tools | In Metis | Can add | Note |
|---|---|---|---|---|---|
| H1 | Scheduled refresh | Atlan, Glean | Part | Yes | `refresh_trigger.py schedule` prints cron/Devin schedule commands; incremental stale detection in `build_plan.py` |
| H2 | Event-driven refresh on commit or merge | Swimm, DeepWiki | Yes | n/a | `refresh_trigger.py` plans incremental refreshes from git commits or HMAC-signed webhooks (`serve-webhook`) and queues tasks |
| H3 | Per-source on/off and cost estimate before a run | Few | No | Yes | In the mockup, not built |
| H4 | Live run view with streaming logs | Few | Part | Yes | Task page and log exist. No streaming |
| H5 | Multi-tenant hosted SaaS | All commercial tools | No | No (by design) | Metis runs locally or in a Devin session, standard library, one KB folder per team. SaaS means hosting, tenancy, billing, security certification. A different business |
| H6 | High availability, SLA, SOC 2 | All commercial tools | No | No | An operating model, not a feature. Applies only if Metis becomes a hosted service |
| H7 | Scale to very large KBs (100k+ nodes) | Atlan, Glean | Part | Yes | SQLite graph and `test_scale.py` exist. Whole-graph rendering at 100k nodes is deferred |
| H8 | Dark mode, mobile layout | Most | Yes | n/a | `/theme` supports auto, light, and dark color modes with CSS variables; responsive layout for mobile viewports (<=800px) |
| H9 | Native mobile app | Guru, Notion | No | No | No consumer. Responsive layout (H8) is enough |

### I. Identity and enterprise

| # | Feature | Commercial tools | In Metis | Can add | Note |
|---|---|---|---|---|---|
| I1 | SSO (SAML, OIDC) | All enterprise tiers | Yes | n/a | `auth_oidc.py` implements OIDC PKCE SSO with RS256 ID-token verification and group-to-role mapping |
| I2 | SCIM user provisioning | Enterprise tiers | No | Part | Only worth it after I1 and a hosted model |
| I3 | Standards-based provenance (W3C PROV, OpenTelemetry) | Atlan | Yes | n/a | `export_prov.py` exports W3C PROV-O (Turtle, JSON) and OpenTelemetry OTLP JSON traces and logs |
| I4 | Data residency and encryption at rest | Enterprise tiers | Part | n/a | KB is in your own git repo; the `cvbc-local-only` rule keeps it in session. Residency follows your repo |
| I5 | Cryptographically bound approver identity | Enterprise tiers | Yes | n/a | With OIDC SSO enabled, user identity is cryptographically bound from verified ID-token claims and recorded on gate actions |

## 3. Counts

Counted by script from the tables above (95 rows), by the "In Metis" column:

- Yes (built): 58
- Part: 21
- No: 16

Of the 37 rows that are Part or No, by the "Can add" column:

- Yes, can add: 23
- Part, can add in part: 4 (B13, B16, E10, I2)
- No, should not or cannot: 9 (A8, A9, B15, B17, C18, G7, H5, H6, H9)
- Not applicable: 1 (I4, already covered by where the KB is stored)

## 4. What cannot or should not be added, and why

| Feature | Verdict | Reason |
|---|---|---|
| Real-time co-editing, live WYSIWYG editor (A8, A9) | No | The KB is markdown in git behind a lead gate. A live editor writes around that gate. Offer "propose an edit", which stages a batch |
| Public customer help portal (B15) | No | Metis content is internal and sensitive. Public content needs a human-written publish layer |
| Auto-translation inside the verified KB (B16) | Part | A translated line cannot match its quoted source, so the evidence check fails. Only as an unverified read-only layer |
| Live source-system permission inheritance (B13) | Part | Content is copied into git. Only labels and role checks are possible |
| Write-back to Jira, Confluence, Bitbucket (G7) | No (except PR comments) | The read-only rule is a safety property. A PR comment is the one write worth reviewing |
| Hosted multi-tenant SaaS, SLA, SOC 2 (H5, H6) | No | Operating model change, not a feature |
| Guarantee of correct answers (C18) | Not possible | A quote check proves the words are in the source, not that the statement is true. This is already stated in the changelog |
| Column lineage and code graph that are 100% complete (E2, E3) | Part | Dynamic SQL, `SELECT *`, reflection and runtime-built calls cannot be resolved statically. Mark the rest `ai-proposed` |
| Data profiling from row data (E10) | Part | Metis avoids reading row values. Ingest results from a quality tool instead |
| Native mobile app, voice (H9, B17) | No | No consumer |

## 5. Recommended order

The first group closes the biggest gap against commercial tools and fits Metis' evidence model.

1. **Page owner and review-due date, with a stale-review report (C5, C7, F5).** Commercial KBs lead with "verified every N days". Metis has the pieces (certification record, `gate.teams`, stale detection) but not the field.
2. **Unanswered-question and zero-result report (C11, D3).** Uses telemetry and miss guidance that already exist.
3. **Global search and facets (B9, B10)**, then **hybrid semantic search (B2)** as an optional dependency, judged by golden questions.
4. **Propose-an-edit on any page (A10)** and **inline comments (G1).**
5. **Notifications to Slack, Teams, email (G3, G4).**
6. **Bitbucket PR impact comment (E7)** and **event-driven refresh (H2).** Both need your Bitbucket and CI details.
7. **tree-sitter code graph (E3)** and **column lineage (E2).**
8. **Duplicate finder (C9), link checker (C8), trend history (D6).**
9. **SSO (I1)**, only when an identity provider is available.
10. **Chat-first UI (B8)**, **exports (F7, F8)**, **more connectors (A5, E9)**, as demand appears. A5 now covers Slack and Teams exports only.

Built on 16 Nov 2026 from this list (rows now Part, except F9): A5, A6, A7, B11, B12, D4, F6, F9, G6. Left out on purpose: B14 (bots and extensions need a hosted endpoint and auth), E9 (live BI sync needs credentials), D7 and H3 (cost views), A13, G2, G5, H4, H7.

## 6. Things to confirm before building

- B9: top-bar search routes to `/search` when registered, with automatic fallback to `/files`.
- F1: the MCP server is tested through the protocol handler and local process, not through a real agent client.
- The "commercial tools" column is from general knowledge. Pick two or three tools you must match and I can check each against its current docs.

### What still needs the user's environment to verify
The following built components were verified locally with unit tests and fakes/mocks, but require live external enterprise environments to fully confirm end-to-end operation:
- **Single Sign-On (OIDC)**: `auth_oidc.py` tested against an in-process fake IdP; requires your corporate identity provider (Azure AD, Okta, Ping) to verify claim names, redirect URIs, and group mappings.
- **Bitbucket PR Impact Comments**: `bb_pr.py` tested against fake REST endpoints; requires your Bitbucket Server/DC or Cloud instance to verify bearer token permissions, comment route, and markdown filter behavior.
- **Push Notifications (Slack, Teams, SMTP)**: `notify.py` tested against fake HTTP and SMTP servers; requires your active Slack webhook URL, Teams Workflows endpoint, and corporate SMTP mail host.
- **Hybrid Embeddings & LLM Judge Endpoints**: `kb_embed.py` and `llm_judge.py` HTTP modes tested against fake transports; require your OpenAI-compatible endpoint and API keys.
- **OpenTelemetry Collector**: `export_prov.py --post` tested locally; requires your active OTLP/HTTP collector.
- **Official OKF Validator**: `okf_bundle.py` validated against internal structural consistency rules; requires the official Open Knowledge Foundation validator for external compliance certification.
- **Tree-Sitter Binary Bindings**: `code_links.py` tested on pure-Python AST fallback; requires tree-sitter package installed in environment for native AST parsing.
- **Live Confluence and SharePoint Intake**: `doc_intake.py` tested against local text snapshots; requires live Confluence spaces and SharePoint libraries to test real API pagination and session tokens.
- **Devin Task Queue**: `tasks.py` and `refresh_trigger.py` queue tasks in `.metis/tasks/`; require active Devin sessions to claim and complete tasks.
- **Slack, Teams and meeting-transcript readers**: `read_docs.py` tested on small hand-written Slack JSON, Teams (Graph) JSON, WebVTT and SRT fixtures; real exports vary by tool and version, so run one real export of each through `doc_intake.py` before relying on them.
- **Read-only API, `/llms.txt`, `/openapi.json`**: `tools/ui/api.py` tested against the real UI server on a local port; the OpenAPI file has not been checked with an external validator or a real client, and the caller's name outside OIDC is an unproven cookie. Confirm the auth model suits your network before sharing the URL.
- **Search nudges (team boost, feedback)**: `kb_search.py` rules are fixed numbers (15%, 3% per rating, cap 10%, 3 ratings minimum) tested on small fixtures; they are not calibrated on your questions. Compare results with and without them on your golden questions before turning `search.feedback_rank` on.
- **Capture, onboarding paths, per-team usage**: `capture.py`, `onboarding.py` and `telemetry.py` team counts are tested on fixtures; team and approver names come from your `gate.teams` profile, so check the output against how your teams are really set up.
