# Argus trace lines

Argus's **Trace** tab shows, per SDLC stage, what a session actually loaded and decided:
agents active and queued, skills and why, rule files loaded or deferred, knowledge-base files
loaded or skipped (with the reason), cross-layer matrix chains used, ontology lookups (with why and what each gained), the gate waiting and who
owns it, and the decisions taken. It is the evidence behind "read a dozen files out of thousands".

It is built only from lines the session prints, in the same `[SDLC]` form as the progress lines
(`.devin/rules/gate-presentation.md` for gates). Nothing is inferred and nothing is invented:
this pipeline has no token counts or similarity scores, so none are printed or shown.

| Line | When | Example |
|---|---|---|
| `[SDLC] route <entry> — <module; layers; tables>` | the requirement matched (or did not match) an entry in `16_REQUIREMENT_ROUTING_MAP.yaml` | `[SDLC] route contract_approval — module Contract; layers db_schema, api_endpoints, fe_components; tables VBC_UI_CNTRCT_PARM` |
| `[SDLC] kb <repo path> — loaded: <why>` | a knowledge-base file is opened | `[SDLC] kb docs/knowledge-base/MODULES/.../10_ENDPOINT_REGISTRY.yaml — loaded: endpoints of the Contract module` |
| `[SDLC] kb <repo path> — skipped: <why>` | a file the routing could have called for is deliberately not read | `[SDLC] kb .../ETL/13_ETL_TABLE_IO_CONTRACT.yaml — skipped: no ETL layer in the routing match` |
| `[SDLC] rule <repo path> — loaded: <why>` / `deferred: <why>` | a `.devin/rules/*` file is read, or put off until a later stage | `[SDLC] rule .devin/rules/secure-coding.md — deferred: not needed before implement` |
| `[SDLC] chain <DC-id> — <what it links>` | a chain from `CROSS-LAYER/CROSS_LAYER_IMPACT_MATRIX.yaml` (or `.CURATED.yaml`) is used | `[SDLC] chain DC-003 — VBC_UI_CNTRCT_PARM.TERM_VAL_TXT → /api/contract/approved → Approved grid` |
| `[SDLC] ontology <command> <term> — <found>; why: <why>; gain: <gain>` | `tools/ontology_lookup.py` is run (`find`, `context`, `impact`, `scenarios`, `touches`, `check`) | `[SDLC] ontology find "TIN group" — Provider Group → CL_PG, 7 screens; why: the requirement says "TIN group", not a table; gain: one lookup instead of the four registries, no question to the BSA` |
| `[SDLC] graph walk <item> — <found>; why: <why>; gain: <gain>` | `ontology_lookup.py walk` follows `CROSS-LAYER/ACME_LINK_GRAPH.yaml` from a table, column, endpoint, screen, file or story | `[SDLC] graph walk CL_PG_LOB — 2 jobs, 2 screens, story ACME-1331; why: the story adds a column to CL_PG_LOB; gain: PG_syncup.sql and the bulk-upload screen added to the scope, ACME-1331 cases to re-run` |
| `[SDLC] drift <artifact> — <what was re-read>; why: <why>; result: <current\|moved\|stale\|not run>` | `ontology_lookup.py drift` or `tools/kb_sync.py` re-reads the file:line each link cites | `[SDLC] drift ACME_LINK_GRAPH.yaml — re-read 16 cited lines for CL_CNTRCT_PARM; why: the plan relies on those links; result: current` |
| `[SDLC] sync <artifact> — <action>: <detail>; why: <why>; result: <current\|updated\|stale\|not run>` | `tools/kb_sync.py` regenerates or checks the matrix, ontology, link graph and KB manifest | `[SDLC] sync ACME_LINK_GRAPH.yaml — regenerated: rebuilt from the ontology, matrix, test imports and story commits; why: the graph is built from the ontology, matrix, tests and commits; result: updated` |
| `[SDLC] qa <artifact> — read <repo> <branch>@<commit>: <what was read>; why: <why>; result: <current\|updated\|stale\|not run>` | `tools/kbgen/gen_qa_suite.py` (run by `tools/kb_sync.py`) reads the claims-qa Behave suite, read only, into the QA-suite coverage; `tools/qa_scenarios.py check` matches a draft's steps to the step library | `[SDLC] qa 03_QA_SUITE_COVERAGE.yaml — read ACME/claims-qa ACME_Automation_092025@4c82c06d: 12 feature files, 85 scenarios, 146 step definitions, 49 query keys, 264 TestData sets; why: new scenarios reuse the suite's steps, and a story's change picks the existing scenarios that test it; result: updated` |
| `[SDLC] evidence <claims file> — <n> claims: <v> verified, <u> unverified (<id>: <why>); why: <why>; result: <verified\|unverified, warning until …\|unverified, blocks SDLC_04>` | `tools/confidence.py claims` checks each claim's file:line, graph link, matrix chain or KB file | `[SDLC] evidence STORY-1-claims.yaml — 6 claims: 5 verified, 1 unverified (C4: api/apps/x/views.py has 80 lines, not 120); why: every claim in the plan needs a source; result: unverified, warning until 2026-11-25` |
| `[SDLC] tests <pack or link graph> — <n> test files from <m> changed files: <list>; why: <why>; result: <selected\|passed\|failed>` | `confidence.py tests` picks the tests, `confidence.py required` checks they ran | `[SDLC] tests REQ-001-STORY-1.yaml — 3 selected tests: 1 not run, 0 failed (api/apps/x/tests/test_views.py not run); why: every picked test must run; result: failed` |
| `[SDLC] contract <registry\|Snowflake> — <what was checked>; why: <why>; result: <passed\|warning\|failed\|not run>` | `confidence.py contract` checks table and column names and literal types in the changed SQL | `[SDLC] contract Snowflake — live column types, row counts and data rules; why: the registry can lag the database; result: not run` |
| `[SDLC] verify <story> — <tier> risk (<why>); why: <why>; result: <not run\|waiting\|passed\|failed\|no verifier needed>` | `tools/verifier.py` rates the story's risk, starts the read-only verifier session for medium and high-risk stories, records its verdict and checks SDLC_05 | `[SDLC] verify ACME-133 — high risk (RISK=1/2; chain DC-001 HIGH); why: medium and high-risk stories get a second, read-only session that did not write the code; result: high risk, verifier passed` |
| `[SDLC] decision <what> — <detail>` | a choice that shapes the rest of the work | `[SDLC] decision questions — 3 to the BSA (missing: environment, owner, date)` |
| `[SDLC] skill <name> — started: <why>` | as the progress line, with the reason after `started` | `[SDLC] skill impact-radar — started: find what else the new column touches` |

