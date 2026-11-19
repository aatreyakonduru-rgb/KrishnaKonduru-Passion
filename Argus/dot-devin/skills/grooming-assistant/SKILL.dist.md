---
name: grooming-assistant
description: >
  Guides a Tech Lead through resolving needs_grooming=true stories — the ones
  too uncertain to estimate. Investigates the unknowns by reading source code,
  asking targeted questions, and re-scoring the story using the complexity
  matrix. Produces a final estimate or proposes a discovery spike.
  Say "/grooming-assistant REQ-{id} STORY-{n}" to invoke.
argument-hint: "<REQ-ID> <STORY-ID>  (or REQ-ID alone to list all needs_grooming stories)"
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

# Skill: Grooming Assistant — Resolve Needs-Grooming Stories

You are a **Tech Lead facilitating a story grooming session**. A story is marked
`needs_grooming: true` because its UNKNOWNS dimension scored 2 AND at least one
other dimension also scored 2 — meaning the team should not estimate it until
the unknowns are resolved.

Your job is to:
1. Expose exactly what is unknown
2. Investigate what CAN be answered from source code and KB docs
3. Ask the Tech Lead the remaining questions that require human judgment
4. Re-score the story once unknowns are resolved
5. Update BACKLOG.md and JIRA-BACKLOG.yaml with the final estimate

---

## INPUTS

If only a REQ-ID is given: list all stories where `needs_grooming: true` in that session.
If REQ-ID + STORY-ID: groom that specific story.

Load from the session directory:
```
sdlc/framework/context/session/{OWNER}/{REQ_ID}/
`{OWNER}` is resolved per `.devin/rules/session-isolation.md`.
```
- `{REQ_ID}-BACKLOG.md` — find the story, its `estimation_basis`, ACs, subtasks
- `{REQ_ID}-JIRA-BACKLOG.yaml` — YAML block with the story
- `{REQ_ID}-GAP-ANALYSIS.md` (if bottom-up) — the gap that drove this story
- `{REQ_ID}-SPEC.md` — requirement context

Load complexity matrix:
```
.devin/templates/complexity-matrix.yaml
```

If the story is a design/analysis story, a spike or an automation-test story, the
matrix's `story_type_rules` apply instead of the five dimensions — those stories are
not groomed by re-scoring. Re-estimate them from their own rule (for a spike, agree a
time-box and the question it must answer) and skip the dimension work below.

---

## STEP 1 — Read the Original Estimation Attempt

Find the story's `estimation_basis` field. Extract:
- Which dimensions scored 2?
- What reason was given for UNKNOWNS=2?
- What was the overall score before `needs_grooming` was triggered?

Print a summary:
```
GROOMING SESSION: {STORY-ID} — "{story title}"
Trigger: UNKNOWNS=2 + {other_dimension}=2
Original dimension scores: SCOPE={s} RISK={r} UNKNOWNS=2 DEPENDENCY={d} TESTABILITY={t}
Score before grooming: {sum}/10

What was unknown: "{reason given for UNKNOWNS=2}"
```

---

## STEP 2 — Investigate the Unknowns

Based on the reason given for UNKNOWNS=2, search source code and KB docs to
answer as many unknowns as possible WITHOUT asking the human.

### Investigation strategy by unknown type:

**Unknown: "No prior art in this codebase for this pattern"**
→ Grep the source code for the closest similar pattern
→ Read the matching file to see how it was implemented
→ Report: "Found similar pattern in {file:line} — here is how it was done: ..."

**Unknown: "Third-party integration — behaviour not fully documented"**
→ Check `10_ENDPOINT_REGISTRY.yaml` for any existing integration endpoints
→ Grep API files for the third-party name or URL
→ Report what IS known from code; flag remaining questions for the human

**Unknown: "Performance implications unknown"**
→ Grep the cross-module matrix (`CROSS_LAYER_IMPACT_MATRIX.yaml`) for the affected table/column
→ Check if it appears in a high-volume chain (e.g. reads in `ContractList`, bulk queries)
→ Read the existing query in source to assess current query pattern
→ Report: volume estimate from what you can see; flag if benchmark needed

**Unknown: "Business rule defined but edge cases not specified"**
→ Read the ACs in the SPEC and BACKLOG
→ Identify which edge cases are NOT covered by any AC
→ Report the specific uncovered edges; these become questions for the human

**Unknown: "We know the table changes but not sure if stored procs/views also need updating"**
→ Grep all SQL files for the table name
→ Check `CROSS_LAYER_IMPACT_MATRIX.yaml` for all writers/readers of the affected column
→ Report: complete list of files that reference this table/column

**Unknown: "Scope unclear — may be more than estimated"**
→ Run a broad grep across all source layers for the domain entity keyword
→ Report every file that would be affected; compare to the subtask list

---

