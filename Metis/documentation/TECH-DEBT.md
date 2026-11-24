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

## TD-8 Ask uses the search to rank pages, not to find lines (partly done)

- Recorded: 2026-11-23. Owner: plugin maintainer. Updated: 2026-11-24.
- Done: Ask now asks `kb_search` (BM25, plus vectors when the profile sets
  `search.hybrid`) for the best pages. A line on one of the 3 best pages that
  shares one word with the question now qualifies, and the search breaks ties
  between equal lines. The quote check, the clearance filter and the audience
  order are unchanged. A broken search falls back to the word matcher and says
  so. `ask.search: false` in the profile turns it off.
- Not done: a line that shares no word with the question still cannot qualify,
  even on the best page (glossary synonyms reach it only through the existing
  boost). The change is not measured on real questions: `pack_eval.py` scores
  packs, and Ask has no golden set of its own.
- Plan: write 20 golden Ask questions for a real KB, compare answers with
  `ask.search` on and off, and widen the rule only if recall rises without new
  wrong lines.

## TD-9 Summaries reach the pack and Ask only when summary pages exist (partly done)

- Recorded: 2026-11-23. Owner: plugin maintainer. Updated: 2026-11-24.
- Done: when the search ranks an `area-summary` page, the pack adds the pages it
  covers (`summarises` front matter, see `kb_summaries.drill_pages`) and Ask
  gives those pages the summary's rank.
- Not done: the summary prose is written by a model session and certified by a
  lead (`kb_summaries.py build`, `verify`, `stage`). A KB with none gets no
  change, and the demo KB has none. Nothing yet starts a pack from the summary
  alone and drills only when needed, so there is no token saving to quote. The
  gain is unmeasured.
- Plan: write and certify summaries for a real KB, then compare tokens and
  recall of packs with and without them using `pack_eval.py`.

## TD-10 A statement can still be wrong while its quote is present (tooling done, labels needed)

- Recorded: 2026-11-23. Owner: lead reviewer. Updated: 2026-11-24.
- `verify_kb.py` needs a quote on repo line tags in strict mode, a word overlap
  with `verify.support_min`, and `Inferred:` on conclusions and on lines citing
  two or more sources (always for answers, `verify.inferred_rule` for pages).
  None of that proves a sentence is right: a quote can be read wrongly, and a
  line on a templated page can share the words of the wrong citation.
- Done: `judge_agreement.py` draws a reproducible sample of cited lines, adds
  control lines (a real citation under an unrelated claim), writes the judge
  requests, and scores a person's labels against the lexical screen and the
  judge, with an interval. It gives no figure under 30 labelled lines.
- Not done: no person has labelled a sample, so we do not know how often the
  screen or the judge agree with a reader. That needs a lead's time and a real
  KB; the demo KB has 25 cited lines, too few.
- Plan: `judge_agreement.py draw <kb> --n 50 --controls 5`; a lead fills in
  `human:` for each item; a model session answers the judge requests; then
  `judge_agreement.py score <kb>`. Set `verify.support_min` from the sweep it
  prints.
