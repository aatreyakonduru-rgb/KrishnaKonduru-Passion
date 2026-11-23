#!/usr/bin/env python3
"""Pass 2 of document ingest: suggest a category for each document, check the pages written from them, and publish
the pages into the KB with who gave each document and where it came from.

    python3 doc_kb.py classify <kb> <scratch>                       write <scratch>/PLAN.yaml (suggested category per document)
    python3 doc_kb.py publish  <kb> <scratch> [--kept-at "<where the originals are kept>"] [--dry-run]
    python3 doc_kb.py index    <kb>                                 rewrite <kb>/context/DOC_INDEX.md
    python3 doc_kb.py approve-restricted <scratch> <doc id> --kb <kb> --by LEAD --note WHY
                                                                    a lead allows a document that is restricted at its source

The pages are written (by Mētis, from <scratch>/<doc id>.txt) as <scratch>/pages/<name>.md:

    ---
    title: Claims payment rules
    category: requirements          # an id from doc-categories.yaml
    ---
    - Claims are paid within 30 days [E: doc:Claims-Rules.docx#para1 "paid within 30 days"]

`publish` refuses the whole batch if any page has a problem: unknown category, no document tag, a quote that is not
at that place in the document, or something that looks like a password or an SSN. When all pages pass it writes each page
to <kb>/<category folder>/<slug>.md with front matter and a "Sources" section (document, who gave it, when, link), a page that
already exists and was not made by this tool, or is on kb-keep.yaml, gets the new text beside it as <slug>.NEW.md,
rewrites context/DOC_INDEX.md, and records the documents and every checked quote in _EVIDENCE/documents/DOC_SOURCES.yaml.
Categories come from <kb>/.metis/doc-categories.yaml, else templates/doc-categories.yaml.
"""
import argparse
import datetime
import os
import re
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kb_compare  # noqa: E402
import kb_gate  # noqa: E402
import read_docs  # noqa: E402
import sensitive  # noqa: E402
import verify_kb  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
GENERATOR = "doc_kb.py"
INDEX = os.path.join("context", "DOC_INDEX.md")
FRONT = re.compile(r"\A---\n(.*?)\n---\n?", re.S)
SKIP_DIRS = ("_EVIDENCE", ".metis", "Archive", "_REGEN", ".git", "_QUESTIONS", "_PENDING", "_FEEDBACK")


def load_yaml(path):
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def categories(kb):
    p = os.path.join(kb, ".metis", "doc-categories.yaml")
    if not os.path.isfile(p):
        p = os.path.join(HERE, "..", "templates", "doc-categories.yaml")
    cats = {}
    for c in load_yaml(p).get("categories") or []:
        if c.get("id") and c.get("folder"):
            cats[c["id"]] = c
    if "other" not in cats:
        cats["other"] = {"id": "other", "title": "Other documents", "folder": "context/other", "keywords": []}
    return cats


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")[:80] or "page"


def split_front(text):
    m = FRONT.match(text.replace("\r\n", "\n"))
    if not m:
        return {}, text.replace("\r\n", "\n")
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        meta = {}
    return (meta if isinstance(meta, dict) else {}), text.replace("\r\n", "\n")[m.end():]


def doc_lines(scratch, did, limit=None):
    out = []
    for _, lines in read_docs.text_at(scratch, did).items():
        out += lines
        if limit and len(out) >= limit:
            break
    return out


