# Acme Claims on Devin Cloud: a guide for Product Owners, BSAs and Scrum Masters

## One-hour session

A one-hour, follow-along introduction. Keep this page open on one side of the screen and a Devin Cloud session on the other. Each tab has a **Try it now** box: paste the text into your own session and check what comes back. Everything here only reads, or shows a preview, so nothing changes in Jira during the session.

### 1. Welcome (5 min)

Devin Cloud does the legwork in Jira, Confluence and the team's documents: it reads the backlog, drafts epics and stories, checks tickets against the Jira rule book, builds the dashboard for your role and answers questions about the application with its sources. Product Owners, BSAs and Scrum Masters keep the decisions: nothing reaches Jira or the knowledge base until you reply **approved**.

| Role | What Devin Cloud helps with |
|---|---|
| Product Owner | Roadmap and epics, story review, grooming, demos, what-if questions |
| BSA | New requirements, BRD and FRD review, open questions, compliance view |
| Scrum Master | Stand-up gaps, sprint close, commitment against capacity, leave, sprint review |

### 2. Your first session (5 min)

1. Open Devin Cloud and select **New session**. Everything is already set up.
2. Devin knows who you are from the team roster, so you never type your name.
3. There are three ways to ask: a slash command (`/dashboard`), a plain sentence ("which stories in the next sprint have no points?"), or `/start` followed by what you need.

> **Try it now.** Type `/whoami`.
> You should see your name and your role (Product Owner, BSA or Scrum Master). If the role is wrong, say so in the same session.

> **Try it now.** Type `/dashboard`.
> You should get a page attached in the chat with the tabs for your role. Open it and look through your tabs.

### 3. Product Owner commands (15 min)

| Type | What comes back |
|---|---|
| `/roadmap` | The year plan beside the live Jira sprint grid |
| `/epics-from-roadmap` with your sheet attached | One draft epic per row, checked against the rule book, as a preview |
| `/feasibility-check "idea"` | Rough size, top risks and the next step, in plain English |
| `/what-if "change"` | Who is affected and whether it needs a sprint or only configuration |
| `/po-story-review REQ-ID` | Which acceptance criteria have no story and which stories need grooming or splitting |
| `/jira-hygiene` | Tickets that don't meet the rule book yet, with the owner |
| `/defects-by-specialty` | Open SIT and UAT defects per specialty |
| `/pi-plan "REQ-001 REQ-002"` | A PI board with sprint assignments and dependencies |
| `/release-notes all` | An executive summary and a change log |

> **Try it now.** Type `/jira-hygiene`.
> You should see the team's tickets grouped by what is missing. Pick one of yours and ask "what exactly is wrong with ACME-nnnn?".

> **Try it now.** Type `/feasibility-check "Let approvers see the contract history on the review screen"`.
> You should get a T-shirt size, the risks and a suggested next step.

### 4. BSA commands (15 min)

| Type | What comes back |
|---|---|
| `/intake "requirement"` | Numbered questions, then a spec with acceptance criteria for you to sign |
| `/intake ACME-1234` | The same, starting from an existing ticket |
| `/document-validation` | The open questions in the knowledge base as one form to answer |
| `/compliance-view HIPAA` | Which features touch protected health information |
| `/explain-capability "question"` | A sourced, plain-English answer about what the application does |
| `/ask-question` | Sends a question to a named person as a Jira Question sub-task |
| `/status REQ-ID` | Where a requirement is, the next step and who has to act |

> **Try it now.** Type `/explain-capability "What happens when a contract is approved?"`.
> You should get a plain-English answer with where it came from.

> **Try it now.** Type `/compliance-view HIPAA`.
> You should see a map of the features that handle protected health information.

### 5. Scrum Master commands (15 min)

| Type | What comes back |
|---|---|
| `/dashboard scrum_master` | Stand-up check, sprint close, commitment, leave, cycle time, defect removal, cost and AI use |
| `/sprint-close-check` | Every story and sub-task not ready for the sprint to close, with what is missing and who owns it |
| `/sprint-review-summary` | Planned, delivered, deferred, risks and what's next, ready for the review |
| `/vacation` | Everyone's time off and who covers their stories, questions and approvals |
| `/status-report` | The monthly status report from Jira |

> **Try it now.** Type `/sprint-close-check`.
> You should see one row per story or sub-task that is not ready, with its owner.

> **Try it now.** Type `/vacation`.
> You should see the team's time off from today. To add your own, type "I am off on <date>" and check the preview; it is saved only after you type approved.

### 6. Try things safely (10 min)

- **Previews first.** Every change to Jira, Confluence or the knowledge base is shown as a preview. It happens only after you type **approved**. Type **rejected** and say why to send it back.
- **Dry runs.** Anything that would create tickets can run as a dry run: you get the epics and stories as a file and nothing is written.
- **Your own work only.** Devin acts on the tickets and documents your role covers. It tells you when something belongs to someone else.
- **Stop any time.** Type "stop" or close the session; a session that goes to sleep does no harm.

> **Try it now.** Type `/epics-from-roadmap` and attach a small roadmap sheet, or type "draft an epic for: approvers can see contract history".
> You should see a preview. Reply "rejected, this is a test" and check that nothing was created.

### 7. Get help (5 min)

| Type | When |
|---|---|
| `/help` | Every command for your role, grouped by what you are trying to do |
| `/explain-capability "question"` | What a feature does, in plain English |
| `/status` | Where your most recent requirement is |
| `/start "what you need"` | When you don't know which command to use |
| A plain question | Anything else. Devin says when it doesn't know rather than guessing |

> **Try it now.** Type `/help`.
> You should see your role's commands first.

### 8. Teach Devin (5 min)

Devin keeps a short list of questions only you can answer: how you work, what a term means, who to ask. In each session it asks one at the end of its first reply. Your answer is shown as a change to the knowledge base and saved after you type **approved**.

- `/learn-more` answers your open questions now.
- `/learn-more add <person> <question>` queues a question for someone else.
- If Devin gets something wrong, say so in plain words ("that's not how we schedule SIT stories"). It shows the correction and saves it after you approve.

> **Try it now.** Type `/learn-more`.
> You should see your open questions, one at a time.

### 9. Argus (5 min)

Argus puts every task for your role on one screen: a **What I do** list on the left, and a screen with buttons for each task. Every change is still shown as a preview first.

![Argus for a Product Owner](../manual-images/wb-po.jpg)

**Product Owner.** Plan, Groom, Sprint, Demo and release, Mine. **Grooming prep** gets the next grooming call ready: roadmap items with no story, stories not ready to groom, missing SIT and UAT stories, who to invite, and a draft agenda.

![Argus for a BSA](../manual-images/wb-bsa.jpg)

**BSA.** Shape, Groom, Answer, Mine. A new requirement, the BRD and FRD reviews, and questions waiting on the business, all from buttons.

![Argus for a Scrum Master](../manual-images/wb-sm.jpg)

**Scrum Master.** Daily, Sprint, Health, Mine. Stand-up check, plan the sprint, time off and sprint close in one place.

Everything on this page also works in Devin Cloud, typed as a slash command.
