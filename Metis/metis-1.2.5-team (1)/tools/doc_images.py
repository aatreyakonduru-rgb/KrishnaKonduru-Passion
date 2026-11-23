#!/usr/bin/env python3
"""Pictures step of document ingest: pull the pictures out of the documents so the model can look at them, then put
what it read back into the documents' text, at a place that can be quoted.

    python3 doc_images.py extract <scratch>     save every picture under <scratch>/images/ and list them in IMAGES.yaml
    python3 doc_images.py merge   <scratch>     add what the model wrote in IMAGE_TEXT.yaml to each document's text

Run it after doc_intake.py (or read_docs.py extract). It covers pictures inside PDF, Word, PowerPoint and Excel files,
scanned PDFs, and picture files given on their own (png, jpg, gif, bmp, tif, webp). No OCR program is needed: the model
looks at each picture file and writes what it sees.

IMAGES.yaml lists each picture: id (img-001), doc, place (p3/image1, slide4/image2, image1), file, bytes and status
(pending, or skipped with a reason: too small to matter, a copy of an earlier picture, or a format the model cannot view).

The model then writes <scratch>/IMAGE_TEXT.yaml:

    images:
      - id: img-001
        kind: text            # text = words visible in the picture, copied exactly (screenshot, scan, table)
        lines: ["Claim status | Days", "Open | 30"]
      - id: img-002
        kind: description     # description = what a diagram or photo shows, in plain words, no guesses
        lines: ["Box 'Intake' points to box 'Adjudication'"]
      - id: img-003
        kind: decorative      # logo, icon, background: nothing to record

`merge` writes each line to the document's text as [<place>] <line> (description lines start with "(model description)"),
so a page can quote it with [E: doc:<id>#slide4/image1 "Open | 30"]. These places are marked as read by a model, not by a
program: the register lists them under read_from_pictures and published pages say so.
"""
import argparse
import os
import posixpath
import re
import shutil
import sys
import zipfile
from xml.etree import ElementTree as ET

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import read_docs  # noqa: E402

VIEWABLE = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp")
MIN_BYTES = 4096
MAX_IMAGES = 200
PIC_PLACE = re.compile(r"(^|/)image\d+$")
REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
DESC = "(model description) "


def is_picture_place(place):
    return bool(PIC_PLACE.search(str(place)))


def sniff(data, name=""):
    ext = os.path.splitext(name)[1].lower()
    if data[:4] == b"\x89PNG":
        return ".png"
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:4] == b"GIF8":
        return ".gif"
    if data[:2] == b"BM":
        return ".bmp"
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return ".tif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return ext or ".bin"


def rels_of(z, part):
    folder, name = posixpath.split(part)
    path = posixpath.join(folder, "_rels", name + ".rels")
    if path not in z.namelist():
        return {}
    out = {}
    for r in ET.fromstring(z.read(path)):
        t = r.get("Target") or ""
        out[r.get("Id")] = posixpath.normpath(t.lstrip("/") if t.startswith("/") else posixpath.join(folder, t))
    return out


def blip_targets(z, part):
    """Media files a part (a slide, the Word body) shows, in the order they appear."""
    rels = rels_of(z, part)
    root = ET.fromstring(z.read(part))
    out = []
    for b in root.iter(read_docs.A + "blip"):
        t = rels.get(b.get(read_docs.R + "embed"))
        if t and t in z.namelist():
            out.append(t)
    return out


def office_images(path, kind):
    with zipfile.ZipFile(path) as z:
        if kind == "pptx":
            slides = sorted((n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)),
                            key=lambda n: int(re.findall(r"\d+", n)[-1]))
            for s in slides:
                num = int(re.findall(r"\d+", s)[-1])
                for j, t in enumerate(blip_targets(z, s), 1):
                    yield "slide%d/image%d" % (num, j), t, z.read(t)
        elif kind == "docx":
            for j, t in enumerate(blip_targets(z, "word/document.xml"), 1):
                yield "image%d" % j, t, z.read(t)
        else:
            for j, t in enumerate(sorted(n for n in z.namelist() if n.startswith("xl/media/")), 1):
                yield "image%d" % j, t, z.read(t)


def pdf_images(path):
    import pypdf
    for i, page in enumerate(pypdf.PdfReader(path).pages, 1):
        for j, im in enumerate(page.images, 1):
            yield "p%d/image%d" % (i, j), im.name, im.data


def pictures_of(doc):
    """(place, original name, bytes) for every picture a document holds."""
    path, k = doc["path"], doc["type"]
    if k == "image":
        with open(path, "rb") as fh:
            yield "image1", doc["name"], fh.read()
    elif k == "pdf":
        yield from pdf_images(path)
    elif k in ("docx", "pptx", "xlsx"):
        yield from office_images(path, k)


