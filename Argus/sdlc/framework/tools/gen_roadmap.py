#!/usr/bin/env python3
"""Generate the Acme Claims delivery roadmap from Jira.

One row per epic owned by the UI team, one column per sprint, and in each cell the
stories that actually target that sprint — the phase they sit in (analysis, dev,
SIT, UAT, automation, release support), what they are, and how far along they are.
Replaces the hand-maintained roadmap spreadsheet, which carried the phase labels
but not the work behind them.

    python3 sdlc/framework/tools/gen_roadmap.py            # live Jira
    python3 sdlc/framework/tools/gen_roadmap.py --cache issues.json

Writes UI-DELIVERY-ROADMAP.html (the grid) and 05_UI_DELIVERY_ROADMAP.md (the same
content as prose and tables) under the Jira-derived knowledge base.

Jira access uses bearer auth with the token in $ACME_JIRA_TOKEN. The token is
validated once against /myself before anything else is fetched; a 401/403 stops the
run rather than retrying, because the service account locks after three failures.
"""
import argparse
import collections
import datetime
import html
import json
import os
import re
import ssl
import sys
import urllib.parse
import urllib.request

import yaml

import artifact_kit

JIRA = (os.environ.get("SDLC_SANDBOX_URL") or "https://jira.acme.example").rstrip("/") + "/rest"
PROJECT = "ACME"
BOARD = 247285
UI_TEAM = "Acme-Claims-Web"

F_SPRINT = "customfield_10002"
F_EPIC_LINK = "customfield_10010"
F_IT_TEAM = "customfield_10004"
F_POINTS = "customfield_10001"

FIELDS = ",".join([
    "summary", "issuetype", "status", "resolution", "resolutiondate", "assignee",
    "fixVersions", "labels", "duedate", "subtasks", "created", "updated",
    F_SPRINT, F_EPIC_LINK, F_IT_TEAM, F_POINTS,
])

SPRINT_NAME = re.compile(r"name=([^,]+),")
SPRINT_TOKEN = re.compile(r"(2\d)\.(\d)\.(\d)")
SPRINT_RANGE = re.compile(r"\((\d{1,2})/(\d{1,2})\s*-\s*(\d{1,2})/(\d{1,2})")
SPRINT_DAYS = 21

# Longest-running phase wins the cell colour; a story's own summary says which
# phase it is, because the team names stories "<what> - Dev", "... - SIT" and so on.
PHASES = [
    ("Release support", re.compile(r"pre-?deployment|deployment support|release support|post.?prod", re.I)),
    ("UAT", re.compile(r"\buat\b", re.I)),
    ("E2E", re.compile(r"\be2e\b|end.to.end", re.I)),
    ("Automation", re.compile(r"automation", re.I)),
    ("Regression", re.compile(r"regression", re.I)),
    ("SIT", re.compile(r"\bsit\b|\bqa\b|test(ing)? (execution|case)", re.I)),
    ("Analysis", re.compile(r"\banalysis\b|\bspike\b|requirement gathering|\bdesign\b|wireframe|\bpoc\b", re.I)),
    ("Dev", re.compile(r"\bdev\b|develop|implement|enhancement|front.?end|back.?end|\bapi\b|script|fix", re.I)),
]
PHASE_ORDER = ["Analysis", "Dev", "SIT", "Automation", "Regression", "E2E", "UAT", "Release support"]
DONE_STATUSES = {"closed", "done", "resolved", "ready for release", "released", "abandoned"}

# Defects and support items are raised against a story, not an epic, so they have no epic link
# to roll up to. They are real sprint load, so they get their own row at the bottom.
UNPARENTED = "(no epic)"
MD_STORY_LIMIT = 12


def _ctx():
    return ssl._create_unverified_context()


