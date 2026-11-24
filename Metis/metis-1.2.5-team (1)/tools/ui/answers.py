#!/usr/bin/env python3
"""Ask the KB, check the answer, and keep the like or dislike.

    python3 answers.py ask  <kb> "<question>" --by NAME [--direction TEXT]     a local answer from the KB, checked
    python3 answers.py list <kb>

Two ways to get an answer, both checked by verify_kb.py before anyone sees them as checked:
  local   the KB lines that share words with the question, and the link-graph edges around objects the question names. Every
          line is a KB line quoted word for word with its page; nothing is written that the KB does not say. It does not reason.
  devin   a task for a Devin session (tasks.py); the session answers with the `metis-ask` skill and completes the task with the
          answer file. The UI refuses an answer file that has a source problem, so the session has to fix it.

A like or dislike goes through feedback.py unchanged: a dislike needs why and exactly one of the right answer or where to look.
A direction ("look in the ETL, not the app") asks again at once with that direction.
"""
import argparse
import difflib
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import ui_common as C  # noqa: E402
import claim_labels  # noqa: E402
import feedback  # noqa: E402
import kb_coverage  # noqa: E402
import telemetry  # noqa: E402
import verify_kb  # noqa: E402

DIR = os.path.join(".metis", "asks")
STOP = set("a an the of to in on for is are was were what which who how does do did and or by with from this that it as at be me my we "
           "our can i you show list tell about when where why there their its into than then also any all should would could "
           "please give find get use used uses using".split())
IMPACT = re.compile(r"\b(chang|drop|impact|break|affect|depend|remov|renam|delet|upstream|downstream)", re.I)
MAX_FACTS, MAX_EDGES, QUOTE_WORDS = 8, 15, 16
MAX_ASK_QUESTIONS, MAX_ASK_ROUNDS = 2, 2  # the same limits tasks.py enforces


def folder(kb):
    return os.path.join(kb, DIR)


def all_asks(kb):
    d = folder(kb)
    out = []
    if os.path.isdir(d):
        for n in sorted(os.listdir(d)):
            if n.endswith(".yaml"):
                r = C.load_yaml(os.path.join(d, n))
                if r.get("id"):
                    out.append(r)
    return out


def get(kb, aid):
    r = C.load_yaml(os.path.join(folder(kb), aid + ".yaml"))
    if not r:
        raise C.UiError("no question %s" % aid)
    return r


def save(kb, r):
    d = folder(kb)
    os.makedirs(d, exist_ok=True)
    guard = os.path.join(d, ".gitignore")
    if not os.path.isfile(guard):
        C.write_text(guard, "*\n")
    C.dump_yaml(os.path.join(d, r["id"] + ".yaml"), r)


def answer_path(kb, aid):
    return os.path.join(folder(kb), aid + ".md")


def next_id(kb):
    nums = [int(r["id"][2:]) for r in all_asks(kb) if r["id"][2:].isdigit()]
    return "A-%04d" % (max(nums or [0]) + 1)


# ---- words ----------------------------------------------------------------------------------------
def stem(w):
    return w[:-1] if len(w) > 3 and w.endswith("s") else w


def stems(text):
    return {stem(w) for w in re.findall(r"[a-z0-9]+", str(text).lower()) if w not in STOP and len(w) > 1}


LABEL = re.compile(r"\{[^{}]*\b(?:env|sensitivity)\s*:[^{}]*\}")   # a claim label; it is not part of what the line says


def quote_of(line):
    """A run of at most QUOTE_WORDS words copied from the line, with no character a tag cannot hold."""
    t = LABEL.sub(" ", verify_kb.TAG.sub(" ", line))
    parts = [C.clean(p) for p in re.split(r"[\"\[\]|`]", t)]
    best = max(parts, key=lambda s: len(s.split()), default="")
    q = " ".join(best.split()[:QUOTE_WORDS]).strip()
    return q if len(q) >= 3 else None


def plain(line):
    t = LABEL.sub("", verify_kb.TAG.sub("", line))
    t = re.sub(r"^\s*([-*>]|\d+[.)])\s+", "", t)
    t = t.strip().strip("|").replace("|", " | ")
    return re.sub(r"\s+", " ", t).strip()


