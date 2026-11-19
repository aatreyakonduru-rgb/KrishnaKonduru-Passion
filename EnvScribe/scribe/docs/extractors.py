"""Document extractors. Each returns a list of (location, text) segments, or raises Unreadable.

Nothing inside a file is executed: no macros, no external links fetched. Images/video/audio are not read.
"""
from __future__ import annotations

import io
import json
import re
import shutil
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

NOT_READ = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp", ".ico", ".heic",
            ".mp4", ".mov", ".avi", ".mkv", ".webm", ".mp3", ".wav", ".m4a", ".flac"}
DOC_EXTS = {".pdf", ".docx", ".xlsx", ".xlsm", ".pptx", ".drawio", ".vsdx", ".puml", ".plantuml", ".mmd", ".bpmn",
            ".svg", ".vtt", ".md", ".txt", ".csv", ".rtf", ".html", ".htm", ".eml"}
MACRO_EXTS = {".xlsm", ".docm", ".pptm", ".xlsb", ".xls", ".doc", ".ppt"}  # legacy/macro formats: quarantined
TRANSCRIPT_HINT = re.compile(r"(?i)(transcript|meeting|recording|teams|standup|retro|review|call)")

MAX_ARCHIVE_RATIO = 200
MAX_UNCOMPRESSED = 200 * 1024 * 1024
MAX_PDF_PAGES = 400
MAX_SHEET_ROWS = 300
MAX_OCR_PAGES = 40


class Unreadable(Exception):
    pass


def tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


def check_zip_safety(path: str) -> None:
    try:
        with zipfile.ZipFile(path) as z:
            total = sum(i.file_size for i in z.infolist())
            comp = max(sum(i.compress_size for i in z.infolist()), 1)
            if total > MAX_UNCOMPRESSED or total / comp > MAX_ARCHIVE_RATIO:
                raise Unreadable("archive exceeds size/ratio limits (possible decompression bomb)")
    except zipfile.BadZipFile as exc:
        raise Unreadable("not a valid OOXML/zip container") from exc


def has_macros(path: str) -> bool:
    try:
        with zipfile.ZipFile(path) as z:
            return any(n.lower().endswith("vbaproject.bin") for n in z.namelist())
    except zipfile.BadZipFile:
        return False


def extract_pdf(path: str) -> tuple[list[tuple[str, str]], dict]:
    from pypdf import PdfReader
    try:
        reader = PdfReader(path)
        if reader.is_encrypted:
            try:
                if not reader.decrypt(""):
                    raise Unreadable("PDF is password-protected")
            except Exception as exc:
                raise Unreadable("PDF is password-protected") from exc
        segs, meta = [], {"pages": len(reader.pages), "ocr_pages": [], "no_text_pages": [], "truncated": False}
        pages = reader.pages[:MAX_PDF_PAGES]
        meta["truncated"] = len(reader.pages) > MAX_PDF_PAGES
        empty: list[int] = []
        for i, page in enumerate(pages, 1):
            txt = (page.extract_text() or "").strip()
            if len(txt) >= 20:
                segs.append((f"p.{i}", txt))
            else:
                empty.append(i)
        if empty:
            ocr = _ocr_pages(path, empty[:MAX_OCR_PAGES])
            for pno in empty:
                if pno in ocr and ocr[pno][0].strip():
                    text, conf = ocr[pno]
                    segs.append((f"p.{pno} (OCR, confidence {conf:.0f}%)", text.strip()))
                    meta["ocr_pages"].append({"page": pno, "confidence": round(conf, 1)})
                else:
                    meta["no_text_pages"].append(pno)
        meta["ocr_available"] = tesseract_available()
        return segs, meta
    except Unreadable:
        raise
    except Exception as exc:
        raise Unreadable(f"PDF could not be parsed: {type(exc).__name__}") from exc


