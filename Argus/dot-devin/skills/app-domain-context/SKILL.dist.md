---
name: app-domain-context
description: Load Acme Claims domain context before any documentation task
argument-hint: "[module_name]"
visibility: internal
triggers:
  - user
  - model
allowed-tools:
  - read
---

# Skill: Acme Claims domain context

Loads the domain context that every KB prompt and SDLC stage relies on: the business terms,
modules, data architecture, roles and compliance rules that the code alone doesn't show.

## When invoked

1. Read the file named by `product.domain_context` in `.devin/rules/kb-profile.yaml`
   (`.devin/rules/DOMAIN_CONTEXT.md`). The KB keeps a copy for its readers at
   `docs/knowledge-base/SHARED/DOMAIN_CONTEXT.md`. If the two differ, use the
   newer one and say that they differ.
2. When the task needs detail the context file doesn't hold (Snowflake schemas, the run-request
   lifecycle, contract type codes, disaster recovery, dependency and script inventories, the
   resources index), read the matching section of
   `docs/knowledge-base/SHARED/DOMAIN_CONTEXT_REFERENCE.md`.
3. If `[module_name]` is given, also read that module's `00_DISCOVERY_REPORT.md` under
   `paths.module_docs`.
4. Confirm in one line which files were loaded and when each was last updated.

If the context file is missing, stop and say so. A new team builds it with `/kb-context-build`.
This skill only loads it.

## Output

"Domain context loaded: <files>". Then carry on with the task that asked for it.
