---
name: vacation
description: The team's vacation planner — the "Time off and backups" table on the Acme Claims Sprint Leave page. "/vacation" shows everyone's time off from today on with who covers their stories, questions and approvals. Anyone can add, change or remove their own time off and name their backups; the Scrum Master can change anyone's row. Nothing is written until the person types "approved". A sick day is the exception, since anyone can report it for anyone ("@Devin <name> is sick today") and it is written at once. The same planner is the "Vacation planner" tab on every dashboard. Say "/vacation", "my vacation", "I am off on <date>", "<name> is sick today" or "who is out next week".
argument-hint: "[show | mine | add <from> <to> | change | remove <from>] [for <person>]"
visibility: internal
triggers:
  - user
  - model
invocations:
  - /vacation
  - my vacation
  - my time off
  - who is on vacation
  - who is out next week
  - is sick today
  - out sick
  - sick day
  - ad hoc leave
  - unplanned leave
allowed-tools:
  - read
  - bash
---

# /vacation — one planner for everyone's time off and backups

The planner is the "Time off and backups" table on the Confluence page Acme Claims Sprint Leave. It holds one row
per period of time off: the dates, who covers the person's stories, questions and approvals, and whether their In
Progress stories go On Hold. Saving it also copies the days off into the sprint sections, so capacity stays right.
Confluence uses `ACME_CONFLUENCE_TOKEN`; on 401/403 stop and say so.

First identify the requester (`/identify-requester`). Use their roster name in `--person` or `--by`.

The sprint's planning sheet is kept in the repo, one file per sprint (old sprints stay):
`sdlc/framework/context/sprint-sheets/<sprint>.json`, and `<sprint>.html` built from it — the Scrum Master's
workbook (Capacity, Carry forward, Previous sprint AI savings) with every cell a text box and the workbook's formulas.
On the Capacity tab a day cell is 1 (in), 0 (off), 0.5 (half day) or H (holiday); available hours = sum of the day
cells × productive hours × % on project, points = team hours ÷ 8, and points with AI = points × the AI factor.

## STEP 1 — Show the sheet

```bash
python3 sdlc/framework/tools/time_off.py list                 # everyone, from today on
python3 sdlc/framework/tools/time_off.py list --person NAME   # one person
```

Show it as a table: Team member, From, To, Stories go to, Questions go to, Approvals go to, Stories on hold.
Mark rows that are on now. For "who is out on <day>", use `time_off.py away --date YYYY-MM-DD`.

Then attach this sprint's leave calendar and give its Unplanned leave numbers:

```bash
python3 sdlc/framework/tools/leave_calendar.py html -o /tmp/leave-calendar.html   # attach the page
python3 sdlc/framework/tools/unplanned_leave.py sprint                          # this sprint's days and counts
```

The calendar has one row per team member and one column per day. Each day is coloured by type: planned time off
(P, blue), sick day (S, yellow), ad hoc leave (A, purple), holiday (H, orange) and weekend (grey), and a half day is
half coloured. List this sprint's sick and ad hoc days with their dates, then each person's count for the sprint and
the year. The counts start from the Scrum Master's leave tracker, which records days per sprint without dates.

For the sprint's numbers, attach the sprint's planning sheet page (`context/sprint-sheets/<sprint>.html`) and give the
totals from `python3 sdlc/framework/tools/sprint_sheet.py show <sprint>`: team hours, story points and story
points with AI. `sprint_sheet.py list` names the sprints kept.

## STEP 2 — Add or change time off

When someone gives dates ("I am off 3 to 7 November"), ask the follow-ups that are not answered yet, one round:

1. Who covers your stories?
2. Should your In Progress stories go On Hold?
3. If someone asks you a question, who should it go to?
4. If an approval comes your way, who should approve it?

Then preview the planner:

```bash
python3 sdlc/framework/tools/time_off.py record --person NAME --by REQUESTER \
  --from YYYY-MM-DD --to YYYY-MM-DD [--stories-to N] [--questions-to N] [--approvals-to N] [--hold] [--note T]
```

