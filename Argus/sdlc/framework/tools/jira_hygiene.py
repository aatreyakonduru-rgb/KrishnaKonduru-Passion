"""Jira hygiene: the Acme Claims tickets that do not yet follow the Jira rule book.

Reads the team's epics, recent stories/defects and recent sub-tasks from Jira, runs the checks from
.devin/rules/jira-ticket-standards.yaml plus the rule-book additions (epic owner, thin epic
description, sub-task phase prefix, sprint carry-over, requester label on Approval/Question
sub-tasks), and writes one self-contained page plus a Markdown copy. The same rows are the "Jira
hygiene" tab on the Tech Lead and PO office dashboards (gen_dashboard.py, kind `hygiene`).

Reading only. Jira access goes through gen_dashboard.JiraClient (bearer token, one /myself check,
no retry on 401/403).

    python3 sdlc/framework/tools/jira_hygiene.py              # live Jira
    python3 sdlc/framework/tools/jira_hygiene.py --cache \
        sdlc/framework/tools/fixtures/jira-hygiene-demo.json
"""
import argparse
import collections
import datetime
import html
import json
import os
import re
import sys

import artifact_kit
import roadmap_epics

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
OUT_DIR = os.path.join(ROOT, "sdlc", "framework", "context", "dashboard")
BROWSE = "https://jira.acme.example/browse/"

F_AC = "customfield_10003"
F_POINTS = "customfield_10001"
F_SPRINT = "customfield_10002"
F_EPIC = "customfield_10010"
F_PRIORITY = "customfield_10012"
F_TEAM = "customfield_10004"
F_EPIC_OWNER = "customfield_10019"

TEAM = 'project = ACME AND "IT Team" = Acme-Claims-Web'
JQL = collections.OrderedDict([
    ("epics", TEAM + " AND issuetype = Epic ORDER BY created DESC"),
    ("stories", TEAM + " AND issuetype in (Story, Defect, Bug, Task) AND created >= -120d ORDER BY created DESC"),
    ("subtasks", TEAM + " AND issuetype = Sub-task AND created >= -60d ORDER BY created DESC"),
])
FIELDS = ",".join([
    "summary", "issuetype", "status", "labels", "fixVersions", "timespent", "timeoriginalestimate",
    "assignee", "reporter", "parent", "subtasks", "description", "created", "issuelinks",
    F_AC, F_POINTS, F_SPRINT, F_EPIC, F_PRIORITY, F_TEAM, F_EPIC_OWNER,
])
PAGE_SIZE = 100
MAX_ISSUES = 1000

PHASES = ("DEV", "SIT", "UAT")
ALLOWED_LABELS = ("AI-Used", "AI-NA", "DEMO-NEEDED", "Approval", "Question")
PLACEHOLDER = re.compile(r"please enter acceptance criteria", re.I)
VAGUE = re.compile(r"should work correctly|as per design|as discussed|user friendly|\betc\b", re.I)
NUMBERED = re.compile(r"^\s*(\d+[.)]|[-*#])", re.M)
NOT_STARTED = ("Open", "Backlog", "New", "To Do")
DONE = ("Done", "Closed", "Resolved")
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
TONE = {"high": "hot", "medium": "watch", "low": "info"}

