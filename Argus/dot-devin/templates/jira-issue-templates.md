# Acme Claims Jira Ticket Templates

Copy-paste shapes for epics, stories and sub-tasks in the Acme Claims project. The machine-readable
version of the same rules — field IDs, required fields, the checks automation can run — is in
`.devin/rules/jira-ticket-standards.yaml`. Estimation lives in
`.devin/templates/complexity-matrix.yaml`.

Status: proposed, for Tech Lead and PO review. New tickets only; we are not going back over the
backlog.

## Two things to know before you use these

**Acceptance criteria have their own field in Acme Claims.** It is not part of the description — it is the
"Acceptance Criteria" field (`customfield_10003`), and it is on epics, stories and sub-tasks. Every
story in 26.4.1 and 26.4.2 has it filled in. Every sub-task still contains the untouched default
text "Please Enter Acceptance Criteria", which reads as real content to anything parsing the field,
so clear it or write something.

**Dev, SIT and UAT stay as separate tickets.** A ticket is one sprint's work; dev happens this
sprint, SIT next, UAT after. Nothing in these templates changes that. What they add is a link
between the three, because right now the only thing connecting them is a matching title with a
different suffix.

---

## Epic

One epic per capability or programme. It outlives sprints; it never carries a phase suffix.

```
Summary:      Contract Template — 2026
Epic Name:    Contract Template 2026
IT Team:      Acme-Claims-Web
Labels:       AI-Used | AI-NA
Fix Version:  (set when the target release is real; clear it if it moves)

Description:
Finance partners configure contract parameters by hand for every new contract, which
takes a day per contract and drifts between analysts. This epic gives them reusable
templates so a new contract starts from an approved set of parameters.

Detail: https://wiki.acme.example/spaces/ACMEWIKI/pages/<id>

Acceptance Criteria:
1. A finance analyst can create a contract from a saved template without re-entering
   any parameter that the template defines.
2. Template changes do not alter contracts already created from it.
3. Every template change is attributable to a user and a timestamp.
```

Why the description and the criteria are worth the two minutes: `/release-notes` and
`/spec-vs-delivery` read them to say whether the epic delivered what it promised, so the sprint
review summary is only ever as good as what is in those two fields. A name plus a Confluence link
leaves both with nothing to work from.

---

## Story — DEV

One user-visible increment, one phase, sized to fit one sprint.

```
Summary:         Platform - Contract Template create and save - DEV
Issue Type:      Story
Epic Link:       ACME-17808
Sprint:          26.4.3
Issue Priority:  Must Have
Story Points:    5
Components:      Contract Template
IT Team:         Acme-Claims-Web
Labels:          AI-Used
Links:           Depend → ACME-18817 (UI Package Number Definition table)

Description:
As a finance analyst, I want to save a set of contract parameters as a template so
that I can start a new contract from an approved baseline instead of re-entering
twelve fields.

Design: https://www.figma.com/proto/<...>
Spec:   https://wiki.acme.example/spaces/ACMEWIKI/pages/<id>
Screen: Provider → Contract Template

estimation_basis:
SCOPE=1/2 (Contained): one new screen, one new API, no schema change
RISK=1/2 (Moderate): writes to live contract config, reversible by delete
UNKNOWNS=0/2 (Clear): same pattern as Episode Hierarchy
DEPENDENCY=1/2 (Internal): needs ACME-18817 merged first
TESTABILITY=1/2 (Moderate): needs seeded contract data
total_score=4/10 → 3 pts
modifiers=[NONE]
final_points=3

Acceptance Criteria:
1. A user with the Finance Configure role can save the current parameter set as a
   named template; the name must be unique and non-blank.
2. Creating a contract from a template pre-fills all twelve parameters, and each
   remains editable before save.
3. Editing a template does not change contracts already created from it.
4. Given a template name that already exists, when the user saves, then the save is
   rejected with the message "Template name already in use".
5. A user without the Finance Configure role cannot see the Save as Template action.
```

Rules that matter:

- **Numbered, pass/fail criteria.** Use Given/When/Then when the behaviour depends on state, a plain
  assertion when it doesn't. `/eval` maps tests to these numbers and `/pr-readiness` holds the PR
  until each one is covered, so "should work correctly" or "as per design" stalls both.
- **Keep scope out of the AC field.** "Development to be Covered: build the API" is description
  material. A criterion says what will be true when the work is done.
- **Record the estimation basis.** Paste the scoring line in, so the number can be re-derived at
  grooming and `/story-splitter` knows which dimension to cut along.
- **Set Issue Priority.** Must / Should / Could have. It is what any sequencing or scope decision —
  ours or an agent's — gets made on.
- **If you clone, re-check the inherited fields.** Epic link, fix version, sprint and AC all arrive
  from the source ticket. A person skims past a wrong epic link; an agent takes it as fact and
  reports on it.

---

## Story — SIT

The next sprint's ticket for the same increment. Clone it if you like, but the AC change: they
describe the testing, not the build.

