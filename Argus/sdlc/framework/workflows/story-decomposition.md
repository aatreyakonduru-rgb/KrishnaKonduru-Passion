# Workflow: Story Decomposition — Epic, Story & Jira Backlog Generation

## Goal
Given an approved gap analysis, produce a fully structured, Jira-importable
backlog: one Epic, implementation stories, SIT stories, and UAT stories per gap,
with Fibonacci story point estimates audited against the gap analysis.

## Agent
**Research Agent** (role: Solution Architect)

## Prerequisites
- `REQ-{id}-SPEC.md` approved by BSA (SDLC_01 signed)
- `REQ-{id}-GAP-ANALYSIS.md` approved by BSA (SDLC_02 signed)
- KB context loaded (staleness check complete)

## Language Tier Rules
Three distinct language levels are enforced across the work hierarchy:

| Level | Language | Rule |
|-------|----------|------|
| **Epic** | Full business language | Zero technical terms. No table/column names, no layer acronyms alone, no file paths, no SQL. A VP with no technical background must understand it. |
| **Story** | Business-leaning | Describes the capability, not the mechanism. The `{LAYER}-DEV/SIT/UAT` suffix is the only technical element in the summary. |
| **Subtask** | Fully technical | One deliverable per subtask (one file / one function / one migration). Must name the exact file/function and the specific change. |

**Epic examples:**
- ✅ `Allow providers to be classified by TIN category and episode count`
- ❌ `Add TIN_CTGRY_CD column to CL_UI_BSNS_PG_PROV_HRCHY`

**Story examples:**
- ✅ `Allow the system to store a provider's TIN classification DB-DEV`
- ❌ `Add TIN_CTGRY_CD VARCHAR(20) NOT NULL to provider table DB-DEV`

**Subtask examples:**
- ✅ `Create V002__add_tin_columns.sql — add TIN_CTGRY_CD, BSNS_APRVD_CTGRY, TTL_VLD_EPSDS, INCLD_IN_RPRTS_IND to CL_UI_BSNS_PG_PROV_HRCHY`
- ✅ `Modify TinController.getTinDetails() — add tinCategoryCode to response DTO`
- ❌ `Update the database`

---

## Story Title Suffix Convention
Every story summary ends with `{LAYER}-{ENV}` (uppercase, no brackets):

| Story type     | Suffix      | Example                                              |
|----------------|-------------|------------------------------------------------------|
| Implementation | `{LAYER}-DEV` | `Add 4 new columns to TIN tables DB-DEV`           |
| SIT            | `{LAYER}-SIT` | `Add 4 new columns to TIN tables DB-SIT`           |
| UAT            | `{LAYER}-UAT` | `Add 4 new columns to TIN tables DB-UAT`           |

Layer values: `DB` | `API` | `UI` | `ETL` | `TESTING` | `BIZ` | `INFRA`

The brief description is **identical** across all three paired stories —
only the suffix changes. Do NOT use `[SIT]` or `[UAT]` prefixes.

## Steps

---

### Step 1: Generate Stories
**Skill**: `enriched-requirements-generator`
**Precondition**: SDLC_02_GAP_ANALYSIS_REVIEW signed by BSA

- Input: `REQ-{id}-SPEC.md`, `REQ-{id}-GAP-ANALYSIS.md`
- For each gap in the gap analysis (by layer):
  - Create one **implementation story** (`{LAYER}-DEV` suffix)
  - Create one paired **SIT story** (`{LAYER}-SIT` suffix) — owned by QA Engineer
  - Create one paired **UAT story** (`{LAYER}-UAT` suffix) — owned by Product Owner
- Estimate story points using Fibonacci scale (1, 2, 3, 5, 8, 13)
  - Every estimate MUST cite the `gap_id` and `effort_estimate` from the gap analysis
  - If `effort_estimate = TBD/?`, flag story as `needs_grooming: true`, leave points blank
- Determine subtask count per story based on complexity (points ≤ 2 → 2-3 subtasks; 3-5 → 3-5; ≥ 8 → 5-8)
- Produce story dependency graph (DB → API → UI ordering)
- Produce sprint ordering recommendation

