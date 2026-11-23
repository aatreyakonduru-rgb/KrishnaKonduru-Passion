#!/usr/bin/env python3
"""Keep the Metis question register: every open question a build raises, who can answer it, and the answers.

    python3 questions.py add    <kb> <new-questions.yaml>   merge a build's questions into the register
    python3 questions.py answer <kb> <answers.yaml|json>     record answers (id, answer, answered_by)
    python3 questions.py html   <kb> [-o file]              write VALIDATE_KB.html (grouped by role and type)
    python3 questions.py check  <kb>                        validate the register
    python3 questions.py raise  <kb> "<question>" --type T --by NAME [--priority P2] [--blocks FILE ...] [--context "[E: ...]" ...]
                                                            add one question in one step (a gap found while answering)
    python3 questions.py sheet  <kb> [--role ROLE] [-o file]  an answer sheet in plain text: open questions for one role,
                                                            most urgent first, with a blank line for each answer

The register is <kb>/_QUESTIONS/VALIDATE_KB.yaml. A question has:
  id, question, type, priority, answer_role, context (source-tagged lines), blocks (KB files or lines),
  possible_answers (each with a source tag; empty means none found in sources), status,
  answer, answered_by, answered_on, raised_on, raised_by_build.
The answer role comes from the type through `questions.role_for_type` in the settings; people come
from `owners.roles`. Possible answers are only options a source gives; Metis never proposes one.
"""
import argparse
import datetime
import html
import json
import os
import re
import sys

import yaml

TYPES = ("business", "application", "data", "etl-batch", "access", "security")
PRIORITIES = ("P1", "P2", "P3")
STATUSES = ("open", "answered", "closed")
DEFAULT_ROLE_FOR_TYPE = {"business": "product owner", "application": "dev lead", "data": "data lead",
                         "etl-batch": "etl lead", "access": "manager", "security": "security lead"}
TAG = re.compile(r"\[E:\s*[^\]]+\]")


def reg_path(kb):
    return os.path.join(kb, "_QUESTIONS", "VALIDATE_KB.yaml")


def load(path):
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    return (json.loads(text) if path.endswith(".json") else yaml.safe_load(text)) or {}


def settings(kb):
    return load(os.path.join(kb, ".metis", "kb-profile.yaml"))


def role_for(kb, qtype):
    table = dict(DEFAULT_ROLE_FOR_TYPE)
    table.update(((settings(kb).get("questions") or {}).get("role_for_type")) or {})
    return table.get(qtype)


def people(kb):
    return ((settings(kb).get("owners") or {}).get("roles")) or {}


def save(kb, reg):
    os.makedirs(os.path.dirname(reg_path(kb)), exist_ok=True)
    with open(reg_path(kb), "w", encoding="utf-8") as fh:
        fh.write("# Metis VALIDATE_KB: open questions for the team. Answer in the answer fields (answer, answered_by), or through `questions.py answer`.\n")
        yaml.safe_dump(reg, fh, sort_keys=False, allow_unicode=True, width=110)


def problems(kb, reg):
    out, seen = [], set()
    for q in reg.get("questions") or []:
        qid = q.get("id", "?")
        if qid in seen:
            out.append("%s: duplicate id" % qid)
        seen.add(qid)
        if not re.match(r"^Q-\d{4,}$", str(qid)):
            out.append("%s: id must look like Q-0001" % qid)
        for f in ("question", "type", "priority", "answer_role", "status"):
            if not q.get(f):
                out.append("%s: missing %s" % (qid, f))
        if q.get("type") not in TYPES:
            out.append("%s: type must be one of %s" % (qid, ", ".join(TYPES)))
        if q.get("priority") not in PRIORITIES:
            out.append("%s: priority must be P1, P2 or P3" % qid)
        if q.get("status") not in STATUSES:
            out.append("%s: status must be open, answered or closed" % qid)
        for line in q.get("context") or []:
            if not TAG.search(str(line)):
                out.append("%s: context line has no [E: source] tag: %s" % (qid, str(line)[:60]))
        for opt in q.get("possible_answers") or []:
            if not TAG.search(str(opt)):
                out.append("%s: possible answer has no [E: source] tag: %s" % (qid, str(opt)[:60]))
        if q.get("status") in ("answered", "closed") and not (q.get("answer") and q.get("answered_by")):
            out.append("%s: answered without answer and answered_by" % qid)
    return out


