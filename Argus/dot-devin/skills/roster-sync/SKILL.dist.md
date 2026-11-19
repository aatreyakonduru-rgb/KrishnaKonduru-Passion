---
name: roster-sync
description: Keep .devin/rules/people.yaml in step with the Confluence page "Acme Claims Team Roster" (space ACMEWIKI, page 100002), which is the human-edited source of truth signed off by the roster owner. Detects when the page version has moved on, pulls the page into people.yaml (keeping local-only fields such as devin_user_id and role_hints), and can publish the local roster back to the page. Say "/roster-sync" or "is the roster page up to date". The tech lead runs it by hand whenever the roster page changes; it is not scheduled.
argument-hint: "check | verify | pull [--write] | publish [--live] | render"
visibility: internal
triggers:
  - user
  - model
invocations:
  - /roster-sync
  - sync the roster from confluence
  - is the roster page up to date
allowed-tools:
  - read
  - bash
---

# /roster-sync — the Confluence page is the roster; people.yaml is its copy

Who is on the team, which gate roles they hold and who owns the roster is decided by people, on a
Confluence page the owner (Resource 1 — `owner.primary` in `people.yaml`) signs off. The
repository keeps a machine-readable copy so sessions can route work without asking Confluence every
time. This skill keeps the two in step.

## STEP 1 — Is the copy stale?

```bash
python3 sdlc/framework/tools/roster_sync.py check
```

Exit `0` = in sync, `1` = the page moved on (prints old and new version), `2` = error. Confluence
uses `ACME_CONFLUENCE_TOKEN` (bearer only). On 401/403 stop and report — never retry.

`check` only compares the page version and sign-off. `verify` compares everything that grants
something — people, gate roles, delegates, owner and backups, sign-off, default role and the Access
table — and exits `1` on any difference:

```bash
python3 sdlc/framework/tools/roster_sync.py verify
```

The write guard and `gates.py` run the same check (through `tools/access_guard.py`, cached for 15
minutes per `people.yaml` content) and block guarded writes and gate sign-offs while it fails or
Confluence cannot be read. They also block while the roster sign-off is not one that
`access.roster_signoff` accepts for the current `gates.mode` (`enforced`): the owner's or a
backup's (interim) sign-off in `dev`, and a backup's (interim) sign-off or a signer who holds the
`manager` or `reviewer` gate role in `enforced`. A pending roster unlocks nothing, even when it matches the page.

## STEP 2 — Pull the page into people.yaml

```bash
python3 sdlc/framework/tools/roster_sync.py pull            # show the diff
python3 sdlc/framework/tools/roster_sync.py pull --write    # regenerate people.yaml
```

Page-controlled fields (name, email, gate roles, primary/secondary role, allocation, delivery,
delegate_to, owner block, sign-off, the Access table) come from the page. While the page has no
Access table yet, the local `access:` section is kept and `verify` fails until it is published. Local-only fields (`devin_user_id`,
`role_hints`) are carried forward. `source:` in `people.yaml` records page id, version and the
owner sign-off status, so the next `check` knows what it is comparing against.

Sign-off is read two ways and the stronger one wins: the *Signed by / Signed on* rows of the
ownership table, or a page comment that starts with `approved` or `approve`. Who wrote it decides the
status — the owner (`owner.primary`) gives `signed`, a backup gives `interim`, anyone else is
ignored. Looser than the gates (which take `approved` only): `ok`, `looks good` do not count. A sign-off
holds only for the page as it was signed: the *Signed by* rows count only when the signer made the
latest edit, and a comment only when it was written after the latest edit. Any later edit, a publish
included, puts the roster back to pending until the owner signs again. `check` exits 1
when the page's sign-off differs from `people.yaml` even if the page version is unchanged (comments
do not bump the version).

Then run `python3 sdlc/framework/tools/reconcile_roster.py --offline` and commit the
result on a branch with `Work-ID: UNTRACKED` — roster changes always land through a pull request.

## STEP 3 — Publish local edits to the page (rare)

```bash
python3 sdlc/framework/tools/roster_sync.py publish          # dry run: shows the storage HTML
python3 sdlc/framework/tools/roster_sync.py publish --live   # updates the page
```

Only for bootstrapping or when the owner asks for the YAML to win. Publish writes the sign-off rows
as pending, and earlier `approved` comments no longer count, so gate sign-offs and guarded writes
stay blocked until the owner signs the new version and the tech lead runs `pull --write`. Say so in
the report.

## Running it

The tech lead runs `/roster-sync` by hand after the roster page changes; it is not scheduled. It runs
`check` and, when the page or its sign-off has moved, `pull --write`, then commits `people.yaml`
straight to `feature/devin-sdlc` with `Work-ID: UNTRACKED`. No PR review is needed: the owner
already approved the content on the Confluence page, and that page is the source of truth. If the
push is rejected by branch permissions it falls back to opening a pull request. It never publishes.

After the commit it runs `confirm --commit <sha> --live`, which leaves a comment on the roster page
("Roster sign-off recorded: signed by <owner> on <date>, committed as <sha> on <branch>") so the
signer can see the framework picked it up. `confirm` is dry-run without `--live`, does nothing when
`people.yaml` still says pending, and does not post twice for the same commit.
