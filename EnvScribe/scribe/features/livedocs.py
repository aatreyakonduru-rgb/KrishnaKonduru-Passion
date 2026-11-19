"""Feature 6 - Generated living docs: per-service architecture page, runbook skeleton, and ADR drafts.

Every statement is assembled from facts and carries its citation. Sections that cannot be filled say UNKNOWN and list what to supply.
ADR drafts record decisions the code already embodies (the "decision" is what is observed; context, consequences and owner approval are left for people).
Runbook skeletons contain only observed commands, ports, health paths and config names; steps that need operator knowledge are marked TO CONFIRM.
"""
from __future__ import annotations

from collections import defaultdict

from . import graph, scorecards
from .common import Ctx, Result, cite, header, md_cell, slug, team_of_repo

ADR_SIGNALS = [  # (id, title, predicate over repo facts -> list of facts)
    ("framework", "Application framework", lambda f: f["kind"] == "dependency" and any(k in f["subject"].lower() for k in ("spring-boot", "spring-web", "express", "fastapi", "flask", "django", "aspnet", "quarkus", "micronaut", "gin-gonic", "nestjs"))),
    ("database", "Database engine", lambda f: f["kind"] == "db_connection"),
    ("messaging", "Messaging platform", lambda f: f["kind"] == "messaging_reference"),
    ("packaging", "Packaging and runtime base image", lambda f: f["kind"] == "container_image"),
    ("orchestration", "Deployment target", lambda f: f["kind"] in ("k8s_resource", "helm_chart", "service_definition")),
    ("pipeline", "CI/CD system", lambda f: f["kind"] == "pipeline_stage"),
    ("api-style", "API style and contract", lambda f: f["kind"] == "api_service"),
    ("auth", "API authentication scheme", lambda f: f["kind"] == "api_auth"),
]


def _bullets(facts, fmt, limit=40):
    seen, out = set(), []
    for f in facts:
        line = fmt(f)
        if line not in seen:
            seen.add(line)
            out.append(f"- {line}")
    return out[:limit] + ([f"- … {len(out) - limit} more in facts/all-facts.jsonl"] if len(out) > limit else [])


def architecture_page(ctx: Ctx, repo: str, g: dict) -> str:
    own = lambda kind: [f for f in ctx.k(kind) if f["attrs"].get("repo") == repo]
    nodes, edges = graph.neighborhood(g, repo)
    team = team_of_repo(ctx.facts, repo)
    langs = defaultdict(int)
    for f in own("source_file"):
        langs[f["attrs"]["language"]] += 1
    p = [header(f"Architecture: {repo}", ctx, "Generated; do not edit by hand. Re-run EnvScribe to refresh."),
         f"**Team owner:** {team or 'UNKNOWN: no CODEOWNERS or catalog-info team found'}  \n"
         f"**Languages:** {', '.join(f'{a} ({b})' for a, b in sorted(langs.items(), key=lambda x: -x[1])) or 'UNKNOWN'}  \n"
         f"**Scorecard:** see [scorecard](../../scorecards/services/{repo}.md)\n", "## Context diagram\n"]
    if len(nodes) > 1:
        p.append(f"```mermaid\n{graph.mermaid_flow(nodes, edges)}\n```\n")
    else:
        p.append("UNKNOWN: no relationships to other services, tables, topics or images were found for this service.\n")
    p.append("## Interfaces\n")
    p += _bullets(own("api_operation"), lambda f: f"`{f['subject']}` - {cite(f)}") or ["- UNKNOWN: no API contract operations"]
    p.append("\n### Endpoints seen in code\n")
    p += _bullets(own("endpoint"), lambda f: f"`{f['subject']}` ({f['attrs']['framework']}) - {cite(f)}") or ["- none found"]
    p.append("\n## Data\n")
    p += _bullets(ctx.k("sql_access") and [f for f in ctx.k("sql_access") if f["attrs"]["repo"] == repo], lambda f: f"{f['attrs']['operation']} `{f['attrs']['table']}` - {cite(f)}") or ["- none found by SQL parsing"]
    p.append("\n### Database connections (engine only)\n")
    p += _bullets(own("db_connection"), lambda f: f"`{f['attrs']['engine']}` env {f['attrs'].get('environment') or 'n/a'} - {cite(f)}") or ["- none found"]
    p.append("\n## Messaging\n")
    p += _bullets(own("messaging_reference"), lambda f: f"`{f['attrs']['topic']}` - {cite(f)}") or ["- none found"]
    p.append("\n## Build and dependencies\n")
    p += _bullets(own("module"), lambda f: f"`{f['subject']}` v{f['attrs'].get('version') or '?'} - {cite(f)}") or ["- none found"]
    p.append(f"\n{len(own('dependency'))} declared dependencies; see [SBOM](../../sbom/index.md).\n")
    p.append("## Deployment\n")
    dep = own("container_image") + own("k8s_resource") + own("helm_chart") + own("service_definition") + own("pipeline_stage") + own("iac_resource")
    p += _bullets(dep, lambda f: f"{f['kind']} `{md_cell(f['subject'])}` - {cite(f)}") or ["- UNKNOWN: no deployment artifacts found"]
    envs = sorted({f["attrs"]["environment"] for f in own("config_entry") if f["attrs"].get("environment")})
    p.append(f"\n## Environments\n\nConfig found for: {', '.join(envs) or 'UNKNOWN'}. See [environment drift](../../drift/environments.md).\n")
    return "\n".join(p) + "\n"


