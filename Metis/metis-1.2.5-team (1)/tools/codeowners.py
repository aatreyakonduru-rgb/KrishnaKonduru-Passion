#!/usr/bin/env python3
"""CODEOWNERS parser and knowledge-base ownership router.

    python3 codeowners.py parse             <repo_or_file>
    python3 codeowners.py owners            <repo> <path>
    python3 codeowners.py page              <kb> <page_rel>
    python3 codeowners.py suggest-question  <kb> <question_id>
    python3 codeowners.py suggest-queue     <kb> <batch> <rel>

Parses CODEOWNERS files (GitHub and Bitbucket locations, gitignore-style glob rules,
last match wins) and routes KB pages, open questions, and review-queue items to owners.
Degrades gracefully when graph_store or CODEOWNERS are absent. Does not change files.
"""
import argparse
import fnmatch
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kb_gate  # noqa: E402

CODEOWNERS_LOCATIONS = (
    ".github/CODEOWNERS",
    "CODEOWNERS",
    "docs/CODEOWNERS",
    ".bitbucket/CODEOWNERS",
)


def pattern_to_regex(pattern):
    """Convert a CODEOWNERS pattern to a compiled regex.

    Follows standard gitignore / CODEOWNERS semantics:
    - Leading '/' anchors to root.
    - If no slash in pattern (or only trailing slash), matches anywhere.
    - If slash is present (other than trailing), pattern is anchored to root.
    - Trailing '/' matches directory and all descendants.
    - '*' matches non-slash characters; '**' matches any characters.
    """
    pat = pattern.strip()
    if not pat:
        return None

    anchored = False
    if pat.startswith("/"):
        anchored = True
        pat = pat[1:]
    elif "/" in pat.rstrip("/"):
        anchored = True

    dir_only = False
    if pat.endswith("/"):
        dir_only = True
        pat = pat[:-1]

    # Translate glob tokens into regex
    i = 0
    n = len(pat)
    res = []
    while i < n:
        c = pat[i]
        if c == "*":
            if i + 1 < n and pat[i + 1] == "*":
                # Double star
                i += 2
                if i < n and pat[i] == "/":
                    i += 1
                    res.append("(?:.*/)?")
                else:
                    res.append(".*")
            else:
                res.append("[^/]*")
                i += 1
        elif c == "?":
            res.append("[^/]")
            i += 1
        elif c in ".^$+|(){}[]\\":
            res.append("\\" + c)
            i += 1
        else:
            res.append(re.escape(c))
            i += 1

    core = "".join(res)
    if dir_only:
        regex_str = r"^" + core + r"(?:/.*)?$" if anchored else r"(?:^|/)" + core + r"(?:/.*)?$"
    else:
        regex_str = r"^" + core + r"(?:/.*)?$" if anchored else r"(?:^|/)" + core + r"(?:/.*)?$"

    try:
        return re.compile(regex_str, re.IGNORECASE)
    except re.error:
        return None


