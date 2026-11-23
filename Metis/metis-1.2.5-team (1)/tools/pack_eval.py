#!/usr/bin/env python3
"""Retrieval benchmark for context packs: does the pack for a golden question carry the pages a good answer cites?

    python3 pack_eval.py <kb> [--budget 6000] [--k 5] [--min-recall 0.8] [--min-precision 0.0] [--json]
                              [--compare-names-only] [--baseline FILE] [--write-baseline FILE]

For every golden question (golden.py) that names the KB files a good answer cites (`cite`), it builds the pack from the question
text alone (`context_pack.build(task=question)`) and reports
  recall      cited pages that are in the pack / cited pages
  precision   cited pages in the pack / pages in the pack
  hit@k       1 if at least one cited page is among the first k pages of the pack, else 0
  full-tier   share of the pack's pages taken whole (a pack of headlines only is a weak pack)
and the means over all questions. Exit 1 when the mean recall is below --min-recall (or mean precision below --min-precision),
or, with --baseline, when either mean is lower than the saved one by more than 0.02: run it in CI after every KB build.
--compare-names-only also runs the old behaviour (graph objects only, no search) so the gain of the search path is a number,
not a claim. Nothing is written to the KB; telemetry is not recorded.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import context_pack  # noqa: E402
import golden  # noqa: E402

TOLERANCE = 0.02


def mean(xs):
    return round(sum(xs) / len(xs), 4) if xs else 0.0


def score_one(cited, files, tiers, k):
    cited, files = list(dict.fromkeys(cited)), list(files)
    got = [c for c in cited if c in files]
    return {"recall": len(got) / len(cited) if cited else 0.0,
            "precision": len(got) / len(files) if files else 0.0,
            "hit_at_k": 1 if any(f in cited for f in files[:k]) else 0,
            "full_tier": (sum(1 for f in files if tiers.get(f) == "full") / len(files)) if files else 0.0,
            "missing": [c for c in cited if c not in files]}


def run_one(kb, question, cited, budget, k, names_only=False):
    try:
        if names_only:
            nodes = context_pack.seeds_from_text(question, context_pack.graph_nodes(kb))
            pack = context_pack.build(kb, seeds=nodes, files=[], budget=budget, stale_marks=False, signals=False) if nodes else None
        else:
            pack = context_pack.build(kb, task=question, budget=budget, stale_marks=False, signals=False)
    except context_pack.PackError as exc:
        return dict(score_one(cited, [], {}, k), error=str(exc))
    if pack is None:
        return score_one(cited, [], {}, k)
    return score_one(cited, pack["files"], pack["tiers"], k)


def evaluate(kb, budget=6000, k=5, compare=False):
    rows, skipped = [], []
    for g in golden.load(kb).get("golden") or []:
        cited = [c for c in g.get("cite") or [] if c.endswith(".md")]
        if not cited:
            skipped.append(g["id"])
            continue
        row = {"id": g["id"], "question": g["question"], "cited": cited}
        row.update(run_one(kb, g["question"], cited, budget, k))
        if compare:
            row["names_only"] = run_one(kb, g["question"], cited, budget, k, names_only=True)
        rows.append(row)
    keys = ("recall", "precision", "hit_at_k", "full_tier")
    out = {"budget": budget, "k": k, "questions": len(rows), "skipped_no_cited_page": skipped,
           "mean": {m: mean([r[m] for r in rows]) for m in keys}, "rows": rows}
    if compare:
        out["mean_names_only"] = {m: mean([r["names_only"][m] for r in rows]) for m in keys}
    return out


def verdict(result, min_recall, min_precision, baseline=None):
    problems = []
    if not result["questions"]:
        problems.append("no golden question names a page to cite: add some with golden.py add --cite")
    m = result["mean"]
    if m["recall"] < min_recall:
        problems.append("mean recall %.3f is below %.3f" % (m["recall"], min_recall))
    if m["precision"] < min_precision:
        problems.append("mean precision %.3f is below %.3f" % (m["precision"], min_precision))
    if baseline:
        for key in ("recall", "precision"):
            if m[key] < baseline.get("mean", {}).get(key, 0.0) - TOLERANCE:
                problems.append("mean %s %.3f fell from the baseline %.3f" % (key, m[key], baseline["mean"][key]))
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("kb")
    ap.add_argument("--budget", type=int, default=6000)
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--min-recall", type=float, default=0.8)
    ap.add_argument("--min-precision", type=float, default=0.0)
    ap.add_argument("--compare-names-only", action="store_true")
    ap.add_argument("--baseline", help="a file written by --write-baseline; fail if the means fall below it")
    ap.add_argument("--write-baseline")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    res = evaluate(a.kb, a.budget, a.k, a.compare_names_only)
    base = None
    if a.baseline:
        with open(a.baseline, encoding="utf-8") as fh:
            base = json.load(fh)
    problems = verdict(res, a.min_recall, a.min_precision, base)
    if a.write_baseline:
        with open(a.write_baseline, "w", encoding="utf-8", newline="\n") as fh:
            json.dump({"budget": res["budget"], "k": res["k"], "mean": res["mean"]}, fh, indent=2)
    if a.json:
        print(json.dumps(dict(res, problems=problems), indent=2))
    else:
        m = res["mean"]
        print("%d golden questions scored (budget %d, k=%d): recall %.3f, precision %.3f, hit@%d %.3f, full-tier %.3f" % (
            res["questions"], a.budget, a.k, m["recall"], m["precision"], a.k, m["hit_at_k"], m["full_tier"]))
        if "mean_names_only" in res:
            n = res["mean_names_only"]
            print("graph objects only (the old behaviour): recall %.3f, precision %.3f, hit@%d %.3f" % (
                n["recall"], n["precision"], a.k, n["hit_at_k"]))
        for r in res["rows"]:
            if r["missing"]:
                print("  %s missing %s" % (r["id"], ", ".join(r["missing"])))
        if res["skipped_no_cited_page"]:
            print("not scored (no cited page): %s" % ", ".join(res["skipped_no_cited_page"]))
        for p in problems:
            print("FAIL: " + p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
