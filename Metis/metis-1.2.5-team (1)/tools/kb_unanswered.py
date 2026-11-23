#!/usr/bin/env python3
"""What people asked that the KB could not answer, ranked.

    python3 kb_unanswered.py report <kb> [--limit N] [--json]     the ranked report
    python3 kb_unanswered.py misses <kb>                          the opt-in hashed miss counter (counts only)
    python3 kb_unanswered.py miss   <kb> "words"                  count one query that found nothing (only when the profile opts in)

Where it reads, and nothing else is stored:
  asks            <kb>/.metis/asks/A-*.yaml, the record ui/answers.py already keeps for every question asked in the UI, with the
                  computed confidence band. An ask whose latest try is Low or None is unanswered.
  disliked        a dislike in _FEEDBACK/FEEDBACK.yaml (feedback.py) that no lead has declined.
  open questions  an open question in _QUESTIONS/VALIDATE_KB.yaml that someone raised through feedback.py or questions.py raise
                  ("raised_by_build" begins "feedback " or "asked by "). Questions the build raised are not user asks and are left out.
  telemetry       tools/telemetry.py records which KB files a pack or answer used. It stores no question text and no record of an
                  answer that cited nothing, so it cannot say what was asked and missed. The report says so, and shows how many
                  answers it holds. This tool adds no question text capture.

Ranking (shown with each item, so a person can judge it): each ask counts 3 when its latest try had no answer and 2 when Low;
a live dislike counts 2; an open question counts 3, 2 or 1 for P1, P2, P3; each further distinct person who asked the same thing
adds 1. Near-identical questions (the same words, feedback.similar >= 0.8) are one item. The asker's name is shown as the
record already holds it.

Opt-in counter: with `search.count_misses: true` in the profile, a search that finds nothing adds 1 to a count keyed by a salted
SHA-256 of the query's sorted words. The salt is random per KB (<kb>/.metis/usage/.miss-salt). The query text is not written, so
the counter shows how often some query missed, never what it was. It cannot be turned back into words except by guessing, and
the salt stops a guess from being checked against another KB. Default off.
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import secrets
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import feedback  # noqa: E402
import questions  # noqa: E402
import telemetry  # noqa: E402

ASKS = os.path.join(".metis", "asks")
COUNTER = os.path.join(".metis", "usage", "misses.json")
SALT = os.path.join(".metis", "usage", ".miss-salt")
SAME = 0.8
BAD_BANDS = {"None": 3, "Low": 2}
PRIORITY = {"P1": 3, "P2": 2, "P3": 1}


def load_yaml(path):
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except (yaml.YAMLError, OSError):
        return {}


def profile(kb):
    return load_yaml(os.path.join(kb, ".metis", "kb-profile.yaml"))


def read_asks(kb):
    d = os.path.join(kb, ASKS)
    out = []
    if os.path.isdir(d):
        for n in sorted(os.listdir(d)):
            if n.endswith(".yaml"):
                r = load_yaml(os.path.join(d, n))
                if isinstance(r, dict) and r.get("id") and r.get("question"):
                    out.append(r)
    return out


def band_of(ask):
    """The confidence band of an ask, or None when it was never answered (waiting for a Devin session, or an old record)."""
    if ask.get("status") == "waiting":
        return None
    c = ask.get("confidence")
    if isinstance(c, dict) and c.get("band"):
        return c["band"]
    chk = ask.get("checked")
    if ask.get("status") == "answered" and isinstance(chk, dict) and not chk.get("lines"):
        return "None"
    return None


def collect(kb):
    """Raw events: [{key text, question, kind, weight, who, on, ref, detail}] from asks, dislikes and raised questions."""
    ev = []
    asks = read_asks(kb)
    by_id = {a["id"]: a for a in asks}
    superseded = set()
    for a in asks:  # a re-ask replaces the try it follows
        if a.get("follows") in by_id:
            superseded.add(a["follows"])
    for a in asks:
        band = band_of(a)
        if band in BAD_BANDS and a["id"] not in superseded:
            ev.append({"question": a["question"], "kind": "ask", "weight": BAD_BANDS[band], "who": str(a.get("by") or ""),
                       "on": str(a.get("on") or "")[:10], "ref": a["id"], "detail": "no answer" if band == "None" else "low confidence"})
    try:
        fb = feedback.load(kb).get("feedback") or []
    except Exception:
        fb = []
    for f in fb:
        if f.get("rating") == "down" and f.get("status") != "declined" and f.get("question"):
            ev.append({"question": f["question"], "kind": "dislike", "weight": 2, "who": str(f.get("by") or ""),
                       "on": str(f.get("on") or ""), "ref": f.get("id"), "detail": "disliked: %s" % str(f.get("why") or "")[:80]})
    try:
        reg = questions.load(questions.reg_path(kb)).get("questions") or []
    except Exception:
        reg = []
    for q in reg:
        raised = str(q.get("raised_by_build") or "")
        if q.get("status") == "open" and (raised.startswith("feedback ") or raised.startswith("asked by ")) and q.get("question"):
            who = raised[len("asked by "):] if raised.startswith("asked by ") else ""
            ev.append({"question": q["question"], "kind": "open question", "weight": PRIORITY.get(q.get("priority"), 1), "who": who,
                       "on": str(q.get("raised_on") or ""), "ref": q.get("id"), "detail": "open %s, answer role %s" % (
                           q.get("priority"), q.get("answer_role"))})
    return ev


def report(kb, limit=50):
    """{items, asks_read, telemetry, counter, notes}. items: [{question, score, why, kinds, refs, askers, last_on}], best first."""
    kb = os.path.abspath(kb)
    events = collect(kb)
    groups = []  # [{question, events}]
    for e in events:
        for g in groups:
            if feedback.similar(e["question"], g["question"]) >= SAME and feedback.similar(g["question"], e["question"]) >= SAME:
                g["events"].append(e)
                break
        else:
            groups.append({"question": e["question"], "events": [e]})
    items = []
    for g in groups:
        evs = g["events"]
        people = sorted({e["who"].lower() for e in evs if e["who"]})
        score = sum(e["weight"] for e in evs) + max(0, len(people) - 1)
        counts = {}
        for e in evs:
            counts[e["kind"]] = counts.get(e["kind"], 0) + 1
        why = ["%d %s" % (n, k if n == 1 else k + ("s" if not k.endswith("s") else "")) for k, n in sorted(counts.items())]
        if len(people) > 1:
            why.append("%d people" % len(people))
        # the clearest wording: the longest of the near-identical questions
        question = max((e["question"] for e in evs), key=len)
        items.append({"question": question, "score": score, "why": why, "kinds": sorted(counts),
                      "refs": [e["ref"] for e in evs if e["ref"]], "askers": sorted({e["who"] for e in evs if e["who"]}),
                      "last_on": max((e["on"] for e in evs if e["on"]), default=""), "detail": [e["detail"] for e in evs][:5]})
    items.sort(key=lambda i: (-i["score"], -ord_date(i["last_on"]), i["question"].lower()))
    tel = telemetry.events(kb)
    notes = []
    if not any(e["kind"] == "ask" for e in events) and not read_asks(kb):
        notes.append("No ask records in .metis/asks yet, so no question was asked in the UI.")
    return {"items": items[:max(0, int(limit))], "total": len(items), "asks_read": len(read_asks(kb)),
            "telemetry": {"events": len(tel), "answers": sum(1 for e in tel if e.get("kind") == "answer"), "has_question_text": False,
                          "note": "telemetry.py stores which KB files an answer used, never the question, and records nothing for an "
                                  "answer that cited no file, so it cannot list unanswered questions. This report reads the ask "
                                  "records, dislikes and raised questions instead."},
            "counter": counter_status(kb), "notes": notes}


def ord_date(s):
    try:
        return datetime.date.fromisoformat(str(s)[:10]).toordinal()
    except ValueError:
        return 0


# ---- the opt-in hashed counter ------------------------------------------------------------------------
def counter_enabled(kb):
    return bool((profile(kb).get("search") or {}).get("count_misses"))


def norm_words(query):
    return " ".join(sorted(set(re.findall(r"[a-z0-9_]+", str(query).lower()))))


def salt(kb):
    p = os.path.join(kb, SALT)
    if not os.path.isfile(p):
        os.makedirs(os.path.dirname(p), exist_ok=True)
        guard = os.path.join(os.path.dirname(p), ".gitignore")
        if not os.path.isfile(guard):
            with open(guard, "w", encoding="utf-8", newline="\n") as fh:
                fh.write("*\n")
        with open(p, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(secrets.token_hex(16))
    with open(p, encoding="utf-8") as fh:
        return fh.read().strip()


def load_counter(kb):
    p = os.path.join(kb, COUNTER)
    try:
        with open(p, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def record_miss(kb, query):
    """Count one query that found nothing, by salted hash only. Returns the new count, or None when the profile has not opted in
    or the query has no words. The query text is never written."""
    kb = os.path.abspath(kb)
    words = norm_words(query)
    if not counter_enabled(kb) or not words:
        return None
    key = hashlib.sha256((salt(kb) + "\n" + words).encode("utf-8")).hexdigest()[:24]
    data = load_counter(kb)
    row = data.get(key) or {"count": 0, "first": datetime.date.today().isoformat()}
    row["count"] += 1
    row["last"] = datetime.date.today().isoformat()
    data[key] = row
    with open(os.path.join(kb, COUNTER), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, sort_keys=True, indent=1)
    return row["count"]


def counter_status(kb):
    data = load_counter(kb)
    rows = sorted(data.items(), key=lambda kv: (-kv[1].get("count", 0), kv[0]))
    return {"enabled": counter_enabled(kb), "distinct": len(data), "total": sum(r.get("count", 0) for r in data.values()),
            "top": [{"id": k, "count": v.get("count", 0), "last": v.get("last", "")} for k, v in rows[:10]],
            "note": "Counts only. The query text is not stored. Turn on with search.count_misses: true in the KB profile."}


# ---- command line -------------------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("report")
    a.add_argument("kb")
    a.add_argument("--limit", type=int, default=20)
    a.add_argument("--json", action="store_true")
    a = sub.add_parser("misses")
    a.add_argument("kb")
    a = sub.add_parser("miss")
    a.add_argument("kb")
    a.add_argument("words")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    kb = os.path.abspath(args.kb)
    if not os.path.isdir(kb):
        print("error: no KB folder %s" % kb, file=sys.stderr)
        return 2
    if args.cmd == "miss":
        n = record_miss(kb, args.words)
        print("not counted: search.count_misses is off in the profile (or no words)" if n is None else "counted (%d)" % n)
        return 0
    if args.cmd == "misses":
        print(json.dumps(counter_status(kb), indent=2))
        return 0
    rep = report(kb, args.limit)
    if args.json:
        print(json.dumps(rep, indent=2))
        return 0
    print("%d unanswered item%s (%d ask records read)" % (rep["total"], "" if rep["total"] == 1 else "s", rep["asks_read"]))
    for i, it in enumerate(rep["items"], 1):
        print("%2d. [%d] %s\n      %s; last %s; %s" % (i, it["score"], it["question"], ", ".join(it["why"]), it["last_on"] or "-",
                                                      ", ".join(it["refs"][:6])))
    print("telemetry: %s" % rep["telemetry"]["note"])
    for n in rep["notes"]:
        print("note: %s" % n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
