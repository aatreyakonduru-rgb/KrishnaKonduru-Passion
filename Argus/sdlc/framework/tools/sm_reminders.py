#!/usr/bin/env python3
"""The Scrum Master's reminders, asked straight to the person who owns the ticket.

The gaps are the Stand-up check rows (scrum_metrics.standup_rows) for the open sprint, for one person. Each code
has a question; an answer becomes a Jira change (due date, fix version) and a comment on the ticket naming the
question and the answer, shown as a preview and written only after the person types "approved" (--write).

    sm_reminders.py for --person NAME [--max 2]          the questions to ask them at the start of a session
    sm_reminders.py answer --key ACME-1 --by NAME (--due YYYY-MM-DD | --fix-version NAME | --note TEXT)
                           [--question TEXT] [--write]
"""
import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scrum_metrics  # noqa: E402

QUESTIONS = {
    "no_due_date": "{key} ({summary}) has been In Progress {days} days. When do you expect to close it? I can put the date on it as the due date.",
    "no_fix_version": "Defect {key} ({summary}) has no fix version. Which release will the fix ship in?",
    "close_story": "Every sub-task of {key} ({summary}) is closed. Shall the story be closed too, or what is left?",
    "no_time": "{key} ({summary}) is In Progress with no time logged. Could you log the hours spent so far?",
    "subtasks": "{key} ({summary}) has no sub-tasks yet. Shall I draft them from the story?",
    "open_subtasks": "{key} is {status} but some sub-tasks are still open. Should they be closed?",
}
ORDER = ["no_due_date", "no_fix_version", "close_story", "open_subtasks", "no_time", "subtasks"]


def questions_for(rows, name, most=2):
    mine = [r for r in rows if r.get("code") in QUESTIONS and scrum_metrics_norm(r.get("owner")) == scrum_metrics_norm(name)]
    mine.sort(key=lambda r: (ORDER.index(r["code"]), r["key"]))
    return [dict(r, question=QUESTIONS[r["code"]].format(**dict({"days": "", "status": ""}, **r))) for r in mine[:most]]


def scrum_metrics_norm(name):
    import re
    return "".join(sorted(re.findall(r"[a-z0-9]+", (name or "").lower())))


def answer_calls(key, by, due="", fix_version="", note="", question=""):
    fields = {}
    if due:
        datetime.date.fromisoformat(due)
        fields["duedate"] = due
    if fix_version:
        fields["fixVersions"] = [{"name": fix_version}]
    answer = due and "due date %s" % due or fix_version and "fix version %s" % fix_version or note
    if not answer:
        raise ValueError("give --due, --fix-version or --note")
    calls = []
    if fields:
        calls.append({"method": "PUT", "path": "/api/2/issue/%s" % key, "body": {"fields": fields}})
    calls.append({"method": "POST", "path": "/api/2/issue/%s/comment" % key, "body": {"body":
                  "Asked by Devin Cloud for the Scrum Master%s\nAnswer from %s: %s" % (
                      ": " + question if question else "", by, answer)}})
    return calls


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("for")
    f.add_argument("--person", required=True)
    f.add_argument("--max", type=int, default=2)
    a = sub.add_parser("answer")
    a.add_argument("--key", required=True)
    a.add_argument("--by", required=True)
    a.add_argument("--due", default="")
    a.add_argument("--fix-version", default="")
    a.add_argument("--note", default="")
    a.add_argument("--question", default="")
    a.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)
    import question_subtask
    client = question_subtask.JiraClient(dry_run=False)
    if args.cmd == "for":
        get = lambda path, **p: client.live("GET", path, **p)  # noqa: E731
        data = {"stories": scrum_metrics.search(get, "project = ACME AND sprint in openSprints() AND issuetype in "
                                                     "(Story, Defect, Bug)", scrum_metrics.STORY_FIELDS,
                                                expand="changelog"), "subtasks": []}
        print(json.dumps(questions_for(scrum_metrics.standup_rows(data), args.person, args.max), indent=1))
        return 0
    calls = answer_calls(args.key, args.by, args.due, args.fix_version, args.note, args.question)
    print(json.dumps(calls, indent=1))
    if not args.write:
        print("Preview only: run again with --write after they say approved.")
        return 0
    for c in calls:
        client.live(c["method"], c["path"], c["body"])
    print("written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