def _get(path, **params):
    token = os.environ.get("ACME_JIRA_TOKEN")
    if not token:
        sys.exit("ACME_JIRA_TOKEN is not set — cannot reach Jira. Use --cache to work offline.")
    url = JIRA + path
    if params:
        url += ("&" if "?" in path else "?") + urllib.parse.urlencode(params)
    request = urllib.request.Request(
        url, headers={"Authorization": "Bearer " + token, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, context=_ctx(), timeout=120) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            sys.exit("Jira returned %d. The service account token is invalid or locked; it must be "
                     "rotated or reset by an admin. Not retrying." % exc.code)
        raise


def fetch_issues():
    _get("/api/2/myself")
    jql = ('project = %s AND cf[12479] = "%s" '
           'AND (labels != Question OR labels is EMPTY) ORDER BY key ASC') % (PROJECT, UI_TEAM)
    issues, start = [], 0
    while True:
        page = _get("/api/2/search", jql=jql, startAt=start, maxResults=100, fields=FIELDS)
        issues += page["issues"]
        start += len(page["issues"])
        if not page["issues"] or start >= page["total"]:
            return issues


def fetch_sprints():
    sprints, start = [], 0
    while True:
        page = _get("/agile/1.0/board/%d/sprint" % BOARD, startAt=start, maxResults=50)
        sprints += page["values"]
        start += len(page["values"])
        if page.get("isLast", True) or not page["values"]:
            return sprints


def fetch_epics(keys):
    """Some rows hang off an epic the UI team does not own, so it was not in the team query."""
    keys = sorted(k for k in keys if re.fullmatch(r"%s-\d+" % PROJECT, k or ""))
    if not keys:
        return []
    jql = "key in (%s)" % ", ".join(keys)
    return _get("/api/2/search", jql=jql, maxResults=len(keys), fields=FIELDS)["issues"]


def token_of(name):
    match = SPRINT_TOKEN.search(name or "")
    return ".".join(match.groups()) if match else None


def sort_key(token):
    year, quarter, seq = (int(part) for part in token.split("."))
    return (year, quarter, seq)


def dates_from_name(name, year):
    """Future sprints carry no dates in Jira, but the team writes the range into the name."""
    match = SPRINT_RANGE.search(name or "")
    if not match:
        return None, None
    m1, d1, m2, d2 = (int(part) for part in match.groups())
    start = datetime.date(year, m1, d1)
    end = datetime.date(year + 1 if m2 < m1 else year, m2, d2)
    return start, end


def build_columns(sprints, issue_tokens, back, ahead):
    """Sprint columns, oldest first, centred on the active sprint.

    Sprints exist in Jira only a few iterations ahead, so the far end of the roadmap is
    projected on the team's 21-day cadence and marked as such.
    """
    known, active = {}, None
    for sprint in sprints:
        token = token_of(sprint.get("name"))
        if not token:
            continue
        year = 2000 + int(token.split(".")[0])
        start = sprint.get("startDate") or ""
        end = sprint.get("endDate") or ""
        start = datetime.date.fromisoformat(start[:10]) if start else None
        end = datetime.date.fromisoformat(end[:10]) if end else None
        if not start:
            start, end = dates_from_name(sprint.get("name"), year)
        current = known.get(token)
        if not current or (current[0] is None and start):
            known[token] = (start, end, sprint.get("state"))
        if sprint.get("state") == "active":
            active = token

    for token in issue_tokens:
        known.setdefault(token, (None, None, "closed"))

    ordered = sorted(known, key=sort_key)
    if active is None:
        active = ordered[-1]
    centre = ordered.index(active)
    window = ordered[max(0, centre - back):centre + ahead + 1]

    columns = []
    for token in window:
        start, end, state = known[token]
        columns.append({"token": token, "start": start, "end": end, "state": state,
                        "active": token == active, "projected": False})

    # Extend with projected sprints until the horizon is `ahead` columns past the active one.
    last = columns[-1]
    while len(columns) - columns.index(next(c for c in columns if c["active"])) <= ahead:
        year, quarter, seq = sort_key(last["token"])
        seq, quarter = (seq + 1, quarter) if seq < 5 else (1, quarter + 1)
        if quarter > 4:
            quarter, year = 1, year + 1
        token = "%d.%d.%d" % (year, quarter, seq)
        start = (last["end"] + datetime.timedelta(days=1)) if last["end"] else None
        end = (start + datetime.timedelta(days=SPRINT_DAYS - 1)) if start else None
        last = {"token": token, "start": start, "end": end, "state": "projected",
                "active": False, "projected": True}
        columns.append(last)
    for column in columns:
        column["past"] = sort_key(column["token"]) < sort_key(active)
    return columns, active


def sprint_tokens(fields):
    out = set()
    for raw in fields.get(F_SPRINT) or []:
        match = SPRINT_NAME.search(raw)
        if match:
            token = token_of(match.group(1))
            if token:
                out.add(token)
    return out


def phase_of(summary):
    for name, pattern in PHASES:
        if pattern.search(summary or ""):
            return name
    return None


PHASE_TAG = (r"(dev only|dev|sit/uat|sit|uat|e2e|prod|automation testing|automation|"
             r"regression testing|regression|analysis|spike|poc)")
PHASE_TRAILING = re.compile(r"\s*[-–—:]?\s*\b%s\b\s*$" % PHASE_TAG, re.I)
PHASE_LEADING = re.compile(r"^\s*\b%s\b\s*[-–—:]+\s*" % PHASE_TAG, re.I)


def strip_phase(summary):
    """The phase already labels the cell, so "SIT- Contract sync-up - Part 2 - Dev" is about
    the contract sync-up."""
    text = (summary or "").strip()
    for _ in range(2):
        stripped = PHASE_LEADING.sub("", PHASE_TRAILING.sub("", text)).strip(" -–—:")
        if not stripped:  # the summary was nothing but a phase, e.g. "SIT- Regression Testing"
            break
        text = stripped
    return re.sub(r"\s+", " ", text) or (summary or "").strip()


# A roadmap cell has room for a label, not a Jira title, so each story is reduced to the
# subject it is about. Most specific pattern wins, so "contract bulk upload" reads as
# "Bulk upload" rather than "Contract".
TOPICS = [
    (r"bulk\s*upload|mass upload", "Bulk upload"),
    (r"sync.?up|synchroni", "Sync-up"),
    (r"provider group|\bpg\b", "Provider grouping"),
    (r"tin[\s/_-]*npi|substitution", "TIN/NPI"),
    (r"contract template", "Contract template"),
    (r"lock|release contract|unlock", "Lock & release"),
    (r"approv", "Approvals"),
    (r"attribut", "Attribution"),
    (r"scorecard", "Scorecard"),
    (r"definition", "Definitions"),
    (r"rerun|re-run", "Rerun"),
    (r"financial|payment|settle|ssav|savings", "Financial"),
    (r"member", "Member data"),
    (r"eligib", "Eligibility"),
    (r"\beoc\b|episode", "EOC"),
    (r"pcmh|\bthl\b|tenncare", "PCMH/THL"),
    (r"\bchf\b", "CHF"),
    (r"\bmsk\b", "ProgramA"),
    (r"\bsmi\b", "ProgramB"),
    (r"\bomh\b|oncology", "ProgramC"),
    (r"maternity", "Maternity"),
    (r"carebridge", "Carebridge"),
    (r"magnolia", "Magnolia"),
    (r"user access|\brole\b|\bad group|entitle|permission", "User access"),
    (r"dashboard|my queue", "Dashboard"),
    (r"\bfilter|search", "Search & filter"),
    (r"drop.?down|dropdown", "Dropdown"),
    (r"stepper", "Stepper"),
    (r"pop.?up|modal", "Popup"),
    (r"\bgrid\b|column (sort|filter|header|order)|pagination", "Grid"),
    (r"export|download", "Export"),
    (r"\bemail|notification", "Notifications"),
    (r"audit|history", "Audit trail"),
    (r"valid(at|ity)|mandatory", "Validation"),
    (r"\bsave\b|persist", "Save"),
    (r"\bedit\b|update functionality", "Edit"),
    (r"\bdelete\b|remove", "Delete"),
    (r"upgrade|version bump|library", "Upgrade"),
    (r"tech debt|refactor|clean.?up", "Tech debt"),
    (r"performance|slow|timeout", "Performance"),
    (r"training|documentation|user manual", "Documentation"),
    (r"onboard|setup|foundational|configuration|config", "Configuration"),
    (r"\bapi\b|endpoint|service", "API"),
    (r"\bscript\b|\bjob\b|\betl\b", "Script"),
    (r"contract", "Contract"),
]
TOPICS = [(re.compile(pattern, re.I), label) for pattern, label in TOPICS]

# Said alongside the topic when both are present: "Bulk upload · API".
QUALIFIERS = [
    (re.compile(r"front.?end|\bui\b screen|screen", re.I), "screen"),
    (re.compile(r"\bapi\b|back.?end|endpoint", re.I), "API"),
    (re.compile(r"\bscript\b|\bjob\b", re.I), "script"),
]
NOISE = re.compile(
    r"\b(the|a|an|and|or|for|from|with|to|of|in|on|is|are|not|able|unable|issue|issues|error|"
    r"errors|screen|screens|page|pages|functionality|function|feature|support|changes|change|"
    r"new|acme|\bui\b|user|story|task|defect|when|after|before|should|need|needs|please|"
    r"implement|implementation|development|develop|create|creation|add|adding|enhancement)\b",
    re.I)


def essence(summary):
    """Two words at most, saying what the story is about, for a roadmap cell."""
    text = strip_phase(summary)
    topic = next((label for pattern, label in TOPICS if pattern.search(text)), None)
    qualifier = next((label for pattern, label in QUALIFIERS if pattern.search(text)), "")
    if topic:
        return topic, ("" if qualifier.lower() in topic.lower() else qualifier)
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z/&-]+", text) if not NOISE.fullmatch(w)]
    if not words:
        return text[:22] or "Story", ""
    label = " ".join(words[:2])
    return label[:1].upper() + label[1:], ""


def is_done(fields):
    return (fields["status"]["name"] or "").lower() in DONE_STATUSES


def collect(issues):
    by_key = {issue["key"]: issue for issue in issues}
    parent = {}
    for issue in issues:
        for sub in issue["fields"].get("subtasks") or []:
            parent[sub["key"]] = issue["key"]

    epics = {k: i for k, i in by_key.items() if i["fields"]["issuetype"]["name"] == "Epic"}
    cells = collections.defaultdict(lambda: collections.defaultdict(
        lambda: {"stories": [], "phases": collections.Counter(), "done": 0, "points": 0.0,
                 "releases": collections.defaultdict(list)}))
    seen_tokens = set()

    for issue in issues:
        fields = issue["fields"]
        kind = fields["issuetype"]["name"]
        if kind == "Epic":
            continue
        tokens = sprint_tokens(fields)
        seen_tokens |= tokens
        if not tokens:
            continue
        epic = fields.get(F_EPIC_LINK)
        if not epic:
            owner = parent.get(issue["key"])
            epic = by_key.get(owner, {}).get("fields", {}).get(F_EPIC_LINK) if owner else None
        epic = epic or UNPARENTED
        phase = phase_of(fields["summary"])
        for token in tokens:
            cell = cells[epic][token]
            cell["phases"][phase or "Dev"] += 1
            if kind == "Sub-task":
                continue
            topic, qualifier = essence(fields["summary"])
            cell["stories"].append({
                "key": issue["key"],
                "title": strip_phase(fields["summary"]),
                "topic": topic,
                "qualifier": qualifier,
                "phase": phase,
                "status": fields["status"]["name"],
                "done": is_done(fields),
                "type": kind,
            })
            for date in version_dates(fields):
                cell["releases"][date].append(issue["key"])
            if is_done(fields):
                cell["done"] += 1
            cell["points"] += float(fields.get(F_POINTS) or 0)
    return epics, cells, seen_tokens, by_key


