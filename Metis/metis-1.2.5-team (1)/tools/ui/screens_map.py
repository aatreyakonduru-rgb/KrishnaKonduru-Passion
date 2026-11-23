"""Map and impact screens for Metis UI: the whole-KB link graph, without JavaScript.

/map     Layer tabs (Sources, Tables, Jobs, APIs, Screens, Other), a clustered overview of the whole KB, a neighbourhood view of
         one object (1-3 hops) drawn as server-side SVG, a list view of the same, and a search box for an object.
/impact  What changes if one object changes (graph_store.impact, the same walk context_pack.py uses) and what it depends on
         (graph_store.upstream), each step with its origin, source tag and the raw trust signals from trust.py.

The layers come from the node types in CROSS-LAYER/LINK_GRAPH.yaml (gen_graph.py), through the SQLite copy graph_store.py keeps:
Tables = table, view, column; Jobs = job; APIs = endpoint, api, service; Screens = screen, component; Sources = class, file, repo,
module, test, document; every other type is Other. Edges are drawn by where the link came from: parsed solid, catalogue dashed,
ai-proposed dotted (anything else: sparse dots, in another weight).

A whole KB can hold far more objects than a page can show, so the overview draws one block per layer and folder (counts only, with
the number of links between blocks as the line weight) and a block opens its objects. A neighbourhood draws at most 300 objects,
nearest first, and says "Showing N of M". The layout is computed here, in Python, with no random step: the same graph always gives
the same picture (radial rings when each ring is small enough, else one column per hop).
"""
import math
import os
import re
import sqlite3
import sys
import urllib.parse

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
for _p in (TOOLS, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import graph_store  # noqa: E402
import ui_common as C  # noqa: E402
from ui_common import esc, form, page  # noqa: E402

MAX_SHOWN = 300          # objects drawn or listed at once
MAX_SEEN = 5000          # a neighbourhood walk stops counting here and says "N+"
MAX_GROUPS_LAYER = 14    # blocks per layer in the whole-KB overview (40 when one layer is open)
MAX_GROUP_LINKS = 200    # lines between blocks
MAX_IMPACT_ROWS = 300
NODE_W, NODE_H = 150, 34
LAYERS = [("sources", "Sources"), ("tables", "Tables"), ("jobs", "Jobs"), ("apis", "APIs"), ("screens", "Screens"), ("other", "Other")]
LAYER_NAME = dict(LAYERS)
LAYER_COLOUR = {"sources": "#7c5cd8", "tables": "#2e9e5b", "jobs": "#d9822b", "apis": "#3b82d4", "screens": "#c2418b", "other": "#8b95a7"}
TYPE_LAYER = {"table": "tables", "view": "tables", "column": "tables", "job": "jobs", "endpoint": "apis", "api": "apis",
              "service": "apis", "screen": "screens", "component": "screens", "class": "sources", "file": "sources",
              "repo": "sources", "module": "sources", "document": "sources", "doc": "sources", "test": "sources", "source": "sources"}
ORIGIN_DASH = {"parsed": "", "catalogue": "7 4", "ai-proposed": "2 3"}
ORIGIN_PILL = {"parsed": "ok", "catalogue": "blue", "ai-proposed": "warn"}
NO_FOLDER = "(no folder)"


class NoGraph(C.UiError):
    """There is no link graph to draw yet."""


# ---- reading the graph -----------------------------------------------------------------------------
def norm_type(t):
    return " ".join(str(t or "").lower().replace("_", " ").replace("-", " ").split())


def layer_of(t):
    return TYPE_LAYER.get(norm_type(t), "other")


def group_of(name):
    """The folder of an object: 'APP' for APP.ORDERS, 'orders' for GET /orders/{id}, 'api' for api/src/A.java."""
    s = str(name or "").strip()
    m = re.match(r"^[A-Za-z]{3,7}\s+(/.*)$", s)
    if m:
        s = m.group(1)
    if "/" in s:
        parts = [p for p in s.split("/") if p]
        return parts[0] if parts else NO_FOLDER
    if "." in s:
        return s.split(".")[0] or NO_FOLDER
    return NO_FOLDER


def open_graph(kb):
    """A sqlite connection to the graph_store copy, rebuilt first when LINK_GRAPH.yaml is newer."""
    yml = os.path.join(kb, "CROSS-LAYER", "LINK_GRAPH.yaml")
    db = graph_store.db_path(kb)
    if not os.path.isfile(yml) and not os.path.isfile(db):
        raise NoGraph("There is no link graph yet. A build writes CROSS-LAYER/LINK_GRAPH.yaml (gen_graph.py) from the *.links.yaml files.")
    try:
        if os.path.isfile(yml) and (not os.path.isfile(db) or os.path.getmtime(yml) > os.path.getmtime(db)):
            graph_store.build(kb)
        return graph_store.connect(kb)
    except (SystemExit, OSError, sqlite3.Error, yaml.YAMLError, KeyError, TypeError) as err:
        raise NoGraph("The link graph cannot be read: %s" % (err if str(err) else type(err).__name__))


_OVERVIEW = {}


def overview(kb):
    """{layers: {layer: object count}, groups: {(layer, folder): count}, links: {(a, b): count}, nodes, edges}, cached per graph file."""
    con = open_graph(kb)
    try:
        st = os.stat(graph_store.db_path(kb))
        key = (st.st_mtime_ns, st.st_size)
        hit = _OVERVIEW.get(kb)
        if hit and hit[0] == key:
            return hit[1]
        where, groups, layers = {}, {}, {}
        for nid, typ, name in con.execute("select id, type, name from nodes"):
            lay, grp = layer_of(typ), group_of(name)
            where[nid] = (lay, grp)
            groups[(lay, grp)] = groups.get((lay, grp), 0) + 1
            layers[lay] = layers.get(lay, 0) + 1
        links, inner, n_edges = {}, 0, 0
        for s, d in con.execute("select src, dst from edges"):
            n_edges += 1
            a, b = where.get(s), where.get(d)
            if not a or not b:
                continue
            if a == b:
                inner += 1
            else:
                links[(a, b)] = links.get((a, b), 0) + 1
        data = {"layers": layers, "groups": groups, "links": links, "nodes": len(where), "edges": n_edges, "inner": inner}
        _OVERVIEW[kb] = (key, data)
        return data
    finally:
        con.close()


def like(text):
    return "%" + str(text).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def find_nodes(con, text, limit=50):
    rows = con.execute("select id, type, name from nodes where id like ? escape '\\' or name like ? escape '\\' order by id limit ?",
                       (like(text), like(text), limit + 1)).fetchall()
    return rows[:limit], len(rows) > limit


def node_row(con, nid):
    return con.execute("select id, type, name from nodes where id=?", (nid,)).fetchone()


EDGES_OF = "select src, rel, dst, source, origin from edges where src=? or dst=? order by n"


def neighbourhood(con, center, hops):
    """Everything within `hops` links of `center`, either direction: ({id: hops}, {(src, dst, origin): {rels, sources}}, cut)."""
    depth_of, edges, frontier, cut = {center: 0}, {}, [center], False

    def take(n):
        for src, rel, dst, source, origin in con.execute(EDGES_OF, (n, n)):
            e = edges.setdefault((src, dst, origin or "unknown"), {"rels": [], "sources": []})
            if rel not in e["rels"]:
                e["rels"].append(rel)
            if source and source not in e["sources"]:
                e["sources"].append(source)
            yield dst if src == n else src

    for d in range(1, hops + 1):
        nxt = []
        for n in frontier:
            for other in take(n):
                if other in depth_of:
                    continue
                if len(depth_of) >= MAX_SEEN:
                    cut = True
                    continue
                depth_of[other] = d
                nxt.append(other)
        frontier = sorted(set(nxt))
    for n in frontier:  # links among the outermost objects: no new objects
        for _ in take(n):
            pass
    return depth_of, edges, cut


# ---- SVG pieces ------------------------------------------------------------------------------------
def short(text, n):
    t = str(text)
    return t if len(t) <= n else t[:n - 1] + "\u2026"


def num(x):
    return ("%.1f" % x).rstrip("0").rstrip(".")


def clip(cx, cy, w, h, tx, ty):
    """The point where the line from the centre of a w x h box towards (tx, ty) leaves the box."""
    dx, dy = tx - cx, ty - cy
    if dx == 0 and dy == 0:
        return cx, cy
    s = min((w / 2.0) / abs(dx) if dx else float("inf"), (h / 2.0) / abs(dy) if dy else float("inf"))
    return cx + dx * s, cy + dy * s


def svg_open(w, h, label):
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" role="img" aria-label="%s">'
            '<defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
            '<path d="M0,0 L10,5 L0,10 z" style="fill:var(--muted)"/></marker></defs>' % (w, h, w, h, esc(label)))


