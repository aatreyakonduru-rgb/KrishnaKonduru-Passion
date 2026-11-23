#!/usr/bin/env python3
"""Likes and dislikes on answers, and what happens to them.

    python3 feedback.py record  <kb> --answer FILE --question TEXT --by NAME --rating up
    python3 feedback.py record  <kb> --answer FILE --question TEXT --by NAME --rating down --why TEXT
                                     (--correct TEXT | --redirect TEXT)
    python3 feedback.py hints   <kb> "<question>"        approved directions for a question like this one
    python3 feedback.py list    <kb> [--status open]
    python3 feedback.py approve <kb> F-0001 --by LEAD [--note TEXT]
    python3 feedback.py decline <kb> F-0001 --by LEAD --reason TEXT
    python3 feedback.py resolve <kb> F-0001 --by NAME     the reporter says the redirected answer is now right

The register is <kb>/_FEEDBACK/FEEDBACK.yaml; each rated answer is kept beside it as _FEEDBACK/answers/F-0001.md.

A like is stored with the files the answer cited.

A dislike must say why the answer is wrong, and either what the right answer is (--correct) or where to look instead
(--redirect). Nothing else is accepted, so the path can be corrected:
  --correct   The claim is not a fact. It becomes a question in VALIDATE_KB for the role that owns the cited area, with the
              wrong answer's own sources as context. When a lead answers it, the next build writes the corrected line with
              [E: answer:Q-xxxx], and the lead certifies it like any other change. Mētis does not edit the KB from a dislike.
  --redirect  The person points Mētis at another place (a folder, page, table, or "look at the ETL, not the app"). The ask
              runs again with that direction at once. The direction is kept for this person's question only; it is shared
              for similar questions after a lead approves it (`hints` then returns it).

`approve` and `decline` are for leads named in the KB profile (see kb_gate.py). Approving a like or a redirect adds it to
the golden question set (golden.py), which is how changes to the KB are tested later.
"""
import argparse
import datetime
import os
import re
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kb_gate  # noqa: E402
import questions  # noqa: E402
import verify_kb  # noqa: E402

DIR = "_FEEDBACK"
STATUS = ("open", "approved", "declined", "resolved")
STOP = set("a an the of to in on for is are was were what which who how does do did and or by with from this that it as at be".split())


class FeedbackError(ValueError):
    pass


def reg_path(kb):
    return os.path.join(kb, DIR, "FEEDBACK.yaml")


