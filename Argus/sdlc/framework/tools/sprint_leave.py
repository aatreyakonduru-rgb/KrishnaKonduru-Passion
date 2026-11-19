#!/usr/bin/env python3
"""Sprint leave, kept on the Confluence page "Acme Claims Sprint Leave" (confluence.pages.sprint_leave).

The Scrum Master marks who is off which day in Argus (or edits the page itself); the page holds one
section per sprint: dates and productive hours, then one row per person with their share of time on the
project, the days off, "No leave" once they have said so, and a note. Capacity is worked out the way the
sprint capacity sheet does it: days in x productive hours x share; the team's hours / hours_per_point are
the points. `xlsx` writes the same thing as a capacity sheet the Scrum Master can keep on SharePoint.

    sprint_leave.py show [SPRINT]          the page as JSON
    sprint_leave.py capacity SPRINT        capacity in the capacity-sheet shape (what the dashboard reads)
    sprint_leave.py xlsx SPRINT -o FILE    a capacity sheet for the sprint
"""
import argparse
import datetime
import html
import json
import os
import re
import sys
import zipfile
from html.parser import HTMLParser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import team_links  # noqa: E402

ROOT = team_links.ROOT
PEOPLE_PATH = os.path.join(ROOT, ".devin", "rules", "people.yaml")
PAGE_KEY = "sprint_leave"
PEOPLE_COLUMNS = ["Jira user", "Name", "% on project", "Days off", "No leave", "Note"]
TIME_OFF_HEADING = "Time off and backups"
TIME_OFF_COLUMNS = ["Jira user", "Name", "From", "To", "Stories go to", "Questions go to", "Approvals go to",
                    "Stories on hold", "Last asked", "Note", "Type"]
TIME_OFF_KEYS = ["jira_user", "name", "from", "to", "stories_to", "questions_to", "approvals_to", "hold", "asked",
                 "note", "kind"]
SICK = "Sick day"
ADHOC = "Ad hoc leave"
UNPLANNED_KINDS = (SICK, ADHOC)
UNPLANNED_HEADING = "Unplanned leave"
UNPLANNED_COLUMNS = ["Date", "Sprint", "Jira user", "Name", "Type", "Reported by"]
UNPLANNED_KEYS = ["date", "sprint", "jira_user", "name", "kind", "by"]
SPRINT_RE = re.compile(r"(\d{2})\.(\d)\.(\d+)(?:\s*\(\s*(\d{1,2})/(\d{1,2})\s*-\s*(\d{1,2})/(\d{1,2}))?")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


class LeaveError(Exception):
    pass


# ---- sprints and days --------------------------------------------------------------------------

def sprint_of(name, start="", end=""):
    """{token, start, end} from a Jira sprint name like 'Acme Claims Sprint 26.4.3(10/28-11/17'; Jira dates win."""
    m = SPRINT_RE.search(name or "")
    if not m:
        return None
    token = "%s.%s.%s" % m.group(1, 2, 3)
    if not (start and end) and m.group(4):
        y = 2000 + int(m.group(1))
        s = datetime.date(y, int(m.group(4)), int(m.group(5)))
        e = datetime.date(y + 1 if int(m.group(6)) < int(m.group(4)) else y, int(m.group(6)), int(m.group(7)))
        start, end = start or s.isoformat(), end or e.isoformat()
    return {"token": token, "start": (start or "")[:10], "end": (end or "")[:10]}


def working_days(start, end, holidays=()):
    """Mon-Fri from start to end inclusive, as ISO dates, without the team holidays."""
    d, last, out = datetime.date.fromisoformat(start), datetime.date.fromisoformat(end), []
    while d <= last:
        if d.weekday() < 5 and d.isoformat() not in holidays:
            out.append(d.isoformat())
        d += datetime.timedelta(days=1)
    return out


def dates_in(text):
    return sorted(set(DATE_RE.findall(text or "")))


# ---- roster ------------------------------------------------------------------------------------

