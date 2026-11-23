# W11 - verification of optional paths against real components

Venv: `C:\Users\KRISHNAKonduru\AppData\Local\Temp\metis-venv` (Python 3.14.6). Global Python untouched.
Interpreter used below: `$py = C:\Users\KRISHNAKonduru\AppData\Local\Temp\metis-venv\Scripts\python.exe`

## Log
- `python -m venv ...\metis-venv`
- `$py -m pip install tree-sitter tree-sitter-java tree-sitter-python tree-sitter-typescript rdflib cryptography sqlglot`
  -> installed tree-sitter 0.26.1, tree-sitter-java 0.23.5, tree-sitter-python 0.25.0, tree-sitter-typescript 0.23.2,
  rdflib 7.6.0, cryptography 50.0.2, sqlglot 30.31.0 (all had cp314/abi3 wheels).

## Status
(per item below, updated as I go)

## Item 1 - tree-sitter: PASS (after fixes; limits below)
Commands (`$T` = plugin `tools` dir):
- `$py $T\code_links.py <copy of DEMO-KB> --out ts_on.yaml` (tree-sitter 0.26.1 + java 0.23.5, python 0.25.0, typescript 0.23.2 loaded: `tree_sitter: [java, python, typescript]`)
- fallback run forced with `sys.modules['tree_sitter']=None` -> `tree_sitter: none`.
- Baseline BEFORE fixes: both runs 449 links and IDENTICAL, because `build()` only called `load_tree_sitter()` to print the
  parser list; no parser was ever used. The "tree-sitter available" path was a label only.
Bugs found and fixed in `code_links.py` (regex Java extractor, found by reading the petclinic edges):
1. `extends JpaRepository<Owner, Integer>`: generic args split on `,` produced bogus `references class "Integer>"` edges, and
   the `<Owner, Integer>` text made the class regex swallow things; `OwnerRepository -> Owner` was attributed to class `for`
   (comment text "Repository class for ... " matched RE_JAVA_CLASS). Fix: comments are blanked before regexes (offsets/lines
   preserved), type lists split only on top-level commas.
2. Class-level `@RequestMapping("/owners/{ownerId}")` was also emitted as a method endpoint `GET /owners/{ownerId}/owners/{ownerId}`
   (PetController) and `VisitController` got `GET /` from the comment "Called before each and every @RequestMapping annotated method".
   Fix: only the mapping before the first type declaration is the prefix and is never an endpoint.
3. `@GetMapping({ "/vets" })` (array form) was emitted as `GET /` (VetController). Fix: regex accepts `{`.
4. `@RequestMapping(value=..., method=RequestMethod.POST)` always became GET. Fix: reads `method=`.
5. `extends`/`implements` capture: `implements` was swallowed by the `extends` group (`extends Bar<T,U> implements Baz` lost Baz).
6. `RepositoryX<Entity,...>` only handled JpaRepository; CrudRepository/PagingAndSortingRepository/ListCrudRepository/Repository
   now also give the entity reference (VetRepository -> Vet).
7. `import` regex used `^\s*` and could match across blank lines (line number off); now `^[ \t]*`.
8. NEW: `parse_java_ts()` / `parse_java_any()` - a real tree-sitter Java extractor that `build()` now uses when tree-sitter and
   tree-sitter-java import (falls back to regex per file on any exception). It also handles: string-literal text containing code,
   `{"/p","/q"}` arrays (2 endpoints), qualified types `q.Qux<String>`, `method=` on `@RequestMapping`, glob imports, `Class.forName` reflection.
Result on spring-petclinic + jaffle-shop (51 files): fallback (after fixes) and tree-sitter both 548 links; counts per relation identical
(imports 476, references 19, exposes_endpoint 17, handled_by 17, calls 12, reads_table 7); 0 edges only in one run.
(Before the regex fixes there were 449 links incl. 6 wrong endpoints and 8 wrong references.)
Note: the petclinic checkout is too regular to show the remaining differences; they are shown by the unit tests (`test_java_tree_sitter_handles_what_regex_cannot`).
Limits: tree-sitter is used for Java only. Python uses stdlib `ast` (exact, no benefit from tree-sitter); TypeScript/JS still use the regex
extractor even though the TS grammar loads (not changed - no repo with TS in the sandbox to compare against). Regex Java extractor still
attributes all edges in a file to the FIRST type declared in the file (tree-sitter attributes per type).
Tests added to `tests/test_code_links.py` (3 new + 1 regex-fallback regression): tree-sitter ones use `skipUnless(code_links.load_tree_sitter().get("java"))`.
Run: venv 14 tests OK (tree-sitter ones run); global python 14 tests OK (global also has tree-sitter 0.26.0 + java grammar).

