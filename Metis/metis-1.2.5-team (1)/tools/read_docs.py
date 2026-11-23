#!/usr/bin/env python3
"""Read documents a person uploads, check quotes taken from them, and record them as KB sources.

The documents never go into the repo. Their text is extracted to a scratch folder outside the repo,
every statement taken from them carries a quote, and when the KB is updated the register
<kb>/_EVIDENCE/documents/DOC_SOURCES.yaml keeps each file's fingerprint and every quote that was checked.

    python3 read_docs.py extract <scratch> <file>... --by "<name>"
    python3 read_docs.py check   <scratch> <text file>...
    python3 read_docs.py record  <kb> <scratch> [--kept-at "<where the originals are kept>"]

Tag form:  [E: doc:<doc id>#<place> "quoted text"]
Places:    p<n> (PDF page), slide<n>, <sheet>!<cell>, para<n> (Word paragraph or table row), line<n>,
           t<hh:mm:ss> (a cue in a .vtt or .srt meeting transcript, named by its start time),
           msg<n> (the n-th message in a Slack or Teams JSON chat export).
A transcript or chat export is read as it is: no speech-to-text is done here (the file must already be text), and the
people named in it are only as reliable as the tool that wrote it.
"""
import argparse
import datetime
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from xml.etree import ElementTree as ET

import yaml

DOC_TAG = re.compile(r'\[E:\s*doc:([\w.-]+)#(\S+?)\s+"([^"\]]+)"\s*\]')
ANY_DOC = re.compile(r"\[E:\s*doc:[^\]]*\]")
TEXT_EXT = (".txt", ".md", ".csv", ".tsv", ".json", ".yaml", ".yml", ".xml", ".sql", ".log", ".vtt", ".srt")
IMG_EXT = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp")
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def norm(text):
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def doc_id(name, taken):
    base = re.sub(r"[^\w.-]+", "-", os.path.basename(name)).strip("-.") or "document"
    i, out = 1, base
    while out in taken:
        i += 1
        out = "%s-%d" % (base, i)
    return out


def docx(path):
    with zipfile.ZipFile(path) as z:
        body = ET.fromstring(z.read("word/document.xml")).find(W + "body")
    n = 0
    for el in body:
        if el.tag == W + "p":
            t = "".join(x.text or "" for x in el.iter(W + "t")).strip()
            if t:
                n += 1
                yield "para%d" % n, t
        elif el.tag == W + "tbl":
            for row in el.iter(W + "tr"):
                cells = ["".join(x.text or "" for x in c.iter(W + "t")).strip() for c in row.iter(W + "tc")]
                if any(cells):
                    n += 1
                    yield "para%d" % n, " | ".join(cells)


def pptx(path):
    with zipfile.ZipFile(path) as z:
        names = sorted((n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)),
                       key=lambda n: int(re.findall(r"\d+", n)[-1]))
        for name in names:
            root = ET.fromstring(z.read(name))
            num = int(re.findall(r"\d+", name)[-1])
            for p in root.iter(A + "p"):
                t = "".join(x.text or "" for x in p.iter(A + "t")).strip()
                if t:
                    yield "slide%d" % num, t


def xlsx(path):
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(S + "si"):
                shared.append("".join(x.text or "" for x in si.iter(S + "t")))
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        target = {r.get("Id"): r.get("Target") for r in rels}
        for sh in wb.iter(S + "sheet"):
            t = target.get(sh.get(R + "id"), "")
            part = t.lstrip("/") if t.startswith("/") else "xl/" + t
            if part not in z.namelist():
                continue
            sname = re.sub(r"\s+", "_", sh.get("name"))
            for c in ET.fromstring(z.read(part)).iter(S + "c"):
                v = c.find(S + "v")
                if c.get("t") == "s" and v is not None:
                    val = shared[int(v.text)]
                elif c.get("t") == "inlineStr":
                    val = "".join(x.text or "" for x in c.iter(S + "t"))
                else:
                    val = v.text if v is not None else ""
                if str(val).strip():
                    yield "%s!%s" % (sname, c.get("r")), str(val).strip()


def pdf(path):
    try:
        import pypdf
        for i, page in enumerate(pypdf.PdfReader(path).pages, 1):
            for t in (page.extract_text() or "").splitlines():
                if t.strip():
                    yield "p%d" % i, t.strip()
        return
    except ImportError:
        pass
    if not shutil.which("pdftotext"):
        raise RuntimeError("no PDF reader on this machine (pip install pypdf, or install poppler-utils)")
    out = subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, text=True, check=True).stdout
    for i, page in enumerate(out.split("\f"), 1):
        for t in page.splitlines():
            if t.strip():
                yield "p%d" % i, t.strip()


