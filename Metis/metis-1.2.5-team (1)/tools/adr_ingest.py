#!/usr/bin/env python3
"""Ingest Architecture Decision Records and incident post-mortems as staged KB pages.

    python3 adr_ingest.py scan  <kb> --repo NAME [--path SUBFOLDER]      list what was recognised (writes nothing)
    python3 adr_ingest.py stage <kb> --repo NAME [--path SUBFOLDER] [--dry-run]
    python3 adr_ingest.py docs  <kb> <scratch> [--kept-at WHERE] [--dry-run]   from a doc_intake.py scratch folder

What it reads. `--repo` is a repo named under sources.repos in <kb>/.metis/kb-profile.yaml (verify_kb.py resolves it the same way).
Recognised, from the headings and the folder:
    nygard       docs/adr/0001-*.md: Status, Context, Decision, Consequences
    madr         Context and Problem Statement, Decision Drivers, Considered Options, Decision Outcome (MADR 2 and 3, with or
                 without front matter)
    confluence   a page text that doc_intake.py wrote from a Confluence page (plain heading lines)
    postmortem   Timeline, Root cause, Action items (two of the three in an incident folder, all three elsewhere)
A file in an adr, decisions, postmortems or incidents folder needs fewer headings than one elsewhere. README, index and template
files are skipped. A heading is a markdown heading or a short plain line such as "Root cause".

What it writes. One page per record: context/decisions/<slug>.md or context/incidents/<slug>.md (folders come from
<kb>/.metis/doc-categories.yaml, else templates/doc-categories.decisions.yaml). Every line is a bullet with
[E: <repo>/<path>:<line> "quote"] (from documents: [E: doc:<id>#<place> "quote"]). A "Record" section holds status, date,
deciders, supersedes and superseded-by; "Related objects" lists graph object names (CROSS-LAYER/LINK_GRAPH.yaml) that appear in the
text. A line with a password, key, token or ID number is left out and listed; the page is never written with it.

Staging. When the KB is locked (kb_gate.py) the pages and the links file go to <kb>/_PENDING/<batch>/ with a digest, and a lead
certifies them. An unlocked KB is written directly. A page already in the KB that this tool did not make is not replaced: the new
text is written beside it as <name>.NEW.md. `docs` hands the pages to doc_kb.py publish, so who gave each document and where it is
kept are recorded, and the links go in a second batch.

Links. CROSS-LAYER/decisions.links.yaml gets one `references` link per record and graph object found in its text, with the
source line of the ADR as evidence. The per-link origin says how sure the match is:
    origin: named-in-text   the exact name (same spelling and case) is in the text
    origin: ai-proposed     only a looser match (case or separators differ); a person should confirm it
gen_graph.py sets an edge's origin from the file name (so today every edge from this file reads ai-proposed); the `origin` and `match`
keys are kept in the file for when it reads them (hook text in documentation/progress/W7-content.md).
"""
import argparse
import datetime
import os
import re
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import doc_kb  # noqa: E402
import kb_gate  # noqa: E402
import read_docs  # noqa: E402
import sensitive  # noqa: E402
import verify_kb  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
_DOC_KB_CATEGORIES = doc_kb.categories
GENERATOR = "adr_ingest.py"
EXTRA_CATEGORIES = os.path.join(HERE, "..", "templates", "doc-categories.decisions.yaml")
LINKS = "CROSS-LAYER/decisions.links.yaml"
SKIP_DIRS = {".git", "node_modules", "target", "build", "dist", "venv", ".venv", "__pycache__", ".idea", ".gradle"}
MAX_FILES, MAX_BYTES, MAX_OBJECTS = 3000, 1024 * 1024, 25