# ---- KB lines ---------------------------------------------------------------------------------------
def viewer_for(kb, who):
    """The claim_labels filter for the asking person, or None when the KB has no labels (then nothing is withheld)."""
    v = claim_labels.Viewer(kb, who)
    return v if v.active else None


def candidate_lines(kb, viewer=None, withheld=None):
    """[(page, line number, raw line, in an exempt section)] for the hand-written pages. With a `viewer`, lines it may not see are
    left out; they are appended to the list `withheld` (same shape) when one is given, so the caller can count them, never show them."""
    out = []
    for rel, text in sorted(kb_coverage.page_files(kb).items()):
        exempt, in_code, in_front = False, False, False
        nums = viewer.numbers(rel, text) if viewer else None
        for n, line in enumerate(text.splitlines() if nums is None else claim_labels.lines_of(text), 1):
            s = line.strip()
            if nums is not None and n not in nums:
                if withheld is not None and s:
                    withheld.append((rel, n, line, False))
                continue
            if n == 1 and s == "---":
                in_front = True
                continue
            if in_front:
                in_front = s != "---"
                continue
            if s.startswith("```"):
                in_code = not in_code
                continue
            h = verify_kb.HEADING.match(s)
            if h:
                # judge the heading's words, not the path inside its source tag ("src/main/resources" holds "sources")
                exempt = bool(verify_kb.EXEMPT.search(verify_kb.TAG.sub("", h.group(2))))
                continue
            if in_code or not s or s.startswith(("<!--", "|---", "| ---", ">")) or re.match(r"^\|?\s*:?-{3,}", s):
                continue
            out.append((rel, n, line, exempt))
    return out


PAGE_BONUS = (0.5, 0.4, 0.3, 0.2, 0.1, 0.1, 0.05, 0.05)   # what the search rank of a page adds to its lines, best page first
PAGE_RESCUE = 3                                            # lines with one word hit on one of this many top pages still qualify


def page_ranks(kb, question, who=None, info=None):
    """{page: bonus} from the KB search (BM25, plus vectors when the profile turns hybrid on), best page first, or None when the
    search is off (profile key ask.search: false) or fails. A failure is recorded in `info` and never stops the answer: the
    caller falls back to the word matcher alone."""
    prof = C.profile(kb) or {}
    if (prof.get("ask") or {}).get("search") is False:
        return None
    try:
        import kb_search
        found = kb_search.search(kb, question, limit=len(PAGE_BONUS), who=who)
    except Exception as err:  # a broken index must not stop an answer
        if info is not None:
            info["search_note"] = "page search skipped: %s" % err
        return None
    pages = {r["path"]: PAGE_BONUS[i] for i, r in enumerate(found.get("results") or [])}
    try:   # a summary page that ranks well passes its rank down to the pages it covers
        import kb_summaries
        for i, r in enumerate(found.get("results") or []):
            for under in kb_summaries.drill_pages(kb_coverage.page_files(kb).get(r["path"], "")):
                pages.setdefault(under, PAGE_BONUS[i])
    except Exception:
        pass
    if info is not None:
        info["search"] = {"engine": found.get("engine"), "hybrid": found.get("hybrid"), "pages": list(pages)}
        if found.get("notes"):
            info["search_note"] = "; ".join(found["notes"])
    return pages or None


def score_lines(lines, qstems, boost, lens=None, pages=None):
    """Scored lines, best first. A `lens` (audience.Lens) multiplies a line's score by what its page's layer is worth to the asker.
    It reorders lines that already matched; it never adds a line and never hides one (a line that matched stays a candidate).
    `pages` ({page: bonus} from page_ranks) adds the page's search bonus to a line that shares a word with the question, and lets a
    one-word line on one of the best pages qualify; the quote and support checks still apply to every line it lets in."""
    scored = []
    top = set(list(pages or {})[:PAGE_RESCUE])
    need = 1 if len(qstems) < 3 else 2
    for rel, n, line, exempt in lines:
        words = stems(plain(line)) | {stem(w) for w in re.findall(r"[a-z0-9]+", rel.lower())}
        hit = len(qstems & stems(plain(line)))
        if not hit:
            continue
        score = hit + len(qstems & words - stems(plain(line))) * 0.5
        if boost:
            score += 2 * len(boost & words) + 0.5 * len(boost & stems(plain(line)))
        if score < need and rel not in top:
            continue
        scored.append((-score, len(line), rel, n, line, exempt))
    if lens:
        scored = [(s[0] * lens.weight(s[2]),) + s[1:] for s in scored]
    if pages:   # after the lens, and small, so the search breaks ties and never overrules the audience order
        scored = [(s[0] - pages.get(s[2], 0),) + s[1:] for s in scored]
    scored.sort()
    return scored


