#!/usr/bin/env python3
"""The sprint planning sheet, kept in the repo: one file per sprint, old sprints stay.

Each sprint is `context/sprint-sheets/<sprint>.json` (the cells and their formulas, tab by tab, the way the
Scrum Master's planning workbook has them) plus `<sprint>.html` built from it: the same sheet in the
browser, every cell a text box, worked out with the sheet's own formulas. On the Capacity tab a day cell is
1 (in), 0 (off), 0.5 (half day) or H (holiday); available hours = sum of the day cells x productive hours x
% on project, the team's hours / 8 are the points, and points x the AI factor are the points with AI.

When someone records time off (/vacation, or Argus after "approved") the same change goes to the
sheet, to that sprint's section of the Confluence page Acme Claims Sprint Leave and to its Time off and backups
table. The dashboard shows the sheet read only.

    sprint_sheet.py import XLSX --sprint 26.4.2 --start 2026-10-07 [--drop Sheet1]   a workbook into the repo
    sprint_sheet.py new 26.4.3 --start 2026-10-28 [--from 26.4.2]                    next sprint's sheet
    sprint_sheet.py list                                                             the sheets kept
    sprint_sheet.py show 26.4.2                                                      totals and days off, JSON
    sprint_sheet.py html 26.4.2                                                      rebuild the page
    sprint_sheet.py off 26.4.2 --person NAME --by NAME --dates D[,D] [--value 0|0.5|1|H] [--write]
    sprint_sheet.py edit 26.4.2 --by NAME --block FILE [--write]                     a pasted edits block
    sprint_sheet.py push 26.4.2 --by NAME [--write]                                  days off to the Sprint Leave page
"""
import argparse
import datetime
import html
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import team_links  # noqa: E402

ROOT = team_links.ROOT
SHEET_DIR = os.path.join(ROOT, "sdlc", "framework", "context", "sprint-sheets")
PEOPLE_PATH = os.path.join(ROOT, ".devin", "rules", "people.yaml")
CAPACITY_TAB = "Capacity"
EDITS_MARK = "# SDLC-SPRINT-SHEET-EDITS v1"
DAY_VALUES = {"0", "0.5", "1", "H"}
REF_RE = re.compile(r"^\$?([A-Z]{1,3})\$?(\d+)$")


class SheetError(Exception):
    pass


# ---- cell references ------------------------------------------------------------------------------

def col_num(letters):
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n


def col_name(n):
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def split_ref(ref):
    m = REF_RE.match(ref.upper())
    if not m:
        raise SheetError("%s is not a cell reference" % ref)
    return col_num(m.group(1)), int(m.group(2))


def shift_formula(formula, dcol, drow):
    """A shared formula moved from its master cell: relative references follow, $-anchored ones stay."""
    def move(m):
        if m.group(0).startswith('"'):
            return m.group(0)
        cabs, col, rabs, row = m.group(1), m.group(2), m.group(3), m.group(4)
        c = col if cabs else col_name(col_num(col) + dcol)
        r = row if rabs else str(int(row) + drow)
        return "%s%s%s%s" % (cabs, c, rabs, r)
    return re.sub(r'"[^"]*"|(\$?)\b([A-Z]{1,3})(\$?)(\d+)\b', move, formula)


# ---- formulas -------------------------------------------------------------------------------------

TOKEN_RE = re.compile(r'\s*(?:(?P<num>\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)|(?P<str>"[^"]*")|'
                      r'(?P<range>\$?[A-Z]{1,3}\$?\d+:\$?[A-Z]{1,3}\$?\d+)|(?P<ref>\$?[A-Z]{1,3}\$?\d+)|'
                      r'(?P<fn>[A-Z][A-Z0-9.]*)\s*\(|(?P<op><>|<=|>=|[-+*/^&=<>(),:]))')


def tokens(text):
    out, i = [], 0
    text = text.strip()
    while i < len(text):
        m = TOKEN_RE.match(text, i)
        if not m or m.end() == i:
            raise SheetError("cannot read formula %r at %r" % (text, text[i:]))
        kind = m.lastgroup
        val = m.group(kind)
        out.append((kind, val.upper() if kind in ("range", "ref", "fn") else val))
        i = m.end()
    return out


def number(v):
    if v is None or v == "":
        return 0.0
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip())
    except ValueError:
        raise SheetError("#VALUE!")


def matches(value, crit):
    m = re.match(r"^(<>|<=|>=|=|<|>)?(.*)$", str(crit))
    op, target = m.group(1) or "=", m.group(2)
    try:
        t = float(target)
        try:
            v = float(value)
        except (TypeError, ValueError):
            return op == "<>"
        return {"=": v == t, "<>": v != t, "<": v < t, ">": v > t, "<=": v <= t, ">=": v >= t}[op]
    except ValueError:
        same = str(value if value is not None else "").strip().lower() == target.strip().lower()
        return same if op == "=" else (not same if op == "<>" else False)


