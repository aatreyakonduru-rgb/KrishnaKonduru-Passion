# W7: content model and ingestion

Plugin root (`$METIS`): `metis-1.2.5-team (1)/`. Tools in `$METIS/tools/`, UI in `$METIS/tools/ui/`, tests in `$METIS/tools/tests/`.
Python standard library plus PyYAML only. No shared file was edited (see "Shared files" below).

## Status

| # | Item | Status | Tests |
|---|---|---|---|
| 1 | `facts_time.py` time-aware facts | done | `test_facts_time.py`, 17 |
| 2 | `claim_labels.py` per-claim labels | done | `test_claim_labels.py`, 18 |
| 3 | `adr_ingest.py` + `templates/doc-categories.decisions.yaml` | done, with limits | `test_adr_ingest.py`, 16 |
| 4 | `recipes_ingest.py` | done, with limits | `test_recipes_ingest.py`, 13 |
| 5 | `page_suggest.py` + `ui/screens_suggest.py` | done | `test_page_suggest.py`, 31; `test_ui_suggest.py`, 20 |

Run (from `$METIS/tools`, all pass, 115 tests):

    python -m unittest tests.test_facts_time tests.test_claim_labels tests.test_adr_ingest tests.test_recipes_ingest tests.test_page_suggest tests.test_ui_suggest

Regression check on neighbours, also passing: `tests.test_ui_golden`, `tests.test_gate`, `tests.test_verify_and_questions` (146 tests together with mine).

## Files created

- `tools/facts_time.py`, `tools/claim_labels.py`, `tools/adr_ingest.py`, `tools/recipes_ingest.py`, `tools/page_suggest.py`
- `tools/ui/screens_suggest.py`
- `templates/doc-categories.decisions.yaml`
- `tools/tests/test_facts_time.py`, `test_claim_labels.py`, `test_adr_ingest.py`, `test_recipes_ingest.py`, `test_page_suggest.py`, `test_ui_suggest.py`

## Shared files

None edited. `verify_kb.py` was NOT changed: its tag regex `\[(E|\?):\s*([^\]]+)\]` only looks inside square brackets, so a trailing
`{...}` group does not break it. `test_facts_time.py` and `test_claim_labels.py` prove that `verify_kb` ignores the annotations and still
flags a bad tag next to one.

## 1. facts_time.py

Grammar, placed after the `[E: ...]` tag on a line (the markdown page format is unchanged):

    - Claims are paid within 30 days [E: file:rules.txt "30 days"] {valid-from: 2026-03-01; valid-to: 2026-09-30; superseded-by: context/rules-v2.md:14}

Keys are optional: `valid-from`, `valid-to` (inclusive), `superseded-by` (a KB page, or a fact id `<kb path>:<line>`). ISO dates only.

    python facts_time.py build   <kb>                        # .metis/facts.sqlite
    python facts_time.py as-of   <kb> 2026-05-01 [--all]     # lines valid that day
    python facts_time.py history <kb> <object>               # lines mentioning the object, oldest first
    python facts_time.py expired <kb> [--today DATE]         # valid-to passed, nothing supersedes it
    python facts_time.py page-at <kb> <rev> <path>           # git show of the whole page

`as_of_edges(kb, date, columns_file=None)` returns the graph edges in force on a date. It reads `CROSS-LAYER/LINK_GRAPH.yaml` and the
optional columns file `CROSS-LAYER/edge_validity.yaml` (`edges: [{from, rel, to, valid_from, valid_to}]`). `graph_store.py` is untouched.

## 2. claim_labels.py

Grammar, after the tag (a group of its own; it may follow a facts_time group): `{env: prod; sensitivity: restricted}`.
Levels: `public < internal < confidential < restricted`. Page defaults come from front matter `env:` and `sensitivity:`.

    python claim_labels.py scan   <kb> [--page REL]
    python claim_labels.py report <kb> [--json]
    python claim_labels.py filter <kb> --out DIR (--max LEVEL | --role WHO) [--page REL]
    python claim_labels.py check  <kb>