def parse_codeowners(text_or_path):
    """Parse CODEOWNERS content into a list of [(pattern, regex, [owners])]."""
    text = text_or_path
    if os.path.isfile(text_or_path):
        with open(text_or_path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()

    rules = []
    for raw_line in str(text).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if not parts:
            continue
        pattern = parts[0]
        owners = parts[1:]
        if not owners:
            continue
        rx = pattern_to_regex(pattern)
        if rx:
            rules.append((pattern, rx, owners))
    return rules


def find_codeowners_file(repo_dir):
    """Find the first CODEOWNERS file in standard GitHub / Bitbucket locations."""
    if not os.path.isdir(repo_dir):
        return None
    for rel in CODEOWNERS_LOCATIONS:
        p = os.path.join(repo_dir, rel.replace("/", os.sep))
        if os.path.isfile(p):
            return p
    return None


def owners_for_path(rules_or_repo, rel_path):
    """Match a relative path against CODEOWNERS rules. Last match wins."""
    if isinstance(rules_or_repo, str):
        if os.path.isdir(rules_or_repo):
            p = find_codeowners_file(rules_or_repo)
            rules = parse_codeowners(p) if p else []
        elif os.path.isfile(rules_or_repo):
            rules = parse_codeowners(rules_or_repo)
        else:
            rules = []
    else:
        rules = rules_or_repo or []

    clean_path = rel_path.strip().replace("\\", "/").lstrip("/")
    matched_owners = []
    for _, rx, owners in rules:
        if rx.search(clean_path):
            matched_owners = owners
    return list(matched_owners)


def repo_rules_map(kb):
    """Load CODEOWNERS rules for each repository configured in the KB."""
    rules = {}
    try:
        import build_plan
        for repo_name, d in build_plan.repo_dirs(kb).items():
            cf = find_codeowners_file(d)
            if cf:
                rules[repo_name] = parse_codeowners(cf)
    except Exception:
        pass
    return rules


def page_codeowners(kb, rel_page):
    """List owners for a KB page mapped through cited source code paths and named graph objects."""
    owners = []
    seen = set()

    def add_owner(o):
        clean_o = str(o).strip()
        if clean_o and clean_o not in seen:
            seen.add(clean_o)
            owners.append(clean_o)

    # 1. Check directly cited repository source files from build_plan
    try:
        import build_plan
        cited = build_plan.cited_files(kb).get(rel_page, {})
        rules_by_repo = repo_rules_map(kb)
        for repo_name, paths in cited.items():
            rules = rules_by_repo.get(repo_name) or []
            for path in paths:
                for o in owners_for_path(rules, path):
                    add_owner(o)
    except Exception:
        pass

    # 2. Check objects named in page via graph_store or LINK_GRAPH
    try:
        import kb_coverage
        texts = [kb_coverage.page_files(kb).get(rel_page, "").lower()]
        link_graph_path = os.path.join(kb, "CROSS-LAYER", "LINK_GRAPH.yaml")
        if os.path.isfile(link_graph_path):
            import yaml
            with open(link_graph_path, encoding="utf-8") as fh:
                g = yaml.safe_load(fh) or {}
            rules_by_repo = repo_rules_map(kb)
            for node in g.get("nodes") or []:
                name = str(node.get("name", ""))
                if name and kb_coverage.named(name, texts):
                    # Check node's defined_in or related edges
                    defined_in = str(node.get("defined_in") or "")
                    if "/" in defined_in:
                        repo, _, subpath = defined_in.partition("/")
                        if repo in rules_by_repo:
                            for o in owners_for_path(rules_by_repo[repo], subpath):
                                add_owner(o)
    except Exception:
        pass

    return owners


def suggest_owner_for_page(kb, rel_page):
    """Return a single suggested owner for a KB page (or None).

    Checks:
    1. Direct CODEOWNERS mapping for the page's cited files.
    2. gate.teams ownership rule from kb-profile.yaml.
    """
    code_owners = page_codeowners(kb, rel_page)
    if code_owners:
        return code_owners[0]

    # Fallback to gate.teams
    try:
        t = kb_gate.team_of(kb, rel_page)
        if t:
            return t["name"]
    except Exception:
        pass

    return None


def suggest_owner_for_question(kb, question_or_id):
    """Return suggested owner for an open question."""
    q_dict = None
    if isinstance(question_or_id, dict):
        q_dict = question_or_id
    else:
        try:
            import questions
            reg = questions.load(questions.reg_path(kb)).get("questions") or []
            q_dict = next((q for q in reg if q.get("id") == question_or_id), None)
        except Exception:
            q_dict = None

    if not q_dict:
        return None

    # Check blocked pages
    blocks = q_dict.get("blocks") or []
    if isinstance(blocks, str):
        blocks = [blocks]

    for p in blocks:
        suggested = suggest_owner_for_page(kb, p)
        if suggested:
            return suggested

    return None


def suggest_owner_for_review_item(kb, item_or_file):
    """Return suggested owner for a review-queue item."""
    rel = item_or_file.get("file") if isinstance(item_or_file, dict) else str(item_or_file)
    return suggest_owner_for_page(kb, rel)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("parse")
    a.add_argument("repo_or_file")

    a = sub.add_parser("owners")
    a.add_argument("repo")
    a.add_argument("path")

    a = sub.add_parser("page")
    a.add_argument("kb")
    a.add_argument("page_rel")

    a = sub.add_parser("suggest-question")
    a.add_argument("kb")
    a.add_argument("question_id")

    a = sub.add_parser("suggest-queue")
    a.add_argument("kb")
    a.add_argument("batch")
    a.add_argument("rel")

    args = ap.parse_args(argv)

    if args.cmd == "parse":
        p = args.repo_or_file
        if os.path.isdir(p):
            cf = find_codeowners_file(p)
            if not cf:
                print("no CODEOWNERS file found in %s" % p)
                return 1
            p = cf
        rules = parse_codeowners(p)
        print("parsed %d rules from %s" % (len(rules), p))
        for pat, _, owners in rules:
            print("  %-30s -> %s" % (pat, ", ".join(owners)))

    elif args.cmd == "owners":
        owners = owners_for_path(args.repo, args.path)
        if owners:
            print("owners for %s: %s" % (args.path, ", ".join(owners)))
        else:
            print("no owner matched %s" % args.path)

    elif args.cmd == "page":
        kb = os.path.abspath(args.kb)
        owners = page_codeowners(kb, args.page_rel)
        suggested = suggest_owner_for_page(kb, args.page_rel)
        print("page: %s" % args.page_rel)
        print("suggested owner: %s" % (suggested or "(none)"))
        if owners:
            print("all mapped owners: %s" % ", ".join(owners))

    elif args.cmd == "suggest-question":
        kb = os.path.abspath(args.kb)
        suggested = suggest_owner_for_question(kb, args.question_id)
        print("question %s suggested owner: %s" % (args.question_id, suggested or "(none)"))

    elif args.cmd == "suggest-queue":
        kb = os.path.abspath(args.kb)
        suggested = suggest_owner_for_review_item(kb, args.rel)
        print("queue item %s in batch %s suggested owner: %s" % (args.rel, args.batch, suggested or "(none)"))

    return 0


if __name__ == "__main__":
    sys.exit(main())
