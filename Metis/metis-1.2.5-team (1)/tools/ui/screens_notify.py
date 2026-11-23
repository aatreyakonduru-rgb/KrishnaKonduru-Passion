"""Notifications screen for Metis UI.

Path /notify, nav label "Notifications".
Shows the channels in the profile (notify.channels) with whether their environment variable is set, never its value; the events
notify.py would send now; a dry-run test message (anyone); a real send (leads only); the refresh plan from refresh_trigger.py with a
button to compute it and, for leads, to queue the Devin task; and a preview of the Bitbucket PR impact comment.

Nothing here posts to Bitbucket: the PR form is a dry run (bb_pr.comment with post=False). Posting is `bb_pr.py comment --post`.
A real send goes to the webhook or mail host named by the environment variable of the profile, and only because a lead pressed the button.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
for _p in (TOOLS, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import bb_pr  # noqa: E402
import kb_gate  # noqa: E402
import notify  # noqa: E402
import refresh_trigger  # noqa: E402
import ui_common as C  # noqa: E402
from ui_common import esc, field, form, page  # noqa: E402

MAX_EVENTS_SHOWN = 30


def need_user(ctx):
    if not C.clean(ctx.user):
        raise C.UiError("Say who you are first (top right, 'You are'). Your name goes on every approval, rating and answer.")
    return C.clean(ctx.user)


def need_lead(ctx):
    who = need_user(ctx)
    if not kb_gate.certifiers(ctx.kb).get(who.lower()):
        raise C.UiError("%s is not a lead named in the KB profile. Only a lead sends for real or queues a task." % who)
    return who


def is_lead(ctx):
    return bool(C.clean(ctx.user)) and bool(kb_gate.certifiers(ctx.kb).get(C.clean(ctx.user).lower()))


def find(ctx, name):
    ch = next((c for c in notify.channels(ctx.kb) if c["name"] == C.clean(name)), None)
    if not ch:
        raise C.UiError("No channel called %s in the profile (notify.channels)." % C.clean(name))
    return ch


def result_html(r):
    pill = '<span class="pill %s">%s</span>' % ("ok" if r["ok"] else "no", "sent" if r["sent"] else "dry run" if r["dry_run"] and r["ok"] else "not sent")
    return '<p>%s %s</p><pre>%s</pre>' % (pill, esc(r["status"]), esc(r["message"]))


# ---- actions ----------------------------------------------------------------------------------
def act_send(ctx, f):
    """A real send. Leads only. `what` is test (one test message) or events (what the channel has not had yet, as notify.run does)."""
    need_lead(ctx)
    ch = find(ctx, f.get("channel"))
    if ch["problems"]:
        raise C.UiError("The channel settings have problems: " + "; ".join(ch["problems"]))
    if f.get("what") == "events":
        rows = notify.run(ctx.kb, send_for_real=True, only=ch["name"])
        row = rows[0] if rows else {"events": 0, "results": [], "held": ""}
        sent = sum(1 for r in row["results"] if r["sent"])
        bad = [r["status"] for r in row["results"] if not r["ok"]]
        if bad:
            raise C.UiError("Sent %d message(s) to %s, then: %s" % (sent, ch["name"], bad[0]))
        if row["held"]:
            return "/notify", "Held back on %s (%s)." % (ch["name"], row["held"])
        return "/notify", "Sent %d message(s) to %s for %d new event(s)." % (sent, ch["name"], row["events"])
    r = notify.send(ch, notify.test_message(ctx.kb, ch), dry_run=False)
    if not r["ok"]:
        raise C.UiError(r["status"])
    return "/notify", "%s: %s." % (ch["name"], r["status"])


def act_refresh(ctx, f):
    """Compute the refresh plan from what changed since the last build record; a lead may also queue the Devin task."""
    by = need_user(ctx)
    task = bool(f.get("task"))
    if task:
        by = need_lead(ctx)
    try:
        plan = refresh_trigger.since_build(ctx.kb)
        with refresh_trigger.WORK:
            if task and plan["pages"]:
                refresh_trigger.create_task(ctx.kb, plan, by)
            refresh_trigger.write_plan(ctx.kb, plan)
    except (refresh_trigger.RefreshError, C.UiError) as err:
        raise C.UiError(str(err))
    except Exception as err:  # no profile, no clone, no git: say so on the page
        raise C.UiError("Could not work out the stale pages: %s" % err)
    return "/notify", "Plan %s: %d stale page(s)%s." % (plan["id"], len(plan["pages"]), "; task %s" % plan["task"] if plan["task"] else "")


# ---- sections ---------------------------------------------------------------------------------
def channels_section(ctx, q):
    rows = notify.channels(ctx.kb)
    lead = is_lead(ctx)
    out = ["<h2>Channels (%d)</h2>" % len(rows)]
    if not rows:
        out.append('<div class="card soft">No channel yet. Add <code>notify.channels</code> to the KB profile: a name, a kind '
                   "(slack, teams, webhook, email), <code>url_env</code> (the NAME of the environment variable that holds the webhook URL) "
                   "and the events it wants. The profile never holds the URL itself.</div>")
        return "".join(out)
    tr = []
    for c in rows:
        env = ('<span class="pill ok">set</span>' if c["env_set"] else '<span class="pill warn">not set here</span>') if c["url_env"] else \
            '<span class="muted">-</span>'
        probs = "".join('<div class="no">%s</div>' % esc(p) for p in c["problems"])
        test = form(ctx, "/notify", '<input type="hidden" name="test" value="%s"><button class="alt">Send test message (dry run)</button>' % esc(c["name"]),
                    method="get", cls="inline")
        real = ""
        if lead and not c["problems"]:
            real = (form(ctx, "/notify/send", '<input type="hidden" name="channel" value="%s"><input type="hidden" name="what" value="test">'
                         '<button class="bad">Send a test for real</button>' % esc(c["name"]), cls="inline") + " " +
                    form(ctx, "/notify/send", '<input type="hidden" name="channel" value="%s"><input type="hidden" name="what" value="events">'
                         '<button class="bad">Send new events for real</button>' % esc(c["name"]), cls="inline"))
        tr.append("<tr><td><b>%s</b></td><td>%s</td><td><code>%s</code> %s</td><td>%s</td><td>%d s%s</td><td>%s%s</td></tr>" % (
            esc(c["name"]), esc(c["kind"] or "?"), esc(c["url_env"] or "(none)"), env,
            " ".join('<span class="pill">%s</span>' % esc(e) for e in c["events"]) or '<span class="muted">none</span>',
            c["min_interval"], ", digest" if c["digest"] else "", probs, test + " " + real))
    out.append("<table><tr><th>Name</th><th>Kind</th><th>Environment variable</th><th>Events</th><th>Min interval</th><th>Actions</th></tr>%s</table>" % "".join(tr))
    if not lead:
        out.append('<p class="muted"><small>Only a lead can send for real. A dry run shows the message and where it would go; it sends nothing.</small></p>')
    test = C.clean(q.get("test"))
    if test:
        try:
            ch = find(ctx, test)
            out.append('<div class="card"><h3 style="margin-top:0">Test message for %s (dry run, nothing was sent)</h3>%s</div>' % (
                esc(ch["name"]), result_html(notify.send(ch, notify.test_message(ctx.kb, ch), dry_run=True))))
        except C.UiError as err:
            out.append('<div class="err">%s</div>' % esc(err))
    return "".join(out)


def events_section(ctx):
    try:
        evs = notify.all_events(ctx.kb)
    except Exception as err:
        return "<h2>Recent events</h2><div class=\"err\">Could not read the events: %s</div>" % esc(err)
    state = notify.load_state(ctx.kb)
    chans = notify.channels(ctx.kb)
    out = ["<h2>Events now (%d)</h2>" % len(evs),
           '<p class="muted">Computed from files that already exist. Each line says which channels have not had it yet. File names, counts and ids only.</p>']
    if not evs:
        out.append('<div class="card soft">Nothing needs attention right now.</div>')
        return "".join(out)
    rows = []
    for e in evs[:MAX_EVENTS_SHOWN]:
        waiting = [c["name"] for c in chans if e["event"] in c["events"] and e["key"] not in (state["sent"].get(c["name"]) or {})]
        rows.append("<tr><td><span class=\"pill\">%s</span></td><td>%s</td><td>%s</td></tr>" % (
            esc(e["event"]), esc(e["text"]), esc(", ".join(waiting)) if waiting else '<span class="muted">sent or no channel wants it</span>'))
    out.append("<table><tr><th>Event</th><th>What</th><th>Not yet sent to</th></tr>%s</table>" % "".join(rows))
    if len(evs) > MAX_EVENTS_SHOWN:
        out.append('<p class="muted">%d more not shown.</p>' % (len(evs) - MAX_EVENTS_SHOWN))
    return "".join(out)


def refresh_section(ctx):
    plan = refresh_trigger.load_plan(ctx.kb)
    out = ["<h2>Refresh plan</h2>",
           '<p class="muted">Which KB pages cite source files that changed. A refresh rewrites only these pages, into a staging folder, '
           "and stages them in _PENDING for a lead to certify. Nothing is written into the KB from here.</p>"]
    if not plan:
        out.append('<div class="card soft">No refresh plan yet.</div>')
    else:
        out.append('<div class="card"><b>%s</b>: %s. Made %s from <code>%s</code>.%s' % (
            esc(plan.get("id")), esc(plan.get("status")), esc(plan.get("created")), esc((plan.get("trigger") or {}).get("kind")),
            " Task <code>%s</code>." % esc(plan["task"]) if plan.get("task") else ""))
        pages = plan.get("pages") or []
        if pages:
            out.append("<table><tr><th>Stale page</th><th>Why</th></tr>%s</table>" % "".join(
                '<tr><td><a href="/files?page=%s">%s</a></td><td>%s</td></tr>' % (esc(p["page"]), esc(p["page"]), esc("; ".join(p["reasons"][:3]))) for p in pages))
        for n in plan.get("notes") or []:
            out.append('<p class="muted"><small>%s</small></p>' % esc(n))
        out.append("</div>")
    body = '<p><button>Work out the stale pages</button></p>'
    if is_lead(ctx):
        body = ('<label><input type="checkbox" name="task" value="1" style="width:auto"> Also queue one Devin task for these pages</label>'
                + body)
    else:
        body += '<p class="muted"><small>Only a lead queues the Devin task.</small></p>'
    out.append('<div class="card soft"><p>Compares each source repo with the commit the last build recorded (<code>build_plan.py</code>).</p>%s</div>' %
               form(ctx, "/notify/refresh", body))
    return "".join(out)


def pr_section(ctx, q):
    out = ["<h2>Bitbucket PR comment preview</h2>",
           '<p class="muted">A dry run: it reads the PR (when the token variable is set here) and shows the comment. It posts nothing. '
           "Posting is a separate step: <code>python tools/bb_pr.py comment &lt;KB&gt; --pr ID --post</code>. "
           "<b>Needs your Bitbucket to verify</b>: the route is unconfirmed and tested only against a fake server.</p>"]
    cfg = bb_pr.config(ctx.kb)
    out.append('<p class="muted"><small>Settings: %s %s; token variable <code>%s</code> %s.%s</small></p>' % (
        esc(cfg["flavor"]), esc(cfg["base_url"] or "(no base_url)"), esc(cfg["token_env"] or "(none)"),
        "is set" if cfg["token_set"] else "is not set here", "".join(" " + esc(p) + "." for p in cfg["problems"])))
    body = (field("pr", "Pull request id", C.clean(q.get("pr")), hint="a number") +
            field("files", "Changed files (optional)", q.get("files") or "", kind="textarea", rows=3,
                  hint="one path per line, as in the repo; leave empty to read them from Bitbucket") +
            "<p><button>Show the comment (dry run)</button></p>")
    out.append('<div class="card">%s</div>' % form(ctx, "/notify", body, method="get"))
    pr = C.clean(q.get("pr"))
    if pr:
        files = [x.strip() for x in str(q.get("files") or "").replace(",", "\n").splitlines() if x.strip()] or None
        try:
            r = bb_pr.comment(ctx.kb, pr, post=False, files=files)
            out.append('<div class="card"><h3 style="margin-top:0">Comment for PR %s <span class="pill ok">dry run</span></h3>'
                       "<p class=\"muted\">%s. %s%d characters%s.</p><pre>%s</pre></div>" % (
                           esc(pr), esc(r["action"]), esc(r["note"] + " ") if r["note"] else "", len(r["text"]),
                           ", cut to the size limit" if r["truncated"] else "", esc(r["text"])))
        except bb_pr.BbError as err:
            out.append('<div class="err">%s</div>' % esc(err))
        except Exception as err:
            out.append('<div class="err">Could not build the comment: %s</div>' % esc(err))
    return "".join(out)


def right_side():
    return ('<h4>What leaves this machine</h4><div class="muted">A message holds file names, counts, ids and links. No KB text, no question text, '
            "no secret; every message is checked with sensitive.py first. Sending is off until a lead presses a send button or runs "
            "<code>notify.py run --send</code>.</div>"
            '<h4>Secrets</h4><div class="muted">The profile holds the NAME of an environment variable. This page says whether it is set, never its value.</div>'
            '<h4>Bitbucket</h4><div class="muted">bb_pr.py is the only Metis tool that writes to an outside system, and it only comments on a pull request. '
            "This page never posts.</div>")


def notify_view(ctx, q, flash=None, error=None):
    body = ["<h1>Notifications</h1>",
            '<p class="lead">Tell the team when something in the KB needs a person, and keep pages fresh when the code changes.</p>',
            channels_section(ctx, q), events_section(ctx), refresh_section(ctx), pr_section(ctx, q)]
    return page(ctx, "Notifications", "/notify", "".join(body), flash, error, right=C.right_pane(right_side()))


SCREENS = {"/notify": notify_view}
ACTIONS = {"/notify/send": ("/notify", act_send), "/notify/refresh": ("/notify", act_refresh)}
NAV = [("/notify", "Notifications")]
