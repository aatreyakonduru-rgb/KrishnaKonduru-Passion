# W12 - three known limits (telemetry lines, chat persistence, section dates)

Plugin root `metis-1.2.5-team (1)/`, tools in `tools/`. Standard library only (PyYAML already used elsewhere).

## Status

| # | Item | Status |
|---|------|--------|
| 1 | `telemetry_lines.py`: stable per-line identity, fallback for old records, re-anchor step | done with limits |
| 2 | Chat threads persisted (`ui/chat_store.py`, `ui/screens_chat.py`, `kb_manifest.LOCAL`) | done with limits |
| 3 | `facts_time.py`: section-level annotations | done |
| 4 | Claim-label filter on `/files` page view (`ui/views.py`, W10 "Not covered") | done (small edit; other surfaces not done) |

## 1. Telemetry lines

- A line is identified by a fingerprint: first 16 hex of SHA-256(per-KB salt, page path, normalised line text). Normalised = no
  `[E: ...]` tag, no `{env/sensitivity/valid-*/superseded-by}` group, no list bullet, lower case, one space. Salt:
  `<kb>/.metis/usage/.line-salt` (git-ignored folder, skipped by kb_manifest). No question, answer or KB text is stored; the hash is salted.
- `telemetry.record(..., anchors=None)`: new optional field. When `lines` is given and `anchors` is not, `telemetry_lines.anchors_for`
  fills `anchors` (`path:line#fp`) - so `ui/answers.py` (ask and `attach_model_answer`) and `mcp_server` unchanged callers get it free.
  Events keep `lines` as before.
- Rated answers: `answers.rate` calls `telemetry_lines.anchor_rated(kb, F-id)` (guarded, never blocks a rating); fingerprints go to
  `<kb>/.metis/usage/line-anchors.json` (atomic write). Ratings made before this have no anchors and are read by line number, as before.
- `report` follows a line by fingerprint: `line` = where it is now, new `moved_from`, `status` "line no longer exists" when the text was
  edited or deleted; `most_used` counts are carried to the new position. New `reanchor(kb)` / `python telemetry_lines.py reanchor <kb>`
  reports `moved` and `gone` (counts carried, nothing rewritten). Old number-only events: read as "the line that has that number now";
  a number past the end of the page is `gone`.
- Consumers: `ui/screens_quality.py` lines tab (text of the note only); `ui/answers.py` `_cited_lines` unchanged; kb_trend does not use it.
- Limits: a reworded line is not matched (reported gone, never guessed); identical lines on one page share one identity; deleting
  `.line-salt` orphans old fingerprints; `used_counts` (old number view) still exists unchanged. Old number-only records of a line that
  moved BEFORE this change cannot be repaired.

## 2. Chat persistence

- New `ui/chat_store.py`: `<kb>/.metis/chat/<user-slug>-<hash>.jsonl`, one JSON line per message
  `{"v":1,"user","thread","id","at"}` - ask ids only, nothing that is not already shown in the chat. Per-user file; records whose user
  differs are ignored on read. Caps: 200 messages per thread, 50 threads per user (older dropped on write). Write = temp file in the
  same folder + `os.replace` (retry on Windows `PermissionError`). `.gitignore` of `*` in the folder.
- `kb_manifest.LOCAL` gets `.metis/chat/` (small edit). `kb_gate.DERIVED` needs nothing: `.metis` is already in `EXEMPT_DIRS` (a test
  locks a KB and checks `kb_gate.status` has no problems after a chat turn).
- `screens_chat.py`: `THREADS` is now a cache loaded from the file on first use (tests that `THREADS.clear()` simulate a restart);
  `add_turn`/`act_chat_clear` write through; a write failure is swallowed (chat continues in memory). 20 turns are still shown.
  A restored id whose ask belongs to someone else is not shown.
- Claim labels: `visible_answer()` re-filters every shown answer through `claim_labels.Viewer`/`source_hidden` (lines citing a now-withheld
  `kb:` line are removed, `answers.WITHHELD_NOTE` added; fail-closed on error). New answers were already filtered by `answers.ask(by=)`.
- Limits: answer text itself is in `.metis/asks/` (as before, local, git-ignored) - not new storage. Withheld-line filtering of an old
  answer works only for lines that cite `kb:` sources (file-only citations cannot be tied to a line). Not safe for two server processes
  writing the same file at the same time (last write wins; each write is still atomic). Names, case and spacing map to one user; no
  authentication (as W10).

## 3. facts_time section annotations

- `## Heading {valid-from: ...; valid-until: ...}` applies to fact lines below it until the next heading of the same or higher level;
  sub-headings inherit and may override per key; a line's own keys override the section's key by key. Aliases: `as-of`, `as of`,
  `as_of` = valid-from; `valid-until` = valid-to. Headings in code blocks / front matter are ignored. A merged valid-to before valid-from
  (section + line mix) is a problem on the line.
- Index: `facts.sqlite` has a new `section` column (`path:line` of the heading); an old index without it is rebuilt automatically.
  `as_of()` rows get `from_section`; CLI `as-of` prints `[section path:line]`. Module docstring updated (format, keys, section rules).
- Limits: only fact lines (those with an `[E:]` tag or a dating group) are indexed, as before; a heading counts as a dated line only
  if it has dates. `superseded-by` on a heading is inherited too. Setext (`===`) headings are not recognised, ATX `#` only.

## 4. `/files` (W10 not-covered item)

`ui/views.py` `file_view`: text is passed through `claim_labels.Viewer(kb, ctx.user).filter(rel, text)`; withheld lines are removed and
counted ("N lines withheld by label"); no effect when the KB has no labels; fail-closed on error. This is a ~10 line edit in a file the
brief marks as shared - done because the task allowed it; the integrator should review it. NOT done: Ask list / `.metis/asks/*.md`
viewers, other `views.py` screens, raw `_EVIDENCE`, the page "Trust signals" box, `screens_pack.py` role, and everything else in W10's list.

## Files

Changed: `telemetry.py`, `telemetry_lines.py`, `kb_manifest.py`, `facts_time.py`, `ui/answers.py` (rate: anchor call),
`ui/screens_chat.py`, `ui/screens_quality.py` (text), `ui/views.py` (`file_view`).
New: `ui/chat_store.py`, `tests/test_chat_persist.py`.
Tests extended: `tests/test_telemetry_lines.py` (+9, class `Anchors`), `tests/test_facts_time.py` (+10).

## How to run

    cd "metis-1.2.5-team (1)/tools"
    python telemetry_lines.py reanchor <KB>
    python facts_time.py as-of <KB> 2026-05-15 [--all]
    python -W ignore -m unittest tests.test_chat_persist tests.test_telemetry_lines tests.test_facts_time tests.test_claim_labels

## Test results

test_chat_persist 19, test_telemetry_lines 22, test_facts_time 27, test_claim_labels 18, test_ui_chat 18 (unchanged), test_ui_quality 13,
test_label_enforcement OK. Full suite `unittest discover -s tests -t .`: 1083 tests, OK (6 skipped).

## Hooks for the integrator

- Manual / CHANGELOG: the lines "chat threads ... lost on server restart" and "line numbers drift when pages are edited" are no longer
  true (see limits above); section annotations are new in the facts_time format; `.metis/chat/` and `.metis/usage/line-anchors.json`,
  `.line-salt` are local files.
- `templates/kb-profile.yaml`: nothing needed. `.gitignore` is written by the code in `.metis/chat/` and `.metis/usage/`.
- `ui/server.py`: nothing. Review the `ui/views.py` `file_view` edit (shared file) and apply the same filter to the other page-reading
  views listed under item 4.
