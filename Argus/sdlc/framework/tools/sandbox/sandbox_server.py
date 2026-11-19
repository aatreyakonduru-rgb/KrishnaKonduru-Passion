#!/usr/bin/env python3
"""The sandbox: Jira and Confluence for a made-up team, kept in plain files in one folder.

    python3 server.py --folder ~/Documents/sdlc-sandbox [--port 8799]

It answers the Jira REST (api/2 and agile/1.0) and Confluence REST (api/content) calls the framework
makes, from <folder>/jira.yaml and <folder>/confluence/, and writes changes back to them, so creating a
ticket, moving it or publishing a page really happens, but only in the sandbox. The Confluence pages
can be read in a browser at the server's address. Any token is accepted; a token that is a sandbox
user name signs in as that user (/rest/api/2/myself). Point the framework at it with
SDLC_SANDBOX=<folder> (tools/sandbox/switch.py). Standard library plus PyYAML.
"""
import argparse
import datetime
import html
import json
import os
import re
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sandbox_jql as jqlmod  # noqa: E402

PORT = 8799
DONE_WORDS = ("done", "closed", "cancelled", "canceled", "rejected", "complete", "completed")


def now():
    return datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S.000+0000")


def load_yaml(path, default):
    import yaml
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or default


def save_yaml(path, data):
    import yaml
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, sort_keys=False, allow_unicode=True, width=110)
    os.replace(tmp, path)


class HttpError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


# ---- Jira ----------------------------------------------------------------------------------------

