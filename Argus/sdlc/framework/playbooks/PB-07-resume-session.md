# Playbook: Resume an Interrupted Session

**Playbook ID:** PB-07  
**Paste into:** Devin Cloud → Settings → Playbooks → New Playbook  
**CLI equivalent:** `/resume-session` skill  
**When to use:** Starting a new Devin Cloud session after an interruption. Reads all session files from disk to determine exactly where the pipeline stopped, then picks up from there without regenerating approved work.

---

## Title

```
Acme Claims: Resume an Interrupted Session
```

## Description

```
Reconstructs SDLC session state from disk when a conversation is interrupted
or started fresh. Reads approvals.yaml and all session artifacts to determine
the current pipeline position. Shows a clear status report, then resumes from
the exact next step — never regenerates approved artifacts.
```

## Playbook Body

---

You are resuming an interrupted Acme Claims SDLC session. Do NOT start from scratch. Read what exists on disk and continue from exactly where the work stopped.

---

## STEP 1 — Identify the Session

Ask: "Which REQ-ID would you like to resume? (e.g. REQ-TIN-001, REQ-001)"

If no ID given, list all active sessions:
```
Scan: framework/context/session/{OWNER}/REQ-* plus legacy framework/context/session/REQ-*
```
`{OWNER}` is resolved per `.devin/rules/session-isolation.md`.
For each owner-scoped or legacy `REQ-*` directory, read its `approvals.yaml` and show:
```
{REQ_ID} | owner: {owner or legacy/unowned} | mode: {top_down/bottom_up} | last approved phase: {phase} | last entry: {provenance.log last line}
```

If the requested REQ-ID is absent from the current owner and legacy sessions,
search other owners. If found, show `owner`, `owner_email`, and
`devin_session_url` from `approvals.yaml`, state that it belongs to someone
else, and require an explicit typed confirmation before reading it. Never write
to that directory; offer to copy it into the current owner's directory.

---

## STEP 2 — Read All Session Artifacts

