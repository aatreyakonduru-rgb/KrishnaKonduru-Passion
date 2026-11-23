"""Review queue with trust signals: what waits for certification, one section per owning team, riskiest first.

Reads the queue from review_queue.py and the raw trust signals from trust.py; writes the per-team plan through review_queue.plan,
certifies through review_queue.certify_team (or kb_gate.certify when an item was rejected) and rejects through kb_gate.reject.
Only a named lead (kb_gate.who) may do any of these. "Approve with sampling" keeps its state in <KB>/.metis/review/<team>.yaml
and writes nothing else of its own.
"""
import datetime
import difflib
import hashlib
import math
import os
import secrets
import sys
import urllib.parse

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import ui_common as C  # noqa: E402
from ui_common import esc, form, pill, page  # noqa: E402
import builds  # noqa: E402
import gen_graph  # noqa: E402
import kb_gate  # noqa: E402
import review_queue  # noqa: E402
import trust  # noqa: E402

THRESHOLD = 10   # a team batch with more items than this is approved with sampling
MIN_SAMPLE = 5   # the random part of the sample is at least this many items
SHARE = 0.2      # ... or this share of the batch, whichever is more

ORIGIN = {"parsed": "parsed: a program read it from the source", "catalogue": "from the database catalogue",
          "ai-proposed": "AI-proposed: a model or a person wrote it; no program read it"}
QUOTE = {"verified": "every quote is found in its source", "resolves, no quote": "source resolves, but a tag quotes nothing",
         "no source tag": "no source tag", "does not resolve": "a source does not resolve"}
SOURCE = {"changed since build": "source file changed since the last build",
          "cannot compare": "cannot compare with the last build (no recorded commit or no clone)",
          "unchanged since build": "source files unchanged since the last build"}


# ---- the queue and its files -----------------------------------------------------------------
def key(r):
    return "%s/%s" % (r["batch"], r["file"])


def pending_path(kb, r):
    return os.path.join(kb_gate.pending_dir(kb, r["batch"]), r["file"] + (".DELETE" if r["action"] == "remove" else ""))


def groups(kb):
    return review_queue.queue(kb)["teams"]


def group_of(kb, team):
    g = next((g for g in groups(kb) if g["team"] == team), None)
    if not g:
        raise C.UiError("Nothing is waiting for %s." % (C.clean(team) or "(no team)"))
    return g


def items_of(kb, g):
    """{batch/file: hash of the pending file}: what the sample and the reviewed marks are tied to."""
    return {key(r): kb_gate.sha_file(pending_path(kb, r)) for r in g["files"]}


def lead(ctx):
    if not C.clean(ctx.user):
        raise C.UiError("Say who you are first (top right, 'You are'). Your name goes on every approval, rating and answer.")
    try:
        return kb_gate.who(ctx.kb, ctx.user)[0]
    except kb_gate.GateError as err:
        raise C.UiError("Only a named lead can do this. %s" % err)


# ---- trust signals -----------------------------------------------------------------------------
def _list(x):
    return x if isinstance(x, list) else [] if x is None else [x]


def signals(kb, tr, r):
    """Raw signals for one waiting file, from trust.py. A link file gets one reading per link; any other file one reading of its
    source tags. trust.page needs the file to be in the KB already, so a waiting file is read through trust.edge instead."""
    rel = r["file"]
    s = {"origin": None, "links": None, "quote": {}, "source": {}, "bad": None, "known": tr.changed is not None,
         "blocked": ["%s (%s)" % (q.get("id"), q.get("priority")) for q in tr.open_q if rel in _list(q.get("blocks"))]}
    if r["action"] == "remove":
        return s
    text = kb_gate.read_text(pending_path(kb, r))
    reads = [tr.edge(None, text)]
    if rel.endswith(".links.yaml"):
        s["origin"] = gen_graph.origin_of(rel)
        try:
            links = [x for x in (yaml.safe_load(text) or {}).get("links") or [] if isinstance(x, dict)]
        except (yaml.YAMLError, AttributeError):
            links = []
        if links:
            s["links"] = len(links)
            reads = [tr.edge(s["origin"], x.get("source")) for x in links]
    for g in reads:
        k = "does not resolve" if g["quote"].startswith("does not resolve") else g["quote"]
        s["quote"][k] = s["quote"].get(k, 0) + 1
        if k == "does not resolve" and not s["bad"]:
            s["bad"] = g["quote"].partition(": ")[2]
        if g.get("source"):
            s["source"][g["source"]] = s["source"].get(g["source"], 0) + 1
    return s


