---
name: start
description: The front door for anyone who has something they need from the Acme Claims product and does not want to learn the pipeline. Say "/start" with a sentence about what you need, in plain English; the skill works out who you are, what kind of ask it is (new requirement, idea to size, question, change-impact check, story review) and hands it to the right stage, then tells you where it is, what happens next and who has to act. Use it instead of remembering /intake, /feasibility-check, /investigate and friends.
argument-hint: "\"<What I need / Where / Done when>\"  |  <REQ-ID> to pick one up  |  <ACME-1234> to start from a Jira ticket"
visibility: public
triggers:
  - user
  - model
invocations:
  - /start
  - I need
  - I want to
  - can we build
  - how do I start
  - new requirement
allowed-tools:
  - read
  - glob
  - grep
  - bash
---

# /start — say what you need; we route it

Nobody has to know the stage names to use this framework. This skill takes a sentence and picks
the right path. It is the recommended first command for BSAs, POs, finance partners and anyone new.

## STEP 0 — Is there an ask

If the message is only a greeting, or names no task, do not guess. Reply with this starter and wait:

```
What I need:  <one sentence>
Where:        <screen, report, table, Jira ticket or REQ-ID>
Done when:    <what you will see when it is finished>
```

When the message has a task but leaves out Where or Done when, carry on and ask for the missing line in your
first reply.

## STEP 1 — Who is asking

Run `/identify-requester` silently. You need the person's roster entry (`.devin/rules/people.yaml`)
and the hat that fits this ask. If the person is not on the roster, continue as `guest` and say
once: "I am continuing with you as a guest. You can do all read-only lookups; for more than that, talk to the solution lead."
Guests get read-only paths only (questions, impact checks, feasibility); nothing that creates a
requirement. Do not ask for their role or offer a roster pull request.

## STEP 2 — What kind of ask is it

Run `python3 sdlc/framework/tools/ontology_lookup.py find "<the sentence>"` first. When it names a business object, screen or
table, say so in the answer ("this is about Provider Group, the `/contractproviderconf` screens")
and pass the names on to the routed skill. Print `[SDLC] ontology <command> <term> — <found>; why: <why>; gain: <gain>` for each lookup (`.devin/rules/workbench-trace.md`). Then read the sentence and classify it. Do not ask the user to classify it for you; if it is genuinely
ambiguous, ask one question with two options.

| The ask sounds like | Route to | What the person gets back |
|---|---|---|
| "We need the screen to…", "add a report…", "change the rule so…" | `/intake "<sentence>"` | a requirement (REQ-ID), the clarifying questions, then the first gate for BSA sign-off |
| "Is it feasible…", "how big is…", "before we commit…" | `/feasibility-check "<sentence>"` | a five-minute T-shirt sizing and the risks, no requirement opened |
| "What does Acme Claims do when…", "who can…", "what is…" | `/explain` | a sourced plain-English answer |
| "What breaks if we change…", "is it safe to…" | `/impact` | the impact report |
| "Here are my meeting notes…" | `/intake notes "<notes>"` | a spec draft plus the questions still open |
| a Jira key `ACME-1234` | `/intake ACME-1234` | the ticket expanded into a requirement |
| a requirement id `REQ-…` | `/status REQ-…` then `/resume-session REQ-…` | where it is and the next stage |
| "do the stories cover…" | `/po-story-review <REQ-ID>` | the coverage review |

Guests may only take the `/explain`, `/impact` and `/feasibility-check` rows.

## STEP 3 — Run it and hand back a plain answer

Run the routed skill. Whatever it produces, close with exactly these three lines so the person
never has to ask "and now what?":

```
Where it is:  <REQ-ID or "no requirement opened"> — <stage or "answered">
Next:         <the one thing that happens next>
Who:          <named person or role that has to act; "you" if it is the requester>
```

If a gate was presented, add: "Reply `approved`, `rejected` or `needs revision` — or type
`/approve <REQ-ID>` — and nothing moves until you do." In dev mode (`.devin/config.json` →
`gates.mode`) also say the requester may sign it themselves.

## Rules

- Never open a requirement for a question. Never answer a requirement with a chat reply.
- Never invent a REQ-ID or Jira key; the routed skill creates them.
- Snowflake and Artifactory are not available in Devin Cloud yet; if the routed path would need
  them, say which step is deferred rather than pretending it ran.
