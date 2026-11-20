#!/usr/bin/env python3
"""Build a first knowledge base from the repository Argus is installed in. No Jira, database or network.

    python3 sdlc/framework/tools/kb_scan.py [--kb docs/knowledge-base] [--stage DIR] [--no-manifest] [--json]
    python3 sdlc/framework/tools/kb_scan.py --check          exit 1 when the written files no longer match the code

Reads the code with static scans (the standard library only) and writes, under <kb>/REPO-SCAN/ (or --stage):

    00_REPO_OVERVIEW.md      languages, layout, entry points, tests, CI, README summary, git commit
    10_ENDPOINT_REGISTRY.yaml  HTTP routes found in Python, JavaScript and TypeScript, each with file:line
    20_DATA_MODEL.yaml       tables from CREATE TABLE and Django models, and tables named in SQL, each with file:line
    30_DEPENDENCIES.yaml     requirements*.txt, package.json, pyproject.toml
    40_UI_ROUTES.yaml        Next.js app/ and pages/ routes
    README.md                what these files are and how they were made

These are facts read from the source, not a replacement for the narrative prompts (/kb-build, /app-run-pipeline),
which add the business meaning. Run this first: the narrative runs then have a map to start from.

It never overwrites a file it did not write (every file carries `generator: kb_scan.py`), never reads secrets
(it records names, paths and line numbers, not values), and skips this framework itself (.devin, sdlc), the
knowledge base and the usual build and dependency folders.
"""
import argparse
import datetime
import fnmatch
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
GENERATOR = "kb_scan.py 1"
OUT_DIR = "REPO-SCAN"
MAX_FILES = 20000
MAX_BYTES = 1_000_000
SKIP_DIRS = {".git", ".devin", "sdlc", "node_modules", "venv", ".venv", "env", "__pycache__", "dist", "build",
             ".next", ".nuxt", "target", ".tox", ".mypy_cache", ".pytest_cache", ".idea", ".vscode",
             ".console-state", "vendor", "coverage"}
LANGUAGES = {".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
             ".ts": "TypeScript", ".tsx": "TypeScript", ".java": "Java", ".kt": "Kotlin", ".go": "Go", ".rb": "Ruby",
             ".php": "PHP", ".cs": "C#", ".sql": "SQL", ".sh": "Shell", ".yml": "YAML", ".yaml": "YAML",
             ".html": "HTML", ".css": "CSS", ".scss": "CSS", ".md": "Markdown"}
