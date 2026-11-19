# Playbook: Bottom-Up Research Pipeline (Code-First)

**Playbook ID:** PB-03  
**Paste into:** Devin Cloud → Settings → Playbooks → New Playbook  
**CLI equivalent:** `/intake` + `/research` (bottom-up path)  
**When to use:** Changing existing behaviour, bug fix, regulatory/compliance mandate, or any case where what code needs to change must be discovered first.

---

## Title

```
Acme Claims: Bottom-Up Research Pipeline (Code-First)
```

## Description

```
Runs the complete bottom-up SDLC pipeline: intake Q&A (technical layer
questions) → SDLC_01 gate → mandatory source staleness check → gap analysis
across DB/API/UI/ETL layers → impact analysis → SDLC_02 BSA gate → story
generation with complexity-matrix estimation → estimation audit → SDLC_03 +
SDLC_03a gates → Jira export.
```

## Playbook Body

---

You are running the **bottom-up** Acme Claims pipeline. Code inspection happens first — stories are derived from gaps found in the codebase.

---

## PHASE 1 — INTAKE

Ask technical, layer-aware clarifying questions. Max 2 per turn.

**Ask from these categories based on what the requirement mentions:**

**Scope & Boundaries**
- What is explicitly OUT of scope?
- Is this net-new behaviour or a change to existing behaviour?

**DB Layer** (ask if data change is mentioned)
- Which tables or columns are involved?
- Expected data type, size, nullability for any new column?
- Backfill needed for existing rows? RLS implications?

**API Layer** (ask if API/backend change is mentioned)
- New endpoint or extending existing? Request/response field changes?
- Breaking change? Auth/authorization implications?

**UI Layer** (ask if a screen or component is mentioned)
- Which page(s) or component(s)? What should users see/do differently?
- Role-gated (admins only, specific Acme Claims roles)?

**ETL/Pipeline** (ask if data pipeline is mentioned)
- Does the ETL pipeline need to supply new data? What is the data source?

**Performance & Scale**
- Expected record count / user volume? Any latency SLA?

**Acceptance Criteria**
- How will you know this is done? Give me a testable pass/fail criterion.

After all questions answered, write `{REQ_ID}-SPEC.md` to `framework/context/session/{OWNER}/{REQ_ID}/`.
`{OWNER}` is resolved per `.devin/rules/session-isolation.md`.

Show the draft to the user: "Does this capture the requirement? Type **YES** to write, or give me feedback."

### GATE: SDLC_01
> "Type **APPROVED** to continue to code inspection."
When APPROVED: update `approvals.yaml` phases.intake = approved.

---

## PHASE 2A — SOURCE STALENESS CHECK (MANDATORY — never skip)

**Before reading any KB doc as fact, check whether it is stale.**

**KB artifacts to check:**
| Artifact | Path |
|---|---|
| DB Table Registry | `docs/knowledge-base/DB-DOCS/DB_TABLE_REGISTRY.yaml` |
| DB Schema Summary | `docs/knowledge-base/DB-DOCS/DB_SCHEMA_SUMMARY.md` |
| DB Cross-Module Matrix | `docs/knowledge-base/CROSS-LAYER/CROSS_LAYER_IMPACT_MATRIX.yaml` |
| API Endpoint Registry | `docs/knowledge-base/MODULES/claims-web/api/10_ENDPOINT_REGISTRY.yaml` |
| FE Component Registry | `docs/knowledge-base/MODULES/claims-web/web/12_COMPONENT_REGISTRY.yaml` |
| ETL IO Contract | `docs/knowledge-base/ETL/claims-etl/13_ETL_TABLE_IO_CONTRACT.yaml` |

**Source code paths (always ground truth):**
| Layer | Path |
|---|---|
| API — Django | `api/` |
| Frontend — Next.js | `web/` |
| SQL / DB | `claims-etl/scripts/sql/` |
| ETL — Glue | `claims-etl-glue/` |
| ETL — Lambda | `claims-etl-lambda/` |

> Note: claims-etl-* repos are separate GitHub repositories and must be cloned independently.

