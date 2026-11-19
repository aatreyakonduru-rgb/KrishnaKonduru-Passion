---
name: document-validation
description: >
  Tech Lead review gate for the knowledge base. Collects every open question the KB
  cannot settle from its own sources, renders them into a single-file HTML form with
  context, rationale, current understanding and a proposed answer, then applies the
  returned answers to the KB documents and commits. Say "/document-validation" to
  generate the form, or paste a SDLC-KB-VALIDATION-ANSWERS block to apply answers.
argument-hint: "[new | apply | status | a priority or area filter, e.g. P1, CHF, jira]"
visibility: internal
triggers:
  - user
  - model
invocations:
  - /document-validation
  - validate the knowledge base
  - what KB questions need answering
  - apply the KB validation answers
allowed-tools:
  - read
  - write
  - edit
  - grep
  - glob
  - exec
---

# /document-validation — Knowledge base validation gate

Two directions. **Out:** turn the KB's open questions into a form a Tech Lead can answer
in a browser. **In:** take the answers back and write them into the KB.

Nothing here touches application code. The only writes are to
`docs/knowledge-base/**` and the validation registry.

## The branch is fixed

The knowledge base lives on **`feature/devin-sdlc`**, always, and this skill commits
straight to it. Nobody has to ask for that branch and nobody should be asked which branch
to use — it is not a choice. Anyone who wants to do something else with the repository can
work on a branch of their own; the KB does not move.

So before anything else:

```
git fetch -q origin && git checkout feature/devin-sdlc && git pull -q --ff-only
```

If the working tree is dirty with unrelated changes, or the pull is not a fast-forward,
stop and tell the user rather than committing KB changes on top of someone else's work.

## Which direction am I in?

| The user… | Do |
|---|---|
| types `/document-validation` (or `new`, or a filter) | **Direction A — generate** |
| pastes a `# SDLC-KB-VALIDATION-ANSWERS` block, or names a file containing one | **Direction B — apply** |
| asks `status` | print the counts from `VALIDATION/ANSWER_LOG.md` and the registry, and stop |

---

# Direction A — generate the form

## STEP A1 — Refresh the registry

The registry is `docs/knowledge-base/VALIDATION/KB_OPEN_QUESTIONS.yaml`.
Its header documents the schema; read it before editing.

Grep the knowledge base for open questions and check each one is represented. The pipelines
write two markers and both are open questions — `[UNRESOLVED]` where a document could not settle
something from its own sources, and `[REQUIRES STAKEHOLDER INPUT]` where only the business can
answer:

```
grep -rnE "UNRESOLVED|REQUIRES STAKEHOLDER INPUT" docs/knowledge-base --include=*.md
grep -rn "REQUIRES STAKEHOLDER INPUT" sdlc/framework/context/session --include=*.md
```

These are the same markers the `/dashboard` "Documents waiting on a business answer" panel counts
for leads, the PO office and the BSA, so a question visible there must end up in this registry —
that panel is where somebody notices it, and this form is how they answer it. Ignore lines where
the marker is a heading or quoted in backticks: those describe the convention rather than ask
anything. A stakeholder-input question is usually for the PO office or the BSA rather than the
Tech Lead, so name the owner in `context` and set `priority` by what it blocks.

Several markers usually describe one decision — the per-document "Open items" lists
repeat what the body already raised. **Group by decision, not by marker.** One question
per thing a human has to decide.

