---
name: defects-by-specialty
description: >
  Open SIT and UAT defects across the whole of project Acme Claims, grouped by specialty (EOC, Maternity,
  CHF, THL, ProgramA, ProgramB, ProgramC, PCMH, Unassigned) and then by IT Team, with who is working on each one,
  when it is planned to ship and what needs a decision. One self-contained page plus a Markdown
  copy. The same view is the "Defects by specialty" tab on the Tech Lead and PO office dashboards.
  Say "/defects-by-specialty".
argument-hint: "[cache]"
visibility: internal
triggers:
  - user
  - model
invocations:
  - /defects-by-specialty
  - open SIT and UAT defects by specialty
  - which specialties have open defects
  - defects by team and specialty
allowed-tools:
  - read
  - grep
  - glob
  - exec
---

# /defects-by-specialty — open SIT and UAT defects by specialty and team

A tech lead or PO asking "where are the open test defects, and is anyone on them?" usually wants
them by specialty, because that is how the business and the release plan talk. Jira can't group
them that way on its own: Acme Claims defects have no specialty field. So this skill reads every open
SIT/UAT defect in the project and sorts it with an editable keyword list.

## What it reads

- **Defects:** project Acme Claims, issue type Defect or Bug, "Defect Detected In" set to SIT or UAT,
  unresolved. This covers the whole project, not just the viewer's team, and every page of results
  is read.
- **Specialty:** the keyword rules in `.devin/rules/defect-specialties.yaml`. They are checked
  against the defect summary first, then the epic name, then the summaries of linked issues. The
  first specialty in the file that matches wins. Anything with no match goes under Unassigned. The
  page shows the matched word, so a wrong match is easy to spot; fix it in the YAML file, not in
  code. Treat the specialty as a rule-based guess, not a Jira fact.
- **For each defect:**
  - who is working on it
  - planned release: the earliest unreleased real fix version, or the sprint end when there is no
    fix version. "NA" and other placeholder versions count as no plan.
  - sprint
  - days open and days since the last update
  - severity, status, epic, linked issues and reporter
- **Flags:**
  - No one assigned
  - No release planned
  - Release date passed (the fix version date, or the sprint end when there is no fix version)
  - Not moving (no update for `stale_days`, 14 by default)

  A Critical or High defect with nobody on it or no live release date turns the dashboard tab red.

## Run it

```bash
python3 sdlc/framework/tools/defects_by_specialty.py
```

- **Live mode** needs `$ACME_JIRA_TOKEN`. It uses bearer auth and checks `/rest/api/2/myself`
  once. On a 401 or 403 it stops and does not retry; report the token problem instead of trying
  again.
- **Offline mode** (`cache` argument) uses sample data:
  `--cache sdlc/framework/tools/fixtures/defects-by-specialty-demo.json`.

It writes two files to the git-ignored `sdlc/framework/context/dashboard/` folder:

- `DEFECTS-BY-SPECIALTY.html`: a single page in the Acme Claims artifact-kit look, with filters by
  specialty, team, environment, severity and "only ones that need a decision"
- `DEFECTS-BY-SPECIALTY.md`: the same content as tables

`--out-html` and `--out-md` change the paths. Attach the HTML to your reply. In the text, give the
per-specialty counts the tool prints and the Critical or High defects that have a flag. Don't
commit either file: they are a snapshot of live Jira and go stale within days.

## When reporting

- **Evidence:** the counts, assignees, fix versions and sprints come straight from Jira, as of
  the time of the run.
- **Assumption:** the specialty. Name the matched word whenever a grouping is questioned.
- **Don't know:** a defect under Unassigned simply has no matching keyword. Don't guess its
  specialty; suggest a keyword for the YAML file, or a Jira label if the team agrees to add one.
- "No release planned" can also mean the fix version was never filled in, so check before
  escalating.
