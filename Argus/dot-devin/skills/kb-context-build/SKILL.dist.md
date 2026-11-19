---
name: kb-context-build
description: Build or rebuild the team's domain context from its own documents, by running the shared context prompts CTX-0A to CTX-0E and then CTX-00, which assembles them into the one context file every other prompt reads.
argument-hint: "[--stage <dir>] [--rebuild]"
allowed-tools:
  - read
  - write
  - edit
  - grep
  - glob
  - exec
visibility: internal
triggers:
  - user
  - model
---

# Skill: KB context build

Every KB prompt reads the domain context named by `product.domain_context` in
`.devin/rules/kb-profile.yaml` (ours is `.devin/rules/DOMAIN_CONTEXT.md`, with the KB copy at
`SHARED/DOMAIN_CONTEXT.md`). This skill builds that file from the team's own documents: its
business material, architecture pages, data dictionaries, job schedules and roster. A new team
runs it once, before any other pipeline. We run it with `--rebuild` to see what a rebuild would
change; our context is on the keep list (`.devin/rules/kb-keep.yaml`), so nothing replaces it
without the owner's approval.

This skill runs in the main session. It starts no other skill.

## Step 0 — set up

1. `<stage>` is the `--stage` argument, else `docs/knowledge-base/_REGEN/<YYYY-MM-DD>`.
2. Run `python3 sdlc/kb/tools/prompts.py lint`. Stop if it reports an error.

## Stages

For each prompt, render it and follow it, writing only the files `outputs` lists:

```bash
python3 sdlc/kb/tools/prompts.py render <file> --stage <stage> --out /tmp/kb-<id>.md
python3 sdlc/kb/tools/prompts.py outputs <file> --stage <stage>
```

| Order | Prompt | File | Writes |
|---|---|---|---|
| 1 | CTX-0A business model | `sdlc/kb/kb-prompts/PROMPT_0A_BUSINESS_MODEL.md` | `CONTEXT_0A_BUSINESS_MODEL.md` |
| 2 | CTX-0B technology and infrastructure | `sdlc/kb/kb-prompts/PROMPT_0B_TECHNOLOGY_STACK.md` | `CONTEXT_0B_TECHNOLOGY_STACK.md` |
| 3 | CTX-0C data architecture | `sdlc/kb/kb-prompts/PROMPT_0C_DATA_ARCHITECTURE.md` | `CONTEXT_0C_DATA_ARCHITECTURE.md` |
| 4 | CTX-0D jobs and orchestration | `sdlc/kb/kb-prompts/PROMPT_0D_JOB_ORCHESTRATION.md` | `CONTEXT_0D_JOB_ORCHESTRATION.md` |
| 5 | CTX-0E team, glossary and sources | `sdlc/kb/kb-prompts/PROMPT_0E_TEAM_GLOSSARY.md` | `CONTEXT_0E_TEAM_GLOSSARY.md` |
| 6 | CTX-00 index and assembly | `sdlc/kb/kb-prompts/PROMPT_0_MODULE_INDEX.md` | `CONTEXT_INDEX.md` and the domain context file |

1 to 5 can run in any order. 6 runs last because it joins them.

Our existing context has more than a rebuild can reach from documents alone: the long reference
sections in `SHARED/DOMAIN_CONTEXT_REFERENCE.md` (schemas, lifecycle codes, disaster
recovery, dependency inventories). Treat that file as a source document for CTX-0B to CTX-0E.

## Gate

⛔ Stop here. The product owner must review and approve the assembled context before any pipeline
uses it. Present it as `.devin/rules/gate-presentation.md` describes. Record who approved and
when. Don't approve on anyone's behalf.

With `--rebuild` (a side-by-side rebuild of a context that already exists, started by
`/kb-build`), don't stop: record the gate as `deferred to /kb-compare review` and carry on. The
staged files replace nothing until the owner approves the comparison. A first build always stops
here.

## When done

State: "Domain context COMPLETE — awaiting product owner review". List the files written and the
`[?]` items still open. Next step: `/kb-compare <stage>`.