def roster(path=PEOPLE_PATH):
    """People who carry sprint work (delivery not false): jira_user, name, allocation %, primary role."""
    out, cur = [], None
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            m = re.match(r"^- jira_user:\s*(\S+)", line)
            if m:
                cur = {"jira_user": m.group(1).strip("'\""), "name": "", "allocation": 100, "delivery": True,
                       "role": ""}
                out.append(cur)
                continue
            if cur is None:
                continue
            if re.match(r"^\S", line):
                cur = None
                continue
            m = re.match(r"^  (name|allocation|delivery|primary_role):\s*(.*)$", line)
            if m:
                key, val = m.group(1), m.group(2).strip().strip("'\"")
                if key == "allocation":
                    cur[key] = float(val) if val else 100
                elif key == "delivery":
                    cur[key] = val.lower() != "false"
                else:
                    cur["role" if key == "primary_role" else key] = val
    return [p for p in out if p["delivery"]]


# ---- page <-> data -----------------------------------------------------------------------------

class _Tables(HTMLParser):
    """Each <h2> and the tables after it: [(heading, [[cell text, ...], ...]), ...]."""

    def __init__(self):
        super().__init__()
        self.sections, self.heading, self.text, self.row, self.table, self.cell = [], None, None, None, None, None

    def handle_starttag(self, tag, attrs):
        if tag == "h2":
            self.text = ""
        elif tag == "table":
            self.table = []
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = ""
        elif tag == "br" and self.cell is not None:
            self.cell += " "

    def handle_endtag(self, tag):
        if tag == "h2" and self.text is not None:
            self.heading, self.text = self.text.strip(), None
            self.sections.append((self.heading, []))
        elif tag in ("td", "th") and self.cell is not None:
            self.row.append(" ".join(self.cell.split()))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.table.append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            if self.sections:
                self.sections[-1][1].append(self.table)
            self.table = None

    def handle_data(self, data):
        if self.cell is not None:
            self.cell += data
        elif self.text is not None:
            self.text += data


def parse_page(storage):
    """{token: {start, end, productive_hours, holidays, people: [{jira_user, name, allocation, off, no_leave, note}]}}"""
    p = _Tables()
    p.feed(storage or "")
    out = {}
    for heading, tables in p.sections:
        m = SPRINT_RE.search(heading)
        if not m or not tables:
            continue
        meta = {r[0].strip().lower(): r[1] for r in tables[0] if len(r) >= 2}
        sprint = {"start": (dates_in(meta.get("starts")) or [""])[0], "end": (dates_in(meta.get("ends")) or [""])[0],
                  "productive_hours": float(meta.get("productive hours a day") or 6),
                  "holidays": dates_in(meta.get("team holidays")), "people": []}
        rows = tables[1] if len(tables) > 1 else []
        head = [c.lower() for c in rows[0]] if rows else []
        col = {c.lower(): head.index(c.lower()) for c in PEOPLE_COLUMNS if c.lower() in head}
        for r in rows[1:]:
            get = lambda c: r[col[c.lower()]] if c.lower() in col and col[c.lower()] < len(r) else ""  # noqa: E731
            if not get("Jira user") and not get("Name"):
                continue
            try:
                alloc = float(get("% on project").rstrip("%") or 100)
            except ValueError:
                alloc = 100.0
            sprint["people"].append({"jira_user": get("Jira user"), "name": get("Name"), "allocation": alloc,
                                     "off": dates_in(get("Days off")),
                                     "no_leave": get("No leave").strip().lower() in ("yes", "y", "true", "x"),
                                     "note": get("Note")})
        out["%s.%s.%s" % m.group(1, 2, 3)] = sprint
    return out


def parse_time_off(storage):
    """The planner rows: [{jira_user, name, from, to, stories_to, questions_to, approvals_to, hold, asked, note, kind}].
    A row with no dates says the person was asked and has no time off planned; kind is SICK for a sick day."""
    p = _Tables()
    p.feed(storage or "")
    for heading, tables in p.sections:
        if heading.strip().lower() != TIME_OFF_HEADING.lower() or not tables or not tables[0]:
            continue
        head = [c.lower() for c in tables[0][0]]
        out = []
        for r in tables[0][1:]:
            row = {k: (r[head.index(c.lower())] if c.lower() in head and head.index(c.lower()) < len(r) else "")
                   for c, k in zip(TIME_OFF_COLUMNS, TIME_OFF_KEYS)}
            if not row["jira_user"] and not row["name"]:
                continue
            row["hold"] = row["hold"].strip().lower() in ("yes", "y", "true", "x")
            for k in ("from", "to", "asked"):
                row[k] = (dates_in(row[k]) or [""])[0]
            out.append(row)
        return out
    return []


