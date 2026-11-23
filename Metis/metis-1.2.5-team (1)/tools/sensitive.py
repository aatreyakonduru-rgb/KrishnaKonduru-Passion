#!/usr/bin/env python3
"""Look for secrets and personal or health data in text that is about to enter the knowledge base.

    python3 sensitive.py <file or folder> [...]      print findings; exit 1 if any is a "block"

Two levels:
    block   never goes into the KB: passwords and keys, private keys, tokens, connection strings with a password,
            social security numbers, card numbers (Luhn-checked)
    review  a lead must look and accept it in writing: email addresses, phone numbers, dates of birth, and numbers
            labelled as member, patient, medical record, claim or policy ids

A finding shows where it is and a masked sample, never the value itself. This is a pattern check, not a guarantee:
it cannot find a person's name or free-text health details, so the lead who certifies a page still reads it.
"""
import os
import re
import sys

BLOCK, REVIEW = "block", "review"

RULES = (
    (BLOCK, "credential", re.compile(r"\b(password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|client[_-]?secret)\b\s*[:=]\s*['\"]?[^\s'\"<>{}]{4,}", re.I)),
    (BLOCK, "private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    (BLOCK, "cloud key", re.compile(r"\b(AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{35}|gh[pousr]_[0-9A-Za-z]{30,}|xox[abprs]-[0-9A-Za-z-]{10,})\b")),
    (BLOCK, "bearer token", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{20,}")),
    (BLOCK, "token (JWT)", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
    (BLOCK, "connection string with password", re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s:/@]+:[^\s/@]{3,}@")),
    (BLOCK, "social security number", re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")),
    (REVIEW, "email address", re.compile(r"\b[\w.+-]+@[\w-]+(\.[\w-]+)+\b")),
    (REVIEW, "phone number", re.compile(r"(?<!\d)(\+?1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?!\d)")),
    (REVIEW, "date of birth", re.compile(r"\b(dob|date of birth|birth ?date|born)\b[^\n]{0,20}\d{1,4}[/.-]\d{1,2}[/.-]\d{1,4}", re.I)),
    (REVIEW, "personal or health id", re.compile(r"\b(member|patient|mrn|medical record|subscriber|policy|claim|beneficiary|npi|driver.?s? licen[sc]e|passport)\s*(id|number|no\.?|#)?\s*[:=#]?\s*[A-Z]*\d{6,}", re.I)),
)
CARD = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
SAFE_VALUES = re.compile(r"^(<[^>]*>|\$\{[^}]*\}|\{\{[^}]*\}\}|\*+|x{4,}|changeme|example|placeholder|none|null|redacted|your[-_ ]?\w*)$", re.I)


def luhn(digits):
    total, flip = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if flip:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        total += d
        flip = not flip
    return total % 10 == 0


def mask(s):
    s = s.strip()
    return s[:2] + "***" if len(s) > 4 else "***"


def scan_line(line):
    out = []
    for level, kind, rx in RULES:
        for m in rx.finditer(line):
            if kind == "credential":
                value = re.split(r"[:=]\s*", m.group(0), maxsplit=1)[-1].strip("'\" ")
                if SAFE_VALUES.match(value):
                    continue
            out.append((level, kind, mask(m.group(0).split()[0] if kind != "credential" else m.group(1))))
    for m in CARD.finditer(line):
        digits = re.sub(r"\D", "", m.group(0))
        if 13 <= len(digits) <= 19 and luhn(digits):
            out.append((BLOCK, "card number", mask(digits)))
    return out


def scan(text):
    """Findings for a text: [{line, level, kind, sample}]. Code blocks are scanned too: secrets hide there."""
    found = []
    for n, line in enumerate(text.splitlines(), 1):
        for level, kind, sample in scan_line(line):
            found.append({"line": n, "level": level, "kind": kind, "sample": sample})
    return found


def blocking(findings):
    return [f for f in findings if f["level"] == BLOCK]


def describe(f, name=""):
    return "%s%d: %s (%s) starting %s" % (name + ":" if name else "", f["line"], f["kind"], f["level"], f["sample"])


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print(__doc__)
        return 2
    worst = 0
    for target in argv:
        paths = []
        if os.path.isdir(target):
            for d, dirs, fs in os.walk(target):
                dirs[:] = [x for x in dirs if x not in (".git", "_EVIDENCE", "Archive")]
                paths += [os.path.join(d, f) for f in fs if f.endswith((".md", ".yaml", ".yml", ".txt"))]
        else:
            paths = [target]
        for p in paths:
            with open(p, encoding="utf-8", errors="replace") as fh:
                for f in scan(fh.read()):
                    print(describe(f, p))
                    worst = 1 if f["level"] == BLOCK else worst
    return worst


if __name__ == "__main__":
    sys.exit(main())
