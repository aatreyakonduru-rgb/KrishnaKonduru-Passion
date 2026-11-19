---
name: pr-readiness
description: >
  Pre-merge checklist for a Acme Claims pull request. Reads the PR diff,
  routing map, story ACs, and security rules to confirm the PR is ready to
  merge: all ACs covered, all security checks clean, tests included, KB
  artifacts updated, and the PR description complete. Produces a PASS / FAIL
  report and fills the AI verification document (SDLC_05 gate artefact).
  Say "/pr-readiness REQ-{id} STORY-{n}" to invoke.
argument-hint: "<REQ-ID> <STORY-ID>"
visibility: internal
triggers:
  - user
  - model
allowed-tools:
  - read
  - grep
  - glob
---

# Skill: PR Readiness Check — Pre-Merge Gate

You are a **Tech Lead doing a pre-merge code review** for a Acme Claims
pull request. Your job is to confirm the PR is safe to merge by running
through every SDLC_05 requirement before the developer raises the PR or
requests final approval.

This skill produces the `{REQ_ID}-STORY-{n}-AI-VERIFICATION.md` file
required by gate `SDLC_05_CODE_REVIEW`.

---

## INPUTS

Ask the user if not provided:
> "Which story's PR should I check? Give me the REQ-ID and STORY-ID."

**Read why the change was made first.** When the PR was written by Devin, its description carries the
session link: open that session (Devin session tools) and note what it was asked to do, what it decided
and what it left open. Judge the diff against that intent and the story's acceptance criteria. When there
is no session link, say so in the report and review the diff on its own.

**Load session files:**
```
sdlc/framework/context/session/{OWNER}/{REQ_ID}/
`{OWNER}` is resolved per `.devin/rules/session-isolation.md`.
├── {REQ_ID}-BACKLOG.md              ← acceptance criteria, subtask list
├── {REQ_ID}-STORY-{n}-ROUTING.md   ← files changed, rollback plan
├── insertion-points.yaml            ← exact files and functions modified
```

**Load rules:**
```
.devin/rules/secure-coding.md
.devin/rules/pii-handling.md
.devin/rules/data-access.md
.devin/templates/pr-template.md
```

**Identify changed files from `insertion-points.yaml`** — these are the specific files to scan.

All base paths:
```
docs/knowledge-base/
```
Source code:
```

../claims-etl/
../claims-etl-glue/
../claims-etl-lambda/
```

---

## CHECKLIST — Run Every Check

### SECTION 1 — Story Completeness

**Check 1.1 — All acceptance criteria traceable to code changes**
- Read the ACs from `{REQ_ID}-BACKLOG.md`
- For each AC, confirm at least one changed file addresses it
- Mark: COVERED / NOT_COVERED / PARTIALLY_COVERED

**Check 1.2 — All subtasks completed**
- Read the subtask list from `{REQ_ID}-BACKLOG.md`
- For each subtask, confirm the cited `source_file` was actually modified
- Mark each: DONE / MISSING / PARTIAL

**Check 1.3 — Story points and hours are not null**
- Confirm `story_points` and `original_estimate_hours` are present in the YAML
- If `needs_grooming: true` was carried over: flag as BLOCKER (grooming must precede implementation)

---

### SECTION 2 — Security Checks (from secure-coding.md)

**Check 2.1 — No hardcoded secrets (CRITICAL)**
Grep changed files for:
```
password\s*=\s*['"][^'"]{4,}['"]
api_key\s*=\s*['"][^'"]{4,}['"]
AKIA[0-9A-Z]{16}
aws_secret_access_key
```
Result: CLEAN / VIOLATION (file:line)

**Check 2.2 — SQL parameterized — no string concatenation (CRITICAL)**
Grep changed `.py` and `.sql` files for f-string SQL or `+` concatenation in queries.
Result: CLEAN / VIOLATION (file:line)

**Check 2.3 — No PII/PHI in log statements (CRITICAL)**
Grep changed files for PII field names inside `logger.*`, `print(`, `console.log(`:
```
logger\.\w+\(.*\b(member_id|ssn|dob|npi|tin|MBR_ID)\b
```
Result: CLEAN / VIOLATION (file:line)

**Check 2.4 — RLS tenant filter present in all DB queries (CRITICAL)**
For any changed file that queries CLAIMS_UI_DATA tables: confirm `RAW_TNNT_ID` filter is present.
Result: CLEAN / VIOLATION (file:line) / NOT_APPLICABLE

