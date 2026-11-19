---
prompt_id: DB-12
title: AI guardrails for the database
kind: prompt
pipeline: db
stage: 12
version: 2.0.0
shareable: true
requires: []
depends_on: [DB-06, DB-09]
placeholders: [PRODUCT_NAME, KB_DB_DOCS, DOMAIN_CONTEXT, SNOWFLAKE_DB, DB_SCHEMA, DB_ENV,
               DB_GLOBAL_FILTERS, DB_ACTIVE_FILTER_COLUMN, DB_ACTIVE_FILTER_VALUE,
               DB_DEFAULT_VIEW_SCHEMA, DB_RESTRICTED_VIEW_SCHEMAS, RUN_DATE]
outputs: ["{{KB_DB_DOCS}}/12_DB_AI_GUARDRAILS.yaml"]
---

# DB-12: AI guardrails for the database

## Purpose

Write the rules any AI agent must follow when it queries or writes about the {{PRODUCT_NAME}}
database. These rules are injected into agent prompts and checked against agent output, so each
one must be specific enough to test: a bad example, a good example, and where the rule came
from. A rule with no source is removed.

## Before you start

1. Render this prompt: `prompts.py render DB_PROMPT_12_AI_GUARDRAILS.md --env <env>`.
2. Read these.
   - Required: `{{KB_DB_DOCS}}/09_DB_SEMANTIC_LAYER.yaml` (`global_filters`, `guardrails`,
     `joins`, `value_dictionaries`).
   - Required: `{{KB_DB_DOCS}}/06_DB_SECURITY_REVIEW.md` (views, policies, grants, agent guidance).
   - Required: the domain context at `{{DOMAIN_CONTEXT}}`.
   - Optional: `{{KB_DB_DOCS}}/VALIDATION_LOG.md` answered items, and DB-03 for key and join findings.
3. Don't query the database.

## Steps

1. **Mandatory filters.** One rule per filter every query needs. Start with the team's list:

{{DB_GLOBAL_FILTERS}}

   Add the current-row filter `{{DB_ACTIVE_FILTER_COLUMN}} = '{{DB_ACTIVE_FILTER_VALUE}}'` for the
   history tables, plus a separate rule for each table that marks current rows another way.
   Each rule gets a severity, what goes wrong without it, bad SQL and good SQL.
2. **Forbidden patterns.** One rule for each mistake the KB shows is easy to make. Look for these:
   - reading a status column from the entity table when the status lives on another table;
   - joining on a column that DB-03 or the domain context says is the wrong key;
   - calling a self-reference a tree or DAG when the evidence says otherwise;
   - treating two similar code values as the same;
   - `SELECT *`, which exposes header columns;
   - reading unmasked schemas by default;
   - assuming declared keys are enforced;
   - stating a schedule or service level nobody has confirmed.

   Include only the patterns the KB actually supports, each with its source.
3. **Schema selection.** Default to `{{DB_DEFAULT_VIEW_SCHEMA}}`. Say when another restricted view
   schema ({{DB_RESTRICTED_VIEW_SCHEMAS}}) may be used and what approval it needs. Say what the
   row access policies in DB-06 already filter, and whether queries still need their own filters.
4. **Value validation.** For each coded column in `value_dictionaries`, the allowed values. An agent
   must reject or question any other value.
5. **Documentation guardrails.** Rules for agents that write documents, not SQL:
   - don't state counts, schedules, owners or meanings without a source;
   - don't decode codes from their spelling;
   - tag every fact `[E: source]`, `[A]` or `[?]`.

   Add each specific claim the validation log shows an earlier run got wrong.
6. **Write safety.** No INSERT, UPDATE, DELETE, MERGE or DDL from an agent. Say which path the
   application uses to write, if the KB documents one. Otherwise that path is `[?]`.

## Output

Write `{{KB_DB_DOCS}}/12_DB_AI_GUARDRAILS.yaml`. Start with comment lines for the product, source
(`{{SNOWFLAKE_DB}}.{{DB_SCHEMA}}`), environment ({{DB_ENV}}), the date ({{RUN_DATE}}),
`prompt_id: DB-12` and prompt version 2.0.0. Then these sections: `metadata`, `mandatory_filters`,
`forbidden_patterns`, `schema_selection`, `value_validation`, `documentation_guardrails`,
`write_safety`, `open_questions`, `assumptions`, `unknowns`.

Each rule has these fields:

```yaml
- id: <MF|FP|SS|VV|DG|WS>-<nnn>
  name: <snake_case>
  severity: <critical | high | medium>
  rule: <one sentence an agent can follow>
  bad: <SQL or text that breaks it>
  good: <SQL or text that follows it>
  why: <what goes wrong>
  source: <"DB-01 Q<n>" | "<doc> §<n>" | "VALIDATION_LOG Q<n>">
  confidence: <1.0 | 0.8 | 0.6 | 0.3>
```

## Evidence rules

- Every rule needs a `source`. Remove any rule that has none.
- `1.0`: a query result or an answered validation-log item. `0.8`: a KB document or the domain context.
- `0.6`: an assumption, also listed under `assumptions`. `0.3`: an unknown, also listed under `unknowns`.
- SQL examples use fully qualified names (`{{SNOWFLAKE_DB}}.{{DB_SCHEMA}}.<table>` or the view schema)
  and only joins from the semantic layer.

## Self-check

- [ ] The file parses as YAML.
- [ ] Every rule has bad and good examples, and a source.
- [ ] Every global filter and the current-row filter has a mandatory-filter rule.
- [ ] The default schema rule names `{{DB_DEFAULT_VIEW_SCHEMA}}`.
- [ ] Every coded column in the semantic layer has a value-validation rule.
- [ ] No rule depends on a value the KB doesn't contain.

## Open questions, assumptions and unknowns

End the file with three lists:

- `open_questions`: text, and the owner who can answer.
- `assumptions`: text, and what changes if it's wrong.
- `unknowns`: text, and who could answer.
