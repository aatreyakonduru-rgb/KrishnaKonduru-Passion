#!/usr/bin/env python3
"""Per-line attribution: which KB lines an answer cited, and which lines the disliked answers leaned on.

    python3 telemetry_lines.py record   <kb> --answer FILE [--by NAME]   record the lines (not the text) an answer file cites
    python3 telemetry_lines.py report   <kb> [--limit N]                 the 'lines to look at first' report
    python3 telemetry_lines.py reanchor <kb>                             which recorded lines moved, and which disappeared

telemetry.py records which KB files an answer used. This adds the lines: for an answer, the `path:line` of every KB line it cited
with `[E: kb:<path>:<line>]`, `[E: kb:<path>:<a>-<b>]` or `[E: kb:<path> "quote"]` (a quote is located in the file and recorded as
the line it is on). The event is the usual telemetry event with an extra `lines` list, in <kb>/.metis/usage/<YYYY-MM>.jsonl,
which is git-ignored. A range is recorded line by line, at most 20 lines per tag. Nothing else is stored: no question, no answer
text, no quote, no KB line text. Old events without `lines` are read as before.

`report` joins the likes and dislikes in _FEEDBACK (feedback.py) to lines. Each rated answer is kept as _FEEDBACK/answers/F-xxxx.md;
its cited lines are read from that copy, so ratings given before this tool existed are counted too. For each `path:line`: how many
disliked answers cited it, how many liked answers, how many a lead declined (counted apart, as in telemetry.py), and how often an
answer used it. Lines are sorted by dislikes, then fewest likes. The current text of the line is shown from the KB itself.

Read it as "look here first", not as a verdict. A dislike names an answer, not a line: a cited line may be right and the answer
wrong.

Stable identity. A line number moves when a page is edited, so each recorded line also gets a fingerprint: the first 16 hex digits of
SHA-256 over a per-KB salt, the page path and the normalised line text (the [E: ...] tag, a {env/sensitivity/valid-...} group and the
list bullet are left out, case and spacing are ignored). Events carry `anchors` ("path:line#fingerprint") beside `lines`; the answer
copies of rated answers get theirs in <kb>/.metis/usage/line-anchors.json when the rating is made (anchor_rated, called by the Ask and
Chat rating). The salt is in <kb>/.metis/usage/.line-salt. All of it is in the git-ignored usage folder, which kb_manifest skips. A
fingerprint is a salted hash: it holds no question, no answer text and no KB text, and cannot be turned back into text.
`report` and `reanchor` find a line by fingerprint in the page as it is now, so counts follow the line when text above it is added or
removed. Records made before this existed have line numbers only: they are read as the line that now has that number (as before), and
a number past the end of the page is reported as gone. A line whose own text is edited, or that is deleted, has no fingerprint match:
it is reported as "line no longer exists" / `gone`, never matched by guesswork. Two identical lines on one page share one identity.
If .line-salt is deleted, old fingerprints stop matching (counts for them are reported as gone).
"""
import argparse
import hashlib
import json
import os
import re
import secrets
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import feedback  # noqa: E402
import telemetry  # noqa: E402
import verify_kb  # noqa: E402

MAX_RANGE = 20
FP_LEN = 16
ANCHORS = os.path.join(".metis", "usage", "line-anchors.json")
SALT = os.path.join(".metis", "usage", ".line-salt")
BULLET = re.compile(r"^\s*([-*>]|\d+[.)])\s+")
ANNOT = re.compile(r"\{[^{}]*\b(?:env|sensitivity|valid[-_]from|valid[-_]to|superseded[-_]by)\s*:[^{}]*\}", re.I)
KB_REF = re.compile(r'^\s*kb:([^:"\s]+)(?::(\d+)(?:-(\d+))?)?(?:\s+"(.+)")?\s*$')


def squash(s):
    return " ".join(str(s).split()).lower()


def read_lines(kb, rel):
    p = os.path.join(kb, rel)
    if not os.path.isfile(p):
        return None
    with open(p, encoding="utf-8", errors="replace") as fh:
        return fh.read().splitlines()


def locate(lines, quote):
    """(first, last) 1-based line numbers where the quote is found, or None. Searches one line, then up to five lines joined."""
    q = squash(quote)
    if not q:
        return None
    for i, l in enumerate(lines):
        if q in squash(l):
            return i + 1, i + 1
    for span in range(2, 6):
        for i in range(0, len(lines) - span + 1):
            if q in squash(" ".join(lines[i:i + span])):
                return i + 1, i + span
    return None


