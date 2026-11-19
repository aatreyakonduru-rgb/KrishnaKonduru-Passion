"""Settings (targets.yaml + ui overrides) and environment config.

token_budget: 0 or blank means no limit. max_workers is clamped to 1..MAX_WORKERS_CAP (100).
IPs and hostnames are always masked in output; there is no setting to allow them.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from pathlib import Path

import yaml

from .util import atomic_write

DEFAULT_ENV_MAP = {"ST": "SIT", "QA": "UAT", "STG": "UAT", "STAGE": "UAT", "STAGING": "UAT",
                   "DEVELOPMENT": "DEV", "PRODUCTION": "PROD", "PRD": "PROD"}
DEFAULT_IGNORES = ["node_modules", ".git", "dist", "build", "target", "__pycache__", "vendor", ".venv", "venv",
                   ".idea", ".gradle", "bin", "obj", "coverage"]
MAX_WORKERS_CAP = 100


def _to_bool(value, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _to_list(value) -> list:
    if isinstance(value, str):
        return [x.strip() for x in value.replace("\n", ",").split(",") if x.strip()]
    return list(value or [])


def _to_int(value, default: int, lo: int = 0, hi: int | None = None) -> int:
    """Blank / None / invalid -> default. Clamped to [lo, hi]."""
    try:
        if value is None or (isinstance(value, str) and not value.strip()):
            return default
        n = int(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return default
    n = max(lo, n)
    return min(hi, n) if hi is not None else n


@dataclass
class Settings:
    output_dir: str = "./envscribe-out"
    sources: list[str] = field(default_factory=list)          # local repo / folder paths to crawl
    upload_dir: str = ""                                       # defaults to <output_dir>/uploads
    environments: list[str] = field(default_factory=lambda: ["DEV", "SIT", "UAT"])
    prod_opt_in: bool = False
    env_map: dict = field(default_factory=lambda: dict(DEFAULT_ENV_MAP))
    aliases: dict = field(default_factory=dict)                # canonical -> [aliases]
    integration_mode: str = "approved-only"                    # approved-only | auto
    approved_integrations: list[str] = field(default_factory=list)
    max_workers: int = 4                                       # 1..100
    token_budget: int = 0                                      # 0 or blank = no limit
    on_budget: str = "stop"                                    # stop | warn
    sweep_mode: str = "redact-rescan-block"                    # redact-rescan-block | block
    custom_terms: list[str] = field(default_factory=list)
    ignore_dirs: list[str] = field(default_factory=lambda: list(DEFAULT_IGNORES))
    exclude_sources: list[str] = field(default_factory=list)   # path substrings never opened (HR/legal)
    max_file_bytes: int = 2_000_000
    llm_provider: str = "none"                                 # none | watsonx | ollama (summaries optional)
    package_size: int = 200                                    # units per work package
    # ---- feature pack (all read-only; outputs pass both sweeps) ----
    disabled_features: list[str] = field(default_factory=list)  # names from scribe.features.FEATURES to switch off
    vuln_lookup: bool = False                                  # OSV lookup sends package names+versions to a public service; off by default
    scan_git_history: bool = True                              # reads `git log -p` of repos that have .git; reports type/file/commit only
    git_history_max_commits: int = 2000
    cloud_inventory: list[str] = field(default_factory=list)   # any of: aws, gcp, azure, kubernetes (uses the CLI login already on this VM)
    runtime_dir: str = ""                                      # APM service-map exports (JSON/CSV); defaults to <output_dir>/runtime-maps
    db_catalogs: list[dict] = field(default_factory=list)      # [{engine: snowflake|postgres, label, database, schemas: []}] metadata-only
    semantic_search: bool = True                               # hybrid BM25 + local semantic matching for Ask

    def __post_init__(self) -> None:
        self.max_workers = _to_int(self.max_workers, 4, 1, MAX_WORKERS_CAP)
        self.token_budget = _to_int(self.token_budget, 0, 0)
        self.package_size = _to_int(self.package_size, 200, 1)
        self.git_history_max_commits = _to_int(self.git_history_max_commits, 2000, 1, 100_000)
        for name in ("vuln_lookup", "scan_git_history", "semantic_search"):
            setattr(self, name, _to_bool(getattr(self, name), name == "scan_git_history" or name == "semantic_search"))
        self.disabled_features = _to_list(self.disabled_features)
        self.cloud_inventory = [x.lower() for x in _to_list(self.cloud_inventory)]

    @property
    def runtime_maps(self) -> str:
        return self.runtime_dir or str(Path(self.output_dir) / "runtime-maps")

    @property
    def unlimited_tokens(self) -> bool:
        return self.token_budget <= 0

    def normalize_env(self, name: str) -> str:
        n = name.strip().upper()
        return self.env_map.get(n, n)

    @property
    def uploads(self) -> str:
        return self.upload_dir or str(Path(self.output_dir) / "uploads")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Settings":
        known = {k: v for k, v in (d or {}).items() if k in cls.__dataclass_fields__}
        return cls(**known)

    @classmethod
    def load(cls, path: str | Path) -> "Settings":
        p = Path(path)
        if not p.exists():
            return cls()
        return cls.from_dict(yaml.safe_load(p.read_text(encoding="utf-8")) or {})

    def save(self, path: str | Path) -> None:
        atomic_write(path, yaml.safe_dump(self.to_dict(), sort_keys=False))


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)
