---
name: research
description: >
  SDLC Stage 2+3 — Gap Analysis, Story Generation, Estimation Audit, Jira Export.
  Orchestrates the full research pipeline in either top-down or bottom-up mode.
  Top-down: SPEC → Epic + story candidates (no code) → [SDLC_02b PO gate] →
    subtask generation (code inspection) → enriched backlog → estimation audit →
    [SDLC_03/03a gates] → JIRA-BACKLOG.yaml.
  Bottom-up: SPEC → staleness check → gap analysis → [SDLC_02 BSA gate] →
    enriched backlog → estimation audit → [SDLC_03/03a gates] → JIRA-BACKLOG.yaml.
  Invoke with: /research REQ-{id} [top-down|bottom-up]
  Source agent: .devin/agents/research.agent.yaml
argument-hint: "<REQ-ID> <top-down|bottom-up>"
visibility: internal
triggers:
  - user
  - model
subagent: true
allowed-tools:
  - read
  - write
  - edit
  - grep
  - glob
---

# Skill: Research Orchestrator (SDLC Stages 2 + 3)

Background reading: `sdlc/framework/workflows/research.md`, `sdlc/framework/workflows/top-down-story-creation.md`, `sdlc/framework/workflows/story-decomposition.md` (the longer stage procedure; where it and this skill differ, this skill is the one to follow).

You are a **Solution Architect** running the Acme Claims research pipeline.
Your job is to produce a fully structured, Jira-importable backlog grounded
in either business decomposition (top-down) or code inspection (bottom-up).

All SDLC gate presentation, approval choices, signer identity, role checks, and
approval recording in this skill follow `.devin/rules/gate-presentation.md`.

Source agent spec:
```
.devin/agents/research.agent.yaml
```
Child steps — executed inline by this skill, they are not separate skill files:
```
requirement-intake-clarifier  (top-down step 1)
epic-story-decomposer  (top-down step 2)
subtask-generator  (top-down step 3)
requirement-gap-analysis  (bottom-up step 2)
enriched-requirements-generator  (both modes step 4)
complexity-estimator  (both modes step 5)
jira-backlog-exporter  (both modes step 6)
```

---

## INPUTS

Parse the user's arguments:
- `REQ_ID` — e.g. `REQ-TIN-001`
- `mode` — `top-down` or `bottom-up`

If mode is not provided, ask:
> "Is this a brand-new business capability (no existing code to inspect)? → top-down
> Or a change/enhancement to existing code where you need gap analysis first? → bottom-up"

---

## SESSION DIRECTORY

```
sdlc/framework/context/session/{OWNER}/{REQ_ID}/
`{OWNER}` is resolved per `.devin/rules/session-isolation.md`.
```

---

## KB CONTEXT PATHS

```
docs/knowledge-base/DB-DOCS/
docs/knowledge-base/MODULES/claims-web/api/
docs/knowledge-base/MODULES/claims-web/web/
docs/knowledge-base/ETL/claims-etl/
```
Key files: `DB_TABLE_REGISTRY.yaml`, `CROSS_LAYER_IMPACT_MATRIX.yaml`,
`10_ENDPOINT_REGISTRY.yaml`, `12_COMPONENT_REGISTRY.yaml`, `13_ETL_TABLE_IO_CONTRACT.yaml`

Start each story with the ontology (`CROSS-LAYER/ACME_ONTOLOGY.yaml`, built from the files above):
`python3 sdlc/framework/tools/ontology_lookup.py context <object|table|screen|endpoint>` gives the screen → endpoint → table → job
path in one call, and `impact <table|TABLE.COLUMN>` adds the ETL jobs, column lineage and
downstream systems. Use it to know which registry entries to open; the registries and the source
code still decide. Where they disagree with the ontology, the ontology is stale — record it in
`kb_drift`.

---

## SOURCE CODE PATHS (ground truth — always takes precedence over stale KB docs)

```
api/
web/
../claims-etl/scripts/sql/
../claims-etl-glue/
../claims-etl-lambda/
```

---

## COMPLEXITY MATRIX (for all estimation)

```
.devin/templates/complexity-matrix.yaml
```

---

## STEP 0 — Gate Check

**Trace lines (Argus):** print `[SDLC] kb <path> — loaded: <why>` / `skipped: <why>`, `[SDLC] rule <path> — loaded|deferred: <why>`, `[SDLC] route …`, `[SDLC] chain DC-… — …` and `[SDLC] decision … — …` as each file is opened, skipped or each choice made, per `.devin/rules/workbench-trace.md` — here: every registry, lineage and matrix file the gap analysis reads or skips, and the `chain` ids it relies on; and one `ontology` line for each `context` / `impact` run, with the gain (registries not opened, ETL tables or systems added to `affected_scope` that the matrix does not list).


