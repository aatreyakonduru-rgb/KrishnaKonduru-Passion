"""Teams Devin Usage tab for the Mētis dashboard. Numbers only as the Devin session tools gave them (usage.json from
dash_usage.py); learning plans and patterns only from findings that name their sessions (dash_usage.py check)."""
import html
import statistics

import dash_usage

E = lambda v: html.escape("" if v is None else str(v))  # noqa: E731


def jira_people(jira, skip=()):
    """Assignees and reporters on the Jira snapshot's stories, with the boards they appear on. The Jira service
    account that read the snapshot, and anyone in usage.not_people, are not people on the team."""
    sa = (jira or {}).get("service_account") or {}
    skip = {x.lower() for x in list(skip) + [sa.get("email") or "", sa.get("name") or ""] if x}
    out = {}
    for i in (jira or {}).get("issues") or []:
        for k in ("assignee", "reporter"):
            p = i.get(k) or {}
            key = p.get("email") or (p.get("display") or "").lower()
            if not key or {key, (p.get("name") or "").lower(), (p.get("display") or "").lower()} & skip:
                continue
            r = out.setdefault(key, {"name": p.get("display") or "", "email": p.get("email") or "", "boards": set(), "stories": set()})
            r["boards"].update(i.get("boards") or [])
            r["stories"].add(i.get("key"))
    return out


def team(cfg, dash, jira, usage):
    """[(person, devin user ids)] for the people the settings say make up the team, matched to Devin by email only."""
    by_mail = {}
    for m in usage.get("members") or []:
        by_mail.setdefault(m["email"], []).append(m["user_id"])
    how = cfg.get("team_from") or "jira"
    people = []
    if how == "jira":
        for p in jira_people(jira, cfg.get("not_people") or []).values():
            people.append({"name": p["name"], "email": p["email"], "boards": sorted(p["boards"]), "stories": len(p["stories"]),
                           "from": "Jira stories (assignee or reporter)"})
    elif how == "dashboard":
        people = [{"name": p.get("name") or "", "email": (p.get("email") or "").lower(), "boards": [], "stories": None,
                   "from": "dashboard.yaml team"} for p in dash.get("team") or []]
    else:
        people = [{"name": m["name"], "email": m["email"], "boards": [], "stories": None, "from": "Devin org member list"}
                  for m in usage.get("members") or []]
    for p in people:
        p["ids"] = by_mail.get((p["email"] or "").lower(), [])
    return how, people


def _slink(usage, sid):
    base = usage.get("session_url")
    short = E(sid[:8])
    return "<a href='%s/%s' target=_blank>%s</a>" % (E(base), E(sid.replace("devin-", "")), short) if base else short


