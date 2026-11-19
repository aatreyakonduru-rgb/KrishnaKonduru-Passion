#!/usr/bin/env python3
"""Time off and backups: the weekly question, the central planner, and who covers whom while someone is away.

The planner is the "Time off and backups" table on the Confluence page Acme Claims Sprint Leave (sprint_leave.py),
so the Scrum Master has everyone's time off in one place and the sprint sections get the days off for capacity.
Once a calendar week the first session with each person on the roster asks about time off. A yes brings the
follow-up questions: who covers their stories, whether their In Progress stories go on hold, where questions
for them go and who approves in their place. Nothing is written until they say "approved" (--write).
While someone is away, question and approval sub-tasks for them go to their backup (route), falling back to
`delegate_to` in people.yaml.
A sick day or ad hoc leave is different: anyone may report it for anyone ("@Devin <name> is sick today"), it is written
at once with no follow-up questions, and it names no backups, puts nothing On Hold and reroutes nothing. If it runs
past a day, the Scrum Master and the tech leads move the work by hand. Each such day also goes to the Unplanned leave
log on the same page, which feeds the Scrum Master's counter (unplanned_leave.py).

    time_off.py due --person NAME                      is this week's question due; the question to ask
    time_off.py record --person NAME --none [--write]
    time_off.py record --person NAME --from D --to D [--stories-to N] [--questions-to N] [--approvals-to N]
                       [--hold] [--note T] [--write]
    time_off.py away [--date D]                        who is away and who covers them
    time_off.py route --person NAME --kind story|question|approval [--date D]
    time_off.py holds --person NAME                    their In Progress stories as Backlog hold blocks
    time_off.py list [--person NAME]                   the planner from today on, with backups (/vacation)
    time_off.py remove --person NAME --from D [--write]
    time_off.py sick --person NAME [--date D] [--reason sick|adhoc] [--by NAME] [--write]   today unless --date

`record` and `remove` take `--by NAME`, the person making the change. Anyone may change their own time off; the
Scrum Master (primary_role scrum_master in people.yaml) may change anyone's. Anyone may record or remove a sick day or ad hoc leave.
"""
import argparse
import datetime
import json
import os
import re
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sprint_leave  # noqa: E402

PEOPLE_PATH = sprint_leave.PEOPLE_PATH
KINDS = {"story": "stories_to", "question": "questions_to", "approval": "approvals_to"}
SICK = sprint_leave.SICK
ADHOC = sprint_leave.ADHOC
UNPLANNED_KINDS = sprint_leave.UNPLANNED_KINDS
REASONS = {"sick": SICK, "adhoc": ADHOC}
QUESTION = ("Any time off coming up in the next few weeks: a day off, a vacation or a holiday you take? "
            "Say no if there is none, or skip.")
FOLLOW_UPS = [
    "Which dates (from and to)?",
    "Who is your backup for your stories while you are away?",
    "Should I put your In Progress stories On Hold, or will your backup carry them?",
    "If someone sends you a question while you are away, who should I send it to?",
    "If an approval comes your way while you are away, who should approve it?",
]
KEEP_DAYS = 60


class TimeOffError(Exception):
    pass


def norm(name):
    return "".join(sorted(re.findall(r"[a-z0-9]+", (name or "").lower())))


def people(path=PEOPLE_PATH):
    """Everyone on the roster, sprint work or not (the Scrum Master and the POs take time off too)."""
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return [{"jira_user": str(p.get("jira_user") or ""), "name": p.get("name") or "",
             "delegate_to": p.get("delegate_to") or "", "primary_role": p.get("primary_role") or ""}
            for p in data.get("people") or []]


def find(roster, value):
    v = (value or "").strip()
    for p in roster:
        if v and (v.upper() == p["jira_user"].upper() or norm(v) == norm(p["name"])):
            return p
    raise TimeOffError("%s is not on the roster (.devin/rules/people.yaml)" % value)


def day(value):
    try:
        return datetime.date.fromisoformat(str(value)[:10])
    except ValueError:
        raise TimeOffError("dates are YYYY-MM-DD, got %r" % value)


def week_start(d):
    return d - datetime.timedelta(days=d.weekday())


