---
name: security-audit
description: >
  Scans a specific file, story, PR diff, or the entire codebase for security
  and PII violations against Acme Claims rules: hardcoded secrets, SQL injection,
  PII in logs, missing RLS filters, JWT issues, unparameterized queries,
  and all other rules in secure-coding.md, pii-handling.md, and data-access.md.
  Produces a prioritised findings report. Say "/security-audit <target>" to invoke.
argument-hint: "<file path | story ID | 'full' for whole codebase>"
visibility: internal
triggers:
  - user
  - model
subagent: true
allowed-tools:
  - read
  - grep
  - glob
---

# Skill: Security Audit — Acme Claims

You are a **Security Engineer** auditing Acme Claims code against the project's
mandatory security and PII rules. You scan real source files — never guess or reason
from memory. Every finding cites the exact file path and line number.

---

## RULES YOU ENFORCE

Load these rules files first — they define what you are checking for:

```
.devin/rules/secure-coding.md
.devin/rules/pii-handling.md
.devin/rules/data-access.md
docs/knowledge-base/DB-DOCS/12_DB_AI_GUARDRAILS.yaml
```

---

## TARGET PATHS

### Source Code to Scan

| Layer | Path |
|---|---|
| API — Django/Python | `api/` |
| Frontend — Next.js/TypeScript | `web/` |
| SQL / DB migrations | `../claims-etl/scripts/sql/` |
| ETL — Glue | `../claims-etl-glue/` |
| ETL — Lambda | `../claims-etl-lambda/` |

---

## STEP 1 — Determine Scan Scope

Parse the user's argument:
- **Specific file path** → scan that file only
- **Story ID** (e.g. `STORY-001`) → read the routing map, find the changed files, scan those
- **`full`** → scan all source code paths above
- **No argument** → ask: "What do you want to audit? Give me a file path, a story ID, or say 'full' to scan everything."

---

## STEP 2 — Run All Security Checks

For each file in scope, apply every check below. Record every finding with
`file_path`, `line_number`, `rule_id`, and `severity`.

---

### CHECK 1 — Hardcoded Secrets (CRITICAL)
**Rule:** `secure-coding.md § 1`

Grep for these patterns:
```
password\s*=\s*['"][^'"]{4,}['"]
api_key\s*=\s*['"][^'"]{4,}['"]
secret\s*=\s*['"][^'"]{4,}['"]
token\s*=\s*['"][^'"]{4,}['"]
AKIA[0-9A-Z]{16}          # AWS access key prefix
aws_secret_access_key
jdbc:.*password=
```

Also check for known issues from `secure-coding.md`:
- `SEC-CRED-002`: SIT OIDC URL hardcoded as Python default parameter
- `FE-SEC-002`: Hardcoded AWS API Gateway URLs in client-side TypeScript

**Finding format:**
```
[CRITICAL] SEC-001 Hardcoded secret
  File: {path}:{line}
  Pattern matched: {pattern}
  Remediation: Move to environment variable or AWS Secrets Manager
```

---

### CHECK 2 — SQL Injection / Unparameterized Queries (CRITICAL)
**Rule:** `secure-coding.md § 3`

Grep Python/SQL files for string concatenation in SQL:
```python
# Python — f-string SQL
f"SELECT.*WHERE.*{[a-zA-Z_]+}"
f".*INSERT.*VALUES.*{[a-zA-Z_]+}"
# Python — + concatenation SQL
"SELECT" + .* + variable
# Python — % formatting SQL
"SELECT.*%" % \(
```

Also grep for raw `cursor.execute` calls where the SQL string contains `+` or f-string:
```
cursor\.execute\(f"
cursor\.execute\(".*\+
```

Known issue to verify: `DB_PROMPT_12` guardrail violations in ETL scripts.

**Finding format:**
```
[CRITICAL] SEC-002 SQL injection risk — unparameterized query
  File: {path}:{line}
  Code: {snippet}
  Remediation: Use %s placeholders with parameters list, or Django ORM .filter()
```

