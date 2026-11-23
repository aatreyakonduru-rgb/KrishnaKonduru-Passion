# W6 Export and Federation Workstream Progress

## Status per Item
1. `tools/export_rdf.py`: done (Turtle, N-Triples, JSON-LD, OWL 2 ontology, RDF-star-free named graphs per origin, reified statement provenance, built-in SPARQL-subset engine [BGP, FILTER =, LIMIT], guarded rdflib import, test suite).
2. `tools/export_prov.py`: done (W3C PROV-O Turtle and PROV-JSON for activities/agents/entities, OpenTelemetry OTLP JSON traces and logs, optional --post to HTTP endpoint, test suite).
3. `tools/okf_bundle.py`: done (OKF-shaped bundle packager with frontmatter + per-folder index.md + okf-manifest.yaml hashes, local validator checking frontmatter/indices/hashes/sensitive data, honest compliance statement, test suite).
4. `tools/shared_index.py`: done (Shared cross-team read index in shared.sqlite, certified-only and non-sensitive enforcement, share: false profile support, register/refresh/search/objects/stats, guarded runtime BM25 search check with pure-Python FTS/term fallback, cross-KB answer citation helper, test suite).
5. `tools/cross_impact.py`: done (Cross-team impact and upstream walks connecting nodes by normalised identity and same_as links, team and origin preservation, ai-proposed flagging for name-only matches, test suite).
6. `tools/ui/screens_federation.py`: done (`/federation` UI screen with registered KBs overview, cross-team search, cross-team impact trace, one-click export actions into `.metis/exports/`, export file browser, test suite).

## Files Created / Modified
### Created Files
- `tools/export_rdf.py`: RDF exporter (Turtle, N-Triples, JSON-LD, OWL ontology) with origin-named graphs and reification, plus built-in SPARQL-subset query command and guarded rdflib support.
- `tools/export_prov.py`: Provenance exporter producing W3C PROV-O (Turtle, JSON) and OpenTelemetry OTLP JSON (traces and logs) with optional `--post` to an OTLP/HTTP endpoint.
- `tools/okf_bundle.py`: Open Knowledge Format bundle packager and validator generating frontmatter, `index.md` in every folder, and `okf-manifest.yaml`.
- `tools/shared_index.py`: Cross-team federated read index in `shared.sqlite` with strict certification gating, sensitive content exclusion, and cross-team Q&A citation helper.
- `tools/cross_impact.py`: Cross-team downstream impact and upstream dependency graph traversals.
- `tools/ui/screens_federation.py`: UI screen at `/federation` with tabs for registered KBs, cross-team search, cross-team impact walks, and one-click export actions.
- `tools/tests/test_export_rdf.py`: Unit tests for `export_rdf.py` including round-trip Turtle parsing (7 tests).
- `tools/tests/test_export_prov.py`: Unit tests for `export_prov.py` including PROV-O, PROV-JSON, and OTLP JSON (5 tests).
- `tools/tests/test_okf_bundle.py`: Unit tests for `okf_bundle.py` including bundling and validation rules (5 tests).
- `tools/tests/test_shared_index.py`: Unit tests for `shared_index.py` (5 tests).
- `tools/tests/test_cross_impact.py`: Unit tests for `cross_impact.py` (3 tests).
- `tools/tests/test_ui_federation.py`: Unit tests for `/federation` UI screen and actions (11 tests).
- `documentation/progress/W6-export-federation.md`: Notes file for W6 workstream tracking.

## How to Run
```bash
# Export RDF / OWL
python tools/export_rdf.py export <kb> [--out <dir>] [--format all|turtle|ntriples|jsonld|owl]
python tools/export_rdf.py query <kb> "SELECT ?s ?name WHERE { ?s <http://www.w3.org/2000/01/rdf-schema#label> ?name . } LIMIT 10"

# Export W3C PROV-O and OpenTelemetry
python tools/export_prov.py prov <kb> [--out <dir>] [--format all|turtle|json]
python tools/export_prov.py otel <kb> [--out <file>] [--post] [--endpoint <url>]

# OKF Bundle Packager and Validator
python tools/okf_bundle.py bundle <kb> [--out <dir>]
python tools/okf_bundle.py validate <bundle_dir_or_kb>

# Shared Cross-Team Read Index
python tools/shared_index.py register <shared.sqlite> <kb> [--name <name>]
python tools/shared_index.py refresh <shared.sqlite> [--name <name>]
python tools/shared_index.py search <shared.sqlite> "<query>"
python tools/shared_index.py objects <shared.sqlite> [--type <type>]
python tools/shared_index.py stats <shared.sqlite>
python tools/shared_index.py helper <shared.sqlite> "<question>"

# Cross-Team Impact Walks
python tools/cross_impact.py impact <shared.sqlite> <node> [--depth 3]
python tools/cross_impact.py upstream <shared.sqlite> <node> [--depth 3]

# Run all W6 unit tests
python -m unittest tests.test_export_rdf tests.test_export_prov tests.test_okf_bundle tests.test_shared_index tests.test_cross_impact tests.test_ui_federation -v
```

## Test Results
All 36 tests passed (0 failures, 0 errors):
- `tests.test_export_rdf`: 7/7 passed
- `tests.test_export_prov`: 5/5 passed
- `tests.test_okf_bundle`: 5/5 passed
- `tests.test_shared_index`: 5/5 passed
- `tests.test_cross_impact`: 3/3 passed
- `tests.test_ui_federation`: 11/11 passed

## Limits
- **SPARQL Engine**: `export_rdf.py query` implements a lightweight SPARQL subset (BGP, `FILTER =`, `LIMIT`) in pure standard Python. For full SPARQL 1.1 features (property paths, OPTIONAL, UNION, aggregations), use `--rdflib` with `rdflib` installed or load the exported `.ttl`/`.nt` files into an external triplestore.
- **OKF Compliance**: `okf_bundle.py` generates an OKF-shaped layout (YAML frontmatter + `index.md` + manifest hashes) validated against Metis's internal consistency rules; formal compliance certification requires the official OKF validator.
- **OpenTelemetry Exporter**: `export_prov.py otel` exports compliant OTLP JSON files locally without requiring background collectors or heavy SDK dependencies; `--post` transmits over standard HTTP POST.

## Hooks for the Integrator
- **Profile Keys in `kb-profile.yaml`**:
  - `share: false` (or `federation.share: false`): Opt-out flag to prevent a KB from being indexed in `shared.sqlite`.
  - `federation.shared_db`: Relative or absolute path to the default `shared.sqlite` cross-team index (defaults to `<KB>/.metis/shared.sqlite`).
  - `otel.endpoint`: Target HTTP endpoint URL for OpenTelemetry trace/log record publication.
- **Auto-discovered UI screen**:
  - `ui/screens_federation.py` exports `SCREENS`, `ACTIONS`, `NAV` (`/federation`, "Federation") for dynamic discovery by `server.py`.
- **Search Integration**:
  - `shared_index.py` guards the import of `tools/kb_search.py` at runtime; when W2's BM25/hybrid search implementation is present, `shared_index.search()` will automatically use it.