def _ocr_pages(path: str, pages: list[int]) -> dict[int, tuple[str, float]]:
    """Local OCR only. Requires tesseract + pymupdf or pdf2image; otherwise pages are reported as 'no text layer'."""
    if not pages or not tesseract_available():
        return {}
    try:
        import pytesseract
        from PIL import Image
    except Exception:
        return {}
    out: dict[int, tuple[str, float]] = {}
    try:
        import fitz  # pymupdf
        doc = fitz.open(path)
        for p in pages:
            pix = doc[p - 1].get_pixmap(dpi=200)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
            words = [w for w, c in zip(data["text"], data["conf"]) if w.strip() and float(c) >= 0]
            confs = [float(c) for w, c in zip(data["text"], data["conf"]) if w.strip() and float(c) >= 0]
            out[p] = (" ".join(words), sum(confs) / len(confs) if confs else 0.0)
    except Exception:
        return out
    return out


def extract_docx(path: str) -> list[tuple[str, str]]:
    check_zip_safety(path)
    import docx
    d = docx.Document(path)
    segs = []
    section, buf = "start", []
    for para in d.paragraphs:
        t = para.text.strip()
        if not t:
            continue
        if para.style is not None and para.style.name.lower().startswith("heading"):
            if buf:
                segs.append((f"section '{section}'", "\n".join(buf)))
            section, buf = t[:80], [t]
        else:
            buf.append(t)
    if buf:
        segs.append((f"section '{section}'", "\n".join(buf)))
    for ti, table in enumerate(d.tables, 1):
        rows = [" | ".join(c.text.strip() for c in r.cells) for r in table.rows]
        segs.append((f"table {ti}", "\n".join(rows)))
    return segs


def extract_xlsx(path: str) -> tuple[list[tuple[str, str]], dict]:
    check_zip_safety(path)
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=False)  # formulas are read as text, never evaluated
    segs, meta = [], {"sheets": [], "truncated": False}
    for ws in wb.worksheets:
        rows = []
        for i, row in enumerate(ws.iter_rows(values_only=True), 1):
            if i > MAX_SHEET_ROWS:
                meta["truncated"] = True
                break
            vals = ["" if v is None else str(v) for v in row]
            if any(vals):
                rows.append(" | ".join(vals))
        meta["sheets"].append({"name": ws.title, "state": getattr(ws, "sheet_state", "visible")})
        if rows:
            segs.append((f"sheet '{ws.title}' rows 1-{len(rows)}", "\n".join(rows)))
    return segs, meta


def extract_pptx(path: str) -> list[tuple[str, str]]:
    check_zip_safety(path)
    from pptx import Presentation
    prs = Presentation(path)
    segs = []
    for i, slide in enumerate(prs.slides, 1):
        parts = []
        for shp in slide.shapes:
            if shp.has_text_frame and shp.text_frame.text.strip():
                parts.append(shp.text_frame.text.strip())
            if getattr(shp, "has_table", False) and shp.has_table:
                for r in shp.table.rows:
                    parts.append(" | ".join(c.text.strip() for c in r.cells))
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame.text.strip():
            parts.append("NOTES: " + slide.notes_slide.notes_text_frame.text.strip())
        if parts:
            segs.append((f"slide {i}", "\n".join(parts)))
    return segs


def _strip(tag: str) -> str:
    return tag.split("}", 1)[-1]


def extract_drawio(path: str) -> tuple[list[tuple[str, str]], dict]:
    raw = Path(path).read_text(encoding="utf-8", errors="replace")
    root = ET.fromstring(raw)
    nodes, edges, pages = {}, [], 0
    for diagram in root.iter("diagram"):
        pages += 1
        if diagram.text and diagram.text.strip() and not list(diagram):
            raise Unreadable("draw.io page is compressed; export as uncompressed XML")
    for cell in root.iter("mxCell"):
        cid = cell.get("id")
        val = re.sub(r"<[^>]+>", " ", cell.get("value") or "").strip()
        if cell.get("edge") == "1":
            edges.append((cid, cell.get("source"), cell.get("target"), val))
        elif cell.get("vertex") == "1" and val:
            nodes[cid] = val
    return _graph_segments(nodes, edges), {"pages": pages, "nodes": len(nodes), "edges": len(edges), "graph": {"nodes": nodes, "edges": edges}}


