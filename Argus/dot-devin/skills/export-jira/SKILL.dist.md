---
name: export-jira
description: >
  Produces the final REQ-{id}-JIRA-BACKLOG.yaml for Jira import.
  Runs only after SDLC_03 (PO) and SDLC_03a (Tech Lead) gates are signed
  and the estimation audit has passed. Validates schema conformance before writing.
  Say "/export-jira" or "export the backlog to Jira" to invoke.
visibility: internal
triggers:
  - user
  - model
allowed-tools:
  - read
  - write
  - edit
  - grep
  - glob
---

# Skill: Export Jira Backlog

## Purpose

Ticket shapes (Epic, Story, SIT/UAT stories, sub-tasks) follow `.devin/templates/jira-issue-templates.md`; the field IDs and the ticket contract are in `.devin/rules/jira-ticket-standards.yaml`.
Produce the final `REQ-{id}-JIRA-BACKLOG.yaml` from the approved backlog and
estimation audit. This is the last skill in the research pipeline, producing
a file the team can import into Jira manually.

## When to Invoke
- User says "/export-jira" or "export to Jira" or "generate Jira YAML"
- Automatically after SDLC_03 and SDLC_03a are both signed
- Triggered by `/research` (SHARED-STEP 7) at the end of the pipeline

---

## Pre-flight Gate Checks (STOP if any fail)

Before writing any output, verify ALL of the following:

1. **SDLC_03 signed** — Read owner-scoped `approvals.yaml` and confirm the
   SDLC_03 phase has `status: approved`, `decision: approved`, a real
   `signed_by`, and the approval-record fields required by
   `.devin/rules/gate-presentation.md`.
   If unsigned → STOP: "Backlog not yet approved by Product Owner. Cannot export."

2. **SDLC_03a signed** — Confirm the SDLC_03a phase in the same
   `approvals.yaml` is approved and has its recorded signer and approval-record
   fields. Gate presentation and recording follow
   `.devin/rules/gate-presentation.md`.
   If unsigned → STOP: "Estimation not yet reviewed by Tech Lead. Cannot export."

3. **Audit status** — Read `{REQ_ID}-ESTIMATION-AUDIT.md`. Confirm `audit_status`
   is `PASS` or `PASS_WITH_FLAGS` (not `FAIL`).
   If FAIL → STOP: "Estimation audit failed. Resolve flagged stories first."

4. **No needs_split stories** — Check BACKLOG.md for any story with `needs_split: true`.
   If found → STOP: "Story {id} flagged needs_split. Split it before exporting."

All 4 checks must pass before proceeding.

---

## Schema Reference

Load and follow EXACTLY:
`.devin/templates/jira-backlog-schema.yaml`

---

## Export Steps (run in order)

### Step 1 — Load Inputs
Read:
- `{REQ_ID}-SPEC.md` — for Epic description, acceptance criteria, business value
- `{REQ_ID}-BACKLOG.md` — for story list and estimates
- `{REQ_ID}-GAP-ANALYSIS.md` (bottom_up) or `{REQ_ID}-STORY-CANDIDATES.md` (top_down)
  — for source files, gap_ids, estimation_basis
- `{REQ_ID}-ESTIMATION-AUDIT.md` — for corrected point values (use audit values, not draft)
- `.devin/templates/jira-backlog-schema.yaml` — schema to conform to

### Step 2 — Build Metadata Block
```yaml
metadata:
  requirement_id: "{REQ_ID}"
  requirement_title: "{title from SPEC}"
  generated_date: "{ISO8601 now}"
  generated_by: "export-jira skill v1.0"
  schema_version: "1.0"
  approval_status: APPROVED
  total_story_points: {sum of impl story points, excluding null}
  story_counts:
    impl: {count}
    sit:  {count}
    uat:  {count}
    total: {total}
  needs_grooming_count: {count from audit}
  needs_split_count: 0  # export blocked if needs_split > 0
```

### Step 3 — Build Issues List

