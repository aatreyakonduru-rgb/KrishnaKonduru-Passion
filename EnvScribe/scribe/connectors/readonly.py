"""Read-only enforcement for every outbound connector call."""
from __future__ import annotations

import re

import httpx

READ_METHODS = {"GET", "HEAD", "OPTIONS"}
_SQL_ALLOWED = re.compile(r"(?is)^\s*(select|show|describe|desc|explain|list|with)\b")
_SQL_FORBIDDEN = re.compile(r"(?i)\b(insert|update|delete|merge|drop|alter|create|truncate|grant|revoke|call|exec|execute|copy|put|get\s+@|remove|use\s+role)\b")


class ReadOnlyViolation(Exception):
    pass


def check_sql(statement: str) -> None:
    """Metadata-only SQL. Rejects anything but SELECT/SHOW/DESCRIBE against catalog views."""
    s = statement.strip().rstrip(";")
    if ";" in s:
        raise ReadOnlyViolation("multiple statements are not allowed")
    if not _SQL_ALLOWED.match(s) or _SQL_FORBIDDEN.search(re.sub(r"'[^']*'", "''", s)):
        raise ReadOnlyViolation("only read-only metadata SQL is allowed")


class ReadOnlyClient:
    """httpx wrapper: GET/HEAD/OPTIONS only, plus POST paths explicitly allow-listed by the connector (search endpoints)."""

    def __init__(self, base_url: str, headers: dict | None = None, allow_post: list[str] | None = None,
                 timeout: float = 20.0, audit=None, transport: httpx.BaseTransport | None = None, system: str = ""):
        self.system = system
        self.allow_post = [re.compile(p) for p in (allow_post or [])]
        self.audit = audit
        self._client = httpx.Client(base_url=base_url, headers=headers or {}, timeout=timeout, transport=transport, follow_redirects=False)

    def request(self, method: str, path: str, **kw) -> httpx.Response:
        m = method.upper()
        if m not in READ_METHODS and not (m == "POST" and any(rx.fullmatch(path.split("?")[0]) for rx in self.allow_post)):
            if self.audit:
                self.audit("blocked", system=self.system, method=m, path=path)
            raise ReadOnlyViolation(f"{m} {path} is not permitted (read-only)")
        if self.audit:
            self.audit("http", system=self.system, method=m, path=path.split("?")[0])
        return self._client.request(m, path, **kw)

    def get(self, path: str, **kw) -> httpx.Response:
        return self.request("GET", path, **kw)

    def close(self) -> None:
        self._client.close()
