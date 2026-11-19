#!/usr/bin/env python3
"""QA scenario helper for the ACME/claims-qa Behave suite — read-only against the QA repo.

/qa-scenarios drafts Gherkin from a story's acceptance criteria. This tool keeps the draft
honest: it knows which step sentences the suite already implements, which query keys and
test-data sets exist, which tags are taken, and which ACs a draft actually covers.

    python3 qa_scenarios.py inventory --qa-repo ~/repos/survey/claims-qa [--json]
    python3 qa_scenarios.py steps --qa-repo ... --grep contract          # find reusable steps
    python3 qa_scenarios.py next-tag --qa-repo ... --prefix ACME_Contract_
    python3 qa_scenarios.py check DRAFT.feature --qa-repo ... [--ac AC-1 AC-2 | --spec SPEC.md]

`check` exits 1 when a step has no step definition, a query key or
test-data set is unknown, a numbered scenario tag (@X_03) is already taken, an AC is uncovered, or an Examples cell looks like PHI.
Coverage is read from comments above each scenario:  # covers: AC-1, AC-3
The suite uses behave's default `parse` matcher ({name} placeholders); that is what we match.
"""
import argparse
import ast
import json
import os
import re
import sys

UNIQUE_TAG = re.compile(r"^\w+?_\d+$")  # scenario ids such as @ACME_Contract_03
KEYWORDS = ("Given ", "When ", "Then ", "And ", "But ", "* ")
DECORATORS = ("step", "given", "when", "then")
PHI_PATTERNS = [
    ("SSN-like", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("long number (member/subscriber id?)", re.compile(r"\b\d{9,}\b")),
    ("email address", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")),
    ("date of birth-like", re.compile(r"\b(19|20)\d{2}-\d{2}-\d{2}\b|\b\d{2}/\d{2}/(19|20)\d{2}\b")),
]


def pattern_to_regex(pattern):
    """behave parse pattern -> anchored regex. {name} / {name:d} match any non-empty text."""
    out, pos = [], 0
    for m in re.finditer(r"\{[^{}]*\}", pattern):
        out.append(re.escape(pattern[pos:m.start()]))
        out.append("(.+?)")
        pos = m.end()
    out.append(re.escape(pattern[pos:]))
    return re.compile("^" + "".join(out) + "$")


def load_steps(qa_repo):
    steps = []
    root = os.path.join(qa_repo, "features", "steps")
    for dirpath, _, files in os.walk(root):
        for name in sorted(files):
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    tree = ast.parse(fh.read())
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for dec in node.decorator_list:
                    fname = (dec.func.id if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name) else
                             dec.func.attr if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) else "")
                    if (fname.lower() in DECORATORS
                            and dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str)):
                        pat = dec.args[0].value
                        steps.append({"pattern": pat, "keyword": fname.lower(), "function": node.name,
                                      "file": os.path.relpath(path, qa_repo), "line": dec.lineno,
                                      "regex": pattern_to_regex(pat)})
    return steps


def load_queries(qa_repo):
    queries = {}
    root = os.path.join(qa_repo, "features", "databaseQueries")
    if not os.path.isdir(root):
        return queries
    for name in sorted(os.listdir(root)):
        if not name.endswith((".txt", ".json")):
            continue
        try:
            with open(os.path.join(root, name), encoding="utf-8") as fh:
                data = json.load(fh)
        except (ValueError, UnicodeDecodeError):
            continue
        if isinstance(data, dict):
            for key, sql in data.items():
                tables = sorted(set(re.findall(r"\b(?:FROM|JOIN)\s+([A-Za-z_][\w.]*)", str(sql), re.I)))
                queries[key] = {"file": "features/databaseQueries/" + name, "tables": tables}
    return queries


def load_test_data(qa_repo):
    data_sets, mappings = {}, []
    root = os.path.join(qa_repo, "TestData")
    if not os.path.isdir(root):
        return data_sets, mappings
    for name in sorted(os.listdir(root)):
        path = os.path.join(root, name)
        if name.lower().endswith(".json"):
            try:
                with open(path, encoding="utf-8") as fh:
                    data = json.load(fh)
            except (ValueError, UnicodeDecodeError):
                continue
            if isinstance(data, dict):
                for key in data:
                    data_sets[key] = "TestData/" + name
        elif name.endswith("_Field_Mapping.py"):
            mappings.append("TestData/" + name)
    return data_sets, mappings


