"""UI field -> Snowflake column mapping, built only from things that can be read.

Sources (all read-only):
  web/src/**                         grid columnDefs ({field, headerName}) and the Contract
                                          stepper field configs ({id, label, backendName, ...})
  web/src/Services/Utility/endpoints.ts
                                          endpoint identifier -> URL; a module "uses" an endpoint
                                          when the identifier appears in one of its files
  api/apps/app/api.py               root_path_route_map: /api/<segment> -> router
  api/apps/<app>/**/*.sql|*.py      where the same field token appears in API SQL or Python,
                                          and which tables that SQL reads from / writes to
  <snapshot>/columns.json, tables.json    the environment's INFORMATION_SCHEMA (T01 by default)
  <snapshot>/ui_mstr_terms.json, ui_term_xref.json
                                          VBC_UI_CNTRCT_MSTR_TERMS / VBC_UI_MSTR_TERM_XREF — the
                                          Contract stepper's own field -> table.column table
  FIGMA-DERIVED/01_FIGMA_ACME_PROTOTYPE.md
                                          the only Figma material in the KB; screen-level

Nothing is chosen for the reader. When a field token is a column of several tables the SQL
touches, every one is listed and the row is MULTIPLE_CANDIDATES. When the token is not in any
API file the row is NOT_IN_API. A Python line that merely pairs two tokens (e.g.
("Episode Name", ("EPISODE_NAME", "EPSD_NM"), 180)) is quoted, and the pairing is tagged [A].

Outputs, under DB-DOCS/<docs_dir>/:
  13_UI_TO_DATA_FIELD_MAPPING.yaml   one record per FE field
  13_UI_TO_DATA_FIELD_MAPPING.md     the same, readable, with the Open Questions / Assumptions /
                                     Don't Know lists at the end

Usage:
    python3 gen_ui_field_map.py --env sit --snapshot /path/to/SIT01_CLAIMS [--register]
"""
import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[4]
KB = REPO / "docs" / "knowledge-base"
DBDOCS = KB / "DB-DOCS"
FE_SRC = REPO / "web" / "src"
API_APPS = REPO / "api" / "apps"
ENDPOINTS_TS = FE_SRC / "Services" / "Utility" / "endpoints.ts"
API_ROUTES = API_APPS / "app" / "api.py"
FIGMA_DOC = KB / "FIGMA-DERIVED" / "01_FIGMA_ACME_PROTOTYPE.md"
ENV_FILE = REPO / ".devin" / "rules" / "snowflake-environments.yaml"
REGISTRY = KB / "VALIDATION" / "KB_OPEN_QUESTIONS.yaml"
STEPPER_CONFIG = FE_SRC / "app" / "contractproviderconf" / "Contract" / "ContractStepper" / "config" / "contractStepperConfig.ts"
SCHEMA = "CLAIMS_UI_DATA"
GEN_BEGIN = "  # BEGIN GENERATED ui_field_map — written by kbgen/gen_ui_field_map.py --register; do not hand-edit"
GEN_END = "  # END GENERATED ui_field_map"

GRID_RE = re.compile(r"\{[^{}]*?\bfield\s*:\s*['\"]([^'\"]+)['\"][^{}]*?\bheaderName\s*:\s*['\"]([^'\"]*)['\"][^{}]*?\}"
                     r"|\{[^{}]*?\bheaderName\s*:\s*['\"]([^'\"]*)['\"][^{}]*?\bfield\s*:\s*['\"]([^'\"]+)['\"][^{}]*?\}", re.S)
STEPPER_FIELD_RE = re.compile(r"\{\s*id\s*:\s*'([^']+)'\s*,\s*name\s*:\s*'([^']+)'\s*,\s*label\s*:\s*'([^']+)'(.*?)\n\s*\},?", re.S)
ENDPOINT_RE = re.compile(r"^\s*(\w+)\s*:\s*\(\)\s*=>\s*`([^`]*)`", re.M)
BASE_RE = re.compile(r"^const\s+(\w+)\s*=\s*\(\)\s*=>\s*`\$\{BASE_URL\}\$\{bp\(\)\}(/api/[^`]*)`", re.M)
ROUTE_RE = re.compile(r"^\s*\"(/?[\w/]+)\"\s*:\s*(\w+),", re.M)
IMPORT_RE = re.compile(r"^from\s+apps\.(\w+)[\w.]*\s+import\s+.*\b(\w+)\b", re.M)
SQL_TABLE_RE = re.compile(r"\b(FROM|JOIN|INSERT\s+INTO|MERGE\s+INTO|UPDATE|DELETE\s+FROM|INTO)\s+(?:\{[A-Z_]+\}\.|[A-Za-z0-9_]+\.)*([A-Z][A-Z0-9_]{3,})", re.I)
WRITE_VERBS = ("INSERT", "MERGE", "UPDATE", "DELETE", "INTO")
UPPER_TOKEN_RE = re.compile(r"\b[A-Z][A-Z0-9_]{2,}\b")


