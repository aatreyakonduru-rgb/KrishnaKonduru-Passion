---
prompt_id: DB-18
title: Database metrics dictionary
kind: prompt
pipeline: db
stage: 8.5
version: 1.0.0
shareable: true
requires: []
depends_on: [DB-09, DB-17, DB-21]
placeholders: [PRODUCT_NAME, KB_DB_DOCS, DOMAIN_CONTEXT, SNOWFLAKE_DB, DB_SCHEMA, DB_ENV, RUN_DATE]
outputs: ["{{KB_DB_DOCS}}/18_DB_METRICS.yaml"]
---

# DB-18: Database metrics dictionary

## Purpose

Record every business metric {{PRODUCT_NAME}} users talk about (for example "active", "overdue",
"turnaround", "revenue") with its formula, grain, filters, source columns and owner. Without this,
an agent invents a formula each time someone asks for a metric, and two answers disagree. The output
is YAML for tools and a reviewer. Every metric must trace to a source. A metric nobody has defined is
listed as a question, not guessed.

## Before you start

1. Render this prompt: `prompts.py render DB_PROMPT_18_METRICS.md --env <env>`.
2. Read these:
   - Required: the domain context at `{{DOMAIN_CONTEXT}}`, for metric names and definitions.
   - Required: `{{KB_DB_DOCS}}/09_DB_SEMANTIC_LAYER.yaml`, `global_filters` and `history_tables`.
   - Required: `{{KB_DB_DOCS}}/21_DB_OBJECT_LOGIC.md`, for metrics already computed in views.
   - Optional: `{{KB_DB_DOCS}}/17_DB_COLUMN_PROFILE.json`, for column meaning.
3. Don't query the database. This prompt records definitions. The check comes in the verified
   queries (DB-10).

## Steps

1. **Find each metric.** Take it from a source: the domain context, the glossary, a view in DB-21
   that computes it, or a validation-log answer. A metric name that appears only in a column name is
   a candidate, not a definition.
2. **Write the definition** for each metric:
   - name and aliases (the words users say);
   - plain-English definition, from the source;
   - formula, as SQL over the semantic-layer tables, using their exact names;
   - grain (one row per what);
   - the global filters and current-row filter it needs (from DB-09);
   - the time basis (point in time, period, or rolling window);
   - the source columns it reads;
   - the owner who confirms the definition.
3. **Check for conflicts.** When two sources define the same metric differently, record both, and
   list the conflict under `open_questions`. Don't pick one.
4. **Check against DB-21.** If a view already computes the metric, the formula must match the view's
   logic. Record any difference.
5. **Undefined metrics.** A metric that appears in the domain context without a definition is
   listed under `unknowns`, with the owner.

## Output

Write `{{KB_DB_DOCS}}/18_DB_METRICS.yaml`. Start with comment lines for the product, source
(`{{SNOWFLAKE_DB}}.{{DB_SCHEMA}}`), environment ({{DB_ENV}}), date ({{RUN_DATE}}), `prompt_id: DB-18`
and `prompt_version: 1.0.0`. Then:

```yaml
metadata:
  generated_date: {{RUN_DATE}}
  metrics: <n>
  defined: <n>
  conflicting: <n>
metrics:
  - id: MET-<name in snake_case>
    name: <canonical name>
    aliases: [<term>, ...]
    definition: <one line>
    formula: |
      <SQL over semantic-layer tables>
    grain: <one row per ...>
    global_filters: [<SQL predicate>]
    time_basis: <point in time | period | rolling window>
    source_columns: [<TABLE.COLUMN>]
    owner: <role>
    alternatives: [{source: <text>, definition: <text>}]
    source: [<"domain context §<n>">, <"DB-21 <object>">]
    confidence: <1.0 | 0.8 | 0.6 | 0.3>
open_questions: []
assumptions: []
unknowns: []
```

Use the metric `id` as a stable key derived from the name, so re-runs do not renumber it.

## Evidence rules

- A definition needs a source: a domain context section, a view in DB-21, or an answered validation item.
- `1.0`: the formula matches a view in DB-21 and the definition matches a source.
- `0.8`: the definition is from a KB document or the domain context, and the formula is written by this prompt.
- `0.6`: the formula is inferred from column names (also an assumption).
- `0.3`: the metric is named but not defined (also an unknown).
- Never invent a threshold, such as "overdue after 30 days", unless a source gives it.

## Self-check

- [ ] The file parses as YAML.
- [ ] Every source column exists in DB-09 or DB-17.
- [ ] Every metric has a source and a confidence.
- [ ] Every metric with a view in DB-21 matches the view or lists the difference.
- [ ] Every conflict is in `open_questions`.
- [ ] No threshold appears without a source.

## Open questions, assumptions and unknowns

- `open_questions`: conflicting definitions, with the owner who can decide.
- `assumptions`: each inferred formula, and what changes if it's wrong.
- `unknowns`: named metrics with no definition, with who could define them.