def cited_lines(kb, answer_text, keep_stale=False):
    """Sorted `path:line` strings for every KB line an answer cites. Tags that name only a file, or whose quote is not found, add none.
    keep_stale keeps an explicit line number even if the file is now shorter (used for old rated answers; the report says so)."""
    out, cache = set(), {}
    for kind, value in verify_kb.TAG.findall(answer_text):
        if kind != "E":
            continue
        for part in value.split(";"):
            m = KB_REF.match(part)
            if not m:
                continue
            rel, a, b, quote = m.groups()
            if rel not in cache:
                cache[rel] = read_lines(kb, rel)
            lines = cache[rel]
            if a:
                lo, hi = int(a), int(b or a)
                if lo < 1 or hi < lo or (not keep_stale and (lines is None or hi > len(lines))):
                    continue
            elif lines is None:
                continue
            elif quote:
                got = locate(lines, quote)
                if not got:
                    continue
                lo, hi = got
            else:
                continue
            for n in range(lo, min(hi, lo + MAX_RANGE - 1) + 1):
                out.add("%s:%d" % (rel, n))
    return sorted(out, key=lambda s: (s.rsplit(":", 1)[0], int(s.rsplit(":", 1)[1])))


# ---- stable fingerprints ----------------------------------------------------------------------------
def normalize(line):
    """The part of a KB line that says something: no source tag, no label/date group, no list bullet; one space, lower case."""
    t = ANNOT.sub(" ", verify_kb.TAG.sub(" ", str(line)))
    return squash(BULLET.sub("", t))