def version_dates(fields):
    """Fix-version names in this project are release dates. Placeholder versions ("TBD - UI")
    carry a filler date, so they say nothing about when the work ships and are dropped."""
    out = set()
    for version in fields.get("fixVersions") or []:
        if str(version.get("name") or "").strip().upper().startswith("TBD"):
            continue
        try:
            out.add(datetime.date.fromisoformat(
                str(version.get("releaseDate") or version.get("name"))[:10]))
        except ValueError:
            continue
    return out


def epic_of_map(issues, by_key):
    parent = {}
    for issue in issues:
        for sub in issue["fields"].get("subtasks") or []:
            parent[sub["key"]] = issue["key"]
    out = {}
    for issue in issues:
        fields = issue["fields"]
        if fields["issuetype"]["name"] == "Epic":
            out[issue["key"]] = issue["key"]
            continue
        epic = fields.get(F_EPIC_LINK)
        if not epic:
            owner = parent.get(issue["key"])
            epic = by_key.get(owner, {}).get("fields", {}).get(F_EPIC_LINK) if owner else None
        if epic:
            out[issue["key"]] = epic
    return out


def describe_row(epic_key, epic):
    if epic_key == UNPARENTED:
        return "Defects and support items raised against stories, not epics"
    if epic:
        return epic["fields"]["summary"]
    return "Epic owned outside the UI team"


def group_stories(stories):
    """Three stories about the scorecard are one line reading "Scorecard ×3", not three
    identical lines. Open work sorts first, since that is what planning is about."""
    groups = collections.OrderedDict()
    for story in sorted(stories, key=lambda s: (s["done"], s["key"])):
        key = (story["topic"], story["qualifier"])
        group = groups.setdefault(key, {
            "label": story["topic"], "qualifier": story["qualifier"],
            "keys": [], "titles": [], "open": 0,
        })
        group["keys"].append(story["key"])
        group["titles"].append("%s — %s" % (story["key"], story["title"]))
        group["open"] += 0 if story["done"] else 1
    return list(groups.values())


def cell_stories(cell, limit=8):
    """The stories themselves, open first, for a grid cell that names real work."""
    stories = sorted(cell["stories"], key=lambda s: (s["done"], s["key"]))
    phases = [p for p in PHASE_ORDER if cell["phases"].get(p)]
    return phases, stories[:limit], stories[limit:]


def cell_summary(cell, limit=6):
    """Open work first, since that is what a planning conversation is about."""
    phases = [p for p in PHASE_ORDER if cell["phases"].get(p)]
    groups = group_stories(cell["stories"])
    return phases, groups[:limit], groups[limit:]


JIRA_BROWSE = "https://jira.acme.example/browse/"
PLAN_PATH = os.path.join("sdlc", "framework", "context", "roadmap", "year-plan.yaml")

# Plan statuses, in the order they are shown. The third value is the colour the team's
# spreadsheet uses for the same thing, so the legend can say "orange on the sheet".
STATUSES = [
    ("delivered", "Delivered", "white"),
    ("this_year", "Due in %(plan_year)s", "orange"),
    ("next_year", "Pushed to %(next_year)s", "yellow"),
    ("unknown", "Year not set", "no colour"),
]
STATUS_LABEL = {key: label for key, label, _ in STATUSES}
SHEET_COLOUR = {key: colour for key, _, colour in STATUSES}

esc = html.escape


def jira_link(key):
    return '<a href="%s%s">%s</a>' % (JIRA_BROWSE, esc(key), esc(key))


# ---------------------------------------------------------------- year plan (hand-maintained)

def load_plan(path):
    """The year plan is a YAML file the team edits by hand; missing file means no plan tabs."""
    if not path or not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        plan = yaml.safe_load(fh) or {}
    plan.setdefault("plan_year", datetime.date.today().year)
    plan.setdefault("next_year", plan["plan_year"] + 1)
    for section in ("foundational", "unsized", "open_questions", "programme_windows"):
        plan.setdefault(section, [])
    plan.setdefault("speciality", {"capabilities": [], "programs": []})
    return plan


def status_label(plan, status):
    return STATUS_LABEL.get(status, status) % plan


def story_total(story):
    points = story.get("points") or {}
    return sum(v for v in points.values() if isinstance(v, (int, float)))


def plan_totals(plan):
    """Foundational points by status, and the same for speciality programme totals."""
    foundational = collections.Counter()
    for capability in plan["foundational"]:
        for story in capability["stories"]:
            if "points" in story:
                foundational[story.get("status", "unknown")] += story_total(story)
    speciality = collections.Counter()
    for program in plan["speciality"].get("programs", []):
        if program.get("total_points") is not None:
            speciality[program.get("status", "unknown")] += program["total_points"]
    return foundational, speciality


def capability_totals(plan):
    rows = []
    for capability in plan["foundational"]:
        by_status = collections.Counter()
        unsized = 0
        for story in capability["stories"]:
            if "points" in story:
                by_status[story.get("status", "unknown")] += story_total(story)
            else:
                unsized += 1
        rows.append((capability["capability"], by_status, unsized))
    return rows


def jira_cell(keys, epics, cells):
    """What Jira says about the epics a plan row points at; a dash when it points at none."""
    if not keys:
        return '<span class="muted">—</span>'
    parts = []
    for key in keys:
        epic = epics.get(key)
        stories = sum(len(c["stories"]) for c in cells.get(key, {}).values())
        if epic:
            parts.append("%s <span class=\"muted\">%s · %d stories in sprints</span>" % (
                jira_link(key), esc(epic["fields"]["status"]["name"]), stories))
        else:
            parts.append("%s <span class=\"muted\">not in the UI team's epics</span>" % jira_link(key))
    return "<br>".join(parts)


def render_legend(plan, sheet=False):
    items = []
    for key, _, colour in STATUSES:
        note = ' <span class="muted">(%s on the sheet)</span>' % esc(colour) if sheet else ""
        items.append('<span class="a-chip" data-plan="%s"><span class="a-dot"></span>%s%s</span>'
                     % (key, esc(status_label(plan, key)), note))
    return '<p class="legend">%s</p>' % "".join(items)


def render_stack(plan, by_status, scale):
    """One horizontal bar split by status; widths are points over the largest row."""
    total = sum(by_status.values())
    if not total or not scale:
        return '<span class="stack stack--empty"></span>'
    spans = "".join(
        '<span class="stack__seg" data-plan="%s" style="width:%.1f%%" title="%s: %d points"></span>'
        % (key, 100.0 * by_status[key] / scale, esc(status_label(plan, key)), by_status[key])
        for key, _, _ in STATUSES if by_status.get(key))
    return '<span class="stack">%s</span>' % spans


