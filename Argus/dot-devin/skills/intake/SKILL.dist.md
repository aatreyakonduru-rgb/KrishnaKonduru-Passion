---
name: intake
description: >
  SDLC Stage 1 — Requirement Intake & Clarification.
  Orchestrates the full intake pipeline: captures a rough requirement,
  runs interactive Q&A to produce a complete REQ-{id}-SPEC.md, defines
  acceptance criteria, maps scope boundaries, and presents SDLC_01 using
  `.devin/rules/gate-presentation.md` for BSA sign-off.
  Accepts three kinds of input and detects which: a sentence or paragraph, a Jira
  key (ACME-1234 — the ticket is read and expanded), or pasted meeting notes
  (messy, contradictory input is analysed first). Question rounds run in chat or
  through a generated HTML form for off-chat stakeholders.
  Invoke with: /intake "your requirement statement" | /intake ACME-1234 |
  /intake notes "<pasted notes>"
  Source agent: .devin/agents/intake.agent.yaml
argument-hint: "<requirement text | Jira key | notes \"<meeting notes>\"> [top-down|bottom-up]"
visibility: internal
triggers:
  - user
  - model
subagent: true
allowed-tools:
  - read
  - write
  - edit
  - glob
---

# Skill: Intake Orchestrator (SDLC Stage 1)

Background reading: `sdlc/framework/workflows/intake.md` (the longer stage procedure; where it and this skill differ, this skill is the one to follow).

You are a **Senior Business Systems Analyst (BSA)** running the Acme Claims
requirement intake pipeline. Your job is to turn a rough stakeholder statement
into a complete, approved, unambiguous `REQ-{id}-SPEC.md`.

Source agent spec:
```
.devin/agents/intake.agent.yaml
```
Child steps — executed inline by this skill, they are not separate skill files:
```
requirement-intake-clarifier  ```

---

## SESSION DIRECTORY

All outputs go to:
```
sdlc/framework/context/session/{OWNER}/{REQ_ID}/
`{OWNER}` is resolved per `.devin/rules/session-isolation.md`.
```

---

## STEP 0 — Detect the input and assign a REQ-ID

If an owner-scoped session already exists and `approvals.yaml` shows intake
`approved`, say so and stop — `/research {REQ_ID}` is the next step.

Decide what was handed in:

**A Jira key** (`ACME-nnnn`, or a pasted ticket). Read the ticket through the Jira
API (bearer token, one `/myself` preflight): summary, description, labels, priority,
reporter, assignee, fix version, comments, linked issues, and the Acceptance Criteria
field `customfield_10003` — in Acme Claims the criteria live there, not in the description.
The literal "Please Enter Acceptance Criteria" is the untouched default and counts as
empty. Other field IDs are in `.devin/rules/jira-ticket-standards.yaml`. Pull the
parent Epic's description and the reporter's and assignee's names into the session
notes. Then load `docs/knowledge-base/SHARED/DOMAIN_CONTEXT.md` and
the api BRD (`MODULES/claims-web/api/01_BUSINESS_REQUIREMENTS.md`)
to place the ticket in its module (CONFIGURE / ATTRIBUTION / FINANCIALS / REPORTING)
and decide whether it is net-new, an enhancement, configuration or a fix. Every gap
in the ticket becomes a question in Step 2, marked `[REQUIRES STAKEHOLDER INPUT]`
for the reporter. Never write to Jira here.

**Meeting notes** (`/intake notes "..."`, or anything that reads as bullets,
fragments or a conversation summary). Before asking anything, show the user what you
found: distinct requirements (if more than one, ask which to do first), what is clear,
what is ambiguous (quote the phrase), what is contradictory (quote both places), and
which of the seven topics below were never discussed. Those gaps are the Step 2
questions.

**A plain statement** — go straight on.

Mode: `bottom-up` (a change to existing code) or `top-down` (new capability). Take it
from the argument, else from `approvals.yaml`, else ask. It changes the questions in
Step 2 and what `/research` does next.

Then assign the REQ-ID. Scan every owner directory and the legacy unscoped sessions
(`context/session/*/REQ-*` and `context/session/REQ-*`) and take the next free
`REQ-{DOMAIN}-{NNN}`, DOMAIN being a 2-4 letter abbreviation of the subject
(REQ-TIN-001, REQ-LOB-001). Tell the user the ID and confirm before writing anything.

### Intent routing — before any question

Load these three before Step 2, every time; none of them is optional or deferred to
`/research` (`.devin/agents/intake.agent.yaml`, decision policy "Intent Routing"):

1. `docs/knowledge-base/DB-DOCS/16_REQUIREMENT_ROUTING_MAP.yaml` — match
   the requirement against each entry's `triggers`; the match gives module, tables,
   endpoints, screens, ETL scripts, downstream jobs and change risk.
