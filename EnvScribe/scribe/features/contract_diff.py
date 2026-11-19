"""Feature 10 - API contract diff and breaking-change detection.

Compares (a) the same API against its snapshot in the previous run, and (b) different contract files that declare the same API title
(for example v1 vs v2, or a contract kept per environment). Rules are exact and listed; nothing is guessed.

BREAKING: operation removed, required parameter added, parameter removed, parameter now required, success status code removed,
request body became required, schema property removed, property type changed, property became required.
NON-BREAKING: operation added, optional parameter added, schema property added (optional), response code added.
"""
from __future__ import annotations

import json
from collections import defaultdict

from ..facts import ev, make_fact
from . import history
from .common import Ctx, Result, header, md_cell


def extract(ctx: Ctx) -> dict:
    """{api_key: {"meta": {...}, "ops": {"VERB path": {...}}, "schemas": {name: {...}}}} from current facts."""
    apis: dict[str, dict] = {}

    def api_for(repo: str, path: str) -> dict:
        title = next((f["attrs"].get("title") for f in ctx.k("api_service") if f["attrs"].get("repo") == repo and f["attrs"].get("path") == path), None)
        key = f"{repo}:{title or path}"
        return apis.setdefault(key, {"meta": {"repo": repo, "title": title or path, "version": None, "file": path}, "ops": {}, "schemas": {}})

    for f in ctx.k("api_service"):
        a = f["attrs"]
        if a.get("protocol") == "rest":
            api_for(a["repo"], a["path"])["meta"]["version"] = a.get("version")
    for f in ctx.k("api_operation"):
        a = f["attrs"]
        if a.get("protocol") != "rest" or not a.get("path_file"):
            continue
        api_for(a["repo"], a["path_file"])["ops"][f["subject"]] = {
            "params": sorted(f"{p.get('in')}:{p.get('name')}:{'req' if p.get('required') else 'opt'}" for p in a.get("parameters", []) if p.get("name")),
            "responses": sorted(a.get("responses", [])), "body": bool(a.get("has_request_body")), "cite": f"{f['evidence'][0]['source']} {f['evidence'][0]['location']}"}
    for f in ctx.k("api_schema"):
        a = f["attrs"]
        if a.get("path") and a["repo"]:
            api_for(a["repo"], a["path"])["schemas"][a["name"]] = {"props": a.get("properties", []), "types": a.get("types", {}), "required": a.get("required", [])}
    return apis


def diff_apis(old: dict, new: dict) -> list[dict]:
    """old/new: {"ops":..., "schemas":...}. Returns [{level, what, detail}] sorted breaking-first."""
    out: list[dict] = []

    def add(level, what, detail):
        out.append({"level": level, "what": what, "detail": detail})

    for op, o in old["ops"].items():
        n = new["ops"].get(op)
        if n is None:
            add("breaking", op, "operation removed")
            continue
        op_p, np_ = {p.rsplit(":", 1)[0]: p.rsplit(":", 1)[1] for p in o["params"]}, {p.rsplit(":", 1)[0]: p.rsplit(":", 1)[1] for p in n["params"]}
        for k in sorted(set(op_p) - set(np_)):
            add("breaking", op, f"parameter removed: {k}")
        for k in sorted(set(np_) - set(op_p)):
            add("breaking" if np_[k] == "req" else "non-breaking", op, f"{'required' if np_[k] == 'req' else 'optional'} parameter added: {k}")
        for k in sorted(set(op_p) & set(np_)):
            if op_p[k] == "opt" and np_[k] == "req":
                add("breaking", op, f"parameter now required: {k}")
        o_ok = {r for r in o["responses"] if r.startswith("2")}
        n_ok = {r for r in n["responses"] if r.startswith("2")}
        for r in sorted(o_ok - n_ok):
            add("breaking", op, f"success response {r} removed")
        for r in sorted(set(n["responses"]) - set(o["responses"])):
            add("non-breaking", op, f"response {r} added")
        if not o["body"] and n["body"]:
            add("breaking", op, "request body added (clients that send none may fail)")
    for op in sorted(set(new["ops"]) - set(old["ops"])):
        add("non-breaking", op, "operation added")
    for name, o in old["schemas"].items():
        n = new["schemas"].get(name)
        if n is None:
            add("breaking", f"schema {name}", "schema removed")
            continue
        for p in sorted(set(o["props"]) - set(n["props"])):
            add("breaking", f"schema {name}", f"property removed: {p}")
        for p in sorted(set(n["props"]) - set(o["props"])):
            add("breaking" if p in n["required"] else "non-breaking", f"schema {name}", f"{'required' if p in n['required'] else 'optional'} property added: {p}")
        for p in sorted(set(o["props"]) & set(n["props"])):
            if o["types"].get(p) and n["types"].get(p) and o["types"][p] != n["types"][p]:
                add("breaking", f"schema {name}", f"property {p} type changed {o['types'][p]} -> {n['types'][p]}")
            if p not in o["required"] and p in n["required"]:
                add("breaking", f"schema {name}", f"property now required: {p}")
    for name in sorted(set(new["schemas"]) - set(old["schemas"])):
        add("non-breaking", f"schema {name}", "schema added")
    return sorted(out, key=lambda x: (x["level"] != "breaking", x["what"], x["detail"]))


