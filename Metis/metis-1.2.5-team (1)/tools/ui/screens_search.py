"""Search screen for Metis UI.

Path /search, nav label "Search".
Searches the text of the KB pages (kb_search.py: BM25, glossary synonyms, facets, snippets that keep the [E: ...] tag) and, in a
second tab, lists what people asked that the KB could not answer (kb_unanswered.py).
GET only: nothing here writes to the KB. The one thing it may write is the opt-in hashed miss counter (profile search.count_misses),
which stores counts and no query text. No JavaScript.

Parameters: q (words), folder, type, owner, oq (yes|no), stale (yes|no), tab (results|unanswered).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
for _p in (TOOLS, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import urllib.parse  # noqa: E402

import kb_search  # noqa: E402
import kb_unanswered  # noqa: E402
import ui_common as C  # noqa: E402
from ui_common import esc, field, form, page  # noqa: E402

LIMIT = 30
FACET_KEYS = (("folder", "folder", "Folder"), ("type", "type", "Page type"), ("owner", "owner", "Owner"),
              ("oq", "open_question", "Open question"), ("stale", "stale", "Stale"))


def clean_params(q):
    return {k: C.clean(q.get(k)) for k in ("q", "folder", "type", "owner", "oq", "stale", "tab")}


def url(p, **over):
    """A /search link with the current parameters changed by `over`; an empty value drops the parameter."""
    d = dict(p, **over)
    qs = urllib.parse.urlencode([(k, v) for k, v in d.items() if v and not (k == "tab" and v == "results")])
    return "/search" + ("?" + qs if qs else "")


def page_href(rel, line=None):
    return "/files?page=%s" % urllib.parse.quote(rel, safe="/")


def left_side(p, facets, total_pages):
    """Facets: each value is a link that narrows the search; the chosen value is marked and links back to clear it."""
    out = []
    for key, name, label in FACET_KEYS:
        counts = facets.get(name) or {}
        if not counts:
            continue
        out.append('<div class="grp">%s</div>' % esc(label))
        for value, n in counts.items():
            on = p.get(key, "").lower() == str(value).lower()
            out.append(C.pane_item(url(p, **{key: "" if on else value}), esc(value), "%d page%s%s" % (n, "" if n == 1 else "s", " &middot; click to clear" if on else ""), on=on))
    if not out:
        out.append('<div class="it muted">No page is indexed yet. Build the KB first.</div>')
    clear = ""
    if any(p.get(k) for k, _, _ in FACET_KEYS):
        clear = '<div class="it"><a href="%s">Clear all filters</a></div>' % esc(url(p, folder="", type="", owner="", oq="", stale=""))
    return C.left_pane("Filters", clear + "".join(out), total_pages)


def result_card(r):
    pills = ""
    if r["stale"]:
        pills += ' <span class="pill warn" title="%s">stale</span>' % esc(r["stale_why"])
    if r["open_question"]:
        pills += ' <span class="pill warn">open question</span>'
    if r["type"]:
        pills += ' <span class="pill">%s</span>' % esc(r["type"])
    if r["owner"]:
        pills += ' <span class="pill blue">owner %s</span>' % esc(r["owner"])
    snippet = ('<div><span class="muted">line %d:</span> %s</div>' % (r["line"], C.inline(r["snippet"]))) if r["snippet"] else ""
    return ('<div class="card"><div><a href="%s"><b>%s</b></a> <span class="muted">%s</span>%s</div>'
            '<div class="muted"><small>%s</small></div>%s</div>') % (
        esc(page_href(r["path"])), esc(r["title"]), esc(r["path"]), pills, esc(r["heading"]), snippet)


def tabs(p, unanswered_count):
    def tab(name, label):
        on = (p.get("tab") or "results") == name
        return '<a class="btn%s" href="%s">%s</a>' % ("" if on else " alt", esc(url(p, tab=name)), label)
    return '<p>%s %s</p>' % (tab("results", "Results"), tab("unanswered", "Unanswered%s" % (" (%d)" % unanswered_count if unanswered_count else "")))


def search_box(ctx, p):
    hidden = "".join('<input type="hidden" name="%s" value="%s">' % (k, esc(p[k])) for k in ("folder", "type", "owner", "oq", "stale") if p.get(k))
    body = (field("q", "Search the KB pages", p.get("q", ""), hint="words from a page, a table name, a business term (the glossary adds synonyms)") +
            hidden + "<p><button>Search</button></p>")
    return form(ctx, "/search", body, method="get")


def unanswered_body(ctx):
    rep = kb_unanswered.report(ctx.kb, 50)
    out = ['<h2>Unanswered (%d)</h2>' % rep["total"],
           '<p class="muted">What people asked in Ask, disliked, or raised as a question, that the KB could not answer well. It reads the '
           "records Metis already keeps; no new question text is collected. Higher score = more urgent.</p>"]
    if not rep["items"]:
        out.append('<div class="card soft">Nothing is unanswered right now.%s</div>' % "".join(" " + esc(n) for n in rep["notes"]))
    else:
        rows = []
        for i, it in enumerate(rep["items"], 1):
            refs = ", ".join(esc(x) for x in it["refs"][:6])
            ask = '<a href="/ask?question=%s">Ask again</a>' % esc(urllib.parse.quote(it["question"]))
            rows.append("<tr><td>%d</td><td>%s<br><small class=\"muted\">%s</small></td><td><b>%d</b></td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                i, esc(it["question"]), esc("; ".join(it["detail"][:2])), it["score"], esc(", ".join(it["why"])),
                esc(", ".join(it["askers"]) or "-"), esc(it["last_on"] or "-"), refs + "<br>" + ask))
        out.append("<table><tr><th>#</th><th>Question</th><th>Score</th><th>Why</th><th>Asked by</th><th>Last</th><th>Records</th></tr>%s</table>" % "".join(rows))
    out.append('<p class="muted"><small>%s</small></p>' % esc(rep["telemetry"]["note"]))
    c = rep["counter"]
    if c["enabled"]:
        out.append('<p class="muted"><small>Searches that found nothing: %d in all, %d distinct (counted by salted hash; the words are not stored).</small></p>' % (
            c["total"], c["distinct"]))
    else:
        out.append('<p class="muted"><small>The searches-that-found-nothing counter is off. Turn it on with search.count_misses: true in the KB profile.</small></p>')
    return "".join(out), rep["total"]


def search_view(ctx, q, flash=None, error=None):
    p = clean_params(q)
    tab = "unanswered" if p.get("tab") == "unanswered" else "results"
    p["tab"] = tab
    body = ['<h1>Search</h1><p class="lead">Find a word, name or rule inside the KB pages. Each result shows the line that matched, '
            "with its source tag, and opens the page.</p>"]
    rep, facets, total_pages = None, {}, 0
    try:
        has_filter = any(p.get(k) for k, _, _ in FACET_KEYS)
        want = LIMIT if (p["q"] or has_filter) else 0
        # who: the signed-in name decides which labelled lines may show (claim_labels.py); no name = the lowest clearance
        rep = kb_search.search(ctx.kb, p["q"], folder=p["folder"] or None, ptype=p["type"] or None, owner=p["owner"] or None,
                               open_question=p["oq"] or None, stale=p["stale"] or None, limit=want, who=ctx.user)
        facets = rep["facets"]
        total_pages = sum(facets.get("folder", {}).values())
    except Exception as err:  # a broken index must show as a message, not take the page down
        error = error or "Search failed: %s: %s" % (type(err).__name__, err)
    un_html, un_count = "", 0
    if tab == "unanswered":
        un_html, un_count = unanswered_body(ctx)
    else:
        try:
            un_count = kb_unanswered.report(ctx.kb, 0)["total"]
        except Exception:
            un_count = 0
    body.append(search_box(ctx, p))
    body.append(tabs(p, un_count))
    if tab == "unanswered":
        body.append(un_html)
    elif rep is not None:
        if rep["notes"]:
            body.append('<div class="card soft">%s</div>' % "<br>".join(esc(n) for n in rep["notes"]))
        if not p["q"] and not has_filter:
            body.append('<div class="card soft">Type some words above, or pick a filter on the left. %d page%s %s indexed.</div>' % (
                total_pages, "" if total_pages == 1 else "s", "is" if total_pages == 1 else "are"))
        else:
            what = ' for <b>%s</b>' % esc(p["q"]) if p["q"] else ""
            extra = ""
            if rep["synonyms"]:
                extra = ' <span class="muted">Also searched (glossary): %s.</span>' % esc(", ".join(rep["synonyms"]))
            body.append("<h2>%d page%s%s</h2>%s" % (rep["total"], "" if rep["total"] == 1 else "s", what, extra))
            if not rep["results"]:
                body.append('<div class="card soft">No page matches.%s Try fewer words, a name as the KB spells it, or clear a filter. '
                            'The <a href="%s">Unanswered tab</a> shows what the KB could not answer.</div>' % (
                                "", esc(url(p, tab="unanswered"))))
                if p["q"]:
                    try:
                        kb_unanswered.record_miss(ctx.kb, p["q"])  # a no-op unless the profile opts in; stores a salted hash, not the words
                    except Exception:
                        pass
            body.append("".join(result_card(r) for r in rep["results"]))
            if rep["total"] > len(rep["results"]):
                body.append('<p class="muted">Showing the first %d of %d. Narrow the search with a filter.</p>' % (len(rep["results"]), rep["total"]))
    side = "<h4>How it ranks</h4><p class=\"muted\">BM25 on page sections. Words in a title or heading count more. " \
           "Glossary synonyms are added. Pages with a secret, and anything pending or in feedback, are never searched.</p>"
    if rep is not None:
        side += '<h4>Index</h4><table><tr><td class="muted">Engine</td><td>%s%s</td></tr><tr><td class="muted">Re-indexed now</td><td>%d page%s</td></tr></table>' % (
            esc(rep["engine"]), " + vectors" if rep["hybrid"] else "", rep["index"]["indexed"], "" if rep["index"]["indexed"] == 1 else "s")
    return page(ctx, "Search", "/search", "".join(body), flash, error, left=left_side(p, facets, total_pages), right=C.right_pane(side))


SCREENS = {"/search": search_view}
ACTIONS = {}
NAV = [("/search", "Search")]
