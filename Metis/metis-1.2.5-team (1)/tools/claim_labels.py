#!/usr/bin/env python3
"""Per-claim environment and sensitivity labels, and who may see which line.

    python3 claim_labels.py audit  <kb> [--role WHO ...] [--queries N]     build a pack, search, answer and export as an uncleared role and
                                                                          exit 1 if any withheld line shows up
    python3 claim_labels.py scan   <kb> [--page REL]                       every line with a label (own, inherited or forced)
    python3 claim_labels.py report <kb> [--json]                           counts by sensitivity and environment, secrets forced to restricted
    python3 claim_labels.py filter <kb> --out DIR (--max LEVEL | --role WHO) [--page REL]
                                                                          copy a page or the whole KB with lines above the level removed
    python3 claim_labels.py check  <kb>                                    restricted lines outside a restricted folder; file/line label conflicts

A line may carry labels AFTER its [E: ...] tag (and after a facts_time.py annotation, in a group of its own):

    - Payer portal password is rotated monthly [E: file:ops.txt "rotated monthly"] {env: prod; sensitivity: restricted}

Keys: `env` (a short word such as prod, uat, test, dev, all) and `sensitivity` (public < internal < confidential < restricted).
A group with any other key is ignored, so `{valid-from: ...}` and `{env: ...}` stay in separate groups. verify_kb.py ignores both.

Defaults for a whole page come from its front matter (`env:` and `sensitivity:`). A page in a folder listed under
`labels.restricted_folders` of <kb>/.metis/kb-profile.yaml (globs, relative to the KB) is at least `restricted`. A page with no
sensitivity is `labels.default_sensitivity` (default `internal`). A label on a heading covers the lines under it, down to the next
heading of the same or a higher level.

A line's effective sensitivity is the highest of: the page, its headings, its own label, and what sensitive.py finds in it (a
secret, key, token, card or social security number forces `restricted`; email, phone, date of birth and member or claim ids force at
least `confidential`). A line can raise a page's level but never lower it; a lower label is reported by `check` as a conflict and
ignored.

Who may see what (`clearance`): the leads named in the profile (kb_gate.certifiers) see everything; an approver of the team that owns a
page (gate.teams) sees up to restricted on that team's pages and confidential elsewhere; anyone else named under owners.roles sees
up to confidential; a name not in the profile sees internal; no name sees public. `labels.clearance: {<name or role>: <level>}`
overrides this. `visible_lines(kb, path, role)` is the function for context_pack and ask to call; see the notes file for the hook text.

Enforcement: a KB "has labels" (`is_active`) when its profile has a non-empty `labels:` block, or a page has `sensitivity:`/`env:` in its
front matter, or a line carries a `{env: ...}` / `{sensitivity: ...}` group. Only then is anything withheld; a KB with none behaves as
before. `Viewer(kb, who)` is the filter the surfaces use (context_pack, ask, kb_search, mcp_server); `Viewer(kb, level=L)` is the filter for
sharing (shared_index, export_rdf, okf_bundle): `L` is `--max-sensitivity`, else `labels.share_max_sensitivity` in the profile, else public.
No person (`who` empty) counts as public, the lowest clearance.
"""
import argparse
import fnmatch
import json
import os
import re
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import facts_time  # noqa: E402
import kb_gate  # noqa: E402
import sensitive  # noqa: E402

LEVELS = ("public", "internal", "confidential", "restricted")
RANK = {n: i for i, n in enumerate(LEVELS)}
KEYS = ("env", "sensitivity")
DEFAULT_SENSITIVITY = "internal"
SKIP_DIRS = ("_EVIDENCE", ".metis", "Archive", ".git", "_PENDING", "_FEEDBACK", "_REGEN", "_QUESTIONS")
HEADING = re.compile(r"^(#{1,6})\s+")
FRONT = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?", re.S)
ENV_WORD = re.compile(r"^[a-z0-9][a-z0-9_-]{0,30}$")


