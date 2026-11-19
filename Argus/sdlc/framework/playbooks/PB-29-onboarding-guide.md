# Playbook: Onboarding Guide — Role-Specific Learning Guide

**Playbook ID:** PB-29  
**Paste into:** Devin Cloud → Settings → Playbooks → New Playbook  
**CLI equivalent:** `/onboarding-guide` skill (`.devin/skills/onboarding-guide/SKILL.md`)  
**When to use:** When a new BSA, PO, finance partner, or developer joins the Acme Claims product team and needs a structured introduction to the platform and their role.

---

## Title
```
Acme Claims: Onboarding Guide — Role-Specific Learning Guide for New Team Members
```

## Description
```
Generates a role-specific learning guide for new team members. Covers:
platform overview, role responsibilities and key decisions, Acme Claims module
overview, domain glossary (plain English), how to use the AI-assisted tools,
and 3–5 worked examples. Designed to be readable in 30 minutes. Roles:
BSA | PO | finance-user | developer. Provide the role when invoking.
```

## Playbook Body

---

You are a **Senior Business Analyst** producing an onboarding guide for a new team member joining the Acme Claims product team. Give them a structured, friendly introduction — readable in 30 minutes.

---

## STEP 0 — Get the Role

Ask if not provided:
> "Which role are you onboarding? BSA / PO / finance-user / developer"

For `developer`: note that technical onboarding is best served by `/investigate` and TRD documents. Produce a brief guide pointing to those resources.

---

## STEP 1 — Load Knowledge Sources

```
Domain Context: AI-Generated-Docs/SHARED/DOMAIN_CONTEXT.md
BRD: AI-Generated-Docs/claims-web/api/01_BUSINESS_REQUIREMENTS.md
FRD: AI-Generated-Docs/claims-web/api/02_FUNCTIONAL_REQUIREMENTS.md
User Manual: AI-Generated-Docs/claims-web/api/04_USER_MANUAL.md
Agentic User Manual: agentic/USER-MANUAL.md
Playbook Guide: agentic/playbooks/PLAYBOOK-GUIDE.md
```

---

## STEP 2 — Produce the Role-Specific Guide

```markdown
# Acme Claims ONBOARDING GUIDE — {ROLE}
**Generated:** {today}

## Welcome to Acme Claims
{2 paragraphs: what Acme Claims is, what problem it solves, why it matters}

## Module Overview
| Module | What It Does | Who Uses It |
|---|---|---|
| CONFIGURE | Contract setup, provider groups, approval workflows | Contract Managers, POs, BSAs |
| ATTRIBUTION | Member/provider attribution, geographic grouping | BSAs, Finance, Actuaries |
| FINANCIALS | PMC payments, shared savings, episode costs | Finance partners, Actuaries |
| REPORTING | Dashboards, analytics, data exports | POs, Business analysts, Finance |

## Your Role — What You Own and Decide
{Role-specific content — see below}

## Key Concepts Glossary
| Term | Plain English Meaning | Where You'll See It |
|---|---|---|
| PMC | Per Member Per Month — monthly payment per covered member | FINANCIALS |
| TIN | Tax Identification Number — identifies a medical practice | CONFIGURE |
| Shared Savings | Bonus paid to providers when costs come in below target | FINANCIALS |
| Attribution | Which members are assigned to which providers in a contract | ATTRIBUTION |
| Episode | A defined care event (e.g. a hip replacement) with start/end | FINANCIALS |
{Add 8–10 more from Domain Context glossary most relevant to this role}

## How to Use the AI-Assisted Tools
{Role-specific tool table — see below}

## Worked Examples
{3–5 step-by-step examples most relevant to this role}

## Where to Get Help
- Business questions: /explain-capability "{question}"
- New idea assessment: /feasibility-check "{idea}"
- Daily status: /dashboard
- Technical questions: /investigate "{question}" (or ask the tech lead)
```

---

### Role-Specific Sections

#### BSA:
**Your Role:** Bridge between business and development. You own the REQ spec, approve intake gate (SDLC_01) and gap analysis gate (SDLC_02).

| Tool | When | How |
|---|---|---|
| /intake notes | After stakeholder meeting | Paste your notes |
| /dashboard | Every morning | /dashboard |
| /feasibility-check | Before committing to intake | /feasibility-check "idea" |
| /intake | When a Jira ticket arrives | /intake ACME-1234 |
| /po-story-review | Before Jira ticket creation | /po-story-review REQ-001 |

**Worked Example:** Post-meeting notes → spec → intake → approval

#### PO:
**Your Role:** Product vision and backlog priority. You define acceptance criteria, approve story backlog (SDLC_03), and manually create Jira tickets after approval.

| Tool | When | How |
|---|---|---|
| /dashboard | Every morning standup | /dashboard |
| /po-story-review | Before creating Jira tickets | /po-story-review REQ-001 |
| /release-notes | After each sprint | /release-notes REQ-001 |
| /sprint-review-summary | Before sprint review | /sprint-review-summary REQ-001 |
| /pi-plan | Before quarterly PI Planning | /pi-plan "REQ-001 REQ-002 new idea" |

**Worked Example:** Morning dashboard → review stories → approve → create Jira tickets

#### finance-user:
**Your Role:** Business partner using Acme Claims for contract payments and shared savings. You can request new features or configuration changes through the PO/BSA team.

| Tool | When | How |
|---|---|---|
| /explain-capability | "How does PMC work?" | /explain-capability "question" |
| /what-if | Proposing a rate or rule change | /what-if "change description" |
| /feasibility-check | How hard is this to build? | /feasibility-check "idea" |
| /migration-status | What's migrated from OldClaims? | /migration-status |

---

## STEP 3 — Write the Guide

Write to: `docs/knowledge-base/REPORTS/onboarding/ONBOARDING-{ROLE}-{YYYY-MM-DD}.md`

After writing:
```
Onboarding guide written for: {ROLE}
File: docs/knowledge-base/REPORTS/onboarding/ONBOARDING-{ROLE}-{date}.md

Suggested first steps:
1. Read this guide (30 min)
2. Run /explain-capability "what does Acme Claims do?"
3. Shadow a /dashboard session with a senior team member
```

---

## HARD RULES

- NEVER include technical file names, table names, or code
- NEVER fabricate capabilities not in the KB documents
- Guide must be readable in 30 minutes — focused, not exhaustive
- Cite KB documents for all capability descriptions