# ---- classify ---------------------------------------------------------------------------------
def classify(kb, scratch):
    cats = categories(kb)
    docs = read_docs.load_manifest(scratch).get("documents", {})
    reg = read_docs.load_register(kb)
    plan = []
    for did, d in docs.items():
        e = {"id": did, "name": d["name"], "given_by": d.get("given_by"), "given_on": d.get("given_on"),
             "origin": d.get("origin"), "status": d.get("status")}
        if d.get("status") != "read":
            e["reason"] = d.get("reason")
            plan.append(e)
            continue
        lines = doc_lines(scratch, did, 400)
        body = " ".join(lines).lower()
        name = d["name"].lower().replace("_", " ").replace("-", " ")
        scores = {}
        for cid, c in cats.items():
            s = sum(body.count(k.lower()) + 3 * name.count(k.lower()) for k in c.get("keywords") or [])
            if s:
                scores[cid] = s
        ranked = sorted(scores.items(), key=lambda kv: -kv[1])
        e["suggested_category"] = ranked[0][0] if ranked else "other"
        e["scores"] = dict(ranked[:3])
        e["title_guess"] = lines[0][:100] if lines else d["name"]
        e["places"] = d.get("places")
        if d.get("access") == "restricted":
            e["restricted_to"] = d.get("restricted_to")
            e["restriction_approved_by"] = (d.get("restriction_approved") or {}).get("by")
        if d.get("changed_from"):
            e["changed_from"] = d["changed_from"]
        if d.get("sha256") in {r.get("sha256") for r in reg.values()}:
            e["already_in_kb"] = True
        older = [k for k, r in reg.items() if r.get("name") == d["name"] and r.get("sha256") != d.get("sha256")]
        if older:
            e["supersedes"] = older
        plan.append(e)
    out = os.path.join(scratch, "PLAN.yaml")
    with open(out, "w", encoding="utf-8") as fh:
        yaml.safe_dump({"categories": {k: c.get("title") for k, c in cats.items()}, "documents": plan}, fh,
                       sort_keys=False, allow_unicode=True)
    print("classified %d documents -> %s" % (len(plan), out))
    return 0


# ---- check pages ------------------------------------------------------------------------------
def doc_info(did, man, reg):
    d = man.get(did) or reg.get(did) or {}
    out = {"id": did, "name": d.get("name"), "given_by": d.get("given_by"), "given_on": d.get("given_on"),
           "origin": d.get("kept_at") or d.get("origin")}
    if d.get("access") == "restricted":
        out["restricted_to"] = d.get("restricted_to") or ["named people"]
        out["restriction_approved_by"] = (d.get("restriction_approved") or {}).get("by")
    return out


def read_pages(scratch):
    folder = os.path.join(scratch, "pages")
    if not os.path.isdir(folder):
        raise SystemExit("no pages in %s (write them as <scratch>/pages/<name>.md first)" % folder)
    pages = []
    for f in sorted(os.listdir(folder)):
        if f.endswith(".md"):
            with open(os.path.join(folder, f), encoding="utf-8") as fh:
                meta, body = split_front(fh.read())
            pages.append({"file": f, "meta": meta, "body": body})
    return pages


def check_page(p, cats, scratch, reg, man, checker=None):
    problems, used, good = [], [], {}
    f = p["file"]
    if not str(p["meta"].get("title") or "").strip():
        problems.append("%s: front matter needs a title" % f)
    if p["meta"].get("category") not in cats:
        problems.append("%s: category must be one of %s" % (f, ", ".join(cats)))
    for line in re.findall(r"^\s*#{1,6}\s*sources\b.*$", p["body"], re.I | re.M):
        problems.append("%s: leave out the Sources section; it is added from the documents' details" % f)
    for n, line in enumerate(p["body"].splitlines(), 1):
        for lvl, kind, _ in sensitive.scan_line(line):
            if lvl == sensitive.BLOCK:
                problems.append("%s:%d: looks like a %s; take it out" % (f, n, kind))
        for tag, prob in read_docs.check_tags(scratch, line):
            if not prob and ";" in tag["quote"]:
                problems.append("%s:%d: a quote must not contain ';' (the source check splits tags there): %s" % (f, n, tag["quote"][:40]))
                continue
            if not prob:
                used.append(tag["doc"])
                good.setdefault(tag["doc"], []).append({"place": tag["place"], "quote": tag["quote"]})
                continue
            if "was not read in this session" in prob and tag.get("doc") in reg:
                done = {(c["place"], read_docs.norm(c["quote"])) for c in reg[tag["doc"]].get("checked") or []}
                if (tag["place"], read_docs.norm(tag["quote"])) in done:
                    used.append(tag["doc"])
                    good.setdefault(tag["doc"], []).append({"place": tag["place"], "quote": tag["quote"]})
                    continue
            problems.append("%s:%d: %s %s" % (f, n, prob, tag.get("raw") or ""))
    for did in sorted(set(used)):
        d = man.get(did) or reg.get(did) or {}
        if d.get("access") == "restricted" and not (d.get("restriction_approved") or {}).get("by"):
            problems.append("%s: %s (%s) is restricted to %s at its source; a lead must approve using it (approve-restricted)" % (
                f, d.get("name"), did, ", ".join(d.get("restricted_to") or ["named people"])))
    if not used and not problems:
        problems.append("%s: no [E: doc:...] tag; a page needs at least one fact from a document" % f)
    if checker is not None and not problems:
        # the same line rule verify_kb.py applies after publishing: every fact line (or its heading) carries a tag
        checker.documents = {d: {"checked": c} for d, c in good.items()}
        found, counts = [], {"tags": 0, "fact_lines": 0}
        checker.check_text(f, p["body"], found, counts)
        problems += ["%s:%d: %s" % (f, n, why) for _, n, why in found]
    return problems, sorted(set(used))


