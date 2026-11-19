#!/usr/bin/env python3
"""Build a patch zip of a shared copy: only the files that changed since a git ref, plus the patch scripts.

    python3 build_patch.py --base <ref> [--copy sdlc/kb/v2.1.101826] [--out sdlc/kb/<name>-patch-<date>.zip]

The zip holds files/ (changed and added files at their paths in the copy), removed.txt, patch.py,
patch.sh (Unix, Git Bash) and patch.cmd (Windows) from tools/installer/, and PATCH-NOTES.md.
"""
import argparse
import datetime
import os
import subprocess
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
SCRIPTS = ("patch.py", "patch.sh", "patch.cmd")
ENGINE = ("install.py", "install_steps.py", "install_ui.py")  # patch.py imports the installer from files/


def changes(base, copy):
    out = subprocess.run(["git", "diff", "--name-status", "--no-renames", base, "HEAD", "--", copy],
                         cwd=ROOT, capture_output=True, text=True, check=True).stdout
    kept, gone = [], []
    for line in out.splitlines():
        status, path = line.split("\t", 1)
        rel = os.path.relpath(path, copy).replace(os.sep, "/")
        (gone if status == "D" else kept).append(rel)
    return sorted(kept), sorted(gone)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", required=True, help="git ref of the copy the team installed")
    ap.add_argument("--copy", default="sdlc/kb/v2.1.101826")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    name = os.path.basename(a.copy.rstrip("/"))
    stamp = datetime.date.today().strftime("%m%d%y")
    out = a.out or os.path.join(ROOT, os.path.dirname(a.copy), "%s-patch.%s.zip" % (name, stamp))
    kept, gone = changes(a.base, a.copy)
    kept = sorted(set(kept) | {e for e in ENGINE if os.path.exists(os.path.join(ROOT, a.copy, e))})
    base_sha = subprocess.run(["git", "rev-parse", "--short", a.base], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    head_sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    top = "%s-patch.%s" % (name, stamp)
    notes = ("# Patch for %s\n\nFrom commit %s to %s: %d files changed or added, %d removed.\n\n"
             "## Apply\n\n- Unix or Git Bash: `./patch.sh /path/to/your-repo` (add `--dry-run` to list the changes first)\n"
             "- Windows: `patch.cmd C:\\path\\to\\your-repo` (add `--dry-run` to list the changes first)\n\n"
             "The script reads your values from `.devin/rules/sdlc-install.yaml`, writes each file where the "
             "installer put it with your values in, keeps every replaced file in `.sdlc-patch-backup/`, "
             "regenerates the counts and pages, and runs `install.py --check --offline`. Commit the result "
             "through a pull request.\n\n## Files\n\n" % (name, base_sha, head_sha, len(kept), len(gone))
             + "".join("- `%s`\n" % r for r in kept) + "".join("- removed: `%s`\n" % r for r in gone))
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in kept:
            z.write(os.path.join(ROOT, a.copy, rel), "%s/files/%s" % (top, rel))
        for s in SCRIPTS:
            info = zipfile.ZipInfo("%s/%s" % (top, s), datetime.datetime.now().timetuple()[:6])
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o100755 if s.endswith(".sh") else 0o100644) << 16
            with open(os.path.join(HERE, "installer", s), "rb") as fh:
                z.writestr(info, fh.read())
        z.writestr("%s/removed.txt" % top, "".join(r + "\n" for r in gone))
        z.writestr("%s/PATCH-NOTES.md" % top, notes)
    print("wrote %s: %d files, %d removed" % (os.path.relpath(out, ROOT), len(kept), len(gone)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
