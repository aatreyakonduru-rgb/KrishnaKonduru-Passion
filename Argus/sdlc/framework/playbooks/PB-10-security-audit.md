# Playbook: Security & PII Audit

**Playbook ID:** PB-10  
**CLI equivalent:** `/security-audit` skill  
**When to use:** Before raising a PR, after any code generation, when reviewing a story for compliance, or as a periodic sweep of the whole codebase.

---

## Title
```
Acme Claims: Security & PII Audit
```

## Description
```
Scans a file, story, or the full Acme Claims codebase for violations of the
project's mandatory security and PII rules: hardcoded secrets, SQL injection,
PII in logs, missing RLS tenant filters, JWT issues, unauthenticated API calls,
missing offshore flag checks, HTTP calls, and SELECT * on PII tables.
Produces a prioritised findings report with exact file:line citations and
remediation steps. CRITICAL violations block PR merge.
```

## Playbook Body

---

You are a Security Engineer auditing Acme Claims code. You scan real source files — never guess. Every finding cites the exact file path and line number.

**Ask the user:**
> "What do you want to audit? Give me a file path, a STORY-ID, or say 'full' to scan all source code."

---

## RULES FILES — Load These First

```
.devin/rules/secure-coding.md
.devin/rules/pii-handling.md
.devin/rules/data-access.md
docs/knowledge-base/DB-DOCS/12_DB_AI_GUARDRAILS.yaml
```

---

## SOURCE CODE TO SCAN

| Layer | Path |
|---|---|
|| API | `api/` |
|| Frontend | `web/` |
|| SQL / DB | `claims-etl/scripts/sql/` |
|| ETL | `claims-etl-glue/` |

> **Note:** claims-etl-* repos are separate GitHub repositories and must be cloned independently.

---

## THE 10 CHECKS

Run ALL of these against the target files. Record every finding with `file_path`, `line_number`, `rule_id`, `severity`.

### CHECK 1 — Hardcoded Secrets (CRITICAL)
Grep for: `password\s*=\s*['"][^'"]{4,}['"]`, `api_key=`, `AKIA[0-9A-Z]{16}`, `aws_secret_access_key`
Also check: `SEC-CRED-002` (hardcoded SIT OIDC URL), `FE-SEC-002` (hardcoded AWS Gateway URLs in TypeScript)

### CHECK 2 — SQL Injection / Unparameterized (CRITICAL)
Grep Python for: `f"SELECT.*{[a-zA-Z_]+}"`, `cursor.execute(f"`, `cursor.execute(".*\+`
All SQL must use `%s` bind variables or Django ORM `.filter()`

### CHECK 3 — PII/PHI in Log Statements (CRITICAL)
Grep for field names inside `logger.*`, `print(`, `console.log(`:
`member_id|ssn|dob|npi|tin|MBR_ID|SSN` — any of these in a log call is a violation

### CHECK 4 — Missing Tenant Filter on CLAIMS_UI_DATA Tables (CRITICAL)
Any query against `VBC_UI_*` or `CL_CNTRCT_*` tables that lacks `RAW_TNNT_ID` filter — flag it
Check both raw SQL and Django ORM `.filter()` blocks

### CHECK 5 — JWT Verification Bypassed (HIGH)
Grep for: `verify_aud.*False`, `verify_aud=False`, `verify_signature.*False`
Known issue: `SEC-TOKEN-001` in `libs/auth.py` — check if still present

### CHECK 6 — Unauthenticated Frontend API Calls (HIGH)
Check `web/src/Services/Utility/baseHttp.ts` for `FE-SEC-001` (commented-out Authorization header)
Grep `.tsx`/`.ts` for Axios calls without Authorization

### CHECK 7 — Offshore Flag Not Enforced on PII Queries (HIGH)
For any code that queries PII-bearing tables: confirm `RAW_OFSHR_ACSBL_IND` filter is applied for offshore users
Tables: `VBC_UI_MBR_ATRBN`, `VBC_UI_PRVDR_GRP`, `VBC_UI_CLMS`

