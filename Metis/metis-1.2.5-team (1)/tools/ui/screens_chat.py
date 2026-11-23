"""Chat-first screen for Metis UI.

Path /chat, nav label "Chat".
A conversation thread per signed-in user. The last 20 turns are shown; the thread (ask ids only, see chat_store.py) is also kept in
<kb>/.metis/chat/<user>.jsonl, a local git-ignored file that kb_manifest skips, so it survives a server restart (newest 200 messages
per thread, 50 threads per user, atomic write; if the file cannot be written Chat carries on in memory). Each turn runs the same
extractive answerer as /ask (answers.ask, mode local: KB lines quoted word for word, checked by verify_kb), shows the cited pages and
the computed confidence, and offers like / dislike through answers.rate, which is feedback.record unchanged (a dislike needs why and
exactly one of the right answer or where to look). A short follow-up ("and its owner?", "what about visits?") carries the key terms of
the previous question as the direction the answerer already understands, so the answer scoring is not touched.
Each turn is also an ordinary ask record, so it appears in Ask's list and in the unanswered report. One form post per turn; no JavaScript.
Labelled lines (claim_labels.py) are filtered by the signed-in name inside answers.ask (`by`), so the chat quotes only what that person
may see; a turn that left lines out says so in the answer without showing them. A restored turn is checked again when it is shown: a
line whose [E: kb:...] source is above the viewer's clearance now (labels added or changed since) is left out and counted.
"""
import os
import re
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
for _p in (TOOLS, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import urllib.parse  # noqa: E402

import answers  # noqa: E402
import chat_store  # noqa: E402
import claim_labels  # noqa: E402
import ui_common as C  # noqa: E402
from ui_common import esc, field, form, page  # noqa: E402

MAX_TURNS = 20
KEY_TERMS = 6
PRONOUNS = re.compile(r"\b(it|its|that|those|this|these|they|them|their|there|same|also|too|and|then|more)\b", re.I)
THREADS = {}            # (kb, lower-case user) -> [ask id, ...], oldest first; a cache of chat_store (loaded on first use)
LOCK = threading.RLock()


def need_user(ctx):
    if not C.clean(ctx.user):
        raise C.UiError("Say who you are first (top right, 'You are'). Your name goes on every approval, rating and answer.")
    return C.clean(ctx.user)


def thread_key(ctx):
    return (ctx.kb, C.clean(ctx.user).lower())


def _cached(ctx):
    """The in-memory thread for this user, read from the chat file the first time (a restart, or THREADS cleared)."""
    key = thread_key(ctx)
    if key not in THREADS:
        try:
            THREADS[key] = chat_store.load(ctx.kb, ctx.user)[-MAX_TURNS:] if key[1] else []
        except (OSError, ValueError):
            THREADS[key] = []
    return THREADS[key]


def thread(ctx):
    with LOCK:
        return list(_cached(ctx))


def add_turn(ctx, aid):
    with LOCK:
        t = _cached(ctx)
        t.append(aid)
        del t[:-MAX_TURNS]
        try:
            chat_store.add(ctx.kb, ctx.user, aid)
        except (OSError, ValueError):
            pass                # the conversation still works in memory; only the restart copy is missing


def key_terms(question):
    """The words of a question that say what it is about, in order, without question padding, at most KEY_TERMS."""
    out = []
    for w in re.findall(r"[a-z0-9_]+", str(question).lower()):
        if w in answers.STOP or w in answers.FILLER or len(w) < 3 or w.isdigit() or w in out:
            continue
        out.append(w)
    return out[:KEY_TERMS]


def is_follow_up(question):
    """A question too short to stand alone, or one that points back ("its", "those", "and ..."), asked after another."""
    return len(key_terms(question)) < 3 or bool(PRONOUNS.search(question))


def follow_direction(ctx, question):
    """The previous question's key terms when `question` is a follow-up, else None."""
    prev = thread(ctx)
    if not prev or not is_follow_up(question):
        return None
    try:
        before = answers.get(ctx.kb, prev[-1])["question"]
    except C.UiError:
        return None
    now = key_terms(question)
    terms = [w for w in key_terms(before) if w not in now]
    return " ".join(terms) or None


def ask_turn(ctx, question):
    by = need_user(ctx)
    question = C.clean(question)
    if not question:
        raise C.UiError("Write a question first.")
    direction = follow_direction(ctx, question)
    r = answers.ask(ctx.kb, question, by, mode="local", direction=direction)
    add_turn(ctx, r["id"])
    return r, direction


# ---- rendering --------------------------------------------------------------------------------------
def confidence_pill(c):
    if not c:
        return ""
    cls = {"High": "ok", "Medium": "warn", "Low": "no", "None": "no"}.get(c["band"], "")
    return '<span class="pill %s" title="%s">Confidence: %s &middot; %d / 100</span>' % (
        cls, esc("; ".join(c.get("reasons") or []) + " (rule-based, uncalibrated until the Usage check passes)"),
        esc(c["band"]), c["score"])


def page_link(p, title=None):
    return '<a href="/files?page=%s">%s</a>' % (esc(urllib.parse.quote(p, safe="/")), esc(title or p))


def citations(a):
    files = a.get("files") or []
    if not files:
        return '<div class="muted"><small>No KB page was cited.</small></div>'
    return '<div class="muted"><small>Cited: %s</small></div>' % ", ".join(page_link(f) for f in files)


def area(name, aid, label, hint="", rows=2):
    h = " <small>%s</small>" % esc(hint) if hint else ""
    return '<label for="%s-%s">%s%s</label><textarea id="%s-%s" name="%s" rows="%d"></textarea>' % (name, esc(aid), esc(label), h, name, esc(aid), name, rows)


def rate_forms(ctx, a):
    aid = esc(a["id"])
    up = form(ctx, "/chat/rate", '<input type="hidden" name="id" value="%s"><input type="hidden" name="rating" value="up">'
              '<button class="thumb" title="Right: like this answer" aria-label="Like">&#128077;</button>' % aid, cls="inline")
    down = form(ctx, "/chat/rate", (
        '<input type="hidden" name="id" value="%s"><input type="hidden" name="rating" value="down">' % aid
        + area("why", a["id"], "What is wrong or missing?")
        + '<p><b>Then give one of these</b> <span class="muted">(a dislike needs exactly one)</span></p>'
        + area("correct", a["id"], "The right answer", "the claim becomes a question for a lead; the KB is not changed")
        + area("redirect", a["id"], "Or where to look instead", "a folder, page, table, or \"the ETL, not the app\"; Metis asks again at once", 1)
        + '<p><button class="bad">Dislike</button></p>'))
    box = "dn-" + aid
    return ('<div class="rate"><input type="checkbox" id="%s" class="dn-toggle">%s'
            '<label for="%s" class="thumb" title="Wrong or incomplete: dislike this answer" aria-label="Dislike">&#128078;</label>'
            '<div class="reason">%s</div></div>') % (box, up, box, down)


def visible_answer(ctx, text):
    """The answer text with each line whose [E: kb:...] source the viewer may not see now taken out (a restored turn may predate a
    label). Returns (text, lines withheld). Same text back when the KB has no labels or nothing is above the viewer's clearance."""
    try:
        viewer = claim_labels.Viewer(ctx.kb, C.clean(ctx.user))
        if not viewer.active:
            return text, 0
        kept, hidden = [], 0
        for line in text.splitlines():
            if claim_labels.source_hidden(viewer, line):
                hidden += 1
            else:
                kept.append(line)
    except Exception:  # noqa: BLE001  fail closed: show nothing rather than an unchecked line
        return "", 1
    if not hidden:
        return text, 0
    return "\n".join(kept) + "\n\n%s\n" % answers.WITHHELD_NOTE, hidden


def turn_html(ctx, a):
    out = ['<div id="t-%s"><div class="bub me">%s</div>' % (esc(a["id"]), esc(a["question"]))]
    if a.get("direction"):
        out.append('<div class="muted" style="text-align:right"><small>topic carried from the last question: %s</small></div>' % esc(a["direction"]))
    out.append('<div class="bub bot">')
    if a.get("status") != "answered" or not a.get("answer_file"):
        out.append('<span class="muted">No answer was recorded for this question.</span>')
    else:
        out.append(C.render_md(visible_answer(ctx, answers.answer_text(ctx.kb, a))[0]))
        out.append(confidence_pill(a.get("confidence")))
        out.append(citations(a))
        chk = a.get("checked") or {}
        out.append('<div class="muted"><small>%d lines checked against the KB, %d source problems</small></div>' % (
            chk.get("lines", 0), len(chk.get("problems") or [])))
        if (a.get("guidance") or {}).get("nearest"):
            out.append('<div class="muted"><small>Nearest pages: %s</small></div>' % ", ".join(page_link(n["page"], n["title"]) for n in a["guidance"]["nearest"]))
        if a.get("feedback"):
            out.append('<div class="muted"><small>Rated %s: %s.</small></div>' % (esc(a["feedback"]), esc(a.get("rating"))))
        else:
            out.append(rate_forms(ctx, a))
    out.append("</div></div>")
    return "".join(out)


def right_side(ctx, last):
    if not last:
        return C.right_pane('<h4>Answer basis</h4><p class="muted">The pages the last answer used show here.</p>')
    chk = last.get("checked") or {}
    files = "".join("<tr><td>%s</td></tr>" % page_link(f) for f in last.get("files") or [])
    out = "<h4>Last answer used</h4>%s" % ("<table>%s</table>" % files if files else '<p class="muted">No KB page was used.</p>')
    c = last.get("confidence")
    if c:
        out += "<h4>Confidence is built from</h4><table>%s</table>" % "".join("<tr><td>%s</td></tr>" % esc(r) for r in c["reasons"])
    out += ('<h4>Checked</h4><table><tr><td class="muted">Lines checked</td><td>%d</td></tr><tr><td class="muted">Source problems</td><td>%d</td></tr></table>'
            % (chk.get("lines", 0), len(chk.get("problems") or [])))
    out += ('<p class="muted">Answers quote KB lines and are checked against them; nothing is invented. Thumbs-down reasons go to a lead. '
            "The conversation is kept in a local file on this machine, not in the shared KB; the last %d turns are shown.</p>" % MAX_TURNS)
    return C.right_pane(out)


def chat_view(ctx, q, flash=None, error=None):
    body = ['<h1>Chat</h1><p class="lead">Ask the KB in a conversation. Every answer quotes KB pages and says how sure it is. '
            "A short follow-up keeps the topic of your last question.</p>"]
    asks, last = [], None
    if not C.clean(ctx.user):
        body.append('<div class="card soft">Say who you are first (top right, "You are") to start a conversation. Your name goes on every answer and rating.</div>')
    else:
        for aid in thread(ctx):
            try:
                a = answers.get(ctx.kb, aid)
            except C.UiError:
                continue
            if C.clean(a.get("by")).lower() == C.clean(ctx.user).lower():   # a restored id for someone else's ask is not shown
                asks.append(a)
        if not asks:
            body.append('<div class="card soft">No messages yet. Ask something below, for example: <i>which table does pets reference?</i></div>')
        body += [turn_html(ctx, a) for a in asks]
        last = asks[-1] if asks else None
        body.append(form(ctx, "/chat/ask", field("question", "Your message", "", kind="textarea", rows=2,
                                                 hint="a follow-up like \"and its owner?\" uses your last question's topic") +
                         '<p><button>Send</button> <span class="muted">Answers come from the KB lines only, no model.</span></p>'))
        if asks:
            body.append(form(ctx, "/chat/clear", '<p><button class="alt">Clear conversation</button></p>'))
    items = "".join('<a class="it" href="#t-%s">%s<span class="s">%s</span></a>' % (
        esc(a["id"]), esc(a["question"][:60]), esc((a.get("confidence") or {}).get("band", "-"))) for a in asks) or \
        '<div class="it muted">No messages yet.</div>'
    return page(ctx, "Chat", "/chat", "".join(body), flash, error, left=C.left_pane("This conversation", items, len(asks)), right=right_side(ctx, last))


# ---- actions ----------------------------------------------------------------------------------------
def act_chat_ask(ctx, f):
    r, direction = ask_turn(ctx, f.get("question", ""))
    return "/chat#t-" + r["id"], "Answered%s." % (" using the topic of your last question" if direction else "")


def act_chat_rate(ctx, f):
    by = need_user(ctx)
    aid = f.get("id", "")
    if aid not in thread(ctx):
        raise C.UiError("That answer is not in your conversation.")
    item, again = answers.rate(ctx.kb, aid, by, f.get("rating", ""), f.get("why"), f.get("correct"), f.get("redirect"))
    if again:
        add_turn(ctx, again["id"])
        return "/chat#t-" + again["id"], "Recorded %s. Asked again with your direction." % item["id"]
    return "/chat#t-" + aid, "Recorded %s." % item["id"]


def act_chat_clear(ctx, f):
    need_user(ctx)
    with LOCK:
        THREADS[thread_key(ctx)] = []
        try:
            chat_store.clear(ctx.kb, ctx.user)
        except (OSError, ValueError):
            pass
    return "/chat", "Conversation cleared. The questions stay in Ask."


SCREENS = {"/chat": chat_view}
ACTIONS = {"/chat/ask": ("/chat", act_chat_ask), "/chat/rate": ("/chat", act_chat_rate), "/chat/clear": ("/chat", act_chat_clear)}
NAV = [("/chat", "Chat")]