- A heading label covers the lines under it. A line label can raise a page's level, never lower it (a lower one is a conflict that
  `check` reports and the code ignores).
- `sensitive.py` BLOCK findings (secrets, keys, tokens, card, SSN) force the line to `restricted` in `report`/`scan`/`filter`; REVIEW findings
  (email, phone, date of birth, member ids) force at least `confidential`.
- `check` reports lines labelled restricted on a page that is not under `labels.restricted_folders`, and file/line conflicts.
- `visible_lines(kb, path, role, max_level=None)` returns the lines a role may see. Roles come from the profile: leads
  (`kb_gate.certifiers`) see all; a team approver sees restricted on that team's pages (`gate.teams`), confidential elsewhere; other named
  people confidential; unknown names internal; no name public. `labels.clearance` overrides.

## 3. adr_ingest.py

    python adr_ingest.py scan  <kb> --repo NAME [--path SUB]
    python adr_ingest.py stage <kb> --repo NAME [--path SUB] [--dry-run]
    python adr_ingest.py docs  <kb> <scratch> [--kept-at WHERE] [--dry-run]     # from doc_intake.py output

Detects Nygard (`docs/adr/0001-*.md`), MADR 2/3, `decisions/`, Confluence text, and post-mortems (Timeline / Root cause / Action items).
Writes `context/decisions/<slug>.md` and `context/incidents/<slug>.md`, every line `[E: repo/path:line "quote"]` (from documents:
`[E: doc:<id>#<place> "quote"]`). Lines with a secret are left out and listed. A locked KB gets a `_PENDING/<batch>/` with DIGEST via
`kb_gate`; an unlocked KB is written directly. A page not made by the tool is never replaced (`<name>.NEW.md` is written beside it).

Links file `CROSS-LAYER/decisions.links.yaml`: one `references` link per record and graph object. `origin: named-in-text` when the exact
name (same spelling and case) is in the text, else `origin: ai-proposed` with `match` saying why. The `docs` path stages the links as a second batch.

## 4. recipes_ingest.py

    python recipes_ingest.py scan  <kb> --repo NAME [--path SUB]
    python recipes_ingest.py stage <kb> --repo NAME [--path SUB] [--dry-run]

Reads runbooks (`runbooks/`, `docs/runbooks/`, `playbooks/`, `ops/`, `*runbook*`), CONTRIBUTING and README command sections, Makefile
targets, `package.json` scripts, and pipelines (GitLab, GitHub Actions, CircleCI, Azure, Bitbucket, Jenkinsfile). Writes
`context/procedures/<repo>-<path-slug>.md` as numbered steps, each with `[E: repo/path:line "quote"]` and the command verbatim in backticks.
A step containing rm, drop, delete, truncate, format or prod is marked `**needs-confirm**`. Steps are documentation; Metis never runs them.
Staging, locked-KB behaviour and the never-replace rule are shared with `adr_ingest.py`.

## 5. page_suggest.py and /suggest

    python page_suggest.py suggest <kb> --page P --by NAME --wrong T --proposed T (--evidence '[E: ...]' | --look T) [--line N]
    python page_suggest.py comment <kb> --page P --by NAME --text T [--reply-to C-0001]
    python page_suggest.py list|thread|inbox <kb> ...
    python page_suggest.py approve <kb> S-0001 --by LEAD (--question | --stage) [--note T]
    python page_suggest.py decline <kb> S-0001 --by LEAD --reason T
    python page_suggest.py answer  <kb> C-0001 --by LEAD --text T

- Storage: `<KB>/_FEEDBACK/suggestions.yaml` (`suggestions: S-0001...`, `comments: C-0001...`), same folder and yaml style as `feedback.py`.
  Reuses `feedback.DIR`, `feedback.question_type`, `questions.cmd_raise`, `kb_gate.pool_for`, `kb_gate.stage_text/digest`.
- Required: a session name, an existing page, what is wrong, proposed text, and exactly one of an `[E: ...]` tag (checked with
  `verify_kb.Checker.resolve`) or a "where to look" hint. Text with a BLOCK-level secret is refused. Length limit 2000.
