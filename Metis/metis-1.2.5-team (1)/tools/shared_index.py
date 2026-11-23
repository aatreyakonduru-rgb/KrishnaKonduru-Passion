#!/usr/bin/env python3
"""Shared cross-team read index for federated Metis knowledge bases.

    python3 shared_index.py register <shared.sqlite> <kb> [--name <name>]
    python3 shared_index.py refresh  <shared.sqlite> [--name <name>]
    python3 shared_index.py search   <shared.sqlite> "<query>" [--kb <name>] [--limit 20]
    python3 shared_index.py objects  <shared.sqlite> [--type <type>] [--kb <name>]
    python3 shared_index.py stats    <shared.sqlite>
    python3 shared_index.py helper   <shared.sqlite> "<question_query>"

Inclusion Rules:
  1. Certified Only: A KB must be locked (kb_gate.is_locked), have 0 uncertified changes (kb_gate.check),
     and have no pending batches (kb_gate.batches).
  2. Per-KB Share Flag: Respects `share: false` (or `federation.share: false`) in the KB's kb-profile.yaml.
  3. Sensitive Data Excluded: Any page with sensitive secrets (sensitive.py) is left out of the shared index.
  4. Claim labels (claim_labels.py): when the KB uses `{env: ...; sensitivity: ...}` labels, only lines at or below the sharing level
     enter the index; `register`/`refresh` take `--max-sensitivity LEVEL`, default `labels.share_max_sensitivity` in the profile, else
     `public`. A page with no label counts as `labels.default_sensitivity` (default `internal`), which is above `public`, so a KB that
     uses labels shares only what is marked public (or what the profile allows). Links whose source cites a withheld line are left
     out. When labels are in use, yaml and txt files other than CROSS-LAYER/LINK_GRAPH.yaml (which is filtered) are not indexed, because
     they cannot be judged line by line. A KB with no labels is indexed exactly as before.

Search:
  Guarded search: uses BM25 from tools/kb_search.py if present at runtime (never imported at module load),
  otherwise falls back to SQLite Full Text Search / tokenized term search.

Cross-KB Helper:
  Returns relevant knowledge pages across all certified KBs annotated with team and KB names, so AI answers
  can cite exactly which team provided each fact.
"""
import argparse
import datetime
import os
import re
import sqlite3
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import claim_labels  # noqa: E402
import kb_gate  # noqa: E402
import kb_manifest  # noqa: E402
import sensitive  # noqa: E402

SCHEMA = """
create table if not exists registered_kbs (
    name text primary key,
    path text,
    team text,
    url text,
    version text,
    certified_at text,
    registered_at text,
    share_allowed integer
);

create table if not exists pages (
    kb_name text,
    rel_path text,
    title text,
    kind text,
    text text,
    tags_count integer,
    sha256 text,
    last_commit text,
    primary key (kb_name, rel_path)
);

create table if not exists objects (
    kb_name text,
    id text,
    type text,
    name text,
    norm_name text,
    primary key (kb_name, id)
);

create table if not exists edges (
    id integer primary key autoincrement,
    kb_name text,
    src text,
    rel text,
    dst text,
    origin text,
    source text,
    defined_in text
);

create index if not exists idx_pages_kb on pages(kb_name);
create index if not exists idx_obj_norm on objects(norm_name);
create index if not exists idx_obj_type_norm on objects(type, norm_name);
create index if not exists idx_edges_src on edges(kb_name, src);
create index if not exists idx_edges_dst on edges(kb_name, dst);
"""

FTS_SCHEMA = """
create virtual table if not exists pages_fts using fts5(
    kb_name, rel_path, title, text, tokenize='porter unicode61'
);
"""

FTS4_SCHEMA = """
create virtual table if not exists pages_fts using fts4(
    kb_name, rel_path, title, text
);
"""


def norm_name(name):
    """Normalize object name for cross-team joins."""
    s = str(name or "").strip().upper()
    # Normalize whitespace and quotes
    s = re.sub(r"\s+", " ", s)
    return s


def connect(db_path):
    """Connect to SQLite database and ensure schema is present."""
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA)
    # Attempt FTS table creation
    try:
        con.executescript(FTS_SCHEMA)
    except sqlite3.OperationalError:
        try:
            con.executescript(FTS4_SCHEMA)
        except sqlite3.OperationalError:
            pass  # FTS not available, fallback will be used
    return con