def forced(s):
    """Why an item is always in the sample."""
    return (["blocked by open question " + ", ".join(s["blocked"])] if s["blocked"] else []) + (["AI-proposed"] if s["origin"] == "ai-proposed" else [])


def signal_lines(s, r):
    if s["origin"]:
        origin = ORIGIN.get(s["origin"], s["origin"])
    elif r["action"] == "remove":
        origin = "removes a certified file; no origin to show"
    else:
        origin = "a page: the KB does not record who wrote a page"

    def counted(d, words, extra=""):
        out = []
        for k, n in sorted(d.items(), key=lambda x: (-x[1], x[0])):
            w = words[k] + (" (%s)" % extra if k == "does not resolve" and extra else "")
            out.append(("%d of %d links: " % (n, s["links"]) if s["links"] else "") + w)
        return "; ".join(out)

    lines = [origin]
    if r["action"] == "remove":
        return lines + ["blocked by open question " + ", ".join(s["blocked"]) if s["blocked"] else "no open question blocks it"]
    lines.append(counted(s["quote"], QUOTE, s["bad"]))
    lines.append(counted(s["source"], SOURCE) if s["source"] else "change since the last build not known" if not s["known"]
                 else "no cited repository file could be compared with the last build")
    lines.append("blocked by open question " + ", ".join(s["blocked"]) if s["blocked"] else "no open question blocks it")
    return lines


# ---- sampling ----------------------------------------------------------------------------------
def state_path(kb, team):
    return os.path.join(kb, ".metis", "review", kb_gate.slug(team) + ".yaml")


def load_state(kb, team):
    return C.load_yaml(state_path(kb, team))


def usable(state, items):
    """A sample counts only while the batch is exactly what it was when the sample was drawn."""
    return bool(state) and state.get("items") == items


def valid(state, items, field):
    """Keys marked in this field of the state whose file is still the one that was marked."""
    return {k for k, v in ((state or {}).get(field) or {}).items() if k in items and isinstance(v, dict) and v.get("sha") == items[k]}


def pick(candidates, seed, n):
    """The random part of a sample: rank every candidate by sha256(seed|key) and take the first n. The same seed and the same
    candidates give the same sample on any machine."""
    return sorted(candidates, key=lambda k: hashlib.sha256(("%s|%s" % (seed, k)).encode("utf-8")).hexdigest())[:n]


def random_share(total):
    return max(MIN_SAMPLE, math.ceil(SHARE * total))


def draw_size(kb, total, who, team):
    """The size of the random draw: the standard number, shortened only by review.trust.sample_share for a reviewer with enough
    history in this team's area, and never below the floor (review_queue.sample_size). Without that policy it is random_share."""
    area = None if team == kb_gate.UNASSIGNED else team
    try:
        return review_queue.sample_size(kb, total, C.clean(who), area, base=random_share(total))
    except Exception:
        n = min(total, random_share(total))
        return {"size": n, "base": n, "floor": n, "reduced": False, "reason": ""}


def readiness(items, state, sigs):
    """(reasons certification must wait, keys that must be marked reviewed, keys rejected). Rejected items are never certified."""
    rejected = valid(state, items, "rejected")
    if len(items) <= THRESHOLD:
        return [], set(), rejected
    if not usable(state, items):
        return ["draw the sample first" if not state else "the batch changed since the sample was drawn; draw a new sample"], set(), rejected
    required = (set(items) if rejected else set(state.get("sample") or {}) | {k for k, s in sigs.items() if forced(s)}) - rejected
    todo = required - valid(state, items, "reviewed")
    return (["%d of %d required items are not marked reviewed" % (len(todo), len(required))] if todo else []), required, rejected