ALIASES = {
    "status": ["status"],
    "context": ["context", "context and problem statement", "background", "problem", "problem statement", "motivation"],
    "drivers": ["decision drivers", "drivers", "forces"],
    "options": ["considered options", "options", "options considered", "alternatives", "alternatives considered",
                "pros and cons of the options"],
    "decision": ["decision", "decision outcome", "outcome", "chosen option", "decision made"],
    "consequences": ["consequences", "positive consequences", "negative consequences", "implications", "consequence"],
    "summary": ["summary", "incident summary", "overview", "tl;dr", "tldr"],
    "impact": ["impact", "customer impact", "business impact"],
    "detection": ["detection", "how it was detected"],
    "timeline": ["timeline", "incident timeline", "chronology", "sequence of events"],
    "root cause": ["root cause", "root cause analysis", "rca", "cause", "causes", "contributing factors", "trigger"],
    "resolution": ["resolution", "mitigation", "remediation", "recovery"],
    "actions": ["action items", "actions", "follow-ups", "follow ups", "follow-up actions", "corrective actions",
                "corrective and preventive actions", "next steps"],
    "lessons": ["lessons learned", "lessons", "what went well", "what went wrong", "what went badly"],
}
CANON = {a: k for k, v in ALIASES.items() for a in v}
TITLES = {"context": "Context", "drivers": "Decision drivers", "options": "Considered options", "decision": "Decision",
          "consequences": "Consequences", "summary": "Summary", "impact": "Impact", "detection": "Detection",
          "timeline": "Timeline", "root cause": "Root cause", "resolution": "Resolution", "actions": "Action items",
          "lessons": "Lessons learned"}
ORDER = {"decision": ["context", "drivers", "options", "decision", "consequences"],
         "incident": ["summary", "impact", "detection", "timeline", "root cause", "resolution", "actions", "lessons"]}
INCIDENT_KEYS = ("timeline", "root cause", "actions")
HEAD = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
KV = re.compile(r"^[\s>*_-]*\**\s*(status|date|deciders?|decision[- ]makers?|decided by|authors?|owner|incident commander|severity|"
                r"duration|technical story)\s*\**\s*[:|]\s*\**\s*(.+?)\s*$", re.I)
META_LABEL = {"decision maker": "deciders", "decision makers": "deciders", "decision-makers": "deciders", "decided by": "deciders",
              "decider": "deciders", "author": "authors"}
META_ORDER = ("status", "date", "deciders", "authors", "owner", "incident commander", "severity", "duration", "technical story")
REL = re.compile(r"\b(supersedes|superseded by|replaces|replaced by)\b[:\s]*(.*)", re.I)
ADR_NUM = re.compile(r"\bADR[-_ ]?0*(\d+)\b", re.I)
LINK_NUM = re.compile(r"\b0*(\d{1,4})-[\w.-]*\.md\b")
PATH_HINT = re.compile(r"(^|/)(adrs?|decisions?|architecture-decisions?|postmortems?|post-mortems?|incidents?|retros?|rcas?)(/|$)")
NAME_HINT = re.compile(r"post-?mortem|incident|\badr[-_ ]?\d|rca", re.I)
SKIP_NAME = re.compile(r"(^|[-_/ ])(readme|index|template|templates)([-_. ]|$)", re.I)
STATUS_WORDS = ("proposed", "accepted", "deprecated", "superseded", "rejected", "approved", "draft", "decided", "adopted",
                "implemented", "resolved", "open", "closed")
DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
LIST_ITEM = re.compile(r"^(?:[-*+]|\d+[.)])\s+")


# ---- small helpers -----------------------------------------------------------------------------
def load_yaml(path):
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def categories(kb):
    """doc_kb.py's categories, plus decisions, incidents and procedures when the KB's own file does not have them."""
    cats = dict(_DOC_KB_CATEGORIES(kb))
    for c in load_yaml(EXTRA_CATEGORIES).get("categories") or []:
        if c.get("id") and c.get("folder"):
            cats.setdefault(c["id"], c)
    return cats


def squash(text):
    return " ".join(str(text or "").split())


def clean_quote(text, limit=90, around=None):
    """A piece of `text` that can go inside an evidence tag (no `]`, `;` or `"`), the longest one, or the one holding `around`.
    None when nothing usable is left. The result is always an exact substring of `text`."""
    parts = [p.strip() for p in re.split(r'[\];"]', str(text or ""))]
    parts = [p for p in parts if len(p) >= 3]
    if around:
        parts = [p for p in parts if around.lower() in p.lower()]
    if not parts:
        return None
    best = max(parts, key=len)
    if len(best) > limit:
        i = best.lower().find(around.lower()) if around else 0
        start = max(0, min(i - 20, len(best) - limit)) if around else 0
        best = best[start:start + limit].strip()
        if around and around.lower() not in best.lower():
            return None
    return best or None


