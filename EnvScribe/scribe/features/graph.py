"""Feature 1 - Dependency and architecture graph (JSON for the viewer, Mermaid and C4 exports).

Edges are built only from facts, each with its class and rule:
  service -> service   DERIVED   a URL's path equals exactly one other service's endpoint/contract path (host is masked, so path only)
  service -> table     DERIVED   static SQL parsed by sqlglot (lineage feature), else the SQL keyword scan
  service -> topic     OBSERVED  messaging reference in code or AsyncAPI
  service -> image     OBSERVED  Dockerfile FROM
  service -> database  OBSERVED  database connection key in config (engine only; host and credentials never recorded)
  service -> api       OBSERVED  OpenAPI/proto/GraphQL contract file in the repo
  any -> any           DOCUMENTED connection drawn in a diagram (not verified against code)
"""
from __future__ import annotations

import json
import re
from collections import defaultdict

from .common import Ctx, Result, cite, header, slug, templated_path_regex, url_path

MAX_EXTERNAL = 60
MAX_JSON_EDGES = 8000


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def compute(ctx: Ctx) -> dict:
    if "graph" in ctx.cache:
        return ctx.cache["graph"]
    nodes: dict[str, dict] = {}
    edges: dict[tuple, dict] = {}

    def node(nid: str, label: str, ntype: str, **extra) -> str:
        nodes.setdefault(nid, {"id": nid, "label": label, "type": ntype, **extra})
        return nid

    def edge(a: str, b: str, etype: str, cls: str, rule: str | None, evidence: str):
        e = edges.setdefault((a, b, etype), {"from": a, "to": b, "type": etype, "class": cls, "rule": rule, "evidence": [], "count": 0})
        e["count"] += 1
        if evidence and evidence not in e["evidence"] and len(e["evidence"]) < 5:
            e["evidence"].append(evidence)

    repos = ctx.repo_names
    for r in repos:
        node(f"svc:{r}", r, "service")

    # contracts a service provides + route table for call matching
    routes: list[tuple[re.Pattern, str, str, str]] = []     # (regex, repo, "VERB path", cite)
    for f in ctx.k("api_service"):
        a = f["attrs"]
        nid = node(f"api:{a['repo']}:{a.get('title') or a.get('name') or f['subject']}", str(a.get("title") or a.get("name") or f["subject"]), "api",
                   version=a.get("version"), protocol=a.get("protocol"))
        edge(f"svc:{a['repo']}", nid, "provides", "OBSERVED", None, cite(f))
    for f in ctx.k("endpoint"):
        a = f["attrs"]
        if a["path"] and a["path"] != "/":
            routes.append((templated_path_regex(a["path"]), a["repo"], f["subject"], cite(f)))
    for f in ctx.k("api_operation"):
        a = f["attrs"]
        if a.get("protocol") == "rest" and a.get("path") and a["path"] != "/":
            routes.append((templated_path_regex(a["path"]), a["repo"], f["subject"], cite(f)))

    ext_count = 0
    for f in ctx.k("url_reference"):
        a = f["attrs"]
        p = url_path(a["url"])
        if not p or p == "/":
            continue
        owners = {r for rx, r, _, _ in routes if rx.match(p) and r != a["repo"]}
        if len(owners) == 1:
            tgt = next(iter(owners))
            edge(f"svc:{a['repo']}", f"svc:{tgt}", "calls", "DERIVED",
                 "URL path equals exactly one other service's endpoint path (host is masked; matching is on path only)", cite(f))
        elif not owners and ext_count < MAX_EXTERNAL:
            ext_count += 1
            nid = node(f"ext:{p}", f"external HTTP {p}", "external")
            edge(f"svc:{a['repo']}", nid, "calls-external", "OBSERVED", None, cite(f))

    # data access: prefer parsed SQL, fall back to keyword scan
    parsed = ctx.k("sql_access")
    seen_pairs = set()
    for f in parsed:
        a = f["attrs"]
        nid = node(f"db:{a['table']}", a["table"], "table")
        edge(f"svc:{a['repo']}", nid, "writes" if a["operation"] == "write" else "reads", "DERIVED", f.get("rule"), cite(f))
        seen_pairs.add((a["repo"], a["table"]))
    for f in ctx.k("table_reference"):
        a = f["attrs"]
        if (a["repo"], a["table"]) in seen_pairs:
            continue
        nid = node(f"db:{a['table']}", a["table"], "table")
        edge(f"svc:{a['repo']}", nid, "references", "DERIVED", f.get("rule"), cite(f))
    for f in ctx.k("db_connection"):
        a = f["attrs"]
        nid = node(f"dbe:{a['engine']}", f"{a['engine']} database", "database")
        edge(f"svc:{a['repo']}", nid, "connects", "OBSERVED", None, cite(f))
    for f in ctx.k("messaging_reference"):
        a = f["attrs"]
        nid = node(f"topic:{a['topic']}", a["topic"], "topic")
        edge(f"svc:{a['repo']}", nid, "uses-topic", "OBSERVED", None, cite(f))
    for f in ctx.k("container_image"):
        a = f["attrs"]
        nid = node(f"img:{a['image']}", a["image"], "image")
        edge(f"svc:{a['repo']}", nid, "built-from", "OBSERVED", None, cite(f))

    # documented edges
    by_norm = {_norm(r): r for r in repos}
    for f in ctx.k("diagram_edge"):
        a = f["attrs"]
        ends = []
        for nm in (a["from"], a["to"]):
            r = by_norm.get(_norm(nm))
            ends.append(f"svc:{r}" if r else node(f"doc:{slug(nm)}", str(nm), "documented"))
        edge(ends[0], ends[1], "documented-connection", "DOCUMENTED", "drawn in a diagram; not verified against code", cite(f))

    g = {"nodes": sorted(nodes.values(), key=lambda n: n["id"]),
         "edges": sorted(edges.values(), key=lambda e: (e["from"], e["to"], e["type"]))}
    ctx.cache["graph"] = g
    return g


