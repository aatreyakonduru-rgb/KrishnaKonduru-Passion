#!/usr/bin/env python3
"""Create, decide, delegate and poll Acme Claims approval sub-tasks.

An approval sub-task is how a gate decision leaves the chat and reaches a named person.
It carries everything the reviewer needs (gate, requirement, artifacts, criteria, the
numbered decision items) and every action against it is appended as a Jira comment, so the
sub-task is the audit trail. The current state travels in a JSON block at the end of the
description so a waiting session can poll it with `status` without parsing comments.

Every write supports --dry-run. Jira access reuses question_subtask.JiraClient: bearer auth,
one /myself validation, no retries on 4xx.
"""
import argparse
import datetime
import json
import os
import re
import sys
import urllib.error
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from question_subtask import (  # noqa: E402
    JiraClient, PROJECT, SUBTASK_TYPE, display_name, find_person, print_request, quote,
)

APPROVAL_LABEL = "Approval"
GATE_LABEL_PREFIX = "gate-"
REQUESTER_LABEL_PREFIX = "requested-by-"
STATE_MARKER = "APPROVAL-STATE"
APPROVE_WORDS = ("approved",)
DECISIONS = ("approve", "approve-with-notes", "reject")
ITEM_STATES = ("pending", "approved", "rejected", "delegated")


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def is_explicit_approval(text):
    """Only the word 'approved' (any case), alone or as the first word, unlocks a gate.

    'continue', 'ok', 'approve', 'looks good' are not approvals — the caller must ask again.
    """
    words = re.findall(r"[a-z]+", (text or "").lower())
    return bool(words) and words[0] in APPROVE_WORDS


def parse_items(value, count):
    """'1,2, 3' or '1-3' or 'all' -> sorted list of 1-based item numbers within count."""
    if not value or value.strip().lower() == "all":
        return list(range(1, count + 1))
    numbers = set()
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            low, high = part.split("-", 1)
            numbers.update(range(int(low), int(high) + 1))
        else:
            numbers.add(int(part))
    bad = [n for n in numbers if n < 1 or n > count]
    if bad:
        raise RuntimeError("item numbers out of range (1-%d): %s" % (count, ", ".join(map(str, sorted(bad)))))
    return sorted(numbers)


def state_block(state):
    return "\n\n{code:title=%s}\n%s\n{code}" % (STATE_MARKER, json.dumps(state, indent=2, sort_keys=True))


def read_state(description):
    match = re.search(r"\{code:title=%s\}\s*(\{.*?\})\s*\{code\}" % STATE_MARKER, description or "", re.S)
    if not match:
        raise RuntimeError("no %s block found in the sub-task description" % STATE_MARKER)
    return json.loads(match.group(1)), description[: match.start()].rstrip()


def overall(state):
    states = [item["state"] for item in state["items"]]
    if any(s == "rejected" for s in states):
        return "rejected"
    if all(s == "approved" for s in states):
        return "approved"
    return "pending"


def item_lines(items):
    return "\n".join(
        "# *[%d]* %s — _%s_%s" % (
            i + 1, item["text"], item["state"],
            (" (%s)" % item["by"]) if item.get("by") else "",
        )
        for i, item in enumerate(items)
    )


def build_description(head, state):
    return head + "\n\n*Decision items (current state):*\n" + item_lines(state["items"]) + state_block(state)


def create_payload(args, requester, assignee, items):
    requester_name = (requester or {}).get("displayName") or args.requested_by
    target_name = (assignee or {}).get("name") or args.assignee
    artifacts = "\n".join("* %s" % a for a in (args.artifact or [])) or "* (none listed)"
    criteria = "\n".join("* %s" % c for c in (args.criterion or [])) or "* (see approval-gates.yaml)"
    head = (
        "*Approval requested by:* %s (%s)\n"
        "*Gate:* %s — %s\n"
        "*Requirement:* %s%s\n"
        "*Parent story:* %s\n"
        "*Session:* %s\n\n"
        "*What you are approving:*\n%s\n\n"
        "*Artifacts under review:*\n%s\n\n"
        "*Approval criteria:*\n%s\n\n"
        "*If rejected:* %s\n\n"
        "*How to decide:* open /dashboard and use Approve / Approve with notes / Reject / "
        "Send to someone else on each numbered item, or comment here with the word *approved* "
        "(any case) and the item numbers. Anything else — including \"continue\" — is not an approval."
    ) % (
        requester_name, args.requested_by, args.gate, args.gate_name or args.gate,
        args.requirement, (" / " + args.story) if args.story else "",
        args.parent, args.session_url or "(not supplied)",
        quote(args.summary_text), artifacts, criteria, args.consequence or "the stage does not advance",
    )
    state = {
        "gate": args.gate,
        "requirement": args.requirement,
        "story": args.story,
        "parent": args.parent,
        "requested_by": args.requested_by,
        "created": now(),
        "items": [{"n": i + 1, "text": text, "state": "pending", "by": None, "note": None, "at": None}
                  for i, text in enumerate(items)],
        "history": [{"at": now(), "action": "created", "by": args.requested_by, "to": target_name,
                     "items": list(range(1, len(items) + 1)), "note": None}],
        "overall": "pending",
    }
    return {
        "fields": {
            "project": {"key": PROJECT},
            "parent": {"key": args.parent},
            "issuetype": {"id": SUBTASK_TYPE},
            "labels": [APPROVAL_LABEL, GATE_LABEL_PREFIX + args.gate, REQUESTER_LABEL_PREFIX + args.requested_by],
            "assignee": {"name": target_name},
            "summary": "Approval [%s] %s: %s" % (args.gate, args.requirement, (args.gate_name or args.gate)[:120]),
            "description": build_description(head, state),
        }
    }


