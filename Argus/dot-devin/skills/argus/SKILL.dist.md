---
name: argus
description: Start Argus — the local web page that runs the whole SDLC from buttons (Jira tickets assigned to you, Start SDLC, the seven-stage rail intake → research → plan → implement → test → release → KB refresh, question cards, sign / forward approvals, artefact downloads, role-based My tools and Knowledge base menus), with Devin sessions working in the background — and hand back the link to open it. Say "/argus" to start it (or restart it if it is already up), "/argus stop" to stop it, "/argus status" to see whether it is running. "/workbench" and "/console" are older names and do the same.
argument-hint: "[start|stop|status] [port]"
visibility: internal
triggers:
  - user
  - model
invocations:
  - /argus
  - /workbench
  - /console
  - open argus
  - open the console
  - open the workbench
  - start the sdlc console
  - launch my ui
allowed-tools:
  - bash
  - browser_preview
---

# /argus — start Argus and give the user the link

Argus lives in `sdlc/framework/console/` (stdlib Python server + plain HTML/JS, no
build step). It is meant to run on the user's own PC at a fixed, bookmarkable address
(`http://127.0.0.1:8787`) and drive Devin through the API: every Start SDLC or menu action creates a
Devin session tagged `sdlc-workbench`; the page polls it, wakes it when it has gone to sleep, and
rebuilds the run list from Devin ("Sessions → Load my runs from Devin"), so nothing depends on one
session staying awake. It can also run inside a Devin session (below), but then the link only works
while that session is awake.

It needs one secret: `DEVIN_API_KEY` (a Devin API key that works on `api.devin.ai/v1`), from the
environment or, on a tester's PC, saved once on the page (Windows Credential Manager). The Jira token
`ACME_JIRA_TOKEN` is optional: with it the ticket lists come straight from Jira; without it —
the normal case on a PC — a short Devin Cloud session reads them with the service account
(`server.py --cloud-stories`) and the page caches them. Approvals, questions and handovers always run
in Cloud. Never print either secret. On a Devin
Cloud VM the network allowlist must include `api.devin.ai` (and `jira.acme.example`); without it
Start fails with "Cannot reach api.devin.ai from this box" — request the host through the
network-access prompt rather than retrying.

On a Windows PC, **Settings → Create desktop icon** on the page, or
`sdlc/framework/console/make-shortcut.cmd` (run once), puts a
**Argus** icon on the desktop. The icon runs `start-workbench.cmd`, which starts the server
in a minimised window when it is not already up (`--user` defaults to the Windows user name) and
opens `http://127.0.0.1:8787`. Windows does not let a script pin to the taskbar: right-click the icon →
Pin to taskbar.

## STEP 1 — Work out who is asking

The page must open as the person who typed `/argus`, the same way `/dashboard` knows who you
are — never make them pick themselves. Resolve them exactly as STEP 1 of `/identify-requester`
does: the requester's Devin Cloud user id first, then their chat identity email, both matched
against `.devin/rules/people.yaml`. Pass that id to Argus as `--user`; the server matches a
Jira username, e-mail or Devin user id against the roster and prints who it opens as. Only when
nobody matches, start without `--user` and say in the reply that the page will ask who they are.

## STEP 2 — Start it under the supervisor

```bash
sdlc/framework/console/run.sh restart [port] --user <devin user id or email>   # /argus
sdlc/framework/console/run.sh status
sdlc/framework/console/run.sh stop
```

`restart` stops an Argus that is already up (possibly started for someone else) and starts it
again for this person; `start` does the same but leaves a running one alone. The default port is
8787 and the supervisor restarts the server if it dies. The person passed with `--user` wins over
whoever was last picked in that browser.

**Where it runs decides how it reaches Devin** (`SDLC_DEVIN_TRANSPORT`, `console/bridge.py`):

- **On the person's PC** (`api`, only when `SDLC_DEVIN_TRANSPORT=api` is set; `start-workbench.cmd` and the
  desktop icon set it): the Devin API key, `DEVIN_API_KEY` or the one saved on the page. Ask for it through the
  secure secret prompt (personal scope) only there.