def render_plan_summary(plan, epics, cells):
    foundational, speciality = plan_totals(plan)
    unsized_count = len(plan["unsized"]) + sum(
        1 for c in plan["foundational"] for s in c["stories"] if "points" not in s)
    velocity = plan.get("velocity_points_per_sprint")

    metrics = []
    for key, _, _ in STATUSES:
        points = foundational[key] + speciality[key]
        if not points and key == "unknown":
            continue
        metrics.append(
            '<div class="a-metric" data-plan="%s"><div class="a-metric__label"><span class="a-dot"></span> %s</div>'
            '<div class="a-metric__value">%d</div><div class="a-metric__delta">foundational %d · speciality %d%s</div></div>'
            % (key, esc(status_label(plan, key)), points, foundational[key], speciality[key],
               " · %.1f sprints at %d/sprint" % (points / velocity, velocity) if velocity and points else ""))
    metrics.append(
        '<div class="a-metric" data-plan="unknown"><div class="a-metric__label"><span class="a-dot"></span> Not sized</div>'
        '<div class="a-metric__value">%d</div><div class="a-metric__delta">items on the plan with no points</div></div>'
        % unsized_count)

    rows = capability_totals(plan)
    program_rows = [(p["name"], collections.Counter({p.get("status", "unknown"): p["total_points"]}), 0)
                    for p in plan["speciality"].get("programs", []) if p.get("total_points") is not None]
    scale = max([sum(b.values()) for _, b, _ in rows + program_rows] or [1])

    def bar_rows(items):
        out = []
        for name, by_status, unsized in items:
            total = sum(by_status.values())
            out.append('<div class="a-bars__row"><span>%s</span>%s<span class="a-bars__value">%d%s</span></div>' % (
                esc(name), render_stack(plan, by_status, scale), total,
                " · %d unsized" % unsized if unsized else ""))
        return ('<p class="muted">Bar length is points, against the largest row (%d points).</p>' % scale
                + "".join(out)) if out else ""

    unsized_rows = "".join(
        '<tr data-plan="%s"><td>%s</td><td><span class="a-chip" data-plan="%s"><span class="a-dot"></span>%s</span></td>'
        '<td>%s%s</td></tr>' % (
            esc(item.get("status", "unknown")), esc(item["name"]), esc(item.get("status", "unknown")),
            esc(status_label(plan, item.get("status", "unknown"))), esc(item.get("note", "")),
            ' <span class="muted">target %s%s</span>' % (
                esc(str(item["target"])), "" if item.get("target_confirmed", True) else ", year to confirm")
            if item.get("target") else "")
        for item in plan["unsized"])

    return (
        '<p class="a-section__note">What the year holds and where it stands: work delivered, work still due '
        'in %(year)d, and work pushed into %(next)d. Points are story + SIT + UAT per item as sized on the '
        'team\'s sheet; nothing here is estimated by the generator. Items without points are listed, not guessed.</p>'
        '%(legend)s'
        '<div class="metrics">%(metrics)s</div>'
        '<h3>Foundational capabilities</h3><div class="a-bars">%(found)s</div>'
        '<h3>Speciality risk programmes</h3><div class="a-bars">%(spec)s</div>'
        '<h3>Committed but not sized</h3>'
        '<div class="a-table-scroll"><table class="a-table"><thead><tr><th>Work</th><th>Status</th><th>Note</th></tr></thead>'
        '<tbody>%(unsized)s</tbody></table></div>'
    ) % {
        "year": plan["plan_year"], "next": plan["next_year"], "legend": render_legend(plan),
        "metrics": "".join(metrics), "found": bar_rows(rows), "spec": bar_rows(program_rows),
        "unsized": unsized_rows or '<tr><td colspan="3" class="muted">Everything on the plan is sized.</td></tr>',
    }


def render_foundational(plan, epics, cells):
    body = []
    for capability in plan["foundational"]:
        first = True
        for story in capability["stories"]:
            status = story.get("status", "unknown")
            points = story.get("points") or {}
            body.append(
                '<tr data-plan="%s">%s<td>%s</td><td class="num">%s</td><td class="num">%s</td><td class="num">%s</td>'
                '<td class="num"><b>%s</b></td><td><span class="a-chip" data-plan="%s"><span class="a-dot"></span>%s</span></td>'
                '<td>%s</td></tr>' % (
                    esc(status),
                    '<th scope="row" rowspan="%d">%s</th>' % (len(capability["stories"]), esc(capability["capability"]))
                    if first else "",
                    esc(story["name"]),
                    points.get("story", "—"), points.get("sit", "—"), points.get("uat", "—"),
                    story_total(story) if points else "not sized",
                    esc(status), esc(status_label(plan, status)),
                    jira_cell(story.get("jira") or [], epics, cells)))
            first = False
    foundational, _ = plan_totals(plan)
    total = sum(foundational.values())
    velocity = plan.get("velocity_points_per_sprint")
    foot = " · ".join("%s %d" % (status_label(plan, k), foundational[k]) for k, _, _ in STATUSES if foundational.get(k))
    return (
        '<p class="a-section__note">Every foundational story on the plan with its points per layer. '
        'Total %d points (%s)%s. The Jira column fills in when a row names its epic key in the plan file.</p>'
        '%s<div class="a-table-scroll"><table class="a-table plan-table"><thead><tr><th>Capability</th><th>Story</th>'
        '<th class="num">Dev</th><th class="num">SIT</th><th class="num">UAT</th><th class="num">Total</th><th>Status</th><th>Jira</th>'
        '</tr></thead><tbody>%s</tbody></table></div>'
    ) % (total, foot, " — %.1f sprints at %d points a sprint" % (total / velocity, velocity) if velocity else "",
         render_legend(plan), "".join(body))


def render_speciality(plan, epics, cells):
    spec = plan["speciality"]
    caps = spec.get("capabilities", [])
    body = []
    for program in spec.get("programs", []):
        status = program.get("status", "unknown")
        breakdown = program.get("breakdown")
        cells_html = "".join(
            '<td class="num">%s</td>' % ("—" if v is None else v)
            for v in (breakdown if breakdown else [None] * len(caps)))
        total = program.get("total_points")
        body.append(
            '<tr data-plan="%s"><th scope="row">%s</th>%s<td class="num"><b>%s</b></td>'
            '<td><span class="a-chip" data-plan="%s"><span class="a-dot"></span>%s</span></td><td>%s</td></tr>' % (
                esc(status), esc(program["name"]), cells_html,
                "no total on the sheet" if total is None else total,
                esc(status), esc(status_label(plan, status)),
                jira_cell(program.get("jira") or [], epics, cells)))
    _, speciality = plan_totals(plan)
    total = sum(speciality.values())
    velocity = plan.get("velocity_points_per_sprint")
    head = "".join("<th class=\"num\">%s</th>" % esc(c) for c in caps)
    return (
        '<p class="a-section__note">Speciality risk programmes: total points per programme and, where the sheet has '
        'one, the split by capability. Programme totals add up to %d points%s. A dash means the sheet had no number, '
        'not zero.</p>%s<div class="a-table-scroll"><table class="a-table plan-table"><thead><tr><th>Programme</th>%s'
        '<th class="num">Total</th><th>Status</th><th>Jira</th></tr></thead><tbody>%s</tbody></table></div>'
    ) % (total, " — %.1f sprints at %d a sprint" % (total / velocity, velocity) if velocity else "",
         render_legend(plan), head, "".join(body))