class Formula:
    """A small recursive-descent reader for the formulas the sheet uses: + - * / ^ &, comparisons,
    SUM, IF, COUNTIF, ROUND, MIN, MAX, AVERAGE. `get(ref)` returns a cell's value."""

    def __init__(self, text, get):
        self.t, self.i, self.get = tokens(text.lstrip("=")), 0, get

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def take(self, val=None):
        tok = self.peek()
        if val is not None and tok[1] != val:
            raise SheetError("expected %s" % val)
        self.i += 1
        return tok

    def run(self):
        v = self.compare()
        if self.i != len(self.t):
            raise SheetError("unexpected %r" % (self.peek()[1],))
        return v

    def compare(self):
        a = self.concat()
        while self.peek()[1] in ("=", "<>", "<", ">", "<=", ">="):
            op = self.take()[1]
            b = self.concat()
            if isinstance(a, str) or isinstance(b, str):
                x, y = str(a).lower(), str(b).lower()
            else:
                x, y = number(a), number(b)
            a = {"=": x == y, "<>": x != y, "<": x < y, ">": x > y, "<=": x <= y, ">=": x >= y}[op]
        return a

    def concat(self):
        a = self.add()
        while self.peek()[1] == "&":
            self.take()
            a = "%s%s" % (show(a), show(self.add()))
        return a

    def add(self):
        a = self.mul()
        while self.peek()[1] in ("+", "-"):
            op = self.take()[1]
            b = self.mul()
            a = number(a) + number(b) if op == "+" else number(a) - number(b)
        return a

    def mul(self):
        a = self.power()
        while self.peek()[1] in ("*", "/"):
            op = self.take()[1]
            b = number(self.power())
            if op == "/" and b == 0:
                raise SheetError("#DIV/0!")
            a = number(a) * b if op == "*" else number(a) / b
        return a

    def power(self):
        a = self.unary()
        while self.peek()[1] == "^":
            self.take()
            a = number(a) ** number(self.unary())
        return a

    def unary(self):
        if self.peek()[1] in ("+", "-"):
            op = self.take()[1]
            v = number(self.unary())
            return v if op == "+" else -v
        return self.primary()

    def primary(self):
        kind, val = self.take()
        if kind == "num":
            return float(val)
        if kind == "str":
            return val[1:-1]
        if kind == "ref":
            return self.get(val.replace("$", ""))
        if kind == "range":
            return self.cells(val)
        if kind == "fn":
            args = []
            if self.peek()[1] != ")":
                args.append(self.compare())
                while self.peek()[1] == ",":
                    self.take()
                    args.append(self.compare())
            self.take(")")
            return self.call(val, args)
        if val == "(":
            v = self.compare()
            self.take(")")
            return v
        raise SheetError("unexpected %r" % val)

    def cells(self, rng):
        a, b = rng.replace("$", "").split(":")
        c1, r1 = split_ref(a)
        c2, r2 = split_ref(b)
        return [self.get("%s%d" % (col_name(c), r)) for r in range(min(r1, r2), max(r1, r2) + 1)
                for c in range(min(c1, c2), max(c1, c2) + 1)]

    @staticmethod
    def flat(args):
        for a in args:
            if isinstance(a, list):
                for x in a:
                    yield x, True
            else:
                yield a, False

    def nums(self, args):
        out = []
        for v, in_range in self.flat(args):
            if in_range:
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    out.append(float(v))
            else:
                out.append(number(v))
        return out

    def call(self, name, args):
        if name == "SUM":
            return sum(self.nums(args))
        if name == "MIN":
            return min(self.nums(args) or [0.0])
        if name == "MAX":
            return max(self.nums(args) or [0.0])
        if name == "AVERAGE":
            n = self.nums(args)
            if not n:
                raise SheetError("#DIV/0!")
            return sum(n) / len(n)
        if name == "ROUND":
            return round(number(args[0]), int(number(args[1]) if len(args) > 1 else 0))
        if name == "IF":
            cond = args[0]
            ok = bool(number(cond)) if not isinstance(cond, str) else bool(cond)
            return args[1] if ok else (args[2] if len(args) > 2 else False)
        if name == "COUNTIF":
            rng = args[0] if isinstance(args[0], list) else [args[0]]
            return float(sum(1 for v in rng if matches(v, args[1])))
        raise SheetError("the sheet uses %s, which this page cannot work out" % name)


def show(v):
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float):
        r = round(v, 4)
        return str(int(r)) if r == int(r) else ("%.4f" % r).rstrip("0")
    return "" if v is None else str(v)


def raw(v):
    """A typed value the way a cell holds it: numbers as numbers, '=…' as a formula, anything else text."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return v
    s = str(v if v is not None else "").strip()
    if s.startswith("="):
        return s
    try:
        f = float(s)
        return int(f) if f == int(f) and "." not in s and "e" not in s.lower() else f
    except ValueError:
        return s


def evaluate(tab):
    """Every cell's value on one tab (formulas worked out; errors as '#…' text)."""
    cells, done, busy = tab["cells"], {}, set()

    def get(ref):
        if ref in done:
            return done[ref]
        v = cells.get(ref)
        if isinstance(v, str) and v.startswith("="):
            if ref in busy:
                return "#CIRCULAR!"
            busy.add(ref)
            try:
                v = Formula(v, get).run()
            except SheetError as exc:
                v = str(exc) if str(exc).startswith("#") else "#ERROR!"
            except (ZeroDivisionError, IndexError, KeyError):
                v = "#ERROR!"
            busy.discard(ref)
        elif isinstance(v, int) and not isinstance(v, bool):
            v = float(v)
        done[ref] = v
        return v

    for ref in cells:
        get(ref)
    return done


# ---- workbook import ------------------------------------------------------------------------------

M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def read_xlsx(path):
    """[(tab name, {ref: value or '=formula'}, {col: width}, [hidden cols])] with shared formulas expanded."""
    z = zipfile.ZipFile(path)
    strings = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall(M + "si"):
            strings.append("".join(t.text or "" for t in si.iter(M + "t")))
    rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
    out = []
    for sheet in ET.fromstring(z.read("xl/workbook.xml")).find(M + "sheets"):
        target = rels[sheet.get(R + "id")].lstrip("/")
        target = target if target.startswith("xl/") else "xl/" + target
        root = ET.fromstring(z.read(target))
        cells, masters, widths, hidden = {}, {}, {}, []
        for col in root.iter(M + "col"):
            for n in range(int(col.get("min")), int(col.get("max")) + 1):
                if col.get("width"):
                    widths[col_name(n)] = round(float(col.get("width")), 1)
                if col.get("hidden") in ("1", "true"):
                    hidden.append(col_name(n))
        for c in root.iter(M + "c"):
            ref, f, v = c.get("r"), c.find(M + "f"), c.find(M + "v")
            if f is not None and (f.text or f.get("si") is not None):
                if f.get("t") == "shared" and f.text:
                    masters[f.get("si")] = (ref, f.text)
                    cells[ref] = "=" + f.text
                elif f.get("t") == "shared":
                    mref, mtext = masters[f.get("si")]
                    (mc, mr), (cc, cr) = split_ref(mref), split_ref(ref)
                    cells[ref] = "=" + shift_formula(mtext, cc - mc, cr - mr)
                else:
                    cells[ref] = "=" + f.text
                continue
            if c.get("t") == "s" and v is not None:
                val = strings[int(v.text)]
            elif c.get("t") == "inlineStr":
                val = "".join(t.text or "" for t in c.iter(M + "t"))
            elif v is not None:
                val = v.text if c.get("t") in ("str", "e") else raw(v.text)
            else:
                continue
            if val not in ("", None):
                cells[ref] = val.strip() if isinstance(val, str) and not val.strip() == "" else val
        out.append((sheet.get("name").strip(), cells, widths, hidden))
    return out