def rel(p):
    return Path(p).resolve().relative_to(REPO).as_posix()


def load_env(env):
    cfg = yaml.safe_load(ENV_FILE.read_text())
    return cfg["environments"][env]


def load_snapshot(folder):
    folder = Path(folder)
    cols = json.loads((folder / "columns.json").read_text())
    tables = json.loads((folder / "tables.json").read_text())
    by_table = defaultdict(dict)
    for c in cols:
        by_table[c["TABLE_NAME"]][c["COLUMN_NAME"]] = c
    table_types = {t["TABLE_NAME"]: t["TABLE_TYPE"] for t in tables}
    meta = json.loads((folder / "meta.json").read_text())
    terms = xref = []
    if (folder / "ui_mstr_terms.json").exists():
        terms = json.loads((folder / "ui_mstr_terms.json").read_text())
    if (folder / "ui_term_xref.json").exists():
        xref = json.loads((folder / "ui_term_xref.json").read_text())
    return by_table, table_types, meta, terms, xref


# ----------------------------------------------------------------------------- FE side
def fe_module(path):
    p = Path(rel(path))
    parts = p.parts
    if "_mfe" in parts:
        i = parts.index("_mfe")
        return "/".join(parts[i:i + 2])
    if "app" in parts:
        i = parts.index("app")
        depth = 3 if parts[i + 1:i + 3] == ("financeconf", "performance") else 2
        return "/".join(parts[i + 1:i + 1 + depth]) if len(parts) > i + 1 + depth else "/".join(parts[i + 1:i + depth])
    return "/".join(parts[:3])


def scan_grid_fields():
    rows = []
    for f in sorted(FE_SRC.rglob("*.ts*")):
        if "node_modules" in f.parts or f.name.endswith(".d.ts") or ".test." in f.name or ".spec." in f.name:
            continue
        text = f.read_text(errors="replace")
        for m in GRID_RE.finditer(text):
            field = m.group(1) or m.group(4)
            header = m.group(2) if m.group(1) else m.group(3)
            line = text.count("\n", 0, m.start()) + 1
            rows.append({"kind": "grid", "module": fe_module(f), "file": rel(f), "line": line,
                         "ui_label": header, "fe_field": field})
    return rows


def parse_stepper_kv(body):
    out = {}
    for key in ("backendName", "type", "dropdownKey", "termTypeCode", "uiTypeCode"):
        m = re.search(r"\b%s\s*:\s*'([^']*)'" % key, body)
        if m:
            out[key] = m.group(1)
    return out


def scan_stepper_fields():
    rows = []
    if not STEPPER_CONFIG.exists():
        return rows
    text = STEPPER_CONFIG.read_text(errors="replace")
    for m in STEPPER_FIELD_RE.finditer(text):
        fid, name, label, body = m.groups()
        line = text.count("\n", 0, m.start()) + 1
        r = {"kind": "stepper", "module": fe_module(STEPPER_CONFIG), "file": rel(STEPPER_CONFIG), "line": line,
             "ui_label": label, "fe_field": name, "fe_id": fid}
        r.update(parse_stepper_kv(body))
        rows.append(r)
    return rows


def load_endpoints():
    text = ENDPOINTS_TS.read_text()
    bases = {m.group(1): m.group(2) for m in BASE_RE.finditer(text)}
    eps = {}
    for m in ENDPOINT_RE.finditer(text):
        name, url = m.groups()
        for b, prefix in bases.items():
            url = url.replace("${%s()}" % b, prefix)
        url = url.replace("${BASE_URL}${bp()}", "")
        eps[name] = url
    return eps


