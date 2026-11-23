# W9: Reviewer Scoring & Trust Weights (second pass)

Status: **done with limits** (see "Limits"). Plugin root: `metis-1.2.5-team (1)/` (`$METIS`).

## What it does
Shows, for each reviewer and area, the counts behind a transparent weight; shows contributors' suggestion track records; suggests
(never assigns) reviewers for pending files; labels low-risk files "suitable for sampling review"; and may shorten the random part
of a bulk-approval sample for a reviewer with enough history, never below a floor. Every certification still needs a named lead or
team approver acting through `kb_gate`.

## Items
| # | Item | Status |
|---|---|---|
| 1 | Trust weights in `tools/reviewer_stats.py` (`policy`, `wilson`, `area_of`, `problem_signals`, `trust_table`, `trust_text`; CLI `trust`) | done |
| 2 | Contributor track record: `page_suggest.contributor_record/contributor_line`, `reviewer_stats.contributor_records` (CLI `contributors`) | done |
| 3 | Routing in `tools/review_queue.py` (`route`, `fast_lane`, `cannot_certify`, `sample_size`; CLI `route`) | done |
| 4 | UI: `/owners?view=trust` (screens_owners), contributor line in the /suggest inbox, suggested reviewer + label in /review (list and item page), reduced draw in /review sampling | done |

## Formula (also printed in the UI and CLI; text is `reviewer_stats.FORMULA`)
- area = owning team (`gate.teams`), else the file's top folder.
- decisions = certifications + certified removals by that reviewer in that area inside `lookback_days`.
- pages held = files whose latest certification in the log is this reviewer's and not removed since.
- problem pages = held pages that were later disliked (dislike dated on/after the certification, not declined by a lead), flagged stale
  (`page_owners.stale_report`), or in a confirmed contradiction (`kb_contradict` report, status `confirmed`).
- problem rate = problem pages / pages held, with a 95% Wilson interval. weight = 1 - Wilson upper bound (3 decimals).
- reversals = files this reviewer certified that a different person later removed by certified removal; reversal rate = reversals / certifications.
- fewer than `min_decisions` decisions (default 20 per reviewer-area): "not enough history", weight none.
- rejections are logged per batch without file names, so they are shown per reviewer, not per area.
- each source that is missing or fails (feedback, stale check, contradiction report) is left out and named in `notes`; the rest still counts.

## Policy: profile key `review.trust` (all optional)
`min_decisions` (20), `max_problem_rate` (0.10), `max_reversal_rate` (0.10), `lookback_days` (365, 0 = no limit), `sample_share`
(none; enables shorter samples), `floor_files` (3), `floor_share` (0.10), `fast_lane_max_lines` (10). Invalid values fall back to
defaults with a note. **Key absent = advisory only**: weights are shown, `eligible` is always False, no sample is ever shortened.

## Routing and the label
- Candidates = `kb_gate.pool_for(file)` (leads + owning team approvers). The person named in `given_by` is excluded while another
  approver exists unless `gate.allow_self_certify` (same rule `kb_gate.certify` applies; reason is shown). Removals are not excluded.
- Order: people with a weight in the file's area first, then lower open load (items routed earlier in the same pass count, plus an
  optional `assigned` map), then higher weight, then more decisions. Up to 3 are suggested. Nothing is stored or assigned.
- "suitable for sampling review" requires all of: not a removal, no source problems, no sensitive-data hits, small diff
  (`fast_lane_max_lines`), owned by a team with a named approver, every source tag verified (quote found, via `trust.py`), no open
  question blocks it, not an AI-proposed link file. If the source checks cannot run, the label is not given. The label is text only.
- Sample size (`review_queue.sample_size`, used by `screens_review.draw_size`): shorter than the standard draw (`max(5, 20%)`) only
  when the profile has `review.trust.sample_share`, the drawing reviewer has a weight (>= `min_decisions`) in the team's area and is
  within both limits. Size = `max(floor, ceil(sample_share * batch))`, never above the standard size, never above the batch;
  floor = `max(floor_files, ceil(floor_share * batch))`. Forced items (blocked by an open question, AI-proposed) are still always in the sample.

## Files
Edited (small, backwards compatible): `tools/reviewer_stats.py`, `tools/review_queue.py`, `tools/page_suggest.py`,
`tools/ui/screens_owners.py`, `tools/ui/screens_review.py`, `tools/ui/screens_suggest.py`.
New: `tools/tests/test_reviewer_trust.py` (37 tests), this notes file.

## How to run
```
python tools/reviewer_stats.py trust <KB> [--reviewer NAME]
python tools/reviewer_stats.py contributors <KB>
python tools/review_queue.py route <KB>
```
UI: Owners & Reviews > Reviewer trust (`/owners?view=trust`); `/review`; `/suggest` (inbox, for leads and team approvers).

## Tests (run from `tools/`)
`python -m unittest tests.test_reviewer_stats tests.test_review_queue tests.test_ui_owners tests.test_ui_review tests.test_page_suggest
tests.test_ui_suggest tests.test_gate tests.test_reviewer_trust` -> 155 tests, OK (118 existing + 37 new). Also ran
`tests.test_trust tests.test_page_owners tests.test_ui_admin`: 41 OK.

## What this does NOT do
- It never approves, certifies, merges or skips a review. No auto-approval, no auto-assignment, no write to any KB file, Jira,
  Confluence or Bitbucket. `route` and `trust` are read-only.
- The fast-lane label is not a permission. Certification still needs a named lead or team approver via `kb_gate.certify`.
- Without `review.trust` nothing is reduced. With it, only the random part of a bulk sample can shrink, for a reviewer with enough
  history and within limits, never below the floor; forced items and the reviewed-marks requirement are unchanged.

## Limits
- A dislike names an answer, not a page or a reviewer: a page cited in a disliked answer may be right. Weights read as "look first".
- "Stale" is the current stale state, not dated: a page flagged stale now counts against the latest certifier even if the source
  changed long after. Contradictions count only after a lead/judge verdict `confirmed`; the pattern-matcher alone does not.
- The log has no per-file reject rows, so rejections are per reviewer only; a reviewer's "rejection rate" is not in the weight.
- Load counts only items routed in the same pass plus an optional `assigned` map; Metis has no stored assignment, so the UI shows
  load from routing order, not from a real work list.
- `lookback_days` filters certifications by their log date; pages certified outside the window are not "held" for the weight.
- Names are matched by case-insensitive text; a reviewer logged under two spellings has two rows.
- Not verified against a real identity provider: the UI trusts the session name as everywhere else in Metis.

## Hooks for the integrator
1. `templates/kb-profile.yaml`, under the existing `review:` block (line ~114), add:
```yaml
review:
  default_days: 90
  trust:                    # reviewer_stats.py / review_queue.py: leave out = advisory only
    min_decisions: 20       # decisions per reviewer and area before a weight is shown
    max_problem_rate: 0.10  # later-problem rate above which a reviewer is not "within limits"
    max_reversal_rate: 0.10
    lookback_days: 365
    # sample_share: 0.10    # optional: shorter bulk-approval sample for a reviewer with history; never below the floor
    floor_files: 3
    floor_share: 0.10
    fast_lane_max_lines: 10
```
2. Manual section 9 / CHANGELOG / Release Record: mark "Reviewer Scoring & Trust Weights" as done with the limits above.