def bare_safe(text):
    """Keep source text from looking like an evidence tag or a bare [A] / [E] / [?] tag to verify_kb.py."""
    text = re.sub(r"\[(A|E|\?)\]", r"(\1)", text)
    return re.sub(r"\[(E|\?):", r"(\1:", text)


def bullet_text(raw):
    """One source line as bullet text, or None for lines that carry nothing (rules, fences, empty table rows)."""
    s = raw.strip()
    if not s or s.startswith(("```", "~~~", "<!--", "![", "<img")) or re.match(r"^[-*_=]{3,}$", s):
        return None
    if s.startswith("|"):
        if re.match(r"^\|?[\s:|-]+\|?$", s):
            return None
        s = " | ".join(c.strip() for c in s.strip("|").split("|") if c.strip())
    s = re.sub(r"^#{1,6}\s+", "", s)
    s = LIST_ITEM.sub("", s)
    s = squash(s.replace("**", "").replace("__", ""))
    return bare_safe(s) or None


def slug_of(text):
    return doc_kb.slug(text)


class Source(object):
    """One file or document as rows of (ref, text), and how to write an evidence tag for a row."""

    def __init__(self, kind, name, rows, repo=None, rel=None, doc_id=None):
        self.kind, self.name, self.rows, self.repo, self.rel, self.doc_id = kind, name, rows, repo, rel, doc_id

    def tag(self, ref, text, around=None):
        q = clean_quote(text, around=around)
        if not q:
            return None
        if self.kind == "repo":
            return '[E: %s/%s:%s "%s"]' % (self.repo, self.rel, ref, q)
        return '[E: doc:%s#%s "%s"]' % (self.doc_id, ref, q)


# ---- recognising a record ----------------------------------------------------------------------
def canon(text):
    t = re.sub(r"^\d+[.)]\s*", "", str(text).strip().strip("*_# ").rstrip(":").strip().lower())
    return CANON.get(re.sub(r"\s+", " ", t))


def heading_of(t):
    """(level, text) for a markdown heading, or for a short plain line that is a known section name (level 0); else None."""
    m = HEAD.match(t)
    if m:
        return len(m.group(1)), squash(m.group(2).strip("*_ "))
    s = t.strip()
    if 0 < len(s) <= 40 and not LIST_ITEM.match(s) and canon(s):
        return 0, squash(s.strip("*_ ").rstrip(":"))
    return None


def classify(rows, strict=True):
    """(kind, format) for a text, or None. kind is decision or incident. `strict` asks for more headings (files outside the usual
    folders)."""
    names, heads = set(), set()
    for _, t in rows:
        h = heading_of(t)
        if h:
            heads.add(h[1].lower().rstrip(":"))
            if canon(h[1]):
                names.add(canon(h[1]))
    has_status = "status" in names or any(KV.match(t) and KV.match(t).group(1).lower() == "status" for _, t in rows[:40])
    if sum(1 for k in INCIDENT_KEYS if k in names) >= (3 if strict else 2):
        return "incident", "postmortem"
    madr = {"context and problem statement", "decision outcome", "considered options", "decision drivers"} & heads
    if len(madr) >= 2 or ("decision outcome" in heads and not strict):
        return "decision", "madr"
    core = {"context", "decision", "consequences"} & names
    if has_status and len(core) == 3:
        return "decision", "nygard"
    if not strict and "decision" in names and (len(core) >= 2 or has_status):
        return "decision", "adr"
    return None


