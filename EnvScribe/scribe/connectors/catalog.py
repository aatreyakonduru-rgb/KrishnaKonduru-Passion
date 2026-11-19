"""Connector catalog: fingerprints, verify probes and read-only collectors.

Connectors can be declared in YAML (declarative REST) or as Python plugins. Credentials are read from environment
variables ONLY at call time and are never stored, logged or placed in facts.
"""
from __future__ import annotations

import base64
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import yaml

from ..facts import ev, make_fact
from .readonly import ReadOnlyClient


@dataclass
class Connector:
    name: str
    category: str
    env_prefixes: list[str]
    host_patterns: list[str] = field(default_factory=list)
    url_vars: list[str] = field(default_factory=list)       # env var names that hold the base URL
    auth: str = "bearer"                                     # bearer | basic | header | none
    token_vars: list[str] = field(default_factory=list)
    user_vars: list[str] = field(default_factory=list)
    auth_header: str = "Authorization"
    verify_path: str = "/"
    verify_field: str | None = None                          # json field naming the identity
    allow_post: list[str] = field(default_factory=list)
    write_scope_markers: list[str] = field(default_factory=list)
    collectors: list[dict] = field(default_factory=list)     # {name, path, list_field, kind, fields, params}
    python_collect: Callable | None = None                   # optional plugin hook(client, connector, audit) -> facts
    notes: str = ""

    def base_url(self) -> str | None:
        for v in self.url_vars:
            if os.environ.get(v):
                return os.environ[v].rstrip("/")
        for k, val in os.environ.items():
            if any(k.startswith(p) for p in self.env_prefixes) and k.endswith(("_URL", "_BASE_URL", "_HOST", "_ENDPOINT")) and val.startswith("http"):
                return val.rstrip("/")
        return None

    def _first_env(self, names: list[str]) -> str | None:
        for n in names:
            if os.environ.get(n):
                return os.environ[n]
        return None

    def headers(self) -> dict:
        tok = self._first_env(self.token_vars) or self._scan_suffix(("TOKEN", "API_KEY", "APIKEY", "PAT", "PASSWORD"))
        user = self._first_env(self.user_vars) or self._scan_suffix(("USER", "USERNAME", "EMAIL"))
        h = {"Accept": "application/json"}
        if self.auth == "bearer" and tok:
            h["Authorization"] = f"Bearer {tok}"
        elif self.auth == "basic" and tok:
            h["Authorization"] = "Basic " + base64.b64encode(f"{user or ''}:{tok}".encode()).decode()
        elif self.auth == "header" and tok:
            h[self.auth_header] = tok
        return h

    def _scan_suffix(self, suffixes: tuple[str, ...]) -> str | None:
        for k, val in os.environ.items():
            if val and any(k.startswith(p) for p in self.env_prefixes) and k.endswith(suffixes):
                return val
        return None


CATALOG: dict[str, Connector] = {}


def register(c: Connector) -> None:
    CATALOG[c.name] = c


register(Connector(
    "bitbucket", "source", ["BITBUCKET_", "BB_"], [r"bitbucket\.org", r"bitbucket"], ["BITBUCKET_URL", "BITBUCKET_BASE_URL"],
    auth="basic", token_vars=["BITBUCKET_APP_PASSWORD", "BITBUCKET_TOKEN"], user_vars=["BITBUCKET_USERNAME", "BITBUCKET_USER"],
    verify_path="/2.0/user", verify_field="display_name",
    collectors=[{"name": "repositories", "path": "/2.0/repositories/{workspace}", "list_field": "values", "kind": "repository",
                 "fields": ["slug", "name", "language", "updated_on", "is_private"], "params": {"pagelen": 100}, "needs": ["workspace"]}]))
register(Connector(
    "jira", "work", ["JIRA_", "ATLASSIAN_"], [r"atlassian\.net", r"jira"], ["JIRA_URL", "JIRA_BASE_URL"],
    auth="basic", token_vars=["JIRA_API_TOKEN", "JIRA_TOKEN", "ATLASSIAN_API_TOKEN"], user_vars=["JIRA_EMAIL", "JIRA_USER", "ATLASSIAN_EMAIL"],
    verify_path="/rest/api/3/myself", verify_field="displayName", allow_post=[r"/rest/api/3/search/jql"],
    collectors=[{"name": "projects", "path": "/rest/api/3/project/search", "list_field": "values", "kind": "jira_project",
                 "fields": ["key", "name", "projectTypeKey"], "params": {"maxResults": 100}}]))