```
Summary:         Platform - Contract Template create and save - SIT
Issue Priority:  Must Have
Story Points:    2          (derived: impl 3 → SIT 1-2, per complexity-matrix.yaml)
Sprint:          26.4.4
Epic Link:       ACME-17808
Links:           Tests → ACME-<the DEV story>      ← this is the one people forget

Description:
SIT for Contract Template create and save. Dev story: ACME-<key>.
Test data: two provider groups with existing contracts, one without.

Acceptance Criteria:
1. All five acceptance criteria of ACME-<dev key> are covered by a qTest case and
   executed in SIT.
2. Regression pack for Contract Template passes.
3. Defects found are raised as Defect issues linked to ACME-<dev key> with severity set.
4. Test cases are uploaded to qTest and attached to this story.
```

Standard sub-tasks (already used consistently by QA — keep them):

```
SIT- Analysis and Test Case Preparation
SIT- Review Test Cases and Attach to story
SIT- Upload Testcases to qTest and Test Execution in qTest
SIT- Test Execution
SIT- Logging Defects and Link to user Story
SIT- Regression Testing
SIT- Sanity Testing
```

---

## Story — UAT

Always 1 point. If UAT looks complex, the acceptance criteria need work, not more points.

```
Summary:         Platform - Contract Template create and save - UAT
Story Points:    1
Sprint:          26.4.5
Links:           Relates → ACME-<the SIT story>

Description:
Business sign-off for Contract Template create and save. Dev: ACME-<key>. SIT: ACME-<key>.

Acceptance Criteria:
1. The PO or nominated finance user exercises each acceptance criterion of
   ACME-<dev key> in UAT and records pass or fail against it.
2. Any fail is raised as a Defect linked to the dev story before sign-off.
3. Sign-off is recorded as a comment naming the person and the date.
```

Standard sub-task:

```
UAT- Demo and sign-off
```

---

## Story — design or analysis

No product code, so the five estimation dimensions score it near zero. It has its own rule in the
complexity matrix: artefacts × stakeholder review rounds.

```
Summary:         EOC TIN Management wireframes - DESIGN
Story Points:    5
Issue Priority:  Should Have

Description:
Wireframe the EOC TIN Management tab under Provider Grouping so the dev story can be
estimated and built. Business contact: <name>.

estimation_basis:
story_type=DESIGN: 1 artefact (low → high fidelity), 2 review rounds → 5 pts
final_points=5

Acceptance Criteria:
1. High-fidelity wireframes exist in Figma for the TIN list, the add-TIN flow and the
   validation states, and the link is on this ticket.
2. Business has reviewed them and their comments are either applied or answered in the
   ticket.
3. A follow-up DEV story exists, linked here, estimated from the agreed wireframes.
```

---

## Story — spike

Time-boxed, not estimated. One point per intended day, five maximum.

```
Summary:         Router Gateway multi-client routing feasibility - SPIKE
Story Points:    3

Description:
Question: can the Router Gateway route by host, path, header and JWT claim without a
per-client deployment, and what does that cost us in latency?

Time-box: 3 days. If the question is still open when the box closes, that is the
finding — we extend deliberately or we stop.

estimation_basis:
story_type=SPIKE: time-boxed 3 day(s) → 3 pts, output=decision note + follow-up story
final_points=3

Acceptance Criteria:
1. A decision note in Confluence answers the question with evidence, or states plainly
   what is still unknown and why.
2. A follow-up implementation story exists and is linked here, to be estimated after
   this lands.
```

---

## Story — automation testing

Priced by scenario count, not by the size of the feature under test.

```
Summary:         Contract Template automation scripts - AUTOMATION
Story Points:    3

estimation_basis:
story_type=AUTOMATION: 5 scenario(s) → 3 pts
final_points=3

Acceptance Criteria:
1. Five scenarios are automated: create, create-duplicate-name, apply-to-contract,
   edit-template, permission-denied.
2. They run in the existing CI pipeline and pass three consecutive runs.
3. Test data setup and teardown are part of the script; no manual prep.
```

---

## Sub-task

The work breakdown inside one story, for the people doing it. Phase prefix, uppercase, consistent.

```
Summary:            DEV- Build contract template save API
Original Estimate:  6h          ← what it would take without AI help
Assignee:           <person>, before the sprint starts
Labels:             AI-Used      ← or AI-NA; every sub-task carries one

Description:
POST /api/contract-templates and GET /api/contract-templates. Validation of duplicate
names sits here, not in the UI.

Acceptance Criteria:   ← clear the default text or write a line; do not leave the placeholder
```

Standard DEV set (the 8-step pattern, see below):

```
DEV- Analysis of the story
DEV- Design
DEV- Backend implementation
DEV- Frontend implementation
DEV- Unit and integration testing
DEV- Code review and PR
DEV- Deployment readiness        ← release notes, runbook, monitoring
DEV- Documentation / KB update
```

`DEV- Performance validation` goes after the testing step when the story names a performance target
(response time, latency, load). Drop Backend or Frontend when the story doesn't touch that layer.

### The 8-step pattern

