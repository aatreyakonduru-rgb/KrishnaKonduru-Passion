---
name: epics-from-roadmap
description: >
  Turn a Product Owner's roadmap spreadsheet (the list of features they want and roughly when) into
  Jira epics that meet the epic contract, asking the PO for whatever the sheet does not say. Reads
  .xlsx or .csv, drafts one epic per row, checks each against .devin/rules/jira-ticket-standards.yaml,
  reads Confluence links with the team service account (or asks for the document when it cannot),
  and shows the result as a plan page with the Jira calls as a preview. Nothing is written to Jira
  until Backlog writes are on and the PO says "approved". Also offers the sheet as a year-plan.yaml
  fragment for /product-roadmap. Invoke with: /epics-from-roadmap <path or uploaded sheet> [notes]
argument-hint: "<roadmap.xlsx | roadmap.csv> [a sentence from the PO about the sheet]"
visibility: internal
triggers:
  - user
  - model
agent: business-analyst
allowed-tools:
  - read
  - grep
  - glob
  - exec
---

# /epics-from-roadmap — a PO roadmap sheet becomes epics the rule book accepts

POs plan ahead in a spreadsheet: a row per feature, a programme, a rough date, sometimes a link. The
epics they raise from it are placeholders, and the hygiene page then flags every one of them (no
outcomes, thin description, no owner). This skill does the raising properly: it reads the sheet, drafts
the epics, and asks the PO the exact questions the epic contract needs answered — then, and only on
their word, creates them through the same Backlog path the stories use.

Read `.devin/rules/jira-ticket-standards.yaml` → `epic:` first. That is the contract; do not add to it
or soften it here.

## Step 1 — read the sheet

```
python3 sdlc/framework/tools/roadmap_epics.py <sheet> --markdown
python3 sdlc/framework/tools/roadmap_epics.py <sheet>              # JSON: epics, questions, sources
```

The tool maps the columns loosely (feature / capability / epic → title; programme / specialty; needed by
/ target / due; link / Confluence; notes / description; outcomes / acceptance; owner). It prints which
column it took for what and which it left as notes. If it chose wrong, say so to the PO and re-run with
the sheet corrected — do not guess a column meaning. `.xls` is not read; ask for an `.xlsx` or `.csv`.

## Step 2 — one question round per epic

Every row gets the questions the tool lists, and only those: a title over eight words or carrying a
year/phase, fewer than two sentences of objective, no Confluence link or document, fewer than two or
more than six measurable outcomes, no needed-by date, no fix version for the date, no owner. Ask them
as the PO would hear them from a colleague (the tool's wording is already that). Print
`[SDLC] question round <n> — <k> questions` so Argus shows them, and record the answers
verbatim in the plan. An epic with an unanswered question stays "not created".

In the same round ask two more, which the PO may skip: "What could stop this epic, how likely is it and how bad would
it be, and who watches it?" and "Does it need anything from another team, and by when?". Each answer is shown as a
`tools/risk_register.py add --epic <key> --kind risk|dependency ...` preview and saved with `--write` after "approved";
it shows on the PO office dashboard's Risks tab.

## Step 3 — Confluence links

Links are read with the team service account (`$ACME_CONFLUENCE_TOKEN`, one `/user/current` check, no
retry after 401/403 — the account locks). Tell the PO which pages were read (title, version, date) and
which could not be (and why — the service ID has no access, or the link has no page id). For those, ask
for the page saved as a document and uploaded here, and say the part they need to remember: **this is
ongoing — when the Confluence page changes, they upload the newer copy**, because the epic records only
what it was given. Every epic's description ends with the tool's `Source:` line (`source_stamp`), which
is what `/jira-hygiene` later reads to flag sources older than 90 days (`EPIC_SOURCE_STALE`).

## Step 4 — the plan page, then (maybe) Jira

Post the Markdown page as `[SDLC] artefact <REQ>-EPIC-PLAN.md — ready`: each epic field by field, the
questions and answers, the source line, and the Jira calls a live run would make (Backlog.create's
`calls`). That is the deliverable of a dry run, and dry run is the default.

Live creation needs both: Argus's Backlog writes switched on (`SDLC_BACKLOG_WRITES=1`, and the
page says so) and the PO typing `approved` on the plan. Then create each ready epic with
`console/backlog.py` → `Backlog.create(draft, by=<PO jira user>, source="roadmap")`, attach the uploaded
document to its epic, and post `[SDLC] note jira <KEY> — created`. Never create an epic that still has a
question open; never create stories here — `/research` does that once the epic exists.

Also render the plan as the review page: `python3 sdlc/framework/tools/review_pages.py epics
--data <json> --out <session dir>/<REQ>-EPIC-PLAN.html` (`sheet`, `pages_read`, and per epic `row`, `title`,
`specialty`, `objective`, `outcomes`, `needed_by`, `release`, `owner`, `source`, `questions`) and attach it.
Each card has Upload document and Approve, Edit makes every field editable, and Send to Devin returns the
decisions, answers, edits and document names as text to paste back.

## Step 5 — the year plan

Offer the PO the same sheet as a `year-plan.yaml` fragment for `/product-roadmap`:

```
python3 sdlc/framework/tools/roadmap_epics.py <sheet> --year-plan /tmp/year-plan.yaml --plan-year 2026
```

Every row is `unsized` (the sheet gives no points) and the open questions are carried across. If they
want it on the roadmap page, merge it into `sdlc/framework/context/roadmap/year-plan.yaml`
on a branch and raise a PR — the roadmap skill explains the file.

## Related

`/jira-hygiene` (the checks these epics will face), `/product-roadmap` (where the sheet shows up as the
Year plan), `/research` (stories under an epic), the Backlog tab's "Create epics from a roadmap"
(`console/server.py` → `build_roadmap_prompt`, which starts this skill in a Cloud session with the
uploaded sheet).
