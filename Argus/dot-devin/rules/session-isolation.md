# Rule: Session Isolation on Shared Branches

Session state is persisted in the repository (`sdlc/framework/context/session/`).
When more than one person works on the same branch, an unscoped session directory means
two people write the same files, and a resumed session can pick up somebody else's work.
Session directories are therefore scoped by owner.

## `{OWNER}` — how to resolve it

`{OWNER}` is a filesystem-safe slug identifying the person who owns the session.

1. Read `git config user.email`.
2. Take the local part (everything before `@`), lowercase it, and replace every run of
   characters outside `[a-z0-9]` with a single `-`. Strip leading and trailing `-`.
   `resource3@acme.example` → `resource3`
3. If `git config user.email` is empty, or the slug comes out empty, ask the user for
   their owner slug once and use the answer.
4. If the session directory being read already records an `owner`, that value wins over
   the derived slug — never rewrite the `owner` of an existing session.

Resolve `{OWNER}` once at the start of a session and reuse it; do not re-derive it per step.

## Session directory layout

```
sdlc/framework/context/session/
├── {OWNER}/
│   └── {REQ_ID}/
│       ├── {REQ_ID}-SPEC.md
│       ├── {REQ_ID}-BACKLOG.md
│       ├── approvals.yaml
│       └── provenance.log
├── REQ-TIN-001/            # legacy, pre-scoping — unowned, shared
└── archive/
```

- **Write** session artefacts only to `context/session/{OWNER}/{REQ_ID}/`.
- **Read** `context/session/{OWNER}/{REQ_ID}/` first. If it does not exist, fall back to
  the unscoped `context/session/{REQ_ID}/` — those are legacy sessions created before
  owner scoping and belong to nobody. Never create new unscoped directories.
- `KB-BASELINE-*` and `archive/` are repository-level, not per-owner; they stay at the
  root of `context/session/`.

## Requirement ID allocation

REQ IDs stay globally unique across owners so they can be referenced in Jira and in
conversation without ambiguity. When allocating a new ID:

1. Scan every `context/session/*/REQ-*` directory **and** the legacy unscoped
   `context/session/REQ-*` directories.
2. Take the highest sequence number for the relevant prefix and add one.
3. If the resulting directory already exists under any owner, take the next free number
   and tell the user which ID was assigned and why.

## Reading or resuming another person's session

Default to the current owner's sessions only.

- Listing sessions lists `context/session/{OWNER}/*` plus legacy unscoped sessions.
- Never silently read, resume, or write a session under a different owner's directory.
- If the user names a REQ ID that exists only under another owner, show its `owner`,
  `owner_email` and `devin_session_url`, state plainly that it belongs to someone else,
  and require an explicit confirmation before reading it. Even then, do not write to it —
  offer to copy it into `context/session/{OWNER}/{REQ_ID}/` instead.
- Read-only cross-owner reporting (`/dashboard`, `/pi-plan`, `/release-notes`,
  `/sprint-review-summary`) is exempt from the confirmation: it aggregates across all
  owners by design, and must show the owner alongside each requirement.

## Gate signing

`approvals.yaml` records both who owns the session and who signed each gate. `owner` is
the person running the session; `signed_by` is the approver of that gate. They are
frequently different people and must not be conflated.

## Persisting session state on a shared branch

Session state only survives because it is committed. On a shared branch:

- Stage by explicit path — `git add sdlc/framework/context/session/{OWNER}/{REQ_ID}/`.
  Never `git add .`, and never stage the whole `context/session/` directory: that picks up
  other people's uncommitted work.
- `git pull --rebase` before pushing. Owner scoping means there is nothing to conflict on
  inside your own session directory, so a rebase should be clean.
- Commit after each milestone and each gate signature, not once at the end of the session —
  an ephemeral VM that goes away with uncommitted artefacts loses them.

### Declarative cloud git settings

`auto_commit` and `auto_push` in `.devin/config.cloud.json` are declarative settings only;
no skill implements them. The agent must run the staged commit explicitly at each milestone.
An ephemeral VM that ends with uncommitted artefacts loses them.
