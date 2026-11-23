---
prompt_id: DB-19
title: Database business-term map
kind: prompt
pipeline: db
stage: 13.5
version: 1.0.0
shareable: true
requires: []
depends_on: [DB-09, DB-13, DB-17, DB-18, DB-20]
placeholders: [PRODUCT_NAME, KB_DB_DOCS, DOMAIN_CONTEXT, DB_FILTER_COLUMN_CANDIDATES, RUN_DATE]
outputs: ["{{KB_DB_DOCS}}/19_DB_TERM_MAP.yaml"]
---

# DB-19: Database business-term map

## Purpose

Map every business word, phrase and field label that people use for {{PRODUCT_NAME}} data to the
column or columns that hold it. DB-13 maps entities to one table. This prompt goes one level
deeper: a business term such as "amount", "balance" or "due date" can point to several columns, in
several tables, and each one needs its own source. An agent uses this map to answer "what is the
balance of this account?" by choosing the right column.

## Before you start

1. Render this prompt: `prompts.py render DB_PROMPT_19_TERM_MAP.md --env <env>`.
2. Read these. A required one that is missing means stop.
   - Required: the domain context at `{{DOMAIN_CONTEXT}}`.
   - Required: `{{KB_DB_DOCS}}/17_DB_COLUMN_PROFILE.json`, the column list and profile.
   - Required: `{{KB_DB_DOCS}}/09_DB_SEMANTIC_LAYER.yaml`, the entities and value dictionaries.
   - Optional: `{{KB_DB_DOCS}}/18_DB_METRICS.yaml`, `{{KB_DB_DOCS}}/20_DB_USAGE_PATTERNS.md`,
     `{{KB_DB_DOCS}}/05_DB_GLOSSARY.md`.
3. Don't query the database. Every fact comes from the files above.
4. Filter columns the team says users filter on, if given: {{DB_FILTER_COLUMN_CANDIDATES}}.

## Steps

1. **Collect candidate terms** from four sources, and record which source gave each one:
   - the domain context and glossary (`[E: <doc> §<n>]`);
   - field labels in the domain context screen lists (`[E: <doc> §<n>]`);
   - the most-used column names and filter columns in DB-20 (`[E: U2]`, `[E: U3]`);
   - metric names in DB-18 (`[E: DB-18 <id>]`).
2. **Map each term to columns.** For each term, list every column that holds the concept, with:
   - its table and column (exact names from the DB-17 column list);
   - the entity from DB-13 it belongs to;
   - the unit (from the domain context or the column comment), or `[?]`;
   - whether the column is a current-row value or a history value (from DB-09 `history_tables`).
3. **Resolve ambiguity.** When a term maps to more than one column, record every candidate and the
   rule that picks one. If no rule is in a source, list the term under `ambiguous` with the owner
   who can decide. Never pick the first column by position.
4. **Code aliases.** For each coded column in DB-09 `value_dictionaries`, map each everyday phrase to
   the stored value. Only phrases from a source. Reuse the DB-13 `code_aliases` entries.
5. **Do not map** a term to a column whose profile (DB-17) shows it is empty, constant, or whose
   name matches the term but whose comment says otherwise. Record it as a rejected mapping with the
   reason.

## Output

Write `{{KB_DB_DOCS}}/19_DB_TERM_MAP.yaml`. Start with comment lines for the product, date
({{RUN_DATE}}), `prompt_id: DB-19` and `prompt_version: 1.0.0`. Then:

```yaml
metadata:
  generated_date: {{RUN_DATE}}
  terms: <n>
  ambiguous: <n>
  rejected: <n>
terms:
  - term: <business word or phrase>
    synonyms: [<term>, ...]
    meaning: <one line, from the source>
    columns:
      - {table: <TABLE>, column: <COLUMN>, entity: <ENT id>, unit: <text or null>, role: <current|history|reference>}
    preferred_column: <TABLE.COLUMN or null>
    resolution_rule: <text or null>
    source: [<"domain context §<n>">, <"DB-17 <table>.<column>">, <"DB-20 U2">]
    confidence: <1.0 | 0.8 | 0.6 | 0.3>
ambiguous:
  - term: <text>
    candidates: [<TABLE.COLUMN>]
    owner: <role who can decide>
rejected:
  - term: <text>
    column: <TABLE.COLUMN>
    reason: <text>
open_questions: []
assumptions: []
unknowns: []
```

## Evidence rules

- A term needs a source: the domain context, the glossary, a field label, or a query result.
- A synonym that appears only in a name (for example, a column called `AMT`) is `0.6` and an assumption.
- `1.0`: the mapping is confirmed by DB-17 profile data and a source.
- Never expand an abbreviation from its spelling. Use DB-13 `abbreviations` only.
- No column is mapped from a similar name without a source.

## Self-check

- [ ] The file parses as YAML.
- [ ] Every `table` and `column` exists in DB-17.
- [ ] Every `entity` exists in DB-13.
- [ ] No term maps to a column with no source.
- [ ] Every ambiguous term has a candidate list and an owner.
- [ ] Every `0.6` item is in `assumptions`, and every `0.3` item is in `unknowns`.

## Open questions, assumptions and unknowns

- `open_questions`: ambiguous terms and rejected mappings, with the owner who can decide.
- `assumptions`: each name-based synonym, and what changes if it's wrong.
- `unknowns`: terms with no column found, with who could answer.
