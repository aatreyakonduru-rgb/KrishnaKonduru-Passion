#!/usr/bin/env python3
"""The leave calendar on the Vacation planner tab: one row per team member, one column per day of the sprint, each
day coloured by what it is, so weekends, holidays, planned time off, sick days and ad hoc leave can be told apart
at a glance.

Days come from the sprint's planning sheet (0 off, 0.5 half day, H holiday), the planner rows on the Sprint Leave
page (Time off, Sick day, Ad hoc leave) and the page's Unplanned leave table. A sick day or ad hoc leave wins over
planned time off on the same day, because the planning sheet keeps no sick days.
"""
import datetime
import html
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sprint_leave  # noqa: E402
import sprint_sheet  # noqa: E402

WEEKEND, HOLIDAY, PLANNED, SICK, ADHOC = "weekend", "holiday", "planned", "sick", "adhoc"
KIND_OF = {sprint_leave.SICK: SICK, sprint_leave.ADHOC: ADHOC}
LEGEND = [(PLANNED, "Planned time off", "P"), (SICK, "Sick day", "S"), (ADHOC, "Ad hoc leave", "A"),
          (HOLIDAY, "Holiday", "H"), (WEEKEND, "Weekend", "")]
LETTER = {k: l for k, _, l in LEGEND}
LABEL = {k: t for k, t, _ in LEGEND}
RANK = {WEEKEND: 0, PLANNED: 1, HOLIDAY: 2, ADHOC: 3, SICK: 4}

CSS = """
.lc-wrap{overflow-x:auto;margin:.25rem 0 1rem}
.lc{border-collapse:collapse;font-size:12px}
.lc th,.lc td{border:1px solid var(--a-border,#d0d5dd);text-align:center;min-width:2.1em;height:1.9em;padding:0 2px}
.lc th.lc-who,.lc td.lc-who{text-align:left;white-space:nowrap;padding:0 8px;position:sticky;left:0;background:var(--a-surface,#fff);z-index:1}
.lc thead th{background:var(--a-surface-2,#f2f4f7);font-weight:600;line-height:1.1}
.lc thead th small{display:block;font-weight:400;color:var(--a-muted,#667085)}
.lc .lc-today{outline:2px solid #1d2939;outline-offset:-2px}
.lc-weekend{background:#e4e7ec;color:#667085}
.lc-holiday{background:#f79009;color:#fff;font-weight:600}
.lc-planned{background:#84caff;color:#0b4a6f;font-weight:600}
.lc-sick{background:#fde047;color:#713f12;font-weight:600}
.lc-adhoc{background:#c4b5fd;color:#3b0764;font-weight:600}
.lc-half{background-image:linear-gradient(135deg,transparent 50%,#fff 50%)}
.lc-legend{display:flex;flex-wrap:wrap;gap:.4rem 1rem;margin:.25rem 0;font-size:12px;align-items:center}
.lc-legend span.lc-key{display:inline-block;width:1.9em;height:1.4em;line-height:1.4em;text-align:center;border:1px solid var(--a-border,#d0d5dd);margin-right:.3rem;vertical-align:middle}
"""


def esc(v):
    return html.escape(str(v if v is not None else ""), quote=True)


def span(start, end):
    d, out = sprint_sheet.day(start), []
    while d <= sprint_sheet.day(end):
        out.append(d)
        d += datetime.timedelta(days=1)
    return out


