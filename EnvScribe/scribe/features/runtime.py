"""Feature 14 - Runtime correlation: import service maps from an APM / tracing tool and compare them with the static graph.

Reads exports dropped in `runtime_dir` (default <output>/runtime-maps). EnvScribe does not call APM products; export from your tool in one of:
  JSON  {"window": "7d", "edges": [{"from": "svc-a", "to": "svc-b", "calls": 1200, "errors": 3}], "endpoints": [{"service": "svc-a", "method": "GET", "path": "/x", "calls": 10}]}
  CSV   columns source,target,calls[,errors]   (edges)    or    service,method,path,calls   (endpoints)
Names are matched to repositories exactly after lower-casing and dropping punctuation; unmatched names are listed, never guessed.
Findings: runtime calls the code does not show (static analysis missed them), static calls with no runtime traffic, endpoints with zero traffic.
Absence in a runtime export means "not seen in the exported window", which is stated on every such finding.
"""
from __future__ import annotations

import csv
import io
import json
import re
from collections import defaultdict
from pathlib import Path

from ..facts import ev, make_fact
from ..util import read_text
from . import graph
from .common import Ctx, Result, header, md_cell, templated_path_regex


def _norm(n: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (n or "").lower())


def _int(v) -> int:
    try:
        return int(float(str(v).replace(",", "")))
    except (TypeError, ValueError):
        return 0


def parse_file(name: str, text: str) -> dict:
    """-> {"edges": [{from,to,calls,errors}], "endpoints": [{service,method,path,calls}], "window": str|None}"""
    out = {"edges": [], "endpoints": [], "window": None}
    s = text.lstrip()
    if s.startswith(("{", "[")):
        d = json.loads(s)
        if isinstance(d, list):
            d = {"edges": d}
        out["window"] = d.get("window")
        for e in d.get("edges", []) or []:
            a, b = e.get("from") or e.get("source"), e.get("to") or e.get("target")
            if a and b:
                out["edges"].append({"from": str(a), "to": str(b), "calls": _int(e.get("calls", e.get("count", e.get("requests", 0)))), "errors": _int(e.get("errors", 0))})
        for e in d.get("endpoints", []) or []:
            if e.get("service") and e.get("path"):
                out["endpoints"].append({"service": str(e["service"]), "method": str(e.get("method") or "ANY").upper(), "path": str(e["path"]), "calls": _int(e.get("calls", e.get("count", 0)))})
        return out
    rows = list(csv.DictReader(io.StringIO(text)))
    for r in rows:
        r = {(k or "").strip().lower(): (v or "").strip() for k, v in r.items()}
        if r.get("source") and r.get("target"):
            out["edges"].append({"from": r["source"], "to": r["target"], "calls": _int(r.get("calls") or r.get("count")), "errors": _int(r.get("errors"))})
        elif r.get("service") and r.get("path"):
            out["endpoints"].append({"service": r["service"], "method": (r.get("method") or "ANY").upper(), "path": r["path"], "calls": _int(r.get("calls") or r.get("count"))})
    return out


def load(directory: str) -> tuple[dict, list[dict]]:
    agg = {"edges": {}, "endpoints": {}, "windows": set(), "files": []}
    problems = []
    d = Path(directory)
    if not d.is_dir():
        return agg, problems
    for p in sorted(d.glob("**/*")):
        if not p.is_file() or p.suffix.lower() not in (".json", ".csv"):
            continue
        text, _ = read_text(str(p), 20_000_000)
        try:
            r = parse_file(p.name, text or "")
        except (ValueError, csv.Error):
            problems.append({"file": p.name, "reason": "could not parse as JSON or CSV"})
            continue
        agg["files"].append(p.name)
        if r["window"]:
            agg["windows"].add(str(r["window"]))
        for e in r["edges"]:
            k = (e["from"], e["to"])
            c = agg["edges"].setdefault(k, {"from": e["from"], "to": e["to"], "calls": 0, "errors": 0, "file": p.name})
            c["calls"] += e["calls"]
            c["errors"] += e["errors"]
        for e in r["endpoints"]:
            k = (e["service"], e["method"], e["path"])
            c = agg["endpoints"].setdefault(k, {**e, "calls": 0, "file": p.name})
            c["calls"] += e["calls"]
    return agg, problems


def correlate(ctx: Ctx, agg: dict) -> dict:
    repos = {_norm(r): r for r in ctx.repo_names}
    g = graph.compute(ctx)
    static = {(e["from"][4:], e["to"][4:]): e for e in g["edges"] if e["type"] == "calls"}
    unmatched, rt = set(), {}
    for (a, b), e in agg["edges"].items():
        ra, rb = repos.get(_norm(a)), repos.get(_norm(b))
        if not ra:
            unmatched.add(a)
        if not rb:
            unmatched.add(b)
        if ra and rb and ra != rb:
            rt[(ra, rb)] = e
    runtime_only = sorted(k for k in rt if k not in static)
    static_unseen = sorted(k for k in static if k not in rt) if rt else []
    confirmed = sorted(k for k in static if k in rt)
    # endpoints: contract/code endpoints per service vs observed traffic
    seen_by_svc = defaultdict(list)
    for (svc, m, p), e in agg["endpoints"].items():
        r = repos.get(_norm(svc))
        if r:
            seen_by_svc[r].append((m, p.split("?")[0].rstrip("/") or "/", e["calls"]))
        else:
            unmatched.add(svc)
    zero = []
    for f in ctx.k("endpoint") + ctx.k("api_operation"):
        a = f["attrs"]
        if a["repo"] not in seen_by_svc or not a.get("path"):
            continue
        rx = templated_path_regex(a["path"])      # a placeholder in the code path matches a concrete or templated observed path
        verb = a.get("verb") or "ANY"
        calls = sum(c for m, obs, c in seen_by_svc[a["repo"]] if (m == verb or "ANY" in (m, verb)) and rx.match(obs))
        if calls == 0:
            zero.append(f)
    return {"runtime_only": runtime_only, "static_unseen": static_unseen, "confirmed": confirmed, "rt": rt, "static": static, "zero_traffic": zero, "unmatched": sorted(unmatched)}


