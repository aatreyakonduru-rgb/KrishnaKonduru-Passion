#!/usr/bin/env python3
"""Build dev-unit-test-cases/<release>/RELEASE-TEST-CASES.md for the stories going to QA.

Executable tests live in the normal app test files so Bamboo runs them on every build; this
tool only indexes them per story. It reads each story's session approvals.yaml
(`phases.code_review.tests` and `jira_key`), confirms every test file and test case still
exists in the source tree, and writes one Markdown manifest per release. Re-running it with
a story left out drops that story from the manifest — nothing is copied, so nothing drifts.

    gen_release_tests.py --release 2026-11-13 --story ACME-18698 --story ACME-18700
    gen_release_tests.py --release 2026-11-13 --stories-file releases/2026-11-13.txt --dry-run
"""
import argparse
import datetime
import glob
import os
import re
import subprocess
import sys

import yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SESSION_ROOT = os.path.join(ROOT, "sdlc", "framework", "context", "session")
OUT_ROOT = os.path.join(ROOT, "dev-unit-test-cases")
PY_TEST = re.compile(r"^\s*(?:async\s+)?def\s+(test\w*)\s*\(", re.M)
JS_TEST = re.compile(r"\b(?:it|test)\s*\(\s*['\"`]([^'\"`]+)['\"`]")
STORY_KEY = re.compile(r"^[A-Z][A-Z0-9]+-\d+$")


def now():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def git(*args):
    try:
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except (subprocess.CalledProcessError, OSError):
        return ""


def load_sessions():
    """Every session approvals.yaml, keyed by the Jira key(s) recorded in it."""
    found = {}
    paths = glob.glob(os.path.join(SESSION_ROOT, "*", "REQ-*", "approvals.yaml"))
    paths += glob.glob(os.path.join(SESSION_ROOT, "REQ-*", "approvals.yaml"))
    for path in sorted(set(paths)):
        with open(path, encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        phases = data.get("phases") or {}
        blocks = [phases.get("code_review") or {}]
        blocks += [v for k, v in phases.items() if k.startswith("code_review_") and isinstance(v, dict)]
        for block in blocks:
            key = block.get("jira_key")
            if key:
                found.setdefault(str(key).upper(), []).append((path, data, block))
    return found


def test_cases_in(path):
    full = os.path.join(ROOT, path)
    if not os.path.isfile(full):
        return None
    with open(full, encoding="utf-8", errors="replace") as handle:
        text = handle.read()
    pattern = PY_TEST if path.endswith(".py") else JS_TEST
    return [m.group(1) for m in pattern.finditer(text)]


def build(release, stories, strict):
    sessions = load_sessions()
    rows, problems = [], []
    for key in stories:
        blocks = sessions.get(key)
        if not blocks:
            problems.append("%s: no session approvals.yaml records jira_key %s" % (key, key))
            continue
        for path, data, block in blocks:
            rel_session = os.path.relpath(path, ROOT)
            for entry in block.get("tests") or []:
                test_path = entry.get("path")
                if not test_path:
                    continue
                present = test_cases_in(test_path)
                if present is None:
                    problems.append("%s: test file %s not found" % (key, test_path))
                    continue
                cases = entry.get("cases") or []
                acs = entry.get("acceptance_criteria") or []
                for i, case in enumerate(cases):
                    ok = case in present
                    if not ok:
                        problems.append("%s: %s has no test named %s" % (key, test_path, case))
                    rows.append({
                        "story": key,
                        "requirement": data.get("requirement_id"),
                        "story_id": block.get("story_id"),
                        "path": test_path,
                        "case": case,
                        "ac": acs[i] if i < len(acs) else "",
                        "signed": block.get("signed_at") or "",
                        "session": rel_session,
                        "present": ok,
                    })
    if strict and problems:
        raise SystemExit("release manifest not written:\n  " + "\n  ".join(problems))
    return rows, problems


def render(release, stories, rows, problems):
    lines = [
        "# Release test cases — %s" % release,
        "",
        "Generated %s by `sdlc/framework/tools/gen_release_tests.py` on branch `%s` @ `%s`."
        % (now(), git("rev-parse", "--abbrev-ref", "HEAD") or "?", git("rev-parse", "--short", "HEAD") or "?"),
        "",
        "The tests themselves stay in the application test files listed below and run in every Bamboo build;",
        "this file is the QA index of which of them belong to the stories in this release. Regenerate it whenever",
        "a story joins or leaves the release — do not edit by hand.",
        "",
        "Stories in this release: " + ", ".join("`%s`" % s for s in stories),
        "",
        "## Run everything for this release",
        "",
        "```",
    ]
    files = sorted({r["path"] for r in rows if r["present"]})
    py = [f for f in files if f.endswith(".py")]
    js = [f for f in files if not f.endswith(".py")]
    if py:
        lines.append("python manage.py test " + " ".join(p[:-3].replace("/", ".") for p in py))
    if js:
        lines.append("npx jest " + " ".join(js))
    if not files:
        lines.append("(no test files recorded)")
    lines += ["```", "", "## By story", ""]
    for key in stories:
        story_rows = [r for r in rows if r["story"] == key]
        lines.append("### %s" % key)
        if not story_rows:
            lines += ["", "_No tests recorded for this story._", ""]
            continue
        head = story_rows[0]
        lines += [
            "",
            "Requirement `%s` · %s · SDLC_05 signed %s · session `%s`"
            % (head["requirement"], head["story_id"] or "", head["signed"] or "not recorded", head["session"]),
            "",
            "| # | Test file | Test case | Covers AC | In source |",
            "|---|---|---|---|---|",
        ]
        for i, r in enumerate(story_rows, 1):
            lines.append("| %d | `%s` | `%s` | %s | %s |"
                         % (i, r["path"], r["case"], r["ac"] or "—", "yes" if r["present"] else "**missing**"))
        lines.append("")
    if problems:
        lines += ["## Problems", ""] + ["- " + p for p in problems] + [""]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--release", required=True, help="release version or date, e.g. 2026-11-13 or R13")
    ap.add_argument("--story", action="append", default=[], help="Jira key going to QA; repeatable")
    ap.add_argument("--stories-file", help="text file with one Jira key per line")
    ap.add_argument("--strict", action="store_true", help="fail instead of writing a manifest with problems")
    ap.add_argument("--dry-run", action="store_true", help="print the manifest, write nothing")
    args = ap.parse_args()

    stories = [s.strip().upper() for s in args.story]
    if args.stories_file:
        with open(args.stories_file, encoding="utf-8") as handle:
            stories += [line.strip().upper() for line in handle if line.strip() and not line.startswith("#")]
    stories = sorted(set(stories))
    bad = [s for s in stories if not STORY_KEY.match(s)]
    if bad:
        raise SystemExit("not Jira keys: %s" % ", ".join(bad))
    if not stories:
        raise SystemExit("no stories given")
    if not re.match(r"^[A-Za-z0-9._-]+$", args.release):
        raise SystemExit("release must be a plain version or date token")

    rows, problems = build(args.release, stories, args.strict)
    text = render(args.release, stories, rows, problems)
    if args.dry_run:
        print(text)
        return 1 if problems else 0
    out_dir = os.path.join(OUT_ROOT, args.release)
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "RELEASE-TEST-CASES.md")
    with open(out, "w", encoding="utf-8") as handle:
        handle.write(text)
    print("wrote %s (%d test cases, %d stories, %d problems)" % (os.path.relpath(out, ROOT), len(rows), len(stories), len(problems)))
    for p in problems:
        print("  problem: " + p, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