def load_routes():
    """/api/<segment> -> apps.<package> from apps/app/api.py [E]."""
    text = API_ROUTES.read_text()
    router_pkg = {}
    for m in re.finditer(r"^from\s+apps\.(\w+)[\w.]*\s+import\s+([^\n]+)", text, re.M):
        pkg, names = m.groups()
        for n in re.split(r"[,\s()]+", names):
            if n and n != "as":
                router_pkg[n] = pkg
    routes = {}
    for m in ROUTE_RE.finditer(text):
        path, router = m.groups()
        seg = path.strip("/").split("/")[0]
        if router in router_pkg:
            routes[seg] = router_pkg[router]
    return routes


def endpoints_in_text(text, eps, routes, via):
    used = {}
    for name, url in eps.items():
        if re.search(r"\b%s\b" % re.escape(name), text):
            seg = url.split("/api/", 1)[1].split("/")[0].split("?")[0] if "/api/" in url else None
            used[name] = {"url": url, "api_app": routes.get(seg), "fe_file": via}
    return used


def service_endpoints(eps, routes):
    """web/src/Services/<name>.ts -> endpoint identifiers it references [E]."""
    out = {}
    for f in (FE_SRC / "Services").glob("*.ts"):
        out[f.stem] = endpoints_in_text(f.read_text(errors="replace"), eps, routes, rel(f))
    return out


def module_endpoints(module, eps, routes, services):
    """Endpoint identifiers used by the module's files directly, or through a Services/<x>.ts it imports [E]."""
    if "/" in module and module.split("/")[0] == "_mfe":
        mod_dir = FE_SRC / module
    else:
        mod_dir = FE_SRC / "app" / module
    used = {}
    if not mod_dir.exists():
        return used
    for f in mod_dir.rglob("*.ts*"):
        text = f.read_text(errors="replace")
        used.update(endpoints_in_text(text, eps, routes, rel(f)))
        for m in re.finditer(r"from\s+['\"](?:@/|\.\./|\./)*(?:src/)?Services/(\w+)['\"]", text):
            for name, v in services.get(m.group(1), {}).items():
                used.setdefault(name, dict(v, fe_file="%s via Services/%s.ts" % (rel(f), m.group(1))))
    return used


# ----------------------------------------------------------------------------- API side
def index_api():
    """token -> [(file, line, text)] across apps/**; file -> tables named in FROM/JOIN/INTO."""
    hits = defaultdict(list)
    file_tables = {}
    for f in sorted(API_APPS.rglob("*")):
        if f.suffix not in (".sql", ".py") or "test" in f.parts or "__pycache__" in f.parts:
            continue
        text = f.read_text(errors="replace")
        rf = rel(f)
        roles = defaultdict(set)
        for m in SQL_TABLE_RE.finditer(text):
            verb, tbl = m.group(1).upper(), m.group(2).upper()
            roles[tbl].add("write" if verb.startswith(WRITE_VERBS) else "read")
        file_tables[rf] = {t: sorted(r) for t, r in roles.items()}
        for i, line in enumerate(text.splitlines(), 1):
            for tok in set(UPPER_TOKEN_RE.findall(line)):
                hits[tok].append((rf, i, line.strip()[:160]))
    return hits, file_tables


def app_of(path):
    parts = Path(path).parts
    return parts[2] if len(parts) > 2 and parts[0] == "api" and parts[1] == "apps" else None


