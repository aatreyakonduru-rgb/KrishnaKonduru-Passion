---
name: kb-compare
description: Compare a staged knowledge-base rebuild (from /kb-build) with the live KB, show the owner what changed and what hand-made content would be lost, and replace live files only after the owner approves, keeping the old copies.
argument-hint: "[<stage dir>] [--approve <files...> --approved-by <name>]"
allowed-tools:
  - read
  - write
  - grep
  - glob
  - exec
visibility: internal
triggers:
  - user
  - model
---

# KB compare

The gate between a staged rebuild and the live knowledge base. The comparison only reads.
Replacing files is a separate step, and it needs the owner's approval.

## Step 1 — compare

`<stage>` is the argument, else the newest folder under `docs/knowledge-base/_REGEN/`.

```bash
python3 sdlc/kb/tools/kb_compare.py docs/knowledge-base <stage> \
  --map .devin/rules/kb-output-names.yaml --keep .devin/rules/kb-keep.yaml --out <stage>/COMPARISON.md
```

The map turns the name a shared prompt writes into our live name, for example
`9B_DB_DATA_CONTRACTS.yaml` into `11_DB_DATA_CONTRACTS.yaml`. The keep list names the live files
no prompt builds (made from a workbook, written by hand, or built by a `kbgen` script). They're
reported as kept, and `kb_promote.py` refuses to replace them. Add a file there when you find
another one.

## Step 2 — review what matters

Read `<stage>/COMPARISON.md` and pick out, per file:

- **Hand-made content that would be lost:** `[E: stated by ...]` facts missing from the new
  version, and live `.PATCHES.md` sidecars whose entries the new version doesn't carry. Either
  carry them into the staged file (and say where each came from), or list them for the owner.
- **Headings removed**, and evidence tags that went down, or `[?]` counts that went up.
- **Old-style tags** (`[CONFIRMED]`, `[INFERRED]` and so on) left in a staged file. The staged file
  should use `[E: ...]`, `[A]` and `[?]`.
- **Live files not rebuilt** in the same folders. Say whether each is expected (no prompt makes it,
  or it came from another source such as a workbook) or a gap.
- **Differences that come from the environment,** for a DB rebuild: compare the `source_db` in both
  headers. A different database means environment differences, not staleness.

## Step 3 — gate

⛔ Stop here. The owner of the documents (a tech lead for DB and app documents, the ETL lead for
ETL documents) must approve which staged files replace the live ones. Present the summary, the
files proposed for replacement and the content that would be lost, with the Approve / Reject with
reasons / Approve with notes options, as `.devin/rules/gate-presentation.md` describes. Record who
approved, when, and the exact file list. Don't approve on anyone's behalf.

## Step 4 — merge the approved files into the live KB

Only for the files the owner approved, and after a dry run. Use `--merge`: the live file is not
replaced wholesale. `sdlc/kb/tools/kb_merge.py` puts the staged, source-checked text first
and keeps below it, under "Kept from the previous version", only the old lines the new text does
not already say, labelled as not re-checked. Old lines that the staged "What changed" table
contradicts are marked **Corrected** with what the source says today. For YAML, keys and list
items only the old copy had go under `kept_from_previous_version`. Where the output-name map
gives a list, the other live copies are merged in too and moved to the archive.

```bash
python3 sdlc/kb/tools/kb_promote.py docs/knowledge-base <stage> --merge \
  --map .devin/rules/kb-output-names.yaml --keep .devin/rules/kb-keep.yaml --approved-by "<name>" --files <file> ... --dry-run
python3 sdlc/kb/tools/kb_promote.py docs/knowledge-base <stage> --merge \
  --map .devin/rules/kb-output-names.yaml --keep .devin/rules/kb-keep.yaml --approved-by "<name>" --files <file> ...
python3 sdlc/framework/tools/kb_manifest.py generate
```

The old copies go to `docs/knowledge-base/Archive/<date>/` word for word (the tool
refuses to overwrite one already there), and each merge is logged in `Archive/PROMOTIONS.log`.
Without `--merge` the staged file replaces the live one; use that only when the owner asks for it. A `.PATCHES.md` sidecar whose entries were carried into the new
file can then be moved to the archive too, with the owner's approval.

The staging folder stays until the owner says it can go. Removing it is a separate, approved step.

## When done

Report the comparison file, the files replaced (with the approver), the files left as they were,
and anything still open.