def capacity_layout(tab):
    """Where things are on the Capacity tab, found from its header rows (not fixed letters)."""
    cells = tab["cells"]
    lay = {"name": None, "pto": None, "role": None, "location": None, "share": None, "hours": None, "days": []}
    for ref, v in cells.items():
        c, r = split_ref(ref)
        if r != 2 or not isinstance(v, str):
            continue
        low = " ".join(v.split()).lower()
        if low == "team member":
            lay["name"] = col_name(c)
        elif low.startswith("pto"):
            lay["pto"] = col_name(c)
        elif low.startswith("office"):
            lay["location"] = col_name(c)
        elif low.startswith("%age") or low.startswith("% on"):
            lay["share"] = col_name(c)
        elif low.startswith("available hours"):
            lay["hours"] = col_name(c)
        elif low in ("m", "t", "w", "f", "s"):
            lay["days"].append(col_name(c))
    lay["days"].sort(key=col_num)
    if not (lay["name"] and lay["share"] and lay["hours"] and lay["days"]):
        raise SheetError("the Capacity tab needs Team Member, %age of time, the day letters and Available hours in row 2")
    if lay["pto"]:
        lay["role"] = col_name(col_num(lay["pto"]) + 1)
    rows = []
    for ref, v in cells.items():
        c, r = split_ref(ref)
        if col_name(c) == lay["name"] and r > 2 and isinstance(v, str) and v.strip():
            rows.append(r)
    lay["rows"] = sorted(rows)
    return lay


def _half_day_hours(cells, lay):
    """Available hours count half days: the sheet's COUNTIF(days,1) becomes SUM(days) (H adds nothing)."""
    first, last = lay["days"][0], lay["days"][-1]
    for r in lay["rows"]:
        ref = "%s%d" % (lay["hours"], r)
        f = cells.get(ref)
        if isinstance(f, str):
            cells[ref] = re.sub(r"COUNTIF\(\s*(\$?%s\$?%d:\$?%s\$?%d)\s*,\s*1\s*\)" % (first, r, last, r),
                                r"SUM(\1)", f)


def import_xlsx(path, sprint, start, end="", drop=(), source=""):
    tabs = []
    for name, cells, widths, hidden in read_xlsx(path):
        if name in drop:
            continue
        tabs.append({"name": name, "cells": cells, "widths": widths, "hidden": hidden})
    sheet = {"sprint": sprint, "start": start, "end": end, "source": source or os.path.basename(path), "tabs": tabs}
    cap = tab_of(sheet, CAPACITY_TAB)
    lay = capacity_layout(cap)
    _half_day_hours(cap["cells"], lay)
    if not end:
        sheet["end"] = (day(start) + datetime.timedelta(days=len(lay["days"]) - 1)).isoformat()
    return sheet


# ---- one sprint's sheet ---------------------------------------------------------------------------

def day(value):
    try:
        return datetime.date.fromisoformat(str(value))
    except ValueError:
        raise SheetError("%s is not a date (YYYY-MM-DD)" % value)


def tab_of(sheet, name):
    for t in sheet["tabs"]:
        if t["name"].strip().lower() == name.lower():
            return t
    raise SheetError("the sheet has no %s tab" % name)


def path_of(sprint, ext="json", folder=None):
    if not re.fullmatch(r"\d+(\.\d+)*", sprint or ""):
        raise SheetError("%r is not a sprint number like 26.4.2" % sprint)
    return os.path.join(folder or SHEET_DIR, "%s.%s" % (sprint, ext))


def load(sprint, folder=None):
    p = path_of(sprint, folder=folder)
    if not os.path.exists(p):
        raise SheetError("no sheet for sprint %s in the repo yet (%s)" % (sprint, os.path.relpath(p, ROOT)))
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def sprints(folder=None):
    folder = folder or SHEET_DIR
    names = [f[:-5] for f in os.listdir(folder) if f.endswith(".json")] if os.path.isdir(folder) else []
    return sorted(names, key=lambda t: [int(x) for x in t.split(".")])


def save(sheet, folder=None):
    """Write the JSON and the page beside it; returns the two paths."""
    folder = folder or SHEET_DIR
    os.makedirs(folder, exist_ok=True)
    jp, hp = path_of(sheet["sprint"], "json", folder), path_of(sheet["sprint"], "html", folder)
    with open(jp, "w", encoding="utf-8") as fh:
        json.dump(sheet, fh, indent=1, sort_keys=False)
        fh.write("\n")
    with open(hp, "w", encoding="utf-8") as fh:
        fh.write(render_page(sheet))
    return jp, hp


def dates(sheet):
    lay = capacity_layout(tab_of(sheet, CAPACITY_TAB))
    start = day(sheet["start"])
    return {col: start + datetime.timedelta(days=i) for i, col in enumerate(lay["days"])}


def norm(name):
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def people(sheet):
    """Each person on the Capacity tab: name, role, share, hours worked out, and their days off / half / H."""
    cap = tab_of(sheet, CAPACITY_TAB)
    lay, vals, when = capacity_layout(cap), evaluate(cap), dates(sheet)
    out = []
    for r in lay["rows"]:
        def at(col):
            return vals.get("%s%d" % (col, r)) if col else None
        p = {"row": r, "name": str(at(lay["name"])).strip(), "role": show(at(lay["role"])),
             "location": show(at(lay["location"])), "pto_note": show(at(lay["pto"])),
             "allocation": round(number(at(lay["share"]) or 0) * 100, 2), "hours": number(at(lay["hours"]) or 0),
             "off": [], "half": [], "holiday": []}
        for col in lay["days"]:
            d = when[col]
            if d.weekday() >= 5:
                continue
            v = show(at(col)).upper()
            if v == "H":
                p["holiday"].append(d.isoformat())
            elif v in ("0", ""):
                p["off"].append(d.isoformat())
            elif v == "0.5":
                p["half"].append(d.isoformat())
        out.append(p)
    return out


TOTAL_NAMES = ["hours", "points", "points_with_ai"]


def total_refs(sheet):
    """The cells under the people in the Available hours column: team hours, points, points with AI."""
    cap = tab_of(sheet, CAPACITY_TAB)
    lay = capacity_layout(cap)
    last = max(lay["rows"]) if lay["rows"] else 2
    below = sorted(split_ref(ref)[1] for ref in cap["cells"]
                   if re.fullmatch(r"%s\d+" % lay["hours"], ref) and split_ref(ref)[1] > last)
    return {TOTAL_NAMES[i]: "%s%d" % (lay["hours"], r) for i, r in enumerate(below[:3])}


def totals(sheet):
    """Team hours, points and points with AI, as the sheet's formulas give them."""
    vals = evaluate(tab_of(sheet, CAPACITY_TAB))
    return {k: round(number(vals.get(ref)), 4) for k, ref in total_refs(sheet).items()}


def find_row(sheet, person):
    rows = [p for p in people(sheet) if norm(p["name"]) == norm(person)]
    if not rows:
        raise SheetError("%s is not on sprint %s's Capacity tab" % (person, sheet["sprint"]))
    return rows[0]["row"]


