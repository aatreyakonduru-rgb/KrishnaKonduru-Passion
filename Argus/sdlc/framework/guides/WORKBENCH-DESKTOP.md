# Argus: desktop version

> **Not for the Acme Claims team.** The Acme Claims team runs Argus in Devin Cloud only (`!argus`) and tests
> in Devin Cloud; nobody on the team needs a Devin API key. Use `USER-MANUAL.md` and the Confluence page
> "Argus User Manual". This page is kept for other teams that run Argus on their own
> Windows PCs, where it calls the Devin API with the person's own key (`SDLC_DEVIN_TRANSPORT=api`).

## How it started

It started with a sketch. One person sits at one window in front, and two windows sit behind it: Devin Cloud and
Devin Local. The person works in the front window and never has to juggle the two behind it.

![Hand sketch: a person, then a box for Argus, with arrows to a Cloud box and a Local box](manual-images/workbench-01-hand-sketch-a-person-then-a-box-for-the-.jpg)

*Resource 3's drawing of the idea: you, with Argus in the middle and Devin Cloud and Devin Local on either side.*

The front window is Argus, the dashboard or a Devin chat. Devin Cloud, behind it, reads Jira, Confluence and
the code, writes the spec, the plan, the code and the pull request on its own machine, and stops at every gate for a
named person. Devin Local, the other window behind, runs on the developer's own PC: it checks out the pull request,
tests it with them and hands the evidence back to the same Cloud session. The commands, gates and dashboards in this
manual all grow out of that picture.

---


## Local Devin: a command box on your own PC

`sdlc/framework/console/local.py` is a small page you run on your own PC. You type into it
what you would type to Devin Cloud, and anything it produces opens in your own browser, not on the
Devin machine.

Start it from a checkout of the repo with `DEVIN_API_KEY` set:
`python3 sdlc/framework/console/local.py --user <your e-mail>` (`python` on Windows). It
opens `http://127.0.0.1:8785` for you. It is plain Python with no packages to install, so it runs the
same on Windows, Mac and Linux.

`/argus` starts Argus next to it on port 8787 and opens it (`/argus stop` and
`/argus status` do what they say; `/console` still works). Argus's Jira ticket lists need
a Jira key on your PC; without one, use Devin Window. Without a key, each list (your tickets, sprint, backlog, epics) is read once through the day's Devin Cloud Jira reader and then kept on your PC; Jira is read again only when you press **Refresh** or **Check now**, so leaving Argus open costs no reads.

`/dashboard` builds your role dashboard and opens it; `/dashboard <lens>` shows another role's view.
Your PC needs no Jira key for it. Without one, the box starts a short Devin Cloud session that builds
the page with the Jira service account and attaches it; the box downloads it, opens it in your browser
and closes that session. That takes a minute or two. If you do have `ACME_JIRA_TOKEN` set, the
page is built on your PC in a few seconds instead. `/help` lists the commands.

The Scrum Master's reminders are also asked straight to the person who owns the ticket, at the start of their Devin Cloud session, two at most: for example "ACME-123 has been In Progress 10 days. When do you expect to close it?" or "Defect ACME-456 has no fix version. Which release will the fix ship in?". The answer is put on the ticket (due date, fix version, or a comment naming the question and the answer) after they say approved (`tools/sm_reminders.py`), so the gap drops off the Stand-up check.

The **PO office**, **BSA** and **Scrum Master** dashboards have their tabs grouped by job (for example Plan, Groom, Sprint, Demo and release, Mine for the PO office), in the same order as Argus's What I do list, and each tab links to the task in Argus where the work is done. Other dashboards group them as Needs you, Waiting, Reference, Tools and All clear. The group buttons are one row under the header, and the next row shows only the tabs of the group you picked; the rest of the window is the tab you are working in. Every page in the Acme Claims look has the same slim purple header strip as Argus: the title and its details line on one line (hover to read a cut-off line in full), with the chips and the theme switch on the right.