def parse_unplanned(storage):
    """The Unplanned leave log: [{date, sprint, jira_user, name, kind, by}], one row per day, never pruned."""
    p = _Tables()
    p.feed(storage or "")
    for heading, tables in p.sections:
        if heading.strip().lower() != UNPLANNED_HEADING.lower() or not tables or not tables[0]:
            continue
        head = [c.lower() for c in tables[0][0]]
        out = []
        for r in tables[0][1:]:
            row = {k: (r[head.index(c.lower())] if c.lower() in head and head.index(c.lower()) < len(r) else "")
                   for c, k in zip(UNPLANNED_COLUMNS, UNPLANNED_KEYS)}
            row["date"] = (dates_in(row["date"]) or [""])[0]
            if row["date"] and (row["jira_user"] or row["name"]):
                out.append(row)
        return out
    return []


def render_unplanned(rows):
    def esc(v):
        return html.escape(str(v), quote=False)
    body = "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % esc(r.get(k, "")) for k in UNPLANNED_KEYS)
                   for r in sorted(rows, key=lambda r: (r.get("date", ""), r.get("name", ""))))
    return ("<h2>%s</h2><p>Every sick day and ad hoc leave reported to Devin, one row per day. Rows stay here (the "
            "Time off and backups table drops old rows), so the Scrum Master's unplanned leave counter keeps them."
            "</p><table><tbody><tr>%s</tr>%s</tbody></table>"
            % (UNPLANNED_HEADING, "".join("<th>%s</th>" % c for c in UNPLANNED_COLUMNS), body))


def merge_unplanned(log, sprints, add=(), drop=()):
    """The log with `add` rows (sprint filled from the sprint sections that hold the date) and without `drop`
    rows ((jira_user, name, date)); a person's day is in it once."""
    def same(r, jira_user, name, date):
        return r.get("date") == date and ((jira_user and r.get("jira_user") == jira_user) or
                                          (not jira_user and r.get("name") == name))
    out = [dict(r) for r in log if not any(same(r, *d) for d in drop)]
    for a in add:
        if any(same(r, a.get("jira_user"), a.get("name"), a["date"]) for r in out):
            continue
        a = dict(a)
        if not a.get("sprint"):
            a["sprint"] = next((t for t, s in sorted(sprints.items()) if s.get("start", "") <= a["date"] <= s.get("end", "")), "")
        out.append(a)
    return out


def render_time_off(rows):
    def esc(v):
        return html.escape(str(v), quote=False)
    body = "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % esc(("yes" if r.get(k) else "") if k == "hold" else r.get(k, ""))
                                           for k in TIME_OFF_KEYS)
                   for r in sorted(rows, key=lambda r: (r.get("name", ""), r.get("from", ""))))
    return ("<h2>%s</h2><p>Who is away when, and who covers their stories, questions and approvals. Devin asks "
            "everyone once a week and fills this in after they say approved; a row without dates means no time off "
            "planned when last asked. A row with Type <strong>Sick day</strong> is a sick day anyone on the team "
            "reported; it has no backups and changes no tickets.</p><table><tbody><tr>%s</tr>%s</tbody></table>"
            % (TIME_OFF_HEADING, "".join("<th>%s</th>" % c for c in TIME_OFF_COLUMNS), body))


def apply_time_off(sprint, rows):
    """The planner's dates as days off in one sprint section (working days only); returns the sprint."""
    days = set(working_days(sprint["start"], sprint["end"], sprint.get("holidays") or ()))
    for p in sprint.get("people") or []:
        for r in rows:
            if not (r.get("from") and r.get("to")):
                continue
            if (r.get("jira_user") and r["jira_user"] == p.get("jira_user")) or \
                    (not r.get("jira_user") and r.get("name") == p.get("name")):
                off = {d for d in working_days(r["from"], r["to"]) if d in days}
                if off:
                    p["off"] = sorted(set(p.get("off") or []) | off)
                    p["no_leave"] = False
    return sprint


INTRO = ("<p>Who is off which day, sprint by sprint. The Scrum Master keeps it from Argus "
         "(<em>Scrum Master follow-ups</em>), and anyone may edit it here: put dates as YYYY-MM-DD, separated by "
         "commas, and <strong>yes</strong> under <em>No leave</em> once you have said you take none. The dashboard "
         "works out sprint capacity from it: days in × productive hours × %% on project, and the team's hours ÷ 8 "
         "are the story points.</p>")