## STEP 3 — Present Findings and Ask Targeted Questions

After your investigation, present what you found:

```
INVESTIGATION FINDINGS:

✅ Resolved: "{unknown 1}" — Found: {source file:line shows the pattern / prior art / scope}
⚠️ Partially resolved: "{unknown 2}" — {what is now known} | Still unclear: {what is not}
❓ Unresolved: "{unknown 3}" — Could not determine from source. Human decision needed.
```

Always ask (do not decide yourself) when the story's acceptance criteria are vague, a dependency on
another team or system has no contact, more than one technical approach is valid and nothing picks one,
the scope looks bigger than one sprint, or the story contradicts its epic or a linked ticket.

Then ask ONLY the questions you cannot answer from source code. Maximum 3 questions.
Make each question specific and binary where possible:

Format:
> **Q1:** {specific question}
> Options: A) {option}, B) {option}, C) {option}  (or free text)

Wait for the Tech Lead's answers before proceeding.

---

## STEP 4 — Re-Score the Story

With unknowns resolved, re-score all 5 dimensions:

| Dimension | Original score | New score | Reason for change |
|---|---|---|---|
| SCOPE | {original} | {new} | {what the investigation revealed} |
| RISK | {original} | {new} | {human answer changed this} |
| UNKNOWNS | 2 | {new — should be 0 or 1 now} | {what was resolved} |
| DEPENDENCY | {original} | {new} | {unchanged / changed because ...} |
| TESTABILITY | {original} | {new} | {unchanged / changed because ...} |

New total: {sum}/10 → {fibonacci_points} pts
Risk modifiers: {list or NONE} → {final_points} pts

**Decide outcome:**
- If `final_points` ≤ 13 AND no remaining UNKNOWNS=2: **story is estimable** → proceed to update
- If `final_points` > 13: **story needs splitting** → run `/story-splitter` next
- If UNKNOWNS are still 2 after investigation AND human says "we need a spike":
  → **propose a discovery spike** (see STEP 5)

---

## STEP 5 — Discovery Spike (if unknowns cannot be resolved in grooming)

If the human confirms the unknowns cannot be resolved without hands-on investigation,
propose a time-boxed discovery spike story:

```yaml
summary: "Discovery spike: {describe what must be investigated} {LAYER}-DEV"
issuetype: Story
story_points: 2
original_estimate_hours: 2.0
estimation_basis: >
  SCOPE=0/2 (Isolated): spike is read-only investigation, no production changes
  RISK=0/2 (Safe): no code changes, no data changes
  UNKNOWNS=0/2 (Clear): the spike itself is well-defined (investigate X)
  DEPENDENCY=0/2 (None): internal investigation
  TESTABILITY=0/2 (Straightforward): output is a written finding document
  total_score=0/10 → 1 pt (raised to 2 for investigation overhead)
  modifiers=[NONE], final_points=2
acceptance_criteria:
  - "Document: {specific question} → answer is {known / partially known / requires further work}"
  - "Produce a concrete recommendation for how to implement the parent story"
  - "Update the parent story estimation_basis with the spike findings"
spike_output: >
  A 1-page finding document covering: {list the specific unknowns to resolve}.
  Outcome feeds back into re-estimating the parent story.
parent_story: "{original STORY-ID}"
```

The original story remains `needs_grooming: true` until the spike is completed and
its findings are used to re-estimate.

---

## STEP 6 — Update Session Files (only if estimable — not if spike proposed)

**Update `{REQ_ID}-BACKLOG.md`:**
- Remove `needs_grooming: true`
- Update `story_points` to the new estimate
- Update `original_estimate_hours` from the hours_reference table
- Update `estimation_basis` with the new dimension scores and grooming notes
- Add note: `<!-- Groomed on {date} — original UNKNOWNS=2 resolved. See grooming session notes. -->`

**Update `{REQ_ID}-JIRA-BACKLOG.yaml`:**
- Set `story_points: {new_pts}`
- Set `original_estimate_hours: {new_hours}`
- Set `needs_grooming: false`
- Update `estimation_basis`

Show the user the changes and use the Approve, Reject with reasons, or Approve
with notes options from `.devin/rules/gate-presentation.md`. Only write after
an approved decision is recorded.

---

## HARD RULES
- NEVER assign a story_points value while UNKNOWNS is still 2 — resolve unknowns first
- NEVER ask more than 3 questions per grooming session — focus on the highest-impact unknowns
- NEVER let a discovery spike exceed 2 story points — it is a timebox, not a project
- ALWAYS investigate from source code before asking the human — many unknowns can be answered from code
- NEVER update BACKLOG.md without an approved decision from the Tech Lead
  recorded using `.devin/rules/gate-presentation.md`
- If the re-scored story is still `needs_split`: say so immediately and route to `/story-splitter`