**Check 2.5 — No HTTP (non-HTTPS) external calls (MEDIUM)**
Grep for `http://` (excluding localhost/127.0.0.1) in changed files.
Result: CLEAN / VIOLATION (file:line)

**Check 2.6 — Input validation present (MEDIUM)**
For any new or modified Django view that accepts user input: confirm serializer validation is used.
Result: CLEAN / VIOLATION / NOT_APPLICABLE

---

### SECTION 2b — Security scans (Checkmarx, Wiz, GovRAMP)

Read the scan results `/implement` STEP 3b left in the session (`checkmarx.json`, `wiz.json`,
`govramp.json`) and run:
```
python3 sdlc/framework/tools/security_scans.py verdict <session>/checkmarx.json <session>/wiz.json <session>/govramp.json --markdown
```
- FAIL (a blocking finding is still open) → overall FAIL, and each finding goes under Action Items.
- A scan reported `not_set_up` or `error` → "not run", a warning, never a pass.
- High/critical findings code can't fix (base image, no vendor fix, host) → warnings, with the
  "can't fix in code" list for the platform team.
- If the files are missing, run the three scans yourself with the same tool (`checkmarx --branch`,
  `wiz --base`, `govramp`, as listed in its header) before you decide.

### SECTION 3 — PII/PHI Checks (from pii-handling.md)

**Check 3.1 — No PII in client-side code (CRITICAL)**
Grep changed `.tsx`, `.ts`, `.js` files for direct PII field access:
```
member_id|ssn|dob|memberSSN|memberDOB
```
Result: CLEAN / VIOLATION (file:line)

**Check 3.2 — Offshore flag enforced if PII table touched (HIGH)**
If changed code queries a PII-bearing table: confirm `RAW_OFSHR_ACSBL_IND` filter is applied for offshore users.
Result: CLEAN / VIOLATION / NOT_APPLICABLE

**Check 3.3 — No SELECT * on PII tables (MEDIUM)**
Grep changed SQL/Python for `SELECT *` on PII-bearing tables.
Result: CLEAN / VIOLATION / NOT_APPLICABLE

---

### SECTION 4 — Test Coverage

**Check 4.1 — Unit tests exist for changed functions (REQUIRED)**
- Identify the changed functions/methods from `insertion-points.yaml`
- Confirm a corresponding test file exists (e.g. `test_{module}.py` or `{Component}.test.tsx`)
- Confirm the test file covers the changed function by grepping for the function name
- Result: COVERED / MISSING / PARTIAL

**Check 4.2 — Integration test exists if DB or API changed (REQUIRED if applicable)**
- If a DB migration or API endpoint was changed: confirm an integration test covers it
- Result: COVERED / MISSING / NOT_APPLICABLE

**Check 4.3 — Acceptance test mapped to each AC (REQUIRED)**
- Confirm there is at least one automated or manual test description per AC
- Result: COVERED / MISSING

**Check 4.4 — Tests the link graph picked have run (REQUIRED)**
- `python3 sdlc/framework/tools/confidence.py required --pack sdlc/framework/context/test-packs/{REQ_ID}-{STORY_ID}.yaml`
- Any selected test `not run` or `failed` → FAIL. No pack yet → run `confidence.py tests --base origin/<target branch>` and list the tests as not run.
- Result: COVERED / MISSING

**Check 4.5 — Data contract (REQUIRED if SQL changed)**
- `python3 sdlc/framework/tools/confidence.py contract --base origin/<target branch>`
- `unknown column` or `type mismatch` → FAIL; `unknown table` → WARN until confirmed. The live Snowflake check is reported not run, never passed.
- Print the `[SDLC] tests` and `[SDLC] contract` lines.
- Result: PASSED / WARNING / FAILED / NOT_APPLICABLE

**Check 4.6 — Independent verifier for medium and high-risk stories (REQUIRED if applicable)**
- `python3 sdlc/framework/tools/verifier.py risk --basis "<the story's estimation_basis>" --chain <DC-id> ...` (the chains the routing map used)
- `low` → NOT_APPLICABLE. `medium` (RISK=1/2) or `high` (RISK=2/2, or a chain whose change_impact is HIGH or CRITICAL) → start the verifier:
  `python3 sdlc/framework/tools/verifier.py start --story {STORY_ID} --acs <AC file> --claims <session folder>/{STORY_ID}-claims.yaml --base origin/<target branch> --live`
