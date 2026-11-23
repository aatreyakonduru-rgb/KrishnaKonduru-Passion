#!/usr/bin/env python3
"""The Devin task queue: how the UI hands a model step to a Devin session and gets the result back.

    python3 tasks.py list     <kb> [--status queued]
    python3 tasks.py show     <kb> T-0001              the instructions for one task
    python3 tasks.py claim    <kb> [T-0001] --by NAME   take the oldest queued task (or the one named); prints its instructions
    python3 tasks.py complete <kb> T-0001 --by NAME [--file RESULT.md] [--note TEXT]
    python3 tasks.py fail     <kb> T-0001 --by NAME --note TEXT
    python3 tasks.py ask-user <kb> T-0001 --by NAME --question TEXT [--question TEXT]   ask the person who asked (an ask task, 2 at most)
    python3 tasks.py wait     <kb> T-0001 [--timeout 600]                               wait for the person's reply; prints it

A task is one file, <kb>/.metis/tasks/T-0001.yaml. The UI writes it; a Devin session (skill `metis-tasks`) claims it, does the
work with the Metis skills, and completes it. Nothing here calls a model, and nothing here writes KB pages: a build task writes
into its staging folder, an ask task returns an answer file that the UI checks against the KB before it is shown.

Kinds:
  ask          answer a question from the KB with `metis-ask`; the result is an answer file
  build-stage  one stage of `kb-build` (context, app:<module>, etl:<module>, db, cross-layer) into the run's staging folder
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import ui_common as C  # noqa: E402

DIR = os.path.join(".metis", "tasks")
STATUS = ("queued", "running", "waiting-user", "done", "failed", "cancelled")
KINDS = ("ask", "build-stage")
MAX_QUESTIONS, MAX_ROUNDS, MAX_QUESTION_CHARS = 2, 2, 300


def folder(kb):
    return os.path.join(kb, DIR)


def path(kb, tid):
    return os.path.join(folder(kb), tid + ".yaml")


def all_tasks(kb):
    d = folder(kb)
    if not os.path.isdir(d):
        return []
    out = []
    for name in sorted(os.listdir(d)):
        if name.endswith(".yaml"):
            t = C.load_yaml(os.path.join(d, name))
            if t.get("id"):
                out.append(t)
    return out


def get(kb, tid):
    t = C.load_yaml(path(kb, tid))
    if not t:
        raise C.UiError("no task %s" % tid)
    return t


def save(kb, t):
    C.dump_yaml(path(kb, t["id"]), t, "# Written by the Metis UI (tools/ui/tasks.py). A Devin session claims and completes it.\n")


def next_id(kb):
    nums = [int(t["id"][2:]) for t in all_tasks(kb) if t["id"][2:].isdigit()]
    return "T-%04d" % (max(nums or [0]) + 1)


def create(kb, kind, title, instructions, by, ref=None, stage=None, result_hint=None):
    """Queue one task. `ref` ties it to a record in the UI (an ask id or a build run); `stage` is the staging folder."""
    if kind not in KINDS:
        raise C.UiError("task kind must be one of %s" % ", ".join(KINDS))
    if not C.clean(title) or not C.clean(instructions):
        raise C.UiError("a task needs a title and instructions")
    t = {"id": next_id(kb), "kind": kind, "title": C.clean(title), "status": "queued", "created": C.now(),
         "created_by": C.clean(by) or "unknown", "ref": ref, "stage": stage, "instructions": instructions.strip(),
         "result_hint": result_hint, "claimed_by": None, "claimed_on": None, "finished_on": None, "result_file": None, "note": None}
    save(kb, t)
    return t


def claim(kb, by, tid=None):
    if not C.clean(by):
        raise C.UiError("say who is claiming the task")
    queued = [t for t in all_tasks(kb) if t["status"] == "queued" and (not tid or t["id"] == tid)]
    if not queued:
        raise C.UiError("no queued task%s" % (" " + tid if tid else ""))
    t = queued[0]
    t.update(status="running", claimed_by=C.clean(by), claimed_on=C.now())
    save(kb, t)
    return t


def complete(kb, tid, by, result_file=None, note=None):
    t = get(kb, tid)
    if t["status"] not in ("queued", "running", "waiting-user"):
        raise C.UiError("%s is already %s" % (tid, t["status"]))
    if not C.clean(by):
        raise C.UiError("say who finished the task")
    if t["kind"] == "ask":
        if not result_file or not os.path.isfile(result_file):
            raise C.UiError("an ask task needs the answer file (--file)")
        import answers
        answers.attach_model_answer(kb, t["ref"], result_file, C.clean(by), tid)
    elif result_file and not os.path.isfile(result_file):
        raise C.UiError("no such file: %s" % result_file)
    t.update(status="done", finished_on=C.now(), claimed_by=t.get("claimed_by") or C.clean(by),
             result_file=os.path.abspath(result_file) if result_file else None, note=C.clean(note) or None)
    save(kb, t)
    return t


def fail(kb, tid, by, note):
    t = get(kb, tid)
    if not C.clean(note):
        raise C.UiError("say why the task failed")
    t.update(status="failed", finished_on=C.now(), claimed_by=t.get("claimed_by") or C.clean(by), note=C.clean(note))
    save(kb, t)
    return t


def ask_user(kb, tid, by, questions):
    """The session needs the asker to say more. The UI shows the questions on the Ask page; `wait` returns the reply."""
    t = get(kb, tid)
    if t["kind"] != "ask":
        raise C.UiError("only an ask task can ask the person a question")
    if t["status"] != "running":
        raise C.UiError("%s is %s; claim it first, and answer the person's last reply before asking again" % (tid, t["status"]))
    qs = [C.clean(q) for q in questions if C.clean(q)]
    if not qs or len(qs) > MAX_QUESTIONS:
        raise C.UiError("ask one or %d questions" % MAX_QUESTIONS)
    if any(len(q) > MAX_QUESTION_CHARS for q in qs):
        raise C.UiError("keep each question under %d characters" % MAX_QUESTION_CHARS)
    rounds = t.get("rounds") or []
    if len(rounds) >= MAX_ROUNDS:
        raise C.UiError("you have asked %d times already: answer with what the KB has, and put the rest under Not in the KB" % MAX_ROUNDS)
    rounds.append({"questions": qs, "asked_by": C.clean(by), "asked_on": C.now(), "replies": None, "replied_by": None, "replied_on": None})
    t.update(status="waiting-user", rounds=rounds)
    save(kb, t)
    return t


def reply(kb, tid, by, replies):
    """The person's answers to the open round, one per question. The task goes back to running for the session."""
    t = get(kb, tid)
    if t["status"] != "waiting-user":
        raise C.UiError("%s is not waiting for a reply" % tid)
    cur = t["rounds"][-1]
    rs = [C.clean(r) for r in replies]
    if len(rs) != len(cur["questions"]) or not any(rs):
        raise C.UiError("answer at least one of the questions")
    cur.update(replies=rs, replied_by=C.clean(by), replied_on=C.now())
    t["status"] = "running"
    save(kb, t)
    return t