# id -> (severity, rule-book rule, plain-English line, applies to)
CHECKS = collections.OrderedDict([
    ("AC_PLACEHOLDER", ("high", "Rule 7",
                        "Acceptance criteria still show the default \"Please Enter Acceptance Criteria\"",
                        "Story, Sub-task")),
    ("AC_MISSING", ("high", "Rule 7", "Acceptance criteria field is empty", "Story, Epic")),
    ("AC_UNNUMBERED", ("medium", "Rule 7", "Acceptance criteria are prose, not a numbered pass/fail list", "Story")),
    ("AC_VAGUE", ("medium", "Rule 7",
                  "Acceptance criteria contain a phrase a tester cannot mark pass or fail", "Story")),
    ("EPIC_LINK_MISSING", ("high", "Rule 3", "Story has no Epic Link", "Story")),
    ("POINTS_MISSING", ("high", "Rule 8", "Story has started but has no story points", "Story")),
    ("PRIORITY_MISSING", ("medium", "Standard", "Issue Priority is empty", "Story")),
    ("PHASE_SUFFIX_MISSING", ("medium", "Rule 2", "Story title does not end with - DEV, - SIT or - UAT", "Story")),
    ("PHASE_SUFFIX_CASE", ("low", "Rule 2", "Phase suffix is not written exactly as - DEV, - SIT or - UAT", "Story")),
    ("DEFECT_TITLE_PREFIX", ("medium", "Defects",
                             "TennCare SIT/UAT defect title is not 'SIT-TC-PCMH|THL|EoC: …' / 'UAT-TC-…' "
                             "(EoC: <Episode> - …)",
                             "Defect")),
    ("SIBLING_LINK_MISSING", ("high", "Rule 2", "SIT/UAT story has no link back to the earlier phase", "Story")),
    ("STORY_TIME_LOGGED", ("medium", "Rule 8", "Hours are logged on the story instead of its sub-tasks", "Story")),
    ("SPRINT_CARRYOVER", ("medium", "Rule 4", "Story has been carried through three or more sprints", "Story")),
    ("AI_LABEL_MISSING", ("medium", "Rule 8", "No AI-Used / AI-NA label", "Story, Sub-task")),
    ("LABEL_CASE", ("low", "Rule 8", "A label is spelled differently from the allowed list (e.g. AI-USED)",
                    "Story, Sub-task, Epic")),
    ("SUBTASK_PREFIX_MISSING", ("low", "Rule 2", "Sub-task title has no DEV- / SIT- / UAT- prefix", "Sub-task")),
    ("WORKLOG_MISSING", ("low", "Rule 8", "Sub-task is done with an estimate but no hours logged", "Sub-task")),
    ("REQUESTER_LABEL_MISSING", ("medium", "Rule 10",
                                 "Approval/Question sub-task does not say who asked (requested-by- / asked-by-)",
                                 "Sub-task")),
    ("EPIC_OWNER_MISSING", ("medium", "Epics", "Epic has no owner", "Epic")),
    ("EPIC_DESCRIPTION_THIN", ("low", "Epics", "Epic description is a bare phrase", "Epic")),
    ("EPIC_TITLE_DATED", ("low", "Epics", "Epic title carries a phase, sprint or year", "Epic")),
    ("EPIC_SOURCE_STALE", ("low", "Epics",
                           "Epic's source (Confluence page read / document uploaded) is older than %d days — "
                           "ask the PO for the current copy" % roadmap_epics.SOURCE_STALE_DAYS, "Epic")),
])

COLUMNS = ["key", "type", "summary", "status", "assignee", "check", "detail"]
COLUMN_LABELS = {"key": "Ticket", "type": "Type", "summary": "Summary", "status": "Status",
                 "assignee": "Assignee", "check": "What is missing", "detail": "Detail", "rule": "Rule"}


def esc(value):
    return html.escape(str(value if value is not None else ""), quote=True)


def fetch(get, queries=JQL):
    """Every matching issue per query (paged). `get(path, **params)` is a validated Jira GET."""
    out = {}
    for name, jql in queries.items():
        issues, start = [], 0
        while True:
            page = get("/api/2/search", jql=" ".join(jql.split()), startAt=start, maxResults=PAGE_SIZE, fields=FIELDS)
            batch = page.get("issues") or []
            issues.extend(batch)
            start += len(batch)
            if not batch or start >= int(page.get("total") or 0) or start >= MAX_ISSUES:
                break
        out[name] = issues
    return out


def person(field):
    if isinstance(field, dict):
        return field.get("displayName") or field.get("name") or ""
    return ""