- Who decides: the leads, plus the approver of the team that owns the page (`kb_gate.pool_for`). Others are refused.
- `approve --question`: a question in VALIDATE_KB with `[E:]` context. `approve --stage`: needs a closed gate, a line number, an `[E:]`
  source, and the line unchanged since it was suggested; the line is replaced in a copy under `_PENDING/<batch>/` with a DIGEST, any
  trailing `{...}` groups kept. It is certified like any batch. No path in this tool writes a live page (a test checks this).
- Comments are append-only and threaded (`reply_to`). A lead's `answer` is a new entry and marks the parent comment `answered`.
- Screen `/suggest`: page picker with filter, `?page=<path>` preselect, suggestion form, comment form and thread, and a lead inbox
  (shown only to a lead or team approver). Actions: `/suggest/submit`, `/suggest/comment`, `/suggest/approve`, `/suggest/decline`,
  `/suggest/answer`. No JavaScript; all user text escaped.

## Limits

- `gen_graph.origin_of()` labels every edge from `decisions.links.yaml` as `ai-proposed`, whatever the per-link `origin` says.
- Facts as-of ignores a section-level annotation: an annotation applies to its own line only.
- Recipes ingest does not resolve YAML anchors, `include:` or `extends:`; a pipeline step that comes from a template is not seen.
- ADR/post-mortem detection is heading based and heuristic; an unusual layout outside an adr/decisions/incidents folder may be missed.
- Confluence/SharePoint inputs are tested only through plain text files written like `doc_intake.py` output. Needs your environment to
  verify against a real Confluence or SharePoint export.
- `facts_time.py page-at` needs the KB to be inside a git repository (`git show`); the test creates a temp repo. Needs your environment to
  verify on a KB under your real git hosting.
- The stage action replaces a single non-heading, non-table line; for anything bigger approve as a question.
- `.metis/facts.sqlite` is derived: rebuild with `facts_time.py build`.

## Hooks for the integrator

1. **context_pack / ask: hide restricted lines.** Where a page's lines are read into a pack or an answer prompt, call
   `claim_labels.visible_lines(kb, path, role)` instead of reading the file. Text to add in `context_pack.py` and `ask`:

       import claim_labels
       lines = claim_labels.visible_lines(kb, rel, role)   # list of (line number, text); role = the signed-in name or role

   For exports use `claim_labels.py filter <kb> --out DIR --max internal`.

2. **views.py: "Suggest an edit" link.** In the page view box (file `tools/ui/views.py`, where the page header or the box with page actions
   is built) add:

       '<a href="/suggest?page=%s">Suggest an edit</a>' % urllib.parse.quote(rel)

   The target `/suggest?page=<kb path>` preselects the page. `screens_suggest.py` is picked up by `server.py` automatically (SCREENS, ACTIONS, NAV).

3. **Merge the decisions categories.** Append the three entries (`decisions`, `incidents`, `procedures`) from
   `templates/doc-categories.decisions.yaml` into `templates/doc-categories.yaml` (and a project's `.metis/doc-categories.yaml`). Until then
   `adr_ingest.py` and `recipes_ingest.py` fall back to the new file.

4. **gen_graph.py: per-link origin.** In `tools/gen_graph.py`, `origin_of()` derives the origin from the file name only. To honour the
   per-link `origin` key written in `decisions.links.yaml`, use `link.get("origin")` when it is `named-in-text` or `ai-proposed`
   (map `named-in-text` to the same trust as `human-confirmed` only if your policy allows it; otherwise keep `ai-proposed`).

5. **kb-profile.yaml template** (`templates/kb-profile.yaml`), add this optional block:

       labels:
         default_sensitivity: internal
         restricted_folders: []        # globs relative to the KB, e.g. ["context/hr/*"]
         clearance: {}                 # {<name or role>: public|internal|confidential|restricted}

6. **.gitignore:** add `.metis/facts.sqlite` (derived index).

7. **Manual / CHANGELOG / Release Record:** nothing was edited. Add the five tools, the `{valid-from...}` and `{env...}` grammars, and
   the `/suggest` screen where your docs list them.
