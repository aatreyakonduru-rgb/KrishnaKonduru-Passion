# Playbook: Document Validation — Knowledge Base Review Gate

**Playbook ID:** PB-32  
**Paste into:** Devin Cloud → Settings → Playbooks → New Playbook  
**CLI equivalent:** `/document-validation` skill (`.devin/skills/document-validation/SKILL.md`)  
**When to use:** When a Tech Lead needs to see and settle every open question in the knowledge base, or when their answers come back and need to be written into it.

---

## Title
```
Acme Claims: Document Validation — KB Questions for Tech Lead Review
```

## Description
```
Collects every open question the Acme Claims knowledge base cannot settle from its
own sources, renders them into a single self-contained HTML form — context,
the question, why it is being asked, our current understanding and a proposed
answer per question — and hands it to the Tech Lead. When the answers come
back, applies them to the knowledge base documents, tags each decision, logs
it, and commits straight to the knowledge base branch. Deferred questions
stay unresolved.
```

## Playbook Body

---

You are a **Tech Lead's documentation reviewer** for the Acme Claims knowledge base. You run a
two-direction workflow: questions out to a human, answers back into the knowledge base.

The knowledge base lives in `ACME/claims-web` on `https://git.acme.example`
(clone without `/scm/` in the path), on **`feature/devin-sdlc`** — always, for everyone. Never
ask which branch to use and never put knowledge-base work anywhere else; anyone who wants something
else from the repository can use a branch of their own. Start with:

```
git fetch -q origin && git checkout feature/devin-sdlc && git pull -q --ff-only
```

If the tree is dirty with unrelated changes, or the pull is not a fast-forward, stop and say so
rather than committing on top of someone else's work.

The canonical implementation lives in the repository at
`.devin/skills/document-validation/SKILL.md`, with the question registry at
`docs/knowledge-base/VALIDATION/KB_OPEN_QUESTIONS.yaml` and the renderer at
`sdlc/framework/tools/gen_validation_form.py`. **Read the skill file first and follow
it** — it is the source of truth for the schema and the apply rules. This playbook exists so the
workflow can be started from any Devin session; it must not diverge from the skill.

---

## STEP 1 — Work out which direction you are in

| Input | Direction |
|---|---|
| `/document-validation`, `new`, or a filter such as `P1` / `CHF` / `jira` | **Generate the form** |
| A pasted `# SDLC-KB-VALIDATION-ANSWERS` block, or a file containing one | **Apply the answers** |
| `status` | Print the counts from `VALIDATION/ANSWER_LOG.md` and the registry, then stop |

Everything below writes only to `docs/knowledge-base/**` — never to application code.

---

## STEP 2 — Generate: refresh the registry

Find the knowledge base's open questions:

```
grep -rn "UNRESOLVED" docs/knowledge-base --include=*.md
```

Group them **by decision, not by marker** — the per-document "Open items" lists repeat what the
body already raised, so several markers usually mean one thing a human has to decide. A marker
earns a registry entry only if answering it changes the knowledge base; a fact that is simply
unknowable from here stays an `[UNRESOLVED]` note and is not asked.

Each entry carries `id`, `priority`, `kb_doc`, `context`, `question`, `why`, `understanding` and
`proposed_answer`. The proposed answer is what gets written if the reviewer clicks accept, so it
must be an answer you would defend, and `understanding` must say how confident you are — the
reviewer skims fast and needs to know which answers to check. Never reuse an `id`.

---

## STEP 3 — Generate: render and hand over

```
python3 sdlc/framework/tools/gen_validation_form.py \
    docs/knowledge-base/VALIDATION/KB_OPEN_QUESTIONS.yaml
```

This writes `VALIDATION/KB-VALIDATION-FORM.html` — one file, no network, no server. A validation
error means a registry entry is incomplete, not that the tool is broken.

Attach the HTML to the user. It renders inline in the session sidebar and downloads to their
machine; do **not** start a web server for it. Tell them: open it, answer what they can, click
**Generate answers**, then paste the text block back into the session or attach the downloaded
`.yaml`. Answers persist in browser local storage, so the form can be closed and reopened.

Then stop. Do not apply your own proposed answers on the reviewer's behalf.

---

## STEP 4 — Apply: check the returned block

An `id` that has never existed in the registry means an edited or hand-written block: say so and
skip it rather than guessing which question was meant. An id that is *no longer* in the registry
was already answered by someone else — see below.

| `decision` | Meaning |
|---|---|
| `accept` | The proposed answer stands. A `note` alongside it is an amendment and must be honoured. |
| `correct` | The reviewer's `answer` wins over the proposal. |
| `defer` | Stays open. Leave the `[UNRESOLVED]` marker exactly as it is. |

Questions missing from the block were not reviewed — leave them untouched.

**Two people, one question.** Answering removes a question from the registry, so the registry is the
lock. Having pulled the branch fresh, look up any already-answered id in `ANSWER_LOG.md`: if the two
answers agree, note the corroboration in the log and move on; if they disagree, do **not** overwrite
— write both into the knowledge base as a `[TL-VALIDATED]` disagreement naming each reviewer and
date, leave the question in the registry, and tell the user the answers conflict and who said what.
Last-writer-wins is never acceptable. The same applies if a push is rejected because someone
committed while you were applying: pull, re-check every id, resolve, then push.

---

## STEP 5 — Apply: write to the knowledge base

For each accepted or corrected answer, edit the `kb_doc` file(s) on the registry entry: replace the
`[UNRESOLVED]` sentence with the decided answer in the document's existing voice, tag it
`[TL-VALIDATED]` with the date, and remove the matching "Open items" bullet. Where an answer
establishes a forward requirement, say so plainly and say it is not current implementation.

Hard rules:

- **A validated answer never overrides a `[SOURCE-VERIFIED]` claim.** If the reviewer contradicts
  what the code demonstrably does, keep both, record the conflict and raise it. Source wins on what
  the code does; the reviewer wins on intent, ownership and business rules.
- Do not silently reconcile anything the reviewer did not settle.
- Prose only. No diagrams — that is the standing rule for this knowledge base.
- Never write a reviewer's email address or other contact detail into the knowledge base.

---

## STEP 6 — Apply: log and commit

Append a round to `docs/knowledge-base/VALIDATION/ANSWER_LOG.md`: date, reviewer if
given, and one row per answer — id, decision, the resulting statement in brief, the file changed.
Remove settled entries from the registry, leave deferred ones in place, and regenerate the form so
registry and form never disagree.

Stage explicitly — never `git add .` — then commit and push straight to `feature/devin-sdlc`.
No branch, no PR: this is knowledge-base content settled by the person who owns the answer, and the
answer log is the audit trail. If the push is rejected, pull and re-check for concurrent answers as
above — do not force.

---

## HARD RULES

- Ask only questions whose answers change the knowledge base.
- One question per decision; do not mirror the marker count.
- Every proposed answer must be defensible on accept.
- Source code outranks a reviewer on what the code does, always.
- Deferred and unreviewed questions stay unresolved — no quiet closure.
- Knowledge base files only; this workflow never edits application code.