def resolve_field(row, hits, file_tables, by_table, apps_used):
    tok = row["fe_field"]
    if not re.fullmatch(r"[A-Z][A-Z0-9_]{2,}", tok):
        row["status"] = "UI_ONLY_KEY"
        row["note"] = "FE field key is not an upper-case column-style token; nothing to search for in API SQL [E: %s:%s]" % (row["file"], row["line"])
        return
    api_hits = hits.get(tok, [])
    in_used = [h for h in api_hits if app_of(h[0]) in apps_used] if apps_used else []
    scope = "module_apps" if in_used else ("any_app" if api_hits else None)
    use = in_used or api_hits
    row["api_hits"] = [{"file": f, "line": ln, "text": t} for f, ln, t in use[:12]]
    row["api_hit_count"] = len(api_hits)
    row["api_hit_scope"] = scope
    if not api_hits:
        row["status"] = "NOT_IN_API"
        return
    candidates = defaultdict(lambda: {"roles": set(), "files": set()})
    for f, ln, t in use:
        for tbl, roles in file_tables.get(f, {}).items():
            if tbl in by_table and tok in by_table[tbl]:
                candidates[tbl]["roles"].update(roles)
                candidates[tbl]["files"].add(f)
    cands = []
    for tbl in sorted(candidates):
        c = by_table[tbl][tok]
        roles = sorted(candidates[tbl]["roles"])
        files = sorted(candidates[tbl]["files"])
        cands.append({"table": tbl, "column": tok, "data_type": c["DATA_TYPE"], "api_access": roles,
                      "evidence": "[E: %s %s %s; %s.%s in snapshot]" % (files[0], "/".join(roles), tbl, tbl, tok)})
    row["column_candidates"] = cands
    writes = [c for c in cands if "write" in c["api_access"]]
    if len(cands) == 1:
        row["status"] = "VERIFIED" if scope == "module_apps" else "VERIFIED_OTHER_APP"
    elif len(cands) > 1 and len(writes) == 1 and scope == "module_apps":
        row["status"] = "VERIFIED_WRITE_TARGET"
        row["write_target"] = "%s.%s" % (writes[0]["table"], tok)
    elif len(cands) > 1:
        row["status"] = "MULTIPLE_CANDIDATES"
    else:
        aliases = set()
        for f, ln, t in use:
            for m in re.finditer(r"\b(?:\w+\.)?([A-Z][A-Z0-9_]{2,})\s+AS\s+%s\b" % re.escape(tok), t, re.I):
                src = m.group(1).upper()
                for tbl, roles in file_tables.get(f, {}).items():
                    if tbl in by_table and src in by_table[tbl]:
                        aliases.add((src, tbl, f, ln))
        if aliases:
            row["sql_alias_of"] = [{"column": s, "table": tb, "data_type": by_table[tb][s]["DATA_TYPE"],
                                   "evidence": "[E: %s:%s `%s AS %s`; table named in the same file]" % (f, ln, s, tok)}
                                  for s, tb, f, ln in sorted(aliases)]
            tables = {tb for _, tb, _, _ in aliases}
            row["status"] = "VERIFIED_SQL_ALIAS" if len(tables) == 1 else "SQL_ALIAS_MULTIPLE_TABLES"
            return
        pairs = set()
        for f, ln, t in use:
            if f.endswith(".py"):
                for other in UPPER_TOKEN_RE.findall(t):
                    if other != tok:
                        for tbl, cols in by_table.items():
                            if other in cols and app_tables_touch(tbl, f, file_tables, hits):
                                pairs.add((other, tbl))
        if pairs:
            row["same_line_tokens"] = [{"token": o, "table": tb,
                                        "tag": "[A] the Python line pairs the FE key with this token; whether it is an alias is not stated in source"}
                                       for o, tb in sorted(pairs)]
            row["status"] = "API_ALIAS_UNCONFIRMED"
        else:
            row["status"] = "IN_API_NO_COLUMN"


def app_tables_touch(tbl, pyfile, file_tables, hits):
    app = app_of(pyfile)
    return any(tbl in ts for f, ts in file_tables.items() if app_of(f) == app)


# ----------------------------------------------------------------------------- Contract master terms
def stepper_from_terms(rows, terms, xref, by_table, env_label):
    by_name = defaultdict(list)
    for t in terms:
        by_name[t["TERM_NM"].strip().lower()].append(t)
    xref_by_term = defaultdict(list)
    for x in xref:
        xref_by_term[x["TERM_ID"]].append(x)
    for r in rows:
        if r["kind"] != "stepper":
            continue
        key = (r.get("backendName") or r["ui_label"]).strip().lower()
        matches = by_name.get(key) or by_name.get(r["ui_label"].strip().lower(), [])
        if not matches:
            r["status"] = "NOT_IN_MASTER_TERMS"
            r["note"] = "no VBC_UI_CNTRCT_MSTR_TERMS row whose TERM_NM equals backendName/label in %s" % env_label
            continue
        cands = []
        for t in matches:
            for x in xref_by_term.get(t["TERM_ID"], []):
                c = by_table.get(x["TERM_TBL_NM"], {}).get(x["TERM_CLMN_NM"])
                cands.append({"table": x["TERM_TBL_NM"], "column": x["TERM_CLMN_NM"],
                              "data_type": c["DATA_TYPE"] if c else "[?] column not in snapshot",
                              "term_id": t["TERM_ID"], "term_type": t["TERM_TYPE_CD"], "ui_type": t["UI_TYPE_CD"],
                              "group": t["GRP_NM"], "business_desc": t.get("BSNS_DESC") or "",
                              "evidence": "[E: %s VBC_UI_CNTRCT_MSTR_TERMS/VBC_UI_MSTR_TERM_XREF TERM_ID=%s]" % (env_label, t["TERM_ID"])})
        r["column_candidates"] = cands
        r["term_ids"] = sorted({t["TERM_ID"] for t in matches})
        if len(cands) == 1:
            r["status"] = "VERIFIED"
        elif cands:
            r["status"] = "MULTIPLE_CANDIDATES"
        else:
            r["status"] = "TERM_WITHOUT_XREF"


