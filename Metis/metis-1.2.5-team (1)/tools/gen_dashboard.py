#!/usr/bin/env python3
"""Mētis dashboard: one read-only HTML page for a person, from a Jira snapshot, the team list and the KB.

    python3 gen_dashboard.py <kb> --user "<name or email>" [--jira jira.json] [--members members.json]
                             [--sessions sessions.json] [--usage usage.json] [--findings findings.json] [--lens manager|tech_lead|product_owner|developer] -o out.html

jira.json comes from dash_jira.py. members.json is the Devin org member list, [{name, email}]. sessions.json is
optional, {"<email>": <Devin sessions in the last 7 days>}.
usage.json (dash_usage.py) and findings.json feed the Teams Devin Usage tab. The page only counts and lists what these sources hold;
it adds no judgement (no "overloaded", no guesses). Every Jira row links to its issue; every KB number names its file.
"""
import argparse
import datetime
import html
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gen_registry  # noqa: E402
import gen_visuals  # noqa: E402
import usage_view  # noqa: E402
import verify_kb  # noqa: E402

load = gen_visuals.load
E = lambda v: html.escape("" if v is None else str(v))  # noqa: E731
TITLES = {"overview": "Overview", "mine": "My work", "sprint": "Current sprint", "workload": "Workload",
          "waiting": "Waiting and stale", "done": "Done recently", "team": "Team", "usage": "Teams Devin Usage", "kb": "Knowledge base",
          "questions": "Questions to answer"}
KB_PAGES = [("VISUALIZATION/index.html", "All visualizations"), ("VISUALIZATION/ONTOLOGY.html", "Ontology and link graph"),
            ("VISUALIZATION/KB_HEALTH.html", "KB health report"), ("VISUALIZATION/TECH_STACK.html", "Tech stack"),
            ("VISUALIZATION/DB_DRIFT.html", "Database drift"), ("VISUALIZATION/ERD.html", "ERD"),
            ("_QUESTIONS/VALIDATE_KB.html", "VALIDATE_KB")]


