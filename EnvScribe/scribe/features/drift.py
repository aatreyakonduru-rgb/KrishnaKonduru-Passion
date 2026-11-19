"""Feature 2 - Environment drift (SIT vs UAT vs prod ...) and run-to-run diff.

Environment drift is computed from config entries whose path names an environment. Secret-like keys compare presence only.
Run-to-run diff compares this run's facts with the previous run's snapshot (kept in <output>/history, outside the journal).
"""
from __future__ import annotations

import itertools
import json
from collections import defaultdict

from .. import analyses
from ..facts import ev, make_fact
from . import history
from .common import Ctx, Result, header, md_cell

MAX_ROWS = 400


def env_drift(ctx: Ctx) -> dict:
    mx = analyses.env_matrix(ctx.facts, ctx.settings.normalize_env)
    envs = mx["environments"]
    pairs = {}
    for a, b in itertools.combinations(envs, 2):
        only_a, only_b, differ, same = [], [], [], 0
        for row in mx["rows"]:
            va, vb = row["values"].get(a), row["values"].get(b)
            if va is None and vb is None:
                continue
            if va is None:
                only_b.append(row["key"])
            elif vb is None:
                only_a.append(row["key"])
            elif va != vb:
                differ.append({"key": row["key"], "a": va, "b": vb})
            else:
                same += 1
        pairs[f"{a} vs {b}"] = {"a": a, "b": b, "only_a": only_a, "only_b": only_b, "differ": differ, "same": same}
    # deployment/pipeline environments and DB engines per environment (OBSERVED facts, compared as sets)
    eng: dict[str, dict[str, set]] = defaultdict(lambda: defaultdict(set))
    for f in ctx.k("db_connection"):
        e = f["attrs"].get("environment")
        if e:
            eng[f["attrs"]["repo"]][ctx.settings.normalize_env(e)].add(f["attrs"]["engine"])
    engine_drift = [{"repo": r, "by_env": {e: sorted(v) for e, v in m.items()}} for r, m in sorted(eng.items()) if len({tuple(sorted(v)) for v in m.values()}) > 1]
    return {"environments": envs, "pairs": pairs, "engine_drift": engine_drift, "rows": mx["rows"]}


def run_diff(ctx: Ctx, prev: dict | None) -> dict:
    cur = history.snapshot_facts(ctx.facts)
    ctx.cache["snapshot_facts"] = cur
    if not prev or "facts" not in prev:
        return {"has_previous": False, "current": cur}
    p = prev["facts"]
    ck, pk = cur["keys"], p["keys"]
    added = sorted(set(ck) - set(pk))
    removed = sorted(set(pk) - set(ck))
    changed = sorted(k for k in set(ck) & set(pk) if ck[k] != pk[k])
    kinds = {}
    for name, ks in (("added", added), ("removed", removed), ("changed", changed)):
        for k in ks:
            kinds.setdefault(k.split("|", 1)[0], {"added": 0, "removed": 0, "changed": 0})[name] += 1
    return {"has_previous": True, "previous_run": prev.get("run_id"), "added": added, "removed": removed, "changed": changed, "kinds": kinds,
            "count_delta": {k: cur["counts"].get(k, 0) - p["counts"].get(k, 0) for k in sorted(set(cur["counts"]) | set(p["counts"])) if cur["counts"].get(k, 0) != p["counts"].get(k, 0)},
            "current": cur}