def terms_not_in_fe(rows, terms, xref):
    fe_names = {(r.get("backendName") or r["ui_label"]).strip().lower() for r in rows if r["kind"] == "stepper"}
    fe_names |= {r["ui_label"].strip().lower() for r in rows if r["kind"] == "stepper"}
    xref_by_term = defaultdict(list)
    for x in xref:
        xref_by_term[x["TERM_ID"]].append(x)
    out = []
    for t in sorted(terms, key=lambda t: (t["CNFGRN_ID"], t["GRP_ID"], t["DSPLY_SQNC_NBR"] or 0)):
        if t["TERM_NM"].strip().lower() in fe_names:
            continue
        out.append({"term_id": t["TERM_ID"], "term_name": t["TERM_NM"], "group": t["GRP_NM"], "config": t["CNFGRN_ID"],
                    "ui_type": t["UI_TYPE_CD"], "targets": ["%s.%s" % (x["TERM_TBL_NM"], x["TERM_CLMN_NM"]) for x in xref_by_term.get(t["TERM_ID"], [])],
                    "business_desc": t.get("BSNS_DESC") or ""})
    return out


# ----------------------------------------------------------------------------- Figma
def figma_index():
    if not FIGMA_DOC.exists():
        return "", []
    text = FIGMA_DOC.read_text(errors="replace")
    screens = re.findall(r"^\|\s*([^|]+?)\s*\|", text, re.M)
    return text, screens


def figma_check(rows, figma_text):
    low = figma_text.lower()
    for r in rows:
        lbl = r["ui_label"].strip()
        r["figma"] = ("label text appears in FIGMA-DERIVED/01_FIGMA_ACME_PROTOTYPE.md [E]" if lbl and len(lbl) > 2 and lbl.lower() in low
                      else "not mentioned in the KB's Figma-derived document (screen-level only) [?]")


# ----------------------------------------------------------------------------- render
def md_escape(s):
    return str(s).replace("|", "\\|").replace("\n", " ")