def resolve(client, value, dry_run):
    if dry_run:
        return {"name": value, "displayName": display_name(value)}
    return find_person(client, value)


def do_create(args):
    items = args.item or ["Approve %s as presented" % args.gate]
    client = JiraClient(args.dry_run)
    requester = resolve(client, args.requested_by, args.dry_run)
    import time_off
    args.assignee, why = time_off.reroute(args.assignee, "approval")
    if "named no backup" in why:
        import gates
        gate = gates.gate_defs().get(args.gate) or {}
        names, notes = gates.approver_route(gate)
        others = [n for n in names if time_off.norm(n) != time_off.norm(display_name(args.assignee))]
        if others:
            args.assignee, why = others[0], "%s; %s gets it from the gate's approvers and backups" % (why, others[0])
    if why:
        print("[SDLC] decision route approval — %s" % why, file=sys.stderr)
    assignee = resolve(client, args.assignee, args.dry_run)
    payload = create_payload(args, requester, assignee, items)
    if args.dry_run:
        print_request("POST", "/api/2/issue", payload)
        return 0
    result = client.live("POST", "/api/2/issue", payload)
    print(result.get("key", "Jira did not return a created issue key"))
    return 0


def fetch(client, key):
    return client.live("GET", "/api/2/issue/%s" % urllib.parse.quote(key), fields="summary,description,assignee,parent,labels")


def audit_comment(action, actor, items, note, target=None, decision=None):
    who = display_name(actor)
    lines = ["*%s by %s* — %s" % (action.capitalize(), who, now())]
    if decision:
        lines.append("*Decision:* %s" % decision)
    lines.append("*Items:* %s" % ", ".join("[%d]" % n for n in items))
    if target:
        lines.append("*Assigned to:* %s" % display_name(target))
    lines.append("*Comment:* %s" % (note or "(none)"))
    return {"body": "\n".join(lines)}


def apply(client, args, key, action, decision=None, target=None):
    """Shared decide/delegate: update state, comment, reassign if needed, close when done."""
    path = "/api/2/issue/%s" % urllib.parse.quote(key)
    if args.dry_run:
        items = parse_items(args.items, 99) if args.items and args.items.lower() != "all" else [0]
        print_request("POST", path + "/comment",
                      audit_comment(action, args.by, items, args.note, target, decision))
        if target:
            print_request("PUT", path + "/assignee", {"name": target})
        print("Would rewrite the %s block in the description and close the sub-task once every item is approved." % STATE_MARKER)
        return {"overall": "dry-run"}
    data = fetch(client, key)
    state, head = read_state((data.get("fields") or {}).get("description"))
    items = parse_items(args.items, len(state["items"]))
    new_state = {"approve": "approved", "approve-with-notes": "approved", "reject": "rejected"}.get(decision, "delegated")
    for n in items:
        item = state["items"][n - 1]
        item.update({"state": new_state, "by": args.by if new_state != "delegated" else target,
                     "note": args.note, "at": now()})
    state["history"].append({"at": now(), "action": action, "by": args.by, "to": target,
                             "decision": decision, "items": items, "note": args.note})
    state["overall"] = overall(state)
    head = re.sub(r"\n\n\*Decision items \(current state\):\*.*\Z", "", head, flags=re.S)
    client.live("PUT", path, {"fields": {"description": build_description(head, state)}})
    client.live("POST", path + "/comment", audit_comment(action, args.by, items, args.note, target, decision))
    if target:
        client.live("PUT", path + "/assignee", {"name": target})
    parent = ((data.get("fields") or {}).get("parent") or {}).get("key")
    if parent:
        client.live("POST", "/api/2/issue/%s/comment" % parent, {
            "body": "*Approval sub-task %s — %s* items %s by %s → overall *%s*" % (
                key, action, ", ".join("[%d]" % n for n in items), display_name(args.by), state["overall"])})
    if state["overall"] in ("approved", "rejected"):
        close(client, path)
    return state


def close(client, path):
    transitions = (client.live("GET", path + "/transitions") or {}).get("transitions", [])
    preferred = {"close": 0, "done": 1, "resolve": 2}
    choices = sorted((t for t in transitions if (t.get("name") or "").lower() in preferred),
                     key=lambda t: preferred[(t.get("name") or "").lower()])
    if choices:
        client.live("POST", path + "/transitions", {"transition": {"id": choices[0]["id"]}})