def fact_lines(kb, qstems, boost, viewer=None, withheld=None, lens=None, pages=None):
    """Scored candidate lines, best first. `withheld`, when a list, receives the scored lines the viewer may not see (the caller
    uses only its length)."""
    hid = [] if withheld is not None else None
    scored = score_lines(candidate_lines(kb, viewer, hid), qstems, boost, lens, pages)
    if hid:
        withheld.extend(score_lines(hid, qstems, boost))
    return scored


# ---- the link graph ---------------------------------------------------------------------------------
def graph(kb, viewer=None):
    g = C.load_yaml(os.path.join(kb, "CROSS-LAYER", "LINK_GRAPH.yaml"))
    nodes, edges = g.get("nodes") or [], g.get("edges") or []
    return claim_labels.filter_graph(viewer, nodes, edges) if viewer else (nodes, edges)


def label(node_id):
    t, _, name = str(node_id).partition(":")
    return "%s %s" % (t, name) if name else str(node_id)


def graph_lines(kb, question, qstems, boost, viewer=None):
    nodes, edges = graph(kb, viewer)
    if not nodes or not edges:
        return []
    ql = question.lower()
    picked = []
    for n in nodes:
        name = str(n.get("name") or "")
        ns = stems(name)
        if not ns:
            continue
        exact = bool(re.search(r"(?<![\w])%s(?![\w])" % re.escape(name.lower()), ql))
        if exact or ns <= qstems or (boost and ns <= boost):
            picked.append((0 if exact else 1, len(name), n["id"]))
    picked.sort()
    seeds = [p[2] for p in picked[:6]]
    if not seeds:
        return []
    depth = 2 if IMPACT.search(question) else 1
    raw = C.read_text(os.path.join(kb, "CROSS-LAYER", "LINK_GRAPH.yaml"))
    norm = " ".join(raw.split())
    seen, out, frontier = set(), [], set(seeds)
    for _ in range(depth):
        nxt = set()
        for e in edges:
            a, b = e.get("from"), e.get("to")
            if a in frontier or b in frontier:
                key = (a, e.get("rel"), b)
                if key in seen:
                    continue
                seen.add(key)
                q = "from: %s rel: %s to: %s" % (a, e.get("rel"), b)
                if any(ch in q for ch in '"[]|`') or q not in norm:
                    continue
                out.append(("%s %s %s." % (label(a), e.get("rel"), label(b)), q))
                nxt |= {a, b}
                if len(out) >= MAX_EDGES:
                    return out
        frontier = nxt - set(seeds)
    return out


# ---- when the KB has nothing: what Metis understood, what it knows nearby ---------------------------------
COUNTING = re.compile(r"\b(how many|count|number of|total)\b", re.I)


def vocabulary(kb, viewer=None):
    """(stem -> pages that use it, surface word -> uses, page -> (title, stems of its path and text))."""
    stem_pages, surface, pages = {}, {}, {}
    texts = kb_coverage.page_files(kb)
    for rel, text in (viewer.filter_pages(texts) if viewer else texts).items():
        body = verify_kb.TAG.sub(" ", text)
        title = next((C.clean(l.lstrip("# ")) for l in body.splitlines() if l.strip()), rel)
        words = re.findall(r"[a-z0-9]+", (rel + " " + body).lower())
        ss = {stem(w) for w in words if w not in STOP and len(w) > 1}
        pages[rel] = (title[:80], ss)
        for s in ss:
            stem_pages.setdefault(s, set()).add(rel)
        for w in words:
            if len(w) >= 3 and not w.isdigit():
                surface[w] = surface.get(w, 0) + 1
    return stem_pages, surface, pages