def render_page(sprints, time_off=None, unplanned=None):
    def esc(v):
        return html.escape(str(v), quote=False)
    out = [INTRO]
    if time_off is not None:
        out.append(render_time_off(time_off))
    if unplanned is not None:
        out.append(render_unplanned(unplanned))
    for token in sorted(sprints, key=lambda t: [int(x) for x in t.split(".")], reverse=True):
        s = sprints[token]
        out.append("<h2>Sprint %s</h2>" % esc(token))
        out.append("<table><tbody><tr><th>Starts</th><td>%s</td></tr><tr><th>Ends</th><td>%s</td></tr>"
                   "<tr><th>Productive hours a day</th><td>%s</td></tr><tr><th>Team holidays</th><td>%s</td></tr>"
                   "</tbody></table>" % (esc(s.get("start", "")), esc(s.get("end", "")),
                                         esc(format(float(s.get("productive_hours") or 6), "g")),
                                         esc(", ".join(s.get("holidays") or []))))
        rows = "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % esc(v) for v in (
            p.get("jira_user", ""), p.get("name", ""), format(float(p.get("allocation", 100)), "g"),
            ", ".join(sorted(p.get("off") or [])), "yes" if p.get("no_leave") else "", p.get("note", "")))
            for p in s.get("people") or [])
        out.append("<table><tbody><tr>%s</tr>%s</tbody></table>"
                   % ("".join("<th>%s</th>" % c for c in PEOPLE_COLUMNS), rows))
    return "".join(out)


def new_sprint(sprint, people=None, productive_hours=6):
    """A fresh section for a sprint: everyone on the roster at their roster allocation, nobody answered yet."""
    people = roster() if people is None else people
    return {"start": sprint["start"], "end": sprint["end"], "productive_hours": productive_hours, "holidays": [],
            "people": [{"jira_user": p["jira_user"], "name": p["name"], "allocation": p.get("allocation", 100),
                        "off": [], "no_leave": False, "note": ""} for p in people]}


def clean_sprint(s):
    """What Argus sends, checked: dates inside the sprint, shares 0-100."""
    if not (DATE_RE.fullmatch(s.get("start") or "") and DATE_RE.fullmatch(s.get("end") or "")):
        raise LeaveError("the sprint needs start and end dates (YYYY-MM-DD)")
    days = set(working_days(s["start"], s["end"]))
    people = []
    for p in s.get("people") or []:
        alloc = float(p.get("allocation", 100))
        if not 0 <= alloc <= 100:
            raise LeaveError("%s: %% on project must be 0-100" % p.get("name"))
        people.append({"jira_user": str(p.get("jira_user") or "")[:20], "name": str(p.get("name") or "")[:80],
                       "allocation": alloc, "off": sorted(d for d in set(p.get("off") or []) if d in days),
                       "no_leave": bool(p.get("no_leave")) and not p.get("off"), "note": str(p.get("note") or "")[:200]})
    return {"start": s["start"], "end": s["end"], "productive_hours": float(s.get("productive_hours") or 6),
            "holidays": sorted(d for d in set(s.get("holidays") or []) if DATE_RE.fullmatch(d)), "people": people}


# ---- capacity -----------------------------------------------------------------------------------

def capacity(token, sprint):
    """The capacity-sheet shape (capacity_sheet.read) worked out from the page, so the dashboard reads either."""
    days = working_days(sprint["start"], sprint["end"], sprint.get("holidays") or ())
    hrs = float(sprint.get("productive_hours") or 6)
    roles = {p["jira_user"]: p["role"] for p in roster()} if os.path.exists(PEOPLE_PATH) else {}
    people = []
    for p in sprint.get("people") or []:
        off = [i for i, d in enumerate(days) if d in set(p.get("off") or [])]
        share = float(p.get("allocation", 100)) / 100.0
        people.append({"name": p["name"], "jira_user": p.get("jira_user", ""), "role": roles.get(p.get("jira_user"), ""),
                       "location": "", "pto_note": p.get("note", ""), "allocation": share,
                       "available_days": len(days) - len(off), "off_days": off,
                       "hours": round((len(days) - len(off)) * hrs * share, 2), "sheet_hours": None,
                       "answered": bool(p.get("off") or p.get("no_leave"))})
    return {"file": "the Sprint Leave page (sprint %s)" % token, "productive_hours": hrs, "sprint_days": len(days),
            "days": [{"day": int(d[8:]), "weekday": "MTWTF"[datetime.date.fromisoformat(d).weekday()], "date": d}
                     for d in days],
            "people": people, "total_hours": round(sum(p["hours"] for p in people), 2)}


