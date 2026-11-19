"""Work packages and the worker that turns one package into one chunk.

The worker is the same code whether it runs in a local thread/process pool or inside a child session started by Devin.
It reads source files, runs the deterministic scanners, applies the INPUT redaction gate, validates facts, and writes:
  chunks/<package_id>/chunk.jsonl  chunk.meta.json  chunk.sha256  skips.jsonl  sensitive-register.jsonl
"""
from __future__ import annotations

import fnmatch
import json
import os
from pathlib import Path

from . import SCANNER_VERSION
from .facts import validate_fact
from .redact import Redactor, redact_fact
from .scanners import build, cicd_iac, code, config as cfgscan, contracts, leaks
from .util import atomic_write, now_iso, read_text, sha256_file, sha256_text, write_jsonl

_PRIORITY = [("entry", 0), ("config", 1), ("contract", 2), ("cicd", 3), ("build", 4), ("code", 5)]


def iter_repo_files(repo_root: str, ignore_dirs: list[str], exclude_sources: list[str]):
    """Yield (relative_path, absolute_path, skip_reason). Skips are returned, never silent."""
    root = Path(repo_root)
    ignore = set(ignore_dirs)
    for dirpath, dirnames, filenames in os.walk(root):
        kept = []
        for d in sorted(dirnames):
            if d in ignore:
                yield (os.path.relpath(os.path.join(dirpath, d), root).replace("\\", "/"), None, f"ignore rule: {d}")
            else:
                kept.append(d)
        dirnames[:] = kept
        for fn in sorted(filenames):
            ap = os.path.join(dirpath, fn)
            rel = os.path.relpath(ap, root).replace("\\", "/")
            if any(x and x in rel for x in exclude_sources):
                yield (rel, None, "excluded source (never opened)")
                continue
            yield (rel, ap, None)


def classify_unit(rel: str) -> str:
    if cfgscan.is_config_file(rel):
        return "config"
    if build.is_build_file(rel):
        return "build"
    if contracts.is_contract_candidate(rel):
        return "contract"
    if cicd_iac.classify(rel):
        return "cicd"
    if code.language_of(rel):
        return "code"
    return "other"


def make_packages(repo_name: str, repo_root: str, settings, run_id: str) -> tuple[list[dict], list[dict]]:
    """Inventory pass: split a repo into idempotent work packages. Returns (packages, skips)."""
    units, skips = [], []
    for rel, ap, why in iter_repo_files(repo_root, settings.ignore_dirs, settings.exclude_sources):
        if why:
            skips.append({"item": f"{repo_name}/{rel}", "reason": why})
            continue
        kind = classify_unit(rel)
        if kind == "other":
            continue
        try:
            size = os.path.getsize(ap)
        except OSError:
            continue
        if size > settings.max_file_bytes:
            skips.append({"item": f"{repo_name}/{rel}", "reason": f"larger than max_file_bytes ({settings.max_file_bytes})"})
            continue
        pr = dict(_PRIORITY)[kind if kind in dict(_PRIORITY) else "code"]
        units.append((pr, rel, kind))
    units.sort()
    packages = []
    n = settings.package_size
    for i in range(0, len(units), n):
        batch = units[i:i + n]
        pid = f"{run_id}-{repo_name}-{i // n:04d}"
        packages.append({"package_id": pid, "run_id": run_id, "stage": "scan", "repo": repo_name, "root": repo_root,
                         "units": [{"rel": r, "kind": k} for _, r, k in batch], "scanner_version": SCANNER_VERSION})
    return packages, skips


