#!/usr/bin/env python3
"""Reconcile the Acme Claims roster against Jira and against the routing configuration.

The roster (``.devin/rules/people.yaml``) is the operational source of truth for who is who.
Jira cannot be that source — Acme Claims's assignable-user search returns the whole Jira instance and
project-role configuration is denied to the service account — so Jira is used the other way
round: to confirm that the usernames in the roster still exist and are active, to fill in work
email addresses, and to spot people who are demonstrably working on Acme Claims but are missing from
the roster.

Run from anywhere:

    python3 sdlc/framework/tools/reconcile_roster.py               # report, live Jira
    python3 sdlc/framework/tools/reconcile_roster.py --offline     # config checks only
    python3 sdlc/framework/tools/reconcile_roster.py --write       # apply safe fixes
    python3 sdlc/framework/tools/reconcile_roster.py --activity-days 180

``--write`` only ever applies changes that cannot be wrong: a missing email that Jira holds for a
username already in the roster, and the ``last_reviewed`` date. Everything else — joiners,
leavers, a role that needs narrowing — is reported for a human to decide in the pull request.

Exit codes: 0 no drift, 1 drift found, 2 the run could not complete.
"""
import argparse
import datetime
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
JIRA = (os.environ.get("SDLC_SANDBOX_URL") or "https://jira.acme.example").rstrip("/") + "/rest"
PROJECT = "ACME"
PEOPLE_PATH = os.path.join(ROOT, ".devin", "rules", "people.yaml")
ROUTING_PATH = os.path.join(ROOT, ".devin", "rules", "role-routing.yaml")
GATES_PATH = os.path.join(ROOT, ".devin", "rules", "approval-gates.yaml")
LENS_PATH = os.path.join(ROOT, ".devin", "rules", "dashboard-roles.yaml")
SKILLS_DIR = os.path.join(ROOT, ".devin", "skills")
PLAYBOOKS_DIR = os.path.join(ROOT, "sdlc", "framework", "playbooks")
TOKEN_ENV = "ACME_JIRA_TOKEN"
SERVICE_ACCOUNT_PATTERN = re.compile(r"^(src|svc)|AD$|^jiralocaladmin$", re.IGNORECASE)
# Acme Claims spans several teams, so the unknown-assignee list can run to hundreds of names. Truncate it:
# a report nobody reads is worse than a shorter one that gets acted on.
JOINER_LIMIT = 25


