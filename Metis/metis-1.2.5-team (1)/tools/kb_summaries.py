#!/usr/bin/env python3
"""Area summaries, GraphRAG style: a tree of areas built without a model, a prompt for a session to write the summaries, and a
check that every summary line keeps the source tags of the pages it summarises.

    python3 kb_summaries.py build  <kb> [--out DIR]       write SUMMARY_TREE.yaml and PROMPT.md (default <kb>/.metis/summaries/)
    python3 kb_summaries.py status <kb> [--out DIR]       the tree, which summaries exist, and which pages changed since it was built
    python3 kb_summaries.py verify <kb> [--dir DIR]       check the summaries a session wrote (default <kb>/.metis/summaries/out/)
    python3 kb_summaries.py stage  <kb> --by NAME [--dir DIR] [--batch NAME]
                                                          verify, then stage the summary pages into _PENDING for a lead to certify

Structure (no model): a page belongs to the area of its folder (a top folder; a top folder with more than 12 pages is split by its
sub-folders). Pages are also grouped by the link graph (CROSS-LAYER/LINK_GRAPH.yaml through graph_store.py): a page whose name is
a graph object is joined to the pages of the objects it is linked to, and a deterministic label-propagation pass groups them.
A group that spans two or more folders becomes a cross-cutting area of its own ("cluster"); a group inside one folder adds nothing
and is not listed. Each area lists its pages, its key objects (graph objects the pages name, most linked first) and the open
questions its pages carry. Parent areas list their children. Summary pages and generated pages are not summarised.

The words are the session's: PROMPT.md tells a Devin or Bob session to write one page per area into the out folder, children
before parents. The rule that makes the result safe is checked here, not trusted: a summary line is a fact line, so it must carry
at least one [E: ...] tag, and each tag must be one that appears verbatim in a page of that area (a parent area may use the tags of
all its descendants). `verify` also resolves every tag against the sources (verify_kb.py) and screens the text for secrets.

`stage` never writes into the KB proper. It puts the pages in _PENDING/<batch>/summaries/ through kb_gate.py; a lead certifies them
like any other change (an open KB shows them as a pending batch too). The tree and prompt live in .metis/ and are not KB content.
"""
import argparse
import hashlib
import json
import os
import re
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import kb_coverage  # noqa: E402
import kb_gate  # noqa: E402
import sensitive  # noqa: E402
import verify_kb  # noqa: E402

DIR = os.path.join(".metis", "summaries")
TREE = "SUMMARY_TREE.yaml"
PROMPT = "PROMPT.md"
OUT = "out"
SPLIT_AT = 12          # a top folder with more pages than this is split by sub-folder
SUBAREA_MIN = 3        # a sub-folder needs this many pages to be an area of its own
SUMMARY_TYPE = "area-summary"
SUMMARY_DIR = "summaries"
WORD = re.compile(r"[A-Za-z0-9_$]+")
QID = re.compile(r"\[\?:\s*(Q-\d+)\s*\]")


class SummaryError(ValueError):
    pass


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-") or "area"


def norm(text):
    return " ".join(str(text).split())


def sha(text):
    return hashlib.sha1(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()[:12]


def folder_dir(kb, out=None):
    return os.path.abspath(out) if out else os.path.join(kb, DIR)


# ---- pages ------------------------------------------------------------------------------------------
def source_pages(kb):
    """{page: text}: hand-written pages, without secrets, without earlier summaries."""
    out = {}
    for rel, text in kb_coverage.page_files(kb).items():
        meta, _ = kb_gate.front(text)
        if str(meta.get("type") or "") == SUMMARY_TYPE or rel.split("/")[0] == SUMMARY_DIR:
            continue
        if sensitive.blocking(sensitive.scan(text)):
            continue
        out[rel] = text
    return out


def title_of(rel, text):
    _, body = kb_gate.front(text)
    for line in body.splitlines():
        m = re.match(r"^#\s+(.*)$", line.strip())
        if m:
            return norm(verify_kb.TAG.sub("", m.group(1))) or rel
    return os.path.splitext(os.path.basename(rel))[0]


def tag_parts(text):
    """The set of E-tag parts (split on ';', whitespace normalised) a text carries."""
    out = set()
    for kind, value in verify_kb.TAG.findall(text):
        if kind == "E":
            out |= {norm(p) for p in value.split(";") if p.strip()}
    return out


# ---- the link graph ---------------------------------------------------------------------------------
def graph_rows(kb):
    """([(id, type, name)], [(src, dst)]) from graph_store; ([], []) when there is no link graph."""
    if not os.path.isfile(os.path.join(kb, "CROSS-LAYER", "LINK_GRAPH.yaml")) and not os.path.isfile(os.path.join(kb, ".metis", "graph.sqlite")):
        return [], []
    try:
        import graph_store
        con = graph_store.connect(kb)
        try:
            return ([tuple(r) for r in con.execute("select id, type, name from nodes order by id")],
                    [tuple(r) for r in con.execute("select src, dst from edges order by n")])
        finally:
            con.close()
    except (Exception, SystemExit):
        return [], []


def short(name):
    return re.split(r"[./]", str(name))[-1].lower()


def label_propagation(nodes, edges, rounds=20):
    """Deterministic: nodes are visited in sorted order, a node takes the most common label among its neighbours (ties: smallest)."""
    adj = {n: set() for n in nodes}
    for a, b in edges:
        if a in adj and b in adj and a != b:
            adj[a].add(b)
            adj[b].add(a)
    label = {n: n for n in sorted(adj)}
    for _ in range(rounds):
        moved = False
        for n in sorted(adj):
            if not adj[n]:
                continue
            tally = {}
            for m in adj[n]:
                tally[label[m]] = tally.get(label[m], 0) + 1
            best = sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))[0]
            if tally.get(label[n], 0) < best[1] and label[n] != best[0]:
                label[n] = best[0]
                moved = True
        if not moved:
            break
    return label


