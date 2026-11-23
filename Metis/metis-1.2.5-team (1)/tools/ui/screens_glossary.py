"""Business glossary screen for Metis UI.

Path /glossary, nav label "Glossary".
Product owners and BSAs onboard terms, synonyms, meanings, and where they appear in the KB.
"""
import os
import sys
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
for _p in (TOOLS, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import glossary  # noqa: E402
import kb_gate  # noqa: E402
import ui_common as C  # noqa: E402
from ui_common import esc, field, form, page, pill  # noqa: E402


def need_user(ctx):
    if not C.clean(ctx.user):
        raise C.UiError("Say who you are first (top right, 'You are'). Your name goes on every approval, rating and answer.")
    return C.clean(ctx.user)


def page_link(kb, p):
    clean_p = p.strip().lstrip("/\\")
    full = os.path.join(kb, clean_p)
    if os.path.isfile(full):
        return '<a href="/files?page=%s">%s</a>' % (esc(clean_p), esc(p))
    return '<span class="no">%s (missing)</span>' % esc(p)


def left_side(entries, shown, search_query):
    """Terms list: each term with how many synonyms and KB pages it has."""
    items = []
    for e in shown:
        sub = "%s &middot; %s" % (
            "%d synonym%s" % (len(e["synonyms"]), "" if len(e["synonyms"]) == 1 else "s"),
            "%d page%s" % (len(e["where_in_kb"]), "" if len(e["where_in_kb"]) == 1 else "s"))
        items.append(C.pane_item("/glossary?q=%s#t-%s" % (urllib.parse.quote(search_query), urllib.parse.quote(e["term"])),
                                 '%s <span class="pill">%d</span>' % (esc(e["term"]), len(e["synonyms"]) + len(e["where_in_kb"])), sub))
    if not items:
        items = ['<div class="it"><span class="s">No terms to list.</span></div>']
    top = form(
        None, "/glossary",
        '<div class="flt"><input type="text" name="q" value="%s" placeholder="Search terms..."></div>' % esc(search_query),
        method="get")
    return C.left_pane("Business terms", "".join(items), len(entries), top=top)


def right_side(ctx, entries, probs, locked, is_lead):
    pages = {p for e in entries for p in e["where_in_kb"]}
    syns = sum(len(e["synonyms"]) for e in entries)
    empty = sum(1 for e in entries if not e["meaning"])
    state = "locked" if locked else "open"
    out = ('<h4>Glossary</h4><div class="grid">'
           '<div class="card"><div class="stat">%d</div><span class="muted">terms</span></div>'
           '<div class="card"><div class="stat">%d</div><span class="muted">synonyms</span></div>'
           '<div class="card"><div class="stat">%d</div><span class="muted">KB pages named</span></div>'
           '<div class="card"><div class="stat">%d</div><span class="muted">problems</span></div></div>' % (
               len(entries), syns, len(pages), len(probs)))
    if empty:
        out += '<p class="muted"><small>%d term%s without a meaning.</small></p>' % (empty, "" if empty == 1 else "s")
    out += ('<h4>Who may change it</h4><div class="muted">KB is %s. %s</div>' % (
        state, "You are a lead." if locked and is_lead else
        "Only a named lead may change the glossary." if locked else "Anyone with a name set may add or edit terms."))
    out += ('<h4>Help</h4><div class="muted">A term has a meaning, synonyms and the KB pages where it appears. '
            "Ask expands a question with the synonyms, so a question that says 'customer' also finds pages about 'owner'. "
            "Write meanings in plain words, with no secrets or keys. Separate synonyms and pages with commas.</div>")
    return out


def glossary_view(ctx, q, flash=None, error=None):
    search_query = C.clean(q.get("q") or q.get("search") or "")
    data = glossary.load(ctx.kb)
    entries = data.get("entries", [])

    leads = kb_gate.certifiers(ctx.kb)
    locked = kb_gate.is_locked(ctx.kb)
    me = kb_gate.clean(ctx.user).lower()
    is_lead = me in leads

    body = [
        "<h1>Business glossary</h1>",
        '<p class="lead">Define business terms, synonyms, meanings, and where they appear in the knowledge base. '
        "Ask queries expand with these synonyms.</p>",
    ]

    # Gate & Lock Status Banner
    lead_names = ", ".join(v[0] for v in leads.values()) or "nobody is named yet (Setup: KB owner and lead roles)"
    if locked:
        if is_lead:
            body.append(
                '<p><span class="pill ok">KB locked &middot; You are a lead (%s)</span> '
                '<span class="muted">You may add, edit, and remove glossary terms.</span></p>' % esc(leads[me][1])
            )
        else:
            body.append(
                '<p><span class="pill warn">KB locked</span> '
                '<span class="muted">After the KB is locked, only a named lead may change the glossary (leads: %s).</span></p>'
                % esc(lead_names)
            )
    else:
        body.append(
            '<p><span class="pill ok">KB open</span> '
            '<span class="muted">Anyone with a name set may add or edit terms before lock.</span></p>'
        )

    # Problems Card
    probs = glossary.problems(ctx.kb)
    if probs:
        items = "".join("<li>%s</li>" % esc(p) for p in probs)
        body.append(
            '<div class="card soft"><h3 style="margin-top:0"><span class="pill warn">%d problem%s</span> in glossary</h3>'
            "<ul>%s</ul></div>" % (len(probs), "" if len(probs) == 1 else "s", items)
        )

    # Search form (in the left pane, see left_side)

    # Filter entries
    if search_query:
        sq = search_query.lower()
        shown = []
        for e in entries:
            t = e["term"].lower()
            m = e["meaning"].lower()
            syns = " ".join(e["synonyms"]).lower()
            pages = " ".join(e["where_in_kb"]).lower()
            if sq in t or sq in m or sq in syns or sq in pages:
                shown.append(e)
    else:
        shown = entries

    # Entries section
    count_label = "%d term%s" % (len(shown), "" if len(shown) == 1 else "s")
    if search_query:
        count_label += ' matching "%s" (%d total)' % (esc(search_query), len(entries))
    body.append("<h2>Terms (%s)</h2>" % count_label)

    if not shown:
        if search_query:
            body.append('<div class="card soft">No terms match "%s". <a href="/glossary">Clear search</a>.</div>' % esc(search_query))
        else:
            body.append('<div class="card soft">No glossary terms added yet. Add your first business term below.</div>')

    for e in shown:
        term_exact = e["term"]
        syns_html = (
            " ".join('<span class="pill">%s</span>' % esc(s) for s in e["synonyms"])
            if e["synonyms"]
            else '<span class="muted">(none)</span>'
        )
        pages_html = (
            ", ".join(page_link(ctx.kb, p) for p in e["where_in_kb"])
            if e["where_in_kb"]
            else '<span class="muted">(none)</span>'
        )
        meaning_html = (
            C.render_md(e["meaning"])
            if e["meaning"]
            else '<p class="muted"><em>(empty meaning)</em></p>'
        )

        edit_form = form(
            ctx,
            "/glossary/edit",
            '<input type="hidden" name="old_term" value="%s">'
            '<div class="row"><div>%s</div><div>%s</div></div>'
            '%s'
            '%s'
            '<p><button>Save changes</button></p>'
            % (
                esc(term_exact),
                field("term", "Term", term_exact, required=True),
                field("synonyms", "Synonyms", ", ".join(e["synonyms"]), hint="comma separated"),
                field("meaning", "Meaning", e["meaning"], kind="textarea", rows=2),
                field("where_in_kb", "Where in KB", ", ".join(e["where_in_kb"]), hint="comma separated KB pages"),
            ),
        )

        remove_form = form(
            ctx,
            "/glossary/remove",
            '<input type="hidden" name="term" value="%s">'
            '<button class="alt bad" onclick="return confirm(\'Remove this term?\')">Remove term</button>'
            % esc(term_exact),
        )

        entry_card = [
            '<div class="card" id="t-%s">' % esc(urllib.parse.quote(term_exact)),
            '<h3 style="margin-top:0">%s %s</h3>' % (
                esc(term_exact), '<span class="pill blue">business term</span>'),
            "<p><b>Synonyms:</b> %s</p>" % syns_html,
            "<div><b>Meaning:</b> %s</div>" % meaning_html,
            "<p><b>Where in KB:</b> %s</p>" % pages_html,
            '<p class="muted"><small>Added by %s on %s</small></p>' % (esc(e.get("added_by") or "unknown"), esc(e.get("added_on") or "unknown")),
            '<details><summary class="muted" style="cursor:pointer">Edit or remove</summary>',
            '<div style="margin-top:10px">%s</div>' % edit_form,
            '<div style="margin-top:10px">%s</div>' % remove_form,
            "</details>",
            "</div>",
        ]
        body.append("".join(entry_card))

    # Add Term Form Card
    add_form = form(
        ctx,
        "/glossary/add",
        '<div class="row"><div>%s</div><div>%s</div></div>'
        '%s'
        '%s'
        '<p><button>Add term</button></p>'
        % (
            field("term", "Term", "", hint="the business term or concept", required=True),
            field("synonyms", "Synonyms", "", hint="comma separated synonyms, e.g. customer, client"),
            field("meaning", "Meaning", "", kind="textarea", hint="plain words explaining what this term means", rows=3),
            field("where_in_kb", "Where in KB", "", hint="comma separated KB pages, e.g. db/PETCLINIC_DB.md"),
        ),
    )

    body.append('<div class="card"><h2 style="margin-top:0">Add a glossary term</h2>%s</div>' % add_form)

    return page(ctx, "Glossary", "/glossary", "".join(body), flash, error,
                left=left_side(entries, shown, search_query), right=C.right_pane(right_side(ctx, entries, probs, locked, is_lead)))


# =============================================================================================== Actions
def act_glossary_add(ctx, f):
    by = need_user(ctx)
    term = f.get("term", "")
    synonyms = f.get("synonyms", "")
    meaning = f.get("meaning", "")
    where_in_kb = f.get("where_in_kb", "")
    entry = glossary.add(ctx.kb, term, synonyms, meaning, where_in_kb, by)
    return "/glossary", "Added term '%s' to the glossary." % entry["term"]


def act_glossary_edit(ctx, f):
    by = need_user(ctx)
    old_term = f.get("old_term", "")
    term = f.get("term", "")
    synonyms = f.get("synonyms", "")
    meaning = f.get("meaning", "")
    where_in_kb = f.get("where_in_kb", "")
    entry = glossary.update(ctx.kb, term, synonyms, meaning, where_in_kb, by, old_term=old_term)
    return "/glossary", "Updated term '%s'." % entry["term"]


def act_glossary_remove(ctx, f):
    by = need_user(ctx)
    term = f.get("term", "")
    removed = glossary.remove(ctx.kb, term, by)
    return "/glossary", "Removed term '%s' from the glossary." % removed


SCREENS = {"/glossary": glossary_view}
ACTIONS = {
    "/glossary/add": ("/glossary", act_glossary_add),
    "/glossary/edit": ("/glossary", act_glossary_edit),
    "/glossary/remove": ("/glossary", act_glossary_remove),
}
NAV = [("/glossary", "Glossary")]