def reply_text(t):
    out = []
    for r in t.get("rounds") or []:
        if r.get("replies") is not None:
            out += ["%s -> %s" % (q, a or "(no answer)") for q, a in zip(r["questions"], r["replies"])]
    return "\n".join(out)


def wait(kb, tid, timeout=600, poll=2.0):
    import time
    end = time.time() + timeout
    while True:
        t = get(kb, tid)
        r = (t.get("rounds") or [{}])[-1]
        if t["status"] != "waiting-user" and r.get("replies") is not None:
            return r
        if t["status"] in ("done", "failed", "cancelled"):
            raise C.UiError("%s is %s" % (tid, t["status"]))
        if time.time() >= end:
            return None
        time.sleep(poll)


def cancel(kb, tid, by):
    t = get(kb, tid)
    if t["status"] not in ("queued", "running", "waiting-user"):
        raise C.UiError("%s is already %s" % (tid, t["status"]))
    t.update(status="cancelled", finished_on=C.now(), note="cancelled by %s" % (C.clean(by) or "unknown"))
    save(kb, t)
    return t


def requeue(kb, tid):
    t = get(kb, tid)
    if t["status"] not in ("running", "waiting-user", "failed", "cancelled"):
        raise C.UiError("%s is %s; only a running, failed or cancelled task can be queued again" % (tid, t["status"]))
    t.update(status="queued", claimed_by=None, claimed_on=None, finished_on=None, note=None)
    save(kb, t)
    return t


def summary(kb):
    c = {s: 0 for s in STATUS}
    for t in all_tasks(kb):
        c[t["status"]] = c.get(t["status"], 0) + 1
    return c


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("list"); a.add_argument("kb"); a.add_argument("--status", choices=STATUS)
    a = sub.add_parser("show"); a.add_argument("kb"); a.add_argument("id")
    a = sub.add_parser("claim"); a.add_argument("kb"); a.add_argument("id", nargs="?"); a.add_argument("--by", required=True)
    a = sub.add_parser("complete"); a.add_argument("kb"); a.add_argument("id"); a.add_argument("--by", required=True)
    a.add_argument("--file"); a.add_argument("--note")
    a = sub.add_parser("fail"); a.add_argument("kb"); a.add_argument("id"); a.add_argument("--by", required=True); a.add_argument("--note", required=True)
    a = sub.add_parser("ask-user"); a.add_argument("kb"); a.add_argument("id"); a.add_argument("--by", required=True)
    a.add_argument("--question", action="append", required=True)
    a = sub.add_parser("wait"); a.add_argument("kb"); a.add_argument("id"); a.add_argument("--timeout", type=int, default=600)
    args = ap.parse_args(argv)
    kb = os.path.abspath(args.kb)
    try:
        if args.cmd == "list":
            for t in all_tasks(kb):
                if not args.status or t["status"] == args.status:
                    print("%s\t%s\t%s\t%s" % (t["id"], t["status"], t["kind"], t["title"]))
        elif args.cmd == "show":
            t = get(kb, args.id)
            print("%s [%s] %s\n\n%s" % (t["id"], t["status"], t["title"], t["instructions"]))
        elif args.cmd == "claim":
            t = claim(kb, args.by, args.id)
            print("%s claimed by %s: %s\n\n%s" % (t["id"], t["claimed_by"], t["title"], t["instructions"]))
        elif args.cmd == "complete":
            t = complete(kb, args.id, args.by, args.file, args.note)
            print("%s done" % t["id"])
        elif args.cmd == "ask-user":
            ask_user(kb, args.id, args.by, args.question)
            print("%s is waiting for the person; run: tasks.py wait %s %s" % (args.id, kb, args.id))
        elif args.cmd == "wait":
            r = wait(kb, args.id, args.timeout)
            if r is None:
                print("no reply yet; run wait again, or finish with what the KB has")
            else:
                print("\n".join("%s -> %s" % (q, a or "(no answer)") for q, a in zip(r["questions"], r["replies"])))
        else:
            print("%s failed" % fail(kb, args.id, args.by, args.note)["id"])
    except C.UiError as err:
        print("error: %s" % err, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
