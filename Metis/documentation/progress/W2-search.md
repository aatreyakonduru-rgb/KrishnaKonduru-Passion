# W2 search and answers: notes

All six items are done. Final run of the six test files together: **107 tests, OK** (Python 3.14.6, FTS5 available).

Plugin root `$METIS` = `metis-1.2.5-team (1)/`. Run commands from `$METIS/tools`.

## Status per item

| # | Item | Status | Tests |
|---|---|---|---|
| 1 | `tools/kb_search.py` BM25 content search, facets, snippets, SQLite cache | done | `tests/test_kb_search.py` 18 |
| 2 | `tools/ui/screens_search.py` `/search` | done | `tests/test_ui_search.py` 12 |
| 3 | `tools/kb_embed.py` hybrid search + eval | done (adapters need your environment to verify) | `tests/test_kb_embed.py` 24 |
| 4 | `tools/kb_unanswered.py` | done | `tests/test_kb_unanswered.py` 16 |
| 5 | `tools/kb_summaries.py` | done | `tests/test_kb_summaries.py` 19 |
| 6 | `tools/ui/screens_chat.py` `/chat` | done | `tests/test_ui_chat.py` 18 |

I edited no existing file. `ui/answers.py` scoring is unchanged.

## Files created (all under `$METIS/tools/`)

`kb_search.py`, `kb_embed.py`, `kb_unanswered.py`, `kb_summaries.py`, `ui/screens_search.py`, `ui/screens_chat.py`, and the six test files above in `tests/`.

## How to run

Tests: `python -m unittest tests.test_kb_search tests.test_kb_embed tests.test_kb_unanswered tests.test_kb_summaries tests.test_ui_search tests.test_ui_chat -v`

(PowerShell shows "NativeCommandError" because unittest writes to stderr. Read the last `Ran N tests ... OK` line.)

- `python kb_search.py index|query|facets|status <KB>`. `query` takes the query text and facet filters. `--engine` picks fts5 or python. The cache is `<KB>/.metis/search.sqlite`. It refreshes by file mtime and size, and a damaged file is rebuilt.
- `python kb_embed.py build|status|query|eval <KB>`. Example: `python kb_embed.py eval <KB> --k 1,3,5,10` scores BM25 against hybrid on the golden questions (`tools/golden.py`). It prints recall@k, hit@k and a verdict.
- `python kb_unanswered.py report|misses|miss <KB>`. `report` is the ranked list. `misses` shows the opt-in hashed counter. `miss` records one.
- `python kb_summaries.py build|status|verify|stage <KB>`. `stage --by NAME` goes through `kb_gate` into `_PENDING/<batch>/summaries/`.
- Screens `/search` and `/chat` are auto-loaded by `ui/server.py`. `/search` has tabs for results and Unanswered.

## Design summary

