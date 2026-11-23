#!/usr/bin/env python3
"""Mētis "Teams Devin Usage": turn the Devin session tools' own output into usage.json, and check findings.

    python3 dash_usage.py parse <raw-dir> --start <unix> --end <unix> [--session-url <base>] -o usage.json
    python3 dash_usage.py check usage.json findings.json

<raw-dir> holds the text pages exactly as the tools returned them: sessions-*.txt (devin_session_search),
insights-*.txt (devin_session_insights action=list) and members-*.txt (devin_user_list, direct and idp). Numbers
are copied as read; nothing is estimated. usage.json and findings.json hold per-person usage, so they stay in the
session's own folder and are never committed.
"""
import argparse
import datetime
import glob
import json
import os
import re
import sys

KV = re.compile(r"^([a-z_]+)=(.*)$")


def _kv(parts):
    out = {}
    for p in parts:
        m = KV.match(p.strip())
        if m:
            out[m.group(1)] = m.group(2)
    return out


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _when(v):
    if v is None:
        return None
    if re.fullmatch(r"\d+", v):
        return int(v)
    try:
        return int(datetime.datetime.strptime(v.replace(" UTC", ""), "%Y-%m-%d %H:%M:%S")
                   .replace(tzinfo=datetime.timezone.utc).timestamp())
    except ValueError:
        return None


def _head(line):
    parts = line[2:].split(" | ")
    i = next((k for k, p in enumerate(parts) if k >= 2 and p.startswith("status=")), len(parts))
    return parts[0].strip(), " | ".join(parts[1:i]).strip(), _kv(parts[i:])


def parse_sessions(text):
    rows = []
    for line in text.splitlines():
        if not line.startswith("- "):
            continue
        sid, title, kv = _head(line)
        prs = []
        for u in [x for x in (kv.get("pull_requests") or "").split(",") if x]:
            m = re.match(r"^(.*?)\[(\w+)\]$", u)
            prs.append({"url": m.group(1), "state": m.group(2)} if m else {"url": u, "state": None})
        rows.append({"session_id": sid, "title": title, "status": (kv.get("status") or "").split(" ")[0] or None,
                     "created": _when(kv.get("created")), "user_id": kv.get("user_id"), "origin": kv.get("origin"),
                     "category": kv.get("category"), "parent": kv.get("parent_session_id"), "prs": prs,
                     "acus": _num(kv.get("acus_consumed"))})
    return rows


def parse_insights(text):
    out, cur = {}, None
    for line in text.splitlines():
        if line.startswith("- "):
            sid, _, kv = _head(line)
            cur = out.setdefault(sid, {"created": _when(kv.get("created"))})
        elif cur is not None and line.startswith("  classification: "):
            parts = line.split(": ", 1)[1].split(" | ")
            kv = _kv(parts[1:])
            cur.update({"classification": parts[0].strip(), "confidence": _num(kv.get("confidence")),
                        "languages": [x for x in (kv.get("languages") or "").split(",") if x],
                        "tools": [x for x in (kv.get("tools") or "").split(",") if x]})
        elif cur is not None and line.startswith("  ") and "num_user_messages=" in line:
            kv = _kv(line.strip().split(" | "))
            for k in ("num_user_messages", "num_devin_messages"):
                if re.fullmatch(r"\d+", kv.get(k) or ""):
                    cur[k] = int(kv[k])
            cur["session_size"] = kv.get("session_size")
            cur["analysis_status"] = kv.get("analysis_status")
    return out


def parse_members(text):
    rows = []
    for line in text.splitlines():
        if line.startswith("- "):
            parts = [p.strip() for p in line[2:].split(" | ")]
            if len(parts) >= 3:
                rows.append({"user_id": parts[0], "email": parts[1].lower(), "name": parts[2]})
    return rows


def parse(raw, start, end, session_url=""):
    def read(pat):
        out = []
        for p in sorted(glob.glob(os.path.join(raw, pat))):
            with open(p, encoding="utf-8") as fh:
                out.append(fh.read())
        return out
    sessions, seen = [], set()
    for t in read("sessions-*.txt"):
        for s in parse_sessions(t):
            if s["session_id"] not in seen and (s["created"] is None or start <= s["created"] <= end):
                seen.add(s["session_id"])
                sessions.append(s)
    insights = {}
    for t in read("insights-*.txt"):
        insights.update({k: v for k, v in parse_insights(t).items() if k in seen})
    members, ids = [], set()
    for t in read("members-*.txt"):
        for m in parse_members(t):
            if m["user_id"] not in ids:
                ids.add(m["user_id"])
                members.append(m)
    iso = lambda u: datetime.datetime.fromtimestamp(u, datetime.timezone.utc).strftime("%Y-%m-%d")  # noqa: E731
    return {"source": "Devin session tools: devin_session_search, devin_session_insights (list), devin_user_list",
            "read_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "period": {"start": start, "end": end, "from": iso(start), "to": iso(end)},
            "session_url": session_url.rstrip("/"), "members": members, "sessions": sessions, "insights": insights}


def _items(f):
    for key in ("prompt_patterns", "gaps", "repeated", "wins"):
        for i, it in enumerate(f.get(key) or []):
            yield key, i, it


def check(usage, findings):
    """Every finding names sessions that are in usage.json; a pattern, gap or repeat needs two or more sessions;
    a person's plan cites only that person's sessions. Returns a list of problems (empty = fine)."""
    owner = {s["session_id"]: s.get("user_id") for s in usage.get("sessions") or []}
    probs = []
    for key, i, it in _items(findings):
        ss = it.get("sessions") or []
        bad = [s for s in ss if s not in owner]
        need = 1 if key == "wins" else 2
        if bad:
            probs.append("%s[%d]: sessions not in usage.json: %s" % (key, i, ", ".join(bad)))
        if len(set(ss) - set(bad)) < need:
            probs.append("%s[%d]: needs at least %d session%s behind it" % (key, i, need, "s" if need > 1 else ""))
        if key == "wins" and it.get("user_id") and any(owner.get(s) != it["user_id"] for s in ss if s in owner):
            probs.append("wins[%d]: cites a session of someone else" % i)
    for uid, plan in (findings.get("people") or {}).items():
        ss = plan.get("sessions") or []
        if not ss:
            probs.append("people[%s]: no sessions behind the plan" % uid)
        for s in ss:
            if owner.get(s) != uid:
                probs.append("people[%s]: session %s is not theirs" % (uid, s))
    return probs


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("parse")
    p.add_argument("raw")
    p.add_argument("--start", type=int, required=True)
    p.add_argument("--end", type=int, required=True)
    p.add_argument("--session-url", default="")
    p.add_argument("-o", "--out", required=True)
    c = sub.add_parser("check")
    c.add_argument("usage")
    c.add_argument("findings")
    a = ap.parse_args(argv)
    if a.cmd == "parse":
        u = parse(a.raw, a.start, a.end, a.session_url)
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump(u, fh, indent=1)
        print("usage -> %s: %d sessions, %d with insights, %d members" % (a.out, len(u["sessions"]), len(u["insights"]), len(u["members"])))
        return 0
    with open(a.usage, encoding="utf-8") as fh:
        usage = json.load(fh)
    with open(a.findings, encoding="utf-8") as fh:
        findings = json.load(fh)
    probs = check(usage, findings)
    for x in probs:
        print("PROBLEM " + x)
    print("findings: %d problem(s)" % len(probs))
    return 1 if probs else 0


if __name__ == "__main__":
    sys.exit(main())