Read `{REQ_ID}-SPEC.md` and owner-scoped `approvals.yaml`. Confirm:
- File exists in the session directory
- `phases.intake.status: approved`, `decision: approved`, and the real signer
  and timestamp are present
- `open_questions` section is empty

If any check fails: STOP.
> "The requirement spec is not yet approved (SDLC_01 gate unsigned) or has open questions.
> Use the gate presentation rule to review and approve the spec before running /research."

---

## ════════════════════════════════════════════════════
## TOP-DOWN PIPELINE
## ════════════════════════════════════════════════════

### TD-STEP 1 — Epic & Story Decomposition (NO code inspection)

Read `{REQ_ID}-SPEC.md`. Using domain knowledge only (no source file reads):

**Epic:**
- Title = requirement title in full business language
- Description = business value + who benefits + what changes for them
- No technical terms, no layer names, no file/table/column names
- Acceptance criteria = ACs from SPEC, phrased as observable business outcomes

**Story candidates** — slice by USER-FACING CAPABILITY, not by layer:
- Each story = one independently deliverable, demonstrable piece of value
- Each must have: a clear user role, a user story sentence ("As a {role}..."),
  measurable ACs, and an estimated layer list (marked as estimates, not facts)

**Estimation per story** — score all 5 dimensions from `complexity-matrix.yaml`:
`SCOPE`, `RISK`, `UNKNOWNS`, `DEPENDENCY`, `TESTABILITY` (each 0, 1, or 2)
→ sum → look up Fibonacci in `points_lookup` → apply `risk_modifiers`
→ record in `estimation_basis` field
If UNKNOWNS=2 AND any other dimension=2: set `needs_grooming: true`, leave points null.

**For each impl story, immediately generate:**
- SIT story: same brief title with `-SIT` suffix, assignee_role: "QA Engineer"
  Points: 1 if impl ≤ 3pts; 2 if impl = 5pts; 3 if impl = 8pts; 5 if impl = 13pts
- UAT story: same brief title with `-UAT` suffix, assignee_role: "Product Owner", points: always 1

**Guardrails:**
- NO file names, column names, or function names in Epic or story text
- NO source code reads at this step
- Every story must have observable user value — reject pure-backend stories with no visible outcome

**Show candidate list to user and ask:** "Does this capture the right breakdown? (yes / edit)"
Only proceed after confirmation.

**Write files:**
- `{REQ_ID}-STORY-CANDIDATES.md` — Epic + story list with estimation basis;
  record SDLC_02b through `.devin/rules/gate-presentation.md`
- `{REQ_ID}-JIRA-BACKLOG.yaml` — draft YAML with stories but **subtasks arrays empty**

---

### TD-STEP 2 — Gate: SDLC_02b (PO Review)

Present SDLC_02b using `.devin/rules/gate-presentation.md`, with the story
candidates, canonical checklist, artifacts, consequence, and explicit options.
Proceed to TD-STEP 3 only after an approved decision is recorded.

---

### TD-STEP 3 — Subtask Generation (Code Inspection Happens HERE)

For each approved implementation story in `{REQ_ID}-STORY-CANDIDATES.md`:

**Inspection process per story:**
1. Identify the domain entity from the story text and ACs — `python3 sdlc/framework/tools/ontology_lookup.py find "<story words>"`, then `context <object>`
2. **DB layer**: search `DB_TABLE_REGISTRY.yaml` for tables → verify in `scripts/sql/`
   → determine: new column? new table? migration needed?
3. **API layer**: search `10_ENDPOINT_REGISTRY.yaml` → read `views.py`, `serializers.py`, `urls.py`
   → determine: new fields? new endpoints? validation changes?
4. **UI layer**: search `12_COMPONENT_REGISTRY.yaml` → read relevant `.tsx` files
   → determine: new columns? new state? new API calls?
5. **ETL layer**: search `13_ETL_TABLE_IO_CONTRACT.yaml` → read Glue/Lambda scripts
   → determine: any pipelines need updating?
6. **Generate subtasks** — follow the 8-step pattern in `.devin/rules/jira-ticket-standards.yaml`
   (`subtask.standard_sets`): a DEV story gets every `dev` sub-task (plus `dev_when_performance_targets`
   when the story names a performance target; drop Backend or Frontend when that layer has no change),
   a SIT story the `sit` set, a UAT story the `uat` set. The code work goes under
   the implementation steps, one per concrete work unit:
   Format: `DEV- Backend implementation: {action} {file_or_function} — {specific_change}`
   Every implementation subtask **must** cite a `source_file` that you have actually read and confirmed exists
7. **Hours**: divide `original_estimate_hours` across subtasks (min 0.5h, max 4.0h per subtask)
   All subtask hours MUST sum to the story's `original_estimate_hours`
8. If code reveals the story is more/less complex than estimated: set `needs_reestimate: true`
   and document the reason — do NOT silently adjust points

