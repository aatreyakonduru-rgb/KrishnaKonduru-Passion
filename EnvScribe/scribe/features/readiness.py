"""Feature 11 - Migration and cloud-readiness signals per service.

Signals are counted from facts and listed with evidence. The suggested path (rehost / replatform / refactor) is a transparent rule over those
signals, labelled as a suggestion for discussion, not an assessment. Anything the scan cannot see (state on local disk, licensing, data volume,
traffic, SLAs) is listed under "not assessed" rather than guessed.
"""
from __future__ import annotations

import json
from collections import defaultdict

from ..facts import ev, make_fact
from . import graph, scorecards
from .common import Ctx, Result, header, md_cell

LICENSED_DB = {"oracle", "db2", "sqlserver"}


def assess(ctx: Ctx, repo: str, g: dict, cards: dict) -> dict:
    out_adj, in_adj = graph.adjacency(g)
    sid = f"svc:{repo}"
    own = lambda kind: [f for f in ctx.k(kind) if f["attrs"].get("repo") == repo]
    files = own("source_file")
    loc = sum(f["attrs"].get("lines", 0) for f in files)
    langs = sorted({f["attrs"]["language"] for f in files})
    calls_out = sorted({e["to"][4:] for e in out_adj.get(sid, []) if e["type"] == "calls"})
    calls_in = sorted({e["from"][4:] for e in in_adj.get(sid, []) if e["type"] == "calls"})
    my_tables = {e["to"] for e in out_adj.get(sid, []) if e["to"].startswith("db:")}
    shared_tables = sorted(t[3:] for t in my_tables if len({e["from"] for e in in_adj.get(t, []) if e["from"] != sid and e["from"].startswith("svc:")}) >= 1)
    my_topics = {e["to"] for e in out_adj.get(sid, []) if e["to"].startswith("topic:")}
    shared_topics = sorted(t[6:] for t in my_topics if len({e["from"] for e in in_adj.get(t, []) if e["from"] != sid and e["from"].startswith("svc:")}) >= 1)
    engines = sorted({f["attrs"]["engine"] for f in own("db_connection")})
    flags = {f["rule"] for f in cards.get(repo, [])}
    containerized = bool(own("container_image")) or bool(own("k8s_resource"))
    envuse = len(own("env_var_use"))
    cfguse = len(own("config_key_use"))
    deps = len(own("dependency"))
    signals = {
        "containerized": containerized, "kubernetes_or_helm": bool(own("k8s_resource") or own("helm_chart")), "infra_as_code": bool(own("iac_resource")),
        "ci_pipeline": bool(own("pipeline_stage")), "externalized_config": envuse + cfguse > 0, "env_specific_config": any(f["attrs"].get("environment") for f in own("config_entry")),
        "licensed_database": sorted(set(engines) & LICENSED_DB), "eol_runtime": "eol_runtime" in flags, "hardcoded_secret": "hardcoded_secret" in flags,
        "health_check": "no_health" not in flags}
    coupling = len(calls_out) + len(calls_in) + 2 * len(shared_tables) + len(shared_topics)
    complexity = {"files": len(files), "lines": loc, "languages": langs, "dependencies": deps, "endpoints": len(own("endpoint")),
                  "tables": len(my_tables), "topics": len(my_topics)}
    # transparent rule
    blockers, rea = [], 0
    if signals["containerized"]:
        rea += 25
    if signals["ci_pipeline"]:
        rea += 15
    if signals["externalized_config"]:
        rea += 15
    if signals["health_check"]:
        rea += 10
    if signals["kubernetes_or_helm"] or signals["infra_as_code"]:
        rea += 10
    if not signals["hardcoded_secret"]:
        rea += 10
    if not signals["eol_runtime"]:
        rea += 10
    if not signals["licensed_database"]:
        rea += 5
    if signals["eol_runtime"]:
        blockers.append("runtime past end of support")
    if signals["hardcoded_secret"]:
        blockers.append("hardcoded secret(s) must be moved out first")
    if shared_tables:
        blockers.append(f"shares {len(shared_tables)} table(s) with other services")
    if signals["licensed_database"]:
        blockers.append("licensed database engine: " + ", ".join(signals["licensed_database"]))
    if signals["eol_runtime"] or len(shared_tables) >= 2 or coupling >= 8:
        path, why = "refactor", "end-of-support runtime, several shared tables or high coupling"
    elif not containerized or signals["licensed_database"] or not signals["externalized_config"]:
        path, why = "replatform", "not containerized, licensed database, or no externalized configuration seen"
    else:
        path, why = "rehost", "containerized, no end-of-support runtime and no shared tables seen"
    cite_f = (own("container_image") or own("source_file") or [None])[0]
    return {"repo": repo, "readiness": min(100, rea), "path": path, "why": why, "blockers": blockers, "coupling": coupling,
            "calls_out": calls_out, "calls_in": calls_in, "shared_tables": shared_tables, "shared_topics": shared_topics,
            "signals": signals, "complexity": complexity, "evidence": cite_f["evidence"][:1] if cite_f else [ev(f"{repo}/", "repository scan")]}