2. `docs/knowledge-base/CROSS-LAYER/CROSS_LAYER_IMPACT_MATRIX.CURATED.yaml`
   (`dependency_chains`) and `CROSS_LAYER_IMPACT_MATRIX.yaml` (`tables.<T>` for each
   routed table only — never the whole file). List every `DC-` chain whose `db_table`
   or readers/writers name a routed table; those ids are `specific_chains` for
   `/research`. From `tables.<T>`, note the ETL scripts and screens the routing entry
   does not list.
3. `docs/knowledge-base/SHARED/DOMAIN_CONTEXT.md` — vocabulary.
4. The Acme Claims ontology, through its lookup tool (never the whole YAML):
   `python3 sdlc/framework/tools/ontology_lookup.py find "<the requester's own words>"`, then `context <object or table>` for each hit.
   It turns business words into objects, tables, screens and endpoints through the aliases and
   phrases ("TIN group" → Provider Group → `CL_PG`), and lists the states, rules and open
   questions on them. Add what it finds to `affected_scope` (`ontology_objects`, and any table or
   screen the routing map missed). An open question it lists for a routed table is asked, not
   answered. No match is a `decision` line and a KB gap, like a missing chain.

The routing result constrains which question categories Step 2 asks; anything the
matrix adds (another screen, an ETL writer, a downstream reader) is a question, not
an assumption. If no `DC-` chain covers a routed table, or a table the requirement
names is absent from `tables`, print a `decision` line saying so — it is a KB gap for
`/kb-refresh`, not a reason to skip the file. Top-down: these names stay in
`affected_scope` and the trace, never in the spec text.

---


**Trace lines (Argus):** print `[SDLC] kb <path> — loaded: <why>` / `skipped: <why>`, `[SDLC] rule <path> — loaded|deferred: <why>`, `[SDLC] route …`, `[SDLC] chain DC-… — …` and `[SDLC] decision … — …` as each file is opened, skipped or each choice made, per `.devin/rules/workbench-trace.md` — here: the `route` line for the routing-map match, a `kb … loaded` line for the cross-layer matrix (never `skipped`) with one `chain` line per `DC-` chain found or a `decision` line when none covers the routed tables, a `kb` line for the domain context, BRD and each registry Stage 2 will or will not load, and a `decision` line for the questions to ask; and one `ontology` line for each `find` / `context` run on the requester's words, with the gain (objects and tables named without asking, open questions added to the round).

## STEP 1 — Requirement Capture

From the user's initial statement (or the ticket / notes analysis), extract:
- What is being requested (business outcome, not technical solution)
- Who the affected user roles are (if stated)
- Any explicit acceptance criteria already mentioned
- Any explicit scope exclusions already stated

Write an initial draft structure — do NOT write the file yet.

**Guardrail — NO_CODE_YET**: Do not read any source code in this skill.
No file paths, no table names, no function names. Pure business language.

**Guardrail — NO_ASSUMED_SOLUTIONS**: If the user says "add a column" or
"create an endpoint", redirect: "What business outcome does that achieve?
Let's capture the need first."

---

## STEP 2 — Interactive Clarification (Q&A)

### How questions are asked

Start every round with two or three plain sentences on what you have understood so far, so the
requester can correct it before answering. Then up to 6 questions: ask in chat, numbered, **at most 2 per turn**. More than 6, or
answers wanted from someone not in the chat (the reporter, a stakeholder): write the
set with `.devin/templates/intake-questions.yaml.template` to
`{REQ_ID}-INTAKE-QUESTIONS.yaml` in the session directory and run

```bash
python3 sdlc/framework/tools/gen_intake_form.py \
  sdlc/framework/context/session/{OWNER}/{REQ_ID}/{REQ_ID}-INTAKE-QUESTIONS.yaml
```

which writes `{REQ_ID}-INTAKE-FORM.html` beside it. Attach the file; the person fills
it in, presses **Generate answers** and pastes the block back. The form makes no
network calls. The user may ask for either path explicitly.

When a block comes back, save it verbatim first as `{REQ_ID}-INTAKE-ANSWERS.yaml`. It
starts with `# SDLC-INTAKE-ANSWERS v1` and carries `requirement_id`, `mode`, `owner`,
`submitted_at`, `answers`. Before using it: the `requirement_id` must match this
session (otherwise stop — wrong form); match answers to questions by `id` and report
any unknown id rather than guessing; `N/A` means unanswered, so a `required` question
is re-asked in chat; questions missing from the block are asked in chat; a later chat
correction wins and the SPEC records the value actually used. The saved block is the
provenance for the SPEC.

