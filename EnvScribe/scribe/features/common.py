"""Shared types and helpers for the feature pack.

Every feature is a module with `run(ctx) -> Result`. A feature never writes files itself: the runner in
`scribe.features` masks every generated line and validates every derived fact before anything reaches the journal,
so a new feature cannot bypass the privacy rules or the grounding policy.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


@dataclass
class Result:
    files: dict[str, str] = field(default_factory=dict)      # path inside the journal -> text
    facts: list[dict] = field(default_factory=list)          # new facts (must be valid; DERIVED needs a rule)
    index: list[str] = field(default_factory=list)           # markdown bullet lines for the journal index
    coverage: dict[str, str] = field(default_factory=dict)   # coverage.md entries


@dataclass
class Ctx:
    settings: object
    run_id: str
    out: Path                                   # run output folder (history lives here, outside the zipped journal)
    journal: Path                               # journal root (what gets swept and zipped)
    facts: list[dict]                           # all facts so far; the runner appends each feature's new facts
    repos: dict[str, str]                       # repo name -> root path on disk
    redactor: object
    collated_at: str
    event: Callable[..., None] = lambda *a, **k: None
    _by_kind: dict | None = None
    cache: dict = field(default_factory=dict)   # cross-feature results (e.g. the graph) so they are computed once

    def k(self, kind: str) -> list[dict]:
        """Facts of one kind (index is rebuilt after each feature adds facts)."""
        if self._by_kind is None:
            d: dict[str, list[dict]] = defaultdict(list)
            for f in self.facts:
                d[f["kind"]].append(f)
            self._by_kind = d
        return self._by_kind.get(kind, [])

    def add_facts(self, facts: list[dict]) -> None:
        self.facts.extend(facts)
        self._by_kind = None

    @property
    def repo_names(self) -> list[str]:
        names = set(self.repos)
        names.update(f["attrs"]["repo"] for f in self.facts if f["attrs"].get("repo"))
        return sorted(names)


def cite(f: dict) -> str:
    e = f["evidence"][0]
    return f"{e['source']} {e['location']}"


def slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", str(s)).strip("-.").lower() or "x"


def md_cell(v) -> str:
    return str(v if v is not None else "").replace("|", "\\|").replace("\r", " ").replace("\n", " ").strip()[:200]


def csv_cell(v) -> str:
    """Neutralise spreadsheet formula injection."""
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def header(title: str, ctx: Ctx, note: str = "") -> str:
    return (f"# {title}\n\n> Run `{ctx.run_id}` · collated at **{ctx.collated_at}** (UTC). Derived from journal facts only; "
            f"statements cite their evidence. {note}\n\n")


# ---- ownership policy: teams only, never individuals ----
_TEAM_WORDS = re.compile(r"(?i)(team|squad|guild|group|owners|platform|engineering|ops|devops|sre|infra|security|architecture|chapter|tribe|devs?|admins?|core)")


def team_of(owner: str) -> str | None:
    """Return a team name for a CODEOWNERS owner token, or None when it may be an individual (never reported)."""
    o = (owner or "").strip()
    if not o or ("@" in o and not o.startswith("@")):      # e-mail address -> a person
        return None
    o = o.lstrip("@")
    if "/" in o:                                           # @org/team form is a team by definition
        t = o.split("/", 1)[1]
        return t or None
    return o if _TEAM_WORDS.search(o) else None


def team_of_repo(facts: list[dict], repo: str) -> str | None:
    teams: dict[str, int] = defaultdict(int)
    for f in facts:
        if f["kind"] == "ownership" and f["attrs"].get("repo") == repo:
            teams[f["attrs"]["team"]] += 1
    return max(teams.items(), key=lambda kv: (kv[1], kv[0]))[0] if teams else None


# ---- version helpers ----
def major_minor(v: str | None) -> tuple[int, int] | None:
    if not v:
        return None
    m = re.search(r"(\d+)(?:\.(\d+))?", str(v))
    return (int(m.group(1)), int(m.group(2) or 0)) if m else None


def templated_path_regex(path: str) -> re.Pattern:
    """/payments/{id} -> regex that matches /payments/123 (exact structure, no guessing beyond placeholders)."""
    p = re.escape(path.rstrip("/") or "/")
    p = re.sub(r"\\\{[^}]+\\\}", r"[^/]+", p)
    p = re.sub(r"/:[A-Za-z_]\w*", "/[^/]+", p.replace("\\/", "/")) if ":" in path else p
    return re.compile("^" + p + "/?$")


def url_path(url: str) -> str | None:
    m = re.match(r"(?i)^[a-z][a-z0-9+.-]*://[^/]*(/[^?#\s]*)?", url or "")
    if not m:
        return None
    return (m.group(1) or "/").rstrip("/") or "/"
