#!/usr/bin/env python3
"""Daily gate-timeout sweep: find gates waiting longer than approval-gates.yaml allows and escalate.

For every session the store can see (tools/session_store.py: every owner's local home, the repo
owner dirs and the legacy dirs) the sweep reads approvals.yaml, finds gates that are still
pending/waiting, and compares the wait against the gate's `timeout_hours`. For each overdue gate it:

  1. writes an `escalated_at` / `escalation_count` stamp on the gate record so the same gate is
     not escalated twice in one day,
  2. records a `gate_escalated` metrics event (tools/metrics.py),
  3. when the gate record carries an `approval_subtask` (ACME-nnnn) and --live is given, posts a
     Jira comment on that sub-task naming the approver role, the roster owner and the wait time.

Because the local session home (~/.sdlc/sessions) lives on the machine that ran the stage, a fresh
daily-automation VM sees none of it. So the sweep also asks Jira directly (--jira): every open
approval sub-task (label Approval, unresolved) whose gate label `gate-<ID>` has a timeout_hours
older than the sub-task's creation time is escalated with the same comment, once per day (a
`gate-timeout-escalated-<date>` label marks it).

Without --live nothing leaves this machine: the report is printed and the Jira comment is shown as
a DRY-RUN request. Jira access reuses question_subtask.JiraClient (bearer auth, one /myself check,
no retries on 4xx). Snowflake and Artifactory are not involved.

  gate_timeouts.py [--live] [--jira] [--hours-grace N] [--json] [--report PATH]

Exit 0 when nothing is overdue, 1 when at least one gate was escalated (so an automation can
notice), 2 on error.
"""
import argparse
import datetime
import json
import os
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gates  # noqa: E402
import metrics  # noqa: E402
import session_store  # noqa: E402
from approval_subtask import APPROVAL_LABEL, GATE_LABEL_PREFIX, read_state  # noqa: E402
from question_subtask import JiraClient, PEOPLE_PATH, PROJECT, load_people, print_request  # noqa: E402

ESCALATED_LABEL_PREFIX = "gate-timeout-escalated-"


def now():
    return datetime.datetime.now(datetime.timezone.utc)


def roster_owner():
    primary = (session_store.load_yaml_file(PEOPLE_PATH).get("owner") or {}).get("primary")
    for person in load_people():
        if person.get("jira_user") == primary:
            return person
    return {"jira_user": primary, "name": primary or "(roster owner not set)"}


def approver_names(gate_def):
    names = []
    for approver in gate_def.get("approvers") or []:
        names.extend(approver.get("names") or [])
    return names


def escalation_text(row, gate_def, owner):
    return (
        "*Gate timeout* — %s%s on %s has been waiting %.0f h (limit %s h).\n"
        "*Needs:* %s (%s)\n*Escalated to:* %s\n"
        "Reply on the sub-task or in the Devin session with 'approved', 'rejected' or 'needs revision'."
        % (row["gate"], (" / " + row["story"]) if row.get("story") else "", row["requirement_id"],
           row["age_hours"], row["timeout_hours"], gate_def.get("required_role"),
           ", ".join(approver_names(gate_def)) or "no names on the gate", owner.get("name"))
    )


def sweep(hours_grace=0.0, live=False, today=None):
    defs = gates.gate_defs()
    owner = roster_owner()
    today = today or now().date().isoformat()
    escalated, skipped = [], []
    client = None
    for owner_slug, req_id, path in session_store.all_session_records():
        data = session_store.load_yaml_file(path)
        if not data:
            continue
        for rec in gates.flatten_records(data):
            status = (rec.get("status") or rec.get("decision") or "pending").lower()
            if status not in ("pending", "waiting"):
                continue
            gate_def = defs.get(rec.get("gate_id"))
            if not gate_def:
                continue
            since = rec.get("presented_at") or rec.get("timestamp")
            if not since:
                continue
            age = (now() - metrics.parse_ts(since)).total_seconds() / 3600
            limit = gate_def.get("timeout_hours") or 0
            if age <= limit + hours_grace:
                continue
            row = {"owner": owner_slug, "requirement_id": req_id, "story": rec.get("story_id"),
                   "gate": rec["gate_id"], "age_hours": round(age, 1), "timeout_hours": limit,
                   "approver_role": gate_def.get("required_role"), "subtask": rec.get("approval_subtask"),
                   "path": path}
            if (rec.get("escalated_at") or "")[:10] == today:
                skipped.append(row)
                continue
            stamp_escalation(path, rec["gate_id"], rec.get("story_id"))
            metrics.record("gate_escalated", req_id, gate=rec["gate_id"], story_id=rec.get("story_id"),
                           owner=owner_slug if owner_slug != "legacy" else None,
                           extra={"age_hours": row["age_hours"], "timeout_hours": limit})
            if row["subtask"]:
                body = {"body": escalation_text(row, gate_def, owner)}
                comment_path = "/api/2/issue/%s/comment" % urllib.parse.quote(row["subtask"])
                if live:
                    client = client or JiraClient(dry_run=False)
                    client.live("POST", comment_path, payload=body)
                else:
                    print_request("POST", comment_path, body)
            escalated.append(row)
    return escalated, skipped, owner