def save_state(kb, state):
    C.dump_yaml(state_path(kb, state["team"]), state, "# Written by the Metis UI (Review queue). The sample for one team's batch; the seed makes the draw repeatable.\n")


# ---- screens -----------------------------------------------------------------------------------
def anchor(team):
    return "team-" + kb_gate.slug(team)


def why_it_ranks(r):
    w = ["%s (%s)" % (f["kind"], f["level"]) for f in r["findings"][:3]]
    if r["problems"]:
        w.append("%d source problems" % len(r["problems"]))
    if r["action"] == "remove":
        w.append("removes a certified file")
    return "; ".join(w) or "nothing found"


def item_url(team, r):
    return "/review?" + urllib.parse.urlencode({"team": team, "batch": r["batch"], "file": r["file"]})


def review(ctx, q, flash=None, error=None):
    if q.get("file"):
        return item_view(ctx, q, flash, error)
    kb = ctx.kb
    leads = kb_gate.certifiers(kb)
    me = C.clean(ctx.user).lower()
    names = ", ".join(v[0] for v in leads.values()) or "nobody is named yet (Setup: KB owner and lead roles)"
    body = ['<h1>Review queue</h1><p class="lead">What waits for certification, by the team that owns it, riskiest first. '
            'The signals are facts read from the KB, the sources and the open questions. They are not a score.</p>',
            '<p>%s <span class="muted">Leads: %s.</span></p>' % (
                pill(me in leads, "you are a lead (%s)" % leads[me][1] if me in leads else "", "you are not a lead" if ctx.user else "set your name top right", True), esc(names))]
    if not kb_gate.is_locked(kb):
        body.append('<div class="card soft">The KB is not locked yet, so nothing is staged for review. Lock it on <a href="/approve">Approve</a>.</div>')
        return page(ctx, "Review queue", "/review", "".join(body), flash, error)
    tr = trust.Trust(kb)
    for n in tr.notes:
        body.append('<p class="muted">Note: %s</p>' % esc(n))
    routes = route_map(kb, tr)
    teams = kb_gate.teams(kb)
    if not teams:
        body.append('<div class="card soft">The profile lists no teams (gate.teams), so everything waits for the leads in one group.</div>')
    by_team = {g["team"]: g for g in groups(kb)}
    for name in [t["name"] for t in teams] + [kb_gate.UNASSIGNED]:
        if name in by_team:
            body.append(team_section(ctx, by_team[name], tr, q, routes))
        elif name != kb_gate.UNASSIGNED:
            body.append('<h2 id="%s">%s</h2><p class="muted">Nothing is waiting.</p>' % (anchor(name), esc(name)))
    if not by_team:
        body.append('<div class="card soft">Nothing waits for review.</div>')
    return page(ctx, "Review queue", "/review", "".join(body), flash, error)


def route_map(kb, tr):
    """{batch/file: routing entry} from review_queue.route: who to ask and the 'suitable for sampling' label. Suggestions only."""
    try:
        return {"%s/%s" % (it["batch"], it["file"]): it for it in review_queue.route(kb, tr=tr)["items"]}
    except Exception:
        return {}


def route_html(it):
    """The suggested reviewer(s) and the sampling label for one waiting file, as facts. Nothing here certifies."""
    if not it:
        return ""
    out = []
    if it["suggested"]:
        out.append("Suggested reviewer: " + "; ".join("%s (%s)" % (
            c["name"], ("weight %.3f in %s, %d decisions" % (c["weight"], c["area"], c["decisions"])) if c["weight"] is not None
            else "no weight in %s: %s" % (c["area"], c["status"])) for c in it["suggested"]))
    if it["excluded"]:
        out.append("Not " + "; ".join("%s (%s)" % (x["name"], x["reason"]) for x in it["excluded"]))
    html = "".join('<div class="muted"><small>%s</small></div>' % esc(x) for x in out)
    if it["fast_lane"]:
        html += '<div><span class="pill ok">%s</span> <small class="muted">%s</small></div>' % (esc(it["fast_lane_label"]), esc(it["note"]))
    return html