For each layer touched by the requirement:
1. Read the KB artifact
2. Read the actual source code files
3. Compare and note what differs
4. Mark as CURRENT, STALE, or UNKNOWN

Produce a staleness table:
```markdown
## KB Staleness Check — {REQ_ID} — {date}
| KB Artifact | Status | Drift Details |
|---|---|---|
| DB_TABLE_REGISTRY.yaml | CURRENT / STALE | [specific differences] |
| 10_ENDPOINT_REGISTRY.yaml | CURRENT / STALE | [specific differences] |
| 12_COMPONENT_REGISTRY.yaml | CURRENT / STALE | [specific differences] |
| 13_ETL_TABLE_IO_CONTRACT.yaml | CURRENT / STALE | [specific differences] |
Ground truth used: [source code where STALE, KB docs where CURRENT]
```

Where STALE: use **source code only** for gap analysis. Discard the stale doc.

---

## PHASE 2B — GAP ANALYSIS (requirement-gap-analysis)

For each layer relevant to the requirement, compare current state (source code) vs. target state (spec acceptance criteria).

For each gap document:
```yaml
gap_id: GAP-001
layer: db | api | ui | etl | bizlogic | testing | infra
description: "[what is missing or what needs changing]"
current_state: "[what exists today — from source code, not KB doc if stale]"
target_state: "[what the requirement needs]"
affected_files:
  - "[real verified path]"
impact: low | medium | high | critical
effort_estimate: "[hours or TBD]"
```

**Rules:**
- Cite the actual source file for every current_state claim
- Verify every file path exists before citing it
- If effort is unknown: set `effort_estimate: TBD` and flag `needs_grooming: true`
- Identify gaps in ALL layers relevant to the requirement — do not skip layers

Then run **impact analysis**: using `CROSS_LAYER_IMPACT_MATRIX.yaml`, trace dependencies for each gap:
- Upstream dependencies (things this change breaks)
- Downstream dependencies (things that consume the changed code)
- Data migration needs (backfill, schema rollback risk)
- Breaking change risks (API contract changes, consumer impact)

Write `{REQ_ID}-GAP-ANALYSIS.md` using template at `.devin/templates/gap-analysis.md`. Include the staleness check table as the first section.

### GATE: SDLC_02 — BSA Reviews Gap Analysis
> "Gap analysis complete. Please review `{REQ_ID}-GAP-ANALYSIS.md`.
> Type **APPROVED** to proceed to story generation, or give me feedback."
When APPROVED: update `approvals.yaml` phases.research = approved.

---

## PHASE 2C — STORY GENERATION (enriched-requirements-generator, mode=bottom_up)

**Read `.devin/templates/complexity-matrix.yaml` before estimating any story.**

For each gap (or logical group of related gaps), generate ONE implementation story.

**Story point estimation — mandatory steps:**
0. Check `story_type_rules` first. Design/analysis stories, spikes and automation-test
   stories are estimated by their own rule, not by the dimensions — record that rule's
   `estimation_basis_line` and skip steps 1-4.
1. Score the story on all 5 dimensions (each 0, 1, or 2):
   - **SCOPE**: How many distinct areas? (0=one file; 1=multiple files/one layer; 2=3+ files/2+ layers)
   - **RISK**: How hard to reverse? (0=safe/additive; 1=managed/needs care; 2=high/data mutation)
   - **UNKNOWNS**: How well understood? (0=clear/same pattern; 1=some gaps; 2=significant unknowns)
   - **DEPENDENCY**: Cross-team/system? (0=none; 1=internal; 2=external/vendor)
   - **TESTABILITY**: How hard to verify? (0=unit tests; 1=integration test; 2=E2E/performance)
2. Sum scores → look up Fibonacci points in `points_lookup` table in complexity-matrix.yaml
3. Apply `risk_modifiers` if present (breaking change, data migration, no prior art, perf-sensitive, PII/security) — +1 Fibonacci each, max +2 total
4. Record all dimension scores in `estimation_basis`:
   ```
   gap_id=GAP-{n}, SCOPE={s}/2 ({label}): {reason}, RISK={r}/2 ({label}): {reason},
   UNKNOWNS={u}/2 ({label}): {reason}, DEPENDENCY={d}/2 ({label}): {reason},
   TESTABILITY={t}/2 ({label}): {reason}, total_score={sum}/10 → {pts} pts,
   modifiers=[{list or NONE}], final_points={pts}
   ```
