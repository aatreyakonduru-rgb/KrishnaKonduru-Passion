---
name: app-run-pipeline
description: >
  Inline documentation pipeline for one API or UI module. Runs the stage skills
  (Discovery → BRD → FRD → TRD → Manual → Process Docs → Diagrams → UI Spec →
  Security Review → Module I/O → Integration → Validation Log), each of which renders
  its shared prompt (APP-01 to APP-17 in sdlc/kb/kb-prompts/) into a staging folder.
argument-hint: "<module_name> <source_path> [--stage <dir>] [--rebuild]"
allowed-tools:
  - read
  - write
  - edit
  - grep
  - glob
  - exec
visibility: internal
triggers:
  - user
  - model
---

# Skill: Acme Claims Run Pipeline

This skill runs in the main session (no `subagent: true`), so it can start each stage skill as a
subagent with its own `agent:` profile. Each stage skill renders its shared prompt from
`sdlc/kb/kb-prompts/` with `.devin/rules/kb-profile.yaml`; this skill only sets the order,
the staging folder and the gates. The stage order and gates follow
`sdlc/kb/kb-prompts/KB_RUNNER_APP.md` (RUN-APP).

**Invocation:** `/app-run-pipeline <module_name> <source_path> [--stage <dir>] [--rebuild]`
**Example:** `/app-run-pipeline api api --stage docs/knowledge-base/_REGEN/<date>`

## Step 0 — set up

1. `<source_path>` must be one of `app.source_dirs` in `.devin/rules/kb-profile.yaml`, or a folder
   inside one. If it isn't, stop and ask.
2. `<stage>` is the `--stage` argument, else `docs/knowledge-base/_REGEN/<YYYY-MM-DD>`.
   Pass it, with the module name and source path, to every stage skill. Nothing in this run writes
   to the live module folder (`paths.module_docs` in the profile).
3. Run `python3 sdlc/kb/tools/prompts.py lint`. Stop if it reports an error.
4. Start the session with HELP-SESSION (`sdlc/kb/kb-prompts/SESSION_MANAGER.md`):
   ```bash
   python3 sdlc/kb/tools/prompts.py render SESSION_MANAGER.md --set MODULE_NAME=<module> --set MODULE_SOURCE=<source_path> --stage <stage> --out /tmp/kb-HELP-SESSION.md
   ```
   Follow its start-of-session steps. It pulls the code, records the branch and commit, and lists
   the documents a code change has made stale. It keeps `SESSION_STATE.md` for the module in the
   staging folder: each stage's status and each gate's decision. APP-08 updates the same file; it
   doesn't start a new one. At the end of the run, follow its end-of-session steps.

## Pipeline map

```
Stage 0  ── /app-domain-context     loads .devin/rules/DOMAIN_CONTEXT.md
Stage 1  ── /app-discovery          APP-01 [discoverer] → 00_DISCOVERY_REPORT.md
             │ Gate: DISCOVERY_REVIEW (tech lead confirms completeness)
Stage 2  ── /app-brd                APP-02 [documenter] → 01_BUSINESS_REQUIREMENTS.md
             │ Gate: BSA_BRD_REVIEW
Stage 3  ── /app-frd                APP-03 [documenter] → 02_FUNCTIONAL_REQUIREMENTS.md
             │ Gate: BSA_FRD_REVIEW (BSA + tech lead)
Stage 4  ── /app-trd                APP-04 [documenter] → 03_TECHNICAL_REQUIREMENTS.md
             │ Gate: BSA_TRD_REVIEW (Dev + BSA)
Stage 5  ── /app-user-manual        APP-05 [documenter] → 04_USER_MANUAL.md
Stage 6  ── /app-process-docs       APP-06 [documenter] → 05_PROCESS_DOCUMENTATION.md
Stage 7  ── /app-diagrams           APP-07 [documenter] → 06_ARCHITECTURE_DIAGRAMS.md
Stage 8  ── /app-ui-spec            APP-15 [documenter] → 07_UI_SPECIFICATION.md  (modules with screens only)
Stage 9  ── /app-security-review    APP-09 [validator]  → 08_SECURITY_REVIEW.md
             │ Gate: SECURITY_REVIEW_SIGNOFF (security lead acknowledges)
Stage 10 ── /app-module-io          APP-16 [documenter] → 10_MODULE_IO_SUMMARY.md
Stage 11 ── /app-integration        APP-17 [documenter] → 11_INTEGRATION_SCENARIOS.md
Stage 12 ── /app-ui-data-mapping    APP-13 [documenter] → 13_UI_FIELD_TO_DATA_MAPPING.md  (modules with screens only)
Stage 13 ── /app-validation-rules   APP-14 [documenter] → 14_VALIDATION_RULES_CATALOGUE.md
Stage 14 ── /app-validation-log     APP-08 [validator]  → VALIDATION_LOG.md, SESSION_STATE.md
Optional ── /app-gap-fill           APP-GAP [documenter] → <SESSION_ID>_SUPPLEMENT.md, when the validation log lists files no stage read
Optional ── /app-code-docs          HELP-CODEDOC [documenter] → DETAILED_CODE_DOCUMENTATION.md, for modules agents change often
```

Every stage and its prompt is listed in `.devin/rules/kb-prompt-wiring.yaml`.

The endpoint registry, API data contracts and component registry (APP-10 to APP-12) come from the
source-analysis scripts in `sdlc/framework/tools/kbgen/`, not from this pipeline. They
give exact handler names, lines and field types. `/kb-build` runs them. Their prompts (APP-10 to
APP-12) describe the same files for teams without the scripts; here, use each prompt's self-check
list to check the generated file. The column-level UI-to-data mapping for each environment also
comes from a script (`gen_ui_field_map.py`); stage 12 reads it.

## Gates

⛔ A normal run stops at each gate above. Present it with its files and criteria, and the
Approve / Reject with reasons / Approve with notes options, as `.devin/rules/gate-presentation.md`
describes. Record the decision in `SESSION_STATE.md`, and don't start the next stage until it is
approved. Don't approve on anyone's behalf.

With `--rebuild` (a side-by-side rebuild of documents that already exist, started by `/kb-build`),
the stages run straight through, because nothing is replaced. Record each gate in
`SESSION_STATE.md` as `deferred to /kb-compare review`. The gate is then the owner's review of the
comparison: no staged file replaces a live one until that review is approved. `--rebuild` is only
for modules that already have live documents. A new module always runs with the gates.

## Resume

If the staging folder already has a `SESSION_STATE.md` for the module, read it. Report the
stages done, the gates signed and the next stage, then continue from there.

## When done

Report the files written, the staging folder, the gates signed or deferred, and the self-check
items still open. Next step: `/kb-compare <stage>`.

## Hard rules

- Never go past an unsigned gate in a normal run.
- Never write into the live knowledge base. Only `/kb-compare` moves staged files there, after
  approval.
- Start every stage skill with its own `agent:` profile.
- Don't run the FRD before the BRD is approved, or the TRD before the FRD is approved, in a normal run.
- The security review is always `08_SECURITY_REVIEW.md`, one per module.
- Skip stages 8 and 12 for modules without screens.
