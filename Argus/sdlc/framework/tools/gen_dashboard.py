#!/usr/bin/env python3
"""Generate the role-aware Acme Claims dashboard as one self-contained HTML file.

Panels and role lenses come from ``.devin/rules/dashboard-roles.yaml``, so a new role is a
configuration change. Live mode reads Jira with bearer auth. ``--cache`` accepts a JSON export
containing ``user``, ``questions_for_me``, ``my_questions``, ``approvals``, ``team_pipeline``,
``branches`` and a ``panels`` map of panel id to rows, which makes the renderer usable offline.
"""
import argparse
import base64
import datetime
import glob
import html
import json
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

import yaml

import artifact_kit
import defects_by_specialty as defect_lib
import jira_hygiene as hygiene_lib
import capacity_sheet as capacity_lib
import sprint_leave
import review_pages
import scrum_metrics as scrum_lib
import verifier as verifier_lib
import gates as gate_lib
import metrics
import reconcile_roster
import session_store
import skill_homes
import gate_config
import role_config
import workbench_config
import team_links
import grooming_prep

ARGUS_LOGO = "data:image/svg+xml;base64," + base64.b64encode(open(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "console", "static", "argus-logo.svg"), "rb").read()).decode()

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
JIRA = (os.environ.get("SDLC_SANDBOX_URL") or "https://jira.acme.example").rstrip("/") + "/rest"
PEOPLE_PATH = os.path.join(ROOT, ".devin", "rules", "people.yaml")
GATES_PATH = os.path.join(ROOT, ".devin", "rules", "approval-gates.yaml")
LENS_PATH = os.path.join(ROOT, ".devin", "rules", "dashboard-roles.yaml")
BUSINESS_PATH = os.path.join(ROOT, ".devin", "rules", "business-screens.json")
SESSION_ROOT = os.path.join(ROOT, "sdlc", "framework", "context", "session")
OUTPUT_ROOT = os.path.join(ROOT, "sdlc", "framework", "context", "dashboard")
ROADMAP_PAGE = os.path.join("docs", "knowledge-base", "JIRA-DERIVED", "UI-DELIVERY-ROADMAP.html")
ROADMAP_GENERATED = re.compile(r"(?:generated|as of) (\d{4}-\d{2}-\d{2})")
QUESTION_JQL = (
    'project = ACME AND labels = Question AND assignee = "%s" '
    "AND resolution = Unresolved ORDER BY created ASC"
)
MY_QUESTION_JQL = (
    'project = ACME AND labels = Question AND (reporter = "%s" OR labels = "asked-by-%s") '
    "AND resolution = Unresolved ORDER BY updated DESC"
)
PROJECT_CLAUSE = "project = ACME"
ISSUE_FIELDS = (
    "summary,issuetype,status,assignee,reporter,priority,labels,resolution,created,updated,"
    "customfield_10002,customfield_10001,customfield_10013"
)
WORKLOAD_FIELDS = "assignee,status,issuetype,timeoriginalestimate,timeestimate,resolution,parent"
TEAM_FIELDS = "summary,assignee,status,issuetype,parent,updated"
QUESTION_FIELDS = (
    "summary,description,assignee,reporter,parent,created,updated,status,resolution,labels,issuetype"
)
KEY_PATTERN = re.compile(r"ACME-\d+")
OBSERVATION_KINDS = ("observation", "defect", "risk")
SEVERITIES = (
    "Critical", "High", "Medium", "Low", "Cosmetic Issue", "Performance Issue",
    "Security Issue", "Fails, no workaround", "Fails, workaround available",
)
ENVIRONMENTS = (
    "Dev", "TEST - System Integration Test (SIT)", "TEST - User Acceptance Test (UAT)",
    "TEST - Continuous Integration", "TEST - End-to-End (E2E)", "TEST - Performance",
    "Preview", "STAGE / PRE-PRODUCTION", "PRODUCTION - Dark Release", "PRODUCTION - Warranty",
)


# The dashboard only reads: every action (answers, approvals, handovers, observations, config changes) is done
# in Argus, on its actions page (--actions, served at /actions in Argus side panel).
# A lens can no longer switch its actions back on.
DASHBOARD_READ_ONLY = True


def read_only_lens(lens):
    return DASHBOARD_READ_ONLY or bool((lens or {}).get("read_only"))


def team_clause():
    """The JQL clause that narrows Acme Claims to this team, from dashboard-roles.yaml `team.scope`.

    Project Acme Claims carries every Value Based Care team, so an unscoped query shows a dashboard full
    of other teams' work. The clause mirrors the board filter behind board 247285.
    """
    return ((load_yaml(LENS_PATH, {}).get("team") or {}).get("scope") or "").strip()


def team_scoped(jql):
    """Insert the team clause straight after the project clause of a query.

    Only for queries that are not already narrowed to one person: work assigned to or raised by the
    viewer is theirs to see even on the handful of issues where the IT Team field was never set.
    """
    clause = team_clause()
    if not clause or clause in jql or PROJECT_CLAUSE not in jql:
        return jql
    return jql.replace(PROJECT_CLAUSE, "%s AND %s" % (PROJECT_CLAUSE, clause), 1)


def team_board():
    """The Jira Agile board this team plans on, from dashboard-roles.yaml `team.board`."""
    return ((load_yaml(LENS_PATH, {}).get("team") or {}).get("board") or "")


def _ctx():
    return ssl._create_unverified_context()


JIRA_READ_TIMEOUT = 120
JIRA_TRIES = 2
JIRA_RETRY_PAUSE = 2


class JiraClient:
    # The nightly build (--all) sets a dict here so every person's dashboard shares one read of each query.
    shared = None

    def __init__(self):
        self.token = os.environ.get("ACME_JIRA_TOKEN")
        self.validated = False
        if not self.token:
            raise RuntimeError("ACME_JIRA_TOKEN is not set — use --cache to work offline.")

    def get(self, path, **params):
        url = JIRA + path
        if params:
            url += ("&" if "?" in path else "?") + urllib.parse.urlencode(params)
        if JiraClient.shared is not None and url in JiraClient.shared:
            return JiraClient.shared[url]
        req = urllib.request.Request(
            url, headers={"Authorization": "Bearer " + self.token, "Accept": "application/json"}
        )
        for attempt in range(JIRA_TRIES):
            try:
                with urllib.request.urlopen(req, context=_ctx(), timeout=JIRA_READ_TIMEOUT) as response:
                    out = json.load(response)
                if JiraClient.shared is not None:
                    JiraClient.shared[url] = out
                return out
            except urllib.error.HTTPError as exc:
                if exc.code in (401, 403):
                    raise RuntimeError(
                        "Jira returned %d. The service account token is invalid or locked; "
                        "it must be rotated or reset by an admin. Not retrying." % exc.code
                    ) from exc
                raise
            except OSError as exc:
                reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
                # a dropped connection is tried again; a read that already waited the full timeout is not
                if attempt + 1 < JIRA_TRIES and not isinstance(reason, TimeoutError):
                    time.sleep(JIRA_RETRY_PAUSE)
                    continue
                raise RuntimeError("Jira could not be reached (%s: %s) on %s, tried %d times." % (
                    type(reason).__name__, reason, path, attempt + 1)) from exc

    def live_get(self, path, **params):
        if not self.validated:
            self.get("/api/2/myself")
            self.validated = True
        return self.get(path, **params)


def load_yaml(path, fallback):
    try:
        with open(path, encoding="utf-8") as fh:
            return yaml.safe_load(fh) or fallback
    except FileNotFoundError:
        return fallback


def people():
    return load_yaml(PEOPLE_PATH, {"people": [], "default_role": "developer"})


def gates():
    return load_yaml(GATES_PATH, {"gates": []}).get("gates", [])


def lens_config():
    return load_yaml(LENS_PATH, {"panels": {}, "lenses": {}, "fallback_lens": "developer"})


def norm(value):
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def resolve_user(client, fragment):
    roster = people().get("people", [])
    for person in roster:
        if person.get("jira_user") and (
            person["jira_user"].lower() == fragment.lower()
            or norm(person.get("name")) == norm(fragment)
        ):
            return {
                "name": person["jira_user"],
                "displayName": person.get("name") or person["jira_user"],
            }
    matches = client.live_get(
        "/api/2/user/assignable/search", project="ACME", username=fragment
    )
    exact = [p for p in matches if p.get("name", "").lower() == fragment.lower()]
    if exact:
        return exact[0]
    named = [p for p in matches if fragment.lower() in (p.get("displayName") or "").lower()]
    if len(named) == 1:
        return named[0]
    if len(matches) == 1:
        return matches[0]
    raise RuntimeError("could not resolve %r via Acme Claims assignable/search" % fragment)


def roster_entry(username, display_name=""):
    for person in people().get("people", []):
        if person.get("jira_user") == username:
            return person
    for person in people().get("people", []):
        if display_name and norm(person.get("name")) == norm(display_name):
            return person
    return {"roles": [people().get("default_role", "developer")]}


