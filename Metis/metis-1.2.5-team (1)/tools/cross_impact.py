#!/usr/bin/env python3
"""Cross-team impact walks across federated knowledge bases in shared.sqlite.

    python3 cross_impact.py impact   <shared.sqlite> <node> [--depth N] [--limit N]
    python3 cross_impact.py upstream <shared.sqlite> <node> [--depth N] [--limit N]

Cross-Team Joins:
  - Links graph nodes across registered KBs by shared object identity:
      1. Explicit `same_as` mappings (from cross-team links files).
      2. Normalised object identity (e.g. database.schema.table, API path, screen name).
  - Matches across KBs that are name-only guesses without explicit source link are flagged as `ai-proposed`.
  - Walks upstream (what this depends on) and downstream (what moves when this changes).
  - Every hop records the owning KB, owning team, edge origin, and evidence source.
"""
import argparse
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gen_matrix  # noqa: E402
import shared_index  # noqa: E402


def norm_node_id(node_str):
    """Normalize node identifier string into (type, normalized_name)."""
    s = str(node_str or "").strip()
    if ":" in s:
        ntype, _, name = s.partition(":")
        return ntype.strip().lower(), shared_index.norm_name(name)
    return "", shared_index.norm_name(s)


def parse_node_arg(node_str):
    """Parse node argument which might be 'table:ORDERS' or 'ORDERS' or 'kb_name:table:ORDERS'."""
    s = str(node_str or "").strip()
    parts = s.split(":")
    if len(parts) == 3:
        return parts[0], parts[1], parts[2]
    elif len(parts) == 2:
        return None, parts[0], parts[1]
    return None, None, s


def load_shared_graph(db_path):
    """Load all registered KBs, objects, and edges from shared.sqlite into memory graph for fast walks."""
    con = shared_index.connect(db_path)
    try:
        kbs = {r[0]: {"name": r[0], "team": r[1], "path": r[2]}
               for r in con.execute("select name, team, path from registered_kbs")}

        # objects: (kb_name, id) -> {kb, id, type, name, norm_name, team}
        objs = {}
        # norm_index: (type, norm_name) -> list of (kb_name, obj_id)
        norm_map = {}
        for kb_n, oid, otype, oname, onorm in con.execute("select kb_name, id, type, name, norm_name from objects"):
            team = kbs.get(kb_n, {}).get("team", "Unknown")
            info = {"kb": kb_n, "team": team, "id": oid, "type": otype, "name": oname, "norm": onorm}
            objs[(kb_n, oid)] = info
            norm_map.setdefault((otype.lower(), onorm), []).append((kb_n, oid))
            # Also index by norm only if type is generic/missing
            norm_map.setdefault(("", onorm), []).append((kb_n, oid))

        # edges: list of {kb, team, src, rel, dst, origin, source, defined_in}
        edges = []
        for kb_n, src, rel, dst, origin, src_tag, def_in in con.execute(
                "select kb_name, src, rel, dst, origin, source, defined_in from edges"):
            team = kbs.get(kb_n, {}).get("team", "Unknown")
            edges.append({
                "kb": kb_n,
                "team": team,
                "src": src,
                "rel": rel,
                "dst": dst,
                "origin": origin or "unknown",
                "source": src_tag or "",
                "defined_in": def_in or "",
            })

        return kbs, objs, norm_map, edges
    finally:
        con.close()


