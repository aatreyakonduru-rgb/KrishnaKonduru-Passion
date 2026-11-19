---
name: handover
description: >
  Hand a Devin session and the work in it to a teammate on the Acme Claims roster. Writes a handover
  note (where the work is, what is signed, what comes next) into the giver's own session
  directory, reassigns the named Jira items with a comment pointing at the session, tags the
  session, and tells the teammate how to pick it up with /resume-session. Say
  "/handover <person> [REQ-ID] [ACME-keys...]" or paste a SDLC-DASHBOARD-SESSION-HANDOVERS block
  from /dashboard.
visibility: public
triggers:
  - user
  - model
invocations:
  - /handover
  - hand this session over to
  - transfer my session to
allowed-tools:
  - read
  - write
  - edit
  - grep
  - glob
  - exec
---

# Skill: Handover

A session in Devin Cloud stays with the person who started it: there is no confirmed way to
change its owner (`[?]` — Devin docs describe `create_as_user_id` for *new* sessions and
view/manage permissions, not a transfer of an existing one). So a handover is three things that
do move: the note, the Jira work, and a pointer for the teammate. The original session URL is
shared as-is; whether the teammate can open it depends on their Devin Cloud permissions, not on
anything this skill does.

## Steps

1. **Work out what is being handed over.** From the command, or from a pasted
   `SDLC-DASHBOARD-SESSION-HANDOVERS v1` block (one entry per `session:` id with `to:` and an
   optional `note:`). If no session id is given, use the current session. If no requirement is
   given, look at what the session worked on; if that is not clear, ask — do not guess a REQ id.
2. **Resolve people.** The giver is the person behind this session (`/identify-requester`);
   the taker must be one roster entry in `.devin/rules/people.yaml`. The tool refuses a name that
   matches nobody or more than one person — pass the Jira username then. Being on the roster is
   not proof they can open the session; say so in the message to them.
3. **Confirm before writing.** Show the giver: taker, session, requirement, the Jira keys that
   will be reassigned, and the note. Only Jira items they name move; never widen the list
   from Jira searches. Wait for a yes.
4. **Run the tool.** Dry run first, then live:
   ```bash
   python3 sdlc/framework/tools/handover.py \
     --session <devin-session-id> --session-title "<title>" \
     --from <giver-jira-user> --to <taker-jira-user> \
     [--requirement REQ-xxx] [--jira ACME-nnnn ...] --note "<where it is, what is next>" --dry-run
   ```
   It writes `HANDOVER-<stamp>-<taker>.md` into the giver's own directory — the requirement's
   directory when the giver owns it under `context/session/{OWNER}/`, otherwise
   `context/session/{OWNER}/handovers/` — appends `provenance.log`, and reassigns each Jira key
   through `question_subtask.py delegate` with a comment carrying the session URL. It refuses to
   write into another owner's directory (`.devin/rules/session-isolation.md`) and refuses a
   requirement that exists under more than one owner.
5. **Finish the Devin side** with the session tools, which the script cannot reach: add the tag
   `handed-to:<taker-jira-user>` to the session, and post the note into it so the history says
   where it went. Commit the note and `provenance.log` by explicit path on the working branch.
6. **Tell the taker**, in plain words: the session link, the requirement id, that
   `/resume-session REQ-xxx` in a new session will show the note and offer to copy the artefacts
   into their own directory, and that their `/dashboard` now carries the reassigned Jira items.
   Tell the giver the session still shows under their name in Devin Cloud.

## What the note carries

Giver and taker with roster roles, the session URL, the requirement and its directory, every
gate in `approvals.yaml` (signed by whom and when, or still open), the file list, the giver's own
words on where the work is, the Jira keys moved, and the branch. Facts read from a file are
tagged `[E: …]`; what the tool cannot know — whether the taker can open the session, whether a
gate that is unsigned is actually blocked — is `[?]` with who can answer. Nothing is inferred
from the chat history: if the giver wrote no note, the file says so and names them.

## Rules

- Roster-only takers; a name that matches two people stops the tool.
- Only the owner of a requirement directory can hand it over; legacy unowned directories are
  handed over by reference and the note lives under the giver's owner slug.
- Jira writes go through `question_subtask.py` (bearer token, one `/myself` check, no retry on
  401/403). `--dry-run` prints the requests without sending them.
- Never claim the session's ownership moved. Never embed a token in anything written.