def business_screens():
    """business-screens.json: the jobs of the PO, BSA and Scrum Master lenses, shared with Argus."""
    try:
        with open(BUSINESS_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def business_groups(lens_id):
    return (business_screens().get("lenses") or {}).get(lens_id) or []


def primary_lens(primary_role):
    """The lens role-routing.yaml gives the person's main role (aliases followed), or ""."""
    if not primary_role:
        return ""
    table = skill_homes.routing()
    role = (table.get("role_aliases") or {}).get(primary_role, primary_role)
    return ((table.get("roles") or {}).get(role) or {}).get("dashboard_lens") or ""


def select_lens(roles, override=None, primary_role=None):
    """--lens first, then the lens of the person's main role (the same one Argus opens), then the first
    lens whose roles match the roster's gate roles."""
    config = lens_config()
    lenses = config.get("lenses") or {}
    if override:
        if override in lenses:
            return override, lenses[override]
        for lens_id, lens in lenses.items():
            if override in (lens.get("roles") or []):
                return lens_id, lens
        raise RuntimeError(
            "unknown lens %r — choose one of: %s" % (override, ", ".join(sorted(lenses)))
        )
    own = primary_lens(primary_role)
    if own in lenses:
        return own, lenses[own]
    for lens_id, lens in lenses.items():
        if set(roles) & set(lens.get("roles") or []):
            return lens_id, lens
    fallback = config.get("fallback_lens", "developer")
    return fallback, lenses.get(fallback, {"label": fallback, "panels": [], "actions": ["answers"]})


def issue_fields(issue):
    return issue.get("fields", issue)


def user_name(value):
    if isinstance(value, dict):
        return value.get("name") or value.get("key") or ""
    return value or ""


def issue_asker(issue):
    fields = issue_fields(issue)
    match = re.search(r"\*Asked by:\*\s*(.+?)\s*\((\S+?)\)", fields.get("description") or "")
    if match:
        return match.group(1)
    reporter = fields.get("reporter") or {}
    return reporter.get("displayName") or reporter.get("name", "")


def issue_question(issue):
    description = issue_fields(issue).get("description") or ""
    match = re.search(r"\*Question:\*\s*(.*?)(?:\n\*Answer here|\Z)", description, re.S)
    return (match.group(1) if match else description).replace("{quote}", "").strip()


def comments_answer(issue):
    comments = (issue_fields(issue).get("comment") or {}).get("comments", [])
    answers = []
    for comment in comments:
        body = comment.get("body") or ""
        if body.startswith("*Answer from "):
            match = re.match(r"\*Answer from (.+?):\*\s*(.*)", body, re.S)
            if match:
                answers.append({"author": match.group(1), "text": match.group(2).strip()})
    return answers[-1] if answers else {"author": "", "text": ""}


def parent_info(issue):
    parent = issue_fields(issue).get("parent") or {}
    fields = parent.get("fields") or {}
    return parent.get("key", ""), fields.get("summary", "")


def day_age(stamp):
    if isinstance(stamp, datetime.datetime):
        stamp = stamp.isoformat()
    try:
        parsed = datetime.datetime.fromisoformat((stamp or "").replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        return "unknown"
    return max(0, (datetime.datetime.now(datetime.timezone.utc) - parsed).days)


def normalise_question(issue, current_user):
    fields = issue_fields(issue)
    parent_key, parent_title = parent_info(issue)
    assignee = fields.get("assignee") or {}
    answer = comments_answer(issue)
    return {
        "key": issue.get("key", ""),
        "parent": parent_key,
        "parent_title": parent_title,
        "asker": issue_asker(issue),
        "assignee": assignee.get("name", ""),
        "question": issue_question(issue),
        "answer": answer.get("text", ""),
        "answer_by": answer.get("author", ""),
        "assignee_display": assignee.get("displayName") or assignee.get("name", ""),
        "age": day_age(fields.get("created")),
        "waiting": user_name(assignee) != current_user,
    }


def short_date(value):
    try:
        return datetime.datetime.fromisoformat((value or "").replace("Z", "+00:00")).date().isoformat()
    except (AttributeError, ValueError):
        return (value or "")[:10]


def sprint_name(value):
    if isinstance(value, list):
        value = value[-1] if value else ""
    if isinstance(value, dict):
        return value.get("name", "")
    match = re.search(r"name=([^,\]]+)", value or "")
    return match.group(1) if match else (value or "")


def named_value(value):
    if isinstance(value, dict):
        return value.get("value") or value.get("name") or ""
    return value or ""


def issue_row(issue):
    fields = issue_fields(issue)
    return {
        "key": issue.get("key", ""),
        "type": (fields.get("issuetype") or {}).get("name", ""),
        "summary": fields.get("summary", ""),
        "status": (fields.get("status") or {}).get("name", ""),
        "assignee": (fields.get("assignee") or {}).get("displayName")
        or (fields.get("assignee") or {}).get("name", ""),
        "reporter": (fields.get("reporter") or {}).get("displayName")
        or (fields.get("reporter") or {}).get("name", ""),
        "priority": (fields.get("priority") or {}).get("name", ""),
        "severity": named_value(fields.get("customfield_10013")),
        "points": fields.get("customfield_10001") or "",
        "sprint": sprint_name(fields.get("customfield_10002")),
        "created": short_date(fields.get("created")),
        "updated": short_date(fields.get("updated")),
    }


def search_questions(client, jql):
    result = client.live_get("/api/2/search", jql=jql, maxResults=100, fields=QUESTION_FIELDS)
    return [
        client.live_get(
            "/api/2/issue/%s" % urllib.parse.quote(item.get("key", "")),
            fields=QUESTION_FIELDS + ",comment",
        )
        for item in result.get("issues", [])
    ]


def load_session_records():
    """(path, data) for every session the store can see: local per-owner home, repo owner dirs, legacy."""
    return [(path, load_yaml(path, {})) for _owner, _req, path in session_store.all_session_records()]


def spec_title(path):
    directory = os.path.dirname(path)
    req = os.path.basename(directory)
    candidates = glob.glob(os.path.join(directory, req + "*SPEC.md"))
    if not candidates:
        candidates = glob.glob(os.path.join(directory, "*SPEC.md"))
    if candidates:
        try:
            text = open(candidates[0], encoding="utf-8").read()
            match = re.search(r"^#\s+(.+)$", text, re.M)
            if match:
                return match.group(1).strip()
        except OSError:
            pass
    return req


def session_label(path):
    directory = os.path.dirname(path)
    if directory.startswith(ROOT):
        return os.path.relpath(directory, ROOT).replace(os.sep, "/")
    return directory


def named_for_gate(gate, username):
    roster = people().get("people", [])
    for approver in gate.get("approvers", []) or []:
        for name in approver.get("names", []) or []:
            matches = [person for person in roster if norm(person.get("name")) == norm(name)]
            if matches and matches[0].get("jira_user") and matches[0].get("jira_user") == username:
                return True
    return False


def approvals_for_user(username):
    pending = []
    pipeline = []
    now = datetime.datetime.now(datetime.timezone.utc)
    for path, data in load_session_records():
        req = os.path.basename(os.path.dirname(path))
        owner = os.path.basename(os.path.dirname(os.path.dirname(path)))
        if owner == "session" or owner.startswith("REQ-"):
            owner = "legacy"
        records = gate_lib.flatten_records(data)
        by_gate = {record.get("gate_id"): record for record in records if isinstance(record, dict)}
        open_gates = []
        for gate in gates():
            if not named_for_gate(gate, username):
                continue
            record = by_gate.get(gate.get("id"), {})
            decision = (record.get("decision") or record.get("status") or "pending").lower()
            if decision in ("approved", "closed", "resolved"):
                continue
            stamp = record.get("timestamp") or record.get("updated_at")
            try:
                started = datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            except (AttributeError, ValueError):
                started = datetime.datetime.fromtimestamp(os.path.getmtime(path), datetime.timezone.utc)
            hours = max(0, int((now - started).total_seconds() // 3600))
            timeout = gate.get("timeout_hours")
            items = [
                {"n": i.get("n", n + 1), "text": i.get("text", ""), "state": i.get("state", "pending")}
                for n, i in enumerate(record.get("decision_items") or []) if isinstance(i, dict)
            ] or [{"n": 1, "text": "Approve %s as presented" % gate.get("name", gate.get("id", "")), "state": "pending"}]
            pending.append({
                "key": record.get("approval_subtask") or "session:%s/%s" % (req, gate.get("id", "")),
                "items": items,
                "waiting_on": record.get("delegated_to") if decision == "waiting" else None,
                "requirement": req,
                "title": spec_title(path),
                "session": session_label(path),
                "gate_id": gate.get("id", ""),
                "name": gate.get("name", gate.get("id", "")),
                "requirement_text": "; ".join(gate.get("approval_criteria") or []),
                "owner": owner,
                "days": hours // 24,
                "timeout_hours": timeout,
                "time_left": None if timeout is None else timeout - hours,
            })
            open_gates.append(gate)
        if open_gates:
            current = open_gates[0]
            pipeline.append({
                "requirement": req,
                "owner": owner,
                "phase": current.get("name", current.get("id", "")),
                "blocked_on": "approval: " + current.get("id", ""),
            })
        elif records:
            signed = [r for r in records if isinstance(r, dict) and r.get("gate_id")]
            last = signed[-1] if signed else {}
            gate_name = next(
                (g.get("name", g["id"]) for g in gates() if g.get("id") == last.get("gate_id")),
                last.get("gate_id", ""),
            )
            age = day_age(last.get("timestamp") or last.get("updated_at") or "")
            pipeline.append({
                "requirement": req, "owner": owner,
                "phase": "Past %s" % gate_name if gate_name else "Moving forward",
                "blocked_on": "nothing — %s signed %s by %s" % (
                    (last.get("decision") or "approved").lower(),
                    "%d day%s ago" % (age, "" if age == 1 else "s") if isinstance(age, int) else "on an unknown date",
                    last.get("approver_name") or "an unnamed approver",
                ) if last else "nothing recorded",
            })
    return pending, pipeline


def git(*args):
    try:
        return subprocess.run(
            ("git",) + args, cwd=ROOT, capture_output=True, text=True, timeout=120
        )
    except (OSError, subprocess.SubprocessError):
        return None


def git_out(*args):
    result = git(*args)
    return result.stdout.strip() if result and result.returncode == 0 else ""


def resolve_base(requested):
    for candidate in [requested, "origin/master", "origin/main", "master", "main"]:
        if candidate and git_out("rev-parse", "--verify", "--quiet", candidate):
            return candidate
    return ""


def merge_conflicts(base, ref):
    result = git("merge-tree", "--write-tree", base, ref)
    if not result or result.returncode not in (0, 1):
        return None
    return "CONFLICT" in result.stdout or result.returncode == 1


def branch_rows(base):
    if not base:
        return []
    listing = git_out(
        "for-each-ref", "--format=%(refname:short)%09%(committerdate:short)%09%(authorname)",
        "refs/heads", "refs/remotes/origin",
    )
    rows = {}
    for line in listing.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        ref, when, author = parts
        if ref in (base, "origin/HEAD"):
            continue
        match = KEY_PATTERN.search(ref.upper())
        if not match:
            continue
        counts = git_out("rev-list", "--left-right", "--count", "%s...%s" % (base, ref)).split()
        behind, ahead = (counts + ["", ""])[:2]
        local = ref if not ref.startswith("origin/") else ref[len("origin/"):]
        existing = rows.get(local)
        if existing and not existing["remote"] and ref.startswith("origin/"):
            existing["remote"] = True
            continue
        if existing:
            continue
        conflicts = merge_conflicts(base, ref) if ahead not in ("", "0") else False
        rows[local] = {
            "branch": ref,
            "key": match.group(0),
            "author": author,
            "committed": when,
            "ahead": ahead,
            "behind": behind,
            "remote": ref.startswith("origin/"),
            "conflicts": conflicts,
        }
    return sorted(rows.values(), key=lambda row: (row["key"], row["branch"]))


def decorate_branches(rows, statuses, mine=None, owner=""):
    decorated = []
    for row in rows:
        row = dict(row)
        status = statuses.get(row["key"], {})
        row["status"] = status.get("status", "unknown to Jira")
        row["assignee"] = status.get("assignee", "")
        row["summary"] = status.get("summary", "")
        notes = []
        if row.get("conflicts"):
            notes.append("conflicts with %s" % row.get("base", "base"))
        if row.get("behind") not in ("", "0", None):
            notes.append("behind base by %s" % row["behind"])
        if row.get("ahead") in ("", "0", None):
            notes.append("nothing to merge")
        if not row.get("remote"):
            notes.append("local only — not pushed")
        if status.get("resolved") and row.get("ahead") not in ("", "0", None):
            notes.append("story is closed but the branch is unmerged")
        row["notes"] = "; ".join(notes) or "clean"
        if mine is not None and row["key"] not in mine and norm(owner) not in (
            norm(row["assignee"]), norm(row["author"])
        ):
            continue
        decorated.append(row)
    return decorated


def working_days(start, end):
    """Weekdays from the sprint's first day to its last, both included."""
    try:
        first = datetime.datetime.fromisoformat((start or "").replace("Z", "+00:00")).date()
        last = datetime.datetime.fromisoformat((end or "").replace("Z", "+00:00")).date()
    except (AttributeError, TypeError, ValueError):
        return 0
    if last < first:
        return 0
    days = 0
    day = first
    while day <= last:
        if day.weekday() < 5:
            days += 1
        day += datetime.timedelta(days=1)
    return days


def workload_issue(issue):
    """One sprint issue reduced to what the workload panel counts."""
    fields = issue_fields(issue)
    assignee = fields.get("assignee") or {}
    category = ((fields.get("status") or {}).get("statusCategory") or {}).get("key", "new")
    return {
        "key": issue.get("key", ""),
        "parent": (fields.get("parent") or {}).get("key", ""),
        "username": assignee.get("name", ""),
        "display": assignee.get("displayName") or assignee.get("name", ""),
        "category": category,
        "estimate_hours": (fields.get("timeoriginalestimate") or 0) / 3600.0,
        "remaining_hours": (fields.get("timeestimate") or 0) / 3600.0,
    }


UNASSIGNED = "(unassigned)"
SPRINT_TOKEN = re.compile(r"\d+\.\d+\.\d+")


def sprint_capacity(sprint, folder=None):
    """The sprint planning sheet for this sprint: (sprint number, {normalised name: person row}).

    Found by the sprint number in the sprint name (26.4.2), else by a sheet starting on the sprint's
    first day. ("", {}) when the repo has no sheet for it.
    """
    import sprint_sheet
    try:
        have = sprint_sheet.sprints(folder)
        found = SPRINT_TOKEN.search(sprint.get("name") or "")
        token = found.group(0) if found and found.group(0) in have else ""
        if not token:
            start = (sprint.get("start") or "")[:10]
            token = next((t for t in have if start and sprint_sheet.load(t, folder).get("start") == start), "")
        if not token:
            return "", {}
        sheet = sprint_sheet.load(token, folder)
        return token, {sprint_sheet.norm(p["name"]): p for p in sprint_sheet.people(sheet)}
    except Exception:  # noqa: BLE001 - a sheet that cannot be read leaves capacity to the roster
        return "", {}


def workload_items(issues):
    """The sprint items that carry the work: sub-tasks, and stories or defects with no sub-task in the sprint.

    A story's own estimate overlaps its sub-tasks' estimates, so a story whose sub-tasks are in the
    sprint is counted through them only.
    """
    parents = {issue.get("parent") for issue in issues if issue.get("parent")}
    return [issue for issue in issues if not (issue.get("key") and issue["key"] in parents)]


def workload_rows(spec, sprint, issues, sheet_people=None):
    """Turn the active sprint's issues into one row per person, plus an unassigned row.

    Load is estimated hours against the hours that person has in the sprint. Those hours are the
    person's Available hours on the sprint planning sheet (leave, holidays, productive hours and
    % on project already taken off); someone not on the sheet gets weekdays in the sprint times
    `hours_per_day` times their `allocation` from people.yaml. Jira assignment is a proxy for
    effort, not a measurement of it, so the panel names a signal and leaves the judgement to the
    reader.
    """
    import sprint_sheet
    sheet_people = sheet_people or {}
    hours_per_day = float(spec.get("hours_per_day") or 8)
    light_at = float(spec.get("light_at") or 0.5)
    heavy_at = float(spec.get("heavy_at") or 1.1)
    overloaded_at = float(spec.get("overloaded_at") or 1.3)
    days = working_days(sprint.get("start"), sprint.get("end"))
    full_capacity = days * hours_per_day

    totals = {}
    for issue in workload_items(issues):
        who = issue.get("username") or UNASSIGNED
        bucket = totals.setdefault(
            who, {"display": issue.get("display") or UNASSIGNED, "items": 0, "in_progress": 0,
                  "done": 0, "hours": 0.0}
        )
        bucket["items"] += 1
        if issue.get("category") == "indeterminate":
            bucket["in_progress"] += 1
        elif issue.get("category") == "done":
            bucket["done"] += 1
        bucket["hours"] += float(issue.get("estimate_hours") or 0)

    rows = []
    seen = set()
    for person in people().get("people", []):
        username = person.get("jira_user")
        if not username or person.get("delivery") is False:
            continue
        seen.add(username)
        bucket = totals.get(username, {"items": 0, "in_progress": 0, "done": 0, "hours": 0.0})
        on_sheet = sheet_people.get(sprint_sheet.norm(person.get("name") or ""))
        if on_sheet:
            allocation = float(on_sheet.get("allocation") or 0)
            capacity = float(on_sheet.get("hours") or 0)
        else:
            allocation = float(person.get("allocation") or 100)
            capacity = full_capacity * allocation / 100.0
        rows.append(
            {
                "person": person.get("name") or username,
                "role": person.get("primary_role") or "",
                "allocation": allocation,
                "items": bucket["items"],
                "in_progress": bucket["in_progress"],
                "hours": round(bucket["hours"], 1),
                "capacity": round(capacity, 1),
                "load": (bucket["hours"] / capacity) if capacity else None,
                "capacity_from": "sheet" if on_sheet else "roster",
                "note": "",
            }
        )
    for username, bucket in sorted(totals.items()):
        if username in seen:
            continue
        rows.append(
            {
                "person": bucket["display"],
                "role": "" if username == UNASSIGNED else "not in the roster",
                "allocation": None,
                "items": bucket["items"],
                "in_progress": bucket["in_progress"],
                "hours": round(bucket["hours"], 1),
                "capacity": None,
                "load": None,
                "capacity_from": "",
                "note": "sprint capacity is not planned for"
                if username == UNASSIGNED
                else "add to the roster or reassign",
            }
        )

    for row in rows:
        load, hours, items = row["load"], row["hours"], row["items"]
        if row["capacity"] is None:
            row["signal"] = "unplanned" if items else "nothing"
        elif not items:
            row["signal"] = "no sprint work"
        elif not hours:
            row["signal"] = "not estimated"
        elif load is None:
            row["signal"] = "no capacity"
        elif load > overloaded_at:
            row["signal"] = "overloaded"
        elif load > heavy_at:
            row["signal"] = "heavy"
        elif load < light_at:
            row["signal"] = "room for more"
        else:
            row["signal"] = "balanced"
    rows.sort(key=lambda r: (-(r["load"] if r["load"] is not None else -1), -r["hours"]))
    return rows


def workload_note(sprint, days, spec, token="", rows=()):
    if not sprint.get("name"):
        return ""
    hours = days * float(spec.get("hours_per_day") or 8)
    roster = [row["person"] for row in rows if row.get("capacity_from") == "roster"]
    if token:
        capacity = ("Capacity is each person's Available hours on the sprint %s planning sheet, so leave, "
                    "holidays, productive hours and %% on project are already taken off." % token)
        if roster:
            capacity += (" Not on the sheet, so %d working days x %g hours x roster allocation: %s."
                         % (days, float(spec.get("hours_per_day") or 8), "; ".join(roster)))
    else:
        capacity = ("No planning sheet for this sprint in the repo, so capacity is %d working days x %g hours "
                    "(%g hours for a full-time seat) x roster allocation, with no leave taken off."
                    % (days, float(spec.get("hours_per_day") or 8), hours))
    return (
        "%s, %s to %s. Estimated is the Jira original estimate on that person's sub-tasks, plus stories "
        "and defects that have no sub-task in the sprint (a story's own estimate is not added on top of "
        "its sub-tasks); an item with no estimate counts as nothing. %s Reading only — rebalancing is a "
        "conversation with the person."
        % (sprint["name"], short_date(sprint.get("start")), short_date(sprint.get("end")), capacity)
    )


class LiveSource:
    kind = "live"

    def __init__(self, fragment, base=None):
        self.client = JiraClient()
        identity = resolve_user(self.client, fragment)
        self.username = identity.get("name")
        self.display = identity.get("displayName") or self.username
        self.entry = roster_entry(self.username, self.display)
        self.base = resolve_base(base or lens_config().get("default_base"))

    def questions(self):
        return [
            normalise_question(issue, self.username)
            for issue in search_questions(self.client, QUESTION_JQL % self.username)
        ]

    def my_questions(self):
        return [
            normalise_question(issue, self.username)
            for issue in search_questions(self.client, MY_QUESTION_JQL % (self.username, self.username))
        ]

    def jira_panel(self, spec):
        raw = " ".join((spec.get("jql") or "").split())
        try:
            raw = team_links.fill_statuses(raw)
        except team_links.LinksError as exc:
            return [], "This panel's query needs a status list: %s" % exc
        jql = raw.replace("{user}", self.username)
        if "{user}" not in raw:
            jql = team_scoped(jql)
        try:
            result = self.client.live_get("/api/2/search", jql=jql, maxResults=60, fields=ISSUE_FIELDS)
        except urllib.error.HTTPError as exc:
            return [], "Jira rejected this query (HTTP %d): %s" % (exc.code, jql)
        return [issue_row(issue) for issue in result.get("issues", [])], ""

    def demo_board(self, spec):
        """Every story the panel's query finds (all result pages), each with its demo page on
        Confluence "Acme Claims Demo Recordings" when one has been published."""
        jql = team_scoped(team_links.fill_statuses(" ".join((spec.get("jql") or "").split())))
        rows, start = [], 0
        try:
            while True:
                page = self.client.live_get("/api/2/search", jql=jql, maxResults=100, startAt=start,
                                            fields=ISSUE_FIELDS).get("issues") or []
                rows += [issue_row(issue) for issue in page]
                if len(page) < 100:
                    break
                start += len(page)
        except urllib.error.HTTPError as exc:
            return [], "Jira rejected this query (HTTP %d): %s" % (exc.code, jql)
        return with_recordings(rows)

    def active_sprint(self):
        """{id, name, start, end} of the active sprint on the team board, or {} when there is none."""
        board = team_board()
        if not board:
            return {}
        active = self.client.live_get(
            "/agile/1.0/board/%s/sprint" % board, state="active"
        ).get("values") or []
        if not active:
            return {}
        ours = [s for s in active if str(s.get("originBoardId") or "") == str(board)]
        current = (ours or active)[-1]
        return {
            "id": current.get("id"),
            "name": current.get("name", ""),
            "start": current.get("startDate", ""),
            "end": current.get("endDate", ""),
        }

    def workload(self, spec):
        """The active sprint on the team board, with its issues for the team only."""
        current = self.active_sprint()
        if not current:
            return {}, []
        sprint = {k: current[k] for k in ("name", "start", "end")}
        jql = team_scoped("%s AND sprint = %s" % (PROJECT_CLAUSE, current.get("id")))
        issues, start = [], 0
        while True:
            page = self.client.live_get(
                "/api/2/search", jql=jql, maxResults=100, startAt=start, fields=WORKLOAD_FIELDS
            )
            issues.extend(page.get("issues") or [])
            start += 100
            if start >= page.get("total", 0) or not page.get("issues"):
                break
        return sprint, [workload_issue(issue) for issue in issues]

    def team_activity(self, spec):
        """The active sprint on the team board and every team issue in it, with summary and status."""
        current = self.active_sprint()
        if not current:
            return {}, []
        jql = team_scoped("%s AND sprint = %s ORDER BY updated DESC" % (PROJECT_CLAUSE, current.get("id")))
        issues, start = [], 0
        while True:
            page = self.client.live_get("/api/2/search", jql=jql, maxResults=100, startAt=start, fields=TEAM_FIELDS)
            issues.extend(page.get("issues") or [])
            start += 100
            if start >= page.get("total", 0) or not page.get("issues"):
                break
        return {k: current[k] for k in ("name", "start", "end")}, [team_issue(issue) for issue in issues]

    def approvals(self):
        pending, pipeline = approvals_for_user(self.username)
        known = {row["key"] for row in pending}
        try:
            result = self.client.live_get(
                "/api/2/search", jql=APPROVAL_JQL % self.username, maxResults=60,
                fields="summary,description,parent,created",
            )
        except urllib.error.HTTPError:
            result = {}
        for issue in result.get("issues", []):
            row = approval_subtask_row(issue)
            if row and row["key"] not in known:
                pending.append(row)
        return pending, pipeline

    def branches(self, scope, assigned_keys):
        rows = branch_rows(self.base)
        for row in rows:
            row["base"] = self.base
        keys = sorted({row["key"] for row in rows})
        statuses = {}
        if keys:
            jql = "project = ACME AND key in (%s)" % ", ".join(keys)
            try:
                result = self.client.live_get(
                    "/api/2/search", jql=jql, maxResults=len(keys), fields=ISSUE_FIELDS
                )
            except urllib.error.HTTPError:
                result = {"issues": []}
            for issue in result.get("issues", []):
                row = issue_row(issue)
                row["resolved"] = bool((issue_fields(issue).get("resolution") or {}))
                statuses[row["key"]] = row
        return decorate_branches(
            rows, statuses, assigned_keys if scope == "mine" else None, self.display
        )

    def automation_branches(self, spec):
        return automation_branch_rows(spec, self.username, self.display)

    def roster(self):
        return roster_findings(), self.username in roster_stewards()

    def sessions(self, path):
        return session_rows(path)

    def health(self):
        return health_summary()

    def defect_matrix(self, spec):
        """Open SIT/UAT defects for the whole project: never narrowed by team.scope, every page read."""
        jql = " ".join((spec.get("jql") or defect_lib.JQL).split())
        try:
            return defect_lib.fetch(self.client.live_get, jql), ""
        except urllib.error.HTTPError as exc:
            return {"issues": [], "epics": {}}, "Jira rejected this query (HTTP %d): %s" % (exc.code, jql)

    def vacation(self, spec):
        """The Time off and backups table on the Sprint Leave page, read once for the Vacation planner tab."""
        if not os.environ.get("ACME_CONFLUENCE_TOKEN"):
            return [], "Sprint Leave page not read (ACME_CONFLUENCE_TOKEN is not set)"
        try:
            return sprint_leave.load_time_off(), ""
        except Exception as exc:  # noqa: BLE001 - the tab says why
            return [], "Sprint Leave page not read (%s)" % exc

    def unplanned(self, spec):
        """The Unplanned leave log on the Sprint Leave page, for the Unplanned leave tab."""
        if not os.environ.get("ACME_CONFLUENCE_TOKEN"):
            return [], "Sprint Leave page not read (ACME_CONFLUENCE_TOKEN is not set), so only the tracker's numbers"
        try:
            return sprint_leave.load_unplanned(), ""
        except Exception as exc:  # noqa: BLE001 - the tab says why
            return [], "Sprint Leave page not read (%s), so only the tracker's numbers" % exc

    def defect_rca(self, spec):
        """SIT/UAT defects with their story, escape stage, root cause and missed impacts (defect_rca.py)."""
        import defect_rca
        import verifier
        try:
            page = self.client.live_get("/api/2/search", jql=defect_rca.JQL, maxResults=200,
                                        fields="summary,resolution,issuelinks,comment,%s" % defect_lib.F_DETECTED)
        except urllib.error.HTTPError as exc:
            return [], "Jira rejected the defect query (HTTP %d)" % exc.code
        rows, note = [], ""
        try:
            graph = verifier.confidence.link_graph.Graph(verifier.confidence.link_graph.load())
        except Exception as exc:  # noqa: BLE001 - the tab still lists the defects
            graph, note = None, "link graph not read (%s), missed impacts not measured" % exc
        for issue in page.get("issues") or []:
            r = defect_rca.row(issue)
            if graph is not None and r["story"]:
                r["missed"] = verifier.missed_impacts(r["story"], [issue["key"]], graph)["defects"][0]["missed"]
            rows.append(r)
        return rows, note

    def backlog(self, spec):
        """Open stories, defects and epics for the Backlog grid, with the rule-book checks and the sprints to move to."""
        bl = review_pages.bl
        fields = ",".join(["summary", "description", "issuetype", "labels", "status", "priority", bl.F_POINTS,
                           bl.F_SPRINT, bl.F_ACCEPTANCE, bl.F_EPIC_LINK, bl.F_PRIORITY])
        limit = int(spec.get("limit", 200))
        try:
            stories = self.client.live_get("/api/2/search", jql=bl.BACKLOG_JQL, fields=fields, maxResults=limit)
            epics = self.client.live_get("/api/2/search", jql=bl.EPICS_JQL, fields=fields, maxResults=limit)
            demos = self.client.live_get("/api/2/search", jql=team_links.fill_statuses(bl.DEMO_JQL),
                                         fields=fields, maxResults=limit)
        except urllib.error.HTTPError as exc:
            return {}, "Jira rejected the backlog queries (HTTP %d)" % exc.code
        seen = {i.get("key") for i in stories.get("issues") or []}
        stories["issues"] = (stories.get("issues") or []) + [i for i in demos.get("issues") or [] if i.get("key") not in seen]
        sprints = ["Backlog"]
        board = team_board()
        if board:
            try:
                got = self.client.live_get("/agile/1.0/board/%s/sprint" % board, state="active,future")
                sprints += [v["name"] + (" (current)" if v.get("state") == "active" else "") for v in got.get("values") or []]
            except urllib.error.HTTPError:
                pass
        team = [p.get("name", "") for p in people().get("people") or [] if p.get("name")]
        items = review_pages.backlog_items(stories.get("issues") or [], epics.get("issues") or [])
        return {"items": items, "sprints": sprints, "team": team}, ""

    def grooming_prep(self, spec):
        """Grooming prep (grooming_prep.py) over the team's backlog, its open epics and the board's sprints."""
        bl = review_pages.bl
        fields = ",".join(["summary", "issuetype", "labels", "status", "assignee", "reporter", "parent", bl.F_POINTS,
                           bl.F_SPRINT, bl.F_ACCEPTANCE, bl.F_EPIC_LINK])
        ids = {"points": bl.F_POINTS, "sprint": bl.F_SPRINT, "acceptance": bl.F_ACCEPTANCE, "epic_link": bl.F_EPIC_LINK}
        stories, limit = [], int(spec.get("limit", 1000))
        try:
            while len(stories) < limit:
                page = self.client.live_get("/api/2/search", jql=bl.BACKLOG_JQL, fields=fields, startAt=len(stories),
                                            maxResults=100)
                got = page.get("issues") or []
                stories += got
                if not got or len(stories) >= page.get("total", 0):
                    break
            epics = self.client.live_get("/api/2/search", jql=bl.EPICS_JQL, fields="summary,labels", maxResults=500)
        except urllib.error.HTTPError as exc:
            return {}, "Jira rejected the grooming queries (HTTP %d)" % exc.code
        sprints, board = [], team_board()
        if board:
            try:
                got = self.client.live_get("/agile/1.0/board/%s/sprint" % board, state="active,future")
                sprints = [{"name": v.get("name", ""), "state": v.get("state", ""), "start": (v.get("startDate") or "")[:10]}
                           for v in got.get("values") or []]
            except urllib.error.HTTPError:
                pass
        plan, teams, cfg = grooming_prep.context()
        epic_rows = [{"key": e.get("key"), "summary": (e.get("fields") or {}).get("summary", "")}
                     for e in epics.get("issues") or []]
        return grooming_prep.analyse_with_roadmap(grooming_prep.rows_from_issues(stories, ids), epic_rows, sprints, plan, teams, cfg), ""

    def hygiene(self, spec):
        """Rule-book conformance for the team's epics, recent stories and sub-tasks (jira_hygiene.py queries)."""
        try:
            return hygiene_lib.fetch(self.client.live_get), ""
        except urllib.error.HTTPError as exc:
            return {}, "Jira rejected the hygiene queries (HTTP %d)" % exc.code

    def scrum(self, spec):
        """Issues behind the Scrum Master tabs (scrum_metrics.py), read once for all of them."""
        if getattr(self, "_scrum", None) is None:
            try:
                data = scrum_lib.fetch(self.client.live_get, team_scoped, self.active_sprint())
                self._scrum = (data, data.pop("history_note", ""))
            except urllib.error.HTTPError as exc:
                self._scrum = ({}, "Jira rejected the Scrum Master queries (HTTP %d)" % exc.code)
            self._scrum = with_capacity(self._scrum, getattr(self, "capacity_sheet", None))
            self._scrum = with_devin_usage(self._scrum)
        return self._scrum


class CacheSource:
    kind = "cache"

    def __init__(self, path, fragment, base=None):
        with open(path, encoding="utf-8") as fh:
            self.data = json.load(fh)
        self.path = path
        identity = self.data.get("user") or {}
        self.username = identity.get("name") or fragment
        self.display = identity.get("displayName") or self.username
        self.entry = (
            {"roles": identity["roles"]}
            if identity.get("roles")
            else roster_entry(self.username, identity.get("displayName", ""))
        )
        self.base = base or self.data.get("base") or "origin/master"

    def questions(self):
        return self.data.get("questions_for_me", [])

    def my_questions(self):
        return self.data.get("my_questions", [])

    def jira_panel(self, spec):
        rows = (self.data.get("panels") or {}).get(spec["id"])
        if rows is None:
            return [], ""
        return rows, ""

    def demo_board(self, spec):
        return self.jira_panel(spec)

    def defect_rca(self, spec):
        return self.data.get("defect_rca") or [], ""

    def vacation(self, spec):
        return self.data.get("time_off") or [], ""

    def unplanned(self, spec):
        return self.data.get("unplanned") or [], ""

    def defect_matrix(self, spec):
        cached = self.data.get("defect_matrix") or {"issues": [], "epics": {}}
        if isinstance(cached, str):   # a fixture file next to this one
            with open(os.path.join(os.path.dirname(os.path.abspath(self.path)), cached), encoding="utf-8") as fh:
                cached = json.load(fh)
        return cached, ""

    def backlog(self, spec):
        cached = self.data.get("backlog") or {}
        if isinstance(cached, str):   # a fixture file next to this one
            with open(os.path.join(os.path.dirname(os.path.abspath(self.path)), cached), encoding="utf-8") as fh:
                cached = json.load(fh)
        return cached, ""

    def grooming_prep(self, spec):
        cached = self.data.get("grooming_prep") or {}
        if isinstance(cached, str):   # a fixture file next to this one
            with open(os.path.join(os.path.dirname(os.path.abspath(self.path)), cached), encoding="utf-8") as fh:
                cached = json.load(fh)
        if not cached:
            return {}, ""
        plan, teams, cfg = grooming_prep.context()
        today = datetime.date.fromisoformat(cached["today"]) if cached.get("today") else None
        return grooming_prep.analyse_with_roadmap(cached.get("stories") or [], cached.get("epics") or [], cached.get("sprints") or [],
                                     plan, teams, cfg, today), ""

    def hygiene(self, spec):
        cached = self.data.get("hygiene") or {}
        if isinstance(cached, str):   # a fixture file next to this one
            with open(os.path.join(os.path.dirname(os.path.abspath(self.path)), cached), encoding="utf-8") as fh:
                cached = json.load(fh)
        return cached, ""

    def scrum(self, spec):
        cached = self.data.get("scrum") or {}
        if isinstance(cached, str):   # a fixture file next to this one
            with open(os.path.join(os.path.dirname(os.path.abspath(self.path)), cached), encoding="utf-8") as fh:
                cached = json.load(fh)
        return with_capacity((cached, ""), getattr(self, "capacity_sheet", None))

    def workload(self, spec):
        cached = self.data.get("workload") or {}
        return cached.get("sprint") or {}, cached.get("issues") or []

    def team_activity(self, spec):
        cached = self.data.get("team_activity") or {}
        return cached.get("sprint") or {}, cached.get("issues") or []

    def approvals(self):
        return self.data.get("approvals", []), self.data.get("team_pipeline", [])

    def branches(self, scope, assigned_keys):
        rows = [dict(row, base=self.base) for row in self.data.get("branches", [])]
        statuses = {row["key"]: row for row in (self.data.get("branch_status") or [])}
        return decorate_branches(
            rows, statuses, assigned_keys if scope == "mine" else None, self.display
        )

    def automation_branches(self, spec):
        cached = self.data.get("automation_branches")
        if cached is None:
            return automation_branch_rows(spec, self.username, self.display)
        return cached.get("rows") or [], cached.get("base") or "", cached.get("note") or ""

    def roster(self):
        """(findings, is_steward) from the fixture when it carries them, else the real roster."""
        cached = self.data.get("roster_findings")
        if cached is None:
            return roster_findings(), self.username in roster_stewards()
        return [tuple(row) for row in cached], True

    def sessions(self, path):
        if path or self.data.get("sessions") is None:
            return session_rows(path)
        return session_rows_from(self.data.get("sessions"))

    def health(self):
        cached = self.data.get("metrics")
        if cached is None:
            return health_summary()
        return metrics.summary(cached)


def esc(value):
    return html.escape(str(value if value is not None else ""), quote=True)


def jira_link(key, label=None):
    key = key or ""
    if not key:
        return esc(label or "")
    return '<a href="https://jira.acme.example/browse/%s">%s</a>' % (esc(key), esc(label or key))


def age_text(age):
    return "%s day old" % age if age == 1 else "%s days old" % age


# How loudly a tab asks for the viewer. Tabs sort in this order; an empty tab is always "clear".
ATTENTION_ORDER = {"hot": 0, "watch": 1, "info": 2, "action": 3, "clear": 4}
ATTENTION_LABELS = {
    "hot": "needs you", "watch": "waiting", "info": "for reference",
    "action": "tools", "clear": "all clear",
}


def panel(title, body, empty="Nothing here.", note="", count=None, attention=None, action=""):
    """One tab of the page. `count` is the badge on the tab, `attention` its colour, `action` the
    generate button that belongs to it (only that button shows while the tab is open)."""
    body = body or ""
    if not body:
        attention, count = "clear", 0
    return {
        "title": title, "body": body, "empty": empty, "note": note,
        "count": count, "attention": attention or "watch", "action": action if body else "",
    }


def labelled(section, icon="", tab=""):
    """Give a rendered tab its icon and short strip label; the full title stays the heading."""
    section["icon"] = icon or section.get("icon", "")
    section["tab"] = tab or section.get("tab", "")
    return section


# The tab strip is split into these groups, loudest first; an empty group is left out.
TAB_GROUPS = [
    ("Needs you", ("hot",)),
    ("Waiting", ("watch",)),
    ("Reference", ("info",)),
    ("Tools", ("action",)),
    ("All clear", ("clear",)),
]


def attention_for(rows, hot_when, otherwise="info"):
    """"hot" when any row trips the predicate, else the quieter level."""
    return "hot" if any(hot_when(row) for row in rows) else otherwise


def table(head_cells, rows):
    """A kit table inside its horizontal scroller; `head_cells` and `rows` are HTML."""
    return (
        '<div class="a-table-scroll"><table class="a-table"><thead><tr>%s</tr></thead>'
        '<tbody>%s</tbody></table></div>' % (head_cells, rows)
    )


def tab_icon(spec):
    icon = spec.get("icon") or ""
    return '<span class="tab-icon" aria-hidden="true">%s</span>' % esc(icon) if icon else ""


def render_tab(index, spec):
    note_html = '<p class="a-section__note">%s</p>' % esc(spec["note"]) if spec["note"] else ""
    if spec.get("workbench"):
        note_html += ('<p class="wb-link"><a class="a-btn a-btn--outline" data-wb href="%s" target="_blank" rel="noopener">'
                      'Do this in Argus: %s</a></p>' % (esc(spec["workbench"][0]), esc(spec["workbench"][1])))
    body = spec["body"] or '<p class="a-empty">%s</p>' % esc(spec["empty"])
    return (
        '<section class="a-section tabpanel" id="tab-%d" role="tabpanel" aria-labelledby="tabbtn-%d" '
        'data-attention="%s" data-action="%s" hidden><h2 class="a-section__title">%s%s</h2>%s'
        '<div class="panel-body">%s</div></section>'
        % (index, index, esc(spec["attention"]), esc(spec.get("action", "")), tab_icon(spec),
           esc(spec["title"]), note_html, body)
    )


def render_tab_button(index, spec):
    """A short label and an icon on the strip; the full title is the tooltip and the accessible name."""
    level = spec["attention"]
    count = spec["count"]
    badge = '<span class="a-badge">%s</span>' % esc(count) if count and level in ("hot", "watch") else ""
    return (
        '<button class="a-btn" id="tabbtn-%d" role="tab" type="button" data-attention="%s" '
        'aria-controls="tab-%d" aria-selected="%s" aria-label="%s" title="%s — %s">'
        '%s<span class="tab-label">%s</span>%s</button>'
        % (index, esc(level), index, "true" if index == 0 else "false", esc(spec["title"]),
           esc(spec["title"]), esc(ATTENTION_LABELS.get(level, level)), tab_icon(spec),
           esc(spec.get("tab") or spec["title"]), badge)
    )


def place_in_groups(sections, groups, workbench_url=""):
    """Job groups from business-screens.json: each tab under the first task that names its panel, with a link
    to do that task in Argus. Questions sit under Mine; anything no task names goes under Reference."""
    where = {}
    for gi, group in enumerate(groups):
        for task in group.get("tasks") or []:
            for pid in task.get("panels") or []:
                where.setdefault(pid, (gi, task))
    mine = next((i for i, g in enumerate(groups) if g.get("group") == "Mine"), len(groups))
    for section in sections:
        pid = section.get("panel_id", "")
        gi, task = (mine, where.get("approvals", (0, None))[1]) if pid in ("questions", "asked") else \
            where.get(pid, (len(groups), None))
        section["group_index"] = gi
        if task and workbench_url:
            section["workbench"] = (workbench_url.rstrip("/") + "/#task=" + task["id"], task["label"])


def render_group_nav(groups, label="Dashboard sections"):
    """Two short rows: the group buttons, then the tabs of the open group only. `groups` is a list of
    (label, attention, tab buttons HTML, tab count); the group holding the selected tab starts open."""
    switches, rows = [], []
    for gi, (name, attention, buttons, count) in enumerate(groups):
        open_ = 'aria-selected="true"' in buttons
        switches.append(
            '<button type="button" class="tab-switch" data-attention="%s" aria-controls="tabgroup-%d" '
            'aria-pressed="%s"><span class="a-dot"></span>%s<span class="tab-switch__n">%d</span></button>'
            % (esc(attention), gi, "true" if open_ else "false", esc(name), count))
        rows.append(
            '<div class="tab-group" id="tabgroup-%d" role="none" data-attention="%s"%s>'
            '<span class="tab-group__label" aria-hidden="true">%s</span>'
            '<div class="tab-group__tabs" role="none">%s</div></div>'
            % (gi, esc(attention), "" if open_ else " hidden", esc(name), buttons))
    return ('<nav class="tab-nav" aria-label="%s"><div class="tab-switches a-no-print" role="group" '
            'aria-label="Tab groups">%s</div><div class="a-tabs tab-strip" data-a-tabs role="tablist" '
            'aria-label="%s">%s</div></nav>' % (esc(label), "".join(switches), esc(label), "".join(rows)))


def render_job_strip(sections, labels):
    """Tab buttons grouped by job (Plan, Groom, Sprint ...); each group's colour is its loudest tab."""
    groups = []
    for gi, label in enumerate(labels):
        members = [(i, s) for i, s in enumerate(sections) if s.get("group_index") == gi]
        if not members:
            continue
        loud = min((s["attention"] for _, s in members), key=lambda a: ATTENTION_ORDER.get(a, 9))
        groups.append((label, loud, "".join(render_tab_button(i, s) for i, s in members), len(members)))
    return render_group_nav(groups)


def render_tab_strip(sections):
    """Tab buttons in their TAB_GROUPS, numbered in the order the panels were sorted; a tab whose panel names a
    `group` goes in that group instead, after the attention groups."""
    groups = []
    for label, levels in TAB_GROUPS:
        members = [(i, s) for i, s in enumerate(sections) if s["attention"] in levels and not s.get("group")]
        if members:
            groups.append((label, levels[0], "".join(render_tab_button(i, s) for i, s in members), len(members)))
    named = []
    for s in sections:
        if s.get("group") and s["group"] not in named:
            named.append(s["group"])
    for label in named:
        members = [(i, s) for i, s in enumerate(sections) if s.get("group") == label]
        loud = min((s["attention"] for _, s in members), key=lambda a: ATTENTION_ORDER.get(a, 9))
        groups.append((label, loud, "".join(render_tab_button(i, s) for i, s in members), len(members)))
    return render_group_nav(groups)


def render_questions(title, items, answer_box=False):
    if not items:
        return panel(title, "", "No open questions.")
    cards = []
    for item in items:
        older = isinstance(item.get("age"), int) and item["age"] > 3
        answer = (
            '<label class="a-field">Answer<textarea data-question-key="%s" rows="5"></textarea></label>'
            '<p class="meta">Click Generate answers, then Save. In a copy attached in chat, paste the block into chat instead.</p>'
        ) % esc(item.get("key"))
        answer_html = answer if answer_box else (
            '<p class="a-pre"><b>%s</b></p>' % esc(item.get("answer") or "Waiting for an answer.")
        )
        cards.append(
            '<article class="a-panel question"%s><div class="a-panel__head"><span class="a-panel__title">%s · '
            '%s</span><span class="age">%s</span></div>'
            '<p class="meta">%s</p>'
            '<p class="meta">Asked by %s</p><p>%s</p>%s</article>'
            % (
                ' data-attention="hot"' if older else "",
                jira_link(item.get("key")),
                jira_link(item.get("parent"), item.get("parent") or "no parent"),
                esc("%s — older than 3 days" % age_text(item.get("age")) if older else age_text(item.get("age"))),
                esc(item.get("parent_title") or ""),
                esc(item.get("asker")),
                esc(item.get("question")),
                answer_html,
            )
        )
    return panel(title, "\n".join(cards), count=len(items), attention="hot",
                 action="answers" if answer_box else "")


def render_my_questions(items):
    if not items:
        return panel("My questions", "", "You have no unresolved questions.")
    cards = []
    for item in items:
        state = "Waiting for answer" if item.get("waiting") else "Answered — review and close"
        answer = item.get("answer") or "No answer comment yet."
        if item.get("answer_by"):
            answer = '<b>Answer from %s:</b><br>%s' % (esc(item["answer_by"]), esc(answer))
        else:
            answer = esc(answer)
        cards.append(
            '<article class="a-panel question"><div class="a-panel__head"><span class="a-panel__title">%s · %s'
            '</span><span class="age">%s</span></div><p class="meta">With %s</p><p>%s</p>'
            '<p class="a-pre">%s</p></article>'
            % (
                jira_link(item.get("key")), jira_link(item.get("parent"), item.get("parent") or "no parent"),
                esc(state), esc(item.get("assignee_display") or "an answerer"),
                esc(item.get("question")),
                answer,
            )
        )
    waiting = [item for item in items if item.get("waiting")]
    return panel(
        "My questions", "\n".join(cards), count=len(items),
        attention="watch" if waiting else "info",
    )


COLUMN_LABELS = {
    "key": "Key", "type": "Type", "summary": "Summary", "status": "Status",
    "assignee": "Assignee", "reporter": "Raised by", "priority": "Priority",
    "severity": "Severity", "points": "Points", "sprint": "Sprint",
    "created": "Raised", "updated": "Updated",
}


def render_jira_panel(spec, rows, note):
    columns = spec.get("columns") or ["key", "type", "summary", "status", "updated"]
    if not rows:
        return panel(spec.get("title", spec["id"]), "", spec.get("empty", "Nothing here."), note)
    head = "".join("<th>%s</th>" % esc(COLUMN_LABELS.get(column, column)) for column in columns)
    body = []
    for row in rows:
        cells = []
        for column in columns:
            value = row.get(column, "")
            cells.append("<td>%s</td>" % (jira_link(value) if column == "key" else esc(value)))
        body.append("<tr>%s</tr>" % "".join(cells))
    return panel(
        spec.get("title", spec["id"]), table(head, "".join(body)), note=note, count=len(rows),
        attention=spec.get("attention", "watch"),
    )


def with_recordings(rows):
    """Mark each row with its published demo (url and AC count) from Confluence; a page that
    cannot be read leaves the column unknown and says why."""
    import demo_needed
    try:
        found = demo_needed.recorded(demo_needed.confluence())
    except Exception as exc:  # noqa: BLE001 - the tab says why
        return [dict(r, recorded=None) for r in rows], "Demo recordings page not read (%s)" % exc
    return [dict(r, recorded=found.get(r.get("key"), {})) for r in rows], ""


def sprint_order(name):
    """Newest sprint first by its number (26.4.2 after 26.4.1); stories in no sprint last."""
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", name or "")
    return (0, tuple(-int(n) for n in m.groups()), "") if m else ((1, (), name) if name else (2, (), ""))


def recorded_cell(value):
    if value is None:
        return '<span class="demo-unknown" title="Confluence was not read">?</span>'
    if not value:
        return '<span class="demo-no">Not recorded</span>'
    return '<a class="demo-yes" href="%s" target="_blank" rel="noopener">Recorded · %d AC</a>' % (
        esc(value.get("url", "")), value.get("acs", 0))


def render_demo_board(spec, rows, note):
    """Stories labelled for a demo, one collapsible group per sprint (newest open), with a
    Demo recorded column read from the Acme Claims Demo Recordings pages."""
    columns = [c for c in (spec.get("columns") or ["key", "type", "summary", "status", "assignee", "updated"])
               if c != "sprint"]
    if not rows:
        return panel(spec.get("title", spec["id"]), "", spec.get("empty", "Nothing here."), note)
    groups = {}
    for row in rows:
        groups.setdefault(row.get("sprint") or "", []).append(row)
    head = "".join("<th>%s</th>" % esc(COLUMN_LABELS.get(c, c)) for c in columns) + "<th>Demo recorded</th>"
    parts = []
    for i, name in enumerate(sorted(groups, key=sprint_order)):
        items = sorted(groups[name], key=lambda r: r.get("key", ""))
        done = sum(1 for r in items if r.get("recorded"))
        body = "".join(
            "<tr>%s<td>%s</td></tr>" % ("".join(
                "<td>%s</td>" % (jira_link(r.get(c, "")) if c == "key" else esc(r.get(c, ""))) for c in columns),
                recorded_cell(r.get("recorded")))
            for r in items)
        parts.append('<details class="demo-sprint"%s><summary><strong>%s</strong> · %d %s · %d recorded</summary>%s</details>'
                     % (" open" if i == 0 else "", esc(name or "Not in a sprint"), len(items),
                        "story" if len(items) == 1 else "stories", done, table(head, body)))
    tools = ('<p class="demo-tools"><button type="button" class="a-btn a-btn--outline" data-demo-open="1">Expand all</button> '
             '<button type="button" class="a-btn a-btn--outline" data-demo-open="0">Collapse all</button></p>')
    return panel(spec.get("title", spec["id"]), tools + "".join(parts), note=note, count=len(rows),
                 attention=spec.get("attention", "watch"))


DEMO_CSS = (".demo-sprint{margin:4px 0}.demo-sprint>summary{cursor:pointer;padding:6px 0}"
            ".demo-yes{font-weight:600}.demo-no,.demo-unknown{color:rgb(var(--text-secondary))}")
DEMO_JS = """
document.addEventListener("click", function (e) {
  var b = e.target.closest && e.target.closest("[data-demo-open]");
  if (!b) return;
  var open = b.getAttribute("data-demo-open") === "1";
  b.closest(".tabpanel, body").querySelectorAll("details.demo-sprint").forEach(function (d) { d.open = open; });
});
"""


ROSTER_LABELS = {
    "schema": "Incomplete entry",
    "vocabulary": "Role not in the vocabulary",
    "hints": "Hint for a hat the person does not hold",
    "routing": "Routing points at something missing",
    "unresolved": "Person cannot be matched",
    "gap": "Gate nobody can sign",
}


def roster_stewards():
    """Jira usernames of the roster resolver and their backups."""
    owner = people().get("owner") or {}
    return [u for u in [owner.get("primary")] + list(owner.get("backups") or []) if u]


def roster_findings():
    """Drift the roster can see without Jira: incomplete entries, bad roles, unsigned gates."""
    routing = load_yaml(
        os.path.join(ROOT, ".devin", "rules", "role-routing.yaml"), {}
    )
    roster = people()
    if not routing or not roster.get("people"):
        return []
    return reconcile_roster.config_findings(roster["people"], routing)


def render_roster(spec, findings, is_steward):
    title = spec.get("title", "Roster")
    if not is_steward:
        return panel(title, "", "Only the roster resolver and their backups see this panel.")
    if not findings:
        return panel(title, "", "No drift. Every entry is complete and every gate has a signer.")
    rows = []
    for kind, message in sorted(findings):
        rows.append(
            "<tr><td>%s</td><td>%s</td></tr>"
            % (esc(ROSTER_LABELS.get(kind, kind)), esc(message))
        )
    table = (
        "<table><thead><tr><th>Finding</th><th>Detail</th></tr></thead><tbody>%s</tbody></table>"
        % "".join(rows)
    )
    return panel(
        title, table, count=len(findings), attention="hot",
        note=spec.get("note", "Run /roster-check to reconcile against Jira and raise the pull "
                              "request; roster changes are reviewed, never applied from here."),
    )


DOC_MARKER = "REQUIRES STAKEHOLDER INPUT"


def doc_marker_hits(spec):
    """Documents carrying the marker that says a generated document is waiting on a human answer.

    The markers live in the knowledge base and the session specs, not in Jira, so nobody sees them
    unless they open the file. One row per document, with the questions it is holding.
    """
    marker = spec.get("marker") or DOC_MARKER
    excludes = [re.compile(p) for p in spec.get("exclude") or []]
    hits = []
    for pattern in spec.get("include") or []:
        for path in sorted(glob.glob(os.path.join(ROOT, pattern), recursive=True)):
            rel = os.path.relpath(path, ROOT)
            if any(rule.search(rel) for rule in excludes) or not os.path.isfile(path):
                continue
            try:
                with open(path, encoding="utf-8", errors="replace") as handle:
                    lines = [l.strip() for l in handle if open_question(l, marker)]
            except OSError:
                continue
            if lines:
                hits.append({"document": rel, "count": len(lines), "questions": lines})
    hits.sort(key=lambda h: (-h["count"], h["document"]))
    return hits


def open_question(line, marker):
    """True for a line that *is* an open question rather than prose about the marker.

    The pipelines write the marker two other ways: as a heading recording that the markers were
    resolved, and quoted in backticks while explaining the convention. Neither is waiting on anyone.
    """
    text = line.strip()
    if marker not in text or text.startswith("#"):
        return False
    return "`[%s]`" % marker not in text and "`%s`" % marker not in text


def marker_question(line, marker):
    """The readable question out of a marker line.

    The question is written after the marker where there is one — `[MARKER — what is unknown]` —
    and the line is a table row or a bullet about the marker where there is not, so the text
    before it is the next best thing.
    """
    head, _, tail = line.partition(marker)
    text = trim_markup(tail) or trim_markup(head)
    return text or "no question text on the line"


def trim_markup(text):
    """A line of markdown reduced to its sentence: no table pipes, list bullets or code fences."""
    text = re.sub(r"\s+", " ", text.replace("%%", " "))
    return text.strip().strip("`*_|#[]—-:. ").strip()


def render_doc_questions(spec, hits):
    title = spec.get("title", "Documents waiting on an answer")
    if not hits:
        return panel(title, "", spec.get("empty", "No document is waiting on a business answer."))
    marker = spec.get("marker") or DOC_MARKER
    limit = int(spec.get("limit") or 10)
    shown = hits[:limit]
    rows = []
    for hit in shown:
        first = marker_question(hit["questions"][0], marker)
        if len(first) > 160:
            first = first[:157] + "…"
        more = (" and %d more" % (hit["count"] - 1)) if hit["count"] > 1 else ""
        rows.append(
            "<tr><td>%s</td><td>%s</td><td>%s%s</td></tr>"
            % (esc(os.path.basename(hit["document"])), esc(hit["count"]), esc(first), esc(more))
        )
        rows.append('<tr><td colspan="3" class="sub">%s</td></tr>' % esc(hit["document"]))
    table = (
        "<table><thead><tr><th>Document</th><th>Open items</th><th>First question</th></tr></thead>"
        "<tbody>%s</tbody></table>" % "".join(rows)
    )
    total = sum(hit["count"] for hit in hits)
    note = "%d open items across %d documents%s. Answering one is an edit to that document — " % (
        total, len(hits), "" if len(hits) <= limit else ", %d documents shown" % limit
    ) + "/document-validation collects them into a form, /explain-capability answers from what the " \
        "knowledge base already knows."
    return panel(title, table, note=spec.get("note", note), count=total, attention="watch")


def learn_questions(name):
    """The viewer's open questions in the learn-more list, or none when the list cannot be read."""
    try:
        import learn_more
        return learn_more.for_person(learn_more.load(), name) if name else []
    except (OSError, ValueError, ImportError):
        return []


def render_learn(spec, items):
    title = spec.get("title", "Learn about who you serve")
    if not items:
        return panel(title, "", spec.get("empty", "Devin has no questions for you right now."))
    rows = "".join(
        "<tr><td>%s</td><td>%s</td><td>%s</td></tr>"
        % (esc(q.get("id", "")), esc(q.get("question", "")), esc(q.get("update", "")))
        for q in items
    )
    table = ("<table><thead><tr><th>#</th><th>Question</th><th>Where the answer goes</th></tr></thead>"
             "<tbody>%s</tbody></table>" % rows)
    return panel(title, table, note=spec.get("note", ""), count=len(items), attention="watch")


def render_commands(spec, roles, lens_id=""):
    """Every command, the person's first: nothing is buried under the full list. Roles the routing file does not
    know fall back to the roles that open this lens."""
    table_roles = skill_homes.routing().get("roles") or {}
    mine = [r for r in roles or [] if r in table_roles] or [r for r, v in table_roles.items()
                                                           if v.get("dashboard_lens") == lens_id]
    got = skill_homes.for_roles(mine)

    def table(items):
        return ("<table><thead><tr><th>Command</th><th>What it does</th></tr></thead><tbody>%s</tbody></table>"
                % "".join("<tr><td><code>/%s</code></td><td>%s</td></tr>" % (esc(s["name"]), esc(s["what"])) for s in items))

    parts = ["<h3>%s</h3>%s" % (head, table(got[key])) for key, head in
             (("first", "Your first commands"), ("more", "Also for your role"), ("everyone", "For everyone")) if got[key]]
    if got["pipelines"]:
        parts.append("<details><summary>Documentation pipelines and their stages (%d)</summary>%s</details>" % (
            sum(len(v) for v in got["pipelines"].values()),
            "".join("<p><code>/%s</code> runs %s</p>" % (esc(p), ", ".join("<code>/%s</code>" % esc(s["name"]) for s in v))
                    for p, v in sorted(got["pipelines"].items()))))
    if got["aliases"]:
        parts.append("<p>Older names that still work: %s.</p>" % ", ".join(
            "<code>/%s</code> for <code>/%s</code>" % (esc(a), esc(b)) for a, b in got["aliases"]))
    if got["internal"]:
        parts.append("<details><summary>Internal to the system (%d)</summary>%s</details>" % (len(got["internal"]), "".join(
            "<p><code>/%s</code> %s</p>" % (esc(s["name"]), esc(s["why"])) for s in got["internal"])))
    if got["other"]:
        parts.append("<details><summary>Every other command (%d)</summary>%s</details>" % (len(got["other"]), table(got["other"])))
    mine = len(got["first"]) + len(got["more"])
    return panel(spec.get("title", "My commands"), "".join(parts), spec.get("empty", "No commands found."),
                 spec.get("note", ""), count=mine, attention="info")


SKILL_CONFIG_JS = """<script>(function () {
  var MARK = {none: "", tick: "\u2713", first: "\u2605", some: "\u25d0"};
  var NEXT = {none: "tick", tick: "first", first: "none", some: "tick"};
  var root = document.getElementById("skill-config");
  if (!root) { return; }
  root.addEventListener("click", function (ev) {
    var b = ev.target.closest("button.sc-cell"); if (!b) { return; }
    var s = b.dataset.state, n = b.dataset.col === "Everyone" ? (s === "none" ? "tick" : "none") : NEXT[s];
    b.dataset.state = n; b.textContent = MARK[n]; b.classList.toggle("sc-changed", n !== b.dataset.was);
  });
  var q = document.getElementById("sc-filter");
  q.addEventListener("input", function () {
    var v = q.value.toLowerCase();
    root.querySelectorAll("tbody tr").forEach(function (r) { r.hidden = v && r.dataset.k.indexOf(v) < 0; });
  });
  document.getElementById("sc-preview").addEventListener("click", function () {
    var lines = ["SDLC-DASHBOARD-SKILL-CONFIG v1"];
    root.querySelectorAll("button.sc-changed").forEach(function (b) {
      lines.push("- skill: " + b.dataset.skill + " | " + b.dataset.col + ": " + b.dataset.state);
    });
    lines.push("END");
    var out = document.getElementById("sc-block");
    out.hidden = false;
    out.value = lines.length > 2 ? lines.join("\\n") : "No ticks changed yet.";
    out.select();
  });
})();</script>"""


ROLE_CONFIG_JS = """<script>(function () {
  var root = document.getElementById("role-config");
  if (!root) { return; }
  var MARK = {none: "", secondary: "\u2713", primary: "\u25cf"};
  root.addEventListener("click", function (ev) {
    var b = ev.target.closest("button.rc-cell"); if (!b) { return; }
    var n = {none: "secondary", secondary: "primary", primary: "none"}[b.dataset.state];
    if (n === "primary") {
      b.closest("tr").querySelectorAll("button.rc-cell").forEach(function (o) {
        if (o !== b && o.dataset.state === "primary") { o.dataset.state = "secondary"; o.textContent = MARK.secondary;
          o.classList.toggle("sc-changed", o.dataset.state !== o.dataset.was); }
      });
    }
    b.dataset.state = n; b.textContent = MARK[n]; b.classList.toggle("sc-changed", n !== b.dataset.was);
  });
  document.getElementById("rc-preview").addEventListener("click", function () {
    var lines = ["SDLC-DASHBOARD-ROLE-CONFIG v1"];
    root.querySelectorAll("button.sc-changed").forEach(function (b) {
      lines.push("- person: " + b.dataset.person + " | " + b.dataset.role + ": " + b.dataset.state);
    });
    lines.push("END");
    var out = document.getElementById("rc-block");
    out.hidden = false; out.value = lines.length > 2 ? lines.join("\\n") : "No ticks changed yet."; out.select();
  });
})();</script>"""


SAVE_JS = """<script>(function () {
  "use strict";
  // Save: the block goes to Argus that served this page (on the PC or in Devin Cloud), which starts a run.
  var onArgus = /^https?:$/.test(location.protocol) && /^\/(dashboard|actions)$/.test(location.pathname);
  function blockOf(box) { var t = (box && box.value || "").trim(); return /^#?\\s*SDLC-[A-Z-]+ v\\d/.test(t) ? t : ""; }
  // Each Save has its own Dry run tick, on by default like Argus: a dry run shows the change and writes nothing.
  function dryOf(b) {
    var d = b.nextElementSibling;
    if (!d || !d.classList.contains("save-dry")) {
      d = document.createElement("label");
      d.className = "save-dry";
      d.title = "A dry run shows the change and writes nothing; untick to raise the pull request after you approve";
      d.innerHTML = ' <input type="checkbox" checked> Dry run';
      b.parentNode.insertBefore(d, b.nextSibling);
    }
    return d;
  }
  function ready() {
    document.querySelectorAll("[data-save]").forEach(function (b) {
      var box = document.getElementById(b.dataset.save);
      b.hidden = !onArgus || (!b.dataset.preview && !blockOf(box));
      if (onArgus) { dryOf(b).hidden = b.hidden; }
    });
  }
  window.sdlcSaveReady = ready;
  document.querySelectorAll("[data-save]").forEach(function (b) {
    b.addEventListener("click", function () {
      if (b.dataset.preview) { var pv = document.getElementById(b.dataset.preview); if (pv) pv.click(); }
      var block = blockOf(document.getElementById(b.dataset.save));
      if (!block || /^SDLC-[A-Z-]+ v\\d\\s*\\nEND$/.test(block)) { alert("Nothing to save yet: change something first."); return; }
      var win = window.open("", "_blank");
      b.disabled = true;
      fetch("/api/blocks", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ block: block, dry_run: dryOf(b).querySelector("input").checked }) })
        .then(function (r) { return r.json(); })
        .then(function (run) {
          if (!run.id) throw new Error(run.error || "Argus did not start a run");
          if (win) { win.location = "/run/" + run.id; } else { location = "/run/" + run.id; }
          b.textContent = "Saved: check the run page";
        })
        .catch(function (e) { if (win) win.close(); b.disabled = false; alert("Could not save: " + e.message); });
    });
  });
  ready();
})();</script>"""


WORKBENCH_CONFIG_JS = """<script>(function () {
  var root = document.getElementById("workbench-config");
  if (!root) { return; }
  root.addEventListener("change", function (ev) {
    var s = ev.target.closest("select.wc-mode"); if (!s) { return; }
    s.classList.toggle("sc-changed", s.value !== s.dataset.was);
  });
  document.getElementById("wc-preview").addEventListener("click", function () {
    var lines = ["SDLC-DASHBOARD-WORKBENCH-CONFIG v1"];
    root.querySelectorAll("select.sc-changed").forEach(function (s) {
      lines.push("- person: " + s.dataset.person + " | test_on_pc: " + s.value);
    });
    lines.push("END");
    var out = document.getElementById("wc-block");
    out.hidden = false; out.value = lines.length > 2 ? lines.join("\\n") : "No choices changed yet."; out.select();
  });
})();</script>"""


def render_workbench_config(spec):
    """Everyone on the roster and how Test on my PC runs for them, with the team default on top."""
    dflt, rows = workbench_config.grid()

    def select(user, value, allow_default):
        opts = ([("default", "Team default")] if allow_default else []) + [(m, workbench_config.LABELS[m])
                                                                           for m in workbench_config.MODES]
        return ('<select class="wc-mode" data-person="%s" data-was="%s" aria-label="Test on my PC for %s">%s</select>' % (
            esc(user), esc(value), esc(user), "".join('<option value="%s"%s>%s</option>' % (
                esc(v), " selected" if v == value else "", esc(label)) for v, label in opts)))
    body = '<tr><td><strong>Team default</strong></td><td>%s</td><td>%s</td></tr>' % (
        select("default", dflt, False), esc(workbench_config.LABELS[dflt]))
    body += "".join('<tr><td>%s<br><span class="a-section__note">%s</span></td><td>%s</td><td>%s</td></tr>' % (
        esc(r["name"]), esc(r["jira_user"]), select(r["jira_user"], r["own"] or "default", True),
        esc(workbench_config.LABELS[r["applies"]])) for r in rows)
    out = ("<p><strong>%d people</strong> on the roster. Test on my PC runs through Local Hands from the person's Devin "
           "Cloud Argus (the org's Local Hands setting must be on), Devin Local on the PC (needs the Devin API key "
           "there), the Devin Cloud VM, or is off. Pick a choice, then Preview change.</p>"
           '<div id="workbench-config" style="overflow-x:auto"><table><thead><tr><th>Person</th><th>Test on my PC</th>'
           "<th>Applies now</th></tr></thead><tbody>%s</tbody></table></div>"
           '<p><button type="button" id="wc-preview">Preview change</button> <button type="button" data-save="wc-block" '
           'data-preview="wc-preview" hidden>Save</button></p>'
           '<textarea id="wc-block" aria-label="Text to paste into Devin" rows="8" style="width:100%%" hidden readonly></textarea>'
           "<p>Save (or, in a saved copy of this page, paste the block into Devin) shows the change to "
           "<code>.devin/rules/workbench-settings.yaml</code>; after you say approved it raises a pull request for "
           "review.</p>" % (len(rows), body)) + WORKBENCH_CONFIG_JS
    return panel(spec.get("title", "Argus config"), out, "", spec.get("note", ""), count=len(rows), attention="info")

def render_role_config(spec):
    """Every person on the roster against every role: the main role, the other hats and the gates they can sign."""
    cols, rows = role_config.grid()
    mark = {"none": "", "secondary": "\u2713", "primary": "\u25cf"}
    head = "".join("<th>%s</th>" % esc(label) for _, label in cols)
    body = "".join('<tr><td>%s<br><span class="a-section__note">%s</span></td>%s<td>%s</td></tr>' % (
        esc(r["name"]), esc(r["jira_user"]),
        "".join('<td><button type="button" class="rc-cell sc-cell" data-person="%s" data-role="%s" data-state="%s" '
                'data-was="%s" title="%s">%s</button></td>' % (esc(r["jira_user"]), esc(c), r["cells"][c], r["cells"][c],
                                                             esc(label), mark[r["cells"][c]]) for c, label in cols),
        esc(", ".join(r["gates"]) or "none")) for r in rows)
    out = ("<p><strong>%d people</strong> on the roster. \u25cf main role (one per person) \u00b7 \u2713 another hat. "
           "The role gives the skills ticked in Skill config, the dashboard view and the gates in the last column. "
           "Click a box to change it, then Preview change.</p>"
           '<div id="role-config" style="overflow-x:auto"><table><thead><tr><th>Person</th>%s<th>Can sign</th></tr></thead>'
           "<tbody>%s</tbody></table></div>"
           '<p><button type="button" id="rc-preview">Preview change</button> <button type="button" data-save="rc-block" data-preview="rc-preview" hidden>Save</button></p>'
           '<textarea id="rc-block" aria-label="Text to paste into Devin" rows="8" style="width:100%%" hidden readonly></textarea>'
           "<p>Save (or, in a saved copy of this page, paste the block into Devin) shows the change to <code>.devin/rules/people.yaml</code>; after you say "
           "approved it raises a pull request for the roster owner or a backup to review (nobody approves their own row). "
           "After the merge, <code>/roster-sync</code> copies it to the Confluence roster page.</p>"
           % (len(rows), head, body)) + ROLE_CONFIG_JS
    return panel(spec.get("title", "Role config"), out, "", spec.get("note", ""), count=len(rows), attention="info")


GATE_CONFIG_JS = """<script>(function () {
  var root = document.getElementById("gate-config");
  if (!root) { return; }
  var MARK = {none: "", backup: "\u2713", named: "\u25cf"};
  root.addEventListener("click", function (ev) {
    var b = ev.target.closest("button.gc-cell"); if (!b) { return; }
    var n = {none: "named", named: "backup", backup: "none"}[b.dataset.state];
    b.dataset.state = n; b.textContent = MARK[n]; b.classList.toggle("sc-changed", n !== b.dataset.was);
  });
  document.getElementById("gc-preview").addEventListener("click", function () {
    var lines = ["SDLC-DASHBOARD-GATE-CONFIG v1"], empty = [];
    root.querySelectorAll("tbody tr").forEach(function (tr) {
      if (!tr.querySelector('button.gc-cell[data-state="named"]')) { empty.push(tr.dataset.gate); }
    });
    root.querySelectorAll("button.sc-changed").forEach(function (b) {
      lines.push("- gate: " + b.dataset.gate + " | " + b.dataset.person + ": " + b.dataset.state);
    });
    lines.push("END");
    var out = document.getElementById("gc-block");
    out.hidden = false;
    out.value = empty.length ? "Every gate needs at least one named approver (\u25cf): " + empty.join(", ")
      : lines.length > 2 ? lines.join("\\n") : "No ticks changed yet.";
    out.select();
  });
})();</script>"""


def render_gate_config(spec):
    """Every approval gate against every person on the roster: who signs it, who backs them up, its timeout and what it blocks."""
    people, rows = gate_config.grid()
    mark = {"none": "", "backup": "\u2713", "named": "\u25cf"}
    head = "".join("<th>%s</th>" % esc(p.get("name")) for p in people)
    body = "".join('<tr data-gate="%s"><td>%s<br><span class="a-section__note">%s<br>Timeout %s \u00b7 blocks %s</span></td>%s</tr>' % (
        esc(r["id"]), esc(r["id"]), esc(r["name"]),
        esc("%s h" % r["timeout"] if r["timeout"] is not None else "none"), esc(r["blocks"] or "nothing named"),
        "".join('<td><button type="button" class="gc-cell sc-cell" data-gate="%s" data-person="%s" data-state="%s" '
                'data-was="%s" title="%s">%s</button></td>' % (
                    esc(r["id"]), esc(p["jira_user"]), r["cells"][str(p["jira_user"])], r["cells"][str(p["jira_user"])],
                    esc(p.get("name")), mark[r["cells"][str(p["jira_user"])]]) for p in people)) for r in rows)
    out = ("<p><strong>%d gates</strong>. \u25cf signs the gate \u00b7 \u2713 backup, asked when everyone named is away "
           "(after each person's own time-off backup). Every gate keeps at least one \u25cf. "
           "Click a box to change it, then Preview change.</p>"
           '<div id="gate-config" style="overflow-x:auto"><table><thead><tr><th>Gate</th>%s'
           "</tr></thead><tbody>%s</tbody></table></div>"
           '<p><button type="button" id="gc-preview">Preview change</button> <button type="button" data-save="gc-block" data-preview="gc-preview" hidden>Save</button></p>'
           '<textarea id="gc-block" aria-label="Text to paste into Devin" rows="8" style="width:100%%" hidden readonly></textarea>'
           "<p>Save (or, in a saved copy of this page, paste the block into Devin) shows the change to <code>.devin/rules/approval-gates.yaml</code>; after you say "
           "approved it raises a pull request for review.</p>" % (len(rows), head, body)) + GATE_CONFIG_JS
    return panel(spec.get("title", "Gate config"), out, "", spec.get("note", ""), count=len(rows), attention="info")


def render_skill_config(spec):
    """Every skill against every role column: the ticks are default_skills (a star), more_skills and everyone_skills in
    role-routing.yaml. Changed ticks become a block for Devin, which turns it into a reviewed PR."""
    rows = skill_homes.grid()
    c = skill_homes.counts()
    cols = [g for g, _ in skill_homes.GROUPS] + [skill_homes.EVERYONE]
    mark = {"none": "", "tick": "\u2713", "first": "\u2605", "some": "\u25d0"}
    body = []
    for r in rows:
        key = esc((r["name"] + " " + r["what"]).lower())
        if r["internal"]:
            body.append('<tr data-k="%s" class="sc-internal"><td><code>/%s</code></td><td>%s</td><td colspan="%d"><em>%s</em></td></tr>'
                        % (key, esc(r["name"]), esc(r["what"]), len(cols), esc(r["internal"])))
            continue
        empty = set(r["cells"].values()) == {"none"}
        cells = "".join('<td><button type="button" class="sc-cell" data-skill="%s" data-col="%s" data-state="%s" data-was="%s"'
                        ' title="%s">%s</button></td>' % (esc(r["name"]), esc(col), r["cells"][col], r["cells"][col],
                                                          esc(r["detail"].get(col) or col), mark[r["cells"][col]]) for col in cols)
        body.append('<tr data-k="%s"%s><td><code>/%s</code>%s</td><td>%s</td>%s</tr>' % (
            key, ' class="sc-empty"' if empty else "", esc(r["name"]),
            " <strong>not assigned</strong>" if empty else "", esc(r["what"]), cells))
    head = "".join("<th>%s</th>" % esc(col) for col in cols)
    out = ("<p><strong>%d skills</strong>: %d assigned, %d not assigned to anyone, %d internal to the system.</p>"
           "<p>\u2605 a first command for that role (the top of My tools and /help, at most eight) \u00b7 \u2713 in that "
           "role's My tools \u00b7 \u25d0 some of the roles under the heading (hover to see which) \u00b7 empty: not given. "
           "Click a box to change it, then Preview change.</p>"
           '<input id="sc-filter" type="search" placeholder="Filter skills" aria-label="Filter skills" style="width:100%%">'
           '<div id="skill-config"><table><thead><tr><th>Skill</th><th>What it does</th>%s</tr></thead><tbody>%s</tbody></table></div>'
           '<p><button type="button" id="sc-preview">Preview change</button> <button type="button" data-save="sc-block" data-preview="sc-preview" hidden>Save</button></p>'
           '<textarea id="sc-block" aria-label="Text to paste into Devin" rows="8" style="width:100%%" hidden readonly></textarea>'
           "<p>Save (or, in a saved copy of this page, paste the block into Devin) shows the change to <code>.devin/rules/role-routing.yaml</code>, and after "
           "you say approved it raises a pull request. Nothing changes until that is merged.</p>"
           "<style>.sc-cell{min-width:2.2em;min-height:1.8em;border:1px solid #c7d2e0;background:#fff;border-radius:4px;cursor:pointer}"
           ".sc-changed{outline:2px solid #4a1fb8}.sc-internal td{color:#6b7280}.sc-empty td:first-child{color:#b42318}</style>"
           % (c["skills"], c["assigned"], c["not_assigned"], c["internal"], head, "".join(body))) + SKILL_CONFIG_JS
    return panel(spec.get("title", "Skill config"), out, "", spec.get("note", ""), count=c["not_assigned"],
                 attention="watch" if c["not_assigned"] else "info")


def render_feedback(spec):
    """Framework feedback (framework_feedback.py): yes and no per gate brief or artefact, least useful first."""
    import framework_feedback
    title = spec.get("title", "Framework feedback")
    rows = framework_feedback.summary(framework_feedback.load())
    if not rows:
        return panel(title, "", spec.get("empty", "No feedback yet."))
    body = "".join("<tr><td>%s</td><td>%d</td><td>%d</td><td>%s</td></tr>" % (
        esc(r["on"]), r["yes"], r["no"], "<br>".join(esc(n) for n in r["notes"][-3:])) for r in rows)
    table = ("<table><thead><tr><th>About</th><th>Useful</th><th>Not useful</th><th>Latest notes</th></tr></thead>"
             "<tbody>%s</tbody></table>" % body)
    return panel(title, table, note=spec.get("note", ""), count=sum(r["no"] for r in rows),
                 attention="watch" if any(r["no"] for r in rows) else "info")


def _link(url, text):
    url = str(url or "")
    return '<a href="%s" target="_blank" rel="noopener">%s</a>' % (esc(url), esc(text)) if url.startswith("http") else esc(text)


def render_workbench_noticed(spec):
    """Problems Argus noticed about itself (framework_feedback.noticed_summary), with the suggested fix."""
    import framework_feedback
    title = spec.get("title", "Argus noticed")
    rows = framework_feedback.noticed_summary(framework_feedback.load_batches())
    if not rows:
        return panel(title, "", spec.get("empty", "Nothing noticed yet."), spec.get("note", ""))
    body = "".join("<tr><td><strong>%s</strong><br><span class=\"muted\">%s</span></td><td>%d</td><td>%d</td>"
                   "<td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                       esc(r["title"]), esc(r["detail"][:200]), r["count"], r["people"], esc(", ".join(r["roles"])),
                       esc(r["first"][:10]), esc(r["last"][:10]), esc(r["fix"])) for r in rows)
    table = ("<table><thead><tr><th>Problem and what was seen</th><th>Times</th><th>People</th><th>Roles</th>"
             "<th>First seen</th><th>Last seen</th><th>How to fix it</th></tr></thead><tbody>%s</tbody></table>" % body)
    return panel(title, table, note=spec.get("note", ""), count=len(rows), attention="watch")


def _fb_context(ctx):
    """The session details a feedback line was sent with, as the lead reads them."""
    ctx = ctx or {}
    parts = []
    where = ", ".join(x for x in ("page " + ctx["page"] if ctx.get("page") else "",
                                  "ticket " + ctx["ticket"] if ctx.get("ticket") else "") if x)
    if where:
        parts.append("<p>On %s.</p>" % esc(where))
    runs = ctx.get("runs") or []
    if runs:
        parts.append("<ul>%s</ul>" % "".join(
            "<li>%s%s %s, stage %s, %s%s%s%s</li>" % (
                "<strong>this one:</strong> " if r.get("this_one") else "",
                esc(r.get("what") or r.get("kind") or "run"), esc(r.get("summary", "")), esc(r.get("stage") or "-"),
                esc(r.get("status") or "-"), " " + _link(r.get("session"), "session") if r.get("session") else "",
                "<br>Error: %s" % esc(r["error"]) if r.get("error") else "",
                "<br>Devin last said: %s" % esc(r["last_devin"]) if r.get("last_devin") else "") for r in runs))
    failing = ["%s: %s" % (k, v.get("error") or v.get("state")) for k, v in (ctx.get("status_light") or {}).items()
               if v.get("state") == "failing"]
    if failing:
        parts.append("<p>Status light failing: %s</p>" % esc("; ".join(failing)))
    if ctx.get("noticed"):
        parts.append("<p>Argus noticed in the last day: %s</p>" % esc("; ".join(
            "%s (x%s)" % (n.get("title"), n.get("count")) for n in ctx["noticed"][:5])))
    if ctx.get("screen_errors"):
        parts.append("<p>Page errors: %s</p>" % esc("; ".join(ctx["screen_errors"])))
    wb = ctx.get("workbench") or {}
    if wb:
        parts.append("<p class=\"muted\">Argus %s, commit %s on %s, %s</p>" % (
            esc(wb.get("version") or "-"), esc(wb.get("commit") or "-"), esc(wb.get("branch") or "-"),
            esc(wb.get("transport") or "")))
    return "<details><summary>Session details</summary>%s</details>" % "".join(parts) if parts else ""


def render_team_feedback(spec):
    """What people sent from Argus's Feedback form, newest first, with the session details it came with."""
    import framework_feedback
    title = spec.get("title", "Feedback from Argus")
    rows = framework_feedback.form_feedback(framework_feedback.load_batches())
    if not rows:
        return panel(title, "", spec.get("empty", "No feedback from Argus yet."), spec.get("note", ""))
    kinds = {"problem": "Problem", "idea": "Idea", "worked": "What worked"}
    body = "".join("<tr><td>%s</td><td>%s<br><span class=\"muted\">%s</span></td><td>%s</td><td>%s</td>"
                   "<td>%s%s</td></tr>" % (
                       esc((r.get("at") or "")[:10]), esc(r.get("by") or "-"), esc(r.get("role") or ""),
                       esc(kinds.get(r.get("kind"), r.get("kind") or "")), esc(r.get("about") or ""),
                       esc(r.get("text") or ""), _fb_context(r.get("context"))) for r in rows)
    table = ("<table><thead><tr><th>Date</th><th>Who</th><th>Kind</th><th>About</th><th>What they said</th></tr>"
             "</thead><tbody>%s</tbody></table>" % body)
    problems = sum(1 for r in rows if r.get("kind") == "problem")
    return panel(title, table, note=spec.get("note", ""), count=problems, attention="watch" if problems else "info")


TEAM_INSIGHTS_EMPTY = ("No Team Insights month yet. The monthly /team-insights run writes the first one to "
                       "SHARED/team-insights/.")
PRIVATE_MISSING = ("Usage and ACUs per person aren't on this PC. The monthly /team-insights run attaches them to its "
                   "session; download the file and run: python3 sdlc/framework/tools/team_insights.py import <file>")
PLANS_EMPTY = ("No learning plans yet. The monthly /team-insights run writes one file per person to "
               "SHARED/team-insights/people/<YYYY>/<MM>/<devin user id>.md.")


def _insights():
    """(shared month, private month or None, learning plans by month and user id, names by user id, $ per ACU),
    read once per page."""
    import team_insights
    if not hasattr(_insights, "cache"):
        shared, private = team_insights.load_month()
        plans = team_insights.all_plans()
        names = team_insights.display_names(sorted({u for month in plans.values() for u in month}))
        _insights.cache = (shared, private, plans, names, team_insights.usd_per_acu())
    return _insights.cache


def _ti_plan(name, path, plan):
    """One person's learning plan file, as the tech lead reads it, with the name in place of the user id."""
    marks = {"open": "☐", "taught": "☑", "better": "☑"}
    items = "".join("<li>%s %s <em>(%s, since %s%s)</em></li>" % (
        marks.get(r.get("status"), "☐"), esc(r.get("gap")), esc(r.get("status", "open")), esc(r.get("since", "")),
        ", seen again %s" % esc(r["seen_again"]) if r.get("seen_again") else "") for r in plan.get("learning") or [])

    def bullets(key):
        return "<ul>%s</ul>" % "".join("<li>%s</li>" % esc(x) for x in plan[key]) if plan.get(key) else "<p>None.</p>"
    prompt = ("<h4>A better prompt</h4><p>Their prompt: %s</p><p>A better one: <strong>%s</strong></p>"
              % (esc(plan.get("prompt_before", "")), esc(plan.get("prompt_after", "")))
              if plan.get("prompt_before") or plan.get("prompt_after") else "")
    opened = sum(1 for r in plan.get("learning") or [] if r.get("status", "open") == "open")
    return ('<details class="ti-plan" data-person="%s"><summary><strong>%s</strong> · %d open · <code>%s</code></summary>'
            '<h4>Learning list</h4>%s<h4>Tips to give</h4>%s<h4>Questions for your one-on-one</h4>%s%s</details>'
            % (esc(name), esc(name), opened, esc(path), "<ul class=\"ti-list\">%s</ul>" % items if items else "<p>None.</p>",
               bullets("tips"), bullets("questions"), prompt))


def _ti_table(head, rows):
    """A dollar column ("$ ...") keeps its heading hidden until Show $ is ticked, like its cells."""
    return table("".join("<th>%s</th>" % ('<span class="ti-usd">%s</span>' % esc(h) if h.startswith("$") else esc(h))
                         for h in head), "".join(rows))


def _ti_row(cells, person=None):
    attr = ' data-person="%s"' % esc(person) if person else ""
    return "<tr%s>%s</tr>" % (attr, "".join("<td>%s</td>" % c for c in cells))


def _ti_counts(counts):
    return ", ".join("%s %s" % (esc(str(k).replace("_", " ")), esc(v)) for k, v in (counts or {}).items())


def _ti_dash(value):
    return "–" if value in (None, "") else esc(value)


def render_insights(spec):
    """One Team Insights tab (team_insights.py). Team numbers, nameless findings and the learning plans (by Devin user
    id, shown with the name) from the repo; usage and ACUs per person only from the private file on this PC. Every
    per-person row can be hidden with the person picker."""
    shared, private, plans, names, usd = _insights()
    view, title = spec.get("view", "overview"), spec.get("title", "Team Insights")
    note = spec.get("note", "")
    if not shared:
        return panel(title, "", TEAM_INSIGHTS_EMPTY, note)
    t = shared.get("team") or {}
    month = esc(shared.get("month", ""))
    people = (private or {}).get("people") or []
    detail = {names[u]: p for u, p in (plans.get(shared.get("month")) or {}).items()}
    missing = '<p class="a-section__note">%s</p>' % esc(PRIVATE_MISSING) if not private else ""
    out, count, attention = "", None, "info"
    if view == "overview":
        kpis = (("Sessions", t.get("sessions")), ("People", t.get("people")), ("On the roster", t.get("on_roster")),
                ("ACUs", t.get("acus")), ("PRs", t.get("prs")), ("Merged PRs", t.get("merged_prs")),
                ("ACUs per merged PR", t.get("acus_per_merged_pr")), ("Sessions analysed", t.get("analysed")))
        out = ("<p><strong>%s</strong> · %s</p>" % (month, esc(shared.get("source", ""))) +
               _ti_table(["Measure", "Value"], [_ti_row([esc(k), _ti_dash(v)]) for k, v in kpis]) +
               "<p><strong>Where people start sessions:</strong> %s</p>" % _ti_counts(t.get("by_origin")) +
               "<p><strong>Kinds of work:</strong> %s</p>" % _ti_counts(t.get("by_category")))
    elif view == "usage":
        if people:
            picks = "".join('<label class="ti-pick"><input type="checkbox" class="ti-person" value="%s" checked> %s%s</label>'
                            % (esc(p["person"]), esc(p["person"]), "" if p.get("on_roster") else " <em>(org)</em>")
                            for p in sorted(people, key=lambda p: (not p.get("on_roster"), p["person"])))
            out = ('<details class="ti-picker" open><summary>People shown (%d) — your choice is kept on this PC and '
                   'applies to every Team Insights tab</summary><p><button type="button" class="a-btn a-btn--outline" '
                   'data-ti-all="1">All</button> <button type="button" class="a-btn a-btn--outline" data-ti-all="0">'
                   'None</button></p><div class="ti-picks">%s</div></details>' % (len(people), picks) +
                   _ti_table(["Person", "Role", "Sessions", "PRs", "Merged", "Median messages per session", "Where",
                              "Kinds of work"],
                             [_ti_row([esc(p["person"]), esc(p.get("role") or ("roster" if p.get("on_roster") else "org")),
                                       esc(p["sessions"]), esc(p["prs"]), esc(p["merged"]),
                                       _ti_dash(p.get("median_messages")), _ti_counts(p.get("origins")),
                                       _ti_counts(p.get("categories"))], p["person"]) for p in people]))
        out = missing + out + _ti_table(["Role", "People", "Sessions", "ACUs"], [
            _ti_row([esc(r), esc(v["people"]), esc(v["sessions"]), esc(v["acus"])]) for r, v in (t.get("by_role") or {}).items()])
    elif view == "cost":
        box = '<label class="ti-usd-box"><input type="checkbox" id="ti-usd"> Show $</label>' if usd else ""
        rate = "<p>$ uses %s per ACU from scrum-master-metrics.yaml.</p>" % esc(usd) if usd else ""

        def cols(cells):
            return cells if usd else [c for i, c in enumerate(cells) if i not in money_at]

        def money(acus):
            return '<span class="ti-usd">$%s</span>' % esc(round(float(acus) * usd, 2)) if usd and acus is not None else ""

        def money_table(head, rows):
            money_at.clear()
            money_at.update(i for i, h in enumerate(head) if h.startswith("$"))
            return _ti_table(cols(head), [_ti_row(cols(r), person) for r, person in rows])
        money_at = set()
        out = box + rate + money_table(["Kind of work", "ACUs", "$"], [
            ([esc(k.replace("_", " ")), esc(v), money(v)], None) for k, v in (t.get("acus_by_category") or {}).items()])
        out += money_table(["Role", "ACUs", "$"], [([esc(r), esc(v["acus"]), money(v["acus"])], None)
                                                  for r, v in (t.get("by_role") or {}).items()])
        if people:
            out += money_table(["Person", "ACUs", "$", "ACUs per merged PR", "$ per merged PR"], [
                ([esc(p["person"]), esc(p["acus"]), money(p["acus"]), _ti_dash(p.get("acus_per_merged_pr")),
                  money(p.get("acus_per_merged_pr"))], p["person"]) for p in people])
        out = missing + out
    elif view == "prompts":
        pats = shared.get("prompt_patterns") or []
        out = _ti_table(["Pattern", "Sessions", "People", "Instead of", "Try"], [
            _ti_row([esc(p.get("pattern")), _ti_dash(p.get("sessions")), _ti_dash(p.get("people")),
                     esc(p.get("before", "")), "<strong>%s</strong>" % esc(p.get("better", ""))]) for p in pats]) if pats else ""
        ex = shared.get("prompt_examples") or []
        if ex:
            out += "<h3>Prompts from this month, rewritten</h3>" + _ti_table(["Asked", "What made it harder", "Better"], [
                _ti_row([esc(e.get("asked", "")), esc(e.get("weak", "")), "<strong>%s</strong>" % esc(e.get("better", ""))])
                for e in ex])
        mine = [(n, d) for n, d in sorted(detail.items()) if d.get("prompt_before") or d.get("prompt_after")]
        if mine:
            out += "<h3>Per person</h3>" + _ti_table(["Person", "Their prompt", "A better one"], [
                _ti_row([esc(n), esc(d.get("prompt_before", "")), "<strong>%s</strong>" % esc(d.get("prompt_after", ""))], n)
                for n, d in mine])
        count, attention = len(pats), "watch" if pats else "info"
    elif view == "gaps":
        gaps, rep = shared.get("gaps") or [], shared.get("repetitive") or []
        if gaps:
            out += "<h3>Skill gaps</h3>" + _ti_table(["Gap", "Sessions", "People", "Lesson", "Command to try"], [
                _ti_row([esc(g.get("gap")), _ti_dash(g.get("sessions")), _ti_dash(g.get("people")),
                         esc(g.get("lesson", "")), "<code>%s</code>" % esc(g["command"]) if g.get("command") else ""])
                for g in gaps])
        if rep:
            out += "<h3>Repeated work a command or automation could do</h3>" + _ti_table(
                ["Task", "Sessions", "People", "Suggestion"],
                [_ti_row([esc(r.get("task")), _ti_dash(r.get("sessions")), _ti_dash(r.get("people")),
                          esc(r.get("suggestion", ""))]) for r in rep])
        count, attention = len(gaps) + len(rep), "watch" if gaps or rep else "info"
    elif view == "wins":
        wins = shared.get("wins") or []
        out = "<ul>%s</ul>" % "".join("<li><strong>%s</strong>: %s</li>" % (esc(w.get("person")), esc(w.get("what")))
                                      for w in wins) if wins else ""
    elif view == "learning":
        import team_insights
        years = {}
        for m in sorted(plans, reverse=True):
            years.setdefault(m[:4], []).append(m)
        latest = max(plans) if plans else ""
        for y, months in years.items():
            body = ""
            for m in months:
                files = "".join(_ti_plan(names[u], os.path.relpath(team_insights.plan_path(m, u), team_insights.TEAM_DIR), p)
                                for u, p in sorted(plans[m].items(), key=lambda kv: names[kv[0]].casefold()))
                body += ('<details class="ti-month"%s><summary>%s · %d people</summary>%s</details>'
                         % (" open" if m == latest else "", esc(datetime.date(int(y), int(m[5:]), 1).strftime("%B %Y")),
                            len(plans[m]), files))
            out += '<details class="ti-year"%s><summary>%s</summary>%s</details>' % (
                " open" if latest.startswith(y) else "", esc(y), body)
        if out:
            out = ("<p>One file per person and month in <code>SHARED/team-insights/people/&lt;YYYY&gt;/&lt;MM&gt;/</code>, "
                   "named by Devin user id; names come from people.yaml. Open items are taught one at a time at the "
                   "start of the person's sessions.</p>" + out)
        count = sum(1 for p in (plans.get(latest) or {}).values() for r in p.get("learning") or []
                    if r.get("status", "open") == "open")
        attention = "watch" if count else "info"
    elif view == "checkins":
        import team_insights
        data = team_insights.load_yaml(team_insights.CHECKINS_PATH, {})
        rows = [c for c in data.get("checkins") or [] if str(c.get("date", "")).startswith(shared.get("month", ""))]
        out = ("<p>%s</p>" % esc(team_insights.CHECKIN_QUESTION) +
               _ti_table(["Date", "Who", "What helped", "What got in the way"],
                         [_ti_row([esc(c.get("date")), esc(c.get("by")), esc(c.get("helped", "")),
                                   esc(c.get("blocked", ""))]) for c in rows])) if rows else ""
    empty = PLANS_EMPTY if view == "learning" else "Nothing for %s." % shared.get("month", "this month")
    return panel(title, out, spec.get("empty", empty), note, count=count, attention=attention)


def render_framework_changes(spec):
    """Recommended framework changes (team_insights.py), newest first; new ones wait on the tech lead."""
    import team_insights
    title = spec.get("title", "Recommended framework changes")
    items = (team_insights.load_yaml(team_insights.RECS_PATH, {}).get("recommendations") or [])[::-1]
    if not items:
        return panel(title, "", spec.get("empty", "No recommended changes yet."), spec.get("note", ""))
    rows = [_ti_row([esc(r.get("id")), "<strong>%s</strong>" % esc(r.get("what")), esc(r.get("why", "")),
                     _ti_dash(r.get("sessions")), _ti_dash(r.get("people")), esc(r.get("gain", "")),
                     esc(r.get("touches", "")), '<span class="a-chip" data-attention="%s">%s</span>' % (
                         "watch" if r.get("status") == "new" else "info", esc(r.get("status"))), esc(r.get("month", ""))])
            for r in items]
    fresh = sum(1 for r in items if r.get("status") == "new")
    body = (_ti_table(["ID", "Change", "Why", "Sessions", "People", "Expected gain", "Touches", "Status", "Month"], rows) +
            "<p>To decide one: <code>python3 sdlc/framework/tools/team_insights.py recommend decide R-001 "
            "accepted --by \"&lt;your name&gt;\" --write</code> (or rejected, or done once built).</p>")
    return panel(title, body, note=spec.get("note", ""), count=fresh, attention="watch" if fresh else "info")


# Team Insights: the person picker hides everyone left unticked on every Team Insights tab (kept on this PC), and
# the Show $ box, there only when a rate is set, shows the dollar cells.
INSIGHTS_JS = r"""(function () {
  var KEY = "sdlc-ti-hidden", boxes = [].slice.call(document.querySelectorAll(".ti-person"));
  var hidden = [];
  try { hidden = JSON.parse(localStorage.getItem(KEY) || "[]"); } catch (e) { hidden = []; }
  function apply() {
    document.querySelectorAll("tr[data-person], details.ti-plan[data-person]").forEach(function (r) {
      r.hidden = hidden.indexOf(r.getAttribute("data-person")) !== -1;
    });
  }
  function save() {
    hidden = boxes.filter(function (b) { return !b.checked; }).map(function (b) { return b.value; });
    try { localStorage.setItem(KEY, JSON.stringify(hidden)); } catch (e) {}
    apply();
  }
  boxes.forEach(function (b) { b.checked = hidden.indexOf(b.value) === -1; b.addEventListener("change", save); });
  document.querySelectorAll("[data-ti-all]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      boxes.forEach(function (b) { b.checked = btn.getAttribute("data-ti-all") === "1"; });
      save();
    });
  });
  var usd = document.getElementById("ti-usd");
  if (usd) usd.addEventListener("change", function () { document.body.classList.toggle("ti-show-usd", usd.checked); });
  apply();
}());
"""
INSIGHTS_CSS = (".ti-usd{display:none}body.ti-show-usd .ti-usd{display:inline}.ti-picks{display:flex;flex-wrap:wrap;"
                "gap:4px 16px}.ti-pick{white-space:nowrap}.ti-picker summary{cursor:pointer;font-weight:600}"
                ".ti-usd-box{display:inline-flex;gap:6px;align-items:center;font-weight:600}"
                ".ti-year>summary,.ti-month>summary,.ti-plan>summary{cursor:pointer;"
                "padding:4px 0}.ti-year>summary{font-weight:700}.ti-month{margin-left:16px}.ti-plan{margin-left:16px;"
                "border-left:3px solid rgb(var(--border-primary));padding-left:12px}.ti-list{list-style:none;padding-left:0}")


def days_between(later, earlier):
    """Whole days from one ISO stamp to another, and zero when either cannot be read."""
    ages = [day_age(later), day_age(earlier)]
    if any(not isinstance(age, int) for age in ages):
        return 0
    return max(0, ages[1] - ages[0])


def doc_drift_rows(spec):
    """Generated documents whose subject has been committed to since the document was last written.

    Git dates only: a document older than the code it describes is a document to re-check. It says
    nothing about whether the content actually diverged, which is what /source-staleness-check reads.
    """
    rows = []
    for area in spec.get("areas") or []:
        code, docs = area.get("code"), area.get("docs")
        if not code or not docs:
            continue
        code_stamp = git_out("log", "-1", "--format=%cI", "--", code)
        if not code_stamp:
            continue
        for path in sorted(glob.glob(os.path.join(ROOT, docs, spec.get("pattern") or "*.md"))):
            rel = os.path.relpath(path, ROOT)
            doc_stamp = git_out("log", "-1", "--format=%cI", "--", rel)
            if not doc_stamp or doc_stamp >= code_stamp:
                continue
            commits = git_out("rev-list", "--count", "--since=%s" % doc_stamp, "HEAD", "--", code)
            rows.append(
                {
                    "document": rel,
                    "area": area.get("name") or code,
                    "doc_date": doc_stamp[:10],
                    "code_date": code_stamp[:10],
                    "behind": days_between(code_stamp, doc_stamp),
                    "commits": commits or "?",
                }
            )
    rows.sort(key=lambda r: (-r["behind"], r["document"]))
    return rows


def render_doc_drift(spec, rows):
    title = spec.get("title", "Knowledge base behind the code")
    if not rows:
        return panel(title, "", spec.get("empty", "Every generated document is newer than the code "
                                                  "it describes."))
    limit = int(spec.get("limit") or 12)
    body = []
    for row in rows[:limit]:
        body.append(
            "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
            % (esc(os.path.basename(row["document"])), esc(row["area"]), esc(row["doc_date"]),
               esc(row["code_date"]), esc(row["commits"]))
        )
    table = (
        "<table><thead><tr><th>Document</th><th>Describes</th><th>Written</th><th>Code changed</th>"
        "<th>Commits since</th></tr></thead><tbody>%s</tbody></table>" % "".join(body)
    )
    note = spec.get(
        "note",
        "Commit dates only — the code moved after the document was written, which makes the "
        "document worth re-checking rather than proven wrong. /source-staleness-check compares the "
        "content, /kb-refresh regenerates it.",
    )
    if len(rows) > limit:
        note = "%d documents behind, %d shown. %s" % (len(rows), limit, note)
    return panel(title, table, note=note, count=len(rows), attention="watch")


def roadmap_page(spec):
    """The page /roadmap last wrote, with the date it says it was generated, or None when absent."""
    rel = spec.get("path") or ROADMAP_PAGE
    try:
        with open(os.path.join(ROOT, rel), encoding="utf-8") as handle:
            text = handle.read()
    except OSError:
        return None
    found = ROADMAP_GENERATED.search(text)
    return {"path": rel, "html": text, "generated": found.group(1) if found else ""}


def render_defect_matrix(spec, data, note):
    """Open SIT/UAT defects grouped by specialty, then team (defects_by_specialty.py does the work)."""
    rules = defect_lib.load_rules(
        os.path.join(defect_lib.ROOT, spec["rules"]) if spec.get("rules") else defect_lib.RULES_PATH)
    rows = defect_lib.defect_rows(data, rules)
    body = defect_lib.render_fragment(rows, rules, spec.get("columns"), dom_id="defect-matrix-%s" % spec["id"])
    return panel(spec.get("title", spec["id"]), body, spec.get("empty", "No open SIT or UAT defects."),
                 note, count=len(rows), attention=defect_lib.attention(rows))


def sprint_sheet_view(today=None):
    """This sprint's planning sheet from the repo, read only; edits happen in Argus or through /vacation."""
    import sprint_sheet
    try:
        token = sprint_sheet.current(today)
        if not token:
            return ""
        sheet = sprint_sheet.load(token)
        return ('<h3>Sprint %s planning sheet</h3><p class="a-section__note">Read only. The Scrum Master edits it in the '
                'Argus (Time off, Sprint planning sheet); anyone can say <code>/vacation</code>.</p>%s'
                % (esc(token), sprint_sheet.render_fragment(sheet)))
    except Exception as exc:  # noqa: BLE001 - the tab still shows the planner
        return '<p class="a-section__note">Sprint planning sheet not shown (%s).</p>' % esc(str(exc))


def unplanned_view(log, today=None):
    """This sprint's sick days and ad hoc leave under the vacation planner, or a note saying why not."""
    import unplanned_leave
    import sprint_sheet
    try:
        return unplanned_leave.render_sprint_view(
            unplanned_leave.sprint_view(unplanned_leave.load(), log, sprint_sheet.current(today) or ""))
    except (unplanned_leave.TrackerError, sprint_sheet.SheetError) as exc:
        return '<p class="a-section__note">Unplanned leave not shown (%s).</p>' % esc(str(exc))


def leave_calendar_view(rows, log, today=None):
    """This sprint's leave calendar, coloured by weekend, holiday, planned time off, sick day and ad hoc leave."""
    import leave_calendar
    import sprint_sheet
    try:
        sprint = sprint_sheet.current(today)
        if not sprint:
            return ""
        return leave_calendar.render(leave_calendar.grid(sprint_sheet.load(sprint), rows, log), today)
    except sprint_sheet.SheetError as exc:
        return '<p class="a-section__note">Leave calendar not shown (%s).</p>' % esc(str(exc))


def render_vacation(spec, rows, note, viewer="", today=None, unplanned=None):
    """Everyone's time off from today on, with who covers their stories, questions and approvals; this sprint's
    unplanned leave when `unplanned` (the Unplanned leave log) is given."""
    today = today or datetime.date.today()
    calendar = leave_calendar_view(rows, unplanned or [], today)
    rows = sorted((r for r in rows if r.get("from") and r.get("to") and r["to"] >= today.isoformat()),
                  key=lambda r: (r["from"], r.get("name", "")))
    def cover(r, key):
        return "—" if r.get("kind") in sprint_leave.UNPLANNED_KINDS else esc(r.get(key) or "not named")
    body = "".join("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
        esc(r.get("name", "")) + (" <em>(you)</em>" if viewer and r.get("jira_user", "").upper() == viewer.upper() else ""),
        esc(r.get("kind") or "Time off"), esc(r["from"]), esc(r["to"]),
        "<strong>away now</strong>" if r["from"] <= today.isoformat() else "",
        cover(r, "stories_to"), cover(r, "questions_to"), cover(r, "approvals_to"),
        "yes" if r.get("hold") else "") for r in rows)
    out = ("<table><thead><tr><th>Team member</th><th>Type</th><th>From</th><th>To</th><th></th><th>Stories go to</th>"
           "<th>Questions go to</th><th>Approvals go to</th><th>Stories on hold</th></tr></thead><tbody>%s</tbody></table>"
           '<p class="a-section__note">To add or change your time off, say <code>/vacation</code> in Devin. Anyone can '
           'report a sick day: <code>@Devin &lt;name&gt; is sick today</code>.</p>' % body)
    out = calendar + (out if rows else '<p>%s</p>' % esc(spec.get("empty", "No time off planned.")))
    if unplanned is not None:
        out += unplanned_view(unplanned, today)
    out += sprint_sheet_view(today)
    now = sum(1 for r in rows if r["from"] <= today.isoformat())
    return panel(spec.get("title", spec["id"]), out, spec.get("empty", "No time off planned."),
                 note, count=len(rows), attention="watch" if now else "info")


def render_unplanned(spec, log, note, today=None, tracker=None):
    """Resource 2's leave tracker: the Unplanned leaves counter (team member by sprint) with this sprint's and the
    year's totals, the latest reported days, and a read-only copy of every workbook tab."""
    import unplanned_leave
    import sprint_sheet
    today = today or datetime.date.today()
    title, empty = spec.get("title", spec["id"]), spec.get("empty", "No unplanned leave counted yet.")
    try:
        tracker = tracker or unplanned_leave.load()
        c = unplanned_leave.counts(tracker, log)
    except (unplanned_leave.TrackerError, sprint_sheet.SheetError) as exc:
        return panel(title, "", empty, "Leave tracker not read (%s)" % exc)
    try:
        current = sprint_sheet.current(today) or ""
    except sprint_sheet.SheetError:
        current = ""
    now = c["totals"].get(current, 0)
    head, rows = unplanned_leave.render_counter(c, current)
    days = unplanned_leave.days_text
    out = ('<div class="ul-sum"><span>Sprint %s <b>%s</b></span><span>This year <b>%s</b></span>'
           '<span>Reported to Devin since %s <b>%s</b></span></div>' % (
               esc(current or "now"), esc(days(now)), esc(days(c["total"])),
               esc(tracker.get("imported_on", "")), esc(days(c["reported"]))))
    out += table(head, rows)
    latest = sorted(log, key=lambda e: e.get("date", ""), reverse=True)[:10]
    if latest:
        out += ("<h4>Latest reported</h4>" + table(
            "<th>Date</th><th>Team member</th><th>Type</th><th>Sprint</th><th>Reported by</th>",
            "".join("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                esc(e.get("date", "")), esc(e.get("name", "")), esc(e.get("kind", "")), esc(e.get("sprint", "")),
                esc(e.get("by", ""))) for e in latest)))
    out += ('<details class="ul-copy"><summary>Leave tracker workbook (read-only copy of %s, imported %s)</summary>%s'
            '</details>' % (esc(tracker.get("source", "")), esc(tracker.get("imported_on", "")),
                            unplanned_leave.render_tabs(tracker, "ul")))
    out += ('<p class="a-section__note">Anyone can report a sick day: <code>@Devin &lt;name&gt; is sick today</code>; '
            'ad hoc leave: <code>@Devin &lt;name&gt; is on ad hoc leave today</code>. Each one adds a day here.</p>'
            '<style>.ul-sum{display:flex;gap:1.5rem;flex-wrap:wrap;margin:.25rem 0 .75rem}.ul-sum b{font-size:1.25rem;'
            'margin-left:.35rem}.ul-now{background:var(--a-accent-soft,#e8f0fe)}.ul-copy{margin-top:1rem}</style>')
    return panel(title, out, empty, note, count=now, attention="watch" if now else "info")


def render_risks(spec):
    """Open risks and dependencies per epic from SHARED/risk-register.yaml: late dependencies, then highest risk."""
    import risk_register
    rows = risk_register.rows(risk_register.load())
    body = "".join("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
        esc(r["id"]), esc(r["epic"]), esc(r["text"]), esc(r["owner"]),
        esc("%s likelihood, %s impact" % (r["likelihood"], r["impact"])) if r["kind"] == "risk"
        else esc("needs %s by %s" % (r["team"], r["needed_by"])) + (" <strong>late</strong>" if r["late"] else ""),
        esc(r.get("mitigation", ""))) for r in rows)
    table = ("<table><thead><tr><th>Id</th><th>Epic</th><th>Risk or dependency</th><th>Owner</th>"
             "<th>Rating or needed by</th><th>Mitigation</th></tr></thead><tbody>%s</tbody></table>" % body)
    hot = any(r["late"] or r["score"] >= 6 for r in rows)
    return panel(spec.get("title", spec["id"]), table if rows else "", spec.get("empty", "No open risks."),
                 "", count=len(rows), attention="watch" if hot else "info")


