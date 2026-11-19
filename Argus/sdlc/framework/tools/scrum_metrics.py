"""Scrum Master numbers from Jira: the stand-up check, cycle time, sprint commitment, leave, load, DRE and AI use.

What is counted and the targets come from .devin/rules/scrum-master-metrics.yaml (the Scrum Master's
"a day in your life" call, 2026-10-12). gen_dashboard.py shows each view as a tab of the Scrum Master
lens (panel kind `scrum`, `view: standup | cycle | commitment | leave | load | dre | ai`). Reading only: findings
name the owner so the Scrum Master can ask them; nothing is written to Jira.
"""
import collections
import datetime
import html
import os
import re

import yaml

import capacity_sheet

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
RULES_PATH = os.path.join(ROOT, ".devin", "rules", "scrum-master-metrics.yaml")
BROWSE = "https://jira.acme.example/browse/"
F_POINTS = "customfield_10001"
F_DETECTED = "customfield_10021"
PAGE_SIZE = 100
MAX_ISSUES = 1000
STORY_FIELDS = "summary,issuetype,status,assignee,subtasks,labels,timespent,aggregatetimespent,timeoriginalestimate,duedate,fixVersions,%s" % F_POINTS
SUBTASK_FIELDS = "summary,status,assignee,labels,timespent,timeoriginalestimate,parent"
VIEWS = ("standup", "cycle", "commitment", "leave", "load", "dre", "ai", "cost", "close")
# views that report figures rather than check them: never "hot"
INFO_VIEWS = ("cost",)


