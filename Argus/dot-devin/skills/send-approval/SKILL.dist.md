---
name: send-approval
description: >
  Send an open approval gate — or some of its numbered decision items — to a named person as a
  Jira approval sub-task under the story, then make this session wait for their explicit
  "approved". The sub-task carries the whole brief (gate, requirement, artifacts, criteria,
  numbered items) and every decision, delegation and note is recorded on it for audit. Say
  "/send-approval <gate> to <person> [items] \"<note>\"", "send this approval to <person>",
  or paste a SDLC-DASHBOARD-APPROVALS block from /dashboard.
visibility: internal
triggers:
  - user
  - model
invocations:
  - /send-approval
  - send this approval to
  - defer this approval to
  - let <person> approve
allowed-tools:
  - read
  - write
  - edit
  - grep
  - glob
  - exec
---

# /send-approval — put a gate decision in someone else's hands, and wait

Use this when the person in the chat is not the right approver, or wants a second name on
part of the decision: "approved 1, 2 and 3 — send 4 to Resource 17, she owns the ACs".
`.devin/rules/gate-presentation.md` ("Send an approval to someone else") is the rule; this
skill is the procedure.

## 1. Work out what is being sent

- **Gate**: the open gate in the current session (`approvals.yaml`, first phase not
  `approved`), or the gate ID named on the line. Stop if there is no open gate.
- **Items**: the numbered decision items from the gate message. Default: every item still
  pending. "send 4 to Resource 17" sends item 4 only; items the speaker approved in the same
  breath are recorded first under the gate rule (they must have said `approved`).
- **Person**: resolve through `.devin/rules/people.yaml` (`jira_user`), then Jira
  `user/assignable/search?project=ACME`. Show the resolved display name and get a yes
  before creating anything. Never guess between two matches.
- **Note**: mandatory. If none was given, ask for one sentence — why this person, what they
  should look at. Do not proceed without it.
- **Parent story**: the Acme Claims key recorded for the session. Stop if there is none; an
  approval sub-task without a parent story is not traceable.

## 2. Create or update the sub-task

First delegation for this gate — create it with the full brief:

```
python3 sdlc/framework/tools/approval_subtask.py create \
  --parent ACME-1234 --assignee <jira-user> --requested-by <session-owner-jira-user> \
  --gate SDLC_01_INTAKE_CLARIFICATION --gate-name "Requirement Intake & Clarification" \
  --requirement REQ-XXX-001 [--story STORY-001] \
  --summary-text "<the decision-relevant content from the gate message>" \
  --item "<decision item 1>" --item "<decision item 2>" ... \
  --artifact "REQ-XXX-001-SPEC.md" ... \
  --criterion "<approval criterion>" ... \
  --consequence "<blocks_if_failed text>" \
  --session-url <this session's URL>
```

`--summary-text` is the same content the chat gate showed — the reviewer must be able to
decide from the sub-task alone. Items already approved in chat are still listed, and are
marked approved with a `decide` call straight after creation so the sub-task shows the whole
picture.

Gate already has a sub-task (`approval_subtask` in `approvals.yaml`) — send the items on:

```
python3 sdlc/framework/tools/approval_subtask.py delegate \
  --key ACME-1250 --items 4 --to <jira-user> --by <sender-jira-user> --note "<note>"
```

Both support `--dry-run`; use it first when the person is new to the flow and show them the
payload.

## 3. Record the wait

In `approvals.yaml`, for the gate's phase:

```yaml
status: waiting
approval_subtask: ACME-1250
delegated_to: dso
delegated_by: resource3
delegated_at: "2026-09-24T18:10:00Z"
delegated_items: [4]
delegation_note: "Resource 17 owns the acceptance criteria"
decision_items:
  - {n: 1, text: "...", state: approved, by: "Resource 3"}
  - {n: 4, text: "Comment on ACME-1234: proposed acceptance criteria ...", state: delegated, by: dso}
```

`signed_by` / `signed_at` stay empty until the sub-task comes back approved.

## 4. Wait for the word

Tell the user: "ACME-1250 is with Resource 17. I'll check every 15 minutes and carry on when
she records *approved*; nothing moves until then." Then loop:

1. `python3 sdlc/framework/tools/approval_subtask.py status --key ACME-1250`
2. Exit `3` (pending): wait 15 minutes (the `wait` tool, 900 seconds) and check again. Say
   nothing in chat unless the user speaks — a progress line every poll is noise.
3. Exit `0` (approved): copy `items[].by`, `items[].at`, `items[].note` into the approval
   record, set `status: approved`, `signed_by` to the sub-task approver(s), and advance to
   `next_gate` under the gate rule. Say who approved, when, and any notes.
4. Exit `4` (rejected): present the rejecting item, who and why, set `decision: rejected`,
   stop the stage.
5. The delegate may send items on again (`delegate` from their dashboard); the poll simply
   keeps waiting and the sub-task assignee changes. Report the new name once.

If this session sleeps or ends while waiting, `/resume-session` finds `status: waiting` and
`approval_subtask`, runs `status` once, and resumes here. Nothing about the delegation lives
only in this chat.

## 5. Dashboard paste-back

`/dashboard` produces a `SDLC-DASHBOARD-APPROVALS v1` block. Apply it line by line:

```
SDLC-DASHBOARD-APPROVALS v1
- key: ACME-1250          # approval sub-task, or "session:REQ-XXX-001/SDLC_01_INTAKE_CLARIFICATION" for a chat-only gate
  items: "1,2,3"
  decision: approve       # approve | approve-with-notes | reject | delegate
  note: "..."
- key: ACME-1250
  items: "4"
  decision: delegate
  to: dso
  note: "Resource 17 owns the ACs"
```

`approve` / `approve-with-notes` / `reject` → `approval_subtask.py decide --by <viewer>`;
`delegate` → this skill from step 1 with the person and note filled in. For a
`session:` key with no sub-task yet, `approve`/`reject` update `approvals.yaml` directly
under the gate rule (the dashboard Approve action counts as the word), and `delegate`
creates the sub-task as in step 2.

## Hard rules

- No note, no delegation. No confirmed assignable person, no sub-task.
- Never write to Jira except through `approval_subtask.py`; never improvise a payload.
- Never advance a gate on a comment, an assignment change or a closed status alone — only
  `status` exit 0, which requires every item to be approved with the word.
- Never put PII in `--summary-text` or notes (`.devin/rules/pii-handling.md`).
- Do not send an approval to yourself to get past a gate.