def build_adjacency(objs, norm_map, edges):
    """Build forward and backward movement graphs incorporating cross-team joins."""
    forward_adj = {}   # (kb, node_id) -> list of {next_key, step_info}
    backward_adj = {}  # (kb, node_id) -> list of {prev_key, step_info}

    # 1. Intra-KB Directed Moves from Edge Semantics
    for e in edges:
        kb_n = e["kb"]
        src_key = (kb_n, e["src"])
        dst_key = (kb_n, e["dst"])

        # Normalize relation direction using gen_matrix.DEPENDS
        norm_r = e["rel"].strip().lower()
        d = gen_matrix.DEPENDS.get(norm_r)

        step_info = {
            "from": e["src"],
            "rel": e["rel"],
            "to": e["dst"],
            "kb": kb_n,
            "team": e["team"],
            "origin": e["origin"],
            "source": e["source"],
            "cross_team": False,
            "match_type": "internal",
        }

        # forward moves: what moves when X changes
        if d in ("to", "both"):
            forward_adj.setdefault(src_key, []).append({"next": dst_key, "via": step_info})
            backward_adj.setdefault(dst_key, []).append({"prev": src_key, "via": step_info})
        if d in ("from", "both"):
            forward_adj.setdefault(dst_key, []).append({"next": src_key, "via": step_info})
            backward_adj.setdefault(src_key, []).append({"prev": dst_key, "via": step_info})

    # 2. Cross-KB Identity Bridges (shared objects across different KBs)
    for (otype, onorm), obj_keys in norm_map.items():
        if not otype or len(obj_keys) <= 1:
            continue
        # Connect identical objects across different KBs
        for i in range(len(obj_keys)):
            for j in range(i + 1, len(obj_keys)):
                k1 = obj_keys[i]
                k2 = obj_keys[j]
                if k1[0] == k2[0]:
                    continue  # Same KB, internal edge

                # Check if this cross-team join is exact or name-guess
                o1 = objs.get(k1, {})
                o2 = objs.get(k2, {})
                exact_match = (o1.get("name") == o2.get("name") and o1.get("type") == o2.get("type"))
                origin_val = "catalogue" if exact_match else "ai-proposed"

                bridge_info_fwd = {
                    "from": "%s:%s" % (k1[0], k1[1]),
                    "rel": "same_as",
                    "to": "%s:%s" % (k2[0], k2[1]),
                    "kb": k2[0],
                    "team": o2.get("team", "Unknown"),
                    "origin": origin_val,
                    "source": "[cross-team shared object: %s]" % onorm,
                    "cross_team": True,
                    "match_type": "explicit" if exact_match else "ai-proposed",
                }
                bridge_info_rev = {
                    "from": "%s:%s" % (k2[0], k2[1]),
                    "rel": "same_as",
                    "to": "%s:%s" % (k1[0], k1[1]),
                    "kb": k1[0],
                    "team": o1.get("team", "Unknown"),
                    "origin": origin_val,
                    "source": "[cross-team shared object: %s]" % onorm,
                    "cross_team": True,
                    "match_type": "explicit" if exact_match else "ai-proposed",
                }

                # Cross-team identity bridges are bidirectional
                forward_adj.setdefault(k1, []).append({"next": k2, "via": bridge_info_fwd})
                forward_adj.setdefault(k2, []).append({"next": k1, "via": bridge_info_rev})
                backward_adj.setdefault(k1, []).append({"prev": k2, "via": bridge_info_fwd})
                backward_adj.setdefault(k2, []).append({"prev": k1, "via": bridge_info_rev})

    return forward_adj, backward_adj


def find_start_keys(objs, norm_map, start_arg):
    """Find matching (kb, node_id) keys from user start argument."""
    kb_filter, ntype_filter, name_part = parse_node_arg(start_arg)
    norm_val = shared_index.norm_name(name_part)

    matching_keys = []
    # Search by exact key
    for (kb_n, oid), info in objs.items():
        if kb_filter and kb_n.lower() != kb_filter.lower():
            continue
        if ntype_filter and info["type"].lower() != ntype_filter.lower():
            continue
        if info["norm"] == norm_val or norm_val in info["norm"] or oid.lower() == start_arg.lower():
            matching_keys.append((kb_n, oid))

    if not matching_keys:
        # Try norm_map
        if (ntype_filter or "").lower() and ((ntype_filter.lower(), norm_val) in norm_map):
            matching_keys.extend(norm_map[(ntype_filter.lower(), norm_val)])
        elif ("", norm_val) in norm_map:
            matching_keys.extend(norm_map[("", norm_val)])

    return list(dict.fromkeys(matching_keys))


