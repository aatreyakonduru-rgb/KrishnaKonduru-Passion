---
name: eval
description: >
  SDLC Stage 6 — Test Execution, Coverage Analysis, Defect Tracking, QA Sign-off.
  Orchestrates the full evaluation pipeline for one story after code review is approved:
  verifies all tests exist and run, checks coverage meets the 80% threshold, validates
  every acceptance criterion is covered, tracks any defects found, and presents
  SDLC_06 using `.devin/rules/gate-presentation.md` for the QA team.
  Invoke with: /eval REQ-{id} STORY-{n}
  Source agent: .devin/agents/eval.agent.yaml
argument-hint: "<REQ-ID> <STORY-ID>  e.g. REQ-TIN-001 STORY-003"
visibility: internal
triggers:
  - user
  - model
subagent: true
allowed-tools:
  - read
  - write
  - grep
  - glob
---

# Skill: Eval Orchestrator (SDLC Stage 6)

Background reading: `sdlc/framework/workflows/eval.md` (the longer stage procedure; where it and this skill differ, this skill is the one to follow).

You are a **QA Engineer** evaluating a Acme Claims story after code review.
Your job is to confirm all acceptance criteria are covered by tests, identify
any uncovered ACs or gaps, track defects, and produce a complete test report.

Source agent spec:
```
.devin/agents/eval.agent.yaml
```
Child steps — executed inline by this skill, they are not separate skill files:
```
test-gen  (generate missing tests)
test-exec  (simulate test execution review)
```

---

## INPUTS

Parse arguments: `REQ_ID` and `STORY_ID`.

---

## SESSION DIRECTORY

```
sdlc/framework/context/session/{OWNER}/{REQ_ID}/
`{OWNER}` is resolved per `.devin/rules/session-isolation.md`.
```

## SOURCE CODE

```
api/
web/
../claims-etl/scripts/
```

---

# Gate presentation and signing

Present SDLC_06 and record its decision using
`.devin/rules/gate-presentation.md`. The canonical criteria and artifact list
come from `.devin/rules/approval-gates.yaml`; do not rely on a skill-specific
approval block or write a literal `signed_by: user`.

## STEP 0 — Gate Check

**Trace lines (Argus):** print `[SDLC] kb <path> — loaded: <why>` / `skipped: <why>`, `[SDLC] rule <path> — loaded|deferred: <why>`, `[SDLC] chain DC-… — …` and `[SDLC] decision … — …` as each file is opened, skipped or each choice made, per `.devin/rules/workbench-trace.md` — here: a `kb` line for the AI verification, backlog and spec; a `kb` line for every test file found in Test Discovery and for each SIT/UAT test-case source used (`CONFLUENCE-DERIVED/05_TEST_CASE_CATALOGUE.md`, Jira attachments); and a `decision` line for each acceptance criterion's verdict (COVERED / PARTIAL / NOT COVERED), the coverage figure or why it could not be measured, each defect raised or not raised, and every test that could not run here and why.

Read `{REQ_ID}-{STORY_ID}-AI-VERIFICATION.md`. Confirm:
- `Overall Status` is PASS or PASS_WITH_WARNINGS (not FAIL)
- `SDLC_05_CODE_REVIEW` gate is referenced as approved in the document

Read `{REQ_ID}-BACKLOG.md`. Extract the story's acceptance criteria.
Read `{REQ_ID}-SPEC.md`. Extract the full requirement ACs for context.

If AI verification status is FAIL: STOP.
> "SDLC_05 (Code Review) produced a FAIL status in the AI verification report.
> The following items must be fixed first: {list from AI-VERIFICATION.md}"

---

## STEP 1 — Test Discovery

Search the source code for all test files related to this story.

For backend (Python/Django):
- Grep `api/` for `test_*.py` files containing the domain entity keywords
- Verify each test file exists and is readable

For frontend (TypeScript/React):
- Grep `web/` for `*.test.tsx` files containing the component names from the story

For acceptance/integration tests:
- Check `acceptance_tests/` directory if it exists

Then let the link graph pick the tests the change reaches:
`python3 sdlc/framework/tools/confidence.py tests --base origin/<target branch> --pack <test pack>`.
It writes `selected_tests:` into the test pack (STEP 3b), each with the link that picked it, and
prints a `[SDLC] tests` line. Add those tests to the inventory. A changed file with no link in the
graph gets its tests from the search above only; say so.

Build a test inventory:
```
Test files found:
  Backend unit tests:        {list or NONE}
  Backend integration tests: {list or NONE}
  Frontend tests:            {list or NONE}
  Acceptance tests:          {list or NONE}
```

---

## STEP 2 — Acceptance Criteria Coverage Check

For each AC from the story in `{REQ_ID}-BACKLOG.md`:

Search ALL test files found in Step 1 for:
- The AC number reference (e.g. `AC-1`, `AC-2`)
- Key domain terms from the AC text (e.g. column name, field name, behaviour described)

Coverage result per AC:
- COVERED: at least one test explicitly covers this criterion
- PARTIALLY_COVERED: a test exists but only covers part of the criterion
- NOT_COVERED: no test covers this criterion

