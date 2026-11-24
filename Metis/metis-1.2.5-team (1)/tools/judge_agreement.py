#!/usr/bin/env python3
"""Measure how far the two automatic support checks can be trusted, against a person's labels on a sample of KB lines.

    python3 judge_agreement.py draw   <kb> [--n 50] [--seed TEXT] [--controls 5] [--no-judge] [--file F]
    python3 judge_agreement.py score  <kb> [--file F] [--threshold 0.2]

The two checks are the lexical screen in verify_kb.py (does the line share words with the text it cites) and the judge in
llm_judge.py (a model reads the cited text and says supported, partial or unsupported). Neither says a line is TRUE. This tool asks a
narrower question that can be answered: when a person reads the claim beside its cited text, how often do the checks agree?

`draw` picks N cited lines, spread over the pages (the same seed gives the same sample), and writes a worksheet
(<kb>/.metis/judge/agreement/sample.yaml). Each item shows the claim, the cited text and what the lexical screen said. It also writes a
judge request for each item; once a session has answered them (see llm_judge.py), `score` reads the verdicts. A person fills in
`human:` for each item: supported, partial, unsupported or unsure. The question is the judge's question: does the cited text support the
claim as written (not: is it true).

`--controls K` adds K lines whose claim is moved onto another page's citation. They are wrong by construction (`control: true`, the
human label is pre-filled as unsupported) and show whether the checks catch a real citation under an unrelated claim, before anyone has
labelled anything. They are reported apart from the sample and never counted in it.

`score` reads the labels. For the screen and for the judge it reports agreement with the person and a 95% interval, how many wrong lines
each caught, and how many good lines each flagged. With fewer than MIN_LABELS labelled sample lines it says the sample is too small
instead of giving a number to quote. The numbers describe THIS KB and THIS sample.
"""
import argparse
import hashlib
import math
import os
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import kb_coverage  # noqa: E402
import llm_judge  # noqa: E402
import verify_kb  # noqa: E402

SUB = os.path.join("agreement", "sample.yaml")
LABELS = ("supported", "partial", "unsupported")
MIN_LABELS = 30          # fewer labelled sample lines than this: no number is given
MIN_WRONG = 5            # fewer wrong lines than this: what each check catches is not meaningful
SWEEP = (0.1, 0.2, 0.3, 0.4, 0.5)


class AgreementError(ValueError):
    pass


def sample_path(kb, file=None):
    return os.path.abspath(file) if file else llm_judge.judge_dir(kb, SUB)


