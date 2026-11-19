---
name: dashboard
description: >
  Role-aware Acme Claims landing surface. One page per role lens (developer, tech lead, architect,
  QA, UAT, BSA, PO office, delivery lead, Scrum Master, release) showing that role's Jira queues, approval
  gates, branch and merge state, with self-contained forms to answer questions, hand work over,
  and raise observations.
visibility: public
triggers:
  - user
  - model
invocations:
  - /dashboard
  - /pending-approvals
  - /lead-dashboard
  - my dashboard
  - what needs my attention
allowed-tools:
  - read
  - write
  - edit
  - grep
  - glob
  - exec
---

# /dashboard — role-aware Acme Claims landing surface

`/dashboard` is the one command everyone runs. `/pending-approvals` and `/lead-dashboard` are
aliases of this command; they do not select a different view.

## Resolve the person

Work out who is asking from the chat identity first. If that is not available, read the git
author email and map its local part to `.devin/rules/people.yaml`. A Jira username or a
name fragment may be supplied when identity is ambiguous. Do not guess a person when more
than one assignable Jira user matches.

## Collect the person's Devin sessions — every run

The generator runs offline and cannot see Devin Cloud, so the "My Devin sessions" tab is only as
good as the list you hand it. Do this before generating, every time, not just when asked:

1. Look the person up in `.devin/rules/people.yaml` and take their `devin_user_id`.
2. Call `devin_session_search` for that user, newest first, and keep the sessions that are not
   archived and not tagged `closed` (all statuses: running, blocked, suspended, finished, expired).
3. Write them to `sdlc/framework/context/dashboard/<USER>-sessions.json` (git-ignored) as
   `{"sessions": [{"session_id", "title", "status", "substatus", "updated", "tags"}]}` —
   ids, titles, states and timestamps only, never a token or a message body. If a session carries
   a `handed-to:<jira-user>` tag, copy that user into `handed_to` so the tab shows it.
4. Pass the file with `--sessions`. If the lookup fails, say so in the reply and still generate:
   the tab then says the list was not collected rather than pretending nothing is open.

## Generate the dashboard

Run:

```
python3 sdlc/framework/tools/gen_dashboard.py --user <jira-username> \
  --sessions sdlc/framework/context/dashboard/<USER>-sessions.json
```

The lens is the `dashboard_lens` of the person's `primary_role` in `.devin/rules/people.yaml`
(looked up in `.devin/rules/role-routing.yaml`, the same lens Argus opens). With no primary role,
their `roles` are matched against the `roles` list of each lens in `.devin/rules/dashboard-roles.yaml`. Pass `--lens <id>` when the
user asks for another role's view or their roster roles are wrong, and `--base <ref>` when the
branch panels should compare against something other than `origin/master`. `--cache <json>`
renders from a fixture with no Jira access — `sdlc/framework/tools/fixtures/dashboard-demo.json`
is a fabricated example useful for showing a lens to someone who has no Acme Claims work yet, and
`sdlc/framework/tools/fixtures/dashboard-demo-tech-lead.json` fills every tech-lead tab
(approvals with numbered items and a delegated item, questions for me, my questions, team
questions older than three days, roster findings, branches, sprint load, Devin sessions) for a
walkthrough. A fixture may carry `roster_findings` and `sessions` so those tabs render offline
too. A page built from a fixture says "Sample data" under its title — never present one as live.

A new role or panel is a change to `.devin/rules/dashboard-roles.yaml`, not to the generator:
add the JQL panel under `panels`, then list it in a lens. Run `git fetch` before generating for
a branch-carrying lens, otherwise ahead/behind and conflict state reflect a stale checkout.

Jira project Acme Claims covers every Value Based Care team, so a team-wide panel — any panel query that
does not name `{user}` — is narrowed by the `team.scope` clause in `.devin/rules/dashboard-roles.yaml`,
the same clause as the team's board 247285. Personal panels are left unscoped so work assigned to
or raised by the viewer still shows even where the IT Team field was never filled in. A second team
reusing this dashboard changes `team.scope`, nothing else.

Attach the generated `sdlc/framework/context/dashboard/<USER>-DASHBOARD.html` to the
reply. The file is ephemeral and ignored by git. Summarise in chat what needs attention first:
questions older than three days, overdue approvals, and anything blocking the team pipeline.
Every panel carries only the controls that fit it: approval cards have Approve / Approve with
notes / Reject / Send to someone else per numbered decision item; question cards have the
answer box; session cards have Hand over. Nothing on the page writes anywhere — each button
produces a paste-back block, and the decision is recorded only when the block is applied under
`.devin/rules/gate-presentation.md`. The approvals panel also lists Jira approval sub-tasks
(label `Approval`) assigned to the viewer, so a delegated decision shows up on their own page.

