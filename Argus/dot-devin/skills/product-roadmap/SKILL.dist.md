---
name: product-roadmap
description: >
  Rebuilds the Acme Claims roadmap: a Year plan for funding conversations (work delivered, due this
  year, pushed to next year — foundational and speciality, with or without Jira) read from a
  hand-kept YAML file, beside the live Jira sprint grid with the stories each epic actually
  targets per sprint. One tabbed page in the Acme Claims look plus a Markdown copy for the knowledge
  base. Say "/product-roadmap" to regenerate it, or "/roadmap".
argument-hint: "[a horizon, e.g. ahead 8 back 4 | epic ACME-224 | cache | no-commit | plan <path>]"
visibility: internal
triggers:
  - user
  - model
invocations:
  - /product-roadmap
  - /roadmap
  - regenerate the UI roadmap
  - update the year plan / funding roadmap
  - what is each epic doing in the next sprints
  - show the sprint roadmap grid
allowed-tools:
  - read
  - write
  - edit
  - grep
  - glob
  - exec
---

# /product-roadmap — Acme Claims roadmap: year plan + Jira sprint grid

Two questions get asked of a roadmap and they need different sources. "What is the team
building this sprint and next?" is answered from Jira. "What did we say we would do this
year, what shipped, what is still due and what got pushed to next year?" is the funding
conversation, and that work may or may not be in Jira yet — so it lives in a small file the
team edits by hand. The page shows both, as tabs, in the same artifact-kit look as `/dashboard`
and the LOE reports (`.devin/rules/html-style.md`).

Outputs, both under `docs/knowledge-base/JIRA-DERIVED/`:

| File | For |
|---|---|
| `UI-DELIVERY-ROADMAP.html` | the tabbed page — one self-contained file, opens in a browser, hand it to a BSA/PO/leadership |
| `05_UI_DELIVERY_ROADMAP.md` | the same content as tables and lists, so the KB and future sessions can read it |

Tabs, in order: **Year plan** (totals by status, bars per capability and programme, the
committed-but-unsized list), **Foundational** (every story row with dev/SIT/UAT points),
**Speciality** (programme totals and breakdown), **Programme windows** (dates copied from the
planning sheet, if the plan file has any), **Sprint grid**, **Not in a sprint**, **Sources &
open questions**.

## The year plan file

`sdlc/framework/context/roadmap/year-plan.yaml`. Edit it, re-run, done. Shape:

- `plan_year`, `next_year`, `velocity_points_per_sprint`, `source` (where the numbers came from).
- `foundational:` capabilities, each with `stories:` — `name`, `status`, `points: {story, sit, uat}`,
  optional `jira: [ACME-…]`. A row with no `points` is `unsized: true` and is listed, never summed.
- `speciality:` `capabilities` (column names) and `programs` — `name`, `status`, `total_points`
  (or `null` when the sheet has none), optional `breakdown` matching the columns.
- `unsized:` committed work with no number yet (`name`, `status`, `note`, optional `target`
  and `target_confirmed: false` when the year is assumed rather than stated).
- `programme_windows:` free-form tables copied from planning sheets (`program`, `team`,
  `columns`, `rows`) — rendered as given, no interpretation.
- `open_questions:` `question` + `owner`. Anything the file cannot settle goes here and is
  printed on the Sources tab. Do not resolve a question by picking an answer in the file.

`status` is `delivered` / `this_year` / `next_year` / `unknown`, which the page labels
"Delivered", "Due in <plan_year>", "Pushed to <next_year>", "Year not set" and colours
green / orange / gold / grey; the legend also says which spreadsheet colour each maps to
(white / orange / yellow), because that is the vocabulary the team uses.

When a row carries `jira:` keys, the generator looks those epics up in what it fetched and
shows status and how many stories sit in sprints. Epics on the grid that no plan row names are
listed on the Sources tab so the two views can be reconciled by adding keys, not by guessing.

When the user hands over a new spreadsheet or numbers in chat, translate them into this file —
keep spellings as written, keep totals the sheet gives, sum nothing the sheet does not sum —
and put every ambiguity (a colour you cannot read, a total with no breakdown, a month with no
year) into `open_questions` rather than deciding it. Then regenerate and open a PR for the
file change if it is more than a routine number refresh.

## The branch is fixed

The knowledge base lives on **`feature/devin-sdlc`**, always, and this skill commits
straight to it. Nobody is asked which branch to use. Step zero, every time:

```
git fetch -q origin && git checkout feature/devin-sdlc && git pull -q --ff-only
```

