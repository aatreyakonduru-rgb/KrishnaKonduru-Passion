#!/usr/bin/env python3
"""Security checks /implement runs before the PR: Checkmarx, Wiz and the GovRAMP access-control rules.

Settings live in .devin/rules/security-scans.yaml. Secrets are read from the environment by name and are
never printed or written to the results. Each command prints one JSON result (and writes it with --out):

    security_scans.py preflight                          which of the three are set up (nothing is scanned)
    security_scans.py checkmarx --branch B [--base BR] [--round N]
                                                         SAST + SCA scan of the pushed branch
    security_scans.py wiz [--base BR] [--round N]        open Wiz findings for the APM on this repo's components
    security_scans.py govramp [--workbook F.xlsx]        the AccessControlGapRules the change must meet
    security_scans.py review govramp.json --id ID --result met|gap|not_affected --evidence "file:line ..."
    security_scans.py verdict F1.json [F2.json ...] [--markdown]
                                                         one PASS / FAIL / PASS_WITH_WARNINGS for /pr-readiness

Result status: clean, findings, checklist (govramp), not_set_up or error. "blocking" lists what stops the PR:
findings at a blocking severity, on the code-fix track, in what the change touched (or anywhere, with
block_pre_existing). The only write anywhere is starting a Checkmarx scan; Wiz, Confluence and Jira are read.
"""
import argparse
import hashlib
import json
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
import io

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
RULES = os.path.join(ROOT, ".devin", "rules", "security-scans.yaml")
SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO")
CX_IGNORED_STATES = ("NOT_EXPLOITABLE",)
CX_DONE_FAILED = ("Failed", "Canceled", "Partial")
MANIFEST = re.compile(r"(^|/)(requirements[^/]*\.txt|pyproject\.toml|Pipfile(\.lock)?|poetry\.lock|setup\.py|"
                      r"package(-lock)?\.json|yarn\.lock|npm-shrinkwrap\.json|Dockerfile[^/]*)$")
XLSX_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
WIZ_QUERY = ("query($first:Int,$after:String,$filterBy:VulnerabilityFindingFilters){"
             " vulnerabilityFindings(first:$first, after:$after, filterBy:$filterBy){"
             " nodes{ id name detailedName version fixedVersion severity status hasExploit locationPath remediation"
             " layerMetadata{ isBaseLayer }"
             " vulnerableAsset{ ... on VulnerableAssetBase{ id name type }"
             " ... on VulnerableAssetContainer{ ImageExternalId } } }"
             " pageInfo{ hasNextPage endCursor } } }")
TRACK_NOTES = {
    "code_fix": "fix in code",
    "needs_approval": "major version jump: developer decides",
    "base_image": "base image: rebuild or platform team",
    "no_vendor_fix": "no vendor fix",
    "vm_host": "VM / host patching",
}


def load(path=RULES):
    with open(path) as fh:
        return yaml.safe_load(fh)


def request(method, url, headers=None, data=None, cafile=None, timeout=60):
    """(HTTP status, body bytes). Status 0 when the host could not be reached."""
    ctx = ssl.create_default_context(cafile=cafile) if cafile else ssl.create_default_context()
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except (urllib.error.URLError, OSError) as exc:
        return 0, str(getattr(exc, "reason", exc)).encode()


def jget(body):
    try:
        return json.loads(body.decode() if isinstance(body, bytes) else body) or {}
    except ValueError:
        return {}


def result(tool, status, note="", findings=(), blocking=(), **extra):
    out = {"tool": tool, "status": status, "note": note, "findings": list(findings), "blocking": list(blocking)}
    out.update(extra)
    return out


def not_set_up(tool, what):
    return result(tool, "not_set_up", note="not set up: " + what)


def error(tool, note):
    return result(tool, "error", note=note)


def changed_files(base=None, changed=None, run=subprocess.run):
    if changed:
        return [c.strip("/") for c in changed]
    if not base:
        return []
    out = run(["git", "diff", "--name-only", base + "...HEAD"], cwd=ROOT, capture_output=True, text=True)
    return [line.strip() for line in out.stdout.splitlines() if line.strip()]


def touched_components(changed, components):
    return {c.split("/", 1)[0] for c in changed if c.split("/", 1)[0] in components}


def counts(findings):
    out = {s: 0 for s in SEVERITIES}
    for f in findings:
        out[f["severity"]] = out.get(f["severity"], 0) + 1
    return out


