# Playbook: Top-Down Pipeline (New Capability)

**Playbook ID:** PB-02  
**Paste into:** Devin Cloud → Settings → Playbooks → New Playbook  
**CLI equivalent:** `/intake` + `/research` (top-down path)  
**When to use:** A PO or BSA is describing a brand-new business capability in plain language. No existing code for this feature.

---

## Title

```
Acme Claims: Top-Down Pipeline (New Capability)
```

## Description

```
Runs the complete top-down SDLC pipeline for a new business capability.
Phases: intake Q&A (business language only) → SDLC_01 gate → Epic + story
decomposition (NO code) → SDLC_02b PO gate → subtask generation (code
inspection) → estimation audit → SDLC_03 + SDLC_03a gates → Jira export.
```

## Playbook Body

---

You are running the **top-down** Acme Claims pipeline. A business need has been stated. No code inspection happens until the PO approves the story breakdown (SDLC_02b).

---

## PHASE 1 — INTAKE (requirement-intake-clarifier)

Ask focused questions across these 7 areas. **No technical terms. No table/column/file names. No solutions.** Max 2 questions per turn. Wait for answers before continuing.

1. **WHAT** — What should users be able to do that they cannot do today?
2. **WHO** — Which user roles benefit? Different access levels?
3. **WHY** — What business problem does this solve? Any regulatory driver?
4. **RULES** — Validation rules, approval steps, volume expectations?
5. **ACCEPTANCE CRITERIA** — How will you know it is done? What would you test in UAT?
6. **SCOPE** — What is explicitly OUT of scope?
7. **PRIORITY** — Must Have / Should Have / Could Have? Target sprint?

After all questions are answered, draft `{REQ_ID}-SPEC.md` and show it to the user:
> "Does this capture your requirement? Type **YES** to write it, or tell me what to change."

Write `{REQ_ID}-SPEC.md` to `framework/context/session/{OWNER}/{REQ_ID}/` using the layout in `/intake` STEP 6 (`.devin/skills/intake/SKILL.md`).
`{OWNER}` is resolved per `.devin/rules/session-isolation.md`.

**Required sections:** requirement_id, title, business_context, affected_user_roles, business_rules, acceptance_criteria (min 3, measurable), out_of_scope, assumptions, open_questions (must be EMPTY), priority, target_sprint, approval_block.

### GATE: SDLC_01 — BSA/PO Approves Spec
Present the spec and ask:
> "Please review `{REQ_ID}-SPEC.md`. Type **APPROVED** to continue to story decomposition, or give feedback."

When APPROVED: update `approvals.yaml` phases.intake = approved with timestamp.

---

## PHASE 2A — EPIC & STORY DECOMPOSITION (epic-story-decomposer)
### *** NO CODE INSPECTION YET ***

Read `.devin/templates/complexity-matrix.yaml` first.

Decompose the approved spec into:

**One Epic** (pure business language — a VP with no technical background must understand it):
- Zero technical terms, no table/column/file names, no layer acronyms (DB/API/UI alone), no SQL
- Describes the business capability, not the mechanism
- Example PASS: "Allow providers to be classified by TIN category and episode count"
- Example FAIL: "Add TIN_CTGRY_CD column to CL_UI_BSNS_PG_PROV_HRCHY"

**N Implementation Stories** (sliced by USER-FACING CAPABILITY, not by layer):
- One story = one thing a user can do differently
- Estimate the likely technical layer (DB / API / UI / ETL) — mark as estimate only
- Use T-shirt → Fibonacci conversion using the 5 complexity dimensions from `complexity-matrix.yaml`:
  - SCOPE (0–2): How many areas of the codebase?
  - RISK (0–2): How hard to reverse if wrong?
  - UNKNOWNS (0–2): How well understood is the full scope?
  - DEPENDENCY (0–2): Depends on other teams or systems?
  - TESTABILITY (0–2): How hard to verify?
  - Sum → look up Fibonacci points in `points_lookup`
  - Apply `risk_modifiers` if applicable (+1 Fibonacci level each, max +2)
- Record dimension scores in `estimation_basis` field
- If UNKNOWNS=2 AND any other dimension=2: set `needs_grooming: true`, leave points null
- Title suffix: `{brief description} {LAYER}-DEV` (e.g. "Display TIN category on provider screen UI-DEV")

**Paired SIT Story** per impl (same brief description + `{LAYER}-SIT`):
- Points: 1 if impl≤3; 2 if impl=5; 3 if impl=8; 5 if impl=13
- Assignee role: QA Engineer always

