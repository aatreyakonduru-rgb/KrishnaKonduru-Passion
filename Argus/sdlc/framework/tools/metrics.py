#!/usr/bin/env python3
"""Append-only pipeline metrics, one JSON line per event, per owner.

Events are written to `<session store>/{OWNER}/metrics.jsonl` by gates.py and by any stage
skill that calls `metrics.py record`. Nothing here talks to the network and no message bodies
are stored — only ids, names, timestamps and decisions — so the file is safe to attach or share.

  python3 metrics.py record stage_started --req REQ-001 --stage intake
  python3 metrics.py record stage_finished --req REQ-001 --stage intake
  python3 metrics.py summary [--json]        # gate wait times, rejections, rework, per owner

Event names: stage_started, stage_finished, gate_presented, gate_decided, gate_escalated.
`summary()` is what the dashboard's pipeline-health panel and /status read.
"""
import argparse
import datetime
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import session_store  # noqa: E402

EVENTS = ("stage_started", "stage_finished", "gate_presented", "gate_decided", "gate_escalated",
          "manual_step")  # a person did a repeatable task by hand; /gate-review reads these


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ts(value):
    return datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)


def metrics_path(owner=None):
    owner = owner or session_store.resolve_owner() or "unknown"
    base = session_store.local_home() if session_store.strategy() != "repo" else session_store.REPO_SESSION_ROOT
    return os.path.join(base, owner, "metrics.jsonl")


def record(event, req_id, stage=None, gate=None, story_id=None, decision=None, approver=None,
           rework=None, extra=None, owner=None, at=None):
    if event not in EVENTS:
        raise ValueError("unknown event %r" % event)
    row = {"at": at or now(), "event": event, "owner": owner or session_store.resolve_owner(),
           "requirement_id": req_id, "story_id": story_id, "stage": stage, "gate": gate,
           "decision": decision, "approver": approver, "rework": rework}
    row.update(extra or {})
    path = metrics_path(owner)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({k: v for k, v in row.items() if v is not None}) + "\n")
    return row


def load(owner=None, path=None):
    path = path or metrics_path(owner)
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def summary(rows):
    """Per requirement and per gate: presentations, decisions, wait hours, rejections, rework."""
    gates = defaultdict(lambda: {"presented": 0, "approved": 0, "rejected": 0, "needs_revision": 0,
                                 "wait_hours": [], "escalated": 0})
    stages = defaultdict(lambda: {"started": 0, "finished": 0, "hours": []})
    manual = defaultdict(lambda: {"count": 0, "minutes": []})
    open_presentations = {}
    open_stages = {}
    reqs = set()
    for row in sorted(rows, key=lambda r: r["at"]):
        key = (row.get("requirement_id"), row.get("story_id"), row.get("gate"))
        reqs.add(row.get("requirement_id"))
        ev = row["event"]
        if ev == "gate_presented":
            gates[row["gate"]]["presented"] += 1
            open_presentations[key] = row["at"]
        elif ev == "gate_decided":
            g = gates[row["gate"]]
            g[row.get("decision") or "needs_revision"] = g.get(row.get("decision") or "needs_revision", 0) + 1
            if key in open_presentations:
                delta = parse_ts(row["at"]) - parse_ts(open_presentations.pop(key))
                g["wait_hours"].append(round(delta.total_seconds() / 3600, 2))
        elif ev == "manual_step":
            m = manual[row.get("task") or "unnamed"]
            m["count"] += 1
            if row.get("minutes") is not None:
                m["minutes"].append(float(row["minutes"]))
        elif ev == "gate_escalated":
            gates[row["gate"]]["escalated"] += 1
        elif ev == "stage_started":
            stages[row["stage"]]["started"] += 1
            open_stages[(row.get("requirement_id"), row.get("story_id"), row.get("stage"))] = row["at"]
        elif ev == "stage_finished":
            s = stages[row["stage"]]
            s["finished"] += 1
            k = (row.get("requirement_id"), row.get("story_id"), row.get("stage"))
            if k in open_stages:
                s["hours"].append(round((parse_ts(row["at"]) - parse_ts(open_stages.pop(k))).total_seconds() / 3600, 2))
    out = {"requirements": sorted(r for r in reqs if r), "gates": {}, "stages": {},
           "waiting_now": [{"requirement_id": k[0], "story_id": k[1], "gate": k[2], "since": v}
                           for k, v in open_presentations.items()]}
    for gate, g in gates.items():
        waits = g.pop("wait_hours")
        g["decisions"] = g["approved"] + g["rejected"] + g["needs_revision"]
        g["rework"] = g["rejected"] + g["needs_revision"]
        g["avg_wait_hours"] = round(sum(waits) / len(waits), 2) if waits else None
        g["max_wait_hours"] = max(waits) if waits else None
        out["gates"][gate] = g
    out["manual_steps"] = {}
    for task, m in manual.items():
        mins = m.pop("minutes")
        m["total_minutes"] = round(sum(mins), 1) if mins else None
        m["avg_minutes"] = round(sum(mins) / len(mins), 1) if mins else None
        out["manual_steps"][task] = m
    for stage, s in stages.items():
        hours = s.pop("hours")
        s["avg_hours"] = round(sum(hours) / len(hours), 2) if hours else None
        out["stages"][stage] = s
    return out


def render(summ):
    lines = ["Pipeline health (%d requirement%s)" % (len(summ["requirements"]), "" if len(summ["requirements"]) == 1 else "s")]
    if summ["gates"]:
        lines.append("%-34s %9s %9s %7s %10s" % ("gate", "presented", "approved", "rework", "avg wait h"))
        for gate, g in sorted(summ["gates"].items()):
            lines.append("%-34s %9d %9d %7d %10s" % (gate, g["presented"], g["approved"], g["rework"],
                                                     "-" if g["avg_wait_hours"] is None else g["avg_wait_hours"]))
    if summ["stages"]:
        lines.append("")
        lines.append("%-14s %8s %9s %8s" % ("stage", "started", "finished", "avg h"))
        for stage, s in sorted(summ["stages"].items()):
            lines.append("%-14s %8d %9d %8s" % (stage, s["started"], s["finished"],
                                                "-" if s["avg_hours"] is None else s["avg_hours"]))
    if summ["waiting_now"]:
        lines.append("")
        lines.append("Waiting for a decision right now:")
        for w in summ["waiting_now"]:
            lines.append("  %s %s %s since %s" % (w["requirement_id"], w.get("story_id") or "", w["gate"], w["since"]))
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("record")
    p.add_argument("event", choices=EVENTS)
    p.add_argument("--req", required=True)
    p.add_argument("--story")
    p.add_argument("--stage")
    p.add_argument("--gate")
    p.add_argument("--decision")
    p.add_argument("--approver")
    p.add_argument("--task", help="manual_step: id from .devin/rules/manual-steps.yaml")
    p.add_argument("--minutes", type=float, help="manual_step: how long it took by hand")
    p = sub.add_parser("summary")
    p.add_argument("--json", action="store_true")
    p.add_argument("--file", help="read this metrics.jsonl instead of the owner's")
    args = parser.parse_args(argv)
    if args.command == "record":
        row = record(args.event, args.req, stage=args.stage, gate=args.gate, story_id=args.story,
                     decision=args.decision, approver=args.approver,
                     extra={k: v for k, v in (("task", args.task), ("minutes", args.minutes)) if v is not None})
        print(json.dumps(row))
    else:
        summ = summary(load(path=args.file))
        print(json.dumps(summ, indent=1) if args.json else render(summ))


if __name__ == "__main__":
    main()