def graded(tool, findings, cfg, **extra):
    block = {s.upper() for s in cfg.get("blocking_severities") or ()}
    pre = bool(cfg.get("block_pre_existing"))
    blocking = [f for f in findings
                if f["severity"] in block and f.get("track", "code_fix") == "code_fix" and (f.get("in_change") or pre)]
    kept = [f for f in findings if f["severity"] in ("CRITICAL", "HIGH", "MEDIUM")]
    return result(tool, "findings" if findings else "clean", findings=kept, blocking=blocking,
                  counts=counts(findings), **extra)


# ---------------------------------------------------------------- Checkmarx

def cx_finding(r):
    data = r.get("data") or {}
    nodes = data.get("nodes") or [{}]
    vuln = r.get("vulnerabilityDetails") or {}
    return {
        "id": r.get("id") or r.get("similarityId") or "",
        "type": str(r.get("type") or "").lower(),
        "severity": str(r.get("severity") or "").upper(),
        "state": str(r.get("state") or "").upper(),
        "name": data.get("queryName") or vuln.get("cveName") or r.get("id") or "",
        "file": str(nodes[0].get("fileName") or "").lstrip("/"),
        "line": nodes[0].get("line"),
        "package": data.get("packageIdentifier") or "",
        "fix": data.get("recommendedVersion") or "",
        "track": "code_fix",
    }


def cx_in_change(f, changed):
    if f["file"]:
        return any(f["file"].endswith(c) or c.endswith(f["file"]) for c in changed)
    return any(MANIFEST.search(c) for c in changed)


def checkmarx(cfg, env, branch, changed, round_no=1, sleep=time.sleep, clock=time.time):
    c = cfg["checkmarx"]
    token = env.get(c["token_env"])
    if not token:
        return not_set_up("checkmarx", "org secret " + c["token_env"])
    if not branch:
        return not_set_up("checkmarx", "no pushed branch to scan (dry run)")
    base = c["base_url"].rstrip("/")
    head = {"Authorization": "Bearer " + token, "Accept": "application/json", "Content-Type": "application/json"}
    code, body = request("GET", base + "/projects?" + urllib.parse.urlencode({"name": c["project"]}), head)
    if code in (401, 403):
        return error("checkmarx", "Checkmarx refused the token (%d); check %s. Not retried." % (code, c["token_env"]))
    if code != 200:
        return error("checkmarx", "Checkmarx projects call returned %s" % code)
    match = [p for p in jget(body).get("projects") or [] if p.get("name") == c["project"]]
    if not match:
        return not_set_up("checkmarx", "no Checkmarx project named %s (the enterprise !security_vulnerability_scanner "
                                       "playbook creates it)" % c["project"])
    payload = {"project": {"id": match[0]["id"]}, "type": "git",
               "handler": {"repoUrl": c["repo_url"], "branch": branch},
               "config": [{"type": t, "value": {}} for t in c.get("scan_types") or ("sast", "sca")],
               "tags": {"initiated_by": "devin"}}
    code, body = request("POST", base + "/scans", head, json.dumps(payload).encode())
    scan_id = jget(body).get("id")
    if code not in (200, 201) or not scan_id:
        return error("checkmarx", "Checkmarx did not start the scan (%s)" % code)
    deadline = clock() + float(c.get("max_minutes", 60)) * 60
    while True:
        code, body = request("GET", base + "/scans/" + scan_id, head)
        status = jget(body).get("status") or ""
        if status == "Completed":
            break
        if status in CX_DONE_FAILED:
            return error("checkmarx", "scan %s ended %s" % (scan_id, status))
        if clock() > deadline:
            return error("checkmarx", "scan %s still %s after %s minutes"
                         % (scan_id, status or code, c.get("max_minutes")))
        sleep(float(c.get("poll_seconds", 30)))
    raw, offset = [], 0
    while True:
        code, body = request("GET", base + "/results?" + urllib.parse.urlencode(
            {"scan-id": scan_id, "limit": 500, "offset": offset}), head)
        if code != 200:
            return error("checkmarx", "Checkmarx results call returned %s" % code)
        page = jget(body).get("results") or []
        raw += page
        if len(page) < 500:
            break
        offset += 500
    findings = [f for f in map(cx_finding, raw) if f["state"] not in CX_IGNORED_STATES]
    for f in findings:
        f["in_change"] = cx_in_change(f, changed)
    return graded("checkmarx", findings, cfg, scan_id=scan_id, branch=branch, round=round_no)


# ---------------------------------------------------------------- Wiz

def asset_component(ref, components):
    for comp in components:
        if re.search(r"(^|[/-])%s([@:#/]|$)" % re.escape(comp), ref):
            return comp
    return ""