def build(usage, findings, jira, dash, me, lens, table, cards):
    cfg = dash.get("usage") or {}
    if not usage:
        return ("<p>Not read yet. Ask Metis for the dashboard; it reads the Devin session tools for the last %s days and writes "
                "<code>usage.json</code> (see the Teams Devin Usage step in the metis-dashboard skill).</p>" % E(cfg.get("days") or 30))
    how, people = team(cfg, dash, jira, usage)
    per = (lens in (cfg.get("per_person_lenses") or ["manager", "tech_lead"]))
    price = cfg.get("usd_per_acu")
    has_price = price not in (None, "")
    usd_t = lambda a: ("$" + format(a * float(price), ",.2f")) if has_price else "not set"  # noqa: E731
    usd = lambda a: usd_t(a) if has_price else "<span class=muted>no price set</span>"  # noqa: E731
    pr = usage["period"]
    src = ("Source: %s, read %s. Period: sessions created %s to %s. ACUs as the tools report them (<code>acus_consumed</code>). "
           % (E(usage.get("source")), E(usage.get("read_at")), E(pr["from"]), E(pr["to"])) +
           ("Dollars: ACUs &times; $%s per ACU from <code>.metis/dashboard.yaml</code> usage.usd_per_acu%s." %
            (E(price), (", given by " + E(cfg.get("usd_per_acu_source"))) if cfg.get("usd_per_acu_source") else "")
            if price not in (None, "") else "No price per ACU is set in <code>.metis/dashboard.yaml</code>, so no dollars are shown."))
    needs = []
    if how == "jira" and not jira:
        needs.append("No Jira snapshot was read, so the team (people on the Jira stories) is unknown. Ask Metis to set up the team to find "
                     "the team's boards, then ask for the dashboard again.")
    elif how == "jira" and not (jira.get("boards") or "project in" in (jira.get("jql_open") or "")):
        needs.append("No Jira boards or projects are set in <code>.metis/kb-profile.yaml</code> sources.jira.")
    if how == "jira" and jira and not jira.get("boards"):
        needs.append("No Jira boards are listed in sources.jira.boards, so people can't be grouped by board. Metis setup "
                     "lists the boards the Jira service account can see for the project and asks which ones are the team's.")
    team_ids = {i for p in people for i in p["ids"]}
    ins = usage.get("insights") or {}
    ss = [s for s in usage.get("sessions") or [] if s.get("user_id") in team_ids]
    left = [s for s in usage.get("sessions") or [] if s.get("user_id") not in team_ids]
    acus = lambda xs: sum(float(s.get("acus") or 0) for s in xs)  # noqa: E731
    merged = lambda xs: sum(1 for s in xs for p in s.get("prs") or [] if p.get("state") == "merged")  # noqa: E731
    nprs = lambda xs: sum(len(s.get("prs") or []) for s in xs)  # noqa: E731
    rows_p = []
    for p in people:
        mine = [s for s in ss if s.get("user_id") in p["ids"]]
        msgs = [ins[s["session_id"]]["num_user_messages"] for s in mine
                if isinstance((ins.get(s["session_id"]) or {}).get("num_user_messages"), int)]
        cats = {}
        for s in mine:
            cats[s.get("category") or "not classified"] = cats.get(s.get("category") or "not classified", 0) + 1
        p.update({"sessions": mine, "acus": acus(mine), "prs": nprs(mine), "merged": merged(mine),
                  "median_msgs": statistics.median(msgs) if msgs else None, "cats": cats})
        rows_p.append(p)
    rows_p.sort(key=lambda p: (-p["acus"], -len(p["sessions"]), p["name"] or p["email"]))
    me_mail = (me.get("email") or "").lower()
    visible = rows_p if per else [p for p in rows_p if p["email"] == me_mail]
    cardsx = [(len(people), "people on the team", E(people[0]["from"]) if people else "team not known"),
              (sum(1 for p in rows_p if p["sessions"]), "used Devin", "at least one session in the period"),
              (len(ss), "sessions", "created in the period"),
              ("%.1f" % acus(ss), "ACUs", "sum of acus_consumed"),
              (usd_t(acus(ss)), "cost", "ACUs &times; price per ACU" if price not in (None, "") else "no price per ACU set"),
              ("%d / %d" % (nprs(ss), merged(ss)), "PRs opened / merged", "from the sessions' pull requests")]
    out = ["".join("<p class=p1>%s</p>" % n for n in needs), cards(cardsx), "<p class=muted>%s</p>" % src]
    if left:
        out.append("<p class=muted>%d sessions (%.1f ACUs) by Devin users who are not on the team list are left out.</p>" % (len(left), acus(left)))
    boards = sorted({b for p in rows_p for b in p["boards"]})
    if boards:
        out.append("<h3>By board</h3>")
        brow = []
        for b in boards:
            bp = [p for p in rows_p if b in p["boards"]]
            bs = [s for p in bp for s in p["sessions"]]
            brow.append([E(b), len(bp), sum(1 for p in bp if p["sessions"]), len(bs), "%.1f" % acus(bs), usd(acus(bs)), merged(bs)])
        out.append(table(["Board", "People", "Used Devin", "Sessions", "ACUs", "Cost", "Merged PRs"], brow) +
                   "<p class=muted>A person on stories of more than one board is counted under each.</p>")
    out.append("<h3>Who uses Devin, and how</h3>")
    if not per:
        out.append("<p class=muted>This view shows your own row only. Managers and tech leads see the whole team.</p>")
    top = lambda d: ", ".join("%s %d" % (k.replace("_", " "), v) for k, v in sorted(d.items(), key=lambda t: -t[1])[:3])  # noqa: E731
    out.append(table(["Person", "Boards", "Sessions", "ACUs", "Cost", "PRs / merged", "ACUs per merged PR", "Median messages from the person", "Main kinds of work"],
                     [[E(p["name"] or p["email"]), E(", ".join(p["boards"])),
                       p["sessions"] and len(p["sessions"]) or ("<span class=muted>no Devin user found</span>" if not p["ids"] else 0),
                       "%.1f" % p["acus"], usd(p["acus"]), "%d / %d" % (p["prs"], p["merged"]),
                       ("%.1f" % (p["acus"] / p["merged"])) if p["merged"] else "",
                       E(p["median_msgs"]) if p["median_msgs"] is not None else "<span class=muted>not analysed</span>",
                       E(top(p["cats"]))] for p in visible], "Nobody to show."))
    out.append("<p class=muted>A person is matched to a Devin user only by the same email. \"no Devin user found\" means no Devin "
               "user in this org has that email.</p>")
    kinds = {}
    for s in ss:
        k = kinds.setdefault(s.get("category") or "not classified", {"s": [], "people": set()})
        k["s"].append(s)
        k["people"].add(s.get("user_id"))
    out.append("<h3>ACUs by kind of work</h3>" + table(["Kind of work", "Sessions", "People", "ACUs", "Cost", "Merged PRs"],
               [[E(k.replace("_", " ")), len(v["s"]), len(v["people"]), "%.1f" % acus(v["s"]), usd(acus(v["s"])), merged(v["s"])]
                for k, v in sorted(kinds.items(), key=lambda t: -acus(t[1]["s"]))]) +
               "<p class=muted>Kind of work is the category Devin gives each session.</p>")
    if per:
        names = {i: (p["name"] or p["email"]) for p in rows_p for i in p["ids"]}
        pair = []
        for k, v in sorted(kinds.items()):
            done, tried = {}, set()
            for s in v["s"]:
                m = sum(1 for x in s.get("prs") or [] if x.get("state") == "merged")
                if m:
                    done[s["user_id"]] = done.get(s["user_id"], 0) + m
                else:
                    tried.add(s["user_id"])
            tried -= set(done)
            if done and tried:
                pair.append([E(k.replace("_", " ")), E(", ".join("%s (%d merged)" % (names.get(u), n) for u, n in sorted(done.items(), key=lambda t: -t[1]))),
                             E(", ".join(sorted(names.get(u) or "" for u in tried)))])
        out.append("<h3>Who could show whom</h3>" + table(["Kind of work", "Has merged PRs from Devin sessions", "Has sessions of this kind, no merged PR yet"], pair,
                   "No kind of work has both.") + "<p class=muted>From counts only: merged PRs per kind of work. It doesn't judge skill; "
                   "it shows who has already landed this kind of work with Devin.</p>")
        none = [p for p in rows_p if not p["sessions"]]
        out.append("<h3>Not using Devin in the period</h3>" + table(["Person", "Boards", "Devin user"],
                   [[E(p["name"] or p["email"]), E(", ".join(p["boards"])), "found, no sessions" if p["ids"] else "no Devin user with this email"] for p in none],
                   "Everyone on the team has at least one session."))
    out.append(_findings(usage, findings, rows_p, me, per, table))
    return "".join(out)


