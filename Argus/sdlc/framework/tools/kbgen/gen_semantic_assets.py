"""Render the AI-facing assets for one Snowflake environment from what we already know.

Inputs (all read-only):
  - the INFORMATION_SCHEMA snapshot for the environment (same folder gen_db_kb.py uses)
  - DB-DOCS/09_DB_SEMANTIC_LAYER.yaml   table descriptions, validated joins, value dictionaries
  - DB-DOCS/05_DB_GLOSSARY.md           abbreviation dictionary used to spell out column names
  - DB-DOCS/16_DB_APP_JOINS.yaml        joins the application executes (extract_app_joins.py)

Outputs, under DB-DOCS/<docs_dir>/ for the chosen environment:
  17_DB_ERD.md                          Mermaid ERD; every edge names the file or document that proves it
  20_COMMENT_ON.sql                     COMMENT ON TABLE / COLUMN script for DBA review — never executed here
  21_CORTEX_ANALYST_SEMANTIC_MODEL.yaml Cortex Analyst semantic model over the _NOPHI views
  05a_DB_CODE_VALUE_QUESTIONS.md        one [REQUIRES STAKEHOLDER INPUT] block per code/indicator/status column

With --register, the code-value questions are also written into
VALIDATION/KB_OPEN_QUESTIONS.yaml between the GENERATED markers so the dashboard and
/document-validation pick them up.

Usage:
    python3 gen_semantic_assets.py --env sit --snapshot /path/to/SIT01_CLAIMS --register
    python3 gen_semantic_assets.py --env dev --snapshot /path/to/DEV01_CLAIMS
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
ENV_FILE = REPO / ".devin" / "rules" / "snowflake-environments.yaml"
REGISTRY = KB / "VALIDATION" / "KB_OPEN_QUESTIONS.yaml"
SCHEMA = "CLAIMS_UI_DATA"
AI_SCHEMA = SCHEMA + "_NOPHI"
RAW_PREFIXES = ("RAW_", "KF_TMS")
COUNT_RE = re.compile(r" \([0-9,]+\)")
GEN_BEGIN = "  # BEGIN GENERATED code_values — written by kbgen/gen_semantic_assets.py --register; do not hand-edit"
GEN_END = "  # END GENERATED code_values"

# Standard EDL / Acme Claims column-name tokens that are not in the glossary abbreviation table.
# These are the naming conventions the glossary itself relies on; they are declared here so
# the COMMENT ON script can say exactly which tokens were spelled out by rule. [A]
BASE_TOKENS = {
    "ID": "identifier", "NM": "name", "CD": "code", "DT": "date", "DTM": "timestamp", "NBR": "number",
    "AMT": "amount", "TXT": "text", "CNT": "count", "PCT": "percent", "VAL": "value", "IND": "indicator",
    "TYPE": "type", "STTS": "status", "STRT": "start", "END": "end", "KEY": "key", "DESC": "description",
    "USER": "user", "LAST": "last", "UPDTD": "updated", "CREAT": "created", "MIN": "minimum", "MAX": "maximum",
    "TIN": "TIN", "NPI": "NPI", "LOB": "line of business", "PSL": "product service line", "PMC": "PMC",
    "EFCTV": "effective", "TRMNTN": "termination", "VRSN": "version", "OPEN": "open", "CLOS": "close",
    "RUN": "run", "STG": "stage", "PARNT": "parent", "DPNDNT": "dependent", "MM": "member month",
    "MBR": "member", "SBSCRBR": "subscriber", "PROV": "provider", "GRP": "group", "ST": "state",
    "MOD": "module", "FILE": "file", "SHEET": "sheet", "CLMN": "column", "DSPLY": "display", "SQNC": "sequence",
    "RATE": "rate", "CAP": "cap", "FEE": "fee", "SUB": "sub", "MDL": "model", "SGMNT": "segment", "TRND": "trend",
    "MSR": "measure", "CMPST": "composite", "HRCHY": "hierarchy", "CNTRCTD": "contracted", "RSLT": "result",
    "SC": "scorecard", "EOC": "episode of care", "EPSD": "episode", "PRD": "period", "YR": "year", "MNTH": "month",
    "QTR": "quarter", "TOT": "total", "AVG": "average", "TRGT": "target", "FLG": "flag", "LVL": "level",
    "SRC": "source", "SET": "set", "DX": "diagnosis", "PX": "procedure", "REIMBMNT": "reimbursement",
    "CSATN": "cessation", "RQRD": "required", "MLTPL": "multiple", "MNDTRY": "mandatory", "LKUP": "lookup",
    "DFLT": "default", "FLTR": "filter", "IGNR": "ignore", "BLNK": "blank", "DWNLD": "download", "UPLD": "upload",
    "EDIT": "edit", "RVW": "review", "TERM": "term", "TERMS": "terms", "XREF": "cross-reference", "IS": "is",
    "UI": "UI", "BULK": "bulk", "ROLE": "role", "PRMSN": "permission", "ELMNT": "element", "PG": "provider group",
    "CNTRCT": "contract", "WAVE": "wave", "HLTH": "health", "LNK": "link", "ATRBN": "attribution", "MTHD": "method",
    "CTGRY": "category", "PRE": "pre", "RCRD": "record", "EXCLSN": "exclusion", "CVR": "cover", "CHLD": "child",
    "BSLN": "baseline", "ALWD": "allowed", "OUTLR": "outlier", "OUTLIER": "outlier", "HCOST": "high cost",
    "FCLTY": "facility", "PAP": "PAP", "PARM": "parameter", "CNFG": "configuration", "DEFN": "definition",
    "TMPLT": "template", "DTL": "detail", "SMRY": "summary", "RPT": "report", "YRLY": "yearly", "ACTVTY": "activity",
    "PAYMNT": "payment", "MNTHLY": "monthly", "RISK": "risk", "BAND": "band", "BSNS": "business", "RMTNC": "remittance",
    "ASGNE": "assignee", "APRVR": "approver", "APRVL": "approval", "CNFGRN": "configuration", "SPCLTY": "specialty",
    "MTRNL": "maternal", "FTL": "fetal", "MDCN": "medicine", "CRCRDTN": "credentialing", "ENGGMNT": "engagement",
    "BSD": "based", "CDPS": "CDPS", "RX": "pharmacy", "AGRGT": "aggregate", "QLTY": "quality", "BNUS": "bonus",
    "PTNTL": "potential", "SSAV": "shared savings", "CPTTN": "capitation", "OVRPAYMNT": "overpayment",
    "SVNGS": "savings", "THRSHLD": "threshold", "BNCHMRK": "benchmark", "TRNCH": "tranche", "CUT": "cut",
    "ENGN": "engine", "PRCNTL": "percentile", "AFNTY": "affinity", "MSRMNT": "measurement", "FUNDG": "funding",
    "TRNSPLNT": "transplant", "MDPNL": "medical panel", "VLDTN": "validation", "SBSTTUTN": "substitution",
    "SPLMNTL": "supplemental", "DWNSTRM": "downstream", "AUDT": "audit", "TRNSCTN": "transaction",
    "INCRMNTL": "incremental", "MBRSHP": "membership", "RSTRCTN": "restriction", "CNTRL": "control",
    "PRCS": "process", "RQST": "request", "SCRCRD": "scorecard", "VBC": "VBC", "OFSHR": "offshore",
    "ACSBL": "accessible", "CLNT": "client", "TNNT": "tenant", "HASH": "hash", "SEQ": "sequence", "NA": "not applicable",
    "RERUN": "rerun", "CALC": "calculation", "FNC": "finance", "PCMH": "PCMH", "THL": "THL", "ProgramC": "ProgramC",
    "CHF": "CHF", "ProgramA": "ProgramA", "ProgramB": "ProgramB", "BH": "behavioral health", "MEDICARE": "Medicare",
    "CREATN": "creation", "CMNT": "comment", "APRVD": "approved", "TRGR": "trigger", "ADRS": "address",
    "DURTN": "duration", "AGE": "age", "UNIT": "unit", "ZIP": "ZIP", "CLM": "claim", "POST": "post", "LINE": "line",
    "VOL": "volume", "WNDW": "window", "CURNT": "current", "INCL": "include", "EXTRCT": "extract", "TOTL": "total",
    "PRCTC": "practice", "RFRNC": "reference", "SCOR": "score", "NMRTR": "numerator", "DNMNTR": "denominator",
    "INDX": "index", "PCTILE": "percentile", "CALCN": "calculation", "UPSD": "upside", "DWNSD": "downside",
    "SHRD": "shared", "SHR": "share", "TRMNT": "treatment", "CRTRIA": "criteria", "APLY": "apply",
    "MTHDLGY": "methodology", "RT": "rate", "ALT": "alternate", "OPIOID": "opioid",
}
TYPE_MAP = {"TEXT": "VARCHAR", "NUMBER": "NUMBER", "DATE": "DATE", "TIMESTAMP_NTZ": "TIMESTAMP_NTZ",
            "BOOLEAN": "BOOLEAN", "FLOAT": "FLOAT", "VARIANT": "VARIANT"}
# code columns the semantic layer already defines, keyed by (table or '*', column)
DICT_KEYS = {("*", "RQST_TYPE_CD"): "RQST_TYPE_CD", ("*", "PRCS_TYPE_CD"): "PRCS_TYPE_CD",
             ("*", "RQST_STG_CD"): "RQST_STG_CD", ("CL_RUN_RQST_STTS", "STTS_CD"): "STTS_CD_RUN_RQST",
             ("CL_UI_PG_STTS", "STTS_CD"): "STTS_CD_PG", ("*", "CNTRCT_TYPE_CD"): "CNTRCT_TYPE_CD",
             ("*", "VBC_TYPE_CD"): "VBC_TYPE_CD", ("*", "CNTRCTD_STTS_CD"): "CNTRCTD_STTS_CD",
             ("VBC_HLTH_LNK_ATRBN_DTL_STTS_DT_ORDR", "CTGRY_CD"): "CTGRY_CD_HLTH_LNK",
             ("*", "HLTHLNK_STTS_TXT"): "HLTHLNK_STTS_TXT"}


def is_edl(col):
    return col.startswith(RAW_PREFIXES) or col == "KF_TMS"


def sql_str(s):
    return "'" + str(s).replace("'", "''") + "'"


def load_glossary_tokens():
    tokens = dict(BASE_TOKENS)
    for line in (DBDOCS / "05_DB_GLOSSARY.md").read_text().splitlines():
        m = re.match(r"^\|\s*([A-Z /]+?)\s*\|\s*([^|]+?)\s*\|\s*$", line)
        if m and m.group(1) not in ("Abbreviation",):
            for abbr in m.group(1).split("/"):
                tokens[abbr.strip()] = m.group(2).strip().lower()
    return tokens


def spell_out(col, tokens):
    """Return ('contract start date', []) or (None, [unknown tokens])."""
    words, unknown = [], []
    for tok in col.split("_"):
        if tok in tokens:
            words.append(tokens[tok])
        elif tok.isdigit():
            words.append(tok)
        else:
            unknown.append(tok)
    return (" ".join(words) if not unknown else None), unknown


def dict_for(table, col, dictionaries):
    key = DICT_KEYS.get((table, col)) or DICT_KEYS.get(("*", col))
    return dictionaries.get(key) if key else None


def simple_join_keys(join):
    """Turn a 09 join into [(left_col, right_col)] or None when the key is not a plain equality."""
    k = str(join["join_key"])
    if re.fullmatch(r"[A-Z0-9_]+", k):
        return [(k, k)]
    m = re.fullmatch(r"(?:child\.)?([A-Z0-9_]+)\s*=\s*(?:parent\.)?([A-Z0-9_]+)", k)
    if m:
        return [(m.group(1), m.group(2))]
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", required=True)
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--register", action="store_true", help="also write code-value questions into KB_OPEN_QUESTIONS.yaml")
    ap.add_argument("--out-root", default=str(KB), help="write under <out-root>/DB-DOCS/<docs_dir> instead of the live KB (for example a _REGEN staging folder)")
    args = ap.parse_args()

    envs = yaml.safe_load(ENV_FILE.read_text())
    if args.env not in envs["environments"]:
        raise SystemExit(f"{args.env} is not in {ENV_FILE}")
    e = envs["environments"][args.env]
    db, docs_dir, label = e["database"], e["docs_dir"], e["label"]
    if docs_dir == ".":
        raise SystemExit("refusing to write generated assets into the DB-DOCS root (production baseline)")
    out = Path(args.out_root).resolve() / "DB-DOCS" / docs_dir
    out.mkdir(parents=True, exist_ok=True)
    snapshot = Path(args.snapshot)
    snap_date = json.load(open(snapshot / "meta.json"))["snapshot_date"]
    rel_out = out.relative_to(REPO)
    print(f"Snowflake target: {db} ({args.env}) -> {rel_out}")

    tables_json = json.load(open(snapshot / "tables.json"))
    columns_json = json.load(open(snapshot / "columns.json"))
    views_json = json.load(open(snapshot / "views.json"))
    codes_json = json.load(open(snapshot / "codes.json"))
    sem = yaml.safe_load((DBDOCS / "09_DB_SEMANTIC_LAYER.yaml").read_text())
    app_joins_path = DBDOCS / "16_DB_APP_JOINS.yaml"
    app_joins = yaml.safe_load(app_joins_path.read_text()) if app_joins_path.exists() else {"edges": []}
    tokens = load_glossary_tokens()

    tnames = sorted(t["TABLE_NAME"] for t in tables_json if t["TABLE_SCHEMA"] == SCHEMA and t["TABLE_TYPE"] == "BASE TABLE")
    tset = set(tnames)
    rows_of = {t["TABLE_NAME"]: int(t["ROW_COUNT"] or 0) for t in tables_json if t["TABLE_SCHEMA"] == SCHEMA}
    cols_by_t = defaultdict(list)
    for c in columns_json:
        if c["TABLE_NAME"] in tset:
            cols_by_t[c["TABLE_NAME"]].append(c)
    for v in cols_by_t.values():
        v.sort(key=lambda c: int(c["ORDINAL_POSITION"]))
    nophi_views = {v["TABLE_NAME"] for v in views_json if v["TABLE_SCHEMA"] == AI_SCHEMA}
    sem_tables = {t["name"]: t for t in sem["tables"]}
    dictionaries = sem["value_dictionaries"]
    sem_src = "DB-DOCS/09_DB_SEMANTIC_LAYER.yaml"

    # ------------------------------------------------------------------ edges
    # Each edge: (left_table, left_col, right_table, right_col, source_kind, evidence, extra)
    edges = []
    for j in sem["joins"]:
        keys = simple_join_keys(j)
        if not keys:
            continue
        for lc, rc in keys:
            edges.append((j["left_table"], lc, j["right_table"], rc, "sem",
                          f"{sem_src} joins[{j['name']!r}]", {"cardinality": j.get("cardinality"), "confidence": j.get("confidence")}))
    for a in app_joins["edges"]:
        edges.append((a["left_table"], a["left_column"], a["right_table"], a["right_column"], "app",
                      "; ".join(a["evidence"]), {"occurrences": a["occurrences"]}))
    present = [ed for ed in edges if ed[0] in tset and ed[2] in tset]
    absent = [ed for ed in edges if ed[0] not in tset or ed[2] not in tset]
    erd_tables = sorted({ed[0] for ed in present} | {ed[2] for ed in present})

    # ------------------------------------------------------------------ 17 ERD
    def attrs(t):
        keys = []
        for ed in present:
            if ed[0] == t:
                keys.append(ed[1])
            if ed[2] == t:
                keys.append(ed[3])
        st = sem_tables.get(t, {})
        for k in st.get("key_columns", []):
            keys.append(k)
        seen, outk = set(), []
        types = {c["COLUMN_NAME"]: TYPE_MAP.get(c["DATA_TYPE"], c["DATA_TYPE"]) for c in cols_by_t[t]}
        for k in keys:
            if k in types and k not in seen:
                seen.add(k)
                outk.append(f"        {types[k]} {k}")
        return outk

    L = ["---", f"source_db: {db}", f"environment: {args.env}", f"schema: {SCHEMA}", f"generated_date: {snap_date}",
         "generator: sdlc/framework/tools/kbgen/gen_semantic_assets.py", "document: 17_DB_ERD", "---", "",
         f"# {db}.{SCHEMA} — Entity Relationship Diagram ({label})", "",
         f"`{db}.{SCHEMA}` has PRIMARY KEY constraints only and no FOREIGN KEYs [E: {rel_out}/_snapshot/constraints.json], "
         "so the lines below are not read from the database. Each one is either a join the application runs "
         "(`app`, with the source file that contains the SQL) or a join validated in the P01 semantic layer "
         f"(`sem`, `{sem_src}`). Tables that share a column name but are never joined in either place are **not** connected here.", "",
         f"Tables shown: {len(erd_tables)} of {len(tnames)} base tables. Attributes listed are the join columns plus the "
         "semantic layer's key columns — not the full column list (see 07_DB_SCHEMA_CATALOG.md for that).", "",
         "```mermaid", "erDiagram"]
    for t in erd_tables:
        L.append(f"    {t} {{")
        L += attrs(t)
        L.append("    }")
    seen_pairs = set()
    for ed in present:
        lt, lc, rt, rc, kind, ev, extra = ed
        pair = (lt, lc, rt, rc)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        card = "}o--||" if kind == "sem" and str(extra.get("cardinality", "")).startswith("many-to-one") else \
               "||--o{" if kind == "sem" and str(extra.get("cardinality", "")).startswith("one-to-many") else "}o--o{"
        lbl = f"{kind}: {lc}" if lc == rc else f"{kind}: {lc}={rc}"
        L.append(f'    {lt} {card} {rt} : "{lbl}"')
    L += ["```", "", "## Edge evidence", "", "| Left | Right | Columns | Source | Evidence | Note |", "|---|---|---|---|---|---|"]
    seen_pairs = set()
    for lt, lc, rt, rc, kind, ev, extra in present:
        pair = (lt, lc, rt, rc, kind)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        note = ""
        if kind == "sem":
            note = f"{extra.get('cardinality') or ''}; confidence {extra.get('confidence')}"
        else:
            note = f"{extra['occurrences']} occurrence(s) in code"
        L.append(f"| {lt} | {rt} | {lc} = {rc} | {kind} | `{ev}` | {note} |")
    L += ["", "## Joins that could not be drawn here", ""]
    if absent:
        L += [f"- {lt}.{lc} = {rt}.{rc} ({kind}) — one side is not a base table in `{db}.{SCHEMA}` on {snap_date}. [E: snapshot]"
              for lt, lc, rt, rc, kind, ev, extra in absent]
    else:
        L.append("- none")
    complex_joins = [j["name"] for j in sem["joins"] if not simple_join_keys(j)]
    L += ["", "Semantic-layer joins whose key is not a plain column equality and are therefore not drawn: "
          + (", ".join(f"`{n}`" for n in complex_joins) if complex_joins else "none") + f". [E: {sem_src}]", "",
          "## What this does not tell you", "",
          "- Direction and cardinality on `app` edges are unknown — the SQL only proves the two columns are compared. [?] "
          "Owner: Acme Claims dev lead.",
          f"- {len(tnames) - len(erd_tables)} base tables have no join evidence in either source and are absent from the diagram. "
          "They are not necessarily standalone. [?]", ""]
    (out / "17_DB_ERD.md").write_text("\n".join(L))

    # ------------------------------------------------------------------ 20 COMMENT ON
    L = [f"-- COMMENT ON script for {db}.{SCHEMA} ({label}) — generated {snap_date} by",
         "-- sdlc/framework/tools/kbgen/gen_semantic_assets.py. FOR DBA REVIEW; nothing here has been executed.",
         "--",
         f"-- Table comments come from {sem_src} (tables[].description). Column comments spell the column name out",
         "-- using the abbreviation table in DB-DOCS/05_DB_GLOSSARY.md plus the standard EDL/Acme Claims tokens declared in",
         "-- the generator (BASE_TOKENS) — a naming-convention expansion, not a business definition, and each such",
         "-- comment says so. Code-column comments append the value meanings from the semantic layer where one exists.",
         "-- Columns with a token the dictionaries do not know are listed at the end and left without a comment.",
         "--",
         f"-- Existing table comments in {db} are change-task ids (e.g. SCTASK…) [E: 00_DB_DISCOVERY_REPORT.md §4];",
         "-- the statements below would REPLACE them. Keep the task id elsewhere first if it is still needed.",
         "--", f"USE DATABASE {db};", f"USE SCHEMA {SCHEMA};", ""]
    n_tab = n_col = 0
    skipped = []
    for t in tnames:
        st = sem_tables.get(t)
        if st and st.get("description"):
            L.append(f"COMMENT ON TABLE {t} IS {sql_str(st['description'] + ' [source: 09_DB_SEMANTIC_LAYER.yaml]')};")
            n_tab += 1
        for c in cols_by_t[t]:
            col = c["COLUMN_NAME"]
            if is_edl(col):
                continue
            text, unknown = spell_out(col, tokens)
            if text is None:
                skipped.append((t, col, unknown))
                continue
            comment = text.capitalize() + " [auto-expanded from column name; verify]"
            d = dict_for(t, col, dictionaries)
            if d:
                vals = "; ".join(f"{k} = {v}" for k, v in d["values"].items())
                comment = f"{d['description']}. Values: {vals} [source: 09_DB_SEMANTIC_LAYER.yaml]"
            L.append(f"COMMENT ON COLUMN {t}.{col} IS {sql_str(comment)};")
            n_col += 1
        L.append("")
    L += ["-- ---------------------------------------------------------------------------",
          f"-- Not commented: {len(skipped)} columns contain a token neither the glossary nor BASE_TOKENS knows.",
          "-- Add the token to DB-DOCS/05_DB_GLOSSARY.md (abbreviation table) and re-run.", "--"]
    unknown_counter = defaultdict(int)
    for t, col, unk in skipped:
        L.append(f"-- {t}.{col}  (unknown: {', '.join(unk)})")
        for u in unk:
            unknown_counter[u] += 1
    L += ["--", "-- Unknown tokens by frequency: " + ", ".join(f"{k}({v})" for k, v in sorted(unknown_counter.items(), key=lambda kv: -kv[1])), ""]
    (out / "20_COMMENT_ON.sql").write_text("\n".join(L))

    # ------------------------------------------------------------------ 21 Cortex Analyst model
    model_tables = sorted(set(sem_tables) | set(erd_tables))
    model_tables = [t for t in model_tables if t in tset]
    no_view = [t for t in model_tables if t not in nophi_views]
    model_tables = [t for t in model_tables if t in nophi_views]
    model = {
        "name": f"acme_{args.env}_nophi",
        "description": (f"Acme Claims configuration data in {db}.{AI_SCHEMA} ({label}). Generated {snap_date} from the "
                        f"INFORMATION_SCHEMA snapshot plus {sem_src}. Every table is the _NOPHI view, never the base table. "
                        "Row-level tenant isolation is enforced by the RP_TNNT_ACCESS policy; the tenant filter is still "
                        "declared here because the semantic layer asks for it explicitly."),
        "tables": [],
        "relationships": [],
        "verified_queries": [],
    }
    for t in model_tables:
        st = sem_tables.get(t, {})
        cols = [c for c in cols_by_t[t] if not is_edl(c["COLUMN_NAME"])]
        dims, tdims, facts = [], [], []
        code_vals = defaultdict(list)
        for r in codes_json.get(t) or []:
            if isinstance(r, dict) and r.get("VAL") not in (None, ""):
                code_vals[r["COL"]].append(str(r["VAL"]))
        for c in cols:
            col = c["COLUMN_NAME"]
            dt = TYPE_MAP.get(c["DATA_TYPE"], c["DATA_TYPE"])
            text, _ = spell_out(col, tokens)
            d = dict_for(t, col, dictionaries)
            desc = d["description"] if d else (text.capitalize() if text else col)
            entry = {"name": col.lower(), "expr": col, "data_type": dt, "description": desc}
            if d:
                entry["sample_values"] = list(d["values"])[:10]
            elif col in code_vals:
                entry["sample_values"] = code_vals[col][:10]
            if dt in ("DATE", "TIMESTAMP_NTZ"):
                tdims.append(entry)
            elif dt in ("NUMBER", "FLOAT") and not col.endswith(("_ID", "_NBR", "_CD", "_KEY")):
                facts.append(entry)
            else:
                dims.append(entry)
        filters = [{"name": "tenant", "description": "Mandatory tenant filter from the semantic layer",
                    "expr": "RAW_CLNT_ID = 59 AND RAW_TNNT_ID = 59"}]
        colset = {c["COLUMN_NAME"] for c in cols_by_t[t]}
        if "VALID_TO_DTM" in colset:
            filters.append({"name": "current_version", "synonyms": ["current", "active", "latest"],
                            "description": "SCD2 current row", "expr": "VALID_TO_DTM = '9999-12-31'::TIMESTAMP"})
        if "TRMNTN_DT" in colset and "VALID_TO_DTM" not in colset:
            filters.append({"name": "current_status", "synonyms": ["current", "active"],
                            "description": "Status row still in force", "expr": "TRMNTN_DT = '9999-12-31'::DATE"})
        entry = {
            "name": t.lower(),
            "description": st.get("description", f"{t} (no description in the semantic layer yet)"),
            "base_table": {"database": db, "schema": AI_SCHEMA, "table": t},
            "dimensions": dims, "time_dimensions": tdims, "facts": facts, "filters": filters,
        }
        bk = st.get("business_key")
        if bk and re.fullmatch(r"[A-Z0-9_]+", str(bk)):
            entry["primary_key"] = {"columns": [bk]}
        model["tables"].append(entry)
    seen_rel = set()
    mset = set(model_tables)
    for lt, lc, rt, rc, kind, ev, extra in present:
        if lt not in mset or rt not in mset or lt == rt:
            continue
        key = (lt, rt)
        if key in seen_rel:
            continue
        seen_rel.add(key)
        cols_pairs = [{"left_column": a, "right_column": b} for (l2, a, r2, b, *_r) in present if (l2, r2) == key]
        rel = {"name": f"{lt.lower()}_to_{rt.lower()}", "left_table": lt.lower(), "right_table": rt.lower(),
               "relationship_columns": cols_pairs, "join_type": "left_outer",
               "relationship_type": "many_to_one" if kind == "sem" and str(extra.get("cardinality", "")).startswith("many-to-one") else "many_to_one",
               "comment": f"{kind}: {ev}"}
        model["relationships"].append(rel)
    hdr = (f"# Cortex Analyst semantic model — {db}.{AI_SCHEMA} ({label}). Generated {snap_date} by\n"
           "# sdlc/framework/tools/kbgen/gen_semantic_assets.py. Not uploaded to Snowflake by this tool.\n"
           "# Layout follows Snowflake's Cortex Analyst semantic model specification as understood on the generation\n"
           "# date; validate by uploading to a stage and opening it in Snowsight before relying on it. [A]\n"
           "# `relationship_type` on app-derived joins is set to many_to_one by default — the code does not prove it. [A]\n"
           "# `comment` keys on relationships are for readers and may need removing if the validator rejects them.\n")
    (out / "21_CORTEX_ANALYST_SEMANTIC_MODEL.yaml").write_text(hdr + yaml.safe_dump(model, sort_keys=False, width=110, allow_unicode=True))

    # ------------------------------------------------------------------ 05a code-value questions
    questions = []  # (table, [(col, values_str, defined)])
    for t in tnames:
        rows = codes_json.get(t)
        if not rows or isinstance(rows, dict):
            continue
        by_col = defaultdict(list)
        for r in rows:
            by_col[r["COL"]].append(r)
        items = []
        for col, rs in by_col.items():
            if dict_for(t, col, dictionaries):
                continue
            vals = ", ".join(f"`{r['VAL'] if r['VAL'] not in (None, '') else '(blank)'}` ({int(r['N']):,})" for r in rs)
            items.append((col, vals))
        if items:
            questions.append((t, items))
    n_q_cols = sum(len(i) for _, i in questions)
    L = ["---", f"source_db: {db}", f"environment: {args.env}", f"schema: {SCHEMA}", f"generated_date: {snap_date}",
         "generator: sdlc/framework/tools/kbgen/gen_semantic_assets.py", "document: 05a_DB_CODE_VALUE_QUESTIONS", "---", "",
         f"# {db}.{SCHEMA} — Code, indicator and status values that need a meaning ({label})", "",
         f"{n_q_cols} code-like columns (`*_CD`, `*_IND`, `*_TYPE`, `*_STTS`, `*_FLAG`, `*_LVL`) across {len(questions)} tables "
         f"hold values on {snap_date} that no document in this knowledge base defines. The values are real "
         f"[E: GROUP BY on {db}, snapshot {snap_date}]; the meanings are unknown [?]. The ten dictionaries that already exist "
         f"(`{sem_src}` value_dictionaries) are not repeated here.", "",
         "How to answer: write one line per value in the **Meaning** column, or use the validation form "
         "(`VALIDATION/KB-VALIDATION-FORM.html`, questions `code_values_<table>`). Answers are applied to "
         "`09_DB_SEMANTIC_LAYER.yaml` value_dictionaries and to `20_COMMENT_ON.sql`.", "",
         "Owner for every item below: BSA for the module that owns the table. [A: the schema does not name an owner]", "", "---", ""]
    for t, items in questions:
        L += [f"## {t}", "", f"[REQUIRES STAKEHOLDER INPUT] {len(items)} column(s), {rows_of.get(t, 0):,} rows in {db}.", "",
              "| Column | Values seen (rows) | Meaning |", "|---|---|---|"]
        for col, vals in items:
            L.append(f"| {col} | {vals} | |")
        L.append("")
    (out / "05a_DB_CODE_VALUE_QUESTIONS.md").write_text("\n".join(L))

    if args.register:
        reg_lines = [GEN_BEGIN,
                     "  - name: \"Code, indicator and status values without a meaning\"",
                     "    intro: >-",
                     f"      One question per table. Values are what exists in {db} on {snap_date}",
                     f"      (DB-DOCS/{docs_dir}/05a_DB_CODE_VALUE_QUESTIONS.md). Meanings cannot be read from the schema;",
                     "      answers go into 09_DB_SEMANTIC_LAYER.yaml value_dictionaries and the COMMENT ON script.",
                     "    questions:"]
        for t, items in questions:
            q = {
                "id": f"code_values_{t.lower()}",
                "priority": "P2",
                "kb_doc": [f"docs/knowledge-base/DB-DOCS/{docs_dir}/05a_DB_CODE_VALUE_QUESTIONS.md",
                           "docs/knowledge-base/DB-DOCS/09_DB_SEMANTIC_LAYER.yaml",
                           f"docs/knowledge-base/DB-DOCS/{docs_dir}/20_COMMENT_ON.sql"],
                "context": f"{t} ({rows_of.get(t, 0):,} rows in {db} on {snap_date}) has {len(items)} code/indicator/status "
                           "column(s) whose values are not defined anywhere in the KB: "
                           + "; ".join(f"{col}: {COUNT_RE.sub('', vals)}" for col, vals in items),
                "question": f"What does each value in these {t} columns mean, and which module/BSA owns the definition?",
                "why": "Without meanings an AI assistant (or a new developer) cannot decode these columns, and the "
                       "COMMENT ON script can only spell out the column name.",
                "understanding": "Unknown. The values are real data; nothing in the schema, glossary or semantic layer explains them.",
                "proposed_answer": "None proposed — please give one line per value (value = meaning). Blank means "
                                   "'not applicable / not set' unless you say otherwise.",
                "kb_effect": f"Adds a value dictionary for each column to 09_DB_SEMANTIC_LAYER.yaml and a real comment to "
                             f"{t} in 20_COMMENT_ON.sql.",
            }
            dumped = yaml.safe_dump([q], sort_keys=False, width=100, allow_unicode=True)
            reg_lines += ["      " + ln if ln.strip() else ln for ln in dumped.rstrip("\n").splitlines()]
        reg_lines.append(GEN_END)
        text = REGISTRY.read_text()
        block = "\n".join(reg_lines) + "\n"
        if GEN_BEGIN in text and GEN_END in text:
            pre = text[:text.index(GEN_BEGIN)]
            post = text[text.index(GEN_END) + len(GEN_END) + 1:]
            text = pre + block + post
        else:
            text = text.rstrip("\n") + "\n\n" + block
        REGISTRY.write_text(text)
        yaml.safe_load(text)  # fail loudly if the file no longer parses
        print(f"registered {len(questions)} code-value questions in {REGISTRY.relative_to(REPO)}")

    print(f"wrote 17_DB_ERD.md ({len(erd_tables)} tables, {len(present)} edges), 20_COMMENT_ON.sql ({n_tab} table, {n_col} column comments, "
          f"{len(skipped)} skipped), 21_CORTEX_ANALYST_SEMANTIC_MODEL.yaml ({len(model_tables)} tables, {len(model['relationships'])} relationships"
          f"{', no _NOPHI view for ' + ', '.join(no_view) if no_view else ''}), 05a_DB_CODE_VALUE_QUESTIONS.md ({n_q_cols} columns in {len(questions)} tables)")


if __name__ == "__main__":
    main()
