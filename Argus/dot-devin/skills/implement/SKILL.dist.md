---
name: implement
description: >
  SDLC Stage 5 — Code Generation, Dev Environment Testing, PR Creation, AI Verification.
  Orchestrates the full implementation pipeline for one story: reads the approved routing
  map and insertion points, generates code changes at the verified locations, runs
  the dev test suite, updates KB artifacts if schema/API changed, runs the
  /pr-readiness check (AI verification), and presents the result for SDLC_05
  code review. Invoke with: /implement REQ-{id} STORY-{n}
  Source agent: .devin/agents/implement.agent.yaml
argument-hint: "<REQ-ID> <STORY-ID>  e.g. REQ-TIN-001 STORY-003"
visibility: internal
triggers:
  - user
  - model
subagent: true
allowed-tools:
  - read
  - write
  - edit
  - grep
  - glob
---

# Skill: Implement Orchestrator (SDLC Stage 5)

Background reading: `sdlc/framework/workflows/implement.md` (the longer stage procedure; where it and this skill differ, this skill is the one to follow).

You are a **Developer** implementing one Acme Claims story. Your job is to
generate code changes at the exact insertion points identified by the Plan agent,
verify them, and produce a clean PR-ready state with a passing AI verification report.

Use `.devin/rules/gate-presentation.md` for SDLC_05 presentation, approval
options, signer identity, role checks, and approval recording.

Source agent spec:
```
.devin/agents/implement.agent.yaml
```
Child skills (execute logic inline):
```
insertion-locator  (re-verify line numbers before writing)
.devin/skills/pr-readiness/SKILL.md              (AI verification — run at end)
.devin/rules/secure-coding.md                   (all code must comply)
.devin/rules/pii-handling.md
.devin/rules/data-access.md
```

---

## INPUTS

Parse arguments: `REQ_ID` and `STORY_ID`.

---

## SESSION DIRECTORY

```
sdlc/framework/context/session/{OWNER}/{REQ_ID}/
`{OWNER}` is resolved per `.devin/rules/session-isolation.md`.
```

## SOURCE CODE

```
api/
web/
../claims-etl/scripts/
../claims-etl-glue/
```

## KB CONTEXT (to update after implementation if changed)

```
docs/knowledge-base/DB-DOCS/DB_TABLE_REGISTRY.yaml
docs/knowledge-base/MODULES/claims-web/api/10_ENDPOINT_REGISTRY.yaml
docs/knowledge-base/MODULES/claims-web/web/12_COMPONENT_REGISTRY.yaml
```

---

## STEP 0 — Gate Check

**Trace lines (Argus):** print `[SDLC] kb <path> — loaded: <why>` / `skipped: <why>`, `[SDLC] rule <path> — loaded|deferred: <why>`, `[SDLC] chain DC-… — …` and `[SDLC] decision … — …` as each file is opened, skipped or each choice made, per `.devin/rules/workbench-trace.md` — here: a `kb` line for `insertion-points.yaml`, the routing map and each KB registry in KB CONTEXT read or skipped; a `rule … loaded` line for each security rule; a `kb` line for every source file opened at an insertion point (repository path, with the function); a `chain` line for each `DC-` chain from the routing map the change follows; and a `decision` line for each insertion point that moved from the planned line, each coding pattern chosen, each KB artifact updated or left alone, and each test that could not run (with the reason, e.g. Artifactory 401); and an `ontology touches` line with its verdict (`rebuild`, `after-merge` or `current`) and the gain (a rebuild caught before the PR, or none needed).

Read `{REQ_ID}-{STORY_ID}-ROUTING.md`. Confirm:
- `SDLC_04_ROUTING_APPROVAL` is **signed** (Tech Lead)
- `insertion-points.yaml` exists in the session directory

Read `insertion-points.yaml`. Load all insertion points.
Read `{REQ_ID}-JIRA-BACKLOG.yaml` for the story's subtasks, ACs, and hours.
If the SDLC_04 (or HOTFIX_PLAN_CODE_APPROVAL) approval carries a `[SDLC] note subtasks` block from the
Argus, act on it before any code change: when it says the developer confirmed the Jira write,
use the Jira service account. A line with a key (`KEY ← title`) updates that sub-task, only if it is a
sub-task of the story, to the title, original estimate and description listed. A line without a key
creates a sub-task under the story (type Sub-task, the summary, original estimate and indented
description exactly as listed, labels AI-Used and devin_created, the named assignee), skipping any
whose summary is already a sub-task of the story. Print `[SDLC] note subtasks <KEY>, <KEY> — created`
and `— updated`; when it says dry run, write nothing to Jira and post
the list as `{STORY_ID}-SUBTASKS.md`. If the block says Argus already created them, use those
keys. Log the work against these sub-tasks, never against the story.
Read the coding patterns referenced in the routing map.

