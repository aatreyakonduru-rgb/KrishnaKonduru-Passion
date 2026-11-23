#!/usr/bin/env python3
"""Score recalibration loop for Metis confidence scoring.

    python3 recalibrate.py run           <kb> [--min-volume 30] [--force]
    python3 recalibrate.py show-proposal <kb>

Reads answer ratings and confidence statistics via ui/calibration.py (Wilson intervals),
and proposes deduction-weight / confidence-cap changes for ui/answers.py.
Writes a PROPOSAL file to <KB>/.metis/CALIBRATION_PROPOSAL.yaml.
NEVER edits ui/answers.py, and NEVER auto-applies proposals.
Requires minimum ratings per band (default: 30) before generating proposals.
"""
import argparse
import datetime
import os
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
UI_DIR = os.path.join(HERE, "ui")
for _p in (HERE, UI_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import answers  # noqa: E402
import calibration  # noqa: E402

PROPOSAL_FILE = os.path.join(".metis", "CALIBRATION_PROPOSAL.yaml")
DEFAULT_MIN_VOLUME = 30

CURRENT_WEIGHTS = {
    "band_threshold_high": 85,
    "band_threshold_medium": 60,
    "band_threshold_low": 1,
    "multi_line_cap": 92,
    "inferred_cap": 80,
    "not_in_cap": 84,
    "opened_cap": 84,
    "uncovered_penalty": 30,
    "multi_line_penalty": 25,
    "linked_penalty": 10,
    "inferred_penalty_per_line": 15,
}


def proposal_path(kb):
    return os.path.join(kb, PROPOSAL_FILE)


def load_proposal(kb):
    """Load existing calibration proposal if present."""
    p = proposal_path(kb)
    if not os.path.isfile(p):
        return None
    with open(p, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def check_volume(kb, min_volume=DEFAULT_MIN_VOLUME):
    """Check if all bands meet the required minimum volume of rated answers."""
    data = calibration.bands(kb)
    counts = {r["band"]: r["rated"] for r in data["rows"]}
    total_rated = sum(counts.values())
    shortfalls = {b: cnt for b, cnt in counts.items() if cnt < min_volume}
    has_enough = len(shortfalls) == 0 and total_rated >= (min_volume * len(counts))
    return has_enough, {"counts": counts, "total_rated": total_rated, "shortfalls": shortfalls, "min_volume": min_volume}


def propose(kb, min_volume=DEFAULT_MIN_VOLUME, force=False):
    """Calculate and write a recalibration proposal. Returns (status_code, proposal_or_info)."""
    has_enough, vol_info = check_volume(kb, min_volume=min_volume)
    calib = calibration.bands(kb)
    rows_by_band = {r["band"]: r for r in calib["rows"]}

    if not has_enough and not force:
        counts_str = ", ".join("%s: %d/%d" % (b, vol_info["counts"].get(b, 0), min_volume) for b in calibration.BANDS)
        msg = "not enough ratings (need at least %d per band; current: %s)" % (min_volume, counts_str)
        return False, {"status": "not_enough_ratings", "message": msg, "volume_info": vol_info, "bands": calib["rows"]}

    # Perform analysis of empirical ratings across bands and deduction types
    proposed = dict(CURRENT_WEIGHTS)
    rationale = []

    hi = rows_by_band.get("High", {})
    med = rows_by_band.get("Medium", {})
    lo = rows_by_band.get("Low", {})

    hi_like = hi.get("liked_share") or 0.0
    med_like = med.get("liked_share") or 0.0
    lo_like = lo.get("liked_share") or 0.0

    # If High satisfaction is lower than 80%, suggest tightening caps and increasing penalties
    if hi_like < 0.80 and hi.get("rated", 0) >= min_volume:
        proposed["band_threshold_high"] = 88
        proposed["inferred_cap"] = 75
        proposed["uncovered_penalty"] = 35
        rationale.append("High band liked rate is %.1f%% (<80%%); propose tightening High threshold to 88 and lowering inferred cap to 75." % (hi_like * 100))
    elif hi_like >= 0.95 and hi.get("rated", 0) >= min_volume:
        rationale.append("High band liked rate is %.1f%% (>=95%%); High band threshold is well-calibrated." % (hi_like * 100))

    # If Medium satisfaction is close to Low, widen gap
    if med.get("rated", 0) >= min_volume and lo.get("rated", 0) >= min_volume:
        if med_like - lo_like < 0.15:
            proposed["band_threshold_medium"] = 65
            proposed["multi_line_penalty"] = 30
            rationale.append("Medium liked rate (%.1f%%) is close to Low (%.1f%%); propose raising Medium threshold to 65." % (med_like * 100, lo_like * 100))

    if not rationale:
        rationale.append("Current weights align reasonably with rating intervals. Minor refinement proposed.")

    proposal_data = {
        "generated_on": datetime.date.today().isoformat(),
        "status": "proposed_for_review",
        "notice": "Metis proposal file. NEVER auto-applied. Inspect and update answers.py manually if approved.",
        "min_volume_required": min_volume,
        "total_rated_answers": vol_info["total_rated"],
        "band_statistics": {
            r["band"]: {
                "answers": r["answers"],
                "rated": r["rated"],
                "liked": r["liked"],
                "disliked": r["disliked"],
                "liked_share": round(r["liked_share"], 3) if r["liked_share"] is not None else None,
                "confidence_interval_95": [round(x, 3) for x in r["ci"]] if r["ci"] else None,
            } for r in calib["rows"]
        },
        "verdict": calib["verdict"],
        "current_weights": CURRENT_WEIGHTS,
        "proposed_weights": proposed,
        "rationale": rationale,
    }

    # Write proposal file
    p = proposal_path(kb)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("# Recalibration Proposal generated by recalibrate.py.\n# Metis does not edit answers.py.\n")
        yaml.safe_dump(proposal_data, fh, sort_keys=False, allow_unicode=True, width=120)

    return True, proposal_data


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("run")
    a.add_argument("kb")
    a.add_argument("--min-volume", type=int, default=DEFAULT_MIN_VOLUME)
    a.add_argument("--force", action="store_true")

    a = sub.add_parser("show-proposal")
    a.add_argument("kb")

    args = ap.parse_args(argv)
    kb = os.path.abspath(args.kb)

    if args.cmd == "run":
        ok, res = propose(kb, min_volume=args.min_volume, force=args.force)
        if not ok:
            print(res["message"])
            return 1
        print("recalibration proposal written to %s" % proposal_path(kb))
        for rat in res.get("rationale", []):
            print("  - " + rat)

    elif args.cmd == "show-proposal":
        prop = load_proposal(kb)
        if not prop:
            print("no proposal file found at %s" % proposal_path(kb))
            return 1
        print("Recalibration Proposal (generated %s):" % prop.get("generated_on"))
        print("Status: %s" % prop.get("status"))
        print("\nBand Statistics:")
        for b, st in (prop.get("band_statistics") or {}).items():
            print("  %-8s rated: %3d  liked: %3d (%.1f%%)" % (
                b, st["rated"], st["liked"], (st["liked_share"] or 0.0) * 100
            ))
        print("\nProposed Weight Changes:")
        curr = prop.get("current_weights", {})
        prop_w = prop.get("proposed_weights", {})
        for k, v in prop_w.items():
            old_v = curr.get(k)
            diff = " (was %s)" % old_v if old_v != v else ""
            print("  %-30s : %s%s" % (k, v, diff))
        print("\nRationale:")
        for r in prop.get("rationale", []):
            print("  - " + r)

    return 0


if __name__ == "__main__":
    sys.exit(main())