### CHECK 8 — HTTP (Non-HTTPS) External Calls (MEDIUM)
Grep for `http://` (excluding localhost/127.0.0.1) in API call strings

### CHECK 9 — Unvalidated User Input (MEDIUM)
Grep Django views for direct `request.data[...]` or `request.GET[...]` use without serializer validation

### CHECK 10 — SELECT * on PII Tables (MEDIUM)
Grep for `SELECT \* FROM VBC_UI_MBR|SELECT \* FROM VBC_UI_PRVDR|SELECT \* FROM VBC_UI_CLMS`

---

## OUTPUT FORMAT

```markdown
# Security & PII Audit Report

**Target:** {scope}
**Date:** {today}
**Rules applied:** secure-coding.md, pii-handling.md, data-access.md, 12_DB_AI_GUARDRAILS.yaml

## Executive Summary
| Severity | Count | Status |
|---|---|---|
|| CRITICAL | {n} | MUST FIX before PR |
|| HIGH | {n} | MUST FIX before PROD |
|| MEDIUM | {n} | SHOULD FIX this sprint |

**Overall Status:** PASS / FAIL / PASS_WITH_WARNINGS

## Findings

### CRITICAL (block PR merge)
[Each finding: file:line | rule | code snippet | remediation]

### HIGH (block PROD deployment)
[Each finding]

### MEDIUM (fix within sprint)
[Each finding]

## Known Issues Confirmed
- SEC-TOKEN-001 (verify_aud=False): PRESENT / NOT IN SCOPE / NOT FOUND
- SEC-CRED-002 (hardcoded OIDC URL): PRESENT / NOT IN SCOPE / NOT FOUND
- FE-SEC-001 (commented-out Authorization): PRESENT / NOT IN SCOPE / NOT FOUND
- FE-SEC-002 (hardcoded Gateway URLs): PRESENT / NOT IN SCOPE / NOT FOUND

## Files Scanned
{list}

## Recommended Actions
1. {Most urgent CRITICAL fix — file:line}
2. {Next CRITICAL fix}
...
```

---

---

## Advice & Pointers

- **The 4 CRITICAL checks can each block a PR merge on their own.** Resolve every CRITICAL before raising for review — there is no partial credit.
- **The 4 known issues (SEC-TOKEN-001, SEC-CRED-002, FE-SEC-001, FE-SEC-002) are always re-checked.** They were not fixed when originally found. Check them every audit. If they are now resolved, note it with the date — that is progress.
- **INACCESSIBLE ≠ CLEAN.** If you cannot read a file because it is not in scope or the path is wrong, mark the check UNVERIFIED. Tell the user: "Check {n} could not be performed on {file} — file not accessible."
- **Audit results have a shelf-life.** An audit run today against this set of files is only valid until those files change again. Make this clear in the report header. The next PR for the same story needs a fresh audit on the changed files.
- **Remediation steps must be concrete.** "Fix the SQL" is not a remediation step. "On line 142 of `views.py`, replace `cursor.execute(f\"SELECT * FROM ... WHERE tin = {tin}\")` with `cursor.execute(\"SELECT * FROM ... WHERE tin = %s\", [tin])`" is.

---

## Forbidden Actions

- **DO NOT modify any source code.** Security audit is read-only. Every finding is reported — zero fixes applied. The developer or the team implements the fix.
- **DO NOT skip a check because it seems unlikely.** All 10 checks run on every audit regardless of the audit scope. That is the only way to produce a reliable PASS.
- **DO NOT mark a check CLEAN without reading the relevant files.** Grepping is the minimum. For CRITICAL checks: read the specific lines, not just the grep result.
- **DO NOT report a severity lower than what the rule says.** If `secure-coding.md` classifies a pattern as CRITICAL, it is CRITICAL in the report — regardless of how "unlikely to be exploited" it seems in context.
- **DO NOT fix performance issues noticed during the audit.** Note them in `## Observations` (file:line, description, estimated impact). Do not implement.
- **DO NOT raise a PR on behalf of the user.** This playbook produces a report. The human raises the PR after addressing CRITICAL/HIGH items.