def _findings(usage, findings, rows_p, me, per, table):
    if not findings:
        return ("<h3>Prompts, skill gaps, repeated work and learning plans</h3><p class=muted>No findings file was given. These come only "
                "from Devin's full session analysis (devin_session_insights generate, then get), written to <code>findings.json</code> "
                "with the sessions behind each point and checked with <code>dash_usage.py check</code>.</p>")
    probs = dash_usage.check(usage, findings)
    bad = {p.split(":")[0] for p in probs}
    link = lambda xs: ", ".join(_slink(usage, s) for s in xs)  # noqa: E731
    name = {i: (p["name"] or p["email"]) for p in rows_p for i in p["ids"]}
    out = []
    keep = lambda key: [(i, it) for i, it in enumerate(findings.get(key) or []) if "%s[%d]" % (key, i) not in bad]  # noqa: E731
    out.append("<h3>How the team writes prompts, and how to write them better</h3>" + table(
        ["Pattern", "Sessions", "Before", "Better"], [[E(it.get("pattern")), link(it["sessions"]), "<code>%s</code>" % E(it.get("before")),
                                                      "<code>%s</code>" % E(it.get("better"))] for _, it in keep("prompt_patterns")], "None found."))
    out.append("<h3>Skill gaps</h3>" + table(["Gap", "Sessions", "What to learn"], [[E(it.get("gap")), link(it["sessions"]), E(it.get("lesson"))]
                                                                                  for _, it in keep("gaps")], "None found."))
    out.append("<h3>Repeated work</h3>" + table(["Task asked for again and again", "Sessions", "What would do it once"],
                                               [[E(it.get("task")), link(it["sessions"]), E(it.get("suggestion"))] for _, it in keep("repeated")], "None found."))
    out.append("<h3>What is going well</h3>" + table(["Person", "What went well", "Sessions"],
                                                    [[E(name.get(it.get("user_id")) or ""), E(it.get("what")), link(it["sessions"])] for _, it in keep("wins")
                                                     if per or it.get("user_id") in _ids(rows_p, me)], "None found."))
    plans = []
    for uid, pl in (findings.get("people") or {}).items():
        if "people[%s]" % uid in bad or not (per or uid in _ids(rows_p, me)) or uid not in name:
            continue
        li = lambda xs: "<ul>%s</ul>" % "".join("<li>%s</li>" % E(x) for x in xs or []) if xs else ""  # noqa: E731
        plans.append("<div class=card><b>%s</b><p>Sessions: %s</p><p>Gaps</p>%s<p>Tips</p>%s<p>Questions for the one-to-one</p>%s"
                     "<p>A prompt as written</p><code>%s</code><p>A better way to write it</p><code>%s</code></div>" % (
                         E(name[uid]), link(pl.get("sessions")), li(pl.get("gaps")), li(pl.get("tips")), li(pl.get("questions")),
                         E(pl.get("prompt_before")), E(pl.get("prompt_after"))))
    out.append("<h3>Learning plan per person</h3>" + ("".join(plans) or "<p class=muted>None to show.</p>"))
    if probs:
        out.append("<h4>Findings left out</h4><ul>%s</ul>" % "".join("<li>%s</li>" % E(p) for p in probs))
    out.append("<p class=muted>Every finding names the sessions it came from; a pattern, gap or repeat needs two or more. "
               "Findings that fail the check are left out and listed above.</p>")
    return "".join(out)


def _ids(rows_p, me):
    return {i for p in rows_p if p["email"] == (me.get("email") or "").lower() for i in p["ids"]}
