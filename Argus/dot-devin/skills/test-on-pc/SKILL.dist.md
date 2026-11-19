---
name: test-on-pc
description: >
  The PC side of Cloud-to-PC testing. Run in Devin Local on the developer's own laptop, in a
  checkout of the PR commit: reads the story's test pack, sets up the environment from the
  tester's own saved values, runs the automated checks, walks the tester through each
  acceptance criterion in the browser, and sends one scrubbed evidence zip back to the same
  Cloud session (and optionally the Jira story). Every result is passed, failed or not run, and
  labelled "ran on PC". Does not sign SDLC_06.
  Invoke with: /test-on-pc <REQ-ID> <STORY-ID>  ·  /test-on-pc <path to test pack>
argument-hint: "<REQ-ID> <STORY-ID>  e.g. REQ-TIN-001 STORY-003"
visibility: internal
triggers:
  - user
  - model
invocations:
  - /test-on-pc
  - test this on my PC
  - test on my laptop
allowed-tools:
  - bash
  - read
---

# /test-on-pc — test the PR on the developer's PC and send the evidence back

Cloud writes the code and the test pack. The PC runs the app against DEV, where the developer has
network, SSO, Artifactory and test-data access, and Snowflake signs in with the developer's own ID
through Okta, as today. On a Devin Cloud VM the app uses the service account instead (see
"Snowflake Connection Identity" in `.devin/rules/data-access.md`). This skill is the PC half. Cloud's half is
`/eval` (`.devin/skills/eval/SKILL.md`, STEP 3b).

The tool is `sdlc/framework/tools/evidence.py`. The pack format is
`.devin/templates/test-pack.yaml`. Runs are kept outside the repo, under
`~/.sdlc/evidence/{REQ_ID}-{STORY_ID}/{commit}/`.

`PACK` below is `sdlc/framework/context/test-packs/{REQ_ID}-{STORY_ID}.yaml`, unless
the user gives a path.

## Started by Argus

Usually the tester presses **Test on my PC** in Argus (`console/pctest.py`) and never types
this command. Argus makes the ticket folder, clones or fetches, checks out the PR branch,
finds the pack in `sdlc/framework/context/test-packs/`, runs `start` and `control pc`, then
starts Devin Local over ACP with this skill and a note saying STEP 0 to STEP 2 are done. In that
case start at STEP 3, stop after STEP 6, and end with the words "Ready to return to Cloud". Do not
run `pack`, `send` or `control` yourself: `.devin/config.json` denies them, and the tester's
**Return to Cloud** button does STEP 7. Devin Local gets no Devin API key in that mode.

## STEP 0 — Right place

This runs on the developer's PC, in Devin Local. If you are in a Devin Cloud session, stop:
> "/test-on-pc runs on your PC. In Cloud, /eval writes the test pack instead."

The checkout must be at the PR head: the pack's `commit`, or the commit that adds the pack on
top of it. Get there one of these ways:
- Devin's own transfer: `devin --cloud --resume <session URL>`, then `/pickup`. This switches the
  current checkout to the PR branch, so use a spare clone or commit/stash first.
- A separate folder, so the developer's own checkout is not touched:
  `git fetch origin <branch>` then `git worktree add ../claims-test-<STORY_ID> origin/<branch>`.
  Ask before creating it.

## STEP 1 — Open the run

```bash
python3 sdlc/framework/tools/evidence.py start PACK
```

The commands below say `python3`. On Windows, where `python3` is often missing, use `py -3`.
Checks in the pack that call `python3` run with whichever Python started `evidence.py`.

It refuses if HEAD is not the pack's commit, or that commit plus test-pack-only commits. Do not
work around that. If the PR has moved on,
Cloud needs to write a new pack for the new head.

## STEP 2 — Take control

Tell the Cloud session the PC has control, so Cloud does not push while you test. Show the
message first (dry run), then send it with the developer's OK:

```bash
python3 sdlc/framework/tools/evidence.py control pc PACK            # dry run
python3 sdlc/framework/tools/evidence.py control pc PACK --live     # needs DEVIN_API_KEY
```

If `DEVIN_API_KEY` is not set on the PC, say so and carry on. The commit check in STEP 7 still
catches a push made while the PC was testing.

## STEP 3 — Environment

