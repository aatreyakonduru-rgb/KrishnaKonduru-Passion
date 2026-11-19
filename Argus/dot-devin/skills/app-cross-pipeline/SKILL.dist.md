---
name: app-cross-pipeline
description: Check the UI, DB and ETL documents against each other (API-to-table, ETL-to-table, DataSync, downstream consumers, security) and merge their open questions. Runs at the end of /kb-build all.
argument-hint: "[<stage>]"
allowed-tools:
  - read
  - grep
  - glob
  - edit
visibility: internal
triggers:
  - user
  - model
---

You are the Acme Claims Cross-Pipeline Orchestrator. Your job is to coordinate documentation across UI, Database, and ETL pipelines to ensure end-to-end consistency.

## SCOPE

This skill checks documents; it builds none. `/kb-build all` builds them into a staging folder and
runs this skill at the end. Run on its own, it checks the live KB.

**Invocation:** `/app-cross-pipeline [<stage>]`. `<stage>` is the staging folder to check. Without
it, the paths below are read from the live KB. With it, read each one from `<stage>` first and
fall back to the live copy.

Load the domain context first (`product.domain_context` in `.devin/rules/kb-profile.yaml`).

## CROSS-PIPELINE CHECKS

### Step 1: Cross-Reference Validation
Perform cross-pipeline consistency checks:
- Verify UI API endpoints match DB table access patterns
- Verify ETL DataSync processes match UI staging tables
- Verify downstream consumer mappings are consistent
- Verify security findings are coordinated across all pipelines

### Step 2: Consolidated Validation Log
Merge all validation logs:
- Combine open questions from UI, ETL, and DB pipelines
- Deduplicate cross-cutting questions
- Route to appropriate owners
- Generate consolidated report

## CROSS-REFERENCE CHECKS

### Check 1: API-to-Table Mapping
Verify that every API endpoint in UI documentation references the correct DB tables:
- Read: `docs/knowledge-base/MODULES/claims-web/api/03_TECHNICAL_REQUIREMENTS.md` (API surface)
- Read: `docs/knowledge-base/DB-DOCS/02_DB_TECHNICAL_REQUIREMENTS.md` (table inventory)
- Validate: All referenced tables exist in schema
- Flag: Orphaned tables or missing references

### Check 2: ETL-to-Table Mapping
Verify that ETL scripts reference correct DB tables:
- Read: `docs/knowledge-base/ETL/claims-etl/03_ETL_TECHNICAL_REQUIREMENTS.md` (ETL data flows)
- Read: `docs/knowledge-base/DB-DOCS/02_DB_TECHNICAL_REQUIREMENTS.md` (table inventory)
- Validate: All ETL targets exist in schema
- Flag: Orphaned ETL targets or missing ETL for tables

### Check 3: DataSync Consistency
Verify DataSync process matches UI staging tables:
- Read: Domain context (DataSync description)
- Read: `docs/knowledge-base/MODULES/claims-web/api/03_TECHNICAL_REQUIREMENTS.md` (UI staging tables)
- Read: `docs/knowledge-base/DB-DOCS/02_DB_TECHNICAL_REQUIREMENTS.md` (FeedFile output tables)
- Validate: DataSync mapping is complete and accurate
- Flag: Missing DataSync mappings

### Check 4: Downstream Consumer Mapping
Verify downstream consumer mappings are consistent:
- Read: Domain context (downstream consumers table)
- Read: `docs/knowledge-base/DB-DOCS/01_DB_BUSINESS_REQUIREMENTS.md` (integration requirements)
- Read: `docs/knowledge-base/MODULES/claims-web/api/01_BUSINESS_REQUIREMENTS.md` (API consumers)
- Validate: All mappings are consistent across documents
- Flag: Inconsistent consumer references

### Check 5: Security Coordination
Verify security findings are coordinated:
- Read: `docs/knowledge-base/MODULES/claims-web/api/08_SECURITY_REVIEW.md` (backend security)
- Read: `docs/knowledge-base/MODULES/claims-web/web/08_SECURITY_REVIEW.md` (frontend security)
- Read: `docs/knowledge-base/DB-DOCS/06_DB_SECURITY_REVIEW.md` (database security)
- Validate: Security posture is consistent across layers
- Flag: Conflicting security controls

## OUTPUT FORMAT

Generate a cross-pipeline execution summary:

```markdown
# CROSS-PIPELINE EXECUTION SUMMARY
## Project: {{PROJECT_SCOPE}}
## Started: {{START_TIME}}
## Completed: {{END_TIME}}
## Duration: {{DURATION}}

---

## PIPELINE RESULTS
| Pipeline | Stage | Status | Documents Generated |
|----------|-------|--------|---------------------|
| UI (Django) | Full Pipeline | ✅ | <n> documents |
| UI (Next.js) | Full Pipeline | ✅ | <n> documents |
| ETL | Full Pipeline | ✅ | <n> documents |
| DB | Full Pipeline | ✅ | <n> documents |

## CROSS-REFERENCE CHECKS
| Check | Status | Issues Found | Resolution |
|-------|--------|--------------|------------|
| API-to-Table Mapping | ✅/❌ | | |
| ETL-to-Table Mapping | ✅/❌ | | |
| DataSync Consistency | ✅/❌ | | |
| Downstream Consumer Mapping | ✅/❌ | | |
| Security Coordination | ✅/❌ | | |

## CONSOLIDATED OPEN QUESTIONS
| # | Pipeline | Document | Section | Question | Assignee | Priority |
|---|----------|----------|---------|----------|----------|----------|

## CONSOLIDATED VALIDATION LOG
[Combined validation log from all pipelines]

## RECOMMENDATIONS
1. [Recommendation 1]
2. [Recommendation 2]
3. [Recommendation 3]

## NEXT STEPS
1. Review cross-pipeline consistency issues
2. Resolve consolidated open questions
3. Update all SESSION_STATE.md files
4. Commit all documentation to version control
```

## WHEN DONE

State: "Cross-Pipeline Documentation COMPLETE for {{PROJECT_SCOPE}}"