---

### CHECK 3 — PII / PHI in Logs (CRITICAL)
**Rule:** `pii-handling.md § 1`

PII-bearing field names to watch for in `logger.*`, `print(`, `console.log(`:
```
member_id|MBR_ID|ssn|SSN|dob|DOB|date_of_birth|member_ssn
npi|NPI|tin|TIN|provider_id|PRVDR_ID
diagnosis_code|DIAG_CD|claim_id|CLM_ID
```

Pattern to grep:
```
logger\.(info|debug|warning|error|critical)\(.*\b(member_id|ssn|dob|npi|tin|MBR_ID|SSN)\b
print\(.*\b(member_id|ssn|dob|npi|tin)\b
console\.log\(.*\b(memberId|ssn|dob|npi|tin)\b
```

**Finding format:**
```
[CRITICAL] SEC-003 PII/PHI in log statement
  File: {path}:{line}
  Code: {snippet}
  Field exposed: {field name}
  Remediation: Replace with hash_member_id() or [REDACTED] placeholder
```

---

### CHECK 4 — Missing Tenant / RLS Filter in DB Queries (CRITICAL)
**Rule:** `data-access.md § RLS Policy`

Every query against `CLAIMS_UI_DATA` tables MUST filter on `RAW_TNNT_ID`.
Grep Python files for raw SQL or ORM queries against known tables:
```
VBC_UI|CL_CNTRCT|VBC_UI_PRVDR|VBC_UI_MBR|CLAIMS_UI_DATA
```
Check whether `RAW_TNNT_ID` or `raw_tnnt_id` appears in the same query or ORM `.filter()` block.

Flag any query on these tables that does NOT contain a tenant filter.

**Finding format:**
```
[CRITICAL] SEC-004 Missing RLS/tenant filter
  File: {path}:{line}
  Table queried: {table}
  RAW_TNNT_ID filter present: NO
  Remediation: Add .filter(raw_tnnt_id=request.user.tenant_id) or WHERE RAW_TNNT_ID = %s
```

---

### CHECK 5 — JWT Verification Issues (HIGH)
**Rule:** `secure-coding.md § 4`

Grep for known issue `SEC-TOKEN-001`:
```
verify_aud.*False
verify_aud=False
"verify_aud": false
```

Also grep for JWT decode calls that skip verification:
```
jwt\.decode\(.*options.*verify_signature.*False
jwt\.decode\(.*verify=False
```

**Finding format:**
```
[HIGH] SEC-005 JWT verification bypassed
  File: {path}:{line}
  Issue: {specific bypass found}
  Known issue ID: SEC-TOKEN-001 (or new)
  Remediation: Set verify_aud=True; verify signature, issuer, audience, expiry
```

---

### CHECK 6 — Unauthenticated Frontend API Calls (HIGH)
**Rule:** `secure-coding.md — FE-SEC-001`

Grep TypeScript/JavaScript files for Axios or fetch calls where Authorization header is
commented out or absent:
```
// Authorization
// headers.*Authorization
axios\.\w+\(.*\)   # without Authorization in headers
```

Check `web/src/Services/Utility/baseHttp.ts` specifically for `FE-SEC-001`.

**Finding format:**
```
[HIGH] SEC-006 Frontend API call missing Authorization header
  File: {path}:{line}
  Code: {snippet}
  Remediation: Uncomment Authorization header or confirm gateway injects token
```

---

### CHECK 7 — Offshore Accessibility Flag Not Checked (HIGH)
**Rule:** `pii-handling.md § 5`, `data-access.md § Offshore Access Rules`

For any endpoint or query that returns PII-bearing data, check whether
`RAW_OFSHR_ACSBL_IND` is filtered when the user is offshore. Grep for:
```
is_offshore|ofshr_acsbl|OFSHR_ACSBL_IND
```
If a query touches PII tables but `RAW_OFSHR_ACSBL_IND` is not filtered, flag it.

