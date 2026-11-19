#!/usr/bin/env python3
"""Create, answer, close and list Acme Claims question sub-tasks, hand work over, and raise observations.

These are the three round trips the /dashboard page can produce: answering a question,
delegating an item to someone else, and raising an observation, defect or risk against a story.
Every write is explicit and supports --dry-run. Jira access uses bearer auth and validates
the token once against /myself before any other live request.
"""
import argparse
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

try:
    import yaml
except ImportError:  # pragma: no cover - the repository already supplies PyYAML
    yaml = None

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
JIRA = (os.environ.get("SDLC_SANDBOX_URL") or "https://jira.acme.example").rstrip("/") + "/rest"
PROJECT = "ACME"
QUESTION_LABEL = "Question"
# Jira stamps the service account as reporter, so the asker travels on a label.
ASKER_LABEL_PREFIX = "asked-by-"
SUBTASK_TYPE = "10112"
PEOPLE_PATH = os.path.join(ROOT, ".devin", "rules", "people.yaml")

# Verified against /rest/api/2/issue/createmeta/Acme Claims/issuetypes/<id> on Jira DC 11.3.10.
OBSERVATION_TYPES = {"observation": "12600", "defect": "11", "risk": "11003"}
DETECTED_IN_FIELD = "customfield_10021"
SEVERITY_FIELD = "customfield_10013"
RISK_LEVEL_FIELD = "customfield_10014"
IMPEDIMENT_FIELD = "customfield_10015"
SEVERITIES = (
    "Critical", "High", "Medium", "Low", "Cosmetic Issue", "Performance Issue",
    "Security Issue", "Fails, no workaround", "Fails, workaround available",
)
DETECTED_IN = (
    "Dev", "TEST - System Integration Test (SIT)", "TEST - User Acceptance Test (UAT)",
    "TEST - Continuous Integration", "TEST - End-to-End (E2E)", "TEST - Performance",
    "Preview", "STAGE / PRE-PRODUCTION", "PRODUCTION - Dark Release", "PRODUCTION - Warranty",
)
RISK_LEVELS = ("1 - High", "2 - Moderate", "3 - Low", "4 - Minimal")
SEVERITY_TO_RISK = {
    "critical": "1 - High", "security issue": "1 - High", "high": "1 - High",
    "fails, no workaround": "1 - High", "medium": "2 - Moderate",
    "fails, workaround available": "2 - Moderate", "performance issue": "2 - Moderate",
    "low": "3 - Low", "cosmetic issue": "4 - Minimal",
}
RELATES_LINK = "Relates"


def _ctx():
    return ssl._create_unverified_context()


class JiraClient:
    def __init__(self, dry_run=False):
        self.dry_run = dry_run
        self.token = os.environ.get("ACME_JIRA_TOKEN")
        self.validated = False
        if not dry_run and not self.token:
            raise RuntimeError("ACME_JIRA_TOKEN is not set — use --dry-run or configure Jira auth.")

    def request(self, method, path, payload=None, **params):
        url = JIRA + path
        if params:
            url += ("&" if "?" in path else "?") + urllib.parse.urlencode(params)
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8") if payload is not None else None,
            method=method,
            headers={
                "Authorization": "Bearer " + self.token,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, context=_ctx(), timeout=120) as response:
                raw = response.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise RuntimeError(
                    "Jira returned %d. The service account token is invalid or locked; "
                    "it must be rotated or reset by an admin. Not retrying." % exc.code
                ) from exc
            detail = exc.read().decode("utf-8", "replace")
            raise RuntimeError("Jira returned %d: %s" % (exc.code, detail[:400])) from exc

    def live(self, method, path, payload=None, **params):
        if self.dry_run:
            return None
        if not self.validated:
            self.request("GET", "/api/2/myself")
            self.validated = True
        return self.request(method, path, payload, **params)


def load_people():
    if not yaml:
        return []
    try:
        with open(PEOPLE_PATH, encoding="utf-8") as fh:
            return (yaml.safe_load(fh) or {}).get("people", [])
    except FileNotFoundError:
        return []


def display_name(username):
    for person in load_people():
        if person.get("jira_user") == username:
            return person.get("name") or username
    return username


def issue_summary(question):
    first = " ".join(question.strip().split())
    return first[:200]