def render_defect_rca(spec, rows, note):
    """Root cause and escape per SIT/UAT defect; closed defects with no root cause yet come first."""
    rows = sorted(rows, key=lambda r: (not r["ask"], r["stage"], r["key"]))
    body = "".join("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
        esc(r["key"]), esc(r["story"] or "not linked"), esc(r["stage"]), esc(r["should_catch"]),
        esc(r["cause"] + (": " + r["cause_note"] if r["cause_note"] else "")) or ("<em>ask the fixer</em>" if r["ask"] else "open"),
        esc(", ".join(r["missed"])) or "none") for r in rows)
    table = ("<table><thead><tr><th>Defect</th><th>Story</th><th>Found in</th><th>Should have been caught by</th>"
             "<th>Root cause</th><th>Files the link graph missed</th></tr></thead><tbody>%s</tbody></table>" % body)
    asks = sum(1 for r in rows if r["ask"])
    return panel(spec.get("title", spec["id"]), table if rows else "", spec.get("empty", "No SIT or UAT defects."),
                 note, count=asks, attention="watch" if asks else "info")


def render_hygiene(spec, data, note):
    """Tickets that do not yet follow the Jira rule book, grouped by check (jira_hygiene.py does the work)."""
    rows = hygiene_lib.finding_rows(data)
    body = hygiene_lib.render_fragment(rows, data, dom_id="jira-hygiene-%s" % spec["id"])
    return panel(spec.get("title", spec["id"]), body, spec.get("empty", "Every ticket read follows the rule book."),
                 note, count=len({r["key"] for r in rows}), attention=hygiene_lib.attention(rows))


