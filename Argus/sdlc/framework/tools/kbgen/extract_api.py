"""Extract the Django-Ninja endpoint surface from api source (AST, no imports)."""
import ast
import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]

API_ROOT = str(REPO / "api")


def rel(p):
    return os.path.relpath(p, str(REPO)).replace(os.sep, "/")


def decorator_info(dec):
    """Return (kind, args) for a decorator node."""
    if isinstance(dec, ast.Call):
        func = dec.func
    else:
        func = dec
    parts = []
    while isinstance(func, ast.Attribute):
        parts.append(func.attr)
        func = func.value
    if isinstance(func, ast.Name):
        parts.append(func.id)
    parts.reverse()
    return ".".join(parts), dec


def literal(node):
    try:
        return ast.literal_eval(node)
    except Exception:
        return ast.unparse(node)


def collect_mounts():
    """Read apps/app/api.py for the prefix -> router variable mapping."""
    path = os.path.join(API_ROOT, "apps/app/api.py")
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    # import alias -> module
    alias_to_module = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("apps."):
            for a in node.names:
                if a.name == "router":
                    alias_to_module[a.asname or a.name] = node.module
    mounts = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    name = None
                    if isinstance(v, ast.Name):
                        name = v.id
                    elif isinstance(v, ast.Attribute):
                        name = v.attr
                    if name and name in alias_to_module:
                        mounts.append((k.value, alias_to_module[name], name))
                    elif name == "root_router":
                        mounts.append((k.value, "apps.app.api", name))
    # add_router calls
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_router":
            if node.args and isinstance(node.args[0], ast.Constant):
                prefix = node.args[0].value
                v = node.args[1] if len(node.args) > 1 else None
                name = v.id if isinstance(v, ast.Name) else (v.attr if isinstance(v, ast.Attribute) else None)
                if name and name in alias_to_module:
                    mounts.append((prefix, alias_to_module[name], name))
    return mounts, src


def parse_router_module(module_dotted):
    path = os.path.join(API_ROOT, module_dotted.replace(".", "/") + ".py")
    if not os.path.exists(path):
        return None
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    tags = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            fn = node.value.func
            fname = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
            if fname == "Router":
                for kw in node.value.keywords:
                    if kw.arg == "tags":
                        tags = literal(kw.value)
    endpoints = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        http = None
        path_str = None
        response_model = None
        auth = []
        extra = {}
        for dec in node.decorator_list:
            name, raw = decorator_info(dec)
            base = name.split(".")[-1]
            if base in {"get", "post", "put", "patch", "delete"} and isinstance(raw, ast.Call):
                http = base.upper()
                if raw.args:
                    path_str = literal(raw.args[0])
                for kw in raw.keywords:
                    if kw.arg == "response":
                        response_model = ast.unparse(kw.value)
                    elif kw.arg in {"auth", "summary", "description", "operation_id"}:
                        extra[kw.arg] = ast.unparse(kw.value)
            elif base:
                auth.append(name if not isinstance(raw, ast.Call) else name)
        if http is None:
            continue
        params = []
        for a in node.args.args:
            if a.arg == "request":
                continue
            params.append({"name": a.arg, "annotation": ast.unparse(a.annotation) if a.annotation else None})
        endpoints.append({
            "path": path_str,
            "method": http,
            "handler": node.name,
            "line": node.lineno,
            "decorators": auth,
            "response_model": response_model,
            "params": params,
            "docstring": (ast.get_docstring(node) or "").strip().splitlines()[:1],
            **extra,
        })
    return {"module": module_dotted, "file": rel(path), "tags": tags, "endpoints": endpoints}


def parse_schemas():
    """Collect ninja Schema / pydantic BaseModel classes per app."""
    out = []
    for dirpath, _dirs, files in os.walk(os.path.join(API_ROOT, "apps")):
        for f in files:
            if f != "schema.py":
                continue
            path = os.path.join(dirpath, f)
            try:
                tree = ast.parse(open(path, encoding="utf-8").read())
            except SyntaxError:
                continue
            classes = []
            for node in tree.body:
                if not isinstance(node, ast.ClassDef):
                    continue
                bases = [ast.unparse(b) for b in node.bases]
                if not any(b.split(".")[-1] in {"Schema", "BaseModel", "ModelSchema"} or b.endswith("Schema") for b in bases):
                    continue
                fields = []
                for st in node.body:
                    if isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name):
                        fields.append({
                            "name": st.target.id,
                            "type": ast.unparse(st.annotation),
                            "required": st.value is None,
                        })
                classes.append({"name": node.name, "bases": bases, "line": node.lineno, "fields": fields})
            if classes:
                out.append({"file": rel(path), "classes": classes})
    return out


def declared_router_modules():
    """Every apps/*/api.py that binds a `router` at module level."""
    found = []
    for dirpath, _dirs, files in os.walk(os.path.join(API_ROOT, "apps")):
        if "api.py" not in files:
            continue
        path = os.path.join(dirpath, "api.py")
        try:
            tree = ast.parse(open(path, encoding="utf-8").read())
        except SyntaxError:
            continue
        for node in tree.body:
            targets = node.targets if isinstance(node, ast.Assign) else ([node.target] if isinstance(node, ast.AnnAssign) else [])
            if any(isinstance(t, ast.Name) and t.id == "router" for t in targets):
                dotted = os.path.relpath(path, API_ROOT)[: -len(".py")].replace(os.sep, ".")
                found.append(dotted)
                break
    return found


def main():
    mounts, root_src = collect_mounts()
    routers = []
    seen = set()
    for prefix, module, var in mounts:
        if (prefix, module) in seen:
            continue
        seen.add((prefix, module))
        info = parse_router_module(module)
        if info is None:
            continue
        info["prefix"] = prefix
        info["router_var"] = var
        routers.append(info)
    data = {
        "routers": sorted(routers, key=lambda r: r["prefix"]),
        "schemas": parse_schemas(),
        "commented_out_mounts": re.findall(r"^#\s*from (apps\.[\w.]+) import router.*$", root_src, re.M),
    }
    mounted = {m for _p, m, _v in mounts}
    commented = set(data["commented_out_mounts"])
    data["declared_but_unmounted"] = sorted(
        m for m in declared_router_modules() if m not in mounted and m not in commented and m != "apps.app.api"
    )
    json.dump(data, sys.stdout, indent=1)


main()
