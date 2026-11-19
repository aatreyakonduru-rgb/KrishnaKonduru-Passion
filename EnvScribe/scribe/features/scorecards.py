"""Feature 5 - Scorecards and risk flags. Every flag is a deterministic rule over facts or the repo root listing; each is a DERIVED fact
that records its rule and cites evidence (or states that the evidence is an absence, naming what was searched)."""
from __future__ import annotations

import json
import os
import re
from collections import defaultdict

from ..facts import ev, make_fact
from .common import Ctx, Result, cite, header, major_minor, md_cell, team_of_repo

# EnvScribe reference table (not read from the repos). Dated so that readers can judge staleness.
EOL_TABLE_DATE = "2025-10"
EOL_REF = {"java": {"eol_max": 10, "aging": {8, 11}}, "node": {"eol_max": 18, "aging": set()}, "python": {"eol_max": 3.9, "aging": set()},
           "dotnet": {"eol_max": 7, "aging": set()}}
HEALTH = re.compile(r"(?i)(^|/)(health|healthz|healthcheck|actuator/health|ping|ready|readyz|livez?|status)(/|$)")

RULES = {  # id -> (weight, severity, title)
    "no_readme": (8, "medium", "No README at the repository root"),
    "no_ci": (15, "high", "No CI/CD pipeline definition found"),
    "no_health": (8, "medium", "No health-check endpoint or HEALTHCHECK found"),
    "hardcoded_secret": (25, "critical", "Secret-like value hardcoded in source or config"),
    "eol_runtime": (15, "high", "Runtime or framework version is past end of support (reference table)"),
    "aging_runtime": (5, "low", "Runtime version is an older release line"),
    "no_tests": (12, "medium", "No test source files found"),
    "no_owner": (8, "medium", "No team owner found (CODEOWNERS / catalog-info)"),
    "no_contract": (8, "medium", "Endpoints exist in code but no API contract file was found"),
    "unpinned_image": (6, "medium", "Container base image is unpinned (`latest` or no tag)"),
    "unpinned_deps": (5, "low", "Dependencies declared without a pinned version"),
    "plaintext_env_config": (0, "info", "Per-environment config files present (see environment matrix)"),
}


def _runtime_versions(ctx: Ctx, repo: str) -> list[tuple[str, str, float, dict]]:
    out = []
    for f in ctx.k("module"):
        a = f["attrs"]
        if a.get("repo") != repo:
            continue
        mm = None
        if a.get("java_version"):
            mm = ("java", a["java_version"])
        elif a.get("engines") and isinstance(a["engines"], dict) and a["engines"].get("node"):
            mm = ("node", a["engines"]["node"])
        elif a.get("target_framework"):
            tf = str(a["target_framework"])
            if tf.startswith("netcoreapp"):
                mm = ("dotnet", "3")
            elif re.match(r"net\d", tf):
                mm = ("dotnet", tf[3:])
        if mm:
            v = major_minor(mm[1])
            if v:
                num = float(f"{v[0]}.{v[1]}") if mm[0] == "python" else float(v[0])
                out.append((mm[0], str(mm[1]), num, f))
    for f in ctx.k("container_image"):
        a = f["attrs"]
        if a.get("repo") != repo:
            continue
        m = re.search(r"(?i)(?:temurin|openjdk|jdk|java)[:\-/]*(\d+)", a["image"])
        if m:
            out.append(("java", m.group(1), float(m.group(1)), f))
        m = re.match(r"(?i)(?:.*/)?node:(\d+)", a["image"])
        if m:
            out.append(("node", m.group(1), float(m.group(1)), f))
        m = re.match(r"(?i)(?:.*/)?python:(\d+)\.(\d+)", a["image"])
        if m:
            out.append(("python", f"{m.group(1)}.{m.group(2)}", float(f"{m.group(1)}.{m.group(2)}"), f))
    return out


