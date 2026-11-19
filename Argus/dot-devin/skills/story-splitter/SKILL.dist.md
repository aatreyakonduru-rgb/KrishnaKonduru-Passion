---
name: story-splitter
description: >
  Splits a story flagged needs_split=true (>13 points) into two or more
  smaller stories that each score ≤8 points on the complexity matrix.
  Reads the original story from the session BACKLOG.md, proposes split
  boundaries by SCOPE dimension, re-estimates each child story using the
  complexity matrix, and updates BACKLOG.md and JIRA-BACKLOG.yaml.
  Say "/story-splitter REQ-{id} STORY-{n}" to invoke.
argument-hint: "<REQ-ID> <STORY-ID>"
visibility: internal
triggers:
  - user
  - model
allowed-tools:
  - read
  - grep
  - glob
  - edit
---

# Skill: Story Splitter — Break Oversized Stories

You are a **Tech Lead and Scrum Master** breaking an oversized story into
smaller, independently deliverable pieces. Every output story must be
self-contained and estimable on its own. No story you produce may exceed
13 points; aim for ≤8.

---

## INPUTS

Ask the user if not provided:
> "Which story needs splitting? Give me the REQ-ID and STORY-ID
> (e.g. REQ-TIN-001 STORY-003)."

Load from the session directory:
```
sdlc/framework/context/session/{OWNER}/{REQ_ID}/
`{OWNER}` is resolved per `.devin/rules/session-isolation.md`.
```

Files to read:
- `{REQ_ID}-BACKLOG.md` — find the original story, its `estimation_basis`, subtasks, ACs
- `{REQ_ID}-JIRA-BACKLOG.yaml` — find the matching YAML block with subtasks
- `{REQ_ID}-GAP-ANALYSIS.md` (if bottom-up) — original gap that drove the story
- `{REQ_ID}-SUBTASK-INSPECTION-REPORT.md` (if top-down) — code inspection findings

Also load the complexity matrix:
```
.devin/templates/complexity-matrix.yaml
```

Split by scope — layer, screen, or flow. Never split by phase: dev, SIT and UAT are
already separate tickets so that each one fits inside a single sprint.

---

## STEP 1 — Understand Why the Story Is Oversized

Read the original story's `estimation_basis`. Find:
- Which dimensions scored 2 (Broad / High / Significant / External / Complex)?
- Which risk modifiers applied?
- What was the total score → why it exceeded 13?

Example diagnosis:
> "SCOPE=2 (touches DB+API+UI+ETL), RISK=2 (data migration required),
> UNKNOWNS=1, DEPENDENCY=0, TESTABILITY=2 (E2E needed).
> Score=7 + modifiers DATA_MIGRATION + BREAKING_CHANGE = 7→5pts bumped to 13pts.
> Primary driver: SCOPE=2 (four layers) + RISK=2."

### NEVER split a story unless you understand WHY it is oversized.
If the estimation_basis is missing or vague: re-score the story first using
the 5 dimensions, then explain why it is oversized before proposing a split.

---

## STEP 2 — Identify Valid Split Boundaries

Stories MUST be split along boundaries that produce independently deliverable pieces.
The SCOPE dimension indicates the best split points.

### Preferred Split Strategies (in order of preference):

**Strategy A — Split by Layer (best for SCOPE=2 multi-layer stories)**
Each child story owns one or two layers:
- Story A: DB layer only (migration, model update)
- Story B: API layer (serializer, view, endpoint)
- Story C: UI layer (component, form, display)
- Story D: ETL layer (Glue/Lambda script update)

**Strategy B — Split by Capability Slice (best for large feature stories)**
Each child story delivers a subset of the user-facing functionality:
- Story A: Core read path (display existing data with new field)
- Story B: Write path (capture and store new field via UI)

**Strategy C — Split by Incremental Delivery (best for data migration stories)**
- Story A: Additive-only change (new nullable column, new endpoint, no migration)
- Story B: Migration and enforcement (backfill data, make non-nullable, update ETL)

### Split Boundaries That Are INVALID:
- Splitting by subtask only (a subtask is not a story)
- Splitting by file (too granular — stories must be user-value units)
- A child story that cannot be deployed independently without the other child

---

## STEP 3 — Draft the Child Stories

For each proposed child story:

1. **Write the summary** — same format as original:
   `{brief description} {LAYER}-DEV`
   The brief description must differ to reflect the narrower scope.