class Jira:
    def __init__(self, folder):
        self.path = os.path.join(folder, "jira.yaml")
        self.files = os.path.join(folder, "jira-attachments")
        self.data = load_yaml(self.path, {})
        d = self.data
        d.setdefault("project", {"key": "ACME", "name": "Acme Claims"})
        d.setdefault("fields", {})
        d.setdefault("statuses", [])
        d.setdefault("users", [])
        d.setdefault("sprints", [])
        d.setdefault("issues", {})
        d.setdefault("next", {"issue": 1 + max([self.num(k) for k in d["issues"]] or [0]), "id": 1000})

    @staticmethod
    def num(key):
        m = re.search(r"-(\d+)$", str(key))
        return int(m.group(1)) if m else 0

    def save(self):
        save_yaml(self.path, self.data)

    def next_id(self):
        self.data["next"]["id"] += 1
        return str(self.data["next"]["id"])

    # lookups
    def user(self, name):
        if not name:
            return None
        n = str(name).lower()
        for u in self.data["users"]:
            if n in (str(u.get("name", "")).lower(), str(u.get("emailAddress", "")).lower(),
                     str(u.get("displayName", "")).lower(), str(u.get("key", "")).lower()):
                return u
        return None

    def user_json(self, name):
        u = self.user(name)
        if not u and not name:
            return None
        u = u or {"name": name, "displayName": name}
        return {"name": u["name"], "key": u.get("key", u["name"]), "displayName": u.get("displayName", u["name"]),
                "emailAddress": u.get("emailAddress", ""), "active": u.get("active", True)}

    def sprint(self, sid):
        for s in self.data["sprints"]:
            if str(s["id"]) == str(sid):
                return s
        return None

    def category(self, status):
        for s in self.data["statuses"]:
            if str(s["name"]).lower() == str(status or "").lower():
                return s.get("category", "indeterminate")
        low = str(status or "").lower()
        return "done" if low in DONE_WORDS else "new" if low in ("to do", "open", "new", "backlog") else "indeterminate"

    def custom(self, field):
        f = field.strip('"').lower()
        m = re.fullmatch(r"cf\[(\d+)\]", f)
        if m:
            return "customfield_" + m.group(1)
        if f.startswith("customfield_"):
            return f
        for name, fid in self.data["fields"].items():
            if name.lower() == f or str(fid).lower() == f:
                return fid
        return None

    def issue(self, key):
        rec = self.data["issues"].get(str(key).upper())
        if rec is None:
            for k, r in self.data["issues"].items():
                if str(r.get("id")) == str(key):
                    return k, r
            raise HttpError(404, "Issue Does Not Exist")
        return str(key).upper(), rec

    def ctx(self, user):
        return {"user": user, "sprints": self.data["sprints"], "user_of": self.user, "sprint": self.sprint,
                "category": self.category, "custom": self.custom, "project_name": self.data["project"]["name"]}

    # rendering
    def brief(self, key):
        rec = self.data["issues"].get(key) or {}
        return {"id": rec.get("id", key), "key": key, "fields": {
            "summary": rec.get("summary", ""), "status": self.status_json(rec.get("status")),
            "issuetype": self.type_json(rec.get("issuetype")), "priority": {"name": rec.get("priority") or "Medium"}}}

    def status_json(self, name):
        cat = self.category(name)
        return {"name": name or "", "id": name or "", "statusCategory": {"key": cat, "name": {
            "new": "To Do", "done": "Done"}.get(cat, "In Progress")}}

    @staticmethod
    def type_json(name):
        name = name or "Story"
        return {"name": name, "id": name, "subtask": name.lower() in ("sub-task", "subtask")}

    def sprint_strings(self, ids):
        out = []
        for sid in ids or []:
            s = self.sprint(sid) or {"id": sid, "name": str(sid), "state": "future"}
            out.append("com.atlassian.greenhopper.service.sprint.Sprint@%s[id=%s,rapidViewId=1,state=%s,name=%s,"
                       "startDate=%s,endDate=%s,completeDate=<null>,sequence=%s]" % (
                           s["id"], s["id"], str(s.get("state", "future")).upper(), s["name"],
                           s.get("startDate") or "<null>", s.get("endDate") or "<null>", s["id"]))
        return out

    def render(self, key, rec, fields=None, expand=""):
        f = {
            "summary": rec.get("summary", ""), "description": rec.get("description"),
            "issuetype": self.type_json(rec.get("issuetype")), "status": self.status_json(rec.get("status")),
            "resolution": {"name": rec["resolution"]} if rec.get("resolution") else None,
            "resolutiondate": rec.get("resolutiondate"), "priority": {"name": rec.get("priority") or "Medium"},
            "assignee": self.user_json(rec.get("assignee")) if rec.get("assignee") else None,
            "reporter": self.user_json(rec.get("reporter")) if rec.get("reporter") else None,
            "creator": self.user_json(rec.get("reporter")) if rec.get("reporter") else None,
            "labels": list(rec.get("labels") or []), "created": rec.get("created"), "updated": rec.get("updated"),
            "duedate": rec.get("duedate"),
            "project": {"key": self.data["project"]["key"], "name": self.data["project"]["name"]},
            "components": [{"name": c} for c in rec.get("components") or []],
            "fixVersions": [{"name": v} for v in rec.get("fix_versions") or []],
            "parent": self.brief(rec["parent"]) if rec.get("parent") and rec["parent"] in self.data["issues"] else None,
            "subtasks": [self.brief(k) for k, r in self.data["issues"].items() if r.get("parent") == key
                         and str(r.get("issuetype", "")).lower() in ("sub-task", "subtask")],
            "issuelinks": [self.link_json(key, ln) for ln in self.links_of(key)],
            "comment": {"comments": [self.comment_json(c) for c in rec.get("comments") or []],
                        "total": len(rec.get("comments") or []), "maxResults": 1000, "startAt": 0},
            "worklog": {"worklogs": [self.worklog_json(w) for w in rec.get("worklogs") or []],
                        "total": len(rec.get("worklogs") or []), "maxResults": 1000, "startAt": 0},
            "attachment": [self.attachment_json(a) for a in rec.get("attachments") or []],
            "timespent": sum(int(w.get("seconds", 0)) for w in rec.get("worklogs") or []) or None,
            "timeoriginalestimate": rec.get("estimate_seconds"),
            "aggregatetimespent": sum(int(w.get("seconds", 0)) for w in rec.get("worklogs") or []) or None,
        }
        for name, fid in self.data["fields"].items():
            if name.lower() == "sprint":
                f[fid] = self.sprint_strings(rec.get("sprints")) or None
            elif name.lower() == "epic link":
                parent = rec.get("parent")
                f[fid] = parent if parent and str(self.data["issues"].get(parent, {}).get("issuetype")) == "Epic" else None
            else:
                f[fid] = (rec.get("fields") or {}).get(fid)
        for fid, v in (rec.get("fields") or {}).items():
            f.setdefault(fid, v)
        if fields:
            want = set(fields)
            if "*all" not in want and "*navigable" not in want:
                f = {k: v for k, v in f.items() if k in want}
        out = {"id": rec.get("id", key), "key": key, "self": "/rest/api/2/issue/%s" % key, "fields": f}
        if "changelog" in (expand or ""):
            out["changelog"] = {"histories": rec.get("history") or [], "total": len(rec.get("history") or [])}
        if "names" in (expand or ""):
            out["names"] = {fid: name for name, fid in self.data["fields"].items()}
        return out

    def comment_json(self, c):
        return {"id": c["id"], "body": c.get("body", ""), "created": c.get("created"), "updated": c.get("created"),
                "author": self.user_json(c.get("author")), "updateAuthor": self.user_json(c.get("author"))}

    def worklog_json(self, w):
        return {"id": w["id"], "timeSpentSeconds": int(w.get("seconds", 0)), "comment": w.get("comment", ""),
                "started": w.get("started"), "author": self.user_json(w.get("author"))}

    @staticmethod
    def attachment_json(a):
        return {"id": a["id"], "filename": a["filename"], "size": a.get("size", 0), "created": a.get("created"),
                "content": "/secure/attachment/%s/%s" % (a["id"], urllib.parse.quote(a["filename"]))}

    def links_of(self, key):
        return [ln for ln in self.data.setdefault("links", []) if key in (ln["inward"], ln["outward"])]

    def link_json(self, key, ln):
        t = ln.get("type", "Relates")
        names = {"Blocks": ("is blocked by", "blocks"), "Relates": ("relates to", "relates to"),
                 "Duplicate": ("is duplicated by", "duplicates"), "Cloners": ("is cloned by", "clones")}
        inward, outward = names.get(t, (t.lower(), t.lower()))
        out = {"id": ln["id"], "type": {"name": t, "inward": inward, "outward": outward}}
        if ln["outward"] == key:
            out["inwardIssue"] = self.brief(ln["inward"])
        else:
            out["outwardIssue"] = self.brief(ln["outward"])
        return out

    # writes
    def apply_fields(self, rec, fields):
        simple = {"summary": "summary", "description": "description", "duedate": "duedate"}
        for k, v in (fields or {}).items():
            if k in simple:
                rec[simple[k]] = v
            elif k == "issuetype":
                rec["issuetype"] = v.get("name") if isinstance(v, dict) else v
            elif k in ("assignee", "reporter"):
                rec[k] = (v or {}).get("name") or (v or {}).get("key") if isinstance(v, dict) else v
            elif k == "priority":
                rec["priority"] = v.get("name") if isinstance(v, dict) else v
            elif k == "labels":
                rec["labels"] = list(v or [])
            elif k == "parent":
                rec["parent"] = (v or {}).get("key") if isinstance(v, dict) else v
            elif k == "components":
                rec["components"] = [c.get("name") if isinstance(c, dict) else c for c in v or []]
            elif k == "fixVersions":
                rec["fix_versions"] = [c.get("name") if isinstance(c, dict) else c for c in v or []]
            elif k == "timetracking":
                est = (v or {}).get("originalEstimate")
                if est:
                    rec["estimate_seconds"] = seconds(est)
            elif k == "project":
                continue
            else:
                name = next((n for n, fid in self.data["fields"].items() if fid == k), "")
                if name.lower() == "sprint":
                    rec["sprints"] = [v] if v and not isinstance(v, list) else list(v or [])
                elif name.lower() == "epic link":
                    rec["parent"] = v
                else:
                    rec.setdefault("fields", {})[k] = v

    def apply_update(self, rec, update):
        for k, ops in (update or {}).items():
            for op in ops or []:
                if k == "labels":
                    labels = rec.setdefault("labels", [])
                    if "add" in op and op["add"] not in labels:
                        labels.append(op["add"])
                    if "remove" in op and op["remove"] in labels:
                        labels.remove(op["remove"])
                    if "set" in op:
                        rec["labels"] = list(op["set"])
                elif k == "comment" and "add" in op:
                    rec.setdefault("comments", []).append({"id": self.next_id(), "body": op["add"].get("body", ""),
                                                           "author": self.data.get("me"), "created": now()})
                elif "set" in op:
                    self.apply_fields(rec, {k: op["set"]})

    def create(self, body, user):
        fields = body.get("fields") or {}
        key = "%s-%d" % (self.data["project"]["key"], self.data["next"]["issue"])
        self.data["next"]["issue"] += 1
        first = self.first_status()
        rec = {"id": self.next_id(), "issuetype": "Story", "summary": "", "status": first, "reporter": user,
               "labels": [], "created": now(), "updated": now()}
        self.apply_fields(rec, fields)
        self.apply_update(rec, body.get("update"))
        self.data["issues"][key] = rec
        self.save()
        return {"id": rec["id"], "key": key, "self": "/rest/api/2/issue/%s" % key}

    def first_status(self):
        for s in self.data["statuses"]:
            if s.get("category") == "new":
                return s["name"]
        return "To Do"

    def touch(self, rec, user, what):
        rec["updated"] = now()
        rec.setdefault("history", []).append({"created": rec["updated"], "author": self.user_json(user),
                                              "items": [what]})

    def search(self, query, start, limit, fields, user, expand=""):
        ctx = self.ctx(user)
        try:
            node = jqlmod.parse(query or "")
        except jqlmod.JqlError as exc:
            raise HttpError(400, "Error in the JQL Query: %s" % exc)
        hits = [(k, r) for k, r in self.data["issues"].items() if jqlmod.evaluate(node, dict(r, key=k), ctx)]
        for field, desc in reversed(jqlmod.order(query or "") or [("key", True)]):
            hits.sort(key=lambda kr: self.sort_key(field, kr), reverse=desc)
        page = hits[start:start + limit]
        return {"startAt": start, "maxResults": limit, "total": len(hits),
                "issues": [self.render(k, r, fields, expand) for k, r in page],
                "warningMessages": sorted("the sandbox ignored %s" % f for f in ctx.get("unknown", ()))}

    def sort_key(self, field, kr):
        key, rec = kr
        if field in ("key", "issuekey", "rank", "id"):
            return (0, self.num(key), "")
        if field in ("created", "updated", "resolutiondate", "resolved", "duedate"):
            return (0, 0, str(rec.get("resolutiondate" if field == "resolved" else field) or ""))
        if field == "priority":
            order = ["highest", "high", "medium", "low", "lowest"]
            p = str(rec.get("priority") or "medium").lower()
            return (0, order.index(p) if p in order else 2, "")
        return (0, 0, str(rec.get(field) or (rec.get("fields") or {}).get(self.custom(field) or "", "")))

    def transitions(self, key):
        _, rec = self.issue(key)
        return {"transitions": [{"id": str(i + 1), "name": s["name"], "to": self.status_json(s["name"])}
                                for i, s in enumerate(self.data["statuses"]) if s["name"] != rec.get("status")]}

    def transition(self, key, body, user):
        k, rec = self.issue(key)
        t = (body.get("transition") or {})
        tid, name = str(t.get("id", "")), t.get("name")
        target = None
        for i, s in enumerate(self.data["statuses"]):
            if str(i + 1) == tid or (name and s["name"].lower() == str(name).lower()):
                target = s["name"]
        if not target:
            raise HttpError(400, "Transition id %s is not valid for this issue." % tid)
        old = rec.get("status")
        rec["status"] = target
        if self.category(target) == "done":
            rec["resolution"] = ((body.get("fields") or {}).get("resolution") or {}).get("name") or "Done"
            rec["resolutiondate"] = now()
        else:
            rec.pop("resolution", None)
            rec.pop("resolutiondate", None)
        self.apply_fields(rec, {f: v for f, v in (body.get("fields") or {}).items() if f != "resolution"})
        self.apply_update(rec, body.get("update"))
        self.touch(rec, user, {"field": "status", "fromString": old, "toString": target})
        self.save()

    def handle(self, method, path, query, body, user, raw=None, headers=None):
        p = path[len("/rest"):] if path.startswith("/rest") else path
        q = {k: v[-1] for k, v in query.items()}
        if p == "/api/2/myself":
            me = self.user_json(user or self.data.get("me"))
            if not me:
                raise HttpError(401, "not signed in")
            return me
        if p in ("/api/2/user/search", "/api/2/user/assignable/search", "/api/2/user/picker"):
            term = (q.get("username") or q.get("query") or "").lower()
            found = [self.user_json(u["name"]) for u in self.data["users"] if not term or term in json.dumps(u).lower()]
            return {"users": found, "total": len(found)} if p.endswith("picker") else found
        if p == "/api/2/user":
            u = self.user(q.get("username") or q.get("key"))
            if not u:
                raise HttpError(404, "The user named '%s' does not exist" % q.get("username"))
            return self.user_json(u["name"])
        if p == "/api/2/field":
            std = [{"id": f, "name": f.title(), "custom": False} for f in (
                "summary", "description", "status", "assignee", "reporter", "labels", "priority", "issuetype",
                "created", "updated", "resolution", "parent", "comment", "issuelinks")]
            return std + [{"id": fid, "name": name, "custom": True, "schema": {"type": "any", "customId": fid}}
                          for name, fid in self.data["fields"].items()]
        m = re.fullmatch(r"/api/2/project/([^/]+)(/statuses)?", p)
        if m:
            pr = self.data["project"]
            if m.group(1).upper() not in (pr["key"].upper(), str(pr.get("id", "")).upper()):
                raise HttpError(404, "No project could be found with key '%s'." % m.group(1))
            if m.group(2):
                types = sorted({str(r.get("issuetype")) for r in self.data["issues"].values()} |
                               {"Epic", "Story", "Task", "Bug", "Sub-task"})
                return [{"name": t, "id": t, "subtask": t == "Sub-task",
                         "statuses": [self.status_json(s["name"]) for s in self.data["statuses"]]} for t in types]
            return {"key": pr["key"], "name": pr["name"], "id": pr.get("id", "10000"),
                    "issueTypes": [{"name": t} for t in ("Epic", "Story", "Task", "Bug", "Sub-task")]}
        if p == "/api/2/search":
            src = body if method == "POST" else q
            fields = src.get("fields")
            if isinstance(fields, str):
                fields = [x.strip() for x in fields.split(",") if x.strip()]
            return self.search(src.get("jql", ""), int(src.get("startAt", 0) or 0),
                               min(int(src.get("maxResults", 50) or 50), 1000), fields, user, src.get("expand", ""))
        if p == "/api/2/issue" and method == "POST":
            return self.create(body, user)
        if p == "/api/2/issue/bulk" and method == "POST":
            return {"issues": [self.create(b, user) for b in body.get("issueUpdates") or []], "errors": []}
        if p == "/api/2/issueLink" and method == "POST":
            inward = (body.get("inwardIssue") or {}).get("key")
            outward = (body.get("outwardIssue") or {}).get("key")
            self.issue(inward)
            self.issue(outward)
            self.data.setdefault("links", []).append({"id": self.next_id(), "type": (body.get("type") or {}).get(
                "name", "Relates"), "inward": inward, "outward": outward})
            self.save()
            return None
        m = re.fullmatch(r"/api/2/attachment/([^/]+)", p)
        if m:
            for k, r in self.data["issues"].items():
                for a in r.get("attachments") or []:
                    if str(a["id"]) == m.group(1):
                        return self.attachment_json(a)
            raise HttpError(404, "attachment not found")
        m = re.fullmatch(r"/api/2/issue/([^/]+)(?:/(\w+))?", p)
        if m:
            key, sub = m.group(1), m.group(2)
            k, rec = self.issue(key)
            if not sub:
                if method == "GET":
                    fields = [x for x in (q.get("fields") or "").split(",") if x] or None
                    return self.render(k, rec, fields, q.get("expand", ""))
                if method == "PUT":
                    self.apply_fields(rec, body.get("fields"))
                    self.apply_update(rec, body.get("update"))
                    self.touch(rec, user, {"field": "fields", "toString": ", ".join(sorted(
                        list((body.get("fields") or {}).keys()) + list((body.get("update") or {}).keys())))})
                    self.save()
                    return None
                if method == "DELETE":
                    del self.data["issues"][k]
                    self.save()
                    return None
            if sub == "comment":
                if method == "POST":
                    c = {"id": self.next_id(), "body": body.get("body", ""), "author": user, "created": now()}
                    rec.setdefault("comments", []).append(c)
                    self.touch(rec, user, {"field": "comment", "toString": "added"})
                    self.save()
                    return self.comment_json(c)
                cs = rec.get("comments") or []
                return {"comments": [self.comment_json(c) for c in cs], "total": len(cs), "startAt": 0,
                        "maxResults": len(cs)}
            if sub == "transitions":
                if method == "POST":
                    self.transition(k, body, user)
                    return None
                return self.transitions(k)
            if sub == "assignee" and method == "PUT":
                rec["assignee"] = body.get("name") or body.get("key")
                self.touch(rec, user, {"field": "assignee", "toString": rec["assignee"]})
                self.save()
                return None
            if sub == "worklog":
                if method == "POST":
                    secs = body.get("timeSpentSeconds") or seconds(body.get("timeSpent") or "0m")
                    w = {"id": self.next_id(), "seconds": int(secs), "comment": body.get("comment", ""),
                         "started": body.get("started") or now(), "author": user}
                    rec.setdefault("worklogs", []).append(w)
                    self.touch(rec, user, {"field": "timespent", "toString": str(secs)})
                    self.save()
                    return self.worklog_json(w)
                ws = rec.get("worklogs") or []
                return {"worklogs": [self.worklog_json(w) for w in ws], "total": len(ws), "startAt": 0,
                        "maxResults": len(ws)}
            if sub == "attachments" and method == "POST":
                made = []
                for name, data in multipart_files(raw, headers):
                    a = {"id": self.next_id(), "filename": name, "size": len(data), "created": now(), "author": user}
                    os.makedirs(self.files, exist_ok=True)
                    with open(os.path.join(self.files, "%s-%s" % (a["id"], safe_name(name))), "wb") as fh:
                        fh.write(data)
                    rec.setdefault("attachments", []).append(a)
                    made.append(self.attachment_json(a))
                self.save()
                return made
        # agile
        if p == "/agile/1.0/board":
            return {"values": [{"id": 1, "name": "%s board" % self.data["project"]["name"], "type": "scrum"}],
                    "isLast": True, "startAt": 0, "maxResults": 50, "total": 1}
        m = re.fullmatch(r"/agile/1\.0/board/([^/]+)/sprint", p)
        if m:
            states = [s.strip() for s in (q.get("state") or "").split(",") if s.strip()]
            vals = [self.sprint_json(s) for s in self.data["sprints"] if not states or s.get("state") in states]
            start = int(q.get("startAt", 0) or 0)
            return {"values": vals[start:], "isLast": True, "startAt": start, "maxResults": 50, "total": len(vals)}
        m = re.fullmatch(r"/agile/1\.0/sprint/([^/]+)(/issue)?", p)
        if m:
            s = self.sprint(m.group(1))
            if not s:
                raise HttpError(404, "sprint not found")
            if not m.group(2):
                return self.sprint_json(s)
            if method == "POST":
                for key in body.get("issues") or []:
                    _, rec = self.issue(key)
                    rec["sprints"] = [x for x in rec.get("sprints") or [] if self.sprint(x) and
                                      self.sprint(x).get("state") == "closed"] + [s["id"]]
                    self.touch(rec, user, {"field": "Sprint", "toString": s["name"]})
                self.save()
                return None
            fields = [x for x in (q.get("fields") or "").split(",") if x] or None
            return self.search("sprint = %s" % s["id"] + (" AND (%s)" % q["jql"] if q.get("jql") else ""),
                               int(q.get("startAt", 0) or 0), int(q.get("maxResults", 50) or 50), fields, user)
        if p == "/agile/1.0/backlog/issue" and method == "POST":
            for key in body.get("issues") or []:
                _, rec = self.issue(key)
                rec["sprints"] = [x for x in rec.get("sprints") or [] if (self.sprint(x) or {}).get("state") == "closed"]
                self.touch(rec, user, {"field": "Sprint", "toString": "backlog"})
            self.save()
            return None
        m = re.fullmatch(r"/agile/1\.0/board/([^/]+)/backlog", p)
        if m:
            open_ids = {s["id"] for s in self.data["sprints"] if s.get("state") in ("active", "future")}
            keys = [(k, r) for k, r in self.data["issues"].items() if not set(r.get("sprints") or []) & open_ids
                    and self.category(r.get("status")) != "done"]
            return {"issues": [self.render(k, r) for k, r in keys], "total": len(keys), "startAt": 0}
        raise HttpError(404, "the sandbox has no Jira call %s %s" % (method, path))

    @staticmethod
    def sprint_json(s):
        return {"id": s["id"], "name": s["name"], "state": s.get("state", "future"), "startDate": s.get("startDate"),
                "endDate": s.get("endDate"), "completeDate": s.get("completeDate"), "originBoardId": 1,
                "goal": s.get("goal", "")}