class LabelError(ValueError):
    pass


def rank(level):
    return RANK.get(level, RANK[DEFAULT_SENSITIVITY])


def top(*levels):
    return max((l for l in levels if l in RANK), key=rank, default=None)


# ---- settings -------------------------------------------------------------------------------------
def settings(kb):
    cfg = kb_gate.profile(kb).get("labels") or {}
    default = str(cfg.get("default_sensitivity") or DEFAULT_SENSITIVITY).lower()
    return {"default": default if default in RANK else DEFAULT_SENSITIVITY,
            "folders": [str(g).strip().strip("/") for g in cfg.get("restricted_folders") or [] if str(g).strip()],
            "clearance": {kb_gate.clean(k).lower(): str(v).lower() for k, v in (cfg.get("clearance") or {}).items()}}


def in_restricted_folder(cfg, rel):
    return any(kb_gate.owns(g, rel) for g in cfg["folders"])


# ---- parsing a page -------------------------------------------------------------------------------
def lines_of(text):
    """The lines of a page, numbered the way every surface numbers them: split on \\n only (a form feed or U+2028 is not a line break),
    with no empty last element for a final newline."""
    out = text.replace("\r\n", "\n").split("\n")
    if out and out[-1] == "":
        out.pop()
    return out


def split_front(text):
    """(front matter dict, number of lines the front matter takes up)."""
    text = text.replace("\r\n", "\n")
    m = FRONT.match(text)
    if not m:
        return {}, 0
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        meta = {}
    return (meta if isinstance(meta, dict) else {}), text[:m.end()].count("\n")


def own_labels(line):
    """({env, sensitivity}, problems) written on one line."""
    vals, probs = facts_time.parse_groups(line, KEYS)
    if "sensitivity" in vals:
        vals["sensitivity"] = vals["sensitivity"].lower()
        if vals["sensitivity"] not in RANK:
            probs.append("sensitivity must be one of %s, got '%s'" % (", ".join(LEVELS), vals.pop("sensitivity")))
    if "env" in vals:
        vals["env"] = vals["env"].lower()
        if not ENV_WORD.match(vals["env"]):
            probs.append("env must be one short word such as prod or uat, got '%s'" % vals.pop("env"))
    return vals, probs


def file_labels(kb, rel, meta, cfg):
    sens = str(meta.get("sensitivity") or "").lower() or None
    problems = []
    if sens and sens not in RANK:
        problems.append("front matter sensitivity must be one of %s, got '%s'" % (", ".join(LEVELS), sens))
        sens = None
    forced = in_restricted_folder(cfg, rel)
    env = str(meta.get("env") or "").lower() or None
    if env and not ENV_WORD.match(env):
        problems.append("front matter env must be one short word such as prod or uat, got '%s'" % env)
        env = None
    floor = top(sens, "restricted" if forced else None)   # what the page itself says; None when it says nothing
    return {"sensitivity": floor or cfg["default"], "floor": floor, "declared": sens, "env": env,
            "in_restricted_folder": forced}, problems