def load_tags(qa_repo):
    tags = {}
    root = os.path.join(qa_repo, "features")
    for dirpath, _, files in os.walk(root):
        for name in files:
            if name.endswith(".feature"):
                path = os.path.join(dirpath, name)
                with open(path, encoding="utf-8", errors="replace") as fh:
                    for i, line in enumerate(fh, 1):
                        if line.strip().startswith("@"):
                            for tag in re.findall(r"@([\w-]+)", line):
                                tags.setdefault(tag, "%s:%d" % (os.path.relpath(path, qa_repo), i))
    return tags


def inventory(qa_repo):
    data_sets, mappings = load_test_data(qa_repo)
    return {"steps": load_steps(qa_repo), "queries": load_queries(qa_repo), "test_data": data_sets,
            "field_mappings": mappings, "tags": load_tags(qa_repo)}


def match_step(text, steps):
    for s in steps:
        if s["regex"].match(text):
            return s
    return None


def next_tag(prefix, tags):
    nums = [int(m.group(1)) for t in tags for m in [re.match(re.escape(prefix) + r"(\d+)$", t)] if m]
    width = max([len(re.match(re.escape(prefix) + r"(\d+)$", t).group(1)) for t in tags
                 if re.match(re.escape(prefix) + r"(\d+)$", t)] or [2])
    return "%s%0*d" % (prefix, width, (max(nums) + 1) if nums else 1)


def parse_feature(text):
    """Scenarios with their tags, covered ACs, steps and Examples rows."""
    scenarios, pending_tags, pending_covers, cur, header = [], [], [], None, None
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            m = re.match(r"#\s*covers?:\s*(.+)$", line, re.I)
            if m:
                pending_covers += [a.strip() for a in re.split(r"[,\s]+", m.group(1)) if a.strip()]
            continue
        if line.startswith("@"):
            pending_tags += re.findall(r"@([\w-]+)", line)
            continue
        if re.match(r"(Scenario|Scenario Outline|Scenario Template):", line):
            cur = {"name": line.split(":", 1)[1].strip(), "line": n, "tags": pending_tags,
                   "covers": pending_covers, "steps": [], "examples": []}
            scenarios.append(cur)
            pending_tags, pending_covers, header = [], [], None
            continue
        if line.startswith(("Feature:", "Background:", "Rule:")):
            pending_tags, cur, header = ([] if line.startswith("Feature:") else pending_tags), (
                None if line.startswith("Feature:") else {"name": "Background", "line": n, "tags": [],
                                                          "covers": [], "steps": [], "examples": [], "background": True}), None
            if cur:
                scenarios.append(cur)
            continue
        if line.startswith("Examples:"):
            header = []
            continue
        if cur is None:
            continue
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if header == []:
                header = cells
            elif header:
                cur["examples"].append(dict(zip(header, cells)))
            continue
        for kw in KEYWORDS:
            if line.startswith(kw):
                cur["steps"].append({"text": line[len(kw):].strip(), "line": n})
                break
    return scenarios


def ac_ids_from_spec(path):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    return sorted(set(re.findall(r"\bAC-\d+\b", text)), key=lambda a: int(a.split("-")[1]))


