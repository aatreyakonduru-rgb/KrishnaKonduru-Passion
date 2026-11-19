#!/usr/bin/env python3
"""Team Insights: how the team uses Devin each month, what to teach, and what to change in the framework.

The monthly /team-insights run (a Devin Cloud session) reads the month's sessions and Devin's analysis of each one
with the Devin session tools and writes two inputs: raw.json (the numbers, as read) and findings.yaml (what the
session concluded from reading them). `build` turns them into:

- SHARED/team-insights/<YYYY-MM>.yaml in the knowledge base: team totals, prompting patterns, skill gaps and
  repeated work, all without names, and the wins, with names. Safe for anyone who can read the repo.
- SHARED/framework-recommendations.yaml: recommended framework changes, each new / accepted / rejected / done.
- SHARED/team-insights/people/<YYYY>/<MM>/<devin user id>.md: each person's learning plan for the month (learning
  list, tips, one-on-one questions, a better prompt), named by Devin user id and never by name. The Tech Lead
  dashboard shows the name from people.yaml. Open items are taught one at a time at the start of the person's
  sessions (`teach next`).
- <session home>/insights/<YYYY-MM>.yaml, never committed: usage and ACUs per person. Only for the tech leads: the
  monthly run attaches the file to its session and a tech lead brings it to their PC with `import`.

Everything that writes is a preview until run again with --write.

    team_insights.py build --raw raw.json --findings findings.yaml [--write]
    team_insights.py import FILE
    team_insights.py recommend list | decide R-001 accepted|rejected|done --by NAME [--note TEXT] [--write]
    team_insights.py learned --person NAME --gap TEXT --status taught|better|open [--write]
    team_insights.py teach next --person NAME
    team_insights.py checkin due --person NAME | add --by NAME --helped TEXT --blocked TEXT [--write]
    team_insights.py deck [--month YYYY-MM] [-o FILE]
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import statistics
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import session_store  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
SHARED = os.path.join(ROOT, "docs", "knowledge-base", "SHARED")
TEAM_DIR = os.path.join(SHARED, "team-insights")
PLANS_DIR = os.path.join(TEAM_DIR, "people")
LEARN_STATUSES = ("open", "taught", "better")
RECS_PATH = os.path.join(SHARED, "framework-recommendations.yaml")
CHECKINS_PATH = os.path.join(SHARED, "team-checkins.yaml")
PEOPLE_PATH = os.path.join(ROOT, ".devin", "rules", "people.yaml")
METRICS_PATH = os.path.join(ROOT, ".devin", "rules", "scrum-master-metrics.yaml")
DECK_DIR = os.path.join(ROOT, "docs", "knowledge-base", "REPORTS", "team-insights")
STATUSES = ("new", "accepted", "rejected", "done")
CHECKIN_QUESTION = ("Once a month: what helped you most with Devin this month, and what got in the way? "
                    "One line each (or skip).")


def load_yaml(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or default


def dump_yaml(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, sort_keys=False, allow_unicode=True)


def private_dir():
    return os.path.join(session_store.local_home(), "insights")


def usd_per_acu(path=None):
    """The contract dollar rate per ACU from scrum-master-metrics.yaml, or None when nobody has set it."""
    value = ((load_yaml(path or METRICS_PATH, {}).get("cost") or {}).get("usd_per_acu"))
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def roster(path=None):
    """devin_user_id -> (name, primary role) for everyone on the roster who has one."""
    out = {}
    for p in load_yaml(path or PEOPLE_PATH, {}).get("people") or []:
        if p.get("devin_user_id"):
            out[p["devin_user_id"]] = (p.get("name") or p["devin_user_id"], p.get("primary_role") or "")
    return out


def link_ids(pairs, path=None):
    """Fill devin_user_id in people.yaml from {user id: [emails]} read off each person's own session messages.

    A roster entry is filled only when its email is one of the emails that user id typed with and its
    devin_user_id is empty. Returns (new text, report); the report lists filled, kept, clashes and unknown."""
    path = path or PEOPLE_PATH
    text = open(path, encoding="utf-8").read()
    people = load_yaml(path, {}).get("people") or []
    by_email = {(p.get("email") or "").lower(): p for p in people if p.get("email")}
    report = {"filled": [], "kept": [], "clash": [], "not_on_roster": []}
    for uid, emails in sorted(pairs.items()):
        hits = [by_email[e.lower()] for e in emails if e.lower() in by_email]
        if len(hits) != 1:
            report["not_on_roster" if not hits else "clash"].append("%s %s" % (uid, ", ".join(emails)))
            continue
        person = hits[0]
        if person.get("devin_user_id") == uid:
            report["kept"].append(person["name"])
            continue
        if person.get("devin_user_id"):
            report["clash"].append("%s has %s, sessions say %s" % (person["name"], person["devin_user_id"], uid))
            continue
        block = re.compile(r"(\n  email: %s\n(?:  [^\n]*\n)*?  devin_user_id: )null\n" % re.escape(person["email"]))
        text, n = block.subn(lambda m: m.group(1) + uid + "\n", text, count=1)
        report["filled" if n else "clash"].append("%s %s" % (person["name"], uid) if n
                                                  else "%s: devin_user_id line not found" % person["name"])
    return text, report


HEROES = ("Falcon", "Phoenix", "Comet", "Nova", "Titan", "Blaze", "Orbit", "Raven", "Jaguar", "Tempest", "Atlas",
          "Vortex", "Echo", "Lynx", "Quasar", "Zephyr", "Sentinel", "Aurora", "Cobalt", "Meteor", "Onyx", "Pulsar",
          "Ranger", "Spark", "Valkyrie", "Wildcat", "Nebula", "Kestrel", "Ember", "Glacier", "Halo", "Ion")


def alias(user_id):
    """A short code name for someone not on the roster, the same every month (from their Devin user id)."""
    if not str(user_id).startswith("user-"):
        return str(user_id)
    n = int(hashlib.sha1(str(user_id).encode()).hexdigest(), 16)
    return "%s %d" % (HEROES[n % len(HEROES)], n // len(HEROES) % 90 + 10)


def alias_map(user_ids):
    """Code names for everyone in `user_ids`, no two alike: a clash moves to the next free name."""
    out, taken = {}, set()
    for uid in sorted(set(user_ids)):
        name, n = alias(uid), 0
        while name in taken:
            n += 1
            h = int(hashlib.sha1(("%s/%d" % (uid, n)).encode()).hexdigest(), 16)
            name = "%s %d" % (HEROES[h % len(HEROES)], h // len(HEROES) % 90 + 10)
        taken.add(name)
        out[uid] = name
    return out


def _merged_urls(sessions):
    """Merged PRs by URL, so a PR that shows on several sessions counts once."""
    return {p.get("url") for s in sessions for p in s.get("prs") or [] if str(p.get("state", "")).lower() == "merged"}


def stats(raw, people=None):
    """Numbers only, straight from raw.json: per person (private) and for the team."""
    people = people if people is not None else roster()
    names = raw.get("names") or {}
    analyses = raw.get("analyses") or {}
    per = {}
    codes = alias_map(s.get("user_id") or "unknown" for s in raw.get("sessions") or [])
    for s in raw.get("sessions") or []:
        uid = s.get("user_id") or "unknown"
        name, role = people.get(uid, (names.get(uid) or codes[uid], ""))
        row = per.setdefault(name, {"person": name, "user_id": uid, "role": role, "on_roster": uid in people,
                                    "sessions": 0, "acus": 0.0, "prs": 0, "merged": 0, "origins": {},
                                    "categories": {}, "messages": []})
        row["sessions"] += 1
        row["acus"] += float(s.get("acus") or 0)
        row["prs"] += len(s.get("prs") or [])
        row.setdefault("_sessions", []).append(s)
        for key, field in (("origins", "origin"), ("categories", "category")):
            value = s.get(field) or "other"
            row[key][value] = row[key].get(value, 0) + 1
        msgs = (analyses.get(s.get("session_id")) or {}).get("num_user_messages")
        if isinstance(msgs, int):
            row["messages"].append(msgs)
    people_rows = []
    for row in per.values():
        msgs = row.pop("messages")
        row["merged"] = len(_merged_urls(row.pop("_sessions", [])))
        row["acus"] = round(row["acus"], 1)
        row["median_messages"] = statistics.median(msgs) if msgs else None
        row["acus_per_merged_pr"] = round(row["acus"] / row["merged"], 1) if row["merged"] else None
        people_rows.append(row)
    people_rows.sort(key=lambda r: -r["acus"])
    sessions = raw.get("sessions") or []
    total_acus = round(sum(float(s.get("acus") or 0) for s in sessions), 1)
    merged = len(_merged_urls(sessions))

    def count(field):
        out = {}
        for s in sessions:
            out[s.get(field) or "other"] = out.get(s.get(field) or "other", 0) + 1
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))

    acus_by_category = {}
    for s in sessions:
        key = s.get("category") or "other"
        acus_by_category[key] = round(acus_by_category.get(key, 0.0) + float(s.get("acus") or 0), 1)
    by_role = {}
    for row in people_rows:
        r = by_role.setdefault(row["role"] or "not on the roster", {"people": 0, "sessions": 0, "acus": 0.0})
        r["people"] += 1
        r["sessions"] += row["sessions"]
        r["acus"] = round(r["acus"] + row["acus"], 1)
    team = {"sessions": len(sessions), "people": len(people_rows),
            "on_roster": sum(1 for r in people_rows if r["on_roster"]), "acus": total_acus,
            "prs": len({p.get("url") for s in sessions for p in s.get("prs") or []}), "merged_prs": merged,
            "acus_per_merged_pr": round(total_acus / merged, 1) if merged else None,
            "analysed": sum(1 for s in sessions if s.get("session_id") in analyses),
            "by_origin": count("origin"), "by_category": count("category"),
            "acus_by_category": dict(sorted(acus_by_category.items(), key=lambda kv: -kv[1])), "by_role": by_role}
    return team, people_rows


def _anon(items, fields):
    """Keep only the listed fields, so a name in a findings line never reaches the shared file."""
    return [{k: i.get(k) for k in fields if i.get(k) not in (None, "")} for i in items or []]


def build(raw, findings, people=None, today=None):
    """(team file, private file, new recommendations) from the two inputs. Nothing is written here."""
    month = raw.get("month") or (today or datetime.date.today()).strftime("%Y-%m")
    team, people_rows = stats(raw, people)
    codes = alias_map(s.get("user_id") or "unknown" for s in raw.get("sessions") or [])
    shared = {
        "month": month,
        "built": (today or datetime.date.today()).isoformat(),
        "source": "Devin session search and session analysis for %s; numbers as read, findings by the /team-insights run" % month,
        "team": team,
        "prompt_patterns": _anon(findings.get("prompt_patterns"), ("pattern", "sessions", "people", "before", "better")),
        "gaps": _anon(findings.get("gaps"), ("gap", "sessions", "people", "lesson", "command")),
        "repetitive": _anon(findings.get("repetitive"), ("task", "sessions", "people", "suggestion")),
        "prompt_examples": _anon(findings.get("prompt_examples"), ("asked", "weak", "better")),
        "wins": [dict(w, person=(people or roster()).get(w.get("person"), (codes.get(w.get("person"), w.get("person")),))[0])
                 for w in _anon(findings.get("wins"), ("person", "what", "session"))],
    }
    private = {"month": month, "people": people_rows,
               "aliases": {r["person"]: r["user_id"] for r in people_rows if not r["on_roster"]}}
    recs = _anon(findings.get("recommendations"), ("what", "why", "sessions", "people", "gain", "touches"))
    return shared, private, recs


def merge_recommendations(data, recs, month):
    """Append new recommendations as R-nnn with status new; one already listed (same what) is left alone."""
    items = data.setdefault("recommendations", [])
    seen = {str(i.get("what", "")).strip().lower() for i in items}
    added = []
    for r in recs:
        if not r.get("what") or r["what"].strip().lower() in seen:
            continue
        item = dict(r, id="R-%03d" % (len(items) + 1), month=month, status="new")
        items.append(item)
        seen.add(r["what"].strip().lower())
        added.append(item)
    return added


def decide(data, rec_id, status, by, note="", today=None):
    if status not in STATUSES:
        raise ValueError("status is one of %s" % ", ".join(STATUSES))
    for item in data.get("recommendations") or []:
        if item.get("id") == rec_id:
            item.update(status=status, decided_by=by, decided=(today or datetime.date.today()).isoformat())
            if note:
                item["note"] = note.strip()[:300]
            return item
    raise KeyError("no recommendation %s" % rec_id)


def plans_dir():
    return PLANS_DIR


def plan_path(month, user_id):
    year, mon = month.split("-")
    return os.path.join(plans_dir(), year, mon, user_id + ".md")


def read_plan(path):
    """The plan from the YAML front matter of a learning plan file."""
    with open(path, encoding="utf-8") as fh:
        m = re.match(r"---\n(.*?)\n---\n", fh.read(), re.S)
    return (yaml.safe_load(m.group(1)) or {}) if m else {}


def plan_markdown(plan):
    """The file: the plan as front matter (what the tools read) and the same plan written out for people."""
    marks = {"open": " ", "taught": "x", "better": "x"}
    lines = ["---", yaml.safe_dump(plan, sort_keys=False, allow_unicode=True).rstrip(), "---", "",
             "# Learning plan, %s" % plan["month"], "",
             "Devin user `%s`. The Tech Lead dashboard shows the name from people.yaml." % plan["devin_user_id"], "",
             "## Learning list", ""]
    lines += ["- [%s] %s (%s, since %s%s)" % (marks.get(r.get("status"), " "), r["gap"], r.get("status", "open"),
                                             r.get("since", ""), ", seen again %s" % r["seen_again"]
                                             if r.get("seen_again") else "") for r in plan.get("learning") or []] or ["None."]
    for title, key in (("Tips to give", "tips"), ("Questions for the one-on-one", "questions")):
        lines += ["", "## " + title, ""] + (["- %s" % x for x in plan.get(key) or []] or ["None."])
    if plan.get("prompt_before") or plan.get("prompt_after"):
        lines += ["", "## A better prompt", "", "- Their prompt: %s" % plan.get("prompt_before", ""),
                  "- A better one: %s" % plan.get("prompt_after", "")]
    return "\n".join(lines) + "\n"


def write_plan(plan):
    path = plan_path(plan["month"], plan["devin_user_id"])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(plan_markdown(plan))
    return path


def all_plans():
    """{month: {devin user id: plan}} for every learning plan file, from people/<YYYY>/<MM>/<id>.md."""
    out, base = {}, plans_dir()
    for year in sorted(os.listdir(base)) if os.path.isdir(base) else []:
        for mon in sorted(os.listdir(os.path.join(base, year))) if re.match(r"^\d{4}$", year) else []:
            folder = os.path.join(base, year, mon)
            for name in sorted(os.listdir(folder)) if re.match(r"^\d{2}$", mon) and os.path.isdir(folder) else []:
                if name.endswith(".md"):
                    plan = read_plan(os.path.join(folder, name))
                    out.setdefault("%s-%s" % (year, mon), {})[plan.get("devin_user_id") or name[:-3]] = plan
    return out


def latest_plan(user_id, before=None, plans=None):
    """(month, plan) for the person's newest plan, or one older than `before`; (None, None) when there is none."""
    plans = all_plans() if plans is None else plans
    for month in sorted(plans, reverse=True):
        if (before is None or month < before) and user_id in plans[month]:
            return month, plans[month][user_id]
    return None, None