def cmd_extract(scratch):
    docs = read_docs.load_manifest(scratch).get("documents", {})
    out = os.path.join(scratch, "images")
    shutil.rmtree(out, ignore_errors=True)
    items, seen, n = [], {}, 0
    for did, d in docs.items():
        if not d.get("path") or not os.path.isfile(d["path"]):
            continue
        try:
            pics = list(pictures_of(d))
        except Exception as e:  # noqa: BLE001
            items.append({"id": "-", "doc": did, "place": "-", "status": "skipped",
                          "reason": "pictures could not be taken out (%s)" % str(e)[:100]})
            continue
        for place, name, data in pics:
            n += 1
            e = {"id": "img-%03d" % n, "doc": did, "place": place, "bytes": len(data)}
            ext = sniff(data, name)
            digest = read_docs.hashlib.sha256(data).hexdigest()
            if digest in seen:
                e.update(status="skipped", reason="same picture as %s; it gets the same text" % seen[digest],
                         duplicate_of=seen[digest])
            elif len(data) < MIN_BYTES:
                e.update(status="skipped", reason="smaller than %d bytes (an icon or a bullet)" % MIN_BYTES)
            elif ext not in VIEWABLE:
                e.update(status="skipped", reason="%s pictures cannot be shown to the model; save it as png and upload again" % ext)
            elif sum(1 for i in items if i.get("status") == "pending") >= MAX_IMAGES:
                e.update(status="skipped", reason="over the limit of %d pictures per run" % MAX_IMAGES)
            else:
                seen[digest] = e["id"]
                folder = os.path.join(out, did)
                os.makedirs(folder, exist_ok=True)
                f = os.path.join(folder, place.replace("/", "_") + ext)
                with open(f, "wb") as fh:
                    fh.write(data)
                e.update(status="pending", file=f)
            items.append(e)
    with open(os.path.join(scratch, "IMAGES.yaml"), "w", encoding="utf-8") as fh:
        yaml.safe_dump({"images": items}, fh, sort_keys=False, allow_unicode=True)
    pend = [i for i in items if i["status"] == "pending"]
    print("pictures: %d found, %d to look at, %d skipped -> %s" % (
        len(items), len(pend), len(items) - len(pend), os.path.join(scratch, "IMAGES.yaml")))
    for i in pend:
        print("  %s  %s#%s  %s" % (i["id"], i["doc"], i["place"], i["file"]))
    return 0


def load(path):
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def cmd_merge(scratch):
    items = {i["id"]: i for i in load(os.path.join(scratch, "IMAGES.yaml")).get("images") or []}
    texts = load(os.path.join(scratch, "IMAGE_TEXT.yaml")).get("images") or []
    problems, done = [], {}
    for t in texts:
        i = items.get(t.get("id"))
        if not i:
            problems.append("%s: not a picture in IMAGES.yaml" % t.get("id"))
        elif i["status"] != "pending":
            problems.append("%s: was skipped (%s)" % (i["id"], i.get("reason")))
        elif t.get("kind") not in ("text", "description", "decorative"):
            problems.append("%s: kind must be text, description or decorative" % i["id"])
        elif t["kind"] != "decorative" and not [x for x in t.get("lines") or [] if str(x).strip()]:
            problems.append("%s: no lines (use kind: decorative if there is nothing to record)" % i["id"])
        else:
            done[i["id"]] = t
    missing = [i["id"] for i in items.values() if i["status"] == "pending" and i["id"] not in done
               and i["id"] not in {t.get("id") for t in texts}]
    for i in items.values():  # a copy of a picture gets the text of the picture the model looked at
        if i.get("duplicate_of") in done:
            done[i["id"]] = done[i["duplicate_of"]]
    man = read_docs.load_manifest(scratch)
    docs = man["documents"]
    by_doc = {}
    for iid, t in done.items():
        i = items[iid]
        rows = by_doc.setdefault(i["doc"], {})
        if t["kind"] == "decorative":
            continue
        for line in t["lines"]:
            line = " ".join(str(line).split())
            if line:
                rows.setdefault(i["place"], []).append(DESC + line if t["kind"] == "description" else line)
                docs[i["doc"]].setdefault("picture_places", {})[i["place"]] = t["kind"]
    for did, rows in by_doc.items():
        kept = []
        for place, lines in read_docs.text_at(scratch, did).items():
            if not is_picture_place(place):
                kept += [(place, x) for x in lines]
        p = os.path.join(scratch, did + ".txt")
        with open(p, "w", encoding="utf-8") as fh:
            for place, x in kept:
                fh.write("[%s] %s\n" % (place, x))
            for place, lines in rows.items():
                for x in lines:
                    fh.write("[%s] %s\n" % (place, x))
        d = docs[did]
        d["places"] = len(read_docs.text_at(scratch, did))
        if rows:
            d["status"] = "read"
            d.pop("reason", None)
    with open(read_docs.manifest_path(scratch), "w", encoding="utf-8") as fh:
        yaml.safe_dump(man, fh, sort_keys=False, allow_unicode=True)
    for p in problems:
        print(p)
    if missing:
        print("no text written yet for: %s" % ", ".join(missing))
    kinds = [t["kind"] for t in done.values()]
    print("pictures merged: %d text, %d described, %d decorative; %d problems, %d still to look at" % (
        kinds.count("text"), kinds.count("description"), kinds.count("decorative"), len(problems), len(missing)))
    return 1 if problems or missing else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("extract", "merge"))
    ap.add_argument("scratch")
    a = ap.parse_args(argv)
    return (cmd_extract if a.cmd == "extract" else cmd_merge)(os.path.abspath(a.scratch))


if __name__ == "__main__":
    sys.exit(main())