def set_days(sheet, person, on, value):
    """Day cells for one person: returns [(ref, date, old, new)] changed; weekends are left as they are."""
    if str(value).upper() not in DAY_VALUES:
        raise SheetError("a day cell takes 1, 0, 0.5 or H")
    cap = tab_of(sheet, CAPACITY_TAB)
    r, changes = find_row(sheet, person), []
    for col, d in dates(sheet).items():
        if d.isoformat() in on and d.weekday() < 5:
            ref = "%s%d" % (col, r)
            new = raw(str(value).upper())
            if cap["cells"].get(ref) != new:
                changes.append((ref, d.isoformat(), cap["cells"].get(ref), new))
                cap["cells"][ref] = new
    return changes


def edit(sheet, edits):
    """Apply {tab: {ref: typed text}}; returns [(tab, ref, old, new)]."""
    changes = []
    for name, cells in (edits or {}).items():
        tab = tab_of(sheet, name)
        for ref, val in cells.items():
            split_ref(ref)
            new = raw(val)
            if isinstance(new, str) and new.startswith("="):
                tokens(new[1:])
            old = tab["cells"].get(ref)
            if show(raw(old) if old is not None else "") != show(new):
                if new == "":
                    tab["cells"].pop(ref, None)
                else:
                    tab["cells"][ref] = new
                changes.append((name, ref, old, new))
    return changes


def only_own_days(sheet, edits, person):
    """True when every edit is a day cell on the person's own Capacity row."""
    cap = tab_of(sheet, CAPACITY_TAB)
    lay, row = capacity_layout(cap), find_row(sheet, person)
    for name, cells in (edits or {}).items():
        if name.strip().lower() != CAPACITY_TAB.lower():
            return False
        for ref in cells:
            c, r = split_ref(ref)
            if r != row or col_name(c) not in lay["days"]:
                return False
    return True


def new_sheet(sprint, start, prev):
    """Next sprint from the last one: same people, shares, hours and tabs; every weekday 1, weekends 0."""
    sheet = json.loads(json.dumps(prev))
    sheet.update(sprint=sprint, start=start, source="copied from sprint %s" % prev["sprint"])
    cap = tab_of(sheet, CAPACITY_TAB)
    lay = capacity_layout(cap)
    s = day(start)
    for i, col in enumerate(lay["days"]):
        d = s + datetime.timedelta(days=i)
        cap["cells"]["%s1" % col] = d.day
        for r in lay["rows"]:
            cap["cells"]["%s%d" % (col, r)] = 0 if d.weekday() >= 5 else 1
    if lay["pto"]:
        for r in lay["rows"]:
            cap["cells"].pop("%s%d" % (lay["pto"], r), None)
    weekdays = sum(1 for i in range(len(lay["days"])) if (s + datetime.timedelta(days=i)).weekday() < 5)
    for ref, v in list(cap["cells"].items()):
        if isinstance(v, str) and re.match(r"^\s*sprint days\s*=", v, re.I):
            cap["cells"][ref] = "Sprint Days = %d" % weekdays
    for tab in sheet["tabs"]:
        if tab is cap:
            continue
        header = all(isinstance(v, str) for ref, v in tab["cells"].items() if split_ref(ref)[1] == 1)
        for ref, v in list(tab["cells"].items()):
            if not (isinstance(v, str) and v.startswith("=")) and not (header and split_ref(ref)[1] == 1):
                del tab["cells"][ref]
    sheet["end"] = (s + datetime.timedelta(days=len(lay["days"]) - 1)).isoformat()
    return sheet


def current(on=None, folder=None):
    """The sprint whose sheet covers the date (today by default), else the latest sheet; None when none."""
    on = (on or datetime.date.today()).isoformat()
    have = sprints(folder)
    for t in reversed(have):
        sh = load(t, folder)
        if sh["start"] <= on <= sh["end"]:
            return t
    return have[-1] if have else None


def workbench_save(sprint, edits, by, write=False, client=None):
    """What Argus page sends: checked, shown as the change, and with write=True saved to the repo
    files and the Sprint Leave page."""
    sheet = load(sprint)
    who = may_edit(sheet, edits, by)
    changes = edit(sheet, edits)
    preview = "Sprint %s, by %s:\n%s" % (sprint, who, describe(changes) or "  no change")
    out = {"preview": preview, "totals": totals(sheet)}
    if write and changes:
        out["saved"] = [os.path.relpath(x, ROOT) for x in save(sheet)]
        out["confluence"] = push(sheet, who, client)["version"]
    return out


def covering(on, folder=None):
    """The sprints whose sheet has the date."""
    out = []
    for t in sprints(folder):
        sh = load(t, folder)
        if sh["start"] <= on <= sh["end"]:
            out.append(t)
    return out


def apply_time_off(rows_before, rows_after, folder=None):
    """A planner change into every sheet it touches: new days become 0, dropped days go back to 1. Sick days and
    ad hoc leave stay off the sheet: they are reported on the day, often from Teams, where Devin does not write to the repo.
    Returns {sprint: [(ref, date, old, new)]}; the caller saves with `save` when writing."""
    from sprint_leave import UNPLANNED_KINDS as unplanned

    def spans(rows):
        out = {}
        for r in rows or []:
            if r.get("from") and r.get("to") and r.get("kind") not in unplanned:
                d, end = day(r["from"]), day(r["to"])
                while d <= end:
                    out.setdefault(r.get("name", ""), set()).add(d.isoformat())
                    d += datetime.timedelta(days=1)
        return out
    before, after = spans(rows_before), spans(rows_after)
    touched = {}
    for t in sprints(folder):
        sh = load(t, folder)
        names = {norm(p["name"]): p["name"] for p in people(sh)}
        changes = []
        for who in set(before) | set(after):
            if norm(who) not in names:
                continue
            gone, new = before.get(who, set()) - after.get(who, set()), after.get(who, set()) - before.get(who, set())
            changes += set_days(sh, names[norm(who)], new, 0) if new else []
            changes += set_days(sh, names[norm(who)], gone, 1) if gone else []
        if changes:
            touched[t] = (sh, changes)
    return touched


def leave_section(sheet, current=None):
    """The sprint's section of the Sprint Leave page from the sheet; No leave and notes kept from the page."""
    roster = {}
    try:
        import yaml
        with open(PEOPLE_PATH, encoding="utf-8") as fh:
            for p in (yaml.safe_load(fh) or {}).get("people") or []:
                roster[norm(p.get("name"))] = p.get("jira_user", "")
    except (OSError, ImportError):
        pass
    old = {norm(p.get("name")): p for p in (current or {}).get("people") or []}
    ppl, holidays = [], None
    for p in people(sheet):
        was = old.get(norm(p["name"]), {})
        off = sorted(set(p["off"]))
        holidays = set(p["holiday"]) if holidays is None else holidays & set(p["holiday"])
        note = was.get("note", "")
        if p["half"]:
            half = "half day " + ", ".join(p["half"])
            note = half if not note or note.startswith("half day ") else note
        ppl.append({"jira_user": was.get("jira_user") or roster.get(norm(p["name"]), ""), "name": p["name"],
                    "allocation": p["allocation"], "off": off, "no_leave": bool(was.get("no_leave")) and not off,
                    "note": note})
    cap = tab_of(sheet, CAPACITY_TAB)
    hrs = number(cap["cells"].get("B1") or (current or {}).get("productive_hours") or 6)
    return {"start": sheet["start"], "end": sheet["end"], "productive_hours": hrs,
            "holidays": sorted(holidays or []), "people": ppl}


