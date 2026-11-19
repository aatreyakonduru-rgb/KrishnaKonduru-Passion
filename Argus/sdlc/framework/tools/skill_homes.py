#!/usr/bin/env python3
"""Who gets each skill: every skill in one place, its assignment configured and counted.

In .devin/rules/role-routing.yaml a role's default_skills are its first commands (the top of /help and of the
Argus's My tools menu, at most eight), more_skills the rest of its My tools, and everyone_skills are on every
role's My tools. A skill is internal to the system when another skill or an automation runs it: the internal_skills
list, the app-, db- and etl- documentation stages that run one shared prompt, and the older names. Everything else
nobody has been given yet is "not assigned". The Skill config tab on the Tech Lead dashboard, the My commands tab
and the daily tip all read this.

  python3 skill_homes.py check                       names in role-routing.yaml that are not installed skills
  python3 skill_homes.py counts                      assigned, not assigned, internal
  python3 skill_homes.py for --role bsa              one role's commands, grouped
  python3 skill_homes.py tip --person "<name or Jira user>"   today's command tip for that person
  python3 skill_homes.py apply --block <file> [--write]       a SDLC-DASHBOARD-SKILL-CONFIG block from the tab
"""
import argparse
import datetime
import glob
import os
import re
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SKILLS_GLOB = ".devin/skills/*/SKILL.md"
ROUTING = ".devin/rules/role-routing.yaml"
PEOPLE = ".devin/rules/people.yaml"
# The Skill config columns: each heading ticks every role under it.
GROUPS = [
    ("Developer", ["developer", "ui_developer", "api_developer", "etl_developer", "ux_designer", "new_joiner"]),
    ("Tech lead", ["solution_lead", "reviewer"]),
    ("Architect", ["architect"]),
    ("QA", ["qa_lead", "qa_staff", "automation_engineer"]),
    ("UAT", ["uat_lead", "uat_staff"]),
    ("BSA", ["bsa", "bsa_lead"]),
    ("PO", ["product_owner"]),
    ("Scrum Master", ["scrum_master"]),
    ("Delivery lead / manager", ["lead", "manager"]),
    ("Release manager", ["release_manager"]),
]
EVERYONE = "Everyone"
MAX_FIRST = 8
BLOCK = "SDLC-DASHBOARD-SKILL-CONFIG v1"
PIPELINES = (("app-", "app-run-pipeline"), ("db-", "db-run-pipeline"), ("etl-", "etl-run-pipeline"))
NO_TIP = {"dashboard", "help"}


def first_sentence(text):
    text = re.sub(r"\s+", " ", str(text or "")).strip().strip("'\"")
    return re.split(r"(?<=[.!?])\s", text)[0]


def skills(root=ROOT):
    out = {}
    for path in sorted(glob.glob(os.path.join(root, SKILLS_GLOB))):
        with open(path, encoding="utf-8") as fh:
            parts = fh.read().split("---", 2)
        fm = yaml.safe_load(parts[1]) if len(parts) > 2 else {}
        name = (fm or {}).get("name") or os.path.basename(os.path.dirname(path))
        desc = re.sub(r"\s+", " ", str((fm or {}).get("description") or "")).strip().strip("'\"")
        out[name] = {"name": name, "what": first_sentence(desc), "description": desc}
    return out


