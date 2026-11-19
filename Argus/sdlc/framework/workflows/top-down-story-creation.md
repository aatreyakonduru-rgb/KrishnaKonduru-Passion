# Workflow: Top-Down Story Creation

## Overview

Top-down story creation starts from a business need stated in plain language —
before anyone looks at code. The PO owns the Epic and story list. Engineers
only inspect code after the PO has approved the story breakdown.

Compare to `story-decomposition.md` (bottom-up), where code inspection happens
first and stories are derived from gaps in the codebase.

---

## When to Use Which Mode

| Situation | Mode |
|-----------|------|
| New feature — no prior code exists for this capability | top_down |
| PO has a business need but hasn't seen the codebase | top_down |
| Enhancement to existing code — gaps need to be found first | bottom_up |
| Regulatory/compliance change where code must match a spec | bottom_up |
| Bug fix or defect — source of truth is the broken behaviour | bottom_up |

**Rule of thumb:** If the question is _"what do we want to build?"_ → top_down.
If the question is _"what needs to change in the code?"_ → bottom_up.

---

## Pipeline at a Glance

```
[PO/BSA] Rough business need (plain language)
              ↓
[SKILL]  requirement-intake-clarifier
         Q&A → REQ-{id}-SPEC.md
              ↓
[GATE]   SDLC_01 — BSA/PO approves spec
              ↓
[SKILL]  epic-story-decomposer
         SPEC → Epic + story candidates
         (NO code inspection — business language only)
         → REQ-{id}-STORY-CANDIDATES.md
         → draft REQ-{id}-JIRA-BACKLOG.yaml (subtasks empty)
              ↓
[GATE]   SDLC_02b — PO approves Epic + story list
         *** CODE IS NOT TOUCHED UNTIL THIS GATE PASSES ***
              ↓
[SKILL]  subtask-generator
         Code inspection happens HERE
         → reads source code per story
         → generates file-level subtasks
         → corrects estimated layers
         → flags needs_reestimate where complexity differs
         → REQ-{id}-SUBTASK-INSPECTION-REPORT.md
         → updates REQ-{id}-JIRA-BACKLOG.yaml (subtasks populated)
              ↓
[SKILL]  enriched-requirements-generator (mode=top_down)
         Finalises structure:
         → validates SIT/UAT pairs, language tiers, suffix conventions, hours
         → REQ-{id}-BACKLOG.md
         → final REQ-{id}-JIRA-BACKLOG.yaml
              ↓
[SKILL]  complexity-estimator (mode=top_down)
         Audits T-shirt→Fibonacci mapping
         Reviews needs_reestimate flags
         → REQ-{id}-ESTIMATION-AUDIT.md
              ↓
[GATE]   SDLC_03 — PO approves final backlog
[GATE]   SDLC_03a — Tech Lead reviews estimation + subtask inspection
              ↓
[SKILL]  jira-backlog-exporter
         → REQ-{id}-JIRA-BACKLOG.yaml (final, ready for import)
```

---

## Step-by-Step Detail

### Step 1 — State the Business Need

Start a session and say:
> "I have a new requirement: [plain language description of the business need]"

The agent identifies this as `mode: top_down` (no existing gap analysis, rough
business statement) and runs `requirement-intake-clarifier`.

### Step 2 — Intake Q&A (requirement-intake-clarifier)

The agent asks focused questions across 7 topic areas:
- **What** — what should users be able to do?
- **Who** — which user roles benefit?
- **Why** — what business problem does this solve?
- **Rules** — what constraints or validations apply?
- **Acceptance Criteria** — what would you test in UAT?
- **Scope** — what is explicitly out of scope?
- **Priority** — Must Have / Should Have / Could Have?

Max 2 questions per turn. No technical terms. No solutions proposed.

**Output:** `REQ-{id}-SPEC.md`

### Step 3 — Gate: SDLC_01

BSA or PO reviews `REQ-{id}-SPEC.md`. Must confirm:
- All ACs are measurable
- `open_questions` is empty
- Scope is bounded

### Step 4 — Epic & Story Decomposition (epic-story-decomposer)

**No code inspection yet.**

The agent decomposes the spec into:
- One **Epic** (full business language — a VP must understand it)
- N **stories** sliced by user-facing capability (not by technical layer)
- Paired **SIT** and **UAT** stories for each implementation story

Stories are estimated using T-shirt sizing → Fibonacci:

| T-shirt | Fibonacci | When to use |
|---------|-----------|-------------|
| XS | 1 | Trivial, one area, no risk |
| S | 2 | Small, standard change pattern |
| M | 3 | Crosses a boundary, some design |
| L | 5 | Multiple touch points, coordination |
| XL | 8 | Significant design, unknowns |
| XXL | 13 | Huge — consider splitting |

**Output:** `REQ-{id}-STORY-CANDIDATES.md` + draft `REQ-{id}-JIRA-BACKLOG.yaml`
(subtasks arrays are empty at this stage — intentionally).

### Step 5 — Gate: SDLC_02b (KEY GATE)

PO reviews the Epic + story list. Code has still not been inspected.

This is the gate where the PO confirms:
- "These stories represent the right breakdown of the business need"
- "The Epic describes the right capability"
- "The estimated effort seems reasonable"