def line_svg(p, origin, weight=1.5, title=""):
    dash = ORIGIN_DASH.get(origin, "1 4")
    return ('<g><title>%s</title><path d="%s" style="fill:none;stroke:var(--muted);stroke-width:%s" %smarker-end="url(#arr)"/></g>' % (
        esc(title), p, num(weight), 'stroke-dasharray="%s" ' % dash if dash else ""))


def straight(a, b):
    """Path from box a to box b, each (cx, cy, w, h), leaving and entering at their borders."""
    x1, y1 = clip(a[0], a[1], a[2], a[3], b[0], b[1])
    x2, y2 = clip(b[0], b[1], b[2], b[3], a[0], a[1])
    return "M%s,%s L%s,%s" % (num(x1), num(y1), num(x2), num(y2))


def arc_right(a, b):
    """Path between two boxes in one column: out of the right side and back in, so it does not run through the boxes between."""
    x1, y1 = a[0] + a[2] / 2.0, a[1]
    x2, y2 = b[0] + b[2] / 2.0, b[1]
    bulge = 28 + min(60, abs(y2 - y1) / 6.0)
    return "M%s,%s C%s,%s %s,%s %s,%s" % (num(x1), num(y1), num(x1 + bulge), num(y1), num(x2 + bulge), num(y2), num(x2), num(y2))