def run_package(pkg: dict, settings, out_dir: str | Path, redactor: Redactor, progress=None, audit=None) -> dict:
    """Process one package into a chunk directory. Returns chunk metadata."""
    chunk_dir = Path(out_dir) / "chunks" / pkg["package_id"]
    facts: list[dict] = []
    skips: list[dict] = []
    register: list[dict] = []
    statuses: list[dict] = []
    repo, root = pkg["repo"], pkg["root"]
    for u in pkg["units"]:
        rel = u["rel"]
        unit_id = f"{repo}/{rel}"
        ap = os.path.join(root, rel)
        try:
            h = sha256_file(ap)
        except OSError as exc:
            statuses.append({"unit": unit_id, "status": "failed", "error": type(exc).__name__})
            continue
        if progress:
            if progress.is_poison(unit_id):
                statuses.append({"unit": unit_id, "status": "skipped", "reason": "poison: repeatedly failed"})
                skips.append({"item": unit_id, "reason": "poison unit (repeated failures)"})
                continue
            prev = progress.reusable(unit_id, h)
            if prev and prev.get("facts_file") and Path(prev["facts_file"]).exists():
                from .util import read_jsonl
                facts.extend(read_jsonl(prev["facts_file"]))
                statuses.append({"unit": unit_id, "status": "done", "reused": True})
                continue
        text, truncated = read_text(ap, settings.max_file_bytes)
        if text is None:
            statuses.append({"unit": unit_id, "status": "skipped", "reason": "binary file"})
            skips.append({"item": unit_id, "reason": "binary file"})
            continue
        unit_facts: list[dict] = []
        try:
            kind = u["kind"]
            if kind == "config":
                unit_facts += cfgscan.scan_config(repo, rel, text)
            if kind == "build":
                unit_facts += build.scan_build(repo, rel, text)
            if kind == "contract":
                unit_facts += contracts.scan_contract(repo, rel, text)
            if kind == "cicd" or cicd_iac.classify(rel):
                unit_facts += cicd_iac.scan_cicd_iac(repo, rel, text)
            lang = code.language_of(rel)
            if lang and kind in ("code", "config", "cicd", "build"):
                unit_facts += code.scan_code(repo, rel, text, lang) if kind == "code" else []
            unit_facts += leaks.scan_leaks(repo, rel, text, redactor)
        except Exception as exc:
            statuses.append({"unit": unit_id, "status": "failed", "error": type(exc).__name__})
            if progress:
                progress.record(unit_id, "scan", h, "failed", error=type(exc).__name__)
            continue
        # INPUT redaction gate + validation
        clean = []
        for f in unit_facts:
            f2, reg = redact_fact(redactor, f)
            register.extend(reg)
            errs = validate_fact(f2)
            if errs:
                skips.append({"item": unit_id, "reason": f"fact rejected: {errs[0]}"})
                continue
            clean.append(f2)
        if truncated:
            skips.append({"item": unit_id, "reason": "partially scanned (file truncated at max_file_bytes)"})
        facts.extend(clean)
        if progress:
            uf = Path(out_dir) / "units" / (sha256_text(unit_id)[:16] + ".jsonl")
            write_jsonl(uf, clean)           # facts first ...
            progress.record(unit_id, "scan", h, "done", facts_file=str(uf), facts=len(clean))   # ... then progress line
        statuses.append({"unit": unit_id, "status": "done", "facts": len(clean)})
        if audit:
            audit("unit_done", unit=unit_id, facts=len(clean))

    facts.sort(key=lambda f: (f["kind"], f["id"]))
    write_jsonl(chunk_dir / "chunk.jsonl", facts)
    write_jsonl(chunk_dir / "skips.jsonl", skips)
    write_jsonl(chunk_dir / "sensitive-register.jsonl", register)
    body = (chunk_dir / "chunk.jsonl").read_bytes()
    meta = {"package_id": pkg["package_id"], "run_id": pkg["run_id"], "scanner_version": SCANNER_VERSION, "generated_at": now_iso(),
            "schema_version": 1, "units": statuses, "counts": {"facts": len(facts), "skips": len(skips), "redactions": len(register)},
            "sha256": sha256_text(body.decode("utf-8", "replace"))}
    atomic_write(chunk_dir / "chunk.meta.json", json.dumps(meta, indent=2))
    atomic_write(chunk_dir / "chunk.sha256", meta["sha256"] + "\n")
    return meta
