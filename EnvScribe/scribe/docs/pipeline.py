"""Document pipeline: type routing -> extraction -> relevance gate -> input redaction -> facts.

Transcripts: speakers/names stripped at intake; content-only facts with class DISCUSSED.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..facts import ev, make_fact
from ..redact import Redactor, strip_speakers
from ..util import sha256_file
from . import extractors as X
from .gate import AppIndex, gate

_ENTITY = re.compile(r"\b(?:[A-Z][A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)+|[a-z]+(?:-[a-z0-9]+)+)\b")
_HEDGE = re.compile(r"(?i)\b(maybe|might|i think|probably|could|should|perhaps|we may|not sure|possibly)\b")


def is_transcript(path: str, text: str) -> bool:
    p = path.lower()
    if p.endswith(".vtt"):
        return True
    if p.endswith((".txt", ".docx", ".md")) and (X.TRANSCRIPT_HINT.search(Path(p).name) or "-->" in text[:2000]):
        return True
    return False


def process_document(path: str, display: str, index: AppIndex, redactor: Redactor, tagged_apps: list[str] | None = None,
                     force: bool = False, source_label: str = "upload") -> dict:
    """Returns {status, facts, register, skip, intake}. status: read | skipped | quarantined | not_read | unreadable | pending."""
    ext = Path(path).suffix.lower()
    kind = X.classify_type(path)
    sha = sha256_file(path)
    base = {"file": display, "sha256": sha, "type": ext}
    if kind == "not_read":
        return {**base, "status": "not_read", "reason": "images, video and audio are not read", "facts": [], "register": []}
    if kind == "quarantine":
        return {**base, "status": "quarantined", "reason": "legacy/macro-enabled format; not parsed", "facts": [], "register": []}
    if kind == "unknown":
        return {**base, "status": "not_read", "reason": "file type not understood (listed only)", "facts": [], "register": []}
    if ext in (".xlsx", ".docx", ".pptx", ".vsdx") and X.has_macros(path):
        return {**base, "status": "quarantined", "reason": "macros detected; not parsed", "facts": [], "register": []}
    meta: dict = {}
    try:
        if ext == ".pdf":
            segs, meta = X.extract_pdf(path)
        elif ext == ".docx":
            segs = X.extract_docx(path)
        elif ext == ".xlsx":
            segs, meta = X.extract_xlsx(path)
        elif ext == ".pptx":
            segs = X.extract_pptx(path)
        elif ext == ".drawio":
            segs, meta = X.extract_drawio(path)
        elif ext == ".vsdx":
            segs, meta = X.extract_vsdx(path)
        elif ext == ".bpmn":
            segs, meta = X.extract_bpmn(path)
        elif ext == ".svg":
            segs = X.extract_svg(path)
        elif ext in (".puml", ".plantuml", ".mmd"):
            segs, meta = X.extract_text_diagram(path)
        else:
            segs = X.extract_plain(path)
    except X.Unreadable as exc:
        return {**base, "status": "unreadable", "reason": str(exc), "facts": [], "register": []}
    except Exception as exc:
        return {**base, "status": "unreadable", "reason": f"extraction failed: {type(exc).__name__}", "facts": [], "register": []}

    full = "\n".join(t for _, t in segs)
    if not full.strip():
        reason = "no text layer; OCR unavailable or empty" if ext == ".pdf" else "no extractable text"
        return {**base, "status": "unreadable", "reason": reason, "meta": meta, "facts": [], "register": []}

    transcript = is_transcript(path, full)
    if transcript:
        segs = [(loc, strip_speakers(t)) for loc, t in segs]
        full = "\n".join(t for _, t in segs)

    # relevance gate reads redacted content, in memory
    gate_text, _ = redactor.redact(full[:300_000], display)
    g = gate(index, Path(path).name, gate_text, tagged_apps)
    if not g["relevant"] and not force:
        return {**base, "status": "skipped", "reason": g["reason"], "meta": meta, "facts": [], "register": [],
                "needs_decision": True}

    register: list[dict] = []
    facts: list[dict] = []
    cls = "DISCUSSED" if transcript else "DOCUMENTED"
    src = f"{source_label}:{display}"
    facts.append(make_fact("document", src, {
        "file": display, "type": ext.lstrip("."), "sha256": sha, "transcript": transcript, "apps": g["apps"],
        "relevance": g["reason"], "meta": {k: v for k, v in meta.items() if k != "graph"}},
        "OBSERVED", [ev(src, "file", sha=sha)], "docs"))
    for loc, text in segs:
        clean, reg = redactor.redact(text, f"{display} {loc}")
        register.extend(reg)
        if not clean.strip():
            continue
        if transcript:
            sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n", clean) if len(s.strip()) > 25]
            for s in sentences[:400]:
                facts.append(make_fact("discussion", src, {
                    "text": s[:400], "hedged": bool(_HEDGE.search(s)), "apps": g["apps"],
                    "note": "content only; discussion is not a decision record; speakers removed"},
                    "DISCUSSED", [ev(src, loc, s[:160])], "docs"))
        else:
            facts.append(make_fact("doc_section", src, {"text": clean[:3000], "apps": g["apps"], "location": loc},
                                   "DOCUMENTED", [ev(src, loc, clean[:160])], "docs"))
        for ent in sorted(set(_ENTITY.findall(clean)))[:40]:
            if index.match(ent):
                facts.append(make_fact("doc_mention", f"{src}->{ent}", {"term": ent, "apps": sorted(index.match(ent))},
                                       "DOCUMENTED" if not transcript else "DISCUSSED", [ev(src, loc, ent)], "docs"))
    graph = meta.get("graph")
    if graph:
        for eid, s, t, lbl in graph["edges"]:
            if s and t:
                facts.append(make_fact("diagram_edge", f"{src}:{graph['nodes'].get(s, s)}->{graph['nodes'].get(t, t)}", {
                    "from": graph["nodes"].get(s, s), "to": graph["nodes"].get(t, t), "label": lbl, "apps": g["apps"],
                    "note": "documented connection; not verified against code"},
                    "DOCUMENTED", [ev(src, f"edge {eid}", f"{graph['nodes'].get(s, s)} -> {graph['nodes'].get(t, t)}")], "docs"))
    return {**base, "status": "read", "reason": g["reason"], "apps": g["apps"], "meta": {k: v for k, v in meta.items() if k != "graph"},
            "facts": facts, "register": register}
