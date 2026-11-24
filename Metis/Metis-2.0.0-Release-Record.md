# Metis 2.0.0: release record

Decided 14 Nov 2026. This file is the record of what ships in which release. Nothing here is dropped: an item
that is not in the MVP is moved to the next release with the trigger that brings it back.

Test applied to every component: it must name a consumer who uses it in the release, and a decision that consumer
makes with it. If it cannot, it moves to the next release.

## Release 2.0 (MVP): what ships

### Core (kept as is from 1.2.5)
| Item | State |
|---|---|
| Evidence rule and `verify_kb.py` (zero problems to finish a build) | Built in 1.2.5 |
| KB build (`kb-build`, prompts, staging, one PR) | Built in 1.2.5 |
| Lead certification gate (`kb_gate.py`), `_PENDING` staging | Built in 1.2.5 |
| Ask with cited, checked answers (`metis-ask`) | Built in 1.2.5 |
| Like / dislike on answers, with a reason; a correction becomes a question for a lead (`feedback.py`) | Built in 1.2.5 |
| Open questions register (`questions.py`, `VALIDATE_KB`) | Built in 1.2.5 |
| Golden and competency questions (`golden.py`) | Built in 1.2.5, scoring is lexical (see below) |
| Document intake with provenance (`metis-ingest`) | Built in 1.2.5 |
| Sensitive-value screen (`sensitive.py`) | Built in 1.2.5 |

### New in 2.0 MVP
| # | Item | Consumer and decision | State |
|---|---|---|---|
| 1 | Impact matrix warns on relations and node types it cannot use; `handled_by` and `handled by` are the same relation | KB owner: is the impact complete? | Built (`gen_matrix.py`) |
| 2 | Coverage report: objects and tables no page names, rejected links, relations and types not understood, open questions blocking | KB owner: what does the KB not know? | Built (`kb_coverage.py`, run by `build_outputs.py`). "Files with no owner" is not measured: the graph has no owner field |
| 3 | Context pack builder (command line): token budget, headline fallback, impact list first, pack id, citations kept, stale marks, secret screen | A developer or an agent session starting a task | Built (`context_pack.py`, skill `metis-context`). Whole page or headline only; no per-page summaries yet |
| 4 | Agent read path: the pack is fetched by command line, same options as the UI | An agent session | Built as the command line and as an MCP server (`tools/mcp_server.py`, stdio, standard library only; pack, trust signals, find objects, hints, answer check, record use, rate answer, raise question). Not offered by design: approve, certify, write pages. Tested through the protocol and as a real process; not tried against a real agent client |
| 5 | Consumption telemetry: which KB files a pack or answer used | KB owner: what is read, cited, ignored | Built (`telemetry.py`; `metis-ask` records answers). `report` joins usage to likes and dislikes by cited file ("look first" list). A dislike names an answer, not a page, so the join is a pointer, not a verdict. Not built: the screen, and per-line (not per-file) attribution |
| 6 | Parser-built graph (sqlglot, tree-sitter), every edge labelled `parsed` or `ai-proposed` | KB owner: how far to trust an impact line | SQL half built (`sql_links.py`, optional `pip install sqlglot`): table-level links from .sql files, `origin` on every edge (`parsed`, `catalogue`, `ai-proposed`) set from the file name, shown in the impact list, `graph_store.py` and the coverage report. SQL it could not read is listed. Not built: tree-sitter for Java, TypeScript and Python code, and column lineage |
| 7 | One codebase, one profile-driven CLI (remove hard-coded team and machine values) | Every team | Half done. Built: the shared tools (`tools/viz/*`, `tools/index/kb_index_build.py`, `tools/etl_layer_lineage.py`, the gallery template) no longer name any product, team, logo or machine path; they read the KB profile's `viz:` section through `tools/site_paths.py` and need `METIS_KB`. `test_site_paths.py` fails if a product or team name returns to those files. Not done: the `cvbc/` and `team/` folders still hold team-specific tools. Measured: `cvbc/tools/build_data_cvbc.py` and `tools/viz/build_data.py` are the same program (97% alike), but the three dashboard builders (`cvbc/tools/hub2.py`, `team/tools/team_hub.py`, `tools/viz/hub.py`) and the two KB generators (`gen_kb.py`, `team_kb.py`) are different programs (13% to 20% alike), about 3,000 lines with no tests, part of them needing live Confluence, Jira and Snowflake. Merging them is a rewrite, not a cleanup. The refactored `tools/viz` pipeline was syntax-checked, not run end to end |
| 8 | Raw trust signals shown instead of confidence bands: parsed or AI-proposed, quote verified, source age, blocked by an open question | Reviewer: can I approve this? | Built without the UI: `trust.py` (`page`, `edge`), and in every context pack line. "Source age" is "changed since the last build" (git), not days; the quote check is "words found in the source", not "statement is right". Not built: the screen, signals in the review queue PR body |
| 9 | Review queue, one PR per owning team, risk-ranked | Tech lead | Built without the UI: `gate.teams` in the profile, `review_queue.py` (`queue`, `plan`, `certify --team`). `plan` writes one PR body and branch name per team; it does not run git or open the PR. Not built: bulk approve with sampling, the screen |