CUE_TIME = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})(?:[.,]\d+)?")
VOICE = re.compile(r"<v(?:\.[^\s>]+)?\s+([^>]+)>")


def cue_place(stamp):
    """t00:01:23 from 00:01:23.456, 00:01:23,456 or 01:23.456."""
    m = CUE_TIME.match(stamp.strip())
    if not m:
        return None
    return "t%02d:%02d:%02d" % (int(m.group(1) or 0), int(m.group(2)), int(m.group(3)))


def transcript(path):
    """WebVTT or SRT: one place per cue, named by its start time (t00:01:23). A second cue that starts in the same second gets
    -2, -3 ... so every place is unique. A speaker named in a <v Name> tag is kept as "Name: text"."""
    with open(path, encoding="utf-8-sig", errors="replace") as fh:
        text = fh.read().replace("\r\n", "\n")
    seen = {}
    for block in re.split(r"\n\s*\n", text):
        lines = [ln for ln in block.split("\n") if ln.strip()]
        at = next((i for i, ln in enumerate(lines) if "-->" in ln), None)
        if at is None:
            continue
        place = cue_place(lines[at].split("-->")[0])
        if not place:
            continue
        speaker = ""
        body = []
        for ln in lines[at + 1:]:
            m = VOICE.search(ln)
            if m and not speaker:
                speaker = m.group(1).strip()
            body.append(re.sub(r"<[^>]+>", "", ln).strip())
        said = " ".join(b for b in body if b)
        if not said:
            continue
        seen[place] = seen.get(place, 0) + 1
        yield (place if seen[place] == 1 else "%s-%d" % (place, seen[place])), ("%s: %s" % (speaker, said) if speaker else said)


def chat_messages(data):
    """The list of message dicts in a Slack day file (a list), a Slack-style {"messages": [...]} or a Teams/Graph {"value": [...]}
    export, or None when the JSON is not shaped like a chat export."""
    items = data.get("value") or data.get("messages") if isinstance(data, dict) else data
    if not isinstance(items, list) or not items or not all(isinstance(m, dict) for m in items):
        return None
    if not any(("text" in m and ("ts" in m or "user" in m or "user_name" in m or "username" in m))
               or isinstance(m.get("body"), dict) for m in items):
        return None
    return items


def chat_like(path):
    try:
        if os.path.getsize(path) > 20 * 1024 * 1024:
            return False
        with open(path, encoding="utf-8-sig") as fh:
            return chat_messages(json.load(fh)) is not None
    except (OSError, ValueError):
        return False


