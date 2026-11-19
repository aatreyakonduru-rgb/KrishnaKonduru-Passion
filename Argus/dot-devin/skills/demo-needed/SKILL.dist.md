---
name: demo-needed
description: >
  Records a demo for every Acme Claims story labelled DEMO-NEEDED whose PR is approved and not merged yet.
  Devin runs each acceptance criterion in the browser at a slow pace while the screen recording shows
  captions: what is being done, what is being checked, and the result. In Confluence each criterion
  gets its own page and video: Acme Claims Demo Recordings > <EPIC> > <KEY> > <KEY>_AC1_demo, and one Jira
  comment links to the story page. When a linked defect is fixed, a new version of each criterion's
  video is recorded next to the old one, with v1-vs-v2 on its page. Labels are never changed. Run by the "Acme Claims DEMO-NEEDED recordings" automation; say
  "/demo-needed" to run it by hand, or "/demo-needed ACME-1234" for one story.
argument-hint: "[ACME-key] [--dry-run]"
visibility: internal
triggers:
  - user
  - model
invocations:
  - /demo-needed
  - record the demo
  - record demos for DEMO-NEEDED stories
allowed-tools:
  - read
  - bash
---

# /demo-needed — record the demo nobody has to ask for

The tool is `sdlc/framework/tools/demo_needed.py`. Runs are kept under
`~/.sdlc/demos/<KEY>/v<N>/`. Nobody needs to approve the demo pages, the attachments or the Jira
comment: the tech lead (roster owner) approved those writes for DEMO-NEEDED stories on 2026-10-14. Nothing else is
written. The DEMO-NEEDED label, the status and every other field stay as they are.

## STEP 1 — Which stories

```bash
python3 sdlc/framework/tools/demo_needed.py find
```

Each story gets an action:
- `v1`: no demo yet.
- `v2`, `v3`, …: a defect linked to the story by **Blocks** or **Linked CNR** reached Resolved or
  Closed after the last demo. The new files are named after the fixed defects, for example
  `ACME-123_AC1_demo_v2_after-ACME-456-fix.mp4`, and sit next to v1 on each criterion's page.
- `skip`: released already (Ready For Release, Closed, Resolved, Abandoned are not searched at all),
  no open PR, or the demo is up to date.

With a key (`/demo-needed ACME-1234`), work on that story only. If `find` says nothing to do, stop
with one line: "No DEMO-NEEDED story needs a demo."

## STEP 2 — Is the PR approved and not merged?

Jira only shows that a PR is open; the service account cannot see reviewers. For each `v1`/`vN`
story, find its PR with the git tools (branches carry the Jira key, e.g. `devin/ACME-1234-...`) and
view it. Go on only when the PR is open (not merged, not declined) and at least one reviewer has
approved it. Otherwise skip the story and give the reason in the final report.

## STEP 3 — Run the app at the PR commit

Check out the PR's head commit in a separate worktree, then start the app in Devin Cloud with the
`sdlc-local-run` skill (backend 8000, frontend 3100 `/acme/`). Data-backed screens need the
Snowflake MCP relay from that skill. If the relay cannot run in this session, still record: an AC
whose screen needs data that did not load is `not run`, never `passed`.

## STEP 4 — Record

Open Chrome on the app, maximised, then:

```bash
T=sdlc/framework/tools/demo_needed.py
python3 $T record start --key ACME-1234 --version 1 --commit <sha> --pr <PR URL> --summary "<story summary>"
python3 $T caption card --key ACME-1234 --version 1 --title "ACME-1234 <summary>" --text "Demo v1: 5 acceptance criteria at commit <sha>" --hold 6
#   v2 and later: --defects ACME-456 on record start, and an opening card saying what changed since v1
```

For each acceptance criterion, in order, word for word from `find`:

```bash
python3 $T caption step --key ACME-1234 --version 1 --ac AC-1 --title "<criterion>" --doing "<what you will click/type>" --checking "<what must be true>"
#   now do it in the browser, slowly: one action at a time, a pause after each, no fast scrolling
python3 $T caption result --key ACME-1234 --version 1 --ac AC-1 --result passed --note "<what the screen showed>"
```

- `--result` is `passed`, `failed` or `not run`. Only what you saw on the screen decides it.
- A criterion you cannot reach (no data, no access, unclear wording) is `not run`, with the reason.
- Never type real member data into captions or notes.

End with a summary card, then stop:

```bash
python3 $T caption card --key ACME-1234 --version 1 --title "Summary" --text "4 passed, 1 failed (AC-3: total not shown at state level)" --hold 6
python3 $T record stop --key ACME-1234 --version 1
```

## STEP 5 — Publish

```bash
python3 $T publish --key ACME-1234 --version 1          # dry run: prints every write
python3 $T publish --key ACME-1234 --version 1 --live   # creates pages, attaches, comments
```

- Pages: **Acme Claims Demo Recordings** (under Acme Claims, next to the team roster) > `<EPIC>` (the epic key)
  > `<KEY>` (the story key) > one `<KEY>_AC<n>_demo` page per criterion. Missing pages are created.
  If another page in the space already has that title, ` (demos)` is added to it.
- The run is cut into one video per criterion at the moment its step started:
  `ACME-1234_AC1_demo_v1.mp4`, and after a fix `ACME-1234_AC1_demo_v2_after-ACME-456-fix.mp4`.
  Each goes on its criterion's page with a row per version and the change (`failed → passed`).
- The story page gets the full run, the `<KEY>_demo_vN.json` results file, every criterion's latest
  result with a link to its page, and the version table.
- A criterion's video over 100 MB (`--max-mb`) stops the publish; the full run is left off the story page
  when it is over the limit. An attachment name that already exists is never overwritten.
- One Jira comment on the story links to the page and gives the counts.
- On 401/403 stop and report; do not retry.

## STEP 6 — Report

One line per story: key, version recorded or the reason it was skipped, the counts, the page link.