def target_for(kb, cats, meta, keep, mine_only=True):
    rel = "%s/%s.md" % (cats[meta["category"]]["folder"].strip("/"), slug(meta["title"]))
    dst = os.path.normpath(os.path.join(kb, rel))
    if not dst.startswith(os.path.normpath(kb) + os.sep):
        raise SystemExit("category folder leaves the KB: %s" % rel)
    if os.path.exists(dst):
        with open(dst, encoding="utf-8", errors="replace") as fh:
            old, _ = split_front(fh.read())
        if kb_compare.kept_by(rel, keep) or old.get("generated_by") != GENERATOR:
            rel = rel[:-3] + ".NEW.md"
            dst = dst[:-3] + ".NEW.md"
    return rel, dst


def render(meta, body, docs):
    front = {"title": meta["title"], "category": meta["category"], "generated_by": GENERATOR,
             "updated": datetime.date.today().isoformat(), "documents": docs}
    body = body.strip("\n")
    if not body.lstrip().startswith("# "):
        body = "# %s\n\n%s" % (meta["title"], body)
    src = ["", "## Sources", ""]
    if re.search(r"doc:[\w.-]+#\S*image\d+\s", body):
        src += ["Some facts above were read from pictures inside the documents by a model, not by a program. "
                "Check them against the originals.", ""]
    for d in docs:
        line = "- %s, given by %s on %s" % (d["name"], d.get("given_by") or "unknown", d.get("given_on") or "unknown date")
        if d.get("origin"):
            line += "; kept at %s" % d["origin"]
        if d.get("restricted_to"):
            line += "; restricted at its source to %s, use approved by %s" % (", ".join(d["restricted_to"]), d.get("restriction_approved_by"))
        src.append(line + " (document id `%s`)" % d["id"])
    return "---\n%s---\n\n%s\n%s\n" % (yaml.safe_dump(front, sort_keys=False, allow_unicode=True), body, "\n".join(src))


def publish(kb, scratch, kept_at=None, dry=False):
    cats, reg = categories(kb), read_docs.load_register(kb)
    man = read_docs.load_manifest(scratch).get("documents", {})
    keep_path = os.path.join(kb, ".metis", "kb-keep.yaml")
    keep = kb_compare.load_keep(keep_path) if os.path.isfile(keep_path) else []
    pages, problems, seen, plan = read_pages(scratch), [], {}, []
    checker = verify_kb.Checker(kb)
    for p in pages:
        bad, used = check_page(p, cats, scratch, reg, man, checker)
        problems += bad
        if bad:
            continue
        rel, dst = target_for(kb, cats, p["meta"], keep)
        if rel in seen:
            problems.append("%s: same title as %s; both would write %s" % (p["file"], seen[rel], rel))
            continue
        seen[rel] = p["file"]
        plan.append((p, rel, dst, [doc_info(d, man, reg) for d in used]))
    if problems:
        print("\n".join(problems))
        print("publish: %d problems, nothing written" % len(problems))
        return 1
    gated = kb_gate.is_locked(kb)
    batch = kb_gate.new_batch(kb, "documents") if gated and not dry else None
    for p, rel, dst, docs in plan:
        print("%s -> %s%s" % (p["file"], rel, " (beside the existing file; not replaced)" if rel.endswith(".NEW.md") else ""))
        if dry:
            continue
        text = render(p["meta"], p["body"], docs)
        if gated:
            kb_gate.stage_text(kb, batch, rel, text)
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    if dry:
        print("publish: dry run, %d pages would be written" % len(plan))
        return 0
    if read_docs.cmd_record(kb, scratch, kept_at):
        return 1
    if gated:
        path, _ = kb_gate.digest(kb, batch)
        print("publish: %d pages staged in batch %s, not in the KB yet. A lead must certify them; digest: %s" % (len(plan), batch, path))
        return 0
    build_index(kb)
    print("publish: %d pages written, index %s" % (len(plan), INDEX.replace(os.sep, "/")))
    return 0