For each `setup.env_files` entry, check that the tester's file has every key **name** in the
list. Never print, invent or commit the values. `web/.env.local` is git-ignored
(`web/.gitignore`: `.env*.local`). List any missing names and ask the tester to add them.

Check each item in `setup.needs` (Artifactory login, DEV API, SSO). For anything that is not
available, say which pack items it blocks. Those items stay "not run".

## STEP 4 — Automated checks

```bash
python3 sdlc/framework/tools/evidence.py run PACK
```

It runs each `checks` entry, keeps a scrubbed log per check, and records passed, failed or not
run. A check whose `needs_env` is missing, or `/build-check`'s exit 5 (no Artifactory
credential), is "not run", never "passed". Show the table it prints. For a failure, open its log
and quote the first real error.

## STEP 5 — Acceptance criteria, in the browser

Start the app with the pack's `setup.start` commands and open each `where` URL. Then, for each
`acceptance` item, one at a time:
1. Show the criterion, the steps, the expected result and the test data to use.
2. Ask the tester what they saw: passed, failed or not run, plus a short note.
3. Record their answer. `mark` takes `passed`, `failed` or `not-run` (with a hyphen):

```bash
python3 sdlc/framework/tools/evidence.py mark PACK AC-1 passed --note "Grid shows LOCATION_CD"
python3 sdlc/framework/tools/evidence.py mark PACK AC-3 not-run --note "No SIT login on this PC"
python3 sdlc/framework/tools/evidence.py mark PACK AC-2 failed --note "Filter ignores blanks" \
  --screenshot C:/Users/me/ac2.png --no-member-data
```

Only the tester's answer sets a manual result. If you looked at the screen yourself, say so in
the note, and still ask the tester to confirm. Before attaching a screenshot, ask the tester to
check that it shows no member names, real IDs or other member data. Only then pass
`--no-member-data`. If they can't confirm it, leave the screenshot out.

## STEP 6 — Fixes found while testing

Fixes go back to Cloud by default. Record the failure, finish the run, and let Cloud fix it on
the PR branch and write a new pack.

If the developer fixes something here anyway, it must be committed and pushed to the PR branch
before control goes back. That fix is a new commit, so this run's evidence is still only for the
old commit. Say that plainly, and ask Cloud for a new pack to re-test.

## STEP 7 — Pack and send

```bash
python3 sdlc/framework/tools/evidence.py pack PACK
python3 sdlc/framework/tools/evidence.py send PACK                        # dry run
python3 sdlc/framework/tools/evidence.py send PACK --live [--jira ACME-n]
python3 sdlc/framework/tools/evidence.py control cloud PACK --live
```

`pack` refuses when tracked files have uncommitted changes, when HEAD moved, or when the PR
branch on origin is no longer the tested commit. `--skip-remote-check` exists for a PC that
can't reach Bitbucket. The manifest then says so, and Cloud sees it.

`send` uploads the zip to the Cloud session and posts the `[SDLC] evidence` line. `--jira` also
attaches the zip to the story and needs `ACME_JIRA_TOKEN` on the PC. Ask before every
`--live`.

## STEP 8 — Report

```
Tested {REQ_ID} {STORY_ID} at {commit} on this PC.
{evidence.py status table}
Sent to {Cloud session}. Cloud writes the test report next; QA signs SDLC_06.
Not run: {items and why}
```

## HARD RULES

- Never mark anything passed that did not run on this PC, at this commit.
- "not run" is a result. Never drop an item or leave it out of the report.
- Never print, log, upload or commit secrets, `.env.local`, tokens, cookies or member data.
- Never sign SDLC_06 or any other gate. A person in the QA role signs it, from Cloud's report.
- Never send evidence for a commit other than the PR head.
- Don't push to the PR branch while Cloud has control, or Cloud while the PC has it.

## Known gaps

- Whether QA accepts PC evidence for SDLC_06, or only SIT runs, is not settled (QA lead).
- Whether the DEV API and SSO work from localhost on our PCs is not known (platform team).
- Whether the tester's own git login can read the Bitbucket projects in a pack's `setup.repos` is
  only found out when Argus clones them.
- Whether `/pickup` brings over the Cloud conversation, or only the code, is not known. The pack
  carries what the PC needs either way.
