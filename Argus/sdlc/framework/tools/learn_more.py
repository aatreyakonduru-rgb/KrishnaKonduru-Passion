#!/usr/bin/env python3
"""What Devin still needs to learn from the team, and who can tell it.

The questions live in docs/knowledge-base/SHARED/learn-more.yaml, each tied to one person.
Nothing here writes to Jira. Changes to the file are shown first and only written with --write, which
/learn-more runs after the person types "approved".

    learn_more.py list [--person NAME] [--all]
    learn_more.py pick [--per-person 2] [--write]        mark the next questions as asked today
    learn_more.py answer L-001 --by NAME --text "..." [--write]
    learn_more.py add --ask NAME --question "..." --update PATH [--role ROLE] [--write]
    learn_more.py next --person NAME [--role ROLE] [--jira | --story "KEY: summary" ...]
                                                          the one question to ask at the start of a session
    learn_more.py note --person NAME --question "..." --text "..." [--role ROLE] [--story KEY] [--write]
    learn_more.py related L-001 [--text "..."]           other open questions in the knowledge base the answer
                                                          may also settle (read only)
"""
import argparse
import datetime
import os
import re
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
PATH = os.path.join(ROOT, "docs", "knowledge-base", "SHARED", "learn-more.yaml")
KNOW_HOW = os.path.join(ROOT, "docs", "knowledge-base", "SHARED", "team-know-how.yaml")


def norm(name):
    """Order-free, so the roster's "Resource 17" and "Resource 17" are the same person."""
    return "".join(sorted(re.findall(r"[a-z0-9]+", (name or "").lower())))


def load(path=PATH):
    if not os.path.exists(path):
        return {"questions": []}
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    data.setdefault("questions", [])
    return data


def load_know_how(path=KNOW_HOW):
    if not os.path.exists(path):
        return {"people": {}}
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    data["people"] = data.get("people") or {}
    return data


def save(data, path=PATH):
    with open(path, encoding="utf-8") as fh:
        head = "".join(line for line in fh if line.startswith("#"))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(head + yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=110))


def for_person(data, name, asked_only=False):
    """Open questions for one person; with asked_only, just the ones the daily pick has put in front of them."""
    return [q for q in data["questions"] if q.get("status") == "open" and norm(q.get("ask")) == norm(name)
            and (q.get("asked_on") or not asked_only)]


def pick(data, per_person=2, today=None):
    """Put up to per_person open questions in front of each person, counting the ones already waiting."""
    today = today or datetime.date.today().isoformat()
    picked = []
    for name in sorted({q.get("ask") for q in data["questions"] if q.get("status") == "open"}):
        waiting = for_person(data, name, asked_only=True)
        for q in [q for q in for_person(data, name) if not q.get("asked_on")][:max(0, per_person - len(waiting))]:
            q["asked_on"] = today
            picked.append(q)
    return picked


def answer(data, qid, text, by, today=None):
    text = (text or "").strip()
    if not text or not (by or "").strip():
        raise ValueError("give the answer and who gave it")
    for q in data["questions"]:
        if q.get("id") == qid:
            q.update(status="answered", answer=text, answered_by=by.strip(),
                     answered_on=today or datetime.date.today().isoformat())
            return q
    raise KeyError("no question %s" % qid)


def add(data, ask, question, update, role=""):
    if not (ask or "").strip() or not (question or "").strip():
        raise ValueError("give who to ask and the question")
    ids = [int(q["id"][2:]) for q in data["questions"] if re.match(r"L-\d+$", q.get("id", ""))]
    q = {"id": "L-%03d" % (max(ids or [0]) + 1), "ask": ask.strip(), "role": role, "question": question.strip(),
         "update": update, "status": "open", "asked_on": None, "answer": None, "answered_by": None,
         "answered_on": None}
    data["questions"].append(q)
    return q


ROLES_FILE = os.path.join(ROOT, ".devin", "rules", "dashboard-roles.yaml")
STOP = set("""about after again also because been before being between both could does doing done each from have
having here into just like make more most much must need only other over same should some still such than that
their them then there these they this those through under very want were what when where which while will with
would your yours""".split())