The **Scrum Master** view (`/dashboard scrum_master`) is laid out around the Scrum Master's day. **Stand-up check** lists, with the person to ask: stories with no sub-tasks, stories and sub-tasks with no AI label (or `AI-USED` instead of `AI-Used`), AI-Used sub-tasks with no original estimate, closed with no hours, or logged over the estimate, stories In Progress with no time logged, stories still open when every sub-task is closed, and stories closed with sub-tasks still open. **Cycle time** is the average from In Progress to Ready For Release or Closed over the last 90 days against the 12.8-day baseline. Days On Hold don't count, the same as the Boost cycle time in Tableau: a story In Progress 1–3 October, On Hold 3–8 October and closed on the 10th counts 4 days. The tab lists each story in progress now with its days (and the days it spent On Hold before), each story On Hold now with how long it has waited, and anyone with more than one story in progress. **Commitment** is the story points in the active sprint against the team capacity and the 185.7-point throughput floor. Capacity comes from the "Acme Claims Sprint Leave" Confluence page (filled in from Scrum Master follow-ups), or from a capacity sheet when one is given, worked out the way the sheet's formulas do: days marked 1 × 6 productive hours × share of time on the project, and the team's hours ÷ 8 give the points. The tab lists each person's days in, days off and hours. **Leave** is a calendar of the sprint: one row per person, one column per working day, "Off" on the days they are away, and who hasn't answered yet. **Over-committed** shows each person's story points in the sprint against their capacity after leave (hours ÷ 8), with how far over they are, so the Scrum Master can ask how they plan to handle it. Give a sheet with `--capacity-sheet <file>.xlsx` or set `capacity.sheet`; with neither the sheet nor the page the tab uses `team_capacity` (181). **DRE** is 1 − production defects ÷ defects in every environment (Defect Detected In) this year. **AI this month** counts closed sub-tasks as AI-Used, AI-NA, no label, wrong case and exempted (AI-Used logged over its estimate), how many of them Devin created (label `devin_created`), and shows AI efficiency: (estimated − logged hours) ÷ estimated hours on the AI-Used sub-tasks, exempted ones left out, against the 30% target. Then Workload, Sprint scope, Stopped moving, Observations awaiting triage, Defects by specialty, Jira hygiene and Grooming. Every epic, story and sub-task Argus creates carries the `devin_created` label, and a `Source BRD:` line when the draft names the BRD it came from; the rule-book check asks an epic for a BRD or Confluence link and two to six measurable outcomes (`epic_definition_of_ready` in `.devin/rules/jira-ticket-standards.yaml`). The targets and definitions are in `.devin/rules/scrum-master-metrics.yaml`; Points still to be settled show as "To confirm" on the tab. The page only reads Jira; Tableau stays the number of record. In Argus the Scrum Master opens on the team sprint.

Everything else, slash commands included, starts a Devin Cloud session, or goes to the session you
have selected on the left. The left side lists your Devin sessions, the same ones you see in the Devin
web app. When Devin posts a page or report, the box saves it under `~/.sdlc/local` and opens it in
your browser once. Close session ends a session for good, as it does in Argus.


### 2. Set up your PC

#### Once per PC

You need Python (`py -3`), git that can fetch from Bitbucket with your own login, and a checkout of `ACME/claims-web` on `feature/devin-sdlc`. Then do these steps once. [A2] [?2]

**1. Install the Devin CLI** (this is Devin Local).

