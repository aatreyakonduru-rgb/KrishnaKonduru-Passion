"""Cross-layer impact matrix: change a column, an endpoint or a screen -> what else moves.

Everything in the output is read from something that exists; nothing is inferred from a name.
Sources, all read-only:

  code (authority)
    api/apps/<app>/**/*.py|*.sql, api/modules/<m>/**/*.sql
                                          table tokens per statement verb (read / write), the
                                          registry columns of those tables that the file names
    DB-DOCS/DB_TABLE_REGISTRY.yaml        the tables and their columns (P01 INFORMATION_SCHEMA)
    MODULES/.../10_ENDPOINT_REGISTRY.yaml endpoint -> handler, file, line, app
    MODULES/.../12_COMPONENT_REGISTRY.yaml endpoint symbol -> URL; routes
    web/src/app/**                   which route directory uses which endpoint symbol
    ETL/.../13_ETL_TABLE_IO_CONTRACT.yaml  ETL script -> tables read / written
    DB-DOCS/<env>/13_UI_TO_DATA_FIELD_MAPPING.yaml
                                          FE field -> table.column, only rows the generator
                                          could pin to one table (VERIFIED*)
  design and flow (context, never authority)
    FIGMA-DERIVED/01_FIGMA_ACME_PROTOTYPE.md   screen family -> code path ([SOURCE-VERIFIED] rows)
    CONFLUENCE-DERIVED/03_UI_SCREEN_FLOWS.md   documented flow -> code path
    CONFLUENCE-DERIVED/05_TEST_CASE_CATALOGUE.md  story -> tables the SIT/UAT suites assert on
  hand-written
    CROSS-LAYER/CROSS_LAYER_IMPACT_MATRIX.CURATED.yaml  the documented chains with their if_changed
                                          guidance, carried over as-is and tagged documentation

Evidence on every row is a repo-relative path, with a line where one exists. An API table
link is tagged by scope: `handler` when the handler's own module names the table, else `app`
(the table appears in the app's SQL/Python folder and the endpoint belongs to that app).

Usage:
    python3 gen_cross_module_matrix.py [--env sit] [--out <file>] [--print]
"""
import argparse
import json
import os
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[4]
KB = REPO / "docs" / "knowledge-base"
KB_OUT = Path(os.environ.get("SDLC_KB_OUT") or KB)
DBDOCS = KB / "DB-DOCS"
OUT = KB_OUT / "CROSS-LAYER" / "CROSS_LAYER_IMPACT_MATRIX.yaml"
CURATED = KB / "CROSS-LAYER" / "CROSS_LAYER_IMPACT_MATRIX.CURATED.yaml"
TABLE_REGISTRY = DBDOCS / "DB_TABLE_REGISTRY.yaml"
ENDPOINTS = KB / "MODULES/claims-web/api/10_ENDPOINT_REGISTRY.yaml"
COMPONENTS = KB / "MODULES/claims-web/web/12_COMPONENT_REGISTRY.yaml"
ETL_IO = KB / "ETL/claims-etl/13_ETL_TABLE_IO_CONTRACT.yaml"
FIGMA = KB / "FIGMA-DERIVED/01_FIGMA_ACME_PROTOTYPE.md"
FLOWS = KB / "CONFLUENCE-DERIVED/03_UI_SCREEN_FLOWS.md"
TESTS = KB / "CONFLUENCE-DERIVED/05_TEST_CASE_CATALOGUE.md"
ENV_FILE = REPO / ".devin/rules/snowflake-environments.yaml"
API_APPS = REPO / "api" / "apps"
API_MODULES = REPO / "api" / "modules"
FE_APP = REPO / "web" / "src" / "app"

TABLE_TOKEN = r"((?:VB|VBC|SDLC)_[A-Z0-9_]+)"
WRITE_RE = re.compile(r"\b(?:INSERT\s+INTO|MERGE\s+INTO|UPDATE|DELETE\s+FROM|TRUNCATE\s+TABLE)\s+"
                      r"(?:[\w{}.]+\.)*" + TABLE_TOKEN, re.I)
READ_RE = re.compile(r"\b(?:FROM|JOIN)\s+(?:[\w{}.]+\.)*" + TABLE_TOKEN, re.I)
ANY_RE = re.compile(r"\b" + TABLE_TOKEN + r"\b")
WORD = r"(?<![A-Z0-9_])%s(?![A-Z0-9_])"
MD_ROW = re.compile(r"^\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*$")
TICK = re.compile(r"`([^`]+)`")
API_TAG = re.compile(r"API\s+`([^`]+)`")
FREQ = re.compile(r"`((?:VB|VBC|SDLC)_[A-Z0-9_]+)`\s*\((\d+)\)")
STORY_ROW = re.compile(r"^\|\s*`(ACME-\d+)`\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*$")


