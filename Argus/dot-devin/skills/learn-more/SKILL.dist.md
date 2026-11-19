---
name: learn-more
description: >
  Learn about who you serve: how Devin keeps learning from the Acme Claims team. Each session with a person on the roster ends its
  first reply with one ice-breaker question about their work, or one of the open questions only they
  can answer (the list in docs/knowledge-base/SHARED/learn-more.yaml). Their answer is
  shown as a knowledge-base change and saved only after they type "approved". The same questions are
  the "Learn about who you serve" tab on every dashboard. No Jira tickets are created for this. Say
  "/learn-about-who-you-serve" (or "/learn-more") to answer your questions now, or
  "/learn-about-who-you-serve add <person> <question>" to queue one.
argument-hint: "[nothing] | add <person> \"<question>\" | answer L-001 \"<answer>\""
visibility: internal
triggers:
  - user
  - model
invocations:
  - /learn-about-who-you-serve
  - /learn-more
  - learn about who you serve
  - what do you want to know from me
  - ask me your questions
  - remember how I work
allowed-tools:
  - read
  - grep
  - glob
  - exec
---

# Learn about who you serve (/learn-about-who-you-serve, also /learn-more) — learning from the team, one question at a time

Devin starts every session fresh, so what it learns about the team has to be written down where the
next session reads it. This skill is how that happens. It is a separate process from Jira: Jira holds
stories, this holds what Devin needs to know about the people and the system.

## Where things live

| File | What it holds |
|---|---|
| `docs/knowledge-base/SHARED/learn-more.yaml` | `questions`: open questions, each with the person who can answer (`ask`), and the file the answer changes (`update`). `icebreakers`: short questions about a person's work, by hat. |
| `docs/knowledge-base/SHARED/team-know-how.yaml` | Ice-breaker answers, by person, in their own words. |
| `docs/knowledge-base/SHARED/delivery-teams.yaml` | The delivery-team sheet. Many open questions point here. |

Tool: `python3 sdlc/framework/tools/learn_more.py` (`list`, `next`, `pick`, `answer`, `note`, `add`).
Every command that changes a file is a preview until it is re-run with `--write`.

## HARD RULES

1. **One question per session.** Ask it at the end of the first reply, after the person's own request is answered (`/identify-requester` STEP 4). Never in scheduled or automated sessions. After the question, add one `Tip:` line with a command from their role (`tools/skill_homes.py tip --person "<name>"`), so the commands they have not tried come up in turn.
2. **"skip" is always fine.** Say "No problem" and do not ask again in that session.
3. **Nothing is saved without "approved".** Show exactly what will be written, in the person's words, and wait.
4. **No Jira writes.** No Question sub-tasks, comments or labels for this process.
5. **Only what they said.** Don't add your own reading of their answer. If it is unclear, ask one follow-up.
6. **No personal details** beyond work: no leave reasons, health, family or opinions of colleagues.
7. **One answer can close more than one question.** When an answer is approved, look for the other open
   questions in the knowledge base it also answers: run `learn_more.py related <id>` (open learn-more questions
   and the "Documents waiting on a business answer" lines). Close each one the answer really settles, citing
   the same answer and person, and update the knowledge base files they point at, in the same preview. Leave
   the rest open; don't stretch an answer to fit.

## STEP 1 — Pick the question

Only people on the team roster (`.devin/rules/people.yaml`, synced from the Confluence page "Acme Claims
Team Roster") are asked. `learn_more.py next --person "<roster name>" --role <hat> --jira` returns, in order:

1. the person's first open question (`kind: question`);
2. a question about a story they have In Progress that they have not been asked about (`kind: story`),
   from the `story_questions` for their hat, e.g. "On ACME-18710 (program year filter), which screens,
   APIs or tables does that change touch besides the obvious one?" — so the answer teaches Devin about
   the system as well as the person. `--jira` reads their stories with the team service account; when
   Jira cannot be read, pass `--story "KEY: summary"` from what you already know, or it falls through;
3. an ice breaker for their hat they have not answered (`kind: icebreaker`);

or nothing. Ask it in plain words:

```
One quick question while I'm here, about your work: <question> (say skip if now isn't a good time).
```

## STEP 2 — Save the answer

1. Show the change: for a `question`, the line in `learn-more.yaml` and the edit to the file in `update`;
   for a `story` or `icebreaker`, the entry under their name in `team-know-how.yaml`.
2. When they type "approved":
   - `learn_more.py answer <id> --by "<name>" --text "<answer>" --write`, then edit the `update` file, or
   - `learn_more.py note --person "<name>" --role <hat> --question "<question>" --text "<answer>" [--story <KEY>] --write`.
   A `story` answer that describes the system (screens, APIs, tables, rules) is also offered as an edit
   to the matching module document in the knowledge base, shown in the same preview.
3. Before saving, run `learn_more.py related <id> --text "<answer>"`. For each open question or doc gap the
   answer also settles, add to the same preview: `learn_more.py answer <other id> --by "<name>" --text "<answer>
   (given for <id>)"` and the edit to its `update` file; for a doc gap, replace the `[REQUIRES STAKEHOLDER INPUT]`
   line with the answer and "(<name>, <date>)". Hard rule 7 applies.
4. Commit through the knowledge-base route in `AGENTS.md` (`access_guard.py approve`, then a
   knowledge-base-only PR against `repo.kb_branch`). When the `update` file is outside the knowledge
   base, such as `.devin/rules/sdlc-profile.json`, a PO, BSA or Scrum Master's answer is saved in
   `learn-more.yaml` only (`status: answered`). Tell them the tech lead applies it; the tech lead finds
   these with `learn_more.py list --all` and applies them in a developer PR.

## /learn-more on its own

List their open questions (`learn_more.py list --person "<name>"`) and take them one at a time, the
same way as STEP 2.

## /learn-more add <person> "<question>"

`learn_more.py add --ask "<person>" --question "<question>" --update <file>`. Anyone may queue a
question. Show the new entry and save it after "approved".

## Daily pick

`learn_more.py pick --per-person 2 --write` marks up to two open questions per person as asked today,
so the "Learn about who you serve" tab shows a few at a time and nobody is flooded.

## Related

- `/identify-requester` — asks the question at the start of a session.
- `/dashboard` — "Learn about who you serve" tab.
- `/document-validation` — the tech lead's form for knowledge-base questions found in the documents.