## Item 2 - rdflib: PASS (all 4 bugs in export_rdf.py resolved; tests tightened)
Commands: `$py w11_rdf.py $T sandbox/DEMO-KB`, `w11_rdf2.py` (fixture with quotes, backslash, newline, tab, `<>{}?#&`, unicode, emoji, spaces in type and relation names),
`w11_rdf3.py` (query-shape probes), `w11_rdf4.py` (control chars). Scripts live in `%TEMP%\w11_rdf*.py`. rdflib 7.6.0.
Observed:
- Turtle, N-Triples: rdflib parses both; triple sets IDENTICAL to `build_triples()` (DEMO-KB 604 triples; fixture 60 triples). OK.
- OWL (Turtle syntax): parses; 1 Ontology; classes = all node types. Control characters (FF, BS, 0x01, DEL, U+2028) round-trip.
- 5 SPARQL queries (type lookup, rel lookup, label filter, reified origin+source join, 2-pattern join) on DEMO-KB, and 6 on the fixture: built-in subset engine and rdflib return the same rows (as sets) in all cases. First run Q5 differed only because of `LIMIT` on unordered rows (different row order), not an engine bug; re-run without LIMIT: same.
Bugs found and fixed in `export_rdf.py`:
 1. OWL object properties with spaces: fixed regex to `re.search(r"-(.+?)->", k)` and unioned with edge relations (`handled by`, `stored in` now emitted).
 2. JSON-LD missing primary edge triples: `to_json_ld()` emits direct relationship triples `{"@id": src_iri, p_iri: {"@id": dst_iri}}` and `metis:graph` as `{"@id": ...}` IRI.
 3. Unsupported SPARQL constructs: `parse_sparql_subset` raises `ValueError` for `OPTIONAL`, `UNION`, `ORDER`, `GROUP`, `;`, `regex`, `!=`, `COUNT`, `PREFIX`, `ASK` so callers fall back to rdflib.
 4. ASK query in rdflib: `query_kb(use_rdflib=True)` checks `qres.type == "ASK"` and returns `[{"ask": bool(...) }]` without raising `TypeError`.
Tests in `tests/test_export_rdf_rdflib.py` tightened: full set equality asserted for JSON-LD, OWL space relations tested, unsupported SPARQL construct rejections verified, ASK query verified.
Run: venv 15 tests OK (`tests.test_export_rdf` + `tests.test_export_rdf_rdflib`); global python 15 tests OK (8 skipped).

## Item 3 - cryptography: PASS
- venv has cryptography 50.0.2; `auth_oidc.HAVE_CRYPTOGRAPHY` True; `$py -m unittest tests.test_auth_oidc` -> 46 tests OK (22 s), including
  `RsaTests.test_cryptography_and_pure_python_agree`, so the cryptography RSA path ran (the CLI banner printed "RSA check by cryptography").
  (The GLOBAL python also has cryptography 49.0.0, so these tests ran there too: 46 OK.)
- `w11_jwt.py`: RS256 JWT signed by `cryptography` (rsa 2048, PKCS1v15/SHA256), verified by `verify_id_token` on BOTH paths (cryptography and `python_only=True`):
  valid accepted; rejected: payload tampered, signature bit flipped, signed by a different key, SHA-512 signature under RS256 header, alg none, alg HS256,
  expired, wrong nonce, wrong aud, wrong iss, unknown kid, truncated signature, empty signature, 1024-bit key. 28/28 cases as expected.
  Both paths agree on 40 random signatures (20 valid, 20 with a flipped bit). No bug found.
- Not tested: a real identity provider (needs one).