For the chosen `{REQ_ID}`, read ALL of the following files (read, don't assume):

| File | What to extract |
|---|---|
| `approvals.yaml` | owner, owner_email, devin_session_url, mode, phase statuses (pending/approved), signed_by, signed_at |
| `{REQ_ID}-SPEC.md` | Does it exist? Is SDLC_01 approval block signed? Is open_questions empty? |
| `{REQ_ID}-STORY-CANDIDATES.md` | Exists? SDLC_02b signed? (top_down) |
| `{REQ_ID}-GAP-ANALYSIS.md` | Exists? SDLC_02 signed? (bottom_up) |
| `{REQ_ID}-SUBTASK-INSPECTION-REPORT.md` | Exists? (top_down) |
| `{REQ_ID}-BACKLOG.md` | Exists? SDLC_03 signed? SDLC_03a signed? |
| `{REQ_ID}-ESTIMATION-AUDIT.md` | Exists? What is `audit_status`? |
| `{REQ_ID}-JIRA-BACKLOG.yaml` | Exists? Is the approval block signed (final) or absent (draft)? |
| `provenance.log` | Last logged action and timestamp |

---

## STEP 3 — Determine the Resume Point

Use this decision tree (check in order, stop at the first match):

```
IF {REQ_ID}-SPEC.md does NOT exist OR SDLC_01 not signed:
  → Resume at: INTAKE PHASE

ELSE IF mode=top_down AND {REQ_ID}-STORY-CANDIDATES.md does NOT exist:
  → Resume at: RESEARCH — Epic & Story Decomposition (Phase 2A of PB-02)

ELSE IF mode=top_down AND SDLC_02b NOT signed:
  → Resume at: GATE SDLC_02b — show STORY-CANDIDATES.md to PO for approval

ELSE IF mode=top_down AND {REQ_ID}-SUBTASK-INSPECTION-REPORT.md does NOT exist:
  → Resume at: RESEARCH — Subtask Generation / Code Inspection (Phase 2B of PB-02)

ELSE IF mode=bottom_up AND {REQ_ID}-GAP-ANALYSIS.md does NOT exist:
  → Resume at: RESEARCH — Staleness Check + Gap Analysis (Phase 2A of PB-03)

ELSE IF mode=bottom_up AND SDLC_02 NOT signed:
  → Resume at: GATE SDLC_02 — show GAP-ANALYSIS.md to BSA for approval

ELSE IF {REQ_ID}-BACKLOG.md does NOT exist:
  → Resume at: Story Generation + Enriched Requirements Generator

ELSE IF {REQ_ID}-ESTIMATION-AUDIT.md does NOT exist:
  → Resume at: Complexity Estimator Audit

ELSE IF SDLC_03 NOT signed OR SDLC_03a NOT signed:
  → Resume at: GATES SDLC_03 + SDLC_03a — present BACKLOG + AUDIT for approval

ELSE IF {REQ_ID}-JIRA-BACKLOG.yaml NOT final (no signed approval block):
  → Resume at: JIRA EXPORT — run pre-flight checks and produce final YAML

ELSE IF JIRA-BACKLOG final AND deployment not confirmed:
  → Session complete for research phase. Remind user next step is PLAN (PB-04) per story.

ELSE IF PROD deployed AND KB refresh not done:
  → Resume at: KB REFRESH (PB-06)
```

---

## STEP 4 — Show Status Report

Before resuming, print this status report:

```
═══════════════════════════════════════════════════════════
SESSION RESUME: {REQ_ID}
Mode: {top_down | bottom_up}
Requirement: {title from SPEC, or "SPEC not yet written"}
Last provenance entry: {last line from provenance.log}
═══════════════════════════════════════════════════════════

PHASE STATUS
────────────────────────────────────────────────────────
✅ Intake (SDLC_01)      APPROVED by {signed_by} at {signed_at}
  OR
⏳ Intake (SDLC_01)      PENDING — [reason: SPEC exists but unsigned / SPEC missing]

✅ Research              APPROVED (SDLC_02 or SDLC_02b signed)
  OR
⏳ Research              IN PROGRESS — [specific sub-step: gap analysis exists, awaiting SDLC_02]
  OR
❌ Research              NOT STARTED

⏳ Estimation Audit      PASS_WITH_FLAGS — {needs_grooming_count} needs-grooming stories
  OR
❌ Estimation Audit      NOT RUN

⏳ Backlog Approval      PENDING (SDLC_03 unsigned / SDLC_03a unsigned)
  OR
✅ Backlog Approval      APPROVED

❌ Jira Export           NOT YET DONE
  OR
✅ Jira Export           DONE — {REQ_ID}-JIRA-BACKLOG.yaml final

RESUMING FROM: {phase name} — {specific step}
Owner: {owner or legacy/unowned}
═══════════════════════════════════════════════════════════
```

Ask: "Does this look right? Type **YES** to resume from {step}, or tell me if something is different."

---

## STEP 5 — Resume Without Regenerating

Load all existing approved artifacts into context. Start ONLY from the identified resume point.

**DO NOT rewrite or regenerate:**
- Any file that already exists and has an approved gate
- Any gap analysis or story candidates that are already approved
- The SPEC if it is already approved

**DO start from scratch only for** the specific step identified in STEP 3.

---

---

## Advice & Pointers

- **Approved work is sacred.** A file with a signed gate is finished. Its content is what was agreed by a human. Never re-read it and decide to "improve" it — only re-read it to understand the current state.
- **Read `approvals.yaml` first, then verify.** The YAML is the authoritative pipeline tracker. But always cross-check: read the actual `.md` approval blocks to confirm the gate is genuinely signed (not just status = pending that someone forgot to update).
- **The provenance log tells you what happened last.** If `approvals.yaml` is ambiguous, the last line of `provenance.log` is usually the most reliable signal of where the work stopped.
- **Show the status report before resuming.** The user starting a new session may not know exactly where things stopped. The status report confirms shared understanding before work continues.
- **When scope is ambiguous about what needs doing next:** Stop and ask one question. Example: "The BACKLOG.md is approved but there are three stories — STORY-001, STORY-002, STORY-003. Do you want to plan all three, or start with a specific one?"

---

## Forbidden Actions

- **DO NOT regenerate any artifact that already has a signed approval gate.** Rewriting approved work without the user's explicit request is unauthorized scope expansion.
- **DO NOT start the full pipeline from scratch.** This playbook resumes from the exact gap — not from the beginning.
- **DO NOT modify any session artifact during the resume check.** Reading files to determine state is the only action. No edits until the resume point is confirmed and the user says YES.
- **DO NOT assume the resume point without reading the files.** Memory of a previous session is unreliable. Always read `approvals.yaml` and the relevant `.md` files.
- **DO NOT move or archive the session directory.** That is a manual user action described in PB-06.
- **NEVER resume another owner's session without explicit confirmation.**
- **NEVER write into another owner's directory.** Offer to copy it into the current owner's directory instead.
- **DO NOT combine a status report and a question into a wall of text.** Show the status table. Ask the single confirmation question. Wait for YES before resuming.
