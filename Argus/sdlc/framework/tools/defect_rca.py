#!/usr/bin/env python3
"""Defect root cause and escape analysis for SIT and UAT defects.

Per defect: the story it is linked to, the files its fix changed (commits naming the defect key), which of
them the link-graph walk from the story's files did not predict (verifier.missed_impacts), the stage that
should have caught it, and the root cause the fixer gave. The root cause is asked of the fixer when the
defect closes and kept as a Jira comment "Root cause: <category> — <note>", written only after "approved".

    defect_rca.py rows                               open and recently closed SIT/UAT defects (Jira read)
    defect_rca.py cause --key ACME-1 --by NAME --category code [--note TEXT] [--write]
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import defects_by_specialty as dbs  # noqa: E402

CATEGORIES = ("requirement", "design", "code", "data", "environment", "test gap")
SHOULD_CATCH = {"SIT": "unit tests and code review (SDLC_05)", "UAT": "SIT testing (SDLC_06)",
                "PRODUCTION": "UAT"}
CAUSE_RE = re.compile(r"^Root cause:\s*([a-z ]+?)\s*(?:—|-)\s*(.*)$", re.I | re.M)
JQL = ('project = ACME AND issuetype in (Defect, Bug) AND (resolution = Unresolved OR resolved >= -30d) '
       'AND "Detected In" in ("TEST - System Integration Test (SIT)", "TEST - User Acceptance Test (UAT)")')
QUESTION = ("{key} is closed. What was the root cause: requirement, design, code, data, environment or test gap? "
            "One line on why helps the next story.")


def stage_of(detected):
    d = (detected or "").upper()
    return "UAT" if "UAT" in d else "SIT" if "SIT" in d else "PRODUCTION" if "PRODUCTION" in d else ""


def cause_from(comments):
    for c in reversed(comments or []):
        m = CAUSE_RE.search(c.get("body") or "")
        if m:
            return m.group(1).lower(), m.group(2).strip()
    return "", ""


def row(issue, missed=None):
    f = issue.get("fields") or {}
    stage = stage_of(dbs.value_of(f.get(dbs.F_DETECTED)))
    cat, why = cause_from(((f.get("comment") or {}).get("comments")))
    stories = [k for k, _ in dbs.linked(f)]
    return {"key": issue["key"], "summary": f.get("summary", ""), "stage": stage,
            "should_catch": SHOULD_CATCH.get(stage, ""), "story": stories[0] if stories else "",
            "resolved": bool(f.get("resolution")), "cause": cat, "cause_note": why,
            "missed": missed or [], "ask": bool(f.get("resolution")) and not cat}


def cause_call(key, by, category, note=""):
    if category not in CATEGORIES:
        raise ValueError("category is one of: %s" % ", ".join(CATEGORIES))
    return {"method": "POST", "path": "/api/2/issue/%s/comment" % key,
            "body": {"body": "Root cause: %s — %s\n(from %s, asked by Devin Cloud)" % (category, note or "no note", by)}}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("rows")
    c = sub.add_parser("cause")
    c.add_argument("--key", required=True)
    c.add_argument("--by", required=True)
    c.add_argument("--category", required=True, choices=CATEGORIES)
    c.add_argument("--note", default="")
    c.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)
    import question_subtask
    import verifier
    client = question_subtask.JiraClient(dry_run=False)
    if args.cmd == "cause":
        call = cause_call(args.key, args.by, args.category, args.note)
        print(json.dumps(call, indent=1))
        if args.write:
            client.live(call["method"], call["path"], call["body"])
            print("written")
        else:
            print("Preview only: run again with --write after they say approved.")
        return 0
    page = client.live("GET", "/api/2/search", jql=JQL, maxResults=200,
                       fields="summary,resolution,issuelinks,comment,%s" % dbs.F_DETECTED)
    graph = verifier.confidence.link_graph.Graph(verifier.confidence.link_graph.load())
    out = []
    for issue in page.get("issues") or []:
        r = row(issue)
        if r["story"]:
            r["missed"] = verifier.missed_impacts(r["story"], [issue["key"]], graph)["defects"][0]["missed"]
        out.append(r)
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