def known_names(kb, per_type=2, limit=8, viewer=None):
    nodes, _ = graph(kb, viewer)
    seen, out = {}, []
    for n in nodes:
        t = str(n.get("id", "")).partition(":")[0]
        if seen.get(t, 0) < per_type and len(out) < limit:
            seen[t] = seen.get(t, 0) + 1
            out.append(label(n["id"]))
    return out


def guidance(kb, question, who=None):
    """Plain data about a question the KB could not answer. Nothing here is a fact about the product: it is about the KB's wording.
    `who` is the asking person: words and pages they may not see are not offered."""
    viewer = viewer_for(kb, who)
    stem_pages, surface, pages = vocabulary(kb, viewer)
    words = []
    for w in re.findall(r"[a-z0-9]+", question.lower()):
        if w not in STOP and len(w) > 1 and not w.isdigit() and w not in words:
            words.append(w)
    known = [{"word": w, "pages": len(stem_pages[stem(w)])} for w in words if stem(w) in stem_pages]
    unknown = [w for w in words if stem(w) not in stem_pages]
    typos = []
    for w in unknown:
        pool = sorted(w for w in surface if w not in STOP)
        close = [c for c in difflib.get_close_matches(w, pool, n=3, cutoff=0.8) if c != w and c[0] == w[0]] if len(w) >= 3 else []
        if close:
            typos.append({"word": w, "options": [{"word": c, "question": re.sub(r"(?i)\b%s\b" % re.escape(w), c, question)} for c in close]})
    kstems = {stem(k["word"]) for k in known}
    scored = []
    for rel, (title, ss) in pages.items():
        hit = len(kstems & ss)
        if hit:
            scored.append((-hit, len(rel), rel, title))
    scored.sort()
    nearest = [{"page": r, "title": t} for _, _, r, t in scored[:4]]
    overview = []
    if not nearest:
        overview = [{"page": r, "title": pages[r][0]} for r in sorted(pages, key=lambda p: (-len(pages[p][1]), p))[:8]]
    tips = []
    if COUNTING.search(question):
        tips.append("The KB lists things and rarely states totals. Ask for the list (for example 'list the screens') and count the lines.")
    if unknown:
        tips.append("Use a name exactly as the KB spells it: a table, screen, job, endpoint or module.")
    tips.append("Say the layer if you know it: the application, the ETL or the database.")
    return {"searched": words, "known": known, "unknown": unknown, "typos": typos, "nearest": nearest, "overview": overview,
            "names": known_names(kb, viewer=viewer), "tips": tips}


# ---- build and check an answer -----------------------------------------------------------------------
def glossary_words(kb, question):
    """Words the glossary says mean the same as words in the question. A missing or broken glossary never stops an answer."""
    try:
        import glossary
        return stems(" ".join(glossary.expand(kb, question).get("extra_words") or []))
    except Exception:
        return set()


WITHHELD_NOTE = "- Some lines are withheld by label, so this answer may be incomplete for you. Ask a lead if you need them."