def grid(sheet, rows=(), log=()):
    """{days: [date], people: [{name, days: {iso: {"kind", "half", "note"}}}]} for the sprint of `sheet`
    (a sprint_sheet sheet). Weekends are filled in for everyone."""
    days = span(sheet["start"], sheet["end"])
    first, last = days[0].isoformat(), days[-1].isoformat()
    people, by = [], {}

    def person(name):
        key = sprint_sheet.norm(name)
        if key not in by:
            by[key] = {"name": name, "days": {}}
            people.append(by[key])
        return by[key]

    def mark(name, iso, kind, half=False, note=""):
        if not (first <= iso <= last):
            return
        cell = person(name)["days"]
        old = cell.get(iso)
        if old is None or RANK[kind] > RANK[old["kind"]]:
            cell[iso] = {"kind": kind, "half": half, "note": note}

    for p in sprint_sheet.people(sheet):
        person(p["name"])
        for iso in p["off"]:
            mark(p["name"], iso, PLANNED, note="Off on the planning sheet")
        for iso in p["half"]:
            mark(p["name"], iso, PLANNED, half=True, note="Half day on the planning sheet")
        for iso in p["holiday"]:
            mark(p["name"], iso, HOLIDAY, note="Holiday")
    for r in rows or []:
        if not (r.get("from") and r.get("to")):
            continue
        kind = KIND_OF.get(r.get("kind"), PLANNED)
        note = r.get("kind") or "Time off"
        for d in span(r["from"], r["to"]):
            if d.weekday() < 5:
                mark(r.get("name") or r.get("jira_user", ""), d.isoformat(), kind, note=note)
    for e in log or []:
        if e.get("date"):
            mark(e.get("name") or e.get("jira_user", ""), e["date"], KIND_OF.get(e.get("kind"), SICK),
                 note="%s, reported by %s" % (e.get("kind") or "Sick day", e.get("by") or "someone"))
    for p in people:
        for d in days:
            if d.weekday() >= 5:
                p["days"].setdefault(d.isoformat(), {"kind": WEEKEND, "half": False, "note": "Weekend"})
    return {"sprint": sheet.get("sprint", ""), "days": days, "people": people}


def legend():
    return '<div class="lc-legend">%s<span>Half day: the cell is half coloured.</span></div>' % "".join(
        '<span><span class="lc-key lc-%s">%s</span>%s</span>' % (k, esc(l), esc(t)) for k, t, l in LEGEND)


def render(g, today=None):
    """The calendar as an HTML fragment, legend first, with its own style."""
    today = (today or datetime.date.today()).isoformat()
    head = '<th class="lc-who">Team member</th>' + "".join(
        '<th%s title="%s">%s<small>%s</small></th>' % (
            ' class="lc-today"' if d.isoformat() == today else "", d.isoformat(), d.day, d.strftime("%a")[:2])
        for d in g["days"])
    body = []
    for p in g["people"]:
        cells = []
        for d in g["days"]:
            iso, c = d.isoformat(), p["days"].get(d.isoformat())
            cls = (["lc-" + c["kind"]] + (["lc-half"] if c["half"] else [])) if c else []
            if iso == today:
                cls.append("lc-today")
            tip = "%s, %s: %s" % (p["name"], iso, c["note"]) if c else ""
            cells.append('<td%s%s>%s</td>' % (' class="%s"' % " ".join(cls) if cls else "",
                                              ' title="%s"' % esc(tip) if tip else "",
                                              esc(LETTER[c["kind"]]) if c else ""))
        body.append('<tr><td class="lc-who">%s</td>%s</tr>' % (esc(p["name"]), "".join(cells)))
    return ('<style>%s</style><h3>Who is out, sprint %s</h3>%s<div class="lc-wrap"><table class="lc"><thead><tr>%s'
            '</tr></thead><tbody>%s</tbody></table></div>' % (CSS, esc(g["sprint"]), legend(), head, "".join(body)))


def page(g, today=None, extra=""):
    """A standalone page with the calendar, for attaching to a /vacation answer."""
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Who is out, sprint %s</title>'
            '<style>body{font-family:"Segoe UI",Arial,sans-serif;font-size:13px;margin:16px;color:#1d2939}</style>'
            '</head><body>%s%s</body></html>' % (esc(g["sprint"]), render(g, today), extra))


def main(argv=None):
    """leave_calendar.py html [--sprint S] [-o PATH]: the sprint's calendar from the planning sheet and the Sprint
    Leave page (planner rows and Unplanned leave table), as an HTML page to attach."""
    import argparse
    ap = argparse.ArgumentParser(description=main.__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    h = sub.add_parser("html")
    h.add_argument("--sprint", default="")
    h.add_argument("-o", "--output", default="")
    a = ap.parse_args(argv)
    try:
        sprint = a.sprint or sprint_sheet.current()
        if not sprint:
            raise sprint_sheet.SheetError("no sprint planning sheet in the repo")
        sheet = sprint_sheet.load(sprint)
        rows, log = [], []
        if os.environ.get("ACME_CONFLUENCE_TOKEN"):
            rows, log = sprint_leave.load_time_off(), sprint_leave.load_unplanned()
        else:
            print("Sprint Leave page not read (ACME_CONFLUENCE_TOKEN is not set): planning sheet only", file=sys.stderr)
        out = a.output or "leave-calendar-%s.html" % sprint
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(page(grid(sheet, rows, log)))
        print(out)
    except sprint_sheet.SheetError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