def parse(rows):
    """{title, meta {key: (value, ref, raw)}, sections [{name, label, ref, text, rows}], rel_rows}."""
    rows, meta = list(rows), {}
    if rows and rows[0][1].strip() == "---":
        end = next((k for k in range(1, len(rows)) if rows[k][1].strip() == "---"), None)
        if end:
            for ref, t in rows[1:end]:
                m = re.match(r"^([A-Za-z][\w -]{0,30}):\s*(.+)$", t.strip())
                if m:
                    key = m.group(1).lower()
                    meta.setdefault(META_LABEL.get(key, key), (m.group(2).strip(" '\""), ref, t))
            rows = rows[end + 1:]
    title, sections, cur, pre = None, [], None, []
    for ref, t in rows:
        if not t.strip():
            continue
        h = heading_of(t)
        if h:
            level, text = h
            c = canon(text)
            if c:
                cur = {"name": c, "label": text.rstrip(":"), "ref": ref, "text": t, "rows": []}
                sections.append(cur)
            elif level == 1 and title is None and not sections:
                title = (text, ref, t)
            elif cur is not None:
                cur["rows"].append((ref, t))
            continue
        kv = KV.match(t)
        if kv and (cur is None or cur["name"] == "status"):
            key = kv.group(1).lower()
            meta.setdefault(META_LABEL.get(key, key), (kv.group(2), ref, t))
            continue
        if cur is None:
            if title is None and not REL.search(t):
                title = (squash(t), ref, t)
            else:
                pre.append((ref, t))
            continue
        cur["rows"].append((ref, t))
    rel_rows = list(pre)
    st = next((s for s in sections if s["name"] == "status"), None)
    for ref, t in (st["rows"] if st else []):
        if REL.search(t):
            rel_rows.append((ref, t))
        elif "status" not in meta:
            meta["status"] = (squash(LIST_ITEM.sub("", t.strip())), ref, t)
    if "status" in meta:
        rel_rows.append((meta["status"][1], meta["status"][2]))
    uniq = []
    for r in rel_rows:
        if r not in uniq and REL.search(r[1]):
            uniq.append(r)
    return {"title": title, "meta": meta, "sections": [s for s in sections if s["name"] != "status"], "rel_rows": uniq}


def norm_status(value):
    low = value.lower()
    for w in STATUS_WORDS:
        if re.search(r"\b%s\b" % w, low):
            return w
    return squash(value)[:40]


def number_of(rel, title):
    base = os.path.basename(rel)
    m = None if re.match(r"^\d{4}-\d{2}-\d{2}", base) else (re.match(r"^0*(\d{1,4})[-_ ]", base) or re.match(r"^adr[-_ ]?0*(\d+)", base, re.I))
    if not m and title:
        m = re.match(r"^(?:ADR[-_ ]?)?0*(\d{1,4})\b\s*[.:)-]", title, re.I) or re.match(r"^ADR[-_ ]?0*(\d{1,4})\b", title, re.I)
    return int(m.group(1)) if m and int(m.group(1)) > 0 else None


def core_title(title, number):
    if number is None:
        return (title or "").strip()
    t = re.sub(r"^(?:ADR[-_ ]?)?0*\d{1,4}\b\s*[.:)-]?\s*", "", title or "", flags=re.I).strip()
    return t or (title or "").strip()


def relation_ids(rel_rows):
    """[(label, [ADR numbers], ref, raw)] from lines such as `Superseded by [ADR-0005](0005-x.md)`."""
    out, seen = [], set()
    for ref, t in rel_rows:
        for m in REL.finditer(t):
            rest = m.group(2)
            nums = [int(n) for n in ADR_NUM.findall(rest)] + [int(n) for n in LINK_NUM.findall(rest)]
            if not nums:
                bare = re.match(r"^\W*#?0*(\d{1,4})\b", rest)
                nums = [int(bare.group(1))] if bare else []
            label = "Superseded by" if m.group(1).lower().startswith(("superseded", "replaced")) else "Supersedes"
            nums = sorted(n for n in set(nums) if n > 0)
            if nums and (label, tuple(nums)) not in seen:
                seen.add((label, tuple(nums)))
                out.append((label, nums, ref, t))
    return out


# ---- graph objects ---------------------------------------------------------------------------------
def graph_nodes(kb):
    out = []
    for n in load_yaml(os.path.join(kb, "CROSS-LAYER", "LINK_GRAPH.yaml")).get("nodes") or []:
        name = str(n.get("name") or "")
        if len(name) >= 3 and n.get("type") not in ("decision", "incident") and not re.search(r'[\];"]', name):
            out.append({"type": str(n.get("type")), "name": name})
    return out