1. Download and run the Windows installer from [docs.devin.ai/cli](https://docs.devin.ai/cli). Most PCs need **x86_64**. Pick **ARM64** only for Windows on ARM.
2. Or open **PowerShell** (not CMD or Git Bash) and run `irm https://static.devin.ai/cli/setup.ps1 | iex`.
3. Close the terminal and open a new one. `devin --version` should print a version. If your PC blocks the installer, ask desktop support to install it.

**2. Get your Devin API key.** In Devin Cloud, open **Settings → API Keys** and create a personal key. It starts with `apk_user_` and is shown only once, so copy it straight away. Treat it like a password: don't put it in a file, a chat, a Jira comment or the repo.

**3. Give the key to Argus**, in one of two ways:

- **On the page (simplest).** Start Argus, open **Test on my PC** and paste the key. It's kept in Windows Credential Manager, not in a file.
- **As an environment variable.** Click Start, search for **Edit environment variables for your account** and open it. Under **User variables** click **New**. Enter `DEVIN_API_KEY` as the name and your key as the value, then click **OK** twice. Close Argus window and start it again, because programs that are already running don't see a new variable. To check it without showing the key, run `[bool]$env:DEVIN_API_KEY` in a new PowerShell window. It should print `True`.

If both are set, `DEVIN_API_KEY` wins. You can also set the variable from PowerShell with `[Environment]::SetEnvironmentVariable("DEVIN_API_KEY", "<your key>", "User")`, but PowerShell then keeps the key in its command history. The dialog doesn't. Devin Local never gets this key. Only Argus uses it, to talk to Devin Cloud.

**4. Start Argus and add the desktop icon.** The first time, open `web\framework\console` in File Explorer and double-click `start-workbench.cmd`. The page opens at `http://127.0.0.1:8787`. Then click **Settings ▾ → Create desktop icon**. A **Argus** icon appears on your desktop, and from then on you start Argus from that icon. `make-shortcut.cmd` in the same folder makes the same icon. To pin it, right-click the icon, choose **Show more options**, then **Pin to taskbar**. [?3]

**5. Sign in to Devin Local.** In **Test on my PC**, press **Sign in to Devin Local** once. It runs `devin auth login`, which opens your browser for the normal Devin sign-in.

Then press **Check my PC**. It checks Python, git, Bitbucket, the Devin API and Devin Local in one go, and tells you what to fix for anything that fails.

You don't have to sign in as yourself. The desktop icon passes your Windows login (for example resource3) to Argus. It finds you on the team roster (`people.yaml`) and opens as you, with your Jira lists, your sub-tasks, your sessions and your role's menus. Only if your login isn't on the roster yet does the **You** box at the top right ask who you are. Ask the roster owner to add you.

#### Every day

Click the icon. It starts Argus in a minimised window if it isn't already running, then opens the page. To stop Argus, close that minimised window.

When an orange **Update Argus** button shows in the top bar, click it between tests. It pulls the latest code, restarts, and reloads the page. It won't update while a test is running or while your checkout has local changes. To check straight away instead of waiting, use **Your name ▾ → Check for updates now**.

If the page loses touch with Argus, an orange banner says so and tells you how to start it again. You don't need to do anything else: the page carries on once Argus is back.


### 5. Test a ticket on your PC

marks screens taken on the Devin machine from the current code, with Devin Local's side replayed from a laptop run. [A1]

#### 5.1 Say what to test

Open **Test on my PC** and type or pick the ticket. Argus finds the rest in Bitbucket: the PR branch, the test pack Cloud wrote on it, and the Cloud session named in the pack. The folder line shows where on your PC the code will go. Then press **Test on my PC**.

![Test on my PC: the This PC checklist with the API key, Devin Local and Jira lines, then What to test with Ticket, PR branch, Cloud session and Test pack](manual-images/workbench-03-test-on-my-pc-this-pc-card-then-what-to-.jpg)

*Before a ticket is picked. Here Devin Local is missing, so its line has the download link, Copy the download link and Check again. This screen uses a deeper purple, so you can tell it apart from the Cloud screens.*

#### 5.2 Argus gets your PC ready

**Steps after Test on my PC**

| # | Step on the card | What happens |
|---|---|---|
| 1 | Ticket folder and code | Makes the ticket's folder and gets the repo into it. |
| 2 | Check out the PR branch | Fetches the branch with your own git login and checks it out. |
| 3 | Find the test pack | Finds the pack Cloud wrote on the branch. |
| 4 | Other repos the pack needs | Gets any other repos the pack lists. |
| 5 | Open the evidence run | Checks the branch is at the commit the pack was written for, then opens a new evidence folder. |
| 6 | Tell Cloud the PC has control | Sends `[SDLC] control pc` to the Cloud session, so Cloud stops pushing to the branch. |
| 7 | Start Devin Local with /test-on-pc | Starts Devin Local and hands it the pack. |

#### 5.3 Devin Local tests with you

A strip at the top of the card shows where the test is. One line under it says what's happening, such as "Waiting for you: answer Devin Local in the box below". The counts only move when a result is actually recorded in the evidence folder.

**Progress strip**

| Stage | Lit while |
|---|---|
| Get the code | Steps 1–5 are running. |
| PC has control | Argus is telling Cloud and starting Devin Local. |
| Automatic checks (n of m) | Some checks have no result yet. |
| Your answers (n of m) | Some acceptance criteria have no result yet. |
| Return to Cloud | Everything has a result, or the return steps are running. |
| Back with Cloud | The evidence is in the Cloud session and Cloud has the branch again. |

For each acceptance criterion, Devin Local tells you what to try in the browser and asks what you saw. Answer in the box on the card: passed, failed, or not run with the reason, plus a note or a screenshot if you have one.

![A test card with the progress strip on Your answers 1 of 3, seven ticked steps, Devin Local's AC-2 question, and the chat panel on the right](manual-images/workbench-04-a-test-card-with-the-progress-strip-on-y.jpg)

*Both checks done, one answer in, and Devin Local asking about AC-2.*

#### 5.4 Permission questions

Devin Local can run read-only git commands and the evidence commands without asking. For anything else it asks first, in an orange box with **Allow once**, **Always allow** and **Deny**. Read the command before you choose. **Allow once** is the safe choice for anything you don't recognise.

![Orange box: Devin Local asks to run evidence.py mark AC-1 passed, with Allow once, Always allow and Deny buttons](manual-images/workbench-05-orange-box-devin-local-asks-to-run-evide.jpg)

*Your answer goes straight to Devin Local, and it carries on.*

#### 5.5 Return to Cloud

When every check and criterion has a result, press **Return to Cloud**.

**Steps after Return to Cloud**

| # | Step on the card | What happens |
|---|---|---|
| 1 | Check nothing is left unpushed | Stops if the folder has local commits that Cloud hasn't seen. |
| 2 | Seal the evidence | Checks the folder is clean and the PR is still at the tested commit, then zips the run. |
| 3 | Send the evidence to Cloud | Checks the PR again, uploads the zip and posts the evidence message to the session. |
| 4 | Hand control back to Cloud | Sends `[SDLC] control cloud`. |

If the Devin API is busy, or says the session is still starting, Argus waits and tries again after 5, 10, 20, 30 and 60 seconds. It only shows an error after that, about two minutes in all.

When it's done, the card says **Back with Cloud** and Argus opens the Cloud session. Cloud checks the zip, writes the test report and carries on. Then the wrap-up starts (section 8).

If the evidence is already in Cloud but the hand-back failed, **Hand back only** sends just the `control cloud` message.

![Finished card: all six stages done, Back with Cloud lit, all eleven steps ticked](manual-images/workbench-06-finished-card-all-six-stages-done-back-w.jpg)

*All steps ticked: "Back with Cloud. The evidence is in the Cloud session."*

![The Cloud session page that opens after the return, with the stage rail and the session's messages](manual-images/workbench-07-the-cloud-session-page-that-opens-after-.jpg)

*The page that opens next: the same Cloud session, with its stages and messages.*

**For QA and UAT testers.** You use exactly the same screen. Pick the ticket from **Ready for QA** or **Ready for UAT**, and Argus checks out the PR the developer tested. Your run gets its own evidence zip, tied to the commit you tested.

### 6. Keep talking to Cloud while you test

The test runs inside Argus program, not in the page. You can move around Argus and the test carries on.

#### 6.1 Chat in the right column

On Test on my PC, the right column is a chat with Cloud. Use **Talk to** to pick the ticket's Cloud session, a chat you've already started, or **New chat with Devin**. A new chat is a plain chat: it answers you, and it doesn't commit, push, open a PR or write to Jira or Confluence unless you ask it to.

![Test on my PC with the This PC card, a ticket's test card with evidence history and wrap-up, and the chat panel on the right](manual-images/workbench-08-test-on-my-pc-with-the-this-pc-card-a-ti.jpg)

*Test on my PC with a finished ticket: the evidence history, the wrap-up, and the chat on the right.*

#### 6.2 Devin Local needs you, on every page

While you're on another page, Argus checks the test every 5 seconds. If Devin Local is waiting for an answer or a permission, an orange **Devin Local needs you** button shows in the top bar. Click it to go back.

![Top bar with the orange Devin Local needs you button, while a Jira ticket page is open](manual-images/workbench-09-top-bar-with-the-orange-devin-local-need.jpg)

*On a ticket page. The "Argus" title hides while the button shows, to keep the bar on one line.*

#### 6.3 Back to Cloud from any page

When Return to Cloud finishes, Argus opens the Cloud session, whatever page you're on. If you're halfway through typing, it doesn't take the page away from you. It shows **Back with Cloud: ACME-…** in the top bar instead.

![Top bar with a Back with Cloud: ACME-17735 button](manual-images/workbench-10-top-bar-with-a-back-with-cloud-acme-1773.jpg)

*The test came back while there was text in the New requirement box, so the jump waits for a click.*

#### 6.4 Desktop pop-ups

Turn them on under **your name ▾ → Desktop notifications**. While the page is in the background, Windows pops up a note when Devin Local needs you, when Devin Cloud replies, when an Argus update is ready, and when a new Jira sub-task is assigned to you. Click the pop-up to go to the right page.

### 7. Evidence: history and Post to Jira

Each test run makes one evidence zip, and Cloud can check it without taking the PC's word for anything:

- It's tied to one commit. Argus checks the PR is still at that commit when it opens, seals and sends the run.
- Cloud checks the file hashes, the commit and every result before it writes the test report.
- Every result is **passed**, **failed** or **not run**. A check that couldn't run, because something it needs is missing, is recorded as not run with the reason. It's never recorded as passed.
- Logs and notes are cleaned of the values of `ARTIFACTORY_TOKEN`, `DEVIN_API_KEY` and the Jira service account's password before they go in the zip.

#### 7.1 Evidence history

Once Argus has found a ticket's Cloud session, the test card has an **Evidence history** button. It lists every evidence message sent to that session, from any PC: when, who tested on which PC, the commit, the passed, failed and not-run counts, and a link to the zip.

#### 7.2 Post to Jira

1. Press **Post to Jira** on a history row and confirm.
2. Argus asks the ticket's Cloud session to add exactly one comment to the Jira ticket. The comment gives the counts, the story, who tested and on which PC, when, the commit and the link to the zip. It's posted by the team's Jira service account, `ACME_JIRA_TOKEN`.
3. The row shows "asked Cloud to post to ACME-n", and then a link to the comment once it's posted. That status is read from the session itself, so nobody can post the same run twice, from any PC.

#### 7.3 Where the evidence lives

**evidence.py commands**

| Command | Run by | What it does |
|---|---|---|
| `start PACK` | Argus | Checks the commit and opens the run under `~/.sdlc/evidence/{REQ}-{STORY}/{commit}/`. |
| `run PACK` | Devin Local | Runs the automatic checks, with the logs cleaned. |
| `mark PACK AC-n …` | Devin Local | Records your answer for one acceptance criterion, with a note and an optional screenshot. |
| `pack`, `send`, `control` | Argus | Seals the zip, sends it to the session, and passes control. |
| `verify ZIP --commit SHA` | Cloud | Checks the zip before the test report is written. |


#### 16.1 Who holds the branch

Only one side works on the PR branch at a time. Control is passed as plain messages in the Cloud session, so anyone can read later who had the branch and when. While your PC has control, Cloud doesn't push to the branch, but you can still chat with it.

**Messages Argus and Cloud exchange**

| When | Message (first line) | What happens |
|---|---|---|
| Test on my PC | `[SDLC] control pc <commit>` | Cloud keeps off the branch until control comes back. |
| Return to Cloud | `[SDLC] evidence REQ STORY <commit> passed=n failed=n not_run=n`, with the zip | Cloud runs `evidence.py verify` against the PR head. The evidence history is read from these messages. |
| Return to Cloud | `[SDLC] control cloud` | Cloud takes the branch back: fixes, test report, PR. |
| Post to Jira | Cloud answers `[SDLC] jira-comment ACME-n <link>` | The history row shows the comment link. |
| Wrap-up check | `[SDLC] wrap-up-check ACME-n`; Cloud answers `[SDLC] wrap-up ACME-n ready\|not-ready <reason>` and `[SDLC] jira-next ACME-n id=Status\|…` | The wrap-up box shows the result and the Jira buttons. |
| Jira move | `[SDLC] jira-move ACME-n <id>`; Cloud answers `[SDLC] jira-moved ACME-n <status>` | The box shows "moved to …" and offers the session choices. |
| Answer, approve or reject a sub-task | Cloud answers `[SDLC] task-reply ACME-n done` | The Approvals row shows answered, approved or rejected. |


#### Argus handoff work

The Cloud → PC → Cloud handoff in this manual took 25 PRs, #2756 to #2776 and #2779 to #2782, between 1 and 4 October. They added 5,557 lines and removed 266. About 3,500 of those lines are code and 1,400 are tests.

---


## How Test on my PC runs for each person

The **Argus config** tab on the Tech Lead dashboard, next to Gate config, has one row per person and a team
default, from `.devin/rules/workbench-settings.yaml`. Each person's Test on my PC runs one of four ways:

- **Local Hands from Devin Cloud:** your Devin Cloud Argus session asks for your PC (a `devin connect <code>`
  card), then runs the test pack there; you approve each step on the PC. No API key on the PC. The org's Local
  Hands setting must be on.
- **Devin Local on the PC:** Argus on your PC starts Devin Local (`devin acp`). Needs the Devin API key on
  the PC.
- **Devin Cloud VM:** the test pack runs on the Cloud VM; nothing runs on your PC.
- **Off:** Test on my PC is hidden.

Pick a choice, press **Preview change**, then **Save**. After you say approved, the run raises a pull request on
workbench-settings.yaml.

