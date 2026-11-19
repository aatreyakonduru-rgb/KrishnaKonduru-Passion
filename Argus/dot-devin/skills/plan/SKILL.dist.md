---
name: plan
description: >
  SDLC Stage 4 — Change Routing, Insertion Point Mapping, Coding Pattern Selection.
  Orchestrates the full planning pipeline for one implementation story: loads the
  approved backlog, runs a staleness check on relevant KB docs, builds the routing
  map (which files/layers change and in what order), locates exact insertion points
  by reading actual source files (with real line numbers), selects coding patterns,
  and presents the unsigned SDLC_04_ROUTING_APPROVAL block for Tech Lead sign-off.
  Invoke with: /plan REQ-{id} STORY-{n}
  Source agent: .devin/agents/plan.agent.yaml
argument-hint: "<REQ-ID> <STORY-ID>  e.g. REQ-TIN-001 STORY-003"
visibility: internal
triggers:
  - user
  - model
subagent: true
allowed-tools:
  - read
  - write
  - edit
  - grep
  - glob
---

# Skill: Plan Orchestrator (SDLC Stage 4)

Background reading: `sdlc/framework/workflows/plan.md` (the longer stage procedure; where it and this skill differ, this skill is the one to follow).

You are a **Technical Architect** producing the implementation plan for one
Acme Claims story. Your job is to produce a verified routing map and
exact insertion-point file — no guessing, no fabricated line numbers.

Use `.devin/rules/gate-presentation.md` for SDLC_04 presentation, approval
options, signer identity, role checks, and approval recording.

Source agent spec:
```
.devin/agents/plan.agent.yaml
```
Child steps — executed inline by this skill, they are not separate skill files:
```
change-routing-map  insertion-locator  ```

---

## INPUTS

Parse arguments: `REQ_ID` and `STORY_ID`.
If not provided, ask: "Which requirement and story? (e.g. REQ-TIN-001 STORY-003)"

---

## SESSION DIRECTORY

```
sdlc/framework/context/session/{OWNER}/{REQ_ID}/
`{OWNER}` is resolved per `.devin/rules/session-isolation.md`.
```

## SOURCE CODE (always read actual files — never fabricate paths or line numbers)

```
api/
web/
../claims-etl/scripts/
../claims-etl-glue/
../claims-etl-lambda/
```

## KB CONTEXT

```
docs/knowledge-base/CROSS-LAYER/CROSS_LAYER_IMPACT_MATRIX.yaml
docs/knowledge-base/MODULES/claims-web/api/10_ENDPOINT_REGISTRY.yaml
docs/knowledge-base/MODULES/claims-web/web/12_COMPONENT_REGISTRY.yaml
docs/knowledge-base/CROSS-LAYER/ACME_ONTOLOGY.yaml   (through tools/ontology_lookup.py only)
```

Draft the routing map from the ontology, then confirm every row in the code:
`python3 sdlc/framework/tools/ontology_lookup.py context <screen or endpoint>` for the screen → endpoint → handler file → table
path, and `impact <table>` for the jobs that read or write those tables and the systems
downstream. Each ontology row in the routing map keeps its source; a row the code does not
confirm is dropped and noted as KB drift.

Then walk the link graph (`CROSS-LAYER/ACME_LINK_GRAPH.yaml`) from each table, endpoint, screen and
file in the routing map: `python3 sdlc/framework/tools/ontology_lookup.py walk <item> --hops 2`.
It lists the screens, jobs, test files and earlier stories linked to it, each with the file:line, KB
entry or commit that proves the link. Add what the routing map missed, or say why it is out of scope.
Before relying on those links, `ontology_lookup.py drift --item <item>` re-reads the cited lines;
a `stale` link is confirmed in the code or dropped. Print `[SDLC] graph walk <item> — …` and
`[SDLC] drift ACME_LINK_GRAPH.yaml — …` lines (`.devin/rules/workbench-trace.md`).

---

## STEP 0 — Gate Check

Read `{REQ_ID}-BACKLOG.md`. Confirm:
- `SDLC_03_BACKLOG_APPROVAL` is **signed** (PO)
- `SDLC_03a_STORY_ESTIMATION_REVIEW` is **signed** (Tech Lead)
- `{STORY_ID}` exists in the backlog and has `needs_split: false` and `needs_grooming: false`