Order MUST be:
1. Epic (one)
2. For each implementation story (in dependency order DB → API → UI → ETL):
   a. Implementation Story
   b. Paired SIT Story (immediately after)
   c. Paired UAT Story (immediately after SIT)
3. Subtasks are nested inside their parent implementation story

**Title Suffix Rules (MANDATORY, no exceptions):**
- Implementation stories: summary ends with `{LAYER}-DEV` (e.g. `DB-DEV`)
- SIT stories: same brief description + `{LAYER}-SIT`
- UAT stories: same brief description + `{LAYER}-UAT`
- The brief description is IDENTICAL across all three paired stories
- NEVER use `[SIT]` or `[UAT]` prefixes
- LAYER values: `DB | API | UI | ETL | TESTING | BIZ | INFRA`

**UAT rules (no exceptions):**
- `story_points: 1`
- `original_estimate_hours: 1.0`
- `assignee_role: "Product Owner"`

**SIT rules (no exceptions):**
- `assignee_role: "QA Engineer"`
- Points: 1 if impl ≤ 3; 2 if impl = 5; 3 if impl = 8; 5 if impl = 13

**Needs-grooming stories:**
- Include in output with `story_points: null`
- Add label `NEEDS-GROOMING`
- Do NOT exclude them

### Step 4 — Schema Validation (before writing)

Verify every issue in the list:
- All required fields populated (issuetype, summary, description, story_points, original_estimate_hours, priority, labels, assignee_role, acceptance_criteria, dependencies)
- story_points in {1,2,3,5,8,13} or null (needs_grooming only)
- All UAT story_points = 1
- All SIT assignee_role = "QA Engineer"
- All UAT assignee_role = "Product Owner"
- Every impl story immediately followed by its SIT story, then UAT story
- All impl summaries end with `{LAYER}-DEV` (uppercase)
- All SIT summaries end with `{LAYER}-SIT` (uppercase)
- All UAT summaries end with `{LAYER}-UAT` (uppercase)
- No `[SIT]` or `[UAT]` prefix in any summary
- All subtask hours sum to parent story `original_estimate_hours`

If any check fails, DO NOT write the file. Report the violation clearly and stop.

### Step 5 — Write Output

Write to: `sdlc/framework/context/session/{OWNER}/{REQ_ID}/{REQ_ID}-JIRA-BACKLOG.yaml`
`{OWNER}` is resolved per `.devin/rules/session-isolation.md`.

Include a header comment at the top:
```yaml
# REQ-{id}-JIRA-BACKLOG.yaml
# Generated by: export-jira skill v1.0
# Schema version: 1.0
# Requirement: {requirement_title}
# Generated: {ISO8601 timestamp}
# Approval status: APPROVED (SDLC_03 + SDLC_03a signed)
#
# HOW TO IMPORT TO JIRA:
# Option 1 — Manual: Create Epic first, then Stories in order, then Subtasks.
#             Use this YAML as the reference for all field values.
# Option 2 — CSV import: Convert to CSV matching your Jira project's field mapping.
#
# Field mapping (this YAML → Jira):
#   summary              → Summary
#   description          → Description
#   story_points         → Story Points
#   priority             → Priority
#   labels               → Labels
#   assignee_role        → Add to Description or Role custom field
#   acceptance_criteria  → Add to Description under "Acceptance Criteria"
#   dependencies         → Issue Links → "is blocked by"
```

### Step 6 — Log to Provenance

Append to `sdlc/framework/context/session/{OWNER}/{REQ_ID}/provenance.log`:
```
{ISO8601} | EXPORT-JIRA | REQ_ID={REQ_ID} | stories={count} | needs_grooming={n} | schema_valid=true
```

---

## Rules
- NEVER write the file if any gate check fails or schema validation fails
- NEVER include a story flagged `needs_split: true`
- NEVER use a person's name in `assignee_role` — roles only
- ALWAYS use the audit's corrected point values, not the draft backlog values
- ALWAYS verify subtask hour sums before writing
