---
name: metis-ask
description: Answer a question or carry out an instruction using only the Mētis knowledge base - "which screens use table X", "what changes if column Z is dropped". Every line cites the KB and is checked; the person can rate the answer. Read only, except when asked to save an answer or raise questions (then via a lead's certification and one PR).
argument-hint: "[your question or instruction]"
allowed-tools: [read, grep, glob, exec, write]
triggers:
  - model
---

# Ask the KB

`$METIS` is the folder two levels above this SKILL.md; `<KB>` holds `.metis/kb-profile.yaml`.
Rules that apply: `$METIS/rules/metis-conversation.md`, `$METIS/rules/metis-evidence.md`, `$METIS/rules/metis-writes.md`.
Read only: nothing in the repo changes in steps 1-5.

## 1. Get the question
- Take the question or instruction from the message. If there is none, ask: "What do you want to know from the KB?"
- If the person also attaches files, use `metis-docs` instead.

## 2. Look for earlier feedback first
```bash
python3 $METIS/tools/feedback.py hints <KB> "<the question>"
```
- It returns approved directions ("look in the batch job, not the API") and earlier corrections for similar questions.
  Read the KB files they point to first. Do not repeat an answer the KB owner has already marked wrong.
- A direction that is not yet approved by a lead is used only for the person who gave it.

## 3. Find the KB files that answer it
- Read through the context pack, not by reading KB files directly. The pack applies the claim-label clearance, the secret
  screen, stale marks and the usage record; reading files yourself skips all four.
  ```bash
  python3 $METIS/tools/context_pack.py <KB> --task "<the question>" --out /tmp/metis-ask/<run>/pack.md --by "<asker>"
  ```
  With the agent tool connection use `metis_context_pack` with `task`. The pack finds the objects the question names, the
  pages the KB search ranks best for it (also pages that do not name the object), and the impact list.
- A pack page taken as `sections` or `headline` lists what it left out. If the answer needs a left-out part, build another
  pack with `--files <that page>` or a bigger `--budget`; do not open the file yourself.
- For "what uses" and "what changes if" questions the pack's impact list is the answer's spine. For a deeper walk, use
  `python3 $METIS/tools/graph_store.py impact <KB> <node>`.
- Only if the pack says "no KB page names these objects" and the search found nothing, say the KB does not cover it
  (step 5). Don't answer from file names, memory or general knowledge.
- The pack's "Not included" lists withheld lines by count only. Never go looking for them in the files.

## 4. Write the answer
- Write it to `/tmp/metis-ask/<YYYY-MM-DD>-<short name>/answer.md`, outside the repo.
- Every line cites the KB file it came from, with the words it relies on:
  `[E: kb:<path> "quoted text"]`, the quote copied exactly from that file, under 20 words.
  The KB line's own source may be added next to it (for example the repo line it cites).
- A point the KB doesn't cover goes under a heading `## Not in the KB`, written as a question. Never fill it in.
- A line that combines KB lines or draws a conclusion the KB does not state starts with `Inferred:` and cites the lines it comes
  from. The UI scores confidence from the answer (100 = one KB line states it; less for each inference or missing part). Never
  write a confidence number yourself.
- Where two KB files disagree, show both with their sources and don't pick one.
- An open question in VALIDATE_KB that bears on the answer is named with `[?: Q-0001]`.

## 5. Check, then show it
- `python3 $METIS/tools/verify_kb.py <KB> --answer /tmp/metis-ask/<run>/answer.md` and fix every problem until it
  shows 0. A line that can't be sourced moves under `## Not in the KB`.
- Note which KB files the answer used (file names only, no question or answer text), so the KB owner can see what is read:
  `python3 $METIS/tools/telemetry.py record <KB> --kind answer --files <each KB file the answer cites> --by "<asker>"`.
- Show the answer in chat. Say how many lines were checked.
- If the KB has nothing for the question, do not stop at "not covered". Say which words you searched, which ones the KB does and
  does not use, the nearest pages, and how to put the question so the KB can answer it. If two readings remain, ask the person
  which they meant (one short question, the readings in the KB's own words). The reply only says where to look; it is never a source.
- If anything is under `Not in the KB`, ask in plain words: "The KB does not cover this. Do you want me to ask the right
  person?" On yes, raise it in one step:
  `python3 $METIS/tools/questions.py raise <KB> "<the question>" --type <type> --by "<asker>" --priority P2`, where the type is
  the kind of question: `business`, `application`, `data`, `etl-batch`, `access` or `security`.
- End every answer with one plain line: "Was this right? You can say so, or tell me what is wrong."

## 6. Feedback: like or dislike
Take the person's reply in their own words.
- Liked it: `python3 $METIS/tools/feedback.py record <KB> --answer /tmp/metis-ask/<run>/answer.md --question "<question>" --by "<name>" --rating up`.
- Disliked it, or said it is wrong: ask, one question at a time, in plain words:
  1. "What is wrong or missing?" (this is the why)
  2. "Do you know the right answer, or should I look somewhere else? If somewhere else, where?"
  Then record it with exactly one of the two:
  - right answer given: `... --rating down --why "<why>" --correct "<the right answer>"`. This raises a question
    for the right lead to confirm, with the KB files the wrong answer used as context. The KB is not changed.
  - direction given: `... --rating down --why "<why>" --redirect "<where to look>"`. It is kept for the asker at once
    and for everyone once a lead approves it (`feedback.py approve`).
  If they give neither, ask again once; without one of the two, the dislike is not recorded as a correction.
- Say plainly what happened: recorded, which lead will see it, and, for a direction, that you will look there now.
  For a direction, redo steps 3-5 with it and show the new answer.
- Leads can ask "what feedback is waiting?": `feedback.py list <KB>`, then approve or decline by name
  (`feedback.py approve <KB> <id> --by "<name>"`, or `feedback.py decline <KB> <id> --by "<name>" --reason "<why>"`). A confirmed correction reaches the KB only through
  `kb_gate.py` certification.

## 7. Only if they asked to save the answer
1. Ask where in the KB it should go (default `<KB>/NOTES/<short name>.md`).
2. Stage it: copy the checked answer to a folder and run `python3 $METIS/tools/kb_gate.py propose <KB> --batch ask-<short name> --from <folder>`
   (before the KB is locked, write it to the file directly on a branch).
3. Tell the lead what is waiting. After certification, `python3 $METIS/tools/build_outputs.py <KB>` (0 problems), branch
   `metis/<YYYY-MM-DD>-ask-<short name>` from `repo.base_branch`, commit only `<KB>/`, open one PR and ask
   `owners.kb_owner` to review it. Never merge.

If they said neither, stop. Nothing is written to the repo.
