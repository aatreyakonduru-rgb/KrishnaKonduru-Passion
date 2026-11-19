---
prompt_id: DB-13
title: Entity registry
kind: prompt
pipeline: db
stage: 13
version: 2.0.0
shareable: true
requires: []
depends_on: [DB-05, DB-09]
placeholders: [PRODUCT_NAME, KB_DB_DOCS, DOMAIN_CONTEXT, APP_SOURCE_DIRS, SNOWFLAKE_DB, DB_SCHEMA,
               DB_ENV, RUN_DATE]
outputs: ["{{KB_DB_DOCS}}/13_DB_ENTITY_REGISTRY.yaml"]
---

# DB-13: Entity registry

## Purpose

Map every word people use for a {{PRODUCT_NAME}} business thing to the one table and key that
holds it. That covers aliases, abbreviations, plain-English phrases for code values, and the
names the API and UI use. Agents need this to turn "which groups are waiting for approval?" into
the right table, column and value. Every alias needs a source. An alias someone made up is
worse than a missing one.

## Before you start

1. Render this prompt: `prompts.py render DB_PROMPT_13_ENTITY_REGISTRY.md --env <env>`.
2. Read these.
   - Required: the domain context at `{{DOMAIN_CONTEXT}}`, for business terms and abbreviations.
   - Required: `{{KB_DB_DOCS}}/05_DB_GLOSSARY.md`.
   - Required: `{{KB_DB_DOCS}}/09_DB_SEMANTIC_LAYER.yaml` (`entities`, `value_dictionaries`, `history_tables`).
   - Optional: `{{KB_DB_DOCS}}/9B_DB_DATA_CONTRACTS.yaml` for API and UI field names, and the
     application source in these folders:

{{APP_SOURCE_DIRS}}

3. Don't query the database.

## Steps

1. **Entities.** One entry per business concept in the domain context or glossary, with:
   - its canonical name and aliases;
   - its main table and key;
   - its current-row filter, from `history_tables`;
   - its status table and column, if status lives elsewhere;
   - its type columns, subtypes and related tables.

   Every table and column must exist in the semantic layer.
2. **Important notes.** For each entity, add the traps the KB records, such as a join key that
   differs from the obvious one, or a status held on a separate table. Each note has a source.
3. **Code aliases.** For each coded column in `value_dictionaries`, map the everyday phrases
   ("waiting for approval", "failed") to the confirmed values. Only use phrases that appear in the
   domain context, glossary, screens or code.
4. **Abbreviations.** Each abbreviation used in table and column names, with its full word.
   Take the full words from the glossary or domain context. Anything else goes under `unknowns`.
5. **Cross-layer names.** For each entity, the names the API (endpoint, serializer or model) and
   the UI (screen, component or label) use, with file references. Note any place the code
   uses test or mock data instead of the table.

## Output

Write `{{KB_DB_DOCS}}/13_DB_ENTITY_REGISTRY.yaml`. Start with comment lines for the product, source
(`{{SNOWFLAKE_DB}}.{{DB_SCHEMA}}`), environment ({{DB_ENV}}), the date ({{RUN_DATE}}),
`prompt_id: DB-13` and prompt version 2.0.0. Then these sections: `metadata`, `entities`,
`code_aliases`, `abbreviations`, `cross_layer_names`, `open_questions`, `assumptions`, `unknowns`.

Each entity has these fields:

```yaml
- id: ENT-<nnn>
  canonical_name: <name>
  aliases: [<term>, ...]
  table: <table>
  key: <column>
  current_row_filter: <SQL or null>
  status: {table: <table or null>, column: <column or null>}
  notes: [<note>]
  source: [<"domain context §<n>">, <"05_DB_GLOSSARY">, <"DB-01 Q<n>">]
  confidence: <1.0 | 0.8 | 0.6 | 0.3>
```

## Evidence rules

- Every alias, abbreviation and note needs a source.
- `1.0`: a query result or code (file and line). `0.8`: a KB document or the domain context.
- `0.6`: an assumption, also listed under `assumptions`. `0.3`: an unknown, also listed under `unknowns`.
- Never expand an abbreviation from how it's spelled.

## Self-check

- [ ] The file parses as YAML.
- [ ] Every entity's table and key exist in the semantic layer.
- [ ] Every entity whose status lives elsewhere names the status table.
- [ ] Every abbreviation in table and column names is expanded, or listed as unknown.
- [ ] No alias lacks a source.

## Open questions, assumptions and unknowns

End the file with three lists:

- `open_questions`: text, and the owner who can answer.
- `assumptions`: text, and what changes if it's wrong.
- `unknowns`: text, and who could answer.