def render_md(rows, env, meta, stats, unused_terms, apps_by_module):
    label = env["label"]
    db = env["database"]
    L = []
    L.append("# 13 — UI field to data column mapping — %s (%s)\n" % (label, db))
    L.append("Generated by `sdlc/framework/tools/kbgen/gen_ui_field_map.py` from the FE source, the API source and the "
             "%s INFORMATION_SCHEMA snapshot of %s. Every row says where it was read. Nothing here is inferred from a name "
             "looking similar; where the source does not settle it, the row says so.\n" % (db, meta["snapshot_date"]))
    L.append("## How a row was built\n")
    L.append("1. FE grid columns are the `{field, headerName}` objects in `web/src/**` [E: file:line on each row]. "
             "Contract stepper fields are the `{id, name, label, backendName}` objects in `contractStepperConfig.ts`.")
    L.append("2. A module's API apps are the endpoint identifiers from `endpoints.ts` that appear in the module's files, "
             "resolved through `root_path_route_map` in `api/apps/app/api.py`.")
    L.append("3. The FE field key is searched, as a whole word, in every `.sql` / `.py` under `api/apps/`. "
             "Tables named in `FROM / JOIN / INTO / UPDATE / MERGE INTO` of those files that also carry that column in %s are the candidates." % db)
    L.append("4. Contract stepper fields are matched on `backendName` (or `label`) = `VBC_UI_CNTRCT_MSTR_TERMS.TERM_NM`, "
             "and the target column comes from `VBC_UI_MSTR_TERM_XREF` — this is data the application itself reads "
             "(`api/modules/contract/sql/master_config/master_data.sql`).")
    L.append("5. Figma: the only Figma material in the KB is screen-level; a field is marked only if its label text appears there.\n")
    L.append("## Status meanings\n")
    L.append("| Status | Meaning |\n|---|---|")
    for s, m in STATUS_HELP.items():
        L.append("| `%s` | %s |" % (s, m))
    L.append("")
    L.append("## Totals\n")
    for k, v in stats.items():
        L.append("- %s: %s" % (k, v))
    L.append("")
    L.append("## Module → API app (from endpoint identifiers found in the module's files)\n")
    L.append("| FE module | Endpoint identifiers found | API app(s) |\n|---|---|---|")
    for mod, eps in sorted(apps_by_module.items()):
        apps = sorted({v["api_app"] for v in eps.values() if v["api_app"]})
        L.append("| %s | %d | %s |" % (mod, len(eps), ", ".join(apps) or "[?] none resolved"))
    L.append("")
    by_mod = defaultdict(list)
    for r in rows:
        by_mod[r["module"]].append(r)
    for mod in sorted(by_mod):
        L.append("## %s\n" % mod)
        L.append("| UI label | FE key | Status | %s table.column | Type | Evidence |\n|---|---|---|---|---|---|" % db)
        for r in by_mod[mod]:
            cands = r.get("column_candidates", []) or r.get("sql_alias_of", [])
            tc = "<br>".join("%s.%s%s" % (c["table"], c["column"], " (%s)" % "/".join(c["api_access"]) if c.get("api_access") else "") for c in cands) or "—"
            ty = "<br>".join(c["data_type"] for c in cands) or "—"
            ev = ["[E: %s:%s]" % (r["file"], r["line"])]
            for h in r.get("api_hits", [])[:2]:
                ev.append("[E: %s:%s]" % (h["file"], h["line"]))
            for c in cands[:1]:
                ev.append(c["evidence"])
            for a in r.get("sql_alias_of", [])[:3]:
                ev.append("%s.%s %s" % (a["table"], a["column"], a["evidence"]))
            for p in r.get("same_line_tokens", [])[:2]:
                ev.append("%s → %s.%s %s" % (r["fe_field"], p["table"], p["token"], p["tag"]))
            if r.get("note"):
                ev.append(r["note"])
            L.append("| %s | `%s` | `%s` | %s | %s | %s |" % (md_escape(r["ui_label"]), r["fe_field"], r["status"], tc, ty, md_escape(" ".join(ev))))
        L.append("")
    L.append("## Contract master terms with no matching stepper field in the FE config\n")
    L.append("These are `VBC_UI_CNTRCT_MSTR_TERMS` rows in %s whose TERM_NM matches no `label`/`backendName` in "
             "`contractStepperConfig.ts`. The stepper is described in code as JSON-driven, so these may be rendered from the API "
             "response rather than from the static config — that is not established here [?].\n" % db)
    L.append("| TERM_ID | Term name | Group | Config | Target column(s) |\n|---|---|---|---|---|")
    for t in unused_terms:
        L.append("| %s | %s | %s | %s | %s |" % (t["term_id"], md_escape(t["term_name"]), md_escape(t["group"]), t["config"], ", ".join(t["targets"]) or "[?] no xref"))
    L.append("")
    L.append("## Open Questions (owner)\n")
    L.append("- For every `MULTIPLE_CANDIDATES` row above: which of the listed tables is the one the screen reads/writes? (Acme Claims API developer of that module)")
    L.append("- For every `API_ALIAS_UNCONFIRMED` row: is the paired token the DB column behind the FE key? (Acme Claims API developer)")
    L.append("- For every `NOT_IN_API` / `IN_API_NO_COLUMN` row: is the value computed in the API/FE, or read from a table the search did not see? (Acme Claims API developer)")
    L.append("- Contract master terms with no static stepper field: are they rendered dynamically from `getMasterConfigData`? (Contract module developer)")
    L.append("- Is the Figma file's field list available as an export? The KB only holds a screen-level comparison. (UX / BSA)\n")
    L.append("## Assumptions\n")
    L.append("- [A] An endpoint identifier appearing in a module's file means that module calls that endpoint. If wrong, the module→API app column is wrong; the field→column candidates are searched repo-wide anyway.")
    L.append("- [A] A `.py` line that lists the FE key next to a %s column name is treated as a possible alias only; it is never promoted to VERIFIED." % db)
    L.append("- [A] Tables named in SQL text are read with a regex over FROM/JOIN/INTO/UPDATE/MERGE INTO; tables built dynamically in Python are missed.\n")
    L.append("## Don't Know\n")
    L.append("- Which routes `/api/module/*` (generic_module) serves for each module at runtime — it is registered per module name from config, not in `api.py`. (API developer)")
    L.append("- Whether the Figma file contains fields not in this list — no field-level Figma export is in the repo. (UX)")
    L.append("- U01 / P01: this run used %s only; nothing here is claimed for other environments.\n" % db)
    L.append("## Files actually read\n")
    files = sorted({r["file"] for r in rows} | {h["file"] for r in rows for h in r.get("api_hits", [])})
    for f in [rel(ENDPOINTS_TS), rel(API_ROUTES), rel(FIGMA_DOC)] + files:
        L.append("- `%s`" % f)
    L.append("- %s snapshot: columns.json, tables.json, ui_mstr_terms.json, ui_term_xref.json (%s)" % (db, meta["snapshot_date"]))
    return "\n".join(L) + "\n"