- **In Devin Cloud** (`bridge`, the team default, what `!argus` and `/argus` use inside a session): no
  API key. Start it, then start the bridge loop below. The page writes each Devin call to `~/.sdlc/console/bridge/outbox`; the loop runs it with this session's own tools
  (`devin_session_create`, `devin_session_interact`, `devin_session_search`, `devin_session_events`, `upload_attachment`),
  so the runs
  it starts are child sessions under the person's name.

```bash
sdlc/framework/console/run.sh restart 8787 --user <devin user id>
```

**Reserved host session.** The page is never hosted in the session the person chats in. When `!argus` or
`/argus` is typed in a person's own session, create one child session with `devin_session_create`: title
`RESERVED – do not type · Argus host · <name>`, tags `sdlc-workbench-host`, prompt
`/argus host for <devin user id>` (with `notify_on_response`). Tell the person to keep working in their own
session and open the link the host returns, and pass that link on when it arrives. A session whose prompt starts
with `/argus host` is the host: it skips this step and runs the rest of STEP 2 and the loop below.

Then run this with `scripted_tools` (timeout 7 days). It is the whole loop; it only runs the five tools above
(`devin_session_events` reads in full the long messages `get_messages` cuts short):

```python
import glob, json, os
D = os.path.expanduser("~/.sdlc/console/bridge")
HOST = "<this session's devin id, devin-...>"  # Argus's seat for team poker and team chat
RUN = {"devin_session_create": tools.devin_session_create, "devin_session_interact": tools.devin_session_interact,
       "devin_session_search": tools.devin_session_search, "devin_session_events": tools.devin_session_events,
       "upload_attachment": tools.upload_attachment}
os.makedirs(D + "/outbox", exist_ok=True); os.makedirs(D + "/inbox", exist_ok=True)
open(D + "/host", "w").write(HOST)
busy = {}  # outbox file -> its task; calls run side by side so a slow one never stops the heartbeat

async def serve(f):
    try:
        req = json.load(open(f))
        out = []
        for c in req.get("calls", []):
            fn = RUN.get(c.get("tool"))
            try:
                out.append({"text": await fn(**c.get("args", {}))} if fn else {"error": "not allowed"})
            except Exception as e:
                out.append({"error": str(e)[:400]})
        tmp = D + "/inbox/" + req["id"] + ".tmp"
        json.dump({"id": req["id"], "results": out}, open(tmp, "w")); os.replace(tmp, tmp[:-4] + ".json")
        os.remove(f)
    except (OSError, ValueError):
        pass  # half-written (read again on the next pass), or the page already gave up on it
    finally:
        busy.pop(f, None)

while True:
    open(D + "/alive", "w").close()
    for f in sorted(glob.glob(D + "/outbox/*.json")):
        if f not in busy:
            busy[f] = asyncio.ensure_future(serve(f))
    await asyncio.sleep(0.5)
```

The loop stops when the session sleeps or someone types in it. For 5 minutes after the last heartbeat
(`SDLC_BRIDGE_GRACE`) the page shows **Reconnecting** in amber and holds every request in the outbox, so nothing
fails; after that it says to send the host session a message. On every new message or wake in this session, answer it, then start the loop again (STEP 2 again if
`run.sh status` says the server is down). Restart it in the same turn without being asked, and without waiting for the person to
say so: the page must never stay red because of a chat message. If someone types in the host anyway, answer in one line
"This session is reserved for Argus: open the link and work there; don't type here.", then restart the loop. Never type requests into this session for the page; it only hosts it.
Never ask for the Jira token, it is an org secret.