def push(sheet, by="", client=None):
    import sprint_leave
    import roster_sync
    client = client or roster_sync.ConfluenceClient()
    _, stored = sprint_leave.load(client)
    return sprint_leave.save(sheet["sprint"], leave_section(sheet, stored.get(sheet["sprint"])), by, client)


# ---- the page -------------------------------------------------------------------------------------

def _extent(tab):
    cols = rows = 0
    for ref in tab["cells"]:
        c, r = split_ref(ref)
        cols, rows = max(cols, c), max(rows, r)
    return cols, rows


def render_tab(sheet, tab, editable):
    vals = evaluate(tab)
    cols, rows = _extent(tab)
    is_cap = tab["name"].strip().lower() == CAPACITY_TAB.lower()
    lay = capacity_layout(tab) if is_cap else {"days": [], "hours": None}
    days = set(lay["days"])
    when = dates(sheet) if is_cap else {}
    hidden = set(tab.get("hidden") or [])
    names, day_cols = {}, {c for c in range(1, cols + 1) if col_name(c) in days}
    for c in range(1, cols + 1):
        top, sub = show(vals.get("%s1" % col_name(c))), show(vals.get("%s2" % col_name(c)))
        label = " ".join(x for x in (top, sub) if x) if c in day_cols else (sub or top)
        names[c] = label if label and not re.match(r"^[\d.]+$", label) else col_name(c)
    who_col = next((c for c in range(1, cols + 1) if re.search(r"member|name", names[c], re.I)), None)
    head = "<tr><th></th>%s</tr>" % "".join(
        '<th%s title="Column %s">%s</th>' % (' class="ss-hide"' if col_name(c) in hidden else
                                              ' class="ss-who"' if c == who_col else "", col_name(c),
                                              html.escape(names[c])) for c in range(1, cols + 1))
    body = []
    for r in range(1, rows + 1):
        tds = []
        who = next((show(vals.get("%s%d" % (col_name(c), r))) for c in range(1, cols + 1)
                    if re.search(r"[A-Za-z]{3}", show(vals.get("%s%d" % (col_name(c), r))) or "")), "")
        for c in range(1, cols + 1):
            ref = "%s%d" % (col_name(c), r)
            stored, val = tab["cells"].get(ref), vals.get(ref)
            text = show(val)
            cls = []
            if col_name(c) in hidden:
                cls.append("ss-hide")
            if c == who_col:
                cls.append("ss-who")
            if col_name(c) in days and r > 2:
                if when.get(col_name(c)) and when[col_name(c)].weekday() >= 5:
                    cls.append("ss-wkend")
                else:
                    cls.append({"0": "ss-off", "H": "ss-hol", "0.5": "ss-half"}.get(text.upper(), ""))
            if isinstance(stored, str) and stored.startswith("="):
                cls.append("ss-f")
            if text.startswith("#"):
                cls.append("ss-err")
            attr = ' class="%s"' % " ".join(x for x in cls if x) if any(cls) else ""
            if editable:
                width = (tab.get("widths") or {}).get(col_name(c))
                size = ' style="width:%sch"' % max(3, int(width or 8)) if width else ""
                tds.append('<td%s><input data-ref="%s" aria-label="%s" data-raw="%s" value="%s"%s%s></td>' % (
                    attr, ref, html.escape("%s, %s (%s)" % (who or "Row %d" % r, names[c], ref), quote=True), html.escape(show(stored) if stored is not None else "", quote=True),
                    html.escape(text, quote=True), size,
                    ' title="%s"' % html.escape(stored, quote=True) if isinstance(stored, str) and stored.startswith("=") else ""))
            else:
                tds.append("<td%s>%s</td>" % (attr, html.escape(text)))
        body.append("<tr><th>%d</th>%s</tr>" % (r, "".join(tds)))
    return ('<div class="a-table-scroll"><table class="ss" data-tab="%s"><thead>%s</thead><tbody>%s</tbody></table></div>'
            % (html.escape(tab["name"], quote=True), head, "".join(body)))


CSS = """
.ss{border-collapse:collapse;font-size:12px}
.ss th,.ss td{border:1px solid var(--a-border,#d0d5dd);padding:0;white-space:nowrap}
.ss thead th,.ss tbody th{background:var(--a-surface-2,#f2f4f7);padding:2px 6px;font-weight:600;position:sticky;top:0}
.ss tbody th{position:sticky;left:0;z-index:1;width:3.5ch;min-width:3.5ch;font-weight:400;font-size:10px;color:var(--a-muted,#667085)}
.ss thead th{white-space:normal;max-width:16ch;vertical-align:bottom;z-index:2}
.ss thead th:first-child{left:0;z-index:3}
.ss .ss-who{position:sticky;left:calc(3.5ch + 12px);z-index:1;background:var(--a-surface,#fff);box-shadow:2px 0 0 var(--a-border,#d0d5dd)}
.ss thead th.ss-who{z-index:3;background:var(--a-surface-2,#f2f4f7)}
.ss td{padding:2px 6px}
.ss td:has(input){padding:0}
.ss input{border:0;background:transparent;font:inherit;padding:2px 4px;width:7ch;color:inherit}
.ss input:focus{outline:2px solid #1b6ef3;background:#fff;color:#111}
.ss .ss-f{background:rgba(27,110,243,.06)}
.ss .ss-off{background:#f8d7da}
.ss .ss-half{background:#fff3cd}
.ss .ss-hol{background:#d1e7dd}
.ss .ss-wkend{background:var(--a-surface-2,#f2f4f7);color:#98a2b3}
.ss .ss-err{color:#b42318}
.ss .ss-hide{display:none}
.ss-sum{display:flex;gap:1.5rem;flex-wrap:wrap;margin:.5rem 0}
.ss-sum b{font-size:1.2em}
"""

