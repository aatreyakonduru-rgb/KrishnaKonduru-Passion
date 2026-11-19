# KB registry generators

Deterministic generators for the four machine-readable KB registries the SDLC skills
read. They exist because those registries are consumed programmatically (`/research`
gap analysis, `/impact-radar`, `/source-staleness-check`) and so must be exact: handler
names, line numbers, schema field types and table I/O are extracted from source rather
than described. The narrative KB documents remain the job of `/app-run-pipeline`.

Nothing here connects to a database or imports the application — an AST walk for Python,
static scans for TypeScript and SQL.

| Script | Reads | Writes |
|---|---|---|
| `extract_api.py` | `api/apps/**/api.py`, `schema.py` | `api.json` on stdout |
| `gen_api_kb.py` | `api.json` | `MODULES/…/api/10_ENDPOINT_REGISTRY.yaml`, `11_API_DATA_CONTRACTS.yaml` |
| `gen_ui_kb.py` | `web/src/**`, `10_ENDPOINT_REGISTRY.yaml` | `MODULES/…/web/12_COMPONENT_REGISTRY.yaml` |
| `gen_etl_kb.py` | `claims-etl/scripts/**`, `DB_TABLE_REGISTRY.yaml` | `ETL/claims-etl/13_ETL_TABLE_IO_CONTRACT.yaml` |
| `gen_cross_module_matrix.py` | the four registries above, `api/apps/**` + `modules/**` SQL/Python, `web/src/app/**`, `DB-DOCS/<env>/13_UI_TO_DATA_FIELD_MAPPING.yaml`, `FIGMA-DERIVED/01_FIGMA_ACME_PROTOTYPE.md`, `CONFLUENCE-DERIVED/03_UI_SCREEN_FLOWS.md` + `05_TEST_CASE_CATALOGUE.md`, `CROSS-LAYER/*.CURATED.yaml` | `CROSS-LAYER/CROSS_LAYER_IMPACT_MATRIX.yaml` — change a column / endpoint / screen → everything it touches, with file:line |
| `gen_ontology.py` | entity registry, semantic layer, lineage, data contracts, table registry, FeedFile catalogue, column glossary, app joins, ETL table I/O and SQL patterns, curated impact chains, `DB-DOCS/SIT/22_DB_COLUMN_SNAPSHOT.yaml` | `CROSS-LAYER/ACME_ONTOLOGY.yaml` + `.html` — business layer over data layer, every item naming its source file; the page is also the Ontology tab on the tech-lead dashboard |
| `gen_link_graph.py` | `CROSS-LAYER/ACME_ONTOLOGY.yaml`, `CROSS-LAYER/CROSS_LAYER_IMPACT_MATRIX.yaml`, import lines of the test files under `web/src/__tests__` and `api`, and commits whose message names a Acme Claims story | `CROSS-LAYER/ACME_LINK_GRAPH.yaml` — stories, objects, tables, columns, endpoints, screens, jobs, systems, code files and test files as nodes, typed links each naming its file:line, KB entry or commit; `ontology_lookup.py walk` / `drift` read it |

## Run

```bash
cd sdlc/framework/tools/kbgen
python3 extract_api.py > api.json
python3 gen_api_kb.py api.json
python3 gen_ui_kb.py
SDLC_ETL_REPO=../../../../../claims-etl python3 gen_etl_kb.py
python3 gen_cross_module_matrix.py            # reads the other registries; --env sit|uat|prod picks the field map
python3 gen_ontology.py                       # reads the registries above and the T01 column snapshot
python3 gen_link_graph.py                     # last: reads the ontology and the matrix (--check: exit 1 when stale)

# or all of the above that Devin Cloud can build, in order, with a check mode:
python3 ../kb_sync.py [--check] [--base origin/feature/devin-sdlc]
python3 ../ontology_lookup.py check           # confirms the committed ontology matches; the skills read it through ontology_lookup.py
```

`gen_etl_kb.py` defaults to a sibling `claims-etl` checkout
(`https://git.acme.example/ACMEETL/claims-etl.git`); set
`SDLC_ETL_REPO` to point elsewhere. The Glue and Lambda repos are not covered.

`gen_ui_kb.py` needs the API registry to be regenerated first — it resolves every
frontend endpoint symbol against it and records the misses under
`unmatched_against_api_registry`.

Requires PyYAML only.