register(Connector(
    "confluence", "docs", ["CONFLUENCE_", "ATLASSIAN_"], [r"atlassian\.net/wiki", r"confluence"], ["CONFLUENCE_URL", "CONFLUENCE_BASE_URL"],
    auth="basic", token_vars=["CONFLUENCE_API_TOKEN", "CONFLUENCE_TOKEN", "ATLASSIAN_API_TOKEN"], user_vars=["CONFLUENCE_EMAIL", "CONFLUENCE_USER", "ATLASSIAN_EMAIL"],
    verify_path="/wiki/rest/api/user/current", verify_field="displayName",
    collectors=[{"name": "spaces", "path": "/wiki/api/v2/spaces", "list_field": "results", "kind": "confluence_space",
                 "fields": ["key", "name", "type", "status"], "params": {"limit": 100}}]))
register(Connector(
    "artifactory", "artifacts", ["ARTIFACTORY_", "JFROG_"], [r"jfrog\.io", r"artifactory"], ["ARTIFACTORY_URL", "JFROG_URL"],
    auth="bearer", token_vars=["ARTIFACTORY_TOKEN", "ARTIFACTORY_API_KEY", "JFROG_ACCESS_TOKEN"],
    verify_path="/artifactory/api/system/ping",
    collectors=[{"name": "repositories", "path": "/artifactory/api/repositories", "list_field": None, "kind": "artifact_repo",
                 "fields": ["key", "type", "packageType", "description"]}]))
register(Connector(
    "bamboo", "cicd", ["BAMBOO_"], [r"bamboo"], ["BAMBOO_URL", "BAMBOO_BASE_URL"],
    auth="bearer", token_vars=["BAMBOO_TOKEN", "BAMBOO_API_TOKEN"], verify_path="/rest/api/latest/info",
    collectors=[{"name": "plans", "path": "/rest/api/latest/plan", "list_field": "plans.plan", "kind": "bamboo_plan",
                 "fields": ["key", "shortName", "enabled"], "params": {"max-result": 100}}]))
register(Connector(
    "sonarqube", "quality", ["SONAR_", "SONARQUBE_"], [r"sonar"], ["SONAR_HOST_URL", "SONARQUBE_URL", "SONAR_URL"],
    auth="basic", token_vars=["SONAR_TOKEN", "SONARQUBE_TOKEN"], verify_path="/api/authentication/validate", verify_field="valid",
    collectors=[{"name": "projects", "path": "/api/projects/search", "list_field": "components", "kind": "sonar_project",
                 "fields": ["key", "name", "qualifier", "lastAnalysisDate"], "params": {"ps": 100}}]))
register(Connector(
    "jenkins", "cicd", ["JENKINS_"], [r"jenkins"], ["JENKINS_URL"], auth="basic", token_vars=["JENKINS_API_TOKEN", "JENKINS_TOKEN"],
    user_vars=["JENKINS_USER", "JENKINS_USERNAME"], verify_path="/api/json",
    collectors=[{"name": "jobs", "path": "/api/json?tree=jobs[name,color,url]", "list_field": "jobs", "kind": "jenkins_job", "fields": ["name", "color"]}]))
register(Connector("snowflake", "database", ["SNOWFLAKE_"], [r"snowflakecomputing\.com"], ["SNOWFLAKE_ACCOUNT"], auth="none",
                   notes="metadata only via INFORMATION_SCHEMA; OAuth token or key-pair required in headless VMs (externalbrowser needs a GUI)"))
register(Connector("aws-rds", "database", ["AWS_"], [r"rds\.amazonaws\.com"], [], auth="none",
                   notes="instance metadata via AWS API (describe-db-instances) plus metadata-only catalog queries"))
register(Connector("sharepoint", "docs", ["SHAREPOINT_", "MS_GRAPH_", "AZURE_"], [r"sharepoint\.com", r"graph\.microsoft\.com"], ["SHAREPOINT_URL"],
                   auth="bearer", token_vars=["SHAREPOINT_TOKEN", "MS_GRAPH_TOKEN"], verify_path="/v1.0/me"))
register(Connector("vault", "secrets", ["VAULT_"], [r"vault"], ["VAULT_ADDR"], auth="header", auth_header="X-Vault-Token", token_vars=["VAULT_TOKEN"],
                   verify_path="/v1/sys/health", notes="paths and names only; secret values are never read"))
