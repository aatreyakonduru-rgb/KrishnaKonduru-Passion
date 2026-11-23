"""Suggest an edit screen for Metis UI.

Path /suggest, nav label "Suggest an edit". /suggest?page=<kb path> is the link target for the "Suggest an edit" box on a page view.
Any reader with a session name can suggest a correction or comment on a page. Leads (and the approver of the team that owns the
page) see an inbox: approve a suggestion as a question in VALIDATE_KB or as a staged _PENDING edit, decline it with a reason, or
answer a comment. Nothing here writes a live page; storage and rules are in page_suggest.py.
"""
import os
import sys
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
for _p in (TOOLS, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import kb_gate  # noqa: E402
import page_suggest as PS  # noqa: E402
import ui_common as C  # noqa: E402
from ui_common import esc, field, form, page  # noqa: E402

MAX_PAGES = 200


def need_user(ctx):
    if not C.clean(ctx.user):
        raise C.UiError("Say who you are first (top right, 'You are'). Your name goes on every suggestion, comment and decision.")
    return C.clean(ctx.user)


def url(path, **kw):
    q = {k: v for k, v in kw.items() if v}
    return path + ("?" + urllib.parse.urlencode(q) if q else "")


def is_decider(ctx):
    """True when the session name may decide on at least one page (a lead or a team approver)."""
    name = C.clean(ctx.user).lower()
    if not name:
        return False
    if name in kb_gate.certifiers(ctx.kb):
        return True
    return any(name == a.lower() for t in kb_gate.teams(ctx.kb) for a in t["approvers"])


def pick_page(ctx, q):
    """The page named in ?page=, if it is a page in the KB; otherwise ('', note)."""
    want = C.clean(q.get("page"))
    if not want:
        return "", ""
    try:
        return PS.page_path(ctx.kb, want), ""
    except PS.SuggestError as err:
        return "", str(err)


def left_side(ctx, sel, find):
    reg = PS.load(ctx.kb)
    open_by_page = {}
    for s in reg["suggestions"]:
        if s["status"] == "open":
            open_by_page[s["page"]] = open_by_page.get(s["page"], 0) + 1
    talk = {}
    for c in reg["comments"]:
        talk[c["page"]] = talk.get(c["page"], 0) + 1
    allp = PS.pages(ctx.kb)
    shown = [p for p in allp if not find or find.lower() in p.lower()]
    # pages with something open first, then the rest in path order
    shown.sort(key=lambda p: (-open_by_page.get(p, 0), p))
    items = []
    for p in shown[:MAX_PAGES]:
        bits = []
        if open_by_page.get(p):
            bits.append("%d open" % open_by_page[p])
        if talk.get(p):
            bits.append("%d comment%s" % (talk[p], "" if talk[p] == 1 else "s"))
        items.append(C.pane_item(url("/suggest", page=p), esc(p), esc(", ".join(bits)), on=(p == sel), dot="warn" if open_by_page.get(p) else ""))
    if not items:
        items.append('<div class="muted" style="padding:8px">No page matches.</div>')
    if len(shown) > MAX_PAGES:
        items.append('<div class="muted" style="padding:8px">Showing %d of %d. Narrow it with the filter.</div>' % (MAX_PAGES, len(shown)))
    top = form(ctx, "/suggest", field("find", "Filter pages", find) + '<input type="hidden" name="page" value="%s"><p><button>Filter</button></p>' % esc(sel),
               method="get")
    return C.left_pane("Pages", "".join(items), len(allp), top=top)


def source_text(s):
    if s.get("evidence"):
        return "Source: " + ", ".join("[E: %s]" % e for e in s["evidence"])
    return "Where to look: %s" % s.get("look", "")


def suggestion_card(ctx, s, lead, with_page=False):
    status = s["status"]
    pill = '<span class="pill %s">%s</span>' % ("ok" if status == "approved" else "no" if status == "declined" else "warn", esc(status))
    head = "<b>%s</b> %s &middot; %s on %s" % (esc(s["id"]), pill, esc(s["by"]), esc(s["on"]))
    if with_page:
        head += ' &middot; <a href="%s">%s</a>' % (esc(url("/suggest", page=s["page"])), esc(s["page"]))
    out = ['<div class="card">', "<p>%s</p>" % head]
    if s.get("line"):
        out.append('<p class="muted">Line %d now reads: <code>%s</code></p>' % (s["line"], esc(s.get("line_text", ""))))
    out.append("<p><b>What is wrong:</b> %s</p><p><b>Proposed:</b> %s</p><p class=\"muted\">%s</p>" % (esc(s["wrong"]), esc(s["proposed"]), esc(source_text(s))))
    if status == "approved":
        what = "question %s in VALIDATE_KB" % s["question_id"] if s.get("action") == "question" else "staged in _PENDING/%s for certification" % s.get("batch")
        out.append('<p class="muted">Approved by %s: %s.%s</p>' % (esc(s.get("decided_by")), esc(what), " Note: " + esc(s["note"]) if s.get("note") else ""))
    elif status == "declined":
        out.append('<p class="muted">Declined by %s: %s</p>' % (esc(s.get("decided_by")), esc(s.get("note"))))
    elif lead and PS.can_decide(ctx.kb, ctx.user, s["page"]):
        out.append('<p class="muted"><small>Track record (facts, not a score): %s.</small></p>' % esc(PS.contributor_line(ctx.kb, s["by"])))
        sid = '<input type="hidden" name="id" value="%s">' % esc(s["id"])
        out.append(form(ctx, "/suggest/approve", sid + '<p><label><input type="radio" name="how" value="question" checked> Raise a question in VALIDATE_KB</label>'
                        '<label><input type="radio" name="how" value="stage"> Stage the edit in _PENDING (needs a line, a source tag and a closed gate)</label></p>'
                        + field("note", "Note (optional)", "") + "<p><button>Approve</button></p>"))
        out.append(form(ctx, "/suggest/decline", sid + field("reason", "Reason to decline", "", required=True) + "<p><button>Decline</button></p>"))
    out.append("</div>")
    return "".join(out)


def thread_html(ctx, rel, lead):
    th = PS.thread(ctx.kb, rel)
    if not th:
        return '<div class="card soft">No comments on this page yet.</div>'
    out = []
    for c in th:
        label = "answer" if c.get("kind") == "answer" else "reply" if c.get("reply_to") else "comment"
        st = ' <span class="pill %s">%s</span>' % ("ok" if c.get("status") == "answered" else "warn", esc(c["status"])) if c.get("status") else ""
        reply = " &middot; reply to %s" % esc(c["reply_to"]) if c.get("reply_to") else ""
        out.append('<div class="card%s"><p class="muted"><b>%s</b> %s &middot; %s &middot; %s%s%s</p><p>%s</p>' % (
            " soft" if c.get("reply_to") else "", esc(c["id"]), esc(label), esc(c["by"]), esc(c["on"]), reply, st, esc(c["text"])))
        if c.get("status") == "open" and lead and PS.can_decide(ctx.kb, ctx.user, rel):
            out.append(form(ctx, "/suggest/answer", '<input type="hidden" name="id" value="%s">' % esc(c["id"]) +
                            field("text", "Answer", "", kind="textarea", rows=2, required=True) + "<p><button>Answer</button></p>"))
        if c.get("kind") != "answer":
            out.append(form(ctx, "/suggest/comment", '<input type="hidden" name="page" value="%s"><input type="hidden" name="reply_to" value="%s">' % (
                esc(rel), esc(c["id"])) + field("text", "Reply", "", required=True) + "<p><button>Reply</button></p>"))
        out.append("</div>")
    return "".join(out)


def inbox_html(ctx):
    sug, com = PS.inbox(ctx.kb, ctx.user)
    out = ["<h2>Inbox (%d suggestion%s, %d comment%s)</h2>" % (len(sug), "" if len(sug) == 1 else "s", len(com), "" if len(com) == 1 else "s")]
    if not sug and not com:
        out.append('<div class="card soft">Nothing is waiting for you.</div>')
    for s in sug:
        out.append(suggestion_card(ctx, s, True, with_page=True))
    for c in com:
        out.append('<div class="card"><p class="muted"><b>%s</b> &middot; %s on <a href="%s">%s</a></p><p>%s</p></div>' % (
            esc(c["id"]), esc(c["by"]), esc(url("/suggest", page=c["page"])), esc(c["page"]), esc(c["text"])))
    return "".join(out)


def suggest_view(ctx, q, flash=None, error=None):
    sel, note = pick_page(ctx, q)
    if note and not error:
        error = note
    find = C.clean(q.get("find"))
    lead = is_decider(ctx)
    body = ["<h1>Suggest an edit</h1>",
            '<p class="lead">Think a page is wrong, or have a question about it? Say what is wrong, give the text you propose and where it comes from. '
            "Nothing changes on the page itself: a lead reads your suggestion and either raises a question, stages the edit for certification, "
            "or tells you why not.</p>"]
    if not C.clean(ctx.user):
        body.append('<div class="card soft">Say who you are (top right, \'You are\') before you send anything.</div>')
    if lead:
        body.append(inbox_html(ctx))
    if not sel:
        body.append('<div class="card soft">Pick a page on the left.</div>')
    else:
        body.append("<h2>%s</h2>" % esc(sel))
        body.append('<p><a href="/files?page=%s">Open the page</a></p>' % esc(sel))
        sug = PS.suggestions(ctx.kb, page=sel)
        form_body = ('<input type="hidden" name="page" value="%s">' % esc(sel) +
                     field("wrong", "What is wrong", "", kind="textarea", rows=2, required=True) +
                     field("proposed", "Proposed text", "", kind="textarea", rows=2, required=True) +
                     field("line", "Line number (optional)", "", hint="needed if you want the edit staged for certification") +
                     field("evidence", "Source tag", "", hint="e.g. [E: kb:context/rules.md \"quote\"]") +
                     field("look", "Or: where to look", "", hint="give exactly one of source tag or where to look") +
                     "<p><button>Send suggestion</button></p>")
        body.append('<div class="card"><h3 style="margin-top:0">Suggest a correction</h3><p class="muted">Sent as: %s.</p>%s</div>' % (
            esc(C.clean(ctx.user) or "(say who you are first)"), form(ctx, "/suggest/submit", form_body)))
        body.append("<h3>Suggestions on this page (%d)</h3>" % len(sug))
        body += [suggestion_card(ctx, s, lead) for s in sug] or ['<div class="card soft">None yet.</div>']
        body.append("<h3>Comments</h3>")
        body.append(thread_html(ctx, sel, lead))
        body.append('<div class="card"><h3 style="margin-top:0">Add a comment</h3>%s</div>' % form(
            ctx, "/suggest/comment", '<input type="hidden" name="page" value="%s">' % esc(sel) +
            field("text", "Comment", "", kind="textarea", rows=3, required=True) + "<p><button>Comment</button></p>"))
        body.append('<p class="muted"><small>Comments are append-only: they cannot be edited or removed.</small></p>')
    return page(ctx, "Suggest an edit", "/suggest", "".join(body), flash, error, left=left_side(ctx, sel, find))


# ---- actions ------------------------------------------------------------------------------------------------
def guard(fn, *args, **kw):
    try:
        return fn(*args, **kw)
    except (PS.SuggestError, kb_gate.GateError, ValueError) as err:
        raise C.UiError(str(err))


def act_submit(ctx, f):
    by = need_user(ctx)
    s = guard(PS.suggest, ctx.kb, f.get("page"), by, f.get("wrong"), f.get("proposed"), f.get("evidence") or None, f.get("look") or None,
              C.clean(f.get("line")) or None)
    return url("/suggest", page=s["page"]), "Sent as %s. A lead will look at it." % s["id"]


def act_comment(ctx, f):
    by = need_user(ctx)
    c = guard(PS.comment, ctx.kb, f.get("page"), by, f.get("text"), C.clean(f.get("reply_to")) or None)
    return url("/suggest", page=c["page"]), "Added %s." % c["id"]


def act_approve(ctx, f):
    by = need_user(ctx)
    how = f.get("how") or "question"
    s = guard(PS.approve, ctx.kb, C.clean(f.get("id")), by, how, f.get("note"))
    what = "question %s raised in VALIDATE_KB" % s["question_id"] if s["action"] == "question" else "staged in _PENDING/%s; certify it with the gate" % s["batch"]
    return url("/suggest", page=s["page"]), "%s approved: %s." % (s["id"], what)


def act_decline(ctx, f):
    by = need_user(ctx)
    s = guard(PS.decline, ctx.kb, C.clean(f.get("id")), by, f.get("reason"))
    return url("/suggest", page=s["page"]), "%s declined." % s["id"]


def act_answer(ctx, f):
    by = need_user(ctx)
    r = guard(PS.answer, ctx.kb, C.clean(f.get("id")), by, f.get("text"))
    return url("/suggest", page=r["page"]), "Answered %s." % r["reply_to"]


SCREENS = {"/suggest": suggest_view}
ACTIONS = {"/suggest/submit": ("/suggest", act_submit), "/suggest/comment": ("/suggest", act_comment),
           "/suggest/approve": ("/suggest", act_approve), "/suggest/decline": ("/suggest", act_decline),
           "/suggest/answer": ("/suggest", act_answer)}
NAV = [("/suggest", "Suggest an edit")]
