"""Audit log, progress file (resume), run manifest, lock file."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from .util import append_jsonl, atomic_write, now_iso, read_jsonl, sha256_text, stable_json


class Audit:
    """Append-only audit of every probe/API call/skip. Never contains secret values."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def __call__(self, event: str, **fields) -> None:
        append_jsonl(self.path, {"ts": now_iso(), "event": event, **fields})


class Progress:
    """progress.jsonl: append-only record of finished units. Facts are written first, then the progress line.

    A truncated final line is ignored on resume. A unit is reused only if input hash, scanner version and kind match.
    """

    def __init__(self, path: str | Path, scanner_version: str):
        self.path = Path(path)
        self.scanner_version = scanner_version
        self._lock = threading.Lock()
        self._done: dict[str, dict] = {}
        for row in read_jsonl(self.path):
            if row.get("unit") and row.get("status") in ("done", "skipped", "quarantined"):
                self._done[row["unit"]] = row
        self.failures: dict[str, int] = {}
        for row in read_jsonl(self.path):
            if row.get("status") == "failed":
                self.failures[row["unit"]] = self.failures.get(row["unit"], 0) + 1

    def reusable(self, unit: str, input_hash: str) -> dict | None:
        row = self._done.get(unit)
        if row and row.get("input_hash") == input_hash and row.get("scanner_version") == self.scanner_version:
            return row
        return None

    def is_poison(self, unit: str, limit: int = 3) -> bool:
        return self.failures.get(unit, 0) >= limit

    def record(self, unit: str, stage: str, input_hash: str, status: str, facts_file: str | None = None, **extra) -> None:
        row = {"unit": unit, "stage": stage, "input_hash": input_hash, "scanner_version": self.scanner_version,
               "status": status, "facts_file": facts_file, "ts": now_iso(), **extra}
        with self._lock:
            append_jsonl(self.path, row)
            if status in ("done", "skipped", "quarantined"):
                self._done[unit] = row
            elif status == "failed":
                self.failures[unit] = self.failures.get(unit, 0) + 1

    def done_count(self) -> int:
        return len(self._done)


class RunLock:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def acquire(self) -> bool:
        if self.path.exists():
            try:
                pid = int(self.path.read_text().strip().split()[0])
                if _pid_alive(pid) and pid != os.getpid():
                    return False
            except (ValueError, IndexError, OSError):
                pass
        atomic_write(self.path, f"{os.getpid()} {now_iso()}\n")
        return True

    def release(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        # os.kill(pid, 0) would interrupt/terminate the target on Windows; query the process instead.
        import ctypes
        k32 = ctypes.windll.kernel32
        handle = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not k32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == 259  # STILL_ACTIVE
        finally:
            k32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def config_fingerprint(settings_dict: dict) -> str:
    keys = ("sources", "environments", "env_map", "aliases", "ignore_dirs", "exclude_sources", "custom_terms", "max_file_bytes", "package_size")
    return sha256_text(stable_json({k: settings_dict.get(k) for k in keys}))[:16]


def write_manifest(path: str | Path, run_id: str, settings_dict: dict, scanner_version: str, extra: dict | None = None) -> dict:
    m = {"run_id": run_id, "started_at": now_iso(), "scanner_version": scanner_version,
         "config_fingerprint": config_fingerprint(settings_dict), "settings": _safe_settings(settings_dict), **(extra or {})}
    atomic_write(path, json.dumps(m, indent=2))
    return m


def _safe_settings(d: dict) -> dict:
    return {k: v for k, v in d.items() if k not in ("custom_terms",)}


def read_manifest(path: str | Path) -> dict | None:
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
