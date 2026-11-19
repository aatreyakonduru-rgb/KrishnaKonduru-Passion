"""Collator: plain code, no LLM. Verifies chunks, re-runs the output redaction gate, dedupes, merges in a fixed order,
flags conflicts, and records unknowns."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from .facts import make_fact, ev, validate_fact
from .redact import Redactor, redact_fact
from .util import now_iso, read_jsonl, sha256_text


def verify_chunk(chunk_dir: Path) -> tuple[bool, str, dict | None]:
    meta_p, data_p = chunk_dir / "chunk.meta.json", chunk_dir / "chunk.jsonl"
    if not meta_p.exists() or not data_p.exists():
        return False, "missing chunk files", None
    meta = json.loads(meta_p.read_text(encoding="utf-8"))
    actual = sha256_text(data_p.read_bytes().decode("utf-8", "replace"))
    if actual != meta.get("sha256"):
        return False, "checksum mismatch", meta
    if meta.get("schema_version") != 1:
        return False, "unsupported schema_version", meta
    return True, "ok", meta


def collate(out_dir: str | Path, redactor: Redactor, extra_fact_files: list[Path] | None = None) -> dict:
    out_dir = Path(out_dir)
    chunks_root = out_dir / "chunks"
    facts_by_id: dict[str, dict] = {}
    skips: list[dict] = []
    register: list[dict] = []
    rejected: list[dict] = []
    chunk_report: list[dict] = []
    gen_times: list[str] = []

    dirs = sorted(p for p in chunks_root.iterdir() if p.is_dir()) if chunks_root.exists() else []
    sources = [(d.name, d) for d in dirs]
    for name, d in sources:
        ok, why, meta = verify_chunk(d)
        chunk_report.append({"package_id": name, "ok": ok, "reason": why})
        if not ok:
            rejected.append({"package_id": name, "reason": why})
            continue
        gen_times.append(meta["generated_at"])
        skips.extend({**s, "package_id": name} for s in read_jsonl(d / "skips.jsonl"))
        register.extend(read_jsonl(d / "sensitive-register.jsonl"))
        for f in read_jsonl(d / "chunk.jsonl"):
            f2, reg = redact_fact(redactor, f)          # the collator does not trust the worker's gate
            register.extend(reg)
            errs = validate_fact(f2)
            if errs:
                rejected.append({"package_id": name, "fact": f.get("id"), "reason": errs[0]})
                continue
            facts_by_id.setdefault(f2["id"], f2)
    for p in extra_fact_files or []:
        for f in read_jsonl(p):
            f2, reg = redact_fact(redactor, f)
            register.extend(reg)
            if not validate_fact(f2):
                facts_by_id.setdefault(f2["id"], f2)

    facts = sorted(facts_by_id.values(), key=lambda f: (f["kind"], f["subject"], f["id"]))
    conflicts = find_conflicts(facts)
    unknowns = build_unknowns(facts, rejected)
    as_ofs = [f["as_of"] for f in facts] or [now_iso()]
    return {"facts": facts, "skips": skips, "register": register, "rejected": rejected, "chunks": chunk_report,
            "conflicts": conflicts, "unknowns": unknowns,
            "as_of_min": min(as_ofs), "as_of_max": max(as_ofs), "collated_at": now_iso()}


def find_conflicts(facts: list[dict]) -> list[dict]:
    """Same key, same environment, different value -> reported, never resolved."""
    cfg: dict[tuple, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for f in facts:
        if f["kind"] != "config_entry" or f["attrs"].get("secret_like"):
            continue
        a = f["attrs"]
        cfg[(a["repo"], a.get("environment") or "-", a["key"])][str(a["value"])].append(f)
    out = []
    for (repo, env, key), vals in cfg.items():
        if len(vals) > 1:
            out.append({"type": "config-conflict", "subject": f"{repo}:{env}:{key}", "note": "same key and environment, different values; not resolved",
                        "values": [{"value": v, "sources": [f"{x['evidence'][0]['source']}:{x['evidence'][0]['location']}" for x in fs[:3]]} for v, fs in vals.items()]})
    # doc vs code: documented diagram edge between apps that code never connects
    return sorted(out, key=lambda c: c["subject"])


def build_unknowns(facts: list[dict], rejected: list[dict]) -> list[dict]:
    out = []
    for f in facts:
        if f["class"] == "UNKNOWN" or f["kind"] == "unparsed":
            out.append({"subject": f["subject"], "reason": f["attrs"].get("reason", "unknown"), "evidence": f["evidence"][0]})
    for r in rejected:
        out.append({"subject": r.get("package_id", "?"), "reason": f"rejected: {r['reason']}", "evidence": None})
    return out