def extract_vsdx(path: str) -> tuple[list[tuple[str, str]], dict]:
    check_zip_safety(path)
    nodes, edges = {}, []
    with zipfile.ZipFile(path) as z:
        for name in sorted(n for n in z.namelist() if n.startswith("visio/pages/page") and n.endswith(".xml")):
            root = ET.fromstring(z.read(name))
            for sh in root.iter():
                if _strip(sh.tag) == "Shape":
                    text = "".join(t.text or "" for t in sh.iter() if _strip(t.tag) == "Text" for t in [t]) or "".join(sh.itertext())
                    text = " ".join(text.split())
                    if text:
                        nodes[f"{name}:{sh.get('ID')}"] = text[:120]
            for cn in root.iter():
                if _strip(cn.tag) == "Connect":
                    edges.append((f"{name}:c", f"{name}:{cn.get('FromSheet')}", f"{name}:{cn.get('ToSheet')}", ""))
    return _graph_segments(nodes, edges), {"nodes": len(nodes), "edges": len(edges), "graph": {"nodes": nodes, "edges": edges}}


def extract_bpmn(path: str) -> tuple[list[tuple[str, str]], dict]:
    root = ET.fromstring(Path(path).read_text(encoding="utf-8", errors="replace"))
    nodes, edges = {}, []
    for el in root.iter():
        t = _strip(el.tag)
        if t == "sequenceFlow":
            edges.append((el.get("id"), el.get("sourceRef"), el.get("targetRef"), el.get("name") or ""))
        elif t in ("task", "userTask", "serviceTask", "startEvent", "endEvent", "exclusiveGateway", "callActivity", "scriptTask") and el.get("id"):
            nodes[el.get("id")] = el.get("name") or t
    return _graph_segments(nodes, edges), {"nodes": len(nodes), "edges": len(edges), "graph": {"nodes": nodes, "edges": edges}}


def extract_svg(path: str) -> list[tuple[str, str]]:
    root = ET.fromstring(Path(path).read_text(encoding="utf-8", errors="replace"))
    texts = [" ".join("".join(t.itertext()).split()) for t in root.iter() if _strip(t.tag) in ("text", "title", "desc", "tspan")]
    texts = [t for t in dict.fromkeys(texts) if t]
    return [("svg text", "\n".join(texts))] if texts else []


def extract_text_diagram(path: str) -> tuple[list[tuple[str, str]], dict]:
    """PlantUML / Mermaid: parse simple arrows A --> B : label."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    edges, nodes = [], {}
    for i, line in enumerate(text.splitlines(), 1):
        m = re.match(r"^\s*([\w\"'\[\]\-. ]+?)\s*(?:-{1,2}>>?|\.\.>|={1,2}>|--o|-->|->)\s*([\w\"'\[\]\-. ]+?)\s*(?::\s*(.*))?$", line)
        if m:
            a, b = m.group(1).strip(" \"'"), m.group(2).strip(" \"'")
            nodes[a], nodes[b] = a, b
            edges.append((f"L{i}", a, b, (m.group(3) or "").strip()))
    return _graph_segments(nodes, edges), {"nodes": len(nodes), "edges": len(edges), "graph": {"nodes": nodes, "edges": edges}}


def _graph_segments(nodes: dict, edges: list) -> list[tuple[str, str]]:
    segs = []
    if nodes:
        segs.append(("diagram nodes", "\n".join(f"{k}: {v}" for k, v in nodes.items())))
    if edges:
        lines = [f"{nodes.get(s, s)} -> {nodes.get(t, t)}" + (f" [{lbl}]" if lbl else "") for _, s, t, lbl in edges if s and t]
        if lines:
            segs.append(("diagram edges", "\n".join(lines)))
    return segs


def extract_plain(path: str) -> list[tuple[str, str]]:
    raw = Path(path).read_bytes()[:3_000_000]
    if b"\x00" in raw[:4096]:
        raise Unreadable("binary content")
    text = raw.decode("utf-8", errors="replace")
    if path.lower().endswith((".html", ".htm")):
        text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
        text = re.sub(r"<[^>]+>", " ", text)
    return [("text", text)]


def classify_type(path: str) -> str:
    ext = Path(path).suffix.lower()
    if ext in NOT_READ:
        return "not_read"
    if ext in MACRO_EXTS:
        return "quarantine"
    if ext in DOC_EXTS:
        return ext.lstrip(".")
    return "unknown"
