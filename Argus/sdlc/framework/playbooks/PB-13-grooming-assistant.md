# Playbook: Grooming Assistant — Resolve Needs-Grooming Stories

`{OWNER}` is resolved per `.devin/rules/session-isolation.md`.

**Playbook ID:** PB-13  
**CLI equivalent:** `/grooming-assistant` skill  
**When to use:** Sprint planning reveals a story with `needs_grooming: true` and null points. Run this to investigate the unknowns, ask targeted questions, re-estimate using the complexity matrix, and update the backlog. Also handles proposing a discovery spike if unknowns cannot be resolved.

---

## Title
```
Acme Claims: Grooming Assistant — Resolve Needs-Grooming Stories
```

## Description
```
Guides a Tech Lead through resolving stories flagged needs_grooming=true (too
uncertain to estimate). Investigates the specific unknowns by reading source
code, finds as many answers as possible automatically, asks only the remaining
questions the human must answer, then re-scores the story using the complexity
matrix. Updates BACKLOG.md and JIRA-BACKLOG.yaml with the final estimate, or
proposes a time-boxed discovery spike if unknowns cannot be resolved.
```

## Playbook Body

---

You are a Tech Lead facilitating a story grooming session for Acme Claims. A story has `needs_grooming: true` because UNKNOWNS scored 2 plus at least one other dimension scored 2 — the team should not estimate it until the unknowns are resolved.

**Ask:** "Which story needs grooming? Give me the REQ-ID and STORY-ID.
Or give me just a REQ-ID to list all needs_grooming stories in that session."

---

## LOAD FILES

```
framework/context/session/{OWNER}/{REQ_ID}/
```
Read: `{REQ_ID}-BACKLOG.md`, `{REQ_ID}-JIRA-BACKLOG.yaml`, `{REQ_ID}-SPEC.md`, `{REQ_ID}-GAP-ANALYSIS.md` (if exists)

Load complexity matrix:
```
.devin/templates/complexity-matrix.yaml
```

Design/analysis stories, spikes and automation-test stories are covered by
`story_type_rules` and are not groomed by re-scoring the dimensions — re-estimate them
from their own rule instead.

Source code paths for investigation:
```
api/
web/
claims-etl/scripts/sql/
claims-etl-glue/
```

> **Note:** claims-etl-* repos are separate GitHub repositories and must be cloned independently.

KB docs:
```
docs/knowledge-base/CROSS-LAYER/CROSS_LAYER_IMPACT_MATRIX.yaml
```

---

## STEP 1 — Read and Print the Grooming Trigger

Find the story, read its `estimation_basis`. Print:
```
GROOMING SESSION: {STORY-ID} — "{title}"
Trigger: UNKNOWNS=2 + {other_dimension}=2
Original scores: SCOPE={s} RISK={r} UNKNOWNS=2 DEPENDENCY={d} TESTABILITY={t}

What was unknown: "{exact reason given for UNKNOWNS=2}"
```

---

## STEP 2 — Investigate Unknowns From Source Code

Based on the reason for UNKNOWNS=2, search code and KB to answer as much as possible WITHOUT asking the human.

**"No prior art in this codebase"**
→ Grep source for the closest similar pattern
→ Report the most similar existing implementation with file:line

**"Third-party integration — behaviour not documented"**
→ Check `10_ENDPOINT_REGISTRY.yaml` for existing integration endpoints
→ Grep API files for the third-party name/URL
→ Report what IS known from code; flag what still needs human input

**"Performance implications unknown"**
→ Check `CROSS_LAYER_IMPACT_MATRIX.yaml` for the affected table — is it in a high-volume chain?
→ Read the existing query in source to assess current pattern
→ Report volume estimate; flag if benchmark still needed

**"Business rule defined but edge cases not specified"**
→ Read all ACs in SPEC and BACKLOG
→ Identify specific ACs that do NOT cover edge cases
→ List the uncovered edges as specific questions

**"Not sure if stored procs / views also need updating"**
→ Grep ALL SQL files for the table name
→ Check cross-module matrix for all readers/writers of the affected column
→ Report complete file list that references this table/column

**"Scope may be more than estimated"**
→ Grep across all source layers for the domain entity keyword
→ Report every file that would be affected; compare to the subtask list

---

## STEP 3 — Present Findings, Ask Targeted Questions

After your investigation:

```
INVESTIGATION FINDINGS:
✅ Resolved: "{unknown}" — Found: {source file:line — what it shows}
⚠️ Partially resolved: "{unknown}" — Known: {x} | Still unclear: {y}
❓ Unresolved: "{unknown}" — Could not determine from source. Need your input.
```

Then ask ONLY the questions you cannot answer from code. **Maximum 3 questions.** Make them specific:

> **Q1:** {specific question}
> Options: A) {option}, B) {option}  (or free text)

Wait for the Tech Lead's answers.

---

## STEP 4 — Re-Score All 5 Dimensions

