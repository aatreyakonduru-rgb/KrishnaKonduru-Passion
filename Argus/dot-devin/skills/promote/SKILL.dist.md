---
name: promote
description: >
  Move Acme Claims code from one environment to the next (dev → sit → uat → prod) by raising the
  pull requests and checking the result — never by merging. Reads the deploy repo
  (ACME/claims-deploy) to show what each environment runs now, what would go
  out, and which config keys the target is missing; raises the app PR into the next
  environment's branch and, when config is missing, a deploy-repo PR for values-<env>.yaml;
  after a person merges, waits for Tekton to write the new image tag. For prod it finds the
  Tekton tag-update PR and hands it to the Release Manager.
  Invoke with: /promote <from> <to> [service ...] [REQ-ID STORY-ID]
argument-hint: "<from> <to> [web|api|web-admin|web-portal|api-portal ...] [REQ-ID STORY-ID]"
visibility: internal
triggers:
  - user
  - model
invocations:
  - /promote
  - promote to sit
  - promote to uat
  - promote to prod
  - move this to the next environment
allowed-tools:
  - bash
  - read
  - edit
  - git_create_pr
  - git_view_pr
---

# /promote — raise the promotion PRs, check the result, never merge

The environments, their order, their branches, the gate before each one and where the
pipeline writes the image tag are settings: `workflow.environments` in
`.devin/rules/sdlc-profile.json`, with the deploy repo in `repo.deploy_slug` and the services in
`repo.services`. Print what this team has set with:

```bash
python3 sdlc/framework/tools/promote_check.py --list
```

Promotion here is two separate things, and this skill handles both
(`docs/knowledge-base/DEPLOY-DERIVED/02_ENVIRONMENT_PROMOTION.md`):

- **Code.** Merging into the next environment's app branch makes Tekton build a new image and
  write its commit SHA into `tekton-values-<env>.yaml` on the same-named deploy branch.
- **Config.** New env vars or secrets go into `values-<env>.yaml` in the deploy repo, by a
  separate PR. The build does not do this.

Our settings today (the `--list` output is the source; this table is a reading aid):

| Environment | App branch | Deploy branch | Tekton writes the tag |
|---|---|---|---|
| dev | `develop` | `develop` | directly |
| sit | `sit` | `sit` | directly |
| uat | `uat` | `uat` | directly |
| prod | `master` | `master` | to `release-tags/image-tag-update`, merged by a person |
| preprod, dr | unverified | unverified | unknown — refuse until DataLake DevOps confirms |

## Hard rules

- Never merge a PR, never push to `develop`, `sit`, `uat`, `preprod`, `master` or `dr` in
  either repo, and never edit `tekton-values-*.yaml` by hand — Tekton owns those files.
- Never copy a config value from one environment into another, and never write a secret value
  into the deploy repo. Ask the owner for each value.
- Follow the Work ID rule for every branch, commit and PR. Ask for the Jira key if there is none.
- If a fact is not in the report or the repos, say so and ask. Do not guess branch names,
  hosts or Argo behaviour.

## STEP 0 — Inputs and gate

Parse `<from> <to>`; they must be adjacent in the promotion order from `--list`
(ours: dev → sit → uat → prod). `promote_check.py` refuses a skip; if the user wants one, ask
before going on and pass `--allow-skip` only once they confirm it was agreed.

- Target with no `gate` in its settings (ours: `sit`, which is QA-controlled per `/release`):
  no gate.
- Target with a `gate` (ours: `uat` and `prod`, SDLC_07_ENV_PROMOTION_APPROVAL): a REQ-ID and
  story are required and that gate must be signed. The report from STEP 1 names it:

```bash
python3 sdlc/framework/tools/gates.py require {gate} {REQ_ID} --story {STORY_ID}
```

Exit 2 means the gate is open: stop and point the user to `/release {REQ_ID} {STORY_ID}` and
`/approve {REQ_ID}`.

Make sure the deploy repo (`repo.deploy_slug`) is cloned (no `/scm/` in the URL):

```bash
[ -d ~/repos/claims-deploy/.git ] || git -c http.sslVerify=false clone \
  https://git.acme.example/ACME/claims-deploy.git ~/repos/claims-deploy
```

## STEP 1 — Read where things stand

```bash
python3 sdlc/framework/tools/promote_check.py --from {from} --to {to} [--service {svc} ...]
```

Show the user, per service: what the target runs now, the commits that would go out, and the
config keys the target is missing. For a target with a `tag_branch` (ours: prod), also list the
unmerged tag updates — if there are any, say so first: they are earlier releases still waiting.

If nothing is pending and no keys are missing, say so and stop.

## STEP 2 — Code PR (app repo)

Ask which branch carries the change. The history shows three patterns: `develop` itself for
dev → sit, a feature branch raised straight into `sit` or `uat`, and a release branch into
`master`. Do not pick one for the user.

Raise one PR with `git_create_pr`: head = that branch, base = the target app branch. The body
lists the commits from STEP 1, the story and Jira key, and says the PR must be merged by a
person. Do not merge.

## STEP 3 — Config PR (deploy repo), only if keys are missing

For each missing key, ask the owner for the target value (for secrets: who provides it and
how — do not put the value in git). Then:

```bash
cd ~/repos/claims-deploy
git checkout -b devin/{JIRA_KEY}-{to}-config origin/{deploy branch}
# edit {service}/values-{to}.yaml: add only the agreed keys under configmap.data
git commit -am "{service}: add {keys} to {to} config" -m "Work-ID: {JIRA_KEY}"
git -c http.sslVerify=false push -u origin HEAD
```

Raise the PR into the target deploy branch with `git_create_pr`. The config PR should merge
before or together with the code PR, or the new code starts without its settings.

## STEP 4 — After a person merges

Get the merge commit on the target app branch, then wait for Tekton:

```bash
python3 sdlc/framework/tools/promote_check.py --to {to} --service {svc} --wait-for {merge commit} --timeout 1800
```

- dev / sit / uat: exit 0 means the tag is written. How Argo then rolls it out is not in the
  repos — tell the user to confirm the pods in the target namespace.
- A target with a `tag_branch` (ours: prod, `release-tags/image-tag-update`): Tekton writes
  the tag there, not to the deploy branch. Find the open PR from that branch into the deploy
  branch and send it to the Release Manager. Do not merge it.
- Timed out: say so, name the service and the tag it still runs, and ask DataLake DevOps to check
  the Tekton pipeline.

## STEP 5 — Report

Three lines: where it is, what happens next, who has to act. Then the PR links. If the target
was prod, remind the user to run `/kb-refresh` once it is live.

## Rollback

Not automated. The earlier image tag is in the deploy branch history
(`git log -- {service}/tekton-values-{env}.yaml`). Restoring it by PR is an option only when
the Release Manager asks for it; whether Tekton would overwrite it on the next build is not
known.
