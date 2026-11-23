"""Federation and Export screen for Metis UI.

Path /federation, nav label "Federation".
Features:
  - Registered KBs and status in the cross-team shared index (shared.sqlite)
  - Cross-team hybrid search box across all certified KBs with team attribution
  - Cross-team upstream and downstream impact walks
  - One-click export buttons for RDF (Turtle, NT, JSON-LD, OWL), W3C PROV-O (Turtle, JSON, OTLP), and OKF Bundle
  - File browser for all generated exports in <KB>/.metis/exports/
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
for _p in (TOOLS, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import cross_impact  # noqa: E402
import export_prov  # noqa: E402
import export_rdf  # noqa: E402
import kb_gate  # noqa: E402
import okf_bundle  # noqa: E402
import shared_index  # noqa: E402
import ui_common as C  # noqa: E402
from ui_common import esc, field, form, page  # noqa: E402


def shared_db_path(kb):
    prof = kb_gate.profile(kb)
    cfg_p = prof.get("federation", {}).get("shared_db")
    if cfg_p:
        return os.path.abspath(os.path.join(kb, cfg_p))
    return os.path.join(kb, ".metis", "shared.sqlite")


def need_user(ctx):
    if not C.clean(ctx.user):
        raise C.UiError("Say who you are first (top right, 'You are'). Your name goes on every approval, rating and answer.")
    return C.clean(ctx.user)


def format_bytes(num):
    for unit in ["B", "KB", "MB", "GB"]:
        if abs(num) < 1024.0:
            return "%3.1f %s" % (num, unit)
        num /= 1024.0
    return "%.1f TB" % num


def list_exports(kb):
    base = os.path.join(kb, ".metis", "exports")
    if not os.path.isdir(base):
        return []
    items = []
    for dirpath, _, filenames in os.walk(base):
        for fname in sorted(filenames):
            fp = os.path.join(dirpath, fname)
            rel = os.path.relpath(fp, base).replace(os.sep, "/")
            sz = os.path.getsize(fp)
            items.append({"path": rel, "bytes": sz, "full_path": fp})
    return items


# ---- View ------------------------------------------------------------------------

def left_side(active_tab, export_count, kb_count):
    items = [
        C.pane_item("/federation?tab=kbs", "Registered KBs", "%d certified KBs" % kb_count, on=(active_tab == "kbs")),
        C.pane_item("/federation?tab=search", "Cross-Team Search", "Search across KBs", on=(active_tab == "search")),
        C.pane_item("/federation?tab=impact", "Cross-Team Impact", "Upstream & downstream", on=(active_tab == "impact")),
        C.pane_item("/federation?tab=exports", "Export Artifacts", "%d files exported" % export_count, on=(active_tab == "exports")),
    ]
    return C.left_pane("Federation", "".join(items), export_count)


def right_side(db_path, stats_data):
    out = [
        "<h4>Shared Read Index</h4>",
        '<div class="grid">',
        '<div class="card"><div class="stat">%d</div><span class="muted">Certified KBs</span></div>' % stats_data.get("total_kbs", 0),
        '<div class="card"><div class="stat">%d</div><span class="muted">Total Pages</span></div>' % stats_data.get("total_pages", 0),
        '<div class="card"><div class="stat">%d</div><span class="muted">Graph Objects</span></div>' % stats_data.get("total_objects", 0),
        '<div class="card"><div class="stat">%d</div><span class="muted">Cross Edges</span></div>' % stats_data.get("total_edges", 0),
        "</div>",
        "<h4>Standards</h4>",
        '<div class="muted">',
        "&bull; <b>RDF / OWL:</b> Turtle, NT, JSON-LD, and OWL 2 Ontology.<br>",
        "&bull; <b>PROV-O:</b> W3C PROV Turtle, JSON, and OpenTelemetry OTLP traces.<br>",
        "&bull; <b>OKF Bundle:</b> Frontmatter + index.md layout with manifest hashes.<br>",
        "&bull; <b>Shared SQLite:</b> Certified-only cross-team read index.",
        "</div>",
    ]
    return "\n".join(out)


def federation_view(ctx, q, flash=None, error=None):
    db_p = shared_db_path(ctx.kb)
    tab = C.clean(q.get("tab")) or "kbs"
    exports = list_exports(ctx.kb)

    try:
        st = shared_index.stats(db_p)
    except Exception:
        st = {"total_kbs": 0, "kbs": [], "total_pages": 0, "total_objects": 0, "total_edges": 0}

    body = [
        "<h1>Federation & Exports</h1>",
        '<p class="lead">Cross-team knowledge federation, unified read indexing, and open standard exports.</p>',
    ]

    # ---- Tab: Registered KBs -----------------------------------------------------
    if tab == "kbs":
        body.append('<h2>Registered Knowledge Bases (%d)</h2>' % len(st.get("kbs", [])))
        if not st.get("kbs"):
            body.append('<div class="card soft">No KBs registered in the shared index yet. Register this KB below.</div>')
        else:
            rows = []
            for k in st["kbs"]:
                rows.append(
                    "<tr><td><b>%s</b></td><td><span class=\"pill\">%s</span></td><td>%d</td><td>%d</td><td>%d</td>"
                    "<td><span class=\"pill ok\">certified %s</span></td></tr>" % (
                        esc(k["name"]), esc(k["team"]), k["pages"], k["objects"], k["edges"], esc(k["certified_at"])))
            body.append("<table><tr><th>KB Name</th><th>Team</th><th>Pages</th><th>Objects</th><th>Edges</th><th>Status</th></tr>"
                        "%s</table>" % "".join(rows))

        # Register this KB Form
        reg_body = (
            field("kb_path", "KB Directory Path", ctx.kb, hint="Path to a certified knowledge base directory", required=True) +
            field("name", "KB Name (optional)", "", hint="Defaults to product.name from kb-profile.yaml") +
            "<p><button>Register KB into Shared Index</button></p>"
        )
        body.append('<div class="card"><h3 style="margin-top:0">Register Knowledge Base</h3>'
                    '<p class="muted">Only certified (locked, 0 uncertified changes) KBs without pending batches can be registered.</p>'
                    '%s</div>' % form(ctx, "/federation/register", reg_body))

        # Refresh Index Form
        ref_body = "<p><button class=\"alt\">Refresh Shared Index</button></p>"
        body.append(form(ctx, "/federation/refresh", ref_body))

    # ---- Tab: Cross-Team Search --------------------------------------------------
    elif tab == "search":
        sq = C.clean(q.get("query"))
        srch_form_body = (
            '<div class="row">'
            '<div style="flex:3">' + field("query", "Search Knowledge Across All Teams", sq, hint="Search pages, rules, definitions across certified KBs") + '</div>'
            '<div style="flex:1; align-self:flex-end; padding-bottom:8px;"><button>Search All KBs</button></div>'
            '</div>'
            '<input type="hidden" name="tab" value="search">'
        )
        body.append('<div class="card">%s</div>' % form(ctx, "/federation", srch_form_body, method="get"))

        if sq:
            try:
                hits = shared_index.search(db_p, sq, limit=25)
                body.append('<h2>Search Results for "%s" (%d)</h2>' % (esc(sq), len(hits)))
                if not hits:
                    body.append('<div class="card soft">No matching pages found across registered KBs.</div>')
                else:
                    rows = []
                    for h in hits:
                        rows.append(
                            "<tr><td><span class=\"pill blue\">%s</span><br><small class=\"muted\">%s</small></td>"
                            "<td><b>%s</b><br><small class=\"muted\">%s</small><p style=\"margin:4px 0;\">%s</p></td>"
                            "<td>%d tags</td></tr>" % (
                                esc(h["team"]), esc(h["kb_name"]), esc(h["title"]), esc(h["rel_path"]),
                                h["snippet"], h["tags_count"]))
                    body.append("<table><tr><th>Team / KB</th><th>Matching Page / Snippet</th><th>Citations</th></tr>%s</table>"
                                % "".join(rows))
            except Exception as e:
                body.append('<div class="err">Search error: %s</div>' % esc(str(e)))

    # ---- Tab: Cross-Team Impact --------------------------------------------------
    elif tab == "impact":
        node_arg = C.clean(q.get("node"))
        direction = C.clean(q.get("dir")) or "impact"

        impact_form_body = (
            '<div class="row">'
            '<div style="flex:3">' + field("node", "Graph Object (e.g. table:CLAIMS, CLAIMS, screen:PORTAL)", node_arg) + '</div>'
            '<div style="flex:1">'
            '<label for="dir">Direction</label>'
            '<select id="dir" name="dir">'
            '<option value="impact"%s>Downstream Impact (what moves)</option>' % (" selected" if direction == "impact" else "") +
            '<option value="upstream"%s>Upstream Dependency (what it depends on)</option>' % (" selected" if direction == "upstream" else "") +
            '</select></div>'
            '<div style="flex:1; align-self:flex-end; padding-bottom:8px;"><button>Trace Cross-Team Walk</button></div>'
            '</div>'
            '<input type="hidden" name="tab" value="impact">'
        )
        body.append('<div class="card">%s</div>' % form(ctx, "/federation", impact_form_body, method="get"))

        if node_arg:
            try:
                walk_fn = cross_impact.impact if direction == "impact" else cross_impact.upstream
                rows, cut = walk_fn(db_p, node_arg, depth=5)
                dir_label = "Downstream Impact" if direction == "impact" else "Upstream Dependencies"
                body.append('<h2>%s for "%s" (%d reached%s)</h2>' % (
                    dir_label, esc(node_arg), len(rows), "; stopped at limit" if cut else ""))

                if not rows:
                    body.append('<div class="card soft">No connected nodes found across registered KBs.</div>')
                else:
                    table_rows = []
                    for r in rows:
                        last = r["via"][-1]
                        orig_pill = '<span class="pill">%s</span>' % esc(last["origin"])
                        cross_pill = ' <span class="pill warn">cross-team</span>' if last.get("cross_team") else ""
                        table_rows.append(
                            "<tr><td><b>Level %d</b></td><td><span class=\"pill blue\">%s</span><br><small>%s</small></td>"
                            "<td><b>%s</b></td><td><code>%s</code> &rarr; <b>%s</b> &rarr; <code>%s</code></td>"
                            "<td>%s%s<br><small class=\"muted\">%s</small></td></tr>" % (
                                r["depth"], esc(r["team"]), esc(r["kb"]), esc(r["node"]),
                                esc(last["from"]), esc(last["rel"]), esc(last["to"]),
                                orig_pill, cross_pill, esc(last["source"])))
                    body.append("<table><tr><th>Depth</th><th>Owning Team / KB</th><th>Target Node</th><th>Step Link</th>"
                                "<th>Provenance</th></tr>%s</table>" % "".join(table_rows))
            except Exception as e:
                body.append('<div class="err">Impact walk error: %s</div>' % esc(str(e)))

    # ---- Tab: Export Artifacts ---------------------------------------------------
    elif tab == "exports":
        body.append("<h2>One-Click Knowledge Base Exports</h2>")
        body.append('<p class="muted">Generate standards-compliant exports directly into <code>.metis/exports/</code>.</p>')

        btn_row = (
            '<div class="row">'
            '<div class="card"><h3 style="margin-top:0">RDF / OWL Export</h3>'
            '<p class="muted"><small>Exports Turtle, N-Triples, JSON-LD, and OWL 2 Ontology with RDF-star-free provenance.</small></p>' +
            form(ctx, "/federation/export_rdf", '<button>Export RDF & OWL</button>') +
            '</div>'
            '<div class="card"><h3 style="margin-top:0">W3C PROV & OTel</h3>'
            '<p class="muted"><small>Exports W3C PROV-O (Turtle, PROV-JSON) and OpenTelemetry OTLP trace JSON.</small></p>' +
            form(ctx, "/federation/export_prov", '<button>Export PROV & OTel</button>') +
            '</div>'
            '<div class="card"><h3 style="margin-top:0">OKF Bundle</h3>'
            '<p class="muted"><small>Exports OKF-shaped Markdown bundle with frontmatter, index.md, and manifest.</small></p>' +
            form(ctx, "/federation/export_okf", '<button>Export OKF Bundle</button>') +
            '</div>'
            '</div>'
        )
        body.append(btn_row)

        body.append('<h2>Exported Files (%d)</h2>' % len(exports))
        if not exports:
            body.append('<div class="card soft">No exports generated yet. Click an export button above.</div>')
        else:
            rows = []
            for exp in exports:
                rows.append("<tr><td><b>%s</b></td><td>%s</td><td><code>.metis/exports/%s</code></td></tr>" % (
                    esc(os.path.basename(exp["path"])), format_bytes(exp["bytes"]), esc(exp["path"])))
            body.append("<table><tr><th>File Name</th><th>Size</th><th>Relative Path</th></tr>%s</table>" % "".join(rows))

    return page(
        ctx, "Federation", "/federation", "".join(body), flash, error,
        left=left_side(tab, len(exports), st.get("total_kbs", 0)),
        right=C.right_pane(right_side(db_p, st)),
    )


# ---- Actions ---------------------------------------------------------------------

def act_federation_register(ctx, f):
    need_user(ctx)
    kb_path = C.clean(f.get("kb_path")) or ctx.kb
    kb_name = C.clean(f.get("name"))
    db_p = shared_db_path(ctx.kb)

    try:
        res = shared_index.register(db_p, kb_path, name=kb_name)
        return "/federation?tab=kbs", "Successfully registered '%s' (%s) in shared index." % (res["name"], res["team"])
    except ValueError as err:
        raise C.UiError(str(err))


def act_federation_refresh(ctx, f):
    need_user(ctx)
    db_p = shared_db_path(ctx.kb)
    try:
        refreshed = shared_index.refresh(db_p)
        return "/federation?tab=kbs", "Refreshed %d registered knowledge bases." % len(refreshed)
    except ValueError as err:
        raise C.UiError(str(err))


def act_federation_export_rdf(ctx, f):
    need_user(ctx)
    out_dir = os.path.join(ctx.kb, ".metis", "exports", "rdf")
    written = export_rdf.export_all(ctx.kb, out_dir)
    return "/federation?tab=exports", "Exported %d RDF files (Turtle, NT, JSON-LD, OWL) to .metis/exports/rdf/." % len(written)


def act_federation_export_prov(ctx, f):
    need_user(ctx)
    out_dir = os.path.join(ctx.kb, ".metis", "exports", "prov")
    written = export_prov.export_all_prov(ctx.kb, out_dir)
    return "/federation?tab=exports", "Exported %d PROV files (Turtle, JSON, OTLP) to .metis/exports/prov/." % len(written)


def act_federation_export_okf(ctx, f):
    need_user(ctx)
    out_dir = os.path.join(ctx.kb, ".metis", "exports", "okf_bundle")
    out_path, count = okf_bundle.bundle(ctx.kb, out_dir)
    return "/federation?tab=exports", "Packaged %d files into OKF Bundle at .metis/exports/okf_bundle/." % count


SCREENS = {"/federation": federation_view}
ACTIONS = {
    "/federation/register": ("/federation", act_federation_register),
    "/federation/refresh": ("/federation", act_federation_refresh),
    "/federation/export_rdf": ("/federation", act_federation_export_rdf),
    "/federation/export_prov": ("/federation", act_federation_export_prov),
    "/federation/export_okf": ("/federation", act_federation_export_okf),
}
NAV = [("/federation", "Federation")]
