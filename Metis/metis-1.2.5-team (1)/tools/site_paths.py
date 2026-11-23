"""Where the dashboard, gallery, lineage and index scripts find things: from the KB's profile, never from a product name.

    import site_paths
    S = site_paths.load()          # reads METIS_KB (the KB folder) and <KB>/.metis/kb-profile.yaml
    S.work, S.kb, S.repos, S.logo, S.name, S.org, S.title, S.primary, S.viz

Folders: METIS_KB is required (the KB folder). METIS_WORK (scratch, default ~/metis-work), METIS_REPOS (default
sources.workspace_root from the profile, else ~/repos) and METIS_LOGO (default viz.logo) override.
Everything team-specific lives under `viz:` in the profile (see templates/kb-profile.yaml): title, logo, colours,
source link, business areas, database folders, catalogue sets, lineage zones. An empty value turns that part off; a
script never falls back to another team's value.
"""
import os
import re
import subprocess

import yaml

DEFAULT_PRIMARY = "#7c3aed"


def read_yaml(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except OSError:
        return {}


class Site:
    def __init__(self, kb, env=None):
        env = os.environ if env is None else env
        self.kb = os.path.abspath(kb)
        self.profile = read_yaml(os.path.join(self.kb, ".metis", "kb-profile.yaml"))
        self.viz = self.profile.get("viz") or {}
        product = self.profile.get("product") or {}
        self.name = product.get("name") or os.path.basename(self.kb)
        self.short = product.get("short_name") or self.name
        self.org = self.viz.get("org_name") or ""
        self.title = self.viz.get("title") or "Mētis - Knowledgebase Dashboard"
        self.primary = self.viz.get("primary_color") or DEFAULT_PRIMARY
        self.palette = {str(k).lower(): str(v) for k, v in (self.viz.get("palette") or {}).items()}
        self.work = env.get("METIS_WORK") or os.path.expanduser("~/metis-work")
        root = (self.profile.get("sources") or {}).get("workspace_root")
        self.repos = env.get("METIS_REPOS") or (os.path.expanduser(str(root)) if root else os.path.expanduser("~/repos"))
        logo = env.get("METIS_LOGO") or self.viz.get("logo") or ""
        if logo and not os.path.isabs(logo):
            logo = os.path.join(self.kb, logo)
        self.logo = logo if logo and os.path.isfile(logo) else None

    def recolor(self, text):
        """Apply the team's `viz.palette` (stock colour -> theirs) to a page. No palette, no change."""
        if not self.palette:
            return text
        return re.sub(r"#[0-9a-fA-F]{6}\b", lambda m: self.palette.get(m.group(0).lower(), m.group(0)), text)

    def list_of(self, key):
        v = self.viz.get(key)
        return v if isinstance(v, list) else []

    def source_link(self):
        """(remote_regex, url_template), either None when the team has not set a link to its code host."""
        s = self.viz.get("source_link") or {}
        return (s.get("remote_regex") or None), (s.get("url") or None)

    def projects(self):
        """{repo folder: project} read from each repo's git remote with source_link.remote_regex (group 1 = project)."""
        rx, _ = self.source_link()
        out = {}
        if not rx or not os.path.isdir(self.repos):
            return out
        pat = re.compile(rx)
        for r in sorted(os.listdir(self.repos)):
            try:
                url = subprocess.run(["git", "-C", os.path.join(self.repos, r), "remote", "get-url", "origin"],
                                     capture_output=True, text=True, timeout=30).stdout.strip()
            except (OSError, subprocess.SubprocessError):
                continue
            m = pat.search(url)
            if m:
                out[r] = m.group(1)
        return out

    def link(self, repo, path, line, projects):
        """URL of a file (and line) in the code host, or "" when no link is configured or the repo has no project."""
        _, tpl = self.source_link()
        if not tpl or repo not in projects:
            return ""
        return tpl.format(project=projects[repo], repo=repo, path=path, line=line if line else "")


def load(kb=None, env=None):
    env = os.environ if env is None else env
    kb = kb or env.get("METIS_KB")
    if not kb:
        raise SystemExit("set METIS_KB to the KB folder (the one that holds .metis/kb-profile.yaml)")
    return Site(kb, env)
