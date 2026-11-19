#!/usr/bin/env python3
"""Walk the Acme Claims link graph and check the lines it cites still say what the graph says.

Reads only `CROSS-LAYER/ACME_LINK_GRAPH.yaml` (built by `tools/kbgen/gen_link_graph.py`). Every link
it returns keeps its source, so the stage can open the file and line and confirm it. Used through
`ontology_lookup.py walk` and `ontology_lookup.py drift`.
"""
import os
import re
from collections import defaultdict, deque

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
GRAPH = "docs/knowledge-base/CROSS-LAYER/ACME_LINK_GRAPH.yaml"
FILE_LINE_RE = re.compile(r"^([\w./@\[\]()-]+?):(\d+)$")
WINDOW = 3
Loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def load(path=None):
    with open(path or os.path.join(REPO, GRAPH), encoding="utf-8") as fh:
        return yaml.load(fh, Loader=Loader)


class Graph:
    def __init__(self, data):
        self.meta = data.get("metadata") or {}
        self.nodes = data.get("nodes") or {}
        self.edges = data.get("edges") or []
        self.adj = defaultdict(list)
        for e in self.edges:
            self.adj[e["from"]].append((e, e["to"]))
            self.adj[e["to"]].append((e, e["from"]))
        self.by_name = defaultdict(list)
        for nid, n in self.nodes.items():
            self.by_name[str(n.get("name")).lower()].append(nid)

    def resolve(self, ref):
        ref = (ref or "").strip()
        if ref in self.nodes:
            return ref
        low = ref.lower()
        hits = self.by_name.get(low) or self.by_name.get("cl_" + low) or []
        if not hits:
            hits = [nid for nid in self.nodes if nid.lower() == low]
        if len(hits) > 1:
            order = ["story", "screen", "endpoint", "table", "column", "file", "test", "job", "object", "system", "chain"]
            hits.sort(key=lambda nid: order.index(self.nodes[nid]["type"]) if self.nodes[nid]["type"] in order else 99)
        return hits[0] if hits else None

    def suggest(self, ref, n=8):
        low = (ref or "").lower()
        return sorted(nid for nid in self.nodes if low and low in nid.lower())[:n]

    def walk(self, ref, hops=2, types=None, limit=300):
        """Every node within `hops` links of `ref`, each with the shortest path and the sources on it."""
        start = self.resolve(ref)
        if not start:
            return {"query": ref, "found": False, "suggestions": self.suggest(ref)}
        seen = {start: []}
        q = deque([start])
        while q:
            cur = q.popleft()
            if len(seen[cur]) >= hops:
                continue
            for e, nxt in self.adj[cur]:
                if nxt not in seen:
                    seen[nxt] = seen[cur] + [e]
                    q.append(nxt)
        reached = defaultdict(list)
        for nid, path in seen.items():
            if nid == start:
                continue
            t = self.nodes.get(nid, {}).get("type", nid.split(":")[0])
            if types and t not in types:
                continue
            reached[t].append({"id": nid, "hops": len(path),
                               "path": ["%s -%s-> %s" % (e["from"], e["type"], e["to"]) for e in path],
                               "sources": [e["source"] for e in path]})
        total = sum(len(v) for v in reached.values())
        for t in reached:
            reached[t].sort(key=lambda r: (r["hops"], r["id"]))
        return {"query": ref, "found": True, "start": start, "hops": hops, "total": total,
                "counts": {t: len(v) for t, v in sorted(reached.items())},
                "reached": {t: v[:limit] for t, v in sorted(reached.items())},
                "truncated": total > sum(min(len(v), limit) for v in reached.values()),
                "gaps": self.meta.get("gaps") or []}

    def token(self, e):
        """What the cited line has to contain for the link to still hold, or None when it cannot be checked."""
        other = e["to"] if e["from"].startswith(("file:", "test:")) else e["from"]
        n = self.nodes.get(other) or {}
        t = n.get("type")
        if e["type"] == "handled_by":
            return (self.nodes.get(e["from"]) or {}).get("handler")
        if t == "table":
            return n["name"]
        if t == "column":
            return n["name"].split(".", 1)[1]
        if e["type"] == "covers":
            return os.path.splitext(os.path.basename(n.get("name", "")))[0]
        return None

    def drift(self, files=None, refs=None):
        """Re-read every cited file:line that the changed files or the named items rely on."""
        files = set(files or [])
        want = set()
        for r in refs or []:
            nid = self.resolve(r)
            if nid:
                want.add(nid)
        rows = []
        cache = {}
        for e in self.edges:
            m = FILE_LINE_RE.match(e["source"])
            if not m:
                continue
            path, line = m.group(1), int(m.group(2))
            if not (path in files or e["from"] in want or e["to"] in want):
                continue
            tok = self.token(e)
            row = {"link": "%s -%s-> %s" % (e["from"], e["type"], e["to"]), "source": e["source"], "token": tok}
            if not tok:
                row["status"] = "not checked"
                row["why"] = "no name to look for on this link"
            else:
                if path not in cache:
                    full = os.path.join(REPO, path)
                    cache[path] = open(full, encoding="utf-8", errors="replace").read().splitlines() if os.path.isfile(full) else None
                lines = cache[path]
                pat = re.compile(r"\b%s\b" % re.escape(tok), re.I)
                if lines is None:
                    row["status"], row["why"] = "missing", "%s no longer exists" % path
                elif any(pat.search(ln) for ln in lines[max(0, line - 1 - WINDOW):line + WINDOW]):
                    row["status"], row["why"] = "current", "%s is still at line %d" % (tok, line)
                else:
                    now = [i + 1 for i, ln in enumerate(lines) if pat.search(ln)]
                    if now:
                        row["status"], row["why"] = "moved", "%s is now at line %s" % (tok, ", ".join(map(str, now[:5])))
                    else:
                        row["status"], row["why"] = "stale", "%s is no longer in %s" % (tok, path)
            rows.append(row)
        summary = defaultdict(int)
        for r in rows:
            summary[r["status"]] += 1
        verdict = "stale" if summary.get("stale") or summary.get("missing") else ("moved" if summary.get("moved") else "current")
        return {"files": sorted(files), "items": sorted(want), "checked": len(rows), "summary": dict(summary),
                "verdict": verdict, "rows": rows,
                "what_to_do": {"stale": "Do not trust the stale links: confirm in the code, record a decision line, and run "
                                        "python3 sdlc/framework/tools/kb_sync.py before the PR.",
                               "moved": "The links still hold at new lines; kb_sync.py refreshes the line numbers.",
                               "current": "Every cited line still says what the graph says."}[verdict]}