**Until SDLC_02b is signed, no source code is read.**

### Step 6 — Subtask Generation (subtask-generator)

**This is where code inspection happens in top-down mode.**

For each approved story, the agent:
1. Identifies the core domain entity from the story text
2. Searches DB, API, UI, ETL layers for relevant files
3. Generates file-level technical subtasks
4. Corrects estimated layers if code reveals a different reality
5. Flags `needs_reestimate` if complexity differs from T-shirt estimate
6. Assigns hours (subtask hours must sum to story `original_estimate_hours`)

**Output:** `REQ-{id}-SUBTASK-INSPECTION-REPORT.md` + populated subtasks in YAML

Layer correction example:
> "Layer correction: ETL added — `CL_PG_PROV_HRCHY` is populated by Glue job
> `claims-etl-sync_providers.py` which also needs updating. Original estimate
> did not account for this. needs_reestimate: true (M → L, 3pts → 5pts recommended)."

### Step 7 — Finalisation (enriched-requirements-generator, mode=top_down)

Produces the same canonical output format as bottom-up:
- `REQ-{id}-BACKLOG.md` — human-readable, for PO review
- Final `REQ-{id}-JIRA-BACKLOG.yaml` — Jira import YAML

Language tier validation happens here:
- Epic: pure business language confirmed
- Stories: business-leaning, `{LAYER}-DEV/SIT/UAT` suffix only
- Subtasks: fully technical, file-level, source_file cited

### Step 8 — Estimation Audit (complexity-estimator, mode=top_down)

Checks:
- T-shirt → Fibonacci mapping is consistent
- `estimation_basis` field is non-empty for every story
- `needs_reestimate` flags are surfaced for Tech Lead review
- Fibonacci scale enforced (1,2,3,5,8,13 only)
- SIT/UAT completeness, UAT = 1pt rule

**Output:** `REQ-{id}-ESTIMATION-AUDIT.md`

### Step 9 — Gates: SDLC_03 + SDLC_03a

Both must be signed before export:

**SDLC_03 (PO)** — Reviews final `REQ-{id}-BACKLOG.md`:
- Story breakdown makes sense
- ACs are testable
- Sprint ordering agreed

**SDLC_03a (Tech Lead)** — Reviews backlog + estimation audit + subtask inspection report:
- T-shirt reasoning is sound
- All `needs_reestimate` flags resolved (accepted or adjusted)
- Layer corrections reviewed and accepted
- Subtask source file citations verified
- Dependency ordering correct

### Step 10 — Jira Export (jira-backlog-exporter)

Produces the final `REQ-{id}-JIRA-BACKLOG.yaml` ready for manual import.
Same format as bottom-up. Team imports to Jira.

---

## Key Differences From Bottom-Up

| | Top-Down | Bottom-Up |
|--|---------|-----------|
| First step | Intake Q&A with PO | Load KB + staleness check |
| Code inspection | Step 6 (after PO approves stories) | Step 2 (before stories) |
| Story source | Business capability slices | One per gap/layer from code |
| Estimation basis | T-shirt → Fibonacci + domain reasoning | gap_id + effort_estimate |
| PO involvement | Drives Epic and story content | Reviews generated output |
| Extra gate | SDLC_02b (story candidates) | SDLC_02 (gap analysis) |
| Subtask report | REQ-{id}-SUBTASK-INSPECTION-REPORT.md | Embedded in gap analysis |
| needs_reestimate | Possible (code may reveal complexity) | Not applicable |

---

## Language Tier Rules (same in both modes)

| Level | Language | Rule |
|-------|----------|------|
| **Epic** | Pure business | Zero tech terms, no jargon, readable by non-technical stakeholders |
| **Story** | Business-leaning | `{LAYER}-DEV/SIT/UAT` suffix is the only technical element in the title |
| **Subtask** | Fully technical | One file/function/migration per subtask, exact file named, source cited |

---

## Files Produced

```
REQ-{id}-SPEC.md                           ← intake-clarifier
REQ-{id}-STORY-CANDIDATES.md               ← epic-story-decomposer
REQ-{id}-JIRA-BACKLOG.yaml (draft)         ← epic-story-decomposer (subtasks empty)
REQ-{id}-SUBTASK-INSPECTION-REPORT.md      ← subtask-generator
REQ-{id}-JIRA-BACKLOG.yaml (updated)       ← subtask-generator (subtasks populated)
REQ-{id}-BACKLOG.md                        ← enriched-requirements-generator
REQ-{id}-JIRA-BACKLOG.yaml (final)         ← enriched-requirements-generator
REQ-{id}-ESTIMATION-AUDIT.md              ← complexity-estimator
REQ-{id}-JIRA-BACKLOG.yaml (export-ready) ← jira-backlog-exporter
```

---

## Gates Summary

| Gate | Mode | Role | Blocks |
|------|------|------|--------|
| SDLC_01 | both | BSA/PO | Epic generation |
| SDLC_02b | top_down only | PO | Code inspection (subtask-generator) |
| SDLC_02 | bottom_up only | BSA | Story generation |
| SDLC_03 | both | PO | Jira export |
| SDLC_03a | both | Tech Lead | Jira export |
