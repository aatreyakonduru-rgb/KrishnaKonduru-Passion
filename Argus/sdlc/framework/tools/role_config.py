#!/usr/bin/env python3
"""Who holds which role: every person on the roster against every role, for the Role config tab.

A person has one main role (primary_role in .devin/rules/people.yaml) and any other hats (secondary_roles). The
role decides the skills they get (Skill config), their dashboard view and the gates they can sign
(role-routing.yaml gate_roles). The tab turns changed ticks into a SDLC-DASHBOARD-ROLE-CONFIG block; this script
shows the change and, after approved, writes it to people.yaml for a reviewed pull request. The Confluence roster
page follows after the merge through /roster-sync.

  python3 role_config.py grid
  python3 role_config.py apply --block <file> [--write]
"""
import argparse
import os
import re
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
PEOPLE = os.path.join(ROOT, ".devin", "rules", "people.yaml")
ROUTING = os.path.join(ROOT, ".devin", "rules", "role-routing.yaml")
BLOCK = "SDLC-DASHBOARD-ROLE-CONFIG v1"


def load(path):
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def grid(people=None, routing=None):
    """(roles, rows): the role columns in role-routing.yaml order, and per person the state of each column
    (primary, secondary or none) with the gates their roles let them sign."""
    people = people if people is not None else load(PEOPLE)
    routing = routing if routing is not None else load(ROUTING)
    table = routing.get("roles") or {}
    cols = [(r, v.get("label", r)) for r, v in table.items()]
    rows = []
    for p in people.get("people") or []:
        prim, sec = p.get("primary_role"), list(p.get("secondary_roles") or [])
        cells = {r: "primary" if r == prim else "secondary" if r in sec else "none" for r, _ in cols}
        gates = sorted({g for r in [prim] + sec for g in (table.get(r) or {}).get("gate_roles") or []})
        rows.append({"jira_user": str(p.get("jira_user") or ""), "name": p.get("name") or "", "cells": cells,
                     "gates": gates})
    return cols, rows


def parse_block(text):
    if BLOCK not in text:
        raise ValueError("no %s block" % BLOCK)
    out = []
    for line in text[text.index(BLOCK):].splitlines()[1:]:
        if line.strip() == "END":
            break
        m = re.match(r"^- person: (\S+) \| ([a-z_]+): (primary|secondary|none)\s*$", line.strip())
        if m:
            out.append(m.groups())
        elif line.strip():
            raise ValueError("not understood: %r" % line)
    return out


def apply(changes, people, routing, editor=""):
    """people.yaml data with the changes made, and one line per change. A person keeps exactly one main role;
    nobody changes their own row (ROSTER-GOVERNANCE.md)."""
    import copy
    people = copy.deepcopy(people)
    table = routing.get("roles") or {}
    by_user = {str(p.get("jira_user") or "").upper(): p for p in people.get("people") or []}
    said = []
    for user, role, state in changes:
        p = by_user.get(user.upper())
        if p is None:
            raise ValueError("%s is not on the roster" % user)
        if role not in table:
            raise ValueError("no role called %r in role-routing.yaml" % role)
        if editor and editor.upper() == user.upper():
            raise ValueError("%s cannot change their own roles; the roster owner or a backup does it" % user)
        sec = [r for r in p.get("secondary_roles") or [] if r != role]
        if state == "primary":
            old = p.get("primary_role")
            if old and old != role and old not in sec:
                sec.insert(0, old)
            p["primary_role"] = role
        elif state == "secondary":
            if p.get("primary_role") == role:
                raise ValueError("%s: pick another main role before making %s a second hat" % (p["name"], role))
            sec.append(role)
        elif p.get("primary_role") == role:
            raise ValueError("%s needs a main role; tick another one as main instead of clearing %s" % (p["name"], role))
        p["secondary_roles"] = sec
        said.append("%s: %s %s" % (p["name"], table[role].get("label", role),
                                   {"primary": "is now the main role", "secondary": "added as another hat",
                                    "none": "taken off"}[state]))
    return people, said


def write(path, people):
    """Rewrite primary_role and secondary_roles of each changed person in place, keeping every other line."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    for p in people.get("people") or []:
        m = re.search(r"(?ms)^- jira_user: %s\n.*?(?=^- jira_user: |^\S|\Z)" % re.escape(str(p["jira_user"])), text)
        if not m:
            continue
        block = m.group(0)
        sec = p.get("secondary_roles") or []
        new = re.sub(r"(?m)^  primary_role: .*$", "  primary_role: %s" % p.get("primary_role"), block)
        new = re.sub(r"(?m)^  secondary_roles:(?: \[\])?\n(?:  - .*\n)*",
                     "  secondary_roles:%s\n" % ("".join("\n  - %s" % r for r in sec) if sec else " []"), new)
        text = text.replace(block, new, 1)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("grid")
    a = sub.add_parser("apply")
    a.add_argument("--block", required=True)
    a.add_argument("--by", default="", help="Jira user of the person making the change")
    a.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd == "grid":
        cols, rows = grid()
        for r in rows:
            print("%s %s: %s" % (r["jira_user"], r["name"], ", ".join("%s=%s" % (c, r["cells"][c]) for c, _ in cols
                                                                      if r["cells"][c] != "none")))
        return 0
    with open(args.block, encoding="utf-8") as fh:
        people, said = apply(parse_block(fh.read()), load(PEOPLE), load(ROUTING), args.by)
    print("\n".join(said))
    if args.write:
        write(PEOPLE, people)
        print("written to .devin/rules/people.yaml")
    else:
        print("preview only: nothing written (say approved, then run again with --write)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
