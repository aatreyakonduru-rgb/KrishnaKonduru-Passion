"""EnvScribe feature pack: runner.

Pipeline contract for every feature module (`run(ctx) -> Result`):
  * new facts are passed through the output redaction gate and validated (evidence required, DERIVED needs a rule); invalid facts are dropped and counted
  * generated text files are masked line by line (secrets, personal data, IPs, hostnames) before they reach the journal
  * one feature failing never stops the run; the failure is reported in coverage.md
Order matters: ownership -> lineage -> graph -> the rest (later features read earlier features' facts).
"""
from __future__ import annotations

import json
from pathlib import Path

from ..facts import validate_fact
from ..redact import redact_fact
from ..util import atomic_write
from . import (catalog, cloudinv, contract_diff, drift, gitscan, history, lineage, livedocs, ownership, readiness, runtime, sbom, scorecards)
from . import graph as graph_mod
from .common import Ctx, Result

# (name, module, label shown in the UI / settings)
FEATURES = [
    ("ownership", ownership, "Ownership (teams only)"),
    ("lineage", lineage, "Data lineage (SQL parsing)"),
    ("graph", graph_mod, "Dependency and architecture graph"),
    ("sbom", sbom, "SBOM and license report"),
    ("scorecards", scorecards, "Scorecards and risk flags"),
    ("catalog", catalog, "Service catalog export"),
    ("drift", drift, "Environment drift and run diff"),
    ("contract_diff", contract_diff, "API contract diff"),
    ("readiness", readiness, "Migration and cloud readiness"),
    ("livedocs", livedocs, "Generated living docs"),
    ("gitscan", gitscan, "Git-history secret scan"),
    ("cloudinv", cloudinv, "Live cloud and Kubernetes inventory"),
    ("runtime", runtime, "Runtime correlation"),
]
FEATURE_NAMES = [n for n, _, _ in FEATURES]
TEXT_SUFFIXES = {".md", ".json", ".jsonl", ".txt", ".yaml", ".yml", ".csv"}


def mask_text(red, text: str, rel: str) -> tuple[str, int]:
    """Redact every line; returns (clean text, number of lines changed)."""
    out, n = [], 0
    for line in text.split("\n"):
        clean, reg = red.redact(line, rel)
        if reg:
            n += 1
        out.append(clean)
    return "\n".join(out), n


def run_all(ctx: Ctx) -> dict:
    """Run enabled features. Returns {"files": {rel: text}, "facts": [...], "index": [...], "coverage": {...}, "masked_lines": n, "dropped_facts": n}."""
    files: dict[str, str] = {}
    new_facts: list[dict] = []
    index: list[str] = []
    coverage: dict[str, str] = {}
    masked = dropped = 0
    disabled = set(ctx.settings.disabled_features)
    for name, mod, label in FEATURES:
        if name in disabled:
            coverage[name] = "disabled in settings"
            continue
        ctx.event("feature", name=name, status="running")
        try:
            res: Result = mod.run(ctx)
        except Exception as exc:                      # a feature must never break the run
            coverage[name] = f"FAILED: {type(exc).__name__}"
            ctx.event("feature", name=name, status="failed", error=type(exc).__name__)
            continue
        good = []
        for f in res.facts:
            f2, _ = redact_fact(ctx.redactor, f)
            if validate_fact(f2):
                dropped += 1
                continue
            good.append(f2)
        ctx.add_facts(good)
        new_facts += good
        for rel, text in res.files.items():
            if Path(rel).suffix.lower() in TEXT_SUFFIXES:
                text, n = mask_text(ctx.redactor, text, rel)
                masked += n
            files[rel] = text
        index += res.index
        coverage.update(res.coverage)
        ctx.event("feature", name=name, status="done", facts=len(good), files=len(res.files))
    return {"files": files, "facts": new_facts, "index": index, "coverage": coverage, "masked_lines": masked, "dropped_facts": dropped}


def write_outputs(journal_root: Path, result: dict) -> list[str]:
    written = []
    for rel, text in sorted(result["files"].items()):
        atomic_write(Path(journal_root) / rel, text)
        written.append(rel)
    if result["index"]:
        p = Path(journal_root) / "index.md"
        base = p.read_text(encoding="utf-8") if p.exists() else ""
        atomic_write(p, base.rstrip("\n") + "\n\n## Analysis outputs\n\n" + "\n".join(result["index"]) + "\n")
    return written


def save_history(out: Path, run_id: str, ctx: Ctx) -> None:
    """Persist this run's snapshot (outside the journal) so the next run can diff against it."""
    snap = ctx.cache.get("snapshot_facts") or history.snapshot_facts(ctx.facts)
    history.save(out, run_id, {"facts": snap, "contracts": ctx.cache.get("snapshot_contracts") or contract_diff.extract(ctx)})