def quote(text):
    return "{quote}%s{quote}" % text


def assignable(client, fragment):
    result = client.live("GET", "/api/2/user/assignable/search", project=PROJECT, username=fragment)
    return result or []


def find_person(client, value, required=True):
    if not value:
        if required:
            raise RuntimeError("a Jira username or name fragment is required")
        return None
    for person in load_people():
        if person.get("jira_user") == value:
            return {"name": value, "displayName": person.get("name") or value}
    matches = assignable(client, value)
    exact = [p for p in matches if p.get("name") == value]
    if exact:
        return exact[0]
    if len(matches) == 1:
        return matches[0]
    lowered = value.lower()
    named = [p for p in matches if lowered in (p.get("displayName") or "").lower()]
    if len(named) == 1:
        return named[0]
    if required:
        raise RuntimeError("could not resolve %r via Acme Claims assignable/search" % value)
    return None


def asker_of(data):
    fields = data.get("fields") or {}
    for label in fields.get("labels") or []:
        if label.startswith(ASKER_LABEL_PREFIX):
            return label[len(ASKER_LABEL_PREFIX):]
    return (fields.get("reporter") or {}).get("name")


def create_payload(args, asker, assignee):
    asker_name = (asker or {}).get("displayName") or args.asker
    target_name = (assignee or {}).get("name") or args.assignee
    session = args.session_url or "(not supplied)"
    description = (
        "*Asked by:* %s (%s)\n"
        "*Story:* %s\n"
        "*Question:*\n"
        "%s\n"
        "*Answer here or via /dashboard.*\n"
        "Session: %s"
    ) % (asker_name, args.asker, args.parent, quote(args.question), session)
    return {
        "fields": {
            "project": {"key": PROJECT},
            "parent": {"key": args.parent},
            "issuetype": {"id": SUBTASK_TYPE},
            "labels": [QUESTION_LABEL, ASKER_LABEL_PREFIX + args.asker],
            "assignee": {"name": target_name},
            "summary": "Question from %s: %s" % (asker_name, issue_summary(args.question)),
            "description": description,
        }
    }


def print_request(method, path, payload=None):
    print(json.dumps({"method": method, "url": JIRA + path, "json": payload}, indent=2, sort_keys=True))


def do_create(args):
    client = JiraClient(args.dry_run)
    asker = find_person(client, args.asker) if not args.dry_run else {"name": args.asker, "displayName": display_name(args.asker)}
    import time_off
    args.assignee, why = time_off.reroute(args.assignee, "question")
    if why:
        print("[SDLC] decision route question — %s" % why, file=sys.stderr)
    assignee = find_person(client, args.assignee) if not args.dry_run else {"name": args.assignee, "displayName": display_name(args.assignee)}
    payload = create_payload(args, asker, assignee)
    if args.dry_run:
        print_request("POST", "/api/2/issue", payload)
        return 0
    result = client.live("POST", "/api/2/issue", payload)
    print(result.get("key", "Jira did not return a created issue key"))
    return 0


def issue(client, key):
    return client.live("GET", "/api/2/issue/%s" % urllib.parse.quote(key), fields="summary,description,reporter,parent")


def answer_body(answer, answerer):
    return "*Answer from %s:*\n%s" % (answerer.get("displayName") or answerer["name"], answer)


def question_text(description):
    match = re.search(r"\*Question:\*\s*(.*?)(?:\n\*Answer here|\Z)", description or "", re.S)
    return (match.group(1) if match else "").replace("{quote}", "").strip()


def parent_mirror(data, answer, answerer):
    fields = data.get("fields") or {}
    parent = fields.get("parent") or {}
    parent_key = parent.get("key")
    question = question_text(fields.get("description"))
    return parent_key, (
        "*Question sub-task %s*\n"
        "*Question:* %s\n\n"
        "%s"
    ) % (data.get("key", ""), question or "(question text unavailable)", answer_body(answer, answerer))


