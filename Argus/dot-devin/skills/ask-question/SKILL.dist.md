---
name: ask-question
description: Route a developer question to a confirmed reviewer through a Jira Question sub-task.
visibility: public
triggers:
  - user
  - model
invocations:
  - /ask "<question>" to <person> [on ACME-1234]
  - ask <person> about <question>
  - ask <person> about this story
allowed-tools:
  - read
  - write
  - edit
  - grep
  - glob
  - exec
---

# /ask — route a question to a reviewer

Use `/ask "<question>" to <person> [on ACME-1234]`, or recognise natural language such as
“ask Resource 5 about X on this story”.

1. Determine the parent story from the explicit Acme Claims key. If no key is given, use the story
   recorded for the current session. Stop if there is no confirmed parent story.
2. Check whether the KB already tracks it: `python3 sdlc/framework/tools/ontology_lookup.py find "<question topic>"` and
   `context <hit>`. If an open question in the ontology covers it, show its id and owner, and
   suggest that owner. The user still picks the person. Print `[SDLC] ontology <command> <term> — <found>; why: <why>; gain: <gain>` for each lookup (`.devin/rules/workbench-trace.md`).
3. Resolve the target through Jira `user/assignable/search?project=ACME&username=<fragment>`.
   Show the resolved display name and ask the user to confirm it before creating anything.
4. After both parent and assignee are confirmed, run:

```
python3 sdlc/framework/tools/question_subtask.py create \
  --parent ACME-1234 --assignee <username> --asker <asker-username> \
  --question "<question>" [--session-url <url>]
```

Tell the user the created sub-task key and that the reviewer will see it in `/dashboard`.

Hard rules:

- Never create a sub-task without a confirmed parent story and confirmed assignee.
- The target must be assignable in Acme Claims; do not use plain `/user/search`.
- Never put PII in the question body. Follow `.devin/rules/pii-handling.md`.
- The question tool owns Jira writes and supports `--dry-run`; do not improvise another payload.
- The flow, the question states, the agreed assumptions and the verified Jira facts are in `sdlc/framework/workflows/question-routing.md`.