def check_kb_eligibility(kb):
    """Verify KB certification, pending batches, and sharing permission."""
    kb = os.path.abspath(kb)
    if not os.path.isdir(kb):
        raise ValueError("KB directory not found: %s" % kb)

    prof = kb_gate.profile(kb)
    # Check share flag in profile
    share_val = prof.get("share")
    if share_val is False or prof.get("federation", {}).get("share") is False:
        raise ValueError("KB profile has share: false; cross-team indexing is disabled for this KB")

    # Check lock status
    if not kb_gate.is_locked(kb):
        raise ValueError("KB is not certified (not locked); only certified KBs may be shared")

    # Check uncertified changes
    probs, locked = kb_gate.check(kb)
    if probs:
        raise ValueError("KB has %d uncertified/modified files; all files must be certified" % len(probs))

    # Check pending batches
    batches = kb_gate.batches(kb)
    if batches:
        raise ValueError("KB has pending batches (%s); certification must be completed before sharing" % ", ".join(batches))

    return prof


def index_kb_data(con, kb, kb_name, team_name, git_url="", max_level=None):
    """Extract pages, objects, and edges from KB and insert into shared SQLite. `max_level`: the highest sensitivity that may be
    shared (default: the profile's labels.share_max_sensitivity, else public); only applies when the KB uses claim labels."""
    viewer = claim_labels.Viewer(kb, level=max_level or claim_labels.share_level(kb))
    # Read manifest / files
    manifest_entries = kb_manifest.collect(kb, git=False)
    cert_state = kb_gate.load_state(kb)
    locked_on = cert_state.get("locked_on") or str(datetime.date.today())
    now_str = datetime.datetime.now().isoformat(timespec="seconds")

    # 1. Register KB
    con.execute(
        "insert or replace into registered_kbs values (?, ?, ?, ?, ?, ?, ?, ?)",
        (kb_name, kb, team_name, git_url, locked_on, locked_on, now_str, 1)
    )

    # 2. Clear old data for this KB
    con.execute("delete from pages where kb_name=?", (kb_name,))
    con.execute("delete from objects where kb_name=?", (kb_name,))
    con.execute("delete from edges where kb_name=?", (kb_name,))
    try:
        con.execute("delete from pages_fts where kb_name=?", (kb_name,))
    except sqlite3.OperationalError:
        pass

    # 3. Index Pages (excluding sensitive pages)
    page_rows = []
    fts_rows = []
    for entry in manifest_entries:
        rel = entry.get("path")
        if not rel.endswith((".md", ".markdown", ".yaml", ".yml", ".txt")):
            continue
        fp = os.path.join(kb, rel)
        if not os.path.isfile(fp):
            continue

        with open(fp, encoding="utf-8", errors="replace") as fh:
            content = fh.read()

        # Sensitive check: skip pages with secrets
        findings = sensitive.scan(content)
        if sensitive.blocking(findings):
            continue

        # Claim labels: keep only the lines at or below the sharing level; a page with nothing left is not shared.
        # When labels are in use, other yaml/txt files are not shared (they cannot be judged line by line) except the link graph.
        if viewer.active and not rel.endswith((".md", ".markdown")):
            if rel != "CROSS-LAYER/LINK_GRAPH.yaml":
                continue
            content = claim_labels.filter_graph_text(viewer, content)
        content, hidden = viewer.filter(rel, content)
        if hidden and not content.strip():
            continue

        # Extract title
        title = rel
        for ln in content.splitlines():
            if ln.strip().startswith("#"):
                title = ln.strip().lstrip("#").strip()
                break

        kind = entry.get("kind") or "page"
        tags_cnt = entry.get("source_tags", 0)
        sha = entry.get("sha256", "")
        last_c = entry.get("last_commit", "")

        page_rows.append((kb_name, rel, title, kind, content, tags_cnt, sha, last_c))
        fts_rows.append((kb_name, rel, title, content))

    con.executemany("insert into pages values (?, ?, ?, ?, ?, ?, ?, ?)", page_rows)
    try:
        con.executemany("insert into pages_fts values (?, ?, ?, ?)", fts_rows)
    except sqlite3.OperationalError:
        pass

    # 4. Index Graph Objects and Edges
    link_path = os.path.join(kb, "CROSS-LAYER", "LINK_GRAPH.yaml")
    if os.path.isfile(link_path):
        with open(link_path, encoding="utf-8") as fh:
            gdata = yaml.safe_load(fh) or {}
            nodes, edges = claim_labels.filter_graph(viewer, gdata.get("nodes") or [], gdata.get("edges") or [])

            obj_rows = []
            for n in nodes:
                nid = n.get("id") or ("%s:%s" % (n.get("type"), n.get("name")))
                ntype = n.get("type") or "node"
                name = n.get("name") or nid
                n_norm = norm_name(name)
                obj_rows.append((kb_name, nid, ntype, name, n_norm))
            con.executemany("insert into objects values (?, ?, ?, ?, ?)", obj_rows)

            edge_rows = []
            for e in edges:
                src = e.get("from")
                rel = e.get("rel")
                dst = e.get("to")
                origin = e.get("origin") or "unknown"
                src_tag = e.get("source") or ""
                def_in = e.get("defined_in") or ""
                edge_rows.append((kb_name, src, rel, dst, origin, src_tag, def_in))
            con.executemany("insert into edges (kb_name, src, rel, dst, origin, source, defined_in) values (?, ?, ?, ?, ?, ?, ?)", edge_rows)

    con.commit()
    return len(page_rows), len(nodes) if 'nodes' in locals() else 0, len(edges) if 'edges' in locals() else 0