If any AC is NOT_COVERED:

Generate a test for it following `test-gen.skill.yaml`:
```python
# {test_file_path}
def test_{ac_slug}():
    """
    AC-{n}: {criterion text}
    """
    # Arrange: {setup needed}
    # Act: {action to take}
    # Assert: {expected outcome}
    {test_code}
```

Write the new test to the appropriate test file.

---

## STEP 3 — Coverage Analysis

Calculate coverage from what is known:
- List every new or modified function/method from `insertion-points.yaml`
- For each function: is there at least one test that calls it directly or covers its path?

Coverage report:
```
Functions/methods changed: {n}
Functions with test coverage: {n}
Coverage estimate: {n}%
Threshold required: 80%
Status: MEETS THRESHOLD / BELOW THRESHOLD
```

If below 80%: list every uncovered function and generate a stub test for each.

**Note**: if `ARTIFACTORY_TOKEN` is provisioned, run `/build-check` for the touched components
and report its table here, labelled "ran in Cloud". Otherwise those tests did not run in Cloud.
Say so, and leave them to the PC run in STEP 3b:
> "These tests are written and ready to run. They have not run yet: {list}"

---

### Required tests and the data contract

Mark each selected test `passed` or `failed` in the pack's `selected_tests` when it has run (in
Cloud, or from a verified PC evidence zip), then run
`python3 sdlc/framework/tools/confidence.py required --pack <test pack>`. It exits 1 when a
selected test is `not run` or `failed`, and SDLC_06 is not presented until it passes. Behave
scenarios from `ACME/claims-qa` carry `run_by: QA`: QA runs them in SIT, so while they are `not run`
they are listed for QA and do not fail the check; a `failed` one still does. Run
`confidence.py contract --base origin/<target branch>` too and put both `[SDLC]` lines in the test
report. The live Snowflake data check stays `not run`.

## STEP 3a — Accessibility and performance

For every page the story changes, with the app running locally (or on its dev URL):

```bash
python3 sdlc/framework/tools/a11y_perf.py run --story {REQ_ID}-STORY-{n} \
  --url <page URL> [--url <page URL> ...] --out <session>/{REQ_ID}-STORY-{n}-A11Y-PERF.md
```

It checks alt text, form labels, button and link names, page language, heading order and duplicate ids, and reads
largest contentful paint, load time, requests and transfer size against `.devin/rules/a11y-perf.yaml`. Put its
Overall Status (PASS, FAIL or INCOMPLETE) in the test report's QA assessment and attach the file to SDLC_06. A page
that could not be opened is INCOMPLETE, never PASS. A story with no UI change records "not applicable — no page changed".

## STEP 3b — Test pack for the PC, and its evidence

Cloud can't reach the DEV API, SSO or (today) Artifactory, so the real UI test runs on the
developer's PC with `/test-on-pc` (`.devin/skills/test-on-pc/SKILL.md`).

1. Write the test pack from `.devin/templates/test-pack.yaml` to
   `sdlc/framework/context/test-packs/{REQ_ID}-{STORY_ID}.yaml`:
   - `commit`: the full SHA of the code to test (`git rev-parse HEAD` after the last code push)
   - `checks`: the commands from STEP 1 and STEP 3 (jest, pytest, `/build-check`, Behave)
   - `acceptance`: one entry per AC, with the criterion word for word, the URL, steps, expected
     result and test data (a test record ID, never a real member)
   - `setup.env_files`: key names only, never values
2. Commit the pack to the PR branch and push. The commit that adds the pack becomes the PR head.
   That's fine: `evidence.py start` accepts a head whose only changes since `commit` are under
   `sdlc/framework/context/test-packs/`, and refuses one with any code change. A new
   code push needs a new pack.
3. Tell the user how to test on the PC:
   > "The PR is ready for a PC test. On your laptop: `devin --cloud --resume {session URL}`,
   > then `/pickup` (in a spare clone), then `/test-on-pc {REQ_ID} {STORY_ID}`."
4. Wait. While the PC has control (`[SDLC] control pc <commit>` in the chat), do not push to the
   PR branch. Resume on `[SDLC] control cloud`.
5. When `[SDLC] evidence ...` arrives with a zip, download it and check it:
   ```bash
   python3 sdlc/framework/tools/evidence.py verify <zip> --commit <PR head SHA>
   ```
   If it exits non-zero (wrong commit, changed file), don't use it. Tell the user why.
6. Every AC and test now has one label in the report:
   - **ran on PC**: from a verified evidence zip, with its status (passed, failed, not run)
   - **ran in Cloud**: run in this session, with the log
   - **not run**: nobody ran it yet, or a prerequisite was missing. Give the reason.

If the user wants to skip the PC run, every UI AC stays "not run". Say so in the report.

---

## STEP 4 — Defect Assessment

Review the code changes (from `insertion-points.yaml` and the edited files) for:
- Logic errors (does the implementation match the AC?)
- Edge cases not handled (null values, empty lists, boundary conditions)
- Missing error handling (what happens when the API is called with invalid input?)
- Regression risk (does this change anything that other stories depend on?)

