#!/usr/bin/env python3
"""Scan added lines for hardcoded secrets and PII patterns.

The Devin write hooks (.devin/hooks/no-hardcoded-secrets.sh, pii-guard.sh) only watch file tools.
This is the same check for everything else: shell edits, other editors, CI. Same patterns, so a
change that passes one passes the other.

  content_scan.py staged                 scan what `git commit` is about to record
  content_scan.py range <base>..<head>   scan the lines a pull request adds (CI, pre-push)
  content_scan.py text                   scan stdin (tests, ad hoc)

Exit 0: clean. Exit 2: findings (printed as path:line: rule, never the matched value).
Any other exit means the scan could not run; callers must treat that as a block.

Allowed on purpose, so a documented example does not block a commit:
  - files under a tests/ or fixtures/ folder (they hold fake keys to test the guards);
  - a line that carries the marker `argus:allow` (say why in the same line).
"""
import argparse
import re
import subprocess
import sys

ALLOW_MARKER = "argus:allow"
EXEMPT_PATH = re.compile(r"(^|/)(tests|fixtures)/")

RULES = [
    ("secret/aws-access-key-id", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("secret/aws-secret", re.compile(r"(aws_secret|aws_access_key)\s*[:=]\s*[\"']?[A-Za-z0-9/+]{20,}", re.I)),
    ("secret/password", re.compile(r"(password|passwd|pwd)\s*[:=]\s*[\"']?[^\s\"'{]{6,}", re.I)),
    ("secret/token", re.compile(r"(api_key|apikey|token|secret)\s*[:=]\s*[\"']?[A-Za-z0-9_-]{16,}", re.I)),
    ("pii/ssn", re.compile(r"\b[0-9]{3}-[0-9]{2}-[0-9]{4}\b")),
    ("pii/dob", re.compile(r"\b(DOB|date_of_birth|dateOfBirth)\s*[:=]", re.I)),
    ("pii/member-id", re.compile(r"\bMBR_ID\s*=\s*[0-9]{6,}", re.I)),
]


def scan_line(line):
    """Rule names the line breaks; none when it carries the allow marker."""
    if ALLOW_MARKER in line:
        return []
    return [name for name, rx in RULES if rx.search(line)]


def scan_diff(diff_text):
    """Findings [(path, line_no, rule)] in the lines a unified diff (-U0) adds."""
    findings, path, line_no = [], None, 0
    for raw in diff_text.splitlines():
        if raw.startswith("+++ "):
            path = raw[6:] if raw.startswith("+++ b/") else None
            continue
        hunk = re.match(r"^@@ -\S+ \+(\d+)(?:,\d+)? @@", raw)
        if hunk:
            line_no = int(hunk.group(1))
            continue
        if raw.startswith("+") and path:
            if not EXEMPT_PATH.search(path):
                findings += [(path, line_no, rule) for rule in scan_line(raw[1:])]
            line_no += 1
    return findings


def git_diff(args):
    out = subprocess.run(["git", "diff", "-U0", "--no-color", "--no-ext-diff", *args],
                         capture_output=True, text=True, encoding="utf-8", errors="replace")
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or "git diff failed")
    return out.stdout


def report(findings):
    for path, line_no, rule in findings:
        print(f"CONTENT-BLOCK: {path}:{line_no}: {rule}", file=sys.stderr)
    if findings:
        print(f"CONTENT-BLOCK: {len(findings)} finding(s). Remove the value, or add '{ALLOW_MARKER}: <why>' "
              "to a line that is a documented example. Values are never printed.", file=sys.stderr)
        return 2
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("staged")
    rng = sub.add_parser("range")
    rng.add_argument("revs", help="<base>..<head>")
    sub.add_parser("text")
    args = ap.parse_args(argv)
    if args.cmd == "text":
        findings = [("<stdin>", n, r) for n, line in enumerate(sys.stdin.read().splitlines(), 1)
                    for r in scan_line(line)]
    elif args.cmd == "staged":
        findings = scan_diff(git_diff(["--cached"]))
    else:
        findings = scan_diff(git_diff([args.revs]))
    return report(findings)


if __name__ == "__main__":
    sys.exit(main())
