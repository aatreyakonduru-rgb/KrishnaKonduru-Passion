# Rule: Gate Presentation and Approval Recording

Every human approval gate must use this rule. Gate definitions come from
`.devin/rules/approval-gates.yaml`; skills must not invent a different approval
flow or omit the decision context.

Some skills define their own review points that have no entry in
`approval-gates.yaml` — the documentation-pipeline gates in
`/app-run-pipeline`, and the write confirmations in `/story-splitter` and
`/grooming-assistant`. Present those the same way, with the review content and
the explicit options in one message, taking the criteria from the skill itself.
They have no phase in `approvals.yaml`, so there is no approval record to write:
the decision governs whether the skill writes its files and advances.

## Present the gate in chat

Before waiting for a decision, send one chat message containing:

1. The gate ID and canonical gate name.
2. The requirement ID and, where applicable, the story ID.
3. Every artifact being reviewed, using session-relative paths.
4. The gate's `approval_criteria` from `approval-gates.yaml` as a checklist.
5. The `blocks_if_failed` consequence.
6. The artifact content needed for the decision. Summarise long artifacts to
   their decision-relevant sections and link the full file; never silently omit
   an artifact or its relevant content.
7. The **numbered decision items** — every distinct thing the approver is being
   asked to sign off, `[1]`, `[2]`, … A gate with nothing separable still has
   one item ("approve this gate as presented"). Whenever the run proposes a
   change to the story's points or fix version, that proposal is its own item,
   worded "Update ACME-nnnn <field> in Jira: <old> → <new>", so the PO/BSA
   answers it explicitly. Approving that item authorises the Jira write;
   declining it keeps the change in the session artifacts only. The description
   and acceptance criteria of a ticket are never changed once SDLC has started
   on it: a proposed change to them, or to scope, is the item
   "Comment on ACME-nnnn: proposed <field> <old> → <new>", and approving it
   posts that comment only.
8. These explicit options, per item or for all items:
   - **Approve** — record an approved decision and continue.
   - **Reject with reasons** — record a rejected decision and rationale; do not
     advance.
   - **Approve with notes** — record an approved decision and the supplied
     notes, then continue.
   - **Send to someone else** — name the person and give a note (the note is
     mandatory); see "Send an approval to someone else" below.

The gate content, decision items and artifact links must appear in the same
message as the options, so the approver can see what they are approving before
choosing.

## What counts as an approval

Only the word **`approved`** — any case: `approved`, `Approved`, `APPROVED` —
as the first word of the reply, or the Approve action from `/dashboard`, records
an approval. Nothing else does. `continue`, `ok`, `go ahead`, `looks good`,
`approve`, `yes`, a thumbs-up, or a request such as "create the PR" are **not**
approvals: reply that the gate is still open, repeat the options, and wait.
`sdlc/framework/tools/approval_subtask.py` exposes the same test as
`is_explicit_approval()` — use it rather than judging the wording yourself.

Partial approvals are allowed and expected: "approved 1, 2 and 3; send 4 to
Resource 17 — she owns the ACs" approves items 1–3 and delegates item 4 with that
note. A gate advances only when every item is approved. One rejected item
rejects the gate.

A reply that only moves the conversation on ("continue", "next") while a gate
is open is a navigation request, not a decision — do not advance, do not write
an approval record.

## Send an approval to someone else

When the approver, or the session owner, says to send the gate (or some of its
items) to a named person — `/send-approval <gate> to <person> [items] "<note>"`
or the dashboard's *Send to someone else* — do this and nothing else:

1. Resolve the person as an assignable Acme Claims user (`.devin/rules/people.yaml`
   first, then Jira `user/assignable/search`). Confirm the resolved name before
   creating anything. Refuse without a note.
2. Create (or update) the approval sub-task under the parent story with
   `approval_subtask.py create` / `delegate`: gate, requirement, story, the full
   decision context, artifacts, criteria, consequence, the numbered items. The
   sub-task is the reviewer's whole brief — they must not need this session.
3. Record in `approvals.yaml` for that gate: `status: waiting`,
   `delegated_to`, `approval_subtask`, the items sent, the note, who sent it and
   when. `signed_by` stays empty.
