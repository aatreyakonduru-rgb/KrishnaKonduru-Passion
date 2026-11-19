#!/usr/bin/env python3
"""Open SIT and UAT defects across project Acme Claims, grouped by specialty and then by team.

    python3 sdlc/framework/tools/defects_by_specialty.py            # live Jira
    python3 sdlc/framework/tools/defects_by_specialty.py \\
        --cache sdlc/framework/tools/fixtures/defects-by-specialty-demo.json

Backs /defects-by-specialty (a page of its own) and the "Defects by specialty" tab that
gen_dashboard.py draws for the Tech Lead and PO office lenses (panel kind `defect_matrix`).

Which defects: project Acme Claims, type Defect or Bug, "Defect Detected In" SIT or UAT, unresolved. The
query is the whole project; it is never narrowed to the viewer's team. Every page of results is read.
Which specialty: keyword rules in .devin/rules/defect-specialties.yaml (Jira has no specialty field).
Per defect it also shows who is on it, the planned release (fix version, else sprint end), how long
it has been open and idle, and flags for the things a lead or PO usually has to act on.
"""
import argparse
import collections
import datetime
import html
import json
import os
import re
import sys

import yaml

import artifact_kit

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
RULES_PATH = os.path.join(ROOT, ".devin", "rules", "defect-specialties.yaml")
OUT_DIR = os.path.join(ROOT, "sdlc", "framework", "context", "dashboard")
BROWSE = "https://jira.acme.example/browse/"

F_DETECTED = "customfield_10021"
F_SEVERITY = "customfield_10013"
F_SPRINT = "customfield_10002"
F_EPIC = "customfield_10010"
F_TEAM = "customfield_10004"

ENVIRONMENTS = {
    "TEST - System Integration Test (SIT)": "SIT",
    "TEST - User Acceptance Test (UAT)": "UAT",
}
JQL = (
    'project = ACME AND issuetype in (Defect, Bug) AND "Defect Detected In" in (%s) '
    "AND resolution = Unresolved ORDER BY created ASC"
    % ", ".join('"%s"' % name for name in ENVIRONMENTS)
)
FIELDS = ",".join([
    "summary", "issuetype", "status", "assignee", "reporter", "created", "updated", "duedate",
    "fixVersions", "issuelinks", F_DETECTED, F_SEVERITY, F_SPRINT, F_EPIC, F_TEAM,
])
PAGE_SIZE = 100
MAX_ISSUES = 2000

SEVERITY_ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
URGENT = ("Critical", "High")
NO_TEAM = "No IT Team"

FLAG_LABELS = collections.OrderedDict([
    ("unassigned", "No one assigned"),
    ("no_release", "No release planned"),
    ("release_passed", "Release date passed"),
    ("not_moving", "Not moving"),
])
FLAG_STATE = {"unassigned": "blocked", "no_release": "at-risk", "release_passed": "blocked",
              "not_moving": "at-risk"}

COLUMNS = ["key", "env", "severity", "summary", "status", "assignee", "team", "release", "sprint",
           "age", "idle", "flags", "matched"]
COLUMN_LABELS = {
    "key": "Key", "env": "Found in", "severity": "Severity", "summary": "Summary",
    "status": "Status", "assignee": "Working on it", "team": "IT Team",
    "release": "Planned release", "sprint": "Sprint", "age": "Days open", "idle": "Days idle",
    "flags": "Needs a decision", "matched": "Specialty from", "reporter": "Raised by",
    "epic": "Epic", "links": "Linked issues", "due": "Due",
}


# ---------------------------------------------------------------- rules

def load_rules(path=RULES_PATH):
    with open(path, encoding="utf-8") as fh:
        rules = yaml.safe_load(fh) or {}
    rules.setdefault("specialties", [])
    rules.setdefault("unassigned", "Unassigned")
    rules.setdefault("placeholder_versions", [])
    rules.setdefault("stale_days", 14)
    return rules


def compile_rules(rules):
    compiled = []
    for spec in rules["specialties"]:
        parts = [r"(?<![A-Za-z0-9])%s(?![A-Za-z0-9])" % re.escape(word)
                 for word in spec.get("keywords") or []]
        parts.extend(spec.get("patterns") or [])
        if parts:
            compiled.append((spec["name"], re.compile("|".join("(?:%s)" % p for p in parts), re.I)))
    return compiled