def do_decide(args):
    if args.decision not in DECISIONS:
        raise RuntimeError("--decision must be one of: %s" % ", ".join(DECISIONS))
    if args.decision in ("approve-with-notes", "reject") and not args.note:
        raise RuntimeError("--note is required for %s" % args.decision)
    if args.decision == "approve" and args.said is not None and not is_explicit_approval(args.said):
        raise RuntimeError("%r is not an explicit approval — the reviewer must say 'approved'" % args.said)
    client = JiraClient(args.dry_run)
    state = apply(client, args, args.key, "decision", decision=args.decision)
    print("%s: %s items %s → overall %s" % (args.key, args.decision, args.items or "all", state["overall"]))
    return 0


def do_delegate(args):
    if not args.note:
        raise RuntimeError("--note is required when sending an approval to someone else")
    client = JiraClient(args.dry_run)
    target = resolve(client, args.to, args.dry_run)["name"]
    state = apply(client, args, args.key, "delegated", target=target)
    print("%s: items %s sent to %s → overall %s" % (args.key, args.items or "all", display_name(target), state["overall"]))
    return 0


def do_status(args):
    """Print the state block as JSON. Exit 0 = approved, 3 = pending, 4 = rejected."""
    client = JiraClient(False)
    data = fetch(client, args.key)
    state, _ = read_state((data.get("fields") or {}).get("description"))
    state["assignee"] = ((data.get("fields") or {}).get("assignee") or {}).get("name")
    print(json.dumps(state, indent=2, sort_keys=True))
    return {"approved": 0, "pending": 3, "rejected": 4}[state["overall"]]


def do_list(args):
    client = JiraClient(False)
    jql = ('project = %s AND labels = %s AND assignee = "%s" AND resolution = Unresolved ORDER BY created ASC'
           % (PROJECT, APPROVAL_LABEL, args.user))
    result = client.live("GET", "/api/2/search", jql=jql,
                         fields="summary,description,assignee,parent,created,updated,status,labels", maxResults=100)
    rows = []
    for issue in result.get("issues", []):
        fields = issue.get("fields") or {}
        try:
            state, _ = read_state(fields.get("description"))
        except (RuntimeError, ValueError):
            state = {"items": [], "gate": "", "requirement": ""}
        rows.append({
            "key": issue.get("key"), "summary": fields.get("summary"),
            "parent": (fields.get("parent") or {}).get("key"), "created": fields.get("created"),
            "gate": state.get("gate"), "requirement": state.get("requirement"), "story": state.get("story"),
            "items": [{"n": i.get("n"), "text": i.get("text"), "state": i.get("state")} for i in state.get("items", [])],
        })
    print(json.dumps(rows, indent=2))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create", help="raise an approval sub-task under a story")
    create.add_argument("--parent", required=True, help="Acme Claims story key")
    create.add_argument("--assignee", required=True, help="who must approve")
    create.add_argument("--requested-by", required=True, help="Jira username of the session owner")
    create.add_argument("--gate", required=True, help="e.g. SDLC_01_INTAKE_CLARIFICATION")
    create.add_argument("--gate-name")
    create.add_argument("--requirement", required=True, help="REQ-ID")
    create.add_argument("--story")
    create.add_argument("--summary-text", required=True, help="the gate content the reviewer decides on")
    create.add_argument("--item", action="append", help="one numbered decision item; repeatable")
    create.add_argument("--artifact", action="append", help="session-relative artifact path; repeatable")
    create.add_argument("--criterion", action="append", help="approval criterion; repeatable")
    create.add_argument("--consequence")
    create.add_argument("--session-url")
    create.add_argument("--dry-run", action="store_true")
    decide = sub.add_parser("decide", help="approve / approve-with-notes / reject numbered items")
    decide.add_argument("--key", required=True)
    decide.add_argument("--decision", required=True, choices=DECISIONS)
    decide.add_argument("--items", default="all", help="e.g. 1,2,3 or 1-3 or all")
    decide.add_argument("--by", required=True, help="Jira username of the approver")
    decide.add_argument("--note")
    decide.add_argument("--said", help="the reviewer's literal words; must start with 'approved' to approve")
    decide.add_argument("--dry-run", action="store_true")
    delegate = sub.add_parser("delegate", help="send numbered items to someone else (note required)")
    delegate.add_argument("--key", required=True)
    delegate.add_argument("--items", default="all")
    delegate.add_argument("--to", required=True)
    delegate.add_argument("--by", required=True)
    delegate.add_argument("--note", required=True)
    delegate.add_argument("--dry-run", action="store_true")
    status = sub.add_parser("status", help="print state; exit 0 approved, 3 pending, 4 rejected")
    status.add_argument("--key", required=True)
    listing = sub.add_parser("list", help="open approvals assigned to a user")
    listing.add_argument("--user", required=True)
    args = parser.parse_args(argv)
    try:
        return {"create": do_create, "decide": do_decide, "delegate": do_delegate,
                "status": do_status, "list": do_list}[args.command](args)
    except (RuntimeError, urllib.error.URLError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