def mine(rows, person):
    return [r for r in rows if r.get("jira_user") == person["jira_user"] or
            (not r.get("jira_user") and norm(r.get("name")) == norm(person["name"]))]


def due(rows, person, today):
    """True when the person has not been asked since Monday of this week."""
    asked = [r["asked"] for r in mine(rows, person) if r.get("asked")]
    return not asked or day(max(asked)) < week_start(today)


def tidy(rows, today):
    """Rows that ended more than KEEP_DAYS ago drop off the page."""
    cut = today - datetime.timedelta(days=KEEP_DAYS)
    return [r for r in rows if not r.get("to") or day(r["to"]) >= cut]


def record_none(rows, person, today):
    rows = [dict(r) for r in rows]
    own = mine(rows, person)
    for r in own:
        r["asked"] = today.isoformat()
    if not [r for r in own if r.get("from") and day(r["to"]) >= today]:
        rows = [r for r in rows if r not in own or r.get("from")]
        rows.append({"jira_user": person["jira_user"], "name": person["name"], "from": "", "to": "",
                     "stories_to": "", "questions_to": "", "approvals_to": "", "hold": False,
                     "asked": today.isoformat(), "note": "No time off planned"})
    return tidy(rows, today)


def record_off(rows, roster, person, start, end, today, stories_to="", questions_to="", approvals_to="",
               hold=False, note=""):
    a, b = day(start), day(end)
    if b < a:
        raise TimeOffError("the time off ends (%s) before it starts (%s)" % (end, start))
    if b < today:
        raise TimeOffError("%s is in the past" % end)
    cover = {}
    for key, who in (("stories_to", stories_to), ("questions_to", questions_to), ("approvals_to", approvals_to)):
        if who:
            backup = find(roster, who)
            if backup["jira_user"] == person["jira_user"]:
                raise TimeOffError("the backup cannot be %s themselves" % person["name"])
            cover[key] = backup["name"]
        else:
            cover[key] = ""
    rows = [dict(r) for r in rows if not (r in mine(rows, person) and (not r.get("from") or r.get("from") == a.isoformat()))]
    for r in mine(rows, person):
        r["asked"] = today.isoformat()
    rows.append(dict({"jira_user": person["jira_user"], "name": person["name"], "from": a.isoformat(),
                      "to": b.isoformat(), "hold": bool(hold), "asked": today.isoformat(), "note": note[:200]}, **cover))
    return tidy(rows, today)


def record_sick(rows, person, on, today, by="", kind=SICK):
    """A one-day unplanned row (Sick day or Ad hoc leave) for `person` on `on`: no backups, no hold, and not an
    answer to the weekly question."""
    d = day(on)
    if d.weekday() >= 5:
        raise TimeOffError("%s is a %s" % (d.isoformat(), d.strftime("%A")))
    if d < today - datetime.timedelta(days=KEEP_DAYS):
        raise TimeOffError("%s is more than %d days ago" % (d.isoformat(), KEEP_DAYS))
    for r in away(mine(rows, person), d):
        raise TimeOffError("%s is already on the planner as off %s to %s%s" % (
            person["name"], r["from"], r["to"], " (%s)" % r["kind"].lower() if r.get("kind") else ""))
    rows = [dict(r) for r in rows]
    rows.append({"jira_user": person["jira_user"], "name": person["name"], "from": d.isoformat(), "to": d.isoformat(),
                 "stories_to": "", "questions_to": "", "approvals_to": "", "hold": False, "asked": "",
                 "note": ("Reported by %s" % by)[:200] if by else "", "kind": kind})
    return tidy(rows, today)


def may_edit(editor, person):
    """Anyone changes their own time off; the Scrum Master changes anyone's."""
    if editor["jira_user"] != person["jira_user"] and editor.get("primary_role") != "scrum_master":
        raise TimeOffError("%s can change only their own time off; the Scrum Master can change %s's"
                           % (editor["name"], person["name"]))


def upcoming(rows, today):
    """Planned time off that has not ended yet, soonest first."""
    return sorted((r for r in rows if r.get("from") and r.get("to") and day(r["to"]) >= today),
                  key=lambda r: (r["from"], r.get("name", "")))


