#!/usr/bin/env python3
"""The golden question set: questions the KB must keep answering well, and a way to test that after every change.

    python3 golden.py add     <kb> --question TEXT --cite REL [REL ...] [--include TEXT ...] --by LEAD [--kind competency]
    python3 golden.py promote <kb> F-0001 --by LEAD [--cite REL ...] [--include TEXT ...]
                                  make an approved like or redirect from feedback.py a golden question
    python3 golden.py list    <kb>
    python3 golden.py static  <kb>                   cheap check, no model: every KB file a golden question relies on still exists
    python3 golden.py score   <kb> <answers dir>     score answers written as <answers dir>/G-0001.md (one per question)

Each question names the KB files a good answer must cite (`cite`) and words it must contain (`include`). `static` is run
with every build and every certification; `score` is run after Metis re-asks the questions (it writes the answers, this
tool never calls a model). A competency question is one a lead lists at the start: what the KB must be able to answer for
the team to call it useful. The set is <kb>/_FEEDBACK/GOLDEN.yaml. Only leads add to it.
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
import verify_kb  # noqa: E402


class GoldenError(ValueError):
    pass


def path(kb):
    return os.path.join(kb, feedback.DIR, "GOLDEN.yaml")


def load(kb):
    if not os.path.isfile(path(kb)):
        return {"golden": []}
    with open(path(kb), encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {"golden": []}


def save(kb, data):
    os.makedirs(os.path.dirname(path(kb)), exist_ok=True)
    with open(path(kb), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("# Golden questions: what the KB must keep answering. Written by golden.py; only leads add to it.\n")
        yaml.safe_dump(data, fh, sort_keys=False, allow_unicode=True, width=110)


def add(kb, question, cite, include, by, kind="golden", source=None):
    name, role = kb_gate.who(kb, by)
    if not (question or "").strip():
        raise GoldenError("give the question")
    if not cite:
        raise GoldenError("name the KB files a good answer cites (--cite)")
    missing = [c for c in cite if not os.path.isfile(os.path.join(kb, c))]
    if missing:
        raise GoldenError("not in the KB: %s" % ", ".join(missing))
    data = load(kb)
    if any(feedback.similar(question, g["question"]) >= 0.95 for g in data["golden"]):
        raise GoldenError("a question like this is already in the set")
    nums = [int(g["id"][2:]) for g in data["golden"] if re.match(r"^G-\d+$", str(g.get("id")))]
    g = {"id": "G-%04d" % (max(nums or [0]) + 1), "question": question.strip(), "cite": list(cite), "include": list(include or []),
         "kind": kind, "added_by": name, "role": role, "added_on": datetime.date.today().isoformat()}
    if source:
        g["from_feedback"] = source
    data["golden"].append(g)
    save(kb, data)
    return g


def promote(kb, fid, by, cite=None, include=None):
    kb_gate.who(kb, by)
    f = feedback.find(feedback.load(kb), fid)
    if f["status"] != "approved":
        raise GoldenError("%s has not been approved by a lead" % fid)
    if f["rating"] == "down" and not f.get("redirect"):
        raise GoldenError("a dislike with a correct answer becomes golden once the question it raised is answered and the "
                          "KB line is certified; add it with `add` then")
    cite = cite or f.get("cited_files") or []
    return add(kb, f["question"], cite, include, by, "feedback", fid)


def static(kb):
    out = []
    for g in load(kb)["golden"]:
        for c in g["cite"]:
            if not os.path.isfile(os.path.join(kb, c)):
                out.append("%s: relies on %s, which is not in the KB" % (g["id"], c))
    return out


def score(kb, answers):
    chk = verify_kb.Checker(kb)
    rows = []
    for g in load(kb)["golden"]:
        p = os.path.join(answers, g["id"] + ".md")
        if not os.path.isfile(p):
            rows.append({"id": g["id"], "result": "missing", "why": ["no answer file"]})
            continue
        with open(p, encoding="utf-8") as fh:
            text = fh.read()
        files, _ = feedback.cited(text)
        why = ["does not cite %s" % c for c in g["cite"] if c not in files]
        why += ["does not say '%s'" % w for w in g.get("include") or [] if w.lower() not in text.lower()]
        rep = chk.check_answer(p)
        if rep["problems"]:
            why.append("%d source problems" % len(rep["problems"]))
        rows.append({"id": g["id"], "result": "fail" if why else "pass", "why": why})
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add"); a.add_argument("kb"); a.add_argument("--question", required=True); a.add_argument("--cite", nargs="+", required=True)
    a.add_argument("--include", nargs="*", default=[]); a.add_argument("--by", required=True); a.add_argument("--kind", default="golden", choices=("golden", "competency"))
    a = sub.add_parser("promote"); a.add_argument("kb"); a.add_argument("id"); a.add_argument("--by", required=True)
    a.add_argument("--cite", nargs="*"); a.add_argument("--include", nargs="*")
    a = sub.add_parser("list"); a.add_argument("kb")
    a = sub.add_parser("static"); a.add_argument("kb")
    a = sub.add_parser("score"); a.add_argument("kb"); a.add_argument("answers")
    args = ap.parse_args(argv)
    kb = os.path.abspath(args.kb)
    try:
        if args.cmd == "add":
            print("%s added" % add(kb, args.question, args.cite, args.include, args.by, args.kind)["id"])
        elif args.cmd == "promote":
            print("%s added" % promote(kb, args.id, args.by, args.cite, args.include)["id"])
        elif args.cmd == "list":
            for g in load(kb)["golden"]:
                print("%s\t%s\t%s" % (g["id"], g["kind"], g["question"][:90]))
        elif args.cmd == "static":
            bad = static(kb)
            print("\n".join(bad))
            print("golden: %d questions, %d problems" % (len(load(kb)["golden"]), len(bad)))
            return 1 if bad else 0
        else:
            rows = score(kb, args.answers)
            for r in rows:
                print("%s %s %s" % (r["id"], r["result"], "; ".join(r["why"])))
            print("golden: %d of %d pass" % (sum(r["result"] == "pass" for r in rows), len(rows)))
            return 0 if all(r["result"] == "pass" for r in rows) else 1
    except (GoldenError, feedback.FeedbackError, kb_gate.GateError) as err:
        print("error: %s" % err, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
