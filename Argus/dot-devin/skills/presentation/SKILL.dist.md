---
name: presentation
description: Show the Acme Claims agentic architecture as a presentable flow diagram — how playbooks, skills, agents, prompts, rules, gates and the knowledge base connect, and the SDLC, BSA/PO and KB creation-and-refresh flows. Use when the user types /presentation, asks for the architecture or flow diagram, asks how it all fits together, or needs something to show a team or stakeholder. "/presentation deck" opens the Beyond the ticket exec deck full screen in Chrome on the Devin machine instead.
argument-hint: "[optional: deck | architecture | sdlc | bsa-po | kb | all]"
visibility: internal
triggers:
  - user
  - model
invocations:
  - /presentation
  - show me the architecture
  - show the flow diagram
  - how does it all connect
  - present the framework
  - open my presentation
  - run my presentation
allowed-tools:
  - read
  - glob
  - grep
---

# /presentation — Show the architecture flow diagram

Read-only. Deliver the diagram; do not run any of the flows it depicts.

## `deck` — open the Beyond the ticket deck

With the argument `deck` (or "open / run my presentation"), skip the steps below and open the deck
for presenting:

1. Open the deck named by `docs.presentation` in `.devin/rules/sdlc-profile.json` (today
   `docs/knowledge-base/DOCUMENTATION/Presentations/beyond-the-ticket-exec.html`)
   from this checkout in the Chrome on the Devin machine, as a `file://` URL. Reuse the tab if the
   deck is already open.
2. Click the slide-1 tab ("1 · Premise"), click an empty part of the page, then press F11 for full
   screen.
3. Check Argus answers: `curl -s -m 3 -o /dev/null -w '%{http_code}' http://127.0.0.1:8787/api/config`
   returns `200`. If it doesn't, say the slide 5 `/dashboard` and `/argus` buttons won't work
   until Argus is running (`/argus`, or Argus desktop icon on a PC).
4. Tell the presenter to use the Desktop tab. The arrow keys change slides, F11 leaves full screen,
   and a live page from slide 5 opens in a new tab. The tab bar is hidden in full screen, so Ctrl+W
   on the live page returns to the deck.

The live buttons go to Argus at `http://127.0.0.1:8787`: `/argus` opens its home page and
`/dashboard` opens `/?open=dashboard`, which builds the dashboard for whoever Argus opened as.
They work wherever Argus is running, on the Devin machine or on a PC started from the desktop
icon. Without it, a copy of the deck still opens the two LOE reports.

## STEP 1 — Attach the rendered diagram

`sdlc/framework/ARCHITECTURE.html` is self-contained (no CDN, no JS) and renders inline when
attached to a message. Attach that file, without rewriting it.

Mermaid source for the same flows, for Bitbucket/Confluence or a slide deck, is
`sdlc/framework/ARCHITECTURE.md`. Paste the relevant fenced block if the user wants it in
their own document rather than as a file.

## STEP 2 — Narrate the section asked for

No argument, or `all` — walk the four sections in order, one or two sentences each:

1. **The stack** — a playbook macro or a slash command invokes a **skill**; the skill loads an **agent**
   profile, a **workflow** procedure, **templates**, **rules** and the **prompt** library; output goes to
   the session directory and the **knowledge base**, which then feeds the next requirement as input.
2. **SDLC pipeline** — `/intake` → `/research` → `/plan` → `/implement` → `/eval` → `/release` →
   `/kb-refresh`, with the 11 gates and the role that signs each one. An unsigned gate blocks the stage
   after it.
3. **BSA/PO flow** — read-only: dashboard, feasibility, what-if, intake from notes or a ticket, story
   review. Writes no code and signs no gate.
4. **KB creation and irrigation** — registries are derived deterministically from source by
   `tools/kbgen/*`; the 12 narrative documents per module come from the shared prompts in
   `sdlc/kb/kb-prompts/` via `/app-run-pipeline` behind BSA review gates, built into a staging
   folder and compared with the live KB (`/kb-build`, `/kb-compare`) before anything is replaced; `/source-staleness-check` plus `/kb-refresh` keep both
   true after a deployment, and drift becomes backlog rather than a silent fix.

With `sdlc`, `bsa-po`, `kb` or `architecture` — narrate only that section and say which part of the
diagram to look at.

## STEP 3 — State the counts and the caveats

Counts come from `python3 sdlc/framework/tools/validate_framework.py` (skills, agents,
executable playbooks, gates, prompts) — quote its output rather than the numbers baked into the
diagram if the two disagree, and say the diagram needs regenerating.

Always close with the limits, so nobody presents this as more than it is:

- Static validation proves the framework loads and is wired, not that every skill has been
  runtime-executed.
- `/db-*` skills and the PowerShell hooks need Snowflake via Devin Desktop.
- Glue and Lambda ETL documentation needs the sibling repositories.
- Slash commands come from the checkout, so a teammate has them only on a branch that contains them;
  playbook macros are org-wide.

## HARD RULES

- Never invent a component, flow, count or gate that is not in `ARCHITECTURE.md`.
- Never execute a pipeline, gate or generator as part of presenting it.
- If the diagram contradicts `CATALOGUE.md` or the validator, the validator wins — say so.
