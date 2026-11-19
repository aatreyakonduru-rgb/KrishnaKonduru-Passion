#!/usr/bin/env python3
"""Look things up in the Acme Claims ontology without loading all of it.

The SDLC skills call this first, then check what it returns against the source code.
It reads only `CROSS-LAYER/ACME_ONTOLOGY.yaml` (built by `tools/kbgen/gen_ontology.py`) and
adds nothing of its own: every line it prints is copied from the ontology and keeps its source.

    python3 ontology_lookup.py find "<words>"              # objects, phrases, tables, columns, screens, endpoints, jobs, states
    python3 ontology_lookup.py context <name>              # the slice around one item: what it is, screens, endpoints, tables, jobs, rules
    python3 ontology_lookup.py impact <TABLE|TABLE.COLUMN|"METHOD /api/..."|/route|job> [--depth 3]
    python3 ontology_lookup.py scenarios <object|table>    # states, flows, rules and phrases to test against
    python3 ontology_lookup.py touches [--base REF] [FILE ...]   # what a change touches; is a rebuild due
    python3 ontology_lookup.py check
    python3 ontology_lookup.py walk <item> [--hops 2] [--types table,screen,test]   # the link graph
    python3 ontology_lookup.py drift [--base REF] [FILE ...] [--item NAME]          # are cited lines still true?                       # exit 1 when the ontology is older than its KB sources

Every command takes --json. Names match without case; a table may be given with or without CL_.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import defaultdict, deque

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
ONTOLOGY = "docs/knowledge-base/CROSS-LAYER/ACME_ONTOLOGY.yaml"
GENERATOR = "sdlc/framework/tools/kbgen/gen_ontology.py"
JOB_IO_NOTE = "job reads A and writes B — not proof that A feeds B"
Loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def load(path=None):
    with open(path or os.path.join(REPO, ONTOLOGY), encoding="utf-8") as fh:
        return yaml.load(fh, Loader=Loader)


STOP = {"the", "and", "for", "what", "which", "how", "is", "are", "of", "in", "on", "my", "our", "a", "an", "to", "with", "show", "me", "do", "does", "why"}


def norm(s):
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


class Ontology:
    def __init__(self, data):
        self.d = data
        bl, dl, al = data["business_layer"], data["data_layer"], data["application_layer"]
        self.objects = {o["id"]: o for o in bl["objects"]}
        self.tables = {t["name"]: t for t in dl["tables"]}
        self.screens = {s["route"]: s for s in al["screens"]}
        self.endpoints = {e["id"]: e for e in al["endpoints"]}
        self.jobs = {j["id"]: j for j in dl["jobs"]}
        self.states = bl.get("states") or {}
        self.chains = data.get("impact", {}).get("chains", [])
        self.table_summary = {t["table"]: t for t in data.get("impact", {}).get("table_summary", [])}
        self.job_out, self.job_in = defaultdict(list), defaultdict(list)
        for e in dl["job_io"]:
            self.job_out[e["from"]].append(e)
            self.job_in[e["to"]].append(e)
        self.lin_out, self.lin_in = defaultdict(list), defaultdict(list)
        for e in dl["column_lineage"]:
            self.lin_out[e["source"]].append(e)
            self.lin_in[e["target"]].append(e)
        self.ep_by_screen = {}
        self.screens_by_ep = defaultdict(set)
        for s in al["screens"]:
            for ep in s.get("endpoints") or []:
                self.screens_by_ep[ep].add(s["route"])
        for e in al["endpoints"]:
            for r in e.get("screens") or []:
                self.screens_by_ep[e["id"]].add(r)

    # ---- names
    def table_name(self, name):
        u = str(name).strip().upper()
        if u in self.tables:
            return u
        if "CL_" + u in self.tables:
            return "CL_" + u
        for t in self.tables:  # schema-qualified lineage names, e.g. CLAIMS_DATA_STG.WORK_VB_PG
            if u.endswith("." + t):
                return t
        return None

    def column(self, ref):
        if "." not in str(ref):
            return None, None
        t, c = str(ref).rsplit(".", 1)
        t = self.table_name(t)
        if not t:
            return None, None
        for col in self.tables[t].get("columns") or []:
            if col["name"].upper() == c.strip().upper():
                return t, col
        return t, None

    def endpoint_id(self, ref):
        r = norm(ref)
        for e in self.endpoints:
            if norm(e) == r:
                return e
        hits = [e for e in self.endpoints if r and (r in norm(e) or norm(self.endpoints[e].get("handler")) == r)]
        return hits[0] if len(hits) == 1 else None

    def object_id(self, ref):
        r = norm(ref).replace("_", " ")
        for o in self.objects.values():
            names = [o["id"].replace("_", " "), o.get("label"), o.get("entity_id")] + list(o.get("aliases") or [])
            if r in {norm(n).replace("_", " ") for n in names if n}:
                return o["id"]
        return None

    def resolve(self, ref):
        """(kind, key) for one name, most specific kind first."""
        s = str(ref).strip()
        if s.startswith("/") and s in self.screens:
            return "screen", s
        if re.match(r"^(GET|POST|PUT|PATCH|DELETE)\s", s, re.I) or s.startswith("/api/"):
            e = self.endpoint_id(s)
            if e:
                return "endpoint", e
        t, c = self.column(s)
        if c:
            return "column", "%s.%s" % (t, c["name"])
        t = self.table_name(s)
        if t:
            return "table", t
        o = self.object_id(s)
        if o:
            return "object", o
        if s in self.jobs:
            return "job", s
        for j in self.jobs.values():
            if s == j.get("path") or os.path.basename(str(j.get("path"))) == s:
                return "job", j["id"]
        if s.upper() in self.states:
            return "state", s.upper()
        e = self.endpoint_id(s)
        if e:
            return "endpoint", e
        return None, None

    # ---- find
    def find(self, words, limit=25):
        q = norm(words)
        toks = [w for w in re.split(r"[^a-z0-9_/]+", q) if len(w) > 1]
        hits = []

        def add(score, kind, key, label, source):
            hits.append({"score": score, "kind": kind, "key": key, "label": label, "source": source})

        def score(texts):
            texts = [norm(t) for t in texts if t]
            if q in texts:
                return 3
            if any(len(t) > 2 and re.search(r"\b%s\b" % re.escape(t), q) for t in texts):
                return 2
            if any(q in t for t in texts):
                return 1
            return 0

        for o in self.objects.values():
            sc = score([o["id"].replace("_", " "), o.get("label"), o.get("entity_id"), o.get("table")] + list(o.get("aliases") or []))
            if sc:
                add(sc + 1, "object", o["id"], o.get("label"), o.get("source"))
        for p in self.d["business_layer"].get("phrases") or []:
            sc = score(p.get("phrases") or [])
            if sc:
                add(sc, "phrase", p["id"], "; ".join(p["phrases"]) + " -> " + json.dumps(p.get("resolves_to")), p.get("source"))
        for t in self.tables.values():
            sc = score([t["name"], t.get("module"), t.get("ui_section"), t.get("cff_sheet")])
            if sc:
                add(sc, "table", t["name"], t.get("module") or "", "; ".join(t.get("sources") or []))
            for c in t.get("columns") or []:
                contract = c.get("contract") or {}
                sc = score([c["name"], "%s.%s" % (t["name"], c["name"]), contract.get("fe_display"), contract.get("api_field")])
                if sc >= 2 or (sc and len(q) > 3 and q == norm(contract.get("fe_display"))):
                    add(sc - 1, "column", "%s.%s" % (t["name"], c["name"]), contract.get("fe_display") or c.get("description") or "",
                        "; ".join(t.get("sources") or []))
        for s in self.screens.values():
            sc = score([s["route"], s.get("page")] + [x for x in s["route"].split("/") if x])
            if sc:
                add(sc, "screen", s["route"], s.get("page"), s.get("source"))
        for e in self.endpoints.values():
            sc = score([e["id"], e.get("handler"), e.get("app")])
            if sc:
                add(sc, "endpoint", e["id"], e.get("code"), e.get("source"))
        for j in self.jobs.values():
            sc = score([j["id"], j.get("path"), j.get("description")])
            if sc:
                add(sc, "job", j["id"], j.get("description"), j.get("source"))
        for m in self.d["business_layer"].get("metrics") or []:
            sc = score([m["id"].replace("_", " "), m.get("label")] + list(m.get("aliases") or []))
            if sc:
                add(sc + 1, "metric", m["id"], m.get("label"), m.get("source"))
        for t in self.d.get("data_layer", {}).get("finance_tables") or []:
            sc = score([t["name"]])
            if sc:
                add(sc, "finance_table", t["name"], t.get("schema"), t.get("source"))
        for k, v in self.states.items():
            vals = v.get("values") or {}
            sc = score([k, v.get("description")] + list(vals.keys()) + [x for x in vals.values() if isinstance(x, str)])
            if sc:
                add(sc, "state", k, v.get("description"), v.get("source"))
        for ch in self.chains:
            sc = score([ch.get("attribute"), ch.get("business_name"), ch.get("id")])
            if sc:
                add(sc, "chain", ch["id"], "%s (%s)" % (ch.get("business_name"), ch.get("attribute")), ch.get("source"))
        if not hits and len(toks) > 1:
            hits.extend(self._word_hits(toks))
        if not hits and len(toks) > 1:
            for w in toks:
                for h in self.find(w, limit)["matches"]:
                    if h["score"] >= 2:
                        hits.append(dict(h, score=h["score"] - 1, matched=w))
        seen, out = set(), []
        for h in sorted(hits, key=lambda h: (-h["score"], h["kind"], h["key"])):
            if (h["kind"], h["key"]) in seen:
                continue
            seen.add((h["kind"], h["key"]))
            out.append(h)
        return {"query": words, "matches": out[:limit]}

    def _word_hits(self, toks):
        """Every word of the question appears in one item (prefix match, so pending finds PENDAPRVR1)."""
        stems = [t[:max(4, len(t) - 3)] for t in toks if t not in STOP]
        if not stems:
            return []

        def all_in(texts):
            words = set(re.split(r"[^a-z0-9]+", " ".join(norm(t) for t in texts if t)))
            return all(any(w.startswith(s) for w in words) for s in stems)
        out = []
        for m in self.d["business_layer"].get("metrics") or []:
            if all_in([m.get("label"), m.get("means")] + list(m.get("aliases") or [])):
                out.append({"score": 1, "kind": "metric", "key": m["id"], "label": m.get("label"), "source": m.get("source")})
        for o in self.objects.values():
            if all_in([o.get("label")] + list(o.get("aliases") or [])):
                out.append({"score": 1, "kind": "object", "key": o["id"], "label": o.get("label"), "source": o.get("source")})
        for k, v in self.states.items():
            vals = v.get("values") or {}
            if all_in([k, v.get("description")] + list(vals.keys()) + [x for x in vals.values() if isinstance(x, str)]):
                out.append({"score": 1, "kind": "state", "key": k, "label": v.get("description"), "source": v.get("source")})
        return out

    # ---- links
    def table_endpoints(self, t):
        reads = [e["id"] for e in self.endpoints.values() if t in (e.get("tables_read") or [])]
        writes = [e["id"] for e in self.endpoints.values() if t in (e.get("tables_written") or [])]
        return reads, writes

    def table_screens(self, t):
        routes = {s["route"] for s in self.screens.values() if t in (s.get("tables") or [])}
        for oid in self.tables.get(t, {}).get("represents") or []:
            routes.update(self.objects.get(oid, {}).get("screens") or [])
        return sorted(routes)

    def chains_for(self, t, col=None):
        out = []
        for ch in self.chains:
            attr = str(ch.get("attribute") or "")
            at, _, ac = attr.partition(".")
            if at == t and (col is None or ac == col):
                out.append(ch)
        return out

    def states_for(self, t):
        cols = {c["name"] for c in self.tables.get(t, {}).get("columns") or []}
        out = []
        for k, v in self.states.items():
            if k in cols:
                out.append(dict(v, code=k, column="%s.%s" % (t, k), match="column name"))
        for o in self.objects.values():
            st = o.get("status") or {}
            if t in (o.get("table"), st.get("table")) and st.get("column"):
                key = "%s_%s" % (st["column"], str(o.get("table", "")).replace("CL_", "", 1))
                if key in self.states:
                    out.append(dict(self.states[key], code=key, column="%s.%s" % (st["table"], st["column"]),
                                    match="object status column (%s)" % o["id"]))
        return out

    def relationships_for(self, t):
        return [r for r in self.d["business_layer"].get("relationships") or [] if t in (r.get("from_table"), r.get("to_table"))]

    def processes_for(self, t):
        out = []
        for p in self.d["business_layer"].get("processes") or []:
            if t in json.dumps(p):
                out.append({"id": p["id"], "name": p.get("name"), "source": p.get("source")})
        return out

    def rules_for(self, t=None):
        out = []
        for r in self.d["business_layer"].get("rules") or []:
            text = r.get("rule", "")
            if r.get("kind") == "mandatory_filters" or (t and re.search(r"\b%s\b" % re.escape(t), text)):
                out.append(r)
        return out

    def phrases_for(self, t):
        return [p for p in self.d["business_layer"].get("phrases") or [] if (p.get("resolves_to") or {}).get("table") == t]

    def systems_for(self, t):
        return [s for s in self.d["data_layer"].get("systems") or [] if t in (s.get("tables") or [])]

    def questions_for(self, terms):
        terms = [x for x in terms if x and len(x) > 3]
        out = []
        for q in self.d.get("open_questions") or []:
            text = q.get("question", "")
            if any(re.search(r"\b%s\b" % re.escape(x), text, re.I) for x in terms):
                out.append(q)
        return out

    # ---- context
    def context(self, ref):
        kind, key = self.resolve(ref)
        if not kind:
            return {"query": ref, "found": False, "suggestions": self.find(ref, 10)["matches"]}
        out = {"query": ref, "found": True, "kind": kind, "key": key}
        if kind == "object":
            o = self.objects[key]
            tables = [o["table"]] + list(o.get("related_tables") or [])
            out.update(item={k: o.get(k) for k in ("id", "entity_id", "label", "aliases", "table", "key", "display",
                                                   "current_row", "status", "confidence", "source")},
                       tables=tables, screens=o.get("screens") or [], endpoints=o.get("endpoints") or [],
                       relationships=[r for t in tables for r in self.relationships_for(t)],
                       states=[s for t in [o["table"]] + [(o.get("status") or {}).get("table")] if t for s in self.states_for(t)],
                       phrases=[p for t in tables for p in self.phrases_for(t)],
                       processes=[p for t in tables for p in self.processes_for(t)],
                       chains=[c["id"] + " " + c["attribute"] for t in tables for c in self.chains_for(t)],
                       open_questions=self.questions_for([o["label"]] + tables))
            out["relationships"] = list({r["id"]: r for r in out["relationships"]}.values())
            out["processes"] = list({p["id"]: p for p in out["processes"]}.values())
        elif kind == "table":
            t = self.tables[key]
            reads, writes = self.table_endpoints(key)
            out.update(item={k: t.get(k) for k in ("name", "module", "ui_section", "cff_sheet", "layer", "pk", "represents", "status", "sources")},
                       columns=[{"name": c["name"], "type": c.get("type"), "phi": bool(c.get("phi") or c.get("phi_mask")),
                                 "fe_display": (c.get("contract") or {}).get("fe_display")} for c in t.get("columns") or []],
                       screens=self.table_screens(key), endpoints_read=reads, endpoints_write=writes,
                       etl_read_by=t.get("etl_read_by") or [], etl_written_by=t.get("etl_written_by") or [],
                       jobs_reading=sorted({e["via"] for e in self.job_out.get(key, [])}),
                       jobs_writing=sorted({e["via"] for e in self.job_in.get(key, [])}),
                       systems=[{"id": s["id"], "name": s["name"], "direction": s["direction"], "source": s["source"]} for s in self.systems_for(key)],
                       relationships=self.relationships_for(key), states=self.states_for(key), phrases=self.phrases_for(key),
                       processes=self.processes_for(key), chains=[c["id"] + " " + c["attribute"] for c in self.chains_for(key)],
                       summary=self.table_summary.get(key), open_questions=self.questions_for([key]))
        elif kind == "column":
            t, c = self.column(key)
            out.update(item=dict(c, table=t), lineage_in=self.lin_in.get(key, []), lineage_out=self.lin_out.get(key, []),
                       chains=self.chains_for(t, c["name"]), states=[s for s in self.states_for(t) if s["column"] == key],
                       screens=self.table_screens(t), table_endpoints=dict(zip(("read", "write"), self.table_endpoints(t))))
        elif kind == "screen":
            s = self.screens[key]
            out.update(item=s, endpoints=[{"id": e, "code": self.endpoints.get(e, {}).get("code")} for e in s.get("endpoints") or []],
                       tables=s.get("tables") or [],
                       objects=sorted(o["id"] for o in self.objects.values() if key in (o.get("screens") or [])))
        elif kind == "endpoint":
            e = self.endpoints[key]
            out.update(item=e, screens=sorted(self.screens_by_ep.get(key, set())),
                       objects=sorted(o["id"] for o in self.objects.values() if key in (o.get("endpoints") or [])))
        elif kind == "job":
            j = self.jobs[key]
            out.update(item=j, io=[e for es in self.job_out.values() for e in es if e["via"] == key])
        elif kind == "state":
            v = self.states[key]
            out.update(item=dict(v, code=key),
                       tables=sorted(t for t, tb in self.tables.items() if key in {c["name"] for c in tb.get("columns") or []}))
        return out

    # ---- impact
    def _walk(self, starts, edges, depth):
        seen, out, dq = set(starts), [], deque((s, 0, None) for s in starts)
        while dq:
            node, d, _ = dq.popleft()
            if d >= depth:
                continue
            for e in edges(node):
                nxt = e["next"]
                if nxt in seen:
                    continue
                seen.add(nxt)
                out.append(dict(e, depth=d + 1))
                dq.append((nxt, d + 1, node))
        return out

    def impact(self, ref, depth=3):
        kind, key = self.resolve(ref)
        if not kind:
            return {"query": ref, "found": False, "suggestions": self.find(ref, 10)["matches"]}
        out = {"query": ref, "found": True, "kind": kind, "key": key, "depth": depth,
               "notes": ["job_io: " + JOB_IO_NOTE,
                         "column_lineage: column-to-column writes Snowflake observed in T01",
                         "endpoint tables come from the router folder (table_evidence_scope), not the single handler",
                         "Every row is a lead for /impact-radar to verify in the source code; none is proof on its own."]}
        tables, columns = [], []
        if kind == "table":
            tables = [key]
        elif kind == "column":
            tables, columns = [key.rsplit(".", 1)[0]], [key]
        elif kind == "object":
            o = self.objects[key]
            tables = [o["table"]] + list(o.get("related_tables") or [])
        elif kind == "endpoint":
            e = self.endpoints[key]
            tables = list(e.get("tables_written") or []) or list(e.get("tables_read") or [])
            out["direct"] = {"screens_calling": sorted(self.screens_by_ep.get(key, set())), "handler": e.get("code"),
                             "tables_read": e.get("tables_read") or [], "tables_written": e.get("tables_written") or []}
        elif kind == "screen":
            s = self.screens[key]
            tables = list(s.get("tables") or [])
            out["direct"] = {"endpoints": s.get("endpoints") or [], "tables": tables}
        elif kind == "job":
            j = self.jobs[key]
            tables = list(j.get("writes") or [])
            out["direct"] = {"reads": j.get("reads") or [], "writes": tables}
        elif kind == "state":
            tables = sorted(t for t, tb in self.tables.items() if key in {c["name"] for c in tb.get("columns") or []})
            columns = ["%s.%s" % (t, key) for t in tables]
        tables = [t for t in tables if t]
        per_table = []
        for t in tables:
            reads, writes = self.table_endpoints(t)
            tb = self.tables.get(t, {})
            per_table.append({
                "table": t,
                "written_by": {"endpoints": writes, "etl": tb.get("etl_written_by") or [],
                               "jobs": sorted({e["via"] for e in self.job_in.get(t, [])})},
                "read_by": {"endpoints": reads, "screens": self.table_screens(t), "etl": tb.get("etl_read_by") or [],
                            "jobs": sorted({e["via"] for e in self.job_out.get(t, [])})},
                "systems": [{"id": s["id"], "name": s["name"], "direction": s["direction"], "source": s["source"]} for s in self.systems_for(t)],
                "chains": [{"id": c["id"], "attribute": c["attribute"], "risk": c.get("risk"), "read_by": c.get("read_by"),
                            "if_changed": c.get("if_changed"), "source": c.get("source")} for c in self.chains_for(t)],
                "summary": self.table_summary.get(t),
            })
        out["tables"] = per_table
        down_tables = self._walk(tables, lambda n: [{"from": e["from"], "via": e["via"], "next": e["to"], "source": e["source"]}
                                                    for e in self.job_out.get(n, [])], depth)
        up_tables = self._walk(tables, lambda n: [{"to": e["to"], "via": e["via"], "next": e["from"], "source": e["source"]}
                                                  for e in self.job_in.get(n, [])], depth)
        out["downstream_tables"] = [{"table": e["next"], "via": e["via"], "from": e["from"], "depth": e["depth"], "source": e["source"]} for e in down_tables]
        out["upstream_tables"] = [{"table": e["next"], "via": e["via"], "to": e["to"], "depth": e["depth"], "source": e["source"]} for e in up_tables]
        cols = columns or [k for t in tables for k in list(self.lin_out) + list(self.lin_in) if self._col_table(k) == t]
        cols = sorted(set(cols))
        down_cols = self._walk(cols, lambda n: [{"from": n, "next": e["target"], "queries_30d": e.get("queries_30d"),
                                                 "last_seen": e.get("last_seen")} for e in self.lin_out.get(n, [])], depth)
        up_cols = self._walk(cols, lambda n: [{"to": n, "next": e["source"], "queries_30d": e.get("queries_30d"),
                                               "last_seen": e.get("last_seen")} for e in self.lin_in.get(n, [])], depth)
        out["downstream_columns"] = [{"column": e["next"], "from": e["from"], "depth": e["depth"], "queries_30d": e["queries_30d"],
                                      "last_seen": e["last_seen"]} for e in down_cols]
        out["upstream_columns"] = [{"column": e["next"], "to": e["to"], "depth": e["depth"], "queries_30d": e["queries_30d"],
                                    "last_seen": e["last_seen"]} for e in up_cols]
        out["open_questions"] = self.questions_for(tables)
        return out

    def _col_table(self, ref):
        t = str(ref).rsplit(".", 1)[0]
        return self.table_name(t) or t

    # ---- scenarios
    def scenarios(self, ref):
        kind, key = self.resolve(ref)
        if kind not in ("object", "table", "column", "state"):
            return {"query": ref, "found": False, "reason": "give an object, table, column or status code",
                    "suggestions": self.find(ref, 10)["matches"]}
        if kind == "object":
            o = self.objects[key]
            tables = [o["table"]] + [x for x in [(o.get("status") or {}).get("table")] if x]
        elif kind == "column":
            tables = [key.rsplit(".", 1)[0]]
        elif kind == "state":
            tables = sorted(t for t, tb in self.tables.items() if key in {c["name"] for c in tb.get("columns") or []})
        else:
            tables = [key]
        cases = []
        states = {}
        for t in tables:
            for s in self.states_for(t):
                if kind == "state" and s["code"] != key:
                    continue
                states[s["code"]] = s
        if kind == "state" and key not in states:
            states[key] = dict(self.states[key], code=key, column=None, match="status code")
        for code, s in states.items():
            vals = s.get("values") or {}
            for v, meaning in vals.items():
                cases.append({"kind": "state value", "check": "%s = %s (%s)" % (code, v, meaning), "source": s.get("source")})
            cases.append({"kind": "invalid value", "check": "a %s value not in [%s] is rejected" % (code, ", ".join(vals)), "source": s.get("source")})
            if s.get("flow"):
                cases.append({"kind": "flow", "check": "moves only as: %s" % s["flow"], "source": s.get("source")})
                steps = [x.strip() for x in re.split(r"→|->", re.sub(r"\(.*?\)", "", s["flow"])) if x.strip()]
                for a, b in zip(steps, steps[2:]):
                    cases.append({"kind": "flow (negative)", "check": "cannot go from %s straight to %s" % (a, b), "source": s.get("source")})
        for t in tables:
            for p in self.phrases_for(t):
                cases.append({"kind": "business phrase", "check": "\"%s\" selects %s" % ("; ".join(p["phrases"]), p.get("sql")),
                              "source": p.get("source")})
            for r in self.rules_for(t):
                cases.append({"kind": "rule (%s)" % r.get("kind"), "check": r["rule"], "source": r.get("source")})
            for c in self.chains_for(t):
                for step in c.get("read_by") or []:
                    cases.append({"kind": "downstream reader (%s)" % c["id"], "check": "%s %s still works: %s" % (step["layer"], step["item"], step["action"]),
                                  "source": c.get("source")})
            for c in self.tables.get(t, {}).get("columns") or []:
                if c.get("mandatory"):
                    cases.append({"kind": "mandatory column", "check": "%s.%s cannot be empty" % (t, c["name"]),
                                  "source": "; ".join(self.tables[t].get("sources") or [])})
        seen, uniq = set(), []
        for c in cases:
            k = (c["kind"], c["check"])
            if k not in seen:
                seen.add(k)
                uniq.append(c)
        return {"query": ref, "found": True, "kind": kind, "key": key, "tables": tables, "cases": uniq,
                "note": "From the ontology only. Each case still needs an AC behind it before it becomes a scenario."}

    # ---- touches
    def touches(self, files):
        sources = set(self.d["metadata"].get("sources") or [])
        kb_changed = sorted(f for f in files if f in sources)
        ontology_changed = ONTOLOGY in files
        code = defaultdict(list)
        for e in self.endpoints.values():
            path = str(e.get("code", "")).split(":")[0]
            code[path].append(("endpoint", e["id"]))
        for s in self.screens.values():
            code[s.get("page")].append(("screen", s["route"]))
        for j in self.jobs.values():
            code[j.get("path")].append(("job", j["id"]))
            code[os.path.join("scripts", "sql", os.path.basename(str(j.get("path"))))].append(("job", j["id"]))
        hit = []
        for f in files:
            for kind, key in code.get(f, []):
                hit.append({"file": f, "kind": kind, "key": key})
            for t in self.tables:
                if f.endswith(".sql") and re.search(r"\b%s\b" % t, os.path.basename(f), re.I):
                    hit.append({"file": f, "kind": "table", "key": t})
        tables = set()
        for h in hit:
            if h["kind"] == "endpoint":
                e = self.endpoints[h["key"]]
                tables.update(e.get("tables_written") or [])
            elif h["kind"] == "screen":
                tables.update(self.screens[h["key"]].get("tables") or [])
            elif h["kind"] == "job":
                tables.update(self.jobs[h["key"]].get("writes") or [])
            elif h["kind"] == "table":
                tables.add(h["key"])
        code_changed = any(f.startswith(("api/", "web/src/")) for f in files)
        verdict = "current"
        if kb_changed and not ontology_changed:
            verdict = "rebuild"
        elif code_changed and not kb_changed:
            verdict = "after-merge"
        return {
            "files": len(files), "kb_sources_changed": kb_changed, "ontology_in_diff": ontology_changed,
            "touched": hit, "tables_affected": sorted(t for t in tables if t in self.tables),
            "verdict": verdict,
            "what_to_do": {
                "rebuild": "KB files the ontology is built from changed in this diff: run python3 %s and commit "
                           "ACME_ONTOLOGY.yaml/.html in the same PR." % GENERATOR,
                "after-merge": "Code changed but no KB source did: /kb-refresh regenerates the matrix and registries after "
                               "deployment, then the ontology.",
                "current": "Nothing in this diff feeds the ontology.",
            }[verdict],
        }


def check(path=None):
    """Rebuild into a temp folder and compare with the committed YAML (the generated date aside)."""
    path = path or os.path.join(REPO, ONTOLOGY)
    tmp = tempfile.mkdtemp()
    r = subprocess.run([sys.executable, os.path.join(REPO, GENERATOR), "--out-dir", tmp], capture_output=True, text=True, cwd=REPO)
    if r.returncode != 0:
        return {"fresh": False, "error": (r.stderr or r.stdout).strip()[-400:]}

    def body(p):
        with open(p, encoding="utf-8") as fh:
            return [ln for ln in fh if not ln.startswith("  generated:")]
    a, b = body(path), body(os.path.join(tmp, "ACME_ONTOLOGY.yaml"))
    return {"fresh": a == b, "committed_lines": len(a), "rebuilt_lines": len(b),
            "fix": None if a == b else "python3 %s, then commit ACME_ONTOLOGY.yaml and .html" % GENERATOR}


def changed_files(base):
    r = subprocess.run(["git", "diff", "--name-only", "%s...HEAD" % base], capture_output=True, text=True, cwd=REPO)
    if r.returncode != 0:
        sys.exit("git diff against %s failed: %s" % (base, r.stderr.strip()))
    return [f for f in r.stdout.splitlines() if f]


# ---- text output
def _lines(title, items, fmt=str):
    if not items:
        return []
    return ["%s:" % title] + ["  - " + fmt(i) for i in items]


def render_graph(cmd, res):
    if not res.get("found", True):
        s = res.get("suggestions") or []
        return "Not in the link graph: %r.%s" % (res["query"], (" Closest: " + ", ".join(s)) if s else "")
    if cmd == "walk":
        out = ["%s within %d hops: %d items %s" % (res["start"], res["hops"], res["total"], json.dumps(res["counts"]))]
        for kind, rows in res["reached"].items():
            out.append("%s:" % kind)
            out += ["  d%d %s  via %s  [%s]" % (r["hops"], r["id"], r["path"][-1], r["sources"][-1]) for r in rows[:40]]
            if len(rows) > 40:
                out.append("  ... %d more (use --json)" % (len(rows) - 40))
        out += ["gap: " + g for g in res.get("gaps") or []]
        return "\n".join(out)
    out = ["verdict: %s — %s" % (res["verdict"], res["what_to_do"]),
           "checked %d cited lines: %s" % (res["checked"], json.dumps(res["summary"]))]
    out += ["  %s %s  [%s] %s" % (r["status"], r["link"], r["source"], r.get("why") or "")
            for r in res["rows"] if r["status"] != "current"]
    return "\n".join(out)


def render(cmd, res):
    if cmd in ("walk", "drift"):
        return render_graph(cmd, res)
    if cmd == "find":
        if not res["matches"]:
            return "No match in the ontology for %r. Say so; it is a KB gap, not a reason to guess." % res["query"]
        return "\n".join(["%-8s %s — %s  [%s]" % (m["kind"], m["key"], m.get("label") or "", m.get("source") or "")
                          for m in res["matches"]])
    if not res.get("found", True):
        s = res.get("suggestions") or []
        return "Not found: %r.%s" % (res["query"], (" Closest: " + ", ".join("%s %s" % (m["kind"], m["key"]) for m in s[:8])) if s else "")
    if cmd == "touches":
        out = ["verdict: %s — %s" % (res["verdict"], res["what_to_do"])]
        out += _lines("KB sources changed", res["kb_sources_changed"])
        out += _lines("touched", res["touched"], lambda h: "%s -> %s %s" % (h["file"], h["kind"], h["key"]))
        out += _lines("tables behind the change (run impact on each)", res["tables_affected"])
        return "\n".join(out)
    if cmd == "check":
        return "ontology is current" if res.get("fresh") else "ontology is STALE — %s" % (res.get("fix") or res.get("error"))
    if cmd == "scenarios":
        out = ["%s %s — tables %s" % (res["kind"], res["key"], ", ".join(res["tables"])), res["note"]]
        out += ["  - [%s] %s  (%s)" % (c["kind"], c["check"], c.get("source") or "") for c in res["cases"]]
        return "\n".join(out)
    if cmd == "impact":
        out = ["%s %s (depth %d)" % (res["kind"], res["key"], res["depth"])] + ["note: " + n for n in res["notes"]]
        if res.get("direct"):
            out.append("direct: " + json.dumps(res["direct"]))
        for t in res["tables"]:
            out.append("table %s" % t["table"])
            out.append("  written by: " + json.dumps(t["written_by"]))
            out.append("  read by:    " + json.dumps(t["read_by"]))
            out += ["  system %s %s (%s)" % (s["direction"], s["name"], s["id"]) for s in t["systems"]]
            out += ["  chain %s %s risk %s" % (c["id"], c["attribute"], c.get("risk")) for c in t["chains"]]
        out += _lines("downstream tables (job_io)", res["downstream_tables"],
                      lambda e: "d%d %s  via %s from %s" % (e["depth"], e["table"], e["via"], e["from"]))
        out += _lines("upstream tables (job_io)", res["upstream_tables"],
                      lambda e: "d%d %s  via %s into %s" % (e["depth"], e["table"], e["via"], e["to"]))
        out += _lines("downstream columns (lineage)", res["downstream_columns"][:60],
                      lambda e: "d%d %s  from %s  (%s queries/30d, last %s)" % (e["depth"], e["column"], e["from"], e["queries_30d"], e["last_seen"]))
        if len(res["downstream_columns"]) > 60:
            out.append("  ... %d more (use --json)" % (len(res["downstream_columns"]) - 60))
        out += _lines("upstream columns (lineage)", res["upstream_columns"][:60],
                      lambda e: "d%d %s  into %s" % (e["depth"], e["column"], e["to"]))
        if len(res["upstream_columns"]) > 60:
            out.append("  ... %d more (use --json)" % (len(res["upstream_columns"]) - 60))
        out += _lines("open questions", res["open_questions"], lambda q: "%s %s (owner %s)" % (q["id"], q["question"][:140], q.get("owner")))
        return "\n".join(out)
    # context
    out = ["%s %s" % (res["kind"], res["key"])]
    for k, v in res.items():
        if k in ("query", "found", "kind", "key") or v in (None, [], {}):
            continue
        if k == "columns":
            out.append("columns (%d): %s" % (len(v), ", ".join(c["name"] + (" [PHI]" if c["phi"] else "") for c in v)))
        elif isinstance(v, list):
            out += _lines(k, v, lambda i: i if isinstance(i, str) else json.dumps(i, ensure_ascii=False)[:300])
        else:
            out.append("%s: %s" % (k, json.dumps(v, ensure_ascii=False)[:1200]))
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ontology", help="another ACME_ONTOLOGY.yaml (default: the committed one)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("find"); p.add_argument("words", nargs="+"); p.add_argument("--limit", type=int, default=25)
    p = sub.add_parser("context"); p.add_argument("name", nargs="+")
    p = sub.add_parser("impact"); p.add_argument("target", nargs="+"); p.add_argument("--depth", type=int, default=3)
    p = sub.add_parser("scenarios"); p.add_argument("target", nargs="+")
    p = sub.add_parser("touches"); p.add_argument("files", nargs="*"); p.add_argument("--base")
    sub.add_parser("check")
    p = sub.add_parser("walk"); p.add_argument("item", nargs="+"); p.add_argument("--hops", type=int, default=2)
    p.add_argument("--types", help="comma list of node types to show, e.g. table,screen,test,story")
    p = sub.add_parser("drift"); p.add_argument("files", nargs="*"); p.add_argument("--base")
    p.add_argument("--item", action="append", default=[], help="a table, column, endpoint, screen or story to check")
    for s in sub.choices.values():
        s.add_argument("--graph", help="another ACME_LINK_GRAPH.yaml (default: the committed one)")
        s.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "check":
        res = check(a.ontology)
        print(json.dumps(res, indent=1) if a.json else render("check", res))
        return 0 if res.get("fresh") else 1
    if a.cmd in ("walk", "drift"):
        import link_graph
        graph = link_graph.Graph(link_graph.load(a.graph))
        if a.cmd == "walk":
            types = [t.strip() for t in (a.types or "").split(",") if t.strip()] or None
            res = graph.walk(" ".join(a.item), a.hops, types)
        else:
            files = list(a.files) + (changed_files(a.base) if a.base else [])
            res = graph.drift(files, a.item)
        print(json.dumps(res, indent=1, ensure_ascii=False) if a.json else render(a.cmd, res))
        if a.cmd == "drift":
            return 1 if res["verdict"] == "stale" else 0
        return 0 if res.get("found", True) else 3
    onto = Ontology(load(a.ontology))
    if a.cmd == "find":
        res = onto.find(" ".join(a.words), a.limit)
    elif a.cmd == "context":
        res = onto.context(" ".join(a.name))
    elif a.cmd == "impact":
        res = onto.impact(" ".join(a.target), a.depth)
    elif a.cmd == "scenarios":
        res = onto.scenarios(" ".join(a.target))
    else:
        files = list(a.files) + (changed_files(a.base) if a.base else [])
        res = onto.touches(files)
    print(json.dumps(res, indent=1, ensure_ascii=False, default=str) if a.json else render(a.cmd, res))
    return 0 if res.get("found", True) else 3


if __name__ == "__main__":
    sys.exit(main())