def display_names(user_ids, people=None):
    """Devin user id -> the name to show: the roster name, else the person's code name."""
    people = people if people is not None else roster()
    codes = alias_map(u for u in user_ids if u not in people)
    return {u: people[u][0] if u in people else codes[u] for u in user_ids}


def resolve_user(value, people=None, aliases=None):
    """A Devin user id from a user id, a roster name or a code name; None when it can't be told."""
    value = str(value or "").strip()
    if value.startswith("user-"):
        return value
    people = people if people is not None else roster()
    for uid, (name, _) in people.items():
        if name.casefold() == value.casefold():
            return uid
    return (aliases or {}).get(value)


def learning_plans(findings, month, people=None, aliases=None, plans=None, today=None):
    """This month's plan per person: last month's learning list carried over (statuses kept), this month's gaps added
    as open. Returns (plans by user id, findings keys that could not be matched to a Devin user id)."""
    day = (today or datetime.date.today()).isoformat()
    out, skipped = {}, []
    for key, detail in (findings.get("people") or {}).items():
        uid = resolve_user(key, people, aliases)
        if not uid:
            skipped.append(key)
            continue
        _, prev = latest_plan(uid, before=month, plans=plans)
        rows = [dict(r) for r in (prev or {}).get("learning") or []]
        known = {r["gap"].lower(): r for r in rows}
        for gap in detail.get("gaps") or []:
            row = known.get(str(gap).lower())
            if row:
                row["seen_again"] = month
            else:
                known[str(gap).lower()] = {"gap": str(gap), "status": "open", "since": month, "updated": day}
                rows.append(known[str(gap).lower()])
        plan = {"devin_user_id": uid, "month": month, "learning": rows}
        for k in ("tips", "questions"):
            plan[k] = [str(x) for x in detail.get(k) or []]
        for k in ("prompt_before", "prompt_after"):
            if detail.get(k):
                plan[k] = str(detail[k])
        out[uid] = plan
    return out, skipped


