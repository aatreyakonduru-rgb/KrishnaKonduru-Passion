---
name: approve
description: Sign the gate that is waiting on you — or send it back — without knowing gate IDs. "/approve REQ-001" shows the open gate's brief (what is being asked, the artefacts, the numbered items) and waits for the word "approved" or "rejected <reasons>". Records who signed, when, and whether it was a self-sign in dev mode. Also the place to say "send this to <person>" instead. For BSAs, POs, tech leads, QA and anyone else named on a gate.
argument-hint: "REQ-ID [STORY-n] [approved | rejected <reasons> | send to <person> \"<note>\"]"
visibility: public
triggers:
  - user
  - model
invocations:
  - /approve
  - approve REQ
  - sign the gate
  - I approve
  - reject this
allowed-tools:
  - read
  - bash
---

# /approve — sign or send back the gate that is waiting

## STEP 1 — Find the open gate

```bash
python3 sdlc/framework/tools/gates.py next REQ-ID --json
```

`state: waiting` gives you `gate` and `story`. Anything else: report the message it returns (nothing
to sign, or the requirement is not the requester's) and stop.

## STEP 2 — Show the brief, exactly as the gate rule says

Follow `.devin/rules/gate-presentation.md`: gate ID and name, requirement and story, the artefacts
with links, the criteria checklist, what a rejection blocks, the numbered decision items, and the
four options (approve / reject with reasons / approve with notes / send to someone else). If the
gate was already presented, re-read the record under the session directory
(`gates.py status REQ-ID`) rather than rebuilding it, and re-show it.

Then wait. Do not fill in the answer.

## STEP 3 — Record the reply

Only a reply that starts with `approved` or `rejected` counts. `ok`, `yes`, `looks good`,
`approve` do not — say the gate is still open and repeat the options.

```bash
python3 sdlc/framework/tools/gates.py decide <GATE> REQ-ID [--story STORY-n] \
    --by "<requester's roster name>" --reply "<their reply verbatim>" [--items 1,3] [--note "..."]
```

Exit `0` = recorded. Exit `4` = this person does not hold the gate's role. In `dev` mode
(`.devin/config.json` → `gates.mode`) the session owner may sign anyway and the record says
`self_signed: true`; tell them that is what happened. In `enforced` mode offer
`/send-approval <GATE> to <person>` instead.

"Send to <person> with note" → hand off to `/send-approval`; the note is mandatory.

## STEP 4 — Say what changed

```
Recorded:  SDLC_05_CODE_REVIEW for REQ-001 STORY-2 — approved by <name> at <time>[ (self-signed, dev mode)]
Next:      /eval REQ-001 STORY-2
Who:       the person running the session
```

For a rejection, `Next` is the stage to rerun and `Who` is the person running the session, with the
reasons quoted back.