def load(kb):
    p = reg_path(kb)
    if not os.path.isfile(p):
        return {"feedback": []}
    with open(p, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {"feedback": []}


def save(kb, reg):
    os.makedirs(os.path.dirname(reg_path(kb)), exist_ok=True)
    with open(reg_path(kb), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("# Likes and dislikes on Metis answers. Written by feedback.py; leads approve or decline each item.\n")
        yaml.safe_dump(reg, fh, sort_keys=False, allow_unicode=True, width=110)


def words(text):
    return {w for w in re.findall(r"[a-z0-9_]+", str(text).lower()) if w not in STOP and len(w) > 2}


def similar(a, b):
    wa, wb = words(a), words(b)
    return len(wa & wb) / max(1, min(len(wa), len(wb))) if wa and wb else 0.0


def cited(answer_text):
    """KB files and quotes an answer cites with [E: kb:...] tags."""
    files, quotes = [], []
    for kind, value in verify_kb.TAG.findall(answer_text):
        for part in value.split(";"):
            m = re.match(r'^\s*kb:([^:"\s]+)(?::\d+(?:-\d+)?)?(?:\s+"(.+)")?\s*$', part)
            if kind == "E" and m:
                if m.group(1) not in files:
                    files.append(m.group(1))
                if m.group(2):
                    quotes.append(m.group(2))
    return files, quotes


def question_type(files):
    top = (files[0].split("/")[0].lower() if files else "")
    return {"db": "data", "etl": "etl-batch", "modules": "application", "app": "application"}.get(top, "business")


def next_id(reg):
    nums = [int(f["id"][2:]) for f in reg["feedback"] if re.match(r"^F-\d+$", str(f.get("id")))]
    return "F-%04d" % (max(nums or [0]) + 1)


def raise_question(kb, item, answer_text):
    files, quotes = cited(answer_text)
    context = ['[E: kb:%s "%s"]' % (f, q) for f, q in zip(files, quotes + [None] * len(files)) if q][:5]
    context += ["[E: kb:%s]" % f for f in files if not any(("kb:%s " % f) in c for c in context)][:3]
    q = {"question": ("%s said the answer to \"%s\" is wrong because %s. They say the correct answer is: %s. Is that right, and "
                      "what is the source?") % (item["by"], item["question"], item["why"].rstrip("."), item["correct"].rstrip(".")),
         "type": question_type(files), "priority": "P2", "context": context, "blocks": files,
         "possible_answers": [], "raised_by_build": "feedback " + item["id"]}
    tmp = os.path.join(kb, DIR, "_new-question.yaml")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        yaml.safe_dump({"questions": [q]}, fh, sort_keys=False, allow_unicode=True)
    try:
        if questions.cmd_add(kb, tmp, "feedback " + item["id"]):
            raise FeedbackError("the question could not be added to VALIDATE_KB")
    finally:
        os.remove(tmp)
    for x in questions.load(questions.reg_path(kb)).get("questions") or []:
        if questions.norm(x.get("question")) == questions.norm(q["question"]) and questions.norm(x.get("blocks")) == questions.norm(files):
            return x["id"]
    return None

def record(kb, answer_file, question, by, rating, why=None, correct=None, redirect=None):
    by = " ".join(str(by or "").split())
    if not by:
        raise FeedbackError("say who is rating the answer")
    if rating not in ("up", "down"):
        raise FeedbackError("rating must be up or down")
    if not (question or "").strip():
        raise FeedbackError("give the question that was asked")
    if not os.path.isfile(answer_file):
        raise FeedbackError("no answer file: %s" % answer_file)
    if rating == "down":
        if not (why or "").strip():
            raise FeedbackError("a dislike needs the reason: what is wrong with the answer?")
        if bool((correct or "").strip()) == bool((redirect or "").strip()):
            raise FeedbackError("a dislike needs exactly one of: the correct answer, or where Metis should look instead")
    with open(answer_file, encoding="utf-8") as fh:
        text = fh.read()
    reg = load(kb)
    fid = next_id(reg)
    files, _ = cited(text)
    item = {"id": fid, "on": datetime.date.today().isoformat(), "by": by, "rating": rating, "question": question.strip(),
            "cited_files": files, "status": "open"}
    os.makedirs(os.path.join(kb, DIR, "answers"), exist_ok=True)
    with open(os.path.join(kb, DIR, "answers", fid + ".md"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    if rating == "down":
        item["why"] = why.strip()
        if (correct or "").strip():
            item["correct"] = correct.strip()
            item["action"] = "question"
            item["question_id"] = raise_question(kb, item, text)
        else:
            item["redirect"] = redirect.strip()
            item["action"] = "ask again with this direction"
    reg["feedback"].append(item)
    save(kb, reg)
    return item


def find(reg, fid):
    for f in reg["feedback"]:
        if f.get("id") == fid:
            return f
    raise FeedbackError("no feedback %s" % fid)


def approve(kb, fid, by, note=None):
    name, role = kb_gate.who(kb, by)
    reg = load(kb)
    f = find(reg, fid)
    if f["status"] not in ("open", "resolved"):
        raise FeedbackError("%s is already %s" % (fid, f["status"]))
    if f["rating"] == "down" and f.get("correct") and not f.get("question_id"):
        raise FeedbackError("%s has no question in VALIDATE_KB to answer" % fid)
    f.update(status="approved", decided_by=name, decided_role=role, decided_on=datetime.date.today().isoformat())
    if note:
        f["note"] = note.strip()
    save(kb, reg)
    return f


def decline(kb, fid, by, reason):
    name, role = kb_gate.who(kb, by)
    if not (reason or "").strip():
        raise FeedbackError("say why it is declined")
    reg = load(kb)
    f = find(reg, fid)
    f.update(status="declined", decided_by=name, decided_role=role, decided_on=datetime.date.today().isoformat(), note=reason.strip())
    save(kb, reg)
    return f


def resolve(kb, fid, by):
    reg = load(kb)
    f = find(reg, fid)
    if f.get("redirect") is None:
        raise FeedbackError("%s was not a redirect" % fid)
    if " ".join(by.split()).lower() != f["by"].lower():
        raise FeedbackError("only %s, who gave the direction, can say it worked" % f["by"])
    f["resolved_on"] = datetime.date.today().isoformat()
    if f["status"] == "open":
        f["status"] = "resolved"
    save(kb, reg)
    return f


def hints(kb, question, threshold=0.6):
    """Directions leads approved for questions like this one."""
    out = []
    for f in load(kb)["feedback"]:
        if f.get("status") == "approved" and f.get("redirect") and similar(question, f["question"]) >= threshold:
            out.append({"id": f["id"], "asked": f["question"], "direction": f["redirect"], "approved_by": f.get("decided_by")})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("record"); a.add_argument("kb"); a.add_argument("--answer", required=True); a.add_argument("--question", required=True)
    a.add_argument("--by", required=True); a.add_argument("--rating", required=True, choices=("up", "down"))
    a.add_argument("--why"); a.add_argument("--correct"); a.add_argument("--redirect")
    a = sub.add_parser("hints"); a.add_argument("kb"); a.add_argument("question")
    a = sub.add_parser("list"); a.add_argument("kb"); a.add_argument("--status", choices=STATUS)
    a = sub.add_parser("approve"); a.add_argument("kb"); a.add_argument("id"); a.add_argument("--by", required=True); a.add_argument("--note")
    a = sub.add_parser("decline"); a.add_argument("kb"); a.add_argument("id"); a.add_argument("--by", required=True); a.add_argument("--reason", required=True)
    a = sub.add_parser("resolve"); a.add_argument("kb"); a.add_argument("id"); a.add_argument("--by", required=True)
    args = ap.parse_args(argv)
    kb = os.path.abspath(args.kb)
    try:
        if args.cmd == "record":
            f = record(kb, args.answer, args.question, args.by, args.rating, args.why, args.correct, args.redirect)
            print("%s recorded (%s)%s" % (f["id"], f["rating"], "; question %s raised in VALIDATE_KB" % f["question_id"] if f.get("question_id") else
                                          "; ask again with: " + f["redirect"] if f.get("redirect") else ""))
        elif args.cmd == "hints":
            for h in hints(kb, args.question):
                print("%s: %s (approved by %s; first asked: %s)" % (h["id"], h["direction"], h["approved_by"], h["asked"]))
        elif args.cmd == "list":
            for f in load(kb)["feedback"]:
                if not args.status or f["status"] == args.status:
                    print("%s\t%s\t%s\t%s\t%s" % (f["id"], f["status"], f["rating"], f["by"], f["question"][:70]))
        elif args.cmd == "approve":
            print("%s approved by %s" % (args.id, approve(kb, args.id, args.by, args.note)["decided_by"]))
        elif args.cmd == "decline":
            print("%s declined by %s" % (args.id, decline(kb, args.id, args.by, args.reason)["decided_by"]))
        else:
            resolve(kb, args.id, args.by)
            print("%s resolved" % args.id)
    except (FeedbackError, kb_gate.GateError) as err:
        print("error: %s" % err, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
