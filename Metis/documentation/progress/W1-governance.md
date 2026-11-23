# W1 Governance Workstream Progress

## Status per Item
1. `tools/page_owners.py`: done (CLI, importable functions, test suite)
2. `tools/codeowners.py`: done (GitHub/Bitbucket CODEOWNERS parsing, object/question/queue routing, test suite)
3. `tools/reviewer_stats.py`: done (CERTIFICATIONS.log parsing, feedback/telemetry dislikes join, advisory text, test suite)
4. `tools/recalibrate.py`: done (confidence loop using Wilson intervals, PROPOSAL file generation, min volume enforcement, test suite)
5. Approve-by-area in `tools/review_queue.py`: done (backwards-compatible `certify --area` / `certify_area`, test suite)
6. `ui/screens_owners.py`: done (`/owners` screen with tabs, forms, stats table, recalibration proposal viewer, test suite)

## Files Created / Modified
### Created Files
- `tools/page_owners.py`: Per-page owner and review frequency stored in `<KB>/.metis/page_meta.yaml`. Implements `set`, `show`, `due`, `stale-report`, `mark-reviewed`, and `files_without_owner(kb)`.
- `tools/codeowners.py`: CODEOWNERS parser (GitHub/Bitbucket styles, last-match-wins glob matching), routing KB pages, open questions, and review queue items.
- `tools/reviewer_stats.py`: Reviewer track records from `CERTIFICATIONS.log` joined with feedback telemetry; advisory routing without hidden auto-approval scores.
- `tools/recalibrate.py`: Confidence recalibration proposals stored in `<KB>/.metis/CALIBRATION_PROPOSAL.yaml` based on rating intervals; never auto-edits `answers.py`.
- `tools/ui/screens_owners.py`: UI screen at `/owners` registering `SCREENS`, `ACTIONS`, `NAV` for governance, reviewer stats, and recalibration.
- `tools/tests/test_page_owners.py`: Unit tests for `page_owners.py` (8 tests).
- `tools/tests/test_codeowners.py`: Unit tests for `codeowners.py` (8 tests).
- `tools/tests/test_reviewer_stats.py`: Unit tests for `reviewer_stats.py` (4 tests).
- `tools/tests/test_recalibrate.py`: Unit tests for `recalibrate.py` (4 tests).
- `tools/tests/test_ui_owners.py`: Unit tests for UI `/owners` screen and actions (10 tests).
- `documentation/progress/W1-governance.md`: Workstream tracking notes.

### Modified Files
- `tools/review_queue.py`: Added `certify_area(kb, area, by, accept_review=None)`, `in_area()`, and CLI `--area` argument.
- `tools/tests/test_review_queue.py`: Added test cases for `certify_area` (13 tests total).

## How to Run
```bash
# Page owners
python tools/page_owners.py show <kb>
python tools/page_owners.py due <kb>
python tools/page_owners.py stale-report <kb>
python tools/page_owners.py set <kb> <page> --owner "Ana Lead" --days 90
python tools/page_owners.py mark-reviewed <kb> <page> --by "Ana Lead"

# CODEOWNERS routing
python tools/codeowners.py parse <repo_path>
python tools/codeowners.py owners <repo_path> <code_path>
python tools/codeowners.py page <kb> <page_rel>
python tools/codeowners.py suggest-question <kb> <question_id>

# Reviewer statistics & routing
python tools/reviewer_stats.py stats <kb>
python tools/reviewer_stats.py route <kb> "Claims Team"

# Recalibration loop
python tools/recalibrate.py run <kb> --min-volume 30
python tools/recalibrate.py show-proposal <kb>

# Review queue area certification
python tools/review_queue.py certify <kb> --area "claims/*" --by "Cleo Claims"

# Run all governance tests
python -m unittest tests.test_page_owners tests.test_codeowners tests.test_reviewer_stats tests.test_recalibrate tests.test_review_queue tests.test_ui_owners -v
```

## Test Results
All 47 tests passed (0 failures, 0 errors):
- `tests.test_page_owners`: 8/8 passed
- `tests.test_codeowners`: 8/8 passed
- `tests.test_reviewer_stats`: 4/4 passed
- `tests.test_recalibrate`: 4/4 passed
- `tests.test_review_queue`: 13/13 passed
- `tests.test_ui_owners`: 10/10 passed

## Limits
- CODEOWNERS parsing supports standard GitHub and Bitbucket glob matching conventions. External git hosting provider API verification requires the respective external environment.
- Confidence recalibration generates non-destructive advisory proposals in `.metis/CALIBRATION_PROPOSAL.yaml` and does not automatically alter `ui/answers.py` source code.

## Hooks for the Integrator
- **Profile Keys in `kb-profile.yaml`**:
  - `review.default_days`: Default review cycle duration in days for pages without an explicit frequency (default fallback: 90 days).
- **Auto-discovered UI screen**:
  - `ui/screens_owners.py` exports `SCREENS`, `ACTIONS`, `NAV` (`/owners`, "Owners & Reviews") for automatic loading in `ui/server.py`.
- **Coverage Integration**:
  - `tools/page_owners.files_without_owner(kb)` is importable and returns all KB pages lacking an explicit or default owner for integration into `tools/kb_coverage.py`.