def find_objects(nodes, lines):
    """Graph objects named in `lines` [(ref, raw)]: [{type, name, match: exact|loose, matched, ref, raw}], first hit per object.
    exact = same spelling and case as the graph name; loose = case or separators (_ - space) differ."""
    found = []
    for n in nodes:
        name = n["name"]
        exact = re.compile(r"(?<![\w])%s(?![\w])" % re.escape(name))
        tokens = [t for t in re.split(r"[_\-\s]+", name) if t]
        loose = re.compile(r"(?<![\w])%s(?![\w])" % "[ _-]?".join(re.escape(t) for t in tokens), re.I) if len(name) >= 5 else None
        hit = None
        for ref, raw in lines:
            m = exact.search(raw)
            if m:
                hit = {"match": "exact", "matched": m.group(0), "ref": ref, "raw": raw}
                break
        if hit is None and loose is not None:
            for ref, raw in lines:
                m = loose.search(raw)
                if m:
                    hit = {"match": "loose", "matched": m.group(0), "ref": ref, "raw": raw}
                    break
        if hit:
            found.append(dict(n, **hit))
    found.sort(key=lambda o: (o["match"] != "exact", o["name"]))
    return found[:MAX_OBJECTS]


# ---- building a page ---------------------------------------------------------------------------------
def build_page(src, hint_name, nodes, kind_fmt):
    """The page for one source: {title, kind, fmt, number, status, date, emitted, omitted, objects, src}. Every emitted line has its tag."""
    kind, fmt = kind_fmt
    p = parse(src.rows)
    number = number_of(hint_name, p["title"][0] if p["title"] else None) if kind == "decision" else None
    raw_title = ((p["title"][0] if p["title"] else None) or (p["meta"].get("title") or (None,))[0]
                 or os.path.splitext(os.path.basename(hint_name))[0])
    core = core_title(raw_title, number)
    title = ("ADR-%04d: %s" % (number, core)) if number is not None else core
    emitted, omitted = [], []

    def emit(section, ref, raw, text=None):
        bt = text if text is not None else bullet_text(raw)
        if not bt:
            return
        blocked = sorted({k for lvl, k, _ in sensitive.scan_line(raw) if lvl == sensitive.BLOCK})
        if blocked:
            omitted.append({"ref": ref, "kinds": blocked})
            return
        tag = src.tag(ref, raw)
        if tag:
            emitted.append({"sec": section, "text": bt, "tag": tag, "ref": ref, "raw": raw})

    meta = p["meta"]
    for key in META_ORDER:
        if key in meta:
            value, ref, raw = meta[key]
            if key == "status":
                value = norm_status(value)
            elif key == "date":
                m = DATE.search(value)
                value = m.group(1) if m else value
            emit("record", ref, raw, text="%s: %s" % (key.capitalize(), bare_safe(squash(value))))
    for label, nums, ref, raw in relation_ids(p["rel_rows"]):
        emit("record", ref, raw, text="%s: %s" % (label, ", ".join("ADR-%04d" % n for n in nums)))
    for s in p["sections"]:
        if s["rows"] and s["label"].lower() != TITLES.get(s["name"], "").lower():
            emit(s["name"], s["ref"], s["text"], text=bare_safe(s["label"]) + ":")
        for ref, raw in s["rows"]:
            emit(s["name"], ref, raw)
    date = None
    if "date" in meta:
        m = DATE.search(meta["date"][0])
        date = m.group(1) if m else None
    if date is None:
        m = DATE.search(os.path.basename(hint_name)) or DATE.search(title)
        date = m.group(1) if m else None
    objects = []
    for o in find_objects(nodes, [(e["ref"], e["raw"]) for e in emitted if e["sec"] != "record"]):
        tag = src.tag(o["ref"], o["raw"], around=o["matched"])
        if tag:
            objects.append(dict(o, tag=tag))
    return {"title": title, "kind": kind, "fmt": fmt, "number": number, "date": date,
            "status": norm_status(meta["status"][0]) if "status" in meta else None,
            "emitted": emitted, "omitted": omitted, "objects": objects, "src": src}


