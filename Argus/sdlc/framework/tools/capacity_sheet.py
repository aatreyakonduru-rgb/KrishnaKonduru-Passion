"""The Scrum Master's sprint capacity sheet (Excel), read the way its own formulas work it out.

Layout of the "Capacity" tab, as kept on SharePoint each sprint:
  row 1: "Productive Hours =6" and the day of the month over every day column;
  row 2: "Team Member", "PTO Plan", the role (no heading), "Office Location", "%age of time on Project",
         the weekday letter over every day column, then "Available hours";
  one row per person: 1 for a day they work, 0 for a day off.
Available hours = days marked 1 x productive hours x share of time on the project ("unassigned" rows
count 0), and the sprint capacity in story points is the team's hours / hours_per_point
(.devin/rules/scrum-master-metrics.yaml, 8 in the sheet). Reading only; standard library only.
"""
import datetime
import os
import re
import sys
import xml.etree.ElementTree as ET
import zipfile

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


def _col(ref):
    n = 0
    for ch in ref:
        if not ch.isalpha():
            break
        n = n * 26 + ord(ch.upper()) - 64
    return n - 1


def _row(ref):
    return int(re.sub(r"^[A-Z]+", "", ref.upper()))


def _norm(text):
    return " ".join(str(text or "").lower().split())


def _number(text):
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def cells(path, sheet="Capacity"):
    """{(row, col): text} for the named tab (first tab when there is no such name)."""
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        shared = []
        if "xl/sharedStrings.xml" in names:
            for si in ET.fromstring(zf.read("xl/sharedStrings.xml")).findall("m:si", NS):
                shared.append("".join(t.text or "" for t in si.iter("{%s}t" % NS["m"])))
        book = ET.fromstring(zf.read("xl/workbook.xml"))
        rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))}
        tabs = [(s.get("name") or "", rels.get(s.get(REL), "")) for s in book.find("m:sheets", NS)]
        if not tabs:
            raise ValueError("%s has no sheets" % path)
        target = next((t for n, t in tabs if _norm(n) == _norm(sheet)), tabs[0][1])
        target = target.lstrip("/")
        target = target if target.startswith("xl/") else "xl/" + target
        out = {}
        for c in ET.fromstring(zf.read(target)).iter("{%s}c" % NS["m"]):
            v = c.find("m:v", NS)
            if c.get("t") == "s" and v is not None:
                text = shared[int(v.text)]
            elif c.get("t") == "inlineStr":
                text = "".join(t.text or "" for t in c.iter("{%s}t" % NS["m"]))
            else:
                text = v.text if v is not None else ""
            if text not in ("", None):
                out[(_row(c.get("r")), _col(c.get("r")))] = str(text).strip()
        return out


def read(path, sprint_start=None):
    """The capacity sheet as plain data (JSON-friendly). `sprint_start` (YYYY-MM-DD) dates the day columns."""
    grid = cells(path)
    find = lambda pred: sorted(k for k, v in grid.items() if pred(_norm(v)))  # noqa: E731
    head = find(lambda v: v == "team member")
    if not head:
        raise ValueError("%s: no 'Team Member' heading on the Capacity tab" % os.path.basename(path))
    hr, name_col = head[0]
    heading = {c: _norm(v) for (r, c), v in grid.items() if r == hr}
    col_of = lambda pred: next((c for c, v in sorted(heading.items()) if pred(v)), None)  # noqa: E731
    alloc_col = col_of(lambda v: "time on project" in v)
    hours_col = col_of(lambda v: v == "available hours")
    loc_col = col_of(lambda v: "location" in v)
    pto_col = col_of(lambda v: v.startswith("pto"))
    if alloc_col is None or hours_col is None:
        raise ValueError("%s: the Capacity tab needs '%%age of time on Project' and 'Available hours'"
                         % os.path.basename(path))
    role_col = next((c for c in range(name_col + 1, alloc_col) if c not in heading), None)

    top = {c: v for (r, c), v in grid.items() if r == hr - 1}
    productive = sprint_days = None
    for c, v in sorted(top.items()):
        m = re.search(r"productive hours\s*=\s*([\d.]+)", _norm(v))
        if m:
            productive = float(m.group(1))
        m = re.search(r"sprint days\s*=\s*(\d+)", _norm(v))
        if m:
            sprint_days = int(m.group(1))
    if productive is None:
        raise ValueError("%s: no 'Productive Hours =' on the Capacity tab" % os.path.basename(path))

    day_cols = [c for c in range(alloc_col + 1, hours_col) if _number(top.get(c)) is not None]
    start = datetime.date.fromisoformat(sprint_start[:10]) if sprint_start else None
    days = []
    for i, c in enumerate(day_cols):
        number = int(_number(top[c]))
        date = start + datetime.timedelta(days=i) if start else None
        days.append({"day": number, "weekday": grid.get((hr, c), ""),
                     "date": date.isoformat() if date and date.day == number else None})
    working = [i for i, d in enumerate(days) if _norm(d["weekday"]) != "s"]

    people = []
    r = hr + 1
    while grid.get((r, name_col)):
        name = grid[(r, name_col)]
        share = _number(grid.get((r, alloc_col))) or 0.0
        marks = [_number(grid.get((r, c))) for c in day_cols]
        on = sum(1 for m in marks if m == 1)
        hours = 0.0 if _norm(name) == "unassigned" else on * productive * share
        people.append({"name": name, "role": grid.get((r, role_col), "") if role_col is not None else "",
                       "location": grid.get((r, loc_col), "") if loc_col is not None else "",
                       "pto_note": grid.get((r, pto_col), "") if pto_col is not None else "",
                       "allocation": share, "available_days": on,
                       "off_days": [i for i in working if marks[i] != 1],
                       "hours": round(hours, 2),
                       "sheet_hours": _number(grid.get((r, hours_col)))})
        r += 1
    return {"file": os.path.basename(path), "productive_hours": productive,
            "sprint_days": sprint_days or len(working), "days": days, "people": people,
            "total_hours": round(sum(p["hours"] for p in people), 2)}


def day_label(capacity, index):
    d = capacity["days"][index]
    if d.get("date"):
        return datetime.date.fromisoformat(d["date"]).strftime("%a %d %b").replace(" 0", " ")
    return "%s %s" % (d.get("weekday", ""), d["day"])


if __name__ == "__main__":
    import json
    print(json.dumps(read(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None), indent=1))
