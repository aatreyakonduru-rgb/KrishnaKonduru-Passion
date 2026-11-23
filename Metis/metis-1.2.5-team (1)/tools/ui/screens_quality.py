"""Quality screen for Metis UI.

Path /quality, nav label "Quality". Tabs (query parameter tab=): contradictions, duplicates, links, trend, lines, judge.
Read only: it shows what kb_contradict.py, kb_dupes.py, kb_links.py, kb_trend.py, telemetry_lines.py and llm_judge.py wrote or can
compute, and never edits a KB page. The one action is "Raise as question" on a contradiction pair, for named leads; it adds a
question to the register through kb_contradict.raise_by_id (questions.py) and nothing else.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
for _p in (TOOLS, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import urllib.parse  # noqa: E402

import kb_contradict  # noqa: E402
import kb_dupes  # noqa: E402
import kb_gate  # noqa: E402
import kb_links  # noqa: E402
import kb_trend  # noqa: E402
import llm_judge  # noqa: E402
import telemetry_lines  # noqa: E402
import ui_common as C  # noqa: E402
from ui_common import esc, form, page  # noqa: E402

TABS = [("contradictions", "Contradictions"), ("duplicates", "Duplicates"), ("links", "Links"), ("trend", "Trend"),
        ("lines", "Lines to look at first"), ("judge", "Judge verdicts")]
SHOW = 50


def table(head, rows):
    return "<table><tr>%s</tr>%s</table>" % ("".join("<th>%s</th>" % h for h in head),
                                             "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % c for c in r) for r in rows))


def page_link(rel):
    return '<a href="/files?page=%s">%s</a>' % (esc(urllib.parse.quote(str(rel))), esc(rel))


def ref_link(page_rel, line):
    return '%s <span class="muted">line %s</span>' % (page_link(page_rel), esc(line))


def not_built(cmd):
    return '<div class="card soft">Not built yet. Run <code>%s</code>.</div>' % esc(cmd)


def more(total, shown):
    return '<p class="muted">%d more not shown.</p>' % (total - shown) if total > shown else ""


def is_lead(ctx):
    name = C.clean(ctx.user)
    return bool(name) and name.lower() in kb_gate.certifiers(ctx.kb)


# ---- tabs --------------------------------------------------------------------------------------
def contradictions_tab(ctx):
    rep = kb_contradict.load_report(ctx.kb)
    if not rep:
        return not_built("python tools/kb_contradict.py scan <KB>")
    items = rep.get("contradictions") or []
    lead = is_lead(ctx)
    out = ['<p class="lead">Pairs of lines on different pages that look as if they disagree about the same thing. Many are not '
           'contradictions (the same name can mean two things, or a value can differ by environment). A lead reads each pair; nothing '
           "is edited. Found %s on %s: %d pairs from %d claims on %d pages.</p>" % (
               esc(rep.get("as_of")), esc(rep.get("scope")), rep.get("pairs", 0), rep.get("claims_read", 0), rep.get("pages_read", 0))]
    if not items:
        return "".join(out) + '<div class="card soft">No pair found.</div>'
    rows = []
    for e in items[:SHOW]:
        a, b = e["a"], e["b"]
        status = e.get("status", "open")
        j = e.get("judgement")
        note = ('<br><span class="muted">%s: %s (%s)</span>' % (esc(j["verdict"]), esc(j["reason"]), esc(j["judged_by"]))) if j else ""
        act = ""
        if status != "dismissed":
            if lead:
                act = form(ctx, "/quality/raise", '<input type="hidden" name="id" value="%s"><button class="alt">Raise as question</button>' % esc(e["id"]))
            else:
                act = '<span class="muted">leads only</span>'
        rows.append([esc(e["id"]), "<b>%s</b><br>%s" % (esc(e["subject"]), esc(e["attribute"])),
                     '%s<br><code>%s</code><br><span class="muted">%s</span>' % (ref_link(a["page"], a["line"]), esc(a["value"]), esc(a["text"][:140])),
                     '%s<br><code>%s</code><br><span class="muted">%s</span>' % (ref_link(b["page"], b["line"]), esc(b["value"]), esc(b["text"][:140])),
                     '<span class="pill %s">%s</span>' % ("warn" if e["confidence"] == "high" else "", esc(e["confidence"])),
                     esc(status) + note, act])
    out.append(table(["Id", "Subject", "One page says", "Another says", "Pattern confidence", "Status", ""], rows))
    out.append(more(len(items), SHOW))
    if not lead:
        out.append('<p class="muted">Only a named lead can raise a pair as a question%s.</p>' % (
            "" if C.clean(ctx.user) else " (say who you are first, top right)"))
    return "".join(out)


def duplicates_tab(ctx):
    rep = kb_dupes.load_report(ctx.kb)
    if not rep:
        return not_built("python tools/kb_dupes.py scan <KB>")
    th = rep.get("thresholds") or {}
    out = ['<p class="lead">Near-duplicate text is a maintenance risk (one copy gets fixed, the other does not), not an error. '
           "Nothing is merged or deleted. Thresholds: pages %s, paragraphs %s. %d pages read.</p>" % (
               esc(th.get("page")), esc(th.get("paragraph")), rep.get("pages_read", 0))]
    pages = rep.get("duplicate_pages") or []
    paras = rep.get("duplicate_paragraphs") or []
    out.append("<h2>Pages (%d)</h2>" % len(pages))
    out.append(table(["Page", "Page", "Overlap", "Kind"], [[page_link(p["a"]), page_link(p["b"]), "%.0f%%" % (100 * p["similarity"]), esc(p["kind"])]
                                                           for p in pages[:SHOW]]) if pages else '<p class="muted">No near-duplicate pages.</p>')
    out.append(more(len(pages), SHOW))
    out.append("<h2>Paragraphs (%d)</h2>" % len(paras))
    out.append(table(["Where", "Where", "Overlap", "Text"], [[ref_link(p["a"]["page"], p["a"]["line"]), ref_link(p["b"]["page"], p["b"]["line"]),
                                                               "%.0f%%" % (100 * p["similarity"]), esc(p["text"])] for p in paras[:SHOW]])
               if paras else '<p class="muted">No near-duplicate paragraphs on different pages.</p>')
    out.append(more(len(paras), SHOW))
    return "".join(out)


def links_tab(ctx):
    rep = kb_links.load_report(ctx.kb)
    if not rep:
        return not_built("python tools/kb_links.py check <KB>")
    out = ['<p class="lead">Markdown links and anchors between KB pages, and pages nothing links to. Report only. %d links in %d pages.</p>' % (
        rep.get("links_checked", 0), rep.get("pages", 0))]
    broken = rep.get("broken") or []
    out.append("<h2>Broken links (%d)</h2>" % len(broken))
    out.append(table(["Page", "Line", "Problem", "Target"], [[page_link(b["page"]), esc(b["line"]), esc(b["problem"]), "<code>%s</code>" % esc(b["target"])]
                                                            for b in broken[:SHOW]]) if broken else '<p class="muted">No broken link.</p>')
    out.append(more(len(broken), SHOW))
    orphans = rep.get("orphans") or []
    out.append("<h2>Orphan pages (%d)</h2>" % len(orphans))
    out.append('<p class="muted">No other page links to these and no index page lists them. Search can still find them.</p>')
    out.append("<ul>%s</ul>" % "".join("<li>%s</li>" % page_link(o) for o in orphans[:SHOW]) if orphans else '<p class="muted">No orphan page.</p>')
    out.append(more(len(orphans), SHOW))
    return "".join(out)


def trend_tab(ctx):
    snaps = kb_trend.trend(ctx.kb, 30)
    if not snaps:
        return not_built("python tools/kb_trend.py record <KB>")
    rows = []
    for label, vals in kb_trend.series(snaps).items():
        ch = kb_trend.change(vals)
        last = next((v for v in reversed(vals) if v is not None), "")
        rows.append([esc(label), kb_trend.sparkline(vals, label=label), esc(last),
                     "%s to %s" % (esc(ch[0]), esc(ch[1])) if ch else '<span class="muted">one build</span>'])
    return ('<p class="lead">One snapshot of counts per build, kept in <code>.metis/trend.jsonl</code>. %d builds shown, oldest on the left. '
            "A line going down is better for every row except pages.</p>%s" % (
                len(snaps), table(["Measure", "Last %d builds" % len(snaps), "Now", "First to last"], rows)))


def split_ref(ref):
    rel, _, n = ref.rpartition(":")
    return rel, n


def lines_tab(ctx):
    rep = telemetry_lines.report(ctx.kb, SHOW)
    out = ['<p class="lead">KB lines cited by answers people disliked, most dislikes first. A dislike names an answer, not a line: a cited '
           "line may be right and the answer wrong. Read this as where to look first, not as a verdict. A line is followed by its text, "
           "so its number is where it is now; a line whose text was edited or deleted shows as no longer existing. Ratings given before "
           "this was kept are read by line number. %d answers recorded with lines; %d lines used in all.</p>" % (
               rep["answers_with_lines"], rep["lines_used"])]
    rows = rep["look_first"]
    if not rows:
        out.append('<div class="card soft">No line is cited in a disliked answer.</div>')
    else:
        out.append(table(["Line", "Disliked", "Liked", "Declined by a lead", "Times used", "Now says"],
                         [[ref_link(*split_ref(r["line"])), r["down"], r["up"], r["declined"], r["used"],
                           esc(r["text"][:140]) if r["text"] is not None else '<span class="no">line no longer exists</span>'] for r in rows]))
    if rep["rated_answers_without_lines"]:
        out.append('<p class="muted">%d rated answer%s cited no line (file-only tags, or no copy kept).</p>' % (
            rep["rated_answers_without_lines"], "" if rep["rated_answers_without_lines"] == 1 else "s"))
    return "".join(out)


def judge_tab(ctx):
    rows = llm_judge.list_requests(ctx.kb)
    out = ['<p class="lead">A judge reads a claim and its quoted source text and says supported, partly supported or not supported. '
           "It never says the claim is correct. Verdicts are written by a Devin or Bob session (or an endpoint your profile names). "
           "They sit beside the lexical checks and do not replace them.</p>"]
    if not rows:
        return "".join(out) + not_built("python tools/llm_judge.py golden_judge <KB> <answers folder>")
    n = {k: sum(1 for r in rows if r["status"] == k) for k in ("judged", "pending", "error")}
    out.append("<p>%d requests: %d judged, %d waiting for a verdict, %d with a problem.</p>" % (len(rows), n["judged"], n["pending"], n["error"]))
    body = []
    for r in sorted(rows, key=lambda r: (r["status"] != "error", r["status"] != "judged", r["id"]))[:SHOW]:
        pill = {"judged": {"supported": "ok", "partial": "warn", "unsupported": "no"}.get(r.get("verdict"), ""), "pending": "", "error": "no"}[r["status"]]
        body.append([esc(r["id"]), esc(r.get("where") or ""), esc(r.get("claim", "")[:140]), esc(r.get("source") or ""),
                     '<span class="pill %s">%s</span>' % (pill, esc(r.get("says") or r["status"])), esc(r.get("reason", "")),
                     esc(r.get("judged_by", ""))])
    out.append(table(["Id", "Where", "Claim", "Source", "Verdict", "Reason", "Judged by"], body))
    out.append(more(len(rows), SHOW))
    out.append('<p class="muted">%s</p>' % esc(llm_judge.NOTE))
    return "".join(out)


TAB_FN = {"contradictions": contradictions_tab, "duplicates": duplicates_tab, "links": links_tab, "trend": trend_tab,
          "lines": lines_tab, "judge": judge_tab}


def counts(ctx):
    """Short text per tab for the left pane. Never raises."""
    out = {}
    try:
        r = kb_contradict.load_report(ctx.kb)
        out["contradictions"] = "%d pairs" % r["pairs"] if r else "not built"
        r = kb_dupes.load_report(ctx.kb)
        out["duplicates"] = "%d page pairs, %d paragraph pairs" % (r["page_pairs"], r["paragraph_pairs"]) if r else "not built"
        r = kb_links.load_report(ctx.kb)
        out["links"] = "%d broken, %d orphans" % (r["broken_links"], r["orphan_pages"]) if r else "not built"
        n = len(kb_trend.trend(ctx.kb, 0))
        out["trend"] = "%d builds" % n if n else "none recorded"
        out["lines"] = "%d lines" % len(telemetry_lines.report(ctx.kb, 0)["look_first"])
        out["judge"] = "%d requests" % len(llm_judge.list_requests(ctx.kb))
    except Exception:
        pass
    return out


def quality(ctx, q, flash=None, error=None):
    tab = C.clean(q.get("tab")) or "contradictions"
    if tab not in TAB_FN:
        tab = "contradictions"
    try:
        content = TAB_FN[tab](ctx)
    except Exception as err:  # a broken report must not take the page down
        content = '<div class="err">This tab could not be read: %s: %s</div>' % (esc(type(err).__name__), esc(err))
    label = dict(TABS)[tab]
    body = '<h1>Quality</h1><h2>%s</h2>%s' % (esc(label), content)
    sub = counts(ctx)
    left = C.left_pane("Quality checks", "".join(C.pane_item("/quality?tab=%s" % k, esc(v), esc(sub.get(k, "")), on=(k == tab)) for k, v in TABS))
    right = C.right_pane(
        '<h4>About this page</h4><div class="muted">Reports are written at build time by the quality tools. Nothing here edits a page. '
        "A flagged pair or line is a place to look, not a finding that the KB is wrong.</div>"
        '<h4>Who can act</h4><div class="muted">Leads: %s</div>' % esc(", ".join(v[0] for v in kb_gate.certifiers(ctx.kb).values()) or "nobody is named yet"))
    return page(ctx, "Quality", "/quality", body, flash, error, left=left, right=right)


def act_raise(ctx, f):
    name = C.clean(ctx.user)
    if not name:
        raise C.UiError("Say who you are first (top right, 'You are'). Your name goes on every question you raise.")
    try:
        kb_gate.who(ctx.kb, name)
        qid, added = kb_contradict.raise_by_id(ctx.kb, C.clean(f.get("id")), name)
    except (kb_gate.GateError, kb_contradict.ContradictError, ValueError) as err:
        raise C.UiError(str(err))
    return "/quality?tab=contradictions", ("Raised as %s." % qid) if added else ("%s already holds this question." % qid)


SCREENS = {"/quality": quality}
ACTIONS = {"/quality/raise": ("/quality", act_raise)}
NAV = [("/quality", "Quality")]
