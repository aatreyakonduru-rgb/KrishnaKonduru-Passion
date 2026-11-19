#!/usr/bin/env python3
"""Turn a PO roadmap spreadsheet into Jira epic drafts, and say what the PO still has to answer.

    python3 sdlc/framework/tools/roadmap_epics.py roadmap.xlsx            # drafts + questions as JSON
    python3 sdlc/framework/tools/roadmap_epics.py roadmap.csv --markdown  # the epic plan page
    python3 sdlc/framework/tools/roadmap_epics.py roadmap.xlsx --year-plan year-plan.yaml

Reads .xlsx and .csv with the standard library only. Column names are matched loosely (feature /
capability / epic → title, programme / specialty → programme, needed by / target / due → target, link /
confluence → source, notes / description → description, outcomes / acceptance → outcomes); any column it
cannot place is kept as a note on the row and reported, never silently dropped.

Each row is checked against the epic contract in .devin/rules/jira-ticket-standards.yaml (title at most
eight words with no phase, sprint or year; a two-to-three sentence objective plus a link; two to six
measurable outcomes; IT team; a fix version once the target is known; an AI label). Everything missing
becomes a question for the PO, grouped per epic. Nothing is written to Jira here: the drafts are in the
shape Backlog.create() takes, and that keeps the preview-first / writes-off behaviour of the Backlog tab.

Confluence links are checked with the team service account (bearer token in $ACME_CONFLUENCE_TOKEN). A page
the service ID cannot read becomes a question asking the PO to upload the document instead; a page it can
read is stamped with its version and date so a later run can tell the PO the source has moved on.
"""
import argparse
import csv
import datetime as dt
import io
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))

CONF_TOKEN_ENV = "ACME_CONFLUENCE_TOKEN"
CONF_HOST = (os.environ.get("SDLC_SANDBOX_URL") or "https://wiki.acme.example").rstrip("/")
IT_TEAM = "Acme-Claims-Web"
SPECIALTY_FILE = os.path.join(REPO, ".devin", "rules", "defect-specialties.yaml")
FOUNDATIONAL = "Foundational"
FOUNDATIONAL_ALIASES = ("foundational", "core", "platform", "cross-cutting", "application")
MAX_TITLE_WORDS = 8
SOURCE_STALE_DAYS = 90

COLUMN_HINTS = [
    ("title", ("feature", "capability", "epic", "item", "initiative", "title", "name", "what")),
    ("programme", ("programme", "program", "specialty", "speciality", "pod", "area", "product")),
    ("target", ("needed by", "needed", "target", "due", "by when", "when", "date", "quarter", "release")),
    ("source", ("confluence", "link", "url", "page", "brd", "spec")),
    ("outcomes", ("outcome", "acceptance", "success", "done when", "benefit")),
    ("description", ("description", "detail", "notes", "note", "why", "objective", "summary")),
    ("owner", ("owner", "po", "product owner", "requested by", "requester")),
    ("priority", ("priority", "rank", "order")),
    ("status", ("status", "state")),
]
DATED = re.compile(r"\b(DEV|SIT|UAT|\d\d\.\d(\.\d)?|20\d\d|Q[1-4])\b", re.IGNORECASE)
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


# ---- reading the sheet ----------------------------------------------------------------------

def _col_index(ref):
    n = 0
    for ch in ref:
        if ch.isalpha():
            n = n * 26 + ord(ch.upper()) - 64
        else:
            break
    return n - 1