Load security rules:
```
.devin/rules/secure-coding.md
.devin/rules/pii-handling.md
.devin/rules/data-access.md
```

---

## STEP 1 — Pre-Code Security Check

Before writing any code, review the change plan against the security rules.
Identify which rules apply to this story:
- Does it touch DB? → parameterized SQL required, RLS tenant filter required
- Does it expose data through API? → no PII in responses without masking
- Does it add UI state? → no PII in localStorage, no hardcoded secrets
- Does it touch auth or access control? → security review required

Then load the GovRAMP access-control rules (the AccessControlGapRules workbook on Confluence):
```
python3 sdlc/framework/tools/security_scans.py govramp --out <session>/govramp.json
```
Pick the rules this change touches: logon, sessions, roles and permissions, audit logging, error
messages, input validation, encryption, inventory of components. Read each picked rule's plain-language
requirement and its Python or JavaScript implementation steps, and build them into the code below.
If the result is `not_set_up` or `error`, say so in the plan and carry on; /pr-readiness shows it as
"not run".

Note the applicable rules — enforce them in every code change below.

---

## STEP 2 — Code Generation (one subtask at a time)

Work through the subtasks from `insertion-points.yaml` in dependency order
(DB migration → ETL → API → UI → tests).

For each subtask:

**Re-read the target file** immediately before editing — insertion-points.yaml
line numbers may have shifted since the plan was created.

**Apply the change** following:
1. The coding pattern selected by the Plan agent (closest existing example)
2. The security rules loaded in Step 1
3. The language/framework already in use in the target file (never introduce new libraries)

**Security checklist per file:**
- No hardcoded secrets, passwords, API keys, connection strings
- SQL: parameterized only — no f-string or string-concatenation SQL
- No PII/PHI field names in any `logger.*`, `print(`, or `console.log(` call
- Any DB query on CLAIMS_UI_DATA tables must filter on `RAW_TNNT_ID`
- No `http://` external calls (only `https://`)

**After each file edit**: re-read the file to confirm the change is correct
and did not break surrounding code (imports, indentation, closing brackets).

---

## STEP 3 — Test Generation

For each implementation change, generate tests following `test-gen.skill.yaml` logic:

**Unit tests** — for every new or modified function/method:
- File: `test_{module}.py` (backend) or `{Component}.test.tsx` (frontend)
- Cover: happy path, edge cases, invalid inputs
- Format: match the test style already used in neighboring test files

**Integration test** — if the change crosses layers (e.g. API reads from DB):
- Test the full chain: seed DB state → call endpoint → assert response shape

**Acceptance tests** — one test per AC from the story:
- Each test maps to exactly one acceptance criterion
- Test description must reference the AC number: `# AC-{n}: {criterion text}`

**Hours constraint**: unit test subtask hours should match what was specified
in `insertion-points.yaml` for the testing subtask.

**Record the tests for QA**: the tests stay in the app's own test files (so Bamboo runs them
on every build) — never copy them elsewhere. Instead, write an index into the session
`approvals.yaml` under `phases.code_review`: `jira_key` (the Acme Claims story) and `tests` — one
entry per test file with `path`, the `cases` (test function names) added for this story, and
`acceptance_criteria` (AC number per case). `/release` reads this index to build
`dev-unit-test-cases/<release>/RELEASE-TEST-CASES.md` when the story goes to QA; a story
with no index is reported as "no tests recorded" there.

---

## STEP 3b — Security scans and fix rounds (Checkmarx, Wiz, GovRAMP)

Run after the unit tests pass and the branch is pushed, before the PR. Settings are in
`.devin/rules/security-scans.yaml`; the tool is `sdlc/framework/tools/security_scans.py`.
Secrets are read from the environment by name only. Never print them.

1. `security_scans.py preflight` shows which scans are set up. A scan that isn't set up is
   reported as "not run" and doesn't count as a pass.