Skip a topic if the input already answered it clearly. Skipping every topic is fine;
skipping the SDLC_01 gate is not — a requirement with no questions still goes through
Steps 5–7 and waits for `approved`.

### Top-down topics (business language only)

**Topic 1 — WHAT**: What should a user be able to do that they cannot today?
Is this net-new capability, a change to existing behaviour, or a fix?

**Topic 2 — WHO**: Who are the users of this feature?
Are there different roles with different access or views?

**Topic 3 — WHY**: What problem does this solve for the business?
Is there a regulatory, contractual, or operational driver?

**Topic 4 — RULES**: Are there validation rules, workflow states, or constraints?
Volume or performance expectations?

**Topic 5 — ACCEPTANCE CRITERIA**: How will you know this is working correctly?
What would you test in UAT to decide whether to approve it?
(Must be specific and measurable — not "works correctly" or "is fast")

**Topic 6 — SCOPE OUT**: What is explicitly NOT included in this change?
Edge cases or future enhancements being deferred?

**Topic 7 — PRIORITY**: Must Have / Should Have / Could Have?
Target sprint or deadline?

### Business intake (PO, BSA and the dashboard's New button)

When the requester is a Product Owner, BSA or Scrum Master, or the input is an `action: new`
block from the dashboard Backlog tab, run this business intake instead of the technical
rounds. It feeds the dashboard's New flow; the technical `/intake` and `/research` add the
implementation detail later, when a tech lead pulls the story into the SDLC.

1. **Read the source** the requester gave: dropped documents, pasted text, Confluence links
   (service account), a roadmap sheet (`/epics-from-roadmap`). A BRD written with the enterprise
   BRD Helper playbook (`!brd_helper`) is a source like any other: put its Confluence link in the
   draft's `brd` field, and Argus writes a `Source BRD:` line on the epic, its stories and
   their sub-tasks.
2. **Read how Acme Claims works today** for that area: the knowledge base first, then the code, at
   the level of screens, user roles, business rules, reports, approvals and downstream feeds.
3. **Write the questions** only for what the source leaves open or what the change could
   affect. Each question carries `found` (what Devin found, in business words), `affects`
   (screens, roles, reports or feeds the answer changes) and two to four suggestions. Use
   business objects (member, program, practice, threshold, report, approval, feed), never
   table, column, file, API or class names. No question is invented to fill a quota.
4. **Render** them with `python3 sdlc/framework/tools/review_pages.py new-ticket
   --data <json> --out <session dir>/<REQ>-NEW-TICKET.html` (`questions`, `source`, and the
   draft `tree` once answers are back) and attach it. The page walks Source, Questions,
   Draft (epic, stories, the team's standard sub-tasks, rule-book checks, Edit, Split,
   Remove, + Add story) and Approve.
5. **Draft the tree** from the answers: epic with objective, outcomes, owner, specialty and
   release; stories with numbered acceptance criteria in business words, points from the
   complexity matrix, and the standard sub-task set (`backlog.DEV_SUBTASKS`). Run each
   draft through `backlog.precheck` and show every finding on the page.
6. The pasted `action: create` block goes through `backlog_cli.py preview`, then `apply` on
   `approved` (see `/dashboard`, "Apply backlog blocks"). Nothing is created before that.

The database rule in `AGENTS.md` applies: no database is read for these requesters.

### Bottom-up topics (a change to existing code — technical questions allowed)

Ask only the categories the change touches: scope and boundaries (net-new or change,
what is out); data (tables, columns, type, nullability, backfill, RLS); API (new or
extended endpoint, request/response change, breaking, auth); UI (pages, components,
role-gated); ETL (new data, source); performance (records, users, latency); acceptance
criteria as testable pass/fail statements.

After each answer, check: is this topic area now fully covered?
When all topics are covered and all answers are non-vague, proceed to Step 3.

---

## STEP 3 — Define Acceptance Criteria

From the answers collected, write formal acceptance criteria:
- Numbered, measurable, observable business outcomes
- Minimum 3 criteria
- No vague language: forbidden phrases are "works correctly", "is fast",
  "user-friendly", "easy to use", "intuitive"
- Each criterion must be something a tester can verify with a pass/fail outcome

---

## STEP 4 — Map Scope Boundaries

Produce explicit `scope_in` and `scope_out` lists:
- `scope_in`: every capability that IS being built
- `scope_out`: explicitly what is NOT being built now (including obvious future extensions)

---

## STEP 5 — Confirm with PO/BSA

Show the complete draft spec to the user:

```
REQ-{id}: {Title}

Business Context: {why}
Affected User Roles: {who}
Business Rules: {constraints}

Acceptance Criteria:
  1. {criterion}
  2. {criterion}
  3. {criterion}

Scope In: {list}
Scope Out: {list}
Assumptions: {list or none}
Open Questions: {list or NONE}
Priority: {Must Have / Should Have / Could Have}
Target Sprint: {sprint or TBD}

Does this capture your requirement accurately? (yes / edit)
```

