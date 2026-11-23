#!/usr/bin/env python3
"""Read-only Jira snapshot for the Mētis dashboard. Nothing is written to Jira or to the repo.

    python3 dash_jira.py <kb> -o /tmp/metis-dashboard/<run>/jira.json

Uses `sources.jira` in <KB>/.metis/kb-profile.yaml (base_url, projects, jql, secret) and `jira` in
<KB>/.metis/dashboard.yaml (sprint_field, points_field, done_days, verify_tls). The token is read from the
environment variable named by `secret` and is never printed. On 401/403 it stops and does not retry.
"""
import argparse
import datetime
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

import yaml

MAX_ISSUES = 2000


def load(p):
    if not os.path.isfile(p):
        return {}
    with open(p, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


class Jira:
    def __init__(self, base, token, verify=True):
        self.base = base.rstrip("/")
        self.token = token
        self.ctx = None if verify else ssl._create_unverified_context()

    def get(self, path, api="/rest/api/2", **params):
        url = self.base + api + path + ("?" + urllib.parse.urlencode(params) if params else "")
        req = urllib.request.Request(url, headers={"Authorization": "Bearer " + self.token, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, context=self.ctx, timeout=120) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise SystemExit("Jira returned %d. The service-account token is invalid or locked and needs to be "
                                 "rotated. Not retrying." % e.code)
            raise


def sprint_of(value):
    """Name and state of the active sprint (else the last one) from a Sprint field value, Server or Cloud form."""
    out = []
    for v in value or []:
        if isinstance(v, dict):
            out.append({"name": v.get("name"), "state": str(v.get("state") or "").upper()})
        else:
            n, s = re.search(r"name=([^,\]]*)", str(v)), re.search(r"state=([^,\]]*)", str(v))
            out.append({"name": n and n.group(1), "state": (s and s.group(1) or "").upper()})
    act = [s for s in out if s["state"] == "ACTIVE"]
    return (act or out or [{"name": None, "state": None}])[-1]


def person(v):
    if not v:
        return None
    return {"display": v.get("displayName"), "email": (v.get("emailAddress") or "").lower() or None,
            "name": v.get("name") or v.get("accountId")}


def row(issue, sf, pf):
    f = issue.get("fields") or {}
    sp = sprint_of(f.get(sf)) if sf else {"name": None, "state": None}
    return {"key": issue["key"], "summary": f.get("summary"), "type": (f.get("issuetype") or {}).get("name"),
            "status": (f.get("status") or {}).get("name"),
            "status_category": ((f.get("status") or {}).get("statusCategory") or {}).get("key"),
            "assignee": person(f.get("assignee")), "reporter": person(f.get("reporter")), "priority": (f.get("priority") or {}).get("name"),
            "points": f.get(pf) if pf else None, "sprint": sp["name"], "sprint_state": sp["state"],
            "created": f.get("created"), "updated": f.get("updated"), "resolved": f.get("resolutiondate"),
            "labels": f.get("labels") or []}


def search(j, jql, fields):
    out, start = [], 0
    while len(out) < MAX_ISSUES:
        r = j.get("/search", jql=jql, startAt=start, maxResults=100, fields=",".join(fields))
        out += r.get("issues") or []
        start += len(r.get("issues") or [])
        if not r.get("issues") or start >= r.get("total", 0):
            break
    return out


def list_boards(src, cfg, project, out):
    if not (src.get("base_url") and src.get("secret")):
        raise SystemExit("sources.jira needs base_url and secret in kb-profile.yaml")
    token = os.environ.get(src["secret"])
    if not token:
        raise SystemExit("the secret %s is not set in this session" % src["secret"])
    j = Jira(src["base_url"], token, cfg.get("verify_tls", True) is not False)
    j.get("/myself")
    boards, start = [], 0
    while True:
        r = j.get("/board", api="/rest/agile/1.0", projectKeyOrId=project, startAt=start, maxResults=50)
        boards += [{"id": b.get("id"), "name": b.get("name"), "type": b.get("type")} for b in r.get("values") or []]
        if r.get("isLast", True) or not r.get("values"):
            break
        start += len(r["values"])
    for b in boards:
        print("%s\t%s\t%s" % (b["id"], b["type"], b["name"]))
    print("%d board(s) in %s visible to this service account" % (len(boards), project))
    if out:
        with open(out, "w", encoding="utf-8") as fh:
            json.dump({"project": project, "base_url": src["base_url"].rstrip("/"), "boards": boards}, fh, indent=1)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("kb")
    ap.add_argument("-o", "--out")
    ap.add_argument("--list-boards", metavar="PROJECT", help="list the boards of a project this service account can see, then stop")
    a = ap.parse_args(argv)
    prof = load(os.path.join(a.kb, ".metis", "kb-profile.yaml"))
    dash = load(os.path.join(a.kb, ".metis", "dashboard.yaml"))
    src = (prof.get("sources") or {}).get("jira") or {}
    cfg = dash.get("jira") or {}
    if a.list_boards:
        return list_boards(src, cfg, a.list_boards, a.out)
    if not a.out:
        ap.error("-o is needed")
    if not (src.get("base_url") and (src.get("projects") or src.get("boards")) and src.get("secret")):
        raise SystemExit("sources.jira needs base_url, projects or boards, and secret in kb-profile.yaml")
    token = os.environ.get(src["secret"])
    if not token:
        raise SystemExit("the secret %s is not set in this session" % src["secret"])
    j = Jira(src["base_url"], token, cfg.get("verify_tls", True) is not False)
    me = j.get("/myself")
    sf, pf = cfg.get("sprint_field"), cfg.get("points_field")
    if not (sf and pf):
        names = {f.get("name"): f.get("id") for f in j.get("/field")}
        sf = sf or names.get("Sprint")
        pf = pf or names.get("Story Points") or names.get("Story points")
    days = int(cfg.get("done_days") or 14)
    fields = ["summary", "status", "assignee", "reporter", "issuetype", "priority", "created", "updated", "resolutiondate", "labels"]
    fields += [x for x in (sf, pf) if x]
    scopes = []
    for b in src.get("boards") or []:
        conf = j.get("/board/%s/configuration" % b["id"], api="/rest/agile/1.0")
        fq = j.get("/filter/%s" % ((conf.get("filter") or {}).get("id")))
        scopes.append((b.get("name") or str(b["id"]), re.split(r"(?i)\s+ORDER\s+BY\s", fq.get("jql") or "")[0].strip()))
    if src.get("projects"):
        scopes.append((None, "project in (%s)" % ",".join('"%s"' % p for p in src["projects"])))
    issues, q_open, q_done = {}, [], []
    for board, base in scopes:
        if (src.get("jql") or "").strip():
            base = "(%s) AND (%s)" % (base, src["jql"].strip())
        qo = "(%s) AND statusCategory != Done ORDER BY updated DESC" % base
        qd = "(%s) AND statusCategory = Done AND resolved >= -%dd ORDER BY resolved DESC" % (base, days)
        q_open.append(qo)
        q_done.append(qd)
        for i in search(j, qo, fields) + search(j, qd, fields):
            r = issues.setdefault(i["key"], row(i, sf, pf))
            r.setdefault("boards", [])
            if board and board not in r["boards"]:
                r["boards"].append(board)
    issues = list(issues.values())
    q_open, q_done = " ; ".join(q_open), " ; ".join(q_done)
    snap = {"read_at": datetime.datetime.now().isoformat(timespec="minutes"), "base_url": src["base_url"].rstrip("/"),
            "jql_open": q_open, "jql_done": q_done, "boards": [b.get("name") or str(b["id"]) for b in src.get("boards") or []], "service_account": {"name": me.get("name"), "email": (me.get("emailAddress") or "").lower() or None},
            "done_days": days, "sprint_field": sf, "points_field": pf,
            "issues": issues}
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(snap, fh, indent=1)
    n_open = sum(1 for i in issues if i["status_category"] != "done")
    if n_open >= MAX_ISSUES:
        print("WARNING: open issues hit the %d-issue cap; counts are truncated. Narrow sources.jira (drop whole-project queries, keep board filters)." % MAX_ISSUES)
    if any(re.match(r"^\s*\(?\s*project\s+(in|=)", q.strip(), re.I) and "team" not in q.lower() for q in q_open.split(" ; ")):
        print("WARNING: a whole-project JQL is in sources.jira; it pulls in every team in the project.")
    print("jira: %d issues read (%d not done, last %d days done) -> %s" % (
        len(issues), sum(1 for i in issues if i["status_category"] != "done"), days, a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