def evaluate(ctx: Ctx, repo: str) -> list[dict]:
    """Return [{rule, detail, evidence:[...], absence:bool}]"""
    flags: list[dict] = []
    root = ctx.repos.get(repo)
    names = {n.lower() for n in os.listdir(root)} if root and os.path.isdir(root) else set()
    own = lambda kind: [f for f in ctx.k(kind) if f["attrs"].get("repo") == repo]

    def flag(rule, detail, evidence, absence=False):
        flags.append({"rule": rule, "detail": detail, "evidence": evidence, "absence": absence})

    if root and not any(n.startswith("readme") for n in names):
        flag("no_readme", f"No README* in the root of `{repo}`", [ev(f"{repo}/", "root listing", "searched for README*")], True)
    if root is not None and not own("pipeline_stage"):
        flag("no_ci", "No Jenkinsfile, Bitbucket Pipelines, GitHub Actions, GitLab CI or Bamboo spec found", [ev(f"{repo}/", "repository scan", "searched pipeline definitions")], True)
    healthy = any(HEALTH.search(f["attrs"].get("path", "").strip("/")) for f in own("endpoint") + own("api_operation"))
    if not healthy:
        for f in own("container_image"):
            dp = f["attrs"].get("path")
            if dp and root:
                try:
                    if re.search(r"(?im)^\s*HEALTHCHECK\b", open(os.path.join(root, dp), encoding="utf-8", errors="replace").read()):
                        healthy = True
                except OSError:
                    pass
    if own("endpoint") and not healthy:
        flag("no_health", "Service exposes endpoints but none is a health/ready/live path and no HEALTHCHECK instruction was found", [ev(f"{repo}/", "endpoint list", "searched endpoints and Dockerfiles")], True)
    leaks, seen_loc = [], set()
    for x in own("secret_leak"):            # several detectors can fire on one line: count each location once
        loc = (x["attrs"].get("path"), x["attrs"].get("line"))
        if loc not in seen_loc:
            seen_loc.add(loc)
            leaks.append(x)
    if leaks:
        flag("hardcoded_secret", f"{len(leaks)} location(s) with a secret-like value in source/config (values never recorded)", [x["evidence"][0] for x in leaks[:3]])
    for kind, ver, num, f in _runtime_versions(ctx, repo):
        ref = EOL_REF[kind]
        if num <= ref["eol_max"]:
            flag("eol_runtime", f"{kind} {ver} is at or below {ref['eol_max']}, past end of support in the EnvScribe reference table ({EOL_TABLE_DATE})", f["evidence"][:1])
        elif int(num) in ref["aging"]:
            flag("aging_runtime", f"{kind} {ver} is an older release line (reference table {EOL_TABLE_DATE})", f["evidence"][:1])
    srcs = [f for f in own("source_file")]
    if srcs and not any(f["attrs"].get("is_test") for f in srcs):
        flag("no_tests", f"{len(srcs)} source file(s), none under a test path or named as a test", [ev(f"{repo}/", "source file list", "searched test paths and names")], True)
    if not team_of_repo(ctx.facts, repo):
        flag("no_owner", "No CODEOWNERS or catalog-info owner found", [ev(f"{repo}/CODEOWNERS", "file", "searched CODEOWNERS locations")], True)
    contract = [f for f in own("api_service") if f["attrs"].get("protocol") in ("rest", "grpc", "graphql", "soap")]
    if own("endpoint") and not contract:
        flag("no_contract", f"{len(own('endpoint'))} endpoint(s) in code and no OpenAPI/proto/GraphQL/WSDL file", [own("endpoint")[0]["evidence"][0]])
    for f in own("container_image"):
        im = f["attrs"]["image"]
        if im.lower() != "scratch" and (":" not in im.split("/")[-1] or im.endswith(":latest")) and "@sha256" not in im and not im.startswith("$"):
            flag("unpinned_image", f"Base image `{im}` has no pinned tag or digest", f["evidence"][:1])
    unp = [f for f in own("dependency") if not f["attrs"].get("version") or str(f["attrs"]["version"]).startswith(("*", "latest", "^", "~", ">", "["))]
    if len(unp) >= 3:
        flag("unpinned_deps", f"{len(unp)} dependencies lack an exact version (floating or missing)", unp[0]["evidence"][:1])
    return flags


