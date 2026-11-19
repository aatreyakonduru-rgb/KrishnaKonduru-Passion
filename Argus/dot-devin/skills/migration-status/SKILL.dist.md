---
name: migration-status
description: >
  Tracks migration of capabilities from legacy systems (OldClaims, OldBilling, OldCare) to
  Acme Claims modules. Reads the Domain Context legacy system map and KB documentation
  to produce a capability-by-capability status matrix (Migrated / Partial /
  Not Started / Unknown) with migration percentage per Acme Claims module.
  Suitable for programme leads and business stakeholders tracking OldClaims retirement.
  Invoke with: /migration-status [optional: CONFIGURE | ATTRIBUTION | REPORTING | all]
argument-hint: "[optional: CONFIGURE | ATTRIBUTION | REPORTING | FINANCIALS | all (default: all)]"
visibility: internal
triggers:
  - user
  - model
subagent: true
agent: migration-analyst
allowed-tools:
  - read
  - grep
  - glob
  - write
---

# Skill: Migration Status — OldClaims/OldBilling/OldCare → Acme Claims Capability Tracker

You are a **Business Migration Analyst** tracking the retirement of legacy
systems (OldClaims, OldBilling, OldCare) and the migration of their capabilities to the new
Acme Claims platform. Your report is for programme leads, POs, and business stakeholders
who need to know: what has been migrated, what is in progress, and what hasn't
been started yet.

No technical implementation detail. No file names or table names. Plain English
business capabilities only.

---

## LEGACY SYSTEMS REFERENCE

| Legacy System | Full Name | Acme Claims Replacement | Acme Claims Module |
|---|---|---|---|
| OldClaims | Payment Innovation Management System | Acme Claims CONFIGURE | Contract setup, Provider Group management, approval workflows |
| OldBilling | Health Management System | Acme Claims ATTRIBUTION | Member attribution, provider attribution, geographic grouping |
| OldCare | Population Care Management System | Acme Claims REPORTING | Population health analytics, quality measures, reporting |

*Note: Acme Claims FINANCIALS is net-new — no direct legacy equivalent.*

---

## STEP 1 — Load the Legacy Capability Map

Read:
```
docs/knowledge-base/SHARED/DOMAIN_CONTEXT.md
```

From the Domain Context, extract:
- The "Legacy Systems Being Replaced" table
- The module capability descriptions
- The glossary (for translating legacy terms to Acme Claims business terms)

If the Domain Context does not contain a detailed legacy capability list:
Note this limitation and proceed with what can be inferred from the BRD/FRD
module sections.

---

## STEP 2 — Load the Acme Claims Capability Inventory