def do_answer(args):
    client = JiraClient(args.dry_run)
    answerer = (
        find_person(client, args.answered_by)
        if not args.dry_run
        else {"name": args.answered_by, "displayName": display_name(args.answered_by)}
    )
    if args.dry_run:
        comment = {"body": answer_body(args.answer, answerer)}
        print_request("POST", "/api/2/issue/%s/comment" % args.key, comment)
        print_request("PUT", "/api/2/issue/%s/assignee" % args.key, {"name": "<reporter from issue>"})
        print("Would GET the question and mirror its question and answer onto its parent story.")
        return 0
    data = issue(client, args.key)
    reporter = asker_of(data)
    if not reporter:
        raise RuntimeError("question %s has no reporter; cannot return it to the asker" % args.key)
    client.live("POST", "/api/2/issue/%s/comment" % args.key, {"body": answer_body(args.answer, answerer)})
    client.live("PUT", "/api/2/issue/%s/assignee" % args.key, {"name": reporter})
    parent_key, mirror = parent_mirror(data, args.answer, answerer)
    if parent_key:
        client.live("POST", "/api/2/issue/%s/comment" % parent_key, {"body": mirror})
    print("Answered %s, reassigned it to reporter %s, and mirrored the Q&A onto %s." %
          (args.key, reporter, parent_key or "no parent story"))
    return 0


def do_delegate(args):
    client = JiraClient(args.dry_run)
    target = (
        find_person(client, args.to)
        if not args.dry_run
        else {"name": args.to, "displayName": display_name(args.to)}
    )
    handing_over = display_name(args.by)
    note = args.note or "(no note supplied)"
    comment = {
        "body": "*Handed over by %s to %s.*\n%s" % (
            handing_over, target.get("displayName") or target["name"], note
        )
    }
    path = "/api/2/issue/%s" % urllib.parse.quote(args.key)
    if args.dry_run:
        print_request("PUT", path + "/assignee", {"name": target["name"]})
        print_request("POST", path + "/comment", comment)
        return 0
    client.live("PUT", path + "/assignee", {"name": target["name"]})
    client.live("POST", path + "/comment", comment)
    print("Reassigned %s to %s and recorded the handover from %s." % (
        args.key, target.get("displayName") or target["name"], handing_over))
    return 0


def choice(value, allowed, label):
    for option in allowed:
        if option.lower() == (value or "").lower():
            return option
    raise RuntimeError("%s must be one of: %s" % (label, ", ".join(allowed)))


def observation_payload(args, raiser, assignee):
    kind = args.kind.lower()
    raiser_name = (raiser or {}).get("displayName") or args.raised_by
    detail = args.detail or "(no detail supplied)"
    description = (
        "*Raised by:* %s (%s)\n"
        "*Story:* %s\n"
        "*Seen in:* %s\n"
        "*Severity:* %s\n"
        "*What happened:*\n%s\n"
        "Session: %s"
    ) % (
        raiser_name, args.raised_by, args.story, args.environment or "not stated",
        args.severity or "not stated", quote(detail), args.session_url or "(not supplied)",
    )
    fields = {
        "project": {"key": PROJECT},
        "issuetype": {"id": OBSERVATION_TYPES[kind]},
        "summary": issue_summary("%s: %s" % (args.story, args.title)),
        "description": description,
        "labels": ["Observation", "ACME-Dashboard"],
    }
    if assignee:
        fields["assignee"] = {"name": assignee["name"]}
    if kind == "defect":
        fields[SEVERITY_FIELD] = {"value": choice(args.severity, SEVERITIES, "--severity")}
        fields[DETECTED_IN_FIELD] = {
            "value": choice(args.environment, DETECTED_IN, "--environment")
        }
    if kind == "risk":
        level = args.risk_level or SEVERITY_TO_RISK.get((args.severity or "").lower())
        fields[RISK_LEVEL_FIELD] = {"value": choice(level, RISK_LEVELS, "--risk-level")}
        fields[IMPEDIMENT_FIELD] = detail
    return {"fields": fields}


