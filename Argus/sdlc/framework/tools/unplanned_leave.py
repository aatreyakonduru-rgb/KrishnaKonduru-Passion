#!/usr/bin/env python3
"""Unplanned leave (sick days and ad hoc leave): the Scrum Master's leave tracker kept in the repo, and its counter.

The leave tracker workbook (tabs Acme Claims 2026, Team Capacity and Unplanned leaves) is kept as
context/leave-tracker/leave-tracker.json with a read-only copy, leave-tracker.html. The Unplanned leaves tab has one
row per team member and one column per sprint. Sick days and ad hoc leave reported to Devin
("@Devin <name> is sick today", time_off.py sick) go to the Unplanned leave table on the Acme Claims Sprint Leave page.
The counter is the tab's numbers plus every reported day from the date the workbook was imported.

    unplanned_leave.py import XLSX [--on YYYY-MM-DD]          the workbook into the repo (replaces the copy)
    unplanned_leave.py html                                    rebuild leave-tracker.html from the json
    unplanned_leave.py count [--person NAME] [--sprint S]      the counter as JSON (reads the Sprint Leave page)
    unplanned_leave.py sprint [--sprint S]                     one sprint's days and counts, for the vacation planner
"""
import argparse
import datetime
import html
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sprint_sheet  # noqa: E402

ROOT = sprint_sheet.ROOT
TRACKER_DIR = os.path.join(ROOT, "sdlc", "framework", "context", "leave-tracker")
JSON_PATH = os.path.join(TRACKER_DIR, "leave-tracker.json")
HTML_PATH = os.path.join(TRACKER_DIR, "leave-tracker.html")
TAB = "Unplanned leaves"
SPRINT_RE = re.compile(r"^\d+\.\d+\.\d+$")


class TrackerError(Exception):
    pass


def esc(v):
    return html.escape(str(v if v is not None else ""), quote=True)


def norm(name):
    return re.sub(r"[^a-z]", "", (name or "").lower())


def sprint_key(token):
    return tuple(int(x) for x in token.split(".")) if SPRINT_RE.match(token or "") else (9999,)


def import_xlsx(path, on, source=""):
    tabs = [{"name": n, "cells": c, "widths": w, "hidden": h} for n, c, w, h in sprint_sheet.read_xlsx(path)]
    tracker = {"source": source or os.path.basename(path), "imported_on": on, "tabs": tabs}
    baseline(tracker)
    return tracker


