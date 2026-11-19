"""Fact model with mandatory provenance. A fact without evidence is rejected."""
from __future__ import annotations

from typing import Any

from .util import now_iso, sha256_text, stable_json

# INFERRED / GUESSED is deliberately not a valid class.
CLASSES = ("OBSERVED", "DERIVED", "DOCUMENTED", "DISCUSSED", "LLM_DESCRIBED", "UNKNOWN")
TRUST_ORDER = {c: i for i, c in enumerate(CLASSES)}


def ev(source: str, location: str, quote: str | None = None, sha: str | None = None) -> dict:
    e: dict[str, Any] = {"source": source, "location": location}
    if quote:
        e["quote"] = quote[:200]
    if sha:
        e["sha"] = sha
    return e


def make_fact(
    kind: str,
    subject: str,
    attrs: dict,
    cls: str,
    evidence: list[dict],
    scanner: str,
    rule: str | None = None,
    as_of: str | None = None,
) -> dict:
    first = evidence[0] if evidence else {}
    fid = "f_" + sha256_text(
        stable_json([kind, subject, attrs, first.get("source"), first.get("location")])
    )[:16]
    f = {
        "id": fid,
        "kind": kind,
        "subject": subject,
        "attrs": attrs,
        "class": cls,
        "evidence": evidence,
        "scanner": scanner,
        "as_of": as_of or now_iso(),
    }
    if rule:
        f["rule"] = rule
    return f


def validate_fact(f: dict) -> list[str]:
    errors: list[str] = []
    for key in ("id", "kind", "subject", "attrs", "class", "evidence", "as_of", "scanner"):
        if key not in f:
            errors.append(f"missing {key}")
    if errors:
        return errors
    if f["class"] not in CLASSES:
        errors.append(f"invalid class {f['class']!r}")
    ev_list = f["evidence"]
    if not isinstance(ev_list, list) or not ev_list:
        errors.append("evidence is mandatory")
    else:
        for e in ev_list:
            if not isinstance(e, dict) or not e.get("source") or not e.get("location"):
                errors.append("evidence needs source and location")
                break
    if f["class"] == "DERIVED" and not f.get("rule"):
        errors.append("DERIVED facts must record the derivation rule")
    if f["class"] == "LLM_DESCRIBED":
        if not any(isinstance(e, dict) and e.get("quote") for e in ev_list or []):
            errors.append("LLM_DESCRIBED facts must quote evidence")
    if not isinstance(f["attrs"], dict):
        errors.append("attrs must be an object")
    return errors


def fact_text(f: dict) -> str:
    """Flat searchable text for a fact."""
    parts = [f.get("kind", ""), f.get("subject", "")]
    for k, v in (f.get("attrs") or {}).items():
        if isinstance(v, (str, int, float)):
            parts.append(f"{k} {v}")
        elif isinstance(v, list):
            parts.extend(str(x) for x in v[:20] if isinstance(x, (str, int, float)))
    return " ".join(str(p) for p in parts)


def cite(f: dict) -> str:
    e = f["evidence"][0]
    return f"{e['source']}:{e['location']}"