def link_for(**kw):
    return "/map?" + urllib.parse.urlencode([(k, v) for k, v in kw.items() if v not in ("", None)])


def node_svg(box, nid, typ, name, center, hops):
    cx, cy, w, h = box
    x, y = cx - w / 2.0, cy - h / 2.0
    col = LAYER_COLOUR[layer_of(typ)]
    return ('<a href="%s"><g><title>%s (%s)</title><rect x="%s" y="%s" width="%d" height="%d" rx="5" '
            'style="fill:var(--soft);stroke:%s;stroke-width:%s"/><rect x="%s" y="%s" width="5" height="%d" style="fill:%s"/>'
            '<text x="%s" y="%s" style="font-size:11px;font-weight:%s;fill:var(--fg)">%s</text>'
            '<text x="%s" y="%s" style="font-size:9px;fill:var(--muted)">%s</text></g></a>' % (
                esc(link_for(center=nid, hops=hops)), esc(nid), esc(typ), num(x), num(y), w, h, col, 3 if center else 1.2,
                num(x), num(y), h, col, num(x + 11), num(y + 14), 700 if center else 400, esc(short(name, 22)),
                num(x + 11), num(y + 27), esc(short(typ, 26))))


def layout_neighbourhood(depth_of, shown, meta, hops):
    """{id: (cx, cy, w, h)} and the mode name. Radial rings when every ring is small enough to read, else one column per hop."""
    by_depth = {}
    for nid in shown:
        by_depth.setdefault(depth_of[nid], []).append(nid)
    for lst in by_depth.values():
        lst.sort(key=lambda i: ([x for x, _ in LAYERS].index(layer_of(meta[i][0])), i))
    top = max(by_depth)
    ring = [0, 190, 380, 570]
    radial = all(len(by_depth.get(d, [])) <= max(1, int(2 * math.pi * ring[d] / 135)) for d in range(1, top + 1))
    boxes = {}
    if radial:
        size = int(2 * (ring[top] + NODE_W / 2 + 24))
        cx = cy = size / 2.0
        boxes[shown[0]] = (cx, cy, NODE_W, NODE_H)
        for d in range(1, top + 1):
            ids = by_depth.get(d, [])
            for i, nid in enumerate(ids):
                a = -math.pi / 2 + 2 * math.pi * i / len(ids)
                boxes[nid] = (cx + ring[d] * math.cos(a), cy + ring[d] * math.sin(a), NODE_W, NODE_H)
        return boxes, "radial", size, size
    gap_x, gap_y = 90, 12
    tall = max(len(v) for v in by_depth.values())
    height = tall * (NODE_H + gap_y) + 24
    for d in range(0, top + 1):
        ids = by_depth.get(d, [])
        y0 = (height - len(ids) * (NODE_H + gap_y)) / 2.0 + gap_y / 2.0 if d == 0 else 12
        for i, nid in enumerate(ids):
            boxes[nid] = (20 + NODE_W / 2.0 + d * (NODE_W + gap_x), y0 + NODE_H / 2.0 + i * (NODE_H + gap_y), NODE_W, NODE_H)
    return boxes, "layered", 40 + (top + 1) * NODE_W + top * gap_x, height


def neighbourhood_svg(center, shown, depth_of, meta, edges, hops):
    boxes, mode, w, h = layout_neighbourhood(depth_of, shown, meta, hops)
    keep = set(shown)
    out = [svg_open(w, h, "Objects within %d hop(s) of %s" % (hops, center))]
    for (s, d, origin), e in edges.items():
        if s not in keep or d not in keep or s == d:
            continue
        a, b = boxes[s], boxes[d]
        p = arc_right(a, b) if mode == "layered" and depth_of[s] == depth_of[d] else straight(a, b)
        out.append(line_svg(p, origin, 1.5, "%s -%s-> %s [%s]" % (s, ", ".join(e["rels"]), d, origin)))
    for nid in shown:
        typ, name = meta[nid]
        out.append(node_svg(boxes[nid], nid, typ, name, nid == center, hops))
    out.append("</svg>")
    return "".join(out), mode