STATUS_HELP = {
    "VERIFIED": "FE key found in this module's API app SQL/Python, and exactly one table named there carries that column in the snapshot. [E]",
    "VERIFIED_OTHER_APP": "Same as VERIFIED, but the API hit is in an app not linked to this module by an endpoint identifier. [E + A]",
    "VERIFIED_WRITE_TARGET": "Several tables carry the column, but this module's API SQL writes (INSERT/MERGE/UPDATE) into exactly one of them; that one is the write target, the others are listed as reads. [E]",
    "MULTIPLE_CANDIDATES": "Several tables named in the API files carry the column; all are listed, none chosen. [?]",
    "VERIFIED_SQL_ALIAS": "API SQL selects `<table column> AS <FE key>` and exactly one table named in that file carries the source column. [E]",
    "SQL_ALIAS_MULTIPLE_TABLES": "API SQL aliases the FE key from a column that exists in more than one table named in that file; all listed. [?]",
    "API_ALIAS_UNCONFIRMED": "FE key appears only in Python beside another column-like token; the pairing is quoted, not trusted. [A]",
    "IN_API_NO_COLUMN": "FE key appears in API files but no table named there has that column in the snapshot. [?]",
    "NOT_IN_API": "FE key does not appear anywhere under api/apps. UI-only, computed, or served elsewhere. [?]",
    "UI_ONLY_KEY": "FE key is camelCase / a UI construct (e.g. Action); no column-style token to search. [E]",
    "NOT_IN_MASTER_TERMS": "Stepper field whose backendName/label matches no TERM_NM in VBC_UI_CNTRCT_MSTR_TERMS. [?]",
    "TERM_WITHOUT_XREF": "Master term found but it has no VBC_UI_MSTR_TERM_XREF row. [?]",
}