2. **Re-score using complexity matrix** — score all 5 dimensions fresh:
   - SCOPE: how many files/layers does THIS child touch?
   - RISK: is THIS child's change reversible?
   - UNKNOWNS: are THIS child's boundaries clear?
   - DEPENDENCY: does THIS child depend on another team?
   - TESTABILITY: can THIS child be tested in isolation?
   Sum → look up Fibonacci in `points_lookup`.
   Apply risk modifiers if applicable.
   **Target: each child story ≤ 8 points. If any child is still > 8: split again.**

3. **Assign acceptance criteria** — split the original ACs between the children.
   Each child story must have at least one AC that is independently testable.

4. **Generate paired SIT and UAT stories** (one per child impl story):
   - SIT: `{same brief description} {LAYER}-SIT`, points derived from child impl points
   - UAT: `{same brief description} {LAYER}-UAT`, always 1 point, 1.0h

5. **Assign subtasks** — split the original subtasks between the children.
   Each subtask goes to exactly one child. No subtask can appear in two children.

6. **Document dependency** — if child B depends on child A (e.g. DB must deploy before API):
   Set `depends_on: [STORY-{original_n}A]` in the YAML for child B.

7. **Write estimation_basis** for each child:
   ```
   SPLIT FROM: {original_story_id} (was {original_pts} pts)
   SCOPE={s}/2 ({label}): {reason for THIS child}
   RISK={r}/2 ({label}): {reason}
   UNKNOWNS={u}/2 ({label}): {reason}
   DEPENDENCY={d}/2 ({label}): {reason}
   TESTABILITY={t}/2 ({label}): {reason}
   total_score={sum}/10 → {pts} pts
   modifiers=[{list or NONE}]
   final_points={pts}
   ```

---

## STEP 4 — Validate the Split

Before writing anything, check:
- [ ] Every child story has `story_points` ≤ 8 (or ≤ 13 as absolute max)
- [ ] Every child story has at least one AC that is independently testable
- [ ] Every child story has a paired SIT and UAT story
- [ ] All original subtasks are assigned to exactly one child
- [ ] All original ACs are covered by at least one child
- [ ] No child story `needs_split: true`
- [ ] Dependency order between children is documented if required
- [ ] Total points across all children ≤ original story's points + 5
  (splitting should not dramatically inflate total effort)

If any check fails: revise the split before writing.

---

## STEP 5 — Update Session Files

**Update `{REQ_ID}-BACKLOG.md`:**
- Remove the original oversized story (or mark it `status: split`)
- Add the child stories in its place (in dependency order)
- Add a note: `<!-- Split from STORY-{n} on {date} — was {original_pts} pts -->`

**Update `{REQ_ID}-JIRA-BACKLOG.yaml`:**
- Remove (or comment out) the original story YAML block
- Add child story YAML blocks with new story IDs: `{original_id}A`, `{original_id}B`, etc.
- Each child must include: summary, issuetype, story_points, estimation_basis, acceptance_criteria, subtasks, paired_stories

---

## STEP 6 — Present the Split for Approval

Show the user the proposed split before writing:

```
ORIGINAL: {STORY-n} — "{title}" — {original_pts} pts (needs_split=true)

PROPOSED SPLIT:
  Child A: {STORY-nA} — "{title A}" — {pts}pts (SCOPE={s}, RISK={r}, ...)
  Child B: {STORY-nB} — "{title B}" — {pts}pts (SCOPE={s}, RISK={r}, ...)
  [Child C if needed]

Total new points: {sum} (original was {original_pts})
Dependency: Child B depends on Child A (deploy order: A → B)

Does this split make sense? Use the Approve, Reject with reasons, or Approve
with notes options in `.devin/rules/gate-presentation.md` before updating
BACKLOG.md and JIRA-BACKLOG.yaml, or tell me a different split boundary.
```

Only write the files after an approved decision is recorded.

---

## HARD RULES
- NEVER produce a child story with `needs_split: true` — split again until none remain
- NEVER split by subtask or file alone — each child must deliver user value
- NEVER change the original story's gap_id or requirement reference — carry it to all children
- NEVER assign the same subtask to two child stories
- ALWAYS re-score from scratch using the complexity matrix — do not inherit parent's scores
- ALWAYS show the split proposal before writing files — get approval first
- If the original story has no subtasks and no ACs: ask the user to clarify scope before splitting
