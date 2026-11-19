#!/usr/bin/env python3
"""Devin usage per story and stage, for the Cost tab.

Reads the team's Devin Cloud sessions (GET /v1/sessions with Argus and verifier tags) and groups them by the
story key in their title or tags and by stage: intake, research, plan, implement, eval, release, kb-refresh, the
independent verifier, or other. For each it gives the number of sessions and their hours from start to last update.
The Devin API does not report ACUs per session, so no ACU figure is shown or guessed; when
cost.devin_usage_export in scrum-master-metrics.yaml names a CSV exported from Devin's usage page (session_id and
acus columns), its ACUs are added.
"""
import csv
import datetime
import json
import os
import re
import urllib.request

API = os.environ.get("DEVIN_API_BASE", "https://api.devin.ai").rstrip("/")
TAGS = ("sdlc-workbench", "sdlc-verifier")
STAGES = ("intake", "research", "plan", "implement", "eval", "release", "kb-refresh")
KEY = re.compile(r"\b(ACME-\d+|REQ-[A-Z0-9-]+?(?:[ /]STORY-\d+)?)\b")


def when(value):
    try:
        return datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def stage_of(session):
    tags = [str(t).lower() for t in session.get("tags") or []]
    title = str(session.get("title") or "").lower()
    if "sdlc-verifier" in tags or title.startswith("verifier"):
        return "verifier"
    for s in STAGES:
        if s in tags or re.search(r"(^|[^a-z])/?%s([^a-z]|$)" % re.escape(s), title):
            return s
    return "other"


def story_of(session):
    for text in [session.get("title") or ""] + [str(t) for t in session.get("tags") or []]:
        m = KEY.search(str(text))
        if m:
            return m.group(1).replace("/", " ")
    return ""


def load_acus(path):
    if not path or not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        return {r.get("session_id", ""): float(r.get("acus") or 0) for r in csv.DictReader(fh)}


def rows(sessions, acus=None):
    """One row per story and stage: sessions, verifier sessions, hours, and ACUs only when an export gives them."""
    acus = acus or {}
    out = {}
    for s in sessions:
        story = story_of(s)
        if not story:
            continue
        stage = stage_of(s)
        r = out.setdefault((story, stage), {"story": story, "stage": stage, "sessions": 0, "hours": 0.0, "acus": None})
        r["sessions"] += 1
        a, b = when(s.get("created_at")), when(s.get("updated_at"))
        if a and b and b > a:
            r["hours"] += (b - a).total_seconds() / 3600.0
        if s.get("session_id") in acus:
            r["acus"] = (r["acus"] or 0) + acus[s["session_id"]]
    for r in out.values():
        r["hours"] = round(r["hours"], 1)
    order = {s: i for i, s in enumerate(STAGES + ("verifier", "other"))}
    return sorted(out.values(), key=lambda r: (r["story"], order[r["stage"]]))


def fetch(key=None, limit=200):
    """The team's sessions with Argus and verifier tags. Raises when the key is missing or the API refuses."""
    key = key or os.environ.get("DEVIN_API_KEY")
    if not key:
        raise RuntimeError("no DEVIN_API_KEY on this machine")
    seen, out = set(), []
    for tag in TAGS:
        req = urllib.request.Request("%s/v1/sessions?limit=%d&tags=%s" % (API, limit, tag),
                                     headers={"Authorization": "Bearer " + key})
        with urllib.request.urlopen(req, timeout=30) as resp:
            for s in (json.load(resp) or {}).get("sessions") or []:
                if s.get("session_id") not in seen:
                    seen.add(s.get("session_id"))
                    out.append(s)
    return out