def overview_svg(data, layer):
    """One column per layer, one block per folder (largest first); lines between blocks weigh the number of links."""
    cap = 40 if layer else MAX_GROUPS_LAYER
    cols, total_groups = [], 0
    for key, _ in LAYERS:
        if layer and key != layer:
            continue
        gs = sorted(((g, n) for (lay, g), n in data["groups"].items() if lay == key), key=lambda x: (-x[1], x[0]))
        total_groups += len(gs)
        if gs:
            cols.append((key, gs[:cap], len(gs)))
    bw, gap_x, gap_y, top = 170, 120, 12, 44
    pos, y_max = {}, top
    for ci, (key, gs, _) in enumerate(cols):
        y = top
        for g, n in gs:
            hh = 34 + min(44, int(7 * math.log2(n + 1)))
            pos[(key, g)] = (24 + ci * (bw + gap_x), y, bw, hh)
            y += hh + gap_y
        y_max = max(y_max, y)
    width = max(300, 48 + len(cols) * bw + max(0, len(cols) - 1) * gap_x)
    out = [svg_open(width, y_max + 12, "Layers and folders of the knowledge base")]
    seen = [(w, a, b) for (a, b), w in data["links"].items() if a in pos and b in pos]
    seen.sort(key=lambda t: (-t[0], t[1], t[2]))
    drawn = seen[:MAX_GROUP_LINKS]
    col_of = {key: i for i, (key, _, _) in enumerate(cols)}
    for w, a, b in sorted(drawn, key=lambda t: (t[1], t[2])):
        pa, pb = pos[a], pos[b]
        ya, yb = pa[1] + pa[3] / 2.0, pb[1] + pb[3] / 2.0
        if col_of[a[0]] < col_of[b[0]]:
            x1, x2, dx = pa[0] + pa[2], pb[0], 40
        elif col_of[a[0]] > col_of[b[0]]:
            x1, x2, dx = pa[0], pb[0] + pb[2], -40
        else:
            x1, x2, dx = pa[0] + pa[2], pb[0] + pb[2], 44
        p = "M%s,%s C%s,%s %s,%s %s,%s" % (num(x1), num(ya), num(x1 + dx), num(ya), num(x2 - dx if dx != 44 else x2 + dx), num(yb), num(x2), num(yb))
        out.append('<g><title>%s -> %s: %d link(s)</title><path d="%s" marker-end="url(#arr)" style="fill:none;stroke:var(--muted);'
                   'stroke-width:%s;opacity:.75"/></g>' % (esc("%s / %s" % (LAYER_NAME[a[0]], a[1])), esc("%s / %s" % (LAYER_NAME[b[0]], b[1])),
                                                          w, p, num(1 + math.log2(w))))
    for key, gs, n_all in cols:
        x = pos[(key, gs[0][0])][0]
        out.append('<a href="%s"><text x="%s" y="24" style="font-size:12px;font-weight:700;fill:var(--fg)">%s</text></a>' % (
            esc(link_for(layer=key)), x, esc("%s (%d object%s)" % (LAYER_NAME[key], data["layers"].get(key, 0), "" if data["layers"].get(key) == 1 else "s"))))
        for g, n in gs:
            bx, by, bw_, bh = pos[(key, g)]
            out.append('<a href="%s"><g><title>%s</title><rect x="%d" y="%d" width="%d" height="%d" rx="6" '
                       'style="fill:var(--soft);stroke:%s;stroke-width:1.5"/><rect x="%d" y="%d" width="6" height="%d" style="fill:%s"/>'
                       '<text x="%d" y="%d" style="font-size:12px;font-weight:600;fill:var(--fg)">%s</text>'
                       '<text x="%d" y="%d" style="font-size:11px;fill:var(--muted)">%d object%s</text></g></a>' % (
                           esc(link_for(layer=key, folder=g)), esc("%s / %s: %d object(s)" % (LAYER_NAME[key], g, n)), bx, by, bw_, bh,
                           LAYER_COLOUR[key], bx, by, bh, LAYER_COLOUR[key], bx + 14, by + 18, esc(short(g, 22)), bx + 14, by + 33, n,
                           "" if n == 1 else "s"))
    out.append("</svg>")
    shown_groups = sum(len(gs) for _, gs, _ in cols)
    return "".join(out), shown_groups, total_groups, len(drawn), len(seen)