def render(page, category, today=None):
    """The page text."""
    src = page["src"]
    front = {"title": page["title"], "category": category, "generated_by": GENERATOR,
             "updated": today or datetime.date.today().isoformat(), "format": page["fmt"],
             "source": ("%s/%s" % (src.repo, src.rel)) if src.kind == "repo" else "doc:%s" % src.doc_id}
    if page["number"] is not None:
        front["adr_id"] = "ADR-%04d" % page["number"]
    for k in ("status", "date"):
        if page[k]:
            front[k] = page[k]
    by = {}
    for e in page["emitted"]:
        by.setdefault(e["sec"], []).append("- %s %s" % (e["text"], e["tag"]))
    L = ["# %s" % page["title"], ""]
    if by.get("record"):
        L += ["## Record", ""] + by["record"] + [""]
    names = ORDER[page["kind"]] + [k for k in by if k not in ORDER[page["kind"]] and k != "record"]
    for name in names:
        if by.get(name):
            L += ["## %s" % TITLES.get(name, name.capitalize()), ""] + by[name] + [""]
    objs = ["- %s (%s): %s %s" % (o["name"], o["type"], "named in the text" if o["match"] == "exact" else
                                  "a similar name appears in the text", o["tag"]) for o in page["objects"]]
    if objs:
        L += ["## Related objects", ""] + objs + [""]
    return "---\n%s---\n\n%s\n" % (yaml.safe_dump(front, sort_keys=False, allow_unicode=True), "\n".join(L).rstrip("\n"))


def link_records(page):
    return [{"from": {"type": page["kind"], "name": page["title"]}, "rel": "references", "to": {"type": o["type"], "name": o["name"]},
             "source": o["tag"], "origin": "named-in-text" if o["match"] == "exact" else "ai-proposed",
             "match": "exact-name" if o["match"] == "exact" else "loose-name"} for o in page["objects"]]


# ---- reading a repo -------------------------------------------------------------------------------
def repo_base(kb, repo):
    full, err = verify_kb.Checker(kb).repo_path(repo + "/")
    if err:
        raise ValueError(err)
    full = os.path.abspath(full)
    if not os.path.isdir(full):
        raise ValueError("repo folder not found: %s" % full)
    return full


def read_rows(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return [(i, t) for i, t in enumerate(fh.read().splitlines(), 1)]


def repo_files(base, sub=None, exts=(".md", ".markdown", ".txt")):
    top = os.path.normpath(os.path.join(base, sub)) if sub else base
    if not (top == base or top.startswith(base + os.sep)) or not os.path.isdir(top):
        raise ValueError("folder not found inside the repo: %s" % sub)
    n = 0
    for d, dirs, files in os.walk(top):
        dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS)
        for f in sorted(files):
            if f.lower().endswith(exts):
                n += 1
                if n > MAX_FILES:
                    return
                yield os.path.relpath(os.path.join(d, f), base).replace(os.sep, "/")


def plan_repo(kb, repo, sub=None):
    """([page], [notes]) for a repo folder."""
    base, nodes, pages, notes = repo_base(kb, repo), graph_nodes(kb), [], []
    for rel in repo_files(base, sub):
        full = os.path.join(base, *rel.split("/"))
        if SKIP_NAME.search(rel) or os.path.getsize(full) > MAX_BYTES:
            continue
        rows = read_rows(full)
        hinted = bool(PATH_HINT.search(rel.lower()) or NAME_HINT.search(os.path.basename(rel)))
        cf = classify(rows, strict=not hinted)
        if not cf:
            continue
        if re.search(r"[:\s]", rel + repo):
            notes.append("%s: left out; a path with a space or colon cannot be written in an evidence tag" % rel)
            continue
        pg = build_page(Source("repo", rel, rows, repo=repo, rel=rel), rel, nodes, cf)
        if pg["emitted"]:
            pages.append(pg)
    return pages, notes


