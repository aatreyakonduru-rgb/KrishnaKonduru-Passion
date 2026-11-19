---
name: resume-session
description: >
  Resumes an interrupted SDLC session from exactly where it left off. Reads
  approvals.yaml from the session directory to determine which phase was
  reached and what was approved, then picks up at the correct next step.
  Say "/resume-session REQ-001" or "resume the REQ-001 session" to invoke.
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

# Skill: Resume Session

## Purpose
Reconstruct session state from disk when a conversation is interrupted or
started fresh. Reads all existing session artifacts to determine the current
pipeline position, then resumes from exactly the right step — not from the
beginning.

## When to Invoke
- User says "/resume-session REQ-{id}" or "resume REQ-{id}" or "pick up where we left off"
- Automatically when Devin detects a partial session (approvals.yaml exists but pipeline is incomplete)
- When a new conversation starts and the user references a previous requirement

---

## Step 1 — Identify the Session

Parse the requirement ID from the user's message (e.g. "REQ-001", "REQ-003").

If no ID is given, list all active sessions:
```
Scanning: sdlc/framework/context/session/{OWNER}/REQ-* plus legacy sdlc/framework/context/session/REQ-*
```
`{OWNER}` is resolved per `.devin/rules/session-isolation.md`.
For each owner-scoped directory matching `REQ-*`, and each legacy directory:
- Read its `approvals.yaml`
- Show: `{REQ_ID} | owner: {owner or legacy/unowned} | mode: {top_down/bottom_up} | last phase: {phase} | status: {status}`

If the requested REQ-ID is not found under `{OWNER}` or in legacy sessions,
search other owner directories. If found, read only the ownership fields from
`approvals.yaml`, print its `owner`, `owner_email`, and `devin_session_url`,
state that it belongs to someone else, and require the user to type an explicit
confirmation before reading it. Never write to that directory; offer to copy it
into `sdlc/framework/context/session/{OWNER}/{REQ_ID}/` instead.

If the requirement's directory, or the owner's `handovers/` folder, holds a `HANDOVER-*.md`
naming the current user as the taker, show it first: it says where the work is, which gates
are signed and what comes next. That note is the giver's authorisation to copy the artefacts
into the current owner's directory — still ask before copying, and never write into the
giver's directory.

Ask: "Which session would you like to resume? (Enter REQ-ID)"

---

## Step 2 — Read Session State

Read ALL of the following from the resolved owner-scoped directory
`sdlc/framework/context/session/{OWNER}/{REQ_ID}/`, falling back to
legacy `sdlc/framework/context/session/{REQ_ID}/` when absent:

| File | What to extract |
|------|----------------|
| `approvals.yaml` | owner, owner_email, devin_session_url, mode, phase statuses (pending/approved), signed_by, signed_at, decision, approver_name, approver_role, timestamp, rationale |
| `{REQ_ID}-SPEC.md` | exists? SDLC_01 approval block signed? open_questions empty? |
| `{REQ_ID}-GAP-ANALYSIS.md` | exists? SDLC_02 approval block signed? (bottom_up) |
| `{REQ_ID}-STORY-CANDIDATES.md` | exists? SDLC_02b approval block signed? (top_down) |
| `{REQ_ID}-SUBTASK-INSPECTION-REPORT.md` | exists? (top_down) |
| `{REQ_ID}-BACKLOG.md` | exists? SDLC_03 signed? SDLC_03a signed? |
| `{REQ_ID}-ESTIMATION-AUDIT.md` | exists? audit_status? |
| `{REQ_ID}-JIRA-BACKLOG.yaml` | exists? is it final (approval block signed) or draft? |
| `provenance.log` | last logged action and timestamp |

`approvals.yaml` exists in two shapes. The current shape is a `phases:` map
(`.devin/templates/approvals.yaml.template`). Older sessions instead hold an
`approvals:` list of `{gate_id, decision, approver_name, timestamp}` entries —
read those by mapping each `gate_id` to its phase via
`.devin/rules/approval-gates.yaml`, and treat any phase with no entry as pending.

---

## Step 3 — Determine Current Position

Before the tree: if any phase has `status: waiting` and an `approval_subtask`, the gate was
sent to someone else and the session went to sleep waiting for them. Run
`python3 sdlc/framework/tools/approval_subtask.py status --key <approval_subtask>`
once. Exit 0 → record the approver(s), timestamp and notes from the sub-task into the phase,
set `status: approved`, and resume at the phase after it. Exit 3 → say who it is with and how
long, then keep waiting under `/send-approval` step 4. Exit 4 → present the rejection and stop.
Never treat a `waiting` phase as approved from the file alone.