def major(version):
    m = re.match(r"\D*(\d+)", str(version or ""))
    return int(m.group(1)) if m else None


def wiz_track(n, asset):
    if str(asset.get("type") or "").upper() in ("VIRTUAL_MACHINE", "VIRTUAL_MACHINE_IMAGE"):
        return "vm_host"
    if not n.get("fixedVersion") and not n.get("remediation"):
        return "no_vendor_fix"
    if (n.get("layerMetadata") or {}).get("isBaseLayer"):
        return "base_image"
    have, fix = major(n.get("version")), major(str(n.get("fixedVersion") or "").split(",")[0])
    if have is not None and fix is not None and fix > have:
        return "needs_approval"
    return "code_fix"


def wiz_finding(n, components):
    asset = n.get("vulnerableAsset") or {}
    ref = asset.get("ImageExternalId") or asset.get("name") or ""
    return {
        "id": n.get("id") or "",
        "severity": str(n.get("severity") or "").upper(),
        "name": n.get("name") or "",
        "package": n.get("detailedName") or "",
        "version": n.get("version") or "",
        "fix": n.get("fixedVersion") or "",
        "file": n.get("locationPath") or "",
        "exploit": bool(n.get("hasExploit")),
        "asset_type": asset.get("type") or "",
        "component": asset_component(ref, components),
        "track": wiz_track(n, asset),
    }


def wiz(cfg, env, changed, round_no=1):
    w = cfg["wiz"]
    cid, secret = env.get(w["client_id_env"]), env.get(w["client_secret_env"])
    if not (cid and secret):
        return not_set_up("wiz", "org secrets %s / %s" % (w["client_id_env"], w["client_secret_env"]))
    apm = str(cfg.get("apm_id") or "").strip()
    if not apm:
        return not_set_up("wiz", "apm_id in security-scans.yaml")
    form = urllib.parse.urlencode({"grant_type": "client_credentials", "audience": "wiz-api",
                                   "client_id": cid, "client_secret": secret}).encode()
    code, body = request("POST", w["auth_url"], {"Content-Type": "application/x-www-form-urlencoded"}, form)
    if code == 401:
        return error("wiz", "Wiz does not recognise the client ID (401); check %s for this org." % w["client_id_env"])
    if code == 400:
        return error("wiz", "Wiz rejected the client secret (400); it may be wrong or rotated.")
    token = jget(body).get("access_token")
    if not token:
        return error("wiz", "Wiz token call returned %s" % code)
    filt = {"status": ["OPEN", "IN_PROGRESS"],
            "assetTags": {"containsAny": [{"key": "apm-id", "value": apm.lower()}]},
            "assetType": list(w["asset_types"])}
    head = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
    nodes, after = [], None
    for _ in range(int(w.get("max_pages", 40))):
        query = {"query": WIZ_QUERY, "variables": {"first": 500, "after": after, "filterBy": filt}}
        code, body = request("POST", w["api_url"], head, json.dumps(query).encode())
        data = jget(body)
        if code != 200 or data.get("errors"):
            msg = ((data.get("errors") or [{}])[0].get("message") or "")[:200]
            return error("wiz", "Wiz findings query returned %s %s" % (code, msg))
        conn = (data.get("data") or {}).get("vulnerabilityFindings") or {}
        nodes += conn.get("nodes") or []
        info = conn.get("pageInfo") or {}
        if not info.get("hasNextPage"):
            break
        after = info.get("endCursor")
    components = cfg.get("components") or []
    touched = touched_components(changed, components)
    manifests = {c.split("/", 1)[0] for c in changed if MANIFEST.search(c)}
    findings = [f for f in (wiz_finding(n, components) for n in nodes) if f["component"]]
    for f in findings:
        f["in_change"] = f["component"] in touched and f["component"] in manifests
    tracks = {}
    for f in findings:
        tracks[f["track"]] = tracks.get(f["track"], 0) + 1
    return graded("wiz", findings, cfg, apm=apm, round=round_no, tracks=tracks,
                  unmatched=len(nodes) - len(findings), touched=sorted(touched))


# ---------------------------------------------------------------- GovRAMP

def col_letters(ref):
    return "".join(ch for ch in ref if ch.isalpha())