def analyse_text(rel, text, cfg, kb=None):
    """One record per labelled or sensitive line of a page, plus page facts and problems.

    Returns {"file": {...}, "lines": {n: record}, "problems": [(n, kind, text)]}. A line gets a record in `lines` only when it
    carries a label, is forced by sensitive.py, or differs from the page's own level or env; every other line is at the page level."""
    meta, front_lines = split_front(text)
    fl, problems = file_labels(kb, rel, meta, cfg)
    problems = [(0, "invalid", p) for p in problems]
    out, stack = {}, []        # stack of (heading level, sensitivity, env)
    in_code = False
    for n, line in enumerate(lines_of(text), 1):
        if n <= front_lines:
            continue
        s = line.strip()
        fence = s.startswith("```")
        if fence:
            in_code = not in_code
        own, probs = ({}, []) if in_code or fence else own_labels(line)
        problems += [(n, "invalid", p) for p in probs]
        h = HEADING.match(s) if not in_code and not fence else None
        if h:
            while stack and stack[-1][0] >= len(h.group(1)):
                stack.pop()
        inh_floor = top(fl["floor"], *[x[1] for x in stack])
        inh_env = next((x[2] for x in reversed(stack) if x[2]), None) or fl["env"]
        if own.get("sensitivity") and inh_floor and rank(own["sensitivity"]) < rank(inh_floor):
            problems.append((n, "conflict", "line says %s but the page or heading above is %s; a line cannot lower it" % (
                own["sensitivity"], inh_floor)))
        if own.get("env") and inh_env and own["env"] != inh_env and "all" not in (own["env"], inh_env):
            problems.append((n, "conflict", "line is for %s but the page or heading above is for %s" % (own["env"], inh_env)))
        found = sensitive.scan_line(line)
        forced = None
        if any(lvl == sensitive.BLOCK for lvl, _, _ in found):
            forced = "restricted"
        elif found:
            forced = "confidential"
        sens = top(inh_floor, own.get("sensitivity"), forced) or cfg["default"]
        env = own.get("env") or inh_env
        if h:
            stack.append((len(h.group(1)), own.get("sensitivity"), own.get("env")))
        if own or forced or sens != fl["sensitivity"] or env != fl["env"]:
            out[n] = {"line": n, "text": line.rstrip(), "sensitivity": sens, "env": env, "own": own,
                      "forced_by": sorted({k for _, k, _ in found}) if forced else [], "forced_level": forced}
    return {"file": fl, "lines": out, "problems": problems}


def pages(kb, only=None):
    if only:
        yield only.replace("\\", "/").strip("/")
        return
    for d, dirs, files in os.walk(kb):
        dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS)
        for f in sorted(files):
            if f.endswith(".md"):
                yield os.path.relpath(os.path.join(d, f), kb).replace(os.sep, "/")


def read(kb, rel):
    p = os.path.normpath(os.path.join(kb, rel))
    if not p.startswith(os.path.normpath(kb) + os.sep) or not os.path.isfile(p):
        raise LabelError("not a page in the KB: %s" % rel)
    with open(p, encoding="utf-8", errors="replace") as fh:
        return fh.read().replace("\r\n", "\n")


def analyse_page(kb, rel, cfg=None):
    return analyse_text(rel, read(kb, rel), cfg or settings(kb), kb)


# ---- scan, report -------------------------------------------------------------------------------------
def scan(kb, page=None):
    """[{path, line, text, sensitivity, env, source}] for every line with a label of its own or one forced by sensitive.py.
    `source` says why: label, secret, personal data."""
    kb, cfg, out = os.path.abspath(kb), settings(kb), []
    for rel in pages(kb, page):
        a = analyse_page(kb, rel, cfg)
        for n, r in sorted(a["lines"].items()):
            if not (r["own"] or r["forced_by"]):
                continue
            why = "label" if r["own"] else "secret" if r["forced_level"] == "restricted" else "personal data"
            out.append({"path": rel, "line": n, "text": r["text"].strip(), "sensitivity": r["sensitivity"], "env": r["env"],
                        "source": why, "forced_by": r["forced_by"]})
    return out


def report(kb):
    """{pages, lines_labelled, by_sensitivity, by_env, forced: [{path, line, kinds}], page_defaults: {path: level}}.
    Kinds of secrets are named, never their values."""
    kb, cfg = os.path.abspath(kb), settings(kb)
    rep = {"pages": 0, "lines_labelled": 0, "by_sensitivity": {l: 0 for l in LEVELS}, "by_env": {}, "forced": [], "page_defaults": {}}
    for rel in pages(kb):
        a = analyse_page(kb, rel, cfg)
        rep["pages"] += 1
        if a["file"]["sensitivity"] != cfg["default"] or a["file"]["env"]:
            rep["page_defaults"][rel] = {"sensitivity": a["file"]["sensitivity"], "env": a["file"]["env"]}
        for n, r in a["lines"].items():
            if r["own"] or r["forced_by"]:
                rep["lines_labelled"] += 1
                rep["by_sensitivity"][r["sensitivity"]] += 1
            if r["own"].get("env"):
                rep["by_env"][r["env"]] = rep["by_env"].get(r["env"], 0) + 1
            if r["forced_by"]:
                rep["forced"].append({"path": rel, "line": n, "level": r["forced_level"], "kinds": r["forced_by"]})
    return rep