def compose(kb, question, direction=None, who=None, audience=None, info=None):
    """(markdown, facts, not_in_kb). Each fact line carries a kb tag with a quote copied from the page. `who` is the asking person
    (a name or role): when the KB uses claim labels, lines above their clearance are not read, not quoted, and the answer says
    that some lines are withheld by label, without saying which.

    `audience` (business, developer, tech_lead, architect, support; default from the profile for `who`) orders the lines by how
    much their layer matters to that reader and sets how many link lines are shown. The lines themselves, their tags and the
    checks are the same for every audience. When `info` is a dict it receives what the lens did: the audience, the layer of each
    line used, and how many matching lines at each layer were left out by the cap."""
    qs = stems(question)
    boost = (stems(direction) if direction else set()) | glossary_words(kb, question)
    direction_words = qs | boost
    facts, unknown, used = [], [], set()
    viewer = viewer_for(kb, who)
    lens = audience_lens(kb, who, audience)
    held, left_out = [], {}
    pages = page_ranks(kb, question, who, info)
    for _, _, rel, n, line, exempt in fact_lines(kb, direction_words, boost, viewer, held, lens, pages):
        text = plain(line)
        if len(facts) >= MAX_FACTS:
            if lens and not exempt and text not in used and quote_of(line):
                left_out[lens.layer(rel)] = left_out.get(lens.layer(rel), 0) + 1
            continue
        if text in used:
            continue
        used.add(text)
        if exempt:
            ids = [v for k, v in verify_kb.TAG.findall(line) if k == "?"]
            unknown.append("- %s%s" % (text, " " + " ".join("[?: %s]" % i for i in ids) if ids else ""))
            continue
        q = quote_of(line)
        if q:
            facts.append("- %s [E: kb:%s \"%s\"]" % (text, rel, q))
            if lens and info is not None:
                info.setdefault("layers", {})[rel] = lens.layer(rel)
    edges = graph_lines(kb, question, direction_words, boost, viewer)
    cut = max(0, len(edges) - lens.a["graph_lines"]) if lens else 0
    for text, quote in edges[:len(edges) - cut]:
        facts.append("- %s [E: kb:CROSS-LAYER/LINK_GRAPH.yaml \"%s\"]" % (text, quote))
    if info is not None and lens:
        info.update(audience=lens.id, describe=lens.describe(), left_out=left_out, links_cut=cut,
                    layers_used=sorted(set(info.get("layers", {}).values())))
    if held:
        unknown.append(WITHHELD_NOTE)
    elif not facts:
        unknown.insert(0, "- The KB has no line about: %s" % C.clean(question))
    return render_answer(question, facts, unknown), len(facts), len(unknown)


def audience_lens(kb, who, asked=None):
    """The audience.Lens for this asker, or None (the KB's own order). A bad audience name raises UiError."""
    import audience as aud
    try:
        return aud.lens_for(kb, who, asked)
    except aud.AudienceError as exc:
        raise C.UiError(str(exc))


def render_answer(question, facts, unknown):
    lines = ["# Answer: %s" % C.clean(question), ""] + facts
    if unknown:
        lines += ["", "## Not in the KB", ""] + unknown
    return "\n".join(lines) + "\n"


def check(kb, path):
    rep = verify_kb.Checker(kb).check_answer(path)
    return {"lines": rep["fact_lines"], "tags": rep["tags"], "problems": rep["problems"]}


# ---- confidence: computed from the checked answer, never claimed by a model --------------------------------
# words that name the kind of thing asked about, or only pad the question; a direct answer need not repeat them
FILLER = {"have", "has", "had", "many", "much", "make", "made", "need", "exist", "exists",
          "table", "column", "field", "row", "screen", "page", "file", "module", "job", "endpoint", "layer", "app", "application",
          "database", "data", "system", "service", "name", "type", "kind", "thing"}
INFERRED = re.compile(r"^\s*(?:[-*>]|\d+[.)])?\s*(?:\(?inferred\)?:?|inference:|derived:)", re.I)
BANDS = ((85, "High"), (60, "Medium"), (1, "Low"), (0, "None"))


def freshness(kb, files):
    """{"stale": [{page, reasons}], "unknown": [repo...], "checked": bool} for the pages an answer used.

    A page is stale when a source file it cites changed since the commit recorded at the last build (build_plan.stale). A repo
    with no recorded commit, or one whose commit is gone, cannot be compared: that is reported as unknown, not as stale, so a KB
    that never recorded a build is not flagged on every answer. Never stops an answer: any failure gives checked False."""
    out = {"stale": [], "unknown": [], "checked": False}
    if not files:
        return out
    try:
        import build_plan
        rows, _notes = build_plan.stale(kb)
    except Exception:  # noqa: BLE001  no profile, no git, no clone: freshness is extra
        return out
    out["checked"] = True
    used = set(files)
    for row in rows:
        if row["page"] not in used:
            continue
        real = [x for x in row["reasons"] if not x.endswith("cannot compare")]
        if real:
            out["stale"].append({"page": row["page"], "reasons": real})
        out["unknown"] += [x.split(":")[0] for x in row["reasons"] if x.endswith("cannot compare")]
    out["unknown"] = sorted(set(out["unknown"]))
    return out


