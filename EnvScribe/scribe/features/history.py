"""Per-run snapshots kept in the output folder (NOT in the journal, so they are never zipped or swept).

A snapshot maps `kind|subject|source` -> a short hash of the fact's attributes, which is enough to report added / removed / changed
facts between runs without storing any content. Contract snapshots keep API operation signatures (names, parameters, status codes).
"""
from __future__ import annotations

import json
from pathlib import Path

from ..util import atomic_write, sha256_text, stable_json

SKIP_KINDS = {"symbol", "import", "todo", "link", "unparsed", "source_file"}   # voluminous; counted, not tracked individually
KEEP = 25


def fact_key(f: dict) -> str:
    e = (f.get("evidence") or [{}])[0]
    return f"{f['kind']}|{f['subject']}|{e.get('source', '')}"


def attr_hash(f: dict) -> str:
    return sha256_text(stable_json(f.get("attrs", {})))[:12]


def hist_dir(out: Path) -> Path:
    return Path(out) / "history"


def load_previous(out: Path, run_id: str) -> dict | None:
    d = hist_dir(out)
    if not d.is_dir():
        return None
    for p in sorted(d.glob("run-*.json"), reverse=True):
        if p.stem != run_id:
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except ValueError:
                continue
    return None


def save(out: Path, run_id: str, payload: dict) -> None:
    d = hist_dir(out)
    atomic_write(d / f"{run_id}.json", json.dumps({"run_id": run_id, **payload}, separators=(",", ":")))
    files = sorted(d.glob("run-*.json"))
    for p in files[:-KEEP]:
        p.unlink(missing_ok=True)


def snapshot_facts(facts: list[dict]) -> dict:
    keys: dict[str, str] = {}
    counts: dict[str, int] = {}
    for f in facts:
        counts[f["kind"]] = counts.get(f["kind"], 0) + 1
        if f["kind"] in SKIP_KINDS:
            continue
        keys[fact_key(f)] = attr_hash(f)
    return {"keys": keys, "counts": counts}