5. Derive `original_estimate_hours` from `hours_reference` table (NEVER set hours before points)

**Title suffix rules (mandatory, no exceptions):**
- Implementation: `{brief description} {LAYER}-DEV`
- SIT: same brief description + `{LAYER}-SIT`
- UAT: same brief description + `{LAYER}-UAT`
- Brief description is IDENTICAL across all three paired stories
- Never use `[SIT]` or `[UAT]` prefixes

**For each impl story, also generate:**

**SIT story:** points = 1 if impl≤3; 2 if impl=5; 3 if impl=8; 5 if impl=13. Assignee: QA Engineer.

**UAT story:** points = always 1; hours = always 1.0h. Assignee: Product Owner.

**Subtasks (under impl story only):**
- Count: ≤2pts → 2–3 subtasks; 3–5pts → 3–5 subtasks; ≥8pts → 5–8 subtasks
- Each = one concrete work unit: one file, one function, one migration, one test module
- Format: `{action} {exact_file_or_function} — {specific_change}`
- Each must cite `source_file` (verified path)
- Hours: min 0.5h, max 4.0h; all subtask hours MUST sum to story `original_estimate_hours`

**Needs-grooming trigger:** If UNKNOWNS=2 AND any other dimension=2: set `needs_grooming: true`, leave points null. Do not estimate.

**Needs-split trigger:** If total score ≥ 10 OR points + modifiers > 13: set `needs_split: true`. Do not create the story — split it first.

Write `{REQ_ID}-BACKLOG.md` and `{REQ_ID}-JIRA-BACKLOG.yaml` with unsigned SDLC_03 + SDLC_03a approval blocks.

---

## PHASE 2D — ESTIMATION AUDIT (complexity-estimator, mode=bottom_up)

Run these 12 checks:
1. All required fields present (issuetype, summary, story_points, etc.)
2. Story points in Fibonacci scale (1,2,3,5,8,13) or null (needs_grooming only)
3. Every impl story cites at least one `gap_id`
4. Dimension scores in `estimation_basis` → Fibonacci points consistent with `points_lookup`
5. TBD/? gaps → `needs_grooming: true`
6. Every impl story has paired SIT story
7. Every impl story has paired UAT story
8. All SIT `assignee_role` = "QA Engineer"
9. All UAT `assignee_role` = "Product Owner"
10. All UAT `story_points` = 1
11. All SIT `story_points` ≤ paired impl `story_points`
12. Acceptance criteria are measurable — no vague language ("works correctly", "fast", "user-friendly")

If any check FAILS: fix the story before proceeding. Set `audit_status: FAIL` only if unfixable.

Write `{REQ_ID}-ESTIMATION-AUDIT.md`.

### GATES: SDLC_03 (PO) + SDLC_03a (Tech Lead)
> "Please review `{REQ_ID}-BACKLOG.md` and `{REQ_ID}-ESTIMATION-AUDIT.md`.
> Product Owner: confirm story breakdown, acceptance criteria, sprint order.
> Tech Lead: confirm estimation basis, all needs_grooming stories acknowledged.
> Both must type **APPROVED**."
When approved: update `approvals.yaml` phases.estimation and phases.backlog = approved.

---

## PHASE 3 — JIRA EXPORT

Pre-flight checks (STOP if any fail):
1. SDLC_03 signed in `BACKLOG.md`
2. SDLC_03a signed in `BACKLOG.md`
3. `audit_status` = PASS or PASS_WITH_FLAGS (not FAIL)
4. No `needs_split: true` stories remain

Write `{REQ_ID}-JIRA-BACKLOG.yaml` validated against `.devin/templates/jira-backlog-schema.yaml`.