If any check fails: STOP with specific reason.

Read `{REQ_ID}-JIRA-BACKLOG.yaml`. Extract the target story's:
- `summary`, `story_points`, `original_estimate_hours`
- `subtasks` list (with `source_file` citations from subtask-generator)
- `acceptance_criteria`
- `gap_ids` or `estimation_basis`

---

## STEP 1 — Routing Map

**Trace lines (Argus):** print `[SDLC] kb <path> — loaded: <why>` / `skipped: <why>`, `[SDLC] rule <path> — loaded|deferred: <why>`, `[SDLC] route …`, `[SDLC] chain DC-… — …` and `[SDLC] decision … — …` as each file is opened, skipped or each choice made, per `.devin/rules/workbench-trace.md` — here: the `chain` ids the routing table follows, each KB registry opened, and a `decision` line for every unknown settled by reading code; and one `ontology` line for each `context` run on a screen or endpoint, with the gain (handler file and line found without opening the registries).


Identify all layers this story touches from its subtasks. For each layer:

**DB layer**: what table(s) are affected? Is a new migration needed?
Read the cross-module matrix for these tables to understand:
- Who else writes/reads these tables (don't break them)
- What downstream systems depend on these columns

**API layer**: which endpoints are affected?
Read `views.py`, `serializers.py`, `urls.py` for the relevant app.
Identify: new endpoint? modified response? new validation? changed model?

**UI layer**: which components are affected?
Read the relevant `.tsx` files. Identify: new column in grid? new form field?
new state? new API service call?

**ETL layer**: do any Glue/Lambda scripts need updating?
Check the cross-module matrix writers/readers — if an ETL job writes to
an affected table's column, it must be updated.

**KB layer**: read `kb_drift` in the session `approvals.yaml` and the staleness table in
`{REQ_ID}-GAP-ANALYSIS.md`. Every `doc` listed there, plus any KB artifact this story's
code change will make wrong (registry entries, module docs), is a file in the routing map
with its own insertion point — the same branch, the same PR, reviewed by the Tech Lead at
SDLC_04 and SDLC_05. If research listed a drift and you believe no KB change is needed,
say so as an explicit "KB exception" item in the SDLC_04 gate; it is not silently dropped.
Any new drift found while reading source here is appended to `kb_drift` too.

Build dependency order: DB migration must deploy before API; API before UI; ETL may deploy independently.

Write `{REQ_ID}-{STORY_ID}-ROUTING.md`:

```markdown
# Routing Map: {REQ_ID} — {STORY_ID}
**Story**: {story summary}
**Date**: {today}

## Affected Layers
| Layer | Files | Change Type | Notes |
|---|---|---|---|
| DB | {file_path} | add/modify | {brief description} |
| API | {file_path} | modify | {brief description} |
| UI | {file_path} | modify | {brief description} |
| ETL | {file_path} | modify | {brief description or N/A} |

## Dependency Order (deploy in this sequence)
1. DB migration
2. ETL update (if applicable)
3. API changes
4. UI changes

## Branch Strategy
Branch name: `feature/{REQ_ID}-{STORY_ID}-{brief-slug}`
Base branch: `develop`

## Rollback Plan
{For each layer: how to reverse this specific change}
- DB: reverse migration script V{n}__reverse_{slug}.sql
- API: revert commit / feature flag
- UI: revert commit / feature flag

## Feature Flag Required?
{YES (reason) / NO}

## Cross-Module Impact
{List any other tables, endpoints, or components that this change might affect,
based on the cross-module matrix — including downstream systems (SC/FIN/MRM)}
```

---

## STEP 2 — Insertion Point Location (READ EVERY FILE — no fabricated line numbers)

For each file in the routing map:

**If new file:**
- Confirm the parent directory exists
- Note the new file path and provide a template appropriate to the file type

**If existing file:**
- READ the actual file content
- Identify the exact function, class, or section to modify
- Count lines to find the exact insertion line number
- Extract the code snippet: 5 lines before + 5 lines after the insertion point
- Search the codebase for all callers/importers of this function/component

**STOP if any file cannot be found.** Report: "File {path} not found — cannot produce insertion point."
Never fabricate an alternative path.

Write `insertion-points.yaml`:

```yaml
insertion_points:
  - file_path: "{absolute_path}"
    file_type: new | existing
    change_type: add | modify | delete
    function_name: "{if existing}"
    line_number: {if existing — real number from reading the file}
    code_snippet: |
      # Lines {n-5} to {n+5}
      {exact code extracted from the file}
    dependencies:
      - "{other_file_that_references_this}"
```

---

### Claims the plan relies on

Write `{STORY_ID}-claims.yaml` in the session folder: one claim per fact the routing map or the
insertion points rely on (this table is written here, this endpoint feeds that screen, this job
reads that column), each with its evidence. The forms are `path:line` (add `expect:` with the text
that must be on or near that line), `kb:<path>`, `graph:<node>` or `graph:<from> -<type>-> <to>`,
and `chain:<DC-id>` (format in `sdlc/framework/tools/confidence.py`). Then run
`python3 sdlc/framework/tools/confidence.py claims <session folder>/{STORY_ID}-claims.yaml`
and print the `[SDLC] evidence` line it prints. Fix or drop each unverified claim, or list it in the
SDLC_04 brief as unverified. SDLC_04 shows the count. After `warn_until` in
`.devin/rules/confidence.yaml`, an unverified or missing claims file blocks the gate.

## STEP 3 — Coding Patterns

Search the codebase for the most recent, closest existing implementation of the
same change type (e.g. if adding a column, find the most recent migration;
if adding a serializer field, find the nearest similar serializer).

Document the selected pattern:
```
Coding pattern selected: {brief description}
Reference file: {path:line}
Pattern: {key code snippet to follow}
```

---

## STEP 4 — Gate: SDLC_04 (Tech Lead Routing Approval)

First suggest the story's sub-tasks for Argus's "Add sub-tasks" panel. Read the story's
sub-tasks in Jira (read only), then post `[SDLC] artefact {STORY_ID}-SUBTASK-PLAN.json — ready` with a
```json block:

```json
{"story": "{STORY_ID}", "subtasks": [
  {"key": "", "summary": "DEV- Backend implementation", "hours": 4,
   "description": "console/server.py: _gate_subtasks (line 4120) - send updates as PUT. Tests: test_workbench.py. AC 2, 3.",
   "change": ""},
  {"key": "ACME-12345", "summary": "DEV- Frontend implementation", "hours": 3,
   "description": "...", "change": "estimate 8h -> 3h: only one screen changes (routing map row 4)"}]}
```

`key` is empty for a new sub-task and the existing sub-task key otherwise; `change` says what you
suggest changing on an existing one and why, or is empty. Every description comes from the routing
map, insertion points and claims file: files and functions with line numbers, the change at each,
the tests to add or run, the AC numbers covered. Anything not in those files is not written. Hours
follow the story's complexity-matrix estimate. Nothing is written to Jira here; the developer confirms
at SDLC_04.

Append the artifact reference and an SDLC_04 gate record to
`{REQ_ID}-{STORY_ID}-ROUTING.md`, then present the gate using
`.devin/rules/gate-presentation.md`. Load the canonical criteria from
`.devin/rules/approval-gates.yaml`; do not substitute a skill-specific
approval block.

Tell the user:
```
Plan complete for {STORY_ID}.

Files written:
  {REQ_ID}-{STORY_ID}-ROUTING.md
  insertion-points.yaml

SDLC_04 gate is pending Tech Lead sign-off. Use the explicit Approve, Reject
with reasons, or Approve with notes options defined in the gate rule.

When the Tech Lead approves, run:
  /implement {REQ_ID} {STORY_ID}
```

---

## HARD RULES
- NEVER report a line number without reading the file first
- NEVER include a file path in output without confirming it exists
- NEVER skip the SDLC_03/03a gate check — story must be in an approved backlog
- NEVER proceed to /implement without a signed SDLC_04 routing approval
  recorded using `.devin/rules/gate-presentation.md`
- If a file is not found: STOP and report — do not substitute a different path
- Rollback plan is MANDATORY for every layer that is changed
