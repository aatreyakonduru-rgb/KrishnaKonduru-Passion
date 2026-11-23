#!/usr/bin/env python3
"""Move reviewed staged files into the live knowledge base, keeping the old copies.

    python3 kb_promote.py LIVE_DIR STAGE_DIR --approved-by NAME --files REL [REL ...]
                          [--map MAP.yaml] [--keep KEEP.yaml] [--archive DIR] [--merge] [--dry-run]

Run it only after the owner has approved the kb_compare.py report for exactly these files.
Each REL is a path relative to STAGE_DIR. MAP.yaml is the same staged-to-live name map that
kb_compare.py takes. A file on the KEEP.yaml list (see kb_compare.py) is never replaced. Before a live file is replaced, it is copied to
ARCHIVE/<date>/<live path> (default ARCHIVE is LIVE_DIR/Archive). Staged files are left in
place. Every promotion is appended to ARCHIVE/PROMOTIONS.log.

With --merge, a live file is not replaced: kb_merge.py writes the staged copy with the live
copy's uncovered and corrected lines kept below it (Markdown), or with the keys only the live
copy had (YAML). A map entry can name a list of live files: the first is the one merged into,
and the others are duplicate copies of the same document. Their lines are merged in too, then
they and their .PATCHES.md sidecars are moved to the archive. Nothing is deleted without a
copy in the archive.
"""
import argparse
import datetime
import os
import shutil
import sys

import yaml

import kb_gate
import kb_merge
from kb_compare import duplicates, kept_by, live_name, load_keep, sidecar


def plan(live, stage, files, mapping, archive, today, keep_list=None):
    steps = []
    for rel in files:
        rel = rel.strip("/")
        src = os.path.join(stage, rel)
        if not os.path.isfile(src):
            raise ValueError("not in the staging folder: %s" % rel)
        live_rel = live_name(mapping, rel)
        for name in [live_rel] + duplicates(mapping, rel):
            if kept_by(name, keep_list):
                raise ValueError("on the keep list, not built by a prompt: %s" % name)
        dst = os.path.join(live, live_rel)
        keep = os.path.join(archive, today, live_rel) if os.path.exists(dst) else None
        if keep and os.path.exists(keep):
            raise ValueError("already archived today, so it would be overwritten: %s" % keep)
        steps.append((rel, src, dst, keep))
    return steps


def read_text(path):
    """A KB file's text. Some older files were saved as Windows-1252, not UTF-8."""
    with open(path, "rb") as fh:
        data = fh.read()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def extras(live, mapping, rel):
    """Existing duplicate copies of rel's document, with their sidecars: [(path, archive rel)]."""
    out = []
    for dup in duplicates(mapping, rel):
        path = os.path.join(live, dup)
        if os.path.isfile(path):
            out.append(path)
            side = sidecar(path)
            if side and os.path.isfile(side):
                out.append(side)
    return out


def promote(live, stage, files, approved_by, mapping=None, archive=None, dry_run=False, today=None,
            keep=None, merge=False):
    if not (approved_by or "").strip():
        raise ValueError("--approved-by is required: name the owner who approved the comparison")
    if not files:
        raise ValueError("name the files to promote with --files")
    today = today or datetime.date.today().isoformat()
    archive = archive or os.path.join(live, "Archive")
    steps = plan(live, stage, files, mapping or {}, archive, today, keep)
    gated = kb_gate.is_locked(live)
    if gated:
        kb_gate.who(live, approved_by)
        for rel, src, dst, _ in steps:
            blocked = kb_gate.sensitive.blocking(kb_gate.findings(rel, read_text(src)))
            if blocked:
                raise ValueError("%s has a %s on line %d; take it out first" % (rel, blocked[0]["kind"], blocked[0]["line"]))
    if dry_run:
        return steps
    log = []
    for rel, src, dst, keep in steps:
        dups = extras(live, mapping or {}, rel) if merge else []
        also = [(os.path.relpath(p, live), read_text(p)) for p in dups if not p.endswith(".PATCHES.md")]
        if keep:
            os.makedirs(os.path.dirname(keep), exist_ok=True)
            shutil.copy2(dst, keep)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if merge and (keep or also):
            text, _ = kb_merge.merge_file(read_text(dst) if keep else "", read_text(src), dst, also,
                                          os.path.relpath(keep, live).replace(os.sep, "/") if keep else None)
            with open(dst, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
        else:
            shutil.copy2(src, dst)
        log.append((dst, keep, "merged" if merge and (keep or also) else "replaced" if keep else "(new)"))
        for path in dups:
            moved = os.path.join(archive, today, os.path.relpath(path, live))
            os.makedirs(os.path.dirname(moved), exist_ok=True)
            shutil.move(path, moved)
            log.append((path, moved, "duplicate merged into %s, moved to archive" % os.path.relpath(dst, live).replace(os.sep, "/")))
    os.makedirs(archive, exist_ok=True)
    with open(os.path.join(archive, "PROMOTIONS.log"), "a", encoding="utf-8", newline="\n") as fh:
        for dst, keep, how in log:
            fh.write("%s\t%s\t%s\t%s\t%s\n" % (today, approved_by.strip(), os.path.relpath(dst, live).replace(os.sep, "/"),
                                               os.path.relpath(keep, live).replace(os.sep, "/") if keep else "(new)", how))
    if gated:
        with kb_gate.gate_lock(live):
            for dst, keep, how in log:
                rel = os.path.relpath(dst, live).replace(os.sep, "/")
                if os.path.isfile(dst):
                    kb_gate.record(live, rel, approved_by, "promote-" + today)
                else:
                    st = kb_gate.load_state(live)
                    st.get("files", {}).pop(rel, None)
                    kb_gate.save_state(live, st)
    return steps


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("live")
    ap.add_argument("stage")
    ap.add_argument("--files", nargs="+", required=True)
    ap.add_argument("--approved-by", required=True)
    ap.add_argument("--map")
    ap.add_argument("--keep")
    ap.add_argument("--archive")
    ap.add_argument("--merge", action="store_true", help="merge into live files instead of replacing them")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    mapping = {}
    if args.map:
        with open(args.map, encoding="utf-8") as fh:
            mapping = yaml.safe_load(fh) or {}
    try:
        steps = promote(args.live, args.stage, args.files, args.approved_by, mapping,
                        args.archive, args.dry_run, keep=load_keep(args.keep) if args.keep else None,
                        merge=args.merge)
    except ValueError as err:
        print("error: %s" % err, file=sys.stderr)
        return 2
    for rel, src, dst, keep in steps:
        print("%s%s -> %s%s" % ("(dry run) " if args.dry_run else "", rel, dst,
                                "  (old copy: %s)" % keep if keep else "  (new)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