- **Search.** One chunk per heading section. Title and heading path are boosted 3x. Glossary synonyms from `ui/glossary.py` are added at weight 0.6. FTS5 is used when present, with a pure-Python BM25 over a postings table as the fallback. It skips `_PENDING`, `_FEEDBACK`, `.metis`, generated pages and pages `sensitive.py` blocks. Snippets show the matched line with its `[E:]` tag intact.
- **Facets.** Folder, type (front matter `type:`), owner (`.metis/page_meta.yaml`), has-open-question (a `[?:Q-]` tag or the register's `blocks`), and stale (`review_due` in the past or `stale: true`).
- **Hybrid.** Default OFF (profile `search.hybrid: false`). Embedders are `HashingEmbedder` (deterministic, 256 buckets, no dependencies), `SentenceTransformerEmbedder` (guarded import) and `HttpEmbedder`. The HTTP embedder needs `allow_page_text: true` in the profile. It reads its key from the env var named in `api_key_env`. Vectors are stored in table `vec` in `search.sqlite`. Chunks are embedded with a "page title > heading path:" prefix. Fusion is reciprocal rank (RRF).
- **Unanswered.** `telemetry.py` stores only the KB files an answer used and keeps no question text. So the report reads what already exists:
  - ask records (`.metis/asks/`) with a Low or None band that no later re-ask supersedes,
  - dislikes a lead has not declined,
  - open questions raised via `feedback.py` or `questions.py` ("asked by").
  
  Near-duplicates merge (`feedback.similar` at least 0.8). No new question text is captured. The only addition is an opt-in hashed counter (`search.count_misses: true`). It writes `.metis/usage/misses.json` with a per-KB salted SHA-256 and no query text.
- **Summaries.** `build` writes `<KB>/.metis/summaries/SUMMARY_TREE.yaml` and `PROMPT.md`. Areas come from folders plus graph connectivity (`graph_store.py`). `verify` needs an `[E:]` tag on every non-heading line. Each tag must appear verbatim in a page of that area, and a parent may use its descendants' tags. It also runs `verify_kb` and a secret screen. `stage` is all-or-nothing. A summary page is front-mattered `type: area-summary`. Nothing is written into a locked KB directly.
- **Chat.** `THREADS` is keyed by (kb, lowercase user) and holds the last 20 turns in memory. Each turn calls `answers.ask(mode="local")`, the same answerer as `/ask`. A follow-up passes the previous question's key terms as `direction`. Citations are shown. Like and dislike go through `answers.rate`, and a re-ask joins the thread. Form post per turn, no JavaScript.

## Limits (honest)

- The sentence-transformers adapter and the HTTP embedding adapter **need your environment to verify**. The HTTP adapter was tested only against a fake transport. The sentence-transformers adapter was tested only for the "not installed" path.
- The hashing embedder matches word shape and not meaning. Hybrid gains with it will be small. Run the eval before enabling hybrid.
- FTS5 cannot weight synonyms. The FTS5 engine expands them as plain OR terms. The pure-Python engine applies the 0.6 weight.
- Chat threads are in memory only. They are lost on server restart. They hold last 20 turns per user.
- `kb_unanswered` is only as good as the ask records. If nobody used `/ask` or `/chat`, the report is empty and says so.
- The summary text itself needs a Devin or Bob session to write it (use `PROMPT.md`). The tool builds only the structure, verifies and stages.
- Not verified: behaviour on a very large KB (thousands of pages). The index is incremental, but I did not time it.
- While testing I saw `server.load_screens()` skip a sibling worker's `ui/screens_owners.py`: "action /owners/recalibrate returns to unknown screen /owners?view=recalibrate". That is not my file. The owner of that file should check it.

## Hooks for the integrator

1. `ui/ui_common.py`, in `page()` around line 384. Replace the filename-filter form
   `form(ctx, "/files", '<input type="text" name="find" placeholder="Search KB files" style="width:160px">', method="get")`
   with:

   ```
   find = form(ctx, "/search", '<input type="text" name="q" placeholder="Search the KB" style="width:160px">', method="get")
   ```
   (GET to `/search` with `name=q`.) If you also want to keep the filename filter, link it from the Files screen.
2. `ui/ui_common.py`, `RAIL_ICON` (optional): add `"/search": ("&#8981;", "Search")` and `"/chat": ("&#9993;", "Chat")`. Without them the rail uses its default icon.
3. `templates/kb-profile.yaml`: add

   ```
   search:
     hybrid: false           # true = BM25 + vectors (kb_embed.py)
     embedder: hashing       # hashing | sentence-transformers[:model] | {type: http, url:, model:, api_key_env:, allow_page_text: true}
     count_misses: false     # true = count searches that found nothing, by salted hash only
   ```
4. `.gitignore` guidance: `.metis/search.sqlite`, `.metis/summaries/` and `.metis/usage/` are local and should stay out of git. `kb_manifest.LOCAL` has `.metis/usage/` and `.metis/graph.sqlite` but not `.metis/search.sqlite`, and `kb_manifest.SKIP` does not skip `.metis`. Consider adding `.metis/search.sqlite` and `.metis/summaries/` to `LOCAL`.
5. Release-record trigger (retrieval eval): run `python kb_embed.py eval <KB>`. Enable hybrid only if recall@k is at least BM25's, and record the numbers.
6. `page_meta.yaml` formats `kb_search` accepts: `pages: {path: {owner, review_due}}`, a bare `{path: {...}}`, or a list of `{path: ..., owner: ...}`. W1 owns that file.
7. Docs and manual: add sections for `kb_search`, `kb_embed`, `kb_unanswered`, `kb_summaries`, `/search` (with Unanswered tab) and `/chat`. CHANGELOG entry for 2.0.0.
