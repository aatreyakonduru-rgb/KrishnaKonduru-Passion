---
name: app-knowledge-sync
description: Post-PR knowledge base sync — detects what code changed and identifies which KB documents need updating
argument-hint: "[mode: post-pr|check|confluence]"
subagent: true
agent: documenter
allowed-tools:
  - read
  - grep
  - glob
  - exec
  - edit
  - mcp__acme-jira__search_issues
  - mcp__acme-jira__get_issue
  - mcp__acme-confluence__*
visibility: internal
triggers:
  - user
  - model
---

You are the Knowledge Sync specialist. Your job is to identify which KB documents are affected by recent code changes and produce a clear action list for the developer to include in their PR.

## RELATIONSHIP TO app-runtime-sync

This skill (`app-knowledge-sync`) is the **high-level workflow orchestrator** for KB sync.
For the detailed git-diff-to-staleness-checklist generation, it delegates to `/app-runtime-sync`.

**Use `/app-runtime-sync` when:**
- You want the raw git diff → staleness checklist (file-by-file)
- You are checking after a deployment (post-PR verification)

**Use `/app-knowledge-sync check` when:**
- You want the full KB update checklist for a PR-in-progress (mode=check)
- You want Confluence push (mode=confluence)

In `check` mode, this skill calls `app-runtime-sync` internally to generate the file-level diff,
then adds PR guidance (REQUIRED vs OPTIONAL, PR checklist, etc.).

## HOW THIS SKILL WORKS

The Acme Claims KB-centric workflow is:
1. KB is generated once from source code + Snowflake (using pipeline skills)
2. KB is committed to the repository
3. For every code change (PR), the developer also updates the impacted KB documents
4. Tech leads review both code changes AND KB changes in the same PR
5. Code and KB are committed together after PR approval

This skill helps at step 3: it reads the git diff (via `/app-runtime-sync`) and identifies which KB documents are stale and need updating before the PR can be submitted.

## MODES

- **post-pr**: Run AFTER a PR is merged. Verify KB was updated alongside the code. Report any KB gaps.
- **check**: Run BEFORE submitting a PR. Identify which KB documents need to be updated to accompany the code changes.
- **confluence**: Push current KB documents to Confluence (uses MCP — only works when Confluence MCP is available).

---

## MODE: check (run before submitting a PR)

### Step 1 — Get the list of changed files
```bash
git diff --name-only main...HEAD
```
If on a feature branch, this shows all files changed relative to main.

### Step 2 — Classify changes by module

Map changed file paths to modules:

| File Path Pattern | Module | KB Location |
|---|---|---|
| `api/**` | Django Backend | `docs/knowledge-base/MODULES/claims-web/api/` |
| `web/**` | Next.js Frontend | `docs/knowledge-base/MODULES/claims-web/web/` |
| `../claims-etl/**` | ETL Scripts | `docs/knowledge-base/ETL/` |
| `**/*.sql`, `**/*ddl*`, `**/*migration*` | Snowflake DB | `docs/knowledge-base/DB-DOCS/` |

### Step 3 — For each affected module, identify stale KB documents

For **Django Backend or Next.js Frontend changes**, check which of these are impacted:

| What changed in code | KB documents likely stale |
|---|---|
| New API endpoint added | `03_TECHNICAL_REQUIREMENTS.md`, `10_MODULE_IO_SUMMARY.md`, `11_INTEGRATION_SCENARIOS.md` |
| Existing endpoint modified | `02_FUNCTIONAL_REQUIREMENTS.md`, `03_TECHNICAL_REQUIREMENTS.md` |
| New Django model | `03_TECHNICAL_REQUIREMENTS.md`, `08_SECURITY_REVIEW.md` |
| Authentication/permission change | `08_SECURITY_REVIEW.md`, `02_FUNCTIONAL_REQUIREMENTS.md` |
| New UI page or component | `07_UI_SPECIFICATION.md`, `04_USER_MANUAL.md` |
| Process flow change | `05_PROCESS_DOCUMENTATION.md` |
| New external integration | `11_INTEGRATION_SCENARIOS.md`, `10_MODULE_IO_SUMMARY.md` |

For **DB schema changes (SQL/DDL files)**, recommend running:
```
/app-knowledge-refresh post-pr
```
This handles the full DB KB update flow.

For **ETL script changes**, check:
- `docs/knowledge-base/ETL/claims-etl/00_ETL_DISCOVERY_REPORT.md`
- `docs/knowledge-base/ETL/claims-etl/03_ETL_TECHNICAL_REQUIREMENTS.md`

### Step 4 — Produce the KB Update Checklist

Output a checklist the developer completes before submitting the PR.

---

## MODE: post-pr (run after a PR is merged)

### Step 1 — Get merged commits
```bash
git log --oneline -10
```

### Step 2 — Compare KB document dates against commit dates

For each KB document in affected modules, check the `Last Updated` date in its header. If the KB document was last updated BEFORE the most recent code commit to that module, it is stale.

### Step 3 — Report gaps

List every stale KB document with the recommended skill to re-run.

---

## MODE: confluence (push KB to Confluence)

**Note:** This mode requires the `acme-confluence` MCP server to be active.

1. Read each KB document from `docs/knowledge-base/` and `docs/knowledge-base/DB-DOCS/`
2. Push to the corresponding Confluence page in the Acme Claims space
3. Report which pages were updated

If MCP is not available, state: "Confluence MCP is not active in this session. Run this mode from Devin Desktop where MCP is configured."

---

## OUTPUT FORMAT

```markdown
# KNOWLEDGE SYNC REPORT
## Mode: {{MODE}}
## Generated: {{DATE}}
## Branch: {{BRANCH_NAME}}

---

## CODE CHANGES DETECTED
| File | Change Type | Module |
|------|-------------|--------|
| [file path] | added/modified/deleted | [module] |

---

## KB UPDATE CHECKLIST
The following KB documents must be updated before this PR can be submitted:

| Priority | KB Document | Recommended Skill | Reason |
|----------|-------------|-------------------|--------|
| REQUIRED | docs/knowledge-base/MODULES/claims-web/api/03_TECHNICAL_REQUIREMENTS.md | `/app-trd api` | New API endpoint added |
| REQUIRED | docs/knowledge-base/DB-DOCS/ | `/app-knowledge-refresh post-pr` | SQL schema change detected |
| OPTIONAL | docs/knowledge-base/MODULES/claims-web/api/08_SECURITY_REVIEW.md | `/app-security-review api` | New model with PHI fields |

**Priority levels:**
- REQUIRED: PR should not be submitted without this KB update
- OPTIONAL: Update recommended but not blocking

---

## PR SUBMISSION CHECKLIST
- [ ] All REQUIRED KB documents updated
- [ ] KB changes included in the same branch as code changes
- [ ] PR description references the KB documents updated
- [ ] Tech lead notified that both code and KB are ready for review

---

## STALE KB GAPS (post-pr mode only)
| KB Document | Last Updated | Latest Code Commit | Gap |
|-------------|-------------|-------------------|-----|
| [document] | [date] | [date] | [days behind] |
```

## WHEN DONE

State: "Knowledge Sync COMPLETE"
State: "Update the KB documents listed above and include them in your PR branch before submission."
