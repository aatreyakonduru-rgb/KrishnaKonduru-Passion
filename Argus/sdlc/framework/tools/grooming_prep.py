"""Grooming prep: what a Product Owner sorts out before the next grooming call.

Resource 17's grooming routine, step by step: read the roadmap for this sprint and next, find roadmap
items that have no story yet (and stories close enough to copy), list the stories that are not ready to
groom, find DEV stories in the sprint whose SIT or UAT story was never created, work out who has to be
on the call, and draft the agenda, the group-chat message and a backup plan. Nothing here writes to Jira
or sends anything: Argus turns each row into a button whose change is previewed first, and the
dashboard shows the same lists read only.

Rules that depend on the PO (what counts as "similar", which partner teams join, their DLs) are read
from docs/knowledge-base/SHARED/grooming.yaml and shown on the page as assumptions until
she confirms them.

    python3 grooming_prep.py --cache backlog.json     the lists as JSON, from a saved story list
"""

import argparse
import datetime
import html
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
PLAN_PATH = os.path.join(ROOT, "sdlc", "framework", "context", "roadmap", "year-plan.yaml")
TEAMS_PATH = os.path.join(ROOT, "docs", "knowledge-base", "SHARED", "delivery-teams.yaml")
SETTINGS_PATH = os.path.join(ROOT, "docs", "knowledge-base", "SHARED", "grooming.yaml")
SETTINGS_REL = "docs/knowledge-base/SHARED/grooming.yaml"
ROADMAP_PATH = os.path.join(ROOT, "sdlc", "framework", "context", "roadmap", "sprint-roadmap.yaml")
ROADMAP_REL = "sdlc/framework/context/roadmap/sprint-roadmap.yaml"
PLANNED = (("DEV", r"\bdev"), ("SIT", r"\bsit\b"), ("UAT", r"\buat\b"))

DEFAULTS = {
    "found_at": 0.67,
    "similar_at": 0.34,
    "groom_labels": ["needs_grooming", "needs_split", "needs-grooming", "needs-split"],
    "split_at": 13,
    "core_roles": ["Product Owner", "Scrum Master", "Dev lead", "Solution Lead", "Testing"],
    "partner_teams": {},
    "dls": {},
    "assumptions": [],
}
STOP = {"the", "and", "for", "with", "from", "into", "of", "to", "in", "on", "an", "story", "stories", "dev",
        "sit", "uat", "part", "new", "ui", "acme", "phase"}
PHASE_TAIL = re.compile(r"[\s\-\u2013\u2014:]*\b(DEV|SIT|UAT)\b\s*$", re.I)
PHASE_HEAD = re.compile(r"^\s*\b(DEV|SIT|UAT)\b\s*[\-\u2013\u2014:]+\s*", re.I)
SPRINT_RE = re.compile(r"(\d{2})\.(\d)\.(\d+)(?:\s*\(\s*(\d{1,2})/(\d{1,2})\s*-\s*(\d{1,2})/(\d{1,2})\s*\))?")
NO_AC = re.compile(r"^\s*(tbd|todo|n/?a|none|-+|\.+)?\s*$", re.I)


def read_yaml(path):
    """The YAML file, or None when it is missing or PyYAML is not installed (an Argus PC may not have it)."""
    try:
        import yaml
    except ImportError:
        return None
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def settings(data=None):
    out = dict(DEFAULTS)
    out.update({k: v for k, v in (data or {}).items() if v is not None})
    return out


# ---------------------------------------------------------------- sprints

def sprint_token(name):
    m = SPRINT_RE.search(name or "")
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def sprint_dates(name):
    m = SPRINT_RE.search(name or "")
    if not m or not m.group(4):
        return None, None
    year = 2000 + int(m.group(1))
    start = datetime.date(year, int(m.group(4)), int(m.group(5)))
    end_year = year + 1 if int(m.group(6)) < int(m.group(4)) else year
    return start, datetime.date(end_year, int(m.group(6)), int(m.group(7)))