def remove(rows, person, start, today):
    a = day(start).isoformat()
    left = [dict(r) for r in rows if not (r in mine(rows, person) and r.get("from") == a)]
    if len(left) == len(rows):
        raise TimeOffError("%s has no time off starting %s on the planner" % (person["name"], a))
    return tidy(left, today)


def away(rows, on):
    return [r for r in rows if r.get("from") and day(r["from"]) <= on <= day(r["to"])]


def route(rows, roster, person, kind, on):
    """Who should get a story, question or approval meant for `person` on day `on`, and why."""
    if kind not in KINDS:
        raise TimeOffError("kind is one of %s" % ", ".join(KINDS))
    off = [r for r in away(rows, on) if r in mine(rows, person) and r.get("kind") not in UNPLANNED_KINDS]
    if not off:
        return {"to": person["name"], "jira_user": person["jira_user"], "away": False, "why": ""}
    r = off[0]
    backup = r.get(KINDS[kind])
    if not backup and person.get("delegate_to"):
        backup = find(roster, person["delegate_to"])["name"]
    if not backup:
        return {"to": person["name"], "jira_user": person["jira_user"], "away": True,
                "why": "%s is away %s to %s and named no backup for %ss" % (person["name"], r["from"], r["to"], kind)}
    b = find(roster, backup)
    return {"to": b["name"], "jira_user": b["jira_user"], "away": True,
            "why": "%s is away %s to %s; %s covers their %ss" % (person["name"], r["from"], r["to"], b["name"], kind)}


def reroute(value, kind, on=None):
    """(assignee, why) for a sub-task meant for `value`: their backup while they are away. The planner page or
    the roster not being readable leaves the assignee as given, so creating the sub-task never fails on it."""
    try:
        roster = people()
        person = find(roster, value)
        got = route(sprint_leave.load_time_off(), roster, person, kind, on or datetime.date.today())
    except Exception as exc:  # noqa: BLE001 - routing is a convenience, the request still goes out
        return value, "time-off planner not read (%s)" % exc
    return (got["jira_user"] or value), got["why"]


def hold_blocks(stories, person, row):
    why = "%s is away %s to %s%s" % (person["name"], row["from"], row["to"],
                                      "; backup %s" % row["stories_to"] if row.get("stories_to") else "")
    return "\n\n".join("SDLC-DASHBOARD-BACKLOG\nact: hold\nkey: %s\nwhy: %s\nEND" % (s, why) for s in stories)


