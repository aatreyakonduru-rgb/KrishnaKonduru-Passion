#!/usr/bin/env python3
"""Risk and dependency register per epic, kept in the knowledge base (SHARED/risk-register.yaml), never Jira.

    risk_register.py add --epic ACME-n --kind risk --text T --owner NAME --likelihood low|medium|high
                         --impact low|medium|high [--mitigation T] --by NAME [--write]
    risk_register.py add --epic ACME-n --kind dependency --text T --owner NAME --team TEAM
                         --needed-by YYYY-MM-DD --by NAME [--write]
    risk_register.py close --id R-1 --by NAME [--note T] [--write]
    risk_register.py list

Without --write it prints the change; --write saves it, after the person types "approved".
"""
import argparse
import datetime
import os
import re
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
PATH = os.path.join(ROOT, "docs", "knowledge-base", "SHARED", "risk-register.yaml")
HEADER = ("# Risks and dependencies per epic for the Acme Claims team: PO office tab on the dashboard.\n"
          "# Written by sdlc/framework/tools/risk_register.py after the person types \"approved\". Never Jira.\n")
LEVELS = ("low", "medium", "high")
KINDS = ("risk", "dependency")


def load(path=PATH):
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    data.setdefault("items", [])
    return data


def save(data, path=PATH):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(HEADER + yaml.safe_dump(data, sort_keys=False, allow_unicode=True))


def add(data, epic, kind, text, owner, by, likelihood="", impact="", mitigation="", team="", needed_by="",
        today=None):
    if not re.fullmatch(r"ACME-\d+", epic or ""):
        raise ValueError("epic must be a Acme Claims key")
    if kind not in KINDS:
        raise ValueError("kind must be risk or dependency")
    if not text or not owner:
        raise ValueError("text and owner are required")
    if kind == "risk" and (likelihood not in LEVELS or impact not in LEVELS):
        raise ValueError("a risk needs likelihood and impact: low, medium or high")
    if kind == "dependency":
        if not team:
            raise ValueError("a dependency needs the team it depends on")
        datetime.date.fromisoformat(needed_by)
    prefix = "R" if kind == "risk" else "D"
    n = 1 + max([int(i["id"][2:]) for i in data["items"] if i["id"].startswith(prefix + "-")] or [0])
    item = {"id": "%s-%d" % (prefix, n), "epic": epic, "kind": kind, "text": text, "owner": owner}
    if kind == "risk":
        item.update(likelihood=likelihood, impact=impact, mitigation=mitigation)
    else:
        item.update(team=team, needed_by=needed_by)
    item.update(status="open", raised_by=by, raised=str(today or datetime.date.today()))
    data["items"].append(item)
    return item


def close(data, item_id, by, note="", today=None):
    for i in data["items"]:
        if i["id"] == item_id:
            i.update(status="closed", closed_by=by, closed=str(today or datetime.date.today()), close_note=note)
            return i
    raise ValueError("no item " + item_id)


def rows(data, today=None):
    today = today or datetime.date.today()
    out = []
    for i in data["items"]:
        if i.get("status") != "open":
            continue
        r = dict(i)
        r["score"] = ((LEVELS.index(i["likelihood"]) + 1) * (LEVELS.index(i["impact"]) + 1)
                      if i["kind"] == "risk" else 0)
        r["late"] = i["kind"] == "dependency" and datetime.date.fromisoformat(str(i["needed_by"])) < today
        out.append(r)
    return sorted(out, key=lambda r: (not r["late"], -r["score"], r["epic"], r["id"]))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    for f in ("epic", "kind", "text", "owner", "by"):
        a.add_argument("--" + f, required=True)
    for f in ("likelihood", "impact", "mitigation", "team", "needed-by"):
        a.add_argument("--" + f, default="")
    c = sub.add_parser("close")
    c.add_argument("--id", required=True)
    c.add_argument("--by", required=True)
    c.add_argument("--note", default="")
    for p in (a, c):
        p.add_argument("--write", action="store_true")
    sub.add_parser("list")
    args = ap.parse_args(argv)
    data = load()
    if args.cmd == "list":
        for r in rows(data):
            print("%(id)s %(epic)s %(kind)s %(owner)s: %(text)s" % r + (" LATE" if r["late"] else ""))
        return 0
    if args.cmd == "add":
        item = add(data, args.epic, args.kind, args.text, args.owner, args.by, args.likelihood, args.impact,
                   args.mitigation, args.team, args.needed_by)
    else:
        item = close(data, args.id, args.by, args.note)
    print(yaml.safe_dump(item, sort_keys=False).rstrip())
    if args.write:
        save(data)
        print("[SDLC] risk register saved: %s" % item["id"])
    else:
        print("[SDLC] preview only: add --write after \"approved\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
