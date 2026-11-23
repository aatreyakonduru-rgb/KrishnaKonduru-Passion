#!/usr/bin/env python3
"""Detect the tech stack from the code and config files, show it, and record the team's approval.

    python3 detect_stack.py detect  <kb> [--all] [--no-questions]   read the repos, write .metis/DETECTED_STACK.yaml
    python3 detect_stack.py show    <kb>                            print the detected stack and what changed since approval
    python3 detect_stack.py approve <kb> --by "<name>" [--changes changes.yaml]

Only what a rule in $METIS/templates/stack-rules.yaml finds is written, each with the file and line it came from.
--all reads every git repo under sources.workspace_root (the repos cloned for the org), not only sources.repos.
A connection value that is a placeholder (${DB_URL}) becomes a VALIDATE_KB question. Secret values are never read
into the output. approve writes .metis/stack.yaml and <context_dir>/TECH_STACK.yaml; each change the team makes
(add or remove) is recorded as an answered VALIDATE_KB question with their name, and cited as [E: answer:Q-n].
changes.yaml: {add: [{category, name, repo, engine, env, value, note}], remove: [{category, name, repo}]}
"""
import argparse
import datetime
import fnmatch
import os
import re
import subprocess
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import questions  # noqa: E402
import verify_kb  # noqa: E402

ENGINES = {"postgresql": "PostgreSQL", "postgres": "PostgreSQL", "snowflake": "Snowflake", "sqlserver": "SQL Server",
           "jtds": "SQL Server", "oracle": "Oracle", "mysql": "MySQL", "mariadb": "MariaDB", "db2": "Db2", "h2": "H2",
           "redshift": "Amazon Redshift", "databricks": "Databricks", "from-ddl": "schema files"}
KEYS = ("category", "name", "repo", "engine", "env", "key", "value")