def read_xlsx(data):
    """Rows of the first non-empty sheet, as lists of strings. Standard library only."""
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        shared = []
        if "xl/sharedStrings.xml" in zf.namelist():
            for si in ET.fromstring(zf.read("xl/sharedStrings.xml")).findall("m:si", NS):
                shared.append("".join(t.text or "" for t in si.iter("{%s}t" % NS["m"])))
        sheets = sorted(n for n in zf.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml$", n))
        for name in sheets:
            rows = []
            for row in ET.fromstring(zf.read(name)).iter("{%s}row" % NS["m"]):
                cells = {}
                for c in row.findall("m:c", NS):
                    v = c.find("m:v", NS)
                    text = ""
                    if c.get("t") == "s" and v is not None:
                        text = shared[int(v.text)]
                    elif c.get("t") == "inlineStr":
                        text = "".join(t.text or "" for t in c.iter("{%s}t" % NS["m"]))
                    elif v is not None:
                        text = v.text or ""
                        if c.get("s") and re.fullmatch(r"\d+(\.0+)?", text) and 20000 < float(text) < 80000:
                            text = (dt.date(1899, 12, 30) + dt.timedelta(days=int(float(text)))).isoformat()
                    cells[_col_index(c.get("r", "A1"))] = text.strip()
                if any(cells.values()):
                    width = max(cells) + 1
                    rows.append([cells.get(i, "") for i in range(width)])
            if rows:
                return rows
    return []


def read_csv(data):
    text = data.decode("utf-8-sig", "replace")
    return [[c.strip() for c in row] for row in csv.reader(io.StringIO(text)) if any(c.strip() for c in row)]


def read_sheet(path_or_name, data=None):
    if data is None:
        with open(path_or_name, "rb") as fh:
            data = fh.read()
    ext = os.path.splitext(str(path_or_name))[1].lower()
    if ext == ".xlsx":
        return read_xlsx(data)
    if ext == ".csv":
        return read_csv(data)
    raise ValueError("%s: give me an .xlsx or .csv export of the roadmap (.xls is not read)" % path_or_name)


def map_columns(header):
    """{field: column index}. Each field takes the first header that names it; leftovers are reported."""
    mapping, unmapped = {}, []
    for i, raw in enumerate(header):
        h = re.sub(r"[^a-z0-9 ]", " ", (raw or "").lower()).strip()
        if not h:
            continue
        for field, hints in COLUMN_HINTS:
            if field in mapping:
                continue
            if any(re.search(r"\b%s" % re.escape(k), h) for k in hints):
                mapping[field] = i
                break
        else:
            unmapped.append(raw)
    return mapping, unmapped


# ---- drafts ---------------------------------------------------------------------------------

def specialties(path=SPECIALTY_FILE):
    """Specialty names from defect-specialties.yaml, plus Foundational for the application itself."""
    names = []
    try:
        with open(path, encoding="utf-8") as fh:
            names = re.findall(r"^\s*-\s*name:\s*([A-Za-z]+)", fh.read(), re.MULTILINE)
    except OSError:
        pass
    return names + [FOUNDATIONAL]


def specialty_of(text):
    """The specialty named in a programme cell or title prefix, '' when it names none."""
    t = (text or "").strip().lower()
    if not t:
        return ""
    if t in FOUNDATIONAL_ALIASES:
        return FOUNDATIONAL
    for name in specialties():
        if re.search(r"\b%s\b" % re.escape(name.lower()), t) or t == name.lower():
            return name
    return ""


def _sentences(text):
    return [s for s in re.split(r"(?<=[.!?])\s+", (text or "").strip()) if s]


def _outcomes(text):
    parts = [p.strip(" -•*\t") for p in re.split(r"[\n;]|\d+[.)]\s", text or "") if p.strip(" -•*\t")]
    return parts


def _links(*texts):
    out = []
    for t in texts:
        out += re.findall(r"https?://[^\s)>\]]+", t or "")
    return out


def epic_draft(row, mapping, line):
    def col(field):
        i = mapping.get(field)
        return row[i] if i is not None and i < len(row) else ""
    title = re.sub(r"\s+", " ", col("title")).strip(" -–:")
    outcomes = _outcomes(col("outcomes"))
    links = _links(col("source"), col("description"))
    description = col("description").strip()
    extras = [row[i] for i in range(len(row)) if i not in mapping.values() and row[i]]
    specialty = specialty_of(col("programme")) or specialty_of(re.split(r"\s+-\s+", title, 1)[0])
    return {
        "specialty": specialty,
        "type": "Epic", "row": line, "summary": title, "programme": col("programme"),
        "target": col("target"), "owner": col("owner"), "priority": col("priority"),
        "sheet_status": col("status"), "description": description, "acceptance_list": outcomes,
        "acceptance": "\n".join("%d. %s" % (i + 1, o) for i, o in enumerate(outcomes)),
        "sources": links, "labels": ["AI-Used"] + ([specialty] if specialty else []),
        "it_team": IT_TEAM, "fix_version": "", "notes": extras,
    }


def contract_check(d):
    """What the epic contract says is still missing on this draft — each one a question for the PO."""
    q = []
    words = d["summary"].split()
    if not words:
        q.append(("summary", "Row %s has no feature name. What should the epic be called?" % d["row"]))
    else:
        if len(words) > MAX_TITLE_WORDS:
            q.append(("summary", "The title '%s' is %d words; the rule is at most %d. How should it be shortened?"
                      % (d["summary"], len(words), MAX_TITLE_WORDS)))
        if DATED.search(d["summary"]):
            q.append(("summary", "The title '%s' carries a phase, sprint, quarter or year; epics are named for the "
                      "capability only. What is the capability name?" % d["summary"]))
    if not d["specialty"]:
        q.append(("specialty", "Which specialty is '%s' for — %s — or is it Foundational (a change to the "
                  "application itself, not tied to a specialty)?%s"
                  % (d["summary"] or "this row", ", ".join(specialties()[:-1]),
                     " The sheet says '%s'." % d["programme"] if d["programme"] else "")))
    sents = _sentences(d["description"])
    if len(sents) < 2:
        have = "'%s'" % d["description"] if d["description"] else "nothing"
        q.append(("description", "Who benefits from '%s' and what changes for them? Two or three sentences, "
                  "please — the sheet has %s." % (d["summary"] or "this row", have)))
    if not d["sources"]:
        q.append(("source", "Is there a Confluence page or BRD for '%s'? Paste the link, or upload the document if "
                  "there is no page yet." % (d["summary"] or "this row")))
    n = len(d["acceptance_list"])
    if n < 2:
        q.append(("acceptance", "What are the business outcomes for '%s' — two to six things someone can measure "
                  "when it is done? (The sheet gives %d.)" % (d["summary"] or "this row", n)))
    elif n > 6:
        q.append(("acceptance", "'%s' lists %d outcomes; the rule is at most six. Which are the ones that define "
                  "done?" % (d["summary"], n)))
    if not d["target"]:
        q.append(("target", "When is '%s' needed by? A release or a month is enough; it sets the fix version."
                  % (d["summary"] or "this row")))
    elif not d["fix_version"]:
        q.append(("fix_version", "The sheet says '%s' is needed by '%s'. Which Jira fix version is that?"
                  % (d["summary"], d["target"])))
    if not d["owner"]:
        q.append(("owner", "Who owns '%s' in Jira (the Epic Owner field is empty on every UI epic today)?"
                  % (d["summary"] or "this row")))
    return q


# ---- Confluence sources -------------------------------------------------------------------

def page_id_of(url):
    m = re.search(r"pageId=(\d+)", url) or re.search(r"/pages/(\d+)", url)
    return m.group(1) if m else ""


class ConfluenceReader:
    """Reads a page with the service account; one /user/current check, no retry after 401/403."""

    def __init__(self, token=None, host=CONF_HOST, opener=None):
        self.token = token if token is not None else os.environ.get(CONF_TOKEN_ENV, "")
        self.host = host
        self.opener = opener or self._open
        self.validated = False
        self.locked = ""

    def _open(self, path):
        headers = {"Authorization": "Bearer " + self.token, "Accept": "application/json"}
        req = urllib.request.Request(self.host + path, headers=headers)
        with urllib.request.urlopen(req, context=ssl._create_unverified_context(), timeout=60) as resp:
            return json.loads(resp.read() or b"{}")

    def _get(self, path):
        try:
            return self.opener(path), ""
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                self.locked = "Confluence returned %d for the service account; not retrying." % exc.code
            return None, "HTTP %d" % exc.code
        except (urllib.error.URLError, OSError, ValueError) as exc:
            return None, str(exc)[:200]

    def check(self, url):
        """{url, readable, title, version, updated, why}. 'why' is what the PO is told when it is not readable."""
        out = {"url": url, "readable": False, "title": "", "version": 0, "updated": "", "why": ""}
        pid = page_id_of(url)
        if not pid:
            out["why"] = "the link has no page id (pageId=… or /pages/<id>/…), so it cannot be fetched"
            return out
        if not self.token:
            out["why"] = "no Confluence service-account token on this machine"
            return out
        if self.locked:
            out["why"] = self.locked
            return out
        if not self.validated:
            me, err = self._get("/rest/api/user/current")
            if me is None:
                out["why"] = self.locked or ("Confluence not reachable: " + err)
                return out
            self.validated = True
        page, err = self._get("/rest/api/content/%s?expand=version,space" % pid)
        if page is None:
            out["why"] = ("the service account cannot read this page (%s) — ask the space owner to grant it, or "
                          "upload the page as a document" % err)
            return out
        ver = page.get("version") or {}
        out.update(readable=True, title=page.get("title") or "", version=ver.get("number") or 0,
                   updated=(ver.get("when") or "")[:10], space=(page.get("space") or {}).get("key") or "")
        return out


def source_stamp(src, today=None):
    """One line for the epic description saying where the detail came from and when — the PO re-uploads on change."""
    today = today or dt.date.today().isoformat()
    if src.get("readable"):
        return ("Source: Confluence page \"%s\" (v%s, updated %s), read %s."
                % (src["title"], src["version"], src["updated"], today))
    return ("Source: document uploaded by the PO on %s (%s). A changed page means a fresh upload."
            % (today, src.get("name") or src.get("url") or ""))


def source_is_stale(stamp, today=None, days=SOURCE_STALE_DAYS):
    """True when an epic's Source line is older than `days` — the hygiene check that reminds the PO."""
    m = re.search(r"(read|uploaded by the PO on) (\d{4}-\d{2}-\d{2})", stamp or "")
    if not m:
        return False
    when = dt.date.fromisoformat(m.group(2))
    today = dt.date.fromisoformat(today) if isinstance(today, str) else (today or dt.date.today())
    return (today - when).days > days


# ---- the whole run --------------------------------------------------------------------------

def plan(rows, confluence=None, today=None):
    if not rows:
        raise ValueError("the sheet is empty")
    mapping, unmapped = map_columns(rows[0])
    if "title" not in mapping:
        raise ValueError("no column names the feature (looked for feature / capability / epic / item); "
                         "the headers are: %s" % ", ".join(h for h in rows[0] if h))
    drafts, questions, sources = [], [], []
    for n, row in enumerate(rows[1:], start=2):
        d = epic_draft(row, mapping, n)
        if not any([d["summary"], d["description"], d["sources"]]):
            continue
        for url in d["sources"]:
            src = confluence.check(url) if confluence else {"url": url, "readable": False, "why": "not checked"}
            sources.append(dict(src, epic=d["summary"]))
            if not src["readable"]:
                ask = ("I cannot read %s for '%s' (%s). Please upload it as a document here — and whenever "
                       "that page changes, upload the newer copy." % (url, d["summary"], src["why"]))
                questions.append({"epic": d["summary"], "row": n, "field": "source", "question": ask})
        for field, text in contract_check(d):
            questions.append({"epic": d["summary"], "row": n, "field": field, "question": text})
        drafts.append(d)
    return {"columns": {k: rows[0][v] for k, v in mapping.items()}, "unmapped_columns": unmapped,
            "epics": drafts, "questions": questions, "sources": sources,
            "ready": [d["summary"] for d in drafts if not [q for q in questions if q["row"] == d["row"]]]}


def to_markdown(result, title="Epic plan from the PO roadmap"):
    cols = ", ".join("%s ← %s" % (k, v) for k, v in result["columns"].items())
    out = ["# %s" % title, "", "Columns read: " + cols + "."]
    if result["unmapped_columns"]:
        out.append("Columns kept as notes (not mapped): " + ", ".join(result["unmapped_columns"]) + ".")
    out += ["", "%d epics, %d still have questions, %d ready to preview. Nothing is written to Jira by this page."
            % (len(result["epics"]), len({q["row"] for q in result["questions"]}), len(result["ready"])), ""]
    for d in result["epics"]:
        qs = [q for q in result["questions"] if q["row"] == d["row"]]
        out += ["## %s" % (d["summary"] or "(row %d — no title)" % d["row"]),
                "- Specialty: %s · Programme: %s · Needed by: %s · Owner: %s"
                % (d["specialty"] or "— (ask)", d["programme"] or "—", d["target"] or "—", d["owner"] or "—"),
                "- Description: %s" % (d["description"] or "—"),
                "- Outcomes: %s" % (" / ".join(d["acceptance_list"]) or "—"),
                "- Sources: %s" % (", ".join(d["sources"]) or "—"),
                "- IT team: %s · Labels: %s · Fix version: %s"
                % (d["it_team"], ", ".join(d["labels"]), d["fix_version"] or "— (from Needed by)")]
        if d["notes"]:
            out.append("- Also on the row: %s" % " | ".join(d["notes"]))
        out.append("- Status: %s" % ("ready to preview" if not qs else "%d question(s) for the PO" % len(qs)))
        for q in qs:
            out.append("  - [%s] %s" % (q["field"], q["question"]))
        out.append("")
    return "\n".join(out)


def to_year_plan(result, plan_year, source):
    def q(v):
        return json.dumps(v, ensure_ascii=False)

    """A year-plan.yaml fragment for /product-roadmap: every epic unsized, status from Needed by, nothing summed."""
    def status(d):
        t = d["target"]
        if not t:
            return "unknown"
        m = re.search(r"20\d\d", t)
        if not m:
            return "unknown"
        year = int(m.group())
        return "this_year" if year == plan_year else "next_year" if year > plan_year else "delivered"
    lines = ["# Generated by tools/roadmap_epics.py from %s — review before committing; every row is unsized."
             % source, "plan_year: %d" % plan_year, "next_year: %d" % (plan_year + 1),
             "source: %s" % q(source), "unsized:"]
    for d in result["epics"]:
        note = " · ".join(x for x in [d["programme"], "needed by " + d["target"] if d["target"] else ""] if x)
        lines += ["  - name: %s" % q(d["summary"]), "    status: %s" % status(d),
                  "    note: %s" % q(note)]
        if status(d) == "unknown":
            lines.append("    target_confirmed: false")
    lines += ["open_questions:"]
    for item in result["questions"]:
        lines += ["  - question: %s" % q(item["question"]), "    owner: PO"]
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("sheet")
    ap.add_argument("--markdown", action="store_true", help="print the epic plan page instead of JSON")
    ap.add_argument("--year-plan", metavar="OUT", help="also write a year-plan.yaml fragment for /product-roadmap")
    ap.add_argument("--plan-year", type=int, default=dt.date.today().year)
    ap.add_argument("--no-confluence", action="store_true", help="do not call Confluence for the links")
    a = ap.parse_args(argv)
    rows = read_sheet(a.sheet)
    result = plan(rows, None if a.no_confluence else ConfluenceReader())
    if a.year_plan:
        with open(a.year_plan, "w", encoding="utf-8") as fh:
            fh.write(to_year_plan(result, a.plan_year, os.path.basename(a.sheet)))
        print("wrote %s" % a.year_plan, file=sys.stderr)
    print(to_markdown(result) if a.markdown else json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