def render_scrum(spec, data, note):
    """One Scrum Master tab (stand-up check, cycle time, commitment, DRE, AI use); scrum_metrics.py does the work."""
    body, count, attention = scrum_lib.render(spec.get("view", ""), data or {})
    return panel(spec.get("title", spec["id"]), body, spec.get("empty", "Nothing to show."), note,
                 count=count, attention=attention)


DEFECT_TYPES = ("Defect", "Bug")


def linked_defects(source, keys):
    """{story key: [defect keys linked to it]}: Jira issue links, or `confidence_defects` in a cache file."""
    client = getattr(source, "client", None)
    if client is None:
        cached = (getattr(source, "data", None) or {}).get("confidence_defects") or {}
        return {k: list(cached.get(k) or []) for k in keys}
    keys = list(keys)
    out = {key: [] for key in keys}
    for n in range(0, len(keys), 80):
        batch = keys[n:n + 80]
        page = client.live_get("/api/2/search", jql="key in (%s)" % ", ".join(batch), maxResults=len(batch),
                               fields="issuelinks")
        for got in page.get("issues") or []:
            out[got["key"]] = sorted(
                other["key"] for link in (got.get("fields") or {}).get("issuelinks") or []
                for other in [link.get("outwardIssue") or link.get("inwardIssue") or {}]
                if ((other.get("fields") or {}).get("issuetype") or {}).get("name") in DEFECT_TYPES)
    return out