JS = r"""
(function(){
var MARK = "# SDLC-SPRINT-SHEET-EDITS v1";
var sheet = JSON.parse(document.getElementById("ss-data").textContent);
var edits = {}, orig = {};
function cn(s){var n=0;for(var i=0;i<s.length;i++){n=n*26+s.charCodeAt(i)-64;}return n;}
function cl(n){var s="";while(n){var r=(n-1)%26;s=String.fromCharCode(65+r)+s;n=(n-1-r)/26;}return s;}
function sp(ref){var m=/^\$?([A-Z]{1,3})\$?(\d+)$/.exec(ref);return [cn(m[1]),+m[2]];}
var TK=/\s*(?:(\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)|("[^"]*")|(\$?[A-Z]{1,3}\$?\d+:\$?[A-Z]{1,3}\$?\d+)|(\$?[A-Z]{1,3}\$?\d+)|([A-Z][A-Z0-9.]*)\s*\(|(<>|<=|>=|[-+*\/^&=<>(),:]))/y;
function toks(t){var o=[],i=0;t=t.trim();while(i<t.length){TK.lastIndex=i;var m=TK.exec(t);if(!m||TK.lastIndex===i){throw "#ERROR!";}
 if(m[1]!==undefined)o.push(["num",m[1]]);else if(m[2]!==undefined)o.push(["str",m[2]]);else if(m[3]!==undefined)o.push(["range",m[3].toUpperCase()]);
 else if(m[4]!==undefined)o.push(["ref",m[4].toUpperCase()]);else if(m[5]!==undefined)o.push(["fn",m[5].toUpperCase()]);else o.push(["op",m[6]]);i=TK.lastIndex;}return o;}
function num(v){if(v===null||v===undefined||v==="")return 0;if(v===true)return 1;if(v===false)return 0;if(typeof v==="number")return v;var f=Number(String(v).trim());if(isNaN(f))throw "#VALUE!";return f;}
function show(v){if(v===true)return "TRUE";if(v===false)return "FALSE";if(typeof v==="number"){var r=Math.round(v*10000)/10000;return String(r);}return v===null||v===undefined?"":String(v);}
function crit(v,c){var m=/^(<>|<=|>=|=|<|>)?(.*)$/.exec(String(c)),op=m[1]||"=",t=m[2],tn=Number(t);
 if(t!==""&&!isNaN(tn)){var x=typeof v==="number"?v:Number(v);if(v===""||v===null||v===undefined||isNaN(x))return op==="<>";return {"=":x===tn,"<>":x!==tn,"<":x<tn,">":x>tn,"<=":x<=tn,">=":x>=tn}[op];}
 var same=String(v==null?"":v).trim().toLowerCase()===t.trim().toLowerCase();return op==="="?same:(op==="<>"?!same:false);}
function evalTab(tab){var cells=tab.cells,done={},busy={};
 function get(ref){if(ref in done)return done[ref];var v=cells[ref];if(typeof v==="string"&&v.charAt(0)==="="){if(busy[ref])return "#CIRCULAR!";busy[ref]=1;try{v=run(v.slice(1));}catch(e){v=(typeof e==="string"&&e.charAt(0)==="#")?e:"#ERROR!";}delete busy[ref];}
  if(v===undefined)v=null;done[ref]=v;return v;}
 function run(text){var t=toks(text),i=0;function pk(){return t[i]||[null,null];}function tk(x){var a=pk();if(x!==undefined&&a[1]!==x)throw "#ERROR!";i++;return a;}
  function cmp(){var a=cat();while(["=","<>","<",">","<=",">="].indexOf(pk()[1])>=0){var op=tk()[1],b=cat(),x,y;if(typeof a==="string"||typeof b==="string"){x=String(a).toLowerCase();y=String(b).toLowerCase();}else{x=num(a);y=num(b);}
   a={"=":x===y,"<>":x!==y,"<":x<y,">":x>y,"<=":x<=y,">=":x>=y}[op];}return a;}
  function cat(){var a=add();while(pk()[1]==="&"){tk();a=show(a)+show(add());}return a;}
  function add(){var a=mul();while(pk()[1]==="+"||pk()[1]==="-"){var op=tk()[1],b=mul();a=op==="+"?num(a)+num(b):num(a)-num(b);}return a;}
  function mul(){var a=pw();while(pk()[1]==="*"||pk()[1]==="/"){var op=tk()[1],b=num(pw());if(op==="/"&&b===0)throw "#DIV/0!";a=op==="*"?num(a)*b:num(a)/b;}return a;}
  function pw(){var a=un();while(pk()[1]==="^"){tk();a=Math.pow(num(a),num(un()));}return a;}
  function un(){if(pk()[1]==="+"||pk()[1]==="-"){var op=tk()[1],v=num(un());return op==="+"?v:-v;}return pr();}
  function rng(r){var p=r.replace(/\$/g,"").split(":"),a=sp(p[0]),b=sp(p[1]),o=[];o.isRange=true;for(var y=Math.min(a[1],b[1]);y<=Math.max(a[1],b[1]);y++)for(var x=Math.min(a[0],b[0]);x<=Math.max(a[0],b[0]);x++)o.push(get(cl(x)+y));return o;}
  function nums(args){var o=[];args.forEach(function(a){if(a&&a.isRange){a.forEach(function(v){if(typeof v==="number")o.push(v);});}else o.push(num(a));});return o;}
  function call(n,a){if(n==="SUM")return nums(a).reduce(function(s,x){return s+x;},0);if(n==="MIN"){var m=nums(a);return m.length?Math.min.apply(null,m):0;}if(n==="MAX"){var M=nums(a);return M.length?Math.max.apply(null,M):0;}
   if(n==="AVERAGE"){var v=nums(a);if(!v.length)throw "#DIV/0!";return v.reduce(function(s,x){return s+x;},0)/v.length;}
   if(n==="ROUND"){var k=Math.pow(10,a.length>1?num(a[1]):0);return Math.round(num(a[0])*k)/k;}
   if(n==="IF"){var c=a[0],ok=typeof c==="string"?!!c:!!num(c);return ok?a[1]:(a.length>2?a[2]:false);}
   if(n==="COUNTIF"){var r=a[0]&&a[0].isRange?a[0]:[a[0]];return r.filter(function(v){return crit(v,a[1]);}).length;}throw "#NAME?";}
  function pr(){var a=tk(),k=a[0],v=a[1];if(k==="num")return Number(v);if(k==="str")return v.slice(1,-1);if(k==="ref")return get(v.replace(/\$/g,""));if(k==="range")return rng(v);
   if(k==="fn"){var args=[];if(pk()[1]!==")"){args.push(cmp());while(pk()[1]===","){tk();args.push(cmp());}}tk(")");return call(v,args);}
   if(v==="("){var r=cmp();tk(")");return r;}throw "#ERROR!";}
  var out=cmp();if(i!==t.length)throw "#ERROR!";return out;}
 Object.keys(cells).forEach(get);return {get:get};}
function rawOf(s){s=String(s).trim();if(s.charAt(0)==="=")return s;if(s!==""&&!isNaN(Number(s)))return Number(s);return s;}
function recalc(){sheet.tabs.forEach(function(tab){var ev=evalTab(tab);
 if(/^capacity$/i.test(tab.name.trim())){document.querySelectorAll("[data-total]").forEach(function(b){if(b.dataset.total)b.textContent=show(ev.get(b.dataset.total));});}
 var t0=0,t=document.querySelector('table.ss[data-tab="'+CSS.escape(tab.name)+'"]');if(!t)return;
 t.querySelectorAll("input[data-ref]").forEach(function(inp){if(document.activeElement===inp)return;var v=ev.get(inp.dataset.ref);inp.value=show(v);
  var td=inp.parentNode;td.classList.toggle("ss-err",show(v).charAt(0)==="#");
  if(td.dataset.day&&!td.classList.contains("ss-wkend")){td.classList.toggle("ss-off",show(v)==="0");td.classList.toggle("ss-half",show(v)==="0.5");td.classList.toggle("ss-hol",show(v).toUpperCase()==="H");}});});
 var b=document.getElementById("ss-edits");if(b){var n=Object.keys(edits).reduce(function(s,k){return s+Object.keys(edits[k]).length;},0);document.getElementById("ss-count").textContent=n?n+" cell"+(n>1?"s":"")+" changed":"No changes yet";}}
document.querySelectorAll("table.ss").forEach(function(t){var lay=JSON.parse(t.dataset.days||"[]");
 t.querySelectorAll("input[data-ref]").forEach(function(inp){var col=inp.dataset.ref.replace(/\d+/g,""),row=+inp.dataset.ref.replace(/[A-Z]+/g,"");if(lay.indexOf(col)>=0&&row>2)inp.parentNode.dataset.day="1";
  inp.addEventListener("focus",function(){inp.value=inp.dataset.raw;});
  function commit(){var name=t.dataset.tab,tab=sheet.tabs.filter(function(x){return x.name===name;})[0],ref=inp.dataset.ref,nv=rawOf(inp.value),old=tab.cells[ref];
   var was=String(old===undefined?"":rawOf(old));orig[name]=orig[name]||{};if(!(ref in orig[name]))orig[name][ref]=was;
   if(String(nv)!==was){if(nv===""){delete tab.cells[ref];}else{tab.cells[ref]=nv;}inp.dataset.raw=String(nv);
    if(String(nv)===orig[name][ref]){if(edits[name]){delete edits[name][ref];if(!Object.keys(edits[name]).length)delete edits[name];}}
    else{(edits[name]=edits[name]||{})[ref]=String(nv);}}recalc();}
  inp.addEventListener("blur",commit);inp.addEventListener("change",commit);
  inp.addEventListener("keydown",function(e){if(e.key==="Enter"){e.preventDefault();inp.blur();}});});});
var save=document.getElementById("ss-save");
if(save){save.addEventListener("click",function(){var by=(document.getElementById("ss-by").value||"").trim(),out=document.getElementById("ss-edits"),msg=document.getElementById("ss-msg");
 if(!Object.keys(edits).length){msg.textContent="Nothing changed.";return;}if(!by){msg.textContent="Type your name first.";return;}
 var block=MARK+"\nsprint: "+sheet.sprint+"\nby: "+by+"\nedits: "+JSON.stringify(edits);
 if(location.protocol.indexOf("http")===0&&window.SS_SAVE_URL){msg.textContent="Showing the change…";
  fetch(window.SS_SAVE_URL,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({sprint:sheet.sprint,by:by,user:by,edits:edits,write:false})}).then(function(r){return r.json();}).then(function(p){
   if(p.error){msg.textContent=p.error;return;}out.value=p.preview||"";out.hidden=false;var ok=document.getElementById("ss-approve");ok.hidden=false;msg.textContent="Check the change, then press Approved and save.";
   ok.onclick=function(){fetch(window.SS_SAVE_URL,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({sprint:sheet.sprint,by:by,user:by,edits:edits,write:true})}).then(function(r){return r.json();}).then(function(d){
    msg.textContent=d.error?d.error:("Saved: "+(d.saved||[]).join(", ")+(d.confluence?" · Sprint Leave page version "+d.confluence:""));if(!d.error){edits={};orig={};ok.hidden=true;recalc();}});};});
 }else{out.value=block;out.hidden=false;out.select();msg.textContent="Copy this block and paste it to Devin; it shows the change and saves it after you type approved.";}});}
recalc();
})();
"""