def render_windows(plan):
    blocks = []
    for block in plan["programme_windows"]:
        head = "".join("<th>%s</th>" % esc(str(c)) for c in block.get("columns", []))
        body = "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % esc(str(v)) for v in row) for row in block.get("rows", []))
        team = ' <span class="muted">%s</span>' % esc(block["team"]) if block.get("team") else ""
        blocks.append('<h3>%s%s</h3><div class="a-table-scroll"><table class="a-table"><thead><tr>%s</tr></thead>'
                      '<tbody>%s</tbody></table></div>' % (esc(block["program"]), team, head, body))
    return ('<p class="a-section__note">Programme delivery windows and handover dates, copied from the planning '
            'sheet exactly as written. Whether they are current is one of the open questions on the Sources tab.</p>'
            + "".join(blocks))


def render_sources(plan, plan_path, epics, cells, rows, generated):
    referenced = set()
    if plan:
        for capability in plan["foundational"]:
            for story in capability["stories"]:
                referenced.update(story.get("jira") or [])
        for program in plan["speciality"].get("programs", []):
            referenced.update(program.get("jira") or [])
        for item in plan["unsized"]:
            referenced.update(item.get("jira") or [])
    unlinked = [r for r in rows if r["key"] != UNPARENTED and r["key"] not in referenced]

    parts = ['<h3>Where each tab comes from</h3><dl class="a-meta-list">'
             '<dt>Sprint grid, Not in a sprint</dt><dd>Live Jira, project %s, epics whose IT Team is %s, read %s. '
             'Story keys, sprints, statuses and fix versions are Jira fields. The phase label on a cell comes from '
             'the suffix the team puts on story summaries, and columns past what Jira holds are projected on the '
             '21-day cadence — both are inferred, and marked so.</dd>' % (esc(PROJECT), esc(UI_TEAM), esc(generated))]
    if plan:
        parts.append('<dt>Year plan, Foundational, Speciality</dt><dd>The hand-maintained plan file '
                     '<code>%s</code>%s. Nothing on those tabs is computed from Jira; edit the file and re-run to change them.</dd>'
                     % (esc(plan_path), " — %s" % esc(plan["source"]) if plan.get("source") else ""))
    parts.append("</dl>")

    if plan and plan["open_questions"]:
        items = "".join('<li>%s <span class="muted">— %s</span></li>' % (esc(q["question"]), esc(q.get("owner", "owner not set")))
                        for q in plan["open_questions"])
        parts.append('<div class="a-callout a-callout--decision"><p class="a-callout__title">Open questions the plan '
                     'still needs answered</p><ol>%s</ol></div>' % items)
    if plan:
        assumed = [i for i in plan["unsized"] if i.get("target") and not i.get("target_confirmed", True)]
        if assumed:
            parts.append('<div class="a-callout"><p class="a-callout__title">Assumptions</p><ul>%s</ul></div>' % "".join(
                '<li>%s: target %s is read as %s — the note said only "%s". If wrong, the item moves to the other year.</li>'
                % (esc(i["name"]), esc(str(i["target"])), esc(status_label(plan, i.get("status", "unknown"))),
                   esc(i.get("note", ""))) for i in assumed))
    if plan and unlinked:
        parts.append('<h3>Jira epics in the sprint grid that no plan row points at</h3>'
                     '<p class="a-section__note">Add the key to the matching row\'s <code>jira:</code> list in the plan '
                     'file and the Jira column fills in. Left as is, these are work in flight that the funding view '
                     'does not name.</p><ul class="plain">%s</ul>' % "".join(
                         '<li>%s %s <span class="muted">%s</span></li>' % (jira_link(r["key"]), esc(r["summary"]), esc(r["status"]))
                         for r in unlinked))
    return "".join(parts)


# ---------------------------------------------------------------- sprint grid (Jira)

def render_unscheduled_html(unscheduled):
    if not unscheduled:
        return '<p class="a-empty">Every open UI epic has at least one story in a sprint.</p>'
    items = "".join(
        '<li>%s %s <span class="muted">%s</span></li>'
        % (jira_link(key), esc(epic["fields"]["summary"]), esc(epic["fields"]["status"]["name"]))
        for key, epic in unscheduled)
    return ('<p class="a-section__note">Open UI epics with nothing in a sprint yet — planned work that has not '
            'been pulled into an iteration, so it has no column on the sprint grid.</p><ul class="plain">%s</ul>' % items)


def render_grid(rows, columns, active, counts):
    head = []
    for column in columns:
        label = column["token"]
        if column["start"] and column["end"]:
            dates = "%d/%d–%d/%d" % (column["start"].month, column["start"].day,
                                     column["end"].month, column["end"].day)
        else:
            dates = "&nbsp;"
        cls = " ".join(filter(None, [
            "active" if column["active"] else "",
            "projected" if column["projected"] else "",
            "past collapsed" if column["past"] else "",
        ]))
        toggle = ('<button class="tg" type="button" data-toggle="%s" aria-label="Expand %s">+</button>'
                  % (esc(label), esc(label))) if column["past"] else ""
        head.append('<th class="%s" data-col="%s">%s<span class="tok">%s</span>'
                    '<span class="dt">%s</span></th>'
                    % (cls, esc(label), toggle, esc(label), dates))

    body = []
    for row in rows:
        cells = []
        for column in columns:
            cell = row["cells"].get(column["token"])
            marker = row["releases"].get(column["token"])
            extra_cls = "".join([" projected" if column["projected"] else "",
                                 " past collapsed" if column["past"] else ""])
            if not cell and not marker:
                cells.append('<td class="empty%s" data-col="%s"></td>' % (extra_cls, esc(column["token"])))
                continue
            parts = []
            if marker:
                parts.append('<div class="rel" title="%s">Ships %d/%d</div>' % (
                    esc("Fix version %s on %s" % (marker.isoformat(), ", ".join(sorted(cell["releases"][marker])))),
                    marker.month, marker.day))
            if cell:
                phases, stories, extra = cell_stories(cell)
                parts.append('<div class="ph">%s</div>' % esc(" · ".join(phases) or "Dev"))
                for story in stories:
                    parts.append(
                        '<div class="st%s" title="%s">%s%s<span class="ti">%s</span></div>' % (
                            "" if not story["done"] else " ok",
                            esc("%s — %s (%s)" % (story["key"], story["title"], story["status"])),
                            jira_link(story["key"]),
                            ' <span class="ph2">%s</span>' % esc(story["phase"]) if story["phase"] else "",
                            esc(story["title"])))
                if extra:
                    parts.append('<div class="more" title="%s">+%d more: %s</div>' % (
                        esc("; ".join("%s — %s" % (s["key"], s["title"]) for s in extra)),
                        len(extra), esc(", ".join(s["key"] for s in extra))))
                parts.append('<div class="meta">%d/%d done%s</div>' % (
                    cell["done"], len(cell["stories"]), " · %gp" % cell["points"] if cell["points"] else ""))
            top = (cell["phases"].most_common(1)[0][0] if cell and cell["phases"] else "Dev")
            phase = "release" if marker else re.sub(r"\W+", "", top).lower()
            cells.append('<td class="cell%s" data-phase="%s" data-col="%s">%s</td>' % (
                extra_cls, esc(phase), esc(column["token"]), "".join(parts)))
        body.append(
            '<tr><th class="epic" scope="row">%s<span class="es">%s</span><span class="ss">%s</span></th>%s</tr>'
            % (jira_link(row["key"]), esc(row["summary"]), esc(row["status"]), "".join(cells)))

    legend = "".join('<span class="a-chip" data-phase="%s"><span class="a-dot"></span>%s</span>' % (k, v) for k, v in (
        ("analysis", "Analysis"), ("dev", "Dev"), ("sit", "SIT"), ("automation", "Automation / regression"),
        ("uat", "UAT"), ("release", "Release")))
    return (
        '<p class="a-section__note">Epics owned by %s against the sprints their stories target. Active sprint %s. %s '
        'Each line is one Jira story — key, phase and summary; hover for status, click the key to open it. Grey lines '
        'are closed or ready for release. A green “Ships m/d” is the fix version carried by that cell\'s stories. '
        'Hatched columns are projected on the 21-day cadence and are not in Jira yet. Delivered sprints start '
        'collapsed — click + to open one.</p>'
        '<p class="controls a-no-print"><button class="a-btn a-btn--outline" type="button" data-delivered="expand">Expand delivered sprints</button> '
        '<button class="a-btn a-btn--outline" type="button" data-delivered="collapse">Collapse delivered sprints</button></p>'
        '<p class="legend">%s</p>'
        '<div class="a-table-scroll grid-wrap"><table class="a-table grid"><thead><tr><th class="epic">Epic</th>%s</tr></thead>'
        '<tbody>%s</tbody></table></div>'
    ) % (esc(UI_TEAM), esc(active), esc(counts), legend, "\n".join(head), "\n".join(body))


