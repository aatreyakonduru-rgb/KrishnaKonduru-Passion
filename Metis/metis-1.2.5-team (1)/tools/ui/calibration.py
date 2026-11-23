#!/usr/bin/env python3
"""Is a confidence band worth anything? Check each band against the likes and dislikes people gave.

    python3 calibration.py <kb>

Every answer the UI keeps is an ask record in <kb>/.metis/asks/A-xxxx.yaml with a confidence band (High, Medium, Low, None) and,
once a person rated it, a rating (up or down). Per band this counts the answers, the rated ones, the liked and disliked share and
a 95% Wilson interval for the liked share. High is called better than Low only when each has at least MIN_RATED rated answers and
the two intervals do not overlap. Below that the statement says "not enough ratings yet". Standard library only.

golden.py keeps the golden questions (GOLDEN.yaml) but not the result of scoring them, so no golden result is used here. The
number of golden questions is reported so the page can say so.
"""
import datetime
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import answers  # noqa: E402
import golden  # noqa: E402

BANDS = ("High", "Medium", "Low", "None")
MIN_RATED = 10


def wilson(k, n, z=1.96):
    """95% Wilson score interval (low, high) for k successes in n trials, or None when n is 0."""
    if n <= 0:
        return None
    p, z2 = k / n, z * z
    centre = (p + z2 / (2 * n)) / (1 + z2 / n)
    half = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / (1 + z2 / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def pct(x):
    return "%d%%" % round(x * 100)


def span(ci):
    return "%s to %s" % (pct(ci[0]), pct(ci[1]))


def verdict(rows):
    """One honest sentence on whether High beats Low. rows is the list from bands()."""
    by = {r["band"]: r for r in rows}
    hi, lo = by["High"], by["Low"]
    if hi["rated"] < MIN_RATED or lo["rated"] < MIN_RATED:
        return ("Not enough ratings yet. Rated answers: High %d, Low %d. Each needs at least %d before "
                "Metis says whether High is better than Low." % (hi["rated"], lo["rated"], MIN_RATED))
    h, lw = hi["ci"], lo["ci"]
    nums = "High was liked %s of %d rated (95%% range %s); Low %s of %d rated (95%% range %s)." % (
        pct(hi["liked_share"]), hi["rated"], span(h), pct(lo["liked_share"]), lo["rated"], span(lw))
    if h[0] > lw[1]:
        return "High is better than Low. " + nums + " The ranges do not overlap."
    if lw[0] > h[1]:
        return "Low did better than High, so the labels do not match what people think of the answers. " + nums + " The ranges do not overlap."
    return "No clear difference between High and Low yet. " + nums + " The ranges overlap, so these ratings cannot tell them apart."


def bands(kb):
    """{"rows": one per band, "verdict": text, "unscored": answers with no band, "waiting": asks not answered yet, "golden": int}."""
    rows = {b: {"band": b, "answers": 0, "rated": 0, "liked": 0, "disliked": 0} for b in BANDS}
    unscored = waiting = 0
    for r in answers.all_asks(kb):
        if not r.get("answer_file"):
            waiting += 1
            continue
        band = (r.get("confidence") or {}).get("band")
        if band not in rows:
            unscored += 1
            continue
        row = rows[band]
        row["answers"] += 1
        if r.get("rating") in ("up", "down"):
            row["rated"] += 1
            row["liked" if r["rating"] == "up" else "disliked"] += 1
    out = []
    for b in BANDS:
        row = rows[b]
        n = row["rated"]
        row["liked_share"] = row["liked"] / n if n else None
        row["disliked_share"] = row["disliked"] / n if n else None
        row["ci"] = wilson(row["liked"], n)
        row["enough"] = n >= MIN_RATED
        out.append(row)
    try:
        n_golden = len(golden.load(kb).get("golden") or [])
    except Exception:
        n_golden = 0
    return {"rows": out, "verdict": verdict(out), "unscored": unscored, "waiting": waiting, "golden": n_golden}


def per_week(kb, last=26):
    """[(Monday of the week, answers)] for every week from the first answer to the last, empty weeks included."""
    days = []
    for r in answers.all_asks(kb):
        if r.get("answer_file"):
            try:
                days.append(datetime.date.fromisoformat(str(r.get("on"))[:10]))
            except ValueError:
                continue
    if not days:
        return []
    monday = lambda d: d - datetime.timedelta(days=d.weekday())  # noqa: E731
    counts = {}
    for d in days:
        counts[monday(d)] = counts.get(monday(d), 0) + 1
    out, w = [], monday(min(days))
    while w <= monday(max(days)):
        out.append((w.isoformat(), counts.get(w, 0)))
        w += datetime.timedelta(days=7)
    return out[-last:]


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print(__doc__)
        return 2
    kb = os.path.abspath(args[0])
    rep = bands(kb)
    for r in rep["rows"]:
        print("%-6s answers %3d  rated %3d  liked %3d  disliked %3d  %s" % (
            r["band"], r["answers"], r["rated"], r["liked"], r["disliked"], span(r["ci"]) if r["ci"] else "no ratings"))
    print(rep["verdict"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