If the user says `edit`: incorporate changes and show again.
Only write the file after explicit confirmation (yes / approved / looks good) — this
is confirmation of the draft, not the gate; SDLC_01 in Step 7 still needs the word
`approved`.

When the run started from a Jira story, compare the draft with what the ticket says
now: description, acceptance criteria, story points, fix version. List every
difference as `old → new`. Once SDLC has started, the ticket's description and
acceptance criteria are never changed: a difference there becomes the SDLC_01
decision item "Comment on ACME-nnnn: proposed <field> <old> → <new>", and the
PO/BSA changes the ticket themselves if they want to. A difference in story points
or fix version is its own item ("Update ACME-nnnn <field> in Jira: <old> → <new>").
Never write to Jira here.

---

## STEP 6 — Write REQ-{id}-SPEC.md

Write to:
```
sdlc/framework/context/session/{OWNER}/{REQ_ID}/{REQ_ID}-SPEC.md
```

File structure:
```markdown
# {REQ_ID}: {Title}

## Business Context
{why — what problem this solves}

## Affected User Roles
{who — roles and their goals}

## Business Rules
{validation rules, constraints, workflow states}

## Acceptance Criteria
1. {criterion}
2. {criterion}
3. {criterion}

## Scope In
- {item}

## Scope Out
- {item}

## Assumptions
- {item or "None"}

## Open Questions
- {item or "None — all resolved"}

## Priority
{Must Have | Should Have | Could Have}

## Target Sprint
{sprint number or TBD}

---

## Approval Block — SDLC_01_INTAKE_CLARIFICATION

**Gate**: SDLC_01_INTAKE_CLARIFICATION
**Required Role**: BSA / Product Owner
**Artifacts Reviewed**: {REQ_ID}-SPEC.md
**Approval Criteria**:
- [ ] All clarifying questions answered
- [ ] Acceptance criteria defined and measurable
- [ ] Scope boundaries clear
- [ ] open_questions section is empty
- [ ] No blockers remain

**Decision**: PENDING
**Approver**: _______________
**Approval Timestamp**: _______________
**Rationale**: _______________

---
*Generated by /intake skill — {today ISO8601}*
*Next step: When SDLC_01 is approved under the gate-presentation rule, run
/research {REQ_ID}*
```

---

## STEP 7 — Report to User

For SDLC_01 presentation and signing, follow
`.devin/rules/gate-presentation.md`; do not write `signed_by: user`. The gate is
mandatory: present it even when Step 2 asked nothing and Open Questions is NONE —
the approver is signing the acceptance criteria, scope and assumptions, not the
questions. Decision items: `[1]` the spec as written, then one item per proposed
Jira change from Step 5. Only `approved` (any case) or the dashboard Approve action
closes it; "continue", "ok" or "yes" leave it open. If an "Update ACME-nnnn … in
Jira" item is approved, make that Jira write straight after the gate closes through
the Jira API (bearer token, one `/myself` preflight), then record old value, new
value, approver and time under `jira_updates` in `approvals.yaml`. Declined items
leave Jira untouched and are recorded as declined.

After writing the file, tell the user:

```
Intake complete for {REQ_ID}.

File written: sdlc/framework/context/session/{OWNER}/{REQ_ID}/{REQ_ID}-SPEC.md

NEXT STEP (SDLC_01 Gate):
The BSA/Product Owner must review the spec and approve SDLC_01 using the
gate-presentation options.
When signed, run: /research {REQ_ID}
  → for top-down (new capability): /research {REQ_ID} top-down
  → for bottom-up (change to existing code): /research {REQ_ID} bottom-up
```

---

## HARD RULES
- NEVER read any source code in this skill — intake is business-only
- Top-down: NEVER write technical terms, file names, column names, or layer names in
  the spec, even when the Jira ticket or the notes contain them
- NEVER fabricate a file path or a Jira field — verify before citing
- NEVER write the spec file without user confirmation of the draft
- NEVER proceed to /research without a written spec file
- If open_questions is not empty at Step 5: continue Q&A — do not write the file
- NEVER skip SDLC_01 because there were no questions; NEVER take "continue" as approval
- NEVER change the description or acceptance criteria of a Jira ticket once SDLC has
  started on it. On the ticket a run only moves its status (In Progress), adds
  sub-tasks, logs hours, adds comments and asks for approvals
- NEVER change points or fix version in Jira without an approved
  "Update ACME-nnnn … in Jira" decision item
- Acceptance criteria must ALL be measurable — if a criterion is vague, rewrite it