def score(flags: list[dict]) -> int:
    return max(0, 100 - sum(RULES[f["rule"]][0] for f in flags))


def compute(ctx: Ctx) -> dict:
    if "scorecards" in ctx.cache:
        return ctx.cache["scorecards"]
    res = {r: evaluate(ctx, r) for r in ctx.repo_names}
    ctx.cache["scorecards"] = res
    return res


def run(ctx: Ctx) -> Result:
    cards = compute(ctx)
    facts: list[dict] = []
    for repo, flags in cards.items():
        for fl in flags:
            w, sev, title = RULES[fl["rule"]]
            facts.append(make_fact("risk_flag", f"{repo}:{fl['rule']}", {"repo": repo, "rule_id": fl["rule"], "severity": sev, "title": title, "detail": fl["detail"],
                                                                      "absence_finding": fl["absence"]},
                                   "DERIVED", fl["evidence"], "scorecard",
                                   ("absence of evidence after searching the stated locations; the repository copy scanned may be incomplete" if fl["absence"]
                                    else f"deterministic rule `{fl['rule']}` over scanned facts")))
        facts.append(make_fact("scorecard", repo, {"repo": repo, "score": score(flags), "flags": [f["rule"] for f in flags]}, "DERIVED",
                               [ev(f"{repo}/", "scorecard", ", ".join(f["rule"] for f in flags) or "no flags")], "scorecard",
                               "100 minus the weight of each raised rule (weights are listed in scorecards/index.md)"))
    sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    md = [header("Scorecards and risk flags", ctx, "Rules are deterministic. A score is a prioritisation aid, not a compliance verdict. Absence findings mean the item was not found in the scanned copy."),
          "## Services (lowest score first)\n\n| Service | Score | Critical | High | Medium | Low | Flags |\n|---|---|---|---|---|---|---|"]
    rows = []
    for repo, flags in cards.items():
        c = defaultdict(int)
        for f in flags:
            c[RULES[f["rule"]][1]] += 1
        rows.append((score(flags), repo, c, flags))
    for s, repo, c, flags in sorted(rows):
        md.append(f"| [{repo}](services/{repo}.md) | **{s}** | {c['critical']} | {c['high']} | {c['medium']} | {c['low']} | {md_cell(', '.join(f['rule'] for f in flags) or '-')} |")
    if not rows:
        md.append("| _no services_ | | | | | | |")
    svc_pages = {}
    for s, repo, c, flags in sorted(rows):
        p = [header(f"Scorecard: {repo}", ctx), f"**Score {s} / 100**\n"]
        for fl in sorted(flags, key=lambda x: (sev_order[RULES[x["rule"]][1]], x["rule"])):
            w, sev, title = RULES[fl["rule"]]
            p.append(f"### [{sev}] {title}\n- {fl['detail']}\n- Evidence: " + "; ".join(f"`{e['source']}` {e['location']}" for e in fl["evidence"]) +
                     ("\n- This is an *absence* finding: nothing was found in the scanned copy." if fl["absence"] else ""))
        if not flags:
            p.append("No rules raised.")
        svc_pages[f"scorecards/services/{repo}.md"] = "\n".join(p) + "\n"
    md.append("\n## Rules and weights\n\n| Rule | Severity | Weight | Meaning |\n|---|---|---|---|")
    md += [f"| `{k}` | {v[1]} | {v[0]} | {v[2]} |" for k, v in RULES.items()]
    md.append(f"\nRuntime support dates come from a fixed EnvScribe reference table dated {EOL_TABLE_DATE}, not from the repositories; confirm against your vendor's current policy.")
    return Result(files={"scorecards/index.md": "\n".join(md) + "\n", **svc_pages,
                         "scorecards/scorecards.json": json.dumps([{"repo": r, "score": s, "flags": [f["rule"] for f in fl]} for s, r, _, fl in sorted(rows)], indent=1)},
                  facts=facts, index=["- [Scorecards and risk flags](scorecards/index.md)"],
                  coverage={"scorecards": f"{len(rows)} services scored; {sum(len(f) for _, _, _, f in rows)} flags raised"})