Rules:

1. Print the `kb` / `rule` line at the moment the file is opened or the decision not to open it is
   made — not as a summary afterwards. One line per file; repository-relative paths.
2. A skipped file needs a reason a person can check ("no ETL layer in the routing match", "module is
   Contract, run-request docs not read"). "Not relevant" is not a reason.
3. `chain` lines name the matrix id and the layers it links; the matrix is a starting point, so a
   chain the code contradicts is reported as a `decision`, not silently dropped.
4. `ontology` lines say what the lookup found, why the stage used it, and what it gained: something
   a person can check against the trace, such as registries not opened, ETL tables or systems the
   matrix does not list, open questions to ask, test cases from states and rules, or a rebuild the
   PR needs. "Faster" or "better context" is not a gain. If the lookup found nothing, say so and
   put `gain: none`. Where the registries or the code contradict the ontology, add a `decision` line.
5. `graph` lines follow the same shape as `ontology` lines: what the walk reached, why, and what it
   gained (screens, jobs, tests or stories added to the scope). A link the code contradicts is a
   `decision` line, and the walk result is not used for it.
6. `drift`, `sync` and `qa` lines end with `result:`. `not run` means the check could not run (no Snowflake,
   commit missing in a shallow clone); it is never written as `current` or `passed`.
7. The lines are additional to the progress lines, not a replacement; stage, agent, gate and
   artefact lines stay as they are. Outside an Argus-driven session they are harmless noise.