def in_progress(jira_user):
    import backlog_cli
    jira = backlog_cli.Jira()
    got = jira.get("/api/2/search", jql='project = ACME AND issuetype = Story AND status = "In Progress" AND '
                                        'assignee = "%s"' % jira_user, fields="summary", maxResults=50)
    return [i["key"] for i in got.get("issues") or []]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("due", "record", "route", "holds", "remove", "sick"):
        p = sub.add_parser(name)
        p.add_argument("--person", required=True)
        p.add_argument("--today", default="")
    rec = sub.choices["record"]
    rec.add_argument("--none", action="store_true")
    rec.add_argument("--from", dest="start", default="")
    rec.add_argument("--to", dest="end", default="")
    rec.add_argument("--stories-to", default="")
    rec.add_argument("--questions-to", default="")
    rec.add_argument("--approvals-to", default="")
    rec.add_argument("--hold", action="store_true")
    rec.add_argument("--note", default="")
    rec.add_argument("--write", action="store_true")
    rec.add_argument("--by", default="")
    rm = sub.choices["remove"]
    rm.add_argument("--from", dest="start", required=True)
    rm.add_argument("--by", default="")
    rm.add_argument("--write", action="store_true")
    sk = sub.choices["sick"]
    sk.add_argument("--date", default="")
    sk.add_argument("--by", default="")
    sk.add_argument("--reason", default="sick", choices=sorted(REASONS))
    sk.add_argument("--write", action="store_true")
    ls = sub.add_parser("list")
    ls.add_argument("--person", default="")
    ls.add_argument("--today", default="")
    sub.choices["route"].add_argument("--kind", required=True, choices=sorted(KINDS))
    sub.choices["route"].add_argument("--date", default="")
    aw = sub.add_parser("away")
    aw.add_argument("--date", default="")
    a = ap.parse_args(argv)
    today = day(getattr(a, "today", "") or datetime.date.today().isoformat())
    roster = people()
    rows = sprint_leave.load_time_off()
    try:
        if a.cmd == "away":
            on = day(a.date) if a.date else today
            print(json.dumps(away(rows, on), indent=1))
            return 0
        if a.cmd == "list":
            got = upcoming(rows, today)
            if a.person:
                got = [r for r in got if r in mine(rows, find(roster, a.person))]
            print(json.dumps(got, indent=1))
            return 0
        person = find(roster, a.person)
        if a.cmd == "sick":
            try:
                by = find(roster, a.by)["name"] if a.by else ""
            except TimeOffError:
                by = a.by.strip()
            on = day(a.date or today.isoformat()).isoformat()
            new = record_sick(rows, person, on, today, by, REASONS[a.reason])
            print(sprint_leave.render_time_off(new))
            import sprint_sheet
            entry = {"date": on, "sprint": (sprint_sheet.covering(on) or [""])[0], "jira_user": person["jira_user"], "name": person["name"],
                     "kind": REASONS[a.reason], "by": by}
            if a.write:
                done = sprint_leave.save_time_off(new, by=by or person["name"], add=[entry])
                print(json.dumps({"version": done["version"]}))
                import unplanned_leave
                print(unplanned_leave.counter_line(person["name"], on, done["unplanned"]))
            else:
                print("Preview only: run again with --write.")
            return 0
        sick_row = a.cmd == "remove" and any(r.get("from") == day(a.start).isoformat() and
                                             r.get("kind") in UNPLANNED_KINDS for r in mine(rows, person))
        try:
            editor = find(roster, a.by) if getattr(a, "by", "") else person
        except TimeOffError:
            if not sick_row:
                raise
            editor = {"name": a.by.strip()}
        if a.cmd in ("record", "remove") and not sick_row:
            may_edit(editor, person)
        if a.cmd == "due":
            print(json.dumps({"person": person["name"], "due": due(rows, person, today), "question": QUESTION,
                              "follow_ups": FOLLOW_UPS, "planned": [r for r in mine(rows, person) if r.get("from")]},
                             indent=1))
            return 0
        if a.cmd == "route":
            print(json.dumps(route(rows, roster, person, a.kind, day(a.date) if a.date else today), indent=1))
            return 0
        if a.cmd == "holds":
            planned = [r for r in mine(rows, person) if r.get("from") and r.get("hold")]
            if not planned:
                print("%s has no time off with stories on hold." % person["name"])
                return 0
            print(hold_blocks(in_progress(person["jira_user"]), person, planned[-1]))
            return 0
        if a.cmd == "remove":
            new = remove(rows, person, a.start, today)
        elif a.none:
            new = record_none(rows, person, today)
        elif a.start and a.end:
            new = record_off(rows, roster, person, a.start, a.end, today, a.stories_to, a.questions_to,
                             a.approvals_to, a.hold, a.note)
        else:
            raise TimeOffError("give --none, or --from and --to")
        print(sprint_leave.render_time_off(new))
        import sprint_sheet
        sheets = sprint_sheet.apply_time_off(rows, new)
        for token, (_, changes) in sorted(sheets.items()):
            print("Sprint %s planning sheet:\n%s" % (token, "\n".join("  %s %s: %s -> %s" % (
                c[0], c[1], sprint_sheet.show(c[2]), sprint_sheet.show(c[3])) for c in changes)))
        if a.write:
            drop = [(person["jira_user"], person["name"], day(a.start).isoformat())] if sick_row else []
            print(json.dumps({"version": sprint_leave.save_time_off(new, by=editor["name"], drop=drop)["version"]}))
            for token, (sheet, _) in sorted(sheets.items()):
                print("\n".join(os.path.relpath(x, sprint_sheet.ROOT) for x in sprint_sheet.save(sheet)))
        else:
            print("Preview only: run again with --write after they say approved.")
        return 0
    except TimeOffError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
