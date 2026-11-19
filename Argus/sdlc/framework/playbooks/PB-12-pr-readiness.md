# Playbook: PR Readiness Check

`{OWNER}` is resolved per `.devin/rules/session-isolation.md`.

**Playbook ID:** PB-12  
**CLI equivalent:** `/pr-readiness` skill  
**When to use:** Before raising a PR or requesting SDLC_05 human review. Also used by Devin after code generation to self-validate. Produces the `AI-VERIFICATION.md` file required by gate SDLC_05.

---

## Title
```
Acme Claims: PR Readiness Check — Pre-Merge Gate
```

## Description
```
Pre-merge checklist for a Acme Claims pull request. Reads the changed files,
routing map, story acceptance criteria, and security rules to confirm the PR
is ready: all ACs covered, all 10 security checks clean, tests included, KB
artifacts updated, and PR description complete. Produces the
REQ-{id}-STORY-{n}-AI-VERIFICATION.md file required by gate SDLC_05_CODE_REVIEW.
Status: PASS / FAIL / PASS_WITH_WARNINGS.
```

## Playbook Body

---

You are a Tech Lead doing a pre-merge review for a Acme Claims PR. Produce the `{REQ_ID}-STORY-{n}-AI-VERIFICATION.md` file required by SDLC_05.

**Ask:** "Which story's PR should I check? Give me the REQ-ID and STORY-ID."

---

## LOAD FILES

**Session files:**
```
framework/context/session/{OWNER}/{REQ_ID}/
├── {REQ_ID}-BACKLOG.md              (ACs, subtask list)
├── {REQ_ID}-STORY-{n}-ROUTING.md   (files changed, rollback plan)
└── insertion-points.yaml            (exact files and functions modified)
```

**Rules:**
```
.devin/rules/secure-coding.md
.devin/rules/pii-handling.md
.devin/rules/data-access.md
.devin/templates/pr-template.md
```

Identify changed files from `insertion-points.yaml` — scan those specific files.

Source code base paths:
```
./
claims-etl/
claims-etl-glue/
```

> **Note:** claims-etl-* repos are separate GitHub repositories and must be cloned independently.

---

## SECTION 1 — Story Completeness

**1.1 All ACs covered by code changes?**
For each AC in BACKLOG.md: confirm at least one changed file addresses it.
Status per AC: COVERED / NOT_COVERED / PARTIALLY_COVERED

**1.2 All subtasks completed?**
For each subtask: confirm the cited `source_file` was modified.
Status per subtask: DONE / MISSING / PARTIAL

**1.3 Story points and hours present?**
Confirm `story_points` and `original_estimate_hours` are non-null in JIRA-BACKLOG.yaml.

---

## SECTION 2 — Security (all from secure-coding.md)

**2.1 CRITICAL — No hardcoded secrets**
Grep changed files for: `password=`, `api_key=`, `AKIA[0-9A-Z]{16}`, `aws_secret_access_key`
Check known issues SEC-CRED-002, FE-SEC-002.

**2.2 CRITICAL — SQL parameterized**
Grep for f-string SQL, `cursor.execute(f"`, `+` concatenation in queries.

**2.3 CRITICAL — No PII/PHI in logs**
Grep for `member_id|ssn|dob|npi|tin` inside `logger.*`, `print(`, `console.log(`.

**2.4 CRITICAL — RLS tenant filter present**
Any query on CLAIMS_UI_DATA tables: confirm `RAW_TNNT_ID` filter exists.

**2.5 MEDIUM — HTTPS only**
Grep for `http://` (not localhost/testserver).

**2.6 MEDIUM — Input validation via serializer**
New/modified Django views that accept user input must route through serializer validation.

---

## SECTION 3 — PII/PHI (from pii-handling.md)

**3.1 CRITICAL — No PII in client-side code**
Grep `.tsx`/`.ts` files for direct `member_id|ssn|dob` access.

**3.2 HIGH — Offshore flag enforced**
If PII tables queried: confirm `RAW_OFSHR_ACSBL_IND = 'Y'` filter for offshore users.

**3.3 MEDIUM — No SELECT * on PII tables**
Tables: `VBC_UI_MBR_ATRBN`, `VBC_UI_PRVDR_GRP`, `VBC_UI_CLMS`.

---

## SECTION 4 — Tests

**4.1 Unit tests exist for changed functions**
For each function in `insertion-points.yaml`: confirm a test file covers it by name.
Result: COVERED / MISSING / PARTIAL

**4.2 Integration test if DB or API changed**
Result: COVERED / MISSING / NOT_APPLICABLE

**4.3 At least one test per AC**
Result: COVERED / MISSING

---

## SECTION 5 — KB Artifacts Updated

**5.1 DB_TABLE_REGISTRY.yaml** — updated if migration file changed? UPDATED / STALE / N/A
**5.2 10_ENDPOINT_REGISTRY.yaml** — updated if urls.py/views.py changed? UPDATED / STALE / N/A
**5.3 12_COMPONENT_REGISTRY.yaml** — updated if .tsx component changed? UPDATED / STALE / N/A

---