def specialty_names(rules):
    return [spec["name"] for spec in rules["specialties"]] + [rules["unassigned"]]


def classify(texts, compiled, unassigned):
    """`texts` is [(source, text)] in priority order. Returns (specialty, evidence, also-matched)."""
    for source, text in texts:
        hits = [(name, rx.search(text or "")) for name, rx in compiled]
        hits = [(name, m) for name, m in hits if m]
        if hits:
            name, match = hits[0]
            return name, '%s: "%s"' % (source, match.group(0)), [n for n, _ in hits[1:]]
    return unassigned, "no keyword matched", []


# ---------------------------------------------------------------- Jira

def fetch(get, jql=JQL):
    """Every matching issue (paged) plus the names of their epics. `get(path, **params)` is a
    validated Jira GET, e.g. gen_dashboard.JiraClient().live_get."""
    issues, start = [], 0
    while True:
        page = get("/api/2/search", jql=jql, startAt=start, maxResults=PAGE_SIZE, fields=FIELDS)
        batch = page.get("issues") or []
        issues.extend(batch)
        start += len(batch)
        if not batch or start >= int(page.get("total") or 0) or start >= MAX_ISSUES:
            break
    epic_keys = sorted({(i.get("fields") or {}).get(F_EPIC) for i in issues} - {None, ""})
    epics = {}
    for n in range(0, len(epic_keys), 50):
        chunk = epic_keys[n:n + 50]
        page = get("/api/2/search", jql="key in (%s)" % ",".join(chunk), maxResults=len(chunk),
                   fields="summary")
        for epic in page.get("issues") or []:
            epics[epic["key"]] = (epic.get("fields") or {}).get("summary", "")
    return {"issues": issues, "epics": epics}


def value_of(field):
    if isinstance(field, list):
        return ", ".join(v for v in (value_of(f) for f in field) if v)
    if isinstance(field, dict):
        return field.get("value") or field.get("name") or field.get("displayName") or ""
    return str(field or "")


def person(field):
    return (field or {}).get("displayName") or (field or {}).get("name") or ""


def to_date(text):
    try:
        return datetime.date.fromisoformat(str(text)[:10])
    except ValueError:
        return None


SPRINT_PART = re.compile(r"(\w+)=([^,\]]*)")


def parse_sprint(raw):
    if isinstance(raw, dict):
        data = raw
    else:
        data = dict(SPRINT_PART.findall(str(raw)))
    return {
        "name": data.get("name") or "",
        "state": (data.get("state") or "").upper(),
        "start": to_date(data.get("startDate") or ""),
        "end": to_date(data.get("endDate") or ""),
    }


def current_sprint(value):
    sprints = [parse_sprint(s) for s in value or []]
    sprints = [s for s in sprints if s["name"]]
    if not sprints:
        return None
    for state in ("ACTIVE", "FUTURE"):
        found = [s for s in sprints if s["state"] == state]
        if found:
            return min(found, key=lambda s: s["start"] or datetime.date.max)
    return max(sprints, key=lambda s: s["end"] or datetime.date.min)


def planned_release(versions, placeholders):
    """The fix version the defect is meant to ship in: the earliest unreleased real one, else the
    latest real one. None when there is no real fix version."""
    skip = {p.upper() for p in placeholders}
    real = [v for v in versions or [] if (v.get("name") or "").strip().upper() not in skip]
    if not real:
        return None
    open_versions = [v for v in real if not v.get("released")]
    pool = open_versions or real
    pick = min(pool, key=lambda v: to_date(v.get("releaseDate") or "") or datetime.date.max)
    return {"name": pick.get("name", ""), "date": to_date(pick.get("releaseDate") or ""),
            "released": bool(pick.get("released"))}


def linked(fields):
    out = []
    for link in fields.get("issuelinks") or []:
        other = link.get("outwardIssue") or link.get("inwardIssue") or {}
        if other.get("key"):
            out.append((other["key"], (other.get("fields") or {}).get("summary", "")))
    return out