Use this decision tree to find the exact resume point:

```
SPEC missing or SDLC_01 not signed
  → Resume at: INTAKE PHASE (Step 5 — write the SPEC)
  → Or if no questions have been asked: INTAKE PHASE (Step 3 — generate questions)

SPEC exists and SDLC_01 signed, BUT:
  top_down: STORY-CANDIDATES missing or SDLC_02b not signed
    → Resume at: RESEARCH PHASE top-down Step 1 (Epic & Story Decomposition)
  bottom_up: GAP-ANALYSIS missing or SDLC_02 not signed
    → Resume at: RESEARCH PHASE bottom-up Step 1 (Source Staleness Check)

GAP-ANALYSIS/STORY-CANDIDATES approved, BUT:
  top_down: SUBTASK-INSPECTION-REPORT missing
    → Resume at: RESEARCH PHASE top-down Step 3 (Subtask Generation — code inspection)
  BACKLOG missing or SDLC_03/SDLC_03a not both signed
    → Resume at: RESEARCH PHASE Step 6/7 (Story Generation + Audit)
  ESTIMATION-AUDIT missing
    → Resume at: RESEARCH PHASE Step 7 (Complexity Estimator Audit)

BACKLOG approved AND ESTIMATION-AUDIT PASS/PASS_WITH_FLAGS AND JIRA-BACKLOG not final
  → Resume at: EXPORT JIRA (/export-jira)

JIRA-BACKLOG final (export done), PROD not yet deployed
  → Session complete for research. Remind user next step is PLAN phase per workflows/plan.md.

PROD deployed, KB refresh not done
  → Resume at: KB REFRESH (/kb-refresh)
```

---

## Step 4 — Show Status Report

Before resuming, print a clear status report:

```
═══════════════════════════════════════════════
SESSION RESUME: {REQ_ID}
Mode: {top_down | bottom_up}
Requirement: {title from SPEC or "not yet written"}
═══════════════════════════════════════════════

PHASE STATUS
────────────
✅ Intake (SDLC_01)         — APPROVED by {signed_by} at {signed_at}
   OR
⏳ Intake (SDLC_01)         — PENDING (last action: {last provenance entry})

✅ Research — gap analysis  — APPROVED (bottom_up)
   OR
✅ Research — story cands   — APPROVED by PO (top_down)
✅ Research — subtasks      — COMPLETE (top_down)
⏳ Research — backlog       — PENDING (BACKLOG.md exists, awaiting SDLC_03+03a)
   OR
❌ Research                 — NOT STARTED

⏳ Estimation Audit         — audit_status: PASS_WITH_FLAGS (2 needs_grooming)
   OR
❌ Estimation Audit         — NOT RUN

❌ Jira Export              — NOT YET DONE
   OR
✅ Jira Export              — DONE ({REQ_ID}-JIRA-BACKLOG.yaml final)

RESUMING FROM: {phase name} — {specific step}
Owner: {owner or legacy/unowned}
═══════════════════════════════════════════════
```

Ask: "Does this look right? Type **YES** to resume from {step}, or tell me if something is wrong."

---

## Step 5 — Resume from the Correct Point

Once confirmed, invoke the appropriate skill or step:

| Resume point | Action |
|-------------|--------|
| Intake — write SPEC | Run intake Step 5 with existing answers |
| Intake — generate questions | Run intake Step 3 with existing raw requirement |
| Research — staleness check (bottom_up) | Run research bottom-up from BU Step 1 |
| Research — epic decomposition (top_down) | Run research top-down from TD Step 1 |
| Research — subtask generation (top_down) | Run research top-down from TD Step 3 |
| Research — story generation | Run research from story generation step |
| Research — estimation audit | Run research complexity estimator audit step |
| Export Jira | Run /export-jira |
| KB Refresh | Run /kb-refresh |

When resuming mid-phase, load ALL existing artifacts first so nothing is regenerated
that is already complete. Only generate what is missing.

---

## Rules
- NEVER regenerate artifacts that already exist and are approved — read them, don't rewrite
- NEVER skip showing the status report before resuming
- NEVER assume a phase is complete — verify by reading the actual files
- ALWAYS cite the source file path where each status was determined
- If approvals.yaml is missing but other session files exist, reconstruct state
  from the files themselves (check for signed gate references in each .md file)
  and then record the decision using `.devin/rules/gate-presentation.md`.
- If session directory doesn't exist at all, tell the user to run `/start`
- NEVER resume another owner's session without explicit typed confirmation
- NEVER write into another owner's directory; offer to copy it into the current owner's directory