The page uses the shared Acme Claims artifact kit (`.devin/rules/html-style.md`) — the same colours,
type and tabs as the LOE report — via `tools/artifact_kit/render_page()`; the generator only
adds layout rules of its own. It is one screen of tabs, each panel scrolling inside its own area. Tabs are ordered by
what they ask of the viewer and coloured to match: red needs them to act (questions for them,
approvals, overloaded people, flagged branches), amber is waiting on someone else (their own
questions, documents awaiting a business answer), blue is reference, violet is a form, and green
is empty — green tabs always sort last, so the first tab is the most urgent thing with content.
A Jira panel's colour when it has rows is its `attention:` in `dashboard-roles.yaml`; the
computed panels (workload, branches, approvals) decide from their rows. The header
chips count tabs, not rows — read the badge on each tab for the row count.

The header is one slim purple strip (title, the details line and the chips), and under it sit two
short rows: the group buttons — Needs you, Waiting, Reference, Tools, All clear, or the jobs on the
PO office, BSA and Scrum Master views — and the tabs of the open group only. Picking a group opens
its last used tab, or its first; the arrow keys move across groups, and a `#tab-N` link opens that
tab's group. The rest of the window is the open tab. Each
tab shows an icon and a short label (a question mark for Questions, a weightlifter for Workload).
Both come from `tab:` and `icon:` on the panel in `dashboard-roles.yaml`; the full title is the
panel heading and the tooltip when you hover the tab.