def do_observe(args):
    if args.kind.lower() not in OBSERVATION_TYPES:
        raise RuntimeError("--kind must be one of: %s" % ", ".join(sorted(OBSERVATION_TYPES)))
    client = JiraClient(args.dry_run)
    raiser = (
        find_person(client, args.raised_by)
        if not args.dry_run
        else {"name": args.raised_by, "displayName": display_name(args.raised_by)}
    )
    assignee = find_person(client, args.assignee, required=False) if args.assignee and not args.dry_run else (
        {"name": args.assignee, "displayName": display_name(args.assignee)} if args.assignee else None
    )
    payload = observation_payload(args, raiser, assignee)
    link = {
        "type": {"name": RELATES_LINK},
        "inwardIssue": {"key": "<created observation>"},
        "outwardIssue": {"key": args.story},
    }
    if args.dry_run:
        print_request("POST", "/api/2/issue", payload)
        print_request("POST", "/api/2/issueLink", link)
        return 0
    result = client.live("POST", "/api/2/issue", payload)
    key = result.get("key")
    if not key:
        raise RuntimeError("Jira did not return a created issue key")
    link["inwardIssue"] = {"key": key}
    client.live("POST", "/api/2/issueLink", link)
    print("Raised %s (%s) and linked it to %s." % (key, args.kind.lower(), args.story))
    return 0


def do_close(args):
    client = JiraClient(args.dry_run)
    path = "/api/2/issue/%s/transitions" % urllib.parse.quote(args.key)
    if args.dry_run:
        print_request("GET", path)
        print("Would choose the first transition named Close, Done, or Resolve (case-insensitive).")
        return 0
    transitions = client.live("GET", path).get("transitions", [])
    preferred = {"close": 0, "done": 1, "resolve": 2}
    choices = sorted(
        (t for t in transitions if (t.get("name") or "").lower() in preferred),
        key=lambda t: preferred[(t.get("name") or "").lower()],
    )
    if not choices:
        print("No Close, Done, or Resolve transition is available for %s." % args.key, file=sys.stderr)
        return 2
    chosen = choices[0]
    client.live("POST", path, {"transition": {"id": chosen["id"]}})
    print("Transitioned %s using %s." % (args.key, chosen.get("name")))
    return 0


def do_list(args):
    client = JiraClient(False)
    user = args.user
    if args.role_view == "answerer":
        jql = 'project = ACME AND labels = Question AND assignee = "%s" AND resolution = Unresolved ORDER BY created ASC' % user
    else:
        jql = 'project = ACME AND labels = Question AND reporter = "%s" AND resolution = Unresolved ORDER BY updated DESC' % user
    result = client.live(
        "GET", "/api/2/search", jql=jql, fields="summary,description,assignee,reporter,parent,created,updated,status,resolution,labels,issuetype", maxResults=100
    )
    print(json.dumps(result.get("issues", []), indent=2))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create")
    create.add_argument("--parent", required=True)
    create.add_argument("--assignee", required=True)
    create.add_argument("--asker", required=True)
    create.add_argument("--question", required=True)
    create.add_argument("--session-url")
    create.add_argument("--dry-run", action="store_true")
    answer = sub.add_parser("answer")
    answer.add_argument("--key", required=True)
    answer.add_argument("--answer", required=True)
    answer.add_argument("--answered-by", required=True)
    answer.add_argument("--dry-run", action="store_true")
    delegate = sub.add_parser("delegate")
    delegate.add_argument("--key", required=True)
    delegate.add_argument("--to", required=True)
    delegate.add_argument("--by", required=True, help="Jira username of the person handing the work over")
    delegate.add_argument("--note")
    delegate.add_argument("--dry-run", action="store_true")
    observe = sub.add_parser("observe")
    observe.add_argument("--story", required=True)
    observe.add_argument("--kind", required=True, choices=sorted(OBSERVATION_TYPES))
    observe.add_argument("--title", required=True)
    observe.add_argument("--detail")
    observe.add_argument("--raised-by", required=True)
    observe.add_argument("--severity")
    observe.add_argument("--environment")
    observe.add_argument("--risk-level")
    observe.add_argument("--assignee")
    observe.add_argument("--session-url")
    observe.add_argument("--dry-run", action="store_true")
    close = sub.add_parser("close")
    close.add_argument("--key", required=True)
    close.add_argument("--dry-run", action="store_true")
    listing = sub.add_parser("list")
    listing.add_argument("--user", required=True)
    listing.add_argument("--role-view", choices=("asker", "answerer"), default="answerer")
    args = parser.parse_args(argv)
    try:
        return {
            "create": do_create,
            "answer": do_answer,
            "delegate": do_delegate,
            "observe": do_observe,
            "close": do_close,
            "list": do_list,
        }[args.command](args)
    except (RuntimeError, urllib.error.URLError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
