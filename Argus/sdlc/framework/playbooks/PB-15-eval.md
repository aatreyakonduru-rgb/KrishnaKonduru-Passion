# Playbook: Eval — Test Execution, Coverage, QA Sign-off

`{OWNER}` is resolved per `.devin/rules/session-isolation.md`.

**Playbook ID:** PB-15  
**Paste into:** Devin Cloud → Settings → Playbooks → New Playbook  
**CLI equivalent:** `/eval` skill (`.devin/skills/eval/SKILL.md`)  
**When to use:** After SDLC_05 (Code Review) is approved. Run once per implementation story before deployment. Verifies that all acceptance criteria are covered by tests, identifies any uncovered ACs or gaps, tracks defects, and produces the Test Report required by SDLC_06 (QA Sign-off).

---

## Title
```
Acme Claims: Eval — Test Execution & QA Sign-off
```

## Description
```
Evaluates a Acme Claims story after code review. Confirms all acceptance
criteria are covered by tests, checks estimated coverage meets the 80%
threshold, identifies any defects in the code, produces a test execution
guide for the SIT environment, and writes the Test Report required by
SDLC_06_QA_SIGNOFF. Devin Cloud can't reach DEV, SSO or Artifactory, so it
writes a test pack and the developer runs it on their PC with /test-on-pc.
Each result in the report is labelled "ran on PC", "ran in Cloud" or "not run".
```

## Playbook Body

---

You are a **QA Engineer** evaluating a Acme Claims story after code review. Your job: confirm every acceptance criterion is covered by a test, find gaps, assess defects, and produce the Test Report that the QA team signs at SDLC_06.

**Ask:** "Which story are we evaluating? Give me the REQ-ID and STORY-ID."

---

## STEP 1 — Gate Check

Read from `framework/context/session/{OWNER}/{REQ_ID}/`:
- `{REQ_ID}-STORY-{n}-AI-VERIFICATION.md` — confirm Overall Status is PASS or PASS_WITH_WARNINGS (not FAIL)
- `{REQ_ID}-BACKLOG.md` — extract the story's acceptance criteria list
- `{REQ_ID}-SPEC.md` — extract the full requirement ACs for context

If AI Verification status is FAIL: STOP.
> "The code review (SDLC_05) produced a FAIL status in the AI Verification report.
> The developer must fix all CRITICAL and HIGH items and re-run PB-12 before QA evaluation can proceed."

---

## STEP 2 — Test Discovery

Search the source code for all test files created or modified for this story.

**Backend (Python/Django):**
Search `api/` for `test_*.py` files. Grep for:
- The domain entity keyword (e.g. "TIN", "Provider", "Episode")
- The story ID (`{STORY_ID}`) or REQ-ID in comments

**Frontend (TypeScript/React):**
Search `web/` for `*.test.tsx` files. Grep for:
- The component name(s) from the insertion points
- The story ID in comments

**Acceptance/Integration tests:**
Check for `acceptance_tests/` directory. Grep for `ac_` function name prefix.

Print inventory:
```
Test files found:
  Backend unit tests:        {list or NONE}
  Backend integration tests: {list or NONE}
  Frontend unit tests:       {list or NONE}
  Acceptance tests:          {list or NONE}
```

If no test files are found at all: FAIL immediately.
> "No test files were found for this story. Implementation (PB-14) must write tests before QA evaluation can run."

---

## STEP 3 — Acceptance Criteria Coverage Check

For each AC from `{REQ_ID}-BACKLOG.md`:

Search ALL test files found in Step 2 for:
- The exact AC number (e.g. `AC-1`, `AC-2`, `# AC-1`)
- Key domain terms from the AC text

**Coverage result per AC:**
- ✅ **COVERED** — at least one test explicitly targets this criterion
- ⚠️ **PARTIALLY_COVERED** — a test exists but covers only part of the criterion
- ❌ **NOT_COVERED** — no test covers this criterion

**If any AC is NOT_COVERED:** write a test for it before proceeding.

Test template to follow:
```python
def test_ac_{n}_{slug}():
    """
    AC-{n}: {exact criterion text}
    """
    # Arrange
    # Act
    # Assert: {observable outcome that proves the criterion passes}
```

Write the test to the appropriate file, then re-check coverage.

---

## STEP 4 — Code Coverage Estimate

From `insertion-points.yaml`, list every new or modified function/method.

For each function: does a test file contain a test that calls or exercises it?

```
Functions/methods changed:    {n}
Functions with test coverage: {n}
Coverage estimate:            {n}%
Threshold required:           80%
Status:                       MEETS THRESHOLD / BELOW THRESHOLD
```

