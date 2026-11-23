#!/usr/bin/env python3
"""Plan the read-only catalogue queries for every database and schema in every environment.

    python3 db_catalog.py plan   <kb> [--env <env>]   write each query to _EVIDENCE/queries/<id>.sql and list them
    python3 db_catalog.py status <kb>                 show which queries have a saved result (<id>.json)

Reads <kb>/.metis/db-environments.yaml. For each database it uses the pack for its engine in
$METIS/templates/db-packs/<engine>.sql. Query ids are CATALOG-<TABLES|COLUMNS|FKEYS>-<ENV>-<LABEL>. The person or
agent runs each .sql read only on the connection shown and saves the result rows as <id>.json (a list of
{column: value}). A database with engine schema-files, or with no pack, is read from its schema files by
gen_registry.py instead. Nothing here connects to a database.
"""
import argparse
import os
import re
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
PACKS = os.path.join(HERE, "..", "templates", "db-packs")
KINDS = ("TABLES", "COLUMNS", "FKEYS")


def load(p):
    if not os.path.isfile(p):
        return {}
    with open(p, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def ident(s):
    return re.sub(r"[^A-Za-z0-9_]", "_", str(s)).upper()


def environments(kb):
    s = load(os.path.join(kb, ".metis", "kb-profile.yaml"))
    db = s.get("db") or {}
    data = load(os.path.join(kb, ".metis", db.get("environments_file") or "db-environments.yaml"))
    envs = {}
    for name, e in (data.get("environments") or {}).items():
        if str(name).startswith("<") or not isinstance(e, dict):
            continue
        dbs = [d for d in e.get("databases") or [] if isinstance(d, dict) and not str(d.get("database", "")).startswith("<")]
        envs[str(name)] = dict(e, databases=dbs)
    ref = data.get("reference_environment") or db.get("reference_environment") or db.get("kb_environment")
    if (not ref or ref not in envs) and len(envs) == 1:
        ref = next(iter(envs))
    return envs, ref if ref in envs else None


def label(d):
    return ident(d.get("label") or d.get("database"))


def qid(kind, env, d):
    return "CATALOG-%s-%s-%s" % (kind, ident(env), label(d))


def pack(engine):
    p = os.path.join(PACKS, "%s.sql" % str(engine).lower())
    if not os.path.isfile(p):
        return None
    out, cur = {}, None
    for line in open(p, encoding="utf-8").read().splitlines():
        m = re.match(r"^--\s*ID:\s*CATALOG-(\w+)", line)
        if m:
            cur = m.group(1)
            out[cur] = []
        elif cur and not line.startswith("--"):
            out[cur].append(line)
    return {k: "\n".join(v).strip() + "\n" for k, v in out.items()}


def render(sql, d):
    schemas = [str(x) for x in d.get("schemas") or []]
    inlist = ", ".join("'%s'" % s.replace("'", "''") for s in schemas)
    sql = re.sub(r"\{\{SCHEMA_FILTER:([\w.]+)\}\}", lambda m: "AND %s IN (%s)" % (m.group(1), inlist) if schemas else "", sql)
    return sql.replace("{{DB}}", str(d["database"]))


def read_only(sql):
    body = re.sub(r"'[^']*'", "''", sql)
    return not re.search(r"\b(INSERT|UPDATE|DELETE|MERGE|CREATE|ALTER|DROP|TRUNCATE|GRANT|REVOKE|COMMENT\s+ON|CALL|COPY|PUT)\b", body, re.I)


def plan(kb, only=None):
    envs, ref = environments(kb)
    qdir = os.path.join(kb, "_EVIDENCE", "queries")
    rows = []
    for env, e in envs.items():
        if only and env != only:
            continue
        for d in e["databases"]:
            p = pack(d.get("engine"))
            if not p:
                rows.append((env, d, None, "read from schema files" if d.get("engine") == "schema-files"
                             else "no pack for engine %s; use schema files" % d.get("engine")))
                continue
            for kind in KINDS:
                if kind not in p:
                    continue
                sql = render(p[kind], d)
                if not read_only(sql):
                    raise SystemExit("pack %s %s is not read only" % (d.get("engine"), kind))
                i = qid(kind, env, d)
                os.makedirs(qdir, exist_ok=True)
                with open(os.path.join(qdir, i + ".sql"), "w", encoding="utf-8") as fh:
                    fh.write("-- %s | env %s | %s %s | connection %s\n%s" % (i, env, d.get("engine"), d["database"],
                                                                             d.get("connection") or "?", sql))
                rows.append((env, d, i, "run read only, save rows as %s.json" % i))
    return ref, rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=("plan", "status"))
    ap.add_argument("kb")
    ap.add_argument("--env")
    a = ap.parse_args(argv)
    if a.cmd == "plan":
        ref, rows = plan(a.kb, a.env)
        print("reference environment: %s" % (ref or "not set"))
        for env, d, i, what in rows:
            print("- %s | %s | %s %s | %s" % (env, label(d), d.get("engine"), d["database"], i and what or what))
        return 0
    envs, ref = environments(a.kb)
    qdir = os.path.join(a.kb, "_EVIDENCE", "queries")
    for env, e in envs.items():
        for d in e["databases"]:
            if not pack(d.get("engine")):
                continue
            for kind in KINDS:
                i = qid(kind, env, d)
                if os.path.isfile(os.path.join(qdir, i + ".sql")):
                    print("- %s: %s" % (i, "saved" if os.path.isfile(os.path.join(qdir, i + ".json")) else "not run yet"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