def defect_rows(data, rules, today=None):
    today = today or datetime.date.today()
    compiled = compile_rules(rules)
    epics = data.get("epics") or {}
    stale = int(rules.get("stale_days") or 14)
    rows = []
    for issue in data.get("issues") or []:
        fields = issue.get("fields") or {}
        summary = fields.get("summary", "")
        epic_key = fields.get(F_EPIC) or ""
        epic_name = epics.get(epic_key, "")
        links = linked(fields)
        texts = [("summary", summary)]
        if epic_name:
            texts.append(("epic %s" % epic_key, epic_name))
        texts.extend(("linked %s" % key, text) for key, text in links)
        specialty, matched, also = classify(texts, compiled, rules["unassigned"])
        release = planned_release(fields.get("fixVersions"), rules["placeholder_versions"])
        sprint = current_sprint(fields.get(F_SPRINT))
        created, updated = to_date(fields.get("created") or ""), to_date(fields.get("updated") or "")
        detected = value_of(fields.get(F_DETECTED))
        row = {
            "key": issue.get("key", ""),
            "type": (fields.get("issuetype") or {}).get("name", ""),
            "env": ENVIRONMENTS.get(detected, detected),
            "severity": value_of(fields.get(F_SEVERITY)),
            "summary": summary,
            "status": (fields.get("status") or {}).get("name", ""),
            "assignee": person(fields.get("assignee")),
            "reporter": person(fields.get("reporter")),
            "team": value_of(fields.get(F_TEAM)) or NO_TEAM,
            "specialty": specialty,
            "matched": matched,
            "also": also,
            "epic": ("%s %s" % (epic_key, epic_name)).strip(),
            "links": [key for key, _ in links],
            "due": fields.get("duedate") or "",
            "release_name": release["name"] if release else "",
            "release_date": release["date"].isoformat() if release and release["date"] else "",
            "sprint_name": sprint["name"] if sprint else "",
            "sprint_state": sprint["state"].lower() if sprint else "",
            "sprint_end": sprint["end"].isoformat() if sprint and sprint["end"] else "",
            "age": (today - created).days if created else "",
            "idle": (today - updated).days if updated else "",
        }
        flags = []
        if not row["assignee"]:
            flags.append("unassigned")
        sprint_ahead = sprint and sprint["state"] in ("ACTIVE", "FUTURE")
        if not release and not sprint_ahead:
            flags.append("no_release")
        planned = release["date"] if release else (sprint["end"] if sprint_ahead else None)
        if planned and planned < today:
            flags.append("release_passed")
        if row["idle"] != "" and row["idle"] >= stale:
            flags.append("not_moving")
        row["flags"] = flags
        rows.append(row)
    order = {name: n for n, name in enumerate(specialty_names(rules))}
    rows.sort(key=lambda r: (order.get(r["specialty"], 99), r["team"] == NO_TEAM, r["team"],
                             SEVERITY_ORDER.get(r["severity"], 9), r["key"]))
    return rows


def needs_attention(row):
    return row["severity"] in URGENT and any(
        f in row["flags"] for f in ("unassigned", "no_release", "release_passed"))


def attention(rows):
    if not rows:
        return "clear"
    return "hot" if any(needs_attention(r) for r in rows) else "watch"


# ---------------------------------------------------------------- shared text

def release_text(row):
    if row["release_name"]:
        when = row["release_date"] or "no date"
        return row["release_name"] if row["release_name"] == when else "%s (%s)" % (row["release_name"], when)
    if row["sprint_end"] and row["sprint_state"] in ("active", "future"):
        return "sprint ends %s" % row["sprint_end"]
    return "Not planned"


def sprint_text(row):
    if not row["sprint_name"]:
        return ""
    return "%s (%s)" % (row["sprint_name"], row["sprint_state"]) if row["sprint_state"] else row["sprint_name"]


def flag_text(row):
    return ", ".join(FLAG_LABELS[f] for f in row["flags"])


def totals(rows, rules):
    """Per specialty: counts that matter for a decision, in rules order."""
    out = collections.OrderedDict((name, collections.Counter()) for name in specialty_names(rules))
    for row in rows:
        c = out.setdefault(row["specialty"], collections.Counter())
        c["total"] += 1
        c[row["env"]] += 1
        if row["severity"] in URGENT:
            c["urgent"] += 1
        for flag in row["flags"]:
            c[flag] += 1
    return out


def fill_rates(rows):
    n = len(rows) or 1
    return {
        "assignee": sum(1 for r in rows if r["assignee"]) * 100 // n,
        "release": sum(1 for r in rows if r["release_name"]) * 100 // n,
        "sprint": sum(1 for r in rows if r["sprint_name"]) * 100 // n,
        "team": sum(1 for r in rows if r["team"] != NO_TEAM) * 100 // n,
    }


