---
name: qa-scenarios
description: >
  Turn a story's acceptance criteria into Behave/Gherkin scenarios for the Acme Claims QA suite
  (ACME/claims-qa), written with the step sentences the suite already implements, plus the
  Snowflake checks and test-data sets each scenario needs. Lists the step definitions, query
  keys and TestData sets that don't exist yet instead of inventing them, and shows which ACs
  are covered. Output is a draft for QA to review; nothing is pushed to claims-qa without a PR QA asks for.
  Invoke with: /qa-scenarios <REQ-ID> <STORY-ID>  ·  /qa-scenarios "<pasted acceptance criteria>"
argument-hint: "<REQ-ID> <STORY-ID> | \"<acceptance criteria>\""
visibility: internal
triggers:
  - user
  - model
invocations:
  - /qa-scenarios
  - write behave scenarios
  - gherkin for this story
  - turn the acceptance criteria into tests
allowed-tools:
  - bash
  - read
  - edit
---

# /qa-scenarios — acceptance criteria to Behave scenarios

The QA suite is `ACME/claims-qa`: Behave feature files in `features/FeatureFiles/Acme Claims/`, step
definitions in `features/steps/`, Snowflake queries in `features/databaseQueries/*.txt` (JSON,
with `ReplaceX` placeholders), test data in `TestData/*.json` and `*_Field_Mapping.py`. The
helper is `sdlc/framework/tools/qa_scenarios.py`. It only reads the QA repo.

## Steps

1. **Get the acceptance criteria.** With a REQ-ID, find the session folder with
   `python3 sdlc/framework/tools/session_store.py path <REQ-ID>` and read the story's
   ACs from `{REQ_ID}-BACKLOG.md` and `{REQ_ID}-SPEC.md` (the same files `/eval` uses). If the
   user pasted ACs, number them AC-1, AC-2... and confirm the numbering with them. If an AC is
   vague ("should work correctly"), ask what it means before writing a scenario for it.

2. **Get the QA repo.**
   ```bash
   [ -d ~/repos/claims-qa/.git ] || git -c http.sslVerify=false clone https://git.acme.example/ACME/claims-qa.git ~/repos/claims-qa
   git -C ~/repos/claims-qa -c http.sslVerify=false pull --ff-only
   export CLAIMS_QA_REPO=~/repos/claims-qa
   python3 sdlc/framework/tools/qa_scenarios.py inventory
   ```

3. **Find what you can reuse.** Start from the QA-suite coverage in the knowledge base,
   `docs/knowledge-base/QA-AUTOMATION-DERIVED/03_QA_SUITE_COVERAGE.md` (generated from claims-qa by
   `tools/kbgen/gen_qa_suite.py`): the existing scenarios for the screen and tables the story changes, the step
   library with how often each step is used, the query keys with the tables they read, and the TestData sets.
   Those scenarios are the regression QA re-runs beside the new ones. Then look at the feature file for the same
   screen and search the steps:
   ```bash
   python3 sdlc/framework/tools/qa_scenarios.py steps --grep "<screen or action>"
   python3 sdlc/framework/tools/qa_scenarios.py next-tag --prefix ACME_Contract_
   ```

   Then check qTest, where the team keeps its SIT cases (the "SIT- Upload Testcases to qTest"
   sub-task). If a qTest token is set up for the org (Test Management Profile in knowledge,
   default secret `QTEST_API_TOKEN`), read the cases already linked to the story before writing
   new ones: `POST <qtest>/api/v3/projects/<id>/search` with
   `{"object_type":"requirements","fields":["*"],"query":"'Name' ~ '<JIRA_KEY>'"}`, then the linked
   test cases. Reuse or extend what is there. With no token, put "qTest not checked" under Don't know.
   Nothing is written to qTest from here.

   Then get the edge cases the KB already knows for the object or table the story changes:
   ```bash
   python3 sdlc/framework/tools/ontology_lookup.py scenarios <object|table|TABLE.COLUMN|status code>
   ```
   It lists each status value, the allowed flow and the skips it forbids, the business phrases,
   the rules, the mandatory columns and the downstream readers to re-check. Use the ones an AC
   asks for; list the rest under *Not covered by an AC* for QA to decide. Never add a case the
   ACs do not support as a covered scenario. Print `[SDLC] ontology <command> <term> — <found>; why: <why>; gain: <gain>` with the cases it added as the gain (`.devin/rules/workbench-trace.md`).

4. **Draft the feature** in the suite's own style: the same background steps, the same group
   tag, a new numbered scenario tag from `next-tag`, `Scenario Outline` with an `Examples` table
   that names TestData sets and query keys (never raw values).
   - Copy step sentences exactly. A step the suite doesn't have is written anyway, marked with
     a `# NEW STEP` comment on the line above, and goes on the *New step definitions* list.
   - Keep UI checks and DB checks as separate steps, the way the existing "in UI And DB"
     scenarios do.
   - Put `# covers: AC-1, AC-3` above each scenario.
   - DB checks use an existing query key when one fits. A new one is written like the existing
     queries (`SELECT <columns> FROM <table> WHERE <key> = 'ReplaceX'`), only with tables and
     columns you have seen in the KB or the query files, and goes on the *New queries* list.
   - Test data: name the TestData set. New sets are described field by field with synthetic
     values only. No real member, provider or TIN data, ever.

5. **Check the draft** and fix everything that isn't a deliberate NEW item:
   ```bash
   python3 sdlc/framework/tools/qa_scenarios.py check <draft>.feature --ac AC-1 AC-2 AC-3
   ```
   Copy the `[SDLC] qa` line it prints into the session for Argus Trace.

6. **Write it up** in the session folder as `{REQ_ID}-{STORY_ID}-QA-SCENARIOS.md` next to
   the `.feature` draft:
   - an AC coverage table (covered, partly, not covered, and why);
   - new step definitions (sentence, which page object it would use);
   - new queries;
   - new TestData sets;
   - the Open questions, Assumptions and Don't know lists.
   Say plainly that the scenarios have not been run.

7. **Hand to QA.** The QA lead or QA staff reviews the draft. Only if they ask, raise a PR to
   `ACME/claims-qa` on a new branch. Never push to its main branch.

## Don't
- Invent step definitions, query keys, tables or columns and present them as existing.
- Put real member data, SSNs, member IDs or TINs in Examples tables.
- Claim a scenario passes. Nothing here runs the suite.