def runbook_page(ctx: Ctx, repo: str) -> str:
    own = lambda kind: [f for f in ctx.k(kind) if f["attrs"].get("repo") == repo]
    health = [f for f in own("endpoint") + own("api_operation") if any(k in f["attrs"].get("path", "").lower() for k in ("health", "ready", "live", "ping", "status"))]
    p = [header(f"Runbook skeleton: {repo}", ctx, "Observed facts only. Items marked TO CONFIRM need an operator; they are not guessed."),
         "## 1. What it is\n", f"- Owner team: {team_of_repo(ctx.facts, repo) or 'TO CONFIRM'}\n- On-call / escalation: TO CONFIRM\n- Service tier and SLA: TO CONFIRM\n",
         "## 2. How it starts (observed)\n"]
    p += _bullets(own("container_command") + own("entry_point"), lambda f: f"{f['attrs'].get('instruction') or 'entry'}: `{md_cell(f['attrs'].get('command') or f['attrs'].get('label'))}` - {cite(f)}") or ["- UNKNOWN: no start command or entry point found"]
    p.append("\n## 3. Ports\n")
    p += _bullets(own("container_port"), lambda f: f"EXPOSE {', '.join(map(str, f['attrs']['ports']))} - {cite(f)}") or ["- none found"]
    p.append("\n## 4. Health checks\n")
    p += _bullets(health, lambda f: f"`{f['subject']}` - {cite(f)}") or ["- UNKNOWN: no health endpoint found. Add one before relying on automated restarts."]
    p.append("\n## 5. Configuration (names only; values and secrets are never printed)\n")
    keys = sorted({f["attrs"]["key"] for f in own("config_key_use")} | {f["attrs"]["name"] for f in own("env_var_use")})
    p += [f"- `{k}`" for k in keys[:80]] or ["- none found"]
    p.append("\n## 6. Deploy and release (observed)\n")
    p += _bullets(own("pipeline_stage") + own("deploy_command"), lambda f: f"{f['attrs'].get('system')}: {f['attrs'].get('stage') or md_cell(f['attrs'].get('command'))} - {cite(f)}") or ["- UNKNOWN: no pipeline found"]
    p.append("\n## 7. Dependencies this service needs\n")
    p += _bullets(own("db_connection") + own("messaging_reference"), lambda f: f"{f['kind']} `{md_cell(f['attrs'].get('engine') or f['attrs'].get('topic'))}` - {cite(f)}") or ["- none found"]
    p.append("\n## 8. To complete (people)\n\n- Rollback procedure: TO CONFIRM\n- Common alerts and their meaning: TO CONFIRM\n- Data recovery and backup: TO CONFIRM\n- Contacts: TO CONFIRM\n")
    return "\n".join(p) + "\n"


def adr_pages(ctx: Ctx, repo: str) -> dict[str, str]:
    own = [f for f in ctx.facts if f["attrs"].get("repo") == repo]
    pages = {}
    n = 0
    for aid, title, pred in ADR_SIGNALS:
        hits = [f for f in own if pred(f)]
        if not hits:
            continue
        n += 1
        values = sorted({md_cell(f["attrs"].get("engine") or f["attrs"].get("topic") or f["attrs"].get("image") or f["attrs"].get("system") or f["attrs"].get("title") or f["attrs"].get("scheme") or f["subject"]) for f in hits})
        p = [header(f"ADR-{n:03d} (draft): {title} for {repo}", ctx, "DRAFT generated from observed facts. Status stays *Proposed* until the owning team reviews it."),
             "## Status\n\nProposed (auto-generated draft)\n", "## Context\n\nTO CONFIRM: the reason this choice was made is not recorded in the repository.\n",
             f"## Decision (observed)\n\n`{repo}` uses: " + ", ".join(f"`{v}`" for v in values[:8]) + ".\n", "## Evidence\n"]
        p += _bullets(hits, lambda f: f"{cite(f)}")
        p.append("\n## Consequences\n\nTO CONFIRM by the owning team.\n\n## Alternatives considered\n\nUNKNOWN: not recorded.\n")
        pages[f"docs-generated/{slug(repo)}/adr/ADR-{n:03d}-{aid}.md"] = "\n".join(p) + "\n"
    return pages


def run(ctx: Ctx) -> Result:
    g = graph.compute(ctx)
    files = {}
    rows = []
    for repo in ctx.repo_names:
        files[f"docs-generated/{slug(repo)}/architecture.md"] = architecture_page(ctx, repo, g)
        files[f"docs-generated/{slug(repo)}/runbook.md"] = runbook_page(ctx, repo)
        adrs = adr_pages(ctx, repo)
        files.update(adrs)
        rows.append(f"- **{repo}**: [architecture]({slug(repo)}/architecture.md) · [runbook]({slug(repo)}/runbook.md) · {len(adrs)} ADR draft(s)" +
                    "".join(f" · [{p.rsplit('/', 1)[1][:-3]}]({slug(repo)}/adr/{p.rsplit('/', 1)[1]})" for p in sorted(adrs)))
    files["docs-generated/index.md"] = header("Generated documentation", ctx, "Architecture pages, runbook skeletons and ADR drafts. Every statement cites evidence; gaps say UNKNOWN or TO CONFIRM.") + "\n".join(rows or ["- no services"]) + "\n"
    return Result(files=files, index=["- [Generated docs: architecture, runbooks, ADR drafts](docs-generated/index.md)"],
                  coverage={"living docs": f"{len(ctx.repo_names)} architecture pages, runbooks; {sum(1 for k in files if '/adr/' in k)} ADR drafts"})
