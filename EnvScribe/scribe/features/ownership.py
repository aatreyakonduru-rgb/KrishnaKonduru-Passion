"""Feature 15 - Ownership, teams only.

Reads CODEOWNERS and catalog-info.yaml. Only team names are reported. An owner that is an e-mail address, a bare
user handle, or ambiguous is never written anywhere; only the count of omitted entries is kept.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import yaml

from ..facts import ev, make_fact
from .common import Ctx, Result, header, team_of

CODEOWNERS_PATHS = ("CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS", ".bitbucket/CODEOWNERS", ".gitlab/CODEOWNERS")


def collect(repos: dict[str, str], exclude: list[str]) -> tuple[list[dict], dict[str, int]]:
    """Return ([{repo, pattern, owner(team), source, line}], {repo: omitted_count})."""
    rows: list[dict] = []
    omitted: dict[str, int] = defaultdict(int)
    for name, root in sorted(repos.items()):
        for rel in CODEOWNERS_PATHS:
            if any(x and x in rel for x in exclude):
                continue
            p = Path(root) / rel
            if not p.is_file():
                continue
            for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                parts = line.split("#")[0].split()
                for o in parts[1:] if len(parts) >= 2 else []:
                    t = team_of(o)
                    if t:
                        rows.append({"repo": name, "pattern": parts[0], "owner": t, "source": f"{name}/{rel}", "line": i})
                    else:
                        omitted[name] += 1
        cat = Path(root) / "catalog-info.yaml"
        if cat.is_file():
            try:
                doc = yaml.safe_load(cat.read_text(encoding="utf-8", errors="replace")) or {}
                owner = str(((doc.get("spec") or {}).get("owner")) or "")
            except yaml.YAMLError:
                owner = ""
            if owner:
                if owner.lower().startswith("user:"):
                    omitted[name] += 1
                else:
                    t = team_of("@" + owner.split(":", 1)[-1].split("/")[-1]) or (owner.split("/")[-1] if owner.lower().startswith("group:") else None)
                    if t:
                        rows.append({"repo": name, "pattern": "*", "owner": t, "source": f"{name}/catalog-info.yaml", "line": 0})
                    else:
                        omitted[name] += 1
    return rows, dict(omitted)


def run(ctx: Ctx) -> Result:
    rows, omitted = collect(ctx.repos, ctx.settings.exclude_sources)
    facts = [make_fact("ownership", f"{r['repo']}:{r['pattern']}:{r['owner']}", {"repo": r["repo"], "pattern": r["pattern"], "team": r["owner"]},
                       "OBSERVED", [ev(r["source"], f"L{r['line']}" if r["line"] else "spec.owner", f"{r['pattern']} {r['owner']}")], "ownership")
             for r in rows]
    by_team: dict[str, set] = defaultdict(set)
    by_repo: dict[str, set] = defaultdict(set)
    for r in rows:
        by_team[r["owner"]].add(r["repo"])
        by_repo[r["repo"]].add(r["owner"])
    md = [header("Ownership (teams only)", ctx, "Individuals are never reported; entries that are not clearly a team are omitted and counted."),
          "## By service\n"]
    for repo in ctx.repo_names:
        teams = sorted(by_repo.get(repo, []))
        md.append(f"- `{repo}`: " + (", ".join(f"`{t}`" for t in teams) if teams else "UNKNOWN: no team owner found"))
    md.append("\n## By team\n")
    md += [f"- `{t}`: " + ", ".join(f"`{r}`" for r in sorted(rs)) for t, rs in sorted(by_team.items())] or ["- none"]
    md.append("\n## Path patterns (as stated in CODEOWNERS)\n")
    md += [f"- `{r['pattern']}` → `{r['owner']}` ({r['repo']})" for r in rows[:500]] or ["- none"]
    n_omit = sum(omitted.values())
    md.append(f"\n## Omitted by policy\n\n{n_omit} owner entr{'y' if n_omit == 1 else 'ies'} omitted because they are individuals or could not be confirmed as a team.")
    return Result(files={"ownership/index.md": "\n".join(md) + "\n"}, facts=facts,
                  index=["- [Ownership (teams only)](ownership/index.md)"],
                  coverage={"ownership": f"{len(rows)} team entries; {n_omit} individual/ambiguous entries omitted by policy"})