def order_sprints(sprints, stories, today=None):
    """(current, next, after) sprint names. Board sprints when Argus could read them; otherwise the
    sprint names on the stories, ordered by their 26.4.2 number, with today inside the current one."""
    today = today or datetime.date.today()
    if sprints:
        active = [s.get("name", "") for s in sprints if s.get("state") == "active"]
        future = sorted((s for s in sprints if s.get("state") == "future"),
                        key=lambda s: (s.get("start") or "9999", sprint_token(s.get("name")) or (99, 9, 99)))
        names = [s.get("name", "") for s in future]
        current = active[-1] if active else ""
    else:
        seen = sorted({s.get("sprint") for s in stories if sprint_token(s.get("sprint"))}, key=sprint_token)
        current, names = "", []
        for i, name in enumerate(seen):
            start, end = sprint_dates(name)
            if start and start <= today <= end:
                current, names = name, seen[i + 1:]
                break
        if not current and seen:
            started = [n for n in seen if (sprint_dates(n)[0] or today) <= today]
            current = started[-1] if started else seen[0]
            names = seen[seen.index(current) + 1:]
    return current, (names[0] if names else ""), (names[1] if len(names) > 1 else "")


# ---------------------------------------------------------------- titles

def phase(summary):
    m = PHASE_TAIL.search(summary or "") or PHASE_HEAD.search(summary or "")
    return m.group(1).upper() if m else ""


def base(summary):
    text = PHASE_HEAD.sub("", PHASE_TAIL.sub("", summary or ""))
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def words(text):
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) >= 2 and w not in STOP}


def similarity(wanted, text):
    """Share of the wanted words that the other title also has: 1.0 means every word is there."""
    if not wanted:
        return 0.0
    return len(wanted & words(text)) / float(len(wanted))


def points_of(story):
    try:
        return float(story.get("points") or 0)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------- the year plan

def plan_items(plan):
    """Year-plan rows still due this plan year: foundational stories and specialty programs."""
    out = []
    for cap in (plan or {}).get("foundational") or []:
        for row in cap.get("stories") or []:
            if row.get("status") == "this_year":
                out.append({"name": row.get("name", ""), "capability": cap.get("capability", ""),
                            "jira": row.get("jira") or []})
    for row in ((plan or {}).get("speciality") or {}).get("programs") or []:
        if row.get("status") == "this_year":
            out.append({"name": row.get("name", ""), "capability": "Specialty program", "jira": row.get("jira") or []})
    return out


def roadmap_gaps(items, stories, epics, found_at, similar_at):
    """(gaps, found): roadmap rows with no matching story or epic, each with the closest stories to copy."""
    pool = [dict(s, kind="story") for s in stories] + [dict(e, kind="epic") for e in epics]
    gaps, found = [], []
    for item in items:
        if item["jira"]:
            found.append(dict(item, match=", ".join(item["jira"])))
            continue
        wanted = words(item["name"])
        if len(wanted) < 2:
            wanted |= words(item["capability"])
        scored = sorted(((similarity(wanted, p.get("summary")), p) for p in pool), key=lambda x: -x[0])
        if scored and scored[0][0] >= found_at:
            found.append(dict(item, match=scored[0][1].get("key", "")))
            continue
        similar = [{"key": p.get("key", ""), "summary": p.get("summary", ""), "kind": p["kind"],
                    "parent": p.get("parent", ""), "score": round(score, 2)} for score, p in scored[:3] if score >= similar_at]
        gaps.append(dict(item, similar=similar))
    return gaps, found


def by_epic(stories, epics, current, nxt):
    names = {e.get("key"): e.get("summary", "") for e in epics}
    rows = {}
    for s in stories:
        if s.get("sprint") not in (current, nxt) or not s.get("sprint"):
            continue
        key = s.get("parent") or ""
        row = rows.setdefault(key, {"epic": key, "name": names.get(key, "") or ("No epic" if not key else key),
                                    "current": 0, "current_points": 0, "next": 0, "next_points": 0})
        slot = "current" if s.get("sprint") == current else "next"
        row[slot] += 1
        row[slot + "_points"] += points_of(s)
    return sorted(rows.values(), key=lambda r: (-(r["current"] + r["next"]), r["name"]))


