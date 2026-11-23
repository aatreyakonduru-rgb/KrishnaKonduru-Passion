"""Golden questions screen for Metis UI.

Path /golden, nav label "Golden questions".
Lists the golden set (golden.py), adds a question through golden.add (leads only), and runs the set through golden.py.
golden.py has no remove function and does not store results, so this page has no Remove button and keeps no score.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
for _p in (TOOLS, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import urllib.parse  # noqa: E402

import golden  # noqa: E402
import kb_gate  # noqa: E402
import ui_common as C  # noqa: E402
from ui_common import esc, field, form, page  # noqa: E402

SEEN = {}  # kb -> {question id: result} of the latest run; in memory for this server run only, used for the Last and Change columns


def need_user(ctx):
    if not C.clean(ctx.user):
        raise C.UiError("Say who you are first (top right, 'You are'). Your name goes on every approval, rating and answer.")
    return C.clean(ctx.user)


def lines(text):
    return [x.strip() for x in str(text or "").replace(",", "\n").splitlines() if x.strip()]


def page_link(kb, p):
    if os.path.isfile(os.path.join(kb, p)):
        return '<a href="/files?page=%s">%s</a>' % (esc(p), esc(p))
    return '<span class="no">%s (missing)</span>' % esc(p)


def run_results(ctx, q):
    """What golden.py does: static (no model) always; score only when an answers folder inside the KB is named."""
    rows = {g["id"]: {"result": "pass", "why": []} for g in golden.load(ctx.kb).get("golden") or []}
    for line in golden.static(ctx.kb):
        gid, _, why = line.partition(": ")
        if gid in rows:
            rows[gid] = {"result": "fail", "why": [why]}
    mode = "static"
    ans = C.clean(q.get("answers"))
    if ans:
        full = os.path.abspath(os.path.join(ctx.kb, ans))
        if os.path.commonpath([full, ctx.kb]) != ctx.kb or not os.path.isdir(full):
            raise C.UiError("The answers folder must be a folder inside the KB.")
        rows = {r["id"]: r for r in golden.score(ctx.kb, full)}
        mode = "score"
    return mode, rows


def result_pill(result):
    return '<span class="pill %s">%s</span>' % ("ok" if result == "pass" else "no", esc(result)) if result else '<span class="muted">-</span>'


def change_pill(now, before):
    """Compare this run with the run before it (kept in memory for this server run only)."""
    if not now or not before:
        return '<span class="muted">-</span>'
    if now == before:
        return '<span class="muted">same</span>'
    if now == "pass":
        return '<span class="pill ok">fixed</span>'
    return '<span class="pill warn">got worse</span>' if before == "pass" else '<span class="pill warn">changed</span>'


def left_side(data, results, sel):
    """Question sets by kind, with the pass rate of the latest run when there is one."""
    kinds = []
    for g in data:
        k = g.get("kind") or "golden"
        if k not in kinds:
            kinds.append(k)
    items = []
    for key, label in [("", "All questions")] + [(k, k) for k in kinds]:
        ids = [g.get("id", "") for g in data if not key or (g.get("kind") or "golden") == key]
        rated = [results[i] for i in ids if i in results]
        sub = "%d question%s &middot; " % (len(ids), "" if len(ids) == 1 else "s")
        sub += "%d%% pass" % (100 * rated.count("pass") // len(rated)) if rated else "not yet run"
        items.append(C.pane_item("/golden?set=%s" % urllib.parse.quote(key), esc(label), sub, on=(key == sel)))
    return C.left_pane("Question sets", "".join(items), len(data))


def right_side(ctx, data, results, sel, kinds_note):
    ok = sum(r["result"] == "pass" for r in results.values())
    out = '<h4>Test suite</h4><div class="grid"><div class="card"><div class="stat">%d</div><span class="muted">questions</span></div>' % len(data)
    if results:
        out += ('<div class="card"><div class="stat">%d%%</div><span class="muted">pass, this run</span></div>'
                '<div class="card"><div class="stat">%d</div><span class="muted">pass</span></div>'
                '<div class="card"><div class="stat">%d</div><span class="muted">not passing</span></div>' % (
                    100 * ok // len(results) if results else 0, ok, len(results) - ok))
    else:
        out += '<div class="card"><div class="stat">-</div><span class="muted">not yet run</span></div>'
    out += "</div>%s" % kinds_note
    run_body = (field("answers", "Answers folder (optional)", "",
                      hint="a folder inside the KB with G-0001.md, G-0002.md, ... written by Metis; leave empty for the static check") +
                '<input type="hidden" name="run" value="1"><input type="hidden" name="set" value="%s">'
                '<p><button>Run the set</button></p>' % esc(sel))
    out += "<h4>Run the set</h4>" + form(ctx, "/golden", run_body, method="get")
    out += ('<h4>Help</h4><div class="muted">The static check only confirms that each KB file a question relies on still exists. '
            "Give an answers folder to score the answers against the expected pages and words.</div>")
    return out


def golden_view(ctx, q, flash=None, error=None):
    data = golden.load(ctx.kb).get("golden") or []
    leads = kb_gate.certifiers(ctx.kb)
    lead_names = ", ".join(v[0] for v in leads.values()) or "nobody is named yet (Setup: KB owner and lead roles)"
    results, summary, mode, before = {}, "", "", {}
    if q.get("run") and not error:
        try:
            mode, results = run_results(ctx, q)
            before = SEEN.get(ctx.kb, {})
            SEEN[ctx.kb] = {k: v["result"] for k, v in results.items()}
            ok = sum(r["result"] == "pass" for r in results.values())
            what = ("Scored the answers in %s" % q.get("answers")) if mode == "score" else \
                "Static check only: every KB file a question relies on still exists. No answers were scored"
            summary = ('<div class="card"><h3 style="margin-top:0">%s</h3><p>%s. %d of %d pass. '
                       '<span class="muted">This result is not stored on disk; the server keeps it in memory to show what changed '
                       "at the next run.</span></p></div>" % ("Result", esc(what), ok, len(results)))
        except C.UiError as err:
            error = str(err)

    sel = C.clean(q.get("set"))
    shown = [g for g in data if not sel or (g.get("kind") or "golden") == sel]
    body = [
        "<h1>Golden questions</h1>",
        '<p class="lead">Questions the KB must keep answering well. Each names the KB files a good answer cites and words it must '
        "contain. Only leads add to the set (leads: %s).</p>" % esc(lead_names),
        '<p class="muted">golden.py has no remove command, so questions cannot be removed here. It stores no score: '
        "a run is shown once and is not kept.</p>",
    ]
    body.append(summary)

    body.append("<h2>Questions (%d)</h2>" % len(shown))
    if not data:
        body.append('<div class="card soft">No golden questions yet. Add the first one below.</div>')
    elif not shown:
        body.append('<div class="card soft">No question in this set. <a href="/golden">Show all</a>.</div>')
    rows = []
    for g in shown:
        gid = g.get("id", "")
        res = results.get(gid)
        why = "".join("<li>%s</li>" % esc(w) for w in (res or {}).get("why") or [])
        cites = ", ".join(page_link(ctx.kb, c) for c in g.get("cite") or []) or '<span class="muted">(none)</span>'
        inc = " ".join('<span class="pill">%s</span>' % esc(w) for w in g.get("include") or []) or '<span class="muted">(none)</span>'
        src = " &middot; from feedback %s" % esc(g["from_feedback"]) if g.get("from_feedback") else ""
        now = res["result"] if res else ""
        rows.append(
            "<tr><td><b>%s</b><br><span class=\"pill\">%s</span></td><td>%s%s<p class=\"muted\"><small>Added by %s (%s) on %s%s</small></p></td>"
            "<td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                esc(gid), esc(g.get("kind", "")), esc(g.get("question", "")), "<ul>%s</ul>" % why if why else "",
                esc(g.get("added_by", "unknown")), esc(g.get("role", "")), esc(g.get("added_on", "unknown")), src,
                cites, inc, result_pill(now), result_pill(before.get(gid, "")), change_pill(now, before.get(gid, ""))))
    if rows:
        body.append("<table><tr><th>ID</th><th>Question</th><th>Expected KB pages</th><th>Must contain</th><th>Now</th><th>Last</th>"
                    "<th>Change</th></tr>%s</table>" % "".join(rows))
        if results and any(r["result"] != "pass" for r in results.values()):
            body.append('<div class="card soft">Some questions are not passing. Look before approving a refresh.</div>')

    add_body = (field("question", "Question", "", kind="textarea", rows=2, required=True) +
                field("cite", "Expected KB pages", "", hint="one or more KB paths, comma separated, e.g. context/rules.md", required=True) +
                field("include", "Facts the answer must contain", "", hint="optional, comma separated words or numbers") +
                '<label for="kind">Kind</label><select id="kind" name="kind"><option value="golden">golden</option>'
                '<option value="competency">competency</option></select>'
                "<p><button>Add question</button></p>")
    body.append('<div class="card"><h2 style="margin-top:0">Add a golden question</h2>'
                '<p class="muted">Added by: %s. Only a named lead may add.</p>%s</div>' % (
                    esc(C.clean(ctx.user) or "(say who you are first)"), form(ctx, "/golden/add", add_body)))
    kinds = {}
    for g in data:
        kinds[g.get("kind") or "golden"] = kinds.get(g.get("kind") or "golden", 0) + 1
    kinds_note = ('<p class="muted"><small>%s</small></p>' % esc(", ".join("%s: %d" % kv for kv in kinds.items()))) if kinds else ""
    return page(ctx, "Golden questions", "/golden", "".join(body), flash, error,
                left=left_side(data, SEEN.get(ctx.kb, {}), sel), right=C.right_pane(right_side(ctx, data, results, sel, kinds_note)))


def act_golden_add(ctx, f):
    by = need_user(ctx)
    kind = f.get("kind") or "golden"
    if kind not in ("golden", "competency"):
        raise C.UiError("Kind must be golden or competency.")
    try:
        g = golden.add(ctx.kb, f.get("question", ""), lines(f.get("cite")), lines(f.get("include")), by, kind)
    except (golden.GoldenError, kb_gate.GateError) as err:
        raise C.UiError(str(err))
    return "/golden", "Added %s to the golden set." % g["id"]


SCREENS = {"/golden": golden_view}
ACTIONS = {"/golden/add": ("/golden", act_golden_add)}
NAV = [("/golden", "Golden questions")]