def team_section(ctx, g, tr, q, routes=None):
    kb, team = ctx.kb, g["team"]
    routes = routes or {}
    sigs = {key(r): signals(kb, tr, r) for r in g["files"]}
    items, state = items_of(kb, g), load_state(kb, g["team"])
    sampling, ok = len(items) > THRESHOLD, usable(state, items)
    why, required, rejected = readiness(items, state, sigs)
    reviewed = valid(state, items, "reviewed")
    out = ['<h2 id="%s">%s <span class="muted">%d items</span></h2><p class="muted">Approvers: %s.</p>' % (
        anchor(team), esc(team), len(items), esc(", ".join(g["approvers"]) or "none named"))]
    if sampling:
        out.append(sampling_card(ctx, g, state, ok, why, required, reviewed, rejected))
    rows = []
    for i, r in enumerate(g["files"], 1):
        k, mark = key(r), (state or {})
        if k in rejected:
            st = '<span class="pill no">problem found</span> <span class="muted">%s: %s</span>' % (esc(mark["rejected"][k].get("by")), esc(mark["rejected"][k].get("note")))
        elif sampling and ok and k in reviewed:
            st = '<span class="pill ok">reviewed</span> <span class="muted">by %s</span>' % esc(mark["reviewed"][k].get("by"))
        elif sampling and ok and k in required:
            st = '<span class="pill warn">must be reviewed</span> <span class="muted">%s</span>' % esc("; ".join(
                (mark.get("sample") or {}).get(k) or forced(sigs[k]) or ["full review"]))
        elif sampling and ok:
            st = '<span class="muted">not in the sample</span>'
        else:
            st = ""
        rows.append('<tr><td>%d</td><td><a href="%s">%s</a><br><span class="muted">batch %s; %s; +%d -%d lines; risk %d</span></td>'
                    '<td class="muted">%s</td><td><ul style="margin:0;padding-left:16px">%s</ul></td><td>%s</td></tr>' % (
                        i, esc(item_url(team, r)), esc(r["file"]), esc(r["batch"]), esc(r["action"]), r["lines_added"], r["lines_removed"], r["risk"],
                        esc(why_it_ranks(r)), "".join("<li>%s</li>" % esc(x) for x in signal_lines(sigs[k], r)) + route_html(routes.get(k)), st))
    out.append('<table><tr><th>#</th><th>File</th><th>Why it ranks here</th><th>Trust signals</th><th>Review</th></tr>%s</table>' % "".join(rows))
    if q.get("plan") == team:
        out.append(plan_card(kb, team, q))
    hid = '<input type="hidden" name="team" value="%s">' % esc(team)
    out.append('<div class="card soft"><div class="row"><div>%s</div><div>%s</div><div>%s</div></div></div>' % (
        form(ctx, "/review/plan", hid + '<p class="muted">Writes the branch name and PR body for each team under _PENDING/_QUEUE.</p>'
             '<button class="alt">Write the plan</button>'),
        form(ctx, "/review/certify", hid + '<input type="text" name="note" placeholder="Why personal-looking data may stay (only if needed)">'
             '<p><button>Certify this team\'s batch as %s</button></p>' % esc(ctx.user or "you")),
        form(ctx, "/review/reject", hid + '<input type="text" name="reason" placeholder="Reason (needed)">'
             '<p><button class="alt bad">Reject this team\'s batch</button></p>')))
    return "".join(out)