For each issue found:
```
DEFECT-{n}:
  Severity: CRITICAL | HIGH | MEDIUM | LOW
  AC affected: AC-{n}
  Description: {what is wrong}
  File: {path}
  Recommendation: {what must change}
```

If any CRITICAL or HIGH defect is found: status = FAIL (QA cannot sign off).

---

## STEP 5 — Produce Test Report

Write `{REQ_ID}-{STORY_ID}-TEST-REPORT.md`:

```markdown
# Test Report: {REQ_ID} — {STORY_ID}

**Story**: {title}
**QA Review Date**: {today}
**Skill**: /eval orchestrator
**Tested commit**: {PR head SHA}
**PC evidence**: {evidence zip name, tested by, machine, date — or "none yet"}

---

## Test Inventory

| Test File | Type | Tests | Result | Where it ran |
|---|---|---|---|---|
| {file} | unit/integration/acceptance | {count} | passed / failed / not run | ran on PC / ran in Cloud / not run |

---

## Acceptance Criteria Coverage

| AC | Criterion | Coverage | Test Reference | Result | Where it ran | Evidence |
|---|---|---|---|---|---|---|
| AC-1 | {criterion} | COVERED / PARTIAL / NOT_COVERED | {test_name} | passed / failed / not run | ran on PC / ran in Cloud / not run | {file in the zip, or log} |
| AC-2 | ... | ... | ... | ... | ... | ... |

**Coverage Summary**: {n}/{total} ACs covered ({pct}%)

---

## Code Coverage Estimate

Functions/methods changed: {n}
Functions with test coverage: {n}
Estimated coverage: {pct}%
Threshold (80%): {PASS / BELOW THRESHOLD}

---

## Defects Found

{If none: "No defects found."}

| ID | Severity | AC | Description | File | Status |
|---|---|---|---|---|---|
| DEFECT-001 | HIGH | AC-2 | {description} | {file} | Open |

---

## Regression Risk Assessment

{List any other stories/features that could be affected by this change, based on
the cross-module matrix and the shared files modified.}

---

## Test Execution Instructions

Anything still "not run" above. On the PC, `/test-on-pc {REQ_ID} {STORY_ID}` runs them from the
test pack. By hand:

**Backend (run from api/):**
```bash
python manage.py test {test_module} -v 2
```

**Frontend (run from web/):**
```bash
npm test -- --testPathPattern="{component_name}"
```

Expected: all tests pass, coverage ≥ 80%

---

## Overall QA Assessment

**Status**: PASS / FAIL / PASS_WITH_WARNINGS

PASS: All ACs covered, coverage ≥ 80%, no CRITICAL or HIGH defects
FAIL: Any AC not covered, coverage < 80%, or CRITICAL/HIGH defect open
PASS_WITH_WARNINGS: ACs covered, coverage ≥ 80%, but MEDIUM/LOW defects open

---

## Approval Block — SDLC_06_QA_SIGNOFF

Gate: SDLC_06_QA_SIGNOFF
Required Role: QA Engineer (Test Lead or Tester)
Artifacts Reviewed: {REQ_ID}-{STORY_ID}-TEST-REPORT.md, test execution logs, PC evidence zip (if any)
Approval Criteria:
  - [ ] Test coverage meets threshold (80%+)
  - [ ] All acceptance criteria validated
  - [ ] No critical defects
  - [ ] Regression tests passed
Decision: PENDING
Approver: _______________
Timestamp: _______________
Rationale: _______________
```

---

## STEP 6 — Report to User

```
Eval complete for {STORY_ID}.

Test report written: {REQ_ID}-{STORY_ID}-TEST-REPORT.md

AC Coverage: {n}/{total} ({pct}%)
Code Coverage: {pct}% (threshold: 80%)
Where it ran: {n} on PC, {n} in Cloud, {n} not run (commit {sha})
Defects: {n_critical} CRITICAL, {n_high} HIGH, {n_medium} MEDIUM
QA Assessment: {PASS / FAIL / PASS_WITH_WARNINGS}

{If FAIL: "The following items must be resolved before QA can sign off: {list}"}

SDLC_06 gate is pending QA team sign-off. Use the explicit Approve, Reject with
reasons, or Approve with notes options from `.devin/rules/gate-presentation.md`.
  Test Lead: Resource 24
  Testers: Resource 33, Resource 19, Resource 21, Resource 18

When QA approves, run: /release {REQ_ID} {STORY_ID}
```

---

## HARD RULES
- NEVER mark an AC as COVERED without finding a specific test that covers it
- NEVER report coverage percentage without checking all changed functions
- NEVER sign off (PASS) if any AC is NOT_COVERED
- NEVER sign off (PASS) if a CRITICAL or HIGH defect is open
- NEVER report a test or AC as passed unless it ran and you have the log or a verified PC evidence
  zip for the PR head. A written test is "not run", not "passed"
- NEVER use PC evidence that `evidence.py verify` rejects, or that is for an older commit
- NEVER present SDLC_06 as ready while a UI AC is "not run". Present it with those ACs listed as
  "not run", and let QA decide
- NEVER push to the PR branch while the PC has control
- If a new test is generated, write it to the correct test file before reporting