def mark_learned(plan, gap, status, today=None):
    if status not in LEARN_STATUSES:
        raise ValueError("status is open, taught or better")
    for row in plan.get("learning") or []:
        if row["gap"].lower() == gap.lower():
            row.update(status=status, updated=(today or datetime.date.today()).isoformat())
            return row
    raise KeyError("no learning item %r" % gap)


def teach_next(person, people=None, plans=None, shared=None):
    """The next open item in the person's newest learning plan, with the lesson and command from that month's gaps."""
    uid = resolve_user(person, people)
    month, plan = latest_plan(uid, plans=plans) if uid else (None, None)
    items = [r for r in (plan or {}).get("learning") or [] if r.get("status", "open") == "open"]
    if not items:
        return {"person": person, "due": False}
    item = items[0]
    shared = shared if shared is not None else (load_month(month)[0] or {})
    match = next((g for g in shared.get("gaps") or [] if str(g.get("gap", "")).lower() == item["gap"].lower()), {})
    return {"person": person, "due": True, "month": month, "gap": item["gap"], "lesson": match.get("lesson", ""),
            "command": match.get("command", ""), "tips": plan.get("tips") or [], "left": len(items),
            "file": os.path.relpath(plan_path(month, uid), ROOT)}


def latest_month(directory=None):
    directory = directory or TEAM_DIR
    months = sorted(f[:-5] for f in os.listdir(directory)
                    if re.match(r"^\d{4}-\d{2}\.yaml$", f)) if os.path.isdir(directory) else []
    return months[-1] if months else None