def norm(text):
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def cmd_add(kb, new_file, build=None):
    reg = load(reg_path(kb)) or {"questions": []}
    qs = reg.setdefault("questions", [])
    index = {(norm(q.get("question")), norm(q.get("blocks"))): q for q in qs}
    nums = [int(q["id"][2:]) for q in qs if re.match(r"^Q-\d+$", str(q.get("id")))]
    nxt = max(nums or [0]) + 1
    added = 0
    incoming = load(new_file)
    incoming = incoming.get("questions", incoming) if isinstance(incoming, dict) else incoming
    today = datetime.date.today().isoformat()
    for item in incoming or []:
        key = (norm(item.get("question")), norm(item.get("blocks")))
        if key in index:
            continue
        q = {"id": "Q-%04d" % nxt, "question": item.get("question"), "type": item.get("type"),
             "priority": item.get("priority"), "answer_role": item.get("answer_role") or role_for(kb, item.get("type")),
             "context": item.get("context") or [], "blocks": item.get("blocks") or [],
             "possible_answers": item.get("possible_answers") or [], "status": "open",
             "answer": None, "answered_by": None, "answered_on": None,
             "raised_on": today, "raised_by_build": build or item.get("raised_by_build")}
        qs.append(q)
        index[key] = q
        nxt += 1
        added += 1
    bad = problems(kb, reg)
    if bad:
        print("\n".join(bad))
        return 1
    save(kb, reg)
    print("Added %d questions; %d in the register." % (added, len(qs)))
    return 0


def cmd_answer(kb, answers_file):
    reg = load(reg_path(kb))
    by_id = {q["id"]: q for q in reg.get("questions") or []}
    data = load(answers_file)
    data = data.get("answers", data) if isinstance(data, dict) else data
    done = 0
    for a in data or []:
        q = by_id.get(a.get("id"))
        if not q:
            print("unknown question %s" % a.get("id"))
            return 1
        if not (a.get("answer") and a.get("answered_by")):
            print("%s: an answer needs both answer and answered_by" % a.get("id"))
            return 1
        q.update(answer=a["answer"], answered_by=a["answered_by"], status=a.get("status", "answered"),
                 answered_on=a.get("answered_on") or datetime.date.today().isoformat())
        done += 1
    save(kb, reg)
    print("Recorded %d answers." % done)
    return 0


def esc(x):
    return html.escape(str(x if x is not None else ""))


def cmd_html(kb, out=None):
    reg = load(reg_path(kb))
    qs = reg.get("questions") or []
    who = people(kb)
    rows = []
    for q in sorted(qs, key=lambda q: (q.get("answer_role") or "", q.get("priority"), q.get("id"))):
        opts = q.get("possible_answers") or []
        rows.append(
            '<tr data-role="%s" data-type="%s" data-pri="%s" data-status="%s"><td>%s</td><td><b>%s</b></td>'
            "<td>%s</td><td>%s<br><small>%s</small></td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
            % (esc(q.get("answer_role")), esc(q.get("type")), esc(q.get("priority")), esc(q.get("status")),
               esc(q.get("id")), esc(q.get("priority")), esc(q.get("question")), esc(q.get("answer_role")),
               esc(who.get(q.get("answer_role"), "not named in settings")), esc(q.get("type")),
               "<br>".join(esc(c) for c in q.get("context") or []),
               "<br>".join(esc(o) for o in opts) if opts else "None found in sources",
               "<br>".join(esc(b) for b in (q.get("blocks") if isinstance(q.get("blocks"), list) else [q.get("blocks")]) if b),
               esc(q.get("status")) + ("<br>%s (%s, %s)" % (esc(q.get("answer")), esc(q.get("answered_by")),
                                                            esc(q.get("answered_on"))) if q.get("answer") else "")))
    def options(field, values):
        return "".join('<option value="%s">%s</option>' % (esc(v), esc(v)) for v in values)
    roles = sorted({q.get("answer_role") for q in qs if q.get("answer_role")})
    page = """<!doctype html><html><head><meta charset="utf-8"><title>Metis open questions</title>
<style>body{font:14px/1.45 system-ui,Segoe UI,Arial;margin:0;color:#1d1530}header{background:#4b2a7b;color:#fff;padding:8px 16px}
main{padding:12px 16px}table{border-collapse:collapse;width:100%%}td,th{border:1px solid #ddd3ec;padding:6px;vertical-align:top;text-align:left}
th{background:#f2edf9}select{margin-right:10px}small{color:#5c4d75}</style></head><body>
<header>Metis &middot; Open questions &middot; as of %s</header><main>
<p>Each question names what the sources say, what it blocks and who can answer it. Possible answers come only from sources.</p>
<p>Role <select id="role"><option value="">All</option>%s</select>Type <select id="type"><option value="">All</option>%s</select>
Priority <select id="pri"><option value="">All</option>%s</select>Status <select id="status"><option value="">All</option>%s</select></p>
<table><thead><tr><th>Id</th><th>Priority</th><th>Question</th><th>Who can answer</th><th>Type</th><th>What the sources say</th>
<th>Possible answers</th><th>Blocks</th><th>Status</th></tr></thead><tbody>%s</tbody></table></main>
<script>var f=["role","type","pri","status"];function go(){document.querySelectorAll("tbody tr").forEach(function(r){
r.style.display=f.every(function(k){var v=document.getElementById(k).value;return !v||r.dataset[k]===v})?"":"none"})}
f.forEach(function(k){document.getElementById(k).onchange=go})</script></body></html>""" % (
        datetime.date.today().isoformat(), options("role", roles), options("type", TYPES), options("pri", PRIORITIES),
        options("status", STATUSES), "\n".join(rows))
    out = out or os.path.join(kb, "_QUESTIONS", "VALIDATE_KB.html")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(page)
    print("Wrote %s (%d questions)." % (out, len(qs)))
    return 0