def render_body(sheet, editable):
    tabs, panels = [], []
    for i, tab in enumerate(sheet["tabs"]):
        tid = "ss-tab-%d" % i
        tabs.append('<button type="button" class="a-btn" role="tab" aria-controls="%s"%s>%s</button>'
                    % (tid, ' aria-selected="true"' if i == 0 else "", html.escape(tab["name"])))
        days = capacity_layout(tab)["days"] if tab["name"].strip().lower() == CAPACITY_TAB.lower() else []
        panels.append('<section role="tabpanel" id="%s"%s>%s</section>'
                      % (tid, "" if i == 0 else " hidden",
                         render_tab(sheet, tab, editable).replace('<table class="ss"', "<table class=\"ss\" data-days='%s'" % json.dumps(days), 1)))
    t = totals(sheet)
    refs = total_refs(sheet)
    summary = ('<div class="ss-sum"><span>Team hours <b data-total="%s">%s</b></span><span>Story points <b data-total="%s">%s</b>'
               '</span><span>Story points with AI <b data-total="%s">%s</b></span><span>%s to %s</span></div>'
               % (refs.get("hours", ""), show(t.get("hours")), refs.get("points", ""), show(t.get("points")),
                  refs.get("points_with_ai", ""), show(t.get("points_with_ai")),
                  html.escape(sheet["start"]), html.escape(sheet["end"])))
    key = ('<p class="a-section__note">Day cells: <b>1</b> in, <b>0</b> off, <b>0.5</b> half day, <b>H</b> holiday. '
           'Available hours = sum of the day cells × productive hours × % on project; points = team hours ÷ 8; '
           'with AI = points × the AI factor. Shaded cells are formulas.</p>')
    out = summary + key + '<div data-a-tabs role="tablist">%s</div>%s' % ("".join(tabs), "".join(panels))
    if editable:
        out += ('<div class="ss-save"><label>Your name <input id="ss-by" class="a-input" placeholder="as on the roster"></label> '
                '<button type="button" class="a-btn" id="ss-save">Save</button> '
                '<button type="button" class="a-btn" id="ss-approve" hidden>Approved, save</button> '
                '<span id="ss-count" class="c-muted"></span> <span id="ss-msg"></span>'
                '<textarea id="ss-edits" rows="6" style="width:100%%" readonly hidden></textarea></div>'
                '<script type="application/json" id="ss-data">%s</script>'
                % json.dumps(sheet).replace("</", "<\\/"))
    return out