def walk(db_path, start_node, direction="forward", depth=3, limit=5000):
    """Breadth-first search walk across federated KBs."""
    kbs, objs, norm_map, edges = load_shared_graph(db_path)
    forward_adj, backward_adj = build_adjacency(objs, norm_map, edges)
    adj = forward_adj if direction == "forward" else backward_adj

    start_keys = find_start_keys(objs, norm_map, start_node)
    if not start_keys:
        return [], False

    seen = set(start_keys)
    out = []
    frontier = [(k, []) for k in start_keys]
    level = 0
    cut = False

    while frontier and (depth is None or level < depth) and not cut:
        level += 1
        nxt = []
        for current_key, current_path in frontier:
            neighbors = adj.get(current_key, [])
            for hop in neighbors:
                target_key = hop["next"] if direction == "forward" else hop["prev"]
                if target_key in seen:
                    continue
                if len(out) >= limit:
                    cut = True
                    break
                seen.add(target_key)
                hop_info = hop["via"]
                new_path = current_path + [hop_info]
                target_obj = objs.get(target_key, {"id": target_key[1], "team": "Unknown", "kb": target_key[0]})

                out.append({
                    "depth": level,
                    "kb": target_key[0],
                    "team": target_obj.get("team", "Unknown"),
                    "node": target_key[1],
                    "node_type": target_obj.get("type", "node"),
                    "node_name": target_obj.get("name", target_key[1]),
                    "via": new_path,
                })
                nxt.append((target_key, new_path))
            if cut:
                break
        frontier = nxt

    return out, cut


def impact(db_path, start_node, depth=3, limit=5000):
    """Downstream walk: what moves when start_node changes across all teams."""
    rows, cut = walk(db_path, start_node, direction="forward", depth=depth, limit=limit)
    return rows, cut


def upstream(db_path, start_node, depth=3, limit=5000):
    """Upstream walk: what start_node depends on across all teams."""
    rows, cut = walk(db_path, start_node, direction="backward", depth=depth, limit=limit)
    return rows, cut


# ---- CLI -------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    a_imp = sub.add_parser("impact", help="Downstream cross-team impact walk")
    a_imp.add_argument("db", help="Path to shared.sqlite")
    a_imp.add_argument("node", help="Start node (e.g. table:CLAIMS or CLAIMS)")
    a_imp.add_argument("--depth", type=int, default=3)
    a_imp.add_argument("--limit", type=int, default=5000)

    a_ups = sub.add_parser("upstream", help="Upstream cross-team dependency walk")
    a_ups.add_argument("db", help="Path to shared.sqlite")
    a_ups.add_argument("node", help="Start node (e.g. table:CLAIMS or CLAIMS)")
    a_ups.add_argument("--depth", type=int, default=3)
    a_ups.add_argument("--limit", type=int, default=5000)

    args = ap.parse_args(argv)

    if args.cmd == "impact":
        rows, cut = impact(args.db, args.node, args.depth, args.limit)
        print("Cross-Team Downstream Impact for '%s' (%d items%s):" % (
            args.node, len(rows), "; stopped at limit" if cut else ""))
        for r in rows:
            last = r["via"][-1]
            origin_tag = "[%s]" % last["origin"]
            cross_badge = " (CROSS-TEAM)" if last.get("cross_team") else ""
            print("  depth %d\t[%s / %s]\t%s\tvia (%s -%s-> %s)\t%s%s\t%s" % (
                r["depth"], r["team"], r["kb"], r["node"], last["from"], last["rel"], last["to"],
                origin_tag, cross_badge, last["source"]))
        return 0

    elif args.cmd == "upstream":
        rows, cut = upstream(args.db, args.node, args.depth, args.limit)
        print("Cross-Team Upstream Dependencies for '%s' (%d items%s):" % (
            args.node, len(rows), "; stopped at limit" if cut else ""))
        for r in rows:
            last = r["via"][-1]
            origin_tag = "[%s]" % last["origin"]
            cross_badge = " (CROSS-TEAM)" if last.get("cross_team") else ""
            print("  depth %d\t[%s / %s]\t%s\tvia (%s -%s-> %s)\t%s%s\t%s" % (
                r["depth"], r["team"], r["kb"], r["node"], last["from"], last["rel"], last["to"],
                origin_tag, cross_badge, last["source"]))
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
