"""Feature 4 - Service catalog export: Backstage `catalog-info.yaml` per service and a CMDB-style CSV/JSON.

Only facts the scan supports are written. Owner is a team or the literal `unknown`. No URLs or hosts are emitted
(Backstage `links` are omitted on purpose: they would be hosts). Generated catalog files are proposals for people to review and commit.
"""
from __future__ import annotations

import csv
import io
import json
import re
from collections import defaultdict

import yaml

from ..facts import ev, make_fact
from . import graph, scorecards
from .common import Ctx, Result, csv_cell, header, md_cell, slug, team_of_repo

_LANG_PREF = ("java", "kotlin", "python", "typescript", "javascript", "go", "csharp", "ruby", "php", "rust", "scala")


def _lifecycle(flags: list[dict]) -> str:
    return "experimental" if any(f["rule"] in ("no_ci", "no_tests") for f in flags) else "production"


def _name(repo: str) -> str:
    n = re.sub(r"[^a-z0-9-_.]", "-", repo.lower()).strip("-_.")[:63]
    return n or "service"


def build_entities(ctx: Ctx) -> list[dict]:
    g = graph.compute(ctx)
    cards = scorecards.compute(ctx)
    out_adj, _ = graph.adjacency(g)
    entities = []
    for repo in ctx.repo_names:
        langs: dict[str, int] = defaultdict(int)
        for f in ctx.k("source_file"):
            if f["attrs"]["repo"] == repo:
                langs[f["attrs"]["language"]] += 1
        mods = [f["attrs"] for f in ctx.k("module") if f["attrs"].get("repo") == repo]
        apis = [f"{n['label']}" for n in g["nodes"] if n["type"] == "api" and n["id"].startswith(f"api:{repo}:")]
        deps_on = sorted({e["to"][4:] for e in out_adj.get(f"svc:{repo}", []) if e["type"] == "calls"})
        resources = sorted({g_["label"] for e in out_adj.get(f"svc:{repo}", []) for g_ in g["nodes"] if g_["id"] == e["to"] and g_["type"] in ("table", "topic")})
        envs = sorted({f["attrs"]["environment"] for f in ctx.k("config_entry") if f["attrs"].get("repo") == repo and f["attrs"].get("environment")})
        images = sorted({f["attrs"]["image"] for f in ctx.k("container_image") if f["attrs"].get("repo") == repo})
        team = team_of_repo(ctx.facts, repo)
        ver = next((m.get("version") for m in mods if m.get("version")), None)
        entities.append({"repo": repo, "name": _name(repo), "team": team, "languages": sorted(langs, key=lambda k: -langs[k]), "module_version": ver,
                         "apis": sorted(set(apis)), "calls": deps_on, "resources": resources[:50], "environments": envs, "images": images,
                         "score": scorecards.score(cards.get(repo, [])), "lifecycle": _lifecycle(cards.get(repo, [])),
                         "flags": [f["rule"] for f in cards.get(repo, [])]})
    return entities


def catalog_info(e: dict, ctx: Ctx) -> str:
    comp = {"apiVersion": "backstage.io/v1alpha1", "kind": "Component",
            "metadata": {"name": e["name"], "description": f"Discovered by EnvScribe from the `{e['repo']}` repository. Review before committing.",
                         "annotations": {"envscribe.io/run-id": ctx.run_id, "envscribe.io/score": str(e["score"])},
                         "tags": [t for t in e["languages"][:5] if re.fullmatch(r"[a-z0-9+#]{1,63}", t.lower())]},
            "spec": {"type": "service", "lifecycle": e["lifecycle"], "owner": f"group:default/{_name(e['team'])}" if e["team"] else "unknown"}}
    if e["apis"]:
        comp["spec"]["providesApis"] = [_name(a) for a in e["apis"]]
    if e["calls"]:
        comp["spec"]["dependsOn"] = [f"component:default/{_name(c)}" for c in e["calls"]]
    docs = [yaml.safe_dump(comp, sort_keys=False)]
    for a in e["apis"]:
        docs.append(yaml.safe_dump({"apiVersion": "backstage.io/v1alpha1", "kind": "API", "metadata": {"name": _name(a), "description": f"API `{a}` from `{e['repo']}`"},
                                    "spec": {"type": "openapi", "lifecycle": e["lifecycle"], "owner": comp["spec"]["owner"],
                                             "definition": "# definition is not embedded; see the contract file in the repository"}}, sort_keys=False))
    return "---\n".join(docs)


COLS = ["service", "team", "languages", "version", "apis", "calls_services", "tables_and_topics", "environments", "images", "score", "lifecycle", "risk_flags"]


def run(ctx: Ctx) -> Result:
    ents = build_entities(ctx)
    files = {}
    for e in ents:
        files[f"catalog/backstage/{slug(e['name'])}/catalog-info.yaml"] = catalog_info(e, ctx)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(COLS)
    for e in ents:
        w.writerow([csv_cell(x) for x in (e["repo"], e["team"] or "unknown", ";".join(e["languages"]), e["module_version"] or "", ";".join(e["apis"]),
                                           ";".join(e["calls"]), ";".join(e["resources"]), ";".join(e["environments"]), ";".join(e["images"]), e["score"],
                                           e["lifecycle"], ";".join(e["flags"]))])
    files["catalog/cmdb.csv"] = buf.getvalue()
    files["catalog/cmdb.json"] = json.dumps({"generated": ctx.collated_at, "services": ents}, indent=1)
    md = [header("Service catalog", ctx, "Owner is a team or `unknown`; individuals are never listed."),
          "| Service | Team | Languages | APIs | Calls | Score |\n|---|---|---|---|---|---|"]
    for e in ents:
        md.append(f"| [{e['repo']}](services/{e['repo']}.md) | {e['team'] or 'unknown'} | {md_cell(', '.join(e['languages'][:3]))} | {md_cell(', '.join(e['apis'][:3]))} | {md_cell(', '.join(e['calls'][:4]))} | {e['score']} |")
    md.append("\nFiles: `catalog/cmdb.csv`, `catalog/cmdb.json`, and one `catalog/backstage/<service>/catalog-info.yaml` per service. "
              "These are generated *proposals*: review owners and lifecycle before committing them to a repository.")
    files["catalog/index.md"] = "\n".join(md) + "\n"
    facts = [make_fact("catalog_entry", e["repo"], {"repo": e["repo"], "team": e["team"] or "unknown", "lifecycle": e["lifecycle"], "score": e["score"]}, "DERIVED",
                       [ev(f"{e['repo']}/", "catalog", f"{e['repo']} -> {e['name']}")], "catalog",
                       "assembled from scanned facts: languages, APIs, calls (graph), team (ownership), lifecycle (no_ci/no_tests => experimental)") for e in ents]
    return Result(files=files, facts=facts, index=["- [Service catalog](catalog/index.md) · `catalog/cmdb.csv` · Backstage `catalog-info.yaml` per service"],
                  coverage={"catalog": f"{len(ents)} services exported"})