def read_xlsx(data):
    """Rows of the first sheet as {column letter: text}. Stdlib only."""
    z = zipfile.ZipFile(io.BytesIO(data))
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall(XLSX_NS + "si"):
            shared.append("".join(t.text or "" for t in si.iter(XLSX_NS + "t")))
    sheets = sorted(n for n in z.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml$", n))
    rows = []
    for row in ET.fromstring(z.read(sheets[0])).iter(XLSX_NS + "row"):
        cells = {}
        for c in row.findall(XLSX_NS + "c"):
            v = c.find(XLSX_NS + "v")
            if c.get("t") == "s" and v is not None:
                text = shared[int(v.text)]
            elif c.get("t") == "inlineStr":
                text = "".join(t.text or "" for t in c.iter(XLSX_NS + "t"))
            else:
                text = v.text if v is not None else ""
            if text:
                cells[col_letters(c.get("r") or "")] = text.strip()
        rows.append(cells)
    return rows


def gap_rules(rows, g):
    need = set(g["required_columns"])
    for i, row in enumerate(rows):
        if need <= set(row.values()):
            header = {v: k for k, v in row.items()}
            break
    else:
        return None
    cols = {field: header.get(name) for field, name in g["columns"].items()}
    rules = []
    for row in rows[i + 1:]:
        rule = {field: row.get(col, "") if col else "" for field, col in cols.items()}
        if rule.get("id"):
            rules.append(rule)
    return rules


def govramp(cfg, env, workbook=None):
    g = cfg["govramp"]
    if workbook:
        with open(workbook, "rb") as fh:
            data = fh.read()
        source = {"source": "file", "path": os.path.basename(workbook)}
        rules = gap_rules(read_xlsx(data), g)
        if rules is None:
            return error("govramp", "%s is not an AccessControlGapRules workbook" % source["path"])
    else:
        token = env.get(g["token_env"])
        if not token:
            return not_set_up("govramp", "org secret " + g["token_env"])
        cafile = os.path.expanduser(g["ca_file"])
        if not os.path.exists(cafile):
            return not_set_up("govramp", "Confluence root CA at %s (security-scans.yaml says how)" % g["ca_file"])
        base = g["confluence_url"].rstrip("/")
        head = {"Authorization": "Bearer " + token, "Accept": "application/json"}
        url = base + "/rest/api/content/%s/child/attachment?expand=version&limit=100" % g["page_id"]
        code, body = request("GET", url, head, cafile=cafile)
        if code in (401, 403):
            return error("govramp", "Confluence refused the service account (%d). Not retried." % code)
        if code != 200:
            return error("govramp", "Confluence attachments call returned %s" % code)
        rules, source = None, {}
        for att in jget(body).get("results") or []:
            if not str(att.get("title") or "").lower().endswith(".xlsx"):
                continue
            code, data = request("GET", base + att["_links"]["download"], head, cafile=cafile)
            if code != 200:
                continue
            try:
                rules = gap_rules(read_xlsx(data), g)
            except (zipfile.BadZipFile, ET.ParseError, IndexError):
                rules = None
            if rules is not None:
                source = {"source": "confluence", "page_id": g["page_id"], "attachment": att.get("title"),
                          "version": (att.get("version") or {}).get("number")}
                break
        if rules is None:
            return error("govramp", "no AccessControlGapRules workbook on Confluence page %s" % g["page_id"])
    layers = set(g.get("layers") or ())
    in_scope = [r for r in rules if not layers or r.get("layer") in layers]
    return result("govramp", "checklist", note="%d of %d gap rules need something from the application"
                  % (len(in_scope), len(rules)), rules=in_scope, rule_count=len(rules), review=[],
                  sha256=hashlib.sha256(data).hexdigest(), **source)


def review(res, rule_id, outcome, evidence):
    if outcome not in ("met", "gap", "not_affected"):
        raise ValueError("result must be met, gap or not_affected")
    rule = next((r for r in res.get("rules") or [] if r["id"] == rule_id), None)
    if rule is None:
        raise ValueError("%s is not one of the gap rules in this result" % rule_id)
    res["review"] = [r for r in res.get("review") or [] if r["id"] != rule_id]
    res["review"].append({"id": rule_id, "result": outcome, "evidence": evidence})
    res["blocking"] = [{"severity": "HIGH", "name": "GovRAMP %s %s" % (r["id"], rule_name(res, r["id"])),
                        "file": r["evidence"], "track": "code_fix"}
                       for r in res["review"] if r["result"] == "gap"]
    return res


def rule_name(res, rule_id):
    return next((r.get("name", "") for r in res.get("rules") or [] if r["id"] == rule_id), "")


# ---------------------------------------------------------------- verdict

def verdict(results):
    blocking, warnings = [], []
    for r in results:
        if r["status"] in ("not_set_up", "error"):
            warnings.append("%s not run: %s" % (r["tool"], r["note"]))
        if r["tool"] == "govramp" and r["status"] == "checklist" and not r.get("review"):
            warnings.append("govramp: no gap rule was reviewed against the change")
        blocking += [dict(f, tool=r["tool"]) for f in r.get("blocking") or []]
        held = [f for f in r.get("findings") or [] if f.get("track", "code_fix") != "code_fix"
                and f["severity"] in ("CRITICAL", "HIGH")]
        if held:
            warnings.append("%s: %d high/critical findings code cannot fix (%s)" % (
                r["tool"], len(held), ", ".join(sorted({TRACK_NOTES.get(f["track"], f["track"]) for f in held}))))
    overall = "FAIL" if blocking else ("PASS_WITH_WARNINGS" if warnings else "PASS")
    return {"overall": overall, "blocking": blocking, "warnings": warnings,
            "tools": [{"tool": r["tool"], "status": r["status"], "round": r.get("round"),
                       "counts": r.get("counts"), "note": r.get("note")} for r in results]}


def markdown(v):
    lines = ["## Security scans: %s" % v["overall"], "", "| Tool | Result | Critical | High | Note |",
             "|---|---|---|---|---|"]
    for t in v["tools"]:
        c = t.get("counts") or {}
        rnd = " (round %s)" % t["round"] if t.get("round") else ""
        lines.append("| %s | %s%s | %s | %s | %s |" % (t["tool"], t["status"], rnd, c.get("CRITICAL", "-"),
                                                       c.get("HIGH", "-"), t.get("note") or ""))
    if v["blocking"]:
        lines += ["", "**Blocking**"]
        for f in v["blocking"]:
            where = f.get("file", "") + (":%s" % f["line"] if f.get("line") else "")
            lines.append("- %s: %s %s %s" % (f["tool"], f["severity"], f.get("name", ""), where))
    if v["warnings"]:
        lines += ["", "**Warnings**"] + ["- " + w for w in v["warnings"]]
    return "\n".join(lines)


def preflight(cfg, env):
    c, w, g = cfg["checkmarx"], cfg["wiz"], cfg["govramp"]
    return {
        "checkmarx": "set up" if env.get(c["token_env"]) else "not set up: org secret " + c["token_env"],
        "wiz": "set up" if env.get(w["client_id_env"]) and env.get(w["client_secret_env"])
        else "not set up: org secrets %s / %s" % (w["client_id_env"], w["client_secret_env"]),
        "govramp": "set up" if env.get(g["token_env"]) and os.path.exists(os.path.expanduser(g["ca_file"]))
        else "not set up: org secret %s and %s" % (g["token_env"], g["ca_file"]),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["preflight", "checkmarx", "wiz", "govramp", "review", "verdict"])
    ap.add_argument("files", nargs="*")
    ap.add_argument("--branch")
    ap.add_argument("--base", help="base branch; the changed files are git diff BASE...HEAD")
    ap.add_argument("--changed", nargs="*", help="changed files, instead of --base")
    ap.add_argument("--round", type=int, default=1)
    ap.add_argument("--workbook")
    ap.add_argument("--id")
    ap.add_argument("--result")
    ap.add_argument("--evidence", default="")
    ap.add_argument("--markdown", action="store_true")
    ap.add_argument("--out")
    ap.add_argument("--rules", default=RULES)
    a = ap.parse_args(argv)
    cfg, env = load(a.rules), os.environ
    if a.command == "preflight":
        out = preflight(cfg, env)
    elif a.command == "checkmarx":
        out = checkmarx(cfg, env, a.branch, changed_files(a.base, a.changed), a.round)
    elif a.command == "wiz":
        out = wiz(cfg, env, changed_files(a.base, a.changed), a.round)
    elif a.command == "govramp":
        out = govramp(cfg, env, a.workbook)
    elif a.command == "review":
        if len(a.files) != 1 or not (a.id and a.result):
            ap.error("review needs one govramp result file, --id and --result")
        with open(a.files[0]) as fh:
            out = review(json.load(fh), a.id, a.result, a.evidence)
        a.out = a.out or a.files[0]
    else:
        results = []
        for path in a.files:
            with open(path) as fh:
                results.append(json.load(fh))
        out = verdict(results)
        if a.markdown:
            print(markdown(out))
            return 1 if out["overall"] == "FAIL" else 0
    if a.out:
        with open(a.out, "w") as fh:
            json.dump(out, fh, indent=2)
    print(json.dumps(out, indent=2))
    return 1 if a.command == "verdict" and out["overall"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