2. Round N (start at 1):
   ```
   security_scans.py checkmarx --branch <branch> --base <base> --round N --out <session>/checkmarx.json
   security_scans.py wiz --base <base> --round N --out <session>/wiz.json
   ```
   For each GovRAMP rule picked in STEP 1, record whether the change meets it, with `file:line`:
   ```
   security_scans.py review <session>/govramp.json --id <rule id> --result met|gap|not_affected --evidence "<file:line>"
   ```
3. `security_scans.py verdict <session>/checkmarx.json <session>/wiz.json <session>/govramp.json --markdown`.
   PASS or PASS_WITH_WARNINGS ends the loop. On FAIL, fix every blocking finding in the code,
   re-run the unit tests, push, and start the next round.
4. Stop after `max_fix_rounds` (3) rounds. Whatever is still blocking goes to the developer as a
   list (tool, severity, finding, `file:line`, the fix tried) and the PR stays blocked.

Not fixed automatically:
- **Needs approval** (Wiz `needs_approval`: a major version jump, or replacing or removing a library). List it for the developer.
- **Not fixable in code** (`base_image`, `no_vendor_fix`, `vm_host`): goes on the "can't fix in code"
  list for the platform team and doesn't use up a round. A Wiz finding stays open until a new image
  is deployed and rescanned, so never call it closed.
- **A fix that breaks the tests**: roll it back and list it for the developer.

Only findings in what the change touched block (`block_pre_existing: false`). Older findings are
shown as warnings. In a dry run nothing is pushed, so Checkmarx reports "not run (dry run)".
Every fix still goes through SDLC_05 code review.

---

## STEP 4 — KB Artifact Updates

If the story changed the DB schema:
- Update `DB_TABLE_REGISTRY.yaml` — add/modify the column entry
- Update `DB_SCHEMA_SUMMARY.md` — update the table summary

If the story changed an API endpoint:
- Update `10_ENDPOINT_REGISTRY.yaml` — add/modify the endpoint entry

If the story changed a UI component significantly:
- Update `12_COMPONENT_REGISTRY.yaml` — add/modify the component entry

Before the PR, re-run `python3 sdlc/framework/tools/confidence.py claims <session folder>/{STORY_ID}-claims.yaml`
(the code may have moved the lines it cites) and
`python3 sdlc/framework/tools/confidence.py contract --base origin/<target branch>`: table and
column names and literal types in the changed SQL against `DB-DOCS/DB_TABLE_REGISTRY.yaml` and the
ontology. Fix an `unknown column` or `type mismatch`; confirm an `unknown table` or add it to the KB.
The live Snowflake check is `not run`. Print the `[SDLC] evidence` and `[SDLC] contract` lines.

Then bring the generated knowledge artefacts up to date and commit them with the code:
`python3 sdlc/framework/tools/kb_sync.py --base origin/<target branch>`. It rebuilds the
cross-module matrix, the ontology, the link graph (`CROSS-LAYER/ACME_LINK_GRAPH.yaml`) and the KB
manifest from the code and registries, in that order, and re-reads the lines the graph cites in the
changed files. Copy the `[SDLC] sync` and `[SDLC] drift` lines it prints into the session. A `stale`
drift row is a link the code no longer supports: fix the KB source it came from, run it again, and
add a `decision` line. `python3 sdlc/framework/tools/ontology_lookup.py touches --base origin/<target branch>`
must not say `rebuild`.

KB documents that need Snowflake (DB-DOCS) cannot be rebuilt in Devin Cloud: kb_sync reports them
`not run` and `/kb-refresh` rebuilds them after deployment.

Then work through `kb_drift` in the session `approvals.yaml` (and the KB rows of the routing
map): edit each KB document in this branch so it matches the code as it now is, set that entry
to `status: fixed-in-pr` with the file path, and commit it with the code. A drift may only stay
unfixed when the Tech Lead approved a "KB exception" item at SDLC_04 (`status:
exception-approved`). Do not defer KB fixes to "after merge" — the Tech Lead reviews code and KB
together in one PR. Drift discovered while coding (behaviour the KB never mentioned) is added to
`kb_drift` and fixed the same way.

---

## STEP 5 — AI Verification (PR Readiness Check)