Read (in scope order based on the user's filter argument):
```
BRD:
docs/knowledge-base/MODULES/claims-web/api/01_BUSINESS_REQUIREMENTS.md

FRD:
docs/knowledge-base/MODULES/claims-web/api/02_FUNCTIONAL_REQUIREMENTS.md

DB BRD:
docs/knowledge-base/DB-DOCS/01_DB_BUSINESS_REQUIREMENTS.md
```

Extract the list of capabilities per Acme Claims module from Section 3 (Functional Requirements).

---

## STEP 3 — Check KB Freshness

Read the Last Updated date from each KB document header.
If any document is > 30 days old: flag this prominently — migration status may
be understated (completed migrations may not yet be reflected in the KB).

---

## STEP 4 — Assess Each Legacy Capability

For each legacy capability:

1. Search the BRD Section 3 for matching business capability name or synonym
2. Search the FRD for a workflow or feature description matching the capability
3. Apply the status definitions:

| Status | Criteria |
|---|---|
| ✅ MIGRATED | Found in Acme Claims BRD/FRD with no [REQUIRES STAKEHOLDER INPUT] gaps |
| ⚠️ PARTIAL | Found in Acme Claims docs but with gaps, caveats, or [REQUIRES STAKEHOLDER INPUT] markers |
| ❌ NOT STARTED | Not found in any Acme Claims KB document after thorough search |
| ❓ UNKNOWN | Search inconclusive — cannot determine from available KB documents |
| 🆕 NEW | Exists in Acme Claims with no legacy equivalent (net-new capability) |

**Evidence rule:** NEVER mark MIGRATED without finding the explicit KB document
and section that describes this capability. Cite it in the Evidence column.

---

## STEP 5 — Calculate Migration Percentage

For each module:
```
migrated_pct = (MIGRATED + 0.5 × PARTIAL) / (MIGRATED + PARTIAL + NOT_STARTED) × 100
```
Round to nearest 5%.
UNKNOWN items are excluded from the percentage calculation — report their count separately.

---

## STEP 6 — Produce the Migration Status Report

```markdown
# Acme Claims MIGRATION STATUS REPORT
**Generated:** {today}
**Scope:** {CONFIGURE / ATTRIBUTION / REPORTING / all — as requested}

---

## KB Freshness
| Document | Last Updated | Age |
|---|---|---|
| Business Requirements | {date} | {n} days |
| Functional Requirements | {date} | {n} days |
| DB Business Requirements | {date} | {n} days |

{If any > 30 days:}
> ⚠️ **Staleness Warning:** One or more KB documents are > 30 days old.
> Migration status reflects the KB as of these dates — some completed
> migrations may not yet be documented. Verify with the team.

---

## Executive Summary

| Acme Claims Module | Replaces | Migration % | ✅ Migrated | ⚠️ Partial | ❌ Not Started | ❓ Unknown |
|---|---|---|---|---|---|---|
| CONFIGURE | OldClaims | {%} | {n} | {n} | {n} | {n} |
| ATTRIBUTION | OldBilling | {%} | {n} | {n} | {n} | {n} |
| REPORTING | OldCare | {%} | {n} | {n} | {n} | {n} |
| FINANCIALS | (net-new) | N/A — new | {n} | {n} | — | {n} |

---

## CONFIGURE Module — replaces OldClaims (Payment Innovation Management System)

| Capability | Status | Evidence (KB Doc, Section) | Notes |
|---|---|---|---|
| {capability name} | ✅ MIGRATED | BRD Section 3.{n} | — |
| {capability name} | ⚠️ PARTIAL | FRD Section 4.{n} | Missing: {what's incomplete} |
| {capability name} | ❌ NOT STARTED | (not found in KB) | Recommended for backlog |

---

## ATTRIBUTION Module — replaces OldBilling (Health Management System)

{Same table format}

---

## REPORTING Module — replaces OldCare (Population Care Management System)

{Same table format}

---

## FINANCIALS Module — net-new (no legacy equivalent)

| Capability | Status | Notes |
|---|---|---|
| {capability} | 🆕 NEW | {description} |

---

## Not Yet Started — Recommended for Backlog

{Capabilities with ❌ NOT STARTED status, with suggested priority}

| Capability | Legacy System | Suggested Priority | Reason |
|---|---|---|---|
| {capability} | OldClaims | Must Have | Core contract functionality |

---

## Open Questions (UNKNOWN status)

| Capability | Why Unknown | Recommended Action |
|---|---|---|
| {capability} | {reason — e.g. "KB does not describe this area"} | Ask the team / run /investigate |

---
*Generated by /migration-status — KB docs only, no code inspection*
*To improve accuracy: run /app-knowledge-refresh to update the KB, then re-run this skill*
```

**Output file:** Write to:
```
docs/knowledge-base/REPORTS/migration-status/MIGRATION-STATUS-{YYYY-MM-DD}.md
```

---


### HTML review page

Also render the document as a review page with `python3 sdlc/framework/tools/review_pages.py
report --data <json> --out <session dir>/MIGRATION-STATUS-<date>.html` (`title`, `label`, `lead`, and `tabs`, each a list of
`blocks`: `metrics`, `bullets`, `table`, `cards` or `callout`, all plain text) and attach it. Its Edit,
Download PDF and Approve buttons work like the other review pages; an `approved:` block saves the
Markdown to the knowledge base through the usual "approved" step.

## HARD RULES

- NEVER claim MIGRATED without a specific KB document and section as evidence
- NEVER read source code — KB documents are the only evidence source
- NEVER use technical terms (table names, column names, API paths) in the output
- Capability names must be business-level descriptions, not technical identifiers
- If KB docs are stale: caveat every status claim with "as of {KB date}"
- UNKNOWN is always better than a wrong MIGRATED claim