def sprint_names(value):
    names = []
    for item in value or []:
        if isinstance(item, dict):
            names.append(item.get("name", ""))
        else:
            found = re.search(r"name=([^,\]]+)", str(item))
            names.append(found.group(1) if found else str(item))
    return names


def ac_of(fields):
    return (fields.get(F_AC) or "").strip()


def labels_of(fields):
    return list(fields.get("labels") or [])


def label_case_issue(labels):
    lowered = {a.lower(): a for a in ALLOWED_LABELS}
    return [lb for lb in labels if lb.lower() in lowered and lb != lowered[lb.lower()]]


def has_ai_label(labels):
    return any(lb.lower().startswith("ai-") for lb in labels)


TENNCARE_RE = re.compile(r"^(SIT|UAT)-TC-(PCMH|THL|EoC): (.+)$")
EOC_RE = re.compile(r"^(SIT|UAT)-TC-EoC: ([^-]+?) - .+$")
TENNCARE_WORDS = {"PCMH": re.compile(r"\bPCMH\b", re.I), "THL": re.compile(r"\b(THL|TLH)\b", re.I),
                  "EoC": re.compile(r"\b(EOC|Episodes?)\b", re.I)}


def tenncare_defect_issue(f):
    """What is wrong with an open TennCare SIT/UAT defect's title, or '' when it follows the prefix rule."""
    summary = (f.get("summary") or "").strip()
    if (f.get("status") or {}).get("name", "") in DONE:
        return ""
    m = TENNCARE_RE.match(summary)
    if m:
        return "" if m.group(2) != "EoC" or EOC_RE.match(summary) else "EoC without '<Episode> - '"
    phase = phase_suffix(summary)
    phase = phase.group(1).upper() if phase else ""
    texts = [summary] + [(lk.get("outwardIssue") or lk.get("inwardIssue") or {}).get("fields", {}).get("summary", "")
                         for lk in f.get("issuelinks") or []]
    for token, rx in TENNCARE_WORDS.items():
        if any(rx.search(t or "") for t in texts):
            return "%s defect, expected '%s-TC-%s: …'" % (token, phase or "SIT|UAT", token)
    return ""


def phase_suffix(summary):
    found = re.search(r"\s*-\s*(dev|sit|uat)\s*$", summary, re.I)
    return found


def has_sibling_link(fields):
    for link in fields.get("issuelinks") or []:
        name = ((link.get("type") or {}).get("name") or "").lower()
        if name in ("tests", "relates", "implements", "depend", "blocks"):
            return True
    return False


def check_epic(issue, add):
    f = issue["fields"]
    desc = (f.get("description") or "").strip()
    if not ac_of(f) or PLACEHOLDER.search(ac_of(f)):
        add("AC_MISSING", "acceptance criteria: %r" % ac_of(f)[:60])
    if not f.get(F_EPIC_OWNER):
        add("EPIC_OWNER_MISSING", "Epic Owner field empty")
    if len(desc.split()) < 12:
        add("EPIC_DESCRIPTION_THIN", "description: %r" % desc[:80])
    if re.search(r"\b(DEV|SIT|UAT|2\d\.\d|20\d\d)\b", f.get("summary") or ""):
        add("EPIC_TITLE_DATED", "title carries a phase, sprint or year")
    stamp = re.search(r"^Source: .*$", desc, re.MULTILINE)
    if stamp and roadmap_epics.source_is_stale(stamp.group()):
        add("EPIC_SOURCE_STALE", stamp.group()[:120])
    bad = label_case_issue(labels_of(f))
    if bad:
        add("LABEL_CASE", "labels: %s" % ", ".join(bad))