def routing(root=ROOT):
    with open(os.path.join(root, ROUTING), encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def stage_of(name, desc):
    if "runs shared prompt" not in desc:
        return None
    for prefix, parent in PIPELINES:
        if name.startswith(prefix) and name != parent:
            return parent
    return None


def alias_of(desc):
    m = re.match(r"Older name for /([a-z0-9-]+)", desc)
    return m.group(1) if m else None


def internal_reason(name, desc, config):
    """Why a skill is internal to the system, or None."""
    listed = config.get("internal_skills") or {}
    if name in listed:
        return "Internal to the system: %s." % str(listed[name]).rstrip(".")
    parent = stage_of(name, desc)
    if parent:
        return "Internal to the system: a stage of /%s." % parent
    alias = alias_of(desc)
    if alias:
        return "Internal to the system: older name for /%s, which still works." % alias
    return None


def homes(root=ROOT, known=None, config=None):
    known = known if known is not None else skills(root)
    config = config if config is not None else routing(root)
    roles = config.get("roles") or {}
    everyone = set(config.get("everyone_skills") or [])
    out = {}
    for name, s in known.items():
        first = [r for r, v in roles.items() if name in (v.get("default_skills") or [])]
        more = [r for r, v in roles.items() if name in (v.get("more_skills") or [])]
        out[name] = {"first": first, "more": more, "everyone": name in everyone,
                     "pipeline": None if first or more or name in everyone else stage_of(name, s["description"]),
                     "alias_of": alias_of(s["description"]),
                     "internal": internal_reason(name, s["description"], config)}
    return out


def unhomed(root=ROOT, known=None, config=None):
    """Skills nobody has been given and that are not internal: the Skill config tab shows them with empty boxes."""
    return sorted(n for n, h in homes(root, known, config).items()
                  if not (h["first"] or h["more"] or h["everyone"] or h["internal"]))


def counts(root=ROOT, known=None, config=None):
    h = homes(root, known, config)
    internal = sum(1 for v in h.values() if v["internal"] and not (v["first"] or v["more"] or v["everyone"]))
    unassigned = len(unhomed(root, known, config))
    return {"skills": len(h), "assigned": len(h) - internal - unassigned, "not_assigned": unassigned,
            "internal": internal}


def grid(root=ROOT, known=None, config=None):
    """One row per skill: the state of each column (first, tick, some or none), or why it is internal."""
    known = known if known is not None else skills(root)
    config = config if config is not None else routing(root)
    table = config.get("roles") or {}
    everyone = set(config.get("everyone_skills") or [])
    h = homes(root, known, config)
    rows = []
    for name in sorted(known):
        v = h[name]
        assigned = v["first"] or v["more"] or v["everyone"]
        row = {"name": name, "what": known[name]["what"], "internal": None if assigned else v["internal"],
               "cells": {}, "detail": {}}
        if not row["internal"]:
            for label, members in GROUPS:
                members = [r for r in members if r in table]
                first = [r for r in members if name in (table[r].get("default_skills") or [])]
                more = [r for r in members if name in (table[r].get("more_skills") or [])]
                if members and len(first) == len(members):
                    state = "first"
                elif members and len(first) + len(more) == len(members):
                    state = "tick"
                elif first or more:
                    state = "some"
                else:
                    state = "none"
                row["cells"][label] = state
                row["detail"][label] = ", ".join(table[r].get("label", r) for r in first + more)
            row["cells"][EVERYONE] = "tick" if name in everyone else "none"
        rows.append(row)
    return rows


def parse_block(text):
    """[(skill, column, state)] from a SDLC-DASHBOARD-SKILL-CONFIG block; state is first, tick or none."""
    if BLOCK not in text:
        raise ValueError("no %s block" % BLOCK)
    out = []
    for line in text[text.index(BLOCK):].splitlines()[1:]:
        if line.strip() == "END":
            break
        m = re.match(r"^- skill: ([a-z0-9-]+) \| (.+): (first|tick|none)\s*$", line.strip())
        if m:
            out.append((m.group(1), m.group(2).strip(), m.group(3)))
        elif line.strip():
            raise ValueError("not understood: %r" % line)
    return out


def apply(changes, config, known=None):
    """The routing config with the changes made, and a line per change. Refuses internal skills, unknown columns
    and more than eight first commands for a role."""
    import copy
    known = known if known is not None else skills()
    config = copy.deepcopy(config)
    table = config.get("roles") or {}
    groups = dict(GROUPS)
    h = homes(known=known, config=config)
    said = []
    for name, column, state in changes:
        if name not in known:
            raise ValueError("/%s is not an installed skill" % name)
        if h[name]["internal"] and not (h[name]["first"] or h[name]["more"] or h[name]["everyone"]):
            raise ValueError("/%s is internal to the system; nobody is given it" % name)
        if column == EVERYONE:
            lst = config.setdefault("everyone_skills", [])
            if state == "none" and name in lst:
                lst.remove(name)
            elif state != "none" and name not in lst:
                lst.append(name)
            said.append("/%s: %s" % (name, "on everyone's My tools" if state != "none" else "taken off everyone's My tools"))
            continue
        if column not in groups:
            raise ValueError("no column called %r" % column)
        for r in [r for r in groups[column] if r in table]:
            role = table[r]
            for key in ("default_skills", "more_skills"):
                if name in (role.get(key) or []):
                    role[key].remove(name)
            key = {"first": "default_skills", "tick": "more_skills"}.get(state)
            if key:
                role.setdefault(key, []).append(name)
                if key == "default_skills" and len(role[key]) > MAX_FIRST:
                    raise ValueError("%s would have %d first commands; at most %d" % (role.get("label", r), len(role[key]), MAX_FIRST))
        said.append("/%s for %s: %s" % (name, column, {"first": "a first command", "tick": "in My tools",
                                                         "none": "taken off"}[state]))
    return config, said


def write_lists(path, config):
    """Rewrite the default_skills, more_skills and everyone_skills lines of role-routing.yaml in place, keeping every
    comment and every other line as it is."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    flow = lambda items: "[%s]" % ", ".join(items)  # noqa: E731
    text = re.sub(r"(?m)^everyone_skills: \[[^\]]*\]", "everyone_skills: " + flow(config.get("everyone_skills") or []), text)
    for r, role in (config.get("roles") or {}).items():
        m = re.search(r"(?ms)^  %s:\n(.*?)(?=^  [a-z_]+:\n|^\S|\Z)" % re.escape(r), text)
        if not m:
            continue
        block = m.group(0)
        new = re.sub(r"(?m)^    default_skills: \[[^\]]*\]", "    default_skills: " + flow(role.get("default_skills") or []), block)
        if re.search(r"(?m)^    more_skills:", new):
            new = re.sub(r"(?m)^    more_skills: \[[^\]]*\]\n", ("    more_skills: %s\n" % flow(role["more_skills"]))
                         if role.get("more_skills") else "", new)
        elif role.get("more_skills"):
            new = re.sub(r"(?m)^(    default_skills: \[[^\]]*\]\n)", lambda x: x.group(1) + "    more_skills: %s\n" % flow(role["more_skills"]), new)
        text = text.replace(block, new, 1)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def unknown_names(root=ROOT, known=None, config=None):
    """Names in default_skills, more_skills or everyone_skills that are not installed skills."""
    known = known if known is not None else skills(root)
    config = config if config is not None else routing(root)
    named = set(config.get("everyone_skills") or [])
    for v in (config.get("roles") or {}).values():
        named |= set(v.get("default_skills") or []) | set(v.get("more_skills") or [])
    return sorted(named - set(known))


def for_roles(roles, root=ROOT, known=None, config=None):
    """One person's commands: their first ones, the rest for their roles, the ones for everyone, the pipelines with
    their stages, and every other command, so the page can show all of them without burying any."""
    known = known if known is not None else skills(root)
    config = config if config is not None else routing(root)
    table = config.get("roles") or {}
    seen = set()

    def take(names):
        got = []
        for n in names:
            if n in known and n not in seen:
                seen.add(n)
                got.append(known[n])
        return got

    first = take(n for r in roles for n in (table.get(r) or {}).get("default_skills") or [])
    more = take(n for r in roles for n in (table.get(r) or {}).get("more_skills") or [])
    everyone = take(config.get("everyone_skills") or [])
    home = homes(root, known, config)
    pipelines = {}
    for n in sorted(known):
        if home[n]["pipeline"]:
            pipelines.setdefault(home[n]["pipeline"], []).append(known[n])
    aliases = sorted((n, home[n]["alias_of"]) for n in known if home[n]["alias_of"])
    staged = {s["name"] for v in pipelines.values() for s in v}
    internal = [dict(known[n], why=home[n]["internal"]) for n in sorted(known)
                if home[n]["internal"] and n not in staged and not home[n]["alias_of"] and n not in seen]
    other = take(n for n in sorted(known) if n not in staged and not home[n]["alias_of"] and not home[n]["internal"])
    return {"first": first, "more": more, "everyone": everyone, "pipelines": pipelines, "aliases": aliases,
            "internal": internal, "other": other}


def person_roles(value, root=ROOT):
    with open(os.path.join(root, PEOPLE), encoding="utf-8") as fh:
        people = (yaml.safe_load(fh) or {}).get("people") or []
    want = re.sub(r"[^a-z ]", "", str(value).lower().replace(",", " ")).split()
    for p in people:
        name = re.sub(r"[^a-z ]", "", str(p.get("name", "")).lower().replace(",", " ")).split()
        if str(p.get("jira_user", "")).upper() == str(value).upper() or (want and sorted(want) == sorted(name)):
            return [p.get("primary_role")] + list(p.get("secondary_roles") or [])
    return []


def tip(roles, today=None, root=ROOT, known=None, config=None):
    """Today's command tip for someone with these roles: their role's commands and the ones for everyone, in turn,
    a different one each day."""
    got = for_roles(roles, root, known, config)
    pool = [s for s in got["first"] + got["more"] + got["everyone"] if s["name"] not in NO_TIP]
    if not pool:
        return None
    today = today or datetime.date.today()
    return pool[today.toordinal() % len(pool)]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    sub.add_parser("counts")
    a = sub.add_parser("apply")
    a.add_argument("--block", required=True)
    a.add_argument("--write", action="store_true")
    f = sub.add_parser("for")
    f.add_argument("--role", action="append", required=True)
    t = sub.add_parser("tip")
    t.add_argument("--person", required=True)
    args = ap.parse_args(argv)
    if args.cmd == "check":
        unknown = unknown_names()
        for n in unknown:
            print("%s names /%s, which is not an installed skill" % (ROUTING, n))
        for n in unhomed():
            print("not assigned to anyone yet: /%s" % n)
        return 1 if unknown else 0
    if args.cmd == "counts":
        print(counts())
        return 0
    if args.cmd == "apply":
        with open(args.block, encoding="utf-8") as fh:
            config, said = apply(parse_block(fh.read()), routing())
        print("\n".join(said))
        if args.write:
            write_lists(os.path.join(ROOT, ROUTING), config)
            print("written to %s" % ROUTING)
        else:
            print("preview only: nothing written (say approved, then run again with --write)")
        return 0
    if args.cmd == "for":
        got = for_roles(args.role)
        for key in ("first", "more", "everyone", "other"):
            print("%s: %s" % (key, ", ".join("/" + s["name"] for s in got[key])))
        for parent, stages in got["pipelines"].items():
            print("/%s runs: %s" % (parent, ", ".join("/" + s["name"] for s in stages)))
        return 0
    roles = person_roles(args.person)
    got = tip(roles)
    if got:
        print("Tip: /%s — %s" % (got["name"], got["what"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