def load(p):
    return yaml.safe_load(p.read_text(encoding="utf-8")) if p.is_file() else None


def rel(p):
    return os.path.relpath(str(p), str(REPO)).replace(os.sep, "/")


def docs_dir(env):
    cfg = load(ENV_FILE) or {}
    envs = cfg.get("environments") or cfg
    e = envs.get(env) or {}
    d = e.get("docs_dir") if isinstance(e, dict) else None
    return DBDOCS / d if d else DBDOCS


def norm_url(u):
    u = re.sub(r"\$\{[^}]*\}", "", u or "")
    u = u.split("?")[0].rstrip("/")
    return u.lower()


class Matrix:
    def __init__(self, env):
        self.env = env
        self.tables = defaultdict(lambda: {"columns": {}, "api": [], "endpoints": set(), "screens": set(), "fields": [],
                                           "etl": [], "tests": [], "figma": set(), "flows": set()})
        self.columns = defaultdict(lambda: {"api_files": [], "fields": [], "etl_scripts": set()})
        self.endpoints = {}
        self.screens = {}
        self.notes = []
        self.registry = {}

    def is_route(self, p):
        q = p.split("src/app/")[-1].rstrip("/")
        return any(k.strip("/") == q for k in self.screens)

    def known(self, t):
        return t in self.registry or t in self.tables

    # ---- DB ---------------------------------------------------------------
    def read_registry(self):
        reg = load(TABLE_REGISTRY) or {}
        for t in reg.get("tables") or []:
            self.registry[t["name"]] = {"columns": [c["name"] for c in t.get("columns") or []],
                                        "module": t.get("module"), "layer": t.get("layer"), "status": t.get("status")}

    # ---- API --------------------------------------------------------------
    def scan_api(self):
        files = list(API_APPS.rglob("*.py")) + list(API_APPS.rglob("*.sql")) + list(API_MODULES.rglob("*.sql"))

        def bucket():
            return defaultdict(lambda: {"access": set(), "files": set(), "columns": set()})
        self.app_tables = defaultdict(bucket)
        self.module_tables = defaultdict(bucket)
        self.file_tables = {}
        for f in sorted(files):
            if "test" in f.parts or "__pycache__" in f.parts:
                continue
            text = f.read_text(encoding="utf-8", errors="replace")
            found = {}
            for m in WRITE_RE.finditer(text):
                found.setdefault(m.group(1).upper(), set()).add("write")
            for m in READ_RE.finditer(text):
                found.setdefault(m.group(1).upper(), set()).add("read")
            for m in ANY_RE.finditer(text):
                found.setdefault(m.group(1).upper(), set())
            found = {t: a for t, a in found.items() if not t.startswith(("CL_TEMP", "VBC_TEMP")) and len(t) > 5}
            if not found:
                continue
            if f.is_relative_to(API_APPS):
                app = f.relative_to(API_APPS).parts[0]
                bucket = self.app_tables[app]
            else:
                app = "generic_module:" + f.relative_to(API_MODULES).parts[0]
                bucket = self.module_tables[f.relative_to(API_MODULES).parts[0]]
            self.file_tables[rel(f)] = {t: (a or {"reference"}) for t, a in found.items()}
            for t, access in found.items():
                e = bucket[t]
                e["access"] |= access or {"reference"}
                line = next((i + 1 for i, l in enumerate(text.splitlines()) if t in l), None)
                e["files"].add("%s:%s" % (rel(f), line) if line else rel(f))
                cols = [c for c in self.registry.get(t, {}).get("columns", []) if re.search(WORD % re.escape(c), text)]
                e["columns"] |= set(cols)
                for c in cols:
                    self.columns["%s.%s" % (t, c)]["api_files"].append(rel(f))

    def read_endpoints(self):
        reg = load(ENDPOINTS) or {}
        for r in reg.get("routers") or []:
            prefix = (r.get("prefix") or "").rstrip("/")
            app = r.get("app")
            for ep in r.get("endpoints") or []:
                path = ep.get("path") or ""
                if path and not path.startswith("/"):
                    path = "/" + path
                url = "/api" + prefix + path
                key = "%s %s" % (ep.get("method", "GET"), url)
                scope = (r.get("source_file") or "").replace("\\", "/").rsplit("/", 1)[0] + "/"
                tabs = defaultdict(set)
                for fpath, found in self.file_tables.items():
                    if fpath.startswith(scope):
                        for t, a in found.items():
                            tabs[t] |= a
                reads = sorted(t for t, a in tabs.items() if "read" in a)
                writes = sorted(t for t, a in tabs.items() if "write" in a)
                self.endpoints[key] = {"app": app, "handler": ep.get("handler"), "file": r.get("source_file"),
                                       "line": ep.get("line"), "tables_read": reads, "tables_written": writes,
                                       "table_evidence_scope": "router folder " + scope, "screens": set(),
                                       "url": norm_url(url)}
                if app == "generic_module":
                    mods = sorted(self.module_tables)
                    self.endpoints[key]["modules"] = mods
                    for m in mods:
                        for t, e in self.module_tables[m].items():
                            (self.endpoints[key]["tables_written"] if "write" in e["access"]
                             else self.endpoints[key]["tables_read"]).append("%s (module %s)" % (t, m))
                for t in set(reads) | set(writes):
                    self.tables[t]["endpoints"].add(key)
        mod_items = [("generic_module:" + m, v) for m, v in self.module_tables.items()]
        for app, tabs in list(self.app_tables.items()) + mod_items:
            for t, e in tabs.items():
                self.tables[t]["api"].append({"app": app, "access": sorted(e["access"]),
                                              "files": sorted(e["files"])[:12], "columns_named": sorted(e["columns"])})

    # ---- UI ---------------------------------------------------------------
    def scan_ui(self):
        comp = load(COMPONENTS) or {}
        sym = {s["symbol"]: norm_url(s["url"]) for s in comp.get("endpoint_symbols") or []}
        by_url = defaultdict(list)
        for k, e in self.endpoints.items():
            by_url[e["url"]].append(k)
        routes = comp.get("routes") or []
        services = {}
        for s in comp.get("services") or []:
            p = REPO / s["file"]
            if p.is_file():
                text = p.read_text(encoding="utf-8", errors="replace")
                services[s["name"]] = sorted(x for x in sym if re.search(r"\b%s\b" % re.escape(x), text))
        route_dirs = {(REPO / r["page"]).parent for r in routes}
        for r in routes:
            d = (REPO / r["page"]).parent
            syms, svc_used = set(), set()
            for f in d.rglob("*.ts*"):
                between = [x for x in f.parents if x != d and d in x.parents]
                if "__tests__" in f.parts or any(x in route_dirs for x in between):
                    continue
                text = f.read_text(encoding="utf-8", errors="replace")
                for name, ss in services.items():
                    if re.search(r"\b%s\b" % re.escape(name), text):
                        svc_used.add(name)
                        syms |= set(ss)
                syms |= {x for x in sym if re.search(r"\b%s\b" % re.escape(x), text)}
            eps = sorted({k for x in syms for k in by_url.get(sym[x], [])})
            tabs = set()
            for k in eps:
                e = self.endpoints[k]
                e["screens"].add(r["route"])
                tabs |= set(e["tables_read"]) | set(e["tables_written"])
            for t in tabs:
                self.tables[t.split(" ")[0]]["screens"].add(r["route"])
            self.screens[r["route"]] = {"page": r["page"], "services": sorted(svc_used), "endpoints": eps,
                                        "tables": sorted(tabs), "fields": [], "figma": [], "flows": [], "tests": []}

    def read_field_map(self):
        p = docs_dir(self.env) / "13_UI_TO_DATA_FIELD_MAPPING.yaml"
        fm = load(p)
        if not fm:
            self.notes.append("field map %s not found; column-level screen evidence skipped" % rel(p))
            return
        for row in fm.get("fields") or []:
            if not str(row.get("status", "")).startswith("VERIFIED"):
                continue
            cands = row.get("column_candidates") or []
            if len(cands) != 1 and row["status"] != "VERIFIED_WRITE_TARGET":
                continue
            writers = [x for x in cands if "write" in (x.get("api_access") or [])]
            c = cands[0] if len(cands) == 1 else (writers or cands)[0]
            rec = {"fe_field": row["fe_field"], "ui_label": row.get("ui_label"), "module": row["module"],
                   "file": "%s:%s" % (row["file"], row.get("line")), "status": row["status"]}
            key = "%s.%s" % (c["table"], c["column"])
            self.columns[key]["fields"].append(rec)
            self.tables[c["table"]]["fields"].append(dict(rec, column=c["column"]))
            route = "/" + row["module"]
            scr = self.screens.get(route)
            if scr is None:
                scr = next((v for k, v in self.screens.items() if route.startswith(k + "/")), None)
            if scr is not None:
                scr["fields"].append(dict(rec, column=key))
                self.tables[c["table"]]["screens"].add(route)

    # ---- ETL --------------------------------------------------------------
    def read_etl(self):
        io = load(ETL_IO) or {}
        for s in (io.get("sql_scripts") or []) + (io.get("python_scripts") or []):
            for access, key in (("read", "reads"), ("write", "writes")):
                for t in s.get(key) or []:
                    if self.known(t):
                        self.tables[t]["etl"].append({"script": s.get("path") or s.get("name"), "access": access})
            for t in s.get("header_target_tables") or []:
                name = s.get("path") or s.get("name")
                if self.known(t) and not any(e["script"] == name and e["access"] == "write"
                                             for e in self.tables[t]["etl"]):
                    self.tables[t]["etl"].append({"script": name, "access": "write (header claim)"})

    # ---- Figma / Confluence ---------------------------------------------
    def read_figma(self):
        if not FIGMA.is_file():
            return
        for line in FIGMA.read_text(encoding="utf-8").splitlines():
            m = MD_ROW.match(line)
            if not m or "SOURCE-VERIFIED" not in m.group(2):
                continue
            family, code = m.group(1), m.group(2)
            paths = [t for t in TICK.findall(code) if "/" in t or t.endswith((".ts", ".tsx"))]
            apps = API_TAG.findall(code)
            for route, scr in self.screens.items():
                page_dir = scr["page"].split("/app/")[-1].rsplit("/", 1)[0]
                if page_dir and any(page_dir == p or (p.startswith(page_dir + "/") and not self.is_route(p))
                                    for p in paths):
                    scr["figma"].append(family)
                    for t in scr["tables"]:
                        self.tables[t.split(" ")[0]]["figma"].add(family)
            for app in apps:
                for t, tabs in self.app_tables.items():
                    if t == app:
                        for tb in tabs:
                            self.tables[tb]["figma"].add(family)
            for t in TICK.findall(code):
                if self.known(t):
                    self.tables[t]["figma"].add(family)

    def read_flows(self):
        if not FLOWS.is_file():
            return
        section = None
        for line in FLOWS.read_text(encoding="utf-8").splitlines():
            if line.startswith("#"):
                section = line.lstrip("# ").strip()
                continue
            if "SOURCE-VERIFIED" not in line:
                continue
            for p in TICK.findall(line):
                if "web/src" not in p and "/" not in p:
                    continue
                for route, scr in self.screens.items():
                    if route == "/":
                        continue
                    page_dir = scr["page"].rsplit("/", 1)[0]
                    q = p.rstrip("/")
                    if q == page_dir or (q.startswith(page_dir + "/") and not self.is_route(q)):
                        if section not in scr["flows"]:
                            scr["flows"].append(section)
                        for t in scr["tables"]:
                            self.tables[t.split(" ")[0]]["flows"].add(section)

    def read_tests(self):
        if not TESTS.is_file():
            return
        for line in TESTS.read_text(encoding="utf-8").splitlines():
            for t, n in FREQ.findall(line):
                if self.known(t) and line.lstrip().startswith("`"):
                    self.tables[t]["tests"].append({"story": "all suites", "cases": "%s references" % n,
                                                    "workbooks": "SIT/UAT workbooks (table frequency)"})
            m = STORY_ROW.match(line)
            if not m:
                continue
            story, count, books = m.groups()
            tabs = [t for t in TICK.findall(books) if self.known(t)]
            for t in tabs:
                self.tables[t]["tests"].append({"story": story, "cases": count, "workbooks": books.replace("`", "")})
                for route, scr in self.screens.items():
                    if t in [x.split(" ")[0] for x in scr["tables"]]:
                        if story not in scr["tests"]:
                            scr["tests"].append(story)

    # ---- output -----------------------------------------------------------
    def build(self):
        self.read_registry()
        self.scan_api()
        self.read_endpoints()
        self.scan_ui()
        self.read_field_map()
        self.read_etl()
        self.read_figma()
        self.read_flows()
        self.read_tests()
        curated = load(CURATED) or {}
        chains = curated.get("dependency_chains") or []
        tables = {}
        for t in sorted(self.tables):
            e = self.tables[t]
            reg = self.registry.get(t, {})
            tables[t] = {
                "in_table_registry": t in self.registry,
                "module": reg.get("module"), "layer": reg.get("layer"), "status": reg.get("status"),
                "columns_in_registry": len(reg.get("columns") or []),
                "api": sorted(e["api"], key=lambda x: x["app"]),
                "endpoints": sorted(e["endpoints"]),
                "screens": sorted(e["screens"]),
                "fields": e["fields"],
                "etl": sorted(e["etl"], key=lambda x: (x["script"], x["access"])),
                "tests": e["tests"],
                "figma_screens": sorted(e["figma"]),
                "documented_flows": sorted(e["flows"]),
                "documented_chains": [c["chain_id"] for c in chains if c.get("db_table") == t],
            }
        columns = {k: {"api_files": sorted(set(v["api_files"])), "fields": v["fields"]}
                   for k, v in sorted(self.columns.items()) if v["fields"] or v["api_files"]}
        endpoints = {}
        for k in sorted(self.endpoints):
            e = dict(self.endpoints[k])
            e.pop("url")
            e["screens"] = sorted(e["screens"])
            e["tables_read"] = sorted(set(e["tables_read"]))
            e["tables_written"] = sorted(set(e["tables_written"]))
            endpoints[k] = e
        screens = {k: self.screens[k] for k in sorted(self.screens)}
        meta = {
            "generated": date.today().isoformat(),
            "generator": "sdlc/framework/tools/kbgen/gen_cross_module_matrix.py",
            "field_map_environment": self.env,
            "how_to_read": {
                "tables": "change a column here -> api (which app's SQL/Python names it, read or write, file:line), "
                          "endpoints (through that app), screens (routes that call those endpoints), fields (FE field "
                          "pinned to this column), etl (scripts that read/write it), tests (SIT/UAT suites that assert "
                          "on "
                          "it), figma_screens / documented_flows (design and Confluence context), documented_chains "
                          "(hand-written guidance in the CURATED file)",
                "endpoints": "change an endpoint -> handler file:line, tables named in the router's folder (SQL and "
                             "Python under table_evidence_scope; not traced into the handler body), screens that "
                             "call it",
                "screens": "change a screen -> endpoints it calls, tables behind them, fields pinned to columns, Figma "
                           "family, documented flow, stories with SIT/UAT cases",
                "evidence": "code is authority; Figma and Confluence rows are context and never add a table link on "
                            "their own; registry tables with no code reference are omitted",
            },
            "sources": [rel(TABLE_REGISTRY), rel(ENDPOINTS), rel(COMPONENTS), rel(ETL_IO), rel(FIGMA), rel(FLOWS),
                        rel(TESTS), rel(CURATED), "api/apps/**", "api/modules/**", "web/src/app/**"],
            "totals": {"tables": len(tables), "columns_with_evidence": len(columns), "endpoints": len(endpoints),
                       "screens": len(screens), "documented_chains": len(chains),
                       "tables_with_etl": sum(1 for t in tables.values() if t["etl"]),
                       "tables_with_screens": sum(1 for t in tables.values() if t["screens"]),
                       "tables_with_tests": sum(1 for t in tables.values() if t["tests"])},
            "notes": self.notes,
        }
        return {"metadata": meta, "tables": tables, "columns": columns, "endpoints": endpoints, "screens": screens,
                "documented_chains": chains}


HEADER = """# Acme Claims — Cross-Layer Impact Matrix (DB column -> API -> screen -> ETL -> tests)
# Generated by sdlc/framework/tools/kbgen/gen_cross_module_matrix.py — do not hand-edit.
# Hand-written chains and their if_changed guidance live in CROSS_LAYER_IMPACT_MATRIX.CURATED.yaml.
# Every row carries the file (and line where known) that proves it. Code is the authority;
# Figma and Confluence rows are context. Ask it three ways: tables.<T>, endpoints."<M /api/..>",
# screens."/route".
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default=os.environ.get("SDLC_FIELD_MAP_ENV", "sit"))
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--print", action="store_true")
    a = ap.parse_args()
    data = Matrix(a.env).build()
    text = HEADER + yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120)
    if a.print:
        print(text)
        return
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    t = data["metadata"]["totals"]
    print("wrote %s: %s" % (rel(out), json.dumps(t)))


if __name__ == "__main__":
    main()