def plan_docs(kb, scratch):
    """([page], [notes]) from a doc_intake.py scratch folder."""
    man = read_docs.load_manifest(scratch).get("documents", {})
    nodes, pages, notes = graph_nodes(kb), [], []
    for did, d in man.items():
        if d.get("status") != "read":
            continue
        rows = []
        with open(os.path.join(scratch, did + ".txt"), encoding="utf-8") as fh:
            for line in fh:
                m = re.match(r"^\[([^\]]+)\] (.*)$", line.rstrip("\n"))
                if m:
                    rows.append((m.group(1), m.group(2)))
        name = d.get("name") or did
        plain = any(re.match(r"^page_id:\s*\S+", t) for _, t in rows[:12])
        body = [(r, t) for r, t in rows if not re.match(r"^(page_id|version|space|updated|path|url):\s", t)]
        cf = classify(body, strict=False)
        if not cf or SKIP_NAME.search(name):
            continue
        if cf[1] in ("nygard", "adr"):
            cf = (cf[0], "confluence" if plain else "document")
        pg = build_page(Source("doc", name, body, doc_id=did), name, nodes, cf)
        if pg["emitted"]:
            pages.append(pg)
    return pages, notes


# ---- writing -----------------------------------------------------------------------------------------------
def is_ours(path, generators=(GENERATOR,)):
    if not os.path.isfile(path):
        return False
    with open(path, encoding="utf-8", errors="replace") as fh:
        meta, _ = doc_kb.split_front(fh.read())
    return meta.get("generated_by") in generators


def target(kb, rel, generators=(GENERATOR,)):
    """The path a page is written to: its own, or <name>.NEW.md beside a page this tool did not make."""
    if os.path.exists(os.path.join(kb, *rel.split("/"))) and not is_ours(os.path.join(kb, *rel.split("/")), generators):
        return rel[:-3] + ".NEW.md"
    return rel


def page_rel(kb, page, cats):
    cat = "decisions" if page["kind"] == "decision" else "incidents"
    stem = page["title"] if page["kind"] == "decision" or not page["date"] or page["date"] in page["title"] \
        else "%s %s" % (page["date"], page["title"])
    return cat, "%s/%s.md" % (cats[cat]["folder"].strip("/"), slug_of(stem))


def merge_links(kb, new, replace_titles):
    """The text of decisions.links.yaml: what is there, minus links from the records being staged again, plus the new ones."""
    old = load_yaml(os.path.join(kb, *LINKS.split("/"))).get("links") or []
    keep = [l for l in old if (l.get("from") or {}).get("name") not in replace_titles]
    head = ("# Written by adr_ingest.py: decisions and incidents -> the graph objects named in their text.\n"
            "# origin named-in-text: the exact name is in the text. origin ai-proposed: a looser match; confirm before relying on it.\n")
    return head + yaml.safe_dump({"links": keep + new}, sort_keys=False, allow_unicode=True, width=100000)