def words(text):
    return {w for w in re.findall(r"[a-z][a-z0-9_-]{3,}", (text or "").lower()) if w not in STOP}


def doc_gaps():
    """The doc-gap lines (marker REQUIRES STAKEHOLDER INPUT) the dashboard's Doc gaps tab lists."""
    import gen_dashboard
    with open(ROLES_FILE, encoding="utf-8") as fh:
        spec = (yaml.safe_load(fh) or {}).get("panels", {}).get("doc_questions") or {}
    return gen_dashboard.doc_marker_hits(spec) if spec else []


def related(data, qid, text="", gaps=None, min_shared=2):
    """Other open questions an answer may also settle: open learn-more questions and doc-gap lines that share
    at least min_shared words with the question and its answer, most shared first."""
    base = next((q for q in data["questions"] if q.get("id") == qid), None)
    if base is None:
        raise KeyError("no question %s" % qid)
    want = words(base.get("question")) | words(text or base.get("answer"))
    out = []
    for q in data["questions"]:
        shared = want & words(q.get("question"))
        if q.get("id") != qid and q.get("status") == "open" and len(shared) >= min_shared:
            out.append({"kind": "question", "id": q["id"], "ask": q.get("ask"), "text": q.get("question"),
                        "update": q.get("update"), "shared": sorted(shared)})
    for hit in gaps or []:
        for line in hit.get("questions") or []:
            shared = want & words(line)
            if len(shared) >= min_shared:
                out.append({"kind": "doc gap", "id": hit["document"], "text": line, "update": hit["document"],
                            "shared": sorted(shared)})
    out.sort(key=lambda r: -len(r["shared"]))
    return out


IN_PROGRESS_JQL = ('project = ACME AND assignee = "{user}" AND status = "In Progress" '
                   "AND issuetype not in subTaskIssueTypes() ORDER BY updated DESC")


def stories_in_progress(name):
    """[{key, summary}] of the person's stories in progress, read from Jira; empty when Jira cannot be read."""
    try:
        import gen_dashboard
        rows, _ = gen_dashboard.LiveSource(name).jira_panel({"jql": IN_PROGRESS_JQL})
    except Exception:  # noqa: BLE001 - no Jira means no story question, never a failed session
        return []
    return [{"key": r.get("key", ""), "summary": r.get("summary", "")} for r in rows if r.get("key")]


def parse_story(text):
    key, _, summary = (text or "").partition(":")
    return {"key": key.strip(), "summary": summary.strip()}


def next_question(data, name, role="", know_how=None, stories=None):
    """One question for the start of a session, in this order: an open question for this person, a question
    about a story they have in progress that they have not been asked about, an ice breaker about their role
    they have not answered. None when there is nothing left to ask."""
    mine = for_person(data, name)
    if mine:
        return dict(mine[0], kind="question")
    known = ((know_how or {}).get("people") or {}).get(name, [])
    asked = {norm(e.get("question")) for e in known}
    done = {e.get("story") for e in known if e.get("story")}
    templates = data.get("story_questions") or {}
    template = templates.get(role) or templates.get("default")
    for story in stories or []:
        if template and story.get("key") and story["key"] not in done:
            return {"kind": "story", "ask": name, "role": role, "story": story["key"],
                    "question": template.format(key=story["key"], summary=story.get("summary") or "this story"),
                    "update": os.path.relpath(KNOW_HOW, ROOT)}
    breakers = data.get("icebreakers") or {}
    for question in (breakers.get(role) or []) + (breakers.get("default") or []):
        if norm(question) not in asked:
            return {"kind": "icebreaker", "ask": name, "role": role, "question": question,
                    "update": os.path.relpath(KNOW_HOW, ROOT)}
    return None


def note(know_how, name, question, text, role="", today=None, story=""):
    """An ice-breaker answer, kept under the person in team-know-how.yaml."""
    text = (text or "").strip()
    if not text or not (name or "").strip() or not (question or "").strip():
        raise ValueError("give the person, the question and their answer")
    entry = {"question": question.strip(), "answer": text, "role": role,
             "on": today or datetime.date.today().isoformat()}
    if story:
        entry["story"] = story
    know_how.setdefault("people", {}).setdefault(name.strip(), []).append(entry)
    return entry


