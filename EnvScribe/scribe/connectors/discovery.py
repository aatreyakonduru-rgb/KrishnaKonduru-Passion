"""Integration discovery: find service accounts in the runtime by NAME and LOCATION only. Values are never read into output.

Sources: environment variable names, secret mount files, tool profile files, repo-referenced hostnames (names matched, not stored).
Unrecognized credentials are reported as 'unclassified' and are never used.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from .catalog import CATALOG, Connector, verify

_CRED_SUFFIX = re.compile(r"(?i)(TOKEN|SECRET|PASSWORD|PASSWD|API_?KEY|APIKEY|ACCESS_?KEY|CLIENT_?ID|PAT|CREDENTIALS?)$")
_IGNORE_VARS = re.compile(r"^(PATH|HOME|PWD|USER|SHELL|LANG|TERM|TEMP|TMP|APPDATA|PROCESSOR_.*|PYTHON.*|VIRTUAL_ENV|OS|COMPUTERNAME|USERNAME|SYSTEMROOT|"
                          r"PSMODULEPATH|PATHEXT|COMSPEC|WINDIR|PROGRAM.*|COMMONPROGRAM.*|LOCALAPPDATA|HOMEDRIVE|HOMEPATH|NUMBER_OF_PROCESSORS|ALLUSERSPROFILE|"
                          r"SESSIONNAME|LOGONSERVER|USERDOMAIN.*|USERPROFILE|DRIVERDATA|PUBLIC|ONEDRIVE.*|NODE_.*|NPM_.*|GIT_.*|PIP_.*)$", re.I)

PROFILE_FILES = {
    "~/.aws/config": "aws", "~/.aws/credentials": "aws", "~/.kube/config": "kubernetes",
    "~/.m2/settings.xml": "maven-repository", "~/.npmrc": "npm-registry", "~/.pypirc": "pypi-registry",
    "~/.netrc": "netrc", "~/.docker/config.json": "container-registry", "~/.config/gcloud/application_default_credentials.json": "gcp",
    "~/.azure/azureProfile.json": "azure", "~/.snowsql/config": "snowflake",
}
SECRET_MOUNTS = ["/var/run/secrets", "/run/secrets", "/mnt/secrets", "/etc/secrets"]


def _match_connector(name: str) -> Connector | None:
    up = name.upper()
    best, best_len = None, 0
    for c in CATALOG.values():
        for p in c.env_prefixes:
            if up.startswith(p) and len(p) > best_len:
                best, best_len = c, len(p)
    return best


def discover(extra_paths: list[str] | None = None, environ: dict | None = None, home: str | None = None) -> dict:
    """Return {found: [...], unclassified: [...]} listing names and locations only."""
    env = environ if environ is not None else os.environ
    found: dict[str, dict] = {}
    unclassified: list[dict] = []

    def note(system: str, source: str, name: str):
        e = found.setdefault(system, {"system": system, "category": CATALOG[system].category if system in CATALOG else "other", "sources": []})
        e["sources"].append({"source": source, "name": name})

    for k in sorted(env):
        if _IGNORE_VARS.match(k):
            continue
        c = _match_connector(k)
        if c:
            note(c.name, "env", k)
        elif _CRED_SUFFIX.search(k) and env.get(k):
            unclassified.append({"name": k, "location": "env", "reason": "credential-like variable with no matching connector"})

    mounts = list(SECRET_MOUNTS) + list(extra_paths or [])
    for m in mounts:
        p = Path(m)
        if p.is_dir():
            for child in sorted(p.iterdir())[:200]:
                if child.is_file():
                    c = _match_connector(child.name.replace("-", "_"))
                    if c:
                        note(c.name, f"mount:{m}", child.name)
                    else:
                        unclassified.append({"name": child.name, "location": f"mount:{m}", "reason": "secret file with no matching connector"})

    h = home or str(Path.home())
    for tmpl, system in PROFILE_FILES.items():
        p = Path(tmpl.replace("~", h))
        if p.exists():
            if system in CATALOG:
                note(system, "profile", tmpl)
            else:
                e = found.setdefault(system, {"system": system, "category": "profile", "sources": []})
                e["sources"].append({"source": "profile", "name": tmpl})
    # de-duplicate unclassified
    seen, uniq = set(), []
    for u in unclassified:
        key = (u["name"], u["location"])
        if key not in seen:
            seen.add(key)
            uniq.append(u)
    return {"found": sorted(found.values(), key=lambda x: x["system"]), "unclassified": uniq}


def verify_all(discovery: dict, approved: list[str], mode: str = "approved-only", audit=None, transport=None) -> list[dict]:
    """Verify discovered systems (read-only probe). Only approved ones are probed in approved-only mode."""
    out = []
    for item in discovery["found"]:
        name = item["system"]
        allowed = mode == "auto" or name in approved
        row = {"system": name, "category": item["category"], "sources": item["sources"], "approved": allowed}
        if name in CATALOG and allowed:
            v = verify(CATALOG[name], audit=audit, transport=transport)
            row.update({k: v[k] for k in ("status", "identity", "write_scopes", "notes")})
            if v["write_scopes"]:
                row["flag"] = "over-privileged: write scopes detected and will not be used"
        else:
            row.update({"status": "discovered, not approved" if name in CATALOG else "no connector", "identity": None, "write_scopes": False,
                        "notes": ""})
        out.append(row)
    return out