def register(db_path, kb, name=None, git_url="", max_level=None):
    """Register and index a certified KB into shared.sqlite."""
    prof = check_kb_eligibility(kb)
    kb_name = name or prof.get("product", {}).get("name") or os.path.basename(os.path.abspath(kb))
    team_name = prof.get("product", {}).get("team") or prof.get("owners", {}).get("kb_owner") or "Team"

    con = connect(db_path)
    try:
        pages, objs, edges = index_kb_data(con, kb, kb_name, team_name, git_url, max_level)
        return {
            "name": kb_name,
            "team": team_name,
            "path": kb,
            "pages": pages,
            "objects": objs,
            "edges": edges,
        }
    finally:
        con.close()


def refresh(db_path, name=None, max_level=None):
    """Refresh indexing for all or specified registered KBs."""
    con = connect(db_path)
    try:
        if name:
            rows = con.execute("select name, path, team, url from registered_kbs where name=?", (name,)).fetchall()
            if not rows:
                raise ValueError("No registered KB found with name '%s'" % name)
        else:
            rows = con.execute("select name, path, team, url from registered_kbs").fetchall()

        refreshed = []
        for r_name, r_path, r_team, r_url in rows:
            check_kb_eligibility(r_path)
            pages, objs, edges = index_kb_data(con, r_path, r_name, r_team, r_url, max_level)
            refreshed.append({"name": r_name, "pages": pages, "objects": objs, "edges": edges})
        return refreshed
    finally:
        con.close()