def run(ctx: Ctx) -> Result:
    agg, problems = load(ctx.settings.runtime_maps)
    if not agg["files"]:
        return Result(files={"runtime/index.md": header("Runtime correlation", ctx) + "UNKNOWN: no APM service-map export was found, so code is not compared with real traffic.\n\n"
                                                  f"Drop JSON or CSV exports from your APM/tracing tool into the runtime folder (setting `runtime_dir`) and run again. Formats are described in the README.\n"},
                      index=["- [Runtime correlation](runtime/index.md)"], coverage={"runtime": "no export provided"})
    c = correlate(ctx, agg)
    win = ", ".join(sorted(agg["windows"])) or "window not stated in the export"
    note = f"not seen in the exported runtime data ({win}); this does not prove the path is unused"
    facts = []
    for (a, b), e in sorted(c["rt"].items()):
        facts.append(make_fact("runtime_edge", f"{a}->{b}", {"from": a, "to": b, "calls": e["calls"], "errors": e["errors"], "window": win}, "OBSERVED",
                               [ev(f"apm-export:{e['file']}", f"{a} -> {b}", f"calls={e['calls']}")], "runtime"))
    for a, b in c["runtime_only"]:
        e = c["rt"][(a, b)]
        facts.append(make_fact("runtime_gap", f"runtime-only:{a}->{b}", {"kind": "runtime_call_not_in_code", "from": a, "to": b, "calls": e["calls"]}, "DERIVED",
                               [ev(f"apm-export:{e['file']}", f"{a} -> {b}")], "runtime", "edge present in the runtime export but no static call edge exists (static analysis cannot see gateways, discovery or reflection)"))
    for a, b in c["static_unseen"]:
        facts.append(make_fact("runtime_gap", f"no-traffic:{a}->{b}", {"kind": "code_path_without_traffic", "from": a, "to": b, "note": note}, "DERIVED",
                               [c["static"][(a, b)]["evidence"] and ev(c["static"][(a, b)]["evidence"][0].split(" L")[0], "call site")], "runtime",
                               "static call edge with no matching edge in the runtime export"))
    for f in c["zero_traffic"][:300]:
        facts.append(make_fact("runtime_gap", f"zero-traffic:{f['attrs']['repo']}:{f['subject']}", {"kind": "endpoint_without_traffic", "repo": f["attrs"]["repo"], "endpoint": f["subject"], "note": note}, "DERIVED",
                               f["evidence"][:1], "runtime", "endpoint exists in code or contract; the service has endpoint traffic data and none matches this endpoint"))
    md = [header("Runtime correlation", ctx, "Compares the static graph with traffic exported from an APM tool."),
          f"Read {len(agg['files'])} export file(s) ({win}): {len(agg['edges'])} service edge(s), {len(agg['endpoints'])} endpoint record(s).\n"]
    if problems:
        md += [f"- UNKNOWN: `{p['file']}` {p['reason']}" for p in problems]
    md.append(f"## Calls seen at runtime but not in code ({len(c['runtime_only'])})\n\nStatic analysis misses gateway routing, service discovery and reflection. Review these first.\n")
    md += [f"- `{a}` → `{b}` ({c['rt'][(a, b)]['calls']} calls, {c['rt'][(a, b)]['errors']} errors)" for a, b in c["runtime_only"][:200]] or ["- none"]
    md.append(f"\n## Calls in code with no runtime traffic ({len(c['static_unseen'])})\n\nEach was {note}.\n")
    md += [f"- `{a}` → `{b}`" for a, b in c["static_unseen"][:200]] or ["- none"]
    md.append(f"\n## Confirmed by both ({len(c['confirmed'])})\n")
    md += [f"- `{a}` → `{b}` ({c['rt'][(a, b)]['calls']} calls)" for a, b in c["confirmed"][:200]] or ["- none"]
    md.append(f"\n## Endpoints with no traffic ({len(c['zero_traffic'])})\n")
    md += [f"- `{f['attrs']['repo']}` `{md_cell(f['subject'])}`" for f in c["zero_traffic"][:200]] or ["- none, or no endpoint-level export was provided"]
    if c["unmatched"]:
        md.append(f"\n## Names in the export that match no scanned repository ({len(c['unmatched'])})\n")
        md += [f"- `{md_cell(n)}`" for n in c["unmatched"][:100]]
    return Result(files={"runtime/index.md": "\n".join(md) + "\n"}, facts=facts, index=["- [Runtime correlation](runtime/index.md)"],
                  coverage={"runtime": f"{len(agg['edges'])} runtime edges; {len(c['runtime_only'])} not in code; {len(c['static_unseen'])} code paths without traffic"})
