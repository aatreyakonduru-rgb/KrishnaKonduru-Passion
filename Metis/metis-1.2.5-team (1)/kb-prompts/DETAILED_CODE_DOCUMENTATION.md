---
prompt_id: HELP-CODEDOC
title: Detailed code documentation (function level)
kind: prompt
pipeline: helper
stage: optional
version: 2.0.0
shareable: true
requires: []
depends_on: [APP-01]
placeholders: [PRODUCT_NAME, KB_MODULE_DOCS, MODULE_NAME, MODULE_SOURCE, RUN_DATE]
outputs: ["{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/DETAILED_CODE_DOCUMENTATION.md"]
---

# HELP-CODEDOC: Detailed code documentation (function level)

## Purpose

Document `{{MODULE_NAME}}` one file at a time and one function at a time, so an AI agent can
change code without reading the whole module first. For each file it records the classes,
functions, SQL statements and calls, with line numbers. Use it for modules that change often.
It's optional, and it's large.

## Before you start

1. Render with the module: `prompts.py render DETAILED_CODE_DOCUMENTATION.md --set MODULE_NAME=<name> --set MODULE_SOURCE=<folder>`.
2. Read `{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/00_DISCOVERY_REPORT.md` for the file layers.
3. **Plan the batches.** Count the source files under `{{MODULE_SOURCE}}`, by layer. Split them
   into batches small enough to read fully in one session, such as one package or folder per
   batch. Write the batch plan at the top of the output. Mark each batch as pending, done or
   partial.

## Steps

For each file in the current batch, read it in full, then record:

1. **File.** Its path, what it's for, its line count, and its imports from inside the module.
2. **Classes and functions.** For each: its name and line, its parameters and return type (as
   written in code), what it does in one or two sentences, and what it calls (other functions,
   endpoints, SQL files, external services). Record errors it raises or catches, and side
   effects such as writes, messages and files.
3. **SQL statements.** For each: its line, its operation, the tables it touches, its parameters,
   and the filters it applies.
4. **Screens or components (UI files).** Props, state, the API calls and their triggers, and
   the fields rendered.
5. **Change notes.** Anything a developer must know before editing, such as shared helpers,
   hidden coupling, duplicated logic or missing tests. Give the line.

**Redaction.** The output copies code, not secrets. Where a line holds a password, token, key,
connection string with credentials, or a literal host or account, write `<redacted>` in place of
the value and keep the rest of the line's meaning. Note in Change notes that a secret was found,
with its file and line, but not its value. Don't copy SQL literals or record values either. Use a
placeholder such as `:value`.

When a batch is finished, mark it done in the plan. If a batch can't be finished, mark it
partial, and list the files left.

## Output

Append to `{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/DETAILED_CODE_DOCUMENTATION.md`. If the file
grows too large, start a new part file named `DETAILED_CODE_DOCUMENTATION_<n>.md`. It starts with:

```yaml
---
document: Detailed code documentation
product: {{PRODUCT_NAME}}
module: {{MODULE_NAME}}
updated_date: {{RUN_DATE}}
prompt_id: HELP-CODEDOC
prompt_version: 2.0.0
commit: <short hash>
---
```

Then add the batch plan, followed by one `## File: <path>` section per file, with
`### Classes and functions`, `### SQL statements` and `### Change notes` subsections as they
apply. Then Open questions, Assumptions and Don't know.

## Evidence rules

- Every entry gives its line: `[E: <file>:<line>]`.
- Only files that were read in full are documented. A file that was skimmed is listed as pending.
- A purpose you can't tell from the code is `[?]`, never guessed from the name.
- Anything taken as true without a source is `[A]` and goes on the Assumptions list.

## Self-check

- [ ] The batch plan covers every source file. Count the files in `{{MODULE_SOURCE}}` and the
      files listed in the plan. The two counts match, or the difference is listed as pending.
- [ ] Every documented file was read in full.
- [ ] No secret, password, token, host or literal record value is in the output.
- [ ] Every function has a line number.
- [ ] Every `[A]` and `[?]` is on its list.

## Open questions, assumptions and unknowns

End with three lists:

- **Open questions:** each with an owner by role (module developer, tech lead).
- **Assumptions:** each `[A]`, and what changes if it's wrong.
- **Don't know:** each `[?]`, with who could answer.
