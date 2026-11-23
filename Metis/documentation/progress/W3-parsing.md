# Workstream W3: Code Parsing and Column Lineage

## Status
- **Item 1: Code Dependency Links (`tools/code_links.py`)**: Done
- **Item 2: Column-Level Lineage (`tools/column_lineage.py`)**: Done
- **Item 3: Column Impact (`column_impact` in `column_lineage.py`)**: Done

## Files Created / Modified
- `metis-1.2.5-team (1)/tools/code_links.py` (New): Extracts code dependency links for Java (Spring, JPA, queries), TypeScript/JavaScript (NestJS, Express, fetch/axios, TypeORM), and Python (AST, Flask, FastAPI, Django, raw SQL). Uses tree-sitter when installed with pure-Python fallbacks. Writes `CROSS-LAYER/parsed.code.links.yaml` or merges into `parsed.links.yaml`. Includes `symbols_for(path)`.
- `metis-1.2.5-team (1)/tools/column_lineage.py` (New): Column-level lineage parser with sqlglot (optional, guarded). Traces target column -> source table.column across SELECT, CTEs, JOINs, aggregates, CASE, INSERT ... SELECT, CREATE TABLE/VIEW AS, and dbt models (ref/source/jinja). Includes catalogue-aware mode for expanding SELECT * from db catalogue snapshot. Includes `column_impact(kb, table, column)` and CLI.
- `metis-1.2.5-team (1)/tools/gen_graph.py` (Modified): Small backwards-compatible edit to treat any file matching `parsed.*.links.yaml` as having `origin: parsed`.
- `metis-1.2.5-team (1)/tools/tests/test_code_links.py` (New): 11 unit tests covering Python, Java, TypeScript, symbols, unparsed cases, citations, merge-into-parsed, and origin derivation.
- `metis-1.2.5-team (1)/tools/tests/test_column_lineage.py` (New): 7 unit tests covering dbt models, CTE chains, aggregates/CASE, INSERT/CREATE AS, catalogue-aware SELECT * expansion, column impact walk, and CLI.

## How to Run
```powershell
# Run tests
cd "metis-1.2.5-team (1)\tools"
python -m unittest tests.test_code_links tests.test_column_lineage tests.test_sql_links -v

# Run code links CLI
python code_links.py <kb> [--out <file>] [--merge-into-parsed]

# Run column lineage CLI
python column_lineage.py build <kb> [--dialect <dialect>] [--out <file>]
python column_lineage.py impact <kb> <table.column> [--depth N] [--limit N]
```

## Test Results
- `tests.test_code_links`: 11 tests passed (0 failures, 0 errors)
- `tests.test_column_lineage`: 7 tests passed (0 failures, 0 errors)
- Combined with `tests.test_sql_links`: 31 tests passed in 0.66s

## Smoke Test Counts & Resolution Rates
- **Spring Petclinic (`sandbox/repos/spring-petclinic`)**:
  - 50 Java files seen, 50 parsed (100% resolution).
  - 434 verified dependency links created:
    - 368 `imports`
    - 21 `references` (inheritance / interfaces / repository entities)
    - 7 `reads_table` (@Table, @Entity, @Query)
    - 19 `exposes_endpoint` (@GetMapping, @PostMapping)
    - 19 `handled_by`
  - 0 unparsed, 0 dropped.
- **Jaffle Shop (`sandbox/repos/jaffle-shop`)**:
  - 15 SQL files seen, 13 dbt model files parsed (100% of SQL model files with target; 2 macro/generic files with no target query).
  - 38 verified column lineage links created mapping mart and staging columns to raw sources.
  - Multi-hop column impact verified (e.g. `ecom.raw_orders.ordered_at` -> `stg_orders.ordered_at` [depth 1] -> `order_items.ordered_at` [depth 2]).
  - 0 unresolved, 0 dropped.

## Limits
- Complex dynamic SQL constructed at runtime via string concatenation without constants cannot be statically resolved and is reported under `unparsed`/`unresolved`.
- Reflection (`Class.forName`, `getattr`) is detected and placed in `unparsed` rather than guessing edges.
- Unexpanded `SELECT *` on base tables without DB catalogue snapshots are reported in `unresolved`.

## Hooks for the Integrator
- In `templates/kb-profile.yaml` (optional settings):
  - `parse.dialect`: optional dialect override for SQL and column parsing (e.g., `snowflake`, `postgres`, `bigquery`).
- In `build_outputs.py` / pipeline:
  - Add `code_links.main([kb])` and `column_lineage.main(["build", kb])` as automated parsing steps when generating CROSS-LAYER links.