**Outputs**:
- `REQ-{id}-BACKLOG.md` — human-readable, unsigned approval block appended
- Draft `REQ-{id}-JIRA-BACKLOG.yaml` — schema-structured, unsigned

**SIT story point rule**:
| Impl story points | SIT story points |
|-------------------|-----------------|
| 1–3               | 1               |
| 4–5               | 2               |
| 6–8               | 3               |
| 13                | 5               |

**UAT story points**: always **1** (no exceptions — it's a sign-off activity)

---

### Step 2: Run Estimation Audit
**Skill**: `complexity-estimator`
**Precondition**: `REQ-{id}-BACKLOG.md` produced by Step 1

Runs 12 checks on every story:
1. Schema validation (all required fields present)
2. Fibonacci scale validation (only 1, 2, 3, 5, 8, 13)
3. Gap citation traceability (every impl story cites a real `gap_id`)
4. Effort-to-points consistency (mapped from gap analysis)
5. Needs-grooming propagation (TBD gaps → flagged stories)
6. SIT/UAT completeness (every impl has both)
7. SIT owner validation (`QA Engineer` always)
8. UAT owner validation (`Product Owner` always)
9. UAT points validation (always 1)
10. SIT points bounded (SIT ≤ paired impl)
11. Split threshold (points > 13 → must split)
12. Acceptance criteria testability (no vague language)

**Output**: `REQ-{id}-ESTIMATION-AUDIT.md`
**Audit status**:
- `PASS` — no issues at all
- `PASS_WITH_FLAGS` — some `needs_grooming` or `needs_split` flags, but no hard failures
- `FAIL` — one or more hard failures (blocks export)

---

### Step 3: Human Gate — Gap Analysis Sign-off
**Gate**: `SDLC_02_GAP_ANALYSIS_REVIEW`
**Required role**: BSA
*(This gate precedes story generation — must already be signed before Step 1 runs.
Listed here for sequence clarity.)*

---

### Step 4: Human Gate — Estimation Review
**Gate**: `SDLC_03a_STORY_ESTIMATION_REVIEW`
**Required role**: Tech Lead
**Artifacts to review**: `REQ-{id}-BACKLOG.md`, `REQ-{id}-ESTIMATION-AUDIT.md`

Tech Lead verifies:
- All story points traceable to gap_id + effort (no unsourced estimates)
- Fibonacci scale only — no invalid values
- No story > 13 points (must split before approval)
- Needs-grooming stories acceptable for Jira grooming
- Dependency ordering correct
- `audit_status` is `PASS` or `PASS_WITH_FLAGS` (not `FAIL`)
- Story title suffixes correct (`{LAYER}-DEV` / `{LAYER}-SIT` / `{LAYER}-UAT`)

**Timeout**: 24 hours

**If audit_status = FAIL**: Tech Lead rejects, agent surfaces flagged stories to BSA
and Tech Lead. Stories must be revised before re-running this gate.

---

### Step 5: Human Gate — Backlog Approval
**Gate**: `SDLC_03_BACKLOG_APPROVAL`
**Required role**: Product Owner
**Artifacts to review**: `REQ-{id}-BACKLOG.md`

PO verifies:
- Backlog prioritization agreed
- Every impl story has a paired SIT and UAT story
- Sprint ordering makes sense
- Acceptance criteria are clear and testable
- Story titles follow `{LAYER}-DEV` / `{LAYER}-SIT` / `{LAYER}-UAT` convention
- Needs-grooming stories flagged and listed
- Effort estimates are reasonable

**Timeout**: 48 hours

> **Both SDLC_03a and SDLC_03 must be signed** before the exporter runs.
> Either gate alone is insufficient.

---

### Step 6: Export to Jira YAML
**Skill**: `jira-backlog-exporter`
**Precondition**: SDLC_03 signed by PO AND SDLC_03a signed by Tech Lead

- Validates all fields against `templates/jira-backlog-schema.yaml`
- Applies final title suffix check (no `[SIT]`/`[UAT]` prefixes anywhere)
- Writes final `REQ-{id}-JIRA-BACKLOG.yaml`
- Stories with `needs_grooming: true` are included with `story_points: null`
  and label `NEEDS-GROOMING` — team grooms them in Jira
- Stories with `needs_split: true` are **excluded** — must be resolved first

---

## Outputs

| Artifact | Owner | Gate |
|----------|-------|------|
| `REQ-{id}-BACKLOG.md` | Research Agent | SDLC_03 (PO) + SDLC_03a (Tech Lead) |
| `REQ-{id}-ESTIMATION-AUDIT.md` | Research Agent | SDLC_03a (Tech Lead) |
| `REQ-{id}-JIRA-BACKLOG.yaml` | Research Agent | Both gates signed |

## Next Workflow
**Plan** (`workflows/plan.md`) — Tech Lead selects a story from the approved backlog
and the Plan Agent generates the routing map and insertion points for it.

---

## Full Story Hierarchy Example (REQ-TIN-001)

```
EPIC-TIN-001: Add New Columns to TIN Management Table and UI
│
├── STORY-001  "Add 4 new columns to TIN tables DB-DEV"             3 pts  High   DB Developer
├── STORY-001-SIT  "Add 4 new columns to TIN tables DB-SIT"         2 pts  High   QA Engineer
├── STORY-001-UAT  "Add 4 new columns to TIN tables DB-UAT"         1 pt   High   Product Owner
│
├── STORY-002  "Return new TIN columns from API endpoint API-DEV"   2 pts  High   Backend Developer
├── STORY-002-SIT  "Return new TIN columns from API endpoint API-SIT" 1 pt  High  QA Engineer
├── STORY-002-UAT  "Return new TIN columns from API endpoint API-UAT" 1 pt  High  Product Owner
│
├── STORY-003  "Accept new TIN columns on API save API-DEV"         3 pts  High   Backend Developer
├── STORY-003-SIT  "Accept new TIN columns on API save API-SIT"     2 pts  High   QA Engineer
├── STORY-003-UAT  "Accept new TIN columns on API save API-UAT"     1 pt   High   Product Owner
│
├── STORY-004  "Add new column editors to TIN Management grid UI-DEV"  3 pts  High  Frontend Developer
├── STORY-004-SIT  "Add new column editors to TIN Management grid UI-SIT"  2 pts  High  QA Engineer
├── STORY-004-UAT  "Add new column editors to TIN Management grid UI-UAT"  1 pt   High  Product Owner
│
├── STORY-005  "Update DataSync SQL to include new TIN columns ETL-DEV"  1 pt  Medium  ETL Developer
├── STORY-005-SIT  "Update DataSync SQL to include new TIN columns ETL-SIT"  1 pt  Medium  QA Engineer
├── STORY-005-UAT  "Update DataSync SQL to include new TIN columns ETL-UAT"  1 pt  Medium  Product Owner
│
├── STORY-006  "Add unit and integration tests for TIN columns TESTING-DEV"  3 pts  Medium  QA Engineer
├── STORY-006-SIT  "Add unit and integration tests for TIN columns TESTING-SIT"  2 pts  Medium  QA Engineer
└── STORY-006-UAT  "Add unit and integration tests for TIN columns TESTING-UAT"  1 pt   Medium  Product Owner

Total: 1 Epic | 6 impl stories | 6 SIT stories | 6 UAT stories = 18 stories
       Impl points: 3+2+3+3+1+3 = 15
       SIT points:  2+1+2+2+1+2 = 10
       UAT points:  6 × 1 = 6
       Grand total: 31 story points
```

## Dependency Flow

```
STORY-001 (DB-DEV)
    └── STORY-001-SIT (DB-SIT)
            └── STORY-001-UAT (DB-UAT)

STORY-002 (API-DEV) — blocked by STORY-001
    └── STORY-002-SIT (API-SIT)
            └── STORY-002-UAT (API-UAT)

STORY-003 (API-DEV) — blocked by STORY-001
    └── STORY-003-SIT (API-SIT)
            └── STORY-003-UAT (API-UAT)

STORY-004 (UI-DEV) — blocked by STORY-002 + STORY-003
    └── STORY-004-SIT (UI-SIT)
            └── STORY-004-UAT (UI-UAT)

STORY-005 (ETL-DEV) — blocked by STORY-001
    └── STORY-005-SIT (ETL-SIT)
            └── STORY-005-UAT (ETL-UAT)

STORY-006 (TESTING-DEV) — blocked by all impl stories
    └── STORY-006-SIT (TESTING-SIT)
            └── STORY-006-UAT (TESTING-UAT)
```

## Hours Estimation

Every story and subtask carries an `original_estimate_hours` set at generation time and **never overwritten**:

| Fibonacci points | Hours | Working days (6h/day) |
|-----------------|-------|----------------------|
| 1 | 1h | < 1 day |
| 2 | 2h | < 1 day |
| 3 | 3h | half day |
| 5 | 5h | < 1 day |
| 8 | 8h | 1.3 days |
| 13 | 12h | 2 days |

SIT hours = SIT points × 1.5h. UAT hours = always 1.0h.

**Subtask hour rule:** All subtask hours within a story must sum exactly to the story's `original_estimate_hours`. Min 0.5h, max 4.0h per subtask.

---

## Time Logging

Time is logged manually by the team directly in Jira against subtasks.

- Working day = **6 productive hours** (2h meetings excluded)
- Log hours against **subtasks**, not parent stories
- Add the **AI-USED** Jira label manually to any subtask where AI tools were used — this is a productivity metric showing time saved vs estimate
- `original_estimate_hours` on each story/subtask is set at generation time and never changed — it is the baseline

---

## Impediment Management

When work is blocked by an external dependency:

```
"declare impediment"  →  impediment-manager skill
"clear blocker on STORY-002"  →  impediment-manager skill (CLEAR mode)
```

- Adds `ON-HOLD` Jira label + blocker comment
- Records in `IMPEDIMENT-REGISTER.md`
- Does **not** change Jira workflow status (team moves stories themselves)
- Clearing removes the label and records the resolution

---

## Guardrails Summary

| Rule | Enforcement |
|------|------------|
| Epic in full business language (no jargon) | `enriched-requirements-generator` EPIC language rule |
| Story in business-leaning language | `enriched-requirements-generator` STORY language rule |
| Subtask at file/function level (fully technical) | `enriched-requirements-generator` SUBTASK rule |
| Every estimate cites a `gap_id` | `complexity-estimator` CHECK_03 |
| Only Fibonacci values (1,2,3,5,8,13) | `complexity-estimator` CHECK_02 |
| Subtask hours sum to story hours | `enriched-requirements-generator` HOURS RULE |
| UAT points always = 1, hours = 1.0h | `complexity-estimator` CHECK_09 |
| SIT owner always = QA Engineer | `complexity-estimator` CHECK_07 |
| UAT owner always = Product Owner | `complexity-estimator` CHECK_08 |
| Every impl has SIT + UAT | `complexity-estimator` CHECK_06 |
| `TBD` gaps → `needs_grooming`, no estimate | `complexity-estimator` CHECK_05 |
| Points > 13 → `needs_split`, not exported | `jira-backlog-exporter` guardrail |
| Title suffix `{LAYER}-DEV/SIT/UAT` | `jira-backlog-exporter` CHECK step 9 |
| No `[SIT]`/`[UAT]` prefix | `jira-backlog-exporter` CHECK step 9 |
| Both gates signed before export | `jira-backlog-exporter` GATE_CHECK_03 + GATE_CHECK_03a |
| original_estimate_hours never overwritten | Schema rule — set at generation, read-only after |
| AI-USED label applied manually in Jira | Team convention — on any subtask where AI was used |
| ON-HOLD label managed (not status) | `impediment-manager` guardrail |

## Hooks
- **Pre-check**: Verify `REQ-{id}-GAP-ANALYSIS.md` has SDLC_02 signed
- **Provenance log**: Record story count, gap_ids used, audit status, needs_grooming flags, export timestamp
- **Approval gates**: SDLC_03 (PO) + SDLC_03a (Tech Lead) both enforced before export