To move dates, remove the old row and record the new one. A row with the same start date is replaced.

```bash
python3 sdlc/framework/tools/time_off.py remove --person NAME --by REQUESTER --from YYYY-MM-DD
```

The preview also lists the planning-sheet cells that change for every sprint sheet the dates fall in (0 for the days
off; days dropped from a row go back to 1). Show the preview and wait for "approved". Then run the same command with
`--write`: it saves the planner and the days on the Sprint Leave page, and writes the sheet files. Commit those files
on a `devin/` branch and raise a PR to `feature/devin-sdlc`. With `--hold`, also show
`time_off.py holds --person NAME` and apply it through `backlog_cli.py apply` after "approved".

**Half days and holidays.** Use the sheet directly:

```bash
python3 sdlc/framework/tools/sprint_sheet.py off SPRINT --person NAME --by REQUESTER --dates YYYY-MM-DD[,…] --value 0.5|0|1|H
```

**Any other cell** (productive hours, % on project, the AI factor, carry forward, AI savings): the sheet page's
**Save** gives a `# SDLC-SPRINT-SHEET-EDITS v1` block. Save it to a file and run
`sprint_sheet.py edit SPRINT --by REQUESTER --block FILE`, show the change and the new totals, and run it again with
`--write` after "approved" (repo files plus the Sprint Leave page), then the PR as above.

**A new sprint** gets its own sheet copied from the last one (same people, % on project and hours; every weekday 1;
Carry forward and AI savings emptied): `sprint_sheet.py new SPRINT --start YYYY-MM-DD`.

## Sick day and ad hoc leave

Someone on the team sends "@Devin <name> is sick today" (or "... is on ad hoc leave today"), by email to the team or
in the team channel, and anyone may send it. Record it straight away: no follow-up questions, no "approved", no backups, no Jira changes, no On Hold. If it
runs past a day, the Scrum Master and the tech leads move the person's tickets themselves.

```bash
python3 sdlc/framework/tools/time_off.py sick --person NAME [--date YYYY-MM-DD] [--reason sick|adhoc] --by SENDER --write
```

`--date` defaults to today ("sick yesterday" gives yesterday's date); `--by` is whoever sent the message, on the
roster or not. It writes one row on the "Time off and backups" table with Type **Sick day** (`--reason adhoc`: **Ad hoc
leave**), the day in the sprint section of the Sprint Leave page, and one row on the page's **Unplanned leave** table.
That table feeds the Scrum Master's unplanned leave counter (`tools/unplanned_leave.py`, the Unplanned leave tab of
the dashboard), on top of the leave tracker workbook kept in `context/leave-tracker/`. It does not touch the planning sheet files in the repo, so it works from a Teams
session (Confluence only). Reply with two lines: "<name> is down as a sick day on <date>." and the counter line the tool prints. Weekends and days already on
the planner are refused with the reason. A sick day reported by mistake is removed by anyone with
`time_off.py remove --person NAME --from YYYY-MM-DD --by SENDER --write`, which also takes it off the
Unplanned leave table. Sick days never send questions, approvals or
gate sign-offs to a backup.

## Who may change what

- Anyone may change their own rows.
- Anyone may record or remove a sick day or ad hoc leave for anyone.
- The Scrum Master (`primary_role: scrum_master` in `.devin/rules/people.yaml`) may change anyone's rows. With
  `--by`, the tool refuses anyone else.
- On the planning sheet, anyone may change their own day cells; the Scrum Master (and the solution lead) any cell.
- Argus opens the same sheet with every cell editable (Time off → **Sprint planning sheet**); its Save shows
  the change and writes after **Approved, save**. The dashboard's Vacation planner tab shows it read only.
- A backup must be on the roster and cannot be the person themselves.

## Rules

- Never write without "approved", except a sick day or ad hoc leave.
- Do not guess dates or backups; ask.
- Show the planner's current state only.