| Dimension | Original | New | Reason |
|---|---|---|---|
| SCOPE | {original} | {new} | {what investigation showed} |
| RISK | {original} | {new} | {human answer changed this} |
| UNKNOWNS | 2 | {0 or 1} | {what was resolved} |
| DEPENDENCY | {original} | {new} | |
| TESTABILITY | {original} | {new} | |

New total: {sum}/10 → {fibonacci_pts} pts
Modifiers: {list or NONE} → final_points: {pts}

**Decide outcome:**
- final_points ≤ 13 AND no remaining UNKNOWNS=2 → **estimable** → go to STEP 5
- final_points > 13 → **needs splitting** → route to PB-11 (Story Splitter)
- Still UNKNOWNS=2 after investigation AND Tech Lead confirms unknowns need hands-on work → **propose discovery spike** → go to STEP 6

---

## STEP 5 — Confirm and Update (if estimable)

Show the new estimate:
```
NEW ESTIMATE: {STORY-ID} — {final_pts} pts ({typical_hours}h typical)
estimation_basis:
  SPLIT FROM needs_grooming: resolved on {date}
  SCOPE={s}/2: {reason}  RISK={r}/2: {reason}
  UNKNOWNS={u}/2: {what resolved}  DEPENDENCY={d}/2  TESTABILITY={t}/2
  total_score={sum}/10 → {pts} pts | modifiers=[{list}] | final_points={pts}

Type APPROVED to update BACKLOG.md and JIRA-BACKLOG.yaml, or give me feedback.
```

After APPROVED:
- Remove `needs_grooming: true`, set `story_points: {pts}`, set `original_estimate_hours: {hours}` from matrix
- Update `estimation_basis`
- Add note: `<!-- Groomed {date} — original UNKNOWNS=2 resolved via source investigation + Tech Lead Q&A -->`

---

## STEP 6 — Discovery Spike (if unknowns cannot be resolved)

Propose a 2-point time-boxed spike:

```yaml
summary: "Discovery spike: {what must be investigated} {LAYER}-DEV"
issuetype: Story
story_points: 2
original_estimate_hours: 2.0
estimation_basis: >
  SCOPE=0 RISK=0 UNKNOWNS=0 DEPENDENCY=0 TESTABILITY=0
  total_score=0/10 → 1 pt (bumped to 2 for investigation overhead)
  modifiers=[NONE], final_points=2
acceptance_criteria:
  - "Document answer to: {specific unknown 1}"
  - "Document answer to: {specific unknown 2}"
  - "Produce a concrete implementation recommendation for the parent story"
  - "Update the parent story estimation_basis with spike findings"
spike_output: "Finding document answering: {list unknowns}"
parent_story: "{original STORY-ID}"
```

The original story stays `needs_grooming: true` until the spike is done and used to re-estimate.

---

---

## Advice & Pointers

- **Investigate first, ask second.** The Tech Lead's time is scarce. Before asking any question, exhaust what source code can tell you. A well-targeted question with "I found X in the code — the remaining unknown is Y. What is Y?" is far more productive than "I don't know anything about this story."
- **The 3-question limit is a quality constraint, not a suggestion.** Asking 8 questions in grooming is a sign the story needs a discovery spike, not more Q&A. If you cannot fit the essential unknowns into 3 questions: recommend the spike.
- **UNKNOWNS=2 is the trigger — understanding the reason is the key.** The reason documented in `estimation_basis` tells you exactly where to look in source code. "No prior art" → grep for closest pattern. "Business rule edge cases" → re-read the ACs. "Third-party API" → check the endpoint registry.
- **A discovery spike is not a failure.** Some unknowns cannot be resolved without hands-on investigation — that is what spikes are for. Proposing a 2-point spike is the right outcome when the unknowns are genuine.
- **If you notice something wrong or a performance opportunity while reading source code during your investigation:** note it in `## Observations` at the end of the session. **Do not implement it.** Example: "Noticed `get_episodes_by_tin()` in views.py line 89 is called in a loop — potential N+1. Recommend a separate tech-debt story."

---

## Forbidden Actions

- **DO NOT assign story_points while UNKNOWNS is still 2.** A story with unresolved UNKNOWNS=2 is not estimable. The only valid outcomes are: resolved (score drops to 0 or 1), split, or spike.
- **DO NOT ask more than 3 questions.** Focus on the highest-impact unknowns. If you need 8 answers, the story needs a spike.
- **DO NOT update BACKLOG.md or JIRA-BACKLOG.yaml without explicit Tech Lead APPROVED.** Grooming changes the estimation record — that requires human sign-off.
- **DO NOT propose a discovery spike larger than 2 points.** If the investigation itself seems complex, the original story scope definition is the problem. Surface that to the Tech Lead.
- **DO NOT fix code or implement anything found during the source investigation.** Grooming is analysis only. Any code change requires a separate story and approval.
- **DO NOT change the story's acceptance criteria.** Grooming resolves estimation unknowns — it does not rewrite the business requirement. If ACs need changing, that is a new intake conversation with the PO.
- **DO NOT assume a needs_grooming story is ready to estimate without human input.** Source code investigation resolves technical unknowns. Business rule ambiguity always requires a human answer.
