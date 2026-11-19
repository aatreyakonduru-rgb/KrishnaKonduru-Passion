---
prompt_id: APP-12
title: UI component registry (YAML)
kind: prompt
pipeline: app
stage: 12
version: 2.0.0
shareable: true
requires: []
depends_on: [APP-01, APP-03, APP-04, APP-10]
placeholders: [PRODUCT_NAME, KB_MODULE_DOCS, MODULE_NAME, MODULE_SOURCE, RUN_DATE]
outputs: ["{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/12_COMPONENT_REGISTRY.yaml"]
---

# APP-12: UI component registry (YAML)

## Purpose

A machine-readable map of the {{PRODUCT_NAME}} frontend module `{{MODULE_NAME}}`, going from
each route to its page file, its components, the API calls each makes and when, its form
fields, its state store and the roles allowed in. An AI agent uses it to find where a screen
lives and what a change to it touches. Run it for UI modules only.

## Before you start

1. Render with the module: `prompts.py render PROMPT_12_COMPONENT_REGISTRY.md --set MODULE_NAME=<name> --set MODULE_SOURCE=<folder>`.
2. Read `00_DISCOVERY_REPORT.md`, `02_FUNCTIONAL_REQUIREMENTS.md` and
   `03_TECHNICAL_REQUIREMENTS.md` in `{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/`.
3. Read the endpoint registry (`10_ENDPOINT_REGISTRY.yaml`) of each API module this frontend
   calls, from its folder under `{{KB_MODULE_DOCS}}`. If there isn't one, API calls still get
   listed, with `endpoint_id: null`.
4. Read the route or page folders, the API client files and the state stores under
   `{{MODULE_SOURCE}}`.

## Steps

For each route in code:

1. Map the route path to its page file.
2. List the components it renders, with file paths. Give each a type, such as data table, filter
   bar, form, multi-step form, modal or chart.
3. For each component: its API calls (method, path and trigger, such as on mount, on change or
   on submit) and its form fields.
4. For multi-step forms, list each step with its name, fields, API calls, and submit endpoint.
5. Name the state it uses: context, store, or local state.
6. Record the route's auth and role requirements, using the guard or role check in code.
7. Match each API call to its endpoint ID in the registry. List the calls that don't match.

## Output

Write `{{KB_MODULE_DOCS}}/{{MODULE_NAME}}/12_COMPONENT_REGISTRY.yaml`:

```yaml
metadata:
  product: {{PRODUCT_NAME}}
  module: {{MODULE_NAME}}
  framework: <name and version, from discovery>
  base_path: <from config>
  state_management: <what's used>
  generated_date: {{RUN_DATE}}
  prompt_id: APP-12
  prompt_version: 2.0.0
routes:
  - path: <route>
    page_file: <path>
    description: <one line>
    auth_required: <bool>
    roles: [<role from code>]
    state_store: <name or null>
    components:
      - name: <name>
        file: <path>
        type: <type>
        fields: [<field>]
        api_calls: [{method: <m>, path: <p>, trigger: <when>, endpoint_id: <EP id or null>}]
        steps: [{name: <step>, fields: [<field>], api_calls: [...]}]
        submit: {endpoint: <"METHOD path">, trigger: <what>}
    source: [<"path:line">]
    confidence: <1.0 | 0.8 | 0.6>
unmatched_api_calls: [<"METHOD path" at "file:line">]
open_questions: []
assumptions: []
dont_know: []
```

## Evidence rules

- Each route and component has a `source` of `[E: <file>:<line>]`.
- A role or trigger you can't see in code is `[?]`, and goes in `dont_know`.
- Anything taken as true without a source is `[A]` and goes in `assumptions`.
- No route or component is listed unless its file exists.

## Self-check

- [ ] Every route in code has an entry.
- [ ] Every component has a file, a type, and its API calls (or an empty list).
- [ ] Multi-step forms list their steps.
- [ ] API calls are matched to the registry, or listed as unmatched.
- [ ] The file parses as YAML.
- [ ] Every `[A]` and `[?]` is in its list.

## Open questions, assumptions and unknowns

Fill the three lists at the end of the YAML:

- **Open questions:** each with an owner by role (frontend developer, UX designer).
- **Assumptions:** each `[A]`, and what changes if it's wrong.
- **Don't know:** each `[?]`, with who could answer.