def adjacency(g: dict) -> tuple[dict, dict]:
    out, inn = defaultdict(list), defaultdict(list)
    for e in g["edges"]:
        out[e["from"]].append(e)
        inn[e["to"]].append(e)
    return out, inn


# ---------------- Mermaid / C4 ----------------
_BAD = re.compile(r"[\"'`<>\[\]{}()|;#&]")


def _label(s: str) -> str:
    return _BAD.sub(" ", str(s))[:60].strip() or "-"


def _select(g: dict, cap: int = 120) -> tuple[list[dict], list[dict], bool]:
    """Overview selection: all services, resources used by 2+ services, and the edges among them."""
    out, inn = adjacency(g)
    keep = {n["id"] for n in g["nodes"] if n["type"] == "service"}
    for n in g["nodes"]:
        if n["type"] in ("table", "topic", "database", "image", "documented", "api"):
            users = {e["from"] for e in inn[n["id"]] if e["from"].startswith("svc:")}
            if len(users) >= 2 or n["type"] in ("documented",):
                keep.add(n["id"])
    truncated = len(keep) > cap
    if truncated:
        svc = sorted(i for i in keep if i.startswith("svc:"))
        rest = sorted(i for i in keep if not i.startswith("svc:"))
        keep = set((svc + rest)[:cap])
    nodes = [n for n in g["nodes"] if n["id"] in keep]
    edges = [e for e in g["edges"] if e["from"] in keep and e["to"] in keep]
    return nodes, edges, truncated


def mermaid_flow(nodes: list[dict], edges: list[dict], direction: str = "LR") -> str:
    ids = {n["id"]: f"n{i}" for i, n in enumerate(nodes, 1)}
    shape = {"service": ("[", "]"), "table": ("[(", ")]"), "database": ("[(", ")]"), "topic": ("[/", "/]"), "image": ("(", ")"),
             "external": ("{{", "}}"), "api": ("([", "])"), "documented": ("[[", "]]")}
    lines = [f"flowchart {direction}"]
    for n in nodes:
        a, b = shape.get(n["type"], ("[", "]"))
        lines.append(f'    {ids[n["id"]]}{a}"{_label(n["label"])}"{b}')
    for e in edges:
        if e["from"] in ids and e["to"] in ids:
            arrow = "-.->" if e["class"] == "DOCUMENTED" else "-->"
            lines.append(f'    {ids[e["from"]]} {arrow}|{_label(e["type"])}| {ids[e["to"]]}')
    return "\n".join(lines)


