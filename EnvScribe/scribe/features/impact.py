"""Feature 9 - Change impact and PR draft (suggest-only).

Given a requirement, find the facts it touches, then expand through the graph: contracts, consumers, config per environment, tables and their other
users, messaging, importing files, and tests. Output is a ranked list of files with the reason and the citation that justifies each one. Nothing is
written to any repository. The optional patch comes only from an injected `llm` callable, is verified against the journal, and is always labelled PROPOSAL.
"""
from __future__ import annotations

import os
import re
from collections import defaultdict
from typing import Callable

from ..facts import fact_text
from .common import templated_path_regex, url_path

LABEL = "PROPOSAL - unverified. Not compiled, not tested, not applied. Review every file before use."


def _cite(f: dict) -> str:
    e = f["evidence"][0]
    return f"{e['source']} {e['location']}"


def _file_of(f: dict) -> tuple[str, str] | None:
    a = f["attrs"]
    repo = a.get("repo")
    p = a.get("file") or a.get("path_file") or a.get("path")     # endpoint/api_operation: `path` is the URL path, the file is stored separately
    return (repo, p) if repo and p else None


def _stem(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0]


def analyse(facts: list[dict], seeds: list[tuple[float, dict]], requirement: str = "", limit: int = 40) -> dict:
    by_kind: dict[str, list[dict]] = defaultdict(list)
    for f in facts:
        by_kind[f["kind"]].append(f)
    files: dict[tuple[str, str], dict] = {}

    def touch(repo, path, score, reason, fact, role="change"):
        e = files.setdefault((repo, path), {"repo": repo, "path": path, "score": 0.0, "reasons": [], "role": role, "cites": []})
        e["score"] += score
        if reason not in e["reasons"] and len(e["reasons"]) < 6:
            e["reasons"].append(reason)
        c = _cite(fact)
        if c not in e["cites"] and len(e["cites"]) < 4:
            e["cites"].append(c)
    seed_facts = [f for _, f in seeds[:25]]
    consumers: dict[str, dict] = {}
    topics, tables, keys, ops = set(), set(), set(), set()
    for s, f in seeds[:25]:
        w = min(s, 8.0) / 8.0 + 0.5
        k, a = f["kind"], f["attrs"]
        fp = _file_of(f)
        if fp and k not in ("source_file",):
            touch(*fp, 3.0 * w, f"matches the requirement ({k})", f)
        if k == "source_file":
            touch(a["repo"], a["path"], 2.5 * w, "source file matches the requirement", f)
        if k in ("endpoint", "api_operation"):
            ops.add((a.get("verb"), a.get("path"), a["repo"]))
        if k in ("table_reference", "sql_access"):
            tables.add(a["table"])
        if k in ("db_table", "db_column"):
            tables.add(a.get("table"))
        if k in ("config_key_use", "config_entry"):
            keys.add(a["key"])
        if k == "messaging_reference":
            topics.add(a["topic"])
    # endpoints/operations -> contract file, implementing code, consumers (URL path match in other repos)
    for verb, path, repo in ops:
        if not path or path == "/":
            continue
        rx = templated_path_regex(path)
        for f in by_kind["endpoint"] + by_kind["api_operation"]:
            a = f["attrs"]
            if a.get("path") and rx.match(a["path"].rstrip("/") or "/") or a.get("path") == path:
                fp = _file_of(f)
                if fp:
                    touch(*fp, 2.0, f"defines or implements `{a.get('verb') or ''} {path}`".replace("  ", " "), f)
        for f in by_kind["url_reference"]:
            a = f["attrs"]
            up = url_path(a["url"])
            if up and rx.match(up) and a["repo"] != repo:
                touch(a["repo"], a["path"], 2.2, f"calls `{path}` (consumer in another service; check compatibility)", f, "consumer")
                consumers.setdefault(a["repo"], f)
    # tables -> every code file that touches them + catalog evidence
    for f in by_kind["sql_access"] + by_kind["table_reference"]:
        if f["attrs"]["table"] in tables:
            touch(f["attrs"]["repo"], f["attrs"]["path"], 1.8, f"accesses table `{f['attrs']['table']}`", f)
    # config keys -> all per-environment definitions
    for f in by_kind["config_entry"]:
        if f["attrs"]["key"] in keys:
            env = f["attrs"].get("environment") or "no environment"
            touch(f["attrs"]["repo"], f["attrs"]["path"], 1.5, f"defines config key `{f['attrs']['key']}` ({env})", f)
    for f in by_kind["config_key_use"]:
        if f["attrs"]["key"] in keys:
            touch(f["attrs"]["repo"], f["attrs"]["path"], 1.5, f"reads config key `{f['attrs']['key']}`", f)
    # topics -> publishers/subscribers
    for f in by_kind["messaging_reference"]:
        if f["attrs"]["topic"] in topics:
            touch(f["attrs"]["repo"], f["attrs"]["path"], 1.5, f"uses topic `{f['attrs']['topic']}`", f)
    # importers of the primary files
    primary = [(r, p) for (r, p), e in files.items() if e["score"] >= 2.5]
    stems = {(r, _stem(p)): p for r, p in primary if _stem(p)}
    for f in by_kind["import"]:
        a = f["attrs"]
        tail = re.split(r"[./\\]", a["target"].strip("; "))[-1]
        if (a["repo"], tail) in stems and a["path"] != stems[(a["repo"], tail)]:
            touch(a["repo"], a["path"], 1.2, f"imports `{tail}` (may need updating)", f, "review")
    # tests: same repo, test file whose stem contains an impacted file's stem, or that imports it
    impacted = [(r, p) for (r, p) in files]
    tests = []
    for f in by_kind["source_file"]:
        a = f["attrs"]
        if not a.get("is_test"):
            continue
        for r, p in impacted:
            if r == a["repo"] and _stem(p) and _stem(p).lower() in a["path"].lower() and a["path"] != p and not files.get((r, a["path"])):
                tests.append((a["repo"], a["path"], p, f))
                break
    for r, tp, p, f in tests[:20]:
        touch(r, tp, 1.0, f"test whose name matches `{_stem(p)}`", f, "test")
    envs = sorted({f["attrs"]["environment"] for f in by_kind["config_entry"] if f["attrs"].get("key") in keys and f["attrs"].get("environment")})
    ranked = sorted(files.values(), key=lambda e: (-e["score"], e["repo"], e["path"]))[:limit]
    owners = sorted({o["attrs"]["team"] for o in by_kind["ownership"] if any(o["attrs"]["repo"] == e["repo"] for e in ranked)})
    return {"files": ranked, "consumers": sorted(consumers), "tables": sorted(t for t in tables if t), "config_keys": sorted(keys), "environments": envs, "topics": sorted(topics),
            "tests": [{"repo": r, "path": tp} for r, tp, _, _ in tests[:20]], "teams_to_notify": owners,
            "summary": {"files": len(ranked), "services": len({e["repo"] for e in ranked}), "consumers": len(consumers)}}


