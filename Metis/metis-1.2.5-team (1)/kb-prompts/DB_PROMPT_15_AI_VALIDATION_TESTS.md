---
prompt_id: DB-15
title: AI validation tests
kind: prompt
pipeline: db
stage: 15
version: 2.0.0
shareable: true
requires: []
depends_on: [DB-09, DB-10, DB-12, DB-14]
placeholders: [PRODUCT_NAME, KB_DB_DOCS, SNOWFLAKE_DB, DB_SCHEMA, DB_ENV, RUN_DATE]
outputs: ["{{KB_DB_DOCS}}/15_DB_AI_VALIDATION_TESTS.yaml"]
---

# DB-15: AI validation tests

## Purpose

Write a test set that shows whether an AI agent has actually learned the {{PRODUCT_NAME}}
database rules. Each test is a question, the right answer, how to tell pass from fail, and the
wrong answers an agent is likely to give. It can feed an agent evaluation tool, or a person can
work through it by hand.

## Before you start

1. Render this prompt: `prompts.py render DB_PROMPT_15_AI_VALIDATION_TESTS.md --env <env>`.
2. Read in full: `12_DB_AI_GUARDRAILS.yaml`, which defines what right looks like. Also read
   `09_DB_SEMANTIC_LAYER.yaml` (`global_filters`, `joins`, `value_dictionaries`),
   `10_DB_VERIFIED_QUERIES.md` and `14_DB_APP_VERIFIED_QUERIES.md` in `{{KB_DB_DOCS}}`.
   If the guardrails file is missing, stop.
3. Don't query the database.

## Steps

1. **One suite per kind of rule**, with at least two tests each:
   - mandatory filters, including a table with a different current-row filter if there is one;
   - status or column location, if the guardrails have a rule for it;
   - join-key traps, one per forbidden join pattern;
   - default schema selection;
   - hallucination resistance, with questions whose honest answer is "not known";
   - alias resolution, using the entity registry;
   - cross-module reasoning, using the lineage and application answers.
2. **Each test has:**
   - a clear question;
   - the expected answer (SQL from DB-10 or DB-14, or text);
   - pass criteria as checks a script or person can apply, such as "contains the filter X" or
     "says it doesn't know";
   - one to three likely wrong answers, each tied to the guardrail it breaks;
   - a severity (critical, high or medium) taken from that guardrail.
3. **Scoring.** Add a summary template with pass counts by severity, and a rule that any failed
   critical test fails the run.

## Output

Write `{{KB_DB_DOCS}}/15_DB_AI_VALIDATION_TESTS.yaml`. Start with comment lines for the product,
source (`{{SNOWFLAKE_DB}}.{{DB_SCHEMA}}`), environment ({{DB_ENV}}), the date ({{RUN_DATE}}),
`prompt_id: DB-15`, prompt version 2.0.0 and the total test count. Then these sections:
`metadata`, `test_suites` (each with `tests`), `evaluation_summary_template`, `open_questions`,
`assumptions`, `unknowns`.

Each test has these fields:

```yaml
- id: T-<nnn>
  question: <text>
  expected_answer: <SQL or text>
  pass_criteria: [<check>, ...]
  fail_criteria: [<check>, ...]
  common_wrong_answers:
    - answer: <text>
      breaks: <guardrail id>
  severity: <critical | high | medium>
  source: [<guardrail id>, <VQR or AVQR id>]
```

## Evidence rules

- Every test cites the guardrail it checks, and the query or answer it expects.
- A test whose right answer isn't in the KB can't be written. Put it under `open_questions` instead.
- Anything taken as true without a source goes under `assumptions`. Anything not known goes under `unknowns`.

## Self-check

- [ ] The file parses as YAML.
- [ ] Every critical guardrail has at least one test.
- [ ] Every test has pass and fail criteria that can be checked.
- [ ] The total in the header matches the number of tests.
- [ ] At least two hallucination-resistance tests expect "not known".

## Open questions, assumptions and unknowns

End the file with three lists:

- `open_questions`: text, and the owner who can answer.
- `assumptions`: text, and what changes if it's wrong.
- `unknowns`: text, and who could answer.