def parse_jira_ts(text):
    # Jira Data Center: 2026-09-20T10:00:00.000+0000
    return datetime.datetime.strptime(text[:19] + text[23:], "%Y-%m-%dT%H:%M:%S%z")


def sweep_jira(hours_grace=0.0, live=False, today=None, client=None):
    """Open approval sub-tasks in Jira past their gate's timeout. Works without any local session state.

    The search is a read; it runs whenever a token is present, live or not. The comment and the
    escalation label are writes and only happen with live=True — a dry run prints them instead."""
    defs = gates.gate_defs()
    owner = roster_owner()
    today = today or now().date().isoformat()
    jql = "project = %s AND labels = %s AND resolution = Unresolved ORDER BY created ASC" % (PROJECT, APPROVAL_LABEL)
    params = {"jql": jql, "fields": "summary,description,assignee,parent,created,labels", "maxResults": 200}
    if client is None:
        if not live and not os.environ.get("ACME_JIRA_TOKEN"):
            print_request("GET", "/api/2/search?" + urllib.parse.urlencode(params))
            return [], []
        client = JiraClient(dry_run=False)
    result = client.live("GET", "/api/2/search", **params) or {}
    escalated, skipped = [], []
    for issue in result.get("issues", []):
        fields = issue.get("fields") or {}
        labels = fields.get("labels") or []
        gate_id = next((l[len(GATE_LABEL_PREFIX):] for l in labels if l.startswith(GATE_LABEL_PREFIX)), None)
        gate_def = defs.get(gate_id)
        if not gate_def:
            continue
        try:
            state, _ = read_state(fields.get("description"))
        except (RuntimeError, ValueError):
            state = {}
        age = (now() - parse_jira_ts(fields["created"])).total_seconds() / 3600
        limit = gate_def.get("timeout_hours") or 0
        if age <= limit + hours_grace:
            continue
        row = {"owner": "jira", "requirement_id": state.get("requirement") or (fields.get("parent") or {}).get("key"),
               "story": state.get("story"), "gate": gate_id, "age_hours": round(age, 1), "timeout_hours": limit,
               "approver_role": gate_def.get("required_role"), "subtask": issue["key"],
               "assignee": (fields.get("assignee") or {}).get("name")}
        if ESCALATED_LABEL_PREFIX + today in labels:
            skipped.append(row)
            continue
        path = "/api/2/issue/%s" % urllib.parse.quote(issue["key"])
        comment = {"body": escalation_text(row, gate_def, owner)}
        label = {"update": {"labels": [{"add": ESCALATED_LABEL_PREFIX + today}]}}
        if live:
            client.live("POST", path + "/comment", payload=comment)
            client.live("PUT", path, payload=label)
            metrics.record("gate_escalated", row["requirement_id"], gate=gate_id, story_id=row["story"],
                           extra={"age_hours": row["age_hours"], "timeout_hours": limit, "subtask": issue["key"]})
        else:
            print_request("POST", path + "/comment", comment)
            print_request("PUT", path, label)
        escalated.append(row)
    return escalated, skipped


def stamp_escalation(path, gate_id, story_id):
    data = session_store.load_yaml_file(path)
    target = None
    phases = data.get("phases") or {}
    key = gates.phase_key(gate_id)
    if story_id:
        target = ((phases.get("stories") or {}).get(story_id) or {}).get(key)
    else:
        target = phases.get(key)
    if target is None:
        for rec in data.get("approvals") or data.get("gates") or []:
            if isinstance(rec, dict) and rec.get("gate_id") == gate_id:
                target = rec
    if target is None:
        return
    target["escalated_at"] = now().strftime("%Y-%m-%dT%H:%M:%SZ")
    target["escalation_count"] = int(target.get("escalation_count") or 0) + 1
    session_store.write_yaml_file(path, data)


def render(escalated, skipped, owner):
    if not escalated and not skipped:
        return "Gate timeouts: nothing overdue."
    lines = ["Gate timeouts — escalated to %s" % owner.get("name")]
    for row in escalated:
        lines.append("  %-22s %-9s %-34s %6.0fh > %sh  needs %s%s" % (
            row["requirement_id"], row.get("story") or "", row["gate"], row["age_hours"], row["timeout_hours"],
            row["approver_role"], ("  (" + row["subtask"] + ")") if row["subtask"] else ""))
    if skipped:
        lines.append("Already escalated today: " + ", ".join(
            "%s/%s" % (r["requirement_id"], r["gate"]) for r in skipped))
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--live", action="store_true", help="post the Jira comments (default: dry run)")
    parser.add_argument("--jira", action="store_true", help="also sweep open approval sub-tasks in Jira")
    parser.add_argument("--hours-grace", type=float, default=0.0)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--report", help="also write the text report to this path")
    args = parser.parse_args(argv)
    try:
        escalated, skipped, owner = sweep(args.hours_grace, args.live)
        if args.jira:
            more, more_skipped = sweep_jira(args.hours_grace, args.live)
            escalated += more
            skipped += more_skipped
    except (RuntimeError, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    text = json.dumps({"escalated": escalated, "skipped": skipped, "owner": owner.get("name")}, indent=1) \
        if args.json else render(escalated, skipped, owner)
    print(text)
    if args.report:
        with open(args.report, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    return 1 if escalated else 0


if __name__ == "__main__":
    sys.exit(main())
