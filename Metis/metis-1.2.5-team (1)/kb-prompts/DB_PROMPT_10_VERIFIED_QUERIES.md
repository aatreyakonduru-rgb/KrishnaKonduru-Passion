---
prompt_id: DB-10
title: Verified queries
kind: prompt
pipeline: db
stage: 10
version: 2.0.0
shareable: true
requires: [snowflake]
depends_on: [DB-09]
placeholders: [PRODUCT_NAME, KB_DB_DOCS, SNOWFLAKE_DB, DB_SCHEMA, DB_ENV, DB_DEFAULT_VIEW_SCHEMA,
               DB_RESTRICTED_VIEW_SCHEMAS, RUN_DATE]
outputs: ["{{KB_DB_DOCS}}/10_DB_VERIFIED_QUERIES.md"]
---

# DB-10: Verified queries

## Purpose

Build a set of business questions about the {{PRODUCT_NAME}} database, each paired with SQL that
is known to be correct. Text-to-SQL tools use them as examples, reviewers use them to test
agent-written SQL, and semantic views can load them as verified queries. A query only counts
as verified once it has run. The rest are marked "not run".

## Before you start

1. Render this prompt: `prompts.py render DB_PROMPT_10_VERIFIED_QUERIES.md --env <env>`.
2. Read `{{KB_DB_DOCS}}/09_DB_SEMANTIC_LAYER.yaml` in full. It's the main reference. If it's missing,
   stop. Use `00_DB_DISCOVERY_REPORT.md` and `07_DB_SCHEMA_CATALOG.md` only for columns the
   semantic layer lacks.
3. If a read-only connection to `{{SNOWFLAKE_DB}}` ({{DB_ENV}}) is available, run each query with
   `LIMIT 10` to check it works. Never run anything but SELECT. If there's no connection, mark
   every query "not run".

## Steps

1. **Rules for every query:**
   - apply every `global_filters` entry, and the current-row filter on history tables;
   - only use joins from `joins` with confidence 0.8 or more;
   - filter code columns only on values from `value_dictionaries`;
   - query `{{DB_DEFAULT_VIEW_SCHEMA}}` by default, and don't use another restricted view schema
     ({{DB_RESTRICTED_VIEW_SCHEMAS}}) unless the question needs it;
   - name every column, never `SELECT *`;
   - prefer joins to subqueries;
   - count distinct keys.
2. **Write at least 40 queries across these categories.** Build each from the entities, value
   dictionaries and joins in the semantic layer, not from a fixed list.

| Category | At least | Examples |
|---|---|---|
| Simple lookups | 8 | count current rows of each main entity; list by status; list by type; most recent |
| Aggregations | 8 | children per parent; counts by status and type; volume per month; history depth |
| Multi-join | 8 | each confirmed join; one three-way chain; one LEFT JOIN that finds parents with no children |
| Status and lifecycle | 6 | stuck in a status longer than N days; failed and never rerun; current in-progress |
| Jobs and requests | 5 | rerun history (self-reference); requests by type and stage; dependencies not finished |
| Time and trend | 5 | new rows per month; turnaround between two statuses; tables altered recently |
| Edge cases | 5 | the join-key trap from DB-12; current row plus previous version; orphan detection |

3. **Anti-patterns.** At least five queries that break a guardrail, each with why it's wrong and a
   link to the correct query. Cover:
   - a missing global filter;
   - a missing current-row filter;
   - a wrong join key;
   - `SELECT *`;
   - reading an unmasked schema by default.
4. **Run them**, if you can. Record for each query: run or not run, the row count, and any error.
   Fix any query that fails, or remove it and list it.

## Output

Write `{{KB_DB_DOCS}}/10_DB_VERIFIED_QUERIES.md`, starting with:

```yaml
---
document: DB verified queries
product: {{PRODUCT_NAME}}
source_db: {{SNOWFLAKE_DB}}
schema: {{DB_SCHEMA}}
environment: {{DB_ENV}}
generated_date: {{RUN_DATE}}
query_count: <n>
queries_run: <n>
prompt_id: DB-10
prompt_version: 2.0.0
---
```

Each query uses this block:

````markdown
## VQR-<nnn>: <short title>

**Category:** <category> · **Difficulty:** <basic | intermediate | advanced>
**Business area:** <from 04_DB_CHANGE_IMPACT_MATRIX, or [?]>
**Tables:** <list> · **Patterns:** <filters and joins it shows>

**Question:**
> <how a business user would ask it>

```sql
<query>
```

**Result shape:** <columns, roughly how many rows, sort order>
**Checked:** <run on {{DB_ENV}} {{RUN_DATE}}, n rows | not run>
**Sources:** <semantic layer sections used>
````

Then the anti-patterns, a summary table (id, category, checked), Open questions, Assumptions,
Don't know, and Files read.

## Evidence rules

- Each query cites the semantic layer sections it relies on, `[E: 09_DB_SEMANTIC_LAYER joins]`.
- "Checked" states only what happened. Never say a query returns a value unless it ran.
- A join or value with confidence below 0.8 isn't used. If a question needs one, the question
  goes on the Don't know list instead.
- Anything taken as true without a source is `[A]` and goes on the Assumptions list.

## Self-check

- [ ] At least 40 queries, and every category meets its minimum.
- [ ] Every query applies every global filter, plus the current-row filter where needed.
- [ ] No `SELECT *` except in the anti-patterns.
- [ ] Every query's "Checked" line is filled in.
- [ ] Nothing but SELECT was run.
- [ ] Every `[A]` and `[?]` is on its list.

## Open questions, assumptions and unknowns

End with three lists:

- **Open questions:** questions that couldn't be answered with confirmed joins or values, each with an owner.
- **Assumptions:** each `[A]`, and what changes if it's wrong.
- **Don't know:** each `[?]`, with who could answer.