def pr_draft(requirement: str, imp: dict, diff: str | None = None) -> dict:
    top = imp["files"][:10]
    body = [f"## {requirement.strip()[:90]}", "", "### Summary", "TO CONFIRM by the author. This draft lists what the journal says is affected.", "", "### Files likely to change"]
    body += [f"- `{e['repo']}/{e['path']}` - {e['reasons'][0]}" for e in top if e["role"] != "test"] or ["- none identified"]
    if imp["consumers"]:
        body += ["", "### Consumers to check", *[f"- `{c}`" for c in imp["consumers"]]]
    if imp["tests"]:
        body += ["", "### Tests to update or add", *[f"- `{t['repo']}/{t['path']}`" for t in imp["tests"][:8]]]
    if imp["environments"]:
        body += ["", "### Environments needing config", f"- {', '.join(imp['environments'])}"]
    if imp["teams_to_notify"]:
        body += ["", "### Teams to notify", *[f"- {t}" for t in imp["teams_to_notify"]]]
    body += ["", "### Checklist", "- [ ] Contract updated first, consumers notified", "- [ ] Config added for each environment above", "- [ ] Tests added or updated", "- [ ] Pipelines for affected services reviewed"]
    return {"label": LABEL, "title": requirement.strip()[:80], "body": "\n".join(body), "patch": diff}


def propose(idx, requirement: str, llm: Callable[[str], str] | None = None, verify=None) -> dict:
    """idx: knowledge.Index. Returns impact + PR draft. Suggest-only."""
    seeds = idx.search(requirement, 40)
    if not seeds:
        return {"found": False, "message": "Nothing in the journal relates to this requirement; no impact can be stated.", "label": LABEL}
    imp = analyse(list(idx.facts.values()), seeds, requirement)
    diff = None
    if llm:
        prompt = ("Using ONLY the files and facts below, write a unified diff proposal for the requirement. Cite facts as [[source location]]. "
                  "If the facts are insufficient, say so instead of inventing code.\n\nREQUIREMENT: " + requirement + "\n\nFILES:\n" +
                  "\n".join(f"- {e['repo']}/{e['path']}: {e['reasons'][0]} [[{e['cites'][0]}]]" for e in imp["files"][:20] if e["cites"]))
        draft = llm(prompt)
        bad = verify(draft, idx) if verify else []
        diff = ("[REJECTED by verifier: cited sources that do not exist: " + ", ".join(bad[:5]) + "]") if bad else draft
    return {"found": True, "label": LABEL, "impact": imp, "pr_draft": pr_draft(requirement, imp, diff)}