### MVP screens
Home, KB files, Ask (with like / dislike and the reason on dislike), Approve, Questions, Coverage, Golden questions,
Context pack. Everything else below waits.

Note on what was built: the first UI build (the "MVP UI" in the changelog) shipped Home, Setup, Build, KB files, Ask,
Questions, Approve and Coverage. Setup and Build were needed to run the product from the UI; Golden questions and
Context pack were not in that first build. Both were added afterwards with the screens below, so all ten of the
screens named above now exist.

### Built after the MVP UI (moved out of "deferred")
These were deferred in the first draft of this record and are now built, each with tests. (Screen and test counts are in the block under "Counts" at the end of this record; they were out of date here before.)

| Item | Screen | Notes and limits |
|---|---|---|
| Golden questions | `/golden` | Scoring is lexical. No remove button |
| Context pack | `/pack` | The pack is kept in memory only (last 20) |
| Business glossary | `/glossary` | Synonyms widen Ask searches; a broken glossary never stops an answer |
| Review queue, trust signals, bulk approve with sampling | `/review` | Sampling applies to batches over 10 files. A sample is not a check of the rest |
| Confidence bands | Ask and `/usage` | Computed from KB lines found, never claimed by a model. Bands are not yet calibrated against ratings; `/usage` shows the check with Wilson intervals, and the trigger in the table below still applies |
| Usage screen | `/usage` | Per-file, not per-line |
| Audit log screen | `/audit` | |
| Teams and rights screen | `/teams` | |
| Settings screen | `/settings` | |
| Compare and promote screen | `/compare` | A locked KB turns a promote into a proposed batch for a lead |

Still not built from the old "screens outside the MVP" row: onboarding wizard, live run view, cost view, detected setup
scan as its own screen, feedback review as its own screen (feedback review is done inside Approve).

### Built after the MVP (second pass)
The second-pass feature build completed all remaining functional workstreams (W1–W8), adding 10 new screens and associated CLI tools. Every moved component satisfies the consumer and decision test:

| Item | Consumer and decision | Tool / Screen | Notes and limits |
|---|---|---|---|
| Approve by area | Tech lead / Area approver: certify batches by path glob | `review_queue.py` (`certify_area`), `/owners` | Pattern-based area matching; requires named certifier |
| Page ownership, review cycles & CODEOWNERS | Tech lead: who owns this page, when is it due | `page_owners.py`, `codeowners.py`, `/owners` | Stores metadata in `.metis/page_meta.yaml`; CODEOWNERS uses glob conventions |
| Reviewer stats & recalibration proposals | Tech lead: advisory routing and confidence tuning | `reviewer_stats.py`, `recalibrate.py`, `/owners` | Advisory proposals in `.metis/CALIBRATION_PROPOSAL.yaml`; never auto-edits code |
| Content search & faceted filters | Developer / reader: find specific facts across pages | `kb_search.py`, `/search` | BM25 chunk search (FTS5 / pure-Python) with facets and synonym expansion |
| Hybrid vector search & eval | Developer / reader: find concepts with mismatched terms | `kb_embed.py`, `/search` | Default off; eval CLI; sentence-transformers and HTTP embedder need your environment to verify |
| Unanswered query report & miss counting | KB owner: what is missing from the KB | `kb_unanswered.py`, `/search` | Salted SHA-256 miss counter (`search.count_misses: true`); reads low-confidence asks and open questions |
| Area summaries (GraphRAG) | System architect: big-picture domain summary | `kb_summaries.py` | Builds `SUMMARY_TREE.yaml` and `PROMPT.md`; prose writing requires Devin/Bob session |
| Chat-first interface | General reader / BSA: interactive conversational Q&A | `screens_chat.py`, `/chat` | Multi-turn extractive chat; threads persisted per user in `.metis/chat/` (up to 50 threads / 200 messages) |
| Code dependency links | Developer: verified code call graph and API endpoints | `code_links.py` | Java, TS, Python; tree-sitter optional with pure-Python AST fallback; verified locally with AST; unparsed dynamic calls flagged |
| Column-level lineage & impact | Data engineer: which columns break if table.column changes | `column_lineage.py`, `column_impact` | sqlglot optional; traces SELECT/CTEs/dbt; unexpanded SELECT * without catalog listed in unresolved |
| Build-time contradiction finder | Reviewer / lead: do staged facts conflict with live KB | `kb_contradict.py`, `/quality` | Pattern matching across tables/key-values; heuristic confidence; cannot catch arbitrary prose conflicts |
| LLM-judged citations & golden scoring | QA lead / lead: semantic citation accuracy check | `llm_judge.py`, `/quality` | File judge (needs Devin/Bob session) and HTTP judge (tested on fake opener, needs your endpoint to verify) |
| Near-duplicate and link checker | KB owner: clean up redundant or broken content | `kb_dupes.py`, `kb_links.py`, `/quality` | MinHash/SimHash shingle Jaccard matching; internal link/anchor/orphan audit |
| Build trend metrics & line telemetry | KB owner: track verification health and citation lines | `kb_trend.py`, `telemetry_lines.py`, `/quality` | Appends counts to `.metis/trend.jsonl`; salted SHA-256 line fingerprints track lines across edits (`telemetry_lines.py reanchor`) |
| Push notifications & refresh triggers | On-call / lead: get alerts on batches, questions, tasks | `notify.py`, `refresh_trigger.py`, `/notify` | Slack, Teams, webhook, SMTP alerts (tested on local fakes, need your environment); HMAC webhook server |
| Bitbucket PR impact comments | PR author / reviewer: downstream impact before merge | `bb_pr.py`, `/notify` | Dry-run default; requires `--post`; Bitbucket comment route unconfirmed, needs your Bitbucket environment |
| RDF, SPARQL, OWL export | External graph tool / architect: query KB without Metis | `export_rdf.py`, `/federation` | Turtle/N-Triples/JSON-LD/OWL; built-in SPARQL subset engine; full SPARQL 1.1 needs rdflib |
| W3C PROV & OpenTelemetry export | Auditor / observability team: provenance & trace ingest | `export_prov.py`, `/federation` | PROV-O Turtle/JSON and OTLP JSON traces/logs; `--post` needs your collector endpoint to verify |
| OKF v0.2 bundle packaging | External data consumer: standardized KB bundle | `okf_bundle.py`, `/federation` | OKF-shaped bundle packager and local validator; formal compliance needs official OKF validator |
| Shared cross-team read index | Cross-team engineer: search across team KBs | `shared_index.py`, `/federation` | Stored in `shared.sqlite`; certified and non-sensitive pages only |
| Cross-team impact walks | Multi-team architect: trace dependencies across teams | `cross_impact.py`, `/federation` | Upstream and downstream walks across `shared.sqlite` by normalized identity and same_as links |
| Time-aware facts | Historical analyst / auditor: what was true at date X | `facts_time.py` | Line and section `{valid-from:...; valid-to:...; superseded-by:...}` annotations; `.metis/facts.sqlite`; `page-at` needs git |
| Per-claim environment & sensitivity labels | Security officer: role-filtered KB views | `claim_labels.py` | `{env:...; sensitivity:...}` annotations; clearance filtering enforced across pack, Ask, search, chat, MCP, `/files`, exports; audit CLI |
| Reviewer trust weights & routing | Tech lead: advisory routing and sampling | `reviewer_stats.py`, `review_queue.py route`, `/owners` | Advisory trust weights from Wilson intervals, contributor track records, suggested routing, fast-lane sampling labels |
| Rationale & ADR context ingest | System architect: why architecture decisions were made | `adr_ingest.py` | Ingests Nygard/MADR/incidents into context; Confluence/SharePoint intake needs your environment |
| Procedural context recipes | On-call engineer: operational runbook guidance | `recipes_ingest.py` | Ingests runbooks and CI pipelines; marks destructive steps needs-confirm; never executes commands |
| Propose-an-edit & threaded comments | Reader / lead: suggest corrections on any page | `page_suggest.py`, `/suggest` | Staged batch approval replaces single lines; multi-line changes routed as open questions |
| Whole-KB graph map & impact view | Architect / lead: visual architecture exploration | `screens_map.py`, `/map`, `/impact` | Clustered layer overview and SVG radial neighborhood view (capped at 300 nodes) |
| Dark mode, mobile layout & theme | Reader on mobile or dark IDE: visual comfort | `ui_common.py`, `/theme` | CSS variables; auto/dark/light cookies; responsive layout for viewports <=800px |
| Single Sign-On (SSO / OIDC) | Enterprise user / auditor: bound identity for actions | `auth_oidc.py`, `server.py` | RS256 PKCE flow tested against fake IdP; needs your identity provider to verify; SCIM is not built |