def check_story(issue, add):
    f = issue["fields"]
    kind = (f.get("issuetype") or {}).get("name", "")
    summary = f.get("summary") or ""
    status = (f.get("status") or {}).get("name", "")
    labels = labels_of(f)
    ac = ac_of(f)
    if PLACEHOLDER.search(ac):
        add("AC_PLACEHOLDER", "default text still in place")
    elif not ac:
        add("AC_MISSING", "acceptance criteria field empty")
    elif VAGUE.search(ac):
        add("AC_VAGUE", "contains: %s" % VAGUE.search(ac).group(0))
    elif len(NUMBERED.findall(ac)) < 2:
        add("AC_UNNUMBERED", "%d characters, no numbered items" % len(ac))
    if kind == "Story":
        if not f.get(F_EPIC):
            add("EPIC_LINK_MISSING", "Epic Link empty")
        if f.get(F_POINTS) is None and status not in NOT_STARTED:
            add("POINTS_MISSING", "status %s, no points" % status)
        if not f.get(F_PRIORITY):
            add("PRIORITY_MISSING", "Issue Priority empty")
        suffix = phase_suffix(summary)
        if not suffix:
            add("PHASE_SUFFIX_MISSING", "title: %s" % summary[-30:])
        else:
            exact = " - " + suffix.group(1).upper()
            if not summary.endswith(exact):
                add("PHASE_SUFFIX_CASE", "ends with %r" % suffix.group(0))
            if suffix.group(1).upper() in PHASES[1:] and not has_sibling_link(f):
                add("SIBLING_LINK_MISSING", "no Tests/Relates link to the %s story" % PHASES[0])
    if kind == "Defect":
        why = tenncare_defect_issue(f)
        if why:
            add("DEFECT_TITLE_PREFIX", why)
    if (f.get("timespent") or 0) > 0 and f.get("subtasks"):
        add("STORY_TIME_LOGGED", "%.1fh on the story" % (f["timespent"] / 3600.0))
    names = sprint_names(f.get(F_SPRINT))
    if len(names) >= 3:
        add("SPRINT_CARRYOVER", ", ".join(names))
    if not has_ai_label(labels):
        add("AI_LABEL_MISSING", "labels: %s" % (", ".join(labels) or "none"))
    bad = label_case_issue(labels)
    if bad:
        add("LABEL_CASE", "labels: %s" % ", ".join(bad))


def check_subtask(issue, add):
    f = issue["fields"]
    summary = f.get("summary") or ""
    status = (f.get("status") or {}).get("name", "")
    labels = labels_of(f)
    decision = bool(set(labels) & {"Approval", "Question"})
    if PLACEHOLDER.search(ac_of(f)):
        add("AC_PLACEHOLDER", "default text still in place")
    if decision:
        if not any(lb.startswith(("requested-by-", "asked-by-")) for lb in labels):
            add("REQUESTER_LABEL_MISSING", "labels: %s" % ", ".join(labels))
        return
    if not re.match(r"^(DEV|SIT|UAT)-\s", summary):
        add("SUBTASK_PREFIX_MISSING", "title: %s" % summary[:40])
    if not has_ai_label(labels):
        add("AI_LABEL_MISSING", "labels: %s" % (", ".join(labels) or "none"))
    bad = label_case_issue(labels)
    if bad:
        add("LABEL_CASE", "labels: %s" % ", ".join(bad))
    if status in DONE and f.get("timeoriginalestimate") and not f.get("timespent"):
        add("WORKLOG_MISSING", "estimate %.1fh, nothing logged" % (f["timeoriginalestimate"] / 3600.0))


def finding_rows(data):
    """One row per (ticket, check). `data` is {epics, stories, subtasks} as fetch() returns it."""
    rows = []
    for group, checker in (("epics", check_epic), ("stories", check_story), ("subtasks", check_subtask)):
        for issue in data.get(group) or []:
            f = issue.get("fields") or {}

            def add(check, detail, issue=issue, f=f):
                severity, rule, text, _ = CHECKS[check]
                rows.append({
                    "key": issue.get("key", ""), "type": (f.get("issuetype") or {}).get("name", ""),
                    "summary": f.get("summary") or "", "status": (f.get("status") or {}).get("name", ""),
                    "assignee": person(f.get("assignee")), "check": check, "severity": severity,
                    "rule": rule, "text": text, "detail": detail,
                })
            checker(issue, add)
    rows.sort(key=lambda r: (SEVERITY_ORDER[r["severity"]], r["check"], r["key"]))
    return rows