def search(db_path, query, kb=None, limit=20):
    """Search pages across all registered KBs using guarded BM25 or FTS/term fallback."""
    # Guarded check for kb_search module at runtime
    search_mod = None
    try:
        tools_dir = os.path.dirname(os.path.abspath(__file__))
        if tools_dir not in sys.path:
            sys.path.insert(0, tools_dir)
        import kb_search  # type: ignore
        search_mod = kb_search
    except (ImportError, Exception):
        search_mod = None

    con = connect(db_path)
    try:
        results = []
        q_clean = query.strip()
        if not q_clean:
            return results

        # 1. Try BM25 from kb_search if available
        if search_mod and hasattr(search_mod, "bm25_search"):
            try:
                bm_res = search_mod.bm25_search(db_path, q_clean, kb=kb, limit=limit)
                if bm_res is not None:
                    return bm_res
            except Exception:
                pass

        # 2. Try SQLite FTS
        try:
            sql = ("select p.kb_name, k.team, p.rel_path, p.title, p.tags_count, "
                   "snippet(pages_fts, 3, '<b>', '</b>', '...', 30) "
                   "from pages_fts f join pages p on p.kb_name = f.kb_name and p.rel_path = f.rel_path "
                   "join registered_kbs k on k.name = p.kb_name "
                   "where pages_fts match ?")
            params = [q_clean]
            if kb:
                sql += " and p.kb_name = ?"
                params.append(kb)
            sql += " order by rank limit ?"
            params.append(limit)

            for kb_n, team, path, title, tags, snip in con.execute(sql, params):
                results.append({
                    "kb_name": kb_n,
                    "team": team,
                    "rel_path": path,
                    "title": title,
                    "tags_count": tags,
                    "snippet": snip,
                })
            if results:
                return results
        except sqlite3.OperationalError:
            pass

        # 3. Simple LIKE / term matching fallback
        sql = ("select p.kb_name, k.team, p.rel_path, p.title, p.tags_count, substr(p.text, 1, 200) "
               "from pages p join registered_kbs k on k.name = p.kb_name "
               "where (p.title like ? or p.text like ?)")
        term = "%%%s%%" % q_clean
        params = [term, term]
        if kb:
            sql += " and p.kb_name = ?"
            params.append(kb)
        sql += " limit ?"
        params.append(limit)

        for kb_n, team, path, title, tags, snip in con.execute(sql, params):
            results.append({
                "kb_name": kb_n,
                "team": team,
                "rel_path": path,
                "title": title,
                "tags_count": tags,
                "snippet": snip.replace("\n", " ").strip() + "...",
            })
        return results
    finally:
        con.close()


def objects(db_path, ntype=None, name=None, kb=None):
    """List indexed graph objects across KBs."""
    con = connect(db_path)
    try:
        sql = "select o.kb_name, k.team, o.id, o.type, o.name from objects o join registered_kbs k on k.name = o.kb_name where 1=1"
        params = []
        if ntype:
            sql += " and o.type = ?"
            params.append(ntype)
        if name:
            sql += " and (o.name like ? or o.norm_name like ?)"
            params.extend(["%%%s%%" % name, "%%%s%%" % norm_name(name)])
        if kb:
            sql += " and o.kb_name = ?"
            params.append(kb)
        sql += " order by o.type, o.name"

        out = []
        for kb_n, team, oid, otype, oname in con.execute(sql, params):
            out.append({
                "kb_name": kb_n,
                "team": team,
                "id": oid,
                "type": otype,
                "name": oname,
            })
        return out
    finally:
        con.close()


def stats(db_path):
    """Summary statistics for shared index."""
    con = connect(db_path)
    try:
        kbs = []
        for name, path, team, ver, cert in con.execute("select name, path, team, version, certified_at from registered_kbs"):
            p_cnt = con.execute("select count(*) from pages where kb_name=?", (name,)).fetchone()[0]
            o_cnt = con.execute("select count(*) from objects where kb_name=?", (name,)).fetchone()[0]
            e_cnt = con.execute("select count(*) from edges where kb_name=?", (name,)).fetchone()[0]
            kbs.append({
                "name": name,
                "team": team,
                "path": path,
                "version": ver,
                "certified_at": cert,
                "pages": p_cnt,
                "objects": o_cnt,
                "edges": e_cnt,
            })
        return {
            "total_kbs": len(kbs),
            "kbs": kbs,
            "total_pages": sum(k["pages"] for k in kbs),
            "total_objects": sum(k["objects"] for k in kbs),
            "total_edges": sum(k["edges"] for k in kbs),
        }
    finally:
        con.close()


def cross_kb_pages(db_path, question_query, limit=5):
    """Helper for Q&A answering: returns pages grouped by team with team attribution headers."""
    hits = search(db_path, question_query, limit=limit)
    con = connect(db_path)
    try:
        by_team = {}
        for h in hits:
            row = con.execute("select text from pages where kb_name=? and rel_path=?", (h["kb_name"], h["rel_path"])).fetchone()
            txt = row[0] if row else ""
            by_team.setdefault(h["team"], []).append({
                "kb_name": h["kb_name"],
                "team": h["team"],
                "rel_path": h["rel_path"],
                "title": h["title"],
                "text": txt,
            })

        sections = []
        for team, items in by_team.items():
            team_header = "### Facts from %s" % team
            page_blocks = []
            for item in items:
                page_blocks.append("#### [%s / %s]\n%s" % (item["kb_name"], item["rel_path"], item["text"]))
            sections.append(team_header + "\n\n" + "\n\n".join(page_blocks))
        return "\n\n---\n\n".join(sections)
    finally:
        con.close()


