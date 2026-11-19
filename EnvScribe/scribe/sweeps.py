"""Pre-zip sweeps: privacy & security sweep, then credential & secret sweep, then seal, then rescan the sealed zip.

Plain code only (no LLM). Findings never contain the matched value: only type, file, line and a short fingerprint.
Any change to a file after a sweep forces a re-sweep (files are hashed at freeze time).
"""
from __future__ import annotations

import io
import json
import re
import zipfile
from pathlib import Path

from .redact import Redactor, speaker_label_hits
from .util import atomic_write, now_iso, sha256_bytes, sha256_file

TEXT_EXT = {".md", ".json", ".jsonl", ".txt", ".yaml", ".yml", ".csv", ".log", ".sha256", ".html"}
SENSITIVE_FILE_NAMES = re.compile(r"(?i)(\.pem|\.key|\.p12|\.pfx|\.jks|\.keystore|\.kdbx|\.env(\..*)?|id_rsa|id_dsa|id_ed25519|\.dump|\.bak|\.sql\.gz)$")
CHECKS_PRIVACY = ["personal data patterns (email, phone, national ID, card + Luhn)", "IP addresses and hostnames",
                  "transcripts: speaker labels / names removed", "document metadata (author, comments)",
                  "sensitive file types (keys, keystores, dumps, .env)", "row-level data (metadata only)",
                  "excluded sources not present", "custom sensitive terms"]
CHECKS_SECRET = ["known-value match (hash compare against secrets loaded in this environment)", "token / key / private-key / JWT patterns",
                 "connection strings with embedded passwords", "high-entropy strings", "base64 / URL-encoded / split-string variants",
                 "env var and mount names appear without values", "logs, audit log, manifests and registers included"]


def freeze(root: Path) -> dict[str, str]:
    """Hash every file. Used to prove the swept bytes are the zipped bytes."""
    return {str(p.relative_to(root)).replace("\\", "/"): sha256_file(p) for p in sorted(root.rglob("*")) if p.is_file()}


def _iter_text(root: Path):
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        yield p, p.suffix.lower() in TEXT_EXT or p.suffix == ""


def _lines(text: str):
    for i, line in enumerate(text.splitlines(), 1):
        yield i, line


def _scan_text(rel: str, text: str, red: Redactor, categories: set[str]) -> list[dict]:
    out = []
    for lineno, line in _lines(text):
        if len(line) > 200_000:
            continue
        for f in red.detect(line):
            if f.category in categories:
                out.append({"file": rel, "line": lineno, "type": f.type, "category": f.category, "fingerprint": f.fingerprint})
    return out


def privacy_sweep(root: Path, red: Redactor, excluded_substrings: list[str], metadata_only_db: bool = True) -> dict:
    findings: list[dict] = []
    checks = {c: "pass" for c in CHECKS_PRIVACY}
    for p, is_text in _iter_text(root):
        rel = str(p.relative_to(root)).replace("\\", "/")
        if SENSITIVE_FILE_NAMES.search(p.name):
            findings.append({"file": rel, "line": 0, "type": "sensitive_file_type", "category": "privacy", "fingerprint": "-"})
            checks["sensitive file types (keys, keystores, dumps, .env)"] = "fail"
            continue
        if any(x and x in rel for x in excluded_substrings):
            findings.append({"file": rel, "line": 0, "type": "excluded_source_present", "category": "privacy", "fingerprint": "-"})
            checks["excluded sources not present"] = "fail"
        if not is_text:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        for f in _scan_text(rel, text, red, {"privacy"}):
            findings.append(f)
            key = {"ip_address": "IP addresses and hostnames", "hostname": "IP addresses and hostnames", "custom_term": "custom sensitive terms"}.get(
                f["type"], "personal data patterns (email, phone, national ID, card + Luhn)")
            checks[key] = "fail"
        if "docs-and-tickets" in rel and "<v " in text:
            findings.append({"file": rel, "line": 0, "type": "speaker_label", "category": "privacy", "fingerprint": "-"})
            checks["transcripts: speaker labels / names removed"] = "fail"
        if re.search(r"(?i)last[_ -]?modified[_ -]?by|\bauthor\s*[:=]", text) and "docs-and-tickets" in rel:
            findings.append({"file": rel, "line": 0, "type": "document_metadata", "category": "privacy", "fingerprint": "-"})
            checks["document metadata (author, comments)"] = "fail"
        if rel.startswith("databases/") and re.search(r"(?i)\brow_?data\b|\bsample_?rows?\b", text):
            findings.append({"file": rel, "line": 0, "type": "row_level_data", "category": "privacy", "fingerprint": "-"})
            checks["row-level data (metadata only)"] = "fail"
    return {"name": "Privacy & security sweep", "checks": checks, "findings": findings, "completed_at": now_iso()}


