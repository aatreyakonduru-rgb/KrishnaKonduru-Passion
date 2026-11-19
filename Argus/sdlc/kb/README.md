# Shareable knowledge-base prompts

This folder builds an AI-ready knowledge base for a product: its database, its application
modules, its ETL jobs, and the business context around them. Hand the folder to a team, and the
team fills in one settings file and runs the prompts. Nothing in the folder holds any team's
data. `lint` proves that before each share.

Version: see `VERSION`. Changes: see `CHANGELOG.md`.

## What's here

| Path | What it is |
|---|---|
| `kb-prompts/` | The prompts. Team values are `{{PLACEHOLDERS}}`. |
| `kb-prompts/PROMPT_STANDARD.md` | How a shareable prompt must be written |
| `kb-prompts/placeholders.yaml` | Every placeholder, and where its value comes from |
| `tools/prompts.py` | `lint` checks the folder. `render` fills in a team's values. `status` lists the prompts. |
| `examples/acme/` | A sample profile, environment file and roster with made-up values |
| `examples/acme/people.yaml` | A sample SDLC roster: Resource 1 to Resource 22 with the roles our team uses, for the approval gates and role routing |

## What you need

- Python 3 with PyYAML.
- An AI coding agent, such as Devin, that can read your repos and run the rendered prompts.
- For the DB prompts, read-only access to your Snowflake database. The queries are Snowflake
  SQL. Other databases would need the queries adapted.

## Setting up

1. Copy `examples/acme/kb-profile.yaml` to `.devin/rules/kb-profile.yaml` in your repo, and
   copy the environment file and roster next to it. Replace every value with your own: product
   name, folders, database, schemas, filters and people. The comments say what each one is for.
   Paths in the profile are relative to your repo root, so point `db.environments_file` and
   `team.roster_file` at where you put those two files.
2. Add your own product names, schema prefixes and code words to `lint.leak_terms` and
   `lint.leak_patterns`. This makes `lint` catch them if they ever leak into a shared prompt.
3. From your repo root, run:

```bash
python3 sdlc/kb/tools/prompts.py lint
python3 -m unittest discover -s sdlc/kb/tools/tests
```

`render` picks the database environment from `--env`, then the `SNOWFLAKE_ENV` variable,
then `db.kb_environment` in the profile, then the environment file's `default`. If an
environment sets `docs_dir`, its DB documents go in that sub-folder of `paths.db_docs`, so a
test-region run never overwrites the documents built from production (`docs_dir: .` means the
folder itself).

## Rebuilding next to the live knowledge base

A rebuild should never write over the live documents, because they carry fixes people made by
hand. Render with `--stage` and every output moves under that folder. The prompt also says to
read an input from the live folder when the staged copy doesn't exist yet:

```bash
python3 sdlc/kb/tools/prompts.py render DB_PROMPT_2_BRD.md --stage kb/_REGEN/2026-01-15 --out /tmp/db-02.md
python3 sdlc/kb/tools/prompts.py outputs DB_PROMPT_2_BRD.md --stage kb/_REGEN/2026-01-15
python3 sdlc/kb/tools/kb_compare.py kb kb/_REGEN/2026-01-15 --out /tmp/compare.md
```

`kb_compare.py` lists each staged file as new, changed or the same. It flags what a reviewer
must check before a swap: hand-supplied facts (`[E: stated by ...]`) the rebuild dropped,
sections that disappeared, `.PATCHES.md` sidecars, and live files the rebuild didn't produce.
If your live file names differ from the prompt output names, pass `--map` with a YAML mapping
of staged path to live path. Pass `--keep` with a YAML list of live files no prompt builds, such
as documents made from a spreadsheet or written by hand (`{keep: [{path: ..., source: ...}]}`):
they are reported as kept, and `kb_promote.py --keep` refuses to replace them. It only reads;
replacing files is a separate, approved step.

To keep the profile somewhere else, set `KB_PROFILE` to its path, and `KB_TEAM_ROOT` to the
folder its relative paths start from. To try the sample as it is:

```bash
KB_PROFILE=sdlc/kb/examples/acme/kb-profile.yaml KB_TEAM_ROOT=sdlc/kb/examples/acme \
  python3 sdlc/kb/tools/prompts.py render DB_PROMPT_1_DISCOVERY.md --env test
```

## Running the prompts

Render a prompt, then give the rendered text to the agent:

```bash
python3 sdlc/kb/tools/prompts.py render DB_PROMPT_1_DISCOVERY.md --env test
python3 sdlc/kb/tools/prompts.py render PROMPT_1_DISCOVERY.md --env test \
  --set MODULE_NAME=orders-api --set MODULE_SOURCE=orders-api
```

Go in this order. Each runner holds its stage table and review gates.

1. **Domain context:** CTX-0A to CTX-0E from your own documents, then CTX-00. Every other
   prompt reads the result.
2. **Database:** `KB_RUNNER_DB.md` (DB-01 to DB-16).
3. **Application modules:** `KB_RUNNER_APP.md`, running API modules before the UIs that call them.
4. **ETL modules:** `KB_RUNNER_ETL.md`.
5. **Cross-module matrix:** DB-16 again, once the app and ETL docs exist.

Use `SESSION_MANAGER.md` at the start and end of each session. For an area still marked `[?]`,
use `PROMPT_GAP_FILL.md`. After a release, run `DB_PROMPT_STALENESS_DETECTION.md` and the
change check in `SESSION_MANAGER.md` to find what needs refreshing.

## Rules every prompt follows

- Facts carry `[E: source]`. Assumptions carry `[A]`, and unknowns carry `[?]`. Every `[A]` and
  `[?]` also goes on a closing list with an owner. Nothing is guessed.
- Database queries are read-only.
- Secrets, hosts and account numbers never go into a generated document.
- Re-runs go to a staging folder first. Reviewed documents are only replaced after the owner
  approves the comparison.

## Before you share a copy

Run `prompts.py lint`. It fails on any team term, profile value, internal path, email address,
account number, credential-like string, old evidence tag, fixed count, or missing section.
Share only a clean folder.

## Not in this folder yet

- Skills that render and run the prompts for you (`/kb-build`, `/kb-refresh`).
- The rest of the agentic SDLC: stage skills, approval gates and ADRs.
