---
name: team-insights
description: >
  Team Insights, once a month: read every Devin session the team and the rest of the org ran that month, and Devin's
  analysis of each one, and work out how people use Devin — usage, ACUs, how they write prompts, skill gaps, repeated
  work a command could do, what is going well — plus the framework changes that would help. Writes the team numbers and
  nameless findings to the knowledge base, the recommended changes to SHARED/framework-recommendations.yaml, each
  person's learning plan to SHARED/team-insights/people/<YYYY>/<MM>/<devin user id>.md, and usage and ACUs per person to
  a private file for the tech leads only, then builds the monthly learning deck.
  Shown on the Tech Lead dashboard under Team Devin Cloud Usage and Framework feedback. Run by the monthly automation; say
  "/team-insights [YYYY-MM]" to run it by hand.
argument-hint: "[YYYY-MM] | deck [YYYY-MM] | decide R-001 accepted|rejected|done"
visibility: internal
triggers:
  - user
  - model
invocations:
  - /team-insights
  - team insights
  - how is the team using devin
  - monthly learning deck
  - recommended framework changes
allowed-tools:
  - bash
  - read
  - edit
  - git_create_pr
---

# /team-insights — how the team uses Devin, what to teach, what to change

The point is coaching and a better framework, not rating people. Findings are advice for the tech lead, never a
performance measure.

## Who sees what

| What | Where | Who |
|---|---|---|
| Team numbers, prompting patterns, skill gaps, repeated work (no names) | `docs/knowledge-base/SHARED/team-insights/<YYYY-MM>.yaml` | anyone who reads the repo |
| Wins, with the person's name | the same file | anyone |
| Recommended framework changes | `SHARED/framework-recommendations.yaml` | anyone; the tech lead decides |
| Learning plan per person: learning list, tips, one-on-one questions, a better prompt | `SHARED/team-insights/people/<YYYY>/<MM>/<devin user id>.md` — named by Devin user id, no names inside | in the repo; the Tech Lead dashboard shows it with the name from `people.yaml` |
| Usage and ACUs per person | `<session home>/insights/<YYYY-MM>.yaml` — never committed | tech leads only |
| The monthly deck | `REPORTS/team-insights/TEAM-INSIGHTS-<YYYY-MM>.html` | anyone |

## HARD RULES

1. **No names in per-person files, and usage never goes into git, Jira or Confluence.** A learning plan file is
   named by Devin user id and holds no name. Usage and ACUs per person are only in the private file; attach it to this
   session for the tech lead. A gap, pattern or repeated task in the shared file names nobody (`build` drops any
   `person` field there).
2. **Wins name the person, gaps never do** — in the shared file and in the deck.
3. **Numbers as read.** Counts and ACUs come from the session tools only. No dollars unless `cost.usd_per_acu` is set
   in `.devin/rules/scrum-master-metrics.yaml`; never guess a rate.
4. **Findings are labelled as findings.** A pattern needs at least two sessions behind it; give the count. If the
   analysis doesn't support a finding, leave it out.
5. **No message content beyond what a finding needs**: no secrets, member data or personal details. Quote a prompt
   only as a short, cleaned example.
6. **Recommendations are proposals.** Each goes in as `new`; only the tech lead moves it to accepted, rejected or done
   (`team_insights.py recommend decide`). Nothing goes to the Jira backlog until it is accepted.

## Steps

1. **Month.** The argument, else the month that just ended. Work out its first and last second as unix times.
2. **Sessions.** Page through `devin_session_search` with `created_after` / `created_before` for the month (`first`
   100, follow `end_cursor`). For each keep: session_id, title, user_id, origin, category, acus_consumed as `acus`,
   status, and pull_requests as `prs` (`url`, `state`). Do this in a script, not in the conversation.
3. **Analyses.** Page through `devin_session_insights list` for the same month and keep, per session,
   num_user_messages, the issues (title, label, impact) and the classification. For a sample of sessions per person
   (the larger ones, and every one with high-impact issues) call `get` for the timeline and the suggested prompt.
4. **Names.** People on the roster are matched by `devin_user_id` in `.devin/rules/people.yaml`. For a user id with
   no roster match, read one message the person typed in their own session (`devin_session_events`, category
   `message`, direction `incoming`, then `details`): each message carries the sender's `user_id` and `email`. Save
   `{user id: [emails]}` to `pairs.json` and run `team_insights.py link-ids --pairs pairs.json`, then `--write`; it
   fills `devin_user_id` only where the email is a roster email and the field is empty, and lists clashes. For others
   in the org put their name in `names` if the session tools show it, else the user id is shown.
5. **raw.json** `{month, names, sessions, analyses}` — numbers only, as read.
6. **findings.yaml**, from reading the analyses:
   - `prompt_patterns`: pattern, sessions, people, a short `before` and a `better` prompt (no names).
   - `gaps`: gap, sessions, people, `lesson`, `command` — name the framework command that covers it when one does.
   - `repetitive`: the same task asked for again and again, and the command, playbook, automation or template
     that would do it (`suggestion`).
   - `wins`: person, what went well (short, specific, kind).
   - `recommendations`: what, why, sessions, people, expected gain, touches (the skill, command or file).
   - `people`: keyed by Devin user id, per person `gaps`, `tips`, `questions` for the one-on-one, `prompt_before`
     and `prompt_after`. `build` carries last month's learning list over (statuses kept) and adds the new gaps as
     open; it lists any key it can't match to a user id.
7. **Preview, then write.**
   ```bash
   python3 sdlc/framework/tools/team_insights.py build --raw raw.json --findings findings.yaml
   python3 sdlc/framework/tools/team_insights.py build --raw raw.json --findings findings.yaml --write
   python3 sdlc/framework/tools/team_insights.py deck
   ```
8. **Hand over.** Commit the shared month file, `framework-recommendations.yaml`, the month's learning plans
   (`SHARED/team-insights/people/<YYYY>/<MM>/`) and the deck through a PR to `feature/devin-sdlc`. Attach `<session home>/insights/<YYYY-MM>.yaml` to the session — never commit it — and
   tell the tech leads to run `team_insights.py import <file>` on their PC and rebuild the dashboard.

## The monthly check-in

Once a month the first session with someone on the roster asks `team_insights.py checkin due --person "<name>"`
instead of the learn-more question. Show their answer with `checkin add --by --helped --blocked` and write it with
`--write` only after they type "approved". Answers feed the next month's recommendations.

## Teaching the learning list

At the start of a session with someone on the roster, after their own request is answered, run
`team_insights.py teach next --person "<roster name>"`. When it says `due`, add one short lesson on its `gap`: the
`lesson` and the `command` to try, or one of the `tips` when there is no lesson. Write it to them in the second person,
two or three lines, and end with "Say got it when this makes sense, or skip." One lesson per session, never in
scheduled or automated sessions. On "got it" show `team_insights.py learned --person "<name>" --gap "<gap>" --status
taught`, write it with `--write`, and commit the plan file through a PR to `feature/devin-sdlc`. A skip leaves the
item open for the next session.

## Other commands

- `team_insights.py recommend list` · `recommend decide R-001 accepted --by "<name>" --write`
- `team_insights.py learned --person "<name>" --gap "<gap>" --status taught|better --write` — updates the person's
  newest plan file; `better` is for the tech lead when the person now does it on their own
- `team_insights.py deck --month YYYY-MM`