def change_confidence(source=None):
    """verifier.py metrics over the session folders; a broken file or a Jira refusal is a note, not a crash."""
    defects_for = (lambda keys: linked_defects(source, keys)) if source is not None else None
    try:
        return verifier_lib.metrics(defects_for=defects_for), ""
    except urllib.error.HTTPError as exc:
        return verifier_lib.metrics(), "Jira rejected the linked-defect read (HTTP %d); missed impacts not read" % exc.code
    except Exception as exc:  # noqa: BLE001 - shown on the tab
        return {}, "Could not read the session folders: %s" % exc


def render_confidence(spec, data, note):
    """Change confidence: claims verified vs unverified per story, and the verifier's verdicts."""
    claims, verdicts = data.get("claims") or [], data.get("verifier") or []
    if not claims and not verdicts:
        return panel(spec.get("title", spec["id"]), "", spec.get("empty", "Nothing to show."), note,
                     count=0, attention="clear")
    total = data.get("verified", 0) + data.get("unverified", 0)
    share = "%d%%" % round(100.0 * data.get("verified", 0) / total) if total else "no claims"
    rework = sum(v["rework"] for v in verdicts)
    impacts = data.get("impacts") or []
    missed = sum(i["missed"] for i in impacts)
    if data.get("defects_read"):
        missed_text = "%d files in the fixes of %d linked defects that the walk did not predict" % (
            missed, sum(len(i["defects"]) for i in impacts))
    else:
        missed_text = "not read (no Jira story keys, or Jira not reached)"
    parts = ['<p><strong>Claims verified:</strong> %d of %d (%s). <strong>Verifier:</strong> %d passed, %d failed. '
             '<strong>Rework after review:</strong> %d failed rounds before a pass. <strong>Impacts missed:</strong> '
             '%s.</p>'
             % (data.get("verified", 0), total, share, sum(1 for v in verdicts if v["verdict"] == "pass"),
                sum(1 for v in verdicts if v["verdict"] == "fail"), rework, esc(missed_text))]
    if impacts:
        rows = "".join("<tr><td>%s</td><td>%d</td><td>%s</td><td>%d</td><td>%s</td></tr>"
                       % (esc(i["story"]), i["predicted"], esc(d["defect"]), d["files"],
                          esc(", ".join(d["missed"]) or "none")) for i in impacts for d in i["defects"])
        parts.append("<h3>Impacts predicted against missed</h3><table><thead><tr><th>Story</th>"
                     "<th>Files predicted</th><th>Linked defect</th><th>Files in its fix</th>"
                     "<th>Missed (not predicted)</th></tr></thead><tbody>%s</tbody></table>" % rows)
    if claims:
        rows = "".join("<tr><td>%s</td><td>%d</td><td>%d</td><td>%s</td><td><code>%s</code></td></tr>"
                       % (esc(c["story"]), c["verified"], c["unverified"],
                          "blocks SDLC_04" if c["blocks"] else ("warning" if c["unverified"] else "verified"),
                          esc(c["file"])) for c in claims)
        parts.append("<h3>Claims per story</h3><table><thead><tr><th>Story</th><th>Verified</th><th>Unverified</th>"
                     "<th>Result</th><th>Claims file</th></tr></thead><tbody>%s</tbody></table>" % rows)
    if verdicts:
        rows = "".join("<tr><td>%s</td><td>%s</td><td>%d</td><td>%d</td><td>%d</td></tr>"
                       % (esc(v["story"]), esc(v["verdict"]), v["rounds"], v["rework"], v["findings"])
                       for v in verdicts)
        parts.append("<h3>Independent verifier (medium and high-risk stories)</h3><table><thead><tr><th>Story</th>"
                     "<th>Verdict</th><th>Rounds</th><th>Failed rounds</th><th>Open findings</th></tr></thead>"
                     "<tbody>%s</tbody></table>" % rows)
    blocked = sum(1 for c in claims if c["blocks"]) + sum(1 for v in verdicts if v["verdict"] == "fail") + missed
    return panel(spec.get("title", spec["id"]), "\n".join(parts), spec.get("empty", "Nothing to show."), note,
                 count=data.get("unverified", 0) + sum(1 for v in verdicts if v["verdict"] == "fail") + missed,
                 attention="hot" if blocked else ("watch" if data.get("unverified") else "clear"))


