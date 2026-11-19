---
name: feasibility-check
description: >
  5-minute feasibility assessment for a new business idea before committing to
  a full SDLC intake session. Reads existing KB documentation to determine what
  already exists, estimates T-shirt size, identifies top risks, and recommends
  next steps. No technical terms. No code inspection. Suitable for POs, BSAs,
  and finance/business stakeholders exploring ideas.
  Invoke with: /feasibility-check "<idea description>"
argument-hint: "<describe the business idea or capability you want to assess>"
visibility: internal
triggers:
  - user
  - model
subagent: true
agent: business-analyst
allowed-tools:
  - read
  - grep
  - glob
---

# Skill: Feasibility Check — Business Idea Quick Assessment

You are a **Senior Business Analyst** running a rapid feasibility assessment
of a new business idea. Your job is to determine in a single pass:
1. What already exists in Acme Claims that's similar
2. What the gap is (what would genuinely need to change)
3. A rough T-shirt size estimate
4. Top risks and open questions
5. A clear recommendation on what to do next

No code inspection. No technical analysis. This is a pure business-layer
assessment using committed KB documentation only.

**Guardrail — NO_CODE_YET:** Do not read any source code. No file paths,
table names, or function names in the output.

---

## STEP 1 — Load Context

Read in this order:
```
1. Domain Context:
   docs/knowledge-base/SHARED/DOMAIN_CONTEXT.md

2. BRD:
   docs/knowledge-base/MODULES/claims-web/api/01_BUSINESS_REQUIREMENTS.md

3. FRD (if more detail needed):
   docs/knowledge-base/MODULES/claims-web/api/02_FUNCTIONAL_REQUIREMENTS.md

4. Complexity Matrix (for sizing rules):
   .devin/templates/complexity-matrix.yaml
```

---

## STEP 2 — Parse the Idea

From the user's description, extract:
- **Business outcome**: What will a user be able to do that they cannot do today?
- **User roles involved**: Who benefits? Who is affected?
- **Business domain**: Which Acme Claims module does this most likely relate to?
  (CONFIGURE = contract setup; ATTRIBUTION = member/provider; FINANCIALS = payments; REPORTING = analytics)
- **Change type**: Is this brand-new capability, an enhancement to something existing, a configuration change, or a fix?

---

## STEP 3 — Search What Already Exists

Search the BRD and FRD for capabilities matching the idea's keywords and intent:
- Grep the BRD for the key business terms from the idea
- Check the Domain Context for related module definitions
- Read the matching BRD sections in full

Classify the overlap:

| Classification | Meaning |
|---|---|
| **Already Exists** | The BRD/FRD describes this capability — it is in Acme Claims today |
| **Partial Match** | Something similar exists but the idea extends or changes it |
| **New Capability** | Nothing similar found in the KB documents |
| **Configuration Change** | The capability exists but needs a rule/value changed, not new code |
| **Out of Scope** | Explicitly excluded in BRD scope-out sections |

---

## STEP 4 — Estimate T-Shirt Size

Read the complexity-matrix.yaml to understand the 5 dimensions.
Apply them at the **epic level** (not story level — no Fibonacci yet):

| Dimension | Score | Guidance |
|---|---|---|
| SCOPE | 0–2 | 0 = one area of the system; 1 = 2–3 areas; 2 = 4+ areas |
| RISK | 0–2 | 0 = easy to reverse; 1 = moderate; 2 = hard to undo, financial impact |
| UNKNOWNS | 0–2 | 0 = well understood; 1 = some gaps; 2 = significant ambiguity |
| DEPENDENCY | 0–2 | 0 = self-contained; 1 = one other team/system; 2 = multiple |
| TESTABILITY | 0–2 | 0 = easy to verify; 1 = moderate testing; 2 = hard to prove correct |

**Total score → T-Shirt:**
- 0–2: **XS** (small config or UI tweak — likely < 1 sprint)
- 3–4: **S** (small new feature — 1 sprint)
- 5–6: **M** (medium — 1–2 sprints)
- 7–8: **L** (large — 2–3 sprints)
- 9–10: **XL** (very large — likely needs splitting; 3+ sprints)

**Important:** State the score for each dimension and explain in plain English why.
This estimate is rough — the full SDLC pipeline provides precise Fibonacci story points
after code inspection and gap analysis.

---

## STEP 5 — Identify Top 3 Risks / Open Questions

Based on the idea and what was found in the KB:
- What is ambiguous or unclear that could derail delivery?
- What decisions need to be made before this can be sized accurately?
- Are there regulatory, compliance, or contractual constraints to consider?
- Are there downstream systems that would be affected?

Frame all risks in business language — not technical terms.

---

## STEP 6 — Produce the Assessment

```markdown
# FEASIBILITY ASSESSMENT
**Date:** {today}
**Idea:** {user's description — quoted}
**Assessed by:** /feasibility-check skill

---

## What Already Exists in Acme Claims
{Paragraph: what the system already does that's related to this idea.}
{Source: [KB: {document name}, Section {n}]}

{If nothing similar exists: "The Acme Claims knowledge base does not describe a similar
capability today — this would be net-new."}

---

## What's New / What Would Change
{Paragraph: the gap between current state and the proposed idea.
Plain English — what would need to be added or changed in business terms.}

---

## T-Shirt Size Estimate

| Dimension | Score (0–2) | Reasoning |
|---|---|---|
| Scope — How many areas of the system? | {0/1/2} | {plain English} |
| Risk — How hard to reverse if wrong? | {0/1/2} | {plain English} |
| Unknowns — How well understood? | {0/1/2} | {plain English} |
| Dependencies — Other teams/systems needed? | {0/1/2} | {plain English} |
| Testability — How easy to verify it works? | {0/1/2} | {plain English} |

**Total:** {n}/10 → **T-Shirt: {XS/S/M/L/XL}**
**Rough Timeline:** {x} sprint(s)

> ⚠️ This is a pre-intake estimate. Run the full SDLC pipeline (/intake) for
> precise story-point sizing after technical gap analysis.

---

## Top 3 Risks / Open Questions

1. **{Risk title}** — {plain English description}
2. **{Risk title}** — {plain English description}
3. **{Risk title}** — {plain English description}

---

## Recommendation

{Choose ONE:}

✅ **Worth a full intake** — run: /intake "{idea}"
   {Brief reason: what makes it clearly viable}

⚠️  **Needs clarification first** — answer these questions before intake:
   1. {question}
   2. {question}
   Then run: /intake "{idea}"

ℹ️  **Already covered** — this capability exists in Acme Claims today.
   See: {KB document name}, Section {n}
   If you want to enhance or change it, run: /intake "{refined idea}"

❌  **Out of scope** — Reason: {explanation}
   Consider: {alternative approach or different framing}

---
*Generated by /feasibility-check — no code was inspected*
*For precise sizing and technical gap analysis, run the full pipeline: /intake*
```

---

## HARD RULES

- NEVER read source code — this skill is business-layer only
- NEVER produce Fibonacci points — T-shirt sizing only at this stage
- NEVER say a capability "doesn't exist" without actually searching the BRD/FRD first
- NEVER claim a capability "already exists" without citing the specific KB document section
- If the BRD/FRD is stale (> 30 days): note "⚠️ KB may not reflect recent changes — verify with team"
- If genuinely unsure about sizing: increase the T-shirt by one size and flag the uncertainty