def approve_restricted(kb, scratch, did, by, note):
    name, role = kb_gate.who(kb, by)
    if not (note or "").strip():
        raise kb_gate.GateError("say why a restricted source may be used")
    man = read_docs.load_manifest(scratch)
    d = (man.get("documents") or {}).get(did)
    if not d:
        raise kb_gate.GateError("document %s was not read in this session" % did)
    if d.get("access") != "restricted":
        raise kb_gate.GateError("%s is not restricted" % did)
    d["restriction_approved"] = {"by": name, "role": role, "on": datetime.date.today().isoformat(), "note": note.strip()}
    with open(read_docs.manifest_path(scratch), "w", encoding="utf-8") as fh:
        yaml.safe_dump(man, fh, sort_keys=False, allow_unicode=True)
    return d


# ---- index ------------------------------------------------------------------------------------
def kb_pages(kb):
    for d, dirs, fs in os.walk(kb):
        dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS)
        for f in sorted(fs):
            rel = os.path.relpath(os.path.join(d, f), kb).replace(os.sep, "/")
            if f.endswith(".md") and rel != INDEX.replace(os.sep, "/"):
                with open(os.path.join(d, f), encoding="utf-8", errors="replace") as fh:
                    meta, _ = split_front(fh.read())
                if meta.get("generated_by") == GENERATOR:
                    yield rel, meta


def cell(x):
    return str(x if x is not None else "").replace("|", "/").replace("\n", " ")


def build_index(kb):
    cats = categories(kb)
    rows = sorted(kb_pages(kb), key=lambda r: (str(r[1].get("category")), r[0]))
    reg = read_docs.load_register(kb)
    used_by = {}
    for rel, meta in rows:
        for d in meta.get("documents") or []:
            used_by.setdefault(d.get("id"), []).append(rel)
    L = ["---", "generated_by: %s index" % GENERATOR, "---", "", "# Document sources", "",
         "Pages in this KB made from documents people uploaded or linked. Each page lists its documents, who gave them and "
         "where they are kept. Rebuilt by `doc_kb.py index`; do not edit by hand.", "",
         "## Sources by page", "", "| Page | Category | Documents | Given by |", "|---|---|---|---|"]
    for rel, meta in rows:
        docs = meta.get("documents") or []
        L.append("| [%s](../%s) | %s | %s | %s |" % (
            cell(meta.get("title")), rel, cell((cats.get(meta.get("category")) or {}).get("title") or meta.get("category")),
            cell(", ".join(str(d.get("name")) for d in docs)),
            cell(", ".join(sorted({str(d.get("given_by")) for d in docs if d.get("given_by")}))))
        )
    L += ["", "## Sources by document", "", "| Document | Given by | Given on | Kept at | Pages |", "|---|---|---|---|---|"]
    for did, r in sorted(reg.items()):
        L.append("| %s | %s | %s | %s | %s |" % (cell(r.get("name")), cell(r.get("given_by")), cell(r.get("given_on")),
                                                 cell(r.get("kept_at") or r.get("origin")),
                                                 cell(", ".join(used_by.get(did, [])) or "none yet")))
    path = os.path.join(kb, INDEX)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(L) + "\n")
    return len(rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("classify"); c.add_argument("kb"); c.add_argument("scratch")
    p = sub.add_parser("publish"); p.add_argument("kb"); p.add_argument("scratch"); p.add_argument("--kept-at"); p.add_argument("--dry-run", action="store_true")
    i = sub.add_parser("index"); i.add_argument("kb")
    r = sub.add_parser("approve-restricted"); r.add_argument("scratch"); r.add_argument("doc"); r.add_argument("--kb", required=True)
    r.add_argument("--by", required=True); r.add_argument("--note", required=True)
    a = ap.parse_args(argv)
    kb = os.path.abspath(a.kb)
    if a.cmd == "classify":
        return classify(kb, os.path.abspath(a.scratch))
    if a.cmd == "approve-restricted":
        try:
            d = approve_restricted(kb, os.path.abspath(a.scratch), a.doc, a.by, a.note)
        except kb_gate.GateError as err:
            print("error: %s" % err, file=sys.stderr)
            return 2
        print("%s may be used: approved by %s" % (d["name"], d["restriction_approved"]["by"]))
        return 0
    if a.cmd == "publish":
        return publish(kb, os.path.abspath(a.scratch), a.kept_at, a.dry_run)
    print("%d pages indexed -> %s" % (build_index(kb), INDEX))
    return 0


if __name__ == "__main__":
    sys.exit(main())
