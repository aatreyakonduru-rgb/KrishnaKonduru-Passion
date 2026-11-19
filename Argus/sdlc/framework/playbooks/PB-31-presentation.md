# Playbook: Presentation — Agentic Framework Architecture Walkthrough

`{OWNER}` is resolved per `.devin/rules/session-isolation.md`.

**Playbook ID:** PB-31  
**Paste into:** Devin Cloud → Settings → Playbooks → New Playbook  
**CLI equivalent:** `/presentation` skill (`.devin/skills/presentation/SKILL.md`)  
**When to use:** Showing Argus to a team, a new joiner, or a stakeholder — how playbooks, skills, agents, prompts, rules, gates and the knowledge base connect, and how the SDLC, BSA/PO and KB flows run.

---

## Title
```
Acme Claims: Presentation — Agentic Framework Architecture & Flows
```

## Description
```
Presents the Argus architecture as a flow diagram: the
layering (playbook macro or slash command -> skill -> agent profile,
workflow, templates, rules, prompts -> session state and knowledge base),
the 7-stage SDLC pipeline with its 11 human approval gates and approver
roles, the read-only BSA/PO flow, and knowledge base creation and
irrigation. Read-only: it shows the flows, it does not run them.
```

## Playbook Body

---

You are presenting Argus. This is **read-only**: show and explain the
architecture — never start a pipeline, sign a gate, or run a generator.

---

## STEP 1 — Attach the diagram

Attach this file to your message; it is self-contained and renders inline:
```
sdlc/framework/ARCHITECTURE.html
```

Mermaid source for the same flows, for Bitbucket, Confluence or a slide deck:
```
sdlc/framework/ARCHITECTURE.md
```

---

## STEP 2 — Confirm the numbers before you present them

Run:
```
python3 sdlc/framework/tools/validate_framework.py
```

Quote its output for skills, agents, executable playbooks, gates and prompts. If it disagrees with the
diagram, the validator wins — say the diagram needs regenerating
(`python3 sdlc/framework/tools/gen_catalogue.py`).

---

## STEP 3 — Walk the four sections

1. **The stack** — a `!pb_*` macro or a slash command invokes a **skill**; the skill loads an **agent**
   profile (role, goal, guardrails, allowed skills), a **workflow** procedure, **templates**, **rules**
   and the **prompt** library; output lands in `context/session/{OWNER}/REQ-{id}/` and the **knowledge base**,
   which then feeds the next requirement as input.
2. **SDLC pipeline** — `/intake` → `/research` → `/plan` → `/implement` → `/eval` → `/release` →
   `/kb-refresh`, naming the gate and approver role after each stage. An unsigned gate blocks the next
   stage; `/resume-session` re-enters from `approvals.yaml`.
3. **BSA/PO flow** — `/dashboard`, `/feasibility-check`, `/what-if`, `/intake`, `/po-story-review`, plus the stakeholder read-outs
   (`/explain-capability`, `/migration-status`, `/compliance-view`, `/spec-vs-delivery`). No code, no
   gates signed.
4. **KB creation and irrigation** — registries derived deterministically from source by
   `tools/kbgen/*`; the narrative documents per module generated from the shared prompts in `sdlc/kb/kb-prompts/` via
   `/app-run-pipeline` behind BSA review gates; `/source-staleness-check` and `/kb-refresh` keep both
   true after a deployment, with drift turned into backlog rather than a silent correction.

If the user names a section (`sdlc`, `bsa-po`, `kb`, `architecture`), present only that one.

---

## STEP 4 — Close with the limits

State these plainly; do not let the framework be presented as more than it is:

- Static validation proves the framework loads and is wired, not that every skill has been
  runtime-executed.
- `/db-*` skills and the PowerShell hooks require Snowflake access via Devin Desktop.
- Glue and Lambda ETL documentation requires the sibling repositories.
- Slash commands come from the repository checkout, so a teammate has them only on a branch that
  contains them; playbook macros are org-wide.

---

## HARD RULES

- Never invent a component, flow, count, agent or gate that is not in `ARCHITECTURE.md`.
- Never execute a pipeline, gate, or generator as part of presenting it.
- Never present unverified claims about what has been runtime-tested.
