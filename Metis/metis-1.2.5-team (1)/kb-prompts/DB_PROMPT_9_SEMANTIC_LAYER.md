---
prompt_id: DB-09
title: Database semantic layer
kind: prompt
pipeline: db
stage: 9
version: 2.0.0
shareable: true
requires: []
depends_on: [DB-01, DB-03, DB-05, DB-07]
placeholders: [PRODUCT_NAME, KB_DB_DOCS, DOMAIN_CONTEXT, SNOWFLAKE_DB, DB_SCHEMA, DB_ENV,
               DB_ACTIVE_FILTER_COLUMN, DB_ACTIVE_FILTER_VALUE, DB_GLOBAL_FILTERS,
               DB_DEFAULT_VIEW_SCHEMA, DB_RESTRICTED_VIEW_SCHEMAS, RUN_DATE]
outputs: ["{{KB_DB_DOCS}}/09_DB_SEMANTIC_LAYER.yaml"]
---

# DB-09: Database semantic layer

## Purpose

Turn the {{PRODUCT_NAME}} database documents into one YAML file that machines read: text-to-SQL
tools, semantic views, retrieval pipelines and AI agents. It says which filters every query needs,
how tables join, what each code means, what each column is, what business words map to which
tables, and what an agent must never do. It isn't written for people to read. Every field traces
back to a query result or a named document.

## Before you start

1. Render this prompt: `prompts.py render DB_PROMPT_9_SEMANTIC_LAYER.md --env <env>`.
2. Read these. If a required one is missing, stop and ask.
   - Required: `{{KB_DB_DOCS}}/00_DB_DISCOVERY_REPORT.md`, in particular the code values (Q12),
     joins (Q13), history (Q14), keys (Q8) and header columns (Q6).
   - Required: `{{KB_DB_DOCS}}/02_DB_TECHNICAL_REQUIREMENTS.md`, keys, joins and design patterns.
   - Required: the domain context at `{{DOMAIN_CONTEXT}}`, for business names and code meanings.
   - Optional: `{{KB_DB_DOCS}}/07_DB_SCHEMA_CATALOG.md` for the wide tables, `05_DB_GLOSSARY.md`,
     and `VALIDATION_LOG.md` for answered questions.
3. Don't query the database. If a value is missing, write `null` with a note, and list it at the top.

## Steps

Build the file section by section. The comments show the shape. Replace every `<...>`.

1. **metadata:** the database, schema, environment, total tables and columns (Q3, Q4), the discovery
   report date and this prompt's version.
2. **global_filters:** the filters every query needs. Start with the team's list:

{{DB_GLOBAL_FILTERS}}

   Then add the current-row filter `{{DB_ACTIVE_FILTER_COLUMN}} = '{{DB_ACTIVE_FILTER_VALUE}}'`, which
   applies to the history tables in step 3. Add the classification header columns found in Q6. Each
   filter gets its SQL, the tables it applies to, why it's needed, and its source.
3. **history_tables:** every table from Q14 with total, current and historical rows, current %, and
   the open and close columns. List separately any table that marks current rows another way,
   with its own filter.
4. **joins:** every join from Q13, with left and right table, key, orphan %, whether both sides
   need the current-row filter, and a SQL pattern that uses fully qualified names
   (`{{SNOWFLAKE_DB}}.{{DB_SCHEMA}}.<table>`) and the global filters. Describe a self-join as the data
   shows it. A join from shared column names only goes in a separate `unconfirmed_joins` list.
5. **value_dictionaries:** every coded column in Q12, with its values. Take each business label
   from the domain context, the glossary or an answered validation-log item. A value with no
   source gets `business_label: null` and goes on the Don't know list. Put a note on any column
   that holds status on a separate table from its entity.
6. **tables:** at least the ten largest tables and every table with more than 20 columns. For each:
   - business name, description, class (from DB-03), grain and filter;
   - key, with confidence 1.0 if Q8 declares it;
   - columns sorted into dimensions, measures, time dimensions and metadata by the rules below.