SUMMARY_COLUMNS = [("total", "Open"), ("SIT", "SIT"), ("UAT", "UAT"), ("urgent", "Critical or High"),
                   ("unassigned", "No one assigned"), ("no_release", "No release planned"),
                   ("release_passed", "Release date passed"), ("not_moving", "Not moving")]


# ---------------------------------------------------------------- HTML

def esc(value):
    return html.escape(str(value if value is not None else ""), quote=True)


def link(key):
    return '<a href="%s%s">%s</a>' % (BROWSE, esc(key), esc(key)) if key else ""


def cell(row, column):
    if column == "key":
        return link(row["key"])
    if column == "summary":
        extra = ""
        if row["epic"]:
            extra += '<br><small>Epic: %s</small>' % esc(row["epic"])
        if row["links"]:
            extra += '<br><small>Linked: %s</small>' % ", ".join(link(k) for k in row["links"][:4])
        return esc(row["summary"]) + extra
    if column == "assignee":
        return esc(row["assignee"]) if row["assignee"] else '<span class="a-status" data-state="blocked">nobody</span>'
    if column == "release":
        text = release_text(row)
        state = "blocked" if "release_passed" in row["flags"] else ("at-risk" if text == "Not planned" else "")
        return '<span class="a-status" data-state="%s">%s</span>' % (state, esc(text)) if state else esc(text)
    if column == "sprint":
        return esc(sprint_text(row))
    if column == "severity":
        state = "blocked" if row["severity"] in URGENT else "planned"
        return '<span class="a-status" data-state="%s">%s</span>' % (state, esc(row["severity"]))
    if column == "flags":
        return " ".join('<span class="a-status" data-state="%s">%s</span>' % (FLAG_STATE[f], esc(FLAG_LABELS[f]))
                        for f in row["flags"])
    if column == "matched":
        also = "<br><small>also matches %s</small>" % esc(", ".join(row["also"])) if row["also"] else ""
        return esc(row["matched"]) + also
    if column == "links":
        return ", ".join(link(k) for k in row["links"])
    return esc(row.get(column, ""))


def metric(label, value, note=""):
    return ('<div class="a-metric"><div class="a-metric__label">%s</div><div class="a-metric__value">%s</div>'
            '<div class="a-metric__delta">%s</div></div>' % (esc(label), esc(value), esc(note)))


def summary_table(rows, rules):
    head = "<th>Specialty</th>" + "".join("<th>%s</th>" % esc(label) for _, label in SUMMARY_COLUMNS)
    body = []
    for name, c in totals(rows, rules).items():
        if not c["total"]:
            continue
        body.append("<tr><th scope=\"row\">%s</th>%s</tr>" % (
            esc(name), "".join("<td>%s</td>" % (c[key] or "") for key, _ in SUMMARY_COLUMNS)))
    return ('<div class="a-table-scroll"><table class="a-table"><thead><tr>%s</tr></thead><tbody>%s</tbody>'
            "</table></div>" % (head, "".join(body)))


def team_table(rows, rules):
    teams = sorted({r["team"] for r in rows}, key=lambda t: (t == NO_TEAM, t))
    counts = collections.Counter((r["specialty"], r["team"]) for r in rows)
    head = "<th>Specialty</th>" + "".join("<th>%s</th>" % esc(t) for t in teams)
    body = []
    for name in specialty_names(rules):
        if not any(counts[(name, t)] for t in teams):
            continue
        body.append("<tr><th scope=\"row\">%s</th>%s</tr>" % (
            esc(name), "".join("<td>%s</td>" % (counts[(name, t)] or "") for t in teams)))
    return ('<div class="a-table-scroll"><table class="a-table"><thead><tr>%s</tr></thead><tbody>%s</tbody>'
            "</table></div>" % (head, "".join(body)))


def options(name, values, label):
    opts = '<option value="">%s: all</option>' % esc(label) + "".join(
        '<option value="%s">%s</option>' % (esc(v), esc(v)) for v in values)
    return '<select class="a-select" data-dm-filter="%s" aria-label="%s">%s</select>' % (name, esc(label), opts)


