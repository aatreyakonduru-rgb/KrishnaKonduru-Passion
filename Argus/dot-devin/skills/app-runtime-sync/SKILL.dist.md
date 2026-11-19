---
name: app-runtime-sync
description: >
  Git diff-based KB staleness checker. Compares committed source code changes
  (via git log/diff) against KB document timestamps to identify which KB docs
  are stale after a code change. Produces a staleness checklist for the
  knowledge refresh workflow. Fills the missing reference in app-knowledge-sync.
argument-hint: "[since_commit_or_date]  — defaults to last KB refresh date"
subagent: true
agent: discoverer
allowed-tools:
  - read
  - grep
  - glob
  - exec
visibility: internal
triggers:
  - user
  - model
---

# Skill: Acme Claims Runtime Sync (Git Diff → KB Staleness Checklist)

## Purpose

After a code change is merged, identify which KB documents in `docs/knowledge-base/` and `docs/knowledge-base/DB-DOCS/` need to be regenerated. Uses git history to find what changed, then maps changed source files to their corresponding KB documents.

This skill bridges the gap between code changes and KB maintenance — it tells you exactly which KB skills need to be re-run after a PR is merged.

---

## When to Run

- After a PR is merged to the main branch
- On its own, to see which KB documents a code diff has made stale. (`/app-knowledge-sync check` calls this skill itself, so there's no need to run it first.)
- When the user asks "what KB docs are stale?" or "what needs to be refreshed?"
- Called by `app-knowledge-sync` when checking post-PR KB state. This skill never calls it back.

---

## Step 1 — Determine the Baseline

Find the date/commit of the last KB refresh:

1. Take the last commit that changed the generated KB folders:
   `git log -1 --format='%H %cs' -- docs/knowledge-base/MODULES docs/knowledge-base/DB-DOCS docs/knowledge-base/ETL`
2. Cross-check the `generated_date` (or `## Generated:` line) in `docs/knowledge-base/MODULES/claims-web/*/00_DISCOVERY_REPORT.md` and `docs/knowledge-base/ETL/*/00_ETL_DISCOVERY_REPORT.md`, and use the older of the two dates
3. If a `since_commit_or_date` argument was provided: use that instead
4. If no baseline found: default to "last 30 days" and note this in the output

Record: `BASELINE_DATE = {date}` and `BASELINE_COMMIT = {hash or "unknown"}`

---

## Step 2 — Run Git Diff

Execute git commands to find what changed since the baseline:

```bash
# All changed files since baseline date
git log --since="{BASELINE_DATE}" --name-only --pretty=format: | sort -u | grep -v "^$"

# Or by commit hash:
git diff --name-only {BASELINE_COMMIT}..HEAD
```

Capture the list of changed source files.

---

## Step 3 — Map Changed Files to KB Documents

For each changed source file, identify which KB documents cover it:

| Changed Source File Pattern | Affected KB Documents | KB Skill to Re-run |
|---|---|---|
| `api/apps/{app}/api.py` | `docs/knowledge-base/MODULES/claims-web/{MODULE}/02_FUNCTIONAL_REQUIREMENTS.md`, `03_TECHNICAL_REQUIREMENTS.md`, `10_MODULE_IO_SUMMARY.md` | `/app-frd`, `/app-trd`, `/app-module-io` |
| `api/apps/{app}/service.py` | `docs/knowledge-base/MODULES/claims-web/{MODULE}/02_FUNCTIONAL_REQUIREMENTS.md`, `03_TECHNICAL_REQUIREMENTS.md` | `/app-frd`, `/app-trd` |
| `api/apps/{app}/schema.py` | `docs/knowledge-base/MODULES/claims-web/{MODULE}/03_TECHNICAL_REQUIREMENTS.md` | `/app-trd` |
| `api/apps/{app}/models.py` | `docs/knowledge-base/DB-DOCS/07_DB_SCHEMA_CATALOG.md` | `/db-discovery` (on Devin Desktop) |
| `api/acme_api/settings/base.py` | `docs/knowledge-base/MODULES/claims-web/{MODULE}/00_DISCOVERY_REPORT.md`, `03_TECHNICAL_REQUIREMENTS.md` | `/app-discovery`, `/app-trd` |
| `api/libs/auth.py` | `docs/knowledge-base/MODULES/claims-web/{MODULE}/08_SECURITY_REVIEW.md` | `/app-security-review` |
| `web/src/app/{page}/` | `docs/knowledge-base/MODULES/claims-web/{MODULE}/07_UI_SPECIFICATION.md`, `02_FUNCTIONAL_REQUIREMENTS.md` | `/app-ui-spec`, `/app-frd` |
| `web/src/_components/{comp}/` | `docs/knowledge-base/MODULES/claims-web/{MODULE}/07_UI_SPECIFICATION.md` | `/app-ui-spec` |
| `claims-etl/scripts/sql/*.sql` | `docs/knowledge-base/DB-DOCS/07_DB_SCHEMA_CATALOG.md`, `02_DB_TECHNICAL_REQUIREMENTS.md` | `/db-discovery` (Devin Desktop) |
| `claims-etl/scripts/python/*.py` | `docs/knowledge-base/ETL/claims-etl/00_ETL_DISCOVERY_REPORT.md` | `/etl-discovery` |
| `api/apps/*/sql_files/*.sql` | `docs/knowledge-base/MODULES/claims-web/{MODULE}/03_TECHNICAL_REQUIREMENTS.md` | `/app-trd` |

---

## Step 4 — Produce the Staleness Checklist

Output a structured checklist that the team can use to drive KB refresh:

```markdown
# KB Staleness Checklist
**Generated**: {today ISO8601}
**Baseline**: {BASELINE_DATE} ({BASELINE_COMMIT})
**Changed source files**: {n}

## Files Changed Since Last KB Refresh

### Source Changes
| File | Changed | Commit |
|------|---------|--------|
| api/apps/contract/api.py | 2026-07-10 | abc1234 |
| web/src/app/contractproviderconf/Contract/page.tsx | 2026-07-11 | def5678 |
| claims-etl/scripts/sql/V003__add_column.sql | 2026-07-12 | ghi9012 |

## KB Documents That Need Refresh

| KB Document | Status | Reason | Skill to Run | Environment |
|---|---|---|---|---|
| docs/knowledge-base/MODULES/claims-web/api/02_FUNCTIONAL_REQUIREMENTS.md | STALE | api.py changed (2026-07-10) | /app-frd CONTRACT | Devin Cloud |
| docs/knowledge-base/MODULES/claims-web/api/03_TECHNICAL_REQUIREMENTS.md | STALE | api.py + schema.py changed | /app-trd CONTRACT | Devin Cloud |
| docs/knowledge-base/DB-DOCS/07_DB_SCHEMA_CATALOG.md | STALE | V003__add_column.sql added | /db-discovery | Devin Desktop (Snowflake required) |
| docs/knowledge-base/MODULES/claims-web/web/07_UI_SPECIFICATION.md | STALE | page.tsx changed | /app-ui-spec web | Devin Cloud |

## Refresh Order (dependency-aware)

Run in this order to avoid stale inputs:

1. `/app-discovery CONTRACT` → updates 00_DISCOVERY_REPORT.md (foundation for all others)
2. `/db-discovery` (Devin Desktop) → updates DB schema docs
3. `/app-frd CONTRACT` → uses updated discovery
4. `/app-trd CONTRACT` → uses updated discovery + FRD
5. `/app-ui-spec CONTRACT` → uses updated FRD + TRD
6. `/app-security-review CONTRACT` → uses updated TRD

## No Refresh Needed

| KB Document | Reason |
|---|---|
| docs/knowledge-base/MODULES/claims-web/api/01_BUSINESS_REQUIREMENTS.md | No relevant source changes |
| docs/knowledge-base/MODULES/claims-web/api/04_USER_MANUAL.md | No relevant source changes |

## Action Items

- [ ] Run refresh skills listed above (see Refresh Order)
- [ ] Commit updated KB docs alongside next code PR
- [ ] Tech Lead to sign off on updated KB (KB_REFRESH gate)
```

---

## Rules

- NEVER modify KB docs in this skill — runtime-sync is read-only (checklist generation only)
- NEVER state a file changed without verifying via git output
- ALWAYS run git commands to get actual diff — do not estimate from memory
- ALWAYS note which refresh skills require Devin Desktop (Snowflake access) vs Devin Cloud
- If git is not accessible: note it and fall back to comparing file timestamps manually
- ALWAYS produce the Refresh Order section with correct dependency sequence
