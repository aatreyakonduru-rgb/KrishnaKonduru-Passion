#!/usr/bin/env python3
"""Where the team's documents live, read from the team settings file.

The `confluence` and `docs` sections of .devin/rules/sdlc-profile.json (or the file SDLC_PROFILE points
to) hold the Confluence host, space and pages (the Devin user manual, the roster) and the repo paths
of the documents people are pointed at (Argus manual, presentation, architecture). Tools build
their links from here, so a moved or renamed page is one edit in that file. Run it to list them:

    python3 sdlc/framework/tools/team_links.py
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class LinksError(Exception):
    pass


def profile_path():
    if os.environ.get("SDLC_PROFILE"):
        return os.environ["SDLC_PROFILE"]
    base = os.path.join(ROOT, ".devin", "rules", "sdlc-profile")
    return base + ".yaml" if os.path.exists(base + ".yaml") else base + ".json"


def load(path=None):
    path = path or profile_path()
    try:
        with open(path, encoding="utf-8") as fh:
            if path.endswith((".yaml", ".yml")):
                import yaml
                return yaml.safe_load(fh) or {}
            return json.load(fh)
    except FileNotFoundError:
        raise LinksError("no team settings at %s: copy sdlc/kb/examples/acme/sdlc-profile.json there" % path)
    except ValueError as exc:
        raise LinksError("%s cannot be read: %s" % (path, exc))


def sandbox_url():
    """The sandbox server's address (tools/sandbox) when SDLC_SANDBOX_URL is set; Jira and Confluence go there."""
    return (os.environ.get("SDLC_SANDBOX_URL") or "").rstrip("/")


def confluence(data=None):
    """{host, space, token_env, pages: {name: {id, title}}}; every one must be filled in."""
    data = load() if data is None else data
    c = data.get("confluence") or {}
    for key in ("host", "space", "token_env", "pages"):
        if not c.get(key):
            raise LinksError("the team settings have no confluence.%s" % key)
    for name, page in c["pages"].items():
        if not (isinstance(page, dict) and page.get("id") and page.get("title")):
            raise LinksError("confluence.pages.%s needs an id and a title" % name)
    return dict(c, host=(sandbox_url() or c["host"]).rstrip("/"))


def page_url(name, data=None):
    c = confluence(data)
    if name not in c["pages"]:
        raise LinksError("the team settings have no confluence.pages.%s" % name)
    return "%s/pages/viewpage.action?pageId=%s" % (c["host"], c["pages"][name]["id"])


STATUS_SLOT = re.compile(r"\{statuses\.(\w+)\}")


def fill_statuses(jql, data=None):
    """Turn each {statuses.<queue>} in a JQL string into the quoted list under jira.statuses.<queue>."""
    if "{statuses." not in jql:
        return jql
    data = load() if data is None else data
    statuses = (data.get("jira") or {}).get("statuses") or {}

    def one(m):
        names = statuses.get(m.group(1))
        if not names:
            raise LinksError("the team settings have no jira.statuses.%s" % m.group(1))
        return ", ".join('"%s"' % str(n).replace('"', '\\"') for n in names)
    return STATUS_SLOT.sub(one, jql)


def docs(data=None):
    """{name: repo-relative path} for the documents in the `docs` section."""
    data = load() if data is None else data
    return {k: v for k, v in (data.get("docs") or {}).items() if not k.startswith("_")}


def main():
    try:
        data = load()
        c = confluence(data)
        print("Confluence pages (space %s):" % c["space"])
        for name, page in sorted(c["pages"].items()):
            print("  %-18s %s  %s" % (name, page["title"], page_url(name, data)))
        print("Documents in the repo:")
        for name, path in sorted(docs(data).items()):
            flag = "" if os.path.exists(os.path.join(ROOT, path)) else "  (MISSING)"
            print("  %-18s %s%s" % (name, path, flag))
    except LinksError as exc:
        sys.exit("team links: %s" % exc)


if __name__ == "__main__":
    main()