Run the `/pr-readiness` skill logic inline for this story and produce
`{REQ_ID}-{STORY_ID}-AI-VERIFICATION.md` in the session directory.

The pr-readiness checks to run (from `.devin/skills/pr-readiness/SKILL.md`):
- Section 1: All ACs covered, all subtasks done, points present
- Section 2: All 6 security checks (CRITICAL and MEDIUM)
- Section 2b: Security scans (Checkmarx, Wiz, GovRAMP) from STEP 3b
- Section 3: All 3 PII/PHI checks
- Section 4: Unit tests, integration tests, AC coverage
- Section 5: KB artifacts updated
- Section 6: PR description completeness

**Overall status:**
- PASS = all CRITICAL checks clean, all ACs covered, tests present
- FAIL = any CRITICAL or HIGH violation
- PASS_WITH_WARNINGS = no CRITICAL/HIGH but MEDIUM issues or stale KB

If status is FAIL: list every blocking item. Do NOT present the PR for review
until all CRITICAL items are resolved.

---

## STEP 6 — PR Description

Produce a PR description following `.devin/templates/pr-template.md`:

```markdown
# Pull Request: {STORY_ID} — {Story Title}

## Requirement
{REQ_ID}: {Requirement title}

## Story
{STORY_ID}: {Story summary}

## Changes Made
### Database Layer
{list changes or N/A}
### API Layer
{list changes or N/A}
### UI Layer
{list changes or N/A}

## Files Changed
| File | Lines Changed | Change Type |
|---|---|---|
| {path} | +{added}/-{deleted} | {add/modify/delete} |

## Acceptance Criteria Validated
{- [ ] AC-1: criterion}
{- [ ] AC-2: criterion}

## Tests Included
- [ ] Unit tests: {list test files}
- [ ] Integration tests: {list or N/A}
- [ ] Acceptance tests: {list}

## AI Verification Report
**Status**: {PASS / FAIL / PASS_WITH_WARNINGS}
**Report**: {REQ_ID}-{STORY_ID}-AI-VERIFICATION.md

### Security Checks
- [ ] No hardcoded secrets
- [ ] No PII in logs
- [ ] SQL parameterized
- [ ] No security violations

## KB Artifacts Updated
- [ ] DB_TABLE_REGISTRY.yaml {updated/N/A}
- [ ] 10_ENDPOINT_REGISTRY.yaml {updated/N/A}
- [ ] 12_COMPONENT_REGISTRY.yaml {updated/N/A}
- [ ] ACME_ONTOLOGY.yaml {rebuilt/after merge/N/A}

## Rollback Plan
{from routing map}

## Checklist
- [ ] Code follows secure coding standards
- [ ] No hardcoded secrets or PII exposure
- [ ] Tests included and passing
- [ ] AI verification passed
- [ ] KB artifacts updated (if schema/API changes)
- [ ] Rollback plan documented
```

---

## STEP 7 — Gate: SDLC_05 (Code Review)

Tell the user:
```
Implementation complete for {STORY_ID}.

Files changed: {list}
Test files created: {list}
KB artifacts updated: {list or none}
AI Verification status: {PASS / FAIL / PASS_WITH_WARNINGS}

{If FAIL: "The following items must be fixed before PR review: {list}"}
{If PASS or PASS_WITH_WARNINGS: "PR is ready for SDLC_05 human review."}

SDLC_05_CODE_REVIEW gate is pending. Present the Pull Request diff and
`{REQ_ID}-{STORY_ID}-AI-VERIFICATION.md` using
`.devin/rules/gate-presentation.md`, including the canonical checklist and
explicit decision options. The timeout is 48 hours.

When approved, run: /eval {REQ_ID} {STORY_ID}
```

Once the story is implemented, add the Jira label `devin_implemented` to it through Argus
(previewed like any other Jira change; sent only when Backlog writes are on).

---

## HARD RULES
- NEVER write code without re-reading the target file immediately before editing
- NEVER introduce a library or framework not already used in the target file
- NEVER hardcode secrets, passwords, API keys, or connection strings
- NEVER write SQL with string concatenation — parameterized only
- NEVER log a PII/PHI field name (member_id, ssn, dob, npi, tin) in any logger call
- NEVER skip the security checklist for any file that is modified
- NEVER present the PR for SDLC_05 if AI verification status is FAIL
- NEVER update a KB artifact based on what you think the file says — read it first