# ---------------------------------------------------------------- stories

def not_ready(stories, nxt, cfg):
    """Stories for the next sprint, or labelled for grooming, that cannot be estimated yet, and why."""
    labels = {l.lower() for l in cfg["groom_labels"]}
    rows = []
    for s in stories:
        flagged = [l for l in s.get("labels") or [] if l.lower() in labels]
        if not (nxt and s.get("sprint") == nxt) and not flagged:
            continue
        missing = []
        if "acceptance" in s and NO_AC.match(s.get("acceptance") or ""):
            missing.append("no acceptance criteria")
        pts = points_of(s)
        if not pts:
            missing.append("no points")
        elif pts >= cfg["split_at"]:
            missing.append("%g points: split it" % pts)
        missing += ["labelled %s" % l for l in flagged]
        if missing:
            rows.append({"key": s.get("key", ""), "summary": s.get("summary", ""), "sprint": s.get("sprint", "") or "Backlog",
                         "parent": s.get("parent", ""), "reporter": s.get("reporter", ""),
                         "assignee": s.get("assignee", ""), "missing": missing})
    return rows


def missing_phases(stories, current, nxt, after):
    """DEV stories in the current sprint with no SIT or UAT story, and SIT stories with no UAT story.
    Siblings are matched by title without the phase, so "Contract sync - DEV" finds "Contract sync - SIT"."""
    by_base = {}
    for s in stories:
        p = phase(s.get("summary"))
        if p:
            by_base.setdefault(base(s.get("summary")), {}).setdefault(p, []).append(s)

    def sibling(s, want):
        exact = by_base.get(base(s.get("summary")), {}).get(want)
        if exact:
            return exact[0]
        wanted = words(base(s.get("summary")))
        for group in by_base.values():
            for other in group.get(want, []):
                if wanted and similarity(wanted, base(other.get("summary"))) >= 0.8:
                    return other
        return None

    rows = []
    for s in stories:
        if not current or s.get("sprint") != current:
            continue
        p = phase(s.get("summary"))
        wants = [("SIT", nxt), ("UAT", after)] if p == "DEV" else [("UAT", nxt)] if p == "SIT" else []
        for want, where in wants:
            other = sibling(s, want)
            title = PHASE_TAIL.sub("", s.get("summary", "")).strip() + " - " + want
            if other is None:
                rows.append({"key": s.get("key", ""), "summary": s.get("summary", ""), "phase": want,
                             "problem": "no %s story" % want, "sprint": where or "the sprint after", "title": title,
                             "other": ""})
            elif not other.get("sprint"):
                rows.append({"key": s.get("key", ""), "summary": s.get("summary", ""), "phase": want,
                             "problem": "%s story %s is not in a sprint" % (want, other.get("key", "")),
                             "sprint": where or "the sprint after", "title": "", "other": other.get("key", "")})
    return rows


# ---------------------------------------------------------------- people

def _names(who):
    return [n.strip() for n in re.split(r",| or ", who or "") if n.strip()]


def core_people(teams, cfg):
    ui = next((t for t in (teams or {}).get("teams") or [] if t.get("key") == "ui"), {})
    out = []
    for want in cfg["core_roles"]:
        for p in ui.get("people") or []:
            if p.get("role", "").lower().startswith(want.lower()):
                out.append({"role": p.get("role", ""), "who": p.get("who", "")})
    return out


def partner_contacts(team):
    return [{"role": p.get("role", ""), "who": p.get("who", "")} for p in team.get("people") or []
            if re.search(r"product owner|lead", p.get("role", ""), re.I)]