If the tree is dirty with unrelated changes or the pull is not a fast-forward, stop and say
so rather than committing on top of someone else's work.

## Run it

```
python3 sdlc/framework/tools/gen_roadmap.py                 # live Jira, default horizon
python3 sdlc/framework/tools/gen_roadmap.py --ahead 8       # further out
python3 sdlc/framework/tools/gen_roadmap.py --back 6 --ahead 4
python3 sdlc/framework/tools/gen_roadmap.py --cache /path/issues.json --sprints-cache /path/sprints.json
python3 sdlc/framework/tools/gen_roadmap.py --plan path/to/other-plan.yaml   # a different plan file
python3 sdlc/framework/tools/gen_roadmap.py --plan ""                          # Jira grid only
```

`--back` and `--ahead` count sprint columns either side of the active sprint; the defaults
are 4 and 6. Live Jira is the default and should stay the default — the point of the skill
is that the roadmap is never stale. Only fall back to `--cache` if Jira is unreachable, and
say in the answer that the grid came from a cached export and when it was taken.

Jira access uses bearer auth with the token in `$ACME_JIRA_TOKEN`. The generator
validates it once against `/rest/api/2/myself` before fetching anything, and exits on a 401
or 403 without retrying, because the service account locks after three failures. Never
print the token. A full run is one `/myself` call plus paged searches, about 30 seconds.

## What the generator does, so you can explain it

- **Rows** are epics with at least one story in the sprint window, ordered by the sprint they
  first appear in. Defects and support items are raised against stories, not epics, so they
  have no epic link at all; they roll up into a single `(no epic)` row at the bottom rather
  than being dropped. Open UI epics holding no sprint-assigned story are listed underneath
  the grid — they are planned but unscheduled, and hiding them would misread as "not planned".
- **Columns** are sprints, normalised to a `YY.Q.N` token, because Jira holds the same sprint
  under several spellings (`26.3.2(7/15-8/4)`, `26.3.2(07/15-08/04)`, `26.3.2 (7/15- 8/4)`).
  Jira only carries sprints a few iterations ahead, so columns past the last real one are
  projected on the team's 21-day cadence and drawn hatched.
- **Delivered columns** — every sprint before the active one — start collapsed to a narrow strip
  in the HTML. Click the `+` in the header to open one, or use the expand/collapse buttons above
  the grid to do the lot.
- **Cells** carry the phase (analysis, dev, SIT, automation, regression, E2E, UAT, release
  support), up to three story lines with their Acme Claims number and title, a `+N more` overflow,
  and a done count plus story points. Grey story lines are closed or ready for release.
  Release markers come from fix-version dates landing inside that sprint's window.

## Provenance, which matters when someone challenges a cell

The Year plan, Foundational, Speciality and Programme windows tabs are **[PLAN-FACT]** — read
from `year-plan.yaml`, which names its own source; nothing on them is computed from Jira, and
the generator never invents a point. Stories, sprints, statuses, points and fix versions on the
grid are **[JIRA-FACT]** — read from fields.
The phase on a cell is **[JIRA-INFERRED]**: it comes from the suffix the team writes on story
summaries (`… - Dev`, `… - SIT`, `… - UAT`), not from a Jira field, so a story summary that
omits the suffix falls back to dev. Projected columns are **[JIRA-INFERRED]** too. Do not
upgrade "in a sprint" or "has a fix version" into "released to production" — that rule lives
in `JIRA-DERIVED/00_METHOD_AND_CAVEATS.md` and this roadmap does not override it.

## Finish

Regenerate both files, then:

```
git add docs/knowledge-base/JIRA-DERIVED/05_UI_DELIVERY_ROADMAP.md \
        docs/knowledge-base/JIRA-DERIVED/UI-DELIVERY-ROADMAP.html
git commit -m "Refresh the Acme Claims delivery roadmap from Jira"
git push origin feature/devin-sdlc
```

No PR, no branch, for a refresh. (Changes to `year-plan.yaml` or the generator go through a
normal branch and PR.) Then attach `UI-DELIVERY-ROADMAP.html` to the reply so the user gets the
page in the browser, and say in two lines what moved since the last refresh — which epics
gained or lost sprints, anything now sitting in a projected column, and whether the plan
totals changed. Repeat the plan's open questions if any are still unanswered.

If the user asked for one epic (`epic ACME-224`), still regenerate the whole grid — it is one
run — but answer with that epic's row read out sprint by sprint from the Markdown.
