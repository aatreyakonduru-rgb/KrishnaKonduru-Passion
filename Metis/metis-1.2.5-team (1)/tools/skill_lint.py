"""Lint the plugin's skills and prompts for context cost and drift.

A skill's `description` sits in the model's context for every session, so it
is the most expensive text per word. This tool reports it, and the body size
(loaded only when the skill runs), and flags:

  - description over --max-description tokens (warning)
  - body over --max-body tokens (warning)
  - missing name or description (error)
  - a skill that can write (allowed-tools has write/exec) and never mentions
    the evidence rule or an [E: ...] tag (warning)
  - near-duplicate skills or prompts: shared-line ratio over --dup (warning)

Token counts are estimates (characters / 4) unless --tokenizer is given
(same values as context_pack.py: tiktoken[:enc] or module:function).

  python skill_lint.py [--root <plugin folder>] [--json] [--strict]
Exit 1 on an error, or on any warning with --strict.
Standard library plus PyYAML.
"""
import argparse
import json
import os
import re
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ROOT = os.path.abspath(os.path.join(HERE, ".."))
EVIDENCE = re.compile(r"metis-evidence|evidence rule|\[E:", re.I)
WRITERS = {"write", "exec", "edit"}


def split_frontmatter(text):
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    try:
        meta = yaml.safe_load(text[3:end]) or {}
    except yaml.YAMLError:
        meta = {}
    return (meta if isinstance(meta, dict) else {}), text[end + 4:]


def est_tokens(text, counter=None):
    if counter:
        return counter(text)
    return (len(text) + 3) // 4


def significant_lines(text):
    out = set()
    for line in text.splitlines():
        s = " ".join(line.split()).lower()
        if len(s) >= 25 and not s.startswith(("#", "---")):
            out.add(s)
    return out


def similarity(a, b):
    """Shared lines over the smaller page: 1.0 means one is inside the other."""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def read(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def collect(root):
    items = []
    sk = os.path.join(root, "skills")
    if os.path.isdir(sk):
        for name in sorted(os.listdir(sk)):
            p = os.path.join(sk, name, "SKILL.md")
            if os.path.isfile(p):
                items.append(("skill", name, p))
    kp = os.path.join(root, "kb-prompts")
    if os.path.isdir(kp):
        for name in sorted(os.listdir(kp)):
            if name.endswith(".md"):
                items.append(("prompt", name, os.path.join(kp, name)))
    return items


def lint(root=DEFAULT_ROOT, max_description=120, max_body=4000, dup=0.8, counter=None):
    findings, rows, lines = [], [], {}
    for kind, name, path in collect(root):
        text = read(path)
        meta, body = split_frontmatter(text)
        lines[(kind, name)] = significant_lines(body)
        row = {"kind": kind, "name": name, "body_tokens": est_tokens(body, counter)}
        if kind == "skill":
            desc = str(meta.get("description") or "")
            row["description_tokens"] = est_tokens(desc, counter)
            if not meta.get("name") or not desc:
                findings.append(("error", name, "missing name or description in frontmatter"))
            if row["description_tokens"] > max_description:
                findings.append(("warning", name, f"description is {row['description_tokens']} tokens "
                                 f"(over {max_description}); it is in context every session"))
            tools = {str(t).lower() for t in (meta.get("allowed-tools") or [])}
            if tools & WRITERS and not EVIDENCE.search(text):
                findings.append(("warning", name, "can write but never mentions the evidence rule or [E: ...]"))
        if row["body_tokens"] > max_body:
            findings.append(("warning", name, f"body is {row['body_tokens']} tokens (over {max_body})"))
        rows.append(row)
    keys = sorted(lines)
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            if a[0] != b[0]:
                continue
            s = similarity(lines[a], lines[b])
            if s >= dup:
                findings.append(("warning", f"{a[1]} ~ {b[1]}", f"near duplicate: {s:.0%} of the smaller one's lines are shared"))
    return {"rows": rows, "findings": [{"level": l, "name": n, "message": m} for l, n, m in findings],
            "description_tokens_total": sum(r.get("description_tokens", 0) for r in rows)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=DEFAULT_ROOT)
    ap.add_argument("--max-description", type=int, default=120)
    ap.add_argument("--max-body", type=int, default=4000)
    ap.add_argument("--dup", type=float, default=0.8)
    ap.add_argument("--tokenizer", default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args(argv)
    counter = None
    if a.tokenizer:
        import context_pack
        counter = context_pack.load_counter(a.tokenizer)
    rep = lint(a.root, a.max_description, a.max_body, a.dup, counter)
    if a.json:
        print(json.dumps(rep, indent=2))
    else:
        skills = [r for r in rep["rows"] if r["kind"] == "skill"]
        print(f"{len(skills)} skills; descriptions total ~{rep['description_tokens_total']} tokens (always in context)")
        for r in sorted(skills, key=lambda r: -r["description_tokens"])[:10]:
            print(f"  {r['description_tokens']:>4} desc  {r['body_tokens']:>5} body  {r['name']}")
        for f in rep["findings"]:
            print(f"{f['level'].upper():8} {f['name']}: {f['message']}")
    bad = any(f["level"] == "error" for f in rep["findings"]) or (a.strict and rep["findings"])
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