# ---------------------------------------------------------------- page

def tab_button(index, title, count=None):
    badge = '<span class="a-badge">%s</span>' % esc(str(count)) if count else ""
    return ('<button class="a-btn" id="tabbtn-%d" role="tab" type="button" aria-controls="tab-%d" '
            'aria-selected="%s">%s%s</button>' % (index, index, "true" if index == 0 else "false", esc(title), badge))


def tab_panel(index, title, body):
    return ('<section class="a-section tabpanel" id="tab-%d" role="tabpanel" aria-labelledby="tabbtn-%d" hidden>'
            '<h2 class="a-section__title">%s</h2><div class="panel-body">%s</div></section>'
            % (index, index, esc(title), body))


def render_html(rows, columns, generated, active, counts, unscheduled=(), plan=None, plan_path=PLAN_PATH,
                epics=None, cells=None):
    epics = epics or {}
    cells = cells or {}
    tabs = []
    if plan:
        tabs.append(("Year plan", render_plan_summary(plan, epics, cells), None))
        tabs.append(("Foundational", render_foundational(plan, epics, cells),
                     sum(len(c["stories"]) for c in plan["foundational"])))
        tabs.append(("Speciality", render_speciality(plan, epics, cells), len(plan["speciality"].get("programs", []))))
        if plan["programme_windows"]:
            tabs.append(("Programme windows", render_windows(plan), len(plan["programme_windows"])))
    tabs.append(("Sprint grid", render_grid(rows, columns, active, counts), len(rows)))
    tabs.append(("Not in a sprint", render_unscheduled_html(unscheduled), len(unscheduled)))
    tabs.append(("Sources & open questions", render_sources(plan, plan_path, epics, cells, rows, generated),
                 len(plan["open_questions"]) if plan else None))

    body = ('<div class="a-tabs a-tabs--wrap" data-a-tabs role="tablist" aria-label="Roadmap sections">%s</div>\n%s' % (
        "".join(tab_button(i, t, n) for i, (t, _, n) in enumerate(tabs)),
        "\n".join(tab_panel(i, t, b) for i, (t, b, _) in enumerate(tabs))))

    subtitle = "Team %s · Jira project %s · active sprint %s · as of %s" % (UI_TEAM, PROJECT, active, generated)
    if plan:
        subtitle = "Plan year %d · " % plan["plan_year"] + subtitle
    aside = ""
    if plan:
        foundational, speciality = plan_totals(plan)
        aside = "".join(
            '<span class="a-chip" data-plan="%s"><span class="a-dot"></span>%d %s</span>'
            % (key, foundational[key] + speciality[key], esc(status_label(plan, key)))
            for key, _, _ in STATUSES if foundational.get(key) or speciality.get(key))
    return artifact_kit.render_page(
        "Acme Claims roadmap", body,
        subtitle=esc(subtitle),
        aside=aside,
        extra_css=ROADMAP_CSS,
        before_kit_js=PICK_TAB_JS,
        extra_js=GRID_JS,
        body_class="roadmap",
    )


