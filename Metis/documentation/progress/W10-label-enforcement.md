# W10 - enforce per-claim labels (second pass)

Plugin root: `metis-1.2.5-team (1)/`. Tools in `tools/`, tests in `tools/tests/`. Standard library plus PyYAML only.

## What this does

`claim_labels.py` could already label a line `{env: ...; sensitivity: ...}`. Now the labels are enforced where content is served:
a line above the viewer's clearance is left out and only counted. Output never contains the withheld text.

- Clearance: `claim_labels.clearance(kb, name_or_role, page)`. Profile `labels.clearance: {name or role: level}` wins; a level word is
  that level; reader/anonymous/guest/public and an empty name = `public`; `lead` and `kb_gate.certifiers` = `restricted`; an approver
  of the team that owns the page = `restricted` there, `confidential` elsewhere; a name under `owners.roles` = `confidential`;
  any other name = `internal`.
- A page or line with no label takes `labels.default_sensitivity` (default `internal`). So when labels exist, the empty name sees almost nothing.
- A KB with no labels at all (no `labels:` block, no page/line labels) is **inactive**: every surface behaves exactly as before.
- `sensitive.py` findings still force a line up (BLOCK to `restricted`, REVIEW to at least `confidential`); not weakened.
- Sharing (shared index, exports) is a fixed level, not a person: `labels.share_max_sensitivity` in the profile, default `public`.

## Status per item

| # | Item | Status |
|---|------|--------|
| 1 | `context_pack.py` `role` / `--role`; filter before budgeting; "Not included" gets `N lines withheld (reason: label)` | done |
| 2 | `ui/answers.py` local answerer filters by the asker; adds the note "Some lines are withheld by label ..." | done |
| 3 | `kb_search.py` (`who=`, `query --role`), `ui/screens_search.py` (`who=ctx.user`), `ui/screens_chat.py` (through `answers.ask(by=)`) | done |
| 4 | `mcp_server.py` identity from `METIS_USER`, then `METIS_ROLE`, else lowest; no tool argument changes it | done |
| 5 | `shared_index.py`, `export_rdf.py`, `okf_bundle.py` `--max-sensitivity`, default `public` / profile | done |
| 6 | `gen_graph.py`: a link may only say `origin: ai-proposed`; it can never raise itself; file-name rule unchanged | done |
| 7 | `python claim_labels.py audit <KB>`, exit 1 on a leak | done |

Also: a link whose `source` is a `kb:` tag citing a withheld line (or sitting in a hidden folder) is dropped from the pack impact
list, `find_nodes`, shared index graph, RDF and the bundle, together with any object only that link named.

## Files changed (all under `tools/`)

`claim_labels.py` (Viewer, filter_graph, audit, `lines_of`, `share_level`, `is_active`), `context_pack.py`, `kb_search.py`,
`mcp_server.py`, `shared_index.py`, `export_rdf.py`, `okf_bundle.py`, `gen_graph.py`, `ui/answers.py`, `ui/screens_search.py`,
`ui/screens_chat.py` (docstring only). New: `tests/test_label_enforcement.py`.

In `answers.py` a claim label `{...}` is now stripped from the quoted line and from the quote in the `[E: kb:...]` tag (before, the
label text went into the quote and the checker rejected the line). No change for lines without a label.

## How to run

    cd "metis-1.2.5-team (1)/tools"
    python claim_labels.py audit <KB> [--role NAME ...] [--queries 40]     # exit 1 on a leak, names page:line, never the text
    python context_pack.py <KB> ... --role "Pat Lee"
    python kb_search.py <KB> query "words" --role "Pat Lee"
    python shared_index.py register <db> <KB> [--max-sensitivity internal]
    python export_rdf.py export <KB> ... --max-sensitivity public
    python okf_bundle.py bundle <KB> --max-sensitivity public
    set METIS_USER=Ana Lead            # identity of the MCP server (or METIS_ROLE); default is the lowest
    python -m unittest tests.test_label_enforcement -v

## Tests

- `tests/test_label_enforcement.py`: 34 tests. Per surface (pack, Ask answer, `answers.ask`, kb_search, search screen, chat screen,
  MCP over `handle`, shared index, RDF Turtle/JSON-LD, OKF bundle): restricted line hidden for an uncleared role, shown for a cleared
  one, and a no-label KB unchanged. Plus: MCP tool arguments cannot raise clearance; `sensitive.py`-forced line stays withheld; a
  hand-written link cannot claim `parsed` (and `parsed.links.yaml` / `catalog.links.yaml` names still work); the audit passes on a
  clean fixture, exits 1 when a surface is patched to leak, and does not print the text.
- Full suite `python -m unittest discover -s tests -t .`: 1025 tests, OK (1 skipped, as before).

## Not covered (be honest with users)

- `ui/views.py` and the file/page viewer (`/files`), the Ask list and every other screen that reads pages or `.metis/asks/*.md`
  directly; raw `_EVIDENCE`. Anyone who can open the UI can read pages there. Answers stored before labels were added are not rewritten.
- `ui/screens_pack.py` calls `context_pack.build(...)` without a role, so with labels on it uses the lowest clearance (safe, but it
  does not pass the signed-in user). `bb_pr.py` does the same.
- The model/Devin path: `answers.attach_model_answer`, the `ask` task instructions and any session that reads KB files itself.
  `guidance()` there is called with no `who`.
- The pack header, "Open questions" section and trust signals; `metis_trust`, `metis_feedback_hints`, `metis_record_answer`,
  `metis_rate_answer`; `metis_check_answer` can confirm that a quote exists in a withheld line.
- `kb_embed.py` vector and hybrid search. In `kb_search` the BM25 ranking is computed over all text, so scores or order can still
  reflect a withheld word; only title, heading and snippet are masked.
- Other readers of page text: `kb_summaries`, `kb_dupes`, `kb_contradict`, `golden`, `page_suggest`, `facts_time`, `export_prov`,
  `gen_visuals`, telemetry/usage (file names only).
- `okf_bundle` copies non-Markdown files other than `LINK_GRAPH.yaml` as they are.
- The shared index stores filtered text; when labels are active it skips non-Markdown files other than the link graph.
- No authentication: clearance follows the name or role the caller claims (the UI session name, `METIS_USER`). The MCP identity is
  set by whoever starts the server.
- The audit looks for the normalised text of withheld lines of 12 or more characters that do not also appear in a visible line;
  shorter or repeated lines are counted as "not judged". It covers pack, kb_search, answers, okf_bundle and RDF export, as the roles
  `""` and `audit-probe` unless `--role` is given; not chat, MCP, shared index or the screens (those have their own tests).

## Hooks for the integrator

- `templates/kb-profile.yaml` (lead): document `labels.share_max_sensitivity` (default `public`) and `labels.clearance`.
- `ui/screens_pack.py`: pass `role=ctx.user` to `context_pack.build`. `bb_pr.py`: pass the author or leave the lowest.
- `ui/views.py`: filter the page viewer with `claim_labels.Viewer(kb, ctx.user).filter(rel, text)`.
- Manual / CHANGELOG / Release Record (lead): section 9 "Per-Claim Environment & Security Labels" can be marked enforced for the
  surfaces in the table above, with the "Not covered" list kept next to it.