**Paired UAT Story** per impl (same brief description + `{LAYER}-UAT`):
- Points: always 1 — no exceptions
- Hours: always 1.0h — no exceptions
- Assignee role: Product Owner always

Write:
- `{REQ_ID}-STORY-CANDIDATES.md` (unsigned SDLC_02b approval block at the end)
- `{REQ_ID}-JIRA-BACKLOG.yaml` (draft — subtasks arrays left empty intentionally)

### GATE: SDLC_02b — PO Approves Epic + Story List
> "Story candidates ready. **No code has been read yet.** Please review `{REQ_ID}-STORY-CANDIDATES.md`.
> Confirm the Epic and story breakdown make sense before I inspect the codebase.
> Type **APPROVED** to proceed to code inspection, or give feedback."

When APPROVED: update `approvals.yaml` phases.research = approved.

---

## PHASE 2B — SUBTASK GENERATION / CODE INSPECTION (subtask-generator)

**Code inspection happens HERE — only after SDLC_02b is signed.**

**Source code paths (ground truth):**
| Layer | Path |
|---|---|
| API — Django | `api/` |
| Frontend — Next.js | `web/` |
| SQL / DB | `claims-etl/scripts/sql/` |
| ETL — Glue | `claims-etl-glue/` |
| ETL — Lambda | `claims-etl-lambda/` |

> Note: claims-etl-* repos are separate GitHub repositories and must be cloned independently.

**KB docs (may be stale — always verify against source code above):**
| Artifact | Path |
|---|---|
| DB Table Registry | `docs/knowledge-base/DB-DOCS/DB_TABLE_REGISTRY.yaml` |
| DB Cross-Module Matrix | `docs/knowledge-base/CROSS-LAYER/CROSS_LAYER_IMPACT_MATRIX.yaml` |
| API Endpoint Registry | `docs/knowledge-base/MODULES/claims-web/api/10_ENDPOINT_REGISTRY.yaml` |
| FE Component Registry | `docs/knowledge-base/MODULES/claims-web/web/12_COMPONENT_REGISTRY.yaml` |
| ETL IO Contract | `docs/knowledge-base/ETL/claims-etl/13_ETL_TABLE_IO_CONTRACT.yaml` |

For each approved implementation story:
1. Identify the core domain entity from the story text (e.g. "TIN", "Provider", "Episode")
2. Search relevant source files across all estimated layers
3. Generate file-level subtasks — **one subtask = one file/function/migration/test module**:
   - Format: `{action} {exact_file_or_function} — {specific_change}`
   - Must cite a real, verified `source_file` path
   - Hours: min 0.5h, max 4.0h; ALL subtask hours MUST sum to story `original_estimate_hours`
4. If code reveals a layer not in the estimate: add it, document the correction
5. If code reveals less complexity than estimated: remove layers, document the correction
6. If complexity differs significantly: set `needs_reestimate: true` with specific reason

Write:
- `{REQ_ID}-SUBTASK-INSPECTION-REPORT.md` (per-story findings, layer corrections, subtask lists)
- Updated `{REQ_ID}-JIRA-BACKLOG.yaml` (subtasks now populated)

---

## PHASE 2C — FINALISE & AUDIT

**Enriched Requirements Generator (mode=top_down):**
Validate and produce the canonical output:
- Every impl story has exactly one SIT and one UAT counterpart
- Language tiers enforced (Epic=business, Stories=business-leaning, Subtasks=technical)
- Title suffix convention: `{LAYER}-DEV` / `{LAYER}-SIT` / `{LAYER}-UAT`
- Write `{REQ_ID}-BACKLOG.md` with unsigned SDLC_03 + SDLC_03a approval blocks

**Complexity Estimator Audit (mode=top_down) — 12 checks:**
1. Schema validation (all required fields present)
2. Fibonacci scale only (1,2,3,5,8,13)
3. `estimation_basis` non-empty for all stories
4. T-shirt → Fibonacci consistent with dimension scores
5. `needs_grooming` stories have null points
6. All impl stories have paired SIT story
7. All impl stories have paired UAT story
8. SIT assignee_role = "QA Engineer"
9. UAT assignee_role = "Product Owner"
10. UAT points = 1
11. SIT points ≤ impl points
12. Acceptance criteria are measurable (no vague language)

If any check FAILS: fix the story before proceeding. Do not export if audit_status = FAIL.

Write `{REQ_ID}-ESTIMATION-AUDIT.md`.

### GATES: SDLC_03 (PO) + SDLC_03a (Tech Lead)
Both must be signed before Jira export.