# ---- who may see what ---------------------------------------------------------------------------------
def clearance(kb, who, rel=None):
    """The highest sensitivity `who` may see on page `rel`. `who` is a person's name, a role word (lead, member, reader), or a level."""
    cfg = settings(kb)
    key = kb_gate.clean(who).lower()
    if not key:
        return "public"
    if key in cfg["clearance"] and cfg["clearance"][key] in RANK:
        return cfg["clearance"][key]
    if key in RANK:
        return key
    if key in ("reader", "anonymous", "guest", "public"):
        return "public"
    if key == "lead" or key in kb_gate.certifiers(kb):
        return "restricted"
    team = kb_gate.team_of(kb, rel) if rel else None
    for t in kb_gate.teams(kb):
        if any(a.lower() == key for a in t["approvers"]):
            return "restricted" if team and team["name"] == t["name"] else "confidential"
    named = {kb_gate.clean(v).lower() for v in ((kb_gate.profile(kb).get("owners") or {}).get("roles") or {}).values()}
    if key in named:
        return "confidential"
    return "internal"


def allowed_level(kb, who, rel, max_level=None, level=None):
    """The highest sensitivity a person (or a fixed `level`, for sharing) may see on page `rel`, capped by `max_level`."""
    for name, val in (("level", level), ("max_level", max_level)):
        if val and val not in RANK:
            raise LabelError("%s must be one of %s" % (name, ", ".join(LEVELS)))
    allowed = level or clearance(kb, who, rel)
    if max_level:
        allowed = allowed if rank(allowed) <= rank(max_level) else max_level
    return allowed


def visible_numbers(kb, path, text, role, max_level=None, cfg=None, level=None):
    """The set of line numbers of `text` (page `path`) that `role` may see. Empty when the page as a whole is above their clearance."""
    kb = os.path.abspath(kb)
    rel = path.replace("\\", "/").strip("/")
    text = text.replace("\r\n", "\n")
    allowed = allowed_level(kb, role, rel, max_level, level)
    a = analyse_text(rel, text, cfg or settings(kb), kb)
    if rank(a["file"]["sensitivity"]) > rank(allowed):
        return set()
    out = set()
    for n in range(1, len(lines_of(text)) + 1):
        rec = a["lines"].get(n)
        if rec and rank(rec["sensitivity"]) > rank(allowed):
            continue
        out.add(n)
    return out


def visible_lines(kb, path, role, max_level=None):
    """(line number, text) for the lines of page `path` that `role` may see: lines above their clearance are left out. Line
    numbers are the page's own. Returns [] for a page the person may not see at all. `max_level` caps the clearance (a context pack
    can pass its own limit)."""
    kb = os.path.abspath(kb)
    rel = path.replace("\\", "/").strip("/")
    text = read(kb, rel)
    nums = visible_numbers(kb, rel, text, role, max_level)
    return [(n, line) for n, line in enumerate(lines_of(text), 1) if n in nums]


# ---- enforcement: what the surfaces call ------------------------------------------------------------------
LABEL_GROUP = re.compile(r"\{[^{}]*\b(?:env|sensitivity)\s*:")


