#!/usr/bin/env python3
"""Argus settings per person, for the dashboard's Argus config tab.

Today it holds how Test on my PC runs (test_on_pc in .devin/rules/workbench-settings.yaml): Local Hands from the
person's Devin Cloud Argus, Devin Local on the PC, the Devin Cloud VM, or off. A person without a row gets the
team default. The tab turns changed choices into a SDLC-DASHBOARD-WORKBENCH-CONFIG block; this script shows the
change and, after approved, writes workbench-settings.yaml for a reviewed pull request.

  python3 workbench_config.py grid
  python3 workbench_config.py apply --block <file> [--write]
"""
import argparse
import copy
import os
import re
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SETTINGS = os.path.join(ROOT, ".devin", "rules", "workbench-settings.yaml")
PEOPLE = os.path.join(ROOT, ".devin", "rules", "people.yaml")
BLOCK = "SDLC-DASHBOARD-WORKBENCH-CONFIG v1"
MODES = ("local_hands", "devin_local", "cloud_vm", "off")
LABELS = {"local_hands": "Local Hands from Devin Cloud", "devin_local": "Devin Local on the PC",
          "cloud_vm": "Devin Cloud VM", "off": "Off"}
FALLBACK = "devin_local"
DEFAULT = "default"


def load(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except OSError:
        return {}


def default_mode(settings):
    mode = ((settings.get("default") or {}).get("test_on_pc") or FALLBACK)
    return mode if mode in MODES else FALLBACK


def mode_for(who, settings=None, people=None):
    """The person's test_on_pc: their row, else the team default. `who` is a Jira user, e-mail or Devin user id."""
    settings = settings if settings is not None else load(SETTINGS)
    people = people if people is not None else load(PEOPLE)
    w = str(who or "").strip().lower()
    user = ""
    for p in people.get("people") or []:
        if w and w in (str(p.get("jira_user") or "").lower(), str(p.get("email") or "").lower(),
                       str(p.get("devin_user_id") or "").lower()):
            user = str(p.get("jira_user") or "")
            break
    row = {str(k).upper(): v for k, v in (settings.get("people") or {}).items()}.get(user.upper()) or {}
    mode = row.get("test_on_pc")
    return mode if mode in MODES else default_mode(settings)


def grid(settings=None, people=None):
    """(default, rows): the team default, and per roster person their own choice ('' = the default) and what applies."""
    settings = settings if settings is not None else load(SETTINGS)
    people = people if people is not None else load(PEOPLE)
    own = {str(k).upper(): (v or {}).get("test_on_pc", "") for k, v in (settings.get("people") or {}).items()}
    dflt = default_mode(settings)
    rows = []
    for p in people.get("people") or []:
        user = str(p.get("jira_user") or "")
        mine = own.get(user.upper(), "")
        rows.append({"jira_user": user, "name": p.get("name") or "", "own": mine if mine in MODES else "",
                     "applies": mine if mine in MODES else dflt})
    return dflt, rows


def parse_block(text):
    if BLOCK not in text:
        raise ValueError("no %s block" % BLOCK)
    out = []
    for line in text[text.index(BLOCK):].splitlines()[1:]:
        if line.strip() == "END":
            break
        m = re.match(r"^- person: (\S+) \| test_on_pc: ([a-z_]+)\s*$", line.strip())
        if m:
            out.append(m.groups())
        elif line.strip():
            raise ValueError("not understood: %r" % line)
    return out


def apply(changes, settings, people):
    """Settings with the changes made, and a line per change. `default` as the person sets the team default;
    `default` as the mode takes the person's own row off so the team default applies."""
    settings = copy.deepcopy(settings or {})
    rows = settings.setdefault("people", {}) or {}
    settings["people"] = rows
    by_user = {str(p.get("jira_user") or "").upper(): p for p in people.get("people") or []}
    said = []
    for user, mode in changes:
        if mode not in MODES + (DEFAULT,):
            raise ValueError("%s: %r is not one of %s" % (user, mode, ", ".join(MODES)))
        if user == DEFAULT:
            if mode == DEFAULT:
                raise ValueError("the team default needs a real choice")
            settings.setdefault("default", {})["test_on_pc"] = mode
            said.append("Team default: Test on my PC is %s" % LABELS[mode])
            continue
        p = by_user.get(user.upper())
        if not p:
            raise ValueError("%s is not on the roster (.devin/rules/people.yaml)" % user)
        key = str(p.get("jira_user"))
        if mode == DEFAULT:
            rows.pop(key, None)
            said.append("%s: uses the team default (%s)" % (p.get("name"), LABELS[default_mode(settings)]))
        else:
            rows[key] = {"test_on_pc": mode}
            said.append("%s: Test on my PC is %s" % (p.get("name"), LABELS[mode]))
    return settings, said


def write(path, settings):
    """Rewrite the settings below the header comment, which is kept as it is."""
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        text = ""
    header = "".join(line for line in text.splitlines(True) if line.startswith("#"))
    body = {"default": {"test_on_pc": default_mode(settings)},
            "people": {k: v for k, v in sorted((settings.get("people") or {}).items())}}
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(header + yaml.safe_dump(body, sort_keys=False, default_flow_style=False).replace("people: {}\n", "people: {}\n"))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("grid")
    a = sub.add_parser("apply")
    a.add_argument("--block", required=True)
    a.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd == "grid":
        dflt, rows = grid()
        print("team default: %s" % dflt)
        for r in rows:
            print("%s %s: %s%s" % (r["jira_user"], r["name"], r["applies"], "" if r["own"] else " (default)"))
        return 0
    with open(args.block, encoding="utf-8") as fh:
        settings, said = apply(parse_block(fh.read()), load(SETTINGS), load(PEOPLE))
    print("\n".join(said) or "no change")
    if args.write:
        write(SETTINGS, settings)
        print("written to .devin/rules/workbench-settings.yaml")
    else:
        print("preview only: nothing written (say approved, then run again with --write)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
