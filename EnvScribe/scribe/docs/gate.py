"""Application identity index and relevance gate. Matching is exact or alias based, never LLM based."""
from __future__ import annotations

import re
from collections import defaultdict

_MIN_LEN = 4
_STOP = {"main", "core", "common", "test", "tests", "util", "utils", "src", "app", "service", "services", "api", "web",
         "java", "python", "data", "base", "lib", "libs", "docs", "doc", "demo", "example", "sample", "build", "target",
         "default", "config", "model", "models", "client", "server", "module", "modules", "package", "version", "release"}


class AppIndex:
    """Maps terms (repo names, artifactIds, service names, tables, hostnames, Jira keys, aliases) to application names."""

    def __init__(self) -> None:
        self.term_to_apps: dict[str, set[str]] = defaultdict(set)
        self._rx: re.Pattern | None = None

    def add(self, term: str, app: str, kind: str = "name") -> None:
        t = (term or "").strip().lower()
        if len(t) < _MIN_LEN or t in _STOP:
            return
        self.term_to_apps[t].add(app)
        self._rx = None

    def add_aliases(self, aliases: dict[str, list[str]]) -> None:
        for canonical, alts in (aliases or {}).items():
            self.add(canonical, canonical)
            for a in alts or []:
                self.add(a, canonical)

    @classmethod
    def from_facts(cls, facts: list[dict], aliases: dict | None = None) -> "AppIndex":
        idx = cls()
        for f in facts:
            a = f.get("attrs", {})
            repo = a.get("repo")
            k = f["kind"]
            if k == "module":
                app = repo or f["subject"]
                idx.add(repo or "", app)
                idx.add(a.get("artifact") or a.get("name") or "", app)
            elif k in ("api_service",):
                idx.add(a.get("title") or a.get("name") or "", repo or f["subject"])
            elif k == "table_reference":
                idx.add(a.get("table", ""), repo or f["subject"], "table")
            elif k in ("service_definition", "helm_chart", "k8s_resource"):
                idx.add(a.get("service") or a.get("name") or "", repo or f["subject"])
            elif k == "source_file" and a.get("repo"):
                idx.add(a["repo"], a["repo"])
        idx.add_aliases(aliases or {})
        return idx

    def _compile(self) -> re.Pattern | None:
        if self._rx is None and self.term_to_apps:
            terms = sorted(self.term_to_apps, key=len, reverse=True)
            self._rx = re.compile(r"(?<![\w-])(" + "|".join(re.escape(t) for t in terms) + r")(?![\w-])", re.I)
        return self._rx

    def match(self, text: str) -> dict[str, list[str]]:
        """Return {app: [matched terms]}. Single compiled pass over the text."""
        rx = self._compile()
        if not rx:
            return {}
        found: dict[str, set[str]] = defaultdict(set)
        for m in rx.finditer(text):
            term = m.group(1).lower()
            for app in self.term_to_apps.get(term, ()):
                found[app].add(term)
        return {a: sorted(t) for a, t in found.items()}

    def apps(self) -> list[str]:
        return sorted({a for s in self.term_to_apps.values() for a in s})


def gate(index: AppIndex, name: str, text: str, tagged_apps: list[str] | None = None) -> dict:
    """Decide whether a document is related to an application in the code. Reads content (pre-scan, in memory)."""
    if tagged_apps:
        return {"relevant": True, "apps": tagged_apps, "reason": "user-tagged", "terms": []}
    matches = index.match(name + "\n" + text)
    if matches:
        return {"relevant": True, "apps": sorted(matches), "reason": "exact/alias match",
                "terms": sorted({t for ts in matches.values() for t in ts})[:15]}
    return {"relevant": False, "apps": [], "reason": "no exact or alias match to any application found in code", "terms": []}