def confidence(question, text, fresh=None):
    """{"score": 0-100, "band": ..., "reasons": [...]}. 100 means one KB line answers the whole question word for word.

    Points come off for what the answer had to do beyond quoting: join several lines, follow a recorded link, infer, leave a part
    out, rest on an open question, or cite a page whose source changed since the build (`fresh`, from freshness()). The reasons
    are shown with the number so the person can judge it."""
    q = {s for s in stems(question) if s not in FILLER}
    facts, not_in, exempt = [], 0, False
    for line in text.splitlines():
        s = line.strip()
        h = verify_kb.HEADING.match(s)
        if h:
            exempt = bool(verify_kb.EXEMPT.search(verify_kb.TAG.sub("", h.group(2))))
            continue
        if not s:
            continue
        if exempt:
            not_in += 1 if re.match(r"^([-*]|\d+[.)])\s", s) else 0
            continue
        tags = verify_kb.TAG.findall(s)
        if any(k == "E" for k, _ in tags):
            facts.append((s, tags))
    if not facts:
        return {"score": 0, "band": "None", "reasons": ["No KB line answers this question."]}
    score, why, cap = 100, [], 100
    cover = [q & {s for s in stems(plain(l)) if s not in FILLER} for l, _ in facts]
    if q:
        whole = len(set().union(*cover)) / len(q)
        best = max(len(c) for c in cover) / len(q)
        if whole < 1:
            lost = {w for w in q if not any(w in c for c in cover)}
            score -= round(30 * (1 - whole))
            why.append("Not covered by any line used: %s." % ", ".join(sorted(lost)))
        if best < 1 and len(facts) > 1:
            score -= round(25 * (1 - best))
            cap = min(cap, 92)  # joined lines are an assembly, not a quote: below 100 but can stay High
            why.append("No single KB line answers the whole question; it is put together from %d lines." % len(facts))
        elif best < 1:
            score -= round(25 * (1 - best))
            why.append("The one KB line used covers only part of the question.")
    linked = [l for l, t in facts if "LINK_GRAPH.yaml" in l]
    if linked and len(linked) == len(facts):
        score -= 10
        why.append("Every line is a relationship the KB records between two objects, not a sentence a page states.")
    inferred = [l for l, _ in facts if INFERRED.match(l)]
    if inferred:
        score -= min(45, 15 * len(inferred))
        cap = min(cap, 80)  # a conclusion the KB does not state is never High
        why.append("%d line%s inferred from KB lines rather than stated by them." % (len(inferred), "" if len(inferred) == 1 else "s"))
    if not_in:
        score -= min(20, 10 * not_in)
        cap = min(cap, 84)  # part of the question has no answer
        why.append("One part of the question is not in the KB." if not_in == 1 else "%d parts of the question are not in the KB." % not_in)
    opened = sum(1 for _, t in facts for k, _ in t if k == "?")
    if opened:
        score -= min(20, 10 * opened)
        cap = min(cap, 84)  # the KB itself is unsure
        why.append("An open question in the KB bears on this." if opened == 1 else "%d open questions in the KB bear on this." % opened)
    if fresh and fresh.get("stale"):
        n = len(fresh["stale"])
        score -= min(25, 15 * n)
        cap = min(cap, 84)  # the source moved on since the KB was built: never High
        why.append("%d page%s used cite%s a source that changed since the KB was built: %s." % (
            n, "" if n == 1 else "s", "s" if n == 1 else "", ", ".join(x["page"] for x in fresh["stale"][:3])))
    score = max(1, min(cap, score))
    if not why:
        why.append("A KB line states this directly, and its quote was checked against the page.")
    return {"score": score, "band": next(b for floor, b in BANDS if score >= floor), "reasons": why}


def cited_files(text):
    files, _ = feedback.cited(text)
    return sorted(set(files))


def _cited_lines(kb, text):
    """Cited path:line pairs for per-line telemetry. Never stops an answer: any failure gives no lines."""
    try:
        import telemetry_lines
        return telemetry_lines.cited_lines(kb, text)
    except Exception:  # noqa: BLE001
        return None



