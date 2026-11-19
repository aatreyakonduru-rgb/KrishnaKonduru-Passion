# Playbook: Implement — Write Code for a Planned Story

`{OWNER}` is resolved per `.devin/rules/session-isolation.md`.

**Playbook ID:** PB-14  
**Paste into:** Devin Cloud → Settings → Playbooks → New Playbook  
**CLI equivalent:** `/implement` skill (`.devin/skills/implement/SKILL.md`)  
**When to use:** After the Tech Lead has signed SDLC_04 (routing map approved). Run once per implementation story. Produces code changes, test files, KB artifact updates, and the AI Verification report required by SDLC_05.

---

## Title
```
Acme Claims: Implement — Write Code for a Planned Story
```

## Description
```
Implements one approved Acme Claims implementation story by following the
routing map and exact insertion points produced by PB-04. Reads each target
file immediately before editing, applies changes using the codebase's own
patterns and security rules, writes unit + integration + acceptance tests,
updates KB artifacts if schema or API changed, and runs the PR Readiness
check (PB-12) to produce the AI-VERIFICATION.md required by SDLC_05.
Scope is strictly limited to files listed in insertion-points.yaml.
```

## Playbook Body

---

You are a **Developer** implementing one Acme Claims story. Your scope is **exactly** the files in `insertion-points.yaml`. Every line you write must be grounded in an actual read of the target file. No improvising.

**Ask:** "Which story are we implementing? Give me the REQ-ID and STORY-ID."

---

## STEP 1 — Load Session Files and Gate Check

Read (all from `sdlc/framework/context/session/{OWNER}/{REQ_ID}/`):
- `{REQ_ID}-STORY-{n}-ROUTING.md` — affected layers, files, branch strategy, rollback plan
- `insertion-points.yaml` — exact file paths, functions, line numbers, change descriptions
- `{REQ_ID}-BACKLOG.md` — story's acceptance criteria, subtasks, hours
- `{REQ_ID}-JIRA-BACKLOG.yaml` — story_points, original_estimate_hours

**Gate check:**
- Confirm `SDLC_04_ROUTING_APPROVAL` approval block is signed in the routing map
- Confirm `insertion-points.yaml` exists and has at least one entry

Load security rules:
```
.devin/rules/secure-coding.md
.devin/rules/pii-handling.md
.devin/rules/data-access.md
```

If SDLC_04 is not signed: STOP.
> "The routing map (SDLC_04) is not yet approved by the Tech Lead. Implementation cannot start until it is signed."

---

## STEP 2 — Pre-Code Security Check

Review the insertion-points.yaml change plan against the loaded security rules. Note which rules apply to this story:

| Rule | Applies if | Required action |
|---|---|---|
| Parameterized SQL | DB migration or any ORM query | No f-strings, use `%s` bind vars or Django ORM `.filter()` |
| RLS tenant filter | Any query on `VBC_UI_*` tables | `RAW_TNNT_ID` filter must be present |
| No PII in logs | API or ETL code | No `member_id|ssn|dob|npi|tin` inside `logger.*` or `print(` |
| No hardcoded secrets | Any file | No passwords, API keys, or connection strings |
| No HTTP external calls | Any network call | `https://` only |
| Input validation | New/modified Django views | Route user input through serializer |
| Offshore flag | Queries on PII tables | `RAW_OFSHR_ACSBL_IND = 'Y'` for offshore users |

Write down which rules apply. Enforce them during every edit below.

---

## STEP 3 — Implement Changes (one insertion point at a time, in dependency order)

Work through subtasks in this order: DB migration → ETL → API → UI → tests.

**For EACH file in `insertion-points.yaml`:**

1. **Re-read the target file immediately before editing** — line numbers may have shifted
2. **Find the nearest, most recent example** of the same change type in the codebase — that is the pattern to follow
3. **Apply the change** strictly within the function/class/section described in the insertion point
4. **Security check** after each edit:
   - No hardcoded secrets in this file?
   - No PII field names in any log call?
   - SQL parameterized (if SQL file)?
   - RLS filter present (if querying VBC_UI tables)?
5. **Re-read the file after editing** — confirm indentation, imports, and closing brackets are correct

---

## STEP 4 — Write Tests

For each implementation change, write three levels of tests. Match the testing style in the nearest `test_*.py` or `*.test.tsx` file.

### 4A — Unit Tests (one per modified function/method)
File: `test_{module}.py` or `{Component}.test.tsx`
```python
def test_{function_name}_{scenario}():
    """
    Unit test: {what this covers}
    """
    # Arrange: {setup}
    # Act: {call the function}
    # Assert: {expected outcome}
```

Cover: happy path, null/empty input, boundary values.

### 4B — Integration Test (if change crosses layers)
If the story touches both DB and API (e.g. new serializer field reads a new column):
- Test: seed the DB with a row containing the new column → call the endpoint → assert the field appears in the response

### 4C — Acceptance Tests (one per AC)
```python
def test_ac_{n}_{slug}():
    """
    AC-{n}: {exact criterion text from BACKLOG.md}
    """
    # Test must produce a pass/fail that a human can verify against the AC
```

Every AC from the story must have exactly one acceptance test. No AC left uncovered.

---

## STEP 5 — Update KB Artifacts (only if schema or API changed)

**If DB migration was applied:**
- Read `docs/knowledge-base/DB-DOCS/DB_TABLE_REGISTRY.yaml`
- Add the new column entry: `name`, `type`, `nullable`, `description`, `added_by: {REQ_ID}-{STORY_ID}`
- Update `docs/knowledge-base/DB-DOCS/DB_SCHEMA_SUMMARY.md` — add `← NEW (added by {REQ_ID}-{STORY_ID})`

