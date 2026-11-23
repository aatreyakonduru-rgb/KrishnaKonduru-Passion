---
prompt_id: DB-11
title: Database data lineage
kind: prompt
pipeline: db
stage: 11
version: 2.0.0
shareable: true
requires: []
depends_on: [DB-01, DB-03, DB-06, DB-09]
placeholders: [PRODUCT_NAME, KB_DB_DOCS, DOMAIN_CONTEXT, SNOWFLAKE_DB, DB_SCHEMA, DB_ENV,
               DB_RELATED_SCHEMAS, DB_RESTRICTED_VIEW_SCHEMAS, RUN_DATE]
outputs: ["{{KB_DB_DOCS}}/11_DB_DATA_LINEAGE.yaml"]
---

# DB-11: Database data lineage

## Purpose

Trace where {{PRODUCT_NAME}} data comes from, how it moves between tables, and where it goes.
Agents use it to answer "where does this come from?" and "what breaks if this table changes?".
Governance uses it to follow sensitive data. The output is YAML for tools. Lineage is easy to
get wrong by guessing, so every flow must name its evidence, and every flow without evidence
is marked as unknown.

## Before you start

1. Render this prompt: `prompts.py render DB_PROMPT_11_DATA_LINEAGE.md --env <env>`.
2. Read these.
   - Required: the domain context at `{{DOMAIN_CONTEXT}}`, for source systems and consumers.
   - Required: `{{KB_DB_DOCS}}/02_DB_TECHNICAL_REQUIREMENTS.md`, data flow and integration sections.
   - Required: `{{KB_DB_DOCS}}/09_DB_SEMANTIC_LAYER.yaml`, joins and history tables.
   - Optional: `{{KB_DB_DOCS}}/06_DB_SECURITY_REVIEW.md`, `VALIDATION_LOG.md` (answered items),
     and any ETL knowledge-base documents that name tables they read or write.
3. The related schemas are {{DB_RELATED_SCHEMAS}}. Tables there may feed or consume `{{DB_SCHEMA}}`.
4. Don't query the database.

## Steps

1. **Inbound flows.** Each process that writes into `{{DB_SCHEMA}}`: the source (a system, a related
   schema, the application or a file load), the target tables, the method, the schedule and the
   evidence. Only list a schedule someone has written down. Otherwise it is `[?]`.
2. **Internal flows.** Movements between tables inside the schema. Examples are staging to review
   to base, request to detail to result, and history versioning. For each, give the trigger and
   say whether the rows are moved, copied or transformed. Describe self-references as the data
   shows them. Don't call something a tree or a DAG unless the evidence says so.
3. **Outbound flows.** Each consumer that reads from the schema or its views: the system, the
   tables or views it reads, how it reads them and the evidence. A consumer named only in the
   domain context gets confidence 0.8. A consumer nobody has confirmed is 0.3.
4. **Sensitive-data flows.** Using DB-06, name the tables with sensitive columns, which restricted
   view schemas mask them ({{DB_RESTRICTED_VIEW_SCHEMAS}}), and which outbound flows read base
   tables instead of masked views.
5. **Timing.** Using the history tables, say which flows create new versions and which update
   rows in place, only where evidence shows it.
6. **Open lineage questions.** Every flow at confidence 0.3, written as a question with an owner.

Don't write any of these without a source:

| Don't write | Write instead |
|---|---|
| a schedule ("every 15 minutes") | `schedule: null`, plus an unknown |
| a table-to-table mapping not in DB-03 or the ETL docs | the flow at 0.3, plus an open question |
| a consumer not named in any document | leave it out, or add a question if someone mentioned it |
| a read or write direction from column names | direction `null`, plus an unknown |

## Output

Write `{{KB_DB_DOCS}}/11_DB_DATA_LINEAGE.yaml`. Start with comment lines for the product, source
(`{{SNOWFLAKE_DB}}.{{DB_SCHEMA}}`), environment ({{DB_ENV}}), the date ({{RUN_DATE}}),
`prompt_id: DB-11`, prompt version 2.0.0 and the confidence scale. Then these sections:
`metadata` (with the list of input documents), `inbound_flows`, `internal_flows`,
`outbound_flows`, `sensitive_flows`, `open_questions`, `assumptions`, `unknowns`.

Each flow has these fields:

```yaml
- id: <IN|INT|OUT>-<n>
  from: <system, schema or table>
  to: <tables or system>
  method: <how, or null>
  trigger: <event or schedule, or null>
  source: <"DB-03 §<n>" | "domain context §<n>" | "VALIDATION_LOG Q<n>" | "unknown">
  confidence: <1.0 | 0.8 | 0.6 | 0.3>
```

## Evidence rules

- `1.0`: a query result or an answered validation-log item.
- `0.8`: a statement in DB-03, the ETL docs or the domain context.
- `0.6`: an assumption. It is also listed under `assumptions`.
- `0.3`: not known. It is also listed under `open_questions` or `unknowns`.

## Self-check

- [ ] The file parses as YAML.
- [ ] Every flow has `source` and `confidence`.
- [ ] No schedule, direction or consumer appears without a source.
- [ ] Every restricted view schema appears in `sensitive_flows`.
- [ ] Every 0.3 flow is on `open_questions` or `unknowns`.

## Open questions, assumptions and unknowns

End the file with three lists:

- `open_questions`: text, and the owner who can answer.
- `assumptions`: text, and what changes if it's wrong.
- `unknowns`: text, and who could answer.