def is_active(kb):
    """True when the KB uses labels at all: a non-empty `labels:` profile block, a page with `sensitivity:` or `env:` in its front
    matter, or a line with an `{env: ...}` / `{sensitivity: ...}` group. A KB with none is served exactly as before."""
    kb = os.path.abspath(kb)
    lab = kb_gate.profile(kb).get("labels")
    if isinstance(lab, dict) and lab:
        return True
    for rel in pages(kb):
        try:
            text = read(kb, rel)
        except LabelError:
            continue
        meta, _ = split_front(text)
        if "sensitivity" in meta or "env" in meta or LABEL_GROUP.search(text):
            return True
    return False


def share_level(kb):
    """The highest level that may leave the team (shared index, exports): `labels.share_max_sensitivity`, default public."""
    lab = kb_gate.profile(kb).get("labels")
    lvl = str((lab.get("share_max_sensitivity") if isinstance(lab, dict) else None) or "public").lower()
    return lvl if lvl in RANK else "public"


class Viewer:
    """The line filter every surface uses. `Viewer(kb, who)` filters for a person or role (empty = public, the lowest);
    `Viewer(kb, level=L)` filters for a fixed level, as sharing and exports do. When the KB has no labels nothing is filtered
    (`numbers` gives None, `filter` gives the text back). `withheld` counts the non-blank lines left out so far."""

    def __init__(self, kb, who=None, max_level=None, level=None):
        self.kb = os.path.abspath(kb)
        self.who = kb_gate.clean(who)
        self.max_level, self.level = max_level, level
        self.cfg = settings(self.kb)
        self.active = is_active(self.kb)
        self.withheld = 0
        self.by_page = {}      # page -> non-blank lines withheld from it by `filter`
        allowed_level(self.kb, self.who, "", max_level, level)   # validates the levels

    def file_hidden(self, rel):
        """True for a file that is not a Markdown page and sits in a restricted folder the viewer may not see."""
        rel = rel.replace("\\", "/").strip("/")
        return (self.active and not rel.endswith(".md") and in_restricted_folder(self.cfg, rel)
                and rank(allowed_level(self.kb, self.who, rel, self.max_level, self.level)) < RANK["restricted"])

    def numbers(self, rel, text):
        """Line numbers the viewer may see, or None when everything is visible."""
        if not self.active:
            return None
        if rel.endswith(".md"):
            return visible_numbers(self.kb, rel, text, self.who, self.max_level, self.cfg, self.level)
        return set() if self.file_hidden(rel) else None

    def filter(self, rel, text):
        """(text with the withheld lines removed, number of non-blank lines removed). Same text back when nothing is removed."""
        nums = self.numbers(rel, text)
        if nums is None:
            return text, 0
        kept, hidden = [], 0
        for n, line in enumerate(lines_of(text), 1):
            if n in nums:
                kept.append(line)
            elif line.strip():
                hidden += 1
        if not hidden:
            return text, 0
        self.withheld += hidden
        self.by_page[rel] = hidden
        return ("\n".join(kept) + "\n" if kept else ""), hidden

    def filter_pages(self, texts):
        """{page: text} with each page filtered; a page with nothing left to show is dropped."""
        out = {}
        for rel, text in texts.items():
            t, hid = self.filter(rel, text)
            if hid and not t.strip():
                continue
            out[rel] = t
        return out


KB_SOURCE = re.compile(r'^kb:([^:"\s]+)(?::(\d+)(?:-(\d+))?)?(?:\s+"(.+)")?$')
E_TAG = re.compile(r"\[E:\s*([^\]]+)\]")


def _flat(text):
    return " ".join(str(text).split()).lower()