def register_questions(rows, env, docs_dir):
    """Write one question per module for the unresolved rows into KB_OPEN_QUESTIONS.yaml."""
    doc = "docs/knowledge-base/DB-DOCS/%s/13_UI_TO_DATA_FIELD_MAPPING.md" % docs_dir
    by_mod = defaultdict(list)
    for r in rows:
        if r["status"] in ("MULTIPLE_CANDIDATES", "SQL_ALIAS_MULTIPLE_TABLES", "API_ALIAS_UNCONFIRMED", "IN_API_NO_COLUMN", "NOT_IN_API", "NOT_IN_MASTER_TERMS", "TERM_WITHOUT_XREF"):
            by_mod[r["module"]].append(r)
    qs = []
    for mod in sorted(by_mod):
        rs = by_mod[mod]
        sample = "; ".join("%s (`%s`, %s)" % (r["ui_label"], r["fe_field"], r["status"]) for r in rs[:8])
        qs.append({
            "id": "ui_field_map_" + re.sub(r"[^a-z0-9]+", "_", mod.lower()).strip("_"),
            "priority": "P2",
            "kb_doc": [doc, "docs/knowledge-base/CROSS-LAYER/CROSS_LAYER_IMPACT_MATRIX.yaml"],
            "context": "%s: %d screen field(s) whose %s column could not be settled from FE + API source: %s%s"
                       % (mod, len(rs), env["database"], sample, " …" if len(rs) > 8 else ""),
            "question": "For each listed field, which table.column does the screen read or write, or is the value computed?",
            "why": "An AI assistant answering in screen labels needs the exact column; a wrong guess returns wrong numbers.",
            "understanding": "Candidates (where any) are listed on the row in the mapping document; none has been chosen.",
            "proposed_answer": "None proposed — please name the table.column per field or say 'computed'.",
            "kb_effect": "Row status becomes VERIFIED with the answer as [E: stakeholder]; CROSS_LAYER_IMPACT_MATRIX picks the column up on the next regeneration.",
        })
    text = REGISTRY.read_text()
    section = yaml.safe_dump([{"name": "UI field to data column mapping (%s)" % env["label"], "questions": qs}],
                             sort_keys=False, allow_unicode=True, width=110, default_flow_style=False)
    section = "".join("  " + ln + "\n" if ln.strip() else "\n" for ln in section.splitlines())
    new = GEN_BEGIN + "\n" + section + GEN_END + "\n"
    if GEN_BEGIN in text:
        text = re.sub(re.escape(GEN_BEGIN) + r".*?" + re.escape(GEN_END) + r"\n", new, text, flags=re.S)
    else:
        text = text.rstrip("\n") + "\n" + new
    REGISTRY.write_text(text)
    yaml.safe_load(text)
    return len(qs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default="sit")
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--register", action="store_true")
    ap.add_argument("--out-root", default=str(KB), help="write under <out-root>/DB-DOCS/<docs_dir> instead of the live KB (for example a _REGEN staging folder)")
    a = ap.parse_args()
    env = load_env(a.env)
    by_table, table_types, meta, terms, xref = load_snapshot(a.snapshot)
    if meta["database"] != env["database"]:
        raise SystemExit("snapshot is %s but --env %s expects %s" % (meta["database"], a.env, env["database"]))

    rows = scan_grid_fields() + scan_stepper_fields()
    eps = load_endpoints()
    routes = load_routes()
    hits, file_tables = index_api()
    services = service_endpoints(eps, routes)
    apps_by_module = {m: module_endpoints(m, eps, routes, services) for m in sorted({r["module"] for r in rows})}
    for r in rows:
        r["api_apps"] = sorted({v["api_app"] for v in apps_by_module[r["module"]].values() if v["api_app"]})
        if r["kind"] == "grid":
            resolve_field(r, hits, file_tables, by_table, set(r["api_apps"]))
    stepper_from_terms(rows, terms, xref, by_table, env["database"])
    figma_text, _ = figma_index()
    figma_check(rows, figma_text)
    unused_terms = terms_not_in_fe(rows, terms, xref)

    stats = defaultdict(int)
    for r in rows:
        stats["rows"] += 1
        stats["status " + r["status"]] += 1
    stats["contract master terms with no static stepper field"] = len(unused_terms)
    stats["FE modules"] = len(apps_by_module)

    if env["docs_dir"] == ".":
        raise SystemExit("refusing to write into the DB-DOCS root (production baseline); this script builds the lower regions only")
    out_dir = Path(a.out_root).resolve() / "DB-DOCS" / env["docs_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)
    header = {"environment": env["label"], "database": env["database"], "snapshot_date": meta["snapshot_date"],
              "generator": "sdlc/framework/tools/kbgen/gen_ui_field_map.py", "status_meanings": STATUS_HELP,
              "totals": dict(stats)}
    (out_dir / "13_UI_TO_DATA_FIELD_MAPPING.yaml").write_text(
        yaml.safe_dump({"header": header, "module_api_apps": {m: {k: v for k, v in e.items()} for m, e in apps_by_module.items()},
                        "fields": rows, "master_terms_without_fe_field": unused_terms},
                       sort_keys=False, allow_unicode=True, width=120))
    (out_dir / "13_UI_TO_DATA_FIELD_MAPPING.md").write_text(render_md(rows, env, meta, stats, unused_terms, apps_by_module))
    for k, v in sorted(stats.items()):
        print("%-60s %s" % (k, v))
    if a.register:
        print("questions registered:", register_questions(rows, env, env["docs_dir"]))


if __name__ == "__main__":
    main()
