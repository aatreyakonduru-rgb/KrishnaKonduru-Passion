#!/usr/bin/env python3
"""Hotfix fast lane for a production incident defect.

A production incident (a Defect whose summary ends "- PROD" and that carries an incident-INC… label,
jira-ticket-standards.yaml) may take one Tech Lead gate, HOTFIX_PLAN_CODE_APPROVAL, in place of SDLC_04 and
SDLC_05. The independent verifier runs on every hotfix, whatever the risk tier, and a follow-up review
sub-task is raised so the full review still happens after the fix is out.

    hotfix.py check    --key ACME-n                                    eligible for the lane?
    hotfix.py followup --key ACME-n --by NAME --reviewer NAME [--days 2] [--write]

followup prints the Jira sub-task it would create; --write creates it, only after "approved".
"""
import argparse
import datetime
import os
import sys
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import question_subtask as qs  # noqa: E402

GATE = "HOTFIX_PLAN_CODE_APPROVAL"
LABEL = "hotfix-review"
DEFECT_TYPES = ("Defect", "Bug")


def eligible(issue):
    f = issue.get("fields") or {}
    why = []
    if ((f.get("issuetype") or {}).get("name")) not in DEFECT_TYPES:
        why.append("not a Defect")
    if not (f.get("summary") or "").rstrip().endswith("- PROD"):
        why.append('summary does not end "- PROD"')
    if not any(str(l).startswith("incident-INC") for l in f.get("labels") or []):
        why.append("no incident-INC label")
    return not why, why


def due_after(start, days):
    d = start
    while days > 0:
        d += datetime.timedelta(days=1)
        if d.weekday() < 5:
            days -= 1
    return d


def followup_payload(key, by, reviewer, due):
    return {"fields": {
        "project": {"key": qs.PROJECT},
        "parent": {"key": key},
        "issuetype": {"id": qs.SUBTASK_TYPE},
        "labels": [LABEL],
        "assignee": {"name": reviewer},
        "duedate": due.isoformat(),
        "summary": "Review: follow-up review of hotfix %s" % key,
        "description": ("%s went out through the hotfix fast lane (%s, approved by %s). "
                        "Review the routing, the diff and the tests as SDLC_04 and SDLC_05 would have, "
                        "by %s." % (key, GATE, by, due.isoformat())),
    }}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--key", required=True)
    f = sub.add_parser("followup")
    f.add_argument("--key", required=True)
    f.add_argument("--by", required=True)
    f.add_argument("--reviewer", required=True)
    f.add_argument("--days", type=int, default=2)
    f.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "check":
        issue = qs.JiraClient(False).live("GET", "/api/2/issue/%s" % urllib.parse.quote(a.key),
                                          fields="summary,issuetype,labels")
        ok, why = eligible(issue)
        print("[SDLC] hotfix %s: %s" % (a.key, "eligible" if ok else "not eligible (%s)" % "; ".join(why)))
        return 0 if ok else 1
    payload = followup_payload(a.key, a.by, a.reviewer, due_after(datetime.date.today(), a.days))
    if not a.write:
        qs.print_request("POST", "/api/2/issue", payload)
        return 0
    print(qs.JiraClient(False).live("POST", "/api/2/issue", payload).get("key", "no key returned"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