# ---- the tree ---------------------------------------------------------------------------------------
def area_pages(pages):
    """{area id: {title, parent, pages}} by folder: top folders, split by sub-folder when a top folder is large."""
    tops = {}
    for rel in pages:
        tops.setdefault(rel.split("/")[0] if "/" in rel else "(top)", []).append(rel)
    areas = {}
    for top, rels in sorted(tops.items()):
        tid = "area-" + slug(top)
        areas[tid] = {"title": top, "parent": None, "folder": top if top != "(top)" else "", "pages": sorted(rels), "children": []}
        if len(rels) > SPLIT_AT:
            subs = {}
            for rel in rels:
                parts = rel.split("/")
                if len(parts) > 2:
                    subs.setdefault(parts[1], []).append(rel)
            for sub, srels in sorted(subs.items()):
                if len(srels) >= SUBAREA_MIN:
                    sid = "area-%s-%s" % (slug(top), slug(sub))
                    areas[sid] = {"title": "%s/%s" % (top, sub), "parent": tid, "folder": "%s/%s" % (top, sub), "pages": sorted(srels), "children": []}
                    areas[tid]["children"].append(sid)
    return areas


def build_tree(kb):
    kb = os.path.abspath(kb)
    pages = source_pages(kb)
    areas = area_pages(pages)
    nodes, edges = graph_rows(kb)
    words = {rel: {w.lower() for w in WORD.findall(text)} for rel, text in pages.items()}
    by_name = {}
    for nid, ntype, name in nodes:
        if len(short(name)) >= 3:
            by_name.setdefault(short(name), []).append(nid)
    info = {nid: (ntype, name) for nid, ntype, name in nodes}
    degree = {}
    for a, b in edges:
        degree[a] = degree.get(a, 0) + 1
        degree[b] = degree.get(b, 0) + 1
    # which graph objects a page names; the object a page is about is the one its file name says
    mentions = {rel: sorted({nid for w in words[rel] for nid in by_name.get(w, [])}) for rel in pages}
    subject = {}
    for rel in pages:
        stem = short(os.path.splitext(os.path.basename(rel))[0])
        for nid in by_name.get(stem, []):
            subject.setdefault(nid, []).append(rel)

    def fill(area):
        rels = area["pages"]
        objs = sorted({nid for r in rels for nid in mentions[r]}, key=lambda n: (-degree.get(n, 0), n))
        linked = ["%s:%s (%d links)" % (info[n][0], info[n][1], degree[n]) for n in objs if degree.get(n)]
        area["key_objects"] = (linked or ["%s:%s" % (info[n][0], info[n][1]) for n in objs])[:8]
        area["open_questions"] = sorted({q for r in rels for q in QID.findall(pages[r])})
        area["page_info"] = [{"path": r, "title": title_of(r, pages[r]), "tags": len(tag_parts(pages[r])), "sha": sha(pages[r])} for r in rels]
        area["tag_count"] = sum(p["tags"] for p in area["page_info"])

    for a in areas.values():
        fill(a)
    # groups by connectivity: pages joined when the objects they are about are linked
    page_edges = []
    for a, b in edges:
        for pa in subject.get(a, []):
            for pb in subject.get(b, []):
                if pa != pb:
                    page_edges.append((pa, pb))
    clusters = []
    if page_edges:
        label = label_propagation(sorted({p for e in page_edges for p in e}), page_edges)
        groups = {}
        for p, lab in label.items():
            groups.setdefault(lab, []).append(p)
        n = 0
        for lab, rels in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            folders = sorted({r.split("/")[0] if "/" in r else "(top)" for r in rels})
            if len(rels) >= 2 and len(folders) >= 2:
                n += 1
                cid = "cluster-%d-%s" % (n, slug(os.path.splitext(os.path.basename(sorted(rels)[0]))[0]))
                c = {"title": "Linked group %d: %s" % (n, ", ".join(os.path.splitext(os.path.basename(r))[0] for r in sorted(rels)[:3])),
                     "parent": "root", "folder": "", "pages": sorted(rels), "children": [], "folders": folders}
                fill(c)
                clusters.append((cid, c))
    for cid, c in clusters:
        areas[cid] = c
    tops = [k for k, v in areas.items() if v["parent"] is None]
    return {"version": 1, "pages": len(pages), "graph": {"nodes": len(nodes), "edges": len(edges)},
            "root": {"id": "root", "title": "Knowledge base", "children": tops + [c for c, _ in clusters]},
            "areas": areas}