def check_draft(text, inv, acs=None):
    scenarios = parse_feature(text)
    problems, report = [], {"steps": [], "tags": [], "data": [], "coverage": {}, "phi": []}
    seen_tags = {}
    for sc in scenarios:
        for st in sc["steps"]:
            hit = match_step(st["text"], inv["steps"])
            report["steps"].append({"line": st["line"], "text": st["text"],
                                    "match": "%s:%d" % (hit["file"], hit["line"]) if hit else None})
            if not hit:
                problems.append("line %d: no step definition for '%s'" % (st["line"], st["text"]))
        for tag in sc["tags"]:
            if not UNIQUE_TAG.match(tag):
                continue  # group tags such as @Contract_Information are meant to be shared
            if tag in inv["tags"]:
                problems.append("line %d: tag @%s already used at %s" % (sc["line"], tag, inv["tags"][tag]))
            if tag in seen_tags:
                problems.append("line %d: tag @%s used twice in this draft" % (sc["line"], tag))
            seen_tags[tag] = sc["line"]
        for row in sc["examples"]:
            for col, val in row.items():
                if val in inv["queries"] or val in inv["test_data"]:
                    report["data"].append({"value": val, "found": inv["queries"].get(val, {}).get("file")
                                           or inv["test_data"].get(val)})
                elif re.match(r"^[A-Z][A-Za-z]+(_[A-Za-z0-9]+)+$", val) or re.match(r"^[A-Z][A-Za-z]+_\d+$", val):
                    report["data"].append({"value": val, "found": None})
                    problems.append("scenario '%s': Examples value '%s' (%s) is not a known query key or "
                                    "TestData set — add it or mark it NEW in the draft" % (sc["name"], val, col))
                for label, rx in PHI_PATTERNS:
                    if rx.search(val):
                        report["phi"].append({"scenario": sc["name"], "column": col, "why": label})
                        problems.append("scenario '%s': Examples column '%s' looks like %s — use synthetic data"
                                        % (sc["name"], col, label))
    covered = {}
    for sc in scenarios:
        for ac in sc["covers"]:
            covered.setdefault(ac, []).append(sc["name"])
    for ac in acs or []:
        report["coverage"][ac] = covered.get(ac, [])
        if not covered.get(ac):
            problems.append("%s is not covered by any scenario (add '# covers: %s' or say why not)" % (ac, ac))
    for ac in covered:
        if acs and ac not in acs:
            problems.append("draft claims to cover %s, which is not in the acceptance criteria" % ac)
        report["coverage"].setdefault(ac, covered[ac])
    report["scenarios"] = len([s for s in scenarios if not s.get("background")])
    return report, problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--qa-repo", default=os.environ.get("CLAIMS_QA_REPO", os.path.expanduser("~/repos/claims-qa")))
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("inventory")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("steps")
    p.add_argument("--grep", default="")
    p = sub.add_parser("next-tag")
    p.add_argument("--prefix", required=True)
    p = sub.add_parser("check")
    p.add_argument("draft")
    p.add_argument("--ac", nargs="*")
    p.add_argument("--spec")
    p.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if not os.path.isdir(os.path.join(args.qa_repo, "features")):
        print("QA repo not found at %s (clone ACME/claims-qa or pass --qa-repo)" % args.qa_repo)
        return 2
    inv = inventory(args.qa_repo)
    if args.command == "inventory":
        if args.json:
            out = dict(inv, steps=[{k: v for k, v in s.items() if k != "regex"} for s in inv["steps"]])
            print(json.dumps(out, indent=2))
        else:
            print("step definitions: %d" % len(inv["steps"]))
            print("query keys:       %d (%s)" % (len(inv["queries"]), ", ".join(sorted({q["file"] for q in inv["queries"].values()}))))
            print("TestData sets:    %d" % len(inv["test_data"]))
            print("field mappings:   %d" % len(inv["field_mappings"]))
            print("tags in use:      %d" % len(inv["tags"]))
    elif args.command == "steps":
        needle = args.grep.lower()
        for s in inv["steps"]:
            if needle in s["pattern"].lower():
                print("%-70s %s:%d" % (s["pattern"][:70], s["file"], s["line"]))
    elif args.command == "next-tag":
        print("@" + next_tag(args.prefix, inv["tags"]))
    elif args.command == "check":
        acs = args.ac or (ac_ids_from_spec(args.spec) if args.spec else None)
        with open(args.draft, encoding="utf-8") as fh:
            report, problems = check_draft(fh.read(), inv, acs)
        if args.json:
            print(json.dumps({"report": report, "problems": problems}, indent=2))
        else:
            reused = sum(1 for s in report["steps"] if s["match"])
            print("scenarios: %d   steps reused: %d/%d" % (report["scenarios"], reused, len(report["steps"])))
            for ac, names in sorted(report["coverage"].items()):
                print("  %-6s %s" % (ac, "; ".join(names) if names else "NOT COVERED"))
            for pr in problems:
                print("PROBLEM: " + pr)
            print("OK" if not problems else "%d problem(s)" % len(problems))
            print("[SDLC] qa %s — matched %d of %d steps to the step library of %s (%d step definitions, %d query keys, "
                  "%d TestData sets); why: a draft reuses the suite's steps instead of inventing them; result: %s"
                  % (os.path.basename(args.draft), reused, len(report["steps"]), args.qa_repo and "ACME/claims-qa",
                     len(inv["steps"]), len(inv["queries"]), len(inv["test_data"]), "gaps" if problems else "matched"))
        return 1 if problems else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