FILTER_JS = """(function () {
  var root = document.getElementById("%(id)s");
  if (!root) { return; }
  var filters = Array.prototype.slice.call(root.querySelectorAll("[data-dm-filter]"));
  function apply() {
    var want = {};
    filters.forEach(function (f) {
      want[f.getAttribute("data-dm-filter")] = f.type === "checkbox" ? (f.checked ? "1" : "") : f.value;
    });
    var rows = Array.prototype.slice.call(root.querySelectorAll("tr[data-dm-row]"));
    rows.forEach(function (tr) {
      tr.hidden = !Object.keys(want).every(function (k) {
        return !want[k] || tr.getAttribute("data-" + k) === want[k];
      });
    });
    root.querySelectorAll("tr[data-dm-team-head]").forEach(function (head) {
      var team = head.getAttribute("data-dm-team-head");
      var group = head.closest("tbody");
      head.hidden = !rows.some(function (tr) {
        return !tr.hidden && tr.closest("tbody") === group && tr.getAttribute("data-team") === team;
      });
    });
    root.querySelectorAll("[data-dm-block]").forEach(function (block) {
      block.hidden = !block.querySelector("tr[data-dm-row]:not([hidden])");
    });
  }
  filters.forEach(function (f) { f.addEventListener("change", apply); });
})();"""


def render_fragment(rows, rules, columns=None, dom_id="defect-matrix"):
    """The body shared by the dashboard tab and the stand-alone page."""
    columns = [c for c in (columns or COLUMNS) if c in COLUMN_LABELS]
    if not rows:
        return ""
    sit = sum(1 for r in rows if r["env"] == "SIT")
    urgent = [r for r in rows if r["severity"] in URGENT]
    flagged = [r for r in rows if r["flags"]]
    rates = fill_rates(rows)
    parts = ['<div id="%s">' % esc(dom_id)]
    parts.append('<div class="a-grid">%s%s%s%s</div>' % (
        metric("Open SIT and UAT defects", len(rows), "%d SIT, %d UAT" % (sit, len(rows) - sit)),
        metric("Critical or High", len(urgent),
               "%d with nobody assigned or no release" % sum(1 for r in urgent if needs_attention(r))),
        metric("Need a decision", len(flagged), "at least one flag below"),
        metric("No specialty found", sum(1 for r in rows if r["specialty"] == rules["unassigned"]),
               "fix by editing defect-specialties.yaml"),
    ))
    parts.append("<h3>By specialty</h3>" + summary_table(rows, rules))
    parts.append("<h3>Specialty by team</h3>" + team_table(rows, rules))
    teams = sorted({r["team"] for r in rows}, key=lambda t: (t == NO_TEAM, t))
    present = [n for n in specialty_names(rules) if any(r["specialty"] == n for r in rows)]
    parts.append(
        '<h3>Defects</h3><div class="a-toolbar">%s%s%s%s<label><input type="checkbox" data-dm-filter="flagged"> '
        "Only ones that need a decision</label></div>" % (
            options("spec", present, "Specialty"), options("team", teams, "Team"),
            options("env", ["SIT", "UAT"], "Found in"),
            options("severity", [s for s in SEVERITY_ORDER if any(r["severity"] == s for r in rows)], "Severity")))
    head = "".join("<th>%s</th>" % esc(COLUMN_LABELS[c]) for c in columns)
    for name in present:
        group = [r for r in rows if r["specialty"] == name]
        body, last_team = [], None
        for row in group:
            if row["team"] != last_team:
                last_team = row["team"]
                n = sum(1 for r in group if r["team"] == last_team)
                body.append('<tr data-dm-team-head="%s"><th colspan="%d" scope="colgroup">%s (%d)</th></tr>'
                            % (esc(last_team), len(columns), esc(last_team), n))
            body.append('<tr data-dm-row data-spec="%s" data-team="%s" data-env="%s" data-severity="%s" '
                        'data-flagged="%s">%s</tr>' % (
                            esc(name), esc(row["team"]), esc(row["env"]), esc(row["severity"]),
                            "1" if row["flags"] else "", "".join("<td>%s</td>" % cell(row, c) for c in columns)))
        parts.append('<div data-dm-block><h4>%s (%d)</h4><div class="a-table-scroll"><table class="a-table">'
                     "<thead><tr>%s</tr></thead><tbody>%s</tbody></table></div></div>"
                     % (esc(name), len(group), head, "".join(body)))
    parts.append(
        '<p class="a-section__note">Specialty comes from keyword rules in .devin/rules/defect-specialties.yaml, '
        "not from a Jira field; the \"Specialty from\" column shows what matched. Planned release is the fix "
        "version, or the sprint end when there is no fix version. Filled in Jira today: assignee %d%%, "
        "fix version %d%%, sprint %d%%, IT Team %d%%.</p>"
        % (rates["assignee"], rates["release"], rates["sprint"], rates["team"]))
    parts.append("<script>%s</script></div>" % (FILTER_JS % {"id": dom_id}))
    return "".join(parts)


