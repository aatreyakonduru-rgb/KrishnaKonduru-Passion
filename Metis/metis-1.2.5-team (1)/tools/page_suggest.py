#!/usr/bin/env python3
"""Suggest an edit to a KB page, and comment on a page.

    python3 page_suggest.py suggest <kb> --page P --by NAME --wrong TEXT --proposed TEXT (--evidence '[E: ...]' | --look TEXT) [--line N]
    python3 page_suggest.py comment <kb> --page P --by NAME --text TEXT [--reply-to C-0001]
    python3 page_suggest.py list    <kb> [--status open] [--page P]
    python3 page_suggest.py thread  <kb> --page P
    python3 page_suggest.py inbox   <kb> --by LEAD              what this person may decide
    python3 page_suggest.py approve <kb> S-0001 --by LEAD (--question | --stage) [--note TEXT]
    python3 page_suggest.py decline <kb> S-0001 --by LEAD --reason TEXT
    python3 page_suggest.py answer  <kb> C-0001 --by LEAD --text TEXT

Any reader who gives a name can suggest a correction or comment on a page. A suggestion says which page, what is wrong, the
proposed text, and where the proposal comes from: exactly one of an [E: ...] tag (checked the way verify_kb checks it) or a
"where to look" hint. This is the same rule feedback.py applies to a dislike.

A lead (or the approver of the team that owns the page, see kb_gate.py) then:
  approve --question  the suggestion becomes a question in VALIDATE_KB. Answering it follows the normal path.
  approve --stage     the suggested line replaces the page's line in a new _PENDING batch (kb_gate), with a DIGEST. Needs a
                      closed gate, a line number, an [E:] tag, and the line unchanged since it was suggested. Certify it with
                      kb_gate.py as any other batch. The live page is never written by this tool.
  decline             closes it with a reason.

Comments are threaded per page and append-only: nothing is edited or deleted; a lead's `answer` is a new entry and marks the
comment answered. Everything is kept in <kb>/_FEEDBACK/suggestions.yaml.
"""
import argparse
import datetime
import os
import re
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import feedback  # noqa: E402
import kb_gate  # noqa: E402
import questions  # noqa: E402
import sensitive  # noqa: E402
import verify_kb  # noqa: E402

FILE = "suggestions.yaml"
STATUS = ("open", "approved", "declined")
MAX_TEXT = 2000
SKIP_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__"}
GROUPS_AT_END = re.compile(r"((?:\s*\{[^{}]*\})+)\s*$")
LIST_MARK = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")


class SuggestError(ValueError):
    pass


# ---- storage (same shape as feedback.py: one yaml register under _FEEDBACK) --------------------
def reg_path(kb):
    return os.path.join(kb, feedback.DIR, FILE)


def load(kb):
    p = reg_path(kb)
    reg = {}
    if os.path.isfile(p):
        with open(p, encoding="utf-8") as fh:
            reg = yaml.safe_load(fh) or {}
    reg.setdefault("suggestions", [])
    reg.setdefault("comments", [])
    return reg