def load(p):
    if not os.path.isfile(p):
        return {}
    with open(p, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def dump(p, data, head=""):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(head)
        yaml.safe_dump(data, fh, sort_keys=False, allow_unicode=True, width=120)


def rules_file():
    for p in (os.path.join(HERE, "..", "templates", "stack-rules.yaml"),):
        if os.path.isfile(p):
            return p
    raise SystemExit("stack-rules.yaml not found")


def settings(kb):
    return load(os.path.join(kb, ".metis", "kb-profile.yaml"))


def workspace(kb, s):
    return os.path.abspath((s.get("sources") or {}).get("workspace_root") or os.path.dirname(os.path.dirname(kb)))


def repo_map(kb, s, all_repos):
    ws = workspace(kb, s)
    repos = dict((s.get("sources") or {}).get("repos") or {})
    repos.update(load(os.path.join(kb, ".metis", "stack.yaml")).get("repos") or {})
    repos = {k: v for k, v in repos.items() if not str(k).startswith("<")}
    if all_repos or not repos:
        for d in sorted(os.listdir(ws)) if os.path.isdir(ws) else []:
            if os.path.isdir(os.path.join(ws, d, ".git")) and d not in repos.values() and d not in repos:
                repos[d] = d
    return ws, repos


def commit(path):
    try:
        return subprocess.run(["git", "-C", path, "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                              timeout=10).stdout.strip() or None
    except Exception:
        return None


def tag(repo, rel, n, quote):
    quote = quote.strip().replace('"', "'")[:90]
    return '[E: %s/%s:%d "%s"]' % (repo, rel, n, quote) if quote else "[E: %s/%s:%d]" % (repo, rel, n)


def short_quote(q):
    if '"' not in q:
        return q
    parts = [x.strip(" :,{}[]") for x in q.split('"')]
    return max(parts, key=len) if any(parts) else ""


def quote_ok(line, quote):
    return quote.replace('"', "'") == quote and quote in line


def scan(kb, all_repos=False):
    s = settings(kb)
    cfg = load(rules_file())
    rules = [dict(r, rx=re.compile(r["match"], re.M)) for r in cfg["rules"]]
    conn_rx, url_rx, path_rx, curl_rx = (re.compile(cfg[k]) for k in ("connection_keys", "url_params", "url_path_db", "connection_url_keys"))
    ph_rx, secret_rx, env_rx = (re.compile(cfg[k]) for k in ("placeholder", "secret", "env_from_path"))
    conf_ext = (".yml", ".yaml", ".properties", ".env", ".json", ".conf", ".tf", ".ini", ".cfg", ".toml", ".xml")
    ws, repos = repo_map(kb, s, all_repos)
    found, unresolved, read = {}, [], []

    def add(item, src):
        k = tuple(item.get(x) for x in KEYS)
        cur = found.setdefault(k, dict(item, sources=[]))
        if len(cur["sources"]) < 5 and src not in cur["sources"]:
            cur["sources"].append(src)

    for name, folder in repos.items():
        base = folder if os.path.isabs(folder) else os.path.join(ws, folder)
        if not os.path.isdir(base):
            continue
        read.append({"name": name, "folder": folder, "commit": commit(base)})
        for d, dirs, files in os.walk(base):
            dirs[:] = sorted(x for x in dirs if x not in cfg["skip_dirs"])
            for f in sorted(files):
                p = os.path.join(d, f)
                rel = os.path.relpath(p, base).replace(os.sep, "/")
                mine = [r for r in rules if any(fnmatch.fnmatch(f, g) for g in r["files"])]
                is_conf = f.endswith(conf_ext) or f.startswith(".env")
                if not (mine or is_conf):
                    continue
                try:
                    if os.path.getsize(p) > cfg["max_file_bytes"]:
                        continue
                    with open(p, encoding="utf-8", errors="strict") as fh:
                        lines = fh.read().splitlines()
                except (UnicodeDecodeError, OSError):
                    continue
                m = env_rx.search("/" + rel)
                env = m.group(1).lower() if m else None
                for r in mine:
                    for n, line in enumerate(lines, 1):
                        mm = r["rx"].search(line)
                        if not mm:
                            continue
                        q = short_quote(mm.group(0))
                        if not quote_ok(line, q):
                            q = ""
                        item = {"category": r["category"], "name": r["name"], "repo": name}
                        eng = r.get("engine")
                        if eng == "from-match":
                            eng = mm.groupdict().get("engine")
                        if eng:
                            item["engine"] = ENGINES.get(eng, eng)
                            if env:
                                item["env"] = env
                        add(item, tag(name, rel, n, q))
                        break
                if not is_conf and not f.endswith((".py", ".java")):
                    continue
                for n, line in enumerate(lines, 1):
                    if secret_rx.search(line.split("=")[0].split(":")[0]) or len(line) > 400:
                        continue
                    hits = []
                    mm = conn_rx.search(line)
                    if mm and is_conf:
                        hits.append((mm.group(1), mm.group("value"), mm.group(0).strip()))
                    mm = curl_rx.search(line)
                    if mm and is_conf and ph_rx.search(mm.group("value")):
                        hits.append(("connection", mm.group("value"), mm.group(0).strip()))
                    for mm in url_rx.finditer(line):
                        hits.append((mm.group("key"), mm.group("value"), mm.group(0).lstrip("?&;")))
                    mm = path_rx.search(line)
                    if mm:
                        hits.append(("database", mm.group("value"), mm.group(0)))
                    for key, value, q in hits:
                        key = {"db": "database", "dbname": "database", "db_name": "database", "databasename": "database",
                               "currentschema": "schema", "schemas": "schema"}.get(key.lower(), key.lower())
                        value = value.strip("\"'")
                        q = short_quote(q)
                        if not quote_ok(line, q):
                            q = ""
                        src = tag(name, rel, n, q)
                        if ph_rx.search(value) or not value:
                            unresolved.append({"repo": name, "file": rel, "line": n, "key": key, "env": env, "source": src})
                            continue
                        add({"category": "connection", "name": key, "repo": name, "env": env, "key": key, "value": value}, src)
    items = []
    for it in found.values():
        items.append({k: v for k, v in it.items() if v is not None})
    order = ["language", "build", "framework", "ui", "database", "connection", "etl-batch", "aws", "test"]
    items.sort(key=lambda i: (order.index(i["category"]) if i["category"] in order else 99, i["name"], i["repo"], i.get("env") or ""))
    return ws, repos, read, items, unresolved


def check(kb, ws, repos, items):
    c = verify_kb.Checker(kb)
    c.root, c.repos = ws, repos
    bad = []
    for it in items:
        for src in it.get("sources", []):
            for kind, value in verify_kb.TAG.findall(src):
                why = c.resolve(kind, value)
                if why:
                    bad.append("%s %s: %s" % (it["category"], it["name"], why))
    return bad


def ident(it):
    return tuple(it.get(x) for x in KEYS)


def cmd_detect(kb, all_repos, raise_q=True):
    ws, repos, read, items, unresolved = scan(kb, all_repos)
    bad = check(kb, ws, repos, items)
    if bad:
        print("\n".join(bad))
        return 1
    dbs = {}
    for it in items:
        if it.get("engine"):
            dbs.setdefault(it["engine"], set()).add(it.get("env") or "any")
    out = {"generated_by": "detect_stack.py", "detected_on": datetime.date.today().isoformat(),
           "repos_read": read, "repos": repos, "items": items,
           "databases": [{"engine": e, "environments": sorted(v)} for e, v in sorted(dbs.items())],
           "unresolved": unresolved}
    dump(os.path.join(kb, ".metis", "DETECTED_STACK.yaml"), out, "# Written by detect_stack.py from the repos. Do not edit; approve with detect_stack.py approve.\n")
    if raise_q and unresolved:
        new = [{"question": "Which %s does %s use%s? The code reads it from a setting that is set outside the repo." % (
                    u["key"], u["repo"], " in %s" % u["env"] if u["env"] else ""),
                "type": "data", "priority": "P2",
                "context": ["%s/%s line %d takes the %s from a placeholder %s" % (u["repo"], u["file"], u["line"], u["key"], u["source"])],
                "blocks": ["context/TECH_STACK.yaml"]} for u in unresolved]
        tmp = os.path.join(kb, ".metis", "_stack_questions.yaml")
        dump(tmp, {"questions": new})
        try:
            questions.cmd_add(kb, tmp, build="stack-detection")
        finally:
            os.remove(tmp)
    print("%d repos read, %d findings, %d values set outside the repo" % (len(read), len(items), len(unresolved)))
    return 0


def text_of(it):
    bits = [it["name"]]
    if it.get("engine") and it["engine"] != it["name"]:
        bits.append("(%s)" % it["engine"])
    if it.get("value"):
        bits.append("= %s" % it["value"])
    if it.get("env"):
        bits.append("[%s]" % it["env"])
    return " ".join(bits)


def cmd_show(kb):
    det = load(os.path.join(kb, ".metis", "DETECTED_STACK.yaml"))
    if not det:
        print("No detection yet. Run: detect_stack.py detect <kb>")
        return 1
    app = load(os.path.join(kb, ".metis", "stack.yaml"))
    print("Repos read: " + ", ".join("%s (%s)" % (r["name"], r.get("commit") or "no commit") for r in det.get("repos_read") or []))
    cat = None
    for it in det.get("items") or []:
        if it["category"] != cat:
            cat = it["category"]
            print("\n" + cat)
        print("- %s, in %s %s" % (text_of(it), it["repo"], it["sources"][0]))
    if det.get("unresolved"):
        print("\nset outside the repo (asked in VALIDATE_KB)")
        for u in det["unresolved"]:
            print("- %s in %s %s" % (u["key"], u["repo"], u["source"]))
    if app:
        old = {ident(i) for i in app.get("items") or [] if "[E: answer:" not in " ".join(i.get("sources", []))}
        new = {ident(i) for i in det.get("items") or []}
        gone = {ident(i) for i in app.get("removed") or []}
        added = [i for i in det["items"] if ident(i) not in old and ident(i) not in gone]
        lost = [i for i in app.get("items") or [] if ident(i) in old - new]
        print("\nSince approval by %s on %s:" % (app.get("approved_by"), app.get("approved_on")))
        print("\n".join(["- new: %s in %s" % (text_of(i), i["repo"]) for i in added] +
                        ["- no longer found: %s in %s" % (text_of(i), i["repo"]) for i in lost]) or "- no changes")
    return 0


def record(kb, reg, text, by, note):
    qs = reg.setdefault("questions", [])
    nums = [int(q["id"][2:]) for q in qs if re.match(r"^Q-\d+$", str(q.get("id")))]
    qid = "Q-%04d" % (max(nums or [0]) + 1)
    today = datetime.date.today().isoformat()
    qs.append({"id": qid, "question": text, "type": "application", "priority": "P3",
               "answer_role": questions.role_for(kb, "application"),
               "context": ["Detected stack at approval [E: kb:.metis/DETECTED_STACK.yaml]"], "blocks": ["context/TECH_STACK.yaml"],
               "possible_answers": [], "status": "answered", "answer": note or "Changed by %s at stack approval" % by,
               "answered_by": by, "answered_on": today, "raised_on": today, "raised_by_build": "stack-approval"})
    return qid


def match(it, sel):
    return all(it.get(k) == v for k, v in sel.items() if k in KEYS and v is not None)


def cmd_approve(kb, by, changes_file=None):
    det = load(os.path.join(kb, ".metis", "DETECTED_STACK.yaml"))
    if not det:
        print("No detection yet. Run: detect_stack.py detect <kb>")
        return 1
    if not by or not by.strip():
        print("approve needs --by <name of the person approving>")
        return 1
    ch = load(changes_file) if changes_file else {}
    reg = questions.load(questions.reg_path(kb)) or {"questions": []}
    items, removed = [dict(i) for i in det.get("items") or []], []
    for sel in ch.get("remove") or []:
        hit = [i for i in items if match(i, sel)]
        if not hit:
            print("nothing detected matches %s" % sel)
            return 1
        qid = record(kb, reg, "Stack change at approval: remove %s %s" % (sel.get("category") or "", sel.get("name")), by, sel.get("note"))
        for i in hit:
            items.remove(i)
            removed.append(dict(i, removed_by="[E: answer:%s]" % qid))
    for a in ch.get("add") or []:
        if not (a.get("category") and a.get("name")):
            print("an added item needs category and name: %s" % a)
            return 1
        qid = record(kb, reg, "Stack change at approval: add %s %s" % (a["category"], text_of(dict(a, repo=a.get("repo")))), by, a.get("note"))
        items.append(dict({k: a[k] for k in KEYS if a.get(k)}, sources=["[E: answer:%s]" % qid]))
    bad = questions.problems(kb, reg)
    if bad:
        print("\n".join(bad))
        return 1
    questions.save(kb, reg)
    today = datetime.date.today().isoformat()
    st = {"approved_by": by, "approved_on": today, "repos": det.get("repos") or {}, "items": items, "removed": removed}
    dump(os.path.join(kb, ".metis", "stack.yaml"), st, "# The team's approved tech stack. Written by detect_stack.py approve.\n")
    s = settings(kb)
    ctx = ((s.get("paths") or {}).get("context_dir") or "<KB>/context").replace("<KB>/", "").replace("<KB>", "")
    ctx = ctx if os.path.isabs(ctx) else os.path.join(kb, ctx)
    dump(os.path.join(ctx, "TECH_STACK.yaml"), {"approved_by": by, "approved_on": today, "items": items},
         "# Tech stack, from the code and config files; changes by the team cite their VALIDATE_KB answer.\n")
    print("Approved by %s: %d items, %d added, %d removed" % (by, len(items), len(ch.get("add") or []), len(removed)))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=("detect", "show", "approve"))
    ap.add_argument("kb")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--no-questions", action="store_true")
    ap.add_argument("--by")
    ap.add_argument("--changes")
    a = ap.parse_args(argv)
    if a.cmd == "detect":
        return cmd_detect(a.kb, a.all, not a.no_questions)
    if a.cmd == "show":
        return cmd_show(a.kb)
    return cmd_approve(a.kb, a.by, a.changes)


if __name__ == "__main__":
    sys.exit(main())
