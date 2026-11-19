#!/usr/bin/env python3
"""The Acme Claims delivery-team sheet: checks it, finds a team, and writes the readable copies.

Source of truth: docs/knowledge-base/SHARED/delivery-teams.yaml

    delivery_teams.py                 check the sheet and write ACME_DELIVERY_TEAMS.md and .html beside it
    delivery_teams.py --check         check only
    delivery_teams.py find <name>     the team for a key, a name or an IT Team value
"""
import argparse
import html
import os
import re
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import artifact_kit  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SHEET = os.path.join(ROOT, "docs", "knowledge-base", "SHARED", "delivery-teams.yaml")
REQUIRED = ("key", "name", "it_team", "board")


def load(path=SHEET):
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def problems(data):
    found, seen = [], set()
    for i, team in enumerate(data.get("teams") or []):
        label = team.get("key") or "team %d" % (i + 1)
        for field in REQUIRED:
            if not team.get(field):
                found.append("%s: no %s" % (label, field))
        if team.get("key") in seen:
            found.append("%s: key used twice" % label)
        seen.add(team.get("key"))
    if not data.get("teams"):
        found.append("no teams")
    return found


def norm(text):
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


def find(data, name):
    """The team whose key, name, other names or IT Team value matches."""
    want = norm(name)
    for team in data.get("teams") or []:
        names = [team.get("key"), team.get("name"), team.get("it_team")] + list(team.get("also_called") or [])
        if want and want in [norm(n) for n in names if n]:
            return team
    return None


def _text(value):
    if isinstance(value, dict):
        return "; ".join("%s: %s" % (k.replace("_", " "), _text(v)) for k, v in value.items())
    if isinstance(value, list):
        return "; ".join(_text(v) for v in value)
    return "" if value is None else str(value)


def sections(data):
    """(heading, [(label, value or list)]) per team, in sheet order."""
    out = []
    for team in data.get("teams") or []:
        rows = []
        for field, value in team.items():
            if field in ("key", "name") or value in (None, "", [], {}):
                continue
            rows.append((_label(field), value))
        out.append((team.get("name") or team.get("key"), rows))
    return out


def markdown(data):
    lines = ["# Acme Claims delivery teams", "", _text(data.get("about")).strip(), "",
             "_Generated from `docs/knowledge-base/SHARED/delivery-teams.yaml` (updated %s). "
             "Edit the YAML, then run `python3 sdlc/framework/tools/delivery_teams.py`._" % data.get("updated", ""), ""]
    for field in ("program_contacts", "ceremonies"):
        if data.get(field):
            lines += ["## " + field.replace("_", " ").capitalize(), ""]
            lines += ["- " + _text(v) for v in (data[field] if isinstance(data[field], list) else [data[field]])] + [""]
    for heading, rows in sections(data):
        lines += ["## " + heading, ""]
        for label, value in rows:
            if isinstance(value, list):
                lines += ["**%s**" % label, ""] + ["- " + _text(v) for v in value] + [""]
            else:
                lines += ["**%s:** %s" % (label, _text(value)), ""]
    return "\n".join(lines).rstrip() + "\n"


def _label(field):
    return "IT team" if field == "it_team" else field.replace("_", " ").capitalize()


def _cell(value):
    e = html.escape
    if isinstance(value, list) and value and all(isinstance(v, dict) for v in value):
        cols = []
        for v in value:
            cols += [k for k in v if k not in cols]
        head = "".join("<th scope=\"col\">%s</th>" % e(_label(k)) for k in cols)
        rows = "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % e(_text(v.get(k))) for k in cols) for v in value)
        return '<table class="a-table"><thead><tr>%s</tr></thead><tbody>%s</tbody></table>' % (head, rows)
    if isinstance(value, list):
        return "<ul>%s</ul>" % "".join("<li>%s</li>" % e(_text(v)) for v in value)
    return e(_text(value))


def page(data):
    e = html.escape
    body = ["<p>%s</p>" % e(_text(data.get("about")).strip())]
    for heading, rows in sections(data):
        body.append('<h2>%s</h2><table class="a-table teams"><tbody>' % e(str(heading)))
        for label, value in rows:
            body.append('<tr><th scope="row">%s</th><td>%s</td></tr>' % (e(label), _cell(value)))
        body.append("</tbody></table>")
    css = (".teams{width:100%}.teams>tbody>tr>th{width:20%;text-align:left;vertical-align:top}"
           ".teams td{vertical-align:top}.teams td .a-table{width:100%;margin:0}ul{margin:0;padding-left:18px}"
           "h2{margin-top:28px}")
    return artifact_kit.render_page(
        "Acme Claims delivery teams", "".join(body),
        subtitle=e("as of %s" % data.get("updated", "")),
        footnote=e("Source: docs/knowledge-base/SHARED/delivery-teams.yaml"),
        extra_css=css)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sheet", default=SHEET)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("find", nargs="*")
    args = ap.parse_args(argv)
    data = load(args.sheet)
    if args.find:
        if args.find[0] != "find":
            ap.error("unknown command %s" % args.find[0])
        team = find(data, " ".join(args.find[1:]))
        if not team:
            print("no team matches %r" % " ".join(args.find[1:]), file=sys.stderr)
            return 1
        print(yaml.safe_dump(team, sort_keys=False, allow_unicode=True).rstrip())
        return 0
    found = problems(data)
    for p in found:
        print("delivery-teams: " + p, file=sys.stderr)
    if found or args.check:
        return 1 if found else 0
    base = os.path.join(os.path.dirname(args.sheet), "ACME_DELIVERY_TEAMS")
    for ext, text in ((".md", markdown(data)), (".html", page(data))):
        with open(base + ext, "w", encoding="utf-8") as fh:
            fh.write(text)
        print("wrote " + os.path.relpath(base + ext, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