## SECTION 6 — PR Description (using pr-template.md)

Check routing map or PR description contains:
- [ ] REQ-ID and STORY-ID reference
- [ ] Files changed table
- [ ] ACs validated checklist
- [ ] Rollback plan
- [ ] Test files listed
- [ ] KB artifacts updated checkbox

---

## OUTPUT — Write AI Verification Report

Write `{REQ_ID}-STORY-{n}-AI-VERIFICATION.md` to the session directory:

```markdown
# AI Verification Report: {REQ_ID}-STORY-{n}
Date: {today} | Story: {title} | Skill: pr-readiness

## Overall Status: ✅ PASS / ❌ FAIL / ⚠️ PASS_WITH_WARNINGS

## Section 1 — Story Completeness
| Check | Status | Notes |
|---|---|---|
|| 1.1 All ACs covered | ✅/❌/⚠️ | {detail} |
|| 1.2 All subtasks done | ✅/❌/⚠️ | {detail} |
|| 1.3 Points present | ✅/❌ | |

## Section 2 — Security
| Check | Severity | Status | Finding |
|---|---|---|---|
|| 2.1 No hardcoded secrets | CRITICAL | ✅/❌ | {file:line} |
|| 2.2 SQL parameterized | CRITICAL | ✅/❌ | {file:line} |
|| 2.3 No PII in logs | CRITICAL | ✅/❌ | {file:line} |
|| 2.4 RLS tenant filter | CRITICAL | ✅/❌/N/A | {file:line} |
|| 2.5 HTTPS only | MEDIUM | ✅/⚠️ | {file:line} |
|| 2.6 Input validation | MEDIUM | ✅/⚠️/N/A | {file:line} |

## Section 3 — PII/PHI
| Check | Severity | Status | Finding |
|---|---|---|---|
|| 3.1 No PII client-side | CRITICAL | ✅/❌ | |
|| 3.2 Offshore flag | HIGH | ✅/❌/N/A | |
|| 3.3 No SELECT * | MEDIUM | ✅/⚠️/N/A | |

## Section 4 — Tests
| Check | Status | Notes |
|---|---|---|
|| 4.1 Unit tests | ✅/❌/⚠️ | {test files} |
|| 4.2 Integration tests | ✅/❌/N/A | |
|| 4.3 AC coverage | ✅/❌ | |

## Section 5 — KB Artifacts
| Artifact | Status |
|---|---|
|| DB_TABLE_REGISTRY.yaml | ✅ Updated/⚠️ STALE/N/A |
|| 10_ENDPOINT_REGISTRY.yaml | ✅ Updated/⚠️ STALE/N/A |
|| 12_COMPONENT_REGISTRY.yaml | ✅ Updated/⚠️ STALE/N/A |

## Action Items Before Merge
{numbered list — CRITICAL and HIGH items only}

## Files Scanned
{list}

## SDLC_05 Gate
This report satisfies the AI verification requirement for SDLC_05_CODE_REVIEW.
Overall status: PASS / FAIL / PASS_WITH_WARNINGS
```

After writing, tell the user the status and what must be fixed (if FAIL).

---

---

## Advice & Pointers

- **This report is the SDLC_05 gate artifact.** Its status directly controls whether the PR can be merged. An honest FAIL is more valuable than a generous PASS — a security violation that reaches PROD costs far more than a delayed PR.
- **"Looks fine" is not a check result.** Each of the 6 security checks, 3 PII checks, and 3 test checks must produce an evidence-based result: COVERED/MISSING/CLEAN/VIOLATION — with file:line.
- **Action items in the report must be concrete.** Not "fix the test coverage" — instead: "No test covers AC-2 (offshore flag applied for offshore users). Add a test in `test_provider_views.py` that calls the endpoint with `RAW_OFSHR_ACSBL_IND='N'` and asserts the response is empty."
- **KB artifact staleness is a PASS_WITH_WARNINGS, not a FAIL.** But it must still be listed. Stale KB is a risk to the next requirement built on this codebase.
- **If you notice something else wrong while reading the files** (a bug unrelated to the story, dead code, a performance anti-pattern), note it in `## Additional Observations` at the end of the verification report. **Do not include it in the PASS/FAIL determination.** That section is advisory only.

---

## Forbidden Actions

- **DO NOT modify source code.** This playbook is read-only verification. Every issue is reported — zero fixes applied.
- **DO NOT mark PASS if any CRITICAL check has a violation.** The logic is binary: CRITICAL violation = FAIL. There are no exceptions, no mitigating circumstances.
- **DO NOT skip a section.** All 6 sections must be run even if the change seems small. A DB-only change still gets the test check and KB artifact check.
- **DO NOT modify the BACKLOG.md or JIRA-BACKLOG.yaml.** PR readiness is a verification activity — it does not update planning documents.
- **DO NOT approve the PR yourself.** This playbook produces the `AI-VERIFICATION.md` report. The human Tech Lead/developer approves the PR in GitHub/Bitbucket.
- **DO NOT implement fixes noticed during the review.** A FAIL means the developer must fix the issue and run a fresh PR readiness check. Devin does not self-repair after producing a FAIL result.