def load_rules(path=RULES_PATH):
    try:
        with open(path, encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except OSError:
        return {}


def esc(value):
    return html.escape(str(value if value is not None else ""), quote=True)


def search(get, jql, fields, expand=None):
    """Every issue for `jql` (paged, capped at MAX_ISSUES)."""
    issues, start = [], 0
    extra = {"expand": expand} if expand else {}
    while True:
        page = get("/api/2/search", jql=" ".join(jql.split()), startAt=start, maxResults=PAGE_SIZE,
                   fields=fields, **extra)
        batch = page.get("issues") or []
        issues.extend(batch)
        start += len(batch)
        if not batch or start >= int(page.get("total") or 0) or start >= MAX_ISSUES:
            return issues


HISTORY_PAGE = 25


def add_history(get, issues):
    """Puts each issue's status history (changelog) on it, read separately in small pages so the main reads
    stay quick. Returns "" or, when Jira didn't answer, why the day counts are missing."""
    by_key = {i["key"]: i for i in issues}
    keys = list(by_key)
    try:
        for n in range(0, len(keys), HISTORY_PAGE):
            batch = keys[n:n + HISTORY_PAGE]
            page = get("/api/2/search", jql="key in (%s)" % ", ".join(batch), maxResults=len(batch),
                       fields="status", expand="changelog")
            for got in page.get("issues") or []:
                if got.get("key") in by_key:
                    by_key[got["key"]]["changelog"] = got.get("changelog") or {}
    except Exception as exc:  # noqa: BLE001 - the other numbers still show; the tab says why
        return "Day counts (cycle time, days in status) not read: %s" % exc
    return ""


def quoted(names):
    return ", ".join('"%s"' % n for n in names)


def fetch_sprint(get, sprint_id, scoped=lambda jql: jql):
    """{"stories", "subtasks"} of one sprint: what the stand-up check and the load view read."""
    out = {"stories": [], "subtasks": []}
    if not sprint_id:
        return out
    out["stories"] = search(get, scoped("project = ACME AND sprint = %s AND issuetype in (Story, Defect, Bug)"
                                        % int(sprint_id)), STORY_FIELDS)
    keys = [s["key"] for s in out["stories"] if (s.get("fields") or {}).get("subtasks")]
    for i in range(0, len(keys), 80):
        out["subtasks"] += search(get, "parent in (%s)" % ", ".join(keys[i:i + 80]), SUBTASK_FIELDS)
    return out


def fetch(get, scoped, sprint, rules=None):
    """The issues every view needs. `get` is a validated Jira GET, `scoped(jql)` adds the team clause,
    `sprint` is {"id", "name", "start", "end"} for the active sprint (or {} when there is none)."""
    rules = rules or load_rules()
    cyc = rules.get("cycle_time") or {}
    dre = rules.get("dre") or {}
    out = dict(fetch_sprint(get, sprint.get("id"), scoped),
               sprint={k: sprint.get(k, "") for k in ("name", "start", "end")})
    out["finished"] = search(get, scoped(
        "project = ACME AND issuetype = Story AND status changed to (%s) after -%dd"
        % (quoted(cyc.get("end") or ["Ready For Release", "Closed"]), int(cyc.get("window_days") or 90))),
        "summary,status,assignee")
    out["month_subtasks"] = search(get, scoped(
        "project = ACME AND issuetype = Sub-task AND resolved >= startOfMonth()"), SUBTASK_FIELDS)
    note = add_history(get, out["stories"] + out["finished"])
    if note:
        out["history_note"] = note
    out["defects"] = search(get, scoped("project = ACME AND issuetype in (Defect, Bug) AND created >= %s"
                                        % (dre.get("since") or "startOfYear()")), "summary,status,%s" % F_DETECTED)
    return out


# ---------------------------------------------------------------------------------------------- helpers

def fields(issue):
    return issue.get("fields") or {}


def owner(issue):
    who = fields(issue).get("assignee") or {}
    return who.get("displayName") or who.get("name") or "nobody"


def status(issue):
    return (fields(issue).get("status") or {}).get("name", "")


def done(issue):
    return ((fields(issue).get("status") or {}).get("statusCategory") or {}).get("key") == "done"


def hours(seconds):
    return round((seconds or 0) / 3600.0, 1)


def day(stamp):
    try:
        return datetime.datetime.fromisoformat(str(stamp)[:19]).date()
    except ValueError:
        return None


def status_moves(issue):
    """[(date, to_status)] from the changelog, oldest first."""
    moves = []
    for h in (issue.get("changelog") or {}).get("histories") or []:
        for item in h.get("items") or []:
            if item.get("field") == "status":
                moves.append((day(h.get("created")), item.get("toString") or ""))
    return sorted((m for m in moves if m[0]), key=lambda m: m[0])


def cycle_span(issue, start, end, hold=(), today=None):
    """(days, held) from the first move into `start` to the first move into `end` after it, or to `today`
    when given and it has not finished, with the days in a `hold` status left out; else None."""
    began = held_from = None
    held = 0
    for when, to in status_moves(issue):
        if began is None:
            if to in start:
                began = when
            continue
        if held_from is not None and to not in hold:
            held += (when - held_from).days
            held_from = None
        if to in end:
            return (when - began).days - held, held
        if to in hold and held_from is None:
            held_from = when
    if began is None or today is None:
        return None
    if held_from is not None:
        held += (today - held_from).days
    return (today - began).days - held, held


def cycle_days(issue, start, end, hold=()):
    """Calendar days from the first move into `start` to the first move into `end` after it, without the
    days in a `hold` status, else None."""
    span = cycle_span(issue, start, end, hold)
    return span[0] if span else None


def in_progress_since(issue, start):
    """The day the story last moved into a start status, when that is where it is now."""
    if status(issue) not in start:
        return None
    since = [when for when, to in status_moves(issue) if to in start]
    return since[-1] if since else None


def ai_label(issue, allowed):
    """(label, problem): the exact-case AI label, or the wrong-case variant it carries, or none."""
    labels = fields(issue).get("labels") or []
    exact = [l for l in labels if l in allowed]
    if len(exact) == 1:
        return exact[0], ""
    if len(exact) > 1:
        return "", "carries both %s" % " and ".join(exact)
    variants = [l for l in labels if l.lower().replace("--", "-") in {a.lower() for a in allowed}]
    if variants:
        return "", "label %s is not the exact case (%s)" % (variants[0], " / ".join(allowed))
    return "", "no AI label"


# ---------------------------------------------------------------------------------------------- views

def is_story(issue):
    return (fields(issue).get("issuetype") or {}).get("name") == "Story"


def standup_rows(data, rules=None):
    """What the Scrum Master checks before stand-up, one row per gap, with the person to ask.

    `code` names the gap for Argus: subtasks, story_label, label, estimate, over, closed_no_time,
    no_time, close_story, open_subtasks."""
    rules = rules or load_rules()
    allowed = rules.get("ai_labels") or ["AI-Used", "AI-NA"]
    start = (rules.get("cycle_time") or {}).get("start") or ["In Progress"]
    subs = {}
    for t in data.get("subtasks") or []:
        subs.setdefault((fields(t).get("parent") or {}).get("key", ""), []).append(t)
    rows = []

    def row(issue, code, check, severity, **extra):
        rows.append(dict({"key": issue["key"], "summary": fields(issue).get("summary", ""), "owner": owner(issue),
                          "status": status(issue), "code": code, "check": check, "severity": severity}, **extra))

    cyc = rules.get("cycle_time") or {}
    hint = int(cyc.get("story_days_hint") or 8)
    for s in data.get("stories") or []:
        f = fields(s)
        if (f.get("issuetype") or {}).get("name") in ("Defect", "Bug") and not done(s) and not f.get("fixVersions"):
            row(s, "no_fix_version", "Defect has no fix version", "watch")
        if not is_story(s):
            continue
        span = cycle_span(s, start, cyc.get("end") or ["Ready For Release", "Closed"], cyc.get("hold") or ["On Hold"],
                          datetime.date.today()) if status(s) in start else None
        if span and span[0] > hint and not f.get("duedate"):
            row(s, "no_due_date", "In Progress %d days with no due date" % span[0], "watch", days=span[0])
        listed = {x.get("key") for x in f.get("subtasks") or []}
        kids = [t for t in subs.get(s["key"], []) if t["key"] in listed] or \
            [t for t in data.get("subtasks") or [] if t["key"] in listed]
        if not listed:
            row(s, "subtasks", "Story has no sub-tasks", "watch")
        label, problem = ai_label(s, allowed)
        if problem:
            row(s, "story_label", "Story: " + problem, "watch", label=label)
        spent = f.get("aggregatetimespent") or (f.get("timespent") or 0) + sum(fields(t).get("timespent") or 0 for t in kids)
        if status(s) in start and not spent:
            row(s, "no_time", "In Progress with no time logged", "watch")
        if kids and all(done(t) for t in kids) and not done(s):
            row(s, "close_story", "Every sub-task is closed but the story is still %s" % status(s), "watch")
        elif kids and done(s):
            open_kids = [t["key"] for t in kids if not done(t)]
            if open_kids:
                row(s, "open_subtasks", "Story is %s with %d sub-task(s) still open: %s"
                    % (status(s), len(open_kids), ", ".join(open_kids)), "hot")
    for t in data.get("subtasks") or []:
        f = fields(t)
        label, problem = ai_label(t, allowed)
        if problem:
            row(t, "label", "Sub-task: " + problem, "hot" if done(t) else "watch")
            continue
        if label != allowed[0]:
            continue
        est, spent = f.get("timeoriginalestimate") or 0, f.get("timespent") or 0
        if not est:
            row(t, "estimate", "AI-Used sub-task has no original estimate", "hot")
        elif spent > est:
            row(t, "over", "AI-Used sub-task logged %sh against a %sh estimate (exempted)" % (hours(spent), hours(est)),
                "hot")
        elif done(t) and not spent:
            row(t, "closed_no_time", "AI-Used sub-task closed with no time logged", "hot")
    return rows


def cycle_summary(data, rules=None, today=None):
    rules = rules or load_rules()
    cyc = rules.get("cycle_time") or {}
    start, end = cyc.get("start") or ["In Progress"], cyc.get("end") or ["Ready For Release", "Closed"]
    hold = cyc.get("hold") or ["On Hold"]
    today = today or datetime.date.today()
    finished = [d for d in (cycle_days(s, start, end, hold) for s in data.get("finished") or []) if d is not None]
    open_rows, held_rows, per_person = [], [], collections.defaultdict(list)
    for s in data.get("stories") or []:
        now = status(s)
        if now not in start and now not in hold:
            continue
        span = cycle_span(s, start, end, hold, today)
        row = {"key": s["key"], "summary": fields(s).get("summary", ""), "owner": owner(s), "status": now}
        if now in hold:
            since = [when for when, to in status_moves(s) if to in hold]
            held_rows.append(dict(row, days=span[0] if span else 0,
                                  on_hold=(today - since[-1]).days if since else 0))
            continue
        since = in_progress_since(s, start)
        if since is None:
            continue
        per_person[owner(s)].append(s["key"])
        open_rows.append(dict(row, days=span[0] if span else (today - since).days, held=span[1] if span else 0))
    open_rows.sort(key=lambda r: -r["days"])
    held_rows.sort(key=lambda r: -r["on_hold"])
    return {"average": round(sum(finished) / len(finished), 1) if finished else None, "finished": len(finished),
            "open": open_rows, "on_hold": held_rows,
            "parallel": {p: k for p, k in per_person.items() if len(k) > 1}}


def commitment_summary(data):
    stories = [s for s in data.get("stories") or [] if (fields(s).get("issuetype") or {}).get("name") == "Story"]
    points = [fields(s).get(F_POINTS) for s in stories]
    return {"stories": len(stories), "points": round(sum(p or 0 for p in points), 1),
            "unpointed": [s["key"] for s, p in zip(stories, points) if not p]}


def name_key(name):
    """'Resource 3' and 'Resource 3' match."""
    return " ".join(sorted(re.sub(r"[^a-z ]", " ", (name or "").lower()).split()))


def load_rows(data, rules=None):
    """Each person's sprint story points against the points their leave leaves them (hours ÷ hours_per_point).
    People with stories but no line on the leave page come last, with no capacity."""
    rules = rules or load_rules()
    per_point = float((rules.get("capacity") or {}).get("hours_per_point") or 8)
    people = (data.get("capacity") or {}).get("people") or []
    mine = collections.OrderedDict()
    for s in data.get("stories") or []:
        if not is_story(s):
            continue
        who = fields(s).get("assignee") or {}
        mine.setdefault((who.get("name") or "", owner(s)), []).append(s)
    rows, seen = [], set()
    for p in people:
        got = [k for k in mine if (p.get("jira_user") and k[0] == p["jira_user"]) or name_key(k[1]) == name_key(p["name"])]
        seen.update(got)
        stories = [s for k in got for s in mine[k]]
        pts = round(sum(fields(s).get(F_POINTS) or 0 for s in stories), 1)
        cap = round(float(p.get("hours") or 0) / per_point, 1)
        rows.append({"owner": p["name"], "jira_user": p.get("jira_user") or (got[0][0] if got else ""),
                     "points": pts, "capacity": cap, "hours": p.get("hours") or 0,
                     "days_off": len(p.get("off_days") or []), "keys": [s["key"] for s in stories],
                     "over": round(pts - cap, 1) if pts > cap else 0})
    for k, stories in mine.items():
        if k not in seen and k[1] != "nobody":
            rows.append({"owner": k[1], "jira_user": k[0], "points": round(sum(fields(s).get(F_POINTS) or 0 for s in stories), 1),
                         "capacity": None, "hours": None, "days_off": None, "keys": [s["key"] for s in stories], "over": 0})
    return rows


def unanswered(data):
    """People on the leave page who have marked neither a day off nor 'No leave'."""
    return [p["name"] for p in (data.get("capacity") or {}).get("people") or [] if p.get("answered") is False]


def time_off_rows(data, today=None):
    """(away now or in the next 14 days, people not asked about time off this calendar week) from the planner."""
    today = today or datetime.date.today()
    rows = data.get("time_off") or []
    soon = today + datetime.timedelta(days=14)
    upcoming = sorted((r for r in rows if r.get("from") and r.get("to") and r["from"] <= soon.isoformat()
                       and r["to"] >= today.isoformat()), key=lambda r: r["from"])
    monday = (today - datetime.timedelta(days=today.weekday())).isoformat()
    asked = {r.get("name") for r in rows if (r.get("asked") or "") >= monday}
    names = [p["name"] for p in (data.get("capacity") or {}).get("people") or []] or sorted({r.get("name") for r in rows})
    return upcoming, [n for n in names if n and n not in asked]


def detected_in(issue):
    value = fields(issue).get(F_DETECTED)
    return (value.get("value") if isinstance(value, dict) else value) or "(not set)"


def dre_summary(data, rules=None):
    rules = rules or load_rules()
    prod = set((rules.get("dre") or {}).get("production") or [])
    by_env = collections.Counter(detected_in(d) for d in data.get("defects") or [])
    total = sum(by_env.values())
    production = sum(n for env, n in by_env.items() if env in prod)
    return {"total": total, "production": production, "by_env": by_env.most_common(),
            "dre": round(1 - production / float(total), 3) if total else None,
            "production_keys": [d["key"] for d in data.get("defects") or [] if detected_in(d) in prod]}


def ai_summary(data, rules=None):
    rules = rules or load_rules()
    allowed = rules.get("ai_labels") or ["AI-Used", "AI-NA"]
    counts = collections.Counter()
    est = spent = 0
    devin = 0
    for t in data.get("month_subtasks") or []:
        label, problem = ai_label(t, allowed)
        f = fields(t)
        devin += "devin_created" in (f.get("labels") or [])
        if problem:
            counts["wrong case" if "exact case" in problem else "no label"] += 1
        elif label == allowed[0] and (f.get("timespent") or 0) > (f.get("timeoriginalestimate") or 0) > 0:
            counts["exempted"] += 1
        else:
            counts[label] += 1
            if label == allowed[0]:
                est += f.get("timeoriginalestimate") or 0
                spent += f.get("timespent") or 0
    closed = sum(counts.values())
    labelled = closed - counts["no label"] - counts["wrong case"]
    return {"closed": closed, "used": counts[allowed[0]], "na": counts[allowed[1]], "exempted": counts["exempted"],
            "no_label": counts["no label"], "wrong_case": counts["wrong case"],
            "labelled_pct": round(100.0 * labelled / closed, 1) if closed else None,
            "efficiency_pct": round(100.0 * (est - spent) / est, 1) if est else None,
            "used_estimate_h": hours(est), "used_spent_h": hours(spent), "devin_created": devin}


# ---------------------------------------------------------------------------------------------- render

def link(key):
    return '<a href="%s%s" target="_blank" rel="noopener">%s</a>' % (BROWSE, esc(key), esc(key))


def metric(label, value, note=""):
    return ('<div class="a-metric"><div class="a-metric__label">%s</div><div class="a-metric__value">%s</div>'
            '<div class="a-metric__delta">%s</div></div>' % (esc(label), esc(value), esc(note)))


def grid(*metrics):
    return '<div class="a-grid">%s</div>' % "".join(metrics)


def table(head, rows):
    return ('<div class="a-table-scroll"><table class="a-table"><thead><tr>%s</tr></thead><tbody>%s</tbody>'
            '</table></div>' % ("".join("<th>%s</th>" % esc(h) for h in head),
                                "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % c for c in r) for r in rows)))


def to_confirm(rules, words):
    """The open questions from the rules file that mention any of `words`."""
    hits = [q for q in rules.get("open_questions") or [] if any(w.lower() in q.lower() for w in words)]
    return "".join('<p class="a-section__note">To confirm: %s</p>' % esc(q) for q in hits)


def cost_rows(data, rules=None):
    """Per sprint story: points, hours logged on it and its sub-tasks, the AI-Used share, and cost when
    scrum-master-metrics.yaml sets cost.hourly_rate (blank: hours only, no cost is guessed)."""
    rules = rules or load_rules()
    rate = (rules.get("cost") or {}).get("hourly_rate")
    subs = collections.defaultdict(list)
    for t in data.get("subtasks") or []:
        parent = (fields(t).get("parent") or {}).get("key")
        if parent:
            subs[parent].append(t)
    out = []
    for s in data.get("stories") or []:
        f, kids = fields(s), subs.get(s["key"], [])
        spent = f.get("aggregatetimespent") or (f.get("timespent") or 0) + sum(fields(t).get("timespent") or 0 for t in kids)
        ai = sum(fields(t).get("timespent") or 0 for t in kids
                 if "ai-used" in [str(x).lower() for x in fields(t).get("labels") or []])
        h, points = round(spent / 3600.0, 1), f.get(F_POINTS)
        out.append({"key": s["key"], "summary": f.get("summary") or "", "points": points, "hours": h,
                    "ai_hours": round(ai / 3600.0, 1),
                    "per_point": round(h / float(points), 1) if points and h else None,
                    "cost": round(h * float(rate)) if rate and h else None})
    return sorted(out, key=lambda r: (-r["hours"], r["key"]))


def devin_usage_html(data, rules):
    """Devin sessions per story and stage, the verifier's extra session among them. ACUs only from an export."""
    import devin_usage
    sessions = data.get("devin_sessions")
    if sessions is None:
        return '<p class="a-section__note">Devin sessions per story: not read on this run.</p>'
    export = (rules.get("cost") or {}).get("devin_usage_export")
    rows = devin_usage.rows(sessions, devin_usage.load_acus(export))
    if not rows:
        return '<p class="a-section__note">No Devin session names a story yet.</p>'
    verifier = sum(r["sessions"] for r in rows if r["stage"] == "verifier")
    note = ("ACUs from %s." % export) if export else (
        "The Devin API does not report ACUs per session, so none are shown; set cost.devin_usage_export to a CSV "
        "from Devin's usage page (session_id, acus) to add them.")
    return ("<h3>Devin sessions per story and stage</h3>"
            "<p>%d sessions over %d stories, %d of them the independent verifier. %s</p>" % (
                sum(r["sessions"] for r in rows), len({r["story"] for r in rows}), verifier, esc(note)) +
            table(["Story", "Stage", "Sessions", "Session hours", "ACUs"],
                  [[esc(r["story"]), esc(r["stage"]), esc(r["sessions"]), esc(r["hours"]),
                    esc(r["acus"] if r["acus"] is not None else "—")] for r in rows]))


def close_rows(data, rules=None):
    """/sprint-close-check: one row per story or sub-task in the sprint that is not ready to close, with every gap.

    Story: all its sub-tasks closed, time logged (on its sub-tasks: hours never go on the story itself), an AI
    label, an original estimate, a closing status. Sub-task: hours logged, an AI label, an original estimate,
    a closing status. A closing status is one in sprint_close.accepted_statuses, or any done-category status
    when sprint_close.done_category_counts is on (scrum-master-metrics.yaml)."""
    rules = rules or load_rules()
    allowed = rules.get("ai_labels") or ["AI-Used", "AI-NA"]
    sc = rules.get("sprint_close") or {}
    accepted = set(sc.get("accepted_statuses") or ["Ready for Approval"])
    by_category = sc.get("done_category_counts", True)

    def closing(issue):
        return status(issue) in accepted or (by_category and done(issue))

    subs = {}
    for t in data.get("subtasks") or []:
        subs.setdefault((fields(t).get("parent") or {}).get("key", ""), []).append(t)
    rows = []

    def add(issue, kind, story, gaps):
        if gaps:
            rows.append({"key": issue["key"], "kind": kind, "story": story, "summary": fields(issue).get("summary", ""),
                         "owner": owner(issue), "status": status(issue), "gaps": gaps})

    def common(issue, gaps):
        problem = ai_label(issue, allowed)[1]
        if problem:
            gaps.append(problem[0].upper() + problem[1:])
        if not fields(issue).get("timeoriginalestimate"):
            gaps.append("No original estimate")
        if not closing(issue):
            gaps.append("Status is %s" % (status(issue) or "unknown"))
        return gaps

    for s in data.get("stories") or []:
        if not is_story(s):
            continue
        f = fields(s)
        listed = {x.get("key") for x in f.get("subtasks") or []}
        kids = [t for t in subs.get(s["key"], []) if not listed or t["key"] in listed]
        gaps = []
        still_open = [t["key"] for t in kids if not done(t)]
        if still_open:
            gaps.append("%d sub-task(s) not closed: %s" % (len(still_open), ", ".join(still_open)))
        if not (f.get("aggregatetimespent") or (f.get("timespent") or 0) + sum(fields(t).get("timespent") or 0 for t in kids)):
            gaps.append("No time logged")
        add(s, "Story", s["key"], common(s, gaps))
        for t in kids:
            add(t, "Sub-task", s["key"], common(t, [] if fields(t).get("timespent") else ["No hours logged"]))
    return rows


def render(view, data, rules=None, today=None):
    """(body, count, attention) for one view. An empty body means nothing to show."""
    rules = rules or load_rules()
    t = rules.get("targets") or {}
    sprint = (data.get("sprint") or {}).get("name") or ""
    if view == "standup":
        rows = standup_rows(data, rules)
        if not rows:
            return "", 0, "clear"
        people = collections.Counter(r["owner"] for r in rows)
        body = grid(metric("Gaps to raise at stand-up", len(rows), sprint),
                    metric("People to ask", len(people), ", ".join("%s (%d)" % p for p in people.most_common(3)))) + \
            table(["Ticket", "Summary", "Status", "Owner", "What is missing"],
                  [[link(r["key"]), esc(r["summary"]), esc(r["status"]), esc(r["owner"]), esc(r["check"])] for r in rows])
        return body, len(rows), "hot" if any(r["severity"] == "hot" for r in rows) else "watch"
    if view == "cycle":
        c = cycle_summary(data, rules, today)
        base = t.get("cycle_time_baseline_days")
        hint = (rules.get("cycle_time") or {}).get("story_days_hint")
        if c["average"] is None and not c["open"] and not c["on_hold"]:
            return "", 0, "clear"
        over = [r for r in c["open"] if hint and r["days"] > hint]
        body = grid(metric("Average cycle time", "%s days" % c["average"] if c["average"] is not None else "—",
                           "%d stories finished in the last %s days, time On Hold left out; baseline %s" % (
                               c["finished"], (rules.get("cycle_time") or {}).get("window_days", 90), base)),
                    metric("In progress now", len(c["open"]), "%d past %s days" % (len(over), hint)),
                    metric("People with more than one story in progress", len(c["parallel"]),
                           "; ".join("%s: %s" % (p, ", ".join(k)) for p, k in c["parallel"].items())),
                    metric("On Hold now", len(c["on_hold"]), "waiting on a question or approval; not counted")) + \
            table(["Story", "Summary", "Owner", "Days in progress", "Days on hold before"],
                  [[link(r["key"]), esc(r["summary"]), esc(r["owner"]), esc(r["days"]), esc(r["held"])]
                   for r in c["open"]]) + \
            (table(["On Hold", "Summary", "Owner", "Days on hold now", "Days in progress so far"],
                   [[link(r["key"]), esc(r["summary"]), esc(r["owner"]), esc(r["on_hold"]), esc(r["days"])]
                    for r in c["on_hold"]]) if c["on_hold"] else "") + \
            to_confirm(rules, ["cycle time"])
        hot = (c["average"] is not None and base and c["average"] > base) or bool(c["parallel"]) or bool(over)
        return body, len(c["open"]), "hot" if hot else "info"
    if view == "commitment":
        if not sprint:
            return "", 0, "clear"
        c = commitment_summary(data)
        floor = t.get("story_throughput_floor")
        sheet = data.get("capacity") or {}
        per_point = float((rules.get("capacity") or {}).get("hours_per_point") or 8)
        if sheet.get("people"):
            cap = round(sheet["total_hours"] / per_point, 1)
            cap_note = "%s team hours ÷ %g, from %s" % (format(sheet["total_hours"], "g"), per_point, sheet["file"])
        else:
            cap, cap_note = t.get("team_capacity"), "story points, set in scrum-master-metrics.yaml"
        body = grid(metric("Story points taken into %s" % sprint, c["points"], "%d stories" % c["stories"]),
                    metric("Team capacity", cap, cap_note),
                    metric("Throughput floor", floor, "story points; throughput must not fall below this"),
                    metric("Stories with no points", len(c["unpointed"]), ", ".join(c["unpointed"][:6])))
        if sheet.get("people"):
            body += '<p class="a-section__note">%d sprint days, %g productive hours a day; hours = days in × %g × share of time on the project.</p>' % (
                sheet["sprint_days"], sheet["productive_hours"], sheet["productive_hours"])
            body += table(["Team member", "Role", "Time on project", "Days in", "Days off", "Hours"],
                          [[esc(p["name"]), esc(p["role"]), esc("%d%%" % round(100 * p["allocation"])),
                            esc(p["available_days"]),
                            esc(", ".join(capacity_sheet.day_label(sheet, i) for i in p["off_days"]) or "—"),
                            esc(format(p["hours"], "g"))] for p in sheet["people"]])
        else:
            body += to_confirm(rules, ["capacity sheet"])
        short = cap is not None and c["points"] < float(cap)
        return body, int(c["points"]), "hot" if short or c["unpointed"] else "info"
    if view == "leave":
        sheet = data.get("capacity") or {}
        upcoming, not_asked = time_off_rows(data)
        planner = ""
        if data.get("time_off") is not None:
            planner = grid(metric("Away now or in the next 14 days", len(upcoming),
                                  "from the Time off and backups table on the Sprint Leave page"),
                           metric("Not asked about time off this week", len(not_asked),
                                  ", ".join(not_asked[:6]) or "everyone has been asked this week"))
            if upcoming:
                planner += table(["Team member", "Type", "From", "To", "Stories go to", "Questions go to",
                                  "Approvals go to", "Stories on hold"],
                                 [[esc(r.get("name") or ""), esc(r.get("kind") or "Time off")] +
                                  [esc(r.get(k) or "") for k in ("from", "to", "stories_to", "questions_to",
                                                                 "approvals_to")] +
                                  ["yes" if r.get("hold") else ""] for r in upcoming])
        if not sheet.get("people"):
            return planner, len(upcoming), "info" if planner else "clear"
        days = [i for i, d in enumerate(sheet.get("days") or []) if str(d.get("weekday", "")).upper() != "S"]
        waiting = unanswered(data)
        off = sum(len(p.get("off_days") or []) for p in sheet["people"])
        body = grid(metric("Days off this sprint", off, "across %d people, from %s" % (len(sheet["people"]), sheet.get("file", ""))),
                    metric("Not answered yet", len(waiting), ", ".join(waiting[:6]) or "everyone has marked leave or No leave"))
        head = ["Team member"] + [capacity_sheet.day_label(sheet, i).rsplit(" ", 1)[0] for i in days] + ["Days in", "Hours"]
        body += '<div class="sm-leave">' + table(head, [
            [esc(p["name"]) + (" <em>(not answered)</em>" if p.get("answered") is False else "")] +
            ['<b title="off">Off</b>' if i in set(p.get("off_days") or []) else "·" for i in days] +
            [esc(p["available_days"]), esc(format(p["hours"], "g"))] for p in sheet["people"]]) + "</div>"
        return planner + body, off, "hot" if waiting else "info"
    if view == "load":
        rows = load_rows(data, rules)
        if not sprint or not rows or not (data.get("capacity") or {}).get("people"):
            return "", 0, "clear"
        over = [r for r in rows if r["over"]]
        body = grid(metric("Over their capacity", len(over), ", ".join("%s (+%g)" % (r["owner"], r["over"]) for r in over[:4])),
                    metric("Not on the leave page", sum(1 for r in rows if r["capacity"] is None), "stories but no capacity line")) + \
            table(["Team member", "Points taken", "Capacity (points)", "Days off", "Over by", "Stories"],
                  [[esc(r["owner"]), esc(r["points"]), esc("—" if r["capacity"] is None else r["capacity"]),
                    esc("—" if r["days_off"] is None else r["days_off"]), esc(r["over"] or "—"),
                    " ".join(link(k) for k in r["keys"])] for r in rows]) + \
            '<p class="a-section__note">Capacity = hours after leave ÷ %g. Ask anyone over how they plan to handle it: move a story out, pair, or split.</p>' % float((rules.get("capacity") or {}).get("hours_per_point") or 8)
        return body, len(over), "hot" if over else "info"
    if view == "dre":
        d = dre_summary(data, rules)
        if not d["total"]:
            return "", 0, "clear"
        body = grid(metric("Defect removal efficiency", d["dre"], "1 − production ÷ all defects"),
                    metric("Production defects", d["production"], ", ".join(d["production_keys"][:6])),
                    metric("Defects in every environment", d["total"], "created since %s" % (
                        (rules.get("dre") or {}).get("since") or "startOfYear()"))) + \
            table(["Defect Detected In", "Defects"], [[esc(env), esc(n)] for env, n in d["by_env"]]) + \
            to_confirm(rules, ["DRE"])
        return body, d["production"], "hot" if d["production"] else "info"
    if view == "ai":
        a = ai_summary(data, rules)
        if not a["closed"]:
            return "", 0, "clear"
        body = grid(metric("Sub-tasks closed this month", a["closed"], "%d AI-Used, %d AI-NA" % (a["used"], a["na"])),
                    metric("Labelled", "%s%%" % a["labelled_pct"], "target %s%%" % t.get("ai_adoption_pct", 100)),
                    metric("No label", a["no_label"], "plus %d in the wrong case" % a["wrong_case"]),
                    metric("Exempted", a["exempted"], "AI-Used, logged over the estimate"),
                    metric("Created by Devin", a["devin_created"], "closed sub-tasks labelled devin_created"),
                    metric("AI efficiency", "%s%%" % a["efficiency_pct"] if a["efficiency_pct"] is not None else "—",
                           "%sh logged against %sh estimated on AI-Used; target %s%%" % (
                               a["used_spent_h"], a["used_estimate_h"], t.get("ai_efficiency_pct", 30))))
        short = a["labelled_pct"] is not None and a["labelled_pct"] < float(t.get("ai_adoption_pct", 100))
        short = short or (a["efficiency_pct"] is not None and a["efficiency_pct"] < float(t.get("ai_efficiency_pct", 30)))
        return body, a["no_label"] + a["wrong_case"] + a["exempted"], "hot" if short or a["exempted"] else "info"
    if view == "cost":
        rows = cost_rows(data, rules)
        if not rows:
            return "", 0, "clear"
        rate = (rules.get("cost") or {}).get("hourly_rate")
        none = [r for r in rows if not r["hours"]]
        body = grid(metric("Hours logged", round(sum(r["hours"] for r in rows), 1), "%d stories in %s" % (len(rows), sprint)),
                    metric("No time logged", len(none), "cost unknown until time is logged"),
                    metric("Cost", sum(r["cost"] or 0 for r in rows) if rate else "—",
                           "hours × %s an hour" % rate if rate else
                           "no hourly rate set (cost.hourly_rate in scrum-master-metrics.yaml)")) + \
            table(["Story", "Summary", "Points", "Hours logged", "Of which AI-Used", "Hours per point", "Cost"],
                  [[link(r["key"]), esc(r["summary"]), esc(r["points"] if r["points"] is not None else "—"),
                    esc(r["hours"]), esc(r["ai_hours"]),
                    esc(r["per_point"] if r["per_point"] is not None else "—"),
                    esc(r["cost"] if r["cost"] is not None else "—")] for r in rows])
        body += devin_usage_html(data, rules)
        return body, len(none), "watch" if none else "info"
    if view == "close":
        stories = [x for x in data.get("stories") or [] if is_story(x)]
        if not stories:
            return "", 0, "clear"
        rows = close_rows(data, rules)
        blocked = {r["story"] for r in rows}
        body = grid(metric("Stories in the sprint", len(stories), sprint),
                    metric("Ready to close", len(stories) - len(blocked), "the story and all its sub-tasks pass"),
                    metric("Exceptions", len(rows), "stories and sub-tasks with something missing")) + \
            to_confirm(rules, ["Sprint close"])
        if not rows:
            return body + '<p class="a-section__note">Every story and sub-task in the sprint passes.</p>', 0, "info"
        body += table(["Ticket", "Type", "Story", "Summary", "Status", "Owner", "What is missing"],
                      [[link(r["key"]), esc(r["kind"]), link(r["story"]), esc(r["summary"]), esc(r["status"]),
                        esc(r["owner"]), esc("; ".join(r["gaps"]))] for r in rows])
        return body, len(rows), "hot"
    return "", 0, "clear"
