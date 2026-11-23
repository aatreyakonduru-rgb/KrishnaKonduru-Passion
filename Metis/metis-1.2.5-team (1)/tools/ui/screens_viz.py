"""Visualizations Hub screen for Metis UI.

Path /visualizations, nav label "Visuals".
Tabs/Views (query parameter view=):
- ontology: Entity types, property models & relationship schemas (from CROSS-LAYER/ONTOLOGY.yaml)
- matrix: Cross-layer impact matrix, relation directions, and entity linkages (from CROSS-LAYER/IMPACT_MATRIX.yaml)
- lineage: Column & table data flows with edge origins (from CROSS-LAYER/column.links.yaml / parsed links)
- erd: Relational database schema, keys, and table-to-table relationships
- stack: Technology stack components, frameworks, and detected repositories
- artifacts: Exported visualization files and artifacts inventory
"""
import os
import sys
import urllib.parse
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
for _p in (TOOLS, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import ui_common as C  # noqa: E402
from ui_common import esc, form, page  # noqa: E402

VIEWS = [
    ("ontology", "Ontology & Models", "Entity schemas & relations"),
    ("matrix", "KB Impact Matrix", "Cross-layer dependencies"),
    ("lineage", "Lineage & Data Flows", "Data flows & column links"),
    ("erd", "Database Schema & ERD", "Tables & foreign key relationships"),
    ("stack", "Tech Stack Topology", "Components & repository stack"),
    ("artifacts", "Visual Artifacts", "Generated visual files"),
]
VIEW_MAP = {k: (title, sub) for k, title, sub in VIEWS}


def load_yaml_file(path):
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            return yaml.safe_load(fh) or {}
    except Exception:
        return {}


def origin_pill(origin):
    origin = str(origin or "ai-proposed").lower()
    cls_ = "ok" if origin == "parsed" else ("blue" if origin == "catalogue" else "warn")
    return '<span class="pill %s">%s</span>' % (cls_, esc(origin))


def ontology_view(ctx):
    ont_path = os.path.join(ctx.kb, "CROSS-LAYER", "ONTOLOGY.yaml")
    ont = load_yaml_file(ont_path)

    out = [
        '<h1>Ontology & Domain Schema</h1>',
        '<p class="lead">Classification of knowledge-base entities, node types, and typed relationship schemas derived from sourced links.</p>',
    ]

    if not ont:
        out.append('<div class="card soft">No <code>CROSS-LAYER/ONTOLOGY.yaml</code> found. Build the KB or run <code>python tools/gen_graph.py %s</code>.</div>' % esc(ctx.kb))
        return "".join(out)

    nodes = ont.get("node_types") or {}
    rels = ont.get("relations") or {}
    total_nodes = sum(nodes.values())
    total_rels = sum(rels.values())

    out.append('<div class="grid" style="margin-bottom:18px;">')
    out.append('<div class="card"><div class="stat">%d</div><span class="muted">Entity Types</span></div>' % len(nodes))
    out.append('<div class="card"><div class="stat">%d</div><span class="muted">Total Entities</span></div>' % total_nodes)
    out.append('<div class="card"><div class="stat">%d</div><span class="muted">Relation Schemas</span></div>' % len(rels))
    out.append('<div class="card"><div class="stat">%d</div><span class="muted">Relation Instances</span></div>' % total_rels)
    out.append('</div>')

    out.append('<h2>Entity & Node Types (%d)</h2>' % len(nodes))
    node_rows = []
    for k, v in sorted(nodes.items(), key=lambda x: -x[1]):
        pct = (v / total_nodes * 100) if total_nodes else 0
        node_rows.append(
            '<tr><td><b>%s</b></td><td><code>%s</code></td><td><div class="bar"><i style="width:%.1f%%"></i></div> %d (%.1f%%)</td>'
            '<td><a class="btn alt" style="padding:1px 8px;font-size:11px" href="/map?layer=%s">View on Map &#8594;</a></td></tr>' % (
                esc(k.capitalize()), esc(k), pct, v, pct, esc(urllib.parse.quote(k.lower()))
            )
        )
    out.append('<table><tr><th>Node Type</th><th>Identifier Pattern</th><th>Volume</th><th>Action</th></tr>%s</table>' % "".join(node_rows))

    out.append('<h2>Typed Relationship Schemas (%d)</h2>' % len(rels))
    rel_rows = []
    for r, count in sorted(rels.items(), key=lambda x: -x[1]):
        parts = r.split(" -> ") if " -> " in r else [r]
        rel_rows.append('<tr><td><code>%s</code></td><td><b>%d</b> instances</td><td><span class="pill ok">verified schema</span></td></tr>' % (
            esc(r), count
        ))
    out.append('<table><tr><th>Relationship Schema</th><th>Occurrences</th><th>Status</th></tr>%s</table>' % "".join(rel_rows))

    return "".join(out)


def matrix_view(ctx, q):
    mat_path = os.path.join(ctx.kb, "CROSS-LAYER", "IMPACT_MATRIX.yaml")
    mat = load_yaml_file(mat_path)

    out = [
        '<h1>Cross-Layer Impact Matrix</h1>',
        '<p class="lead">Normalized dependency and ripple-effect matrix across system boundaries and architectural layers.</p>',
    ]

    if not mat:
        out.append('<div class="card soft">No <code>CROSS-LAYER/IMPACT_MATRIX.yaml</code> generated yet. Run <code>python tools/gen_matrix.py %s</code>.</div>' % esc(ctx.kb))
        return "".join(out)

    dirs = mat.get("directions") or {}
    entries = mat.get("entries") or {}
    flt = C.clean(q.get("f"))

    dir_badges = " ".join('<span class="pill" title="Direction: %s">%s: %s</span>' % (
        esc(d), esc(k), esc(d)) for k, d in sorted(dirs.items())[:12])
    out.append('<div class="card soft" style="margin-bottom:14px;"><small><b>Relation Directions:</b> %s</small></div>' % dir_badges)

    filter_form = form(ctx, "/visualizations",
                       '<input type="hidden" name="view" value="matrix">'
                       '<input type="text" name="f" value="%s" placeholder="Filter entities (e.g. endpoint, class, table)" style="width:280px"> '
                       '<button>Filter</button> %s' % (
                           esc(flt), '<a class="btn alt" href="/visualizations?view=matrix">Clear</a>' if flt else ""),
                       method="get")
    out.append(filter_form)

    filtered_entries = {}
    for k, v in entries.items():
        if not flt or flt.lower() in k.lower() or flt.lower() in str(v.get("type", "")).lower():
            filtered_entries[k] = v

    out.append('<h2>Impacted Entities (%d shown of %d)</h2>' % (len(filtered_entries), len(entries)))
    rows = []
    for k in sorted(filtered_entries.keys())[:100]:
        val = filtered_entries[k]
        typ = val.get("type", "object")
        moves = val.get("moves_by_type") or {}
        moves_summary = ", ".join("%s: %d" % (mk, len(mv)) for mk, mv in moves.items()) if moves else '<span class="muted">terminal (no downstream)</span>'
        rows.append(
            '<tr><td><code>%s</code></td><td><span class="pill">%s</span></td><td>%s</td>'
            '<td><a class="btn alt" style="padding:1px 6px;font-size:11px" href="/impact?node=%s">Trace Impact &#8594;</a></td></tr>' % (
                esc(k), esc(typ), moves_summary, esc(urllib.parse.quote(k, safe=""))
            )
        )

    out.append('<table><tr><th>Entity</th><th>Type</th><th>Downstream Impact Breakdown</th><th>Deep Walk</th></tr>%s</table>' % "".join(rows))
    if len(filtered_entries) > 100:
        out.append('<p class="muted">Showing first 100 entities. Use the filter box above to narrow down.</p>')

    return "".join(out)


def lineage_view(ctx):
    col_path = os.path.join(ctx.kb, "CROSS-LAYER", "column.links.yaml")
    links_data = load_yaml_file(col_path)
    links = links_data.get("links") or [] if isinstance(links_data, dict) else []

    out = [
        '<h1>Lineage & Data Flows</h1>',
        '<p class="lead">Fine-grained column-to-column data provenance and table-level transformations extracted from SQL queries and code.</p>',
    ]

    # Check for parsed links if column links are empty
    if not links:
        parsed_code = load_yaml_file(os.path.join(ctx.kb, "CROSS-LAYER", "parsed.code.links.yaml"))
        code_links = parsed_code.get("links") or [] if isinstance(parsed_code, dict) else []

        graph_links = load_yaml_file(os.path.join(ctx.kb, "CROSS-LAYER", "LINK_GRAPH.yaml"))
        all_edges = graph_links.get("edges") or [] if isinstance(graph_links, dict) else []

        display_links = code_links or all_edges

        if display_links:
            out.append('<h2>Data & Code Linkage Flows (%d)</h2>' % len(display_links))
            rows = []
            for l in display_links[:100]:
                src = l.get("from") or l.get("source")
                rel = l.get("rel") or l.get("relation") or "links to"
                tgt = l.get("to") or l.get("target")
                orig = l.get("origin") or "parsed"
                rows.append('<tr><td><code>%s</code></td><td><i>%s</i></td><td><code>%s</code></td><td>%s</td></tr>' % (
                    esc(src), esc(rel), esc(tgt), origin_pill(orig)))
            out.append('<table><tr><th>Source Entity</th><th>Relation</th><th>Target Entity</th><th>Origin</th></tr>%s</table>' % "".join(rows))
            return "".join(out)

        out.append('<div class="card soft">No lineage records found in <code>CROSS-LAYER/column.links.yaml</code>. Run <code>python tools/column_lineage.py %s</code>.</div>' % esc(ctx.kb))
        return "".join(out)

    out.append('<h2>Column Data Flows (%d)</h2>' % len(links))
    rows = []
    for l in links[:100]:
        rows.append('<tr><td><code>%s</code></td><td><i>%s</i></td><td><code>%s</code></td><td>%s</td></tr>' % (
            esc(l.get("from")), esc(l.get("rel")), esc(l.get("to")), origin_pill(l.get("origin", "parsed"))))
    out.append('<table><tr><th>From Column / Table</th><th>Relation</th><th>To Column / Target</th><th>Origin</th></tr>%s</table>' % "".join(rows))
    return "".join(out)


def erd_view(ctx):
    graph_path = os.path.join(ctx.kb, "CROSS-LAYER", "LINK_GRAPH.yaml")
    graph = load_yaml_file(graph_path)

    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []

    tables = [n["name"] for n in nodes if n.get("type") in ("table", "view")]
    table_edges = [e for e in edges if e.get("rel") in ("references", "reads", "stored in", "joins", "writes") or
                   any(e.get("from", "").startswith("table:") or e.get("to", "").startswith("table:") for _ in [1])]

    out = [
        '<h1>Database Schema & Entity-Relationship Model</h1>',
        '<p class="lead">Relational schema structure, tables, declared primary/foreign keys, and data relationships.</p>',
    ]

    out.append('<div class="grid" style="margin-bottom:18px;">')
    out.append('<div class="card"><div class="stat">%d</div><span class="muted">Tables & Views</span></div>' % len(tables))
    out.append('<div class="card"><div class="stat">%d</div><span class="muted">Relational Joins & FKeys</span></div>' % len(table_edges))
    out.append('</div>')

    if not tables:
        out.append('<div class="card soft">No database tables or relationships recorded in the link graph yet.</div>')
        return "".join(out)

    out.append('<h2>Tables & Data Entities (%d)</h2>' % len(tables))
    t_rows = []
    for t in sorted(tables):
        t_rows.append('<tr><td><b><code>%s</code></b></td><td><a class="btn alt" style="padding:1px 8px;font-size:11px" href="/impact?node=table:%s">Trace Table Impact &#8594;</a></td></tr>' % (
            esc(t), esc(urllib.parse.quote(t, safe=""))
        ))
    out.append('<table><tr><th>Table Name</th><th>Impact & Lineage</th></tr>%s</table>' % "".join(t_rows))

    if table_edges:
        out.append('<h2>Relational Foreign Keys & Joins (%d)</h2>' % len(table_edges))
        e_rows = []
        for e in table_edges[:100]:
            e_rows.append('<tr><td><code>%s</code></td><td><b>%s</b></td><td><code>%s</code></td><td>%s</td><td><small class="muted">%s</small></td></tr>' % (
                esc(e.get("from")), esc(e.get("rel")), esc(e.get("to")), origin_pill(e.get("origin")), esc(e.get("source", "")[:90])
            ))
        out.append('<table><tr><th>From Table / Column</th><th>Relation</th><th>To Table / Target</th><th>Origin</th><th>Source Tag</th></tr>%s</table>' % "".join(e_rows))

    return "".join(out)


def stack_view(ctx):
    prof = C.profile(ctx.kb)
    sources = prof.get("sources") or {}
    repos = sources.get("repos") or {}

    out = [
        '<h1>Technology Stack & Topology</h1>',
        '<p class="lead">Detected programming languages, application frameworks, databases, and repository configurations.</p>',
    ]

    out.append('<h2>Repositories & Components (%d)</h2>' % len(repos))
    if repos:
        repo_rows = []
        for rk, rv in sorted(repos.items()):
            repo_rows.append('<tr><td><b>%s</b></td><td><code>%s</code></td><td>%s</td><td><span class="pill ok">active source</span></td></tr>' % (
                esc(rk), esc(rv.get("path") or rv.get("folder") or rk), esc(rv.get("stack", "general source"))
            ))
        out.append('<table><tr><th>Component / Repo</th><th>Path</th><th>Stack Detected</th><th>Status</th></tr>%s</table>' % "".join(repo_rows))
    else:
        out.append('<div class="card soft">No repositories configured under <code>sources.repos</code> in <code>kb-profile.yaml</code>.</div>')

    # Databases configured
    db_envs = C.load_yaml(os.path.join(ctx.kb, ".metis", "db-environments.yaml"))
    envs = db_envs.get("environments") or {}
    if envs:
        out.append('<h2>Database Environments (%d)</h2>' % len(envs))
        env_rows = []
        for ek, ev in sorted(envs.items()):
            eng = ev.get("engine", "database")
            host = ev.get("host") or ev.get("account") or "configured"
            env_rows.append('<tr><td><b>%s</b></td><td><code>%s</code></td><td>%s</td></tr>' % (esc(ek), esc(eng), esc(host)))
        out.append('<table><tr><th>Environment</th><th>Engine</th><th>Host / Target</th></tr>%s</table>' % "".join(env_rows))

    return "".join(out)


def artifacts_view(ctx):
    viz_dir = os.path.join(ctx.kb, "VISUALIZATION")
    files = sorted(os.listdir(viz_dir)) if os.path.isdir(viz_dir) else []
    html_files = [f for f in files if f.endswith(".html")]

    out = [
        '<h1>Visual Artifacts & Downloads</h1>',
        '<p class="lead">Collection of standalone HTML visual documents and exported artifacts generated by build tools.</p>',
    ]

    if not html_files:
        out.append('<div class="card soft">No HTML visualization artifacts found in <code>VISUALIZATION/</code>.</div>')
        return "".join(out)

    rows = []
    for hf in html_files:
        fp = os.path.join(viz_dir, hf)
        sz = os.path.getsize(fp) if os.path.isfile(fp) else 0
        name = os.path.splitext(hf)[0].replace("_", " ").title()
        url = "/viz/" + urllib.parse.quote(hf)
        rows.append(
            '<tr><td><b>%s</b></td><td><code>VISUALIZATION/%s</code></td><td>%.1f KB</td>'
            '<td><a class="btn" href="%s" target="_blank">Open Standalone &#8599;</a></td></tr>' % (
                esc(name), esc(hf), sz / 1024.0, esc(url)
            )
        )

    out.append('<table><tr><th>Artifact</th><th>File Location</th><th>Size</th><th>Action</th></tr>%s</table>' % "".join(rows))
    return "".join(out)


def visualizations_view(ctx, q, flash=None, error=None):
    v = C.clean(q.get("view")) or "ontology"
    if v not in VIEW_MAP:
        v = "ontology"

    if v == "ontology":
        body = ontology_view(ctx)
    elif v == "matrix":
        body = matrix_view(ctx, q)
    elif v == "lineage":
        body = lineage_view(ctx)
    elif v == "erd":
        body = erd_view(ctx)
    elif v == "stack":
        body = stack_view(ctx)
    elif v == "artifacts":
        body = artifacts_view(ctx)
    else:
        body = ontology_view(ctx)

    # Left navigation pane
    left_items = []
    for key, title, sub in VIEWS:
        left_items.append(C.pane_item("/visualizations?view=%s" % key, esc(title), esc(sub), on=(key == v)))
    left = C.left_pane("Visualizations", "".join(left_items))

    # Right inspector pane
    right_content = [
        '<h4>Visualizations</h4>',
        '<div class="muted">Live domain schemas, entity-relationship models, and cross-layer impact matrices.</div>',
        '<h4>Quick Explorers</h4>',
        '<p><a href="/map"><b>&#9673; Interactive KB Map</b></a><br><small class="muted">Radial SVG graph explorer</small></p>',
        '<p><a href="/impact"><b>&#8644; Impact Explorer</b></a><br><small class="muted">Multi-hop ripple traversal</small></p>',
        '<p><a href="/files"><b>&#9776; KB Files Reader</b></a><br><small class="muted">Lineage & citations</small></p>',
        '<h4>Origin Verification</h4>',
        '<div class="muted">Edges are tagged with verifiable origins: <code>parsed</code> (compiler/AST), <code>catalogue</code> (DB schema), and <code>ai-proposed</code>.</div>'
    ]
    right = C.right_pane("".join(right_content))

    return page(ctx, "Visualizations", "/visualizations", body, flash, error, left=left, right=right)


SCREENS = {
    "/visualizations": visualizations_view,
    "/viz-hub": visualizations_view,
}
ACTIONS = {}
NAV = [("/visualizations", "Visuals")]