CODE_EXT = {".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".java", ".kt", ".go", ".rb", ".php", ".cs", ".sql"}
METHODS = ("get", "post", "put", "delete", "patch")
ENTRY_FILES = ("manage.py", "run.py", "main.py", "app.py", "wsgi.py", "asgi.py", "server.js", "index.js", "main.go",
               "Dockerfile", "docker-compose.yml", "docker-compose.yaml", "Makefile", "package.json",
               "pyproject.toml", "requirements.txt", "pom.xml", "build.gradle")


def read(path):
    try:
        if os.path.getsize(path) > MAX_BYTES:
            return ""
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def git(root, *args):
    try:
        done = subprocess.run(["git", "-C", root] + list(args), capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def skipped(rel, kb_rel, extra=()):
    parts = rel.split("/")
    if any(p in SKIP_DIRS for p in parts[:-1]):
        return True
    if rel.startswith(kb_rel.strip("/") + "/"):
        return True
    return any(fnmatch.fnmatch(rel, pat) for pat in extra)


def list_files(root, kb_rel, extra=()):
    """Repo-relative paths, forward slashes. git's own list when there is a repo (it honours .gitignore)."""
    found = git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    if found:
        names = [n for n in found.split("\0") if n]
    else:
        names = []
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for f in files:
                names.append(os.path.relpath(os.path.join(dirpath, f), root).replace(os.sep, "/"))
    out = [n for n in names if not skipped(n, kb_rel, extra) and os.path.isfile(os.path.join(root, n))]
    return sorted(out)[:MAX_FILES]


def line_of(text, index):
    return text.count("\n", 0, index) + 1


# --------------------------------------------------------------------------- overview

def overview(root, files, texts):
    langs = {}
    for rel in files:
        lang = LANGUAGES.get(os.path.splitext(rel)[1].lower())
        if not lang:
            continue
        entry = langs.setdefault(lang, {"files": 0, "lines": 0})
        entry["files"] += 1
        entry["lines"] += texts.get(rel, "").count("\n")
    top = {}
    for rel in files:
        key = rel.split("/")[0] if "/" in rel else "(repo root)"
        top[key] = top.get(key, 0) + 1
    tests = [r for r in files if re.search(r"(^|/)(tests?|__tests__|spec)(/|$)|(^|/)test_[^/]*\.py$|\.(test|spec)\.[jt]sx?$", r)]
    ci = [r for r in files if r.startswith(".github/workflows/") or r in (".gitlab-ci.yml", "Jenkinsfile", "azure-pipelines.yml",
                                                                         "bitbucket-pipelines.yml")]
    entry = [r for r in files if os.path.basename(r) in ENTRY_FILES and r.count("/") <= 2]
    readme = next((r for r in files if os.path.basename(r).lower() == "readme.md" and "/" not in r), "")
    summary = ""
    if readme:
        for para in re.split(r"\n\s*\n", texts.get(readme, "")):
            clean = para.strip()
            if clean and not clean.startswith(("#", "!", "[", "<", "```", "|", "-", "*")):
                summary = re.sub(r"\s+", " ", clean)[:400]
                break
    return {"languages": dict(sorted(langs.items(), key=lambda kv: -kv[1]["lines"])), "top_level": dict(sorted(top.items())),
            "tests": tests, "ci": ci, "entry_points": entry, "readme": readme, "readme_summary": summary}


# --------------------------------------------------------------------------- endpoints

PY_DECORATOR = re.compile(r"^[ \t]*@(\w+)\.(get|post|put|delete|patch|route)\(\s*(?:path\s*=\s*)?[\"']([^\"']*)[\"']([^\n]*)", re.M)
PY_DEF = re.compile(r"^[ \t]*(?:async\s+)?def\s+(\w+)\s*\(", re.M)
DJANGO_PATH = re.compile(r"\b(?:re_)?path\(\s*r?[\"']([^\"']*)[\"']\s*,\s*([\w.]+)")
JS_ROUTE = re.compile(r"\b(\w+)\.(get|post|put|delete|patch)\(\s*[\"'`]([^\"'`]+)[\"'`]")
NEXT_METHOD = re.compile(r"export\s+(?:async\s+)?(?:function|const)\s+(GET|POST|PUT|DELETE|PATCH)\b")


def framework_of(text):
    low = text[:6000]
    if re.search(r"^\s*(from|import)\s+ninja\b", low, re.M):
        return "django-ninja"
    if re.search(r"^\s*(from|import)\s+fastapi\b", low, re.M):
        return "fastapi"
    if re.search(r"^\s*(from|import)\s+flask\b", low, re.M):
        return "flask"
    return "python"


def endpoints(files, texts):
    out = []
    for rel in files:
        ext = os.path.splitext(rel)[1].lower()
        text = texts.get(rel, "")
        if not text:
            continue
        if ext == ".py":
            fw = framework_of(text)
            for m in PY_DECORATOR.finditer(text):
                verb = m.group(2).upper()
                if verb == "ROUTE":
                    ms = re.search(r"methods\s*=\s*\[([^\]]*)\]", m.group(4))
                    verb = "/".join(re.findall(r"[A-Za-z]+", ms.group(1))).upper() if ms else "GET"
                handler = PY_DEF.search(text, m.end())
                out.append({"method": verb, "path": m.group(3), "handler": handler.group(1) if handler else "",
                            "framework": fw, "file": rel, "line": line_of(text, m.start()),
                            "router": m.group(1)})
            if os.path.basename(rel) == "urls.py":
                for m in DJANGO_PATH.finditer(text):
                    out.append({"method": "ANY", "path": m.group(1), "handler": m.group(2), "framework": "django",
                                "file": rel, "line": line_of(text, m.start()), "router": "urlpatterns"})
        elif ext in (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"):
            base = os.path.basename(rel)
            if re.fullmatch(r"route\.(js|ts)", base) and re.search(r"(^|/)app/", rel):
                route = "/" + re.sub(r"^.*?(?:^|/)app/", "", rel.rsplit("/", 1)[0]).strip("/")
                for m in NEXT_METHOD.finditer(text):
                    out.append({"method": m.group(1), "path": route.replace("//", "/"), "handler": m.group(1),
                                "framework": "next-route-handler", "file": rel, "line": line_of(text, m.start()),
                                "router": ""})
                continue
            if "express" in text or re.search(r"\b(app|router|server)\.(get|post|put|delete|patch)\(", text):
                for m in JS_ROUTE.finditer(text):
                    if m.group(1) in ("app", "router", "server", "api", "routes"):
                        out.append({"method": m.group(2).upper(), "path": m.group(3), "handler": "",
                                    "framework": "express", "file": rel, "line": line_of(text, m.start()),
                                    "router": m.group(1)})
    seen, unique = set(), []
    for e in out:
        key = (e["method"], e["path"], e["file"], e["line"])
        if key not in seen:
            seen.add(key)
            unique.append(e)
    return sorted(unique, key=lambda e: (e["file"], e["line"]))


# --------------------------------------------------------------------------- data

CREATE_TABLE = re.compile(r"CREATE\s+(?:OR\s+REPLACE\s+)?(?:TEMP(?:ORARY)?\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([\w.\"`\[\]]+)\s*\(",
                          re.I)
SQL_REF = re.compile(r"\b(FROM|JOIN|INTO|UPDATE)\s+([A-Za-z_][\w.]*)")
SQL_WORDS = {"SELECT", "WHERE", "SET", "VALUES", "DUAL", "TABLE", "ONLY", "THE", "LATERAL"}
CONSTRAINT = ("PRIMARY", "FOREIGN", "UNIQUE", "CONSTRAINT", "KEY", "INDEX", "CHECK")
DJANGO_MODEL = re.compile(r"^class\s+(\w+)\(([^)]*Model[^)]*)\):", re.M)
DJANGO_FIELD = re.compile(r"^\s{4}(\w+)\s*=\s*(?:models\.)?(\w+(?:Field|Key))\(", re.M)


def columns(block):
    cols = []
    depth, cur = 0, ""
    for ch in block:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            cols.append(cur)
            cur = ""
        else:
            cur += ch
    cols.append(cur)
    out = []
    for c in cols:
        parts = c.strip().split()
        if len(parts) >= 1 and parts[0].strip("\"`[]").upper() not in CONSTRAINT and re.match(r"^[\"`\[]?\w+", parts[0]):
            out.append({"name": parts[0].strip("\"`[]"), "type": parts[1].upper() if len(parts) > 1 else ""})
    return out


def data_model(files, texts):
    tables, models, refs = [], [], {}
    for rel in files:
        ext = os.path.splitext(rel)[1].lower()
        text = texts.get(rel, "")
        if not text or ext not in CODE_EXT:
            continue
        for m in CREATE_TABLE.finditer(text):
            start = m.end()
            depth, i = 1, start
            while i < len(text) and depth and i - start < 6000:
                depth += {"(": 1, ")": -1}.get(text[i], 0)
                i += 1
            tables.append({"table": m.group(1).strip("\"`[]"), "kind": "sql", "file": rel, "line": line_of(text, m.start()),
                           "columns": columns(text[start:i - 1])})
        if ext == ".py":
            for m in DJANGO_MODEL.finditer(text):
                nxt = DJANGO_MODEL.search(text, m.end())
                body = text[m.end():nxt.start() if nxt else len(text)]
                fields = [{"name": f.group(1), "type": f.group(2)} for f in DJANGO_FIELD.finditer(body)]
                if fields:
                    models.append({"model": m.group(1), "kind": "django-model", "file": rel,
                                   "line": line_of(text, m.start()), "columns": fields})
        for m in SQL_REF.finditer(text):
            name = m.group(2)
            if name.upper() in SQL_WORDS or name.islower() and ext != ".sql" and "_" not in name and "." not in name:
                continue
            refs.setdefault(name, []).append("%s:%d" % (rel, line_of(text, m.start())))
    referenced = [{"table": t, "used_at": sorted(set(w))[:12], "uses": len(w)} for t, w in sorted(refs.items())]
    return tables, models, referenced


# --------------------------------------------------------------------------- dependencies, UI routes

def dependencies(files, texts):
    out = []
    for rel in files:
        base = os.path.basename(rel)
        text = texts.get(rel) or ""
        if re.fullmatch(r"requirements[\w.-]*\.txt", base):
            pkgs = []
            for n, line in enumerate(text.splitlines(), 1):
                m = re.match(r"^([A-Za-z0-9][A-Za-z0-9_.\-]*)\s*([<>=!~][^#;]*)?", line.strip())
                if m and not line.strip().startswith(("-", "#")):
                    pkgs.append({"name": m.group(1), "spec": (m.group(2) or "").strip(), "line": n})
            out.append({"file": rel, "kind": "python-requirements", "packages": pkgs})
        elif base == "package.json":
            try:
                data = json.loads(text)
            except ValueError:
                continue
            out.append({"file": rel, "kind": "node-package", "name": data.get("name", ""),
                        "scripts": sorted((data.get("scripts") or {}).keys()),
                        "dependencies": data.get("dependencies") or {}, "dev_dependencies": data.get("devDependencies") or {}})
        elif base == "pyproject.toml":
            try:
                import tomllib
                data = tomllib.loads(text)
            except (ImportError, ValueError):
                out.append({"file": rel, "kind": "pyproject", "note": "not parsed (needs Python 3.11+ tomllib)"})
                continue
            out.append({"file": rel, "kind": "pyproject", "name": (data.get("project") or {}).get("name", ""),
                        "dependencies": (data.get("project") or {}).get("dependencies") or []})
    return out


def ui_routes(files):
    out = []
    for rel in files:
        m = re.match(r"^(?:(.*?)/)?(app|pages)/(.*)/?(page|index)\.(tsx|jsx|js|ts)$", rel)
        if not m:
            m2 = re.match(r"^(?:(.*?)/)?(app|pages)/(page|index)\.(tsx|jsx|js|ts)$", rel)
            if not m2:
                continue
            route, kind = "/", m2.group(2)
        else:
            kind = m.group(2)
            route = "/" + re.sub(r"/(page|index)$", "", m.group(3).strip("/")).strip("/")
            if m.group(4) == "index" and kind == "app":
                continue
        route = re.sub(r"\([^)]*\)/?", "", route).replace("//", "/") or "/"
        out.append({"route": route, "router": "next-" + kind, "file": rel})
    return sorted(out, key=lambda r: r["route"])


# --------------------------------------------------------------------------- writing

def dump(value, indent=0):
    """A small YAML writer (no PyYAML needed): dicts, lists, strings, numbers, booleans."""
    pad = "  " * indent
    lines = []
    if isinstance(value, dict):
        if not value:
            return [pad + "{}"]
        for k, v in value.items():
            if isinstance(v, (dict, list)) and v:
                lines.append("%s%s:" % (pad, scalar_key(k)))
                lines += dump(v, indent + 1)
            else:
                lines.append("%s%s: %s" % (pad, scalar_key(k), scalar(v)))
    elif isinstance(value, list):
        if not value:
            return [pad + "[]"]
        for item in value:
            if isinstance(item, (dict, list)) and item:
                sub = dump(item, indent + 1)
                lines.append(pad + "- " + sub[0].lstrip())
                lines += sub[1:]
            else:
                lines.append("%s- %s" % (pad, scalar(item)))
    else:
        lines.append(pad + scalar(value))
    return lines


def scalar_key(k):
    return scalar(k) if re.search(r"[:#\s]", str(k)) else str(k)


def scalar(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, dict):
        return "{}"
    if isinstance(v, list):
        return "[]"
    return json.dumps(str(v), ensure_ascii=False)


def header(commit, today):
    return {"generator": GENERATOR, "source": "repository scan at commit %s" % (commit or "unknown (not a git repo)"),
            "generated": today}


def yaml_file(title, head, body):
    lines = ["# %s" % title] + dump(head) + dump(body)
    return "\n".join(lines) + "\n"


def mine(path):
    """True when the file is absent or was written by this tool (its first lines say so)."""
    if not os.path.exists(path):
        return True
    head = read(path)[:1500]
    return "generator: kb_scan.py" in head or "**Generator:** kb_scan.py" in head


def build(root, kb="docs/knowledge-base", extra_exclude=(), today=None, commit=None):
    """The scan result as a dict of file name -> text, plus counts. Writes nothing."""
    today = today or datetime.date.today().isoformat()
    commit = git(root, "rev-parse", "--short", "HEAD") if commit is None else commit
    branch = git(root, "rev-parse", "--abbrev-ref", "HEAD")
    files = list_files(root, kb, extra_exclude)
    texts = {rel: read(os.path.join(root, rel)) for rel in files if os.path.splitext(rel)[1].lower() in LANGUAGES
             or os.path.basename(rel) in ENTRY_FILES or re.fullmatch(r"requirements[\w.-]*\.txt", os.path.basename(rel))}
    ov = overview(root, files, texts)
    eps = endpoints(files, texts)
    tables, models, refs = data_model(files, texts)
    deps = dependencies(files, texts)
    routes = ui_routes(files)
    head = header(commit, today)

    md = ["# Repository overview", "",
          "**Generator:** kb_scan.py 1  ", "**Source:** repository scan at commit %s%s  " % (
              commit or "unknown", " on branch %s" % branch if branch else ""),
          "**Generated:** %s" % today, "",
          "Facts read from the code by a static scan; each carries its file. The business meaning is not here: "
          "run `/kb-build` for that.", ""]
    if ov["readme_summary"]:
        md += ["## What the README says", "", ov["readme_summary"] + " [E: %s]" % ov["readme"], ""]
    md += ["## Languages", "", "| Language | Files | Lines |", "|---|---|---|"]
    md += ["| %s | %d | %d |" % (k, v["files"], v["lines"]) for k, v in ov["languages"].items()]
    md += ["", "## Top-level layout", "", "| Folder | Files |", "|---|---|"]
    md += ["| `%s` | %d |" % (k, n) for k, n in ov["top_level"].items()]
    md += ["", "## Entry points and build files", ""] + (["- `%s`" % e for e in ov["entry_points"]] or ["- none found"])
    md += ["", "## Tests", "", "%d test files." % len(ov["tests"])] + ["- `%s`" % t for t in ov["tests"][:15]]
    md += ["", "## CI", ""] + (["- `%s`" % c for c in ov["ci"]] or ["- none found"])
    md += ["", "## Counts", "", "- HTTP endpoints: %d" % len(eps), "- Tables defined: %d" % len(tables),
           "- Models: %d" % len(models), "- Tables named in SQL: %d" % len(refs), "- UI routes: %d" % len(routes), ""]

    readme = ["# Repository scan", "",
              "**Generator:** kb_scan.py 1  ", "**Source:** repository scan at commit %s  " % (commit or "unknown"),
              "**Generated:** %s" % today, "",
              "Written by `sdlc/framework/tools/kb_scan.py`. These files are facts read from the source by static scans:",
              "routes, tables, dependencies, layout. Every entry names its file and line.", "",
              "- Rebuild: `python3 sdlc/framework/tools/kb_scan.py` (only files with `generator: kb_scan.py` are replaced).",
              "- Check for drift: `python3 sdlc/framework/tools/kb_scan.py --check`.",
              "- This is a starting map, not the full knowledge base. `/kb-build` adds the narrative documents.", ""]

    out = {
        "README.md": "\n".join(readme),
        "00_REPO_OVERVIEW.md": "\n".join(md) + "\n",
        "10_ENDPOINT_REGISTRY.yaml": yaml_file("HTTP endpoints found in the code", head, {
            "count": len(eps), "note": "path is as written in the decorator or call; a router prefix mounted elsewhere is not added",
            "endpoints": eps}),
        "20_DATA_MODEL.yaml": yaml_file("Tables and models found in the code", head, {
            "tables_defined": tables, "models": models, "tables_named_in_sql": refs}),
        "30_DEPENDENCIES.yaml": yaml_file("Dependencies declared in the repo", head, {"manifests": deps}),
        "40_UI_ROUTES.yaml": yaml_file("UI routes (Next.js app/ and pages/)", head, {"routes": routes}),
    }
    counts = {"files_scanned": len(files), "endpoints": len(eps), "tables": len(tables), "models": len(models),
              "tables_named_in_sql": len(refs), "dependency_manifests": len(deps), "ui_routes": len(routes),
              "languages": {k: v["files"] for k, v in ov["languages"].items()}}
    return out, counts


def body_of(text):
    """The file without its generated date and commit, so a rerun on the same code compares equal."""
    return "\n".join(l for l in text.splitlines()
                     if not re.match(r"^\s*(generated|source):|^\*\*(Generated|Source):\*\*", l))


def run(root=ROOT, kb="docs/knowledge-base", stage=None, force=False, manifest=True, check=False, extra_exclude=()):
    """Write the files (or, with check, compare). Returns a summary dict; never raises on a bad repo."""
    files, counts = build(root, kb, extra_exclude)
    out_dir = os.path.abspath(os.path.join(root, stage)) if stage else os.path.join(root, kb, OUT_DIR)
    result = {"folder": os.path.relpath(out_dir, root).replace(os.sep, "/"), "counts": counts, "written": [],
              "unchanged": [], "skipped": [], "stale": []}
    if not counts["files_scanned"]:
        result["error"] = "no source files found to scan in %s" % root
        return result
    for name, text in files.items():
        path = os.path.join(out_dir, name)
        existing = read(path) if os.path.exists(path) else None
        if existing is not None and body_of(existing) == body_of(text):
            result["unchanged"].append(name)
            continue
        if check:
            result["stale"].append(name)
            continue
        if not force and not mine(path):
            result["skipped"].append({"file": name, "why": "it exists and was not written by kb_scan.py"})
            continue
        os.makedirs(out_dir, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        result["written"].append(name)
    if manifest and result["written"] and not check and not stage:
        tool = os.path.join(root, "sdlc", "framework", "tools", "kb_manifest.py")
        if os.path.isfile(tool):
            done = subprocess.run([sys.executable, tool, "generate"], cwd=root, capture_output=True, text=True)
            result["manifest"] = "updated" if done.returncode == 0 else "not updated: %s" % (
                (done.stderr.strip().splitlines() or ["?"])[-1])
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", default=ROOT, help="the repository to scan (default: the one this framework is in)")
    ap.add_argument("--kb", default="docs/knowledge-base")
    ap.add_argument("--stage", help="write here instead of <kb>/%s (relative to the repo)" % OUT_DIR)
    ap.add_argument("--exclude", action="append", default=[], help="extra path pattern to skip, e.g. 'legacy/*'")
    ap.add_argument("--force", action="store_true", help="replace files even when kb_scan.py did not write them")
    ap.add_argument("--no-manifest", action="store_true", help="do not regenerate KNOWLEDGE-MANIFEST.yaml")
    ap.add_argument("--check", action="store_true", help="write nothing; exit 1 when the files are stale or missing")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    res = run(os.path.abspath(args.root), args.kb, args.stage, args.force, not args.no_manifest, args.check, args.exclude)
    if args.json:
        print(json.dumps(res, indent=2))
    else:
        c = res["counts"]
        print("[SDLC] kb-scan %s: %d files, %d endpoints, %d tables, %d models, %d UI routes -> %s" % (
            "check" if args.check else "done", c["files_scanned"], c["endpoints"], c["tables"], c["models"],
            c["ui_routes"], res["folder"]))
        for n in res["written"]:
            print("  wrote %s" % n)
        for n in res["stale"]:
            print("  stale %s" % n)
        for s in res["skipped"]:
            print("  skipped %s: %s" % (s["file"], s["why"]))
        if res.get("manifest"):
            print("  manifest %s" % res["manifest"])
        if res.get("error"):
            print("  " + res["error"])
    if res.get("error"):
        return 2
    return 1 if args.check and res["stale"] else 0


if __name__ == "__main__":
    sys.exit(main())