def source_hidden(viewer, src):
    """True when a `kb:` source in the string `src` cites a page, a line range or a quote the viewer may not see."""
    if not viewer.active:
        return False
    for tag in E_TAG.findall(src or ""):
        for part in tag.split(";"):
            m = KB_SOURCE.match(part.strip())
            if not m:
                continue
            rel, a, b, quote = m.groups()
            try:
                text = read(viewer.kb, rel)
            except LabelError:
                continue
            nums = viewer.numbers(rel, text)
            if nums is None:
                continue
            lines = text.splitlines()
            if a:
                lo, hi = int(a), int(b or a)
                if any(n not in nums and lines[n - 1].strip() for n in range(lo, min(hi, len(lines)) + 1)):
                    return True
            elif quote:
                seen = _flat(" ".join(l for n, l in enumerate(lines, 1) if n in nums))
                if _flat(quote) in _flat(text) and _flat(quote) not in seen:
                    return True
            elif not any(l.strip() and n in nums for n, l in enumerate(lines, 1)):
                return True
    return False


def filter_graph(viewer, nodes, edges):
    """(nodes, edges) without the links whose source cites a withheld line or whose file is in a hidden folder, and without the
    objects that only those links named."""
    if not viewer.active:
        return nodes, edges
    kept, gone = [], set()
    for e in edges:
        if source_hidden(viewer, e.get("source")) or (e.get("defined_in") and viewer.file_hidden(e["defined_in"])):
            gone |= {e.get("from"), e.get("to")}
        else:
            kept.append(e)
    still = {e.get("from") for e in kept} | {e.get("to") for e in kept}
    return [n for n in nodes if (n.get("id") or "%s:%s" % (n.get("type"), n.get("name"))) not in gone
            or (n.get("id") or "%s:%s" % (n.get("type"), n.get("name"))) in still], kept


def filter_graph_text(viewer, text):
    """The text of a LINK_GRAPH.yaml with the links (and objects only they named) the viewer may not see taken out."""
    data = yaml.safe_load(text) or {}
    data["nodes"], data["edges"] = filter_graph(viewer, data.get("nodes") or [], data.get("edges") or [])
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120)


# ---- audit ------------------------------------------------------------------------------------------------
PROBE = "audit-probe"      # a name nobody has in the profile: internal clearance
MIN_NEEDLE = 12


def _norm(text):
    t = re.sub(r"\[(?:E|\?):[^\]]*\]", " ", str(text))
    t = re.sub(r"\{[^{}]*\}", " ", t).replace("|", " ")
    return " ".join(t.split())


def _needle(line):
    return re.sub(r"^(?:[-*>#]+|\d+[.)])\s*", "", _norm(line)).lower()