def save(kb, reg):
    os.makedirs(os.path.dirname(reg_path(kb)), exist_ok=True)
    with open(reg_path(kb), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("# Suggested edits and page comments. Written by page_suggest.py; comments are append-only.\n")
        yaml.safe_dump(reg, fh, sort_keys=False, allow_unicode=True, width=110)


def next_id(items, prefix):
    nums = [int(i["id"][2:]) for i in items if re.match(r"^%s-\d+$" % prefix, str(i.get("id")))]
    return "%s-%04d" % (prefix, max(nums or [0]) + 1)


# ---- validation ---------------------------------------------------------------------------------
def who(by):
    name = kb_gate.clean(by)
    if not kb_gate.real(name):
        raise SuggestError("say who you are (your name) before suggesting or commenting")
    return name


def page_path(kb, page):
    rel = str(page or "").strip().replace("\\", "/").lstrip("/")
    if not rel:
        raise SuggestError("say which page")
    parts = rel.split("/")
    if ".." in parts or not rel.endswith(".md") or parts[0].startswith((".", "_")) or parts[0] in SKIP_DIRS:
        raise SuggestError("%s is not a KB page" % rel)
    if not os.path.isfile(os.path.join(kb, rel)):
        raise SuggestError("no such page: %s" % rel)
    return rel


def pages(kb):
    """KB pages a reader can pick, as KB-relative paths."""
    out = []
    for d, dirs, files in os.walk(kb):
        rel_d = os.path.relpath(d, kb).replace(os.sep, "/")
        dirs[:] = sorted(x for x in dirs if not x.startswith((".", "_")) and x not in SKIP_DIRS) if rel_d == "." else sorted(
            x for x in dirs if x not in SKIP_DIRS)
        for f in sorted(files):
            if f.endswith(".md"):
                out.append(f if rel_d == "." else rel_d + "/" + f)
    return out


def text_field(label, value):
    t = " ".join(str(value or "").split())
    if not t:
        raise SuggestError("%s is required" % label)
    if len(t) > MAX_TEXT:
        raise SuggestError("%s is too long (%d characters; the limit is %d)" % (label, len(t), MAX_TEXT))
    kinds = [f["kind"] for f in sensitive.scan(t) if f["level"] == sensitive.BLOCK]
    if kinds:
        raise SuggestError("%s looks like it contains %s; remove it, the register is kept in the KB" % (label, ", ".join(sorted(set(kinds)))))
    return t


def evidence_specs(text):
    """The source specs in an '[E: a; b]' string, or in a bare 'a; b' string."""
    text = str(text or "").strip()
    if not text:
        return []
    tags = verify_kb.TAG.findall(text)
    if tags:
        if any(kind != "E" for kind, _ in tags):
            raise SuggestError("a suggestion's source must be an [E: ...] tag")
        raw = [v for _, value in tags for v in value.split(";")]
    else:
        raw = text.split(";")
    return [" ".join(s.split()) for s in raw if s.strip()]


def check_evidence(kb, specs):
    checker = verify_kb.Checker(kb)
    for s in specs:
        why = checker.resolve("E", s)
        if why:
            raise SuggestError("source '%s' does not check out: %s" % (s, why))


def source_of(kb, evidence, look):
    specs = evidence_specs(evidence)
    hint = " ".join(str(look or "").split())
    if bool(specs) == bool(hint):
        raise SuggestError("give exactly one of: an [E: ...] source for the proposed text, or where to look instead")
    if specs:
        check_evidence(kb, specs)
        return {"evidence": specs}
    return {"look": text_field("where to look", hint)}


def page_line(kb, rel, line):
    with open(os.path.join(kb, rel), encoding="utf-8", errors="replace") as fh:
        lines = fh.read().splitlines()
    if not 1 <= line <= len(lines):
        raise SuggestError("%s has no line %d (it has %d)" % (rel, line, len(lines)))
    return lines[line - 1]


# ---- suggestions and comments ---------------------------------------------------------------------
def suggest(kb, page, by, wrong, proposed, evidence=None, look=None, line=None):
    by = who(by)
    rel = page_path(kb, page)
    item = {"id": None, "on": datetime.date.today().isoformat(), "by": by, "page": rel,
            "wrong": text_field("what is wrong", wrong), "proposed": text_field("the proposed text", proposed)}
    item.update(source_of(kb, evidence, look))
    if line not in (None, ""):
        try:
            n = int(line)
        except (TypeError, ValueError):
            raise SuggestError("the line must be a number")
        item["line"] = n
        item["line_text"] = page_line(kb, rel, n)
    item["status"] = "open"
    reg = load(kb)
    for s in reg["suggestions"]:
        if s["status"] == "open" and s["by"].lower() == by.lower() and s["page"] == rel and s["proposed"] == item["proposed"] \
                and s.get("line") == item.get("line"):
            raise SuggestError("you already suggested this on %s (%s)" % (rel, s["id"]))
    item["id"] = next_id(reg["suggestions"], "S")
    reg["suggestions"].append(item)
    save(kb, reg)
    return item


def comment(kb, page, by, text, reply_to=None):
    by = who(by)
    rel = page_path(kb, page)
    reg = load(kb)
    c = {"id": next_id(reg["comments"], "C"), "on": datetime.date.today().isoformat(), "by": by, "page": rel,
         "text": text_field("the comment", text), "kind": "comment"}
    if reply_to:
        parent = find_comment(reg, reply_to)
        if parent["page"] != rel:
            raise SuggestError("%s is on another page" % reply_to)
        c["reply_to"] = reply_to
    else:
        c["status"] = "open"
    reg["comments"].append(c)
    save(kb, reg)
    return c


def find_comment(reg, cid):
    for c in reg["comments"]:
        if c.get("id") == cid:
            return c
    raise SuggestError("no comment %s" % cid)


def find_suggestion(reg, sid):
    for s in reg["suggestions"]:
        if s.get("id") == sid:
            return s
    raise SuggestError("no suggestion %s" % sid)


def suggestions(kb, status=None, page=None):
    return [s for s in load(kb)["suggestions"] if (not status or s["status"] == status) and (not page or s["page"] == page)]


def contributor_record(kb, since=None):
    """{lowercase name: {name, suggested, approved, declined, open, approved_later_disliked, disliked_pages}}: facts about what each
    person's suggestions came to. `approved_later_disliked` counts approved suggestions whose page was cited in an answer that
    someone disliked on or after the day the suggestion was approved (a lead declining that dislike removes it). It names the
    answer, not the contributor: read it as "look first", not as a verdict. `since` (YYYY-MM-DD) leaves out older suggestions.
    No score: the lead reads the counts."""
    downs = {}
    try:
        for f in feedback.load(kb).get("feedback") or []:
            if f.get("rating") == "down" and f.get("status") != "declined":
                for rel in f.get("cited_files") or []:
                    downs.setdefault(rel, []).append(str(f.get("on") or ""))
    except Exception:
        downs = {}
    out = {}
    for s in load(kb)["suggestions"]:
        if since and str(s.get("on") or "") < since:
            continue
        r = out.setdefault(s["by"].lower(), {"name": s["by"], "suggested": 0, "approved": 0, "declined": 0, "open": 0,
                                             "approved_later_disliked": 0, "disliked_pages": []})
        r["suggested"] += 1
        status = s.get("status")
        if status == "approved":
            r["approved"] += 1
            decided = str(s.get("decided_on") or "")
            if any(d and d >= decided for d in downs.get(s["page"], [])):
                r["approved_later_disliked"] += 1
                if s["page"] not in r["disliked_pages"]:
                    r["disliked_pages"].append(s["page"])
        elif status == "declined":
            r["declined"] += 1
        else:
            r["open"] += 1
    return out


def contributor_line(kb, name, since=None):
    """One plain sentence of facts about a contributor, for the lead to read beside a suggestion."""
    r = contributor_record(kb, since).get(kb_gate.clean(name).lower())
    if not r:
        return "%s: no earlier suggestions" % kb_gate.clean(name)
    return "%s: %d suggested; %d approved, %d declined, %d open; %d approved on a page disliked afterwards" % (
        r["name"], r["suggested"], r["approved"], r["declined"], r["open"], r["approved_later_disliked"])


def thread(kb, page):
    """Every comment on a page, oldest first (replies carry reply_to)."""
    return [c for c in load(kb)["comments"] if c["page"] == page]


# ---- who decides --------------------------------------------------------------------------------------
def deciders(kb, page):
    """{lowercase name: (name, role)}: the leads plus the approvers of the team that owns the page."""
    pool = kb_gate.pool_for(kb, page)[1]
    if not pool:
        raise kb_gate.GateError("no lead is named in %s; name them first" % os.path.join(".metis", "kb-profile.yaml"))
    return pool


def decider(kb, by, page):
    pool = deciders(kb, page)
    hit = pool.get(kb_gate.clean(by).lower())
    if not hit:
        raise kb_gate.GateError("%s may not decide on %s (allowed: %s)" % (kb_gate.clean(by) or "(no name)", page,
                                                                           ", ".join(v[0] for v in pool.values())))
    return hit


def can_decide(kb, by, page):
    try:
        decider(kb, by, page)
        return True
    except kb_gate.GateError:
        return False


def inbox(kb, by):
    """(open suggestions, unanswered comments) this person may decide."""
    reg = load(kb)
    sug = [s for s in reg["suggestions"] if s["status"] == "open" and can_decide(kb, by, s["page"])]
    com = [c for c in reg["comments"] if c.get("status") == "open" and can_decide(kb, by, c["page"])]
    return sug, com


# ---- decisions ------------------------------------------------------------------------------------------
def quote_of(line_text):
    head = re.split(r'[\[\]{};"]', line_text or "")[0].strip()
    return head[:70].strip()


def question_text(s):
    where = "%s line %d" % (s["page"], s["line"]) if s.get("line") else s["page"]
    src = "Their source: %s." % "; ".join(s["evidence"]) if s.get("evidence") else "They suggest looking at: %s." % s["look"]
    return ("%s says %s is wrong: %s They propose: %s %s Is that right, and what is the source?"
            % (s["by"], where, s["wrong"].rstrip(".") + ".", s["proposed"].rstrip(".") + ".", src))


def approve_as_question(kb, s, by, qtype=None, priority="P2"):
    qtype = qtype or feedback.question_type([s["page"]])
    q = quote_of(s.get("line_text"))
    ctx = ['[E: kb:%s:%d "%s"]' % (s["page"], s["line"], q) if s.get("line") and q else "[E: kb:%s]" % s["page"]]
    ctx += ["[E: %s]" % e for e in s.get("evidence") or []]
    try:
        qid, _ = questions.cmd_raise(kb, question_text(s), qtype, by, priority, blocks=[s["page"]], context=ctx)
    except ValueError as err:
        raise SuggestError(str(err))
    if not qid:
        raise SuggestError("the question could not be added to VALIDATE_KB")
    return {"action": "question", "question_id": qid}


def new_line(s, original):
    if original.lstrip().startswith(("#", "|")):
        raise SuggestError("line %d is a heading or table row; approve it as a question and edit it by hand" % s["line"])
    body = " ".join(re.sub(r"\[E:[^\]]*\]", " ", s["proposed"]).split())
    if not LIST_MARK.match(body):
        body = re.match(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)?", original).group(0) + body
    groups = GROUPS_AT_END.search(original)
    return "%s [E: %s]%s" % (body, "; ".join(s["evidence"]), (" " + groups.group(1).strip()) if groups else "")


def approve_as_stage(kb, s, by):
    if not kb_gate.is_locked(kb):
        raise SuggestError("the gate is not closed, so there is nothing to stage into; approve it as a question, or edit the page directly")
    if not s.get("line"):
        raise SuggestError("%s has no line number; approve it as a question instead" % s["id"])
    if not s.get("evidence"):
        raise SuggestError("%s only says where to look; approve it as a question instead" % s["id"])
    with open(os.path.join(kb, s["page"]), encoding="utf-8", errors="replace", newline="") as fh:
        raw = fh.read().splitlines(keepends=True)
    n = s["line"]
    if n > len(raw):
        raise SuggestError("%s no longer has line %d" % (s["page"], n))
    original = raw[n - 1].rstrip("\r\n")
    if original != s["line_text"]:
        raise SuggestError("line %d of %s has changed since it was suggested; ask for a fresh suggestion" % (n, s["page"]))
    replacement = new_line(s, original)
    raw[n - 1] = replacement + raw[n - 1][len(original):]
    text = "".join(raw)
    probs = [(m, why) for _, m, why in kb_gate.source_problems(kb, s["page"], text)[0] if m == n]
    if probs:
        raise SuggestError("the new line does not check out: %s" % probs[0][1])
    blocked = [f["kind"] for f in kb_gate.findings(s["page"], text) if f["line"] == n and f["level"] == sensitive.BLOCK]
    if blocked:
        raise SuggestError("the new line looks like it contains %s" % ", ".join(sorted(set(blocked))))
    batch = kb_gate.new_batch(kb, "suggest-" + s["id"].lower())
    kb_gate.stage_text(kb, batch, s["page"], text)
    kb_gate.digest(kb, batch)
    return {"action": "stage", "batch": batch}


def approve(kb, sid, by, how="question", note=None, qtype=None, priority="P2"):
    reg = load(kb)
    s = find_suggestion(reg, sid)
    name, role = decider(kb, by, s["page"])
    if s["status"] != "open":
        raise SuggestError("%s is already %s" % (sid, s["status"]))
    if how == "question":
        res = approve_as_question(kb, s, name, qtype, priority)
    elif how == "stage":
        res = approve_as_stage(kb, s, name)
    else:
        raise SuggestError("approve as 'question' or 'stage'")
    reg = load(kb)
    s = find_suggestion(reg, sid)
    s.update(res, status="approved", decided_by=name, decided_role=role, decided_on=datetime.date.today().isoformat())
    if (note or "").strip():
        s["note"] = note.strip()
    save(kb, reg)
    return s


def decline(kb, sid, by, reason):
    reg = load(kb)
    s = find_suggestion(reg, sid)
    name, role = decider(kb, by, s["page"])
    if not (reason or "").strip():
        raise SuggestError("say why it is declined")
    if s["status"] != "open":
        raise SuggestError("%s is already %s" % (sid, s["status"]))
    s.update(status="declined", decided_by=name, decided_role=role, decided_on=datetime.date.today().isoformat(),
             note=text_field("the reason", reason))
    save(kb, reg)
    return s


def answer(kb, cid, by, text):
    reg = load(kb)
    parent = find_comment(reg, cid)
    name, role = decider(kb, by, parent["page"])
    reply = {"id": next_id(reg["comments"], "C"), "on": datetime.date.today().isoformat(), "by": name, "page": parent["page"],
             "text": text_field("the answer", text), "kind": "answer", "reply_to": cid}
    reg["comments"].append(reply)
    if parent.get("status") == "open":
        parent.update(status="answered", answered_by=name, answered_on=reply["on"])
    save(kb, reg)
    return reply


# ---- CLI ------------------------------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("suggest"); a.add_argument("kb"); a.add_argument("--page", required=True); a.add_argument("--by", required=True)
    a.add_argument("--wrong", required=True); a.add_argument("--proposed", required=True); a.add_argument("--evidence")
    a.add_argument("--look"); a.add_argument("--line")
    a = sub.add_parser("comment"); a.add_argument("kb"); a.add_argument("--page", required=True); a.add_argument("--by", required=True)
    a.add_argument("--text", required=True); a.add_argument("--reply-to")
    a = sub.add_parser("list"); a.add_argument("kb"); a.add_argument("--status", choices=STATUS); a.add_argument("--page")
    a = sub.add_parser("thread"); a.add_argument("kb"); a.add_argument("--page", required=True)
    a = sub.add_parser("inbox"); a.add_argument("kb"); a.add_argument("--by", required=True)
    a = sub.add_parser("approve"); a.add_argument("kb"); a.add_argument("id"); a.add_argument("--by", required=True)
    g = a.add_mutually_exclusive_group(required=True); g.add_argument("--question", action="store_true"); g.add_argument("--stage", action="store_true")
    a.add_argument("--note")
    a = sub.add_parser("decline"); a.add_argument("kb"); a.add_argument("id"); a.add_argument("--by", required=True); a.add_argument("--reason", required=True)
    a = sub.add_parser("answer"); a.add_argument("kb"); a.add_argument("id"); a.add_argument("--by", required=True); a.add_argument("--text", required=True)
    args = ap.parse_args(argv)
    kb = os.path.abspath(args.kb)
    try:
        if args.cmd == "suggest":
            s = suggest(kb, args.page, args.by, args.wrong, args.proposed, args.evidence, args.look, args.line)
            print("%s recorded on %s" % (s["id"], s["page"]))
        elif args.cmd == "comment":
            print("%s recorded on %s" % (comment(kb, args.page, args.by, args.text, args.reply_to)["id"], args.page))
        elif args.cmd == "list":
            for s in suggestions(kb, args.status, args.page):
                print("%s\t%s\t%s\t%s\t%s" % (s["id"], s["status"], s["by"], s["page"], s["proposed"][:60]))
        elif args.cmd == "thread":
            for c in thread(kb, args.page):
                print("%s\t%s\t%s\t%s%s" % (c["id"], c["on"], c["by"], c["text"], "  (reply to %s)" % c["reply_to"] if c.get("reply_to") else ""))
        elif args.cmd == "inbox":
            sug, com = inbox(kb, args.by)
            for s in sug:
                print("%s\tsuggestion\t%s\t%s" % (s["id"], s["page"], s["proposed"][:60]))
            for c in com:
                print("%s\tcomment\t%s\t%s" % (c["id"], c["page"], c["text"][:60]))
        elif args.cmd == "approve":
            s = approve(kb, args.id, args.by, "question" if args.question else "stage", args.note)
            print("%s approved by %s; %s" % (args.id, s["decided_by"], ("question %s raised in VALIDATE_KB" % s["question_id"]) if s["action"] == "question"
                                              else "staged in _PENDING/%s for certification" % s["batch"]))
        elif args.cmd == "decline":
            print("%s declined by %s" % (args.id, decline(kb, args.id, args.by, args.reason)["decided_by"]))
        else:
            print("%s answered by %s" % (args.id, answer(kb, args.id, args.by, args.text)["by"]))
    except (SuggestError, kb_gate.GateError) as err:
        print("error: %s" % err, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