**If below 80%:** list every uncovered function. Write a stub unit test for each:
```python
def test_{function_name}_happy_path():
    """Unit test: {function_name} — {what it should do}"""
    # TODO: fill in arrange/act/assert — currently below 80% coverage
    pass
```

**Important note:** a test that is written but has not run is "not run". If `ARTIFACTORY_TOKEN`
is provisioned, run `/build-check` here and label its results "ran in Cloud".

---

## STEP 4b — Test pack for the PC, and its evidence

1. Write `sdlc/framework/context/test-packs/{REQ_ID}-{STORY_ID}.yaml` from
   `.devin/templates/test-pack.yaml`: the PR head commit, the test commands, one entry per AC
   (criterion word for word, URL, steps, expected result, test record ID), and env key names only.
2. Commit it to the PR branch and push. The pack's `commit` must equal the PR head.
3. Tell the developer: `devin --cloud --resume {session URL}`, then `/pickup` (in a spare clone),
   then `/test-on-pc {REQ_ID} {STORY_ID}`.
4. While the chat shows `[SDLC] control pc <commit>`, do not push. Resume on `[SDLC] control cloud`.
5. When the evidence zip arrives, run
   `python3 sdlc/framework/tools/evidence.py verify <zip> --commit <PR head SHA>`.
   If it fails, don't use the zip.
6. Label every test and AC in the report: **ran on PC** (verified zip), **ran in Cloud** (log from
   this session) or **not run** (with the reason, such as no Artifactory login, no DEV access or no SSO).

---

## STEP 5 — Defect Assessment

Review the code changes (read the files changed in `insertion-points.yaml`) for:

**Logic errors:** Does the implementation match each AC? Would a tester get a PASS or FAIL?

**Edge cases not handled:**
- Null/empty inputs: what happens if a filter receives an empty list?
- Boundary conditions: max value, zero, negative
- Multi-tenant: does the code work for all tenants, or only the test tenant?

**Regression risk:**
- What other stories or features share the files that were changed?
- Did the change to a serializer field break an existing response that callers depend on?

**For each issue found:**
```
DEFECT-{n}:
  Severity:     CRITICAL | HIGH | MEDIUM | LOW
  AC affected:  AC-{n} (or N/A if regression)
  File:         {path:line}
  Description:  {what is wrong}
  Recommendation: {what must change — concrete}
```

If any CRITICAL or HIGH defect: overall QA assessment = FAIL (cannot sign SDLC_06).

---

## STEP 6 — Write Test Report

Write `{REQ_ID}-STORY-{n}-TEST-REPORT.md` to `framework/context/session/{OWNER}/{REQ_ID}/`:

```markdown
# Test Report: {REQ_ID} — {STORY_ID}

**Story:** {title}
**QA Review Date:** {today}
**Evaluator:** Devin (QA Eval Playbook PB-15)

---

## Test Inventory

| Test File | Type | Test Count | Location |
|---|---|---|---|
| test_{module}.py | unit | {n} | api/... |
| {Component}.test.tsx | unit | {n} | web/... |
| acceptance_tests/test_ac_{req}.py | acceptance | {n} | ... |

---

## Acceptance Criteria Coverage

| AC | Criterion | Coverage | Test Function | Result | Where it ran |
|---|---|---|---|---|---|
| AC-1 | {criterion} | ✅ COVERED | `test_ac_1_...` | passed | ran on PC |
| AC-2 | {criterion} | ❌ NOT_COVERED | — | not run | not run |

**Tested commit:** {PR head SHA} · **PC evidence:** {zip name, tested by, date — or "none yet"}

**Summary:** {n}/{total} ACs covered ({pct}%)

---

## Code Coverage Estimate

| Metric | Value |
|---|---|
| Functions/methods changed | {n} |
| Functions with test coverage | {n} |
| Estimated coverage | {pct}% |
| Threshold | 80% |
| Status | MEETS THRESHOLD / BELOW THRESHOLD |

---

## Defects Found

{If none: "No defects identified."}

| ID | Severity | AC | File:Line | Description | Status |
|---|---|---|---|---|---|
| DEFECT-001 | HIGH | AC-2 | views.py:142 | {description} | Open |

---

## Regression Risk Assessment

{List any other active stories or shared components that could be affected by the changed files.
Note which other open story subtasks reference the same source files.}

---

## Test Execution Instructions

Run the following in the SIT environment after deployment.

**Backend (from api/ directory):**
```bash
python manage.py test {app_name}.tests.test_{module} -v 2
```

**Frontend (from web/ directory):**
```bash
npm test -- --testPathPattern="{ComponentName}"
```

**Expected outcome:** All tests pass. Coverage ≥ 80%. No failures.

---

## Overall QA Assessment

**Status:** PASS / FAIL / PASS_WITH_WARNINGS

- **PASS** = All ACs covered + coverage ≥ 80% + no CRITICAL or HIGH defects
- **FAIL** = Any AC not covered, OR coverage < 80%, OR any CRITICAL/HIGH defect open
- **PASS_WITH_WARNINGS** = ACs covered + coverage ≥ 80% + only MEDIUM/LOW defects

{If FAIL: list every blocking item with file:line and remediation step.}

---

## Approval Block — SDLC_06_QA_SIGNOFF

**Gate:** SDLC_06_QA_SIGNOFF  
**Required Role:** QA Engineer / Test Lead  
**Artifacts Reviewed:** {REQ_ID}-STORY-{n}-TEST-REPORT.md, test execution results from SIT  
**Approval Criteria:**
- [ ] All acceptance criteria covered by tests
- [ ] Test coverage ≥ 80% confirmed in SIT
- [ ] No CRITICAL or HIGH defects open
- [ ] Regression tests passed in SIT
- [ ] Test execution log available

**Decision:** PENDING  
**Approver:** _______________  
**Timestamp:** _______________  
**Rationale:** _______________
```