# ---- capacity sheet (.xlsx) ----------------------------------------------------------------------

def _col(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def xlsx(token, sprint, path, hours_per_point=8):
    """A capacity sheet laid out like the team's: 1 = in, 0 = off, hours and points as formulas."""
    cap = capacity(token, sprint)
    n, hrs = len(cap["days"]), cap["productive_hours"]
    first, hcol = 3, 3 + n

    def cell(r, c, v=None, f=None):
        ref = "%s%d" % (_col(c), r)
        if f is not None:
            return '<c r="%s"><f>%s</f><v>%s</v></c>' % (ref, html.escape(f), v)
        if isinstance(v, (int, float)):
            return '<c r="%s"><v>%s</v></c>' % (ref, format(v, "g"))
        return '<c r="%s" t="inlineStr"><is><t>%s</t></is></c>' % (ref, html.escape(str(v)))

    rows = [[cell(1, 0, "Productive Hours = %s" % format(hrs, "g")), cell(1, 1, hrs),
             cell(1, 2, "Sprint Days = %d" % n)] + [cell(1, first + i, d["day"]) for i, d in enumerate(cap["days"])],
            [cell(2, 0, "Team Member"), cell(2, 2, "%age of time on Project")] +
            [cell(2, first + i, d["weekday"]) for i, d in enumerate(cap["days"])] +
            [cell(2, hcol, "Available hours"), cell(2, hcol + 1, "PTO / note")]]
    r = 3
    for p in cap["people"]:
        marks = [0 if i in p["off_days"] else 1 for i in range(n)]
        rng = "%s%d:%s%d" % (_col(first), r, _col(hcol - 1), r)
        rows.append([cell(r, 0, p["name"]), cell(r, 1, p["role"]), cell(r, 2, p["allocation"])] +
                    [cell(r, first + i, m) for i, m in enumerate(marks)] +
                    [cell(r, hcol, format(p["hours"], "g"), 'IF(A%d="unassigned",0,COUNTIF(%s,1)*$B$1*C%d)' % (r, rng, r)),
                     cell(r, hcol + 1, p["pto_note"] or "")])
        r += 1
    total, last = r + 1, r - 1
    rows.append([cell(total, hcol - 1, "Total hours"),
                 cell(total, hcol, format(cap["total_hours"], "g"), "SUM(%s3:%s%d)" % (_col(hcol), _col(hcol), last))])
    rows.append([cell(total + 1, hcol - 1, "Capacity (points)"),
                 cell(total + 1, hcol, format(cap["total_hours"] / hours_per_point, "g"),
                      "%s%d/%g" % (_col(hcol), total, hours_per_point))])
    by_row = {}
    for row in rows:
        by_row[int(re.search(r'r="[A-Z]+(\d+)"', row[0]).group(1))] = row
    sheet = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/'
             'spreadsheetml/2006/main"><sheetData>%s</sheetData></worksheet>'
             % "".join('<row r="%d">%s</row>' % (k, "".join(v)) for k, v in sorted(by_row.items())))
    ns = "http://schemas.openxmlformats.org"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml",
                    '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="%s/package/2006/content-types">'
                    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                    '<Default Extension="xml" ContentType="application/xml"/>'
                    '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.'
                    'spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="'
                    'application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>' % ns)
        zf.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="%s/package/2006/'
                    'relationships"><Relationship Id="rId1" Type="%s/officeDocument/2006/relationships/officeDocument"'
                    ' Target="xl/workbook.xml"/></Relationships>' % (ns, ns))
        zf.writestr("xl/workbook.xml", '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="%s/spreadsheetml/2006/'
                    'main" xmlns:r="%s/officeDocument/2006/relationships"><sheets><sheet name="Capacity" sheetId="1" '
                    'r:id="rId1"/></sheets><calcPr fullCalcOnLoad="1"/></workbook>' % (ns, ns))
        zf.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="%s/'
                    'package/2006/relationships"><Relationship Id="rId1" Type="%s/officeDocument/2006/relationships/'
                    'worksheet" Target="worksheets/sheet1.xml"/></Relationships>' % (ns, ns))
        zf.writestr("xl/worksheets/sheet1.xml", sheet)
    return path


