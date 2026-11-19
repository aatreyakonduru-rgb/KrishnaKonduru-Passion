"""Small shared helpers: time, hashing, atomic IO, JSONL, safe paths."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import threading
from pathlib import Path
from typing import Any, Iterable

_io_lock = threading.Lock()


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8", "replace"))


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def stable_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def atomic_write(path: str | Path, data: str | bytes) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    mode = "wb" if isinstance(data, bytes) else "w"
    kwargs = {} if isinstance(data, bytes) else {"encoding": "utf-8", "newline": "\n"}
    with open(tmp, mode, **kwargs) as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, p)


def safe_join(base: str | Path, rel: str) -> Path:
    """Join rel under base; raise ValueError on traversal."""
    base_p = Path(base).resolve()
    target = (base_p / rel).resolve()
    if target != base_p and base_p not in target.parents:
        raise ValueError(f"path escapes base directory: {rel}")
    return target


def read_text(path: str | Path, max_bytes: int = 2_000_000) -> tuple[str | None, bool]:
    """Return (text, truncated). text is None for binary files."""
    with open(path, "rb") as fh:
        raw = fh.read(max_bytes + 1)
    truncated = len(raw) > max_bytes
    raw = raw[:max_bytes]
    if b"\x00" in raw[:8192]:
        return None, truncated
    return raw.decode("utf-8", errors="replace"), truncated


def append_jsonl(path: str | Path, obj: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(obj, ensure_ascii=False, default=str) + "\n"
    with _io_lock:
        with open(p, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())


def write_jsonl(path: str | Path, rows: Iterable[Any]) -> None:
    body = "".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in rows)
    atomic_write(path, body)


def read_jsonl(path: str | Path) -> list[Any]:
    p = Path(path)
    if not p.exists():
        return []
    out = []
    with open(p, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # truncated / corrupt line is ignored
    return out