def seconds(text):
    total = 0
    for n, unit in re.findall(r"(\d+(?:\.\d+)?)\s*([wdhm])", str(text)):
        total += float(n) * {"w": 5 * 8 * 3600, "d": 8 * 3600, "h": 3600, "m": 60}[unit]
    return int(total)


def safe_name(name):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name or "file")[:120]


def multipart_files(raw, headers):
    ctype = (headers or {}).get("Content-Type", "")
    if "multipart/form-data" not in ctype or raw is None:
        return []
    from email.parser import BytesParser
    from email.policy import default
    msg = BytesParser(policy=default).parsebytes(b"Content-Type: " + ctype.encode() + b"\r\n\r\n" + raw)
    out = []
    for part in msg.iter_parts():
        name = part.get_filename()
        if name:
            out.append((os.path.basename(name), part.get_payload(decode=True) or b""))
    return out


# ---- Confluence ----------------------------------------------------------------------------------

class Confluence:
    def __init__(self, folder):
        self.root = os.path.join(folder, "confluence")
        self.pages_dir = os.path.join(self.root, "pages")
        self.files = os.path.join(self.root, "attachments")
        self.index_path = os.path.join(self.root, "index.yaml")
        self.data = load_yaml(self.index_path, {})
        self.data.setdefault("space", "ACME")
        self.data.setdefault("pages", {})
        self.data.setdefault("next_id", 100100)
        os.makedirs(self.pages_dir, exist_ok=True)

    def save(self):
        save_yaml(self.index_path, self.data)
        self.write_index_html()

    def body_path(self, pid):
        return os.path.join(self.pages_dir, "%s.html" % pid)

    def body(self, pid):
        path = self.body_path(pid)
        if not os.path.exists(path):
            return ""
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def write_body(self, pid, text):
        with open(self.body_path(pid), "w", encoding="utf-8") as fh:
            fh.write(text or "")

    def new_id(self):
        self.data["next_id"] += 1
        return str(self.data["next_id"])

    def page(self, pid):
        rec = self.data["pages"].get(str(pid))
        if rec is None:
            raise HttpError(404, "No content found with id: %s" % pid)
        return rec

    def ancestors(self, pid):
        out, rec = [], self.data["pages"].get(str(pid))
        while rec and rec.get("parent") and str(rec["parent"]) in self.data["pages"]:
            parent = str(rec["parent"])
            out.insert(0, {"id": parent, "title": self.data["pages"][parent]["title"], "type": "page"})
            rec = self.data["pages"][parent]
        return out

    def render(self, pid, expand=""):
        rec = self.page(pid)
        out = {"id": str(pid), "type": rec.get("type", "page"), "status": "current", "title": rec["title"],
               "space": {"key": rec.get("space", self.data["space"])},
               "version": {"number": rec.get("version", 1), "when": rec.get("updated"),
                           "by": {"username": rec.get("by", ""), "displayName": rec.get("by", "")}},
               "_links": {"webui": "/pages/viewpage.action?pageId=%s" % pid,
                          "tinyui": "/x/%s" % pid, "self": "/rest/api/content/%s" % pid}}
        out["ancestors"] = self.ancestors(pid)
        if rec.get("container"):
            out["container"] = {"id": str(rec["container"]), "type": "page"}
        out["body"] = {"storage": {"value": self.body(pid), "representation": "storage"}}
        if "history" in expand:
            out["history"] = {"createdDate": rec.get("created"), "createdBy": {"username": rec.get("by", "")}}
        return out

    def find(self, title=None, space=None, ancestor=None, parent=None, kind="page", text=None):
        out = []
        for pid, rec in self.data["pages"].items():
            if rec.get("type", "page") != kind:
                continue
            if title is not None and rec["title"].lower() != title.lower():
                continue
            if space and rec.get("space", self.data["space"]).lower() != space.lower():
                continue
            if parent and str(rec.get("parent")) != str(parent):
                continue
            if ancestor and str(ancestor) not in [a["id"] for a in self.ancestors(pid)]:
                continue
            if text and text.lower() not in (rec["title"] + " " + self.body(pid)).lower():
                continue
            out.append(pid)
        return out

    def results(self, ids, expand, start=0, limit=25):
        page = ids[start:start + limit]
        return {"results": [self.render(i, expand) for i in page], "size": len(page), "start": start,
                "limit": limit, "totalSize": len(ids), "_links": {}}

    def cql(self, text):
        args = {}
        for field, value in re.findall(r"(\w+)\s*(?:=|~)\s*\"?([^\"]+?)\"?(?:\s+and\s+|\s+AND\s+|$)", text or ""):
            args[field.lower()] = value.strip()
        return self.find(title=args.get("title"), space=args.get("space"), ancestor=args.get("ancestor"),
                         parent=args.get("parent"), kind=args.get("type", "page"), text=args.get("text"))

    def create(self, body, user):
        kind = body.get("type", "page")
        title = body.get("title") or ""
        space = (body.get("space") or {}).get("key") or self.data["space"]
        if kind == "page" and self.find(title=title, space=space):
            raise HttpError(400, "A page with this title already exists: A page already exists with the title "
                                 "%s in this space." % title)
        pid = self.new_id()
        anc = body.get("ancestors") or []
        rec = {"type": kind, "title": title or ("Re: comment %s" % pid), "space": space, "version": 1,
               "created": now(), "updated": now(), "by": user or ""}
        if anc:
            rec["parent"] = str(anc[-1]["id"])
        if body.get("container"):
            rec["container"] = str(body["container"].get("id"))
        self.data["pages"][pid] = rec
        self.write_body(pid, ((body.get("body") or {}).get("storage") or {}).get("value", ""))
        self.save()
        return self.render(pid)

    def update(self, pid, body, user):
        rec = self.page(pid)
        want = int((body.get("version") or {}).get("number") or 0)
        if want != rec.get("version", 1) + 1:
            raise HttpError(409, "Version must be incremented on update. Current version is: %s" % rec.get("version", 1))
        rec["version"] = want
        rec["title"] = body.get("title") or rec["title"]
        rec["updated"], rec["by"] = now(), user or rec.get("by", "")
        if body.get("ancestors"):
            rec["parent"] = str(body["ancestors"][-1]["id"])
        storage = ((body.get("body") or {}).get("storage") or {}).get("value")
        if storage is not None:
            self.write_body(pid, storage)
        self.save()
        return self.render(pid)

    def attachments(self, pid):
        rec = self.page(pid)
        return [{"id": a["id"], "type": "attachment", "title": a["title"], "version": {"number": a.get("version", 1)},
                 "extensions": {"fileSize": a.get("size", 0), "mediaType": a.get("media", "")},
                 "_links": {"download": "/download/attachments/%s/%s" % (pid, urllib.parse.quote(a["title"]))}}
                for a in rec.get("attachments") or []]

    def add_attachments(self, pid, raw, headers, user, att_id=None):
        rec = self.page(pid)
        made = []
        for name, data in multipart_files(raw, headers):
            items = rec.setdefault("attachments", [])
            old = next((a for a in items if (att_id and a["id"] == att_id) or a["title"] == name), None)
            if old:
                old["version"] = old.get("version", 1) + 1
                old["size"], a = len(data), old
            else:
                a = {"id": "att" + self.new_id(), "title": name, "version": 1, "size": len(data)}
                items.append(a)
            folder = os.path.join(self.files, str(pid))
            os.makedirs(folder, exist_ok=True)
            with open(os.path.join(folder, safe_name(name)), "wb") as fh:
                fh.write(data)
            made.append(a)
        self.save()
        return {"results": [x for x in self.attachments(pid) if x["id"] in {m["id"] for m in made}],
                "size": len(made)}

    def handle(self, method, path, query, body, user, raw=None, headers=None):
        q = {k: v[-1] for k, v in query.items()}
        expand = q.get("expand", "")
        start, limit = int(q.get("start", 0) or 0), int(q.get("limit", 25) or 25)
        if path == "/rest/api/content" and method == "GET":
            ids = self.find(title=q.get("title"), space=q.get("spaceKey"), kind=q.get("type", "page"))
            return self.results(ids, expand, start, limit)
        if path == "/rest/api/content" and method == "POST":
            return self.create(body, user)
        if path == "/rest/api/content/search":
            return self.results(self.cql(q.get("cql", "")), expand, start, limit)
        if path == "/rest/api/user/current":
            return {"type": "known", "username": user or "", "userKey": user or "", "displayName": user or ""}
        if path == "/rest/api/space" or path.startswith("/rest/api/space/"):
            key = path.rsplit("/", 1)[-1] if path.count("/") > 3 else self.data["space"]
            return {"key": key, "name": self.data.get("space_name", key), "type": "global"}
        m = re.fullmatch(r"/rest/api/content/([^/]+)(?:/child/(\w+)(?:/([^/]+)/data)?|/(\w+))?", path)
        if m:
            pid, child, att, other = m.groups()
            if not child and not other:
                if method == "GET":
                    return self.render(pid, expand)
                if method == "PUT":
                    return self.update(pid, body, user)
                if method == "DELETE":
                    self.page(pid)
                    del self.data["pages"][pid]
                    self.save()
                    return None
            if child == "page" or other == "child" and False:
                ids = [i for i, r in self.data["pages"].items() if str(r.get("parent")) == str(pid)
                       and r.get("type", "page") == "page"]
                return self.results(ids, expand, start, limit)
            if child == "comment":
                ids = [i for i, r in self.data["pages"].items() if str(r.get("container")) == str(pid)
                       and r.get("type") == "comment"]
                return self.results(ids, expand, start, limit)
            if child == "attachment":
                if method == "POST":
                    return self.add_attachments(pid, raw, headers, user, att)
                items = self.attachments(pid)
                if q.get("filename"):
                    items = [a for a in items if a["title"] == q["filename"]]
                return {"results": items, "size": len(items), "start": 0, "limit": len(items)}
            if other == "history":
                rec = self.page(pid)
                return {"createdDate": rec.get("created"), "lastUpdated": {"when": rec.get("updated")}}
        raise HttpError(404, "the sandbox has no Confluence call %s %s" % (method, path))

    # browser views
    def write_index_html(self):
        rows = []
        tops = [i for i, r in self.data["pages"].items() if r.get("type", "page") == "page" and not r.get("parent")]

        def tree(pid, depth):
            r = self.data["pages"][pid]
            rows.append('<li style="margin-left:%dem"><a href="pages/%s.html">%s</a> <small>v%s</small></li>' % (
                depth * 1.5, pid, html.escape(r["title"]), r.get("version", 1)))
            for c in sorted(i for i, x in self.data["pages"].items() if str(x.get("parent")) == pid
                            and x.get("type", "page") == "page"):
                tree(c, depth + 1)
        for t in sorted(tops):
            tree(t, 0)
        with open(os.path.join(self.root, "index.html"), "w", encoding="utf-8") as fh:
            fh.write("<!doctype html><meta charset=utf-8><title>Sandbox Confluence</title><h1>Sandbox Confluence: "
                     "space %s</h1><p>Open the page files below, or the sandbox server's address in a browser.</p>"
                     "<ul>%s</ul>" % (html.escape(self.data["space"]), "".join(rows)))

    def view(self, pid):
        rec = self.page(pid)
        crumbs = " / ".join('<a href="/pages/viewpage.action?pageId=%s">%s</a>' % (a["id"], html.escape(a["title"]))
                            for a in self.ancestors(pid))
        comments = "".join("<div style='border-top:1px solid #ddd;padding:6px 0'><b>%s</b> %s<div>%s</div></div>" % (
            html.escape(r.get("by", "")), html.escape(str(r.get("created", ""))), self.body(i))
            for i, r in self.data["pages"].items() if str(r.get("container")) == str(pid))
        atts = "".join("<li>%s</li>" % html.escape(a["title"]) for a in rec.get("attachments") or [])
        return ("<!doctype html><meta charset=utf-8><title>%s</title><body style='font-family:system-ui;margin:24px'>"
                "<p><a href='/'>Sandbox Confluence</a> %s</p><h1>%s</h1><p><small>version %s, %s</small></p>%s"
                "%s%s</body>" % (html.escape(rec["title"]), (" / " + crumbs) if crumbs else "", html.escape(rec["title"]),
                                 rec.get("version", 1), html.escape(str(rec.get("updated", ""))), self.body(pid),
                                 ("<h3>Attachments</h3><ul>%s</ul>" % atts) if atts else "",
                                 ("<h3>Comments</h3>" + comments) if comments else ""))