def invitees(rows, epics, teams, cfg):
    """Per story: the UI team core, the people on the story, and partner teams the story or epic names."""
    names = {e.get("key"): e.get("summary", "") for e in epics}
    by_key = {t.get("key"): t for t in (teams or {}).get("teams") or []}
    out = []
    for r in rows:
        text = " ".join([r.get("summary", ""), names.get(r.get("parent"), "")]).lower()
        partners = []
        for key, phrases in (cfg["partner_teams"] or {}).items():
            if any(re.search(r"\b%s\b" % re.escape(p.lower()), text) for p in phrases or []):
                team = by_key.get(key, {})
                partners.append({"team": team.get("name", key), "key": key, "contacts": partner_contacts(team),
                                 "dl": (cfg["dls"] or {}).get(key, "")})
        on_story = [n for n in (r.get("reporter"), r.get("assignee")) if n and n != "Unassigned"]
        out.append({"key": r.get("key", ""), "summary": r.get("summary", ""), "on_story": on_story, "partners": partners})
    return out


# ---------------------------------------------------------------- drafts

def agenda(sprint, ready_rows, gaps, phases, planned=None):
    """Stories for the upcoming sprint first, then the sprints after it (the PO's order)."""
    lines = ["Grooming%s" % (" for " + sprint if sprint else ""), ""]
    n = 0
    ready_rows = sorted(ready_rows, key=lambda r: sprint_token(r.get("sprint") or "") or (999,))
    for r in ready_rows:
        n += 1
        lines.append("%d. %s %s: %s" % (n, r["key"], r["summary"], ", ".join(r["missing"])))
    if gaps:
        lines += ["", "Roadmap items with no story yet:"] + ["- %s (%s)" % (g["name"], g["capability"]) for g in gaps]
    if planned:
        lines += ["", "On the roadmap with no story yet:"] + ["- %s %s %s: %s" % (p["token"], p["epic"] or "(no epic)", p["name"], p["problem"])
                                                            for p in planned]
    if phases:
        lines += ["", "SIT and UAT stories to create:"] + ["- %s: %s" % (p["key"], p["problem"]) for p in phases]
    return "\n".join(lines)


def chat(sprint, core, people):
    must = sorted({n for c in core for n in _names(c["who"])} |
                  {n for p in people for n in p["on_story"]} |
                  {n for p in people for t in p["partners"] for c in t["contacts"] for n in _names(c["who"])})
    return ("Hi all, grooming%s is coming up. Must attend: %s. Please reply here by end of day if you can't make it, "
            "so we can plan around it." % (" for " + sprint if sprint else "", ", ".join(must) or "(add names)"))


# ---------------------------------------------------------------- the PO's sprint roadmap

