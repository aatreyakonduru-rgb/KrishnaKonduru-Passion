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
  - model
---

# Skill: KB context build

`$METIS` below is the Mētis plugin folder: the folder two levels above this SKILL.md. `<KB>` is the knowledge-base folder named in the Mētis settings (`<KB>/.metis/kb-profile.yaml`). Follow `$METIS/rules/metis-evidence.md` and `$METIS/rules/metis-writes.md` throughout.

Every KB prompt reads the domain context named by `product.domain_context` in
`<KB>/.metis/kb-profile.yaml`. This skill builds that file from the team's own documents: its
business material, architecture pages, data dictionaries, job schedules and roster. A new team
runs it once, before any other pipeline. If the team puts its context on the keep list (`<KB>/.metis/kb-keep.yaml`), a rebuild writes the new version beside it for review.

This skill runs in the main session. It starts no other skill.

## Step 0 — set up

1. `<stage>` is the `--stage` argument, else `<KB>/_REGEN/<YYYY-MM-DD>`.
2. Run `python3 $METIS/tools/prompts.py lint`. Stop if it reports an error.

## Stages

For each prompt, render it and follow it, writing only the files `outputs` lists:

```bash
python3 $METIS/tools/prompts.py render <file> --stage <stage> --out /tmp/kb-<id>.md
python3 $METIS/tools/prompts.py outputs <file> --stage <stage>
```

| Order | Prompt | File | Writes |
|---|---|---|---|
| 1 | CTX-0A business model | `$METIS/kb-prompts/PROMPT_0A_BUSINESS_MODEL.md` | `CONTEXT_0A_BUSINESS_MODEL.md` |
| 2 | CTX-0B technology and infrastructure | `$METIS/kb-prompts/PROMPT_0B_TECHNOLOGY_STACK.md` | `CONTEXT_0B_TECHNOLOGY_STACK.md` |
| 3 | CTX-0C data architecture | `$METIS/kb-prompts/PROMPT_0C_DATA_ARCHITECTURE.md` | `CONTEXT_0C_DATA_ARCHITECTURE.md` |
| 4 | CTX-0D jobs and orchestration | `$METIS/kb-prompts/PROMPT_0D_JOB_ORCHESTRATION.md` | `CONTEXT_0D_JOB_ORCHESTRATION.md` |
| 5 | CTX-0E team, glossary and sources | `$METIS/kb-prompts/PROMPT_0E_TEAM_GLOSSARY.md` | `CONTEXT_0E_TEAM_GLOSSARY.md` |
| 6 | CTX-00 index and assembly | `$METIS/kb-prompts/PROMPT_0_MODULE_INDEX.md` | `CONTEXT_INDEX.md` and the domain context file |

1 to 5 can run in any order. 6 runs last because it joins them.


## Gate

⛔ Stop here. The product owner must review and approve the assembled context before any pipeline
uses it. Present it as `$METIS/rules/metis-approvals.md` describes. Record who approved and
when. Don't approve on anyone's behalf.

With `--rebuild` (a side-by-side rebuild of a context that already exists, started by
`kb-build`), don't stop: record the gate as `deferred to kb-compare review` and carry on. The
staged files replace nothing until the owner approves the comparison. A first build always stops
here.

## When done

State: "Domain context COMPLETE — awaiting product owner review". List the files written and the
`[?]` items still open. Next step: `kb-compare <stage>`.