def cmd_raise(kb, question, qtype, by, priority="P2", blocks=None, context=None):
    """One question straight into the register. Returns (id, added). A question already open with the same words is reused."""
    if qtype not in TYPES:
        raise ValueError("type must be one of %s" % ", ".join(TYPES))
    if priority not in PRIORITIES:
        raise ValueError("priority must be P1, P2 or P3")
    if not (question or "").strip() or not (by or "").strip():
        raise ValueError("a question needs its text and who is raising it")
    item = {"question": question.strip(), "type": qtype, "priority": priority, "blocks": list(blocks or []),
            "context": list(context or []), "possible_answers": [], "raised_by_build": "asked by " + by.strip()}
    tmp = os.path.join(kb, "_QUESTIONS", "_new.yaml")
    os.makedirs(os.path.dirname(tmp), exist_ok=True)
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        yaml.safe_dump({"questions": [item]}, fh, sort_keys=False, allow_unicode=True)
    try:
        if cmd_add(kb, tmp, "asked by " + by.strip()):
            raise ValueError("the question was not accepted; see above")
    finally:
        os.remove(tmp)
    for q in load(reg_path(kb)).get("questions") or []:
        if norm(q.get("question")) == norm(item["question"]) and norm(q.get("blocks")) == norm(item["blocks"]):
            return q["id"], q.get("raised_by_build") == "asked by " + by.strip() and q.get("status") == "open"
    return None, False


def cmd_sheet(kb, role=None, out=None):
    """Plain-text answer sheet: a person reads it in chat and answers by id. Written for people, not for a table viewer."""
    reg = load(reg_path(kb))
    who = people(kb)
    rows = [q for q in reg.get("questions") or [] if q.get("status") == "open" and (not role or q.get("answer_role") == role)]
    rows.sort(key=lambda q: (q.get("answer_role") or "", q.get("priority") or "", q.get("id")))
    lines = ["# Open questions%s" % (" for the %s" % role if role else ""), "",
             "%d open. Answer by id, for example: Q-0001: the answer, and where it comes from. Say \"skip\" to leave one." % len(rows), ""]
    current = None
    for q in rows:
        if q.get("answer_role") != current:
            current = q.get("answer_role")
            lines += ["## %s (%s)" % (current, who.get(current) or "not named in the settings"), ""]
        lines += ["### %s (%s, %s)" % (q["id"], q.get("priority"), q.get("type")), q.get("question") or "", ""]
        for c in q.get("context") or []:
            lines.append("- Sources say: %s" % c)
        for o in q.get("possible_answers") or []:
            lines.append("- A source offers: %s" % o)
        if q.get("blocks"):
            lines.append("- Blocks: %s" % ", ".join(q["blocks"] if isinstance(q["blocks"], list) else [q["blocks"]]))
        lines += ["- Your answer: ", ""]
    text = "\n".join(lines) + "\n"
    if out:
        with open(out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    return text, len(rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("raise"); e.add_argument("kb"); e.add_argument("question"); e.add_argument("--type", required=True)
    e.add_argument("--by", required=True); e.add_argument("--priority", default="P2")
    e.add_argument("--blocks", nargs="*", default=[]); e.add_argument("--context", nargs="*", default=[])
    s = sub.add_parser("sheet"); s.add_argument("kb"); s.add_argument("--role"); s.add_argument("-o")
    a = sub.add_parser("add"); a.add_argument("kb"); a.add_argument("file"); a.add_argument("--build")
    b = sub.add_parser("answer"); b.add_argument("kb"); b.add_argument("file")
    c = sub.add_parser("html"); c.add_argument("kb"); c.add_argument("-o")
    d = sub.add_parser("check"); d.add_argument("kb")
    args = ap.parse_args(argv)
    if args.cmd == "add":
        return cmd_add(args.kb, args.file, args.build)
    if args.cmd == "answer":
        return cmd_answer(args.kb, args.file)
    if args.cmd == "html":
        return cmd_html(args.kb, args.o)
    if args.cmd == "raise":
        try:
            qid, _ = cmd_raise(args.kb, args.question, args.type, args.by, args.priority, args.blocks, args.context)
        except ValueError as err:
            print("error: %s" % err, file=sys.stderr)
            return 2
        print("Question %s is in the register." % qid)
        return 0
    if args.cmd == "sheet":
        text, n = cmd_sheet(args.kb, args.role, args.o)
        print(text if not args.o else "Wrote %s (%d open questions)." % (args.o, n))
        return 0
    bad = problems(args.kb, load(reg_path(args.kb)))
    print("\n".join(bad) or "Register is valid.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