def load_month(month=None):
    """(shared, private or None) for a month, the latest when none is given; (None, None) before the first run."""
    month = month or latest_month()
    if not month:
        return None, None
    shared = load_yaml(os.path.join(TEAM_DIR, month + ".yaml"), None)
    private = load_yaml(os.path.join(private_dir(), month + ".yaml"), None)
    return shared, private


def checkin_due(data, person, today=None):
    today = today or datetime.date.today()
    month = today.strftime("%Y-%m")
    return not any(c.get("by") == person and str(c.get("date", "")).startswith(month) for c in data.get("checkins") or [])


def checkin_add(data, by, helped, blocked, today=None):
    if not by or not (helped or blocked):
        raise ValueError("give who (--by) and at least one of --helped or --blocked")
    entry = {"date": (today or datetime.date.today()).isoformat(), "by": by,
             "helped": (helped or "").strip()[:300], "blocked": (blocked or "").strip()[:300]}
    data.setdefault("checkins", []).append(entry)
    return entry


def _list(items, render):
    return "<ul>%s</ul>" % "".join("<li>%s</li>" % render(i) for i in items) if items else '<p class="a-empty">None this month.</p>'


def deck(shared, recs):
    """The monthly learning deck: wins with names, gaps without, in the Acme Claims look, one slide per section."""
    import artifact_kit
    esc = artifact_kit.esc
    t = shared["team"]
    month = shared["month"]
    numbers = ('<div class="ti-kpis">%s</div>' % "".join(
        '<div class="ti-kpi"><b>%s</b><span>%s</span></div>' % (esc(v), esc(k)) for k, v in (
            ("sessions", t["sessions"]), ("people", t["people"]), ("ACUs", t["acus"]),
            ("merged PRs", t["merged_prs"]), ("ACUs per merged PR", t["acus_per_merged_pr"] or "–"))))
    slides = [
        ("The month in numbers", numbers + "<p>Most of the work: %s.</p>" % esc(", ".join(
            "%s (%d)" % (k.replace("_", " "), v) for k, v in list(t["by_category"].items())[:4]))),
        ("Well done", _list(shared.get("wins"), lambda w: "<b>%s</b>: %s. Thank you, keep it up." % (
            esc(w.get("person")), esc(w.get("what"))))),
        ("Better prompts", _list(shared.get("prompt_patterns"), lambda p: "<b>%s</b> (%s sessions)%s%s" % (
            esc(p.get("pattern")), esc(p.get("sessions", "?")),
            '<div class="ti-before">Instead of: %s</div>' % esc(p["before"]) if p.get("before") else "",
            '<div class="ti-after">Try: %s</div>' % esc(p["better"]) if p.get("better") else ""))),
        ("Prompts from this month, rewritten", _list(shared.get("prompt_examples"), lambda e: (
            '<div class="ti-before">Asked: %s</div><div>What made it harder: %s</div><div class="ti-after">Better: %s</div>'
            % (esc(e.get("asked", "")), esc(e.get("weak", "")), esc(e.get("better", "")))))),
        ("What to learn next", _list(shared.get("gaps"), lambda g: "<b>%s</b>%s%s" % (
            esc(g.get("gap")), " — %s" % esc(g["lesson"]) if g.get("lesson") else "",
            " · try <code>%s</code>" % esc(g["command"]) if g.get("command") else ""))),
        ("Stop repeating, start reusing", _list(shared.get("repetitive"), lambda r: "<b>%s</b> (%s sessions): %s" % (
            esc(r.get("task")), esc(r.get("sessions", "?")), esc(r.get("suggestion", ""))))),
        ("Framework changes from your feedback", _list(
            [r for r in recs if r.get("status") in ("accepted", "done")],
            lambda r: "<b>%s</b> · %s" % (esc(r.get("what")), esc(r.get("status"))))),
    ]
    body = "".join('<section class="a-section ti-slide"><h2 class="a-section__title">%d. %s</h2>%s</section>'
                   % (i + 1, esc(title), html) for i, (title, html) in enumerate(slides))
    css = (".ti-slide{break-after:page}.ti-slide li{margin-bottom:10px}.ti-kpis{display:flex;flex-wrap:wrap;gap:16px}"
           ".ti-kpi{border:1px solid rgb(var(--border-primary));border-radius:8px;padding:12px 16px;min-width:140px}"
           ".ti-kpi b{display:block;font-size:28px}.ti-before{color:rgb(var(--text-secondary))}.ti-after{font-weight:600}")
    return artifact_kit.render_page(
        "Team Insights — %s" % month, body,
        subtitle="How the Acme Claims team used Devin in %s · wins name the person, learning points name nobody" % esc(month),
        footnote="Built by tools/team_insights.py from %s." % esc(shared.get("source", "")), extra_css=css)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--raw", required=True)
    b.add_argument("--findings", required=True)
    b.add_argument("--write", action="store_true")
    i = sub.add_parser("import")
    i.add_argument("file")
    r = sub.add_parser("recommend")
    r.add_argument("action", choices=["list", "decide"])
    r.add_argument("id", nargs="?")
    r.add_argument("status", nargs="?")
    r.add_argument("--by", default="")
    r.add_argument("--note", default="")
    r.add_argument("--write", action="store_true")
    le = sub.add_parser("learned")
    le.add_argument("--person", required=True)
    le.add_argument("--gap", required=True)
    le.add_argument("--status", required=True)
    le.add_argument("--write", action="store_true")
    te = sub.add_parser("teach")
    te.add_argument("action", choices=["next"])
    te.add_argument("--person", required=True)
    c = sub.add_parser("checkin")
    c.add_argument("action", choices=["due", "add"])
    c.add_argument("--person", default="")
    c.add_argument("--by", default="")
    c.add_argument("--helped", default="")
    c.add_argument("--blocked", default="")
    c.add_argument("--write", action="store_true")
    li = sub.add_parser("link-ids")
    li.add_argument("--pairs", required=True)
    li.add_argument("--write", action="store_true")
    d = sub.add_parser("deck")
    d.add_argument("--month")
    d.add_argument("-o", "--out")
    args = ap.parse_args(argv)

    if args.cmd == "build":
        with open(args.raw, encoding="utf-8") as fh:
            raw = json.load(fh)
        findings = load_yaml(args.findings, {})
        shared, private, recs = build(raw, findings)
        data = load_yaml(RECS_PATH, {"recommendations": []})
        added = merge_recommendations(data, recs, shared["month"])
        plans, skipped = learning_plans(findings, shared["month"], aliases=private["aliases"])
        print(yaml.safe_dump({"team": shared, "new_recommendations": added}, sort_keys=False, allow_unicode=True))
        print("Learning plans for %d people go to %s." % (len(plans), os.path.relpath(
            os.path.join(plans_dir(), *shared["month"].split("-")), ROOT)))
        if skipped:
            print("No Devin user id for: %s (key findings.people by Devin user id)." % ", ".join(skipped))
        print("Usage and ACUs for %d people go to %s (not committed)." % (len(private["people"]), private_dir()))
        if not args.write:
            print("Preview only: run again with --write.")
            return 0
        dump_yaml(os.path.join(TEAM_DIR, shared["month"] + ".yaml"), shared)
        dump_yaml(RECS_PATH, data)
        for plan in plans.values():
            write_plan(plan)
        dump_yaml(os.path.join(private_dir(), shared["month"] + ".yaml"), private)
        print("written: %s, %s, %d learning plans and the private file"
              % (os.path.relpath(os.path.join(TEAM_DIR, shared["month"] + ".yaml"), ROOT), os.path.relpath(RECS_PATH, ROOT),
                 len(plans)))
        return 0
    if args.cmd == "import":
        data = load_yaml(args.file, {})
        if not data.get("month") or "people" not in data:
            print("%s is not a Team Insights per-person file" % args.file)
            return 1
        os.makedirs(private_dir(), exist_ok=True)
        dest = os.path.join(private_dir(), data["month"] + ".yaml")
        shutil.copyfile(args.file, dest)
        print("saved to %s; rebuild the dashboard to see it" % dest)
        return 0
    if args.cmd == "link-ids":
        with open(args.pairs, encoding="utf-8") as fh:
            text, report = link_ids(json.load(fh))
        print(yaml.safe_dump(report, sort_keys=False, allow_unicode=True))
        if not args.write:
            print("Preview only: run again with --write.")
            return 0
        with open(PEOPLE_PATH, "w", encoding="utf-8") as fh:
            fh.write(text)
        return 0
    if args.cmd == "recommend":
        data = load_yaml(RECS_PATH, {"recommendations": []})
        if args.action == "list":
            print(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
            return 0
        print(yaml.safe_dump(decide(data, args.id, args.status, args.by, args.note), sort_keys=False, allow_unicode=True))
        if not args.write:
            print("Preview only: run again with --write.")
            return 0
        dump_yaml(RECS_PATH, data)
        return 0
    if args.cmd == "learned":
        uid = resolve_user(args.person)
        month, plan = latest_plan(uid) if uid else (None, None)
        if not plan:
            print("No learning plan for %s." % args.person)
            return 1
        print(yaml.safe_dump(mark_learned(plan, args.gap, args.status), sort_keys=False, allow_unicode=True))
        if args.write:
            print("written to %s" % os.path.relpath(write_plan(plan), ROOT))
        else:
            print("Preview only: run again with --write.")
        return 0
    if args.cmd == "teach":
        print(json.dumps(teach_next(args.person), indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "checkin":
        data = load_yaml(CHECKINS_PATH, {"checkins": []})
        if args.action == "due":
            due = checkin_due(data, args.person)
            print(CHECKIN_QUESTION if due else "Already answered this month.")
            return 0
        print(yaml.safe_dump(checkin_add(data, args.by, args.helped, args.blocked), sort_keys=False, allow_unicode=True))
        if not args.write:
            print("Preview only: run again with --write after they say approved.")
            return 0
        dump_yaml(CHECKINS_PATH, data)
        return 0
    shared, _ = load_month(args.month)
    if not shared:
        print("No Team Insights month yet: the monthly /team-insights run writes the first one.")
        return 1
    out = args.out or os.path.join(DECK_DIR, "TEAM-INSIGHTS-%s.html" % shared["month"])
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(deck(shared, load_yaml(RECS_PATH, {}).get("recommendations") or []))
    print("written to %s" % os.path.relpath(out, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
