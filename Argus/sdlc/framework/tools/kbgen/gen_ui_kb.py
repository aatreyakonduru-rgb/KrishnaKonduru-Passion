"""Regenerate 12_COMPONENT_REGISTRY.yaml from the Next.js source tree."""
import json
import os
import re
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
KB = REPO / "docs" / "knowledge-base"
# SDLC_KB_OUT: write into a staging copy of the KB (e.g. _REGEN/<date>) instead of the live one.
KB_OUT = Path(os.environ.get("SDLC_KB_OUT") or KB)

FE = str(REPO / "web")
SRC = os.path.join(FE, "src")
OUT = str(KB_OUT / "MODULES/claims-web/web/12_COMPONENT_REGISTRY.yaml")
os.makedirs(os.path.dirname(OUT), exist_ok=True)
TODAY = date.today().isoformat()


def q(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def read(p):
    return open(p, encoding="utf-8", errors="replace").read()


# ---------------------------------------------------------------- endpoints.ts
ep_src = read(os.path.join(SRC, "Services/Utility/endpoints.ts"))
bases = dict(re.findall(r"const (\w+) = \(\) => `\$\{BASE_URL\}\$\{bp\(\)\}(/api/[\w/]*)`", ep_src))
getters = {}
for name, body in re.findall(r"^\s{2}(\w+):\s*(?:\(\) =>\s*)?`([^`]*)`,", ep_src, re.M):
    url = body
    for b, v in bases.items():
        url = url.replace("${%s()}" % b, v)
    url = re.sub(r"\$\{BASE_URL\}", "", url)
    getters[name] = url
# aliases that point at a base function directly
for name, base in re.findall(r"^\s{2}(\w+):\s*(\w+_BASE),", ep_src, re.M):
    if base in bases:
        getters[name] = bases[base]

# --------------------------------------------------------------------- routes
routes = []
app_dir = os.path.join(SRC, "app")
for dirpath, _d, files in os.walk(app_dir):
    if "page.tsx" not in files:
        continue
    route = "/" + os.path.relpath(dirpath, app_dir).replace(os.sep, "/")
    route = "/" if route == "/." else route
    page = os.path.join(dirpath, "page.tsx")
    body = read(page)
    imports = re.findall(r'from\s+["\'](?:@/|\.{1,2}/)?([^"\']*Services/[\w./-]+)["\']', body)
    routes.append({
        "route": route,
        "file": os.path.relpath(page, os.path.dirname(FE)).replace(os.sep, "/"),
        "loc": body.count("\n") + 1,
        "client_component": body.lstrip().startswith('"use client"') or body.lstrip().startswith("'use client'"),
        "services": sorted({i.split("/")[-1] for i in imports}),
    })
routes.sort(key=lambda r: r["route"])

# ------------------------------------------------------------------- services
def code(text):
    """Source without block comments and whole-line // comments."""
    return re.sub(r"(?m)^\s*//.*$", "", re.sub(r"(?s)/\*.*?\*/", "", text))


def auth_pattern():
    """What the frontend code shows about the API token; nothing more is claimed."""
    hits = []
    for dirpath, _dirs, files in os.walk(os.path.join(SRC, "Services")):
        for f in files:
            if f.endswith((".ts", ".tsx")) and re.search(r"\bAuthorization\b", code(read(os.path.join(dirpath, f)))):
                hits.append(os.path.relpath(os.path.join(dirpath, f), os.path.dirname(FE)).replace(os.sep, "/"))
    if hits:
        return "Authorization header set in " + ", ".join(sorted(hits))
    return "unknown: no Authorization header is set in src/Services; how the token reaches the API is not in this code"


AUTH_PATTERN = auth_pattern()
services = []
svc_dir = os.path.join(SRC, "Services")
for f in sorted(os.listdir(svc_dir)):
    if not f.endswith(".ts"):
        continue
    body = code(read(os.path.join(svc_dir, f)))
    funcs = sorted(set(re.findall(r"export\s+(?:async\s+)?function\s+(\w+)", body)
                       + re.findall(r"export\s+const\s+(\w+)\s*(?::[^=]+)?=\s*(?:async\b|\(|<|\w+\s*=>)", body)))
    used = sorted({e for e in getters if re.search(r"\b%s\b" % re.escape(e), body)})
    urls = sorted({getters[e] for e in used})
    services.append({
        "name": f[:-3],
        "file": f"web/src/Services/{f}",
        "functions": funcs,
        "endpoint_symbols": used,
        "api_paths": urls,
    })

# ----------------------------------------------------------------- components
components = []
comp_root = os.path.join(SRC, "_components")
if os.path.isdir(comp_root):
    for name in sorted(os.listdir(comp_root)):
        d = os.path.join(comp_root, name)
        if not os.path.isdir(d):
            continue
        files = [os.path.join(dp, fn) for dp, _x, fs in os.walk(d) for fn in fs
                 if fn.endswith((".tsx", ".ts"))]
        components.append({"name": name, "dir": f"web/src/_components/{name}",
                           "files": len(files)})

# --------------------------------------------- cross-check against API registry
import yaml  # noqa: E402
_endpoints = KB_OUT / "MODULES/claims-web/api/10_ENDPOINT_REGISTRY.yaml"
reg = yaml.safe_load(open(_endpoints if _endpoints.exists() else KB / "MODULES/claims-web/api/10_ENDPOINT_REGISTRY.yaml"))
api_paths = set()
for r in reg["routers"]:
    for e in r["endpoints"]:
        p = str(e["path"])
        p = p if p.startswith("/") else "/" + p
        api_paths.add(("/api" + r["prefix"].rstrip("/") + p).rstrip("/"))

unmatched = []
for sym, url in sorted(getters.items()):
    path = url.split("?")[0].rstrip("/")
    if not path.startswith("/api"):
        continue
    if path in api_paths:
        continue
    # tolerate path params: /api/users/get_user vs /api/users/get_user/{user_id}/{moduleName}
    if any(a.startswith(path + "/{") for a in api_paths):
        continue
    if path in {p.rsplit("/", 1)[0] for p in api_paths if "{" in p}:
        continue
    if path in {"/api" + r["prefix"].rstrip("/") for r in reg["routers"]}:
        continue  # base-URL constant, not an endpoint
    unmatched.append((sym, url))

lines = [
    "# Acme Claims Frontend Component Registry",
    "# Confidence: 1.0 — generated by static scan of web/src",
    f'# Generated: {TODAY}',
    "# Routes come from the Next.js app router tree, services from src/Services/*.ts,",
    "# and API paths are resolved from the endpoints.ts getter templates.",
    "",
    "metadata:",
    "  confidence: 1.0",
    f'  generated: "{TODAY}"',
    '  framework: "Next.js App Router + React + TypeScript"',
    '  base_path: "/${CLIENT_BUSINS_TYPE} (default /acme)"',
    '  generation_method: "static scan of web/src (app router pages, Services, _components)"',
    f"  total_routes: {len(routes)}",
    f"  total_services: {len(services)}",
    f"  total_component_groups: {len(components)}",
    f"  total_endpoint_symbols: {len(getters)}",
    "  auth_pattern: %s" % json.dumps(AUTH_PATTERN),
    "",
    "routes:",
]
for r in routes:
    lines += [
        f"  - route: {q(r['route'])}",
        f"    page: {r['file']}",
        f"    client_component: {str(r['client_component']).lower()}",
        f"    lines_of_code: {r['loc']}",
        f"    services_imported: {json.dumps(r['services'])}",
    ]

lines += ["", "services:"]
for s in services:
    lines += [
        f"  - name: {s['name']}",
        f"    file: {s['file']}",
        f"    exported_functions: {json.dumps(s['functions'])}",
        f"    api_paths: {json.dumps(s['api_paths'])}",
    ]

lines += ["", "component_groups:"]
for c in components:
    lines.append(f"  - {{ name: {c['name']}, dir: {c['dir']}, files: {c['files']} }}")

lines += ["", "endpoint_symbols:"]
for sym, url in sorted(getters.items()):
    lines.append(f"  - {{ symbol: {sym}, url: {q(url)} }}")

lines += [
    "",
    "# Frontend endpoint symbols whose resolved path has no match in",
    "# 10_ENDPOINT_REGISTRY.yaml (i.e. the API does not expose them).",
    "unmatched_against_api_registry:",
]
for sym, url in unmatched:
    lines.append(f"  - {{ symbol: {sym}, url: {q(url)} }}")
if not unmatched:
    lines.append("  []")

open(OUT, "w").write("\n".join(lines).rstrip("\n") + "\n")
print("routes", len(routes), "services", len(services), "symbols", len(getters),
      "unmatched", len(unmatched))
for u in unmatched:
    print("   ", u[0], u[1])