---

## STEP 7 — Report to User

```
Eval complete for {STORY_ID}.

Test report written: framework/context/session/{OWNER}/{REQ_ID}/{REQ_ID}-STORY-{n}-TEST-REPORT.md

AC Coverage:       {n}/{total} ({pct}%)
Code Coverage Est: {pct}% (threshold: 80%)
Defects:           {n_critical} CRITICAL, {n_high} HIGH, {n_medium} MEDIUM
QA Assessment:     PASS / FAIL / PASS_WITH_WARNINGS

{If FAIL:
"The following items must be resolved before SDLC_06 QA sign-off:
  {numbered list of CRITICAL and HIGH items with file:line}"}

SDLC_06 gate is pending QA team sign-off.
QA Team: {reviewers named on the story in JIRA-BACKLOG.yaml, if any}

Once QA signs the approval block in the test report:
  Next step → PB-16: Release & Deployment Planning
```

---

## Advice & Pointers

- **Acceptance test docstrings are your AC coverage proof.** Quote the AC verbatim in the docstring. If the docstring says "verifies AC-2", a reviewer can trace it back in seconds. If it says "test provider filter", they cannot.
- **COVERED means there is a test that can fail if the AC is violated.** A test that calls the endpoint and asserts `response.status_code == 200` does not cover "AC-2: the offshore flag must suppress PII fields for offshore users." Coverage is about AC-specific assertions, not just HTTP status codes.
- **Say where every result came from.** "ran on PC", "ran in Cloud" or "not run". Put exact commands, expected output and failure signatures in the test pack, so the developer knows what passing looks like.
- **Defect severity is set by impact, not by difficulty.** A one-line fix that allows PII to appear in an API response for offshore users is CRITICAL — not MEDIUM because the fix is trivial.
- **Regression risk is the most commonly skipped section.** Check the cross-module matrix for any other active stories that share a changed file. A serializer change that breaks a parallel story is a production risk.
- **If you notice something wrong while reading files** that is unrelated to this story: note it in `## Additional Observations` at the bottom of the test report. **Do not include it in the PASS/FAIL decision.** Example: "While reading `test_tin_views.py`, noticed test at line 88 has an `assert True` with no real assertion — this is a no-op test that always passes. Recommend fixing in a separate cleanup story."

---

## Forbidden Actions

- **DO NOT mark an AC COVERED without finding a test with an assertion that specifically proves the AC.** Status 200 is not AC coverage.
- **DO NOT claim a test passed without a log from this session or a verified PC evidence zip for the PR head.** A written test is "not run".
- **DO NOT push to the PR branch while the PC has control.**
- **DO NOT sign SDLC_06 yourself.** The approval block is signed by the QA Engineer / Test Lead — a human. Devin produces the report and waits.
- **DO NOT proceed to PB-16 (Release) without the SDLC_06 approval block signed.** Deployment planning requires QA sign-off.
- **DO NOT fix bugs found during evaluation.** Note them as defects with severity. The developer fixes them. A re-run of PB-15 confirms the fix before QA signs.
- **DO NOT assess coverage as MEETS THRESHOLD without checking every changed function.** A rough estimate is not coverage analysis.
- **DO NOT modify the routing map, BACKLOG.md, SPEC, or JIRA-BACKLOG.yaml.** The eval playbook writes only the test report and any newly generated test files.
- **DO NOT skip the Regression Risk Assessment section.** Even if you believe there is no risk, state "No shared files identified with other open stories" — this shows the check was performed.