def mermaid_c4(nodes: list[dict], edges: list[dict], title: str) -> str:
    ids = {n["id"]: f"c{i}" for i, n in enumerate(nodes, 1)}
    lines = ["C4Container", f'    title {_label(title)}']
    for n in nodes:
        i = ids[n["id"]]
        if n["type"] == "service":
            lines.append(f'    Container({i}, "{_label(n["label"])}", "service", "from scanned repository")')
        elif n["type"] in ("table", "database"):
            lines.append(f'    ContainerDb({i}, "{_label(n["label"])}", "{n["type"]}", "")')
        elif n["type"] == "topic":
            lines.append(f'    ContainerQueue({i}, "{_label(n["label"])}", "topic", "")')
        else:
            lines.append(f'    System_Ext({i}, "{_label(n["label"])}", "{n["type"]}")')
    for e in edges:
        if e["from"] in ids and e["to"] in ids:
            lines.append(f'    Rel({ids[e["from"]]}, {ids[e["to"]]}, "{_label(e["type"])}")')
    return "\n".join(lines)


def neighborhood(g: dict, repo: str) -> tuple[list[dict], list[dict]]:
    sid = f"svc:{repo}"
    out, inn = adjacency(g)
    es = out.get(sid, []) + inn.get(sid, [])
    ids = {sid} | {e["from"] for e in es} | {e["to"] for e in es}
    by = {n["id"]: n for n in g["nodes"]}
    return [by[i] for i in sorted(ids) if i in by], es


def run(ctx: Ctx) -> Result:
    g = compute(ctx)
    nodes, edges, truncated = _select(g)
    counts = defaultdict(int)
    for e in g["edges"]:
        counts[e["type"]] += 1
    note = " (overview truncated to the first 120 nodes; full graph is in graph.json)" if truncated else ""
    overview = (header("Architecture graph", ctx, "Solid arrows are OBSERVED or DERIVED from code/config; dotted arrows are DOCUMENTED claims not verified against code.") +
                f"## Overview{note}\n\nServices plus resources shared by two or more services.\n\n```mermaid\n{mermaid_flow(nodes, edges)}\n```\n\n"
                "## Edge counts\n\n" + ("\n".join(f"- {k}: {v}" for k, v in sorted(counts.items())) or "- none") + "\n\n"
                "## Service-to-service calls (DERIVED)\n\n" +
                ("\n".join(f"- `{e['from'][4:]}` → `{e['to'][4:]}` ({e['count']} call site(s)) - {e['evidence'][0]}" for e in g["edges"] if e["type"] == "calls") or "- none found; cross-service calls are only linked when a URL path equals exactly one other service's endpoint path") +
                "\n\n## Not shown\n\nHosts are always masked, so a call to another system is matched on URL path only. Calls through service discovery, gateways or message brokers are only visible via the topic edges.\n")
    c4 = (header("C4 container diagram", ctx, "Mermaid C4 syntax.") + f"```mermaid\n{mermaid_c4(nodes, edges, 'EnvScribe discovered containers')}\n```\n")
    capped = {"nodes": g["nodes"], "edges": g["edges"][:MAX_JSON_EDGES], "truncated_edges": max(0, len(g["edges"]) - MAX_JSON_EDGES)}
    index = (header("Graph", ctx) + "- [Architecture overview (Mermaid)](architecture.md)\n- [C4 containers](c4-containers.md)\n"
             "- `graph.json` - nodes and edges with evidence; open the **Graph** tab in the viewer for the interactive view.\n")
    return Result(files={"graph/architecture.md": overview, "graph/c4-containers.md": c4, "graph/graph.json": json.dumps(capped, indent=1),
                         "graph/index.md": index},
                  index=["- [Architecture graph](graph/index.md)"],
                  coverage={"graph": f"{len(g['nodes'])} nodes, {len(g['edges'])} edges"})