def chat(path):
    """Slack and Teams JSON exports: one place per message, msg<n> by its position in the file. Text is "when who: text"."""
    with open(path, encoding="utf-8-sig") as fh:
        items = chat_messages(json.load(fh)) or []
    for i, m in enumerate(items, 1):
        body = m.get("body") if isinstance(m.get("body"), dict) else None
        text = (body or {}).get("content") if body else m.get("text")
        text = html.unescape(re.sub(r"<[^>]+>", " ", str(text or "")))
        text = " ".join(text.split())
        if not text:
            continue
        who = ((m.get("from") or {}).get("user") or {}).get("displayName") if isinstance(m.get("from"), dict) else None
        who = who or (m.get("user_profile") or {}).get("real_name") or m.get("user_name") or m.get("username") or m.get("user") or ""
        when = m.get("createdDateTime") or ""
        if not when and m.get("ts"):
            try:
                when = datetime.datetime.fromtimestamp(float(m["ts"]), datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            except (ValueError, OverflowError, OSError):
                when = str(m["ts"])
        yield "msg%d" % i, " ".join(p for p in (str(when), "%s:" % who if who else "", text) if p)


def plain(path, strip_html=False):
    with open(path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    if strip_html:
        text = html.unescape(re.sub(r"<[^>]+>", "\n", re.sub(r"(?is)<(script|style).*?</\1>", "", text)))
    for i, t in enumerate(text.splitlines(), 1):
        if t.strip():
            yield "line%d" % i, t.strip()


def kind(path):
    with open(path, "rb") as fh:
        head = fh.read(8)
    low = path.lower()
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"PK"):
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
        for k, part in (("docx", "word/document.xml"), ("pptx", "ppt/presentation.xml"), ("xlsx", "xl/workbook.xml")):
            if part in names:
                return k
        return "zip"
    if low.endswith(IMG_EXT) or head[:4] in (b"\x89PNG", b"GIF8", b"II*\x00", b"MM\x00*") or head[:3] == b"\xff\xd8\xff":
        return "image"
    if low.endswith((".html", ".htm")):
        return "html"
    if low.endswith((".vtt", ".srt")):
        return "transcript"
    if low.endswith(".json") and chat_like(path):
        return "chat"
    if low.endswith(TEXT_EXT):
        return "text"
    return "other"


READERS = {"docx": docx, "pptx": pptx, "xlsx": xlsx, "pdf": pdf, "text": plain,
           "html": lambda p: plain(p, True), "transcript": transcript, "chat": chat}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def manifest_path(scratch):
    return os.path.join(scratch, "manifest.yaml")


def load_manifest(scratch):
    p = manifest_path(scratch)
    if not os.path.isfile(p):
        raise SystemExit("no documents read yet in %s (run extract first)" % scratch)
    with open(p, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def cmd_extract(scratch, files, by, origins=None, registered=None, extra=None):
    """origins: {file: where it came from (a link, or a zip member)}. extra: {file: facts to keep with it: version, access, restricted_to, changed_from}.
    registered: {doc id: sha256} already in the KB register, so the same file keeps its id and a changed file gets a new one."""
    os.makedirs(scratch, exist_ok=True)
    man = load_manifest(scratch) if os.path.isfile(manifest_path(scratch)) else {"documents": {}}
    docs = man.setdefault("documents", {})
    registered = registered or {}
    for f in files:
        digest = sha256(f)
        known = [k for k, d in docs.items() if d["sha256"] == digest]
        if known:
            print("%s: already read as %s" % (f, known[0]))
            continue
        same = [k for k, s in registered.items() if s == digest and k not in docs]
        did = same[0] if same else doc_id(f, set(docs) | set(registered))
        k = kind(f)
        entry = {"name": os.path.basename(f), "sha256": digest, "bytes": os.path.getsize(f), "type": k,
                 "given_by": by, "given_on": datetime.date.today().isoformat(), "places": 0,
                 "path": os.path.abspath(f)}
        if (origins or {}).get(f):
            entry["origin"] = origins[f]
        entry.update((extra or {}).get(f) or {})
        try:
            if k == "image":
                raise RuntimeError("a picture has no text layer; the model reads it in the pictures step (doc_images.py)")
            if k not in READERS:
                raise RuntimeError("file type %s has no text reader; it is listed but not used as a source" % k)
            rows = list(READERS[k](f))
            if not rows:
                raise RuntimeError("no text found (a scanned or picture-only file? the pictures step, doc_images.py, can read it)")
            with open(os.path.join(scratch, did + ".txt"), "w", encoding="utf-8") as fh:
                for place, text in rows:
                    fh.write("[%s] %s\n" % (place, text))
            entry["places"] = len(rows)
            entry["status"] = "read"
            print("%s: read as %s (%s, %d places) -> %s.txt" % (f, did, k, len(rows), did))
        except Exception as e:  # noqa: BLE001
            entry["status"] = "not read"
            entry["reason"] = str(e)
            print("%s: NOT READ - %s" % (f, e))
        docs[did] = entry
    with open(manifest_path(scratch), "w", encoding="utf-8") as fh:
        yaml.safe_dump(man, fh, sort_keys=False, allow_unicode=True)
    return 0


def text_at(scratch, did):
    out = {}
    p = os.path.join(scratch, did + ".txt")
    if os.path.isfile(p):
        with open(p, encoding="utf-8") as fh:
            for line in fh:
                m = re.match(r"^\[([^\]]+)\] (.*)$", line.rstrip("\n"))
                if m:
                    out.setdefault(m.group(1), []).append(m.group(2))
    return out


def check_tags(scratch, text):
    """Yield (tag dict, problem or None) for every doc tag in text."""
    docs = load_manifest(scratch).get("documents", {})
    cache = {}
    for line in text.splitlines():
        good = DOC_TAG.findall(line)
        for raw in ANY_DOC.findall(line):
            if not DOC_TAG.match(raw):
                yield {"raw": raw}, 'doc tag must be [E: doc:<id>#<place> "quoted text"]'
        for did, place, quote in good:
            tag = {"doc": did, "place": place, "quote": quote}
            if did not in docs:
                yield tag, "document %s was not read in this session" % did
                continue
            if docs[did].get("status") != "read":
                yield tag, "document %s could not be read" % did
                continue
            places = cache.setdefault(did, text_at(scratch, did))
            if place not in places:
                yield tag, "%s has no place %s" % (did, place)
            elif norm(quote) not in norm(" ".join(places[place])):
                yield tag, "quoted text not found at %s#%s" % (did, place)
            else:
                yield tag, None


def cmd_check(scratch, files):
    bad = n = 0
    for f in files:
        with open(f, encoding="utf-8") as fh:
            for tag, prob in check_tags(scratch, fh.read()):
                n += 1
                if prob:
                    bad += 1
                    print("%s: %s %s" % (f, prob, tag.get("raw") or ""))
    print("doc check: %d tags, %d problems" % (n, bad))
    return 1 if bad else 0


def register_path(kb):
    return os.path.join(kb, "_EVIDENCE", "documents", "DOC_SOURCES.yaml")


def cmd_record(kb, scratch, kept_at=None):
    docs = load_manifest(scratch).get("documents", {})
    used, bad = {}, []
    for d, _, fs in os.walk(kb):
        if "/.git" in d or os.path.basename(d) == ".git":
            continue
        for f in fs:
            if not f.endswith((".md", ".yaml", ".yml", ".txt", ".html")):
                continue
            p = os.path.join(d, f)
            if os.path.abspath(p) == os.path.abspath(register_path(kb)):
                continue
            with open(p, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            for tag, prob in check_tags(scratch, text):
                if prob:
                    if "was not read in this session" in prob and tag.get("doc") in existing_ids(kb):
                        continue
                    bad.append("%s: %s" % (os.path.relpath(p, kb), prob))
                else:
                    used.setdefault(tag["doc"], set()).add((tag["place"], tag["quote"]))
    if bad:
        print("\n".join(bad))
        print("record: %d problems, nothing recorded" % len(bad))
        return 1
    reg = load_register(kb)
    for did, pairs in used.items():
        src = docs[did]
        entry = reg.setdefault(did, {k: src[k] for k in ("name", "sha256", "bytes", "type", "given_by", "given_on")})
        if entry.get("sha256") != src["sha256"]:
            print("%s: a different file with the same id is already recorded; nothing recorded" % did)
            return 1
        if src.get("origin"):
            entry.setdefault("origin", src["origin"])
        for k in ("version", "access", "restricted_to", "restriction_approved"):
            if src.get(k):
                entry[k] = src[k]
        if kept_at:
            entry["kept_at"] = kept_at
        elif str(src.get("origin") or "").startswith("http"):
            entry.setdefault("kept_at", src["origin"])
        have = {(c["place"], c["quote"]) for c in entry.get("checked", [])}
        picture = src.get("picture_places") or {}
        entry["checked"] = entry.get("checked", []) + [
            dict({"place": pl, "quote": q, "checked_on": datetime.date.today().isoformat()},
                 **({"read_from_picture_by_model": picture[pl]} if pl in picture else {}))
            for pl, q in sorted(pairs - have)]
    os.makedirs(os.path.dirname(register_path(kb)), exist_ok=True)
    with open(register_path(kb), "w", encoding="utf-8") as fh:
        fh.write("# Documents used as KB sources. The files are not in the repo; each quote below was checked\n"
                 "# against the file with this sha256 when it was recorded.\n")
        yaml.safe_dump({"documents": reg}, fh, sort_keys=False, allow_unicode=True)
    print("recorded %d documents, %d quotes -> %s" % (len(used), sum(len(v) for v in used.values()),
                                                      os.path.relpath(register_path(kb), kb)))
    return 0


def load_register(kb):
    p = register_path(kb)
    if not os.path.isfile(p):
        return {}
    with open(p, encoding="utf-8") as fh:
        return (yaml.safe_load(fh) or {}).get("documents") or {}


def existing_ids(kb):
    return set(load_register(kb))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("extract"); e.add_argument("scratch"); e.add_argument("files", nargs="+"); e.add_argument("--by", required=True)
    c = sub.add_parser("check"); c.add_argument("scratch"); c.add_argument("files", nargs="+")
    r = sub.add_parser("record"); r.add_argument("kb"); r.add_argument("scratch"); r.add_argument("--kept-at")
    a = ap.parse_args(argv)
    if a.cmd == "extract":
        return cmd_extract(a.scratch, a.files, a.by)
    if a.cmd == "check":
        return cmd_check(a.scratch, a.files)
    return cmd_record(a.kb, a.scratch, a.kept_at)


if __name__ == "__main__":
    sys.exit(main())