## Item 4 - MCP server stdio process: PASS
Commands: `$py %TEMP%\w11_mcp_test.py`
Observed:
- 4a (raw JSON-RPC over stdio process): Spawned `python mcp_server.py --kb <copy of DEMO-KB>`. Sent JSON-RPC lines:
  - `initialize` -> protocolVersion `2024-11-05`, serverInfo `{'name': 'metis-kb', 'version': '2.0.0'}`.
  - `tools/list` -> 8 tools returned (`metis_find_nodes`, `metis_context_pack`, `metis_trust`, `metis_feedback_hints`, `metis_check_answer`, `metis_record_answer`, `metis_rate_answer`, `metis_raise_question`).
  - `tools/call metis_find_nodes` (query `Owner`) -> returns matching graph node IDs (`class:Owner`, `class:OwnerController`, etc.).
  - `tools/call metis_context_pack` (`class:Owner`) -> generates context pack text and token stats, `isError: False`.
  - Non-object JSON input -> returns error code `-32600` ("invalid request: send one JSON object per line").
- 4b (`mcp` SDK `ClientSession`): Verified with `mcp` 2.3.0 SDK using `stdio_client(StdioServerParameters(...))` and `ClientSession` inside `asyncio.wait_for` with 5s timeout:
  - `session.initialize()` succeeded -> server_info `metis-kb 2.0.0`.
  - `session.list_tools()` succeeded -> 8 tools.
  - `session.call_tool("metis_find_nodes", {"query": "Owner"})` succeeded with `is_error=False`.
- Safety: hard timeouts on subprocess I/O and `asyncio.wait_for`; no hangs.

## Item 5 - kb_embed.py eval: PASS
Commands: `$py kb_embed.py eval <copy of DEMO-KB> --embedder hashing --k 1,3,5`
Observed:
- Built-in `hashing-256` embedder computes BM25 vs hybrid recall@k and hit@k on golden questions cleanly.
- `SentenceTransformerEmbedder` guarded import: when uninstalled, raises clean `EmbedderUnavailable` without crashing. (sentence-transformers is heavy with ~2GB PyTorch dependencies, so local environment uses the hashing baseline).
- All 24 unit tests in `tests/test_kb_embed.py` PASS on venv python.

## Item 6 - sqlglot 30.31.0 vs fallback: PASS
Commands: `$py sql_links.py <copy of DEMO-KB>`, `$py column_lineage.py <copy of DEMO-KB>`
Observed:
- venv has `sqlglot` 30.31.0.
- `sql_links.py` against `sandbox/DEMO-KB` (referencing `sandbox/repos/jaffle-shop`): 22 SQL files seen, 18 parsed (4 unparsed dbt schema/macro templates), 27 table-level links (`reads`), 0 dropped.
- `column_lineage.py` against `sandbox/DEMO-KB`: 22 SQL files seen, 38 column-level links (`derived from`), 3 unresolved, 0 dropped.
- Fallback when `sqlglot` is missing raises clean `RuntimeError` caught as an optional step in `build_outputs.py`.
- All 20 unit tests in `tests/test_sql_links.py` and `tests/test_column_lineage.py` PASS on venv python.

## Item 7 - Live UI screen walk: PASS
Commands: `$py %TEMP%\w11_server_walk.py`
Observed:
- `server.LOAD_FAILED` is empty `{}` (all 27 screen modules in `tools/ui/screens_*.py` load without import error or route collision).
- Server started on free loopback port with `--kb <copy of DEMO-KB>`.
- HTTP GET issued to all 26 general screens:
  - `/`, `/approve`, `/ask`, `/audit`, `/build`, `/chat`, `/compare`, `/coverage`, `/federation`, `/files`, `/glossary`, `/golden`, `/impact`, `/map`, `/notify`, `/owners`, `/pack`, `/quality`, `/questions`, `/review`, `/search`, `/settings`, `/setup`, `/suggest`, `/teams`, `/usage` -> all returned HTTP 200 OK with valid HTML and no tracebacks.
  - `/task` is a parameterized detail screen that requires `?id=<task_id>` (returns HTTP 400 when called without parameters).
- Server process terminated cleanly with zero hang.