def show(items):
    for q in items:
        print("%s  %s (%s): %s\n      answer goes to: %s%s" % (
            q["id"], q.get("ask"), q.get("role") or "-", q.get("question"), q.get("update"),
            "  [asked %s]" % q["asked_on"] if q.get("asked_on") else ""))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", default=PATH)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("list"); s.add_argument("--person"); s.add_argument("--all", action="store_true")
    s = sub.add_parser("pick"); s.add_argument("--per-person", type=int, default=2); s.add_argument("--write", action="store_true")
    s = sub.add_parser("answer"); s.add_argument("id"); s.add_argument("--by", required=True)
    s.add_argument("--text", required=True); s.add_argument("--write", action="store_true")
    s = sub.add_parser("add"); s.add_argument("--ask", required=True); s.add_argument("--question", required=True)
    s.add_argument("--update", default=""); s.add_argument("--role", default=""); s.add_argument("--write", action="store_true")
    s = sub.add_parser("next"); s.add_argument("--person", required=True); s.add_argument("--role", default="")
    s.add_argument("--jira", action="store_true"); s.add_argument("--story", action="append", default=[])
    s = sub.add_parser("note"); s.add_argument("--person", required=True); s.add_argument("--question", required=True)
    s.add_argument("--text", required=True); s.add_argument("--role", default=""); s.add_argument("--write", action="store_true")
    s.add_argument("--story", default="")
    s = sub.add_parser("related"); s.add_argument("id"); s.add_argument("--text", default="")
    ap.add_argument("--know-how", default=KNOW_HOW)
    args = ap.parse_args(argv)
    data = load(args.file)
    know_how = load_know_how(args.know_how)
    if args.cmd == "related":
        try:
            rows = related(data, args.id, args.text, doc_gaps())
        except KeyError as exc:
            print("learn_more: %s" % exc, file=sys.stderr)
            return 2
        for r in rows:
            print("%s %s: %s\n      answer goes to: %s  (shared: %s)" % (
                r["kind"], r["id"], r["text"], r["update"], ", ".join(r["shared"])))
        print("(no other open question looks related)" if not rows else
              "Check each one: close it only when this answer really settles it, shown first like any answer.")
        return 0
    if args.cmd == "next":
        stories = [parse_story(t) for t in args.story]
        if args.jira and not stories and not for_person(data, args.person):
            stories = stories_in_progress(args.person)
        q = next_question(data, args.person, args.role, know_how, stories)
        print(yaml.safe_dump(q, sort_keys=False, allow_unicode=True).rstrip() if q else "(nothing to ask)")
        return 0
    if args.cmd == "note":
        try:
            entry = note(know_how, args.person, args.question, args.text, args.role, story=args.story)
        except ValueError as exc:
            print("learn_more: %s" % exc, file=sys.stderr)
            return 2
        print(yaml.safe_dump({args.person: [entry]}, sort_keys=False, allow_unicode=True).rstrip())
        if args.write:
            save(know_how, args.know_how)
            print("wrote %s" % os.path.relpath(args.know_how, ROOT))
        else:
            print("preview only: run again with --write after the person types approved")
        return 0
    try:
        if args.cmd == "list":
            items = data["questions"] if args.all else [q for q in data["questions"] if q.get("status") == "open"]
            show([q for q in items if not args.person or norm(args.person) in norm(q.get("ask"))])
            return 0
        if args.cmd == "pick":
            changed = pick(data, args.per_person)
        elif args.cmd == "answer":
            changed = [answer(data, args.id, args.text, args.by)]
        else:
            changed = [add(data, args.ask, args.question, args.update, args.role)]
    except (ValueError, KeyError) as exc:
        print("learn_more: %s" % exc, file=sys.stderr)
        return 2
    print(yaml.safe_dump(changed, sort_keys=False, allow_unicode=True).rstrip() or "(nothing to change)")
    if args.write:
        save(data, args.file)
        print("wrote %s" % os.path.relpath(args.file, ROOT))
    else:
        print("preview only: run again with --write after the person types approved")
    return 0


if __name__ == "__main__":
    sys.exit(main())