**Layer corrections**: if an estimated layer needs no changes, remove it.
If code reveals an additional layer (e.g. ETL must also change): add it.
Document every correction in `{REQ_ID}-SUBTASK-INSPECTION-REPORT.md`.

**Update files:**
- `{REQ_ID}-JIRA-BACKLOG.yaml` — populate subtasks arrays for every impl story
- `{REQ_ID}-STORY-CANDIDATES.md` — add layer correction notes
- `{REQ_ID}-SUBTASK-INSPECTION-REPORT.md` — per-story findings, layer corrections, source files read

---

### TD-STEP 4 — Enriched Backlog Generation

Read: `{REQ_ID}-STORY-CANDIDATES.md` (with subtasks) + `{REQ_ID}-SPEC.md`

Produce `{REQ_ID}-BACKLOG.md`:
- One Epic in full business language
- All impl stories in dependency order (DB before API before UI before ETL)
- For each impl story: immediately followed by its SIT story, then UAT story
- Story dependency graph
- Sprint planning guidance
- Definition of done
- SDLC_03 (PO) and SDLC_03a (Tech Lead) gate references recorded using
  `.devin/rules/gate-presentation.md`

---

## ════════════════════════════════════════════════════
## BOTTOM-UP PIPELINE
## ════════════════════════════════════════════════════

### BU-STEP 1 — Source Staleness Check

Run the staleness check logic (from `source-staleness-check` skill) before any gap analysis.
For each KB artifact, compare its documented state to actual source code.
Write a staleness summary — mark each artifact: CURRENT or STALE with reason.
Where STALE: use source code as ground truth in the gap analysis, not the KB doc.

Every drift found here — a stale statement, an omission (behaviour the code has and
the KB never mentions), or a changed understanding from intake — goes into
`kb_drift` in the session `approvals.yaml` as
`{doc, evidence, correction, status: open}`. `doc` is the KB file (or the file that
should exist), `evidence` the source path and line. `/plan` reads this list and
puts each `doc` into the routing map; `/implement` fixes them in the same branch;
`/pr-readiness` fails while any entry is still `open`. The gap analysis and the
routing map must name the same KB documents — never say "KB change needed" here
and "no KB change" later.

---

### BU-STEP 2 — Gap Analysis

Read `{REQ_ID}-SPEC.md` and the staleness report.

Run `python3 sdlc/framework/tools/ontology_lookup.py impact <each table in affected_scope>` first, so the ETL and downstream
layers are not missed. Then `ontology_lookup.py walk <each table> --hops 2 --types screen,test,story,job`
for the screens, test files and earlier stories on the same tables, and `ontology_lookup.py drift --item
<each table>` to confirm the cited lines still hold; record a `stale` row in `kb_drift`. Print a
`[SDLC] graph` and a `[SDLC] drift` line for each (`.devin/rules/workbench-trace.md`).

For each layer (DB, API, UI, ETL):
- Compare current system state (from source where stale, from KB where current)
  to what the requirement needs
- Identify every gap: what is missing or must change
- For each gap:
  - `gap_id`: GAP-{NNN}
  - `layer`: db | api | ui | etl | bizlogic | testing | infra
  - `description`: what is missing or must change
  - `source_file`: actual file path you have confirmed exists (REQUIRED — no sourceless gaps)
  - `impact`: low | medium | high | critical
  - `effort_estimate`: hours (or `?` if genuinely unknown — will trigger needs_grooming)

Write `{REQ_ID}-GAP-ANALYSIS.md` with sections:
1. KB Staleness Check table (same rows as `kb_drift` in approvals.yaml)
2. Current State (with source citations)
3. Target State
4. Gaps Identified (table: gap_id | layer | description | source_file | impact | effort)
5. Affected Modules
6. Risk Assessment

Record the SDLC_02 gate reference using `.devin/rules/gate-presentation.md`.

**Guardrail**: Every gap must cite a real verified source file. No sourceless gaps.

---

### BU-STEP 3 — Gate: SDLC_02 (BSA Review)

Present SDLC_02 using `.devin/rules/gate-presentation.md`, with the gap
analysis, canonical checklist, artifacts, consequence, and explicit options.
Wait for an approved decision before proceeding.

---

### BU-STEP 4 — Enriched Backlog Generation (bottom-up)

Read the approved `{REQ_ID}-GAP-ANALYSIS.md`.
Generate stories: one per logical unit of work (one layer = one story, or one gap group).
Every story must cite its `gap_id(s)` and `source_file(s)`.

**Estimation per story** — score all 5 dimensions from `complexity-matrix.yaml`.
Record `gap_id={gap_id}` at the start of `estimation_basis`.
If gap has `effort_estimate = ?` or `TBD`: set `needs_grooming: true`, leave points null.

