#!/usr/bin/env python3
"""A SQLite copy of the link graph, so impact questions are answered on demand instead of precomputed.

    python3 graph_store.py build  <kb>                          write <kb>/.metis/graph.sqlite from CROSS-LAYER/LINK_GRAPH.yaml
    python3 graph_store.py impact <kb> <type:name> [--depth N] [--limit N]
                                                                what moves when this changes, with the source of each step
    python3 graph_store.py around <kb> <type:name>              every link touching the node, followed or not

The YAML files stay the reviewable export; the database is a rebuildable index (keep it out of git). Impact walks read
only the rows they reach, one indexed lookup per step, so a depth the matrix could not afford (METIS_IMPACT_DEPTH caps
gen_matrix.py at 3) costs only what the walk touches. --limit stops a walk and says it stopped.
"""
import argparse
import os
import sqlite3
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gen_matrix  # noqa: E402

DB = os.path.join(".metis", "graph.sqlite")
SCHEMA = """
create table nodes (id text primary key, type text, name text);
create table edges (n integer primary key, src text, rel text, dst text, source text, defined_in text, origin text);
create table moves (changed text, moves text, edge integer);
create index moves_changed on moves(changed);
create index edges_src on edges(src);
create index edges_dst on edges(dst);
"""


def db_path(kb):
    return os.path.join(kb, DB)


def build(kb):
    path = os.path.join(kb, "CROSS-LAYER", "LINK_GRAPH.yaml")
    if not os.path.isfile(path):
        raise SystemExit("no link graph at %s; run gen_graph.py first" % path)
    with open(path, encoding="utf-8") as fh:
        g = yaml.safe_load(fh) or {}
    os.makedirs(os.path.dirname(db_path(kb)), exist_ok=True)
    if os.path.exists(db_path(kb)):
        os.remove(db_path(kb))
    con = sqlite3.connect(db_path(kb))
    con.executescript(SCHEMA)
    con.executemany("insert into nodes values (?,?,?)", [(n["id"], n["type"], n["name"]) for n in g.get("nodes") or []])
    edges = g.get("edges") or []
    con.executemany("insert into edges values (?,?,?,?,?,?,?)",
                    [(i, e["from"], e["rel"], e["to"], e.get("source"), e.get("defined_in"), e.get("origin") or "unknown")
                     for i, e in enumerate(edges)])
    moves = []
    for i, e in enumerate(edges):
        d = gen_matrix.DEPENDS.get(gen_matrix.norm_rel(e["rel"]))
        if d in ("from", "both"):
            moves.append((e["to"], e["from"], i))
        if d in ("to", "both"):
            moves.append((e["from"], e["to"], i))
    con.executemany("insert into moves values (?,?,?)", moves)
    con.commit()
    con.close()
    return len(g.get("nodes") or []), len(edges)


def connect(kb):
    if os.path.isfile(db_path(kb)):
        con = sqlite3.connect(db_path(kb))
        if any(c[1] == "origin" for c in con.execute("pragma table_info(edges)")):
            return con
        con.close()  # built by a version that did not record origin
    build(kb)
    return sqlite3.connect(db_path(kb))


FORWARD = ("select m.moves, e.src, e.rel, e.dst, e.source, e.origin from moves m join edges e on e.n = m.edge "
           "where m.changed=? order by e.n")
BACKWARD = ("select m.changed, e.src, e.rel, e.dst, e.source, e.origin from moves m join edges e on e.n = m.edge "
            "where m.moves=? order by e.n")


def walk(kb, start, sql, depth, limit):
    """Breadth-first walk along `moves` in the direction `sql` gives: [(node, depth, via)], and whether the limit stopped it."""
    con = connect(kb)
    try:
        if not con.execute("select 1 from nodes where id=?", (start,)).fetchone():
            return [], False
        seen, out, frontier, level, cut = {start}, [], [(start, [])], 0, False
        while frontier and (depth is None or level < depth) and not cut:
            level += 1
            nxt = []
            for node, path in frontier:
                for other, src, rel, dst, source, origin in con.execute(sql, (node,)):
                    if other in seen:
                        continue
                    if len(out) >= limit:
                        cut = True
                        break
                    seen.add(other)
                    p = path + [{"from": src, "rel": rel, "to": dst, "source": source, "origin": origin}]
                    out.append((other, level, p))
                    nxt.append((other, p))
                if cut:
                    break
            frontier = nxt
        return out, cut
    finally:
        con.close()


def impact(kb, start, depth=None, limit=5000):
    """Breadth-first walk of what moves when `start` changes: [{moves, depth, via: [step, ...]}], and whether the limit stopped it."""
    rows, cut = walk(kb, start, FORWARD, depth, limit)
    return [{"moves": n, "depth": d, "via": p} for n, d, p in rows], cut


def upstream(kb, start, depth=None, limit=5000):
    """What `start` depends on: nodes whose change moves it. [{changes, depth, via: [step, ...]}], and whether the limit stopped it."""
    rows, cut = walk(kb, start, BACKWARD, depth, limit)
    return [{"changes": n, "depth": d, "via": p} for n, d, p in rows], cut


def around(kb, node):
    con = connect(kb)
    try:
        return [{"from": s, "rel": r, "to": d, "source": src, "origin": o} for s, r, d, src, o in con.execute(
            "select src, rel, dst, source, origin from edges where src=? or dst=? order by n", (node, node))]
    finally:
        con.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("build"); a.add_argument("kb")
    a = sub.add_parser("impact"); a.add_argument("kb"); a.add_argument("node"); a.add_argument("--depth", type=int); a.add_argument("--limit", type=int, default=5000)
    a = sub.add_parser("around"); a.add_argument("kb"); a.add_argument("node")
    args = ap.parse_args(argv)
    if args.cmd == "build":
        n, e = build(args.kb)
        print("%d nodes, %d edges -> %s" % (n, e, db_path(args.kb)))
    elif args.cmd == "impact":
        rows, cut = impact(args.kb, args.node, args.depth, args.limit)
        for r in rows:
            last = r["via"][-1]
            print("%d\t%s\t(%s %s %s)\t[%s]\t%s" % (r["depth"], r["moves"], last["from"], last["rel"], last["to"],
                                                    last["origin"], last["source"]))
        print("%d things move%s" % (len(rows), "; stopped at the limit, more exist" if cut else ""))
    else:
        for r in around(args.kb, args.node):
            print("%s -%s-> %s\t[%s]\t%s" % (r["from"], r["rel"], r["to"], r["origin"], r["source"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
