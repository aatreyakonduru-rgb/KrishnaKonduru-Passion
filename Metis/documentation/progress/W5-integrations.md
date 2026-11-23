# W5 integrations: notes

Plugin root `$METIS` = `metis-1.2.5-team (1)/`. All four items are built and tested. No shared file was edited.

| # | Item | Status |
|---|---|---|
| 1 | `tools/notify.py` (Slack, Teams, generic webhook, email) | done |
| 2 | `tools/bb_pr.py` (Bitbucket PR impact comment) + `templates/bitbucket-pipelines.yml` | done with limits: needs your Bitbucket to verify |
| 3 | `tools/refresh_trigger.py` (event-driven refresh, `serve-webhook`, `schedule`) | done with limits: needs your Bitbucket / Devin to verify |
| 4 | `tools/ui/screens_notify.py` + `tests/test_ui_notify.py` | done |

## Files created
- `tools/notify.py`, `tools/bb_pr.py`, `tools/refresh_trigger.py`, `tools/ui/screens_notify.py`
- `templates/bitbucket-pipelines.yml` (sample, Bitbucket Cloud Pipelines)
- `tools/tests/test_notify.py` (17), `test_bb_pr.py` (13), `test_refresh_trigger.py` (19), `test_ui_notify.py` (11)

## Test result
`python -m unittest tests.test_notify tests.test_bb_pr tests.test_refresh_trigger tests.test_ui_notify tests.test_ui` from `$METIS/tools`:
74 tests, OK (60 of them are W5's; `test_ui` is the existing UI suite, which loads every `screens_*.py`, so `/notify` loads without a path clash).
Seen while running, not mine: `screens_owners.py skipped: action /owners/recalibrate returns to unknown screen /owners?view=recalibrate` (W1).

## How to run
```
python tools/notify.py channels <KB>                 # channels + whether each env var is set (never the value)
python tools/notify.py events   <KB> [--channel N]   # events not yet sent
python tools/notify.py run      <KB> [--digest] [--send]   # DRY RUN unless --send
python tools/notify.py test     <KB> --channel N [--send]

python tools/bb_pr.py check   <KB>
python tools/bb_pr.py comment <KB> --pr 42 [--files a b] [--post]    # DRY RUN unless --post
python tools/bb_pr.py ci      <KB> [--post]                          # PR id etc. from pipeline env vars

python tools/refresh_trigger.py plan <KB> (--files api/A.java | --git REPO FROM TO | --payload push.json | --env | --since-build) [--task --by NAME]
python tools/refresh_trigger.py show <KB>
python tools/refresh_trigger.py serve-webhook <KB> [--port 8766] [--secret-env METIS_WEBHOOK_SECRET] [--branch main] [--task]
python tools/refresh_trigger.py schedule <KB> --every daily --at 02:00      # prints only
```
UI: `/notify` (nav "Notifications").

## Profile sections (the integrator adds these to `templates/kb-profile.yaml`; see Hooks)
`notify:` channels with `name`, `kind` (slack|teams|webhook|email), `url_env` (NAME of an env var, never a value), `events`, `min_interval`, `digest`; email adds `host, port, security, user, from, to` (`url_env` then names the SMTP password variable). `notify.base_url` gives links.
`bitbucket:` `flavor, base_url, project|workspace, repo, token_env, source_repo, max_chars, metis_url`.
`refresh:` optional `secret_env`, `branches`.
A `url_env` / `token_env` / `secret_env` that is not a valid variable NAME is refused, so a pasted URL or token is never accepted or echoed.

## Design points
- notify events (from existing files only): `pending_certification` (`_PENDING` batches), `open_question_raised` (VALIDATE_KB open questions: id, priority, type, blocked files, never the question text), `devin_task_queued` (`.metis/tasks`), `review_overdue` (`.metis/page_meta.yaml|json` if present; accepts `review_due|review_by|next_review|due`), `stale_pages` (`build_plan.stale`), `build_failed` (`.metis/builds` failed stage, failed build-stage task), `pr_impact_posted` (`.metis/bb_pr_log.json`).
- Dedupe in `.metis/notify_state.json` (keys per channel, last send time for `min_interval`). A dry run never writes it. More than 20 new events on a channel become one digest.
- Every message goes through `sensitive.py` (`clean_message`): a matching line is replaced by a note. Webhook URLs and SMTP passwords are never in messages, results, errors or the UI; network errors are reduced to the exception type. Webhooks must be https (http only for localhost).
- Slack payload `{"text"}`; Teams payload is the Workflows `message` + Adaptive Card attachment; generic webhook `{"source","message","events":[{event,key,files}]}`.
- `refresh_trigger` creates tasks with `ui/tasks.py create` (kind `build-stage`, `ref` = plan id, `stage` = `refresh`), a `_REGEN/<date>-refresh` staging folder, and tells the session to stage through `kb_gate.py propose`. A task for the same pages is not queued twice while one is queued/running. It never calls the Devin API or a model. Derived files (link graph, matrix, registries; `kb_gate.derived`) are left out of the stale list.
- `serve-webhook`: binds 127.0.0.1 by default, refuses to start without the secret env var, HMAC-SHA256 over the body in `X-Hub-Signature: sha256=...` (also `X-Metis-Signature`), 401 before parsing on a missing/wrong signature, 1 MB body limit, only `/webhook`. Writes the plan; queues a task only with `--task`.

## Safety: the one external write (for the integrator's safety text)
`bb_pr.py` is the ONLY Metis tool that writes to an external system, and it writes ONE kind of thing: a comment on a Bitbucket pull request.
- Dry run is the default (reads only, GET requests, prints the comment); `--post` is required to create or update the comment. The UI screen only previews (dry run); it has no post button.
- It never approves, merges, declines, or edits a PR, branch or file, and never touches Jira or Confluence.
- It updates its own earlier comment (marker line `[//]: # (metis-pr-impact)`) instead of adding one per push.
- The token is read from the env var named in `bitbucket.token_env`, sent only to the configured Bitbucket host, never printed or stored.
- The comment holds object names, links, trust signals, page names and question ids/priorities; no KB text, no question text; passed through `sensitive.py`.
- Suggested wording for the rules: "Metis never writes to Jira, Confluence or Bitbucket, except `bb_pr.py --post`, which adds or updates one comment on a pull request. Dry run is the default."

## Limits and what needs your environment to verify
- **Bitbucket comment route: NEEDS YOUR BITBUCKET TO VERIFY.** Both routes (Server/Data Center `/rest/api/1.0/projects/{p}/repos/{r}/pull-requests/{id}/comments`, with `/changes` and `/activities` to read; Cloud `/2.0/repositories/{ws}/{repo}/pullrequests/{id}/comments`, with `/diffstat`) follow the REST docs and are tested only against a fake server. Not confirmed: whether your token may comment, whether the marker line survives the markdown filter (the lookup is by the text `metis-pr-impact` in the comment body), Server edit conflicts (`version`), and pagination on a very large PR. The Release Record should keep this row as unconfirmed.
- Bitbucket push payloads (`repo:refs_changed`, `repo:push`) and the `X-Hub-Signature` / `X-Event-Key` headers follow the Bitbucket docs and are tested only with made-up payloads. The clone must already hold the pushed commit (fetch first); otherwise the plan lists every citing page as "cannot compare".
- Teams Workflows card format, Slack webhook, SMTP: tested against a local fake HTTP server and a fake SMTP object only; needs your Slack / Teams / mail host to verify.
- Devin: tasks are queued in the existing file queue. Nothing calls Devin; a session must claim the task. The `schedule` helper prints a wording for a Devin schedule; nothing is installed. Needs your Devin to verify.
- File-to-object mapping in `bb_pr.py` uses the `[E: repo/path:line]` tag of each graph edge (`graph_store` edges). A changed file that no edge cites yields "no impact traced", which the comment says is not the same as "no impact". The repo name in tags comes from `bitbucket.source_repo` (default: the repo slug).
- `review_overdue` depends on a `.metis/page_meta.yaml|json` that W1 may or may not produce; if absent the event is simply not raised.
- Pack link: the comment names the context pack id and a `context_pack.py` command; it does not host the pack (`/pack` builds in memory per server run).

## Hooks for the integrator
1. `templates/kb-profile.yaml`: add after `questions:` (exact text):
```yaml
# Notifications (tools/notify.py). Never put a webhook URL or password here: url_env is the NAME of an environment variable.
notify:
  base_url: ""                           # e.g. http://metis.example:8765, used for links in messages
  channels: []
  #  - name: team-slack
  #    kind: slack                       # slack | teams | webhook | email
  #    url_env: METIS_SLACK_WEBHOOK      # NAME of the env var that holds the webhook URL (email: the SMTP password variable)
  #    events: [pending_certification, open_question_raised, devin_task_queued, review_overdue, stale_pages, build_failed, pr_impact_posted]
  #    min_interval: 300                 # seconds between two messages on this channel
  #    digest: false                     # true: one summary message per run
  #  - name: leads-mail
  #    kind: email
  #    url_env: METIS_SMTP_PASSWORD
  #    host: smtp.example.com
  #    port: 587
  #    security: starttls                # starttls | ssl | none
  #    user: metis@example.com
  #    from: metis@example.com
  #    to: ["leads@example.com"]

# Bitbucket PR impact comment (tools/bb_pr.py). The only write Metis makes to an outside system; comment only, dry run by default.
bitbucket:
  flavor: ""                             # server (Bitbucket Server / Data Center) or cloud
  base_url: ""                           # server: https://bitbucket.example.com ; cloud: leave empty
  project: ""                            # server: project key
  workspace: ""                          # cloud: workspace
  repo: ""                               # repository slug
  token_env: ""                          # NAME of the env var that holds the bearer token
  source_repo: ""                        # repo name used in [E: repo/path:line] tags (default: the slug)
  max_chars: 8000

# Event-driven refresh (tools/refresh_trigger.py serve-webhook).
refresh:
  secret_env: METIS_WEBHOOK_SECRET       # NAME of the env var that holds the webhook shared secret
  branches: []                           # only these branches trigger a plan (empty: all)
```
2. Safety text (rules, manual section on safety, Release Record): add the paragraph under "Safety: the one external write" above. Release Record: keep the Bitbucket comment route as "unconfirmed: needs your Bitbucket to verify"; add Slack/Teams/SMTP/Devin-task rows as "built, tested against fakes, needs your environment to verify".
3. Manual / CHANGELOG: new tools `notify.py`, `bb_pr.py`, `refresh_trigger.py`, new screen `/notify`, new template `templates/bitbucket-pipelines.yml`.
4. Skills / MCP (optional): `metis-tasks` skill may mention that `refresh_trigger` tasks (`stage: refresh`, instructions list the stale pages) end with `kb_gate.py propose`, not a build run.
5. Nav: `screens_notify.py` is auto-loaded; `ui_common.RAIL_ICON` has no `/notify` entry so the rail uses the default dot and the first 8 letters of the label. Optional: add `"/notify": ("&#9993;", "Notify")` (W8 owns that file).
6. Optional: a periodic job (cron / Task Scheduler / Devin schedule) running `notify.py run <KB> --send` after `refresh_trigger.py plan <KB> --since-build`; `refresh_trigger.py schedule` prints the second one.
7. `docs`: `Metis-2.0.0-implementation-plan.md` WP8 names `bitbucket_pr.py` / `test_bitbucket_pr.py`; the delivered names are `bb_pr.py` / `test_bb_pr.py`.