A marker earns a registry entry only if answering it changes the KB. If it records a
fact that is simply unknowable from here (a vendor's internal schedule), leave it as an
`[UNRESOLVED]` note and do not ask.

For each new entry write all of `context`, `question`, `why`, `understanding`,
`proposed_answer`, `kb_doc`, `priority`. The proposed answer is the one that matters:
it is what gets written if the reviewer clicks accept, so it must be what you would
defend, not a placeholder. Say how confident you are inside `understanding` — a
reviewer skims fast and needs to know which answers to check.

Never reuse an `id` for a different question; answers are matched on it.

## STEP A2 — Render

```
python3 sdlc/framework/tools/gen_validation_form.py \
    docs/knowledge-base/VALIDATION/KB_OPEN_QUESTIONS.yaml
```

Writes `VALIDATION/KB-VALIDATION-FORM.html` — self-contained, no network, no server.
The generator refuses to render a question missing any required field, so a validation
error means the registry entry is incomplete, not that the tool is broken.

If the user gave a filter (`P1`, `CHF`, `jira`), still render everything — the form has
priority filters built in — and just tell them which filter to use on screen.

## STEP A3 — Hand it over

Attach the HTML to the user with `message_user`. It renders inline in the session
sidebar and downloads to their machine; do **not** start a web server for it.

Tell them, briefly: open it, answer what they can, click **Generate answers**, then
either paste the text block back into the session or download the `.yaml` and attach it.
Answers are held in browser local storage, so the form can be closed and reopened.

Then stop and wait. Do not pre-emptively apply your own proposed answers.

**Started from Argus** (the prompt says so): Argus cannot see attachments.
It renders the form itself from the registry on the branch, so post
`[SDLC] artefact docs/knowledge-base/VALIDATION/KB-VALIDATION-FORM.html — repo file`
instead of attaching, say how many questions were added or changed, and tell the user to reload
the form tab. In a dry run nothing is committed, so list the questions you would add instead.
Answers sent from the form arrive as `/document-validation apply these answers` with the block in
a `yaml` code fence; that is Direction B.

---

# Direction B — apply the answers

## STEP B1 — Parse and check

The block is YAML with a `# SDLC-KB-VALIDATION-ANSWERS v1` header. For each answer:

- Its `id` must exist in the registry. **An id that is absent has already been answered
  by someone else** — see "Two people, one question" below. An id that has never existed
  means an edited or hand-written block: say so and skip it, never guess which question
  was meant.
- `decision` is `accept`, `correct` or `defer`.
- `accept` carries the proposed answer as `answer`; a `note` alongside it is an
  amendment and must be honoured, not dropped.
- `correct` carries the reviewer's own `answer`, which wins over the proposal.
- `defer` means the question stays open. Leave the KB's `[UNRESOLVED]` marker exactly
  as it is and record the deferral.

Questions absent from the block were not reviewed. Leave them untouched.

### Two people, one question

Answering removes a question from the registry, so the registry *is* the lock. Always
pull the branch fresh (above) before applying, then for any returned id that is no longer
in the registry, find what the earlier reviewer decided in `ANSWER_LOG.md` and compare:

- **Same answer** — nothing to do. Note the corroboration in the log row and move on.
- **Different answer** — do **not** overwrite. Write both into the KB as a
  `[TL-VALIDATED]` disagreement naming each reviewer and date, leave the question in the
  registry so it comes back, and tell the user the two answers conflict and who said what.

Last-writer-wins is never acceptable here. The same applies if a push is rejected because
someone committed while you were applying: pull, re-check every id against the refreshed
registry, and resolve as above before pushing again.

## STEP B2 — Apply to the KB

For each accepted or corrected answer, edit the `kb_doc` file(s) named on the registry
entry:

- Replace the `[UNRESOLVED]` sentence with the decided answer, written as prose in the
  document's existing voice.
- Tag the new statement `[TL-VALIDATED]` and add the date, so a later reader can tell a
  human decision from a source fact.
- Remove the matching bullet from the document's "Open items" section.
- Where an answer establishes a forward requirement, say so plainly and say it is not
  current implementation.

Hard rules:

- **A validated answer never overrides `[SOURCE-VERIFIED]`.** If the reviewer's answer
  contradicts what the code demonstrably does, keep both, record the conflict, and raise
  it with the user. Source wins on what the code does; the reviewer wins on intent,
  ownership and business rules.
- Do not silently reconcile anything the reviewer did not settle.
- No diagrams. Prose only — that is the standing rule for this knowledge base.
- Never write a reviewer's email address or any other contact detail into the KB.

## STEP B3 — Log

Append to `docs/knowledge-base/VALIDATION/ANSWER_LOG.md`: the date,
reviewer (if given), and one row per answer — id, decision, the resulting statement in
brief, and the file changed. The log is the audit trail for why a KB claim reads the way
it does.

Then update the registry: remove entries that are now settled, and leave deferred ones
in place so they come back next time.

## STEP B4 — Commit

Regenerate the form first, so the registry and the form never disagree. Then stage
explicitly — the KB documents, the registry, the answer log, the regenerated form. Never
`git add .`.

Commit and push straight to `feature/devin-sdlc`. No branch, no PR: this is KB
content settled by the person who owns the answer, and the answer log is the audit trail.
If the push is rejected, pull and re-check for concurrent answers as described above — do
not force.

---

## HARD RULES

- Ask only questions whose answers change the knowledge base.
- One question per decision; do not mirror the KB's marker count.
- Every proposed answer must be defensible on accept.
- Source code outranks a reviewer on what the code does, always.
- Deferred and unreviewed questions stay unresolved — no quiet closure.
- KB files only; this skill never edits application code.