7. **entities:** each business concept in the domain context, with its aliases, main table, key,
   status table and type columns. Only use tables and columns that exist in Q3 and Q4.
8. **guardrails:** rules any AI agent must follow.
   - **Mandatory filters:** the global filters and the current-row filter, each with a severity
     and what goes wrong without it.
   - **Default schema:** read from `{{DB_DEFAULT_VIEW_SCHEMA}}` unless the user explicitly needs
     unmasked data and has approval. The restricted view schemas are {{DB_RESTRICTED_VIEW_SCHEMAS}}.
   - **Forbidden actions:** no INSERT, UPDATE, DELETE or DDL. Don't read unmasked schemas without
     approval. Don't use DISTINCT to hide missing current-row filters. Never join on a column that
     DB-03 or the domain context says is the wrong key. Never treat two codes as the same unless
     a source says they are.
   - **Query rules:** fully qualified names; aliases in joins; only joins from the `joins` section;
     name every column instead of `SELECT *`; count distinct keys, not rows; a row limit unless the
     user asks for more.
   - **Response rules:** explain the query before showing it, decode codes, warn when sensitive
     data is involved, never state results without running the query, and say when unsure.
9. **routing:** common question patterns (how many, pending, failed, by entity, recent, downstream)
   mapped to the tables and filters that answer them. Build them from the entities, value
   dictionaries and joins above. Don't invent a status value for a pattern.

Sort columns with these rules. The team's naming conventions from DB-03 take precedence.

| Column | Class | Aggregation |
|---|---|---|
| code, indicator, type, id or name suffix | dimension | - |
| long text | dimension, not used for grouping | - |
| amount | measure | SUM |
| percent or rate | measure | AVG |
| count or number | measure | SUM, or COUNT DISTINCT if it's an identifier |
| date | time dimension | day |
| timestamp | time dimension | second |
| shared header (Q6), history open and close | metadata, never shown to users | - |
| none of the above | unknown, listed under Don't know | - |

## Output

Write `{{KB_DB_DOCS}}/09_DB_SEMANTIC_LAYER.yaml`. Start with comment lines for the product, source
database and schema, environment ({{DB_ENV}}), the date ({{RUN_DATE}}), `prompt_id: DB-09`, prompt version
2.0.0, and the confidence scale below. Then, if anything is missing, add:

```yaml
# INCOMPLETE SECTIONS: [<section>, ...]
# REASON: <which query or document was missing>
```

Then the sections in this order: `metadata`, `global_filters`, `history_tables`, `joins`,
`unconfirmed_joins`, `value_dictionaries`, `tables`, `entities`, `guardrails`, `routing`,
`open_questions`, `assumptions`, `unknowns`.

## Evidence rules

YAML has no inline tags, so every item carries `source` and `confidence` fields instead:

- `confidence: 1.0` with `source: "DB-01 Q<n>"` for a direct query result.
- `confidence: 0.8` with `source: "<doc> §<section>"` for a statement in a KB document or the domain context.
- `confidence: 0.6` with `source: "assumption"` for an assumption. It is also listed under `assumptions`.
- `confidence: 0.3` with `source: "unknown"` for an unknown. It is also listed under `unknowns`.

Never fill a value from a naming pattern alone without marking it 0.6 and listing it.

## Self-check

- [ ] The file parses as YAML.
- [ ] No `<...>` markers are left.
- [ ] Every Q13 join is in `joins` with its orphan rate.
- [ ] Every Q12 coded column is in `value_dictionaries`.
- [ ] Every Q14 table is in `history_tables`.
- [ ] Every item has `source` and `confidence`.
- [ ] Every 0.6 item is in `assumptions`, and every 0.3 item is in `unknowns`.
- [ ] The guardrails include every global filter, the default schema and the forbidden actions.

## Open questions, assumptions and unknowns

End the file with three lists:

- `open_questions`: text, and who can answer.
- `assumptions`: text, and what changes if it's wrong.
- `unknowns`: text, and who could answer.
