# Metis feature build: master progress

Started 14 Nov 2026. This file is the one to hand to a new chat. Per-worker detail is in the other files in this folder.
Brief for all workers: `BRIEF.md`. Baseline: 391 tests (1 skipped). After W1-W8 and integration: 954 tests, OK (1 skipped). Those were the counts on those days; later passes added more. The current counts, taken from the code:

<!-- metrics:begin -->
Counted from the code by `tools/doc_metrics.py`; run `python3 doc_metrics.py write` to refresh.
- Tests discovered: 1231
- UI screens (paths in `server.SCREENS`): 29
- Tools (`tools/*.py`): 77
- Skills: 74
<!-- metrics:end -->

## Workstreams (all built; limits are in each notes file)

| ID | Scope | Notes file | Status |
|---|---|---|---|
| W1 | Page owners and review-due, stale-review report, CODEOWNERS, reviewer stats, recalibration proposals, approve by area, `/owners` | W1-governance.md | done |
| W2 | Content search (BM25, facets), hybrid search (off by default, eval command), unanswered report, area summaries, chat, `/search`, `/chat` | W2-search.md | done |
| W3 | Code links (Java, TS, Python; tree-sitter optional, pure-Python fallback), column lineage (sqlglot), column impact | W3-parsing.md | done |
| W4 | Contradiction finder, LLM-judge (file and HTTP), duplicates, link checker, trend, per-line telemetry, `/quality` | W4-quality.md | done |
| W5 | Notifications (Slack, Teams, webhook, email), Bitbucket PR impact comment, event-driven refresh, `/notify` | W5-integrations.md | done |
| W6 | RDF/OWL/SPARQL-subset, PROV and OTel export, OKF-shaped bundle, shared cross-team index, cross-impact, `/federation` | W6-export-federation.md | done |
| W7 | Time-aware facts, claim labels, ADR ingest, procedure ingest, propose-an-edit and comments, `/suggest` | W7-content.md | done |
| W8 | Dark mode and mobile, `/map` and `/impact`, environment switcher, OIDC SSO, top-bar search to `/search` | W8-experience-identity.md | done |

All screens load (`server.LOAD_FAILED` is empty; 27 on the day this line was written, current count in the block above). `/owners` was being skipped at start-up; fixed.

## Integration done by the lead
- `kb_gate.DERIVED`: contradictions, duplicates, link-check reports added.
- `kb_manifest.LOCAL`: trend, judge, contradict, search, facts, shared, exports, notify and refresh-plan files added.
- `build_outputs.py`: runs code_links, column_lineage, contradictions, duplicates, link check, trend as optional steps (a failure is printed and does not change the exit code).
- `screens_owners.py`: fixed an action redirect that made server skip the screen.

## Integration finished by the lead
- [x] Profile template: review, search, judge, parse, labels, notify, bitbucket, refresh, federation, otel, auth blocks (parses; all defaults keep old behaviour)
- [x] `kb_coverage.py`: reports files_without_owner from page_owners
- [x] `answers.py`: per-line telemetry through `_cited_lines` (never stops an answer)
- [x] `views.py`: "Suggest an edit" link on file pages
- [x] `gen_matrix.py`: understands the relations code_links writes (imports, reads table, writes table, exposes endpoint); module and function nodes are chain-only. Found by the full suite after wiring code_links into build_outputs
- [x] CHANGELOG, manual (section 9, new screens, safety text), Release Record, gap analysis, comparison doc (done by docs worker; see each file)
- [x] Full suite: 954 tests, OK (1 skipped). Live server on the demo KB: 26 screens return 200, search returns page-content hits, map draws SVG

## SECOND PASS (W9 to W12), state at end of session 2 (15 Nov 2026) - START HERE
Goal of this pass: build all items in manual section 9 "Coming Soon", mark each State "done" in the manual (keep honest limits), keep notes here.

| ID | Scope | Notes file | Status |
|---|---|---|---|
| W9 | Reviewer trust (advisory weights, track records, `route`, sampling label; never certifies) | W9-reviewer-trust.md | done, 155 group tests OK |
| W10 | Claim-label enforcement in pack, Ask, search, chat, MCP, shared index, RDF, OKF; `claim_labels.py audit` | W10-label-enforcement.md | done (gaps under "Not covered") |
| W11 | Verify optional paths with real components (venv `C:\Users\KRISHNAKonduru\AppData\Local\Temp\metis-venv`) | W11-verification.md | done (items 1-7 PASS, 4 export_rdf bugs fixed) |
| W12 | Telemetry fingerprints, persisted chat (`ui/chat_store.py`), section-level `facts_time`, `/files` label filter | W12-small-limits.md | done; W12 reported full suite 1083 tests OK, 6 skipped |
| MCP fix | `mcp_server.handle` replies -32600 to non-object messages, regression test added | n/a | done (a later external edit to `mcp_server.py` and `tests/test_mcp_server.py` was seen: re-run `tests.test_mcp_server`) |