def read_sheet_rows(path, tab):
    """{row: {col index: text}} for one tab of an .xlsx, stdlib only."""
    import zipfile
    import xml.etree.ElementTree as ET
    m, r = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}", \
        "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    z = zipfile.ZipFile(path)
    strings = []
    if "xl/sharedStrings.xml" in z.namelist():
        strings = ["".join(t.text or "" for t in si.iter(m + "t"))
                   for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall(m + "si")]
    rels = {x.get("Id"): x.get("Target") for x in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
    for sheet in ET.fromstring(z.read("xl/workbook.xml")).find(m + "sheets"):
        if sheet.get("name").strip() != tab:
            continue
        target = rels[sheet.get(r + "id")].lstrip("/")
        target = target if target.startswith("xl/") else "xl/" + target
        rows = {}
        for c in ET.fromstring(z.read(target)).iter(m + "c"):
            v = c.find(m + "v")
            if c.get("t") == "inlineStr":
                val = "".join(t.text or "" for t in c.iter(m + "t"))
            elif v is None:
                continue
            else:
                val = strings[int(v.text)] if c.get("t") == "s" else v.text
            ref = re.match(r"([A-Z]+)(\d+)", c.get("r"))
            col = 0
            for ch in ref.group(1):
                col = col * 26 + ord(ch) - 64
            if str(val).strip():
                rows.setdefault(int(ref.group(2)), {})[col - 1] = str(val)
        return rows
    raise ValueError("the workbook has no tab called %s" % tab)


def parse_roadmap(rows, source=""):
    """The PO's sprint roadmap tab: a header row of sprint numbers, then one row per epic
    ("ACME-123\nEpic name" | feature | the plan text under each sprint | Notes)."""
    head = next((n for n in sorted(rows) if sum(1 for v in rows[n].values() if re.fullmatch(r"\d+\.\d+\.\d+", v.strip())) >= 3), None)
    if head is None:
        raise ValueError("no row of sprint numbers (26.4.2, 26.4.3, ...) on the tab")
    cols = {k: v.strip() for k, v in rows[head].items() if re.fullmatch(r"\d+\.\d+\.\d+", v.strip())}
    notes = next((k for k, v in rows[head].items() if v.strip().lower() == "notes"), None)
    dates = rows.get(head - 1, {})
    out = {"source": source, "sprints": {t: " ".join(dates.get(k, "").split()) for k, t in sorted(cols.items())}, "epics": []}
    for n in sorted(rows):
        if n <= head:
            continue
        r = rows[n]
        first = " ".join((r.get(0) or "").split())
        if first.lower() == "distant future":
            break
        m = re.match(r"(ACME-\d+)\s*(.*)", first)
        plan = {cols[k]: " ".join(v.split()) for k, v in r.items() if k in cols}
        if not (first or r.get(1)) or not plan:
            continue
        out["epics"].append({"key": m.group(1) if m else "", "name": (m.group(2) if m else first) or "",
                             "feature": " ".join((r.get(1) or "").split()), "plan": plan,
                             "note": " ".join((r.get(notes) or "").split()) if notes is not None else ""})
    return out


def sprint_roadmap(path=ROADMAP_PATH):
    return read_yaml(path)


def token_text(name):
    t = sprint_token(name or "")
    return ".".join(str(x) for x in t) if t else ""


def planned_phases(text):
    low = (text or "").lower()
    return [p for p, rx in PLANNED if re.search(rx, low)]


def roadmap_phases(sheet, stories, current, nxt):
    """Each epic's plan for this sprint and next, against its stories in Jira: a planned DEV, SIT or UAT with
    no story of that phase in that sprint is a gap; a row with no epic key is a gap too."""
    rows = []
    for sprint in (current, nxt):
        token = token_text(sprint)
        if not token:
            continue
        for e in (sheet or {}).get("epics") or []:
            text = (e.get("plan") or {}).get(token, "")
            if not text:
                continue
            mine = [s for s in stories if e.get("key") and s.get("parent") == e["key"] and token_text(s.get("sprint")) == token]
            for ph in planned_phases(text) or [""]:
                have = [s for s in mine if (phase(s.get("summary")) or "DEV") == ph] if ph else mine
                if have and e.get("key"):
                    continue
                rows.append({"sprint": sprint, "token": token, "epic": e.get("key", ""), "name": e.get("name", ""),
                             "feature": e.get("feature", ""), "phase": ph, "plan": text, "note": e.get("note", ""),
                             "problem": "no epic in Jira" if not e.get("key") else
                             ("no %s story in %s" % (ph, token) if ph else "no story in %s" % token)})
    return rows


def analyse_with_roadmap(*args, **kw):
    return analyse(*args, sheet=sprint_roadmap(), **kw)


def analyse(stories, epics, sprints=None, plan=None, teams=None, cfg=None, today=None, sheet=None):
    cfg = settings(cfg)
    stories = [s for s in stories if (s.get("type") or "Story") != "Epic"]
    current, nxt, after = order_sprints(sprints or [], stories, today)
    planned = roadmap_phases(sheet, stories, current, nxt) if sheet else []
    gaps, found = ([], 0) if sheet else roadmap_gaps(plan_items(plan), stories, epics, cfg["found_at"], cfg["similar_at"])
    ready = not_ready(stories, nxt, cfg)
    phases = missing_phases(stories, current, nxt, after)
    core = core_people(teams, cfg)
    people = invitees(ready, epics, teams, cfg)
    backup = [p["key"] for p in people if not p["partners"]]
    notes = []
    if plan is None and not sheet:
        notes.append("The year plan was not read, so roadmap gaps are not shown.")
    if teams is None:
        notes.append("delivery-teams.yaml was not read, so the UI team and partner contacts are not shown.")
    return {
        "current": current, "next": nxt, "after": after,
        "roadmap": by_epic(stories, epics, current, nxt),
        "gaps": gaps, "found": found if isinstance(found, int) else len(found), "planned": planned,
        "roadmap_source": (sheet or {}).get("source", "") if sheet else "year plan",
        "not_ready": ready, "phases": phases,
        "core": core, "people": people, "backup": backup,
        "agenda": agenda(nxt, ready, gaps, phases, planned), "chat": chat(nxt, core, people),
        "assumptions": list(cfg["assumptions"] or []), "notes": notes,
        "settings_file": SETTINGS_REL,
        "count": len(gaps) + len(ready) + len(phases) + len(planned),
    }


def context():
    """(plan, teams, settings) from the repository; any of them None when it could not be read."""
    return read_yaml(PLAN_PATH), read_yaml(TEAMS_PATH), read_yaml(SETTINGS_PATH)


def rows_from_issues(issues, fields):
    """Raw Jira search issues -> Argus story rows analyse() reads. `fields` names the custom field
    ids: points, sprint, acceptance, epic_link."""
    out = []
    for issue in issues or []:
        f = issue.get("fields") or {}
        sprint = f.get(fields["sprint"]) or []
        name = ""
        if sprint:
            last = sprint[-1]
            if isinstance(last, dict):
                name = last.get("name", "")
            else:
                m = re.search(r"name=([^,\]]+)", str(last))
                name = m.group(1) if m else ""
        ac = f.get(fields["acceptance"])
        out.append({
            "key": issue.get("key", ""), "summary": f.get("summary", ""),
            "type": (f.get("issuetype") or {}).get("name", ""), "status": (f.get("status") or {}).get("name", ""),
            "assignee": (f.get("assignee") or {}).get("displayName", "Unassigned"),
            "reporter": (f.get("reporter") or {}).get("displayName", ""),
            "points": f.get(fields["points"]) or "", "sprint": name, "labels": f.get("labels") or [],
            "parent": (f.get("parent") or {}).get("key", "") or f.get(fields["epic_link"]) or "",
            "acceptance": ac if isinstance(ac, str) else str((ac or {}).get("value", "") if isinstance(ac, dict) else ac or ""),
        })
    return out


# ---------------------------------------------------------------- HTML

def esc(value):
    return html.escape(str(value if value is not None else ""))


def _table(head, rows, caption):
    if not rows:
        return ""
    return ('<div class="a-table-scroll"><table class="a-table"><caption class="a-visually-hidden">%s</caption>'
            '<thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>'
            % (esc(caption), "".join('<th scope="col">%s</th>' % esc(h) for h in head),
               "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % c for c in r) for r in rows)))


def _btn(label, **data):
    attrs = " ".join('data-%s="%s"' % (k.replace("_", "-"), esc(v)) for k, v in data.items())
    return '<button type="button" class="a-btn a-btn--outline gp-act" %s>%s</button>' % (attrs, esc(label))


def _key(key, browse):
    return '<a href="%s%s" target="_blank" rel="noopener">%s</a>' % (esc(browse), esc(key), esc(key)) if browse and key else esc(key)


def render(data, browse="", actions=False):
    """The six steps as HTML. With actions the rows carry buttons Argus wires up; without, read only."""
    d = data
    act = (lambda label, **kw: _btn(label, **kw)) if actions else (lambda label, **kw: "")
    parts = ['<p class="gp-line">Current sprint: <b>%s</b>. Next sprint: <b>%s</b>. Nothing changes in Jira until you '
             'press a button, read the preview and approve it.</p>' % (esc(d["current"] or "not found"), esc(d["next"] or "not found"))]
    for note in d.get("notes") or []:
        parts.append('<p class="gp-line gp-warn">%s</p>' % esc(note))

    parts.append("<h3>1. Roadmap: this sprint and next</h3>")
    parts.append(_table(["Epic", "This sprint", "Next sprint"],
                        [[_key(r["epic"], browse) + " " + esc(r["name"]) if r["epic"] else esc(r["name"]),
                          "%d stories, %g pts" % (r["current"], r["current_points"]),
                          "%d stories, %g pts" % (r["next"], r["next_points"])] for r in d["roadmap"]],
                        "Stories per epic in this sprint and next") or '<p class="gp-line">No stories in either sprint.</p>')

    parts.append("<h3>2. Roadmap items with no story yet</h3>")
    if d.get("planned") is not None and d.get("roadmap_source") not in ("", "year plan"):
        parts.append('<p class="gp-line">From %s: what each epic plans for this sprint and next, against its stories in Jira.</p>'
                     % esc(d["roadmap_source"]))
        parts.append(_table(["Sprint", "Epic", "Planned", "Problem", ""],
                            [[esc(p["token"]), (_key(p["epic"], browse) + " " if p["epic"] else "") + esc(p["name"]) +
                              ('<br><span class="gp-sub">%s</span>' % esc(p["note"]) if p["note"] else ""),
                              esc(p["plan"]), esc(p["problem"]),
                              act("Write new", gpnew=("%s - %s" % (p["feature"] or p["name"], p["phase"])) if p["phase"] else (p["feature"] or p["name"]))]
                             for p in d["planned"]], "Roadmap gaps") or
                     '<p class="gp-line">Every planned phase this sprint and next has a story.</p>')
    else:
        parts.append('<p class="gp-line">Year-plan rows due this year, compared with every open story and epic by the '
                     'words in their titles. Rows that already have a story: %d.</p>' % d["found"])
        parts.append(_table(["Roadmap item", "Similar stories to copy", ""],
                            [[esc(g["name"]) + '<br><span class="gp-sub">%s</span>' % esc(g["capability"]),
                              "<br>".join("%s %s" % (_key(s["key"], browse), esc(s["summary"])) for s in g["similar"]) or "None close",
                              "".join(act("Copy " + s["key"], gpclone=s["key"]) for s in [x for x in g["similar"] if x["kind"] == "story" and x["parent"]][:1]) +
                              act("Write new", gpnew=g["name"])] for g in d["gaps"]],
                            "Roadmap gaps") or '<p class="gp-line">Every roadmap row due this year has a story.</p>')

    parts.append("<h3>3. Not ready to groom</h3>")
    parts.append(_table(["Story", "Sprint", "What is missing", ""],
                        [[_key(r["key"], browse) + " " + esc(r["summary"]), esc(r["sprint"]), esc(", ".join(r["missing"])),
                          act("Groom", gpgroom=r["key"])] for r in d["not_ready"]],
                        "Stories not ready") or '<p class="gp-line">Every story for the next sprint has acceptance criteria and points.</p>')

    parts.append("<h3>4. SIT and UAT stories missing</h3>")
    parts.append('<p class="gp-line">DEV stories in the current sprint need a SIT story next sprint and a UAT story the '
                 'sprint after. They are matched by title without the phase.</p>')
    parts.append(_table(["Story this sprint", "Problem", "Goes in", ""],
                        [[_key(r["key"], browse) + " " + esc(r["summary"]), esc(r["problem"]), esc(r["sprint"]),
                          act("Create " + r["phase"] + " story", gpnew=r["title"], gpfrom=r["key"]) if r["title"] else
                          act("Move to " + r["sprint"], gpgroom=r["other"])] for r in d["phases"]],
                        "Missing phase stories") or '<p class="gp-line">Every DEV story in the sprint has its SIT and UAT stories.</p>')

    parts.append("<h3>5. Who to invite</h3>")
    core = ", ".join("%s (%s)" % (esc(c["who"]), esc(c["role"])) for c in d["core"]) or "not listed"
    parts.append('<p class="gp-line">UI team, on every call: %s.</p>' % core)
    parts.append(_table(["Story", "On the story", "Partner teams the story or epic names"],
                        [[_key(p["key"], browse) + " " + esc(p["summary"]), esc(", ".join(p["on_story"]) or "nobody"),
                          "<br>".join("%s: %s%s" % (esc(t["team"]),
                                                    esc(", ".join(c["who"] for c in t["contacts"]) or "contact not listed"),
                                                    esc("; DL " + t["dl"]) if t["dl"] else "; no DL on file")
                                      for t in p["partners"]) or "UI team only"] for p in d["people"]],
                        "Invitees") or '<p class="gp-line">No story to groom yet.</p>')

    parts.append("<h3>6. Agenda, group chat and backup plan</h3>")
    parts.append('<div class="gp-two"><div><b>Agenda</b> (paste into the invite)<textarea class="a-input gp-text" rows="9" readonly>%s</textarea>%s</div>'
                 '<div><b>Group chat</b> (paste into Teams)<textarea class="a-input gp-text" rows="5" readonly>%s</textarea>%s'
                 '<p class="gp-line"><b>Backup plan:</b> if a partner team can\'t join, groom these with the UI team only: %s.</p></div></div>'
                 % (esc(d["agenda"]), act("Copy agenda", gpcopy="agenda"), esc(d["chat"]), act("Copy message", gpcopy="chat"),
                    esc(", ".join(d["backup"])) or "none"))
    parts.append('<p class="gp-line">Devin Cloud cannot send the invite or start the chat, so these are drafts to copy.</p>')
    if d.get("assumptions"):
        parts.append('<details><summary>Assumptions until the Product Owner confirms them (%s)</summary><ul>%s</ul></details>'
                     % (esc(d["settings_file"]), "".join("<li>%s</li>" % esc(a) for a in d["assumptions"])))
    return "".join(parts)


CSS = """
.gp-line{color:rgb(var(--text-secondary));margin:4px 0 10px}.gp-warn{color:rgb(var(--text-orange))}
.gp-sub{font-size:12px;color:rgb(var(--text-secondary))}.gp-act{margin:1px 2px}
.gp-two{display:grid;grid-template-columns:1fr 1fr;gap:12px}.gp-text{width:100%;font:12.5px/1.45 ui-monospace,Menlo,monospace}
@media(max-width:760px){.gp-two{grid-template-columns:1fr}}
"""


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cache", help="JSON with stories, epics and sprints (Argus /api/backlog shape)")
    ap.add_argument("--import-roadmap", metavar="XLSX", help="load the PO's sprint roadmap tab into %s" % ROADMAP_REL)
    ap.add_argument("--tab", default="0922_2026", help="with --import-roadmap: the tab to read")
    ap.add_argument("--source", default="", help="with --import-roadmap: who keeps the sheet, shown on the page")
    args = ap.parse_args(argv)
    if args.import_roadmap:
        import yaml
        src = args.source or "%s, tab %s" % (os.path.basename(args.import_roadmap), args.tab)
        sheet = parse_roadmap(read_sheet_rows(args.import_roadmap, args.tab), src)
        with open(ROADMAP_PATH, "w", encoding="utf-8") as fh:
            fh.write("# The Product Owner's sprint roadmap, loaded with grooming_prep.py --import-roadmap. Reload it when she\n"
                     "# re-sends the sheet; Grooming prep checks each epic's planned phase per sprint against Jira.\n")
            yaml.safe_dump(sheet, fh, sort_keys=False, allow_unicode=True, width=120)
        print("%s: %d epics, sprints %s" % (ROADMAP_REL, len(sheet["epics"]), ", ".join(sheet["sprints"])))
        return 0
    if not args.cache:
        ap.error("--cache is needed")
    with open(args.cache, encoding="utf-8") as fh:
        data = json.load(fh)
    plan, teams, cfg = context()
    print(json.dumps(analyse_with_roadmap(data.get("stories") or [], data.get("epics") or [], data.get("sprints") or [],
                                          plan, teams, cfg), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