**Test on my PC** (top bar, and on a run) checks the PR branch out into `~/sdlc/work/<ticket>/` on the
PC, finds the test pack in `sdlc/framework/context/test-packs/`, and drives Devin Local over
ACP (`devin acp`) with `/test-on-pc`; **Return to Cloud** packs, sends and hands control back
(`console/pctest.py`). It only works where Argus runs on the tester's own PC. On that screen the right
column is a chat with Devin Cloud: the ticket's Cloud session, or a new plain chat (not an SDLC run). While a
test runs, other pages stay usable: an orange **Devin Local needs you** button shows when the test is waiting for
an answer, and the page still goes back to the Cloud session after Return. `SDLC_CONSOLE_JIRA_USER=<id>` in the environment is the fallback when `--user`
is not given (for someone running it by hand on their own PC).

Check it answers before going on:

```bash
curl -s http://127.0.0.1:8787/api/config
```

`jira_ok` and `devin_ok` should both be true, and `default_jira_user` should be the requester's
Jira username. If `jira_ok` is false the response carries the Jira
error — do not retry Jira on 401/403, report it.

## STEP 3 — Hand back the link

Open a browser preview named "Argus" on the port and tell the user in one line:
click the preview chip, then open Argus in its own browser tab (the bar at the top of Argus has **Open in its
own tab**): inside the Devin page every run Argus starts is a new session and the Devin page switches to it,
taking Argus with it. The link works while the session is awake, and the
pages it opens in new tabs (Dashboard, run pages, Documentation) stay on the same session. On
their own PC they bookmark `http://127.0.0.1:8787`.

**Test on my PC** follows the person's `test_on_pc` in `.devin/rules/workbench-settings.yaml` (Argus config
tab on the dashboard): `devin_local` is the PC flow above; `local_hands` means this Cloud session asks for the
person's PC (the `devin connect <code>` card; the org's Local Hands setting must be on) and runs
`/test-on-pc` there, each step approved on the PC; `cloud_vm` runs the test pack on this VM; `off` hides it.

**Save** on the dashboard tabs (Skill, Role, Gate and Argus config, Answers, Approvals, Handovers,
Observations, Backlog) and on the review and intake pages sends the block to `/api/blocks` or to the run it came
from. It is a dry run unless the Save's Dry run tick is off (`dry_run` defaults to true). The run previews it and
waits for `approved`; repo files go through a pull request from a `devin/` branch
into `feature/devin-sdlc`, Jira only with `SDLC_BACKLOG_WRITES=1`. A saved copy of a page keeps the paste
text.

**Backlog** (top bar; every role sees it — as **Log hours** for roles outside the product owner, tech
lead, delivery lead, BSA and solution lead) is the day-to-day Jira work from buttons
(`console/backlog.py`): log hours as a worklog on the ticket's sub-task (a **Log hours** button on
the story view opens it preselected), groom and point a story,
run a planning-poker round (hidden votes, show, agree), move stories between sprints or back to the
backlog, clone a ticket (sprint and fix version cleared), add meeting notes as a comment or
attachment, and draft an epic or story from pasted notes with the rule-book precheck (numbered AC,
phase suffix, epic link, priority, one AI label) before it is created. A pointed story gets the standard DEV sub-tasks
(`DEV_SUBTASKS`) whose Original Estimates default to add up to the story's hours
(`hours_reference` in `.devin/templates/complexity-matrix.yaml`); `SUBTASK_ESTIMATE_SUM` flags a drift.
Titles start with the specialty (`specialties()` from `.devin/rules/defect-specialties.yaml` + `Platform`,
`SPECIALTY_MISSING`). "Set order" on selected tickets previews `Blocks` links A→B→C plus an `Order:` line;
`blocked_by` on a new ticket does the same; `move()` refuses (409) a sprint earlier than a blocker's sprint.
"Raise" on a ticket (every role, QA/UAT included): question / clarification → Question sub-task under the
story (`question_subtask` shapes: type 10112, labels Question + asked-by-<user>); observation / defect / risk →
the Observation / Defect / Risk issue types with a Defect or Relates link back to the story. Previews too. Every write is planned as the
exact Jira calls and shown under **Previews**; nothing is sent unless `SDLC_BACKLOG_WRITES=1` *and*
the ticket (or, for a new ticket, its epic) is in `SDLC_BACKLOG_TICKETS` (comma-separated
allow-list of test tickets). Writes carry a `requested-by-<jira user>` label and a comment naming
the person, so the shared service account never hides who asked. The ticket lists come from the
same Jira reader as the rest of the page (`backlog` and `epics` scopes); the sprint picker needs the
direct Jira service account and is empty when the page reads through Devin Cloud.