def render_page(rows, rules, generated, sample=False):
    subtitle = "%d open, as of %s from %s" % (len(rows), generated, "sample data" if sample else "live Jira")
    body = render_fragment(rows, rules, dom_id="defect-matrix") or '<p class="a-empty">No open SIT or UAT defects.</p>'
    return artifact_kit.render_page(
        "Open SIT and UAT defects by specialty", '<section class="a-section">%s</section>' % body,
        subtitle=esc(subtitle),
        footnote="Query: %s" % esc(JQL),
    )


# ---------------------------------------------------------------- Markdown

def md(text):
    return str(text if text is not None else "").replace("|", "\\|").replace("\n", " ")


def render_markdown(rows, rules, generated, sample=False):
    out = ["# Open SIT and UAT defects by specialty", "",
           "Generated %s from %s. %d open defects across project Acme Claims." % (
               generated, "sample data" if sample else "live Jira", len(rows)), "",
           "Specialty comes from the keyword rules in `.devin/rules/defect-specialties.yaml`, not from a Jira "
           "field. Planned release is the fix version, or the sprint end when there is no fix version.", "",
           "## By specialty", "",
           "| Specialty | " + " | ".join(label for _, label in SUMMARY_COLUMNS) + " |",
           "|---|" + "---|" * len(SUMMARY_COLUMNS)]
    for name, c in totals(rows, rules).items():
        if c["total"]:
            out.append("| %s | %s |" % (name, " | ".join(str(c[k]) for k, _ in SUMMARY_COLUMNS)))
    for name in specialty_names(rules):
        group = [r for r in rows if r["specialty"] == name]
        if not group:
            continue
        out += ["", "## %s (%d)" % (name, len(group))]
        for team in sorted({r["team"] for r in group}, key=lambda t: (t == NO_TEAM, t)):
            members = [r for r in group if r["team"] == team]
            out += ["", "### %s (%d)" % (team, len(members)), "",
                    "| Key | Found in | Severity | Summary | Status | Working on it | Planned release | Days open | Needs a decision |",
                    "|---|---|---|---|---|---|---|---|---|"]
            for r in members:
                out.append("| [%s](%s%s) | %s | %s | %s | %s | %s | %s | %s | %s |" % (
                    r["key"], BROWSE, r["key"], r["env"], r["severity"], md(r["summary"]), r["status"],
                    md(r["assignee"] or "nobody"), md(release_text(r)), r["age"], md(flag_text(r))))
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- CLI

def load(args):
    if args.cache:
        with open(args.cache, encoding="utf-8") as fh:
            return json.load(fh), True
    from gen_dashboard import JiraClient   # bearer auth, one /myself check, no retry on 401/403
    return fetch(JiraClient().live_get), False


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cache", help="read {issues, epics} from this JSON file instead of Jira")
    parser.add_argument("--rules", default=RULES_PATH)
    parser.add_argument("--out-html", default=os.path.join(OUT_DIR, "DEFECTS-BY-SPECIALTY.html"))
    parser.add_argument("--out-md", default=os.path.join(OUT_DIR, "DEFECTS-BY-SPECIALTY.md"))
    args = parser.parse_args(argv)
    try:
        data, sample = load(args)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 2
    rules = load_rules(args.rules)
    rows = defect_rows(data, rules)
    generated = datetime.date.today().isoformat()
    for path, text in ((args.out_html, render_page(rows, rules, generated, sample)),
                       (args.out_md, render_markdown(rows, rules, generated, sample))):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    print("%d open SIT/UAT defects%s" % (len(rows), " (sample data)" if sample else ""))
    for name, c in totals(rows, rules).items():
        if c["total"]:
            print("  %-12s %3d  (SIT %d, UAT %d, Critical/High %d, needs a decision %d)" % (
                name, c["total"], c["SIT"], c["UAT"], c["urgent"],
                sum(1 for r in rows if r["specialty"] == name and r["flags"])))
    print("wrote %s\nwrote %s" % (args.out_html, args.out_md))
    return 0


if __name__ == "__main__":
    sys.exit(main())