def ask(kb, question, by, mode="local", direction=None, follows=None, queue_task=True, audience=None):
    question, by = C.clean(question), C.clean(by)
    if not question:
        raise C.UiError("write the question first")
    if not by:
        raise C.UiError("say who is asking (top right, 'You are')")
    aid = next_id(kb)
    r = {"id": aid, "question": question, "by": by, "on": C.now(), "mode": mode, "direction": C.clean(direction) or None,
         "follows": follows, "status": "answered", "answer_file": None, "checked": None, "files": [], "task": None,
         "rating": None, "feedback": None, "hints": []}
    audience_lens(kb, by, audience)  # a misspelt audience is refused before anything is written
    try:
        r["hints"] = feedback.hints(kb, question)
    except Exception:
        r["hints"] = []
    dirs = " ".join([direction or ""] + [h["direction"] for h in r["hints"]])
    if mode == "local":
        lens_info = {}
        text, nfacts, nunk = compose(kb, question, dirs.strip() or None, who=by, audience=audience, info=lens_info)
        if lens_info.get("audience"):
            r["audience"] = {k: lens_info[k] for k in ("audience", "describe", "left_out", "links_cut", "layers_used")}
        C.write_text(answer_path(kb, aid), text)
        chk = check(kb, answer_path(kb, aid))
        if chk["problems"]:
            # a line the checker rejects is dropped, never shown: the answer keeps only what holds
            bad = {p["line"] for p in chk["problems"]}
            keep = [l for i, l in enumerate(text.splitlines(), 1) if i not in bad]
            text = "\n".join(keep) + "\n"
            C.write_text(answer_path(kb, aid), text)
            chk = check(kb, answer_path(kb, aid))
        files = cited_files(text)
        fresh = freshness(kb, files)
        r.update(answer_file=aid + ".md", checked=chk, files=files, freshness=fresh, confidence=confidence(question, text, fresh))
        if not chk["lines"] or r["confidence"]["band"] != "High":
            r["guidance"] = guidance(kb, question, by)
        if r["files"]:
            telemetry.record(kb, "answer", r["files"], by=by, lines=_cited_lines(kb, text))
    else:
        import tasks
        r["status"] = "waiting"
        t = tasks.create(kb, "ask", "Answer %s" % aid, ask_instructions(kb, r), by, ref=aid,
                         result_hint=os.path.abspath(answer_path(kb, aid)))
        r["task"] = t["id"]
    save(kb, r)
    return r


def ask_instructions(kb, r):
    ans = os.path.abspath(answer_path(kb, r["id"]))
    extra = ""
    if r.get("direction"):
        extra += "\nThe asker says to look here: %s\n" % r["direction"]
    for h in r.get("hints") or []:
        extra += "A lead approved this direction for a similar question: %s\n" % h["direction"]
    return ("Answer this question using only the Metis knowledge base, with the `metis-ask` skill.\n\n"
            "Question: %s\nAsked by: %s\nKB folder: %s\n%s\n"
            "Write the answer to: %s\n"
            "Every fact line cites the KB as [E: kb:<path> \"quoted text\"], the quote copied exactly from that file. A point the KB\n"
            "does not cover goes under `## Not in the KB`. Check it with: python3 <metis>/tools/verify_kb.py %s --answer %s\n"
            "It must report 0 problems. Then finish the task (the UI refuses an answer with a source problem):\n"
            "  python3 <metis>/tools/ui/tasks.py complete %s <task id> --by \"<your name>\" --file %s\n\n"
            "If you cannot tell what the person means, look for the path first: search the KB for their words, near spellings and the\n"
            "names in KNOWLEDGE-MANIFEST.yaml and LINK_GRAPH.yaml. Only if two or more readings of the question remain, ask them, at most\n"
            "%d short questions, each offering the readings you found in the KB's own words, and at most %d times:\n"
            "  python3 <metis>/tools/ui/tasks.py ask-user %s <task id> --by \"<your name>\" --question \"<question>\"\n"
            "  python3 <metis>/tools/ui/tasks.py wait %s <task id>      (prints the person's reply; run it again if it says no reply yet)\n"
            "Use the reply to find the right KB lines. Never invent a fact to make the question easier to answer.\n\n"
            "Confidence is computed by the UI from your answer. Quote a KB line that states the answer when one exists. If you must\n"
            "combine lines or draw a conclusion the KB does not state, start that line with `Inferred:` (the line still cites the KB\n"
            "lines it comes from). Do not hide an inference inside a plain line, and never write a confidence number yourself.\n"
            % (r["question"], r["by"], os.path.abspath(kb), extra, ans, os.path.abspath(kb), ans, os.path.abspath(kb), ans,
               MAX_ASK_QUESTIONS, MAX_ASK_ROUNDS, os.path.abspath(kb), os.path.abspath(kb)))


