#!/usr/bin/env python3
"""The sandbox database: read-only SQL over <sandbox>/sample.db, in place of Snowflake.

    python3 db.py tables                     every table with its columns and row count
    python3 db.py query "SELECT ..." [--json] one statement, read only

The folder is SDLC_SANDBOX (or --folder). The database skills use this instead of the Snowflake
MCP when SDLC_SANDBOX is set. Standard library only.
"""
import argparse
import json
import os
import sqlite3
import sys


def connect(folder):
    path = os.path.join(os.path.abspath(os.path.expanduser(folder)), "sample.db")
    if not os.path.exists(path):
        raise SystemExit("no sample.db in %s: make the sandbox first (make_sandbox.py)" % folder)
    return sqlite3.connect("file:%s?mode=ro" % path.replace("\\", "/"), uri=True)


def tables(db):
    out = []
    for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        cols = [(c[1], c[2]) for c in db.execute("PRAGMA table_info(%s)" % name)]
        rows = db.execute("SELECT COUNT(*) FROM %s" % name).fetchone()[0]
        out.append({"table": name, "rows": rows, "columns": [{"name": n, "type": t} for n, t in cols]})
    return out


def query(db, sql, limit=1000):
    cur = db.execute(sql)
    cols = [d[0] for d in cur.description or []]
    return cols, cur.fetchmany(limit)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--folder", default=os.environ.get("SDLC_SANDBOX") or "~/Documents/sdlc-sandbox")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("tables")
    q = sub.add_parser("query")
    q.add_argument("sql")
    q.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    db = connect(args.folder)
    if args.cmd == "tables":
        for t in tables(db):
            print("%s (%d rows): %s" % (t["table"], t["rows"], ", ".join("%s %s" % (c["name"], c["type"])
                                                                         for c in t["columns"])))
        return 0
    try:
        cols, rows = query(db, args.sql)
    except sqlite3.Error as exc:
        print("SQL error: %s" % exc)
        return 1
    if args.json:
        print(json.dumps([dict(zip(cols, r)) for r in rows], indent=1, default=str))
    else:
        print("\t".join(cols))
        for r in rows:
            print("\t".join("" if v is None else str(v) for v in r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