def render_page(sheet, editable=True, save_url=""):
    import artifact_kit
    body = render_body(sheet, editable)
    js = ("window.SS_SAVE_URL=%s;\n" % json.dumps(save_url) if save_url else "") + (JS if editable else "")
    return artifact_kit.render_page(
        "Acme Claims Sprint %s planning sheet" % sheet["sprint"], body,
        subtitle="Capacity, carry forward and AI savings, with the sheet's formulas. Kept in the repo; days off also go to the Acme Claims Sprint Leave page.",
        footnote="From %s. One file per sprint in sdlc/framework/context/sprint-sheets/." % html.escape(sheet.get("source", "")),
        extra_css=CSS, extra_js=js)


def render_fragment(sheet):
    """The read-only sheet for the dashboard (no inputs, no script)."""
    return "<style>%s</style>%s" % (CSS, render_body(sheet, editable=False))


# ---- edits blocks ---------------------------------------------------------------------------------

def parse_block(text):
    if EDITS_MARK not in text:
        raise SheetError("not a sprint sheet edits block (it starts with %s)" % EDITS_MARK)
    out = {}
    for line in text.split(EDITS_MARK, 1)[1].splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    try:
        out["edits"] = json.loads(out.get("edits") or "{}")
    except ValueError:
        raise SheetError("the edits line is not readable")
    return out


def may_edit(sheet, edits, by):
    """Anyone may change their own day cells; the Scrum Master (and the solution lead) anything."""
    import yaml
    with open(PEOPLE_PATH, encoding="utf-8") as fh:
        roster = (yaml.safe_load(fh) or {}).get("people") or []
    who = [p for p in roster if norm(p.get("name")) == norm(by) or (p.get("jira_user") or "").upper() == by.upper()]
    if not who:
        raise SheetError("%s is not on the roster (.devin/rules/people.yaml)" % by)
    p = who[0]
    if p.get("primary_role") in ("scrum_master", "solution_lead"):
        return p["name"]
    if only_own_days(sheet, edits, p["name"]):
        return p["name"]
    raise SheetError("%s may change only their own day cells; the Scrum Master changes the rest" % p["name"])


def describe(changes):
    return "\n".join("  %s: %s -> %s" % (" ".join(x for x in (c[0], c[1]) if x), show(c[2]) if c[2] is not None else "(empty)",
                                            show(c[3]) if c[3] != "" else "(empty)") for c in changes)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("import"); p.add_argument("xlsx"); p.add_argument("--sprint", required=True)
    p.add_argument("--start", required=True); p.add_argument("--end", default=""); p.add_argument("--drop", action="append", default=[])
    p.add_argument("--source", default="")
    p = sub.add_parser("new"); p.add_argument("sprint"); p.add_argument("--start", required=True); p.add_argument("--from", dest="prev", default="")
    sub.add_parser("list")
    for name in ("show", "html"):
        sub.add_parser(name).add_argument("sprint")
    p = sub.add_parser("off"); p.add_argument("sprint"); p.add_argument("--person", required=True); p.add_argument("--by", required=True)
    p.add_argument("--dates", required=True); p.add_argument("--value", default="0"); p.add_argument("--write", action="store_true")
    p = sub.add_parser("edit"); p.add_argument("sprint"); p.add_argument("--by", required=True); p.add_argument("--block", required=True)
    p.add_argument("--write", action="store_true")
    p = sub.add_parser("push"); p.add_argument("sprint"); p.add_argument("--by", default=""); p.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "import":
            sheet = import_xlsx(a.xlsx, a.sprint, a.start, a.end, set(a.drop), a.source)
            print("\n".join(os.path.relpath(x, ROOT) for x in save(sheet)))
            print(json.dumps(totals(sheet)))
            return 0
        if a.cmd == "new":
            have = sprints()
            prev = a.prev or (have[-1] if have else "")
            if not prev:
                raise SheetError("no earlier sheet to copy; import one first")
            if os.path.exists(path_of(a.sprint)):
                raise SheetError("sprint %s already has a sheet" % a.sprint)
            sheet = new_sheet(a.sprint, a.start, load(prev))
            print("\n".join(os.path.relpath(x, ROOT) for x in save(sheet)))
            return 0
        if a.cmd == "list":
            print(json.dumps([{"sprint": t, "start": load(t)["start"], "end": load(t)["end"]} for t in sprints()], indent=1))
            return 0
        sheet = load(a.sprint)
        if a.cmd == "show":
            print(json.dumps({"sprint": sheet["sprint"], "start": sheet["start"], "end": sheet["end"],
                              "totals": totals(sheet), "people": people(sheet)}, indent=1))
            return 0
        if a.cmd == "html":
            print("\n".join(os.path.relpath(x, ROOT) for x in save(sheet)))
            return 0
        if a.cmd == "push":
            sec = leave_section(sheet)
            print(json.dumps({p["name"]: p["off"] for p in sec["people"] if p["off"]}, indent=1))
            if a.write:
                print(json.dumps({"version": push(sheet, a.by)["version"]}))
            else:
                print("Preview only: run again with --write after they say approved.")
            return 0
        if a.cmd == "off":
            edits = None
            on = {day(d.strip()).isoformat() for d in a.dates.split(",") if d.strip()}
            row = find_row(sheet, a.person)
            lay = capacity_layout(tab_of(sheet, CAPACITY_TAB))
            edits = {CAPACITY_TAB: {"%s%d" % (col, row): a.value for col, d in dates(sheet).items() if d.isoformat() in on}}
            by = may_edit(sheet, edits, a.by)
            changes = set_days(sheet, a.person, on, a.value)
            del lay
        else:
            block = parse_block(open(a.block, encoding="utf-8").read() if os.path.exists(a.block) else a.block)
            if block.get("sprint") and block["sprint"] != a.sprint:
                raise SheetError("the block is for sprint %s, not %s" % (block["sprint"], a.sprint))
            by = may_edit(sheet, block["edits"], a.by)
            changes = [("%s %s" % (c[0], c[1]), "", c[2], c[3]) for c in edit(sheet, block["edits"])]
        print("Sprint %s, by %s:\n%s" % (a.sprint, by, describe([(c[0], c[1] or "", c[2], c[3]) for c in changes]) or "  no change"))
        print(json.dumps(totals(sheet)))
        if a.write and changes:
            print("\n".join(os.path.relpath(x, ROOT) for x in save(sheet)))
            print(json.dumps({"confluence_version": push(sheet, by)["version"]}))
        elif not a.write:
            print("Preview only: run again with --write after they say approved.")
        return 0
    except SheetError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
