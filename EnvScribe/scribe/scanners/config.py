"""Config/param scanner. Values are only recorded when the key is not secret-like; secret-like keys record presence only."""
from __future__ import annotations

import configparser
import io
import json
import re

import yaml

from ..facts import ev, make_fact

_SECRET_KEY = re.compile(r"(?i)(password|passwd|pwd|secret|token|api[_-]?key|apikey|private[_-]?key|credential|auth[_-]?key|access[_-]?key|connection[_-]?string)")
_ENV_NAMES = ("dev", "sit", "uat", "qa", "st", "stg", "stage", "staging", "prod", "prd", "production", "test", "local", "development", "preprod", "perf", "dr")
_DB_KEY = re.compile(r"(?i)(url|uri|host|jdbc|datasource|dsn|database|db[_.-]?name|schema|port|driver|connection)")

CONFIG_NAMES = re.compile(r"(?i)(^|/)(application[\w.-]*|bootstrap[\w.-]*|config[\w.-]*|settings[\w.-]*|values[\w.-]*|appsettings[\w.-]*|"
                          r"[\w.-]*\.(properties|ini|cfg|conf|toml|env|tfvars)|\.env[\w.-]*|[\w.-]*params?[\w.-]*|[\w.-]*parameters?[\w.-]*)(\.(ya?ml|json|properties|xml))?$")


def is_config_file(rel: str) -> bool:
    low = rel.lower()
    if low.endswith(("package.json", "package-lock.json", "composer.json", "tsconfig.json", "pom.xml", ".csproj")):
        return False
    if "/.github/" in "/" + low or low.endswith(("docker-compose.yml", "docker-compose.yaml")):
        return False
    return bool(CONFIG_NAMES.search(low)) and low.endswith((".yml", ".yaml", ".properties", ".json", ".ini", ".cfg", ".conf", ".toml", ".env", ".tfvars", ".xml")) \
        or low.rsplit("/", 1)[-1].startswith(".env")


def detect_environment(rel: str) -> str | None:
    low = rel.lower()
    for tok in re.split(r"[/\\._\-]", low):
        if tok in _ENV_NAMES:
            return tok.upper()
    return None


def _flatten(obj, prefix=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _flatten(v, f"{prefix}.{k}" if prefix else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _flatten(v, f"{prefix}[{i}]")
    else:
        yield prefix, obj


def _pairs(rel: str, text: str) -> list[tuple[str, str, int]]:
    low = rel.lower()
    out: list[tuple[str, str, int]] = []
    try:
        if low.endswith((".yml", ".yaml")):
            for doc in yaml.safe_load_all(text):
                if doc is not None:
                    out.extend((k, "" if v is None else str(v), 0) for k, v in _flatten(doc))
        elif low.endswith(".json"):
            out.extend((k, "" if v is None else str(v), 0) for k, v in _flatten(json.loads(text)))
        elif low.endswith((".ini", ".cfg", ".conf", ".toml")) and not low.endswith("pyproject.toml"):
            cp = configparser.ConfigParser(interpolation=None, strict=False)
            cp.read_file(io.StringIO(text if "[" in text else "[root]\n" + text))
            for sec in cp.sections():
                for k, v in cp.items(sec):
                    out.append((f"{sec}.{k}" if sec != "root" else k, v, 0))
        else:  # properties / .env / tfvars
            for i, line in enumerate(text.splitlines(), 1):
                s = line.strip()
                if not s or s.startswith(("#", "!", "//", ";")):
                    continue
                m = re.match(r"^(?:export\s+)?([\w.\-\[\]/]+)\s*[=:]\s*(.*)$", s)
                if m:
                    out.append((m.group(1), m.group(2).strip().strip("'\""), i))
    except Exception:
        return []
    return out


def scan_config(repo: str, rel: str, text: str) -> list[dict]:
    src = f"{repo}/{rel}"
    env = detect_environment(rel)
    facts = []
    pairs = _pairs(rel, text)
    if not pairs:
        return [make_fact("unparsed", src, {"reason": "config empty or did not parse", "repo": repo, "path": rel}, "UNKNOWN", [ev(src, "L1")], "config")]
    for key, val, lineno in pairs[:2000]:
        loc = f"L{lineno}" if lineno else f"key {key}"
        secret = bool(_SECRET_KEY.search(key.split(".")[-1])) or bool(_SECRET_KEY.search(key))
        is_ref = bool(re.fullmatch(r"\$\{[^}]+\}|\{\{[^}]+\}\}|<[^>]+>|%\w+%|\$\w+", val)) if val else False
        attrs = {"key": key, "environment": env, "repo": repo, "path": rel, "secret_like": secret, "is_placeholder": is_ref}
        if secret:
            attrs["value"] = "[NOT RECORDED: secret-like key]"
            attrs["has_value"] = bool(val) and not is_ref
        else:
            attrs["value"] = val[:300]
        quote = f"{key.split('.')[-1]}: <value not shown>" if secret else f"{key}={val[:80]}"
        facts.append(make_fact("config_entry", f"{repo}:{rel}:{key}", attrs, "OBSERVED", [ev(src, loc, quote)], "config"))
        if not secret and _DB_KEY.search(key) and re.search(r"(?i)jdbc:|mongodb|postgres|mysql|oracle|sqlserver|snowflake|redshift|redis|db2", val):
            facts.append(make_fact("db_connection", f"{repo}:{rel}:{key}", {
                "key": key, "environment": env, "engine": _engine(val), "target": _strip_cred(val)[:300], "repo": repo, "path": rel},
                "OBSERVED", [ev(src, loc, _strip_cred(f"{key}={val}")[:120])], "config"))
    return facts


def _engine(v: str) -> str:
    for name in ("snowflake", "postgres", "mysql", "mariadb", "oracle", "sqlserver", "db2", "mongodb", "redshift", "redis", "h2"):
        if name in v.lower():
            return name
    return "unknown"


def _strip_cred(v: str) -> str:
    v = re.sub(r"(?i)(password|pwd)=[^;&\s]+", r"\1=[REDACTED]", v)
    return re.sub(r"(//[^/:@\s]+):[^@/\s]+@", r"\1:[REDACTED]@", v)