### Built after the architecture review (context engineering)
| Item | Consumer and decision | Tool / Screen | Notes and limits |
|---|---|---|---|
| Task-driven context pack | Developer / agent: what to read before this change | `context_pack.py --task`, `/pack`, `metis_context_pack` | Hybrid search picks pages that never name the object; full / sections / headline tiers; `stale="true"` attribute; tag escaping; `--tokenizer`. No per-page summaries |
| Retrieval benchmark | Lead: did a change make the pack worse | `pack_eval.py` | Recall, precision, hit@k, full-tier share against golden questions; baseline and `--min-recall` gate. Only as good as the golden set |
| Experimental registry | Lead: what is safe to rely on | `features.py`, profile `experimental.enable` | Screens of 12 untried-on-real-systems features are hidden from the menu until enabled. The command-line tools still run |
| Cross-process gate lock | Two leads certifying at once | `kb_gate.py` (`gate_lock`), `kb_promote.py` | File lock `.metis/gate.lock` plus atomic state write; single machine only, not a multi-writer database |
| Skill and prompt lint | Maintainer: context cost of the plugin | `skill_lint.py` | Estimates tokens (chars / 4 unless `--tokenizer`); flags long descriptions, writers without the evidence rule, near-duplicates |
| Doc counts from code | Reviewer: can I trust the numbers in this record | `doc_metrics.py` | Keeps the block under "Counts" equal to the code; loose numbers in older notes are history and are only reported |
| Source-check and confidence caveats | Reader of an answer | `verify_kb.py`, Ask, `/usage` | A pass means the quote is in the source, not that it is right; bands are labelled uncalibrated |
| Packaging | Installer | `pyproject.toml`, `requirements.txt` | PyYAML is the only required package; optional extras per feature. The folder is still named 1.2.5-team |
| Real-repo smoke test | Maintainer | `tests/test_smoke_sandbox.py` | Source check, search and `--task` pack over a copy of `sandbox/DEMO-KB` and the real jaffle-shop and spring-petclinic repos. Skipped if the sandbox is absent. Not CI and not a live MCP client |
| Asker-aware answers | Business, developer, tech lead, architect, support: the layer they need first | `audience.py`, Ask and Pack selectors, `--audience`, MCP `audience` | Four KB layers, five audiences; orders lines and pages and sets link lines and impact share; never changes a fact, tag or clearance. Weights are starting values, untested with real readers; a one-layer KB gives every audience the same lines |
| Stricter source check | Reader of an answer; lead | `verify_kb.py` (`verify.strict_tags`, `verify.support_min`) | A repo line range needs a quote in strict mode; a fact line must share words with its quotes. Lexical screen, not a judge; says nothing about a quote read wrongly |
| Enforced `Inferred:` | Reader of an answer; lead | `verify_kb.py` (`verify.inferred_rule`) | A line with conclusion wording, or citing 2+ different sources, must start with `Inferred:` (always for answers, off by default for pages). Looks at wording and source count; a conclusion written without those words is not seen |
| Stale-source warning in Ask | Reader of an answer | `ui/answers.py` (`freshness`), `build_plan.stale` | A cited page whose source changed since the build shows a pill and lowers confidence; never High. Needs `built-from.yaml` and the git clones; otherwise it says `not compared` |
| Search-ranked Ask | Anyone asking | `ui/answers.py` (`page_ranks`), `kb_search` | The best 3 pages let one-word lines in; ties broken by search rank; `ask.search: false` turns it off. Not measured on real questions (TD-8) |
| Layer in page front matter | KB builder; reader by audience | build prompts, `PROMPT_STANDARD.md`, `audience.py layers --strict` | Prompts write `layer:`; `--strict` fails when a layer is a guess. Existing pages without it keep the folder or source guess |
| Summaries in the pack and Ask | Anyone with area summaries | `context_pack.py`, `kb_summaries.drill_pages` | A matching `area-summary` page brings in the pages it covers. Needs summaries written by a session and certified by a lead; the demo KB has none; saving unmeasured (TD-9) |
| Judge-agreement sampling | Lead reviewer | `judge_agreement.py` | Draws a sample plus control lines, writes judge requests, scores a person's labels (needs 30+). No labels exist yet, so the agreement rate is still unknown (TD-6, TD-10) |


