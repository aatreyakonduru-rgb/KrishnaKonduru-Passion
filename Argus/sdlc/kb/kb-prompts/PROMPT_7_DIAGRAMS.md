---
prompt_id: APP-07
title: Module architecture and flow diagrams
kind: prompt
pipeline: app
stage: 7
version: 2.0.0
shareable: true
requires: []
depends_on: [APP-01, APP-03, APP-04, APP-06]
placeholders: [PRODUCT_NAME, DOMAIN_CONTEXT, KB_MODULE_DOCS, MODULE_NAME, MODULE_SOURCE, RUN_DATE]
outputs: ["{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/06_ARCHITECTURE_DIAGRAMS.md"]
---

# APP-07: Module architecture and flow diagrams

## Purpose

Draw `{{MODULE_NAME}}` as Mermaid diagrams: where it sits in {{PRODUCT_NAME}}, its parts, its
routes, its data flows, its auth, its lifecycles and how it's deployed. Every box and arrow
comes from a document or file. A diagram with a made-up link is worse than having no diagram.

## Before you start

1. Render with the module: `prompts.py render PROMPT_7_DIAGRAMS.md --set MODULE_NAME=<name> --set MODULE_SOURCE=<folder>`. The module's source is in `{{MODULE_SOURCE}}`.
2. Read the domain context at `{{DOMAIN_CONTEXT}}`: the architecture, systems and environments.
3. Read `00_DISCOVERY_REPORT.md`, `02_FUNCTIONAL_REQUIREMENTS.md`, `03_TECHNICAL_REQUIREMENTS.md`
   and `05_PROCESS_DOCUMENTATION.md` in `{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/`. Stop if 00 or 03
   is missing.

## Steps

Draw each diagram that applies. Skip the ones that don't, and give the reason.

1. **System context.** The users, this product and the outside systems it talks to (identity,
   database, downstream, storage). Show only the systems in config or the domain context.
2. **Components.** This module's main parts (routers, services, data access, shared libraries,
   pages, stores) and how they call each other.
3. **Route map.** The routes grouped by area, with the method and the handler.
4. **Data flow.** How data moves from a user action through this module to its tables, and
   then on to sync and downstream jobs. Label each arrow with how it moves.
5. **Authentication.** The login redirect, the token, the checks and the role lookup, as a
   sequence diagram.
6. **Lifecycles.** One state diagram for each entity with a status. Use the exact values from
   the FRD.
7. **Deployment.** Environments, containers or functions, ingress and the data stores. Show
   only what the deploy config or the domain context states.
8. **Workflows.** A flowchart for each multi-step wizard or approval chain in the FRD.
9. **Check each diagram.** It must parse as Mermaid. Every node must appear in a source, and
   every edge must have a label or a source note.

## Output

Write `{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/06_ARCHITECTURE_DIAGRAMS.md`, starting with:

```yaml
---
document: Architecture and flow diagrams
product: {{PRODUCT_NAME}}
module: {{MODULE_NAME}}
version: <n>
generated_date: {{RUN_DATE}}
prompt_id: APP-07
prompt_version: 2.0.0
---
```

For each diagram, give:

- a heading;
- one sentence on what it shows;
- the Mermaid block;
- a sources list, with each node or edge group mapped to its source.

Then Open questions, Assumptions, Don't know and Files read.

## Evidence rules

- Each node or edge group is backed by `[E: <file>]`, `[E: <doc> §<n>]` or `[E: domain context §<n>]`.
- A link you believe exists but can't source is drawn dashed, labelled `[?]`, and listed.
- Anything taken as true without a source is `[A]` and goes on the Assumptions list.
- Hosts, account IDs and secrets never appear in a diagram. Use role names, such as "prod database".

## Self-check

- [ ] Every diagram parses.
- [ ] Every lifecycle value matches the FRD.
- [ ] Every dashed or `[?]` edge is on the Don't know list.
- [ ] No hosts, account IDs or secrets appear.
- [ ] Every `[A]` and `[?]` is on its list.

## Open questions, assumptions and unknowns

End with three lists:

- **Open questions:** each with an owner by role (architect, DevOps, tech lead).
- **Assumptions:** each `[A]`, and what changes if it's wrong.
- **Don't know:** each `[?]`, with who could answer.
