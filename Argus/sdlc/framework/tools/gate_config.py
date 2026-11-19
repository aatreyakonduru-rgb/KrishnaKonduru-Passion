#!/usr/bin/env python3
"""Who signs each gate: every approval gate against every person on the roster, for the Gate config tab.

A person is a named approver of a gate (names in .devin/rules/approval-gates.yaml) or one of its backups (backups,
asked when everyone named is away, gates.approver_route). The tab turns changed ticks into a
SDLC-DASHBOARD-GATE-CONFIG block; this script shows the change and, after approved, writes approval-gates.yaml for a
reviewed pull request.

  python3 gate_config.py grid
  python3 gate_config.py apply --block <file> [--write]
"""
import argparse
import copy
import os
import re
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
GATES = os.path.join(ROOT, ".devin", "rules", "approval-gates.yaml")
PEOPLE = os.path.join(ROOT, ".devin", "rules", "people.yaml")
BLOCK = "SDLC-DASHBOARD-GATE-CONFIG v1"


def load(path):
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def norm(name):
    return "".join(sorted(re.findall(r"[a-z0-9]+", str(name).lower())))


def gate_name(person):
    """The roster name as the gates write it: "Resource 16" -> "Resource 16"."""
    return " ".join(w.capitalize() if w.isupper() and len(w) > 1 else w
                    for w in str(person.get("name") or "").replace(",", " ").split())


def grid(gates=None, people=None):
    """(people, rows): the roster, and per gate its id, name, timeout and the state of each person (named, backup or none)."""
    gates = gates if gates is not None else load(GATES)
    people = [p for p in (people if people is not None else load(PEOPLE)).get("people") or []]
    rows = []
    for g in gates.get("gates") or []:
        first = (g.get("approvers") or [{}])[0]
        named = {norm(n) for a in g.get("approvers") or [] for n in a.get("names") or []}
        backup = {norm(n) for a in g.get("approvers") or [] for n in a.get("backups") or []}
        cells = {str(p["jira_user"]): "named" if norm(p.get("name")) in named else
                 "backup" if norm(p.get("name")) in backup else "none" for p in people}
        rows.append({"id": g.get("id"), "name": g.get("name") or "", "role": first.get("role") or g.get("required_role") or "",
                     "timeout": g.get("timeout_hours"), "blocks": g.get("blocks_if_failed") or "",
                     "cells": cells})
    return people, rows


def parse_block(text):
    if BLOCK not in text:
        raise ValueError("no %s block" % BLOCK)
    out = []
    for line in text[text.index(BLOCK):].splitlines()[1:]:
        if line.strip() == "END":
            break
        m = re.match(r"^- gate: (\S+) \| (\S+): (named|backup|none)\s*$", line.strip())
        if m:
            out.append(m.groups())
        elif line.strip():
            raise ValueError("not understood: %r" % line)
    return out


def apply(changes, gates, people):
    """approval-gates data with the changes made to each gate's first approver entry, and a line per change.
    A gate always keeps at least one named approver."""
    gates = copy.deepcopy(gates)
    by_id = {g.get("id"): g for g in gates.get("gates") or []}
    by_user = {str(p.get("jira_user") or "").upper(): p for p in people.get("people") or []}
    said = []
    for gid, user, state in changes:
        g, p = by_id.get(gid), by_user.get(user.upper())
        if g is None:
            raise ValueError("no gate %s in approval-gates.yaml" % gid)
        if p is None:
            raise ValueError("%s is not on the roster" % user)
        entries = g.setdefault("approvers", [{"role": g.get("required_role") or ""}])
        now = ("named" if any(norm(n) == norm(p["name"]) for a in entries for n in a.get("names") or []) else
               "backup" if any(norm(n) == norm(p["name"]) for a in entries for n in a.get("backups") or []) else "none")
        if now == state:
            said.append("%s: %s already %s, no change" % (gid, p["name"], {"named": "signs it", "backup": "is a backup",
                                                                          "none": "off"}[state]))
            continue
        for a in entries:
            for key in ("names", "backups"):
                a[key] = [n for n in a.get(key) or [] if norm(n) != norm(p["name"])]
        if state != "none":
            entries[0].setdefault("names" if state == "named" else "backups", []).append(gate_name(p))
        if not any(a.get("names") for a in entries):
            raise ValueError("%s needs at least one named approver" % gid)
        said.append("%s: %s %s" % (gid, p["name"], {"named": "signs it", "backup": "is a backup",
                                                    "none": "taken off"}[state]))
    return gates, said


def write(path, gates):
    """Rewrite the names and backups lines of each gate's approver entries in place, keeping every other line."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    flow = lambda items: "[%s]" % ", ".join(items)  # noqa: E731
    for g in gates.get("gates") or []:
        m = re.search(r"(?ms)^  - id: %s\n.*?(?=^  - id: |^\S|\Z)" % re.escape(str(g.get("id"))), text)
        if not m:
            continue
        block, entries = m.group(0), iter(g.get("approvers") or [])

        def entry(mm):
            a = next(entries, None)
            if a is None:
                return mm.group(0)
            out = mm.group(1) + "        names: %s\n" % flow(a.get("names") or [])
            if a.get("backups") or "backups:" in mm.group(0):
                out += "        backups: %s\n" % flow(a.get("backups") or [])
            return out
        new = re.sub(r"(?m)^(      - role: .*\n)(?:        names: .*\n)?(?:        backups: .*\n)?", entry, block)
        text = text.replace(block, new, 1)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("grid")
    a = sub.add_parser("apply")
    a.add_argument("--block", required=True)
    a.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd == "grid":
        people, rows = grid()
        names = {str(p["jira_user"]): p["name"] for p in people}
        for r in rows:
            print("%s: %s" % (r["id"], "; ".join("%s=%s" % (names[u], s) for u, s in r["cells"].items() if s != "none")))
        return 0
    with open(args.block, encoding="utf-8") as fh:
        gates, said = apply(parse_block(fh.read()), load(GATES), load(PEOPLE))
    print("\n".join(said))
    if args.write:
        write(GATES, gates)
        print("written to .devin/rules/approval-gates.yaml")
    else:
        print("preview only: nothing written (say approved, then run again with --write)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
