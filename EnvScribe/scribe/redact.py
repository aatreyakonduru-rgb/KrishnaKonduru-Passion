"""Redaction and detection. Used by the input gate, output gate and the pre-zip sweeps.

Detectors never return the matched value, only type, position and a short fingerprint hash.
"""
from __future__ import annotations

import base64
import math
import re
import urllib.parse
from dataclasses import dataclass

from .util import sha256_text

# (type, category, compiled regex). category: "secret" or "privacy"
_PATTERNS: list[tuple[str, str, re.Pattern]] = [
    ("private_key", "secret", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY(?: BLOCK)?-----")),
    ("aws_access_key", "secret", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github_token", "secret", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("slack_token", "secret", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("google_api_key", "secret", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("jwt", "secret", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")),
    ("bearer_token", "secret", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{20,}")),
    ("url_credentials", "secret", re.compile(r"(?i)\b[a-z][a-z0-9+.-]{1,20}://[^\s/:@'\"]{1,64}:[^\s/@'\"]{1,128}@[^\s'\"]+")),
    ("jdbc_password", "secret", re.compile(r"(?i)\bjdbc:[^\s'\"]*?[?;&](?:password|pwd)=[^\s;&'\"]+")),
    (
        "assigned_secret",
        "secret",
        re.compile(
            r"(?i)\b[\w.-]*(?:password|passwd|pwd|secret|token|api[_-]?key|apikey|access[_-]?key|client[_-]?secret|private[_-]?key)[\w.-]*"
            r"\s*[:=]\s*['\"]?(?!\$\{|\{\{|<|%|\*{3}|\[REDACTED|None\b|null\b|true\b|false\b|changeme\b)[^\s'\",;]{6,}"
        ),
    ),
    ("email", "privacy", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("us_ssn", "privacy", re.compile(r"\b(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b")),
    ("phone", "privacy", re.compile(r"(?<![\w.])(?:\+\d{1,3}[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?![\w.])")),
    ("iban", "privacy", re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")),
]
# IPs and hostnames are ALWAYS masked (never written to output). Masked as a stable token so that
# "same host in two environments" is still visible without revealing it.
_IPV4 = re.compile(r"(?<![\w.-])(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?![\w-]|\.\d)")
_IPV6 = re.compile(r"(?<![\w:])(?:[0-9A-Fa-f]{1,4}:){4,7}[0-9A-Fa-f]{1,4}(?![\w:])")
_URL_HOST = re.compile(r"(?i)\b[a-z][a-z0-9+.-]{1,20}://(?:[^\s/@'\"]+@)?(\[[0-9a-f:]+\]|[A-Za-z0-9_][A-Za-z0-9_.\-]*)(?=[:/?#'\"\s)\]]|$)")
_AT_HOST = re.compile(r"@([A-Za-z0-9_][A-Za-z0-9_.\-]{1,100})(?=:\d{2,5}\b)")  # jdbc:oracle:thin:@host:1521
_KV_HOST = re.compile(r"(?i)\b(?:host(?:name)?|server|data\s+source|address|endpoint)\s*[=:]\s*['\"]?([A-Za-z0-9_][A-Za-z0-9_.\-]{2,100})")
_FQDN = re.compile(
    r"(?<![\w@./-])((?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    r"(?:com|net|org|edu|gov|mil|co|biz|internal|local|corp|lan|intranet|svc|localdomain))(?![\w-]|\.\w)")
_NOT_HOST_FIRST = {"java", "javax", "jakarta", "android", "kotlin", "scala", "system", "microsoft", "sun", "jdk", "spring", "springframework",
                   "example", "github", "this", "self", "config", "settings", "app", "application", "env", "process", "window", "document"}
_NOT_HOST_VALUES = {"localhost", "true", "false", "null", "none", "password", "secret", "token", "example", "changeme"}
_CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_ENTROPY_TOKEN = re.compile(r"[A-Za-z0-9+/=_\-]{32,}")
_SPEAKER = re.compile(r"(?m)^\s*(?:\[?\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?\]?\s*)?(?:<v\s+[^>]+>|[A-Z][\w.'-]*(?:\s[A-Z][\w.'-]*){0,3}\s*:\s)")
_PATH_LIKE = re.compile(r"^[\w./\\-]+$")


@dataclass
class Finding:
    type: str
    category: str  # secret | privacy
    start: int
    end: int
    fingerprint: str

    def public(self, location: str) -> dict:
        return {"type": self.type, "category": self.category, "location": location, "fingerprint": self.fingerprint}


def luhn_ok(digits: str) -> bool:
    nums = [int(c) for c in digits if c.isdigit()]
    if not 13 <= len(nums) <= 19:
        return False
    total = 0
    for i, n in enumerate(reversed(nums)):
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def shannon(s: str) -> float:
    if not s:
        return 0.0
    freq = {c: s.count(c) for c in set(s)}
    return -sum((n / len(s)) * math.log2(n / len(s)) for n in freq.values())


def _fp(value: str) -> str:
    return sha256_text(value)[:10]


class Redactor:
    def __init__(self, known_secret_hashes: set[str] | None = None, custom_terms: list[str] | None = None,
                 entropy_threshold: float = 4.2):
        self.known_hashes = known_secret_hashes or set()
        self.custom_terms = [t for t in (custom_terms or []) if t.strip()]
        self.entropy_threshold = entropy_threshold
        self._term_res = [re.compile(re.escape(t), re.I) for t in self.custom_terms]

    def _host_findings(self, text: str) -> list[Finding]:
        """IP addresses and hostnames are never allowed in output (policy: no ips or hosts)."""
        out: list[Finding] = []
        for m in _IPV4.finditer(text):
            out.append(Finding("ip_address", "privacy", m.start(), m.end(), _fp(m.group(0))))
        for m in _IPV6.finditer(text):
            out.append(Finding("ip_address", "privacy", m.start(), m.end(), _fp(m.group(0))))
        for rx in (_URL_HOST, _AT_HOST, _KV_HOST):
            for m in rx.finditer(text):
                host = m.group(1)
                if host.lower() in _NOT_HOST_VALUES or host.startswith("${") or host.isdigit():
                    continue
                out.append(Finding("hostname", "privacy", m.start(1), m.end(1), _fp(host.lower())))
        for m in _FQDN.finditer(text):
            host = m.group(1)
            if host.split(".", 1)[0].lower() in _NOT_HOST_FIRST:
                continue
            out.append(Finding("hostname", "privacy", m.start(1), m.end(1), _fp(host.lower())))
        return out

    def set_known_values(self, values: list[str]) -> None:
        """Register actual secret values (as hashes only) for exact-match sweeps."""
        for v in values:
            if v and len(v) >= 6:
                self.known_hashes.add(sha256_text(v))
                self.known_hashes.add(sha256_text(v.strip()))

    # ---------- detection ----------
    def detect(self, text: str, include_entropy: bool = True) -> list[Finding]:
        out: list[Finding] = []
        for typ, cat, rx in _PATTERNS:
            for m in rx.finditer(text):
                out.append(Finding(typ, cat, m.start(), m.end(), _fp(m.group(0))))
        for m in _CARD.finditer(text):
            digits = re.sub(r"\D", "", m.group(0))
            if luhn_ok(digits):
                out.append(Finding("credit_card", "privacy", m.start(), m.end(), _fp(digits)))
        for rx in self._term_res:
            for m in rx.finditer(text):
                out.append(Finding("custom_term", "privacy", m.start(), m.end(), _fp(m.group(0).lower())))
        out.extend(self._host_findings(text))
        if include_entropy:
            for m in _ENTROPY_TOKEN.finditer(text):
                tok = m.group(0)
                if _PATH_LIKE.match(tok) and ("/" in tok or "." in tok):
                    continue
                if re.fullmatch(r"[0-9a-f]{32,64}", tok):  # hashes/SHAs are not secrets
                    continue
                if len(set(tok)) > 12 and shannon(tok) >= self.entropy_threshold:
                    out.append(Finding("high_entropy", "secret", m.start(), m.end(), _fp(tok)))
        out.extend(self._known_and_encoded(text))
        return _dedupe(out)

    def _known_and_encoded(self, text: str) -> list[Finding]:
        found: list[Finding] = []
        if not self.known_hashes:
            return found
        candidates: list[tuple[int, int, str]] = []
        for m in re.finditer(r"[^\s'\"<>(){}\[\],;]{6,}", text):
            candidates.append((m.start(), m.end(), m.group(0)))
        for s, e, tok in candidates:
            variants = {tok, tok.strip("=:"), urllib.parse.unquote(tok)}
            if "=" in tok:
                variants.add(tok.split("=", 1)[1])
            if ":" in tok:
                variants.add(tok.split(":", 1)[1])
            for v in list(variants):
                if len(v) >= 8 and re.fullmatch(r"[A-Za-z0-9+/=_-]+", v):
                    try:
                        pad = v + "=" * (-len(v) % 4)
                        dec = base64.b64decode(pad, validate=False).decode("utf-8", "ignore")
                        if dec:
                            variants.add(dec)
                    except Exception:
                        pass
            for v in variants:
                if v and sha256_text(v) in self.known_hashes:
                    found.append(Finding("known_secret", "secret", s, e, _fp(v)))
                    break
        # secrets split across a simple concatenation: "ab" + "cd"
        joined = re.sub(r"['\"]\s*\+\s*['\"]", "", text)
        if joined != text:
            for m in re.finditer(r"[^\s'\"<>(){}\[\],;]{6,}", joined):
                if sha256_text(m.group(0)) in self.known_hashes:
                    found.append(Finding("known_secret_split", "secret", 0, 0, _fp(m.group(0))))
        return found

    # ---------- redaction ----------
    def redact(self, text: str, location: str = "") -> tuple[str, list[dict]]:
        findings = self.detect(text)
        if not findings:
            return text, []
        spans = sorted(((f.start, f.end, f) for f in findings if f.end > f.start), key=lambda t: (t[0], t[1]))
        merged: list[tuple[int, int, Finding]] = []
        for s, e, f in spans:
            if merged and s < merged[-1][1]:
                ps, pe, pf = merged[-1]
                merged[-1] = (ps, max(pe, e), pf)
            else:
                merged.append((s, e, f))
        out, last = [], 0
        for s, e, f in merged:
            out.append(text[last:s])
            out.append(f"[REDACTED: {f.type}]")
            last = e
        out.append(text[last:])
        reg = [f.public(location) for _, _, f in merged]
        redacted = "".join(out)
        # split-secret findings have no span: neutralise by re-checking
        for f in findings:
            if f.end == f.start:
                reg.append(f.public(location))
        return redacted, reg

    def has_blocking(self, text: str) -> list[Finding]:
        return self.detect(text)


def _dedupe(findings: list[Finding]) -> list[Finding]:
    seen, out = set(), []
    for f in sorted(findings, key=lambda x: (x.start, x.end, x.type)):
        key = (f.start, f.end, f.type)
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    return out


def strip_speakers(text: str) -> str:
    """Remove speaker labels, WebVTT cue timing/ids, and keep spoken content only."""
    lines_out: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.upper().startswith("WEBVTT") or line.startswith("NOTE"):
            continue
        if re.fullmatch(r"\d+", line):  # cue id
            continue
        if "-->" in line:  # cue timing
            continue
        line = re.sub(r"<v\s+[^>]*>", "", line)
        line = re.sub(r"</?v>|</?c[^>]*>", "", line)
        line = re.sub(r"^\[?\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d+)?\]?\s*", "", line)
        line = re.sub(r"^[A-Z][\w.'-]*(?:\s[A-Z][\w.'-]*){0,3}\s*:\s+", "", line)
        line = line.strip()
        if line:
            lines_out.append(line)
    return "\n".join(lines_out)


def speaker_label_hits(text: str) -> int:
    return len(_SPEAKER.findall(text))


def redact_value(red: "Redactor", v, location: str, register: list):
    """Recursively redact every string in a JSON-like value."""
    if isinstance(v, str):
        clean, reg = red.redact(v, location)
        register.extend(reg)
        return clean
    if isinstance(v, list):
        return [redact_value(red, x, location, register) for x in v]
    if isinstance(v, dict):
        return {k: redact_value(red, x, location, register) for k, x in v.items()}
    return v


def redact_fact(red: "Redactor", fact: dict) -> tuple[dict, list[dict]]:
    """Output/input gate for a fact: masks secrets, personal data, IPs and hostnames in subject, attrs and evidence quotes."""
    register: list[dict] = []
    loc = f"{fact.get('kind')}:{(fact.get('evidence') or [{}])[0].get('source', '')}"
    out = dict(fact)
    out["subject"] = redact_value(red, fact.get("subject", ""), loc, register)
    out["attrs"] = redact_value(red, fact.get("attrs", {}), loc, register)
    ev_out = []
    for e in fact.get("evidence", []):
        e2 = dict(e)
        if "quote" in e2:
            e2["quote"] = redact_value(red, e2["quote"], loc, register)
        ev_out.append(e2)
    out["evidence"] = ev_out
    return out, register
