---
name: metis-validate
description: Apply the team's answers from the Mētis VALIDATE_KB file (or answers given in chat) to the knowledge base - record who answered, rebuild the lines that were waiting on each answer, and open a PR.
argument-hint: "[answers file]"
allowed-tools: [read, write, edit, grep, glob, exec]
triggers:
  - model
---

# Apply VALIDATE_KB answers

`$METIS` is the folder two levels above this SKILL.md; `<KB>` holds `.metis/kb-profile.yaml`.

1. Collect answers: from the file given, from `answer` / `answered_by` filled in
   `<KB>/_QUESTIONS/VALIDATE_KB.yaml`, or from the chat (write them to `/tmp/answers.yaml` as a list of
   `id`, `answer`, `answered_by`). An answer without the person's name is not recorded.
2. `python3 $METIS/tools/questions.py answer <KB> <answers file>`, then `python3 $METIS/tools/questions.py check <KB>`.
3. For each answered question, open every file and line listed under `blocks`, replace `[?: Q-xxxx]` with the
   answered fact tagged `[E: answer:Q-xxxx]`. Write only what the answer says.
4. If an answer contradicts a source, do not choose: raise a new P1 question naming both sources.
5. `python3 $METIS/tools/questions.py html <KB>`, `python3 $METIS/tools/verify_kb.py <KB>` (0 problems),
   `python3 $METIS/tools/gen_graph.py <KB>`.
6. Once the KB is locked, the edited files are not written into the KB: stage them with
   `python3 $METIS/tools/kb_gate.py propose <KB> --batch answers-<date> --from <folder with the edited files>`, show the lead
   what is waiting, and certify under the lead's name (`kb_gate.py certify`) when they say so.
7. Branch `metis/<YYYY-MM-DD>-answers`, commit only `<KB>/`, one PR, review from `owners.kb_owner`. Never merge.

To help people answer in chat, `python3 $METIS/tools/questions.py sheet <KB> --role "<their role>"` writes a plain-text
sheet of just their open questions. Show it, take their replies in their own words, and record each with their name.
