"""Secret-leak scan of source files. Reports locations and types only, never the value."""
from __future__ import annotations

from ..facts import ev, make_fact
from ..redact import Redactor


def scan_leaks(repo: str, rel: str, text: str, redactor: Redactor) -> list[dict]:
    src = f"{repo}/{rel}"
    out = []
    for f in redactor.detect(text, include_entropy=True):
        if f.category != "secret":
            continue
        line = text.count("\n", 0, f.start) + 1
        out.append(make_fact(
            "secret_leak", f"{src}:L{line}:{f.type}", {"type": f.type, "repo": repo, "path": rel, "line": line, "fingerprint": f.fingerprint},
            "OBSERVED", [ev(src, f"L{line}", f"[{f.type} detected; value not recorded]")], "leak_scan"))
    return out[:200]
