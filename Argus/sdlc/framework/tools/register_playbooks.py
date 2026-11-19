#!/usr/bin/env python3
"""Register the playbooks in playbooks/ in Devin Cloud, each as a !pb_<nn>_<name> macro.

A dry run by default: it lists what it would create, update or leave alone. --apply makes the
calls (GET, POST and PUT /v1/playbooks). Needs a Devin API key in DEVIN_API_KEY, from a service
user of your organization that may manage playbooks; DEVIN_API_BASE overrides https://api.devin.ai.
A playbook is matched to an existing one by its macro, so running it again only updates.
"""
import argparse
import glob
import json
import os
import re
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PLAYBOOKS = os.path.join(os.path.dirname(HERE), "playbooks")
API = os.environ.get("DEVIN_API_BASE", "https://api.devin.ai").rstrip("/")


def parse(path):
    """Title, macro and body of one playbook file; None if it has no "## Playbook Body"."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    body = re.search(r"^## Playbook Body[^\n]*\n(.*)\Z", text, re.M | re.S)
    if not body:
        return None
    name = os.path.splitext(os.path.basename(path))[0]
    title = re.search(r"^## Title[^\n]*\n+```\n(.+?)\n```", text, re.M | re.S)
    return {"file": os.path.basename(path),
            "title": title.group(1).strip() if title else name,
            "macro": "!" + re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_"),
            "body": body.group(1).strip() + "\n"}


def local(folder=PLAYBOOKS):
    return [p for p in (parse(f) for f in sorted(glob.glob(os.path.join(folder, "PB-*.md")))) if p]


def call(method, path, key, data=None):
    req = urllib.request.Request(API + path, method=method,
                                 data=None if data is None else json.dumps(data).encode("utf-8"),
                                 headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8") or "null")


def plan(books, remote):
    """(action, playbook, remote match) for each local playbook: create, update or same."""
    by_macro = {r.get("macro"): r for r in remote if r.get("macro")}
    out = []
    for b in books:
        r = by_macro.get(b["macro"])
        if not r:
            out.append(("create", b, None))
        elif r.get("title") == b["title"] and (r.get("body") or "").strip() == b["body"].strip():
            out.append(("same", b, r))
        else:
            out.append(("update", b, r))
    return out


def main(argv=None, api=call):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true", help="create and update the playbooks (default: dry run)")
    ap.add_argument("--folder", default=PLAYBOOKS, help="playbook folder (default: %(default)s)")
    args = ap.parse_args(argv)
    books = local(args.folder)
    key = os.environ.get("DEVIN_API_KEY", "")
    if not key:
        print("DEVIN_API_KEY is not set, so Devin Cloud was not read. %d playbooks to register:" % len(books))
        for b in books:
            print("  %-36s %s" % (b["macro"], b["title"]))
        return 2 if args.apply else 0
    remote = api("GET", "/v1/playbooks", key)
    remote = remote.get("items", []) if isinstance(remote, dict) else (remote or [])
    failed = 0
    for action, b, r in plan(books, remote):
        print("%-7s %-36s %s" % (action, b["macro"], b["title"]))
        if not args.apply or action == "same":
            continue
        data = {"title": b["title"], "body": b["body"], "macro": b["macro"]}
        try:
            if action == "create":
                api("POST", "/v1/playbooks", key, data)
            else:
                api("PUT", "/v1/playbooks/%s" % r["playbook_id"], key, data)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            failed += 1
            print("        failed: %s" % exc)
    if not args.apply:
        print("Dry run. Run again with --apply to make these changes.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