## What the user sees

- **Top bar:** Test on my PC, Backlog (roles above), Dashboard (builds `/dashboard` for the role's lens and opens it),
  My tools ▾ (Start a new requirement, then the role's `default_skills` from
  `.devin/rules/role-routing.yaml` under plain names from `MENU_TEXT` in `server.py`, with the
  command beside each; `test-on-pc` and `dashboard` are left out because they have their own
  buttons), Knowledge base ▾ (**Look things up**: Ask a question and Explain a capability, for
  everyone; **Keep it current**: Refresh after a release, Find drift and Settle open questions for
  solution_lead, architect and manager, plus Generate new knowledge for solution_lead and manager),
  Waiting on me (gates, questions, Jira sub-tasks waiting on the user and their sprint Reminders), My sessions (all runs;
  Reload from Devin), Help ▾ (Documentation), Settings ▾, the "who are you" picker (roster from
  `.devin/rules/people.yaml`) and the role chip. Every menu item opens in a new tab, in one of three ways:
  - **Ready-made pages, no Devin session:** Help, Catalogue, Onboarding guide and Presentation open
    `/page/<name>` at once. Help, Catalogue and Onboarding are built from `USER-MANUAL.md`,
    `CATALOGUE.md` and the newest `ONBOARDING-<role>-<date>.md` per role on `feature/devin-sdlc`;
    Presentation is `ARCHITECTURE.html`. The committed copies live in `sdlc/framework/reference/`
    (`tools/gen_reference_pages.py`, checked by `validate_framework.py`). The onboarding page has a
    button to ask Devin to write or rewrite a role's guide.
  - **Roster check** opens `/page/roster` first: everyone on `.devin/rules/people.yaml`, grouped by job
    role, with the hats they wear, the gate roles they can sign, sprint time, away cover and whether
    their Devin user id is known. Its button starts `/roster-check` for the drift check.
  - **Forms:** Settle open questions (below).
  - **Work:** everything else starts one Devin session and opens its result page (`/run/<id>`): what
    Devin said, its documents (Markdown and HTML open as formatted pages via `/view/<run>/<n>`;
    repository `.md` files render too), question cards, the gate to sign, a reply box and Wake. Skills
    whose `allowed-tools` only read start for real; skills that can write start as a dry run with "Run
    it for real". Asking for the same thing again within 24 hours reopens that answer instead of
    starting another session, with "Run again now" on the page. A skill whose `argument-hint` is
    optional (`[...]`) starts at once; one that needs input (`<...>`) asks for it first, with its
    listed choices as buttons.
  A skill listed in the Knowledge base menu is not repeated under
  My tools. **Settle open questions** opens the validation form (`/validation`) straight
  away, rendered from `KB_OPEN_QUESTIONS.yaml` on `feature/devin-sdlc` (this checkout's copy if
  the remote cannot be read); **Send my answers to Devin** starts `/document-validation apply` with the
  answers block, and **Look for new questions** starts `/document-validation new`.
- **Settings ▾ → View as role (temporary):** lists every role in `role-routing.yaml`. Picking one
  makes the menus, dashboard lens and gate checks behave as that role, shows a "Previewing" banner
  and a "Back to my role" button. It changes what the page shows, not what anyone is allowed to do.
- **Left:** Jira tickets (assigned to me / current sprint / all open for Acme-Claims-Web), and a
  New requirement box with Dry run and **Start SDLC** (runs `/intake "<text>"`; shows as
  `REQ-<mmddhhmm>` until a Jira story exists).
- **Start SDLC** keeps the person on the ticket: a note confirms the start and the ticket shows
  "This ticket's run" (progress bar, stage, questions to answer in place, Open the run). Argus never
  switches to the run or the Devin session by itself; only Open the run / Open in Devin do.
- **Middle (run page):** a progress bar, the seven-stage rail (Intake, Research, Plan, Implement,
  Test, Release, KB refresh; click a stage to filter), "Right now" in plain English, question cards
  pinned above the messages (type answers, Send answers), Devin's messages (no step-by-step lines;
  those are in Trace), a message box, Wake and Open in Devin.