Tell user: "`{REQ_ID}-JIRA-BACKLOG.yaml` is ready for manual Jira import. Create Epic first, then Stories in dependency order (DB → API → UI → ETL), then Subtasks."

---

## OUTPUT FILES

```
framework/context/session/{OWNER}/{REQ_ID}/
├── approvals.yaml
├── {REQ_ID}-SPEC.md
├── {REQ_ID}-GAP-ANALYSIS.md              ← includes staleness check + impact analysis
├── {REQ_ID}-BACKLOG.md
├── {REQ_ID}-ESTIMATION-AUDIT.md
└── {REQ_ID}-JIRA-BACKLOG.yaml
```

---

## Advice & Pointers

- **The staleness check is your most important first step.** A stale KB doc used as ground truth produces a gap analysis built on fiction. Always run Phase 2A before Phase 2B — no exceptions.
- **Cite source files, not KB docs, in gap descriptions.** The gap analysis is only trustworthy if every current-state claim traces to a line in source code you have actually read.
- **`effort_estimate: TBD` is honest. Use it.** If you genuinely do not know how long a gap will take to resolve — perhaps because the affected area is poorly understood — write TBD and set `needs_grooming: true`. Do not guess. A confident wrong estimate wastes a sprint.
- **Impact analysis often reveals additional layers.** When the cross-module matrix shows a table is also read by an ETL job or a downstream system (SC/FIN/MRM), add those as separate gaps even if they weren't in the original requirement. Missing them now causes production issues.
- **Story language: capability, not mechanism.** "Allow the system to store a provider's TIN category" (PASS) vs "Add TIN_CTGRY_CD VARCHAR(20) to CL_UI_BSNS_PG_PROV_HRCHY" (FAIL — that is subtask language).
- **When scope is ambiguous during gap analysis:** Stop. Ask one question before continuing. Example: "GAP-003 affects `VBC_UI_PRVDR_GRP`. The cross-module matrix shows this table is also written by the ETL job `claims-etl-sync_providers.py`. Should I include an ETL layer gap for this requirement, or is that out of scope?"
- **If you notice something wrong in a file you are reading** (a bug, a logic error, an inconsistency), note it in an `## Observations` section at the end of the gap analysis — including the file, line, description, and a suggested fix. **Do not make any changes.** Flag it so the team can decide.
- **If you notice a performance improvement opportunity** while reading source code (e.g. an N+1 query, missing index, inefficient loop), note it in `## Observations` with the location, what the opportunity is, and an estimated impact. **Do not implement it.** Example: "views.py line 142: `get_queryset()` runs a separate query per provider — adding `select_related('tin_group')` could reduce DB calls by ~80% for large result sets. Recommend raising a separate story if the team wants to address this."

---

## Forbidden Actions

- **DO NOT skip the staleness check (Phase 2A).** Even if the KB docs were recently refreshed. Even if the user says "they're fine". The check is mandatory before any gap analysis begins.
- **DO NOT read a KB artifact and use it as fact without comparing it to the source code.** Every KB claim must be validated.
- **DO NOT fabricate a file path.** If a path listed in a KB registry does not exist in the actual file system, report: "File not found at {path} — possible stale entry. Cannot verify." Do not substitute a different path.
- **DO NOT write `{REQ_ID}-SPEC.md` before the user confirms the draft.** Show the draft first.
- **DO NOT modify any source code.** This playbook is research and analysis only. Zero code changes.
- **DO NOT generate stories from gaps that have `effort_estimate: TBD` without flagging `needs_grooming: true`.** Do not estimate a TBD gap — leave points null.
- **DO NOT export to Jira if `audit_status = FAIL`.** Fix failed stories first.
- **DO NOT proceed past SDLC_02 without explicit BSA APPROVED.** The gap analysis is the foundation — if it is wrong, everything downstream is wrong. Give the BSA time to review.
- **DO NOT add `[SIT]` or `[UAT]` prefixes to story summaries.** The suffix (`{LAYER}-SIT`, `{LAYER}-UAT`) is the only type indicator.
- **DO NOT fix observed bugs or implement observed performance improvements.** Note them in `## Observations` only. Any fix requires a separate requirement and approval.