def sampling_card(ctx, g, state, ok, why, required, reviewed, rejected):
    team = g["team"]
    n = len(g["files"])
    ss = draw_size(ctx.kb, n, ctx.user, team)
    c = ['<div class="card"><h3 style="margin-top:0">Approve with sampling</h3>'
         '<p>This batch has %d items, more than %d. Before the rest can be certified, a lead opens and marks reviewed: every item blocked '
         'by an open question, every AI-proposed item, and a random draw of %d items (the larger of %d or %d%% of the batch) from the others. '
         'The draw is stored with its seed: items are ranked by sha256 of the seed and the item name, and the first ones are taken.</p>' % (
             n, THRESHOLD, random_share(n), MIN_SAMPLE, round(SHARE * 100))]
    if ss["reduced"]:
        c.append('<p>By the review.trust policy the draw is %d items for %s: %s. The floor is %d items. Certifying still takes a named lead.</p>' % (
            ss["size"], esc(C.clean(ctx.user)), esc(ss["reason"]), ss["floor"]))
    if not ok:
        c.append('<p>%s</p>%s' % (esc(why[0]), form(ctx, "/review/draw", '<input type="hidden" name="team" value="%s"><button>Draw the sample</button>' % esc(team))))
    else:
        c.append('<p>Seed %s, drawn by %s on %s. %d of %d required items are marked reviewed.</p>' % (
            esc(state["seed"]), esc(state.get("drawn_by")), esc(state.get("drawn_on")), len(required & reviewed), len(required)))
    if rejected:
        c.append('<p class="no"><b>A problem was found in %d item(s).</b> The whole batch needs a full review: every other item must be opened and '
                 'marked reviewed before the batch is certified. Rejected items are not certified.</p>' % len(rejected))
    if ok and why:
        c.append('<p class="warn">Not ready to certify: %s.</p>' % esc(why[0]))
    c.append("</div>")
    return "".join(c)


def plan_card(kb, team, q):
    try:
        date = datetime.date.fromisoformat(q.get("date", "")).isoformat()
    except ValueError:
        date = C.today()
    p = os.path.join(kb_gate.pending_dir(kb), review_queue.QUEUE_DIR, kb_gate.slug(team) + ".md")
    if not os.path.isfile(p):
        return ""
    return ('<div class="card"><h3 style="margin-top:0">Plan for %s</h3><p><b>Mētis does not run git or open a pull request.</b> Create this branch, '
            'put the files in it, and open the PR yourself with the text below. Mētis never merges.</p>'
            '<label>Branch name</label><input type="text" readonly value="%s" onclick="this.select()">'
            '<label>PR body</label><textarea readonly rows="12" onclick="this.select()">%s</textarea></div>') % (
        esc(team), esc(review_queue.branch_name(team, date)), esc(C.read_text(p)))


def item_view(ctx, q, flash=None, error=None):
    kb, team = ctx.kb, q.get("team", "")
    g = group_of(kb, team)
    r = next((x for x in g["files"] if x["batch"] == q.get("batch") and x["file"] == q.get("file")), None)
    if not r:
        raise C.UiError("That item is not waiting in the queue any more.")
    tr = trust.Trust(kb)
    sig = signals(kb, tr, r)
    items, state = items_of(kb, g), load_state(kb, team)
    why, required, rejected = readiness(items, state, {key(r): sig})
    k = key(r)
    if r["action"] == "remove":
        shown = '<p>This removes a certified file. The KB copy now reads:</p><pre>%s</pre>' % esc(C.read_text(os.path.join(kb, r["file"])))
    else:
        text = kb_gate.read_text(pending_path(kb, r))
        old = os.path.join(kb, r["file"])
        diff = ""
        if r["action"] == "change" and os.path.isfile(old):
            diff = "<h3>Changes against the KB copy</h3><pre>%s</pre>" % esc("\n".join(difflib.unified_diff(
                kb_gate.read_text(old).splitlines(), text.splitlines(), "KB copy", "proposed", lineterm="")))
        shown = diff + '<h3>The proposed file</h3><div class="card">%s</div>' % (C.render_md(text) if r["file"].endswith(".md") else "<pre>%s</pre>" % esc(text))
    finds = "".join("<li>%s (%s), line %d</li>" % (esc(f["kind"]), esc(f["level"]), f["line"]) for f in r["findings"])
    probs = "".join("<li>line %s</li>" % esc(p) for p in r["problems"][:10])
    body = ['<p><a href="/review#%s">Review queue</a> / %s</p><h1>%s</h1><p class="muted">Team %s; batch %s; %s; risk %d.</p>' % (
        anchor(team), esc(team), esc(r["file"]), esc(team), esc(r["batch"]), esc(r["action"]), r["risk"]),
        '<div class="card soft"><b>Trust signals</b> <span class="muted">(facts, not a score)</span><ul>%s</ul></div>' % "".join(
            "<li>%s</li>" % esc(x) for x in signal_lines(sig, r))]
    rt = route_html(route_map(kb, tr).get(k))
    if rt:
        body.append('<div class="card soft"><b>Routing</b> <span class="muted">(a suggestion; certifying still takes a named lead)</span>%s</div>' % rt)
    if finds or probs:
        body.append("<div class=\"card\"><b>Findings</b><ul>%s%s</ul></div>" % (finds, probs))
    body.append(shown)
    if len(items) > THRESHOLD and usable(state, items):
        mark = (state.get("reviewed") or {}).get(k) if k in valid(state, items, "reviewed") else None
        bad = (state.get("rejected") or {}).get(k) if k in rejected else None
        status = ("Rejected by %s: %s" % (bad.get("by"), bad.get("note"))) if bad else (
            "Marked reviewed by %s on %s. %s" % (mark.get("by"), mark.get("on"), mark.get("note") or "")) if mark else "Not marked reviewed yet."
        hid = "".join('<input type="hidden" name="%s" value="%s">' % (n, esc(v)) for n, v in (("team", team), ("batch", r["batch"]), ("file", r["file"])))
        body.append('<div class="card"><h3 style="margin-top:0">Sample review</h3><p>%s <span class="muted">%s</span></p>%s</div>' % (
            esc(status), "Required: %s." % esc("; ".join((state.get("sample") or {}).get(k) or forced(sig) or ["full review"])) if k in required else "Not in the sample.",
            form(ctx, "/review/mark", hid + '<label><input type="checkbox" name="read" value="1" style="display:inline"> I opened and read this item. '
                 '(The page cannot check that; your name is recorded.)</label><input type="text" name="note" placeholder="Note (needed if there is a problem)">'
                 '<p><button name="do" value="reviewed">Mark reviewed</button> <button class="alt bad" name="do" value="problem">Problem found: reject this item</button></p>')))
    return page(ctx, r["file"], "/review", "".join(body), flash, error)