- **Ticket text:** once SDLC has started on a ticket, Backlog edits, grooming and AC writes refuse
  its description and acceptance criteria (409); points, title, sub-tasks, hours and comments still work.
- **Right:** the sign panel for the waiting gate — name, who signs, timeout and the gate's approval
  criteria from `.devin/rules/approval-gates.yaml` as tick boxes; Approve / Approve with notes /
  Reject with reasons (the reply always starts with `approved` or `rejected`, as
  `.devin/rules/gate-presentation.md` requires); **Forward…** sends `/send-approval <gate> to <person>`
  (roster person + required note; the session creates the Jira approval sub-task). On the intake gate
  (SDLC_01) "Also create a Jira story in Acme Claims from this spec" works as before (roster assignee;
  unticked writes nothing to Jira). On the gate before coding (SDLC_04 / HOTFIX_PLAN_CODE_APPROVAL),
  when the run has a Jira story, "Add sub-tasks to <story> before coding starts" shows editable rows
  (title + original estimate in hours, both required, + technical description) filled from the
  `<STORY>-SUBTASK-PLAN.json` artefact /plan posts (standard DEV set until then). Sub-tasks already on
  the story are rows too, with Devin's suggested change and an "Update <key> in Jira" tick; only ticked
  ones are updated, and only if they are sub-tasks of the story. Approving asks "Update Jira?" listing
  what is created and what is updated before anything is written. Argus writes them itself when
  Backlog writes are on; otherwise the approval carries `[SDLC] note subtasks` for the session to
  write them (a dry run only lists them). Unticked writes nothing to Jira. Tabs: Documents (each artefact viewable and downloadable),
  Diffs, PR, Skills, **Trace** (per stage: agents active and queued, skills and why, rule files
  loaded or deferred, knowledge-base files loaded or skipped with the reason, cross-layer matrix
  chains used, the gate waiting and who owns it, decisions — built only from the `[SDLC] route /
  kb / rule / chain / decision` lines the session prints, `.devin/rules/workbench-trace.md`; no
  token counts or scores, the pipeline has none; **Settings → Trace** opens the same view in a
  floating window that can be dragged aside, minimised or closed), Chat, and **Download all (.zip)**.
- **Dry run** is on by default everywhere: no commits, pushes, PRs, promotions, Jira or Confluence
  writes; steps that would write post what they would write as an artefact instead. Untick it only
  when the user explicitly says the run is real.
- **Look:** the Acme Claims kit (`acme.css`, Acme purple); ◐ cycles Acme Claims → earth → dark.

**Closing sessions.** "Close" means the Devin session is terminated (`DELETE /v1/sessions/{id}`, it
cannot be woken again) and tagged `closed`; the answer, documents and messages stay on the result
page. Archiving is different: an archived session only drops out of lists and can still resume, so
Argus does not use it. A menu action closes itself once Devin has posted
`[SDLC] skill <name> — finished` and is not waiting on a question or a gate; the result page then
says "finished · session closed" and offers Run again instead of a reply box. SDLC runs are never
closed automatically. Any run has a **Close session** button, and the dashboard's Sessions tab (which
Argus fills from the Devin API) has tick boxes and **Close sessions**
(`POST /api/sessions/close`).

Runs are cached in `~/.sdlc/console/runs.json` (older five-stage runs are mapped onto the seven
stages; a `pr` stage becomes part of Implement).