def legend():
    def sample(dash):
        return ('<svg width="44" height="10" viewBox="0 0 44 10" aria-hidden="true"><path d="M2,5 L42,5" style="fill:none;stroke:var(--muted);'
                'stroke-width:1.5" %s/></svg>' % ('stroke-dasharray="%s"' % dash if dash else ""))
    rows = [("parsed (a program read it)", ""), ("catalogue (a database catalogue)", ORIGIN_DASH["catalogue"]),
            ("ai-proposed (a model wrote it)", ORIGIN_DASH["ai-proposed"]), ("unknown origin", "1 4")]
    return ('<h4>Line style = where the link came from</h4><table>%s</table>'
            '<p class="muted"><small>An arrow points from the object that has the link to the object it names. '
            'A solid line is not "true": it only says a program read it.</small></p>' % "".join(
                "<tr><td>%s</td><td>%s</td></tr>" % (sample(d), esc(t)) for t, d in rows))


# ---- list pieces -----------------------------------------------------------------------------------
def origin_pill(origin):
    return '<span class="pill %s">%s</span>' % (ORIGIN_PILL.get(origin, "no"), esc(origin or "unknown"))


def obj_link(nid, hops=1, impact=False):
    path = "/impact?node=%s" % urllib.parse.quote(nid, safe="") if impact else link_for(center=nid, hops=hops)
    return '<a href="%s">%s</a>' % (esc(path), esc(nid))


def left_side(ctx, data, layer, center_layer=""):
    sel = layer or center_layer
    items = [C.pane_item("/map", "Whole KB", "%d objects, %d links" % (data["nodes"], data["edges"]), on=not sel and not center_layer)]
    for key, label in LAYERS:
        n = data["layers"].get(key, 0)
        if n or key == sel:
            items.append(C.pane_item(link_for(layer=key), esc(label), "%d object%s" % (n, "" if n == 1 else "s"), on=(key == sel)))
    search = form(ctx, "/map", '<input type="text" name="q" placeholder="Find an object" aria-label="Find an object">', method="get", cls="flt")
    return C.left_pane("Layers", "".join(items), top=search)


def placeholder_left(ctx):
    search = form(ctx, "/map", '<input type="text" name="q" placeholder="Find an object" aria-label="Find an object">', method="get", cls="flt")
    return C.left_pane("Layers", '<div class="it muted">No link graph yet.</div>', top=search)


# ---- /map ------------------------------------------------------------------------------------------
def clamp(v, lo, hi, default):
    try:
        return min(max(int(v), lo), hi)
    except (TypeError, ValueError):
        return default


def search_html(con, text):
    rows, more = find_nodes(con, text)
    if not rows:
        return '<div class="card soft">No object has "%s" in its id or name.</div>' % esc(text)
    trs = "".join("<tr><td>%s</td><td>%s</td><td>%s</td></tr>" % (obj_link(i), esc(t), esc(LAYER_NAME[layer_of(t)])) for i, t, _ in rows)
    return ("<h2>Objects matching &quot;%s&quot;</h2><table><tr><th>Object</th><th>Type</th><th>Layer</th></tr>%s</table>%s" % (
        esc(text), trs, '<p class="muted">Showing the first %d matches; type more to narrow them.</p>' % len(rows) if more else ""))


def group_html(con, data, layer, folder):
    total = data["groups"].get((layer, folder), 0)
    rows = []
    for nid, typ, name in con.execute("select id, type, name from nodes order by id"):
        if layer_of(typ) == layer and group_of(name) == folder:
            rows.append((nid, typ))
            if len(rows) >= MAX_SHOWN:
                break
    trs = "".join("<tr><td>%s</td><td>%s</td></tr>" % (obj_link(i), esc(t)) for i, t in rows)
    note = ('<p class="muted">Showing %d of %d objects in this folder. Open one, or search for the rest.</p>' % (len(rows), total)
            if total > len(rows) else '<p class="muted">Showing all %d objects in this folder.</p>' % total)
    return ('<h1>%s / %s</h1><p class="lead">%s</p>%s<table><tr><th>Object</th><th>Type</th></tr>%s</table>' % (
        esc(LAYER_NAME[layer]), esc(folder), '<a href="%s">Back to %s</a>' % (esc(link_for(layer=layer)), esc(LAYER_NAME[layer])), note, trs))