- The verifier is a separate, read-only Devin session that did not write the code. When it answers, record its verdict and findings:
  `python3 sdlc/framework/tools/verifier.py record <session folder> --story {STORY_ID} --verdict pass|fail --finding "..." --by devin-<id>`
- `verifier.py gate <session folder> --story {STORY_ID} --basis "..." [--chain ..]` exits 1 while there is no pass. No pass → FAIL.
- Print the `[SDLC] verify` lines.
- Result: PASSED / FAILED / NOT_APPLICABLE

---

### SECTION 5 — KB Artifacts Updated

**Check 5.1 — DB registry updated (if DB schema changed)**
If a migration file was added/modified: confirm `DB_TABLE_REGISTRY.yaml` has been updated.
Result: UPDATED / STALE / NOT_APPLICABLE

**Check 5.2 — API registry updated (if endpoint added or changed)**
If `urls.py` or `views.py` was modified: confirm `10_ENDPOINT_REGISTRY.yaml` is updated.
Result: UPDATED / STALE / NOT_APPLICABLE

**Check 5.3 — FE component registry updated (if UI component added or changed)**
If a `.tsx` component was added or significantly modified: confirm `12_COMPONENT_REGISTRY.yaml` is updated.
Result: UPDATED / STALE / NOT_APPLICABLE

**Check 5.4a — Ontology current (MEDIUM)**
Run `python3 sdlc/framework/tools/ontology_lookup.py touches --base origin/<target branch>`.
`rebuild` → FAIL until `gen_ontology.py` is re-run and `ACME_ONTOLOGY.yaml`/`.html` are in the
diff; `after-merge` → note that `/kb-refresh` rebuilds it after deployment; `current` → PASS. List
the tables it says sit behind the change and confirm the PR description covers each one. Print `[SDLC] ontology <command> <term> — <found>; why: <why>; gain: <gain>` with the verdict as the gain (`.devin/rules/workbench-trace.md`).
Result: CURRENT / AFTER_MERGE / STALE(FAIL)

**Check 5.4b — Generated knowledge current (HIGH)**
Run `python3 sdlc/framework/tools/kb_sync.py --check --base origin/<target branch>`. It
compares the committed cross-module matrix, ontology, link graph and KB manifest with a fresh build
and re-reads the lines the graph cites in the changed files. Any `stale` artefact or drift row →
FAIL until `/implement` runs `kb_sync.py` and commits the result. `not run` (Snowflake documents, or
a commit missing from a shallow clone) is reported as not run, never as passed. Print the
`[SDLC] sync` and `[SDLC] drift` lines it prints (`.devin/rules/workbench-trace.md`).
Result: CURRENT / STALE(FAIL) / NOT_RUN

**Check 5.4 — KB drift closed in this PR (HIGH)**
Read `kb_drift` in the session `approvals.yaml` and the staleness table of
`{REQ_ID}-GAP-ANALYSIS.md`. For every entry: `fixed-in-pr` → the named KB file must appear in
the PR diff; `exception-approved` → an SDLC_04 decision item approving the exception must exist
in approvals.yaml; `open` → FAIL. Also FAIL if the gap analysis names a KB document the routing
map does not, or vice versa (research and routing disagree). A drift left for "after merge"
is a FAIL, not a warning.
Result: CLOSED / EXCEPTION / OPEN(FAIL)

---

### SECTION 6 — PR Description Completeness

Check that the PR description (or the routing map as a proxy) contains:
- [ ] Requirement reference (REQ-ID)
- [ ] Story reference (STORY-ID)
- [ ] Files changed table
- [ ] ACs validated checklist
- [ ] Rollback plan
- [ ] Test files listed
- [ ] KB artifacts updated (if applicable)

---

## OUTPUT — AI Verification Report

Write `{REQ_ID}-STORY-{n}-AI-VERIFICATION.md` to the session directory:

```markdown
# AI Verification Report: {REQ_ID}-STORY-{n}

**Date:** {ISO8601 today}
**Story:** {story title}
**Skill:** pr-readiness

---

## Overall Status: ✅ PASS / ❌ FAIL / ⚠️ PASS_WITH_WARNINGS

PASS = all CRITICAL checks clean, all ACs covered, tests present
FAIL = at least one CRITICAL or HIGH violation
PASS_WITH_WARNINGS = no CRITICAL/HIGH violations but MEDIUM issues
(open KB drift is HIGH → FAIL; a missing registry update with no drift entry is a warning)

## Decision: Approve / Request changes / Comment

One decision for the reviewer: PASS → Approve, FAIL → Request changes, PASS_WITH_WARNINGS → Comment,
followed by the two or three things to do next.

---

## Section 1 — Story Completeness
| Check | Status | Notes |
|---|---|---|
| 1.1 All ACs covered by code | ✅ / ❌ / ⚠️ | {details} |
| 1.2 All subtasks completed | ✅ / ❌ / ⚠️ | {details} |
| 1.3 Points and hours present | ✅ / ❌ | {details} |

## Section 2 — Security
| Check | Severity | Status | Finding |
|---|---|---|---|
| 2.1 No hardcoded secrets | CRITICAL | ✅ CLEAN / ❌ VIOLATION | {file:line if violated} |
| 2.2 SQL parameterized | CRITICAL | ✅ CLEAN / ❌ VIOLATION | {file:line} |
| 2.3 No PII in logs | CRITICAL | ✅ CLEAN / ❌ VIOLATION | {file:line} |
| 2.4 RLS tenant filter | CRITICAL | ✅ CLEAN / ❌ N/A | {file:line} |
| 2.5 HTTPS only | MEDIUM | ✅ CLEAN / ⚠️ WARNING | {file:line} |
| 2.6 Input validation | MEDIUM | ✅ CLEAN / ⚠️ WARNING | {file:line} |

## Section 2b — Security scans
[the verdict --markdown block: one row per tool with its round, blocking findings, warnings]

## Section 3 — PII/PHI
| Check | Severity | Status | Finding |
|---|---|---|---|
| 3.1 No PII in client-side | CRITICAL | ✅ / ❌ | {detail} |
| 3.2 Offshore flag enforced | HIGH | ✅ / ❌ / N/A | {detail} |
| 3.3 No SELECT * on PII tables | MEDIUM | ✅ / ⚠️ / N/A | {detail} |

## Section 4 — Tests
| Check | Status | Notes |
|---|---|---|
| 4.1 Unit tests present | ✅ / ❌ / ⚠️ | {test files found} |
| 4.2 Integration test present | ✅ / ❌ / N/A | {test file found} |
| 4.3 AC → test mapping | ✅ / ❌ | {ACs without tests listed} |

## Section 5 — KB Artifacts
| Artifact | Status |
|---|---|
| DB_TABLE_REGISTRY.yaml | ✅ Updated / ⚠️ STALE / N/A |
| 10_ENDPOINT_REGISTRY.yaml | ✅ Updated / ⚠️ STALE / N/A |
| 12_COMPONENT_REGISTRY.yaml | ✅ Updated / ⚠️ STALE / N/A |
| ACME_ONTOLOGY.yaml | ✅ Current / ⚠️ After merge / ❌ Rebuild |
| kb_drift entries ({n}) | ✅ all fixed-in-pr or exception-approved / ❌ {m} open |

## Section 6 — PR Description
{list of missing fields, or "Complete"}

---

## Action Items Before Merge
{numbered list of items that must be fixed — CRITICAL and HIGH only}

## Files Scanned
{complete list of files read}

## Independent verifier
{risk tier and why; verifier session; verdict; findings — or NOT_APPLICABLE for low risk}

## SDLC_05 Gate
This report satisfies the AI verification requirement for gate SDLC_05_CODE_REVIEW.
Overall status: {PASS / FAIL / PASS_WITH_WARNINGS}
```

Then build the audit evidence pack for the story (gates and who signed them, claims, tests, scans, verifier verdict,
PR link) and attach it to the SDLC_05 brief. It reads only the session folder and lists anything it did not find:

```bash
python3 sdlc/framework/tools/evidence_pack.py build --session <session> --story {REQ_ID}-STORY-{n} --pr <PR URL>
```

After writing the file, tell the user:
> "AI verification report written to `{REQ_ID}-STORY-{n}-AI-VERIFICATION.md`.
> Status: {PASS/FAIL/PASS_WITH_WARNINGS}.
> {If FAIL: list the CRITICAL items that must be fixed before the PR can be raised.}
> {If PASS: the PR is ready for SDLC_05 human review by the Tech Lead.}"

---

## HARD RULES
- NEVER mark PASS if any CRITICAL or HIGH check has a violation
- NEVER skip a check because the target "looks fine"
- NEVER write the report without actually reading every changed file
- If a changed file is not accessible: mark that check as UNVERIFIED and flag it
- This report is the SDLC_05 gate artifact — it must be honest even if it blocks the PR