class JiraClient:
    """Bearer-token Jira client. One pre-flight call, and no retry on 401/403."""

    def __init__(self):
        self.token = os.environ.get(TOKEN_ENV)
        if not self.token:
            raise RuntimeError("%s is not set — rerun with --offline to skip the Jira checks." % TOKEN_ENV)
        self.validated = False

    def get(self, path, **params):
        url = JIRA + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(
            url, headers={"Authorization": "Bearer " + self.token, "Accept": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, context=ssl._create_unverified_context(), timeout=120) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise RuntimeError(
                    "Jira returned %d. The service account token is invalid or the account is "
                    "locked; an admin must rotate or reset it. Not retrying." % exc.code
                ) from exc
            if exc.code == 404:
                return None
            raise

    def live(self, path, **params):
        if not self.validated:
            self.get("/api/2/myself")
            self.validated = True
        return self.get(path, **params)

    def user(self, username):
        return self.live("/api/2/user", username=username)

    def recent_participants(self, days):
        """Usernames assigned Acme Claims work inside the window.

        Assignee only, on purpose: anyone in the enterprise can report a Acme Claims issue, so reporters
        describe the customer base rather than the delivery team and drown the report in names.
        Narrowed to this team as well: project Acme Claims holds every Value Based Care team, and without
        the clause the report proposes adding a hundred people who work on other teams' boards.
        """
        clause = team_clause()
        jql = "project = %s%s AND updated >= -%dd ORDER BY updated DESC" % (
            PROJECT, (" AND " + clause) if clause else "", days
        )
        seen, start = {}, 0
        while True:
            page = self.live(
                "/api/2/search", jql=jql, startAt=start, maxResults=100, fields="assignee"
            ) or {}
            issues = page.get("issues") or []
            for issue in issues:
                person = (issue.get("fields") or {}).get("assignee") or {}
                name = person.get("name")
                if name:
                    seen.setdefault(name, person.get("displayName") or name)
            start += len(issues)
            if start >= int(page.get("total", 0)) or not issues:
                return seen


def team_clause():
    """The JQL clause narrowing Acme Claims to this team, from dashboard-roles.yaml `team.scope`."""
    return ((load_yaml(LENS_PATH, {}).get("team") or {}).get("scope") or "").strip()


def name_tokens(name):
    return {t for t in re.split(r"[^A-Za-z]+", (name or "").lower()) if len(t) > 2}


def same_person(roster_name, jira_display):
    """True when the two names share every meaningful token, in any order.

    Jira writes "Resource 27 [X]" where the roster writes "Resource 27", so the
    comparison ignores punctuation, order and the contractor marker. A single shared surname is not
    enough; every token of the shorter name must appear in the longer one.
    """
    left, right = name_tokens(roster_name), name_tokens(jira_display) - {"x"}
    if not left or not right:
        return False
    shorter, longer = sorted((left, right), key=len)
    return len(shorter) > 1 and shorter <= longer


def load_yaml(path, fallback):
    try:
        with open(path, encoding="utf-8") as handle:
            return yaml.safe_load(handle) or fallback
    except FileNotFoundError:
        return fallback


def gate_roles():
    roles = set()
    for gate in load_yaml(GATES_PATH, {}).get("gates", []) or []:
        if gate.get("required_role"):
            roles.add(gate["required_role"])
        for approver in gate.get("approvers", []) or []:
            if approver.get("role"):
                roles.add(approver["role"])
    return roles


def lens_roles():
    roles = set()
    for lens in (load_yaml(LENS_PATH, {}).get("lenses") or {}).values():
        roles.update(lens.get("roles") or [])
    return roles


def access_roles():
    roles = set()
    for area in (load_yaml(PEOPLE_PATH, {}).get("access") or {}).get("areas") or []:
        roles.update(area.get("roles") or [])
    return roles


def config_findings(people, routing):
    """Checks that need no Jira access: schema, vocabulary and cross-file consistency."""
    findings = []
    roles = routing.get("roles") or {}
    aliases = routing.get("role_aliases") or {}
    lenses = lens_roles()
    gates = gate_roles()
    areas = access_roles()
    seats = {role: [] for role in gates}

    for person in people:
        who = person.get("name") or person.get("jira_user") or "<unnamed>"
        for field in ("jira_user", "email", "devin_user_id", "primary_role", "roles"):
            if field not in person:
                findings.append(("schema", "%s: field '%s' is missing from the entry" % (who, field)))
        if not person.get("jira_user"):
            findings.append(("unresolved", "%s: no Jira username — cannot be matched to a gate" % who))
        if not person.get("email"):
            findings.append(("unresolved", "%s: no work email — cannot be matched from chat identity" % who))

        primary = person.get("primary_role")
        hats = [primary] + list(person.get("secondary_roles") or [])
        for hat in [h for h in hats if h]:
            if hat not in roles:
                findings.append(("vocabulary", "%s: role '%s' is not defined in role-routing.yaml" % (who, hat)))
        for hat in person.get("role_hints") or {}:
            if hat not in (person.get("secondary_roles") or []) and hat != primary:
                findings.append(
                    ("hints", "%s: role_hints names '%s', a hat this person does not hold" % (who, hat))
                )
        for role in person.get("roles") or []:
            if role not in gates and role not in lenses and role not in areas:
                findings.append(
                    ("vocabulary", "%s: gate role '%s' matches no gate, dashboard lens or access area" % (who, role))
                )
            seats.setdefault(role, []).append(who)

    for role, holders in sorted(seats.items()):
        if not holders:
            findings.append(("gap", "no one holds gate role '%s', but a gate requires it" % role))

    for name, role in sorted(roles.items()):
        if role.get("dashboard_lens") not in (load_yaml(LENS_PATH, {}).get("lenses") or {}):
            findings.append(("routing", "role '%s': dashboard_lens '%s' does not exist" % (name, role.get("dashboard_lens"))))
        for skill in (role.get("default_skills") or []) + (role.get("more_skills") or []):
            if not os.path.isfile(os.path.join(SKILLS_DIR, skill, "SKILL.md")):
                findings.append(("routing", "role '%s': default skill '/%s' is not installed" % (name, skill)))
        for playbook in role.get("default_playbooks") or []:
            if not os.path.isfile(os.path.join(PLAYBOOKS_DIR, playbook + ".md")):
                findings.append(("routing", "role '%s': default playbook '%s' does not exist" % (name, playbook)))
        for gate_role in role.get("gate_roles") or []:
            if gate_role not in gates:
                findings.append(("routing", "role '%s': gate_role '%s' signs no gate" % (name, gate_role)))
    for legacy, target in sorted(aliases.items()):
        if target not in roles:
            findings.append(("routing", "role_aliases: '%s' points at unknown role '%s'" % (legacy, target)))

    return findings


def jira_findings(client, people, activity_days, fixes):
    findings = []
    known = {p.get("jira_user") for p in people if p.get("jira_user")}

    for person in people:
        username = person.get("jira_user")
        if not username:
            continue
        who = person.get("name") or username
        details = client.user(username)
        if not details:
            findings.append(("leaver", "%s (%s): no such Jira user — left, or the username changed" % (who, username)))
            continue
        if not details.get("active"):
            findings.append(("leaver", "%s (%s): Jira account is inactive — confirm the person has left" % (who, username)))
        email = details.get("emailAddress")
        if email and not person.get("email"):
            fixes.append((username, "email", email))
        elif email and person.get("email") and email.lower() != str(person["email"]).lower():
            findings.append(
                ("email", "%s (%s): roster email %s, Jira holds %s" % (who, username, person["email"], email))
            )

    if not activity_days:
        return findings

    participants = {
        username: display
        for username, display in client.recent_participants(activity_days).items()
        if username not in known and not SERVICE_ACCOUNT_PATTERN.search(username)
    }

    for person in people:
        if person.get("jira_user"):
            continue
        who = person.get("name") or ""
        matches = [(u, d) for u, d in participants.items() if same_person(who, d)]
        if len(matches) == 1:
            username, display = matches[0]
            findings.append(
                ("candidate", "%s: looks like '%s' (%s), assigned Acme Claims work in the last %d days"
                 % (who, display, username, activity_days))
            )
            participants.pop(username, None)
        elif len(matches) > 1:
            findings.append(
                ("candidate", "%s: several Jira users could match (%s) — ask the person which is theirs"
                 % (who, ", ".join(sorted(u for u, _ in matches))))
            )

    for username, display in sorted(participants.items(), key=lambda kv: kv[1]):
        findings.append(
            ("joiner", "%s (%s): assigned Acme Claims work in the last %d days but absent from the roster"
             % (display, username, activity_days))
        )
    return findings


def apply_fixes(fixes, review_date):
    """Rewrite people.yaml in place, touching only the lines the fixes name."""
    with open(PEOPLE_PATH, encoding="utf-8") as handle:
        lines = handle.readlines()

    current = None
    for index, line in enumerate(lines):
        entry = re.match(r"^\s*-\s*jira_user:\s*(\S+)", line)
        if entry:
            current = entry.group(1).strip('"')
            continue
        for username, field, value in fixes:
            if current == username and re.match(r"^\s*%s:\s*null" % field, line):
                indent = line[: len(line) - len(line.lstrip())]
                lines[index] = "%s%s: %s\n" % (indent, field, value)

    for index, line in enumerate(lines):
        if re.match(r"^\s*last_reviewed:", line):
            indent = line[: len(line) - len(line.lstrip())]
            lines[index] = "%slast_reviewed: %s\n" % (indent, review_date)
            break

    with open(PEOPLE_PATH, "w", encoding="utf-8") as handle:
        handle.writelines(lines)


def reviewers(roster):
    """Roster owner first, then the backups, resolved to names where the roster knows them."""
    by_user = {p.get("jira_user"): p.get("name") for p in roster.get("people") or []}
    owner = roster.get("owner") or {}
    usernames = [owner.get("primary")] + list(owner.get("backups") or [])
    return [
        "%s (%s)" % (by_user[u], u) if by_user.get(u) else u for u in usernames if u
    ]


def report(findings, fixes, offline, roster):
    order = [
        "schema", "vocabulary", "hints", "routing", "unresolved", "candidate", "gap", "leaver",
        "joiner", "email",
    ]
    titles = {
        "schema": "Entries missing a field",
        "vocabulary": "Roles that are not in the vocabulary",
        "hints": "Hint keywords for hats the person does not hold",
        "routing": "Routing configuration that points at something missing",
        "unresolved": "Entries that cannot yet be matched to a person",
        "candidate": "Unresolved entries with a likely Jira user — confirm with the person",
        "gap": "Gate roles with nobody to sign them",
        "leaver": "People who look like leavers",
        "joiner": "People assigned Acme Claims work who are not in the roster",
        "email": "Email addresses that disagree with Jira",
    }
    grouped = {}
    for kind, message in findings:
        grouped.setdefault(kind, []).append(message)

    today = datetime.date.today().isoformat()
    print("# Acme Claims roster reconciliation — %s%s\n" % (today, " (offline: config checks only)" if offline else ""))
    if not findings and not fixes:
        print("No drift. The roster matches Jira and the routing configuration.")
        return
    for kind in order:
        if kind not in grouped:
            continue
        messages = sorted(grouped[kind])
        print("## %s (%d)\n" % (titles[kind], len(messages)))
        shown = messages[:JOINER_LIMIT] if kind == "joiner" else messages
        for message in shown:
            print("- %s" % message)
        if len(messages) > len(shown):
            print("- …and %d more. Acme Claims is a large project; narrow the window with --activity-days."
                  % (len(messages) - len(shown)))
        print()
    if fixes:
        print("## Safe fixes (%d) — applied with --write\n" % len(fixes))
        for username, field, value in fixes:
            print("- %s: %s → %s" % (username, field, value))
        print()
    named = reviewers(roster)
    print("Raise these as a pull request against `.devin/rules/people.yaml`.")
    if len(named) > 1:
        print("Reviewer: %s, or any of %s while they are away."
              % (named[0], ", ".join(named[1:])))
    elif named:
        print("Reviewer: %s." % named[0])
    print("See sdlc/framework/ROSTER-GOVERNANCE.md.")


def main():
    parser = argparse.ArgumentParser(description="Reconcile .devin/rules/people.yaml against Jira.")
    parser.add_argument("--offline", action="store_true", help="skip every Jira call")
    parser.add_argument("--write", action="store_true", help="apply the safe fixes to people.yaml")
    parser.add_argument(
        "--activity-days", type=int, default=90,
        help="how far back to look for Acme Claims participants missing from the roster (0 disables)",
    )
    args = parser.parse_args()

    roster = load_yaml(PEOPLE_PATH, None)
    if not roster or not roster.get("people"):
        print("cannot read %s" % PEOPLE_PATH, file=sys.stderr)
        return 2
    routing = load_yaml(ROUTING_PATH, None)
    if not routing:
        print("cannot read %s" % ROUTING_PATH, file=sys.stderr)
        return 2

    people = roster["people"]
    findings = config_findings(people, routing)
    fixes = []
    if not args.offline:
        try:
            findings += jira_findings(JiraClient(), people, args.activity_days, fixes)
        except RuntimeError as exc:
            print("Jira checks skipped: %s\n" % exc, file=sys.stderr)

    if args.write and fixes:
        apply_fixes(fixes, datetime.date.today().isoformat())

    report(findings, fixes, args.offline, roster)
    return 1 if findings or fixes else 0


if __name__ == "__main__":
    sys.exit(main())
