# Playbook: Promote — Raise the PRs to Move Code to the Next Environment

**Playbook ID:** PB-35  
**Paste into:** Devin Cloud → Settings → Playbooks → New Playbook  
**CLI equivalent:** `/promote` skill (`.devin/skills/promote/SKILL.md`)  
**When to use:** When a change is ready to move to the next environment (ours: dev → sit → uat → prod). For an environment with a gate (ours: uat and prod), after that gate (SDLC_07_ENV_PROMOTION_APPROVAL) is signed.
**Settings:** environments, order, branches and gates are `workflow.environments` in `.devin/rules/sdlc-profile.json`; the deploy repo is `repo.deploy_slug`. `promote_check.py --list` prints them.

---

## Title
```
Acme Claims: Promote — raise the promotion PRs, never merge
```

## Description
```
Reads ACME/claims-deploy to show what each environment runs,
what would go out and which config keys the target is missing. Raises the app
PR into the next environment's branch and, if needed, a deploy-repo PR for
values-<env>.yaml. After a person merges, waits for Tekton to write the new
image tag. For prod, hands the Tekton tag-update PR to the Release Manager.
Never merges, never pushes to an environment branch.
```

## Playbook Body

---

Run `/promote {from} {to} [services] [REQ-ID STORY-ID]` and follow `.devin/skills/promote/SKILL.md`
step by step.

1. Run `python3 sdlc/framework/tools/promote_check.py --list`; {from} → {to} must be the next step in the order.
2. Check the gate the target's settings name (ours: uat and prod need SDLC_07_ENV_PROMOTION_APPROVAL signed).
3. Run `python3 sdlc/framework/tools/promote_check.py --from {from} --to {to}` and show the result.
4. Ask which branch carries the change, then raise the app PR into the target branch.
5. If config keys are missing, ask the owner for each value and raise the deploy-repo PR.
6. After a person merges, wait for the Tekton tag with `promote_check.py --wait-for`.
7. For a target with a `tag_branch` (ours: prod), find the PR from that branch and send it to the Release Manager.

## Forbidden actions
- Merging any PR, or pushing to any environment branch in `workflow.environments` (ours: `develop`, `sit`, `uat`, `preprod`, `master`, `dr`).
- Editing `tekton-values-*.yaml` by hand.
- Copying a config or secret value between environments, or committing a secret value.
- Promoting to an environment marked `verified: false` (ours: preprod, dr) before DataLake DevOps confirms how it deploys.