Open from that review, and not fixable in code alone: authentication (labels are a filter; see `documentation/TECH-DEBT.md` TD-3), a measured LLM-judge agreement rate (TD-6), calibrated confidence bands (TD-5, needs rating volume), and runs against real Bitbucket, Slack, SMTP, OIDC, OTLP, sentence-transformers and an MCP client (TD-4). `cvbc/` and `team/` are still inside the plugin (TD-1).

## Next release: deferred, nothing dropped

| Item | Why it waits | Trigger to bring it back |
|---|---|---|
| SCIM user provisioning | Identity synchronization; SSO authentication is built | Organization mandates automated user lifecycle provisioning over SSO |
| SHACL constraint validation | Research check: poor fit for a SQLite property graph | Replaced in Metis by JSON Schema plus SQL integrity checks; revisit only if an RDF triplestore is adopted |
| Reviewer scoring auto-approval | High risk of bypassing lead certification gate | Policy defines trusted contributor thresholds and leads explicitly request auto-approval |
| Live source-system ACL inheritance | Content is copied into git; live querying Confluence/SharePoint adds latency and runtime dependency | Real-time source ACL synchronization is mandated by enterprise security |
| Calibrated confidence bands (High / Medium / Low) | Bands are shown and recalibration proposals exist, but automated tuning needs high volume | Sufficient rating volume across all bands to prove calibration stability |
| Onboarding wizard, live run view streaming, cost view, detected setup scan screen, feedback review screen | Core functionality exists inside Setup, Build/Task, and Approve; dedicated streaming/wizard screens deferred | Each team asks for it, or a lead cannot do the task from the command line |

## Open decisions
- Which graph store, if any, beyond SQLite.
- Whether Bitbucket offers a route for pull request comments.
- How tech leads review (line by line or by trusting the author): decides how much approval tooling is worth building.

## Counts

<!-- metrics:begin -->
Counted from the code by `tools/doc_metrics.py`; run `python3 doc_metrics.py write` to refresh.
- Tests discovered: 100
- UI screens (paths in `server.SCREENS`): 5
- Tools (`tools/*.py`): 7
- Skills: 3
<!-- metrics:end -->