def audit(kb, roles=None, queries=40):
    """Run each surface as uncleared roles and look for the text of a withheld line in what comes back.

    Returns {"active", "checked", "skipped", "leaks": [{surface, role, path, line}]}. Leaks name a page and a line number, never the
    text. A line is not judged when its text is shorter than MIN_NEEDLE characters or also appears in a line the role may see."""
    import tempfile
    here = os.path.dirname(os.path.abspath(__file__))
    for p in (here, os.path.join(here, "ui")):
        if p not in sys.path:
            sys.path.insert(0, p)
    import answers
    import context_pack
    import export_rdf
    import kb_coverage
    import kb_search
    import okf_bundle
    kb = os.path.abspath(kb)
    res = {"active": is_active(kb), "checked": 0, "skipped": 0, "leaks": []}
    if not res["active"]:
        return res
    cfg = settings(kb)
    texts = {rel: read(kb, rel) for rel in pages(kb)}

    def needles(who=None, level=None):
        hidden, shown = [], []
        for rel, text in texts.items():
            nums = visible_numbers(kb, rel, text, who, None, cfg, level)
            for n, line in enumerate(lines_of(text), 1):
                if n in nums:
                    shown.append(_norm(line).lower())
                elif line.strip():
                    hidden.append((rel, n, _needle(line)))
        blob = "\n".join(shown)
        out, seen = [], set()
        for rel, n, nd in hidden:
            if len(nd) < MIN_NEEDLE or nd in blob:
                res["skipped"] += 1
            elif nd not in seen:
                seen.add(nd)
                out.append((rel, n, nd))
        return out

    def judge(surface, who, hidden, output):
        flat = _norm(output).lower()
        for rel, n, nd in hidden:
            res["checked"] += 1
            if nd in flat:
                res["leaks"].append({"surface": surface, "role": who or "(none)", "path": rel, "line": n})

    for who in (roles or ["", PROBE]):
        hidden = needles(who)
        if not hidden:
            continue
        viewer = Viewer(kb, who)
        files = sorted(viewer.filter_pages(kb_coverage.page_files(kb)))
        try:
            seeds = [n["id"] for n in context_pack.graph_nodes(kb)]
        except Exception:  # noqa: BLE001 - no graph is fine
            seeds = []
        if files or seeds:
            try:
                judge("context_pack", who, hidden, context_pack.build(kb, seeds=seeds, files=files, budget=1000000, stale_marks=False,
                                                                     signals=False, role=who)["text"])
            except context_pack.PackError:
                pass
        asked = hidden[:max(1, queries)]
        found, said = [], []
        for _, _, nd in asked:
            words = nd.split()
            found.append("\n".join("%s\n%s\n%s" % (r["title"], r["heading"], r["snippet"]) for r in
                                   kb_search.search(kb, " ".join(words[:6]), limit=50, who=who)["results"]))
            # the answer repeats the question in its title and in "The KB has no line about"; those are not KB text
            said.append("\n".join(l for l in answers.compose(kb, " ".join(words[:6]), who=who)[0].splitlines()
                                  if not l.startswith(("# Answer:", "- The KB has no line about:"))))
        judge("kb_search", who, hidden, "\n".join(found))
        judge("answers", who, hidden, "\n".join(said))
    share = share_level(kb)
    hidden = needles(level=share)
    if hidden:
        with tempfile.TemporaryDirectory() as tmp:
            out, _ = okf_bundle.bundle(kb, os.path.join(tmp, "okf"), max_level=share)
            blob = []
            for d, _, fs in os.walk(out):
                for f in fs:
                    with open(os.path.join(d, f), encoding="utf-8", errors="replace") as fh:
                        blob.append(fh.read())
            judge("okf_bundle", "share:" + share, hidden, "\n".join(blob))
        judge("export_rdf", "share:" + share, hidden, export_rdf.to_turtle(kb, max_level=share) + export_rdf.to_json_ld(kb, max_level=share))
    return res