def run(ctx: Ctx) -> Result:
    g = graph.compute(ctx)
    cards = scorecards.compute(ctx)
    rows = [assess(ctx, r, g, cards) for r in ctx.repo_names]
    facts = [make_fact("readiness", r["repo"], {"repo": r["repo"], "readiness_score": r["readiness"], "suggested_path": r["path"], "coupling": r["coupling"], "blockers": r["blockers"]},
                       "DERIVED", r["evidence"], "readiness",
                       f"signal rule: {r['why']}; readiness = points for containerized, CI, externalized config, health check, K8s/IaC, no hardcoded secret, supported runtime, unlicensed DB")
             for r in rows]
    md = [header("Migration and cloud-readiness signals", ctx, "A starting point for discussion. Suggested paths come from the listed rule; they are not an assessment."),
          "| Service | Readiness | Suggested path | Coupling | Files | Lines | Blockers |\n|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda x: (-x["readiness"], x["repo"])):
        c = r["complexity"]
        md.append(f"| [{r['repo']}](services/{r['repo']}.md) | {r['readiness']} | **{r['path']}** | {r['coupling']} | {c['files']} | {c['lines']} | {md_cell('; '.join(r['blockers']) or '-')} |")
    if not rows:
        md.append("| _no services_ | | | | | | |")
    for r in rows:
        s = r["signals"]
        md.append(f"\n## {r['repo']}\n\nSuggested: **{r['path']}** ({r['why']})\n\n- Containerized: {s['containerized']} · Kubernetes/Helm: {s['kubernetes_or_helm']} · IaC: {s['infra_as_code']} · CI: {s['ci_pipeline']}\n"
                  f"- Externalized configuration seen: {s['externalized_config']} · per-environment config: {s['env_specific_config']} · health check: {s['health_check']}\n"
                  f"- Calls out to: {', '.join(r['calls_out']) or 'none found'} · called by: {', '.join(r['calls_in']) or 'none found'}\n"
                  f"- Tables shared with other services: {', '.join(r['shared_tables']) or 'none found'} · topics shared: {', '.join(r['shared_topics']) or 'none found'}\n"
                  f"- Complexity: {r['complexity']['files']} files, {r['complexity']['lines']} lines, {r['complexity']['dependencies']} dependencies, {r['complexity']['endpoints']} endpoints, languages: {', '.join(r['complexity']['languages']) or '-'}")
    md.append("\n## Rule\n\n- **refactor**: runtime past end of support, or 2+ tables shared with other services, or coupling score 8+ (calls + 2 × shared tables + shared topics).\n"
              "- **replatform**: not containerized, a licensed database engine (Oracle, Db2, SQL Server), or no externalized configuration seen.\n- **rehost**: none of the above.\n"
              "\n## Not assessed\n\nLocal-disk state, data volumes, traffic and SLAs, licensing terms, network and compliance constraints, team skills. These are not visible to a static scan.")
    return Result(files={"readiness/index.md": "\n".join(md) + "\n", "readiness/readiness.json": json.dumps(rows, indent=1, default=list)},
                  facts=facts, index=["- [Migration and cloud readiness](readiness/index.md)"],
                  coverage={"readiness": f"{len(rows)} services; " + ", ".join(f"{k} {v}" for k, v in sorted({p: sum(1 for r in rows if r['path'] == p) for p in ('rehost', 'replatform', 'refactor')}.items()))})