# ---- HTTP ----------------------------------------------------------------------------------------

class Sandbox:
    def __init__(self, folder):
        self.folder = os.path.abspath(os.path.expanduser(folder))
        self.lock = threading.Lock()
        self.jira = Jira(self.folder)
        self.wiki = Confluence(self.folder)


def user_from(headers, sandbox):
    """The sandbox user named by the Authorization header (Bearer <user> or Basic <user:...>)."""
    auth = headers.get("Authorization") or ""
    who = auth.split(None, 1)[1] if " " in auth else ""
    if auth.lower().startswith("basic "):
        import base64
        try:
            who = base64.b64decode(who).decode().split(":", 1)[0]
        except ValueError:
            who = ""
    u = sandbox.jira.user(who) if who else None
    return u["name"] if u else sandbox.jira.data.get("me")


class Handler(BaseHTTPRequestHandler):
    sandbox = None

    def log_message(self, fmt, *args):
        sys.stderr.write("sandbox %s\n" % (fmt % args))

    def send(self, code, payload, ctype="application/json"):
        data = payload if isinstance(payload, bytes) else (
            payload.encode("utf-8") if isinstance(payload, str) else json.dumps(payload).encode("utf-8"))
        self.send_response(code)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if "text" in ctype or "json" in ctype else ""))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def route(self):
        sb = self.sandbox
        url = urllib.parse.urlsplit(self.path)
        path, query = url.path.rstrip("/") or "/", urllib.parse.parse_qs(url.query, keep_blank_values=True)
        for prefix in ("/jira", "/confluence", "/wiki"):
            if path.startswith(prefix + "/"):
                path = path[len(prefix):]
        raw = None
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            raw = self.rfile.read(length)
        body = {}
        if raw and "json" in (self.headers.get("Content-Type") or "json"):
            try:
                body = json.loads(raw.decode("utf-8"))
            except ValueError:
                body = {}
        user = user_from(self.headers, sb)
        try:
            with sb.lock:
                if path == "/":
                    return self.send(200, open(os.path.join(sb.wiki.root, "index.html"), encoding="utf-8").read()
                                     if os.path.exists(os.path.join(sb.wiki.root, "index.html")) else "<p>empty</p>",
                                     "text/html")
                if path == "/pages/viewpage.action":
                    return self.send(200, sb.wiki.view(query.get("pageId", [""])[0]), "text/html")
                m = re.fullmatch(r"/pages/(\d+)\.html", path)
                if m:
                    return self.send(200, sb.wiki.view(m.group(1)), "text/html")
                m = re.fullmatch(r"/download/attachments/([^/]+)/(.+)", path)
                if m:
                    f = os.path.join(sb.wiki.files, m.group(1), safe_name(urllib.parse.unquote(m.group(2))))
                    if not os.path.exists(f):
                        raise HttpError(404, "no attachment")
                    with open(f, "rb") as fh:
                        return self.send(200, fh.read(), "application/octet-stream")
                if path.startswith(("/rest/api/content", "/rest/api/space", "/rest/api/user/current")):
                    out = sb.wiki.handle(self.command, path, query, body, user, raw, self.headers)
                elif path.startswith(("/rest/api/2/", "/rest/agile/1.0/", "/api/2/", "/agile/1.0/")):
                    out = sb.jira.handle(self.command, path, query, body, user, raw, self.headers)
                elif path == "/status":
                    out = {"sandbox": sb.folder, "issues": len(sb.jira.data["issues"]),
                           "pages": len(sb.wiki.data["pages"])}
                else:
                    raise HttpError(404, "the sandbox has no page %s" % path)
        except HttpError as exc:
            return self.send(exc.code, {"errorMessages": [exc.message], "message": exc.message,
                                        "statusCode": exc.code})
        except Exception as exc:  # keep the server up for the next call
            return self.send(500, {"errorMessages": ["sandbox error: %s" % exc]})
        if out is None:
            return self.send(204, b"")
        return self.send(200, out)

    do_GET = do_POST = do_PUT = do_DELETE = do_HEAD = route


def serve(folder, host="127.0.0.1", port=PORT):
    Handler.sandbox = Sandbox(folder)
    srv = ThreadingHTTPServer((host, port), Handler)
    return srv


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--folder", default=os.environ.get("SDLC_SANDBOX") or "~/Documents/sdlc-sandbox")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=int(os.environ.get("SDLC_SANDBOX_PORT") or PORT))
    args = ap.parse_args(argv)
    folder = os.path.abspath(os.path.expanduser(args.folder))
    if not os.path.exists(os.path.join(folder, "jira.yaml")):
        print("No sandbox in %s: make one first with make_sandbox.py --folder %s" % (folder, folder))
        return 1
    srv = serve(folder, args.host, args.port)
    print("SANDBOX READY http://%s:%d  (folder %s)" % (args.host, args.port, folder), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