register(Connector("kubernetes", "cloud", ["KUBE", "KUBERNETES_"], [r"kubernetes"], [], auth="none", notes="manifests via repo; live read-only via kubeconfig"))
register(Connector("gcp", "cloud", ["GOOGLE_", "GCP_", "GCLOUD_"], [r"googleapis\.com"], [], auth="none"))
register(Connector("aws", "cloud", ["AWS_"], [r"amazonaws\.com"], [], auth="none"))
register(Connector("azure", "cloud", ["AZURE_", "ARM_"], [r"azure\.com", r"windows\.net"], [], auth="none"))


def load_yaml_connectors(directory: str | Path) -> list[str]:
    """Declarative connector specs: one YAML file per system. No code needed for REST tools."""
    loaded = []
    d = Path(directory)
    if not d.exists():
        return loaded
    for f in sorted(d.glob("*.y*ml")):
        spec = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        if not spec.get("name") or not spec.get("env_prefixes"):
            continue
        keys = {k: v for k, v in spec.items() if k in Connector.__dataclass_fields__ and k != "python_collect"}
        register(Connector(**keys))
        loaded.append(spec["name"])
    return loaded


# ---------------- collection (read-only) ----------------
def _dig(obj, dotted: str | None):
    if not dotted:
        return obj
    for part in dotted.split("."):
        obj = obj.get(part) if isinstance(obj, dict) else None
    return obj


def verify(c: Connector, audit=None, transport=None) -> dict:
    """Read-only identity probe. Returns status without ever exposing secret values."""
    base = c.base_url()
    result = {"system": c.name, "category": c.category, "status": "not_configured", "identity": None, "write_scopes": False, "notes": c.notes}
    if c.auth == "none" or not base:
        result["status"] = "detected" if c.auth == "none" else "not_configured"
        return result
    client = ReadOnlyClient(base, c.headers(), c.allow_post, audit=audit, transport=transport, system=c.name)
    try:
        r = client.get(c.verify_path)
        if r.status_code in (401, 403):
            result["status"] = f"failed ({r.status_code})"
        elif r.status_code < 300:
            result["status"] = "verified"
            try:
                body = r.json()
                ident = body.get(c.verify_field) if c.verify_field and isinstance(body, dict) else None
                result["identity"] = str(ident)[:60] if ident is not None else None
            except ValueError:
                pass
            scopes = (r.headers.get("x-oauth-scopes") or r.headers.get("X-OAuth-Scopes") or "").lower()
            if any(m in scopes for m in (c.write_scope_markers or ["write", "admin"])):
                result["write_scopes"] = True
        else:
            result["status"] = f"failed ({r.status_code})"
    except Exception as exc:
        result["status"] = f"failed ({type(exc).__name__})"
    finally:
        client.close()
    return result


def collect(c: Connector, params: dict | None = None, audit=None, transport=None) -> list[dict]:
    """Run declarative collectors. Facts carry DOCUMENTED/OBSERVED evidence pointing at the API path."""
    base = c.base_url()
    if not base:
        return []
    client = ReadOnlyClient(base, c.headers(), c.allow_post, audit=audit, transport=transport, system=c.name)
    facts: list[dict] = []
    try:
        for col in c.collectors:
            needs = col.get("needs", [])
            if any(n not in (params or {}) for n in needs):
                continue
            path = col["path"].format(**(params or {}))
            r = client.get(path, params=col.get("params"))
            if r.status_code >= 300:
                facts.append(make_fact("unknown", f"{c.name}:{col['name']}", {"reason": f"HTTP {r.status_code}", "system": c.name},
                                       "UNKNOWN", [ev(f"{c.name}:{path.split('?')[0]}", "response")], "connector"))
                continue
            body = r.json()
            items = _dig(body, col.get("list_field")) if col.get("list_field") else body
            if isinstance(items, dict):
                items = [{"key": k, **(v if isinstance(v, dict) else {"value": v})} for k, v in items.items()]
            for i, item in enumerate(items or []):
                if not isinstance(item, dict):
                    continue
                attrs = {f: item.get(f) for f in col.get("fields", []) if f in item}
                attrs["system"] = c.name
                ident = str(item.get("key") or item.get("slug") or item.get("name") or i)
                facts.append(make_fact(col["kind"], f"{c.name}:{ident}", attrs, "OBSERVED",
                                       [ev(f"{c.name}:{path.split('?')[0]}", f"item {ident}", ident)], "connector"))
    except Exception as exc:
        facts.append(make_fact("unknown", f"{c.name}:collect", {"reason": f"collector failed: {type(exc).__name__}", "system": c.name},
                               "UNKNOWN", [ev(f"{c.name}", "collect")], "connector"))
    finally:
        client.close()
    return facts