def attach_model_answer(kb, aid, file, by, tid):
    r = get(kb, aid)
    text = C.read_text(file)
    dst = answer_path(kb, aid)
    C.write_text(dst, text)
    chk = check(kb, dst)
    if chk["problems"]:
        os.remove(dst)
        shown = "\n".join("line %d: %s" % (p["line"], p["problem"]) for p in chk["problems"][:15])
        raise C.UiError("the answer has %d source problems; fix them and complete the task again:\n%s" % (len(chk["problems"]), shown))
    if not chk["lines"] and "## Not in the KB" not in text:
        os.remove(dst)
        raise C.UiError("the answer has no checked line and no 'Not in the KB' section")
    files = cited_files(text)
    fresh = freshness(kb, files)
    r.update(status="answered", answer_file=aid + ".md", checked=chk, files=files, answered_by=by, task=tid, freshness=fresh,
             confidence=confidence(r["question"], text, fresh))
    if not chk["lines"] or r["confidence"]["band"] != "High":
        r["guidance"] = guidance(kb, r["question"])
    save(kb, r)
    if r["files"]:
        telemetry.record(kb, "answer", r["files"], by=r["by"], lines=_cited_lines(kb, text))
    return r


def clarify(kb, aid, by, text):
    """The person says more about what they meant. Ask the same question again with their words as the direction."""
    r = get(kb, aid)
    text = C.clean(text)
    if not text:
        raise C.UiError("say a little more about what you want to know")
    if r.get("status") == "waiting":
        raise C.UiError("this question is still being answered")
    return ask(kb, r["question"], C.clean(by), mode=r.get("mode") or "local", direction=text, follows=aid)


def reword(kb, aid, by, question):
    """The person picks a spelling or wording the KB uses. Ask that question, linked to the first."""
    r = get(kb, aid)
    return ask(kb, question, C.clean(by), mode=r.get("mode") or "local", follows=aid)


def answer_text(kb, r):
    if not r.get("answer_file"):
        return ""
    return C.read_text(os.path.join(folder(kb), r["answer_file"]))


# ---- like and dislike ---------------------------------------------------------------------------------
def rate(kb, aid, by, rating, why=None, correct=None, redirect=None):
    """Record the rating through feedback.py. Returns (feedback item, new ask or None). A direction asks again at once."""
    r = get(kb, aid)
    if r.get("feedback"):
        raise C.UiError("this answer is already rated (%s)" % r["feedback"])
    if not r.get("answer_file"):
        raise C.UiError("there is no answer to rate yet")
    try:
        item = feedback.record(kb, os.path.join(folder(kb), r["answer_file"]), r["question"], by, rating, why, correct, redirect)
    except feedback.FeedbackError as err:
        raise C.UiError(str(err))
    try:  # keep a stable fingerprint of the cited lines so per-line counts survive page edits (telemetry_lines.py); never stops a rating
        import telemetry_lines
        telemetry_lines.anchor_rated(kb, item["id"])
    except Exception:  # noqa: BLE001
        pass
    r.update(rating=rating, feedback=item["id"], rated_by=C.clean(by))
    save(kb, r)
    again = None
    if item.get("redirect"):
        again = ask(kb, r["question"], r["by"], mode="local", direction=item["redirect"], follows=aid)
    return item, again


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("ask"); a.add_argument("kb"); a.add_argument("question"); a.add_argument("--by", required=True)
    a.add_argument("--direction")
    a = sub.add_parser("list"); a.add_argument("kb")
    args = ap.parse_args(argv)
    kb = os.path.abspath(args.kb)
    try:
        if args.cmd == "ask":
            r = ask(kb, args.question, args.by, direction=args.direction)
            print(answer_text(kb, r))
            print("%d lines checked, %d problems" % (r["checked"]["lines"], len(r["checked"]["problems"])))
        else:
            for r in all_asks(kb):
                print("%s\t%s\t%s\t%s" % (r["id"], r["status"], r.get("rating") or "-", r["question"][:70]))
    except C.UiError as err:
        print("error: %s" % err, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