4. Wait. Poll `approval_subtask.py status --key <sub-task>` every 15 minutes
   (exit 0 approved, 3 pending, 4 rejected). On approved, copy the approver, the
   timestamp and the notes from the sub-task into the approval record and
   advance. On rejected, present the reasons and stop. While pending, do not
   advance and do not draft the next stage.
5. If the session goes to sleep or is closed while waiting, `/resume-session`
   reads `approval_subtask` from `approvals.yaml`, checks the status once, and
   either advances or keeps waiting — a delegated approval is never lost with
   the session.

Every create, decision, delegation and note lands as a comment on the sub-task
and a one-line mirror on the parent story; the sub-task is the audit trail.
No Jira write is made outside `approval_subtask.py` / `question_subtask.py`.

## Record the real approver

When the user selects an approval option, identify the approver from the
display name and email given in the approving chat message. If either is not
provided, fall back to `git config user.name` and `git config user.email`.
Write `signed_by` as the real display name and email, for example
`Resource 3 <resource3@acme.example>`. Never write the literal
`user`.

The session `owner` remains the person who ran the session. `signed_by` and the
approval record identify the person who approved this gate; they must not be
conflated.

## Record the approval schema

For the selected gate, update its phase entry in `approvals.yaml` without
removing the existing `status`, `signed_by`, `signed_at`, or `notes` fields.
Record the fields from `approval_record_schema` in
`.devin/rules/approval-gates.yaml` alongside them:

```yaml
gate_id: SDLC_01_INTAKE_CLARIFICATION
requirement_id: REQ-YYYY-NNN
story_id: ~
approver_name: "Resource 3"
approver_role: bsa
decision: approved
approval_words: "approved 1-3; send 4 to Resource 17"   # the literal reply, for the audit trail
timestamp: "2026-09-18T01:37:53Z"
rationale: "The criteria and scope are complete."
artifacts_reviewed:
  - "REQ-YYYY-NNN-SPEC.md"
decision_items:
  - {n: 1, text: "Acceptance criteria 1-5 as written", state: approved, by: "Resource 3"}
  - {n: 2, text: "Comment on ACME-18698: proposed acceptance criteria (none) → AC 1-5", state: approved, by: "Resource 17"}
approval_subtask: ACME-18750      # when any item was sent to someone else
delegated_to: dso
next_gate: SDLC_02_GAP_ANALYSIS_REVIEW
role_mismatch: false
```

For **Approve**, set `status: approved`, `decision: approved`, populate the
identity, timestamp, rationale, reviewed artifacts, and next gate. For
**Approve with notes**, do the same and copy the notes into both `rationale`
and the existing `notes` field where appropriate.

For **Reject with reasons**, set `decision: rejected` (or
`needs_revision` when that is the clearest outcome), keep `status` unapproved,
write the rationale to `notes` and `rationale`, and do not populate an
approved `next_gate`. The skill must stop and must not advance.

## Check the approver role

Read the gate's `required_role` and named `approvers` from
`.devin/rules/approval-gates.yaml`. Anyone with "lead" in one of their roles
(tech_lead, delivery_lead, solution_lead, lead) may sign any gate. If the approver is not in the named list
for that gate, still record the decision, set `role_mismatch: true`, and state
in the chat confirmation that the expected role or named approver list did not
match. Include the expected role in the note. This is a visible warning, not a
block: delegated approvals are allowed.

## Advance only after approval

Only an approved decision — every decision item approved, each by the word
`approved` or the dashboard Approve action — may advance to `next_gate`.
Rejections, `needs_revision`, `waiting` on a sub-task, missing identity,
unanswered items, or a reply that is not an explicit approval leave the gate
pending and require follow-up in chat.

No gate is optional. `SDLC_01_INTAKE_CLARIFICATION` is presented even when
intake produced no questions: the spec, acceptance criteria, scope and
assumptions are still shown with the options above and wait for `approved`.

When an item of the form "Update ACME-nnnn … in Jira" or "Comment on ACME-nnnn: …"
is approved, make that write (the field update, or the comment) immediately after
the gate closes, record old and new values plus the approver in `approvals.yaml`
under `jira_updates`, and say so in chat. Neither writes the description or
acceptance criteria fields. When it
is rejected or not offered, Jira is not touched.