# ---- Confluence ---------------------------------------------------------------------------------

def page_ref():
    c = team_links.confluence()
    if PAGE_KEY not in c["pages"]:
        raise LeaveError("the team settings have no confluence.pages.%s" % PAGE_KEY)
    return c, c["pages"][PAGE_KEY]


def load(client=None):
    """(page, sprints) from Confluence; `client` is a roster_sync.ConfluenceClient (bearer service account)."""
    import roster_sync
    client = client or roster_sync.ConfluenceClient()
    _, ref = page_ref()
    page = client.get("/rest/api/content/%s" % ref["id"], expand="body.storage,version")
    return page, parse_page(page["body"]["storage"]["value"])


def save(token, sprint, by="", client=None):
    """Write one sprint's section back; the other sprints and anything edited on the page meanwhile stay."""
    import roster_sync
    client = client or roster_sync.ConfluenceClient()
    c, ref = page_ref()
    page, sprints = load(client)
    sprints[token] = clean_sprint(sprint)
    storage = page["body"]["storage"]["value"]
    time_off, unplanned = parse_time_off(storage), parse_unplanned(storage)
    body = {"id": ref["id"], "type": "page", "title": page["title"], "space": {"key": c["space"]},
            "version": {"number": page["version"]["number"] + 1,
                        "message": ("Sprint %s leave" % token) + (" (by %s)" % by if by else "")},
            "body": {"storage": {"value": render_page(sprints, time_off, unplanned or None),
                                 "representation": "storage"}}}
    done = client.write("PUT", "/rest/api/content/%s" % ref["id"], body)
    return {"version": (done.get("version") or {}).get("number"), "sprint": sprints[token]}


def load_time_off(client=None):
    page, _ = load(client)
    return parse_time_off(page["body"]["storage"]["value"])


def load_unplanned(client=None):
    page, _ = load(client)
    return parse_unplanned(page["body"]["storage"]["value"])


def save_time_off(rows, by="", client=None, add=(), drop=()):
    """Write the planner table, and the planner's dates into every sprint section already on the page.
    `add` and `drop` change the Unplanned leave log (merge_unplanned); the rest of the log stays."""
    import roster_sync
    client = client or roster_sync.ConfluenceClient()
    c, ref = page_ref()
    page, sprints = load(client)
    for token in sprints:
        apply_time_off(sprints[token], rows)
    unplanned = merge_unplanned(parse_unplanned(page["body"]["storage"]["value"]), sprints, add, drop)
    body = {"id": ref["id"], "type": "page", "title": page["title"], "space": {"key": c["space"]},
            "version": {"number": page["version"]["number"] + 1,
                        "message": "Time off and backups" + (" (by %s)" % by if by else "")},
            "body": {"storage": {"value": render_page(sprints, rows, unplanned or None), "representation": "storage"}}}
    done = client.write("PUT", "/rest/api/content/%s" % ref["id"], body)
    return {"version": (done.get("version") or {}).get("number"), "rows": rows, "unplanned": unplanned}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["show", "capacity", "xlsx"])
    ap.add_argument("sprint", nargs="?", default="")
    ap.add_argument("-o", "--out")
    args = ap.parse_args(argv)
    _, sprints = load()
    if args.command == "show":
        print(json.dumps(sprints.get(args.sprint) if args.sprint else sprints, indent=1))
        return 0
    if args.sprint not in sprints:
        raise SystemExit("no sprint %s on the page (has: %s)" % (args.sprint, ", ".join(sorted(sprints)) or "none"))
    if args.command == "capacity":
        print(json.dumps(capacity(args.sprint, sprints[args.sprint]), indent=1))
        return 0
    print(xlsx(args.sprint, sprints[args.sprint], args.out or "ACME_UI_Sprint_%s_capacity.xlsx" % args.sprint))
    return 0


if __name__ == "__main__":
    sys.exit(main())
