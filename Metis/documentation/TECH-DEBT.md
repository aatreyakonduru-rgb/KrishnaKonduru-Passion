# Metis 2.0 technical debt register

Each item has an owner role, a date it was recorded and a plan. Dates are when
the item was written down, not when it is due.

## TD-1 Team-specific code lives inside the generic plugin

- Recorded: 2026-11-23. Owner: plugin maintainer.
- `metis-1.2.5-team (1)/cvbc/` and `metis-1.2.5-team (1)/team/` hold about 74
  files of team-specific tools, queries and settings (CVBC Scorecard and
  team KB builders). Nothing under `tools/` imports them
  (`tools/tests/test_boundaries.py` fails if that changes).
- They have no tests in `tools/tests/`. The refactored pipeline was
  syntax-checked, not run end to end (see CHANGELOG, "Profile-driven tools").
- Plan: move both folders to a separate plugin (`metis-team-cvbc`) that
  depends on `metis-kb`. Until then the boundary test keeps the two sides
  from growing together. The move is not done here because it needs the
  owning team to confirm which settings files they still use.

## TD-2 Folder and plugin name say 1.2.5-team, the product is 2.0.0

- Recorded: 2026-11-23. Owner: plugin maintainer.
- The folder is `metis-1.2.5-team (1)`. Docs and tests reference that path, so
  it was not renamed. `.devin-plugin/plugin.json` and `pyproject.toml` now
  say 2.0.0.
- Plan: rename the folder to `metis/` in one commit that also updates the
  documentation paths, and re-run the suite.

## TD-3 No authentication in the UI beyond a shared password or OIDC cookie

- Recorded: 2026-11-23. Owner: security reviewer.
- Claim labels (`env`, `sensitivity`) are a filter, not access control.
  Without OIDC the caller name is an unproven cookie. The manual lists the
  surfaces the filter does not cover.
- Plan: require OIDC for any shared deployment; add per-user API keys if the
  JSON API is exposed beyond a trusted network. Needs an identity provider.

## TD-4 Unverified against real systems

- Recorded: 2026-11-23. Owner: team lead.
- Not tried against real systems: Bitbucket PR comments, Slack/Teams/SMTP,
  OIDC providers, OTLP collectors, sentence-transformers, an MCP client,
  an OpenAI-compatible judge endpoint.
- Plan: one acceptance run per system in the customer environment, recorded
  in the Release Record.

## TD-5 Confidence bands are not calibrated

- Recorded: 2026-11-23. Owner: lead reviewer.
- The deductions in `ui/answers.py` are fixed rules. `calibration.py` and
  `recalibrate.py` report whether they hold, but need enough rated answers.
- Plan: review `CALIBRATION_PROPOSAL.yaml` after the first 100 rated answers.

## TD-6 LLM-judge agreement rate unknown

- Recorded: 2026-11-23. Owner: lead reviewer.
- `llm_judge.py` has never been compared with human verdicts.
- Plan: have a lead label a sample, then report agreement beside the judge's
  results.

## TD-7 Audience weights are starting values

- Recorded: 2026-11-23. Owner: lead reviewer.
- `audience.py` weights the four layers per audience (business, developer,
  tech lead, architect, support). They were chosen by reasoning, not measured.
  A KB with pages at one layer only gives every audience the same lines (the
  answer says so). Page layers come from front matter, folder or cited sources;
  a page with none of those is read as `design`.
- Plan: run `audience.py layers <kb>`, fix the pages it guesses wrong with a
  `layer:` front-matter line, add golden questions per audience to
  `pack_eval.py`, then tune the weights against recall and a reader's rating.

## TD-8 Ask does not use the hybrid search

- Recorded: 2026-11-23. Owner: plugin maintainer.
- `ui/answers.py` scores lines with its own stem matcher; only the context
  pack uses `kb_search` (BM25 plus optional vectors). So a question whose words
  differ from the page's reach Ask less well than the pack.
- Plan: route Ask's candidate lines through `kb_search`, keep the quote check
  and clearance filter, and compare with `pack_eval.py` before switching.

## TD-9 Area summaries are not in the answer path

- Recorded: 2026-11-23. Owner: plugin maintainer.
- `kb_summaries.py` builds a summary tree (needs a model session for the prose)
  but neither Ask nor the pack starts from it, so the layered structure does not
  yet save tokens or choose where to drill.
- Plan: start a pack from the summary page for the area, then add the full
  pages the question needs; measure tokens and recall with `pack_eval.py`.

## TD-10 A statement can still be wrong while its quote is present

- Recorded: 2026-11-23. Owner: lead reviewer.
- `verify_kb.py` now needs a quote on repo line tags in strict mode and, with
  `verify.support_min`, a word overlap between statement and quote. Neither
  proves the sentence is right: a quote can be read wrongly, and `Inferred:`
  lines are not screened.
- Plan: sample 50 certified lines, have a lead mark each right or wrong, then
  compare with the lexical screen and with `llm_judge.py` before relying on
  either (see TD-6).

