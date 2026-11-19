#!/usr/bin/env python3
"""/gate-review — find manual SDLC work worth automating. It never retires an approval gate.

Reads the manual-work register (.devin/rules/manual-steps.yaml), the pipeline metrics
(metrics.jsonl: gate waits, rework, and `manual_step` events people record) and the gate list.
It writes a ranked automation backlog. Human decisions stay with people; for a slow gate the
only suggestion is to automate the evidence the approver reads, not the approval.

    python3 gate_review.py                  # report on the owner's metrics
    python3 gate_review.py --file m.jsonl   # someone else's metrics file
    python3 gate_review.py --md OUT.md      # also write the report as markdown
    python3 gate_review.py --check          # validate the register only; exit 1 on problems
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gates  # noqa: E402
import metrics  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
REGISTER = os.path.join(ROOT, ".devin", "rules", "manual-steps.yaml")
KINDS = ("manual_work", "human_decision")
STATUSES = ("open", "in_progress", "automated", "blocked")
RUNS_PER_MONTH = {"every-15-min": 2880, "daily": 22, "weekly": 4, "monthly": 1, "quarterly": 1 / 3.0}
FORBIDDEN = re.compile(r"\b(retire|remove|skip|bypass|auto-?approve|drop)\b", re.I)
SLOW_GATE_HOURS = 24


def unknown(value):
    return value is None or str(value).strip() in ("", "[?]")


def load_register(path=REGISTER):
    return gates.load_yaml(path).get("tasks", []) or []


def validate(tasks, gate_ids=None):
    problems, seen = [], set()
    for t in tasks:
        tid = t.get("id") or "<no id>"
        if tid in seen:
            problems.append("%s: duplicate id" % tid)
        seen.add(tid)
        for key in ("id", "kind", "stage", "task", "evidence", "status"):
            if not t.get(key):
                problems.append("%s: missing '%s'" % (tid, key))
        if t.get("kind") not in KINDS:
            problems.append("%s: kind must be one of %s" % (tid, ", ".join(KINDS)))
        if t.get("status") and t["status"] not in STATUSES:
            problems.append("%s: status must be one of %s" % (tid, ", ".join(STATUSES)))
        for ev in t.get("evidence") or []:
            if not str(ev).startswith("[E:"):
                problems.append("%s: evidence must be tagged [E: source] — %r" % (tid, ev))
        if t.get("kind") == "human_decision":
            if t.get("status") == "automated":
                problems.append("%s: a human decision cannot be marked automated" % tid)
            if FORBIDDEN.search(str(t.get("automation", ""))) and not re.search(r"\bkeep\b", str(t.get("automation", "")), re.I):
                problems.append("%s: a human decision's plan may not retire, skip or auto-approve it" % tid)
            if gate_ids is not None and t.get("gate") and t["gate"] not in gate_ids:
                problems.append("%s: gate %s is not in approval-gates.yaml" % (tid, t["gate"]))
        if t.get("kind") == "manual_work" and not t.get("automation"):
            problems.append("%s: manual work needs an 'automation' idea" % tid)
    return problems


def monthly_minutes(task, observed):
    """(minutes per month, how we know). None when frequency or duration is unknown."""
    per_run = observed.get("avg_minutes") if observed else None
    source = "recorded" if per_run is not None else None
    if per_run is None and not unknown(task.get("minutes_each")):
        per_run, source = float(task["minutes_each"]), "register"
    runs = RUNS_PER_MONTH.get(str(task.get("frequency")))
    if per_run is None or runs is None:
        return None, source
    return round(per_run * runs), source


def priority(task, minutes):
    if task.get("status") == "automated":
        return "done"
    if minutes is None:
        return "size unknown"
    return "high" if minutes >= 240 else "medium" if minutes >= 60 else "low"


def review(tasks, summ, gate_list):
    manual = summ.get("manual_steps", {})
    backlog, decisions, unknowns = [], [], []
    for t in tasks:
        obs = manual.get(t["id"])
        if t["kind"] == "human_decision":
            decisions.append(t)
            continue
        mins, how = monthly_minutes(t, obs)
        backlog.append({"task": t, "observed": obs, "monthly_minutes": mins, "how": how,
                        "priority": priority(t, mins)})
        for key in ("done_by_today", "frequency", "minutes_each", "candidate_owner"):
            if unknown(t.get(key)):
                unknowns.append("%s — %s" % (t["id"], key.replace("_", " ")))
    order = {"high": 0, "medium": 1, "low": 2, "size unknown": 3, "done": 4}
    status_order = {"open": 0, "in_progress": 1, "blocked": 2, "automated": 3}
    backlog.sort(key=lambda r: (order[r["priority"]], status_order.get(r["task"]["status"], 9),
                                -(r["monthly_minutes"] or 0)))
    registered = {t["id"] for t in tasks}
    unregistered = sorted(k for k in manual if k not in registered)
    gate_rows = []
    for g in gate_list:
        s = summ.get("gates", {}).get(g["id"], {})
        slow = (s.get("avg_wait_hours") or 0) > SLOW_GATE_HOURS
        gate_rows.append({"id": g["id"], "presented": s.get("presented", 0), "rework": s.get("rework", 0),
                          "avg_wait_hours": s.get("avg_wait_hours"),
                          "advice": ("Keep. Waits over %dh on average — automate the evidence the approver reads"
                                     % SLOW_GATE_HOURS) if slow else "Keep."})
    return {"backlog": backlog, "decisions": decisions, "gates": gate_rows,
            "unregistered": unregistered, "unknowns": unknowns}


def render(result, metrics_source):
    out = ["# Manual work that could be automated", "",
           "Approval gates are not on this list to be removed. People still make every decision; the",
           "work below is the copying, checking and chasing around those decisions "
           "[E: .devin/rules/manual-steps.yaml].", "",
           "Metrics read from `%s`." % metrics_source, "",
           "## Automation backlog", "",
           "| Priority | Task | Stage | Status | Time per month | What would replace it | Needs | Evidence |",
           "|---|---|---|---|---|---|---|---|"]
    for r in result["backlog"]:
        t = r["task"]
        mins = "[?]" if r["monthly_minutes"] is None else "%d min (%s)" % (r["monthly_minutes"], r["how"])
        out.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
            r["priority"], t["task"], t["stage"], t["status"], mins, t.get("automation", ""),
            t.get("needs", "") or "", "<br>".join(t.get("evidence", []))))
    out += ["", "## Decisions that stay with people", ""]
    for t in result["decisions"]:
        out.append("- **%s** (%s%s) — %s %s" % (t["task"], t.get("done_by_today", "[?]"),
                                               ", gate " + t["gate"] if t.get("gate") else "",
                                               t.get("automation", ""), " ".join(t.get("evidence", []))))
    out += ["", "## Approval gates", "",
            "| Gate | Presented | Sent back | Avg wait (h) | Advice |", "|---|---|---|---|---|"]
    for g in result["gates"]:
        out.append("| %s | %d | %d | %s | %s |" % (g["id"], g["presented"], g["rework"],
                                                   "-" if g["avg_wait_hours"] is None else g["avg_wait_hours"],
                                                   g["advice"]))
    if result["unregistered"]:
        out += ["", "## Recorded manual steps not in the register", "",
                "People logged these with `metrics.py record manual_step` but nobody has described them yet:", ""]
        out += ["- %s" % k for k in result["unregistered"]]
    out += ["", "## Assumptions", "",
            "- Time per month = average minutes per run × runs per month for the stated frequency "
            "(daily = 22 working days). If the frequency is wrong, the priority is wrong.",
            "", "## Don't know", ""]
    out += ["- %s — [?] ask the task's owner, or record a few runs with "
            "`metrics.py record manual_step --task <id> --minutes <n>`" % u for u in result["unknowns"]] or ["- nothing"]
    return "\n".join(out) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--register", default=REGISTER)
    parser.add_argument("--file", help="metrics.jsonl to read instead of the owner's")
    parser.add_argument("--md", help="write the report here as well")
    parser.add_argument("--check", action="store_true", help="validate the register and stop")
    args = parser.parse_args(argv)
    tasks = load_register(args.register)
    gate_list = list(gates.gate_defs().values())
    problems = validate(tasks, {g["id"] for g in gate_list})
    for p in problems:
        print("REGISTER: " + p)
    if args.check or problems:
        print("register OK (%d tasks)" % len(tasks) if not problems else "%d register problem(s)" % len(problems))
        return 1 if problems else 0
    path = args.file or metrics.metrics_path()
    report = render(review(tasks, metrics.summary(metrics.load(path=path)), gate_list),
                    os.path.relpath(path, ROOT) if path.startswith(ROOT) else path)
    print(report)
    if args.md:
        with open(args.md, "w", encoding="utf-8") as fh:
            fh.write(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