def render_roadmap(spec, page):
    """The roadmap page, Year plan and sprint grid tabs included, opened in a page of its own.

    The page travels inside the dashboard as JSON, so the dashboard stays one self-contained file.
    Choosing the Roadmap tab opens it in a new browser tab; the button is there for when the
    browser blocks that pop-up.
    """
    title = spec.get("title", "Roadmap")
    refresh = ('<button class="a-btn a-btn--outline" type="button" data-roadmap-refresh hidden>'
               'Refresh from Jira (runs /roadmap in Devin Cloud)</button>')
    if not page:
        empty = html.escape(spec.get("empty", "No roadmap has been generated yet — run /roadmap."))
        return panel(title, '<p class="c-muted">%s</p><p>%s</p>' % (empty, refresh), count=0, attention="clear")
    doc = json.dumps(page["html"]).replace("</", "<\\/")
    body = (
        '<p><button class="a-btn a-btn--primary" type="button" data-roadmap-open>Open the roadmap in a new tab'
        '</button> %s</p><script type="application/json" id="roadmap-doc">%s</script>' % (refresh, doc)
    )
    note = spec.get(
        "note",
        "The page /roadmap wrote to %s%s. It opens in a new tab. Run /roadmap to rebuild it from Jira and the year plan."
        % (page["path"], ", as of %s" % page["generated"] if page["generated"] else ""),
    )
    return panel(title, body, note=note, attention=spec.get("attention", "info"))


def render_grooming_prep(spec, data, note):
    """Grooming prep read only: the same six steps Argus screen has buttons for."""
    title = spec.get("title", "Grooming prep")
    if not data:
        return panel(title, "", note or spec.get("empty", "Nothing read yet."), note)
    count = data.get("count") or 0
    return panel(title, grooming_prep.render(data, "https://jira.acme.example/browse/"), note=note,
                 count=count or None, attention=spec.get("attention", "watch") if count else "clear")


def render_backlog(spec, data, note):
    """The Backlog grid (review_pages.backlog_page), carried inside the dashboard and opened in a new tab;
    on a read-only lens, the same tickets as a plain list."""
    title = spec.get("title", "Backlog")
    items = (data or {}).get("items") or []
    if not items:
        return panel(title, '<p class="c-muted">%s</p>' % html.escape(note or spec.get("empty", "Nothing open in the backlog.")),
                     count=0, attention="clear")
    groom = sum(1 for i in items if i.get("groom"))
    if spec.get("read_only"):
        head = "".join("<th>%s</th>" % h for h in ("Key", "Type", "Title", "Epic", "Sprint", "Points", "Status", "Grooming"))
        body = "".join("<tr><td>%s</td>%s</tr>" % (jira_link(i.get("k")), "".join("<td>%s</td>" % esc(v) for v in (
            i.get("t"), i.get("s"), i.get("ep"), i.get("sprint"), i.get("pts"), i.get("st"),
            "needs grooming" if i.get("groom") else ""))) for i in items)
        return panel(title, '<p class="c-muted">%d open tickets, %d need grooming.</p>%s' % (len(items), groom, table(head, body)),
                     note=note, count=groom or None, attention=spec.get("attention", "watch") if groom else "clear")
    page = {"html": review_pages.backlog_page(data), "path": "this dashboard", "generated": ""}
    spec = dict(spec, summary="%d open tickets, %d need grooming. Groom, edit, point or run planning poker, move, clone, "
                "split, hold, add notes or create new epics, stories and sub-tasks from one screen." % (len(items), groom),
                note=spec.get("note", "Opened from Argus, Save sends each button's block to a Devin run; in a copy attached "
                              "in chat, paste the block into chat. Devin shows the Jira change and waits for \"approved\". "
                              "Re-run /dashboard to refresh the list."))
    return render_embedded_page(spec, page)


def render_embedded_page(spec, page):
    """A generated KB page (for example the ontology) carried inside the dashboard and opened in a new tab."""
    title = spec.get("title", spec["id"])
    if not page:
        empty = html.escape(spec.get("empty", "The page has not been generated yet."))
        return panel(title, '<p class="c-muted">%s</p>' % empty, count=0, attention="clear")
    doc_id = "page-doc-%s" % spec["id"]
    doc = json.dumps(page["html"]).replace("</", "<\\/")
    body = ('<p>%s</p><p><button class="a-btn a-btn--primary" type="button" data-roadmap-open data-doc="%s">Open %s in a new tab'
            '</button></p><script type="application/json" id="%s">%s</script>'
            % (html.escape(spec.get("summary", "")), doc_id, html.escape(title.lower()), doc_id, doc))
    note = spec.get("note", "The page at %s%s. It opens in a new tab. %s" % (
        page["path"], ", as of %s" % page["generated"] if page["generated"] else "", spec.get("rebuild", "")))
    return panel(title, body, note=note, attention=spec.get("attention", "info"))


WORKLOAD_SIGNALS = {
    "overloaded": "over", "heavy": "warn", "room for more": "light",
    "no sprint work": "light", "not estimated": "warn", "unplanned": "warn",
}


def render_workload(spec, sprint, sprint_issues):
    title = spec.get("title", "Who is carrying the sprint")
    if not sprint.get("name"):
        return panel(title, "", spec.get("empty", "No active sprint on the team board."))
    token, sheet_people = sprint_capacity(sprint)
    rows = workload_rows(spec, sprint, sprint_issues, sheet_people)
    days = working_days(sprint.get("start"), sprint.get("end"))
    body = []
    for row in rows:
        load = "—" if row["load"] is None else "%d%%" % round(row["load"] * 100)
        capacity = "—" if row["capacity"] is None else "%gh" % row["capacity"]
        role = row["role"]
        if row["allocation"] not in (None, 100.0):
            role = "%s · %g%% allocated" % (role, row["allocation"])
        signal = WORKLOAD_SIGNALS.get(row["signal"], "ok")
        body.append(
            '<tr%s><td>%s</td><td>%s</td><td>%s</td><td>%gh</td><td>%s</td>'
            "<td><b>%s</b></td><td>%s</td></tr>"
            % (' data-attention="%s"' % esc(signal) if signal != "ok" else "", esc(row["person"]),
               esc(role), esc(row["items"]), row["hours"], esc(capacity), esc(load), esc(row["signal"]))
        )
    overloaded = [row for row in rows if row["signal"] == "overloaded"]
    return panel(
        title,
        table("<th>Person</th><th>Role</th><th>Sprint items</th><th>Estimated</th>"
              "<th>Capacity</th><th>Load</th><th>Signal</th>", "".join(body)),
        note=workload_note(sprint, days, spec, token, rows),
        count=len(overloaded) or len(rows),
        attention="hot" if overloaded else attention_for(rows, lambda r: r["signal"] == "heavy", "info"),
    )


def team_issue(issue):
    """One sprint issue for the Team activity tab: who has it, what it is and where it stands."""
    fields = issue_fields(issue)
    assignee = fields.get("assignee") or {}
    status = fields.get("status") or {}
    return {
        "key": issue.get("key", ""),
        "summary": fields.get("summary") or "",
        "type": (fields.get("issuetype") or {}).get("name", ""),
        "status": status.get("name", ""),
        "category": (status.get("statusCategory") or {}).get("key", "new"),
        "parent": (fields.get("parent") or {}).get("key", ""),
        "username": assignee.get("name", ""),
        "updated": fields.get("updated") or "",
    }


# Session states as a lead reads them about someone else's session.
TEAM_SESSION_STATES = {
    "waiting_for_user": "Waiting on them", "blocked": "Waiting on them", "finished": "Finished",
    "suspended": "Asleep", "working": "Devin working", "running": "Devin working",
    "exit": "Ended", "error": "Ended", "expired": "Ended",
}


def team_sessions(path):
    """The team's Devin Cloud sessions Argus collected for this page ({"sessions": [...], "viewer", "days"}),
    or None when none were collected (no file, or Argus could not read Devin Cloud)."""
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else {"sessions": data}


def team_session_row(entry):
    state = ""
    for value in (entry.get("substatus"), entry.get("status")):
        state = TEAM_SESSION_STATES.get(str(value or "").strip().lower(), "")
        if state:
            break
    text = " ".join([entry.get("title") or ""] + [str(t) for t in entry.get("tags") or []])
    story = KEY_PATTERN.search(text)
    return {
        "id": str(entry.get("session_id", "")).replace("devin-", ""),
        "title": entry.get("title") or "untitled session",
        "state": state or "Unknown",
        "idle": stamp_age(entry.get("updated") or entry.get("created")),
        "updated": entry.get("updated") or entry.get("created") or 0,
        "story": story.group(0) if story else "",
        "argus": "sdlc-workbench" in (entry.get("tags") or []),
    }


def team_activity_rows(issues, sessions, roster=None):
    """One row per roster person: their sprint items by status and their recent Devin Cloud sessions."""
    roster = roster if roster is not None else people().get("people") or []
    by_user, by_devin = {}, {}
    for issue in issues:
        by_user.setdefault(issue.get("username") or "", []).append(issue)
    for entry in sessions or []:
        by_devin.setdefault(str(entry.get("user_id") or ""), []).append(team_session_row(entry))
    rows = []
    for person in roster:
        user = person.get("jira_user") or ""
        if not user:
            continue
        items = by_user.get(user, [])
        mine = sorted(by_devin.get(person.get("devin_user_id") or "", []),
                      key=lambda r: -(r["updated"] if isinstance(r["updated"], (int, float)) else 0))
        rows.append({
            "person": person.get("name") or user,
            "role": (person.get("primary_role") or ", ".join(person.get("roles") or [])).replace("_", " "),
            "doing": [i for i in items if i.get("category") == "indeterminate"],
            "todo": len([i for i in items if i.get("category") == "new"]),
            "done": len([i for i in items if i.get("category") == "done"]),
            "sessions": mine,
            "known_in_devin": bool(person.get("devin_user_id")),
        })
    rows.sort(key=lambda r: (not (r["doing"] or r["sessions"]), r["person"].casefold()))
    return rows


def _team_item(issue):
    under = ' <span class="a-badge">sub-task of %s</span>' % jira_link(issue["parent"]) if issue.get("parent") else ""
    return "<li>%s %s · <em>%s</em>%s</li>" % (jira_link(issue["key"]), esc(issue.get("summary", "")),
                                               esc(issue.get("status", "")), under)


def _team_session(row, host):
    link = '<a href="https://%s/sessions/%s" target="_blank" rel="noopener">%s</a>' % (
        esc(host), esc(row["id"]), esc(row["title"]))
    bits = [esc(row["state"]), esc(age_text(row["idle"]) if isinstance(row["idle"], int) else "unknown")]
    if row["story"] and row["story"] not in row["title"]:
        bits.append(jira_link(row["story"]))
    if row["argus"]:
        bits.append("Argus")
    return "<li>%s · %s</li>" % (link, " · ".join(bits))


def render_team_activity(spec, sprint, issues, collected, viewer=None):
    """Who is working on what: each roster person's sprint items in progress, what is still to do, and the
    Devin Cloud sessions they used lately. Reading only."""
    title = spec.get("title", "Who is working on what")
    host = spec.get("host") or "acme.devinenterprise.com"
    limit = int(spec.get("limit") or 4)
    days = int((collected or {}).get("days") or spec.get("days") or 7)
    sessions = (collected or {}).get("sessions") or []
    rows = team_activity_rows(issues, sessions)
    if not rows:
        return panel(title, "", spec.get("empty", "No one on the roster."))
    body = []
    for row in rows:
        doing = "<ul>%s</ul>" % "".join(_team_item(i) for i in row["doing"]) if row["doing"] else "Nothing in progress"
        if collected is None:
            devin = "—"
        elif not row["known_in_devin"]:
            devin = "<em>No Devin Cloud id on the roster</em>"
        elif row["sessions"]:
            more = len(row["sessions"]) - limit
            devin = "<ul>%s</ul>%s" % ("".join(_team_session(r, host) for r in row["sessions"][:limit]),
                                       "<p>and %d more</p>" % more if more > 0 else "")
        else:
            devin = "None in the last %d days" % days
        body.append('<tr data-person="%s"><td><strong>%s</strong><br>%s</td><td>%s</td><td>%d to do · %d done</td>'
                    "<td>%s</td></tr>" % (esc(row["person"]), esc(row["person"]), esc(row["role"]), doing,
                                          row["todo"], row["done"], devin))
    busy = len([r for r in rows if r["doing"]])
    active = len([r for r in rows if r["sessions"]])
    note = ("%s: %d of %d people have sprint work in progress." % (sprint.get("name"), busy, len(rows))
            if sprint.get("name") else "No active sprint on the team board, so no Jira work is shown.")
    if collected is None:
        note += " Devin Cloud sessions were not collected for this page; open the dashboard from Argus to see them."
    else:
        note += " %d used Devin Cloud in the last %d days." % (active, days)
        others = {str(e.get("user_id") or "") for e in sessions} - {viewer or ""}
        if sessions and not others and any(r["known_in_devin"] for r in rows if r["person"] != (viewer or "")):
            note += (" Only your own sessions came back: seeing teammates' sessions needs the View sessions "
                     "permission in Devin Cloud.")
    note += " Sub-tasks show under the person they are assigned to. Reading only."
    table_html = (table("<th>Person</th><th>In progress in Jira</th><th>Rest of the sprint</th>"
                        "<th>Devin Cloud sessions (last %d days)</th>" % days, "".join(body)))
    return panel(title, table_html, note=spec.get("note", note), count=busy or None, attention="info")


APPROVAL_JQL = (
    'project = ACME AND labels = Approval AND assignee = "%s" AND resolution = Unresolved ORDER BY created ASC'
)
APPROVAL_DECISIONS = (("", "— no decision —"), ("approve", "Approve"),
                      ("approve-with-notes", "Approve with notes"), ("reject", "Reject"),
                      ("delegate", "Send to someone else"))


def approval_subtask_row(issue):
    """An approval sub-task assigned to the viewer, read the same way approval_subtask.py writes it."""
    fields = issue_fields(issue)
    match = re.search(r"\{code:title=APPROVAL-STATE\}\s*(\{.*?\})\s*\{code\}", fields.get("description") or "", re.S)
    if not match:
        return None
    try:
        state = json.loads(match.group(1))
    except ValueError:
        return None
    if state.get("overall") != "pending":
        return None
    age = day_age(fields.get("created") or "")
    return {
        "key": issue.get("key", ""),
        "items": [{"n": i.get("n"), "text": i.get("text", ""), "state": i.get("state", "pending")}
                  for i in state.get("items", [])],
        "waiting_on": None,
        "requirement": state.get("requirement", ""),
        "title": (fields.get("parent") or {}).get("key", "") + " — " + (fields.get("summary") or ""),
        "session": "Jira approval sub-task %s (requested by %s)" % (issue.get("key", ""), state.get("requested_by", "")),
        "gate_id": state.get("gate", ""),
        "name": state.get("gate", ""),
        "requirement_text": "See the sub-task for artifacts and criteria.",
        "owner": state.get("requested_by", ""),
        "days": age if isinstance(age, int) else 0,
        "timeout_hours": None,
        "time_left": None,
    }


def approval_item_controls(key, item):
    n = item.get("n")
    state = item.get("state", "pending")
    if state != "pending":
        return '<span class="a-badge">%s</span>' % esc(state)
    options = "".join('<option value="%s">%s</option>' % (esc(v), esc(label)) for v, label in APPROVAL_DECISIONS)
    return (
        '<select aria-label="Decision" data-approval-decision="%s" data-item="%s">%s</select> '
        '<select aria-label="Send to" data-approval-to="%s" data-item="%s">%s</select>'
        '<textarea aria-label="Note" data-approval-note="%s" data-item="%s" rows="2" '
        'placeholder="notes — required to reject or send on"></textarea>'
    ) % (esc(key), n, options, esc(key), n, person_picker("— send to —"), esc(key), n)


def normalise_approvals(items):
    """Every approval row needs a paste-back key and at least one decision item."""
    for item in items:
        item["key"] = item.get("key") or "session:%s/%s" % (item.get("requirement", ""), item.get("gate_id", ""))
        item.setdefault("items", [{"n": 1, "text": "Approve %s as presented" % item.get("name", ""), "state": "pending"}])
    return items


def render_approvals(spec, items):
    normalise_approvals(items)
    if not items:
        return panel(spec.get("title", "Approvals awaiting me"), "", "Nothing is waiting on you.")
    rows = []
    for item in items:
        left = item.get("time_left")
        if left is None:
            time_text = "no timeout set"
        elif left < 0:
            time_text = "overdue by %s hours" % abs(left)
        else:
            time_text = "%s hours left" % left
        key = item["key"]
        waiting = item.get("waiting_on")
        decision_rows = "".join(
            '<tr class="approval-item"><td>[%s]</td><td>%s</td><td>%s</td></tr>'
            % (esc(d.get("n")), esc(d.get("text")),
               ('<span class="a-badge">with %s</span>' % esc(waiting)) if waiting else approval_item_controls(key, d))
            for d in item.get("items") or []
        )
        rows.append(
            "<tr><td><b>%s</b><br>%s<br><small>%s</small></td><td>%s<br><small>%s</small></td>"
            "<td><table class=\"approval-items\">%s</table></td><td>%s days<br>%s</td></tr>"
            % (esc(item.get("requirement")), esc(item.get("title")), esc(item.get("session", "")),
               esc(item.get("name")), esc(item.get("requirement_text")), decision_rows,
               esc(item.get("days")), esc(time_text))
        )
    body = table("<th>Requirement</th><th>Gate</th><th>Decision items</th><th>Waiting</th>", "".join(rows))
    return panel(
        spec.get("title", "Approvals awaiting me"), body, count=len(items), attention="hot", action="approvals",
        note="Decide each numbered item: Approve, Approve with notes, Reject (note required) or Send to "
             "someone else (pick the person, note required). Then click Generate approvals and Save (in a copy attached "
             "in chat, paste the block into chat). The block is the approval; nothing is recorded until it is applied.",
    )


def render_pipeline(spec, items):
    if not items:
        return panel(spec.get("title", "Team pipeline"), "", "No active requirements.")
    rows = "".join(
        "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" %
        (esc(i.get("requirement")), esc(i.get("owner")), esc(i.get("phase")), esc(i.get("blocked_on")))
        for i in items
    )
    body = table("<th>Requirement</th><th>Owner</th><th>Phase</th><th>Blocked on</th>", rows)
    blocked = [i for i in items if (i.get("blocked_on") or "").startswith("approval:")]
    return panel(
        spec.get("title", "Team pipeline"), body, count=len(blocked) or len(items),
        attention="watch" if blocked else "info",
    )


def health_summary():
    """Pipeline-health numbers from every owner's metrics.jsonl the store can see."""
    rows = []
    for path in glob.glob(os.path.join(session_store.local_home(), "*", "metrics.jsonl")):
        rows.extend(metrics.load(path=path))
    return metrics.summary(rows)


def render_health(spec, summ):
    gates_seen = summ.get("gates") or {}
    waiting = summ.get("waiting_now") or []
    if not gates_seen:
        return panel(spec.get("title", "Pipeline health"), "",
                     "No gate events recorded yet. Numbers appear once /intake presents its first gate.")
    waiting_by_gate = {}
    for w in waiting:
        waiting_by_gate[w["gate"]] = waiting_by_gate.get(w["gate"], 0) + 1
    rows = "".join(
        "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
            esc(gid), esc(g["presented"]), esc(g["approved"]), esc(g["rework"]),
            "-" if g["avg_wait_hours"] is None else esc(g["avg_wait_hours"]),
            esc(g["escalated"]), esc(waiting_by_gate.get(gid, 0)))
        for gid, g in sorted(gates_seen.items())
    )
    body = table("<th>Gate</th><th>Presented</th><th>Approved</th><th>Rework</th>"
                 "<th>Avg wait (h)</th><th>Escalated</th><th>Waiting now</th>", rows)
    if waiting:
        body += table("<th>Waiting</th><th>Story</th><th>Gate</th><th>Since</th>", "".join(
            "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                esc(w["requirement_id"]), esc(w.get("story_id") or ""), esc(w["gate"]), esc(w["since"]))
            for w in waiting))
    escalations = sum(g["escalated"] for g in gates_seen.values())
    rework = sum(g["rework"] for g in gates_seen.values())
    note = "%d requirement(s); %d rework loop(s); %d escalation(s)." % (
        len(summ.get("requirements") or []), rework, escalations)
    return panel(spec.get("title", "Pipeline health"), body, note=note,
                 count=len(waiting) or None, attention="watch" if escalations else "info")


def render_branches(spec, rows, base):
    if not rows:
        return panel(spec.get("title", "Branches"), "", spec.get("empty", "No branch carries a Acme Claims key."))
    body = []
    flagged = 0
    rows = sorted(rows, key=lambda r: not branch_needs_attention(r))
    for row in rows:
        hot = branch_needs_attention(row)
        flagged += hot
        body.append(
            "<tr%s><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>+%s / -%s</td><td>%s</td></tr>"
            % (' data-attention="hot"' if hot else "",
               esc(row.get("branch")), jira_link(row.get("key")), esc(row.get("status")),
               esc(row.get("author")), esc(row.get("ahead") or "0"), esc(row.get("behind") or "0"),
               esc(row.get("notes")))
        )
    branch_table = table(
        "<th>Branch</th><th>Story</th><th>Jira status</th><th>Last commit by</th>"
        "<th>Ahead / behind</th><th>State</th>", "".join(body))
    note = "Compared against %s in this checkout. Fetch first for an up-to-date picture." % (
        base or "no base branch"
    )
    if flagged:
        note = "%d of %d branches need a decision — highlighted. %s" % (flagged, len(rows), note)
    return panel(
        spec.get("title", "Branches"), branch_table, note=note, count=flagged or len(rows),
        attention="hot" if flagged else "info",
    )