# Layout only: the page fills the whole window, edge to edge, and each panel scrolls inside itself, like /dashboard.
# The plan statuses and grid phases map onto kit tokens so light, dark and print stay consistent.
ROADMAP_CSS = """
body.roadmap { height: 100vh; display: flex; flex-direction: column; }
body.roadmap .a-shell { --max-width: none; flex: 1; display: flex; flex-direction: column; min-height: 0; width: 100%;
  padding: calc(var(--unit) * 4) calc(var(--unit) * 6) 0; }
body.roadmap .a-header { margin-bottom: 0; }
body.roadmap .a-tabs--wrap { margin-top: calc(var(--unit) * 3); }
body.roadmap .a-section__note { max-width: none; }
@media (max-width: 640px) { body.roadmap .a-shell { padding: calc(var(--unit) * 2) calc(var(--unit) * 3) 0; } }
.tabpanel { flex: 1; display: flex; flex-direction: column; min-height: 0; margin-top: calc(var(--unit) * 3);
  padding: calc(var(--unit) * 2) calc(var(--unit) * 4) calc(var(--unit) * 4);
  background: rgb(var(--bg-elevated)); border: 1px solid rgb(var(--border-secondary)); border-radius: var(--radius); }
.tabpanel[hidden] { display: none; }
.panel-body { flex: 1; min-height: 240px; overflow: auto; }
.panel-body h3 { margin: calc(var(--unit) * 5) 0 calc(var(--unit) * 2); font-size: 14px; color: rgb(var(--brand-heading)); }
.muted { color: rgb(var(--text-secondary)); font-size: 12px; }
ul.plain { padding-left: 18px; } ul.plain li { margin-bottom: 4px; }
.legend { display: flex; flex-wrap: wrap; gap: calc(var(--unit) * 2); margin: calc(var(--unit) * 2) 0; }

[data-plan="delivered"] { --attention: var(--text-green); }
[data-plan="this_year"] { --attention: var(--text-orange); }
[data-plan="next_year"] { --attention: var(--brand-gold); }
[data-plan="unknown"] { --attention: var(--brand-slate); }
.legend .a-chip, .a-metric__label { color: rgb(var(--text-primary)); }
.a-metric[data-plan] { box-shadow: inset 3px 0 0 rgb(var(--attention)); }
.a-metric__label .a-dot { display: inline-block; vertical-align: middle; }
.metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: calc(var(--unit) * 3); }
.stack { display: flex; height: 12px; border-radius: 999px; background: rgb(var(--tint-secondary)); overflow: hidden; }
.stack__seg { display: block; height: 100%; background: rgb(var(--attention)); }
.a-table.plan-table td.num, .a-table.plan-table th.num { text-align: right; font-family: var(--font-mono); white-space: nowrap; }
.a-table.plan-table tr[data-plan] td:first-child, .a-table.plan-table tr[data-plan] th[scope="row"] { box-shadow: inset 3px 0 0 rgb(var(--attention)); }
.a-table.plan-table th[scope="row"] { vertical-align: top; text-align: left; }

/* sprint grid */
.grid-wrap { max-height: none; }
.a-table.grid { font-size: 12px; border-collapse: separate; border-spacing: 0; }
.a-table.grid th, .a-table.grid td { vertical-align: top; }
.a-table.grid thead th { white-space: nowrap; }
.a-table.grid thead th.active { box-shadow: inset 0 -3px 0 rgb(var(--brand-gold)); }
.a-table.grid thead th.projected { opacity: 0.75; }
.a-table.grid thead th .tok, .a-table.grid thead th .dt { display: block; }
.a-table.grid thead th .dt { font-weight: 400; font-size: 11px; opacity: 0.85; }
.a-table.grid th.epic { position: sticky; left: 0; z-index: 2; background: rgb(var(--bg-elevated)); width: 220px;
  min-width: 220px; text-align: left; border-right: 2px solid rgb(var(--brand-line)); }
.a-table.grid thead th.epic { z-index: 4; background: rgb(var(--brand-navy)); }
.a-table.grid th.epic a { font-size: 11px; }
.a-table.grid th.epic .es { display: block; font-weight: 600; }
.a-table.grid th.epic .ss { display: block; font-weight: 400; color: rgb(var(--text-secondary)); font-size: 11px; }
.a-table.grid td { width: 250px; min-width: 250px; }
.a-table.grid td.projected { background-image: repeating-linear-gradient(45deg, rgb(var(--text-primary) / 0.03) 0 6px, transparent 6px 12px); }
.a-table.grid td.cell { box-shadow: inset 3px 0 0 rgb(var(--attention)); background: rgb(var(--attention) / 0.06); }
[data-phase="analysis"] { --attention: var(--brand-slate); }
[data-phase="dev"] { --attention: var(--text-blue); }
[data-phase="sit"] { --attention: var(--text-orange); }
[data-phase="automation"], [data-phase="regression"] { --attention: var(--text-purple); }
[data-phase="e2e"] { --attention: var(--brand-teal); }
[data-phase="uat"] { --attention: var(--brand-gold); }
[data-phase="releasesupport"], [data-phase="release"] { --attention: var(--text-green); }
.ph { font-weight: 700; font-size: 11px; letter-spacing: .02em; text-transform: uppercase; margin-bottom: 3px; }
.st { margin-bottom: 5px; line-height: 1.3; }
.st a { font-weight: 600; font-size: 11px; }
.st .ti { display: block; }
.st .ph2 { color: rgb(var(--text-tertiary)); font-size: 10px; text-transform: uppercase; letter-spacing: .02em; }
.st.ok, .st.ok .ti, .st.ok a { color: rgb(var(--text-tertiary)); }
.more, .meta { font-size: 11px; color: rgb(var(--text-secondary)); }
.rel { font-weight: 700; color: rgb(var(--text-green)); }
.tg { float: right; margin-left: 6px; cursor: pointer; border: 1px solid rgb(255 255 255 / 0.5); background: transparent;
  color: inherit; border-radius: 3px; font: 600 11px/1 inherit; padding: 2px 5px; }
.a-table.grid th.collapsed, .a-table.grid td.collapsed { width: 30px; min-width: 30px; max-width: 30px; padding: 4px 3px; overflow: hidden; }
.a-table.grid th.collapsed .dt, .a-table.grid td.collapsed > div { display: none; }
.a-table.grid th.collapsed .tok { font-size: 11px; writing-mode: vertical-rl; }
.a-table.grid th.collapsed .tg { float: none; display: block; margin: 0 0 4px; padding: 1px 3px; }
.controls { margin: 0 0 calc(var(--unit) * 2); }
@media print { body.roadmap { height: auto; } .panel-body { overflow: visible; } .tabpanel[hidden] { display: flex; }
  .a-table.grid th.collapsed, .a-table.grid td.collapsed { width: auto; min-width: 0; max-width: none; }
  .a-table.grid td.collapsed > div, .a-table.grid th.collapsed .dt { display: block; } }
"""

# Runs before the kit: open the tab named in the URL hash.
PICK_TAB_JS = """(function () {
  var wanted = location.hash.replace("#", "");
  if (wanted.indexOf("tab-") !== 0 || !document.getElementById(wanted)) return;
  document.querySelectorAll('[data-a-tabs] [role="tab"]').forEach(function (tab) {
    tab.setAttribute("aria-selected", tab.getAttribute("aria-controls") === wanted ? "true" : "false");
  });
}());"""

GRID_JS = """(function () {
  "use strict";
  var list = document.querySelector("[data-a-tabs]");
  function remember() {
    var tab = list && list.querySelector('[role="tab"][aria-selected="true"]');
    if (tab) history.replaceState(null, "", "#" + tab.getAttribute("aria-controls"));
  }
  if (list) {
    list.addEventListener("click", remember);
    list.addEventListener("keydown", function () { setTimeout(remember, 0); });
  }
  function apply(token, collapsed) {
    document.querySelectorAll('[data-col="' + token + '"]').forEach(function (cell) {
      cell.classList.toggle("collapsed", collapsed);
    });
    var button = document.querySelector('th[data-col="' + token + '"] .tg');
    if (button) { button.textContent = collapsed ? "+" : "\\u2013"; }
  }
  document.querySelectorAll(".tg[data-toggle]").forEach(function (button) {
    button.addEventListener("click", function () {
      var header = button.closest("th");
      apply(button.dataset.toggle, !header.classList.contains("collapsed"));
    });
  });
  document.querySelectorAll("[data-delivered]").forEach(function (button) {
    button.addEventListener("click", function () {
      var collapsed = button.dataset.delivered === "collapse";
      document.querySelectorAll("th.past").forEach(function (header) { apply(header.dataset.col, collapsed); });
    });
  });
}());"""


def render_plan_markdown(plan, plan_path):
    out = ["## Year plan (hand-maintained, not from Jira)", ""]
    out.append("Read from `%s`%s. Points are story + SIT + UAT per item as sized on the team's sheet; "
               "items without points are listed as not sized. Statuses: delivered (white on the sheet), "
               "due in %d (orange), pushed to %d (yellow). [PLAN-FACT]" % (
                   plan_path, " — %s" % plan["source"] if plan.get("source") else "",
                   plan["plan_year"], plan["next_year"]))
    out.append("")
    foundational, speciality = plan_totals(plan)
    out.append("| Status | Foundational | Speciality | Total |")
    out.append("|---|---|---|---|")
    for key, _, _ in STATUSES:
        if foundational.get(key) or speciality.get(key):
            out.append("| %s | %d | %d | %d |" % (status_label(plan, key), foundational[key], speciality[key],
                                                 foundational[key] + speciality[key]))
    out.append("")
    out.append("### Foundational")
    out.append("")
    out.append("| Capability | Story | Dev | SIT | UAT | Total | Status | Jira |")
    out.append("|---|---|---|---|---|---|---|---|")
    for capability in plan["foundational"]:
        for story in capability["stories"]:
            points = story.get("points") or {}
            out.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
                capability["capability"], story["name"], points.get("story", "—"), points.get("sit", "—"),
                points.get("uat", "—"), story_total(story) if points else "not sized",
                status_label(plan, story.get("status", "unknown")), ", ".join(story.get("jira") or []) or "—"))
    out.append("")
    out.append("### Speciality risk programmes")
    out.append("")
    caps = plan["speciality"].get("capabilities", [])
    out.append("| Programme | %s | Total | Status |" % " | ".join(caps))
    out.append("|---|%s---|---|" % ("---|" * len(caps)))
    for program in plan["speciality"].get("programs", []):
        breakdown = program.get("breakdown") or [None] * len(caps)
        total = program.get("total_points")
        out.append("| %s | %s | %s | %s |" % (
            program["name"], " | ".join("—" if v is None else str(v) for v in breakdown),
            "no total on the sheet" if total is None else total, status_label(plan, program.get("status", "unknown"))))
    out.append("")
    if plan["unsized"]:
        out.append("### Committed but not sized")
        out.append("")
        for item in plan["unsized"]:
            target = ""
            if item.get("target"):
                target = " Target %s%s." % (item["target"], "" if item.get("target_confirmed", True) else " [ASSUMED year]")
            out.append("- %s — %s. %s%s" % (item["name"], status_label(plan, item.get("status", "unknown")),
                                            item.get("note", ""), target))
        out.append("")
    for block in plan["programme_windows"]:
        out.append("### Programme windows — %s%s" % (block["program"], " (%s)" % block["team"] if block.get("team") else ""))
        out.append("")
        cols = [str(c) for c in block.get("columns", [])]
        out.append("| %s |" % " | ".join(cols))
        out.append("|%s" % ("---|" * len(cols)))
        for row in block.get("rows", []):
            out.append("| %s |" % " | ".join(str(v) for v in row))
        out.append("")
    if plan["open_questions"]:
        out.append("### Open questions")
        out.append("")
        for q in plan["open_questions"]:
            out.append("- %s — %s" % (q["question"], q.get("owner", "owner not set")))
        out.append("")
    return out