# ---- CLI -------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    a_reg = sub.add_parser("register", help="Register certified KB into shared index")
    a_reg.add_argument("db", help="Path to shared.sqlite")
    a_reg.add_argument("kb", help="Path to KB folder")
    a_reg.add_argument("--name", help="Custom name for the KB")
    a_reg.add_argument("--url", default="", help="Git URL of the KB repository")
    a_reg.add_argument("--max-sensitivity", help="highest claim-label level to share (default: profile labels.share_max_sensitivity, else public)")

    a_ref = sub.add_parser("refresh", help="Refresh indexed KBs in shared index")
    a_ref.add_argument("db", help="Path to shared.sqlite")
    a_ref.add_argument("--name", help="Refresh only this KB name")
    a_ref.add_argument("--max-sensitivity", help="highest claim-label level to share (default: profile labels.share_max_sensitivity, else public)")

    a_srch = sub.add_parser("search", help="Search pages across registered KBs")
    a_srch.add_argument("db", help="Path to shared.sqlite")
    a_srch.add_argument("query", help="Search query")
    a_srch.add_argument("--kb", help="Filter by KB name")
    a_srch.add_argument("--limit", type=int, default=20)

    a_obj = sub.add_parser("objects", help="List graph objects across KBs")
    a_obj.add_argument("db", help="Path to shared.sqlite")
    a_obj.add_argument("--type", help="Filter by object type (e.g. table, endpoint)")
    a_obj.add_argument("--name", help="Filter by object name")
    a_obj.add_argument("--kb", help="Filter by KB name")

    a_stat = sub.add_parser("stats", help="Show shared index statistics")
    a_stat.add_argument("db", help="Path to shared.sqlite")

    a_hlp = sub.add_parser("helper", help="Cross-KB Q&A question context helper")
    a_hlp.add_argument("db", help="Path to shared.sqlite")
    a_hlp.add_argument("query", help="Question text")

    args = ap.parse_args(argv)

    if args.cmd == "register":
        try:
            res = register(args.db, args.kb, args.name, args.url, args.max_sensitivity)
            print("Registered '%s' (%s): %d pages, %d objects, %d edges -> %s" % (
                res["name"], res["team"], res["pages"], res["objects"], res["edges"], args.db))
            return 0
        except ValueError as e:
            print("Registration refused: %s" % e, file=sys.stderr)
            return 1

    elif args.cmd == "refresh":
        try:
            refreshed = refresh(args.db, args.name, args.max_sensitivity)
            for r in refreshed:
                print("Refreshed '%s': %d pages, %d objects, %d edges" % (r["name"], r["pages"], r["objects"], r["edges"]))
            return 0
        except ValueError as e:
            print("Refresh failed: %s" % e, file=sys.stderr)
            return 1

    elif args.cmd == "search":
        hits = search(args.db, args.query, args.kb, args.limit)
        print("Found %d results for '%s':" % (len(hits), args.query))
        for h in hits:
            print("[%s | %s] %s (%s) - %s" % (h["team"], h["kb_name"], h["title"], h["rel_path"], h["snippet"][:80]))
        return 0

    elif args.cmd == "objects":
        objs = objects(args.db, args.type, args.name, args.kb)
        print("Found %d objects:" % len(objs))
        for o in objs:
            print("[%s | %s] %s (%s)" % (o["team"], o["kb_name"], o["id"], o["type"]))
        return 0

    elif args.cmd == "stats":
        st = stats(args.db)
        print("Shared Index Statistics (%d KBs):" % st["total_kbs"])
        for k in st["kbs"]:
            print("  - %s (%s): %d pages, %d objects, %d edges [certified %s]" % (
                k["name"], k["team"], k["pages"], k["objects"], k["edges"], k["certified_at"]))
        print("Total: %d pages, %d objects, %d edges" % (st["total_pages"], st["total_objects"], st["total_edges"]))
        return 0

    elif args.cmd == "helper":
        txt = cross_kb_pages(args.db, args.query)
        print(txt)
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