def overview_html(data, layer):
    svg, shown_g, total_g, drawn, links = overview_svg(data, layer)
    title = LAYER_NAME[layer] if layer else "The whole knowledge base"
    body = ['<h1>%s</h1>' % esc(title),
            '<p class="lead">%d objects and %d links. Each block is one folder of one layer; the line weight is the number of links '
            'between two blocks. Click a block to see its objects.</p>' % (
                data["layers"].get(layer, 0) if layer else data["nodes"], data["edges"])]
    if not total_g:
        body.append('<div class="card soft">The link graph has no objects in this layer.</div>')
        return "".join(body)
    note = "Showing %d of %d folders" % (shown_g, total_g)
    if shown_g < total_g:
        note += " (the largest in each layer; search for an object to reach the rest)"
    if drawn < links:
        note += ". Showing the %d heaviest of %d lines between blocks" % (drawn, links)
    body.append('<p class="muted">%s.</p><div class="tscroll card soft">%s</div>' % (esc(note), svg))
    rows = sorted(((lay, g, n) for (lay, g), n in data["groups"].items() if not layer or lay == layer),
                  key=lambda t: ([k for k, _ in LAYERS].index(t[0]), -t[2], t[1]))
    trs = "".join('<tr><td>%s</td><td><a href="%s">%s</a></td><td>%d</td></tr>' % (
        esc(LAYER_NAME[lay]), esc(link_for(layer=lay, folder=g)), esc(g), n) for lay, g, n in rows[:MAX_SHOWN])
    body.append("<h2>List of folders</h2><table><tr><th>Layer</th><th>Folder</th><th>Objects</th></tr>%s</table>" % trs)
    if len(rows) > MAX_SHOWN:
        body.append('<p class="muted">Showing %d of %d folders.</p>' % (MAX_SHOWN, len(rows)))
    if layer:
        out = {}
        for (a, b), w in data["links"].items():
            if a[0] == layer and b[0] != layer:
                out[("to", b[0])] = out.get(("to", b[0]), 0) + w
            elif b[0] == layer and a[0] != layer:
                out[("from", a[0])] = out.get(("from", a[0]), 0) + w
        if out:
            body.append("<h2>Links to other layers</h2><table><tr><th>Direction</th><th>Layer</th><th>Links</th></tr>%s</table>" % "".join(
                '<tr><td>%s</td><td><a href="%s">%s</a></td><td>%d</td></tr>' % ("from this layer to" if d == "to" else "into this layer from",
                                                                             esc(link_for(layer=k)), esc(LAYER_NAME[k]), n)
                for (d, k), n in sorted(out.items(), key=lambda t: (-t[1], t[0]))))
    return "".join(body)


def neighbourhood_html(ctx, con, center, hops, view):
    row = node_row(con, center)
    if not row:
        raise C.UiError("There is no object %r in the link graph. Search for it below." % center)
    depth_of, edges, cut = neighbourhood(con, center, hops)
    order = sorted(depth_of, key=lambda i: (depth_of[i], i))
    meta = {}
    for nid in order[:MAX_SHOWN]:
        r = node_row(con, nid)
        meta[nid] = (r[1], r[2]) if r else ("?", nid)
    shown = [i for i in order[:MAX_SHOWN] if i in meta]
    total = len(depth_of)
    more = "+" if cut else ""
    hop_links = " ".join('<a class="btn%s" href="%s">%d hop%s</a>' % ("" if h == hops else " alt", esc(link_for(center=center, hops=h, view=view)), h,
                                                                       "" if h == 1 else "s") for h in (1, 2, 3))
    base = link_for(center=center, hops=hops)
    body = ['<h1>%s</h1>' % esc(row[2]),
            '<p class="lead"><code>%s</code> &middot; %s &middot; layer %s &middot; <a href="/impact?node=%s">what changes if it changes</a></p>' % (
                esc(center), esc(row[1]), esc(LAYER_NAME[layer_of(row[1])]), esc(urllib.parse.quote(center, safe=""))),
            "<p>%s &nbsp; %s</p>" % (hop_links, " ".join('<a class="btn%s" href="%s">%s</a>' % (
                "" if v == view else " alt", esc(base + "&view=" + v), lab) for v, lab in (("graph", "Graph"), ("list", "List"))))]
    note = "Showing %d of %d%s objects within %d hop%s of this one" % (len(shown), total, more, hops, "" if hops == 1 else "s")
    if len(shown) < total:
        note += " (nearest first; the rest are not drawn)"
    body.append('<p class="muted">%s.</p>' % esc(note))
    kept = set(shown)
    shown_edges = [(k, e) for k, e in edges.items() if k[0] in kept and k[1] in kept and k[0] != k[1]]
    if len(shown) == 1:
        body.append('<div class="card soft">No link touches this object, so there is nothing to draw around it.</div>')
    elif view == "list":
        trs = "".join("<tr><td>%d</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
            depth_of[i], obj_link(i, hops), esc(meta[i][0]), esc(LAYER_NAME[layer_of(meta[i][0])])) for i in shown)
        body.append("<h2>Objects</h2><table><tr><th>Hops</th><th>Object</th><th>Type</th><th>Layer</th></tr>%s</table>" % trs)
        lt = "".join("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
            obj_link(s, hops), esc(", ".join(e["rels"])), obj_link(d, hops), origin_pill(o), "<br>".join("<code>%s</code>" % esc(x) for x in e["sources"][:2]))
            for (s, d, o), e in shown_edges[:MAX_SHOWN])
        body.append("<h2>Links between them</h2><table><tr><th>From</th><th>Relation</th><th>To</th><th>Origin</th><th>Source</th></tr>%s</table>" % lt)
        if len(shown_edges) > MAX_SHOWN:
            body.append('<p class="muted">Showing %d of %d links.</p>' % (MAX_SHOWN, len(shown_edges)))
    else:
        svg, mode = neighbourhood_svg(center, shown, depth_of, meta, edges, hops)
        body.append('<div class="tscroll card soft">%s</div><p class="muted"><small>Layout: %s. Click any object to centre the map on it. '
                    '%d link%s drawn.</small></p>' % (svg, "rings around the object" if mode == "radial" else "one column per hop",
                                                      len(shown_edges), "" if len(shown_edges) == 1 else "s"))
    origins = {}
    for (_, _, o), e in shown_edges:
        origins[o] = origins.get(o, 0) + len(e["rels"])
    side = ['<h4>This object</h4><table><tr><td class="muted">Id</td><td><code>%s</code></td></tr><tr><td class="muted">Type</td><td>%s</td></tr>'
            '<tr><td class="muted">Layer</td><td>%s</td></tr><tr><td class="muted">Links touching it</td><td>%d</td></tr></table>' % (
                esc(center), esc(row[1]), esc(LAYER_NAME[layer_of(row[1])]),
                sum(len(e["rels"]) for (s, d, _), e in edges.items() if center in (s, d)))]
    if origins:
        side.append("<h4>Links drawn, by origin</h4><table>%s</table>" % "".join(
            "<tr><td>%s</td><td>%d</td></tr>" % (origin_pill(o), n) for o, n in sorted(origins.items())))
    side.append(legend())
    return "".join(body), "".join(side), row