def totals(data):
    return {k: len(data.get(k) or []) for k in JQL}


def by_check(rows):
    out = collections.OrderedDict((c, []) for c in CHECKS)
    for row in rows:
        out[row["check"]].append(row)
    return collections.OrderedDict((c, r) for c, r in out.items() if r)


def attention(rows):
    if not rows:
        return "clear"
    return "hot" if any(r["severity"] == "high" for r in rows) else "watch"


def link(key):
    return '<a href="%s%s" target="_blank" rel="noopener">%s</a>' % (BROWSE, esc(key), esc(key))


def metric(label, value, note=""):
    return ('<div class="a-metric"><div class="a-metric__label">%s</div><div class="a-metric__value">%s</div>'
            '<div class="a-metric__delta">%s</div></div>' % (esc(label), esc(value), esc(note)))


def cell(row, column):
    if column == "key":
        return link(row["key"])
    if column == "check":
        return esc(row["text"])
    return esc(row.get(column, ""))


FILTER_JS = """(function () {
  var root = document.getElementById("%(id)s");
  if (!root) { return; }
  var box = root.querySelector("[data-jh-filter]");
  if (!box) { return; }
  box.addEventListener("input", function () {
    var q = box.value.toLowerCase();
    root.querySelectorAll("[data-jh-row]").forEach(function (tr) {
      tr.hidden = q && tr.textContent.toLowerCase().indexOf(q) < 0;
    });
  });
}());"""


