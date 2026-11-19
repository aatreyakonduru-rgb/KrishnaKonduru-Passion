# Knowledge Base Context

## Purpose
This directory contains references to the canonical knowledge base (YAML + Markdown artifacts) used by agents and skills.

## Structure
All KB artifacts remain in their original locations. This directory contains:
- Symlinks (Windows: shortcuts) to canonical KB directories
- Reference documentation for quick lookup

## Canonical KB Locations

### Database Layer
- **Primary**: `docs/knowledge-base/DB-DOCS/`
- **Secondary**: `../../acme_ai_documentation/docs/knowledge-base/DB-DOCS/`
- **Key Files**:
  - `DB_TABLE_REGISTRY.yaml` — Table schemas, PKs, RLS policies
  - `DB_COLUMN_GLOSSARY.yaml` — Column definitions and aliases
  - `DB_SCHEMA_SUMMARY.md` — Human-readable schema overview
  - `DB_CROSS_MODULE_MATRIX.yaml` — Column-to-layer dependency chains
  - `DB_AI_GUARDRAILS.yaml` — Mandatory SQL rules for AI code gen
  - `DB_ENTITY_REGISTRY.yaml` — Alias resolution
  - `DB_DATA_LINEAGE.yaml` — Data flow and transformations

### API Layer
- **Primary**: `docs/knowledge-base/MODULES/claims-web/api/`
- **Secondary**: `../../acme_ai_documentation/docs/knowledge-base/MODULES/claims-web/api/`
- **Key Files**:
  - `API_ENDPOINT_REGISTRY.yaml` — Endpoint definitions, methods, auth
  - `API_DATA_CONTRACTS.yaml` — Request/response schemas
  - `API_COMPONENT_REGISTRY.yaml` — Reusable API components

### UI / Presentation Layer
- **Primary**: `docs/knowledge-base/MODULES/claims-web/web/`
- **Secondary**: `../../acme_ai_documentation/docs/knowledge-base/MODULES/claims-web/web/`
- **Key Files**:
  - `FE_COMPONENT_REGISTRY.yaml` — React components, props, state
  - `FE_DATA_CONTRACTS.yaml` — Frontend data models
  - `FE_ROUTING_MAP.yaml` — Page routes and navigation

### Data Processing Layer (ETL)
- **Primary**: `docs/knowledge-base/ETL/claims-etl/`
- **Secondary**: `../../acme_ai_documentation/docs/knowledge-base/ETL/claims-etl/`
- **Key Files**:
  - `ETL_MODULE_IO_SUMMARY.yaml` — Module inputs/outputs
  - `ETL_INTEGRATION_SCENARIOS.yaml` — Integration patterns
  - `ETL_SQL_PATTERNS.yaml` — Reusable SQL patterns

### Domain Context
- **Primary**: `.devin/rules/DOMAIN_CONTEXT.md` (copy for KB readers: `docs/knowledge-base/SHARED/DOMAIN_CONTEXT.md`), loaded by `/app-domain-context`
- **Reference sections**: `docs/knowledge-base/SHARED/DOMAIN_CONTEXT_REFERENCE.md` (schemas, lifecycles, contract types, DR, inventories)
- **Content**: Business domain, tech stack, roles, known issues

## Usage by Agents
- **Intake Agent**: Loads `DOMAIN_CONTEXT.md`
- **Research Agent**: Loads all registries + cross-module matrix
- **Plan Agent**: Loads registries + coding patterns
- **Implement Agent**: Loads guardrails + verified queries
- **Eval Agent**: Loads validation tests + coverage requirements
- **KB Refresh Agent**: Updates all YAML/MD artifacts

## Provenance
All KB artifacts include provenance metadata:
- Source files (DDL, API specs, UI code)
- Generation timestamp
- Approver (if manually reviewed)
- Last refresh timestamp

## Staleness Detection
KB artifacts are refreshed when:
- Schema changes in Snowflake (detected by staleness check)
- API endpoints deployed (detected by API staleness check)
- UI components added/modified (detected by FE staleness check)
- Post-production deployment (triggered by KB Refresh Agent)