Every lens starts with the two question panels and then the person's own Devin sessions:
what each one is waiting for (a reply from them sorts first, then finished, asleep, working,
expired), how long since it moved, and a "hand to" picker from the roster with a note box. That
tab is red while any session is waiting on the viewer. After that each lens shows what that role acts
on: developers their work, branches and merge blockers; tech leads the review queue, branch
hygiene, aging questions and roster drift; architects debt, risks and epics; QA the test queue, the defects
they raised and untriaged observations; UAT what is waiting for business validation and what
came back fixed; BSAs unrouted questions and stories not ready to estimate; the PO office sprint
scope and stalled work; delivery leads the same plus who is carrying what and roster drift;
Scrum Masters what to raise at stand-up (stories with no sub-tasks, sub-tasks with no AI label or
the wrong case, AI-Used sub-tasks with no estimate, no hours or hours over the estimate), cycle time
and who has more than one story in progress, sprint points against capacity, DRE and this month's
AI labels (targets and definitions in `.devin/rules/scrum-master-metrics.yaml`, read by
`tools/scrum_metrics.py`; anything not yet settled shows as "To confirm"; when the user gives this sprint's capacity sheet (.xlsx), pass it with `--capacity-sheet <path>` so Commitment uses its hours, read by `tools/capacity_sheet.py`);
release managers the promotion queue and production validation.

The PO office lens deliberately carries no per-person load: no sprint workload, roster or team
pipeline panel, and its shared panels drop the assignee column through the lens-level `columns:`
override. Who is loaded and who is free belongs to the tech lead, architect and delivery lead
lenses.

The sprint workload panel, on the tech-lead and delivery-lead lenses, answers who is carrying the
sprint. It reads the active sprint from the team board, sums the original estimate of each
person's items in it, and compares that with the hours they have in the sprint: weekdays in the
sprint times eight, times their `allocation` in `.devin/rules/people.yaml` where it is set. Rows
read as `overloaded` above 130%, `heavy` above 110%, `room for more` below 50%, and `not
estimated` where someone holds items nobody sized. Unassigned sprint work and anyone working the
team's board who is not in the roster each get their own row. Two cautions when summarising it:
an estimate in Jira is a proxy for effort rather than a measurement of it, and a person whose work
is not estimated in hours — the PO office, UX, sometimes QA — reads as light when they are not.
The panel is read-only: rebalancing is a conversation, and moving one item is the handover form.

Two panels read the knowledge base rather than Jira, because the pipelines leave their open
items inside documents where nobody sees them. "Documents waiting on a business answer", on the
tech-lead, PO-office, delivery-lead and BSA lenses, counts `[REQUIRES STAKEHOLDER INPUT]` lines in the generated
knowledge base and the session specs, one row per document with the first question. Answering one
is an edit to that document: `/document-validation` collects them into a form with a proposed
answer for each, and `/explain-capability` often settles one from what the knowledge base already
knows. "Knowledge base behind the code", on the tech-lead and architect lenses, compares commit
dates only — a document last written before the code it describes moved is worth re-checking, which
is not the same as proven wrong, so send it to `/source-staleness-check` to compare content and
`/kb-refresh` to regenerate rather than reporting it as drift.

The tech-lead lens also carries a Roadmap tab: the page `/roadmap` last wrote to
`docs/knowledge-base/JIRA-DERIVED/UI-DELIVERY-ROADMAP.html` — Year plan, Sprint grid
and its other tabs — carried inside the dashboard and opened in a new browser tab when the Roadmap
tab is chosen, with the date it was generated under the tab title. The dashboard does not query Jira for it; when that date is old, run `/roadmap` first.

It also carries an Ontology tab: `docs/knowledge-base/CROSS-LAYER/ACME_ONTOLOGY.html`, the
business and data layers of the Acme Claims ontology with a lineage graph per business object, opened in a
new browser tab the same way. `tools/kbgen/gen_ontology.py` rebuilds it from the knowledge base.

The Tech Lead lens also has a Change confidence tab (`kind: confidence`), built by
`tools/verifier.py metrics` from the session folders with no Jira read: claims verified against
unverified per story (each `{STORY}-claims.yaml`), the independent verifier's verdict on each medium
or high-risk story (`{STORY}-verifier.yaml`), and rework, which counts the failed verifier rounds
before a pass, and missed impacts. A missed impact is a file changed by the fix of a defect linked to
the story in Jira (issue links of type Defect or Bug; commits found by the Acme Claims key in the message)
that the link-graph walk (2 hops) from the story's own files did not predict. The Jira read is one
issue call per story key; the demo cache gives it as `confidence_defects`.

The same two lenses carry two demo tabs for stories labelled `DEMO-NEEDED` (or `Demo`), the stories
that owe stakeholders a demo before they move from DEV to SIT. "Ready to demo" lists every labelled story,
whatever its status, in one collapsible group per sprint (the story's latest sprint, newest sprint
open first, then "Not in a sprint"; Expand all / Collapse all buttons). Its Demo recorded column links
to the story's page under Confluence "Acme Claims Demo Recordings" once /demo-needed has published an AC demo
(`demo_needed.recorded()`, one CQL search of the page's descendants), else says Not recorded; "?" means
Confluence could not be read and the tab note says why. "Demos coming up" lists the open ones whose
status is not yet in `jira.statuses.demo_ready` in `.devin/rules/sdlc-profile.json`. On
the Backlog tab these stories carry a 🎤 marker and a "Demo needed only" filter (ready ones first);
the Demo button books it (`action: demo scheduled`, a comment) or records it as given (`action: demo
given`, which takes the label off with a comment naming the date and audience). When a PO says the
ready statuses are different, offer to change `demo_ready`.

The tech-lead and PO-office lenses also carry "Defects by specialty": every open SIT and UAT
defect in project Acme Claims, not only the viewer's team, grouped by specialty and then IT Team. Each row shows who
is working on it, the planned release (fix version, else sprint end), days open and idle, and flags
for nobody assigned, no release planned, release date passed and not moving. Jira has no specialty
field, so the specialty comes from the keyword rules in `.devin/rules/defect-specialties.yaml`,
and the row shows which word matched; say so when you summarise it. `/defects-by-specialty` draws
the same view as a page of its own.

The same two lenses carry "Jira hygiene": the team's epics, recent stories and sub-tasks that do
not yet follow the Jira rule book (`.devin/rules/jira-ticket-standards.yaml` plus the rule-book
additions), grouped by check with what is missing. Red when a high-severity check trips. Talk
about tickets and checks, never people, when you summarise it. `/jira-hygiene` draws the same
view as a page of its own.

The roster panel only has content for the roster resolver and the backups named in the `owner`
block of `.devin/rules/people.yaml`; for anyone else it renders empty. It lists what the roster
and routing configuration can see without Jira: incomplete entries, people who cannot be matched
to a Jira user, roles outside the vocabulary and gates nobody can sign. It is read-only — the
correction is a pull request, raised by `/roster-check`, so run that when the panel is not empty.

## Apply backlog blocks

The BSA, PO office and Scrum Master lenses carry a **Backlog** tab: one grid of open stories,
defects and epics (`review_pages.py backlog`, rows from `review_pages.backlog_items`), filtered
by type and "needs grooming", grouped by specialty or epic, with the selected ticket in the
middle and the buttons Groom, Edit, Point / poker, Move, Clone, Split, Hold, Add note and
+ New ticket. Each button produces a `SDLC-DASHBOARD-BACKLOG` block. When one is pasted:

1. Save the block to a file and run
   `python3 sdlc/framework/tools/backlog_cli.py preview --block <file> --by <jira-username>`.
   `<jira-username>` is the requester resolved above, never the service account. Show the
   preview (the Jira calls and any rule-book findings) in plain words and wait for `approved`.
2. On `approved`, run the same command with `apply`. Writes happen only when
   `SDLC_BACKLOG_WRITES=1` and every ticket is on `SDLC_BACKLOG_TICKETS`; otherwise say it
   stayed a preview and why. Every write carries the requested-by label and comment.
3. `action: split` goes to `/story-splitter`; show the proposed stories on the
   `review_pages.py new-ticket` page (draft step) for approval.
4. `action: new` starts the **business intake** in `/intake` (section "Business intake").
   The draft tree comes back as an `action: create` block and follows steps 1 and 2.
5. Planning poker: `poker start` keeps the round in the facilitator's session. Tell each
   voter to send their card (a `poker vote` block with the round id) to the facilitator,
   who pastes it here; votes stay hidden until `poker reveal`; `poker agree` sets the points.

The grid is a snapshot from when the dashboard was built; re-running `/dashboard` refreshes it.

## Apply answers

When the user pastes a `SDLC-DASHBOARD-ANSWERS v1` block:

1. Parse every `key` and its `answer`; reject malformed or duplicate entries rather than guessing.
2. Call `question_subtask.py answer --key <key> --answer <answer> --answered-by <jira-username>`
   once per entry. `<jira-username>` must be the human whose dashboard produced the block;
   it must never be the Jira service account.
3. Confirm each key, including that the question was answered, returned to its asker (the
   `asked-by-<jira-username>` label — Jira records the service account as reporter), and
   mirrored onto the parent story. The user still closes the sub-task after deciding the answer
   is sufficient.

## Apply handovers

When the user pastes a `SDLC-DASHBOARD-DELEGATIONS v1` block, call
`question_subtask.py delegate --key <key> --to <jira-username> --by <dashboard owner> [--note <note>]`
once per entry. That reassigns the Jira item and comments who handed it over and why, so the
handover is visible to the next person on the story rather than only in chat.

## Apply approvals

When the user pastes a `SDLC-DASHBOARD-APPROVALS v1` block (`key:`, `items:`, `decision:`,
optional `to:` and `note:`), hand it to `/send-approval` step 5. Rules that skill enforces and
this one must not bypass: the Approve action from the dashboard is the approval word; a
`reject`, `approve-with-notes` or `delegate` line without a `note` is refused; `delegate`
without a confirmed assignable `to` is refused; a `session:` key with a `delegate` decision
creates the approval sub-task first. Confirm what was applied item by item.

## Apply session closes

When the user pastes a `SDLC-DASHBOARD-SESSION-CLOSE v1` block (`session:` per entry), call
`devin_session_interact` with `action: terminate` and `archive_on_terminate: true` for each one.
Terminating ends it for good; archiving takes it off the lists. Never close the session you are
running in: skip it and say so. Confirm each one closed, or the error it gave. When Argus
serves the dashboard, Close sessions does this itself through the Devin API and no block is needed.

## Apply session handovers

When the user pastes a `SDLC-DASHBOARD-SESSION-HANDOVERS v1` block (`session:`, `to:`, optional
`note:` per entry), run `/handover` once per entry — `.devin/skills/handover/SKILL.md`. It
confirms the taker, requirement and Jira keys with the user before writing anything, because
the dashboard row knows the session but not which requirement or Jira items go with it.

## Apply Argus feedback

A `SDLC-WORKBENCH-FEEDBACK v1` block comes from Argus: Send on its Feedback form, or its daily send of
the problems it noticed. Save it to a file and run
`python3 sdlc/framework/tools/framework_feedback.py import --block <file>` (preview), then again with
`--write`. It writes one new file, `SHARED/workbench-feedback/<YYYY>/<MM>/<batch>.yaml`, and refuses a batch that is
already there. The tech lead has said these pull requests need no approval or review: do not wait for `approved`
and add no reviewers. Commit only that file on a `devin/` branch from the working branch (`Pushed-by:` the
requester, `Work-ID: WORKBENCH-FEEDBACK`; if the access guard asks for an approval, pressing Send was it, so run
`access_guard.py approve`), push, raise the pull request, then merge it yourself: merge the branch into the
working branch with `git merge --no-ff` and push (never force). Merge only when the diff is exactly that one new
file. If Bitbucket refuses, leave the pull request open and say why in one line.

## Apply observations

When the user pastes a `SDLC-DASHBOARD-OBSERVATIONS v1` block, call
`question_subtask.py observe --story <key> --kind observation|defect|risk --title <title>
--detail <detail> --raised-by <dashboard owner> [--severity <severity>] [--environment <env>]`
once per entry. Each one creates the Jira issue and links it to the story with `Relates`.
Defects require a severity and an environment; risks derive their risk level from the severity
unless `--risk-level` is given. Confirm the created key back in chat. Refuse an entry whose
detail carries a member or provider identifier — see `.devin/rules/pii-handling.md`.

When the user pastes a `SDLC-DASHBOARD-SKILL-CONFIG v1` block (from the Skill config tab, one `- skill: <name> |
<column>: first|tick|none` line per changed box), save it to a file and run
`python3 sdlc/framework/tools/skill_homes.py apply --block <file>`. Show the lines it prints: who gains or
loses each skill. After the user says approved, run it again with `--write`, then commit
`.devin/rules/role-routing.yaml` on a `devin/` branch and raise a pull request into the working branch. It refuses
internal skills, unknown columns and more than eight first commands for a role; say why and change nothing.

When the user pastes a `SDLC-DASHBOARD-ROLE-CONFIG v1` block (from the Role config tab, one `- person: <Jira user> |
<role>: primary|secondary|none` line per changed box), run
`python3 sdlc/framework/tools/role_config.py apply --block <file>` the same way: the preview first, `--write`
after approved, then a pull request on `.devin/rules/people.yaml` for the roster owner or a named backup to review
(nobody approves a change to their own row, `ROSTER-GOVERNANCE.md`). After it merges, `/roster-sync` publishes the
roster to the Confluence roster page.

When the user pastes a `SDLC-DASHBOARD-GATE-CONFIG v1` block (from the Gate config tab, one `- gate: <gate id> |
<Jira user>: named|backup|none` line per changed box), run
`python3 sdlc/framework/tools/gate_config.py apply --block <file>` the same way: the preview first, `--write`
after approved, then a pull request on `.devin/rules/approval-gates.yaml`. It refuses an unknown gate, a person who is
not on the roster and a gate left with no named approver; say why and change nothing.

Run any of these with `--dry-run` first when the block looks unusual; it prints the exact Jira
requests without sending them.

Never make a network call from the generated HTML. The Submit/Generate button only assembles
the pasteable block on the page.

## Verify offline

```
for lens in developer tech_lead architect qa uat bsa po_office delivery_lead scrum_master release; do
  python3 sdlc/framework/tools/gen_dashboard.py --user <jira-username> --lens "$lens" \
    --cache sdlc/framework/tools/fixtures/dashboard-demo.json \
    --sessions sdlc/framework/tools/fixtures/dashboard-sessions.json -o /tmp/dash-"$lens".html
done
```

The Scrum Master **Leave** tab also reads the **Time off and backups** table on the Sprint Leave page
(`tools/time_off.py`): who is away now or in the next 14 days with their backups for stories, questions and
approvals (Type shows a Sick day), and who has not been asked about time off this calendar week.

On every dashboard the **Vacation planner** tab (`kind: vacation`) starts with this sprint's leave calendar
(`tools/leave_calendar.py`): one row per team member, one column per day, coloured by planned time off, sick day,
ad hoc leave, holiday and weekend, from the planning sheet and the Sprint Leave page. Under the planner rows it shows
this sprint's Unplanned leave: the dated sick and ad hoc days, and each person's count for the sprint and the year.

Next to the Vacation planner, the Scrum Master's **Unplanned leave** tab (`kind: unplanned`, `tools/unplanned_leave.py`)
counts sick days and ad hoc leave per team member and sprint: the Unplanned leaves tab of the leave tracker workbook
in `context/leave-tracker/` plus every row of the Unplanned leave table on the Sprint Leave page from the import date
on. It shows this sprint's and this year's totals, the latest days reported, and a read-only copy of every workbook
tab. A new workbook replaces the copy with `unplanned_leave.py import <file>.xlsx`.