def render_fragment(rows, data, dom_id="jira-hygiene"):
    """The body shared by the dashboard tab and the stand-alone page."""
    if not rows:
        return ""
    counts = totals(data)
    tickets = {r["key"] for r in rows}
    high = [r for r in rows if r["severity"] == "high"]
    groups = by_check(rows)
    parts = ['<div id="%s">' % esc(dom_id)]
    parts.append('<div class="a-grid">%s%s%s%s</div>' % (
        metric("Tickets read", sum(counts.values()), "%d epics, %d stories, %d sub-tasks" % (
            counts["epics"], counts["stories"], counts["subtasks"])),
        metric("Tickets with a gap", len(tickets),
               "%d%% of those read" % (100 * len(tickets) // max(1, sum(counts.values())))),
        metric("Findings", len(rows), "%d high" % len(high)),
        metric("Checks tripped", len(groups), "of %d" % len(CHECKS)),
    ))
    summary_rows = "".join(
        '<tr><td>%s</td><td>%s</td><td><span class="a-badge" data-attention="%s">%s</span></td><td>%d</td></tr>' % (
            esc(CHECKS[c][2]), esc(CHECKS[c][1]), TONE[CHECKS[c][0]], esc(CHECKS[c][0]), len(r))
        for c, r in groups.items())
    parts.append('<h3>By check</h3><div class="a-table-scroll"><table class="a-table"><thead><tr>'
                 "<th>What is missing</th><th>Rule</th><th>Severity</th><th>Tickets</th></tr></thead>"
                 "<tbody>%s</tbody></table></div>" % summary_rows)
    parts.append('<h3>Tickets</h3><div class="a-toolbar"><input class="a-input" type="search" data-jh-filter '
                 'placeholder="Filter by key, person, status or word" aria-label="Filter findings"></div>')
    head = "".join("<th>%s</th>" % esc(COLUMN_LABELS[c]) for c in COLUMNS)
    for check, group in groups.items():
        body = "".join('<tr data-jh-row>%s</tr>' % "".join("<td>%s</td>" % cell(r, c) for c in COLUMNS)
                       for r in group)
        parts.append('<details%s><summary><span class="a-badge" data-attention="%s">%d</span> %s '
                     '<span class="c-muted">· %s</span></summary><div class="a-table-scroll"><table class="a-table">'
                     "<thead><tr>%s</tr></thead><tbody>%s</tbody></table></div></details>" % (
                         " open" if CHECKS[check][0] == "high" else "", TONE[CHECKS[check][0]], len(group),
                         esc(CHECKS[check][2]), esc(CHECKS[check][1]), head, body))
    parts.append('<p class="a-section__note">Checks come from .devin/rules/jira-ticket-standards.yaml and the Jira '
                 "rule book. These patterns were normal practice before the standard existed; the list is here to make "
                 "the rules concrete, not to single anyone out. Reading only — fix the ticket in Jira and the row goes "
                 "away on the next run.</p>")
    parts.append("<script>%s</script></div>" % (FILTER_JS % {"id": dom_id}))
    return "".join(parts)


def render_page(rows, data, generated, sample=False):
    subtitle = "%d findings on %d tickets, as of %s from %s" % (
        len(rows), len({r["key"] for r in rows}), generated, "sample data" if sample else "live Jira")
    body = render_fragment(rows, data) or '<p class="a-empty">Every ticket read follows the rule book.</p>'
    return artifact_kit.render_page("Jira hygiene — tickets that do not yet follow the rule book",
                                    '<section class="a-section">%s</section>' % body, subtitle=esc(subtitle))


def render_markdown(rows, data, generated, sample=False):
    counts = totals(data)
    out = ["# Jira hygiene — tickets that do not yet follow the rule book", "",
           "Generated %s from %s. %d epics, %d stories, %d sub-tasks read; %d findings on %d tickets." % (
               generated, "sample data" if sample else "live Jira", counts["epics"], counts["stories"],
               counts["subtasks"], len(rows), len({r["key"] for r in rows})), ""]
    for check, group in by_check(rows).items():
        sev, rule, text, _ = CHECKS[check]
        out += ["## %s (%d) — %s, %s" % (text, len(group), rule, sev), "",
                "| Ticket | Type | Summary | Status | Assignee | Detail |", "|---|---|---|---|---|---|"]
        out += ["| [%s](%s%s) | %s | %s | %s | %s | %s |" % (
            r["key"], BROWSE, r["key"], r["type"], r["summary"].replace("|", "/"), r["status"],
            r["assignee"], r["detail"].replace("|", "/")) for r in group]
        out.append("")
    return "\n".join(out)


def load(args):
    if args.cache:
        with open(args.cache, encoding="utf-8") as fh:
            return json.load(fh), True
    from gen_dashboard import JiraClient   # bearer auth, one /myself check, no retry on 401/403
    return fetch(JiraClient().live_get), False


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cache", help="read {epics, stories, subtasks} from this JSON file instead of Jira")
    parser.add_argument("--out-html", default=os.path.join(OUT_DIR, "JIRA-HYGIENE.html"))
    parser.add_argument("--out-md", default=os.path.join(OUT_DIR, "JIRA-HYGIENE.md"))
    args = parser.parse_args(argv)
    try:
        data, sample = load(args)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 2
    rows = finding_rows(data)
    generated = datetime.date.today().isoformat()
    for path, text in ((args.out_html, render_page(rows, data, generated, sample)),
                       (args.out_md, render_markdown(rows, data, generated, sample))):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    print("%d findings on %d tickets%s" % (len(rows), len({r["key"] for r in rows}),
                                           " (sample data)" if sample else ""))
    for check, group in by_check(rows).items():
        print("  %-24s %4d  %s" % (check, len(group), CHECKS[check][2]))
    print("wrote %s\nwrote %s" % (args.out_html, args.out_md))
    return 0


if __name__ == "__main__":
    sys.exit(main())
