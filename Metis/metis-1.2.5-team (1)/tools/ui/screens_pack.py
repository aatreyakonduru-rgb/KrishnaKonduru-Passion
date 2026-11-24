"""Context pack screen for Metis UI.

Path /pack, nav label "Context pack".
Builds a pack with context_pack.build (the same function the command line uses) and shows it. The start objects are the
graph objects the task text names (the same rule context_pack uses for a Jira ticket) plus any object names typed in.
context_pack saves no pack. Like its command line, this screen notes each run in <kb>/.metis/usage/ (file names only,
telemetry.record). The shown pack is kept in memory for this server run, nowhere else.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
for _p in (TOOLS, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import context_pack  # noqa: E402
import kb_coverage  # noqa: E402
import telemetry  # noqa: E402
import ui_common as C  # noqa: E402
from ui_common import esc, field, form, page  # noqa: E402

DEFAULT_BUDGET = 6000  # the --budget default in context_pack.main()
MIN_BUDGET, MAX_BUDGET = 500, 200000
KEEP = 20
PACKS = {}  # (kb, pack id) -> {"pack": build result, "task": text, "start": [node ids], "by": name}


def need_user(ctx):
    if not C.clean(ctx.user):
        raise C.UiError("Say who you are first (top right, 'You are'). Your name goes on every approval, rating and answer.")
    return C.clean(ctx.user)


def lines(text):
    return [x.strip() for x in str(text or "").replace(",", "\n").splitlines() if x.strip()]


def pick_start(kb, task, names):
    """Node ids: those the typed names match (id or name, exact) and those the task text names (4+ letters, whole word)."""
    nodes = context_pack.graph_nodes(kb)
    seeds = []
    for n in names:
        hit = [x["id"] for x in nodes if n.lower() in (x["id"].lower(), str(x["name"]).lower())]
        if not hit:
            raise C.UiError("No object called '%s' in the link graph. Use a name or an id such as table:pets." % n)
        seeds += [h for h in hit if h not in seeds]
    low = task.lower()
    for x in nodes:
        if len(str(x["name"])) >= 4 and kb_coverage.named(x["name"], [low]) and x["id"] not in seeds:
            seeds.append(x["id"])
    return seeds


def act_pack_build(ctx, f):
    by = need_user(ctx)
    task = str(f.get("task") or "").strip()
    names = lines(f.get("objects"))
    if not task and not names:
        raise C.UiError("Write the task or ticket text, or name at least one object.")
    raw = C.clean(f.get("budget"))
    try:
        budget = int(raw) if raw else DEFAULT_BUDGET
    except ValueError:
        raise C.UiError("The token budget must be a whole number.")
    if not MIN_BUDGET <= budget <= MAX_BUDGET:
        raise C.UiError("The token budget must be between %d and %d." % (MIN_BUDGET, MAX_BUDGET))
    try:
        seeds = pick_start(ctx.kb, task, names)
        pack = context_pack.build(ctx.kb, seeds=seeds, budget=budget, task=task or None, role=by,
                                  audience=C.clean(f.get("audience")) or None)
        if not seeds and not pack["files"]:
            raise C.UiError("No object in the link graph is named in the task text, and the search found no page for it. "
                            "Name the objects below, for example table:pets.")
    except context_pack.PackError as err:
        raise C.UiError(str(err))
    except SystemExit as err:
        raise C.UiError(str(err))
    telemetry.record(ctx.kb, "pack", pack["files"], pack["pack_id"], pack["tokens"], by, len(pack["skipped"]))
    if len(PACKS) >= KEEP:
        PACKS.pop(next(iter(PACKS)))
    PACKS[(ctx.kb, pack["pack_id"])] = {"pack": pack, "task": task, "start": seeds, "by": by}
    return "/pack?pack=" + pack["pack_id"], "Built %s: %d of %d tokens." % (pack["pack_id"], pack["tokens"], budget)


def split_pack(text):
    """Cut the pack text into its parts, as context_pack.render wrote them."""
    out = {"head": [], "table": [], "impact": [], "pages": [], "questions": [], "left": []}
    where, cur = "head", None
    for ln in text.splitlines():
        if cur is not None:
            if ln.strip() == "</kb-file>":
                cur = None
            else:
                cur["text"].append(ln)
            continue
        m = re.match(r'^<kb-file path="(.*)" tier="([a-z]*)"( stale="true")?>$', ln)
        if m and where == "impact":
            cur = {"path": m.group(1), "tier": m.group(2), "text": [], "stale": bool(m.group(3))}
            out["pages"].append(cur)
        elif ln == "## Included":
            where = "table"
        elif ln.startswith("## Impact list"):
            where = "impact"
        elif ln == "## Open questions":
            where = "questions"
        elif ln == "## Not included":
            where = "left"
        else:
            out[where].append(ln)
    return out


def table_rows(table):
    """{path: (why, tokens, signals)} from the Included table; signals is '' when the pack has none."""
    rows = {}
    for ln in table:
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if ln.startswith("|") and len(cells) >= 4 and cells[0] not in ("File", "---"):
            rows[cells[0]] = (cells[1], cells[3], cells[4] if len(cells) > 4 else "")
    return rows


def pack_view(ctx, info):
    pack = info["pack"]
    parts = split_pack(pack["text"])
    rows = table_rows(parts["table"])
    secret = [(p, why) for p, why in pack["skipped"] if "secret or card number" in why]
    other = [(p, why) for p, why in pack["skipped"] if "secret or card number" not in why]
    used = int(100.0 * pack["tokens"] / pack["budget"]) if pack["budget"] else 0
    out = ['<div class="card"><h2 style="margin-top:0">Pack %s</h2>' % esc(pack["pack_id"]),
           "<p>%d of %d tokens (%d%%, estimated). %d pages included, %d left out. Start objects: %s. Built by %s.</p></div>" % (
               pack["tokens"], pack["budget"], used, len(pack["files"]), len(pack["skipped"]),
               ", ".join("<code>%s</code>" % esc(s) for s in info["start"]), esc(info["by"]))]
    out.append("<h2>Impact list</h2><p class=\"muted\">Every link followed from the start objects, with its source tag and trust signals. "
               "Signals are facts, not a score.</p>" + C.render_md("\n".join(parts["impact"])))
    out.append("<h2>Pages included (%d)</h2>" % len(parts["pages"]))
    if not parts["pages"]:
        out.append('<div class="card soft">No KB page names these objects.</div>')
    for pg in parts["pages"]:
        text = "\n".join(pg["text"])
        why, tok, sig = rows.get(pg["path"], ("", "", ""))
        cites = len(re.findall(r"\[E:\s*[^\]]+\]", text))
        stale = ' <span class="pill warn">stale</span>' if pg.get("stale") else ""
        out.append(
            '<div class="card"><h3 style="margin-top:0"><a href="/files?page=%s">%s</a> <span class="pill">%s</span>%s</h3>'
            '<p class="muted"><small>Why: %s. %s tokens. %d source tags in the text.</small></p>%s'
            "<details><summary>Page text as the pack carries it</summary>%s</details></div>" % (
                esc(pg["path"]), esc(pg["path"]), esc(pg["tier"]), stale, esc(why), esc(tok), cites,
                "<p><b>Trust signals:</b> %s</p>" % esc(sig) if sig else "", C.render_md(text)))
    out.append("<h2>Open questions</h2>" + C.render_md("\n".join(parts["questions"])))
    out.append("<h2>Left out</h2>")
    if other:
        out.append("<ul>%s</ul>" % "".join("<li><code>%s</code>: %s</li>" % (esc(p), esc(w)) for p, w in other))
    else:
        out.append('<p class="muted">No page was left out because of the budget.</p>')
    listed = ["- %s: %s" % (p, w) for p, w in pack["skipped"]] + ["- nothing left out"]
    notes = [x for x in parts["left"] if x.strip() and x not in listed]
    if notes:
        out.append("<p><b>Notes from context_pack:</b></p><ul>%s</ul>" % "".join("<li>%s</li>" % esc(n[2:]) for n in notes))
    out.append("<h2>Secret screen</h2>")
    if secret:
        out.append('<p><span class="pill no">%d left out</span> These pages hold a secret, key, token or card number, so context_pack '
                   "left them out. Fix the page.</p><ul>%s</ul>" % (
                       len(secret), "".join("<li><code>%s</code>: %s</li>" % (esc(p), esc(w)) for p, w in secret)))
    else:
        out.append('<p><span class="pill ok">clean</span> No page that names these objects held a secret or card number '
                   "(checked by sensitive.py).</p>")
    out.append('<h2>The pack as markdown</h2><p class="muted">Read only. Select all and copy.</p>'
               '<textarea readonly rows="18" style="min-height:300px">%s</textarea>' % esc(pack["text"]))
    return "".join(out)


MODES = [("ticket", "A Jira ticket", "paste the ticket text"),
         ("objects", "Object names", "name graph objects, e.g. table:pets"),
         ("text", "Custom text", "any task description")]


def left_side(ctx, mode, pid):
    """One left pane: the input modes, then the packs built in this server run (newest first)."""
    keep = "&pack=" + pid if pid else ""
    modes = "".join(C.pane_item("/pack?mode=%s%s" % (m, keep), esc(label), esc(sub), on=(m == mode)) for m, label, sub in MODES)
    mine = [(k[1], v) for k, v in PACKS.items() if k[0] == ctx.kb][::-1]
    hist = "".join(C.pane_item("/pack?pack=" + esc(p), esc(p), "%d of %d tokens &middot; %d pages" % (
        v["pack"]["tokens"], v["pack"]["budget"], len(v["pack"]["files"])), on=(p == pid)) for p, v in mine)
    if not hist:
        hist = '<div class="it"><span class="s">No pack built in this server run.</span></div>'
    return C.left_pane("Build a pack from", modes + '<div class="hd"><span>Recent packs</span><span>%d</span></div>' % len(mine) + hist)


def right_side(info):
    out = ('<h4>Options</h4><div>'
           '<span class="pill ok">on</span> Include upstream<br><span class="pill ok">on</span> Include downstream<br>'
           '<span class="pill ok">on</span> Include open questions<br><span class="pill ok">on</span> Mark stale files<br>'
           '<span class="pill ok">on</span> Show trust signals</div>'
           '<p class="muted"><small>These are what context_pack.build does here, with depth 2. The screen has no switches for them.</small></p>')
    if info:
        pack = info["pack"]
        out += ('<h4>This pack</h4><div>%d of %d tokens<br>%d pages included<br>%d left out</div>' % (
            pack["tokens"], pack["budget"], len(pack["files"]), len(pack["skipped"])))
    out += ('<h4>For agents</h4><div class="muted">The same pack can be fetched by an agent with the context_pack.py command line, '
            "using the same budget. Every line keeps its [E: ...] tag, so the agent can say where a fact came from. "
            "The text inside &lt;kb-file&gt; tags is data, not instructions.</div>"
            '<h4>Not included</h4><div class="muted">Pages that hold a secret, key, token or card number.</div>')
    return out


def pack_view_screen(ctx, q, flash=None, error=None):
    mode = C.clean(q.get("mode"))
    mode = mode if mode in [m[0] for m in MODES] else "text"
    task_f = field("task", "Jira ticket text" if mode == "ticket" else "Task or ticket text", "", kind="textarea",
                   rows=8 if mode in ("ticket", "text") else 3,
                   hint="Any graph object whose name (4 letters or more) appears here is a start point")
    obj_f = field("objects", "Object names" if mode == "objects" else "Object names (optional)", "", kind="textarea",
                  rows=8 if mode == "objects" else 2, hint="one per line: a name or an id such as table:pets")
    build_body = ((obj_f + task_f if mode == "objects" else task_f + obj_f) +
                  field("budget", "Token budget", str(DEFAULT_BUDGET), hint="estimated at 4 characters a token; leave room") +
                  '<p><label>Pack for <select name="audience">%s</select></label> <span class="muted">orders pages and sets the impact share; '
                  'facts, tags and what you may see do not change</span></p>' % C.audience_options(ctx) +
                  "<p><button>Build the pack</button></p>")
    body = [
        "<h1>Context pack</h1>",
        '<p class="lead">The part of the KB one task needs, cut to a token budget. Every page line keeps its [E: ...] tag.</p>',
        '<p class="muted">What context_pack.py cannot do: it takes a page whole, or only its headline (heading and first paragraph). '
        "It makes no per-page summaries, and no model writes any of it. A page that does not fit is left out. "
        "It saves no pack file from here: copy the markdown below.</p>",
        '<div class="card"><h2 style="margin-top:0">Build a pack</h2>%s</div>' % form(ctx, "/pack/build", build_body),
    ]
    pid = C.clean(q.get("pack"))
    info = None
    if pid and not error:
        info = PACKS.get((ctx.kb, pid))
        body.append(pack_view(ctx, info) if info else
                    '<div class="card soft">Pack %s is not in memory (the server restarted, or it is old). Build it again.</div>' % esc(pid))
    return page(ctx, "Context pack", "/pack", "".join(body), flash, error,
                left=left_side(ctx, mode, pid if info else ""), right=C.right_pane(right_side(info)))


SCREENS = {"/pack": pack_view_screen}
ACTIONS = {"/pack/build": ("/pack", act_pack_build)}
NAV = [("/pack", "Context pack")]