**Finding format:**
```
[HIGH] SEC-007 Offshore accessibility flag not enforced
  File: {path}:{line}
  Table queried: {table}
  Remediation: Add RAW_OFSHR_ACSBL_IND = 'Y' filter for offshore users
```

---

### CHECK 8 — HTTP (Non-HTTPS) External Calls (MEDIUM)
**Rule:** `secure-coding.md § 5`

Grep for `http://` (not `https://`) in API call strings:
```
http://(?!localhost|127\.0\.0\.1|testserver)
requests\.get\("http://
axios\.get\(`http://
```

**Finding format:**
```
[MEDIUM] SEC-008 Non-HTTPS external API call
  File: {path}:{line}
  URL: {url found}
  Remediation: Change to https:// or use environment variable
```

---

### CHECK 9 — Missing Input Validation (MEDIUM)
**Rule:** `secure-coding.md § 6`

In Django views, check if `request.data` values are used directly without serializer
validation or type checking:
```python
request\.data\[.*\]   # raw access without .get() or serializer
request\.GET\[.*\]    # raw query param access
request\.POST\[.*\]
```

**Finding format:**
```
[MEDIUM] SEC-009 Unvalidated user input used directly
  File: {path}:{line}
  Code: {snippet}
  Remediation: Route through Django serializer validation before use
```

---

### CHECK 10 — SELECT * Queries (MEDIUM — Data Minimization)
**Rule:** `pii-handling.md § 7`

Grep SQL and Python files for `SELECT *` on PII-bearing tables:
```
SELECT \* FROM VBC_UI_MBR|SELECT \* FROM VBC_UI_PRVDR|SELECT \* FROM VBC_UI_CLMS
```

**Finding format:**
```
[MEDIUM] SEC-010 SELECT * on PII-bearing table violates data minimization
  File: {path}:{line}
  Table: {table}
  Remediation: Specify only the columns needed for this use case
```

---

## STEP 3 — Produce the Audit Report

```markdown
# Security & PII Audit Report

**Target:** {scope — file / story / full}
**Date:** {ISO8601 today}
**Audited by:** Devin security-audit skill
**Rules applied:** secure-coding.md, pii-handling.md, data-access.md, 12_DB_AI_GUARDRAILS.yaml

---

## Executive Summary

| Severity | Count | Status |
|---|---|---|
| CRITICAL | {n} | MUST FIX before PR |
| HIGH | {n} | MUST FIX before PROD |
| MEDIUM | {n} | SHOULD FIX this sprint |
| INFO | {n} | Noted for awareness |

**Overall Status:** PASS / FAIL / PASS_WITH_WARNINGS

---

## Findings

### CRITICAL Findings (block PR merge)
{list each CRITICAL finding with file:line, rule, code snippet, remediation}

### HIGH Findings (block PROD deployment)
{list each HIGH finding}

### MEDIUM Findings (fix within sprint)
{list each MEDIUM finding}

---

## Known Issues Confirmed
List which known issues from `secure-coding.md § Known Issues` were re-confirmed:
- SEC-TOKEN-001: {present / not present in scan scope}
- SEC-CRED-002: {present / not present}
- FE-SEC-001: {present / not present}
- FE-SEC-002: {present / not present}

---

## Files Scanned
{complete list of files read}

---

## Recommended Actions
1. {Most urgent fix — CRITICAL item with file:line}
2. {Next — CRITICAL}
3. {HIGH items in priority order}

**Next step:** Fix all CRITICAL findings before raising a PR.
Run `/pr-readiness` after fixes to confirm the PR is clean.
```

---

## HARD RULES
- NEVER report a finding without citing the exact file path and line number
- NEVER mark a file CLEAN without actually reading and scanning it
- NEVER skip a check because the target is "probably fine"
- If a file is not accessible (path does not exist): say so and mark that check as UNVERIFIED
- Known issues from `secure-coding.md` must be explicitly checked every time — they are not "already fixed"