def _comparisons(ctx: Ctx, cur: dict, prev_apis: dict | None) -> list[dict]:
    comps = []
    if prev_apis:
        for key, new in cur.items():
            old = prev_apis.get(key)
            if old:
                comps.append({"kind": "previous run -> this run", "api": key, "old_label": f"run {prev_apis.get('_run', 'previous')}", "new_label": ctx.run_id,
                              "changes": diff_apis(old, new)})
        for key in sorted(set(prev_apis) - set(cur) - {"_run"}):
            comps.append({"kind": "previous run -> this run", "api": key, "old_label": "previous", "new_label": ctx.run_id,
                          "changes": [{"level": "breaking", "what": key, "detail": "API contract no longer present"}]})
    by_title: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    for key, v in cur.items():
        by_title[str(v["meta"]["title"]).lower()].append((key, v))
    for title, group in by_title.items():
        if len(group) >= 2:
            group.sort(key=lambda kv: (str(kv[1]["meta"]["version"] or ""), kv[0]))
            for (ka, a), (kb, b) in zip(group, group[1:]):
                comps.append({"kind": "same API title, different contract files", "api": title, "old_label": f"{a['meta']['repo']}/{a['meta']['file']} (v{a['meta']['version']})",
                              "new_label": f"{b['meta']['repo']}/{b['meta']['file']} (v{b['meta']['version']})", "changes": diff_apis(a, b)})
    return comps


def run(ctx: Ctx) -> Result:
    cur = extract(ctx)
    prev = history.load_previous(ctx.out, ctx.run_id)
    prev_apis = (prev or {}).get("contracts")
    if prev_apis is not None:
        prev_apis = {**prev_apis, "_run": prev.get("run_id")}
    ctx.cache["snapshot_contracts"] = cur
    comps = _comparisons(ctx, cur, prev_apis)
    facts = []
    for c in comps:
        for ch in c["changes"]:
            facts.append(make_fact("contract_change", f"{c['api']}:{ch['what']}:{ch['detail']}",
                                   {"api": c["api"], "level": ch["level"], "what": ch["what"], "detail": ch["detail"], "comparison": c["kind"],
                                    "from": c["old_label"], "to": c["new_label"]},
                                   "DERIVED", [ev(c["new_label"].split(" ")[0] if "/" in c["new_label"] else f"{c['api']}", "contract diff", ch["detail"])], "contract_diff",
                                   "exact comparison of operations, parameters, response codes and schema properties between two contract versions"))
    nb = sum(1 for c in comps for ch in c["changes"] if ch["level"] == "breaking")
    md = [header("API contract changes", ctx, "Breaking-change rules are listed at the bottom. REST (OpenAPI/Swagger) contracts only."),
          f"{len(cur)} REST contract(s) found. {len(comps)} comparison(s); **{nb} breaking change(s)**.\n"]
    if not comps:
        md.append("UNKNOWN: nothing to compare yet. A comparison needs either a previous run in this output folder or two contract files that declare the same API title.\n")
    for c in comps:
        md.append(f"## {c['api']}: {c['kind']}\n\n`{md_cell(c['old_label'])}` → `{md_cell(c['new_label'])}`\n")
        md += [f"- **{ch['level'].upper()}** {md_cell(ch['what'])}: {md_cell(ch['detail'])}" for ch in c["changes"][:300]] or ["- no differences"]
        md.append("")
    md.append("## Rules\n\n- BREAKING: operation or schema removed; parameter removed; parameter newly required or required parameter added; success status code removed; "
              "request body added; response property removed, retyped or newly required.\n- NON-BREAKING: operation, optional parameter, optional property or response code added.\n"
              "- Not detected: semantic changes with the same shape, enum value changes, header and security changes, non-REST contracts.")
    return Result(files={"contracts/changes.md": "\n".join(md) + "\n"}, facts=facts, index=["- [API contract changes](contracts/changes.md)"],
                  coverage={"contract diff": f"{len(cur)} REST contracts; {len(comps)} comparisons; {nb} breaking changes"})
