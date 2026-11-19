---
prompt_id: DB-06
title: Database security and sensitive-data review
kind: prompt
pipeline: db
stage: 6
version: 2.0.0
shareable: true
requires: [snowflake]
depends_on: [DB-01]
placeholders: [PRODUCT_NAME, KB_DB_DOCS, SNOWFLAKE_DB, DB_SCHEMA, DB_ENV, DB_RESTRICTED_VIEW_SCHEMAS, RUN_DATE]
outputs: ["{{KB_DB_DOCS}}/06_DB_SECURITY_REVIEW.md"]
---

# DB-06: Database security and sensitive-data review

## Purpose

Record how the {{PRODUCT_NAME}} database protects sensitive data: restricted view layers, masking
and row access policies, classification columns, grants and schema access settings. The
readers are security reviewers, DBAs and anyone setting up an AI agent's access. This stage can
run at the same time as DB-04 and DB-05.

## Before you start

1. Render this prompt: `prompts.py render DB_PROMPT_6_SECURITY.md --env <env>`.
2. Read `{{KB_DB_DOCS}}/00_DB_DISCOVERY_REPORT.md`. It must contain Q2, Q6, Q9 and Q10 results,
   or failure notes for them. If it doesn't, stop and rerun DB-01.
3. The queries below are read-only. Some need a higher role. If one fails, record the error and
   carry on. Don't ask for more access in this stage.

## Steps

1. **Restricted view layers.** For each restricted view schema, give its view count (Q9), its
   comment as stored (Q2) and its likely base tables (Q9). Quote comments exactly.
2. **Classification columns.** If Q6 found header columns that classify rows (such as a security
   level or an offshore-access flag), list each one with its default and how many tables carry
   it. If Q6 found none, say so.
3. **Tenancy.** If Q6 found client or tenant columns on most tables, list them. Say this makes
   row-level separation possible, not that separation is enforced.
4. **Schema access settings.** Whether each schema uses managed access (Q2), and what that means
   for who can grant access.
5. **Row access policies** (Q10). Each policy with its table and policy schema. If there are none,
   say so. If a schema comment says rows are filtered and no policy explains it, tag the
   mechanism `[?]` and ask the data owner.
6. **Masking inventory** (Q10). A table of schema, view, column and policy, grouped by schema,
   then view. Then:
   - the distinct masked column names, which is the sensitive-column inventory;
   - any column masked in one restricted schema but not another, and any column with different
     policies in different schemas.

   If Q10 failed, say that the inventory isn't available and why. As a fallback, read the
   definition of up to five views, one per business area from DB-02:
   ```sql
   SELECT GET_DDL('VIEW', '{{SNOWFLAKE_DB}}.<restricted schema>.<view>');
   ```
   Say the fallback coverage is partial.
7. **Grants.** Try:
   ```sql
   SHOW GRANTS ON SCHEMA {{SNOWFLAKE_DB}}.{{DB_SCHEMA}};
   SHOW GRANTS ON SCHEMA {{SNOWFLAKE_DB}}.<each restricted schema>;
   ```
   The restricted schemas are: {{DB_RESTRICTED_VIEW_SCHEMAS}}. List the roles on each schema and
   which access level each schema gives. Say which roles look like service accounts only if a
   naming rule in the grants output or the team's documentation shows it. If `SHOW GRANTS`
   fails, record that and tag grants `[?]`.
8. **Compliance summary.** A short list of the controls found above, each with its source. Don't
   state that the system meets a regulation. Say which controls exist and let reviewers judge.
9. **Guidance for AI agents.** Label this section as guidance, not findings. By default, an agent
   should use the most restricted view schema that still does the job. It should never change
   policies or grants, and it should get approval before reading unmasked data. Name the role it
   should use only if the grants output shows one. Otherwise tag it `[?]` and ask the security team.

## Output

Write `{{KB_DB_DOCS}}/06_DB_SECURITY_REVIEW.md`, starting with:

```yaml
---
document: DB security review
product: {{PRODUCT_NAME}}
source_db: {{SNOWFLAKE_DB}}
schema: {{DB_SCHEMA}}
environment: {{DB_ENV}}
generated_date: {{RUN_DATE}}
inputs: [00_DB_DISCOVERY_REPORT.md]
prompt_id: DB-06
prompt_version: 2.0.0
---
```

Sections, in order: Restricted view layers, Classification columns, Tenancy, Schema access
settings, Row access policies, Masking inventory, Grants, Compliance summary, Guidance for AI
agents, Failed queries, Open questions, Assumptions, Don't know.

## Evidence rules

- Facts are tagged with their source: `[E: DB-01 Q10]`, or `[E: SHOW GRANTS <schema>]` for queries run here.
- Schema comments are quoted exactly, with their source.
- Anything taken as true without a source is `[A]` and goes on the Assumptions list.
- Anything not known is `[?]` and goes on the Don't know list.
- Never copy data values from rows. Only metadata goes in this document.

## Self-check

- [ ] Every restricted view schema has a view count and its comment, or a failure note.
- [ ] The masking inventory is complete, or clearly marked partial with the reason.
- [ ] Grants are listed, or the failure is recorded.
- [ ] The guidance section is labelled as guidance.
- [ ] No data values, people's names or credentials appear.
- [ ] Every `[A]` and `[?]` in the body is on its list.

## Open questions, assumptions and unknowns

End with three lists:

- **Open questions:** each names who can answer (security team, DBA, data owner). Include every
  filtering or masking mechanism that couldn't be confirmed.
- **Assumptions:** each `[A]`, and what changes if it's wrong.
- **Don't know:** each `[?]`, with who could answer.