def load(kb, file=None):
    p = sample_path(kb, file)
    if not os.path.isfile(p):
        raise AgreementError("no sample yet; run: python3 judge_agreement.py draw %s" % kb)
    with open(p, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def save(kb, data, file=None):
    p = sample_path(kb, file)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    if not file:
        llm_judge.guard(kb)
    with open(p, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("# Fill in `human:` for each item: supported | partial | unsupported | unsure.\n"
                 "# Question: does the cited text support the claim AS WRITTEN? (Not: is the claim true.)\n")
        yaml.safe_dump(data, fh, sort_keys=False, allow_unicode=True, width=120)
    return p


def digest(*parts):
    return hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()


def share(claim, cited):
    """The lexical screen's number: how much of the smaller word set is shared. None when there is nothing to compare."""
    a, b = verify_kb.content_words(claim), verify_kb.content_words(cited or "")
    if len(a) < 4 or not b:
        return None
    return len(a & b) / float(min(len(a), len(b)))


def candidates(kb):
    """[(page, line number, request)]: one per cited line whose source can be shown to a judge."""
    chk = verify_kb.Checker(kb)
    out = []
    for rel, text in sorted(kb_coverage.page_files(kb).items()):
        seen = set()
        for req, _ in llm_judge.citation_requests(kb, text, rel, chk):
            if not req.get("id"):
                continue
            n = int(req["where"].rsplit(":", 1)[1])
            if n in seen:
                continue
            seen.add(n)
            out.append((rel, n, req))
    return out


def spread(cands, n, seed):
    """n candidates, round-robin over the pages in a fixed shuffled order, so one big page cannot fill the sample."""
    by_page = {}
    for rel, line, req in cands:
        by_page.setdefault(rel, []).append((digest(seed, rel, line), rel, line, req))
    pages = sorted(by_page, key=lambda r: digest(seed, r))
    queues = [sorted(by_page[r], key=lambda t: t[0]) for r in pages]
    out = []
    while len(out) < n and any(queues):
        for q in queues:
            if q and len(out) < n:
                out.append(q.pop(0)[1:])
    return out


def item(req, rel, line, layer, thr, control=False):
    quote = req.get("quote") or ""
    sh = share(req["claim"], quote or req.get("source_window"))
    return {"id": req["id"], "where": "%s:%d" % (rel, line), "layer": layer, "control": control, "claim": req["claim"],
            "source": req["source"], "cited_text": req["source_window"], "quote": quote,
            "lexical_share": None if sh is None else round(sh, 3), "judge": None,
            "human": "unsupported" if control else None, "note": ""}


def layer_fn():
    try:
        import audience
        pages = kb_coverage.page_files
        return lambda kb, rel: audience.layer_of(rel, pages(kb).get(rel, ""))[0]
    except Exception:
        return lambda kb, rel: ""


def draw(kb, n=50, seed="metis", controls=0, request_judge=True, file=None, threshold=None):
    kb = os.path.abspath(kb)
    thr = threshold if threshold is not None else verify_kb.ANSWER_SUPPORT_MIN
    cands = candidates(kb)
    if not cands:
        raise AgreementError("no cited lines in %s that a judge could be shown" % kb)
    layer = layer_fn()
    items = [item(req, rel, line, layer(kb, rel), thr) for rel, line, req in spread(cands, int(n), seed)]
    chosen = {i["id"] for i in items}
    made, requests = [], {c[2]["id"]: c[2] for c in cands}
    if controls:
        rest = [c for c in cands if c[2]["id"] not in chosen] or cands
        pool = spread(rest, int(controls) * 4, str(seed) + "-controls")
        for k in range(len(pool) // 2):
            if len(made) >= int(controls):
                break
            (rel_a, _, a), (rel_b, line_b, b) = pool[k], pool[len(pool) - 1 - k]
            if rel_a == rel_b or a["claim"] == b["claim"] or share(a["claim"], b.get("quote") or b.get("source_window")) is None:
                continue
            req = dict(b, claim=a["claim"])
            req["id"] = "C" + llm_judge.request_id(req)[1:]
            requests[req["id"]] = req
            made.append(item(req, rel_b, line_b, layer(kb, rel_b), thr, control=True))
    items += made
    if request_judge:
        fj = llm_judge.FileJudge(kb)
        for it in items:
            fj.judge(requests[it["id"]])   # writes the request file when there is no verdict yet
    data = {"drawn_from": kb, "seed": seed, "threshold": thr, "lines_available": len(cands), "items": items}
    return {"path": save(kb, data, file), "sample": len(items) - len(made), "controls": len(made), "available": len(cands)}


def refresh_judge(kb, items):
    """Fill `judge` from the verdict files a session wrote; leave it empty where there is none yet."""
    fj = llm_judge.FileJudge(kb)
    for it in items:
        if it.get("judge"):
            continue
        try:
            v = fj.judge({"id": it["id"]})
        except llm_judge.JudgeError:
            v = None
        if v:
            it["judge"] = v["verdict"]


# ---- the numbers ---------------------------------------------------------------------------------------
def wilson(k, n, z=1.96):
    if not n:
        return None
    p = k / float(n)
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return round(max(0.0, (c - m) / d), 3), round(min(1.0, (c + m) / d), 3)


def bad(label):
    return label in ("partial", "unsupported")


def metrics(pairs):
    """pairs: (the check flagged it, the person says it is bad). Agreement, what it caught, what it flagged by mistake."""
    n = len(pairs)
    tp = sum(1 for f, b in pairs if f and b)
    fp = sum(1 for f, b in pairs if f and not b)
    fn = sum(1 for f, b in pairs if not f and b)
    tn = sum(1 for f, b in pairs if not f and not b)
    return {"n": n, "agree": tp + tn, "agreement": round((tp + tn) / float(n), 3) if n else None, "interval": wilson(tp + tn, n),
            "caught": tp, "missed": fn, "false_alarms": fp, "good_passed": tn,
            "recall": round(tp / float(tp + fn), 3) if tp + fn else None,
            "false_alarm_rate": round(fp / float(fp + tn), 3) if fp + tn else None}


def score(kb, file=None, threshold=None):
    kb = os.path.abspath(kb)
    data = load(kb, file)
    items = data.get("items") or []
    refresh_judge(kb, items)
    thr = threshold if threshold is not None else data.get("threshold", verify_kb.ANSWER_SUPPORT_MIN)
    sample = [i for i in items if not i.get("control")]
    labelled = [i for i in sample if i.get("human") in LABELS]
    controls = [i for i in items if i.get("control")]
    wrong = sum(1 for i in labelled if bad(i["human"]))
    rep = {"threshold": thr, "drawn": len(sample), "labelled": len(labelled), "unsure": sum(1 for i in sample if i.get("human") == "unsure"),
           "wrong": wrong, "enough": len(labelled) >= MIN_LABELS, "wrong_enough": wrong >= MIN_WRONG, "min_labels": MIN_LABELS}
    rep["lexical"] = metrics([(i["lexical_share"] < thr, bad(i["human"])) for i in labelled if i.get("lexical_share") is not None])
    rep["judge"] = metrics([(bad(i["judge"]), bad(i["human"])) for i in labelled if i.get("judge") in LABELS])
    rep["judge_exact"] = {"n": sum(1 for i in labelled if i.get("judge") in LABELS),
                          "same_verdict": sum(1 for i in labelled if i.get("judge") == i["human"])}
    rep["sweep"] = {t: metrics([(i["lexical_share"] < t, bad(i["human"])) for i in labelled if i.get("lexical_share") is not None])
                    for t in SWEEP}
    rep["controls"] = {"n": len(controls),
                       "lexical_screened": sum(1 for i in controls if i.get("lexical_share") is not None),
                       "lexical_caught": sum(1 for i in controls if i.get("lexical_share") is not None and i["lexical_share"] < thr),
                       "judge_answered": sum(1 for i in controls if i.get("judge") in LABELS),
                       "judge_caught": sum(1 for i in controls if bad(i.get("judge")))}
    return rep


def pct(v):
    return "n/a" if v is None else "%d%%" % round(v * 100)


def fmt(m, who):
    if not m["n"]:
        return "  %-7s nothing to compare yet" % who
    iv = "" if not m["interval"] else " (95%% interval %d-%d%%)" % (round(m["interval"][0] * 100), round(m["interval"][1] * 100))
    return ("  %-7s agrees with the person on %d of %d = %s%s; caught %d of %d wrong lines (%s); flagged %d of %d good lines (%s)"
            % (who, m["agree"], m["n"], pct(m["agreement"]), iv, m["caught"], m["caught"] + m["missed"], pct(m["recall"]),
               m["false_alarms"], m["false_alarms"] + m["good_passed"], pct(m["false_alarm_rate"])))


def report(rep):
    out = ["sample: %d lines drawn, %d labelled by a person (%d unsure), %d of them wrong or only partly supported"
           % (rep["drawn"], rep["labelled"], rep["unsure"], rep["wrong"])]
    c = rep["controls"]
    if c["n"]:
        out.append("controls (a real citation under an unrelated claim): the screen caught %d of %d, the judge %d of %d"
                   % (c["lexical_caught"], c["lexical_screened"], c["judge_caught"], c["judge_answered"]))
    if not rep["enough"]:
        out.append("TOO SMALL: %d labelled lines; at least %d are needed before any agreement figure is worth quoting. "
                   "Label more items in the worksheet." % (rep["labelled"], rep["min_labels"]))
    else:
        out += [fmt(rep["lexical"], "screen"), fmt(rep["judge"], "judge")]
        if not rep["wrong_enough"]:
            out.append("Only %d wrong lines in the sample: how many wrong lines each check catches is not meaningful yet. Agreement is "
                       "mostly 'both said fine'." % rep["wrong"])
        je = rep["judge_exact"]
        if je["n"]:
            out.append("  judge gave the same three-way verdict as the person on %d of %d" % (je["same_verdict"], je["n"]))
        out.append("  screen threshold sweep (share needed): " + "; ".join(
            "%.1f: caught %s, flagged %s of good" % (t, pct(m["recall"]), pct(m["false_alarm_rate"])) for t, m in rep["sweep"].items()))
    out.append("These figures describe this KB and this sample. They say how often the checks agree with a person reading the cited "
               "text; they do not say the lines are true.")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("draw")
    d.add_argument("kb")
    d.add_argument("--n", type=int, default=50)
    d.add_argument("--seed", default="metis")
    d.add_argument("--controls", type=int, default=0)
    d.add_argument("--no-judge", action="store_true", help="do not write judge requests")
    d.add_argument("--file")
    d.add_argument("--threshold", type=float)
    s = sub.add_parser("score")
    s.add_argument("kb")
    s.add_argument("--file")
    s.add_argument("--threshold", type=float)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "draw":
            r = draw(a.kb, a.n, a.seed, a.controls, not a.no_judge, a.file, a.threshold)
            print("worksheet: %s\n%d sample lines (of %d cited lines) and %d control lines. Fill in `human:` for each item."
                  % (r["path"], r["sample"], r["available"], r["controls"]))
            return 0
        print(report(score(a.kb, a.file, a.threshold)))
        return 0
    except (AgreementError, llm_judge.JudgeError, OSError) as err:
        print("error: %s" % err, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