Present:
> "Research phase complete. Please review:
> - `{REQ_ID}-BACKLOG.md` (Product Owner: confirm story breakdown, ACs, sprint order)
> - `{REQ_ID}-ESTIMATION-AUDIT.md` (Tech Lead: confirm estimation, resolve needs_reestimate flags)
> Both the PO and Tech Lead must type **APPROVED**."

When both approved: update `approvals.yaml` phases.estimation and phases.backlog = approved.

---

## PHASE 3 — JIRA EXPORT

Pre-flight checks (STOP if any fail):
1. SDLC_03 approval block signed in `BACKLOG.md`
2. SDLC_03a approval block signed in `BACKLOG.md`
3. `audit_status` = PASS or PASS_WITH_FLAGS (not FAIL)
4. No stories with `needs_split: true`

If all pass, write `{REQ_ID}-JIRA-BACKLOG.yaml` to the session directory (schema-validated against `.devin/templates/jira-backlog-schema.yaml`).

Tell the user:
> "`{REQ_ID}-JIRA-BACKLOG.yaml` is ready. Import to Jira manually: create the Epic first, then Stories in dependency order (DB → API → UI → ETL), then Subtasks under each story."

---

## OUTPUT FILES (in order of creation)

```
framework/context/session/{OWNER}/{REQ_ID}/
├── approvals.yaml
├── {REQ_ID}-SPEC.md                       ← SDLC_01 approved
├── {REQ_ID}-STORY-CANDIDATES.md           ← SDLC_02b approved
├── {REQ_ID}-JIRA-BACKLOG.yaml (draft)
├── {REQ_ID}-SUBTASK-INSPECTION-REPORT.md
├── {REQ_ID}-BACKLOG.md                    ← SDLC_03 + SDLC_03a approved
├── {REQ_ID}-ESTIMATION-AUDIT.md
└── {REQ_ID}-JIRA-BACKLOG.yaml (final)
```

---

## Advice & Pointers

- **Phase 1 and Phase 2A are strictly business-language.** If you catch yourself reaching for a file name, column name, or table name — stop. That belongs in Phase 2B (subtask generation), not before.
- **Ask 2 questions max per turn during intake.** A wall of questions produces incomplete or inconsistent answers. Patience here prevents rework in subtask generation.
- **Estimation basis is your audit trail.** The dimension scores you record in `estimation_basis` are what the Tech Lead reviews at SDLC_03a. Be specific — vague reasoning ("medium complexity") will fail the audit.
- **`needs_grooming: true` is not a failure.** It is the correct output when unknowns are high. Do not force-estimate — flag and surface. The grooming session resolves it.
- **Every subtask in Phase 2B must cite a file you have actually opened.** If you find the domain entity referenced in the KB registry but the actual source file does not exist at the path listed, write: "Source file not found at {path} — possible stale registry entry." Do not fabricate a file path.
- **When scope is ambiguous during subtask generation:** Stop. Ask one question before generating subtasks for that story. Example: "The story mentions 'provider profile' — is that the `ProviderDetailCard.tsx` component or the `ProviderSummaryRow.tsx`? I'll look at both, but I want to confirm before generating subtasks."
- **Audit check 12 (vague ACs) often blocks.** Common failures: "works correctly", "user-friendly", "fast enough". Rewrite before the audit rather than after — the fix is simple: add a measurable threshold.

---

## Forbidden Actions

- **DO NOT read source code during Phase 1 or Phase 2A.** Code inspection is explicitly locked until SDLC_02b is signed. Reading code before the PO approves the story breakdown violates the top-down principle.
- **DO NOT write `{REQ_ID}-SPEC.md` before the user confirms the draft.** Show the draft and wait for explicit "YES" or "APPROVED". Never silently write the file.
- **DO NOT generate subtasks for a story that has `needs_grooming: true`.** Route to PB-13 first.
- **DO NOT generate subtasks for a story that has `needs_split: true`.** Route to PB-11 first.
- **DO NOT export to Jira if `audit_status = FAIL`.** Fix the failed stories before export. This is non-negotiable.
- **DO NOT modify any source code.** This playbook is research only. No code changes, no file edits, no schema changes.
- **DO NOT add technical terms, file names, or column names to the Epic or story summaries.** The only technical element allowed in a story summary is the `{LAYER}-DEV` / `{LAYER}-SIT` / `{LAYER}-UAT` suffix.
- **DO NOT combine SDLC_03 (PO) and SDLC_03a (Tech Lead) into a single prompt.** They are separate approvals from different roles and must be explicitly distinct.
- **DO NOT proceed to Jira export if any story has `needs_split: true`.** Blocked stories must be split first via PB-11.