def write_files(kb, files, batch_name, dry=False):
    """Check, then write {rel: text}. Nothing is written when any file has a source problem or a secret. A locked KB gets a
    _PENDING batch and a digest. Returns {written, batch, digest, problems}."""
    res = {"written": [], "batch": None, "digest": None, "problems": []}
    chk = verify_kb.Checker(kb)
    for rel, text in sorted(files.items()):
        found, _ = kb_gate.source_problems(kb, rel, text, chk)
        res["problems"] += ["%s:%d: %s" % (rel, n, why) for _, n, why in found]
        res["problems"] += ["%s:%d: %s (%s)" % (rel, f["line"], f["kind"], f["level"]) for f in kb_gate.findings(rel, text)
                            if f["level"] == sensitive.BLOCK]
    if res["problems"]:
        return res
    res["written"] = sorted(files)
    if dry:
        return res
    if kb_gate.is_locked(kb):
        res["batch"] = kb_gate.new_batch(kb, batch_name)
        for rel, text in files.items():
            kb_gate.stage_text(kb, res["batch"], rel, text)
        res["digest"], _ = kb_gate.digest(kb, res["batch"])
    else:
        for rel, text in files.items():
            dst = os.path.join(kb, *rel.split("/"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
    return res


def stage_repo(kb, repo, sub=None, dry=False):
    kb = os.path.abspath(kb)
    pages, notes = plan_repo(kb, repo, sub)
    cats = categories(kb)
    files, links, titles, used = {}, [], set(), {}
    for pg in pages:
        cat, rel = page_rel(kb, pg, cats)
        if rel in used:
            notes.append("%s: same page name as %s; left out" % (pg["src"].rel, used[rel]))
            continue
        used[rel] = pg["src"].rel
        files[target(kb, rel)] = render(pg, cat)
        links += link_records(pg)
        titles.add(pg["title"])
        notes += ["%s line %s: left out (%s)" % (pg["src"].rel, om["ref"], ", ".join(om["kinds"])) for om in pg["omitted"]]
    res = {"pages": sorted(files), "notes": notes, "links": len(links), "written": [], "batch": None, "digest": None, "problems": []}
    if not files:
        return res
    if links:
        files[LINKS] = merge_links(kb, links, titles)
    out = write_files(kb, files, "decisions", dry)
    res.update({k: out[k] for k in ("written", "batch", "digest", "problems")})
    return res


def publish_docs(kb, scratch, kept_at=None, dry=False):
    """Write the pages to <scratch>/pages/ and let doc_kb.publish check, stage and record them (who gave each document, where
    it is kept). The links go in a second write after that. Returns doc_kb.publish's exit code."""
    kb, scratch = os.path.abspath(kb), os.path.abspath(scratch)
    pages, notes = plan_docs(kb, scratch)
    cats = categories(kb)
    out = os.path.join(scratch, "pages")
    os.makedirs(out, exist_ok=True)
    titles, links = set(), []
    for pg in pages:
        cat, _ = page_rel(kb, pg, cats)
        meta, body = doc_kb.split_front(render(pg, cat))
        small = "---\n%s---\n\n%s" % (yaml.safe_dump({"title": meta["title"], "category": cat}, sort_keys=False, allow_unicode=True), body)
        with open(os.path.join(out, "adr-%s.md" % slug_of(pg["title"])), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(small)
        titles.add(pg["title"])
        links += link_records(pg)
        notes += ["%s line %s: left out (%s)" % (pg["src"].name, om["ref"], ", ".join(om["kinds"])) for om in pg["omitted"]]
    for n in notes:
        print(n)
    if not titles:
        print("docs: no decision or incident records found in %s" % scratch)
        return 0
    real = doc_kb.categories
    doc_kb.categories = categories      # doc_kb.py does not know decisions / incidents until its category file is merged
    try:
        rc = doc_kb.publish(kb, scratch, kept_at, dry)
    finally:
        doc_kb.categories = real
    if rc == 0 and links and not dry:
        res = write_files(kb, {LINKS: merge_links(kb, links, titles)}, "decisions-links")
        if res["problems"]:
            print("\n".join(res["problems"]))
            print("links: not written")
            return 1
        print("links: %d in %s%s" % (len(links), LINKS, " (batch %s; certify it too)" % res["batch"] if res["batch"] else ""))
    return rc


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("scan", "stage"):
        a = sub.add_parser(name); a.add_argument("kb"); a.add_argument("--repo", required=True); a.add_argument("--path")
        if name == "stage":
            a.add_argument("--dry-run", action="store_true")
    a = sub.add_parser("docs"); a.add_argument("kb"); a.add_argument("scratch"); a.add_argument("--kept-at"); a.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    kb = os.path.abspath(args.kb)
    try:
        if args.cmd == "docs":
            return publish_docs(kb, args.scratch, args.kept_at, args.dry_run)
        if args.cmd == "scan":
            pages, notes = plan_repo(kb, args.repo, args.path)
            for pg in pages:
                print("%s\t%s\t%s\t%s\t%s\t%d lines, %d objects" % (pg["src"].rel, pg["kind"], pg["fmt"], pg["title"], pg["status"] or "-",
                                                                   len(pg["emitted"]), len(pg["objects"])))
            for n in notes:
                print(n)
            print("%d records recognised" % len(pages))
            return 0
        res = stage_repo(kb, args.repo, args.path, args.dry_run)
    except (ValueError, kb_gate.GateError) as err:
        print("error: %s" % err, file=sys.stderr)
        return 2
    for n in res["notes"]:
        print(n)
    if res["problems"]:
        print("\n".join(res["problems"]))
        print("stage: %d problems, nothing written" % len(res["problems"]))
        return 1
    for rel in res["written"]:
        print("%s%s" % ("would write " if args.dry_run else "", rel))
    if res["batch"]:
        print("staged in batch %s, not in the KB yet; a lead must certify it. Digest: %s" % (res["batch"], res["digest"]))
    print("%d pages, %d links%s" % (len(res["pages"]), res["links"], " (dry run)" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