def tree_path(kb, out=None):
    return os.path.join(folder_dir(kb, out), TREE)


def load_tree(kb, out=None):
    p = tree_path(kb, out)
    if not os.path.isfile(p):
        raise SummaryError("no summary tree yet; run: python3 kb_summaries.py build <kb>")
    with open(p, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def descendants(tree, aid):
    if aid == "root":
        return sorted({p for a in tree["areas"].values() for p in a["pages"]})
    a = tree["areas"].get(aid) or {}
    out = set(a.get("pages") or [])
    for c in a.get("children") or []:
        out |= set(descendants(tree, c))
    return sorted(out)


def order(tree):
    """Area ids, children before parents, the root last."""
    kids = {c for a in tree["areas"].values() for c in a.get("children") or []}
    return sorted(kids) + [a for a in tree["areas"] if a not in kids] + ["root"]


# ---- the prompt -------------------------------------------------------------------------------------
def prompt_text(kb, tree, out_dir):
    L = ["# Task: write the area summaries for this KB", "",
         "KB folder: %s" % os.path.abspath(kb),
         "Write one Markdown page per area into: %s" % os.path.abspath(out_dir),
         "Name each file after the area id: `<area id>.md`. The tree is in `SUMMARY_TREE.yaml` next to this file.",
         "Write children before parents. Finish with `root.md`, which summarises the areas.", "",
         "## Rules (they are checked by `kb_summaries.py verify`, and a page that breaks one is refused)", "",
         "1. Use only what the pages of the area say. Do not add a fact, a number or a name the pages do not state.",
         "2. Every line that is not a heading carries at least one source tag `[E: ...]`. Copy the tag from the page line you "
         "are summarising, character for character. Do not write a new tag, do not shorten a quote, do not use a tag from a page "
         "outside the area. A parent area may use the tags of any page below it.",
         "3. A line that joins several lines of a page keeps the tag of each of them, in one bracket separated by `;` or in "
         "several brackets.",
         "4. Where the pages leave something unknown, say so under `## Not in the KB` and keep the page's `[?: Q-nnnn]` tag. "
         "Never fill the gap.",
         "5. Short: about five to twelve lines per area. Lead with what the area is for, then the main objects, the rules and "
         "the limits. Name the key objects listed for the area.",
         "6. No secrets, passwords, keys or personal ids.", "",
         "Start each page with a title line, for example `# Summary: <area title>`. Do not write front matter: it is added when "
         "the page is staged.", "",
         "When all pages are written, check them and stage them:", "",
         "    python3 <metis>/tools/kb_summaries.py verify \"%s\"" % os.path.abspath(kb),
         "    python3 <metis>/tools/kb_summaries.py stage \"%s\" --by \"<your name>\"" % os.path.abspath(kb), "",
         "Staging puts the pages in `_PENDING`; a lead certifies them. Do not write into the KB folders yourself.", "",
         "## Areas (children first)", ""]
    for aid in order(tree):
        if aid == "root":
            kids = tree["root"]["children"]
            L += ["### root - %s" % tree["root"]["title"], "- Summarises the areas: %s" % ", ".join(kids), ""]
            continue
        a = tree["areas"][aid]
        L.append("### %s - %s" % (aid, a["title"]))
        if a.get("children"):
            L.append("- Child areas (summarise them first): %s" % ", ".join(a["children"]))
        if a.get("folders"):
            L.append("- Crosses folders: %s" % ", ".join(a["folders"]))
        L.append("- Pages (%d, %d source tags):" % (len(a["pages"]), a.get("tag_count", 0)))
        L += ["    - %s: %s" % (p["path"], p["title"]) for p in a["page_info"]]
        if a.get("key_objects"):
            L.append("- Key objects: %s" % "; ".join(a["key_objects"]))
        if a.get("open_questions"):
            L.append("- Open questions on these pages: %s" % ", ".join(a["open_questions"]))
        L.append("")
    return "\n".join(L) + "\n"


def build(kb, out=None):
    kb = os.path.abspath(kb)
    tree = build_tree(kb)
    d = folder_dir(kb, out)
    os.makedirs(os.path.join(d, OUT), exist_ok=True)
    with open(tree_path(kb, out), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("# Summary tree skeleton from kb_summaries.py (structure only, no model). Not KB content.\n")
        yaml.safe_dump(tree, fh, sort_keys=False, allow_unicode=True, width=110)
    with open(os.path.join(d, PROMPT), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(prompt_text(kb, tree, os.path.join(d, OUT)))
    return {"dir": d, "areas": len(tree["areas"]), "pages": tree["pages"], "tree": tree_path(kb, out), "prompt": os.path.join(d, PROMPT)}


# ---- verify -----------------------------------------------------------------------------------------
def verify_text(kb, tree, aid, text, checker=None, pages=None):
    """Problems [(line, text)] in one summary page for area `aid`."""
    if aid != "root" and aid not in tree["areas"]:
        return [(0, "%s is not an area in the tree" % aid)]
    pages = pages if pages is not None else source_pages(kb)
    allowed = set()
    for rel in descendants(tree, aid):
        if rel in pages:
            allowed |= tag_parts(pages[rel])
    problems, in_code, exempt = [], False, False
    _, body = kb_gate.front(text)
    line0 = text.count("\n") - body.count("\n")
    for n, raw in enumerate(body.split("\n"), line0 + 1):
        s = raw.strip()
        if s.startswith("```"):
            in_code = not in_code
            continue
        if in_code or not s or s.startswith("<!--") or re.match(r"^\|?\s*:?-{3,}[\s|:-]*$", s):
            continue
        h = verify_kb.HEADING.match(s)
        if h:
            exempt = bool(verify_kb.EXEMPT.search(verify_kb.TAG.sub("", h.group(2))))
            continue
        tags = verify_kb.TAG.findall(s)
        etags = [(k, v) for k, v in tags if k == "E"]
        if not etags and not (exempt and tags):
            problems.append((n, "summary line has no [E: ...] tag: %s" % s[:80]))
            continue
        for _, value in etags:
            for part in value.split(";"):
                if part.strip() and norm(part) not in allowed:
                    problems.append((n, "tag [E: %s] is not a tag of any page in %s" % (norm(part)[:70], aid)))
    checker = checker or verify_kb.Checker(kb)
    found, counts = [], {"tags": 0, "fact_lines": 0}
    checker.check_text(aid + ".md", text, found, counts)
    problems += [(n, why) for _, n, why in found if not why.startswith("no source tag")]
    for f in sensitive.blocking(sensitive.scan(text)):
        problems.append((f["line"], "%s must come out" % f["kind"]))
    return sorted(set(problems))


def verify(kb, directory=None, out=None):
    """{dir, files, tags, problems:[{file, line, problem}], missing:[area ids with no page], ok}."""
    kb = os.path.abspath(kb)
    tree = load_tree(kb, out)
    d = os.path.abspath(directory) if directory else os.path.join(folder_dir(kb, out), OUT)
    if not os.path.isdir(d):
        raise SummaryError("no summaries folder %s" % d)
    pages, checker = source_pages(kb), verify_kb.Checker(kb)
    files, probs, tags = [], [], 0
    for name in sorted(os.listdir(d)):
        if not name.endswith(".md"):
            continue
        aid = name[:-3]
        with open(os.path.join(d, name), encoding="utf-8", errors="replace") as fh:
            text = fh.read().replace("\r\n", "\n")
        files.append(aid)
        tags += len(verify_kb.TAG.findall(text))
        probs += [{"file": name, "line": n, "problem": why} for n, why in verify_text(kb, tree, aid, text, checker, pages)]
    missing = [a for a in order(tree) if a not in files]
    return {"dir": d, "files": files, "tags": tags, "problems": probs, "missing": missing, "ok": bool(files) and not probs}


# ---- stage ------------------------------------------------------------------------------------------
def with_front(tree, aid, text):
    meta, body = kb_gate.front(text)
    meta = dict(meta)
    meta.setdefault("type", SUMMARY_TYPE)
    meta.setdefault("area", aid)
    meta.setdefault("summarises", list(descendants(tree, aid)))
    return "---\n%s---\n%s" % (yaml.safe_dump(meta, sort_keys=False, allow_unicode=True, width=110), body.lstrip("\n"))


def stage(kb, by, directory=None, batch=None, out=None):
    """Verify the summaries and stage them in _PENDING/<batch>/summaries/. Raises SummaryError when any page fails: nothing is staged."""
    kb = os.path.abspath(kb)
    if not norm(by):
        raise SummaryError("say who is staging the summaries (--by)")
    rep = verify(kb, directory, out)
    if not rep["files"]:
        raise SummaryError("no summary pages in %s" % rep["dir"])
    if rep["problems"]:
        shown = "; ".join("%s:%s %s" % (p["file"], p["line"], p["problem"]) for p in rep["problems"][:5])
        raise SummaryError("%d problems; nothing was staged (first: %s)" % (len(rep["problems"]), shown))
    tree = load_tree(kb, out)
    name = kb_gate.new_batch(kb, batch or "area summaries")
    staged = []
    for aid in rep["files"]:
        with open(os.path.join(rep["dir"], aid + ".md"), encoding="utf-8", errors="replace") as fh:
            text = fh.read().replace("\r\n", "\n")
        rel = "%s/%s.md" % (SUMMARY_DIR, aid)
        kb_gate.stage_text(kb, name, rel, with_front(tree, aid, text))
        staged.append(rel)
    try:
        kb_gate.digest(kb, name)
    except kb_gate.GateError:
        pass
    return {"batch": name, "staged": staged, "by": norm(by), "locked": kb_gate.is_locked(kb)}


def status(kb, out=None):
    kb = os.path.abspath(kb)
    tree = load_tree(kb, out)
    pages = source_pages(kb)
    changed = []
    for a in tree["areas"].values():
        for p in a["page_info"]:
            if (sha(pages[p["path"]]) if p["path"] in pages else None) != p["sha"]:
                changed.append(p["path"])
    d = os.path.join(folder_dir(kb, out), OUT)
    have = sorted(n[:-3] for n in os.listdir(d) if n.endswith(".md")) if os.path.isdir(d) else []
    return {"areas": len(tree["areas"]), "pages": tree["pages"], "written": have, "missing": [a for a in order(tree) if a not in have],
            "pages_changed_since_build": sorted(set(changed)), "graph": tree.get("graph")}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("build")
    a.add_argument("kb")
    a.add_argument("--out")
    a = sub.add_parser("status")
    a.add_argument("kb")
    a.add_argument("--out")
    a = sub.add_parser("verify")
    a.add_argument("kb")
    a.add_argument("--dir")
    a.add_argument("--out")
    a = sub.add_parser("stage")
    a.add_argument("kb")
    a.add_argument("--by", required=True)
    a.add_argument("--dir")
    a.add_argument("--batch")
    a.add_argument("--out")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    kb = os.path.abspath(args.kb)
    if not os.path.isdir(kb):
        print("error: no KB folder %s" % kb, file=sys.stderr)
        return 2
    try:
        if args.cmd == "build":
            r = build(kb, args.out)
            print("%d areas over %d pages\ntree:   %s\nprompt: %s" % (r["areas"], r["pages"], r["tree"], r["prompt"]))
        elif args.cmd == "status":
            print(json.dumps(status(kb, args.out), indent=2))
        elif args.cmd == "verify":
            r = verify(kb, args.dir, args.out)
            for p in r["problems"][:100]:
                print("%s:%s: %s" % (p["file"], p["line"], p["problem"]))
            print("Checked %d summary pages, %d tags: %d problems. Areas without a page: %s" % (
                len(r["files"]), r["tags"], len(r["problems"]), ", ".join(r["missing"]) or "none"))
            return 0 if r["ok"] else 1
        else:
            r = stage(kb, args.by, args.dir, args.batch, args.out)
            print("staged %d pages in _PENDING/%s%s" % (len(r["staged"]), r["batch"],
                                                         "" if r["locked"] else " (the KB is not locked yet; they are still pending, not in the KB)"))
    except (SummaryError, kb_gate.GateError) as err:
        print("error: %s" % err, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