def load(path=JSON_PATH):
    if not os.path.exists(path):
        raise TrackerError("no leave tracker in the repo yet (%s)" % os.path.relpath(path, ROOT))
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def save(tracker, json_path=JSON_PATH, html_path=HTML_PATH):
    os.makedirs(os.path.dirname(json_path), exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(tracker, fh, indent=1, sort_keys=True)
        fh.write("\n")
    with open(html_path, "w", encoding="utf-8") as fh:
        fh.write(render_page(tracker))
    return [json_path, html_path]


def baseline(tracker):
    """(sprints, [(name, {sprint: days})]) from the Unplanned leaves tab: row 1 holds the sprints, column A the
    names; a row with no name (the totals row) is skipped."""
    tab = sprint_sheet.tab_of(tracker, TAB)
    values = sprint_sheet.evaluate(tab)
    cols, rows = {}, {}
    for ref in tab["cells"]:
        c, r = sprint_sheet.split_ref(ref)
        rows.setdefault(r, {})[c] = values.get(ref, "")
    for c, v in (rows.get(1) or {}).items():
        if SPRINT_RE.match(sprint_sheet.show(v).strip()):
            cols[c] = sprint_sheet.show(v).strip()
    if not cols:
        raise TrackerError("the %s tab has no sprint columns in row 1" % TAB)
    people = []
    for r in sorted(k for k in rows if k > 1):
        name = str(rows[r].get(1, "") or "").strip()
        if not name or name.lower().startswith("total"):
            continue
        days = {}
        for c, s in cols.items():
            v = rows[r].get(c, "")
            try:
                n = sprint_sheet.number(v)
            except sprint_sheet.SheetError:
                n = 0.0
            if n:
                days[s] = n
        people.append((name, days))
    return sorted(cols.values(), key=sprint_key), people


def counts(tracker, log):
    """The counter: the tracker's numbers plus every logged day on or after the import date.
    {sprints, people: [{name, days: {sprint: n}, total}], totals: {sprint: n}, total, reported: n}"""
    sprints, base = baseline(tracker)
    people = [{"name": n, "days": dict(d)} for n, d in base]
    by_name = {norm(p["name"]): p for p in people}
    cut, reported = tracker.get("imported_on", ""), 0
    for e in log:
        if e.get("date", "") < cut:
            continue
        s = e.get("sprint") or "no sprint"
        p = by_name.get(norm(e.get("name")))
        if p is None:
            p = by_name[norm(e.get("name"))] = {"name": e.get("name") or e.get("jira_user", ""), "days": {}}
            people.append(p)
        p["days"][s] = p["days"].get(s, 0) + 1
        reported += 1
        if s not in sprints:
            sprints = sorted(sprints + [s], key=sprint_key)
    totals = {s: sum(p["days"].get(s, 0) for p in people) for s in sprints}
    for p in people:
        p["total"] = sum(p["days"].values())
    return {"sprints": sprints, "people": people, "totals": totals, "total": sum(totals.values()),
            "reported": reported}


def sprint_view(tracker, log, sprint):
    """One sprint's unplanned leave for the vacation planner: the days reported in it, with dates, and each person's
    count for the sprint and the year. {sprint, team, year, days: [log entries], people: [{name, sprint, year}]}"""
    c = counts(tracker, log)
    days = sorted((e for e in log if e.get("sprint") == sprint and e.get("date", "") >= tracker.get("imported_on", "")),
                  key=lambda e: (e.get("date", ""), e.get("name", "")))
    people = sorted(({"name": p["name"], "sprint": p["days"].get(sprint, 0), "year": p["total"]}
                     for p in c["people"] if p["total"]), key=lambda p: (-p["sprint"], -p["year"], p["name"]))
    return {"sprint": sprint, "team": c["totals"].get(sprint, 0), "year": c["total"], "days": days, "people": people,
            "imported_on": tracker.get("imported_on", "")}


def render_sprint_view(v):
    """The Unplanned leave section under the vacation planner."""
    s = esc(v["sprint"] or "now")
    out = ('<h3>Unplanned leave, sprint %s</h3><p>Sick days and ad hoc leave: <strong>%s</strong> this sprint, '
           '<strong>%s</strong> this year.</p>' % (s, esc(days_text(v["team"])), esc(days_text(v["year"]))))
    if v["days"]:
        out += ("<table><thead><tr><th>Date</th><th>Team member</th><th>Type</th><th>Reported by</th></tr></thead>"
                "<tbody>%s</tbody></table>" % "".join(
                    "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                        esc(e.get("date", "")), esc(e.get("name", "")), esc(e.get("kind", "")), esc(e.get("by", "")))
                    for e in v["days"]))
    else:
        out += "<p>No sick days or ad hoc leave reported to Devin this sprint.</p>"
    if v["people"]:
        out += ("<table><thead><tr><th>Team member</th><th>Sprint %s</th><th>This year</th></tr></thead><tbody>%s"
                "</tbody></table>" % (s, "".join("<tr><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                    esc(p["name"]), num(p["sprint"]) or "0", num(p["year"])) for p in v["people"])))
    out += ('<p class="a-section__note">Counts include the leave tracker kept by the Scrum Master (imported %s), which '
            'records days per sprint without dates. Days reported to Devin since then are listed with their dates. '
            'The full grid is on the Scrum Master\'s Unplanned leave tab.</p>' % esc(v["imported_on"]))
    return out


def num(n):
    return sprint_sheet.show(float(n)) if n else ""


def counter_line(name, on, log, tracker=None):
    """One line for the reply: this person's unplanned days in the sprint of `on`, and the team's."""
    try:
        c = counts(tracker or load(), log)
    except (TrackerError, sprint_sheet.SheetError) as exc:
        return "Unplanned leave counter not updated (%s)" % exc
    entry = next((e for e in log if e.get("date") == on and norm(e.get("name")) == norm(name)), {})
    s = entry.get("sprint") or "no sprint"
    p = next((p for p in c["people"] if norm(p["name"]) == norm(name)), {"days": {}, "total": 0})
    return ("Unplanned leave: %s has %s in sprint %s (%s this year); the team has %s in sprint %s."
            % (name, days_text(p["days"].get(s, 0)), s, days_text(p["total"]), days_text(c["totals"].get(s, 0)), s))


def days_text(n):
    return "%s day%s" % (sprint_sheet.show(float(n)), "" if n == 1 else "s")


def render_counter(c, current=""):
    """The Unplanned leaves tab: team member by sprint, with a Total column and a Total row."""
    def th(s):
        return '<th%s>%s</th>' % (' class="ul-now" title="current sprint"' if s == current else "", esc(s))

    def td(s, v, strong=False):
        cell = "<strong>%s</strong>" % num(v) if strong and v else num(v)
        return '<td%s>%s</td>' % (' class="ul-now"' if s == current else "", cell)
    head = "<th>Team member</th>%s<th>Total</th>" % "".join(th(s) for s in c["sprints"])
    body = "".join("<tr><td>%s</td>%s<td><strong>%s</strong></td></tr>" % (
        esc(p["name"]), "".join(td(s, p["days"].get(s, 0)) for s in c["sprints"]), num(p["total"]) or "0")
        for p in c["people"])
    body += "<tr><td><strong>Total</strong></td>%s<td><strong>%s</strong></td></tr>" % (
        "".join(td(s, c["totals"][s], True) for s in c["sprints"]), num(c["total"]) or "0")
    return head, body


def render_tab_grid(tab):
    """One workbook tab as a plain grid of its values (formulas worked out), empty rows and columns left out."""
    values = sprint_sheet.evaluate(tab)
    grid = {}
    for ref in tab["cells"]:
        c, r = sprint_sheet.split_ref(ref)
        v = sprint_sheet.show(values.get(ref, "")).strip()
        if v:
            grid.setdefault(r, {})[c] = v
    if not grid:
        return "<p>This tab is empty.</p>"
    cols = sorted({c for row in grid.values() for c in row})
    first = min(grid)
    head = "".join("<th>%s</th>" % esc(grid[first].get(c, "")) for c in cols)
    body = "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % esc(grid[r].get(c, "")) for c in cols)
                   for r in sorted(grid) if r != first)
    return ('<div class="a-table-scroll"><table class="a-table"><thead><tr>%s</tr></thead><tbody>%s</tbody>'
            '</table></div>' % (head, body))


def render_tabs(tracker, prefix="lt"):
    """Every workbook tab, as kit tabs."""
    tabs = tracker["tabs"]
    strip = "".join('<button type="button" class="a-btn" role="tab" aria-controls="%s-%d"%s>%s</button>' % (
        prefix, i, ' aria-selected="true"' if i == 0 else "", esc(t["name"])) for i, t in enumerate(tabs))
    panes = "".join('<section role="tabpanel" id="%s-%d"%s>%s</section>' % (
        prefix, i, "" if i == 0 else " hidden", render_tab_grid(t)) for i, t in enumerate(tabs))
    return '<div data-a-tabs role="tablist">%s</div>%s' % (strip, panes)


def render_page(tracker):
    import artifact_kit
    return artifact_kit.render_page(
        "Acme Claims leave tracker", render_tabs(tracker),
        subtitle="Read-only copy of %s, imported %s" % (esc(tracker.get("source", "")), esc(tracker.get("imported_on", ""))),
        footnote="Rebuilt by tools/unplanned_leave.py. New sick days and ad hoc leave are counted on the Unplanned "
                 "leave tab of the Scrum Master dashboard.")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    im = sub.add_parser("import")
    im.add_argument("xlsx")
    im.add_argument("--on", default=datetime.date.today().isoformat())
    im.add_argument("--source", default="")
    sub.add_parser("html")
    ct = sub.add_parser("count")
    ct.add_argument("--person", default="")
    ct.add_argument("--sprint", default="")
    sp = sub.add_parser("sprint")
    sp.add_argument("--sprint", default="")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "import":
            sprint_sheet.day(a.on)
            done = save(import_xlsx(a.xlsx, a.on, a.source))
            print("\n".join(os.path.relpath(p, ROOT) for p in done))
        elif a.cmd == "html":
            tracker = load()
            with open(HTML_PATH, "w", encoding="utf-8") as fh:
                fh.write(render_page(tracker))
            print(os.path.relpath(HTML_PATH, ROOT))
        elif a.cmd == "sprint":
            import sprint_leave
            log = sprint_leave.load_unplanned() if os.environ.get("ACME_CONFLUENCE_TOKEN") else []
            print(json.dumps(sprint_view(load(), log, a.sprint or sprint_sheet.current() or ""), indent=1))
        else:
            import sprint_leave
            log = sprint_leave.load_unplanned() if os.environ.get("ACME_CONFLUENCE_TOKEN") else []
            c = counts(load(), log)
            if a.person:
                c["people"] = [p for p in c["people"] if norm(a.person) in norm(p["name"])]
            if a.sprint:
                c = {"sprint": a.sprint, "team": c["totals"].get(a.sprint, 0),
                     "people": {p["name"]: p["days"].get(a.sprint, 0) for p in c["people"]}}
            print(json.dumps(c, indent=1))
    except (TrackerError, sprint_sheet.SheetError) as exc:
        print("unplanned_leave: %s" % exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