def map_view(ctx, q, flash=None, error=None):
    layer = C.clean(q.get("layer"))
    layer = layer if layer in LAYER_NAME else ""
    folder = C.clean(q.get("folder"))
    center = C.clean(q.get("center") or q.get("node"))
    text = C.clean(q.get("q"))
    hops = clamp(q.get("hops"), 1, 3, 1)
    view = "list" if q.get("view") == "list" else "graph"
    try:
        data = overview(ctx.kb)
        con = open_graph(ctx.kb)
    except NoGraph as err:
        return page(ctx, "Map", "/map", "<h1>Map</h1>", flash, str(err), left=placeholder_left(ctx),
                    right=C.right_pane(legend()))
    try:
        side, center_layer = legend(), ""
        body = []
        if center:
            try:
                html_, side, row = neighbourhood_html(ctx, con, center, hops, view)
                body.append(html_)
                center_layer = layer_of(row[1])
            except C.UiError as err:
                error = "\n".join(x for x in (error, str(err)) if x)
                body.append(search_html(con, center.split(":")[-1]))
        elif text:
            body.append("<h1>Find an object</h1>" + search_html(con, text))
        elif layer and folder:
            body.append(group_html(con, data, layer, folder))
        else:
            body.append(overview_html(data, layer))
        if not center:
            body.append('<h2>Find an object</h2>' + form(ctx, "/map", '<input type="text" name="q" value="%s" placeholder="table, job, endpoint or screen name" '
                                                                  'aria-label="Find an object"> <button>Search</button>' % esc(text), method="get"))
        return page(ctx, "Map", "/map", "".join(body), flash, error, left=left_side(ctx, data, layer, center_layer),
                    right=C.right_pane(side))
    finally:
        con.close()


# ---- /impact ---------------------------------------------------------------------------------------
def step_text(step):
    return "%s <i>%s</i> %s" % (esc(step["from"]), esc(step["rel"]), esc(step["to"]))


def impact_table(rows, trust, key):
    if not rows:
        return '<p class="muted">Nothing.</p>'
    out = []
    for r in rows[:MAX_IMPACT_ROWS]:
        last = r["via"][-1]
        sig = ""
        if trust is not None:
            try:
                sig = trust.edge_text(trust.edge(last.get("origin"), last["source"]))
            except Exception as exc:  # signals are extra; a row without them is still a fact
                sig = "signals not available: %s" % exc
        out.append("<tr><td>%d</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td><code>%s</code></td><td>%s</td></tr>" % (
            r["depth"], obj_link(r[key], 1), '<a href="/impact?node=%s">impact</a>' % esc(urllib.parse.quote(r[key], safe="")), step_text(last),
            origin_pill(last.get("origin")), esc(last["source"]), esc(sig)))
    return ("<table><tr><th>Hops</th><th>Object</th><th></th><th>Because (last step)</th><th>Origin</th><th>Source</th><th>Trust signals</th></tr>%s</table>%s" % (
        "".join(out), '<p class="muted">Showing %d of %d.</p>' % (MAX_IMPACT_ROWS, len(rows)) if len(rows) > MAX_IMPACT_ROWS else ""))