# ---- actions -----------------------------------------------------------------------------------
def back(team, msg):
    return "/review#" + anchor(team), msg


def act_plan(ctx, f):
    lead(ctx)
    g = group_of(ctx.kb, f.get("team", ""))
    date = C.today()
    if not any(p["team"] == g["team"] for p in review_queue.plan(ctx.kb, date)):
        raise C.UiError("Nothing is waiting for %s." % g["team"])
    return "/review?%s#%s" % (urllib.parse.urlencode({"plan": g["team"], "date": date}), anchor(g["team"])), "Plan written for %s. Nothing was sent to git." % g["team"]


def act_draw(ctx, f):
    by = lead(ctx)
    g = group_of(ctx.kb, f.get("team", ""))
    items, old = items_of(ctx.kb, g), load_state(ctx.kb, g["team"])
    if len(items) <= THRESHOLD:
        raise C.UiError("%s has %d items. Sampling applies above %d; review them all and certify." % (g["team"], len(items), THRESHOLD))
    if usable(old, items):
        raise C.UiError("A sample is already drawn for this batch (seed %s). It stands; drawing again would let a draw be repeated until it suits." % old["seed"])
    tr = trust.Trust(ctx.kb)
    must = {k: forced(s) for k, s in ((key(r), signals(ctx.kb, tr, r)) for r in g["files"]) if forced(s)}
    rest = [k for k in items if k not in must]
    seed = secrets.randbelow(2 ** 32)
    sample = dict(must)
    sample.update({k: ["random draw"] for k in pick(rest, seed, min(len(rest), draw_size(ctx.kb, len(items), by, g["team"])["size"]))})
    save_state(ctx.kb, {"team": g["team"], "seed": seed, "drawn_by": by, "drawn_on": C.now(), "items": items, "sample": sample,
                        "reviewed": {k: (old or {})["reviewed"][k] for k in valid(old, items, "reviewed")},
                        "rejected": {k: (old or {})["rejected"][k] for k in valid(old, items, "rejected")}})
    return back(g["team"], "Sample drawn for %s: %d of %d items, seed %d." % (g["team"], len(sample), len(items), seed))