| Step | Where it lives |
|---|---|
| 1. Planning / Discovery | DEV- Analysis of the story |
| 2. Design / Architecture | DEV- Design |
| 3. Development | DEV- Backend implementation, DEV- Frontend implementation |
| 4. Unit & Integration Testing | DEV- Unit and integration testing |
| 5. Performance Validation | DEV- Performance validation, only with a performance target |
| 6. Regression / QA | The SIT story's seven sub-tasks |
| 7. UAT / Demo | The UAT story: UAT- Demo and sign-off |
| 8. Deployment Readiness | DEV- Deployment readiness |

The DEV story also carries DEV- Code review and PR and DEV- Documentation / KB update.

### Hours

The story carries an original estimate; the sub-task estimates under it add up to that number. When
a sub-task is added, split or dropped, the story estimate moves with it — reports and burndown read
the story's number, so a stale one is the one that gets believed.

Time is logged on sub-tasks only, never on the story, and against the sub-task the work actually
belonged to. Carried-over work keeps logging to its original sub-task rather than a fresh ticket, so
the full cost of a piece of work stays in one place. Estimate plus actual on the same sub-task is
what lets the hours column in `complexity-matrix.yaml` be re-derived from real work instead of from
how we use points.

### The AI label, and the productivity number

`AI-Used` or `AI-NA` goes on every sub-task, and the story carries `AI-Used` when any of its
sub-tasks do. Sub-task level is the level that can be measured — "AI helped with this story" has
nothing to compare against; "AI helped with this backend implementation sub-task" compares against
every other backend implementation sub-task.

The productivity figure is derived, not entered. Estimate the sub-task at what it would take without
AI, log the hours it actually took, and the gap is the finding — with AI-NA sub-tasks of the same
type as the control group. Reducing logged hours because a ticket is tagged AI-Used makes the number
an input rather than a measurement, and it does not survive being asked how it was produced.
Estimates set at grooming, before it is known whether AI will be used, are what keep the comparison
honest.

---

## Dependencies and order

When the business wants A, then B, then C, write it on the tickets:

```
Links:         ACME-A  blocks  ACME-B;  ACME-B  blocks  ACME-C
Description:   Order: ACME-A → ACME-B → ACME-C — finance signs off A before B is visible to providers
```

Argus writes both from "Set order" (or `blocked_by` on a new ticket) and will not move a
story into a sprint earlier than its blocker's.

## How to point a story

Points are complexity, risk and uncertainty — not hours. Score the five questions in
`complexity-matrix.yaml` (scope, data, integration, unknowns, testing: 0 / 1 / 2 each), add them up
and read the Fibonacci value off the table: 0–1 → 1, 2–3 → 2, 4–5 → 3, 6–7 → 5, 8–9 → 8, 10 → 13.
Unknowns = 2 with any other 2 → "needs grooming", no points until the spike is done. Score 10 or
more → split by scope (screen, layer, flow), never by phase. Hours follow from the points
(hours_reference) and are split across the sub-tasks; they are never entered first.

## Bug found in the sprint

Not a new ticket. Add a `DEV- fix <what>` sub-task under the story and log the hours there.

## Enhancement after the story is done

A new story under the same epic (specialty prefix, phase suffix, points), with a `Relates` link to
the story it extends. A closed story is never reopened for new scope.

## Production incident

A Defect with the `- PROD` suffix, the ServiceNow number in the description and an `incident-INC…`
label, Priority from the incident, Fix Version = the hotfix release.

## Defect

```
Summary:     Platform - Contract Template save accepts a duplicate name - SIT
Severity:    <set it — this is the field QA reporting runs on>
Links:       Defect → ACME-<story whose AC it breaks>

Description:
Steps: 1. Provider → Contract Template. 2. Save as Template, name "Standard EOC".
3. Save again with the same name.
Expected: rejected with "Template name already in use" (AC 4 of ACME-<key>).
Actual: second template saved; two templates share a name.
Environment: SIT, build <n>, data: provider group <id>.
```

---

## Definition of ready

Check at grooming, before the story enters a sprint.

1. Epic link points at the right epic — not whatever the clone source pointed at.
2. Description has the user story and the design or spec link.
3. Acceptance criteria are numbered, pass/fail, and free of "as discussed", "as per design", "etc".
4. Story points set, with the estimation basis recorded.
5. Issue Priority set.
6. Sibling phase tickets linked, or this is the first phase and the siblings don't exist yet.
7. Real dependencies linked with Blocks or Depend.
8. Sub-tasks exist with estimates and the right phase prefix, and those estimates sum to the story's.
9. AI-Used or AI-NA on the story and on every sub-task, exact case. Jira counts AI-USED as a different label.
10. Neither needs_grooming nor needs_split is still open.

## Definition of done

1. Every acceptance criterion has a test that exercises it, and it passes.
2. PR merged, `/pr-readiness` PASS.
3. Defects from this phase are closed or deferred with the decision recorded on the ticket.
4. The next phase's ticket exists and is linked.
5. Hours logged on the sub-tasks, against the work they belonged to.
6. KB updated if schema, API or documented behaviour changed.
