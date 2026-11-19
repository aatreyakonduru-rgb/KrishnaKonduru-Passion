# Workflow: Intake — Requirement Intake & Clarification

## Goal
Capture and clarify a new requirement to produce an approved, unambiguous specification.

## Agent
**Intake Agent** (role: Senior BSA)

## Prerequisites
- Raw requirement received (Jira ticket, email, or stakeholder ask)
- Domain context loaded (`DOMAIN_CONTEXT.md`)

## Steps

### 1. Capture Requirement
**Skill**: `requirement-capture`
- Input: Raw requirement text
- Output: Initial draft of `REQ-{id}-SPEC.md`
- Action: Extract title, description, and initial scope

### 2. Generate Clarifying Questions
**Skill**: `clarifying-questions-generator`
- Input: Initial draft
- Output: List of clarifying questions
- Action: Identify ambiguities, missing details, and potential blockers

### 3. Wait for Human Answers
**Human Gate**: BSA answers all clarifying questions
- Timeout: 48 hours
- Deliverable: Answered questions appended to `REQ-{id}-SPEC.md`

### 4. Define Acceptance Criteria
**Skill**: `acceptance-criteria-definer`
- Input: Requirement + answered questions
- Output: Acceptance criteria section in `REQ-{id}-SPEC.md`
- Action: Define measurable, testable acceptance criteria

### 5. Map Scope Boundaries
**Skill**: `scope-boundary-mapper`
- Input: Requirement + acceptance criteria
- Output: Scope-in and scope-out sections in `REQ-{id}-SPEC.md`
- Action: Clearly define what is in scope and what is explicitly out of scope

### 6. Submit for Approval
**Human Gate**: `SDLC_01_INTAKE_CLARIFICATION`
- Required Role: BSA
- Artifacts to Review: `REQ-{id}-SPEC.md`
- Approval Criteria:
  - All clarifying questions answered
  - Acceptance criteria defined
  - Scope boundaries clear
  - No blockers remain
- Timeout: 48 hours

## Outputs
- `REQ-{id}-SPEC.md` (approved)
- Provenance log entry

## Next Workflow
**Research** (`workflows/research.md`)

## Example
**Input**: "Add provider location filter to Contract UI search"

**Output**: `REQ-001-SPEC.md`
```markdown
# REQ-001: Add Provider Location Filter to Contract UI Search

## Description
Enable users to filter contract search results by provider location (city, state, or ZIP code).

## Acceptance Criteria
1. User can select location filter from dropdown (city, state, ZIP)
2. Search results update dynamically when location filter is applied
3. Location filter works in combination with existing TIN/NPI filters
4. Performance: Search returns results within 2 seconds for up to 10,000 providers

## Scope In
- Add location filter dropdown to Contract Search UI
- Extend API endpoint to accept location parameter
- Add LOCATION_CD column to VBC_UI_PRVDR_GRP table

## Scope Out
- Geocoding or map-based location search (future enhancement)
- Historical location tracking (use current location only)

## Blockers Resolved
- Q: What location granularity? A: City, state, or ZIP code
- Q: How to handle providers with multiple locations? A: Show all matches

## Approver
BSA: [Name]

## Approval Timestamp
2026-09-03 10:00:00 UTC
```

## Hooks
- **Pre-check**: Verify domain context is loaded
- **Provenance log**: Record intake session (user, timestamp, questions, answers, approval)
- **Approval gate**: Enforce BSA approval before proceeding to Research