def act_mark(ctx, f):
    by = lead(ctx)
    g = group_of(ctx.kb, f.get("team", ""))
    items, state = items_of(ctx.kb, g), load_state(ctx.kb, g["team"])
    k = "%s/%s" % (f.get("batch", ""), f.get("file", ""))
    if k not in items:
        raise C.UiError("That item is not waiting in the queue any more.")
    if not usable(state, items):
        raise C.UiError("Draw the sample for %s first; if one was drawn, the batch has changed since and needs a new one." % g["team"])
    entry = {"sha": items[k], "by": by, "on": C.now(), "note": C.clean(f.get("note"))}
    if f.get("do") == "problem":
        if not entry["note"]:
            raise C.UiError("Say what the problem is.")
        state.setdefault("rejected", {})[k] = entry
        state.setdefault("reviewed", {}).pop(k, None)
        msg = "%s rejected. The whole batch now needs a full review." % k
    else:
        if k in valid(state, items, "rejected"):
            raise C.UiError("This item was rejected for a problem. It stays rejected and is not certified.")
        if not f.get("read"):
            raise C.UiError("Tick the box to say you opened and read this item.")
        state.setdefault("reviewed", {})[k] = entry
        msg = "%s marked reviewed by %s." % (k, by)
    save_state(ctx.kb, state)
    return back(g["team"], msg)


def act_certify(ctx, f):
    by = lead(ctx)
    kb, g = ctx.kb, group_of(ctx.kb, f.get("team", ""))
    items, state = items_of(kb, g), load_state(kb, g["team"])
    tr = trust.Trust(kb)
    why, _, rejected = readiness(items, state, {key(r): signals(kb, tr, r) for r in g["files"]})
    if why:
        raise C.UiError("Not certified: %s." % why[0])
    note = f.get("note") or None
    left = [r for r in g["files"] if key(r) not in rejected]
    try:
        if rejected:
            if not left:
                raise C.UiError("Every item here was rejected. Reject the batch so a corrected one can be proposed.")
            by_batch = {}
            for r in left:
                by_batch.setdefault(r["batch"], []).append(r["file"])
            done = sum(kb_gate.certify(kb, b, by, files, note) for b, files in sorted(by_batch.items()))
        else:
            done = review_queue.certify_team(kb, g["team"], by, note)
    except kb_gate.GateError as err:
        raise C.UiError(str(err))
    msg = "Certified %d files for %s by %s." % (done, g["team"], by)
    for b in sorted({r["batch"] for r in left}):
        if os.path.isdir(kb_gate.pending_dir(kb, b)):
            continue
        for run in builds.runs(kb):
            if run.get("batch") == b and run.get("status") == "waiting for lead":
                builds.after_certification(kb, run["run"])
                msg += " The outputs were rebuilt."
    if state:
        state["certified"] = {"by": by, "on": C.now(), "files": done}
        save_state(kb, state)
    if rejected:
        msg += " %d rejected item(s) still wait in the queue." % len(rejected)
    return back(g["team"], msg)


def act_reject(ctx, f):
    by = lead(ctx)
    kb, g = ctx.kb, group_of(ctx.kb, f.get("team", ""))
    if not C.clean(f.get("reason")):
        raise C.UiError("Say why the batch is rejected.")
    mine = {r["batch"] for r in g["files"]}
    shared = {t["team"] for t in groups(kb) if t["team"] != g["team"] and any(r["batch"] in mine for r in t["files"])}
    if shared:
        raise C.UiError("Not rejected: the batches that hold %s's files also hold files for %s. The tool rejects a whole batch, which would "
                        "reject theirs too. Certify this team's files, or ask for the batches to be split." % (g["team"], ", ".join(sorted(shared))))
    try:
        done = sum(kb_gate.reject(kb, b, by, f["reason"]) for b in sorted(mine))
    except kb_gate.GateError as err:
        raise C.UiError(str(err))
    return back(g["team"], "Rejected %d files for %s." % (done, g["team"]))


SCREENS = {"/review": review}
ACTIONS = {"/review/plan": ("/review", act_plan), "/review/draw": ("/review", act_draw), "/review/mark": ("/review", act_mark),
           "/review/certify": ("/review", act_certify), "/review/reject": ("/review", act_reject)}
NAV = [("/review", "Review queue")]