def _salt(kb, create=False):
    p = os.path.join(kb, SALT)
    if not os.path.isfile(p):
        if not create:
            return ""
        os.makedirs(os.path.dirname(p), exist_ok=True)
        guard = os.path.join(os.path.dirname(p), ".gitignore")
        if not os.path.isfile(guard):
            with open(guard, "w", encoding="utf-8", newline="\n") as fh:
                fh.write("*\n")
        with open(p, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(secrets.token_hex(16))
    with open(p, encoding="utf-8") as fh:
        return fh.read().strip()


def fingerprint(rel, text, salt):
    """Stable identity of a line: salted hash of page path + normalised text, or None for a line with no words."""
    t = normalize(text)
    if not t:
        return None
    return hashlib.sha256(("%s\n%s\n%s" % (salt, rel, t)).encode("utf-8")).hexdigest()[:FP_LEN]


def _page_fps(kb, rel, salt, cache):
    """[(line number, fingerprint)] for the page as it is now ([] when the page is gone)."""
    if rel not in cache:
        lines = read_lines(kb, rel) or []
        cache[rel] = [(n, fp) for n, fp in ((n, fingerprint(rel, l, salt)) for n, l in enumerate(lines, 1)) if fp]
    return cache[rel]


def anchors_for(kb, refs):
    """Sorted "path:line#fingerprint" for the `path:line` refs whose line exists and has words. Creates the salt if needed."""
    salt, cache, out = _salt(kb, create=True), {}, []
    for ref in refs or []:
        rel, n = split(ref)
        for m, fp in _page_fps(kb, rel, salt, cache):
            if m == n:
                out.append("%s#%s" % (ref, fp))
    return sorted(set(out))


def split_anchor(a):
    ref, _, fp = a.rpartition("#")
    return ref, fp


def _load_anchor_file(kb):
    try:
        with open(os.path.join(kb, ANCHORS), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def anchor_rated(kb, fid):
    """Keep the fingerprints of the lines the rated answer F-xxxx cited, as the page reads now (call when the rating is made).
    Written atomically. Returns the number of lines anchored; 0 when the copy cites none. Never raises on a missing copy."""
    p = os.path.join(kb, feedback.DIR, "answers", "%s.md" % fid)
    if not os.path.isfile(p):
        return 0
    with open(p, encoding="utf-8", errors="replace") as fh:
        refs = cited_lines(kb, fh.read(), keep_stale=True)
    got = dict(a.rsplit("#", 1) for a in anchors_for(kb, refs))
    if not got:
        return 0
    data = _load_anchor_file(kb)
    data[str(fid)] = got
    tmp = os.path.join(kb, ANCHORS + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, sort_keys=True, indent=1)
    os.replace(tmp, os.path.join(kb, ANCHORS))
    return len(got)


def used_by_anchor(kb):
    """{(page, fingerprint): times used}. An event with anchors uses them; an older event (line numbers only) is read as the line
    that now has that number. Legacy refs past the end of their page are returned under (ref, None)."""
    salt, cache, out = _salt(kb), {}, {}
    for e in telemetry.events(kb):
        done = set()
        for a in e.get("anchors") or []:
            ref, fp = split_anchor(a)
            out[(split(ref)[0], fp)] = out.get((split(ref)[0], fp), 0) + 1
            done.add(ref)
        for ref in e.get("lines") or []:
            if ref in done:
                continue
            rel, n = split(ref)
            fp = dict(_page_fps(kb, rel, salt, cache)).get(n)
            key = (rel, fp) if fp else (ref, None)
            out[key] = out.get(key, 0) + 1
    return out


def find_fp(kb, rel, fp, cache=None, salt=None):
    """Line numbers where the page has a line with this fingerprint now."""
    salt = _salt(kb) if salt is None else salt
    return [n for n, f in _page_fps(kb, rel, salt, {} if cache is None else cache) if f == fp]


def reanchor(kb):
    """Where the recorded lines are now: {checked, unchanged, moved: [{from, to, used}], gone: [{line, used}]}. Reads only; the
    counts are carried by fingerprint, so nothing needs rewriting. `gone`: the line's text was edited or deleted, or an old
    number-only record points past the end of its page."""
    salt, cache = _salt(kb), {}
    seen = {}                                        # (page, fingerprint) -> latest recorded ref
    for e in telemetry.events(kb):
        for a in e.get("anchors") or []:
            ref, fp = split_anchor(a)
            seen[(split(ref)[0], fp)] = ref
    for fid, m in _load_anchor_file(kb).items():
        for ref, fp in (m or {}).items():
            seen.setdefault((split(ref)[0], fp), ref)
    used = used_by_anchor(kb)
    out = {"checked": 0, "unchanged": 0, "moved": [], "gone": []}
    for (rel, fp), ref in sorted(seen.items(), key=lambda kv: kv[1]):
        out["checked"] += 1
        here = find_fp(kb, rel, fp, cache, salt)
        if not here:
            out["gone"].append({"line": ref, "used": used.get((rel, fp), 0)})
        elif split(ref)[1] in here:
            out["unchanged"] += 1
        else:
            out["moved"].append({"from": ref, "to": "%s:%d" % (rel, here[0]), "used": used.get((rel, fp), 0)})
    for (key, fp), n in sorted(used.items(), key=lambda kv: str(kv[0])):
        if fp is None:                               # an old number-only record past the end of its page
            out["checked"] += 1
            out["gone"].append({"line": key, "used": n})
    return out


def used_now(kb):
    """{path:line as the page is now: times used}: counts carried across edits by fingerprint. Lines that disappeared are left out."""
    salt, cache, out = _salt(kb), {}, {}
    for (rel, fp), n in used_by_anchor(kb).items():
        if fp is None:
            continue
        here = find_fp(kb, rel, fp, cache, salt)
        if here:
            ref = "%s:%d" % (rel, here[0])
            out[ref] = out.get(ref, 0) + n
    return out


def record_answer(kb, answer_text, by=None):
    """Record an answer's cited files and lines as one telemetry event. Returns the event, or None when it cited no KB file."""
    files, _ = feedback.cited(answer_text)
    if not files:
        return None
    return telemetry.record(kb, "answer", files, by=by, lines=cited_lines(kb, answer_text))


def split(ref):
    rel, _, n = ref.rpartition(":")
    return rel, int(n)


def line_text(kb, ref):
    """What the KB says on that line now (KB content, not stored anywhere), or None when the line is gone."""
    rel, n = split(ref)
    lines = read_lines(kb, rel)
    if lines is None or not 1 <= n <= len(lines):
        return None
    return lines[n - 1].strip()


def used_counts(kb):
    out = {}
    for e in telemetry.events(kb):
        for ref in e.get("lines") or []:
            out[ref] = out.get(ref, 0) + 1
    return out


def _rated(kb):
    """({key: {up, down, declined, ref}}, rated answers that cited no line). key is (page, fingerprint) when the rating was anchored,
    else (path:line,) for an old rating that has line numbers only; `ref` is the line as recorded."""
    out, no_lines, side = {}, 0, _load_anchor_file(kb)
    for f in feedback.load(kb).get("feedback") or []:
        p = os.path.join(kb, feedback.DIR, "answers", "%s.md" % f.get("id"))
        refs = []
        if os.path.isfile(p):
            with open(p, encoding="utf-8", errors="replace") as fh:
                refs = cited_lines(kb, fh.read(), keep_stale=True)
        if not refs:
            no_lines += 1
        anchored = side.get(str(f.get("id"))) or {}
        for ref in refs:
            fp = anchored.get(ref)
            row = out.setdefault((split(ref)[0], fp) if fp else (ref,), {"up": 0, "down": 0, "declined": 0, "ref": ref})
            if f.get("rating") == "up":
                row["up"] += 1
            elif f.get("status") == "declined":
                row["declined"] += 1
            else:
                row["down"] += 1
    return out, no_lines


def rated_lines(kb):
    """({path:line: {up, down, declined}}, rated answers that cited no line) from the answer copies kept by feedback.py, by the
    line number as recorded (the old view; `report` follows the line by fingerprint)."""
    rows, no_lines = _rated(kb)
    out = {}
    for m in rows.values():
        row = out.setdefault(m["ref"], {"up": 0, "down": 0, "declined": 0})
        for k in row:
            row[k] += m[k]
    return out, no_lines


def report(kb, limit=50):
    """{answers_with_lines, lines_used, look_first: [{line, page, down, up, declined, used, text, status, moved_from}], ...}.
    `line` is where the line is now (found by fingerprint when it was anchored); `moved_from` is the recorded ref when it moved."""
    ev = [e for e in telemetry.events(kb) if e.get("lines")]
    anchored = used_by_anchor(kb)
    salt, cache = _salt(kb), {}
    marks, no_lines = _rated(kb)
    rows = []
    for key, m in marks.items():
        if not m["down"]:
            continue
        ref, moved, used = m["ref"], None, 0
        if len(key) == 2:                                    # anchored rating: follow the line by its fingerprint
            here = find_fp(kb, key[0], key[1], cache, salt)
            used = anchored.get(key, 0)
            if here:
                ref = "%s:%d" % (key[0], here[0])
                moved = m["ref"] if ref != m["ref"] else None
            txt = line_text(kb, ref) if here else None
        else:                                                # old rating: the line that has that number now
            txt = line_text(kb, ref)
            rel, n = split(ref)
            fp = dict(_page_fps(kb, rel, salt, cache)).get(n) if txt is not None else None
            used = anchored.get((rel, fp), 0) if fp else anchored.get((ref, None), 0)
        rows.append({"line": ref, "page": split(ref)[0], "down": m["down"], "up": m["up"], "declined": m["declined"],
                     "used": used, "text": txt, "status": "current" if txt is not None else "line no longer exists",
                     "moved_from": moved})
    rows.sort(key=lambda r: (-r["down"], r["up"], r["line"]))
    now = used_now(kb)
    return {"answers_with_lines": len(ev), "lines_used": len(anchored), "look_first": rows[:limit] if limit else rows,
            "lines_rated": len(marks), "rated_answers_without_lines": no_lines,
            "most_used": sorted(({"line": k, "used": v} for k, v in now.items()), key=lambda r: (-r["used"], r["line"]))[:10]}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record"); r.add_argument("kb"); r.add_argument("--answer", required=True); r.add_argument("--by")
    p = sub.add_parser("report"); p.add_argument("kb"); p.add_argument("--limit", type=int, default=50)
    n = sub.add_parser("reanchor"); n.add_argument("kb")
    a = ap.parse_args(argv)
    kb = os.path.abspath(a.kb)
    if a.cmd == "reanchor":
        rep = reanchor(kb)
        for m in rep["moved"]:
            print("moved  %s -> %s  (used %d)" % (m["from"], m["to"], m["used"]))
        for g in rep["gone"]:
            print("gone   %s  (used %d)" % (g["line"], g["used"]))
        print("%d lines checked: %d unchanged, %d moved (counts carried), %d disappeared" % (
            rep["checked"], rep["unchanged"], len(rep["moved"]), len(rep["gone"])))
        return 0
    if a.cmd == "record":
        with open(a.answer, encoding="utf-8") as fh:
            ev = record_answer(kb, fh.read(), a.by)
        if not ev:
            print("lines: the answer cites no KB file; nothing recorded")
            return 0
        print("lines: recorded %d cited lines in %d files" % (len(ev.get("lines") or []), len(ev["files"])))
        return 0
    rep = report(kb, a.limit)
    print("%d answers recorded with lines; %d distinct lines used; %d lines cited by rated answers" % (
        rep["answers_with_lines"], rep["lines_used"], rep["lines_rated"]))
    for r in rep["look_first"]:
        print("%3d down %3d up %3d declined  used %3d  %s  %s%s" % (
            r["down"], r["up"], r["declined"], r["used"], r["line"],
            r["text"][:70] if r["text"] is not None else "(line no longer exists)",
            "  (moved from %s)" % r["moved_from"] if r.get("moved_from") else ""))
    if not rep["look_first"]:
        print("No line is cited in a disliked answer.")
    else:
        print("A dislike names an answer, not a line: read this as where to look first, not as a verdict.")
    if rep["rated_answers_without_lines"]:
        print("%d rated answers cited no line (file-only tags, or no copy kept)." % rep["rated_answers_without_lines"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