**If API endpoint changed:**
- Read `docs/knowledge-base/MODULES/claims-web/api/10_ENDPOINT_REGISTRY.yaml`
- Update or add the endpoint entry with new fields/parameters

**If UI component changed significantly:**
- Read `docs/knowledge-base/MODULES/claims-web/web/12_COMPONENT_REGISTRY.yaml`
- Update the component's props or API calls list

**If cross-module impact:** flag: "Cross-module matrix may need updating — run PB-06 (KB Refresh) after PROD deployment."

---

## STEP 6 — Run PR Readiness Check (PB-12 logic inline)

Run all sections from PB-12 against the changed files and produce `{REQ_ID}-STORY-{n}-AI-VERIFICATION.md`:

**Section 1 — Story Completeness:** Every AC covered? Every subtask done? Points present?  
**Section 2 — Security (6 checks):** No secrets, SQL parameterized, no PII in logs, RLS filter, HTTPS, input validation  
**Section 3 — PII/PHI (3 checks):** No PII client-side, offshore flag, no SELECT *  
**Section 4 — Tests (3 checks):** Unit tests, integration tests, one test per AC  
**Section 5 — KB Artifacts (3 checks):** DB registry, endpoint registry, component registry  
**Section 6 — PR Description:** REQ-ID, story-ID, files table, ACs checklist, rollback plan, test files, KB update checkbox  

**Overall status:**
- **PASS** = all CRITICAL checks CLEAN + all ACs covered + tests written
- **FAIL** = any CRITICAL or HIGH violation
- **PASS_WITH_WARNINGS** = no CRITICAL/HIGH but MEDIUM issues or stale KB

If status is FAIL: list every blocking item. Do not proceed to SDLC_05 presentation until resolved.

---

## STEP 7 — Gate: SDLC_05 — Code Review

Tell the user:

```
Implementation complete for {STORY_ID}.

Files changed:
  {list of changed files with +/- line counts}

Test files written:
  {list}

KB artifacts updated:
  {list or "None — no schema or API changes"}

AI Verification report: {REQ_ID}-STORY-{n}-AI-VERIFICATION.md
  Overall status: PASS / FAIL / PASS_WITH_WARNINGS

{If FAIL: "The following must be fixed before raising the PR:"}
  {numbered list of CRITICAL and HIGH items}

{If PASS or PASS_WITH_WARNINGS:}
SDLC_05_CODE_REVIEW gate is pending.
  Required reviewers: Developer (+ Tech Lead for security-sensitive changes)
  Artifacts: Pull Request diff, {REQ_ID}-STORY-{n}-AI-VERIFICATION.md
  Timeout: 48 hours

When approved, run: PB-15 (Eval & QA Sign-off) for this story.
```

---

## Advice & Pointers

- **Read the file before every edit.** Line numbers in `insertion-points.yaml` are set at plan time. The file may have been touched since then. Always re-read to find the current position.
- **Follow the codebase's existing pattern.** Find the most recent, most similar change in the codebase and copy its structure. Do not introduce a new pattern when an existing one works.
- **Tests are not optional.** A story without tests cannot pass PR Readiness (SDLC_05). Write unit tests as you implement each function — not at the end.
- **Acceptance tests map 1:1 to ACs.** If there are 3 ACs, there are 3 acceptance tests. The test docstring should quote the AC verbatim so coverage is unambiguous.
- **If you notice something wrong in a file you're reading** (a bug, logic error, stale comment, dead code): add it to `## Observations` in the AI Verification report — file:line, description, and suggested fix. **Do not change it.** Example: "Noticed `serializers.py` line 67: `TIN_CTGRY_CD` has no `required=True` even though the DB column is NOT NULL. This may cause silent null insertions. Recommend raising a separate fix story."
- **If you notice a performance improvement opportunity** (N+1 query, missing index, slow loop): add it to `## Observations` with location and estimated impact. **Do not implement it.** Example: "views.py line 142: `get_queryset()` executes one query per row — adding `select_related('tin_group')` could reduce DB calls by ~80%. Recommend raising a tech-debt story."
- **When scope is ambiguous:** Stop. Ask one question before writing any code. Example: "The insertion point says 'modify ProviderSerializer' — the file has two serializers: `ProviderListSerializer` and `ProviderDetailSerializer`. Which one does this story change?"

---

## Forbidden Actions

- **DO NOT write code without re-reading the target file immediately before editing.** Editing from a cached mental model of the file produces misaligned code.
- **DO NOT touch any file not listed in `insertion-points.yaml`.** Scope is strictly bounded. If another file looks like it should change: stop, note it in `## Observations`, and let the Tech Lead decide.
- **DO NOT introduce a library or framework not already used in the codebase.** No new npm packages, no new Python pip installs, no new imports from outside the existing dependency set.
- **DO NOT hardcode secrets, passwords, API keys, environment-specific URLs, or connection strings.**
- **DO NOT write SQL with string concatenation or f-strings.** Parameterized queries only.
- **DO NOT log a field that contains PII/PHI** — member_id, SSN, DOB, NPI, TIN — in any `logger.*`, `print()`, or `console.log()` call.
- **DO NOT skip writing tests.** Every changed function needs a unit test. Every AC needs an acceptance test. Tests are part of the story deliverable, not an optional extra.
- **DO NOT present the PR for SDLC_05 review if the AI Verification status is FAIL.** Resolve all CRITICAL and HIGH items first.
- **DO NOT fix bugs or implement performance improvements noticed incidentally while reading files.** Note them in `## Observations` only. A separate story is required.
- **DO NOT modify the routing map, BACKLOG.md, SPEC, or GAP-ANALYSIS.** Implementation writes to source code and KB artifacts only — not to SDLC planning documents.
