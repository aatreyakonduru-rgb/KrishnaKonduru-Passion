"""API contract scanner: OpenAPI/Swagger, WSDL, proto, GraphQL, AsyncAPI."""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET

import yaml

from ..facts import ev, make_fact

_VERBS = ("get", "post", "put", "delete", "patch", "head", "options")


def is_contract_candidate(rel: str) -> bool:
    low = rel.lower()
    return low.endswith((".proto", ".graphql", ".gql", ".wsdl", ".xsd")) or (
        low.endswith((".yaml", ".yml", ".json")) and any(k in low for k in ("openapi", "swagger", "api", "asyncapi", "contract", "spec")))


def _line(text: str, needle: str) -> int:
    i = text.find(needle)
    return text.count("\n", 0, i) + 1 if i >= 0 else 1


def scan_contract(repo: str, rel: str, text: str) -> list[dict]:
    src = f"{repo}/{rel}"
    low = rel.lower()
    out: list[dict] = []
    try:
        if low.endswith(".proto"):
            for m in re.finditer(r"(?m)^\s*service\s+(\w+)\s*\{", text):
                out.append(make_fact("api_service", f"grpc:{m.group(1)}", {"protocol": "grpc", "name": m.group(1), "repo": repo, "path": rel},
                                     "OBSERVED", [ev(src, f"L{_line(text, m.group(0))}", m.group(0).strip())], "contract"))
            for m in re.finditer(r"(?m)^\s*rpc\s+(\w+)\s*\(\s*(?:stream\s+)?([\w.]+)\s*\)\s*returns\s*\(\s*(?:stream\s+)?([\w.]+)\s*\)", text):
                out.append(make_fact("api_operation", f"grpc:{m.group(1)}", {"protocol": "grpc", "operation": m.group(1), "request": m.group(2),
                                                                           "response": m.group(3), "repo": repo, "path": rel},
                                     "OBSERVED", [ev(src, f"L{_line(text, m.group(0))}", m.group(0).strip())], "contract"))
            for m in re.finditer(r"(?m)^\s*message\s+(\w+)\s*\{", text):
                out.append(make_fact("api_schema", f"proto:{m.group(1)}", {"name": m.group(1), "repo": repo, "path": rel},
                                     "OBSERVED", [ev(src, f"L{_line(text, m.group(0))}", m.group(0).strip())], "contract"))
        elif low.endswith((".graphql", ".gql")):
            for m in re.finditer(r"(?m)^\s*(?:extend\s+)?type\s+(Query|Mutation|Subscription)\s*\{([^}]*)\}", text):
                for f in re.finditer(r"(?m)^\s*(\w+)\s*(?:\([^)]*\))?\s*:\s*([\[\]\w!]+)", m.group(2)):
                    out.append(make_fact("api_operation", f"graphql:{m.group(1)}.{f.group(1)}", {
                        "protocol": "graphql", "operation_type": m.group(1), "operation": f.group(1), "returns": f.group(2), "repo": repo, "path": rel},
                        "OBSERVED", [ev(src, f"L{_line(text, f.group(0))}", f.group(0).strip())], "contract"))
        elif low.endswith((".wsdl", ".xsd")) and "<" in text[:200]:
            root = ET.fromstring(text)
            for el in root.iter():
                tag = el.tag.split("}")[-1] if isinstance(el.tag, str) else ""
                if tag == "operation" and el.get("name"):
                    out.append(make_fact("api_operation", f"soap:{el.get('name')}", {"protocol": "soap", "operation": el.get("name"), "repo": repo, "path": rel},
                                         "OBSERVED", [ev(src, f"L{_line(text, 'name=' + chr(34) + el.get('name') + chr(34))}", f'operation name="{el.get("name")}"')], "contract"))
        else:
            doc = json.loads(text) if low.endswith(".json") else yaml.safe_load(text)
            if isinstance(doc, dict) and ("openapi" in doc or "swagger" in doc):
                info = doc.get("info") or {}
                ver = doc.get("openapi") or doc.get("swagger")
                out.append(make_fact("api_service", f"openapi:{info.get('title', rel)}", {
                    "protocol": "rest", "title": info.get("title"), "version": info.get("version"), "spec": str(ver),
                    "servers": [s.get("url") for s in (doc.get("servers") or []) if isinstance(s, dict)], "repo": repo, "path": rel},
                    "OBSERVED", [ev(src, "L1", f"openapi: {ver}")], "contract"))
                sec = (doc.get("components") or {}).get("securitySchemes") or doc.get("securityDefinitions") or {}
                for name, s in sec.items():
                    out.append(make_fact("api_auth", f"openapi-auth:{name}", {"scheme": name, "type": (s or {}).get("type"), "repo": repo, "path": rel},
                                         "OBSERVED", [ev(src, f"L{_line(text, name)}", name)], "contract"))
                for path, item in (doc.get("paths") or {}).items():
                    if not isinstance(item, dict):
                        continue
                    for verb in _VERBS:
                        op = item.get(verb)
                        if not isinstance(op, dict):
                            continue
                        params = [{"name": p.get("name"), "in": p.get("in"), "required": p.get("required", False)}
                                  for p in (op.get("parameters") or []) + (item.get("parameters") or []) if isinstance(p, dict)]
                        responses = sorted(str(k) for k in (op.get("responses") or {}).keys())
                        out.append(make_fact("api_operation", f"{verb.upper()} {path}", {
                            "protocol": "rest", "verb": verb.upper(), "path": path, "operation_id": op.get("operationId"),
                            "summary": op.get("summary"), "parameters": params, "responses": responses,
                            "has_request_body": "requestBody" in op or any(p.get("in") == "body" for p in params), "repo": repo, "path_file": rel},
                            "OBSERVED", [ev(src, f"L{_line(text, path)}", f"{path}: {verb}")], "contract"))
                schemas = (doc.get("components") or {}).get("schemas") or doc.get("definitions") or {}
                for name, sch in schemas.items():
                    props = sorted((sch or {}).get("properties", {}).keys()) if isinstance(sch, dict) else []
                    out.append(make_fact("api_schema", f"schema:{name}", {"name": name, "properties": props, "repo": repo, "path": rel},
                                         "OBSERVED", [ev(src, f"L{_line(text, name)}", name)], "contract"))
            elif isinstance(doc, dict) and "asyncapi" in doc:
                for ch, spec in (doc.get("channels") or {}).items():
                    out.append(make_fact("messaging_reference", ch, {"topic": ch, "asyncapi": True, "repo": repo, "path": rel,
                                                                    "operations": [k for k in ("publish", "subscribe") if isinstance(spec, dict) and k in spec]},
                                         "OBSERVED", [ev(src, f"L{_line(text, ch)}", ch)], "contract"))
    except Exception as exc:  # contract files vary wildly; report, don't guess
        out.append(make_fact("unparsed", src, {"reason": f"contract did not parse: {type(exc).__name__}", "repo": repo, "path": rel},
                             "UNKNOWN", [ev(src, "L1")], "contract"))
    return out