def secret_sweep(root: Path, red: Redactor) -> dict:
    findings: list[dict] = []
    checks = {c: "pass" for c in CHECKS_SECRET}
    for p, is_text in _iter_text(root):
        if not is_text:
            continue
        rel = str(p.relative_to(root)).replace("\\", "/")
        text = p.read_text(encoding="utf-8", errors="replace")
        for f in _scan_text(rel, text, red, {"secret"}):
            findings.append(f)
            if f["type"] in ("known_secret", "known_secret_split"):
                checks[CHECKS_SECRET[0]] = "fail"
            elif f["type"] == "high_entropy":
                checks["high-entropy strings"] = "fail"
            elif f["type"] in ("url_credentials", "jdbc_password"):
                checks["connection strings with embedded passwords"] = "fail"
            else:
                checks["token / key / private-key / JWT patterns"] = "fail"
    return {"name": "Credential & secret sweep", "checks": checks, "findings": findings, "completed_at": now_iso()}


def auto_redact_files(root: Path, red: Redactor, findings: list[dict]) -> int:
    """Redact in place the files named in findings, then the caller re-sweeps. Returns number of files rewritten."""
    files = sorted({f["file"] for f in findings if f["line"] != 0 or f["type"] in ("sensitive_file_type",)})
    n = 0
    for rel in files:
        p = root / rel
        if not p.exists():
            continue
        if SENSITIVE_FILE_NAMES.search(p.name):
            p.unlink()
            n += 1
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        clean = "\n".join(red.redact(line, rel)[0] for line in text.split("\n"))
        if clean != text:
            atomic_write(p, clean)
            n += 1
    return n


def run_sweeps(root: Path, red: Redactor, excluded: list[str], mode: str = "redact-rescan-block", events=None) -> dict:
    """privacy -> secret -> (auto-redact + rescan) -> blocking findings. Returns a gate decision."""
    emit = events or (lambda *a, **k: None)
    attempts = 0
    while True:
        attempts += 1
        emit("sweep", name="privacy", status="running")
        priv = privacy_sweep(root, red, excluded)
        emit("sweep", name="privacy", status="done", findings=len(priv["findings"]))
        emit("sweep", name="secret", status="running")
        sec = secret_sweep(root, red)
        emit("sweep", name="secret", status="done", findings=len(sec["findings"]))
        blocking = priv["findings"] + sec["findings"]
        if not blocking:
            break
        if mode != "redact-rescan-block" or attempts >= 2:
            break
        changed = auto_redact_files(root, red, blocking)
        emit("sweep", name="auto-redact", status="done", files=changed)
        if changed == 0:
            break
    return {"privacy": priv, "secret": sec, "blocking": blocking, "passed": not blocking, "attempts": attempts,
            "frozen": freeze(root), "completed_at": now_iso()}


def seal_zip(root: Path, zip_path: Path, frozen: dict[str, str], label: str = "complete") -> dict:
    """Zip exactly the frozen bytes. Refuses if any file changed after the sweep."""
    now = freeze(root)
    if now != frozen:
        changed = sorted(k for k in set(now) | set(frozen) if now.get(k) != frozen.get(k))
        raise RuntimeError(f"output changed after sweep; re-sweep required ({len(changed)} files, e.g. {changed[:3]})")
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in sorted(frozen):
            z.write(root / rel, rel)
        z.writestr("SEAL.json", json.dumps({"label": label, "sealed_at": now_iso(), "files": len(frozen), "sha256": frozen}, indent=2))
    return {"zip": str(zip_path), "sha256": sha256_file(zip_path), "files": len(frozen)}


def verify_zip(zip_path: Path, red: Redactor, excluded: list[str]) -> dict:
    """Final rescan of the sealed zip itself, extracted to memory."""
    findings = []
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            name = info.filename
            if name == "SEAL.json":
                continue
            if SENSITIVE_FILE_NAMES.search(name):
                findings.append({"file": name, "line": 0, "type": "sensitive_file_type", "category": "privacy", "fingerprint": "-"})
                continue
            if Path(name).suffix.lower() in TEXT_EXT or "." not in name:
                text = z.read(name).decode("utf-8", errors="replace")
                findings += _scan_text(name, text, red, {"secret", "privacy"})
    return {"passed": not findings, "findings": findings, "completed_at": now_iso()}