def run(ctx: Ctx) -> Result:
    d = env_drift(ctx)
    prev = history.load_previous(ctx.out, ctx.run_id)
    rd = run_diff(ctx, prev)
    facts = []
    for name, p in d["pairs"].items():
        n = len(p["differ"]) + len(p["only_a"]) + len(p["only_b"])
        if n:
            facts.append(make_fact("env_drift", name, {"environment_a": p["a"], "environment_b": p["b"], "differing_keys": len(p["differ"]), "only_in_a": len(p["only_a"]),
                                                      "only_in_b": len(p["only_b"]), "identical_keys": p["same"]},
                                   "DERIVED", [ev("environments/matrix.md", name, f"{n} differences")], "drift",
                                   "same repository and key, config files whose path names the environment; secret-like keys compare presence only"))
    md = [header("Environment drift", ctx, "Only config files whose path names an environment are compared. Values that are IPs or hosts are masked, so a masked value may hide a real difference.")]
    if len(d["environments"]) < 2:
        md.append("UNKNOWN: fewer than two environments have config files whose path names them, so there is nothing to compare.\n")
    for name, p in d["pairs"].items():
        md.append(f"## {name}\n\n- identical keys: {p['same']}\n- differing values: {len(p['differ'])}\n- only in {p['a']}: {len(p['only_a'])}\n- only in {p['b']}: {len(p['only_b'])}\n")
        if p["differ"]:
            md.append(f"| Key | {p['a']} | {p['b']} |\n|---|---|---|")
            md += [f"| `{md_cell(x['key'])}` | `{md_cell(x['a'])}` | `{md_cell(x['b'])}` |" for x in p["differ"][:MAX_ROWS]]
        if p["only_a"] or p["only_b"]:
            md.append(f"\nMissing counterpart:")
            md += [f"- `{k}` only in {p['a']}" for k in p["only_a"][:MAX_ROWS]] + [f"- `{k}` only in {p['b']}" for k in p["only_b"][:MAX_ROWS]]
        md.append("")
    if d["engine_drift"]:
        md.append("## Database engine differs between environments\n")
        md += [f"- `{x['repo']}`: " + "; ".join(f"{e}: {', '.join(v)}" for e, v in sorted(x['by_env'].items())) for x in d["engine_drift"]]
    md.append("\n> `prod` is compared only if production config files are part of the crawled sources.")
    # ---- run diff page
    rdm = [header("Changes since the previous run", ctx)]
    if not rd["has_previous"]:
        rdm.append("UNKNOWN: this is the first run in this output folder, so there is no earlier run to compare. Run again later to see what changed.\n")
    else:
        rdm.append(f"Compared with `{rd['previous_run']}`. Counts: **{len(rd['added'])} added, {len(rd['removed'])} removed, {len(rd['changed'])} changed** "
                   "(symbols, imports, TODOs and source-file facts are counted below but not listed).\n")
        rdm.append("## By kind\n\n| Kind | Added | Removed | Changed |\n|---|---|---|---|")
        rdm += [f"| {k} | {v['added']} | {v['removed']} | {v['changed']} |" for k, v in sorted(rd["kinds"].items())] or ["| _none_ | | | |"]
        for title, key in (("Added", "added"), ("Removed", "removed"), ("Changed", "changed")):
            rdm.append(f"\n## {title} (first {MAX_ROWS})\n")
            rdm += [f"- `{k.split('|')[0]}` {md_cell(k.split('|')[1])}" for k in rd[key][:MAX_ROWS]] or ["- none"]
        if rd["count_delta"]:
            rdm.append("\n## Fact count changes\n")
            rdm += [f"- {k}: {v:+d}" for k, v in rd["count_delta"].items()]
        facts.append(make_fact("run_diff", ctx.run_id, {"previous_run": rd["previous_run"], "added": len(rd["added"]), "removed": len(rd["removed"]), "changed": len(rd["changed"])},
                               "DERIVED", [ev("history/", ctx.run_id, f"vs {rd['previous_run']}")], "drift", "set difference of fact keys (kind|subject|source) and attribute hashes between two runs"))
    files = {"drift/environments.md": "\n".join(md) + "\n", "drift/since-last-run.md": "\n".join(rdm) + "\n",
             "drift/drift.json": json.dumps({"pairs": {k: {**v, "differ": v["differ"][:MAX_ROWS]} for k, v in d["pairs"].items()}, "engine_drift": d["engine_drift"],
                                              "run_diff": {k: (v[:MAX_ROWS] if isinstance(v, list) else v) for k, v in rd.items() if k != "current"}}, indent=1)}
    n_diff = sum(len(p["differ"]) + len(p["only_a"]) + len(p["only_b"]) for p in d["pairs"].values())
    return Result(files=files, facts=facts, index=["- [Environment drift](drift/environments.md) · [Changes since last run](drift/since-last-run.md)"],
                  coverage={"drift": f"{len(d['environments'])} environments, {n_diff} cross-environment differences; "
                                     + (f"{len(rd['added'])}+/{len(rd['removed'])}-/{len(rd['changed'])}~ vs previous run" if rd["has_previous"] else "no previous run to compare")})