def branch_needs_attention(row):
    """Unmerged work on a closed story, a conflict, or commits that never left the machine."""
    notes = (row.get("notes") or "").lower()
    if "nothing to merge" in notes:
        return False
    return any(word in notes for word in ("conflict", "closed but", "local only", "not pushed"))


def automation_settings():
    """`automation` in sdlc-profile.json: the test automation repo, its base branches and the personal branch name."""
    try:
        with open(os.path.join(ROOT, ".devin", "rules", "sdlc-profile.json"), encoding="utf-8") as fh:
            return json.load(fh).get("automation") or {}
    except (OSError, ValueError):
        return {}


def automation_checkout(spec, settings):
    """Where the automation repo is checked out: ACME_AUTOMATION_CHECKOUT, the panel's `checkout`, else ~/repos/<repo name>."""
    path = os.environ.get("ACME_AUTOMATION_CHECKOUT") or spec.get("checkout") or ""
    if not path and settings.get("repo"):
        path = os.path.join("~", "repos", settings["repo"].split("/")[-1])
    return os.path.expanduser(path) if path else ""


def repo_git(checkout, *args, timeout=120):
    try:
        result = subprocess.run(("git",) + args, cwd=checkout, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None, ""
    return result, (result.stdout.strip() if result.returncode == 0 else "")


def repo_conflicts(checkout, base, ref):
    """True/False when `ref` would or would not merge cleanly into `base`, None when git can't tell.
    git 2.38+ has `merge-tree --write-tree`; older git gets the three-argument form and its conflict markers."""
    merged, out = repo_git(checkout, "merge-tree", "--write-tree", base, ref)
    if merged and merged.returncode in (0, 1):
        return merged.returncode == 1 or "CONFLICT" in out
    fork = repo_git(checkout, "merge-base", base, ref)[1]
    if not fork:
        return None
    merged, out = repo_git(checkout, "merge-tree", fork, base, ref)
    return None if not merged or merged.returncode else "<<<<<<<" in out


def automation_branch_rows(spec, username, display, fetch=True):
    """The viewer's branches in the automation repo against its first base branch: (rows, base, note).
    Theirs = the personal branch (`personal_branch` with {user}) or a branch whose last commit they made."""
    settings = automation_settings()
    checkout = automation_checkout(spec, settings)
    if not checkout or not os.path.isdir(os.path.join(checkout, ".git")):
        return [], "", "The automation repo (%s) is not checked out on this machine, so its branches could not be read." % (
            settings.get("repo") or "not set")
    note = ""
    if fetch:
        result, _ = repo_git(checkout, "fetch", "-q", "origin", timeout=90)
        if not result or result.returncode:
            note = "Could not fetch the automation repo just now; this is the last copy on this machine."
    bases = settings.get("base_branches") or []
    base = "origin/" + (spec.get("base") or (bases[0] if bases else "master"))
    if not repo_git(checkout, "rev-parse", "--verify", "--quiet", base)[1]:
        return [], base, "The base branch %s is not in the automation repo." % base
    personal = (settings.get("personal_branch") or "").replace("{user}", username or "")
    skip = {"origin/HEAD", "origin/master", "origin", base} | {"origin/" + b for b in bases}
    _, listing = repo_git(checkout, "for-each-ref", "--format=%(refname:short)%09%(committerdate:short)%09%(authorname)",
                          "refs/remotes/origin")
    rows = []
    for line in listing.splitlines():
        parts = line.split("\t")
        if len(parts) != 3 or parts[0] in skip:
            continue
        ref, when, author = parts
        name = ref[len("origin/"):] if ref.startswith("origin/") else ref
        if not ((personal and name == personal) or (display and norm(author) == norm(display))):
            continue
        counts = repo_git(checkout, "rev-list", "--left-right", "--count", "%s...%s" % (base, ref))[1].split()
        behind, ahead = (counts + ["", ""])[:2]
        conflicts = repo_conflicts(checkout, base, ref) if ahead not in ("", "0") else None
        match = KEY_PATTERN.search(name.upper())
        rows.append({"branch": name, "key": match.group(0) if match else "", "committed": when, "author": author,
                     "ahead": ahead, "behind": behind, "conflicts": conflicts, "personal": name == personal})
    rows.sort(key=lambda r: (not r["personal"], r["branch"]))
    return rows, base, note


def automation_branch_state(row, base):
    """(text, hot) for one automation branch against the base."""
    short = base.split("/", 1)[-1]
    ahead, behind = row.get("ahead") or "0", row.get("behind") or "0"
    if ahead == "0":
        return ("Nothing to merge — same as %s" % short if behind == "0" else "Nothing new; %s behind %s" % (behind, short)), False
    if row.get("conflicts"):
        return "Conflicts with %s — resolve before the pull request" % short, True
    if behind != "0":
        return "%s commits to merge; %s has moved on by %s — update from it before the pull request" % (ahead, short, behind), True
    return "%s commits to merge, up to date with %s" % (ahead, short), False


def render_automation_branches(spec, rows, base, note=""):
    title = spec.get("title", "My automation branches")
    if not rows:
        return panel(title, "", spec.get("empty", "No automation branch of yours."), note=note)
    body, hot = [], 0
    for row in rows:
        state, flag = automation_branch_state(row, base)
        hot += flag
        body.append("<tr%s><td>%s</td><td>%s</td><td>%s</td><td>+%s / -%s</td><td>%s</td></tr>" % (
            ' data-attention="hot"' if flag else "", esc(row.get("branch")), jira_link(row.get("key")) or "—",
            esc(row.get("committed")), esc(row.get("ahead") or "0"), esc(row.get("behind") or "0"), esc(state)))
    grid = table("<th>Branch</th><th>Story</th><th>Last commit</th><th>Ahead / behind</th><th>State</th>", "".join(body))
    lead = "Your branches in the automation repo against %s: your own branch and any branch you last committed to." % (
        base.split("/", 1)[-1])
    return panel(title, grid, note=" ".join(n for n in (lead, note) if n), count=hot or len(rows),
                 attention="hot" if hot else "info")


SESSION_STATES = {
    "waiting_for_user": (0, "Ready for you", "Devin is waiting on your reply."),
    "blocked": (0, "Ready for you", "Devin is blocked and needs a decision from you."),
    "finished": (1, "Finished", "Read the result and close it out."),
    "suspended": (2, "Asleep", "Send it a message to wake it and carry on."),
    "working": (3, "Devin is working", "Nothing for you until it reports back."),
    "expired": (4, "Expired", "Past its window — start a new session if the work still matters."),
}
SESSION_UNKNOWN = (2, "Unknown", "Open it to see where it stopped.")


def stamp_age(value):
    """Whole days since a unix timestamp or an ISO stamp, and "unknown" for neither."""
    if isinstance(value, (int, float)):
        value = datetime.datetime.fromtimestamp(value, datetime.timezone.utc).isoformat()
    return day_age(value)


def session_rows(path):
    """The viewer's own Devin sessions, sorted by who they are waiting on.

    The session list is not readable from this machine: /dashboard queries it with the Devin
    session tools and writes the JSON this reads, which keeps the generator offline and the page
    free of a token. Sessions waiting on a reply sort first, ones Devin is still working last.
    """
    if not path:
        return []
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    return session_rows_from(payload.get("sessions") if isinstance(payload, dict) else payload)


def session_rows_from(entries):
    rows = []
    for entry in entries or []:
        if entry.get("is_archived") or "closed" in (entry.get("tags") or []):
            continue
        rank, label, next_step = SESSION_UNKNOWN
        for value in (entry.get("substatus"), entry.get("status")):
            state = str(value or "").strip().lower()
            if state in SESSION_STATES:
                rank, label, next_step = SESSION_STATES[state]
                break
        rows.append(
            {
                "id": str(entry.get("session_id", "")).replace("devin-", ""),
                "title": entry.get("title") or "untitled session",
                "state": label,
                "next": entry.get("note") or next_step,
                "idle": stamp_age(entry.get("updated") or entry.get("created")),
                "rank": rank,
                "handed_to": entry.get("handed_to") or "",
            }
        )

    def order(row):
        idle = row["idle"] if isinstance(row["idle"], int) else 0
        return (row["rank"], -idle if row["rank"] == 0 else idle)

    rows.sort(key=order)
    return rows


def person_picker(empty_label):
    options = []
    for person in people().get("people", []):
        if person.get("jira_user"):
            options.append(
                '<option value="%s">%s (%s)</option>'
                % (esc(person["jira_user"]), esc(person.get("name") or person["jira_user"]),
                   esc(", ".join(person.get("roles") or [])))
            )
    return '<option value="">%s</option>' % esc(empty_label) + "".join(options)


def render_sessions(spec, rows, can_hand_over):
    title = spec.get("title", "My Devin sessions")
    if not rows:
        return panel(title, "", spec.get("empty", "No session of yours is open."))
    host = spec.get("host") or "acme.devinenterprise.com"
    limit = int(spec.get("limit") or 12)
    picker = person_picker("— keep with me —") if can_hand_over else ""
    body = []
    for row in rows[:limit]:
        link = '<a href="https://%s/sessions/%s">%s</a>' % (esc(host), esc(row["id"]), esc(row["title"]))
        state = esc(row["state"])
        if row["handed_to"]:
            state += ' <span class="a-badge">handed to %s</span>' % esc(row["handed_to"])
        cells = [
            '<input type="checkbox" data-session-close="%s" aria-label="Close %s">' % (esc(row["id"]), esc(row["title"])),
            link, state,
            esc(age_text(row["idle"]) if isinstance(row["idle"], int) else "unknown"),
            esc(row["next"]),
        ]
        if can_hand_over:
            cells.append('<select aria-label="Hand over to" data-session-to="%s">%s</select>' % (esc(row["id"]), picker))
            cells.append(
                '<textarea aria-label="Note" data-session-note="%s" rows="2" '
                'placeholder="where it is, what is next"></textarea>' % esc(row["id"])
            )
        body.append(
            "<tr%s>%s</tr>" % (
                ' class="load-over"' if row["rank"] == 0 else "",
                "".join("<td>%s</td>" % cell for cell in cells),
            )
        )
    head = "<th>Close</th><th>Session</th><th>State</th><th>Last moved</th><th>What happens next</th>"
    if can_hand_over:
        head += "<th>Hand to</th><th>Handover note</th>"
    ready = len([row for row in rows if row["rank"] == 0])
    note = "%s of your %d open sessions %s waiting on you." % (
        ready or "None", len(rows), "is" if ready == 1 else "are"
    )
    if len(rows) > limit:
        note += " %d shown." % limit
    note += (
        " Tick the ones you are done with and click Close sessions: each one is ended for good (not just archived), "
        "so it stops using resources. Its transcript stays readable in Devin."
    )
    if can_hand_over:
        note += (
            " To pass a session to a teammate, pick them, say where the work is, and click "
            "Generate session handovers, then Save; the run does /handover for each one."
        )
    return panel(
        title, table(head, "".join(body)), note=spec.get("note", note),
        count=ready or len(rows), attention="hot" if ready else "info",
        action="sessions",
    )


def render_delegations(rows):
    if not rows:
        return ""
    picker = person_picker("— keep with me —")
    body = []
    for row in rows:
        body.append(
            '<tr><td>%s</td><td>%s</td><td>%s</td>'
            '<td><select aria-label="Delegate to" data-delegate-key="%s">%s</select></td>'
            '<td><textarea aria-label="Note" data-delegate-note="%s" rows="2" '
            'placeholder="why, and what done looks like"></textarea></td></tr>'
            % (jira_link(row.get("key")), esc(row.get("summary")), esc(row.get("status")),
               esc(row.get("key")), picker, esc(row.get("key")))
        )
    return panel(
        "Hand work over",
        table("<th>Item</th><th>Summary</th><th>Status</th><th>Hand to</th><th>Note</th>", "".join(body)),
        count=len(rows), attention="action", action="delegations",
        note="Pick a person, add the handover note, click Generate handovers, then Save. "
             "The run reassigns the Jira item and records who handed it over.",
    )


def observation_form(kinds, severities, environments):
    kind_options = "".join('<option value="%s">%s</option>' % (esc(k), esc(k)) for k in kinds)
    severity_options = "".join('<option value="%s">%s</option>' % (esc(s), esc(s)) for s in severities)
    env_options = "".join('<option value="%s">%s</option>' % (esc(e), esc(e)) for e in environments)
    rows = []
    for index in range(3):
        rows.append(
            '<fieldset class="a-fieldset"><legend>Observation %d</legend>'
            '<label class="a-field">Story or epic key<input data-obs="story" data-row="%d" placeholder="ACME-1234"></label>'
            '<label class="a-field">Kind<select data-obs="kind" data-row="%d">%s</select></label>'
            '<label class="a-field">Severity<select data-obs="severity" data-row="%d">%s</select></label>'
            '<label class="a-field">Where you saw it<select data-obs="environment" data-row="%d">%s</select></label>'
            '<label class="a-field">One-line title<input data-obs="title" data-row="%d" '
            'placeholder="what is wrong, in one line"></label>'
            '<label class="a-field">What happened<textarea data-obs="detail" data-row="%d" rows="4" '
            'placeholder="steps, expected, actual — no member or provider identifiers"></textarea></label>'
            '</fieldset>'
            % (index + 1, index, index, kind_options, index, severity_options, index,
               env_options, index, index)
        )
    return panel(
        "Raise an observation", "".join(rows), attention="action", action="observations",
        note="Observations go to Jira as an Observation, Defect or Risk linked to the story. "
             "A row is only included once it has a story, a title and what happened. "
             "Triage decides whether an observation becomes a defect. Never type member or "
             "provider identifiers here — see .devin/rules/pii-handling.md.",
    )


def capacity_sheet_path(given=None):
    """The sprint capacity sheet: --capacity-sheet, else capacity.sheet in scrum-master-metrics.yaml."""
    path = given or (scrum_lib.load_rules().get("capacity") or {}).get("sheet")
    return path and (path if os.path.isabs(path) else os.path.join(ROOT, path))


def with_leave_page(data, note):
    """With no capacity sheet: the active sprint's section of the Sprint Leave page, when it has one."""
    sprint = (data or {}).get("sprint") or {}
    found = sprint_leave.sprint_of(sprint.get("name", ""), sprint.get("start"), sprint.get("end"))
    if not found or not os.environ.get("ACME_CONFLUENCE_TOKEN"):
        return data, note
    try:
        page, stored = sprint_leave.load()
    except Exception as exc:  # noqa: BLE001 - the tab says why and falls back to the configured capacity
        return data, "; ".join(n for n in (note, "Sprint Leave page not read (%s)" % exc) if n)
    data = dict(data, time_off=sprint_leave.parse_time_off(page["body"]["storage"]["value"]))
    if found["token"] not in stored:
        return data, note
    return dict(data, capacity=sprint_leave.capacity(found["token"], stored[found["token"]])), note


def with_devin_usage(result):
    """Add the team's Devin sessions for the Cost tab; a key that is missing or refused becomes the note."""
    import devin_usage
    data, note = result
    try:
        return dict(data, devin_sessions=devin_usage.fetch()), note
    except Exception as exc:  # noqa: BLE001 - the Cost tab still shows Jira hours
        return data, "; ".join(n for n in (note, "Devin sessions not read (%s)" % exc) if n)


def with_capacity(result, path):
    """Add the capacity sheet to the Scrum Master data; a sheet that cannot be read becomes the note."""
    data, note = result
    if not path:
        return with_leave_page(data, note)
    data = dict(data)
    try:
        data["capacity"] = capacity_lib.read(path, (data.get("sprint") or {}).get("start"))
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        note = "; ".join(n for n in (note, "Capacity sheet not read (%s)" % exc) if n)
    return data, note


def jira_unanswered(exc):
    return str(exc).startswith("Jira could not be reached")


def jira_unanswered_panel(spec, exc):
    """One tab whose Jira read timed out or dropped: it says so, and the rest of the dashboard still builds."""
    return panel(spec.get("title", spec["id"]), "", "Jira didn't answer while this tab was built.", str(exc),
                 attention="watch")


def build(args):
    source = (
        CacheSource(args.cache, args.user, args.base) if args.cache
        else LiveSource(args.user, args.base)
    )
    source.capacity_sheet = capacity_sheet_path(getattr(args, "capacity_sheet", None))
    roles = source.entry.get("roles") or [people().get("default_role", "developer")]
    primary = source.entry.get("primary_role") or ""
    lens_id, lens = select_lens(roles, args.lens, primary)
    config = lens_config()
    specs = config.get("panels") or {}
    questions, asked = [], []
    try:
        questions = source.questions()
        asked = source.my_questions()
    except RuntimeError as exc:
        if not jira_unanswered(exc):
            raise
    approvals, pipeline = ([], [])
    panels = []
    panel_specs = []
    delegatable = []
    sessions = []
    assigned_keys = set()
    overrides = lens.get("columns") or {}
    hats = {primary} | set(roles) | set(source.entry.get("secondary_roles") or [])
    for panel_id in lens.get("panels") or []:
        spec = dict(specs.get(panel_id) or {})
        spec["id"] = panel_id
        if spec.get("audience") and not hats & set(spec["audience"]):
            continue
        if read_only_lens(lens):
            spec["read_only"] = True
        panel_specs.append(spec)
        if panel_id in overrides:
            spec["columns"] = overrides[panel_id]
        try:
            kind = spec.get("kind")
            if kind == "jira":
                rows, note = source.jira_panel(spec)
                if panel_id == "my_work":
                    assigned_keys.update(row.get("key", "") for row in rows)
                if spec.get("delegatable"):
                    delegatable.extend(rows)
                panels.append(render_jira_panel(spec, rows, note))
            elif kind == "demo_board":
                rows, note = source.demo_board(spec)
                if spec.get("delegatable"):
                    delegatable.extend(rows)
                panels.append(render_demo_board(spec, rows, note))
            elif kind == "approvals":
                approvals, pipeline = source.approvals()
                panels.append(render_approvals(spec, approvals))
            elif kind == "pipeline":
                if not pipeline:
                    approvals, pipeline = source.approvals()
                panels.append(render_pipeline(spec, pipeline))
            elif kind == "health":
                panels.append(render_health(spec, source.health()))
            elif kind == "workload":
                sprint, sprint_issues = source.workload(spec)
                panels.append(render_workload(spec, sprint, sprint_issues))
            elif kind == "team_activity":
                sprint, team_items = source.team_activity(spec)
                collected = team_sessions(getattr(args, "team_sessions", None))
                if collected is None and source.kind == "cache":
                    collected = source.data.get("team_sessions")
                panels.append(render_team_activity(spec, sprint, team_items, collected,
                                                   source.entry.get("devin_user_id") or ""))
            elif kind == "docgap":
                panels.append(render_doc_questions(spec, doc_marker_hits(spec)))
            elif kind == "learn":
                panels.append(render_learn(spec, learn_questions(source.entry.get("name", ""))))
            elif kind == "role_config":
                panels.append(render_role_config(spec))
            elif kind == "gate_config":
                panels.append(render_gate_config(spec))
            elif kind == "workbench_config":
                panels.append(render_workbench_config(spec))
            elif kind == "skill_config":
                panels.append(render_skill_config(spec))
            elif kind == "commands":
                panels.append(render_commands(spec, ([primary] if primary else []) + roles, lens_id))
            elif kind == "feedback":
                panels.append(render_feedback(spec))
            elif kind == "workbench_noticed":
                panels.append(render_workbench_noticed(spec))
            elif kind == "workbench_feedback":
                panels.append(render_team_feedback(spec))
            elif kind == "insights":
                panels.append(render_insights(spec))
            elif kind == "framework_changes":
                panels.append(render_framework_changes(spec))
            elif kind == "docdrift":
                panels.append(render_doc_drift(spec, doc_drift_rows(spec)))
            elif kind == "vacation":
                rows, note = source.vacation(spec)
                log, _ = source.unplanned(spec)
                panels.append(render_vacation(spec, rows, note, getattr(source, "username", ""), unplanned=log))
            elif kind == "unplanned":
                rows, note = source.unplanned(spec)
                panels.append(render_unplanned(spec, rows, note))
            elif kind == "risks":
                panels.append(render_risks(spec))

            elif kind == "defect_rca":
                rows, note = source.defect_rca(spec)
                panels.append(render_defect_rca(spec, rows, note))
            elif kind == "defect_matrix":
                data, note = source.defect_matrix(spec)
                panels.append(render_defect_matrix(spec, data, note))
            elif kind == "grooming_prep":
                data, note = source.grooming_prep(spec)
                panels.append(render_grooming_prep(spec, data, note))
            elif kind == "backlog":
                data, note = source.backlog(spec)
                panels.append(render_backlog(spec, data, note))
            elif kind == "hygiene":
                data, note = source.hygiene(spec)
                panels.append(render_hygiene(spec, data, note))
            elif kind == "scrum":
                data, note = source.scrum(spec)
                panels.append(render_scrum(spec, data, note))
            elif kind == "confidence":
                panels.append(render_confidence(spec, *change_confidence(source)))
            elif kind == "roadmap":
                panels.append(render_roadmap(spec, roadmap_page(spec)))
            elif kind == "page":
                panels.append(render_embedded_page(spec, roadmap_page(spec)))
            elif kind == "roster":
                findings, is_steward = source.roster()
                panels.append(render_roster(spec, findings, is_steward))
            elif kind == "branches":
                panels.append((spec, spec.get("scope", "all")))
            elif kind == "automation_branches":
                rows, base, note = source.automation_branches(spec)
                panels.append(render_automation_branches(spec, rows, base, note))
            elif kind == "sessions":
                sessions = source.sessions(args.sessions)
                panels.append(render_sessions(spec, sessions, "session_handovers" in (lens.get("actions") or [])))
            else:
                panels.append(
                    panel(spec.get("title", panel_id), "", "This panel kind is not supported.")
                )
        except RuntimeError as exc:
            if not jira_unanswered(exc):
                raise
            panels.append(jira_unanswered_panel(spec, exc))
    resolved = []
    for spec, item in zip(panel_specs, panels):
        if isinstance(item, tuple):
            try:
                item = render_branches(spec, source.branches(item[1], assigned_keys), source.base)
            except RuntimeError as exc:
                if not jira_unanswered(exc):
                    raise
                item = jira_unanswered_panel(spec, exc)
        item = labelled(item, spec.get("icon", ""), spec.get("tab", ""))
        item["panel_id"] = spec["id"]
        item["group"] = spec.get("group", "")
        resolved.append(item)
    actions = [] if read_only_lens(lens) else (lens.get("actions") or ["answers"])
    seen = set()
    unique_delegatable = []
    for row in delegatable:
        key = row.get("key")
        if key and key not in seen:
            seen.add(key)
            unique_delegatable.append(row)
    return {
        "username": source.username,
        "display": source.display,
        "roles": roles,
        "lens_id": lens_id,
        "lens": lens,
        "questions": questions,
        "asked": asked,
        "approvals": approvals,
        "panels": resolved,
        "delegatable": unique_delegatable,
        "sessions": sessions,
        "actions": actions,
        "groups": business_groups(lens_id),
        "workbench_url": business_screens().get("workbench_url", ""),
        "sample": source.kind == "cache",
    }


def render(ctx):
    sections = [
        labelled(render_questions("Questions for me", ctx["questions"], answer_box="answers" in ctx["actions"]),
                 "\u2753", "Questions"),
        labelled(render_my_questions(ctx["asked"]), "\U0001F64B", "Asked"),
    ]
    sections[0]["panel_id"], sections[1]["panel_id"] = "questions", "asked"
    sections.extend(ctx["panels"])
    if "delegations" in ctx["actions"] and ctx["delegatable"]:
        sections.append(labelled(render_delegations(ctx["delegatable"]), "\U0001F91D", "Hand over"))
    if "observations" in ctx["actions"]:
        sections.append(labelled(observation_form(OBSERVATION_KINDS, SEVERITIES, ENVIRONMENTS),
                                 "\U0001F6A9", "Raise"))
    # Loudest first, in config order within a level, and every empty tab at the end.
    groups = ctx.get("groups") or []
    if groups:
        place_in_groups(sections, groups, ctx.get("workbench_url", ""))
        sections.sort(key=lambda s: (s["group_index"], ATTENTION_ORDER.get(s["attention"], 9)))
        tabs = render_job_strip(sections, [g.get("group", "") for g in groups] + ["Reference"])
    else:
        named = []
        for section in sections:
            if section.get("group") and section["group"] not in named:
                named.append(section["group"])
        # Named groups (Framework feedback, Team Devin Cloud Usage) come after the attention groups, in config order.
        sections.sort(key=lambda s: (named.index(s["group"]) + 1, 0) if s.get("group") in named
                      else (0, ATTENTION_ORDER.get(s["attention"], 9)))
        tabs = render_tab_strip(sections)
    panes = "\n".join(render_tab(i, s) for i, s in enumerate(sections))
    tally = {level: 0 for level in ATTENTION_ORDER}
    for section in sections:
        tally[section["attention"]] += 1
    summary = "".join(
        '<span class="a-chip" data-attention="%s"><span class="a-dot"></span>%d %s</span>'
        % (level, tally[level], esc(ATTENTION_LABELS[level]))
        for level in ("hot", "watch", "clear") if tally[level]
    )
    buttons = []
    if "answers" in ctx["actions"]:
        buttons.append('<button id="build-answers" data-action="answers" class="a-btn a-btn--primary" type="button">Generate answers</button>')
    if "delegations" in ctx["actions"] and ctx["delegatable"]:
        buttons.append('<button id="build-delegations" data-action="delegations" class="a-btn a-btn--primary" type="button">Generate handovers</button>')
    if "observations" in ctx["actions"]:
        buttons.append('<button id="build-observations" data-action="observations" class="a-btn a-btn--primary" type="button">Generate observations</button>')
    if ctx["sessions"]:
        buttons.append('<button id="close-sessions" data-action="sessions" class="a-btn a-btn--primary" '
                       'type="button">Close sessions</button>')
    if "session_handovers" in ctx["actions"] and ctx["sessions"]:
        buttons.append('<button id="build-session-handovers" data-action="sessions" class="a-btn a-btn--outline" type="button">Generate session handovers</button>')
    if ctx["approvals"] and ctx["actions"]:
        buttons.append('<button id="build-approvals" data-action="approvals" class="a-btn a-btn--primary" type="button">Generate approvals</button>')
    lens = ctx["lens"]
    team = (load_yaml(LENS_PATH, {}).get("team") or {}).get("it_team") or ""
    body = BODY % {"tabs": tabs, "panels": panes, "buttons": "\n".join(buttons)}
    if not ctx["actions"]:
        body = re.sub(r'<p class="a-section__note">Fill in a tab.*?</p>', lambda m: '<p class="a-section__note">' +
                      "This dashboard only reads. Every action is in Argus: My tools → Answer, approve, hand over, change config.</p>",
                      body, count=1, flags=re.S)
    return artifact_kit.render_page(
        "Acme Claims dashboard — %s" % lens.get("label", ctx["lens_id"]),
        body,
        subtitle="%s · your roles: %s · %s · as of %s" % (
            esc(ctx["display"] if ctx["display"] == ctx["username"] else "%s · %s" % (ctx["display"], ctx["username"])),
            esc(", ".join(ctx["roles"])),
            esc("team %s" % team if team else "whole Acme Claims project"),
            esc(datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))),
        aside=('<span class="a-chip" data-attention="watch" title="Rendered from a fixture for demonstration; '
               'no live Jira, git or Devin session was read.">Sample data</span>' if ctx.get("sample") else "") + summary,
        extra_css=DASHBOARD_CSS + grooming_prep.CSS + INSIGHTS_CSS + DEMO_CSS +
        ".a-table-scroll{content-visibility:auto;contain-intrinsic-size:auto 480px}",
        before_kit_js=PICK_TAB_JS + WB_LINK_JS + NEW_TAB_JS,
        logo=ARGUS_LOGO,
        extra_js=GROUP_JS + INSIGHTS_JS + DEMO_JS + FORM_JS % {
            "question_keys": json.dumps([i.get("key", "") for i in ctx["questions"]]),
            "delegate_keys": json.dumps([i.get("key", "") for i in ctx["delegatable"]]),
            "session_ids": json.dumps([i["id"] for i in ctx["sessions"]]),
            "approval_keys": json.dumps([i.get("key", "") for i in ctx["approvals"]]),
        },
        body_class="dashboard",
    )