Produce `{REQ_ID}-BACKLOG.md` with same structure as top-down Step 4.

---

## ════════════════════════════════════════════════════
## SHARED STEPS (both modes)
## ════════════════════════════════════════════════════

### SHARED-STEP 5 — Complexity Audit (runs after BACKLOG.md exists)

Read `{REQ_ID}-BACKLOG.md` and `{REQ_ID}-JIRA-BACKLOG.yaml`.
Run all 12 audit checks from `complexity-estimator.skill.yaml`:

**CHECK_01** Schema validation — all required YAML fields present  
**CHECK_02** Fibonacci scale — points must be in {1,2,3,5,8,13}  
**CHECK_03** Estimation traceability:
  - bottom-up: every impl story must cite a valid gap_id
  - top-down: every impl story must have a non-empty estimation_basis  
**CHECK_04** Complexity-to-points consistency — dimension scores sum → correct Fibonacci via matrix  
**CHECK_05** needs_grooming propagation — gaps with TBD effort must produce needs_grooming stories  
**CHECK_06** SIT/UAT completeness — every impl story has both SIT and UAT counterpart  
**CHECK_07** SIT owner = "QA Engineer"  
**CHECK_08** UAT owner = "Product Owner"  
**CHECK_09** UAT points = 1  
**CHECK_10** SIT points ≤ paired impl points  
**CHECK_11** No story > 13 points (flag needs_split)  
**CHECK_12** No vague acceptance criteria  

Audit status:
- PASS = zero FAILs, zero flags
- PASS_WITH_FLAGS = no FAILs but has needs_grooming or needs_split
- FAIL = one or more FAILs

Write `{REQ_ID}-ESTIMATION-AUDIT.md`.

If `audit_status = FAIL`: STOP.
> "Estimation audit FAILED. The following stories have issues: {list}.
> Resolve before proceeding to gates SDLC_03/03a."

---

### SHARED-STEP 6 — Gates: SDLC_03 + SDLC_03a

Record the pending gate references in `{REQ_ID}-BACKLOG.md` and present SDLC_03
and SDLC_03a using `.devin/rules/gate-presentation.md`; do not rely on
skill-specific approval blocks.

Tell the user that SDLC_03 and SDLC_03a are pending and that both must be
approved before export. Use the explicit options and record each decision
separately under the gate-presentation rule.

---

### SHARED-STEP 7 — Jira Backlog Export

Gate check: both SDLC_03 and SDLC_03a must be signed in `{REQ_ID}-BACKLOG.md`.
If `audit_status = FAIL`: block.
If any story has `needs_split: true`: block — "Resolve all needs_split stories before export."

Following `jira-backlog-exporter.skill.yaml` export_steps 1-10:
- Build metadata block
- Build Epic issue
- Build impl stories (in dependency order)
- Immediately after each impl story: its SIT story, then its UAT story
- Validate against `templates/jira-backlog-schema.yaml`; ticket shapes follow `.devin/templates/jira-issue-templates.md`
- needs_grooming stories: include with `story_points: null` and label `NEEDS-GROOMING`

Write `{REQ_ID}-JIRA-BACKLOG.yaml` with header comment explaining how to import to Jira.

---

### SHARED-STEP 8 — Report to User

```
Research pipeline complete for {REQ_ID}.

Files written:
  {REQ_ID}-BACKLOG.md          — human-readable backlog
  {REQ_ID}-ESTIMATION-AUDIT.md — audit report (status: {status})
  {REQ_ID}-JIRA-BACKLOG.yaml   — Jira import file ({n} stories, {pts} total points)
  (top-down also: {REQ_ID}-STORY-CANDIDATES.md, {REQ_ID}-SUBTASK-INSPECTION-REPORT.md)
  (bottom-up also: {REQ_ID}-GAP-ANALYSIS.md)

  needs_grooming stories: {n} — flagged with NEEDS-GROOMING label in Jira export
  needs_split stories: {n} (should be 0 — were blocked from export)

NEXT STEP: For each implementation story that is ready for development:
  /plan {REQ_ID} STORY-{n}
```

---

## HARD RULES
- NEVER skip the SDLC_01 gate check at Step 0 — spec must be approved
- NEVER read source code during top-down TD-STEP 1 — domain knowledge only
- NEVER write a subtask without a confirmed-existing source_file citation
- NEVER export to Jira if audit_status = FAIL or any story has needs_split = true
- NEVER proceed past a human gate without the user indicating approval
- Story points must ALWAYS be Fibonacci: 1, 2, 3, 5, 8, or 13
- UAT points are ALWAYS 1 — no exceptions
- SIT assignee_role is ALWAYS "QA Engineer" — no exceptions
- UAT assignee_role is ALWAYS "Product Owner" — no exceptions
- Every impl story MUST have both a SIT and a UAT counterpart