def jload(p, default):
    if not p:
        return default
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def table(head, rows, empty="Nothing here."):
    if not rows:
        return "<p class=muted>%s</p>" % empty
    return "<table><tr>%s</tr>%s</table>" % ("".join("<th>%s</th>" % h for h in head),
                                             "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % c for c in r) for r in rows))


def cards(items):
    return "<div class=cards>%s</div>" % "".join("<div class=card><b>%s</b>%s<br><span class=muted>%s</span></div>"
                                                 % (E(n), E(t), s) for n, t, s in items)


def team_of(dash, prof, members):
    """People from the org list, with a role only where dashboard.yaml or owners.roles names them."""
    roles = {}
    for r, who in ((prof.get("owners") or {}).get("roles") or {}).items():
        for w in [x.strip() for x in str(who or "").split(",") if x.strip()]:
            roles[w.lower()] = r
    people, seen = [], set()
    for p in (dash.get("team") or []) + (members or []):
        key = (p.get("email") or p.get("name") or "").lower()
        if not key or key in seen:
            continue
        seen.add(key)
        role = p.get("role") or roles.get((p.get("email") or "").lower()) or roles.get((p.get("name") or "").lower()) or ""
        people.append({"name": p.get("name") or "", "email": (p.get("email") or "").lower(), "role": role,
                       "from": "dashboard.yaml" if p in (dash.get("team") or []) else "Devin org member list"})
    return people


def match(issue, people):
    a = issue.get("assignee") or {}
    for p in people:
        if p["email"] and a.get("email") == p["email"]:
            return p
    for p in people:
        if p["name"] and (a.get("display") or "").lower() == p["name"].lower():
            return p
    return None


def find_user(user, people):
    u = (user or "").lower()
    for p in people:
        if u and (u == p["email"] or u == p["name"].lower()):
            return p
    return None


def build(kb, user, jira, members, sessions, lens=None, usage=None, findings=None):
    prof = load(os.path.join(kb, ".metis", "kb-profile.yaml"))
    dash = load(os.path.join(kb, ".metis", "dashboard.yaml"))
    if not dash:
        dash = load(os.path.join(HERE, "..", "templates", "dashboard.yaml"))
    jc = dash.get("jira") or {}
    people = team_of(dash, prof, members)
    me = find_user(user, people) or {"name": user, "email": (user or "").lower(), "role": ""}
    lens = lens or (dash.get("role_lens") or {}).get(me.get("role")) or dash.get("default_lens") or "developer"
    tabs = (dash.get("lenses") or {}).get(lens) or ["overview", "kb"]
    issues = (jira or {}).get("issues") or []
    base = (jira or {}).get("base_url", "")
    link = lambda k: "<a href='%s/browse/%s' target=_blank>%s</a>" % (E(base), E(k), E(k))  # noqa: E731
    who = lambda i: E((i.get("assignee") or {}).get("display") or "unassigned")  # noqa: E731
    irow = lambda i: [link(i["key"]), E(i["summary"]), E(i["type"]), E(i["status"]), who(i), E(i.get("points") or "")]  # noqa: E731
    head = ["Issue", "Summary", "Type", "Status", "Assignee", "Points"]
    openi = [i for i in issues if i.get("status_category") != "done"]
    sprint = [i for i in issues if i.get("sprint_state") == "ACTIVE"]
    names = sorted({i["sprint"] for i in sprint if i.get("sprint")})
    waiting = [i for i in openi if i.get("status") in (jc.get("waiting_statuses") or [])]
    now = datetime.datetime.now(datetime.timezone.utc)
    stale_days = int(jc.get("stale_days") or 5)

    def age(i):
        try:
            return (now - datetime.datetime.strptime(i["updated"][:19] + "+0000", "%Y-%m-%dT%H:%M:%S%z")).days
        except (TypeError, ValueError, KeyError):
            return None
    stale = [i for i in openi if i.get("status_category") == "indeterminate" and (age(i) or 0) >= stale_days]
    done = [i for i in issues if i.get("status_category") == "done"]
    jsrc = ("Source: Jira %s, read %s. Open: <code>%s</code>. Done: <code>%s</code>." % (
        E(base), E(jira.get("read_at")), E(jira.get("jql_open")), E(jira.get("jql_done")))) if jira else \
        "No Jira snapshot was given, so Jira tabs are empty."
    qs = load(os.path.join(kb, "_QUESTIONS", "VALIDATE_KB.yaml")).get("questions") or []
    openq = [q for q in qs if q.get("status") == "open"]
    rep = verify_kb.Checker(kb).run()
    stack = load(os.path.join(kb, ".metis", "stack.yaml"))
    drift = load(os.path.join(gen_registry.db_docs(kb, prof), "DB_DRIFT.yaml"))
    ndiff = len(drift.get("differences") or [])
    mine = [i for i in openi if match(i, [me]) is me]
    sec = {}
    sec["overview"] = cards([
        (len(openi), "open Jira issues", "not Done"), (len(sprint), "in the current sprint", E(", ".join(names)) or "no active sprint found"),
        (len(waiting), "waiting", E(", ".join(jc.get("waiting_statuses") or []))),
        (len(stale), "in progress, not updated for %d+ days" % stale_days, "by Jira 'updated'"),
        (len(done), "done in the last %s days" % E((jira or {}).get("done_days", jc.get("done_days"))), "by Jira 'resolved'"),
        (len(openq), "open KB questions", "%d P1 &middot; <code>_QUESTIONS/VALIDATE_KB.yaml</code>" % sum(1 for q in openq if q.get("priority") == "P1")),
        (len(rep["problems"]), "KB source problems", "%d files, %d source tags checked" % (rep["files"], rep["tags"]))]) + "<p class=muted>%s</p>" % jsrc
    sec["mine"] = table(head, [irow(i) for i in mine], "No open issue in the snapshot is assigned to you.")
    by = {}
    for i in sprint:
        by.setdefault(i.get("status"), []).append(i)
    sec["sprint"] = ("<p>%s</p>" % (E(", ".join(names)) or "No active sprint found in the snapshot.")
                     + table(["Status", "Issues", "Points"], [[E(s), len(v), E(sum(float(x.get("points") or 0) for x in v) or "")]
                                                              for s, v in sorted(by.items(), key=lambda t: str(t[0]))]) + table(head, [irow(i) for i in sprint]))
    wl = {}
    for i in sprint:
        k = (i.get("assignee") or {}).get("display") or "unassigned"
        w = wl.setdefault(k, [0, 0.0, 0, 0])
        w[0] += 1
        w[1] += float(i.get("points") or 0)
        w[2] += i.get("status_category") == "indeterminate"
        w[3] += i.get("status_category") == "done"
    sec["workload"] = table(["Person", "Sprint issues", "Points", "In progress", "Done"],
                            [[E(k), v[0], E(v[1] or ""), v[2], v[3]] for k, v in sorted(wl.items())],
                            "No current-sprint issues.") + "<p class=muted>Counts only. No capacity was given, so nothing is marked over or under.</p>"
    sec["waiting"] = ("<h3>Waiting</h3>" + table(head, [irow(i) for i in waiting]) +
                      "<h3>In progress, not updated for %d+ days</h3>" % stale_days +
                      table(head + ["Days since update"], [irow(i) + [E(age(i))] for i in stale]))
    sec["done"] = table(head + ["Resolved"], [irow(i) + [E((i.get("resolved") or "")[:10])] for i in done])
    cnt = {}
    for i in openi:
        p = match(i, people)
        cnt[p["email"] or p["name"] if p else None] = cnt.get(p["email"] or p["name"] if p else None, 0) + 1
    rows = [[E(p["name"]), E(p["email"]), E(p["role"]) or "<span class=muted>not named</span>",
             cnt.get(p["email"] or p["name"], 0), E((sessions or {}).get(p["email"], "")) if sessions else "<span class=muted>not read</span>",
             E(p["from"])] for p in people]
    extra = sorted({(i.get("assignee") or {}).get("display") for i in openi if i.get("assignee") and not match(i, people)})
    sec["team"] = (table(["Name", "Email", "Role", "Open Jira issues", "Devin sessions, last 7 days", "Listed from"], rows,
                         "No team list: the Devin org member list wasn't read and dashboard.yaml has no team.") +
                   ("<h4>Jira assignees not on the team list</h4><p>%s</p>" % E(", ".join(extra)) if extra else ""))
    sec["usage"] = usage_view.build(usage, findings, jira, dash, me, lens, table, cards)
    kbase = (dash.get("kb_link_base") or "").rstrip("/")
    pages = [[("<a href='%s/%s' target=_blank>%s</a>" % (E(kbase), E(p), E(t)) if kbase else E(t)), "<code>%s</code>" % E(p),
              "yes" if os.path.isfile(os.path.join(kb, p)) else "<span class=muted>not built yet</span>"] for p, t in KB_PAGES]
    pri = {k: sum(1 for q in openq if q.get("priority") == k) for k in ("P1", "P2", "P3")}
    roles = {}
    for q in openq:
        roles[q.get("answer_role")] = roles.get(q.get("answer_role"), 0) + 1
    sec["kb"] = (cards([(len(rep["problems"]), "source problems", "verify_kb.py over the KB"),
                        (len(openq), "open questions", "P1 %d &middot; P2 %d &middot; P3 %d" % (pri["P1"], pri["P2"], pri["P3"])),
                        (len(stack.get("items") or []), "approved stack items",
                         ("approved by %s" % E(stack.get("approved_by"))) if stack else "not approved yet"),
                        (ndiff, "database differences", "<code>DB_DRIFT.yaml</code>")]) +
                 "<h3>Open questions by who answers</h3>" + table(["Role", "Open"], [[E(k), v] for k, v in sorted(roles.items(), key=lambda t: str(t[0]))]) +
                 "<h3>KB pages</h3>" + table(["Page", "In the KB folder", "Built"], pages))
    myq = [q for q in openq if me.get("role") and q.get("answer_role") == me["role"]]
    showq = myq if lens != "manager" and myq else openq
    sec["questions"] = (("<p>Open questions for your role (%s).</p>" % E(me["role"])) if showq is myq and myq else "<p>All open questions.</p>") + table(
        ["Id", "Priority", "Who answers", "Question"], [[E(q.get("id")), "<span class=%s>%s</span>" % (E(str(q.get("priority")).lower()), E(q.get("priority"))),
                                                        E(q.get("answer_role")), E(q.get("question"))] for q in showq], "No open questions.")
    nav = "<nav class=tabs>%s</nav>" % "".join("<button data-t='%s'>%s</button>" % (t, TITLES[t]) for t in tabs if t in sec)
    body = nav + "".join("<section id='%s' hidden>%s</section>" % (t, sec[t]) for t in tabs if t in sec)
    product = (prof.get("product") or {}).get("name") or "KB"
    sub = "%s &middot; %s &middot; %s view" % (E(product), E(me.get("name")), E(lens.replace("_", " ")))
    out = gen_visuals.page("Dashboard", sub, body, {}, "tabs();")
    return out.replace("Built by Mētis from the KB files. Every link shown names its source; nothing on this page is added by the page itself.",
                       "Built by Mētis, read only. Jira numbers come from the snapshot named on the Overview tab; KB numbers from the KB files named beside them. Nothing on this page is added by the page itself.")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("kb")
    ap.add_argument("--user", required=True)
    ap.add_argument("--jira")
    ap.add_argument("--members")
    ap.add_argument("--sessions")
    ap.add_argument("--usage")
    ap.add_argument("--findings")
    ap.add_argument("--lens")
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args(argv)
    page = build(a.kb, a.user, jload(a.jira, None), jload(a.members, []), jload(a.sessions, None), a.lens,
                 jload(a.usage, None), jload(a.findings, None))
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write(page)
    print("dashboard -> %s" % a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