# ---- filter ---------------------------------------------------------------------------------------------
def filter_kb(kb, out_dir, max_level=None, role=None, page=None):
    """Write a copy of one page, or of every .md page, with the lines above the level removed. Pages whose own level is above it
    are not copied at all. Other file types are not copied. The output folder must be outside the KB.
    Returns {"copied": [...], "dropped": [...], "lines_removed": n}."""
    kb, out_dir = os.path.abspath(kb), os.path.abspath(out_dir)
    if out_dir == kb or out_dir.startswith(kb + os.sep):
        raise LabelError("write the filtered copy outside the KB folder")
    if bool(max_level) == bool(role):
        raise LabelError("give exactly one of a level (--max) or a person or role (--role)")
    if max_level and max_level not in RANK:
        raise LabelError("level must be one of %s" % ", ".join(LEVELS))
    res = {"copied": [], "dropped": [], "lines_removed": 0}
    for rel in pages(kb, page):
        text = read(kb, rel)
        lines = text.splitlines()
        kept = visible_lines(kb, rel, role or max_level)
        if not kept and lines:
            res["dropped"].append(rel)
            continue
        dst = os.path.join(out_dir, *rel.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("".join(l + "\n" for _, l in kept))
        res["copied"].append(rel)
        res["lines_removed"] += len(lines) - len(kept)
    return res


# ---- check -------------------------------------------------------------------------------------------------
def check(kb):
    """[{path, line, kind, problem}] kinds: not-in-restricted-folder, secret-outside-restricted, conflict, invalid."""
    kb, cfg, out = os.path.abspath(kb), settings(kb), []
    where = ("not under any folder in labels.restricted_folders (%s)" % ", ".join(cfg["folders"])) if cfg["folders"] else \
        "and no labels.restricted_folders are listed in kb-profile.yaml"
    for rel in pages(kb):
        a = analyse_page(kb, rel, cfg)
        fl = a["file"]
        if fl["declared"] == "restricted" and not fl["in_restricted_folder"]:
            out.append({"path": rel, "line": 0, "kind": "not-in-restricted-folder",
                        "problem": "the page is labelled restricted in its front matter, %s" % where})
        for n, kind, why in a["problems"]:
            out.append({"path": rel, "line": n, "kind": kind, "problem": why})
        for n, r in sorted(a["lines"].items()):
            if fl["in_restricted_folder"]:
                continue
            if r["own"].get("sensitivity") == "restricted":
                out.append({"path": rel, "line": n, "kind": "not-in-restricted-folder",
                            "problem": "line is labelled restricted, %s" % where})
            elif r["forced_level"] == "restricted":
                out.append({"path": rel, "line": n, "kind": "secret-outside-restricted",
                            "problem": "line contains %s, so it counts as restricted, %s" % (", ".join(r["forced_by"]), where)})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("audit"); a.add_argument("kb"); a.add_argument("--role", action="append"); a.add_argument("--queries", type=int, default=40)
    a = sub.add_parser("scan"); a.add_argument("kb"); a.add_argument("--page")
    a = sub.add_parser("report"); a.add_argument("kb"); a.add_argument("--json", action="store_true")
    a = sub.add_parser("filter"); a.add_argument("kb"); a.add_argument("--out", required=True)
    a.add_argument("--max"); a.add_argument("--role"); a.add_argument("--page")
    a = sub.add_parser("check"); a.add_argument("kb")
    args = ap.parse_args(argv)
    kb = os.path.abspath(args.kb)
    try:
        if args.cmd == "audit":
            res = audit(kb, args.role, args.queries)
            if not res["active"]:
                print("this KB has no labels; nothing is withheld, so there is nothing to audit")
                return 0
            for l in res["leaks"]:
                print("LEAK %s role=%s %s:%d" % (l["surface"], l["role"], l["path"], l["line"]))
            print("%d withheld lines checked, %d not judged (too short or also said elsewhere), %d leaks" % (
                res["checked"], res["skipped"], len(res["leaks"])))
            return 1 if res["leaks"] else 0
        if args.cmd == "scan":
            rows = scan(kb, args.page)
            for r in rows:
                print("%s:%d\t%s\tenv=%s\t(%s)\t%s" % (r["path"], r["line"], r["sensitivity"], r["env"] or "-", r["source"],
                                                       "" if r["source"] != "label" else r["text"][:100]))
            print("%d labelled lines" % len(rows))
        elif args.cmd == "report":
            rep = report(kb)
            if args.json:
                print(json.dumps(rep, indent=2))
            else:
                print("%d pages, %d lines carry a label" % (rep["pages"], rep["lines_labelled"]))
                for l in LEVELS:
                    print("  %-13s %d" % (l, rep["by_sensitivity"][l]))
                for e, n in sorted(rep["by_env"].items()):
                    print("  env %-9s %d" % (e, n))
                for f in rep["forced"]:
                    print("  forced to %s: %s:%d (%s)" % (f["level"], f["path"], f["line"], ", ".join(f["kinds"])))
        elif args.cmd == "filter":
            r = filter_kb(kb, args.out, args.max, args.role, args.page)
            print("%d pages copied, %d withheld whole, %d lines removed -> %s" % (
                len(r["copied"]), len(r["dropped"]), r["lines_removed"], os.path.abspath(args.out)))
        else:
            rows = check(kb)
            for r in rows:
                print("%s:%d: %s: %s" % (r["path"], r["line"], r["kind"], r["problem"]))
            print("%d label problems" % len(rows))
            return 1 if rows else 0
    except LabelError as err:
        print("error: %s" % err, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