### Pending, in order
1. **[DONE] W11 items 4-7**: items 4a/4b (MCP raw & SDK), 5 (kb_embed eval & unit tests), 6 (sqlglot on jaffle-shop), 7 (live UI 27 screen walk) all verified PASS in `W11-verification.md`.
2. **[DONE] Fix 4 `export_rdf.py` bugs**: (1) OWL space relations, (2) JSON-LD direct edge triples & IRI graph, (3) SPARQL subset ValueError on unsupported constructs, (4) rdflib ASK query TypeError fix. `test_export_rdf` and `test_export_rdf_rdflib` all 15 tests PASS.
3. **[DONE] Tidy `tests/test_mcp_server.py`** around line 73 (missing blank line before a `def`, extra blank lines after).
4. **[DONE] Profile template**: add the `review.trust` example block (exact text in `W9-reviewer-trust.md`) and any W10/W12 keys (e.g. `labels.share_max_sensitivity`) to `templates/kb-profile.yaml`. Use PowerShell `ReadAllText`/`WriteAllText` (the file has CRLF; `apply_diff` and `search_and_replace` failed on it). Re-check that it parses.
5. **[DONE] Manual section 9** (`documentation/Metis-2.0.0-manual.md`, about lines 734-765): set each item State to Done with a short limits note. Reviewer Scoring: Done (advisory, never auto-approves). Items that need the user's environment: "Done, needs your environment to verify: ..." (Bitbucket, Slack, Teams, SMTP, OIDC provider, embedding and judge endpoints, official OKF validator, MCP in Devin). Tree-sitter and rdflib are verified locally. Also fix lines saying chat is lost on restart and line numbers drift (W12 fixed both).
6. **[DONE] Docs**: update `CHANGELOG.md` (plugin root), `Metis-2.0.0-Release-Record.md`, `documentation/Metis-2.0.0-gap-analysis.md`, `documentation/Metis-vs-Commercial-KB-Builders.md` for W9-W12.
7. **[DONE] W12 hook** (screens_pack passes role=user, file_view filters by label, bb_pr keeps the lowest clearance on purpose; remaining gaps stay listed in W10 'Not covered'): `ui/views.py` `file_view` was edited by W12 (label filter). Review that edit, and apply the same filter to other page-reading views (`screens_pack`, `bb_pr`). Other "Not covered" items in `W10-label-enforcement.md`: Devin/model answer path, `kb_embed`, other readers of page text.
8. **[DONE] Final validation** (24 Nov: 1231 tests OK, 9 skipped): full suite from `metis-1.2.5-team (1)\tools`: `python -W ignore -m unittest discover -s tests -p "test_*.py"` (about 110 s: run with `background: true`; last known 1083 OK, 6 skipped), plus live server check of all screens. Update the count and Log.
9. User's own tasks: try the MCP server from Devin; verify the environment list below.

### Conventions to remember
- Standard library only, optional packages behind guarded imports. Evidence rule (`[E: ...]`), lead-certification gate and read-only sources stay. Only external write is the opt-in Bitbucket PR comment (dry-run default).
- Python 3.14, no pytest: use `unittest`. Workers must not edit shared files (`server.py`, `ui_common.py`, `views.py`, manual, CHANGELOG, profile template) unless told; the lead does that.

## First-pass leftovers (items 3 and 4 below were resolved in the second pass)

## Not done / next chat should pick up
- [ ] Try the MCP server from Devin (you said you will do this)
- [ ] Verify against your environment: see the list below
- [x] Labels are enforced in `context_pack.py` (role filter before ranking and budgeting), Ask, search, chat, MCP, `/files`, shared index and exports (W10, W12). Labels are a filter, not access control: no authentication, and the surfaces in `W10-label-enforcement.md` "Not covered" are still open
- [ ] `gen_graph.py` ignores the per-link `origin` written by adr_ingest: decision links show as ai-proposed (safe side)
- [ ] `tools/ui/ui_common.py` has rail icons for the new screens (W8 did this); check on screen
- [x] `docs`: the implementation plan named bitbucket_pr.py; the real file is bb_pr.py (fixed in the plan)
## Needs your environment to verify (cannot be proven here)
Devin MCP client, Bitbucket PR comments (route unconfirmed), Slack, Teams, SMTP, OIDC provider (tested only against a fake one), embedding endpoint and sentence-transformers, LLM judge endpoint, official OKF validator, tree-sitter (fallback tested; tree-sitter path not run if not installed).

## Log
- 14 Nov: brief created, 8 workers run in parallel, all finished. Full suite 954 OK.
- 14 Nov: integration finished, full suite 954 OK, live server check passed (26 screens).
- 15 Nov: second pass. W9, W10, W12 done; W11 items 1-3 done; MCP non-object fix.
- 15 Nov: W11 items 4-7 completed (all PASS); 4 export_rdf.py bugs fixed and verified against rdflib test suite.
- 24 Nov: items 3-8 checked in code and marked done. Full suite 1231 tests OK, 9 skipped. Remaining: user's own tasks (Devin MCP, environment verification) and the first-pass leftovers.