# The dashboard fills the whole window, edge to edge: the slim header, one row of group buttons and one row with the open
# group's tabs on top; the active panel takes the rest and scrolls inside itself, and the action bar stays pinned at the bottom. Everything else is the shared Acme Claims kit.
# Keeps the open group in step with the selected tab (click, arrow keys, #tab- link) and opens a group on its
# last used tab, or its first.
GROUP_JS = r"""(function () {
  var nav = document.querySelector(".tab-nav");
  if (!nav) return;
  var list = nav.querySelector("[data-a-tabs]");
  var switches = [].slice.call(nav.querySelectorAll(".tab-switch"));
  var last = {};
  function show(id) {
    switches.forEach(function (b) { b.setAttribute("aria-pressed", b.getAttribute("aria-controls") === id ? "true" : "false"); });
    nav.querySelectorAll(".tab-group").forEach(function (g) { g.hidden = g.id !== id; });
  }
  function sync() {
    var tab = list.querySelector('[role="tab"][aria-selected="true"]');
    var group = tab && tab.closest(".tab-group");
    if (!group) return null;
    last[group.id] = tab;
    show(group.id);
    return tab;
  }
  sync();
  list.addEventListener("click", sync);
  list.addEventListener("keydown", function (e) {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    var tab = sync();
    if (tab) tab.focus();
  });
  switches.forEach(function (b) {
    b.addEventListener("click", function () {
      var id = b.getAttribute("aria-controls");
      var tab = last[id] || document.querySelector("#" + id + ' [role="tab"]');
      show(id);
      if (tab) tab.click();
    });
  });
}());
"""

NEW_TAB_JS = """
document.querySelectorAll('.panel-body a[href^="http"]').forEach(function (a) { a.target = "_blank"; a.rel = "noopener"; });
"""

DASHBOARD_CSS = """
.panel-body a:not(.a-btn) { color: rgb(var(--text-accent)); text-decoration: none; }
.panel-body a:not(.a-btn):hover { text-decoration: underline; }
body.dashboard { height: 100vh; display: flex; flex-direction: column; }
body.dashboard .a-shell { --max-width: none; flex: 1; display: flex; flex-direction: column; min-height: 0;
  width: 100%; padding: calc(var(--unit) * 4) calc(var(--unit) * 6) 0; }
body.dashboard .a-header { margin-bottom: 0; }
.tabpanel { flex: 1; display: flex; flex-direction: column; min-height: 0; margin-top: calc(var(--unit) * 2);
  padding: calc(var(--unit) * 2) calc(var(--unit) * 4) calc(var(--unit) * 4);
  background: rgb(var(--bg-elevated)); border: 1px solid rgb(var(--border-secondary));
  border-radius: var(--radius); box-shadow: inset 3px 0 0 rgb(var(--attention)); }
.tabpanel[hidden] { display: none; }
.tabpanel { overflow: hidden; }
.a-tabs .a-btn[aria-selected="true"] .a-badge { background: rgb(255 255 255 / 0.25); color: #fff; }
.tab-nav { flex: none; margin-top: calc(var(--unit) * 2); }
.tab-switches { display: flex; gap: calc(var(--unit) * 1); overflow-x: auto; scrollbar-width: thin;
  border-bottom: 1px solid rgb(var(--border-primary)); }
.tab-switch { appearance: none; flex: none; display: inline-flex; align-items: center; gap: calc(var(--unit) * 1.5);
  padding: 5px 12px 4px; border: 0; border-bottom: 3px solid transparent; background: transparent; cursor: pointer;
  font: inherit; font-size: 13px; font-weight: 600; color: rgb(var(--text-secondary)); white-space: nowrap; }
.tab-switch:hover { color: rgb(var(--text-primary)); background: rgb(var(--tint-secondary)); }
.tab-switch[aria-pressed="true"] { color: rgb(var(--text-primary)); border-bottom-color: rgb(var(--attention)); }
.tab-switch__n { font-weight: 400; font-size: 12px; color: rgb(var(--text-tertiary)); }
.a-tabs.tab-strip { display: block; margin-top: calc(var(--unit) * 1.5); padding: 2px; }
.tab-group[hidden] { display: none; }
.tab-group__label { display: none; }
.tab-group__tabs { display: flex; flex-wrap: wrap; gap: 2px calc(var(--unit) * 1); }
.tab-strip .a-btn { display: inline-flex; align-items: center; gap: calc(var(--unit) * 1.5); padding: 3px 10px; white-space: nowrap; }
.tab-strip .a-btn .tab-icon { font-size: 14px; }
.tab-icon { font-size: 16px; line-height: 1; }
.tabpanel .a-section__title .tab-icon { font-size: 20px; margin-right: calc(var(--unit) * 2); }
.tabpanel .a-section__title { margin-top: calc(var(--unit) * 2); }
.tabpanel .a-section__note { max-width: none; }
.panel-body { flex: 1; min-height: 120px; overflow: auto; }
.panel-body .a-table-scroll { border: 0; border-radius: 0; }
.panel-body .a-table { min-width: 650px; }
.question { margin-bottom: calc(var(--unit) * 3); }
.question[data-attention="hot"] { box-shadow: inset 3px 0 0 rgb(var(--attention)); }
.age { margin-left: auto; color: rgb(var(--text-tertiary)); font-size: 12px; }
.meta { margin: calc(var(--unit) * 1) 0; color: rgb(var(--text-secondary)); font-size: 13px; }
.a-empty { margin: calc(var(--unit) * 4) 0; }
.a-empty::before { content: "\\2713"; display: block; font-size: 24px; color: rgb(var(--text-green)); }
td.sub { font-size: 12px; color: rgb(var(--text-secondary)); }
.action-bar { flex: none; position: sticky; bottom: 0; margin-top: calc(var(--unit) * 2);
  padding: calc(var(--unit) * 2) 0; background: rgb(var(--bg-page));
  border-top: 1px solid rgb(var(--border-primary)); }
.action-bar__row { display: flex; flex-wrap: wrap; align-items: center; gap: calc(var(--unit) * 2); }
.action-bar__row .a-section__note { margin: 0 auto 0 0; flex: 1 1 320px; max-width: none; font-size: 12px; }
@media (max-width: 640px) { body.dashboard .a-shell { padding: calc(var(--unit) * 2) calc(var(--unit) * 3) 0; }
  .tab-group__tabs { flex-wrap: nowrap; overflow-x: auto; } }
#answers { width: 100%; margin-top: calc(var(--unit) * 2); }
#output { width: 100%; min-height: 120px; max-height: 30vh; font: 12px/18px var(--font-mono);
  padding: calc(var(--unit) * 2); border: 1px solid rgb(var(--border-primary)); border-radius: var(--radius-sm);
  background: rgb(var(--bg-elevated)); color: rgb(var(--text-primary)); }
@media print { body.dashboard { height: auto; } .panel-body { overflow: visible; }
  .tabpanel[hidden] { display: flex; } .action-bar { display: none; } .tab-nav { display: none; } }
"""

BODY = """%(tabs)s
%(panels)s
<div class="action-bar a-no-print"><div class="action-bar__row"><p class="a-section__note">Fill in a tab and click its
button. Opened from Argus, Save sends the block to a Devin run, which shows the change and waits for your approval;
a saved copy of this page calls nothing, so paste the block into chat. Tabs without a form have no button.</p>
%(buttons)s
<button id="save-output" class="a-btn a-btn--primary" type="button" data-save="output" hidden>Save</button>
<button id="toggle-output" class="a-btn a-btn--outline" type="button" hidden>Hide block</button></div>
<div id="answers" hidden><textarea id="output" readonly spellcheck="false" aria-label="Generated block"></textarea></div></div>
""" + SAVE_JS

# Runs before the kit: mark the tab named in the URL hash as selected so the kit opens on it.
PICK_TAB_JS = """(function () {
  var wanted = location.hash.replace("#", "");
  if (wanted.indexOf("tab-") !== 0 || !document.getElementById(wanted)) return;
  document.querySelectorAll('[data-a-tabs] [role="tab"]').forEach(function (tab) {
    tab.setAttribute("aria-selected", tab.getAttribute("aria-controls") === wanted ? "true" : "false");
  });
}());"""

# Served by Argus (/dashboard on its own address): open Argus links on that same address.
WB_LINK_JS = """(function () {
  if (location.pathname !== "/dashboard") return;
  document.querySelectorAll("a[data-wb]").forEach(function (a) {
    a.href = "/" + a.getAttribute("href").replace(/^[^#]*/, "");
  });
}());"""

FORM_JS = r"""(function () {
  "use strict";
  var list = document.querySelector("[data-a-tabs]");
  function showButtonsFor(tab) {
    var pane = tab && document.getElementById(tab.getAttribute("aria-controls"));
    var action = pane ? pane.getAttribute("data-action") : "";
    document.querySelectorAll(".action-bar [data-action]").forEach(function (button) {
      button.hidden = button.getAttribute("data-action") !== action;
    });
  }
  function remember() {
    var tab = list && list.querySelector('[role="tab"][aria-selected="true"]');
    if (tab) history.replaceState(null, "", "#" + tab.getAttribute("aria-controls"));
    showButtonsFor(tab);
  }
  function openRoadmap(id) {
    var doc = document.getElementById(typeof id === "string" ? id : "roadmap-doc");
    if (!doc) return;
    var url = URL.createObjectURL(new Blob([JSON.parse(doc.textContent)], { type: "text/html" }));
    window.open(url, "_blank", "noopener");
  }
  document.querySelectorAll("[data-roadmap-open]").forEach(function (button) {
    button.addEventListener("click", function () { openRoadmap(button.getAttribute("data-doc") || "roadmap-doc"); });
  });
  // Only the dashboard Argus serves (on the PC or in Devin Cloud) can start a session; a saved or attached copy cannot.
  var onArgus = /^https?:$/.test(location.protocol) && /^\/(dashboard|actions)$/.test(location.pathname);
  document.querySelectorAll("[data-roadmap-refresh]").forEach(function (button) {
    button.hidden = !onArgus;
    button.addEventListener("click", function () {
      if (!confirm("Rebuild the roadmap from Jira in Devin Cloud? /roadmap commits the new page to feature/devin-sdlc; the next Dashboard shows it.")) return;
      var win = window.open("", "_blank");
      button.disabled = true;
      fetch("/api/actions", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ skill: "product-roadmap", text: "", dry_run: false }) })
        .then(function (r) { return r.json(); })
        .then(function (run) {
          if (!run.id) throw new Error(run.error || "Argus did not start a session");
          if (win) { win.location = "/run/" + run.id; } else { location = "/run/" + run.id; }
          button.textContent = "Roadmap refresh started in Devin Cloud";
        })
        .catch(function (e) { if (win) win.close(); button.disabled = false; alert("Could not start /roadmap: " + e.message); });
    });
  });
  if (list) {
    list.addEventListener("click", function (event) {
      var tab = event.target.closest('[role="tab"]');
      var pane = tab && document.getElementById(tab.getAttribute("aria-controls"));
      var opener = pane && pane.querySelector("[data-roadmap-open]");
      if (opener) openRoadmap(opener.getAttribute("data-doc") || "roadmap-doc");
      setTimeout(remember, 0);
    });
    list.addEventListener("keydown", function () { setTimeout(remember, 0); });
    showButtonsFor(list.querySelector('[role="tab"][aria-selected="true"]'));
  }
  var toggle = document.getElementById("toggle-output");
  toggle.addEventListener("click", function () {
    var box = document.getElementById("answers");
    box.hidden = !box.hidden;
    toggle.textContent = box.hidden ? "Show block" : "Hide block";
  });
}());
(function () {
  "use strict";
  var questionKeys = %(question_keys)s;
  var delegateKeys = %(delegate_keys)s;
  var sessionIds = %(session_ids)s;
  var approvalKeys = %(approval_keys)s;
  function yamlValue(text) {
    text = (text || "").replace(/\r/g, "");
    if (text.indexOf("\n") === -1) return JSON.stringify(text);
    return "|\n" + text.split("\n").map(function (line) { return "    " + line; }).join("\n");
  }
  function show(lines) {
    document.getElementById("output").value = lines.join("\n") + "\n";
    if (window.sdlcSaveReady) window.sdlcSaveReady();
    document.getElementById("answers").hidden = false;
    var toggle = document.getElementById("toggle-output");
    toggle.hidden = false;
    toggle.textContent = "Hide block";
    document.getElementById("output").focus();
  }
  function value(selector) {
    var field = document.querySelector(selector);
    return field ? field.value.trim() : "";
  }
  function on(id, handler) {
    var button = document.getElementById(id);
    if (button) button.addEventListener("click", handler);
  }
  on("build-answers", function () {
    var lines = ["SDLC-DASHBOARD-ANSWERS v1"];
    questionKeys.forEach(function (key) {
      var text = value('[data-question-key="' + key + '"]');
      if (text) lines.push("- key: " + key, "  answer: " + yamlValue(text));
    });
    show(lines);
  });
  on("build-delegations", function () {
    var lines = ["SDLC-DASHBOARD-DELEGATIONS v1"];
    delegateKeys.forEach(function (key) {
      var to = value('[data-delegate-key="' + key + '"]');
      if (!to) return;
      lines.push("- key: " + key, "  to: " + to);
      var note = value('[data-delegate-note="' + key + '"]');
      if (note) lines.push("  note: " + yamlValue(note));
    });
    show(lines);
  });
  on("build-session-handovers", function () {
    var lines = ["SDLC-DASHBOARD-SESSION-HANDOVERS v1"];
    sessionIds.forEach(function (id) {
      var to = value('[data-session-to="' + id + '"]');
      if (!to) return;
      lines.push("- session: " + id, "  to: " + to);
      var note = value('[data-session-note="' + id + '"]');
      if (note) lines.push("  note: " + yamlValue(note));
    });
    show(lines);
  });
  on("close-sessions", function () {
    var ids = sessionIds.filter(function (id) {
      var box = document.querySelector('[data-session-close="' + id + '"]');
      return box && box.checked;
    });
    if (!ids.length) return;
    var lines = ["SDLC-DASHBOARD-SESSION-CLOSE v1"].concat(ids.map(function (id) { return "- session: " + id; }));
    function done(closed) {
      closed.forEach(function (id) {
        var box = document.querySelector('[data-session-close="' + id.replace("devin-", "") + '"]');
        var row = box && box.closest("tr");
        if (row) { row.style.opacity = "0.45"; box.disabled = true; box.checked = false; }
      });
    }
    if (!/^https?:$/.test(location.protocol)) { show(lines); return; }
    fetch("/api/sessions/close", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_ids: ids }) })
      .then(function (r) { if (!r.ok) throw new Error(r.statusText); return r.json(); })
      .then(function (j) {
        done(j.closed || []);
        if ((j.failed || []).length) show(["# Could not close these; paste this block into chat to try from there."]
          .concat(["SDLC-DASHBOARD-SESSION-CLOSE v1"], j.failed.map(function (f) { return "- session: " + f.session_id; })));
      })
      .catch(function () { show(lines); });
  });
  on("build-approvals", function () {
    var lines = ["SDLC-DASHBOARD-APPROVALS v1"];
    var problems = [];
    approvalKeys.forEach(function (key) {
      document.querySelectorAll('[data-approval-decision="' + key + '"]').forEach(function (field) {
        var item = field.getAttribute("data-item");
        var decision = field.value;
        if (!decision) return;
        var to = value('[data-approval-to="' + key + '"][data-item="' + item + '"]');
        var note = value('[data-approval-note="' + key + '"][data-item="' + item + '"]');
        if ((decision === "reject" || decision === "delegate" || decision === "approve-with-notes") && !note) {
          problems.push(key + " item " + item + ": a note is required to " + decision.replace(/-/g, " "));
          return;
        }
        if (decision === "delegate" && !to) {
          problems.push(key + " item " + item + ": pick who to send it to");
          return;
        }
        lines.push("- key: " + key, "  items: " + JSON.stringify(item), "  decision: " + decision);
        if (decision === "delegate") lines.push("  to: " + to);
        if (note) lines.push("  note: " + yamlValue(note));
      });
    });
    if (problems.length) { window.alert(problems.join("\n")); return; }
    show(lines);
  });
  on("build-observations", function () {
    var lines = ["SDLC-DASHBOARD-OBSERVATIONS v1"];
    document.querySelectorAll('[data-obs="story"]').forEach(function (field) {
      var row = field.getAttribute("data-row");
      function cell(name) { return value('[data-obs="' + name + '"][data-row="' + row + '"]'); }
      var story = field.value.trim();
      var title = cell("title");
      var detail = cell("detail");
      if (!story || !title || !detail) return;
      lines.push(
        "- story: " + story,
        "  kind: " + cell("kind"),
        "  severity: " + cell("severity"),
        "  environment: " + JSON.stringify(cell("environment")),
        "  title: " + yamlValue(title),
        "  detail: " + yamlValue(detail)
      );
    });
    show(lines);
  });
}());"""


def load_reads(path):
    """The Jira answers a nightly build saved with --save-reads ({url: answer}), or {} when there are none."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data.get("reads") or {} if isinstance(data, dict) else {}


def save_reads(path, reads):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path + ".tmp", "w", encoding="utf-8") as fh:
        json.dump({"saved_at": time.time(), "reads": reads}, fh, separators=(",", ":"), sort_keys=True)
    os.replace(path + ".tmp", path)


def build_all(out_dir, users=None, lens=None, reads=None, save_to=None):
    """Every roster person's dashboard, one file each (<jira user>.<lens>.html) in `out_dir`, reading each
    shared Jira query once. A person whose build fails keeps their last saved page. Writes nightly.json.
    `reads` starts from the Jira answers of a shared nightly build (a query it does not hold is read live);
    `save_to` writes every Jira answer this build used, for the other Argus copies to build from."""
    os.makedirs(out_dir, exist_ok=True)
    JiraClient.shared = dict(reads or {})
    started, built, failed = time.time(), [], {}
    try:
        for user in users or [p["jira_user"] for p in people().get("people") or [] if p.get("jira_user")]:
            try:
                ctx = build(argparse.Namespace(user=user, lens=lens, base=None, cache=None, sessions=None,
                                               team_sessions=None, capacity_sheet=None))
                path = os.path.join(out_dir, "%s.%s.html" % (ctx["username"], ctx["lens_id"]))
                with open(path + ".tmp", "w", encoding="utf-8") as fh:
                    fh.write(render(ctx))
                os.replace(path + ".tmp", path)
                built.append(os.path.basename(path))
            except (RuntimeError, OSError, ValueError, KeyError, yaml.YAMLError) as exc:
                failed[user] = str(exc)[:300]
        if save_to and built:
            save_reads(save_to, JiraClient.shared)
    finally:
        JiraClient.shared = None
    summary = {"started_at": started, "finished_at": time.time(), "built": built, "failed": failed}
    with open(os.path.join(out_dir, "nightly.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=1)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--user", help="Jira username or name fragment")
    parser.add_argument("--all", metavar="DIR",
                        help="build every roster person's dashboard into DIR (the nightly build in Argus)")
    parser.add_argument("--lens", help="force a role lens from .devin/rules/dashboard-roles.yaml")
    parser.add_argument("--base", help="base branch for the branch panels (default from the lens config)")
    parser.add_argument("--cache", help="offline JSON fixture")
    parser.add_argument("--reads", metavar="FILE",
                        help="with --all: build from the Jira answers a shared nightly build saved (misses read live)")
    parser.add_argument("--save-reads", metavar="FILE",
                        help="with --all: save every Jira answer the build used, for the other Argus copies")
    parser.add_argument(
        "--sessions",
        help="JSON list of the viewer's Devin sessions, written by /dashboard from devin_session_search",
    )
    parser.add_argument("--team-sessions",
                        help="JSON of the team's recent Devin Cloud sessions, written by Argus for the Team activity tab")
    parser.add_argument("--capacity-sheet", help="this sprint's capacity sheet (.xlsx) for the Scrum Master lens")
    parser.add_argument("-o", "--output", help="HTML output path")
    parser.add_argument("--actions", action="store_true",
                        help="Argus actions page: the same tabs with their Generate and Save buttons")
    args = parser.parse_args(argv)
    global DASHBOARD_READ_ONLY
    DASHBOARD_READ_ONLY = not args.actions
    if args.all:
        done = build_all(args.all, [args.user] if args.user else None, args.lens,
                         reads=load_reads(args.reads) if args.reads else None, save_to=args.save_reads)
        print("Built %d dashboards; %d failed." % (len(done["built"]), len(done["failed"])))
        for user, why in sorted(done["failed"].items()):
            print("  %s: %s" % (user, why), file=sys.stderr)
        return 0 if done["built"] or not done["failed"] else 1
    if not args.user:
        parser.error("--user is required (or --all DIR)")
    try:
        ctx = build(args)
        output = args.output or os.path.join(OUTPUT_ROOT, "%s-DASHBOARD.html" % ctx["username"])
        os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
        with open(output, "w", encoding="utf-8") as fh:
            fh.write(render(ctx))
        print("Dashboard for %s (%s) — roles: %s — lens: %s" % (
            ctx["display"], ctx["username"], ", ".join(ctx["roles"]), ctx["lens_id"]))
        print("Questions for me: %d; my questions: %d" % (len(ctx["questions"]), len(ctx["asked"])))
        print("Approvals awaiting me: %d" % len(ctx["approvals"]) if ctx["approvals"]
              else "No approvals awaiting me.")
        print("HTML: %s" % output)
        return 0
    except (RuntimeError, OSError, ValueError, yaml.YAMLError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
