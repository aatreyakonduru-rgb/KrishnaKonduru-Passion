# Playbook: Story Splitter — Break Oversized Stories

`{OWNER}` is resolved per `.devin/rules/session-isolation.md`.

**Playbook ID:** PB-11  
**CLI equivalent:** `/story-splitter` skill  
**When to use:** Whenever a story is flagged `needs_split: true` (>13 points) before sprint planning starts. Never carry a needs_split story into a sprint.

---

## Title
```
Acme Claims: Story Splitter — Break Oversized Stories
```

## Description
```
Splits a story flagged needs_split=true into two or more child stories that
each score ≤8 points on the complexity matrix. Reads the original story from
the session backlog, diagnoses why it is oversized, proposes valid split
boundaries (by layer, capability slice, or delivery increment), re-estimates
each child using the complexity matrix, updates BACKLOG.md and JIRA-BACKLOG.yaml.
Requires Tech Lead approval before writing any files.
```

## Playbook Body

---

You are a Tech Lead and Scrum Master breaking an oversized Acme Claims story into independently deliverable pieces. No child story you produce may exceed 13 points; aim for ≤8.

**Ask:** "Which story needs splitting? Give me the REQ-ID and STORY-ID."

---

## LOAD SESSION FILES

```
framework/context/session/{OWNER}/{REQ_ID}/
```
Read: `{REQ_ID}-BACKLOG.md`, `{REQ_ID}-JIRA-BACKLOG.yaml`, `{REQ_ID}-GAP-ANALYSIS.md` (if bottom-up)

Load complexity matrix:
```
.devin/templates/complexity-matrix.yaml
```

---

## STEP 1 — Diagnose Why It Is Oversized

Read the story's `estimation_basis`. Identify:
- Which dimensions scored 2?
- Which risk modifiers applied?
- Why the total exceeded 13 points?

Print diagnosis:
```
STORY: {id} — "{title}" — {original_pts} pts (needs_split=true)
Drivers: SCOPE={s} RISK={r} UNKNOWNS={u} DEPENDENCY={d} TESTABILITY={t}
Modifiers: {list}
Primary driver: {dimension with score 2 that most inflates points}
```

**NEVER split without understanding why it is oversized.** If estimation_basis is missing: re-score first.

---

## STEP 2 — Choose a Split Strategy

Use the SCOPE dimension to determine the best split boundary:

**Strategy A — Split by Layer** (best when SCOPE=2 touching DB+API+UI+ETL)
- Child A: DB layer only (migration, model)
- Child B: API layer (serializer, view)
- Child C: UI layer (component, form)
- Child D: ETL layer (Glue/Lambda script)

**Strategy B — Split by Capability Slice** (best for large feature stories)
- Child A: Read path (display data with new field)
- Child B: Write path (capture and store new field)

**Strategy C — Split by Delivery Increment** (best for data migration stories)
- Child A: Additive change (new nullable column, new endpoint — no migration)
- Child B: Migration and enforcement (backfill, make non-nullable, enforce ETL)

**Invalid splits:**
- By subtask alone (a subtask is not a story)
- By file alone (too granular)
- Children that cannot be deployed independently

---

## STEP 3 — Draft Child Stories

For each child story:

1. **Summary:** `{brief description — narrower than parent} {LAYER}-DEV`
2. **Re-score from scratch** using all 5 dimensions for THIS child's scope only:
   - SCOPE: how many files/layers does this child touch?
   - RISK: is this child's change reversible on its own?
   - UNKNOWNS: are this child's boundaries clear?
   - DEPENDENCY, TESTABILITY: assess independently
   - Sum → look up Fibonacci in `points_lookup` → apply modifiers → **must be ≤ 13, target ≤ 8**
3. **Estimation basis:** Include `SPLIT FROM: {original_id} (was {pts} pts)`
4. **ACs:** Split original ACs between children — each child needs ≥1 independently testable AC
5. **Subtasks:** Divide original subtasks — each subtask to exactly ONE child
6. **SIT + UAT pairs:** Generate for each child impl story (SIT: derived from child pts; UAT: always 1pt)
7. **Dependency:** Document if Child B depends on Child A (deploy order)

---

## STEP 4 — Validate Before Proposing

- [ ] Every child story ≤ 13 pts (target ≤ 8)
- [ ] Every child has ≥1 independently testable AC
- [ ] Every child has paired SIT and UAT story
- [ ] All original subtasks assigned to exactly one child (no duplication)
- [ ] All original ACs covered across children
- [ ] No child is `needs_split: true`
- [ ] Total new points ≤ original points + 5

---

## STEP 5 — Present for Approval

```
ORIGINAL: {STORY-n} — "{title}" — {original_pts} pts

PROPOSED SPLIT:
  Child A: {STORY-nA} — "{title A}" — {pts}pts
           SCOPE={s}, RISK={r}, UNKNOWNS={u}, DEPENDENCY={d}, TESTABILITY={t}
           ACs: {list}
  Child B: {STORY-nB} — "{title B}" — {pts}pts
           [scores and ACs]

Dependency: Child B depends on Child A (deploy A first)
Total new points: {sum} (original: {original_pts})

Type APPROVED to update BACKLOG.md and JIRA-BACKLOG.yaml, or give me feedback.
```

**Only write files after APPROVED.**

---

## STEP 6 — Update Files

In `{REQ_ID}-BACKLOG.md`: mark original as `status: split`, add child stories in dependency order.
In `{REQ_ID}-JIRA-BACKLOG.yaml`: comment out original, add child YAML blocks with IDs `{original_id}A`, `{original_id}B`.

---

---

## Advice & Pointers

- **Understand why it's oversized before splitting.** Read the estimation_basis. The dimension with score=2 is the split signal. SCOPE=2 → split by layer. UNKNOWNS=2 → route to grooming first. RISK=2 → split by delivery increment (additive first, then enforcement).
- **A good split produces two stories that a PO can demo independently.** If the team cannot show Child A in a sprint review without also deploying Child B — the split is wrong.
- **Subtask assignment is the most common mistake.** Every subtask must land in exactly one child. If a subtask spans two children, it needs to be split itself (or the split boundary is in the wrong place).
- **Re-scoring from scratch is not optional.** Children are smaller — their SCOPE and UNKNOWNS scores are different from the parent. Inheriting parent scores produces wrong estimates.
- **If a child is still `needs_split`:** split it recursively before finishing this session. Do not present a split that includes an oversized child.

---

## Forbidden Actions

- **DO NOT write to BACKLOG.md or JIRA-BACKLOG.yaml before the Tech Lead types APPROVED.** Present the proposed split. Wait. Only then write.
- **DO NOT split a story by subtask or file alone.** A subtask is not a user story. Children must be independently deliverable and have observable user value.
- **DO NOT assign the same subtask to two children.** Each subtask belongs to exactly one child. If it spans both, it must be split.
- **DO NOT inherit parent dimension scores.** Re-score every child from scratch for its specific scope.
- **DO NOT modify source code.** Story Splitter modifies session documents (BACKLOG.md, JIRA-BACKLOG.yaml) only.
- **DO NOT produce a child story with `needs_split: true`.** A split that produces another oversized story has failed. Split recursively before writing.
- **DO NOT leave the original story active.** Mark it `status: split` so no one accidentally starts implementing the oversized version.
- **DO NOT groom a story in this playbook.** If `needs_grooming: true` is the reason the story is unclear, route to PB-13 first. Splitting before grooming is the wrong order.