def render_markdown(rows, columns, generated, active, counts, unscheduled=(), plan=None, plan_path=PLAN_PATH):
    out = ["# Acme Claims roadmap", ""]
    out.append("Generated %s from Jira project Acme Claims, epics whose IT Team is `%s`. Active sprint "
               "%s. %s" % (generated, UI_TEAM, active, counts))
    out.append("")
    if plan:
        out.extend(render_plan_markdown(plan, plan_path))
        out.append("## Sprint grid (Jira-derived)")
        out.append("")
    out.append("This document is generated by `sdlc/framework/tools/gen_roadmap.py` and is "
               "[JIRA-FACT] throughout this section: every story, sprint and status below is read from Jira "
               "fields. The phase label on each cell (analysis, dev, SIT, UAT, automation, release "
               "support) is [JIRA-INFERRED] — it comes from the phase suffix the team puts on story "
               "summaries, not from a Jira field. The short label on each story is also "
               "[JIRA-INFERRED]: it is the subject reduced to a word or two, with the Jira keys "
               "and summaries it stands for listed beside it. Sprint columns beyond those Jira "
               "holds are projected on the 21-day cadence and marked as projected.")
    out.append("")
    for row in rows:
        out.append("## %s — %s" % (row["key"], row["summary"]))
        out.append("")
        out.append("Epic status: %s." % row["status"])
        if row["releases"]:
            dates = ", ".join("%s (%s)" % (d.isoformat(), t) for t, d in sorted(
                row["releases"].items(), key=lambda kv: kv[1]))
            out.append("Release dates the stories in each sprint carry: %s." % dates)
        out.append("")
        for column in columns:
            cell = row["cells"].get(column["token"])
            if not cell:
                continue
            phases, lines, extra = cell_summary(cell, limit=MD_STORY_LIMIT)
            head = "**%s**%s — %s" % (
                column["token"],
                " (projected)" if column["projected"] else (" (active)" if column["active"] else ""),
                " / ".join(phases) or "dev")
            out.append("%s, %d of %d story items closed or ready for release." % (
                head, cell["done"], len(cell["stories"])))
            for group in lines:
                out.append("- %s%s: %s." % (
                    group["label"],
                    " (%s)" % group["qualifier"] if group["qualifier"] else "",
                    "; ".join(group["titles"])))
            if extra:
                out.append("- Also in this sprint: %s." % "; ".join(
                    "%s (%s)" % (g["label"], ", ".join(g["keys"])) for g in extra))
            out.append("")
    if unscheduled:
        out.append("## Open UI epics with no sprint-assigned work")
        out.append("")
        out.append("These epics are planned but hold no story in any sprint, so they have no column "
                   "in the grid. [JIRA-FACT]")
        out.append("")
        for key, epic in unscheduled:
            out.append("- %s — %s (%s)" % (key, epic["fields"]["summary"],
                                           epic["fields"]["status"]["name"]))
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cache", help="read issues from this JSON file instead of Jira")
    parser.add_argument("--sprints-cache", help="read board sprints from this JSON file")
    parser.add_argument("--back", type=int, default=4, help="sprint columns before the active one")
    parser.add_argument("--ahead", type=int, default=6, help="sprint columns after the active one")
    parser.add_argument("--out-html", default="docs/knowledge-base/JIRA-DERIVED/UI-DELIVERY-ROADMAP.html")
    parser.add_argument("--out-md", default="docs/knowledge-base/JIRA-DERIVED/05_UI_DELIVERY_ROADMAP.md")
    parser.add_argument("--plan", default=PLAN_PATH,
                        help="hand-maintained year plan YAML; pass an empty string to render the Jira grid alone")
    args = parser.parse_args(argv)
    plan = load_plan(args.plan)

    if args.cache:
        issues = json.load(open(args.cache, encoding="utf-8"))
        issues = [i for i in issues if any(
            UI_TEAM in (t.get("value") or "") for t in (i["fields"].get(F_IT_TEAM) or []))]
    else:
        issues = fetch_issues()

    if args.sprints_cache:
        raw = json.load(open(args.sprints_cache, encoding="utf-8"))
        sprints = raw.get(str(BOARD), raw) if isinstance(raw, dict) else raw
        sprints = sprints if isinstance(sprints, list) else sprints.get("values", [])
    else:
        sprints = fetch_sprints()

    epics, cells, seen_tokens, by_key = collect(issues)
    if not args.cache:
        for epic in fetch_epics(set(cells) - set(epics)):
            epics[epic["key"]] = epic

    columns, active = build_columns(sprints, seen_tokens, args.back, args.ahead)
    tokens = [c["token"] for c in columns]

    rows = []
    for epic_key, per_sprint in cells.items():
        in_window = {t: c for t, c in per_sprint.items() if t in tokens}
        if not in_window:
            continue
        epic = epics.get(epic_key)
        # A release marker belongs to the cell whose own stories carry that fix version, not to
        # every cell in the row: one story shipping in November says nothing about the next-year
        # work sitting in the cell beside it.
        markers = {}
        for token, cell in in_window.items():
            if cell["releases"]:
                date = max(cell["releases"])
                markers[token] = date
        rows.append({
            "key": epic_key,
            "summary": describe_row(epic_key, epic),
            "status": epic["fields"]["status"]["name"] if epic else "n/a",
            "cells": in_window,
            "releases": markers,
        })

    rows.sort(key=lambda r: (r["key"] == UNPARENTED,
                             tokens.index(min(r["cells"], key=lambda t: tokens.index(t))),
                             -sum(len(c["stories"]) for c in r["cells"].values())))

    scheduled = set(cells)
    unscheduled = sorted(
        (key, epic) for key, epic in epics.items()
        if key not in scheduled and (epic["fields"]["status"]["name"] or "").lower() != "closed")

    generated = datetime.date.today().isoformat()
    counts = "%d epics, %d story items across %d sprint columns." % (
        len(rows), sum(len(c["stories"]) for r in rows for c in r["cells"].values()), len(columns))

    page = render_html(rows, columns, generated, active, counts, unscheduled,
                       plan=plan, plan_path=args.plan, epics=epics, cells=cells)
    prose = render_markdown(rows, columns, generated, active, counts, unscheduled, plan=plan, plan_path=args.plan)
    for path, text in ((args.out_html, page), (args.out_md, prose)):
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        print("wrote", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