def layer_counts(rows, key, meta):
    c = {}
    for r in rows:
        lay = layer_of(meta.get(r[key], ("",))[0])
        c[lay] = c.get(lay, 0) + 1
    return ", ".join("%d %s" % (n, LAYER_NAME[k].lower()) for k, _ in LAYERS for n in [c.get(k, 0)] if n) or "nothing"


def impact_view(ctx, q, flash=None, error=None):
    node = C.clean(q.get("node"))
    depth = clamp(q.get("depth"), 1, 5, 3)
    try:
        data = overview(ctx.kb)
        con = open_graph(ctx.kb)
    except NoGraph as err:
        return page(ctx, "Impact", "/map", "<h1>Impact</h1>", flash, str(err), left=placeholder_left(ctx), right=C.right_pane(legend()))
    try:
        search = form(ctx, "/impact", '<input type="text" name="q" value="%s" placeholder="object name" aria-label="Find an object"> '
                                      '<button>Search</button>' % esc(q.get("q", "")), method="get")
        left = left_side(ctx, data, "", "x")
        if not node:
            text = C.clean(q.get("q"))
            body = ['<h1>Impact</h1><p class="lead">Pick an object to see what changes if it changes.</p>', search]
            if text:
                rows, _ = find_nodes(con, text)
                body.append("<table><tr><th>Object</th><th>Type</th></tr>%s</table>" % "".join(
                    '<tr><td><a href="/impact?node=%s">%s</a></td><td>%s</td></tr>' % (esc(urllib.parse.quote(i, safe="")), esc(i), esc(t))
                    for i, t, _ in rows) if rows else '<div class="card soft">No object matches.</div>')
            return page(ctx, "Impact", "/map", "".join(body), flash, error, left=left, right=C.right_pane(legend()))
        row = node_row(con, node)
        if not row:
            return page(ctx, "Impact", "/map", "<h1>Impact</h1>" + search, flash,
                        "There is no object %r in the link graph." % node, left=left, right=C.right_pane(legend()))
        down, cut_d = graph_store.impact(ctx.kb, node, depth, MAX_SEEN)
        up, cut_u = graph_store.upstream(ctx.kb, node, depth, MAX_SEEN)
        trust, notes = None, []
        try:
            import trust as trust_signals
            trust = trust_signals.Trust(ctx.kb)
            notes += trust.notes
        except Exception as exc:  # signals are extra: say so, show the rest
            notes.append("trust signals not available: %s" % exc)
        names = {r["moves"] for r in down} | {r["changes"] for r in up}
        meta = {x[0]: (x[1], x[2]) for x in (node_row(con, n) for n in sorted(names)) if x}
        depth_links = " ".join('<a class="btn%s" href="/impact?node=%s&amp;depth=%d">%d</a>' % (
            "" if d == depth else " alt", esc(urllib.parse.quote(node, safe="")), d, d) for d in range(1, 6))
        body = ['<h1>If %s changes</h1>' % esc(row[2]),
                '<p class="lead"><code>%s</code> &middot; %s &middot; <a href="%s">see it on the map</a></p>' % (
                    esc(node), esc(row[1]), esc(link_for(center=node))),
                "<p>Follow links up to %s hop(s).</p>" % depth_links,
                "<h2>What moves (%d)</h2><p>%s%s.</p>" % (len(down), esc(layer_counts(down, "moves", meta)),
                                                         " Stopped at the limit, more exist." if cut_d else ""),
                impact_table(down, trust, "moves"),
                "<h2>What it depends on (%d)</h2><p>%s%s.</p>" % (len(up), esc(layer_counts(up, "changes", meta)),
                                                                 " Stopped at the limit, more exist." if cut_u else ""),
                impact_table(up, trust, "changes"),
                '<p class="muted"><small>Only links whose relation has a known direction are followed (gen_matrix.DEPENDS). '
                'The trust signals are facts read from the KB and git, not a score: a verified quote means the words are in the source, '
                'not that the statement drawn from them is right.</small></p>']
        side = ['<h4>Trust signals</h4><div class="muted">%s</div>' % ("<br>".join(esc(n) for n in notes) if notes else "No notes."), legend()]
        return page(ctx, "Impact", "/map", "".join(body), flash, error, left=left, right=C.right_pane("".join(side)))
    finally:
        con.close()


SCREENS = {"/map": map_view, "/impact": impact_view}
ACTIONS = {}
NAV = [("/map", "Map")]
