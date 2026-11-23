#!/usr/bin/env python3
"""Reviewer track record, trust weights and advisory routing for Metis knowledge bases.

    python3 reviewer_stats.py stats        <kb> [--reviewer NAME]
    python3 reviewer_stats.py route        <kb> <team_or_file>
    python3 reviewer_stats.py trust        <kb> [--reviewer NAME]     per reviewer and area: counts, formula, weight
    python3 reviewer_stats.py contributors <kb>                       track record of people who suggest edits

Parses .metis/CERTIFICATIONS.log to compute reviewer history (certified files, rejected
batches/files, page reviews) and joins with feedback/telemetry to identify later-disliked
pages. Shows pure numbers only — no hidden score is used to auto-approve.
Trust weight is advisory text in review queue output.

Trust weights (`trust`): per reviewer and per area (the owning team, else the top folder), from raw counts only: certifications,
certified pages later disliked / flagged stale / in a confirmed contradiction, reversals, and a Wilson interval on the
"later problem" rate. Every weight is printed with the counts that produced it and the formula (FORMULA below). Below the
minimum volume (default 20 decisions per reviewer and area) there is no weight: "not enough history". The policy is the
profile key `review.trust` (min_decisions, max_problem_rate, lookback_days, ...); absent means advisory only. Nothing here
certifies, approves or skips anything: a weight is only read by review_queue.py to order suggestions and to bound sampling.
"""
import argparse
import datetime
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import feedback  # noqa: E402
import kb_gate  # noqa: E402
import page_suggest  # noqa: E402
import telemetry  # noqa: E402

LOG_FILE = os.path.join(".metis", "CERTIFICATIONS.log")


def log_path(kb):
    return os.path.join(kb, LOG_FILE)


def parse_log(kb):
    """Parse .metis/CERTIFICATIONS.log into structured event rows."""
    p = log_path(kb)
    if not os.path.isfile(p):
        return []
    rows = []
    with open(p, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            cols = line.split("\t")
            if len(cols) < 3:
                continue
            dt = cols[0]
            action = cols[1]
            name = cols[2]
            role = cols[3] if len(cols) > 3 else ""
            batch = cols[4] if len(cols) > 4 else ""
            detail = cols[5:] if len(cols) > 5 else []
            rows.append({
                "timestamp": dt,
                "action": action,
                "name": kb_gate.clean(name),
                "role": role,
                "batch": batch,
                "detail": detail,
                "raw_line": line,
            })
    return rows


def reviewer_stats(kb, reviewer=None):
    """Compute track record for all reviewers or a specific reviewer."""
    rows = parse_log(kb)
    stats = {}

    for r in rows:
        name = r["name"]
        if not name:
            continue
        entry = stats.setdefault(name.lower(), {
            "name": name,
            "roles": set(),
            "certified_count": 0,
            "certified_files": set(),
            "rejected_count": 0,
            "reviews_count": 0,
            "locks_count": 0,
            "actions": [],
        })
        if r["role"]:
            entry["roles"].add(r["role"])
        entry["actions"].append(r)

        if r["action"] in ("certify", "certify-removal"):
            entry["certified_count"] += 1
            if r["detail"]:
                file_rel = r["detail"][0]
                entry["certified_files"].add(file_rel)
        elif r["action"] == "reject":
            entry["rejected_count"] += 1
        elif r["action"] == "review":
            entry["reviews_count"] += 1
        elif r["action"] == "lock":
            entry["locks_count"] += 1

    # Join with feedback to check later dislikes
    rated_files = telemetry.rated(kb)
    for k, entry in stats.items():
        entry["roles"] = sorted(entry["roles"])
        entry["certified_files"] = sorted(entry["certified_files"])
        disliked_pages = []
        liked_pages = []
        for f in entry["certified_files"]:
            m = rated_files.get(f)
            if m:
                if m.get("down", 0) > 0:
                    disliked_pages.append({"file": f, "down": m["down"], "up": m.get("up", 0)})
                elif m.get("up", 0) > 0:
                    liked_pages.append({"file": f, "up": m["up"]})
        entry["later_disliked_pages"] = disliked_pages
        entry["later_disliked_count"] = len(disliked_pages)
        entry["later_liked_count"] = len(liked_pages)

    if reviewer:
        return stats.get(kb_gate.clean(reviewer).lower())
    return stats


def advisory_text(stats_entry):
    """Generate advisory text representation of a reviewer's track record."""
    if not stats_entry:
        return "no prior certification history"
    return "%s: %d certified, %d rejected, %d page-reviews, %d later-disliked pages" % (
        stats_entry["name"],
        stats_entry["certified_count"],
        stats_entry["rejected_count"],
        stats_entry["reviews_count"],
        stats_entry["later_disliked_count"],
    )


def suggest_routing(kb, team_or_file):
    """Suggest reviewers with their numbers for a team or file path."""
    all_stats = reviewer_stats(kb)
    leads = kb_gate.certifiers(kb)
    candidates = {}

    target = team_or_file.strip().replace("\\", "/").lstrip("/")

    # Check pool for this file or team
    team_obj = None
    for t in kb_gate.teams(kb):
        if t["name"].lower() == target.lower():
            team_obj = t
            break

    if not team_obj and "/" in target or target.endswith(".md"):
        team_obj = kb_gate.team_of(kb, target)

    # Eligible pool: leads + team approvers
    approvers = team_obj["approvers"] if team_obj else []
    for a in approvers:
        candidates[a.lower()] = a
    for lead_name, _ in leads.values():
        candidates[lead_name.lower()] = lead_name

    suggestions = []
    for key, name in sorted(candidates.items()):
        st = all_stats.get(key)
        # Count past certifications in this target area
        area_matches = 0
        if st:
            for f in st["certified_files"]:
                if team_obj:
                    if any(kb_gate.owns(g, f) for g in team_obj["owns"]):
                        area_matches += 1
                elif target and f.startswith(target.rstrip("/") + "/"):
                    area_matches += 1

        total_cert = st["certified_count"] if st else 0
        total_rej = st["rejected_count"] if st else 0
        total_rev = st["reviews_count"] if st else 0
        disliked = st["later_disliked_count"] if st else 0

        suggestions.append({
            "name": name,
            "area_certifications": area_matches,
            "total_certified": total_cert,
            "total_rejected": total_rej,
            "total_reviews": total_rev,
            "later_disliked_pages": disliked,
            "advisory": advisory_text(st) if st else "%s: no prior certification record" % name,
        })

    # Sort suggestions by area_certifications descending, then total_certified descending
    return sorted(suggestions, key=lambda s: (-s["area_certifications"], -s["total_certified"], s["name"]))


# ---- trust weights ---------------------------------------------------------------------------------
# Every number below is a count taken from CERTIFICATIONS.log, the likes and dislikes, the stale check or the contradiction report.
# The weight is one formula over those counts, printed next to them. Nothing here certifies, approves or skips a review.
FORMULA = (
    "area = the team that owns the file (gate.teams), else its top folder. decisions = certifications + certified removals "
    "by this reviewer in this area within the lookback. pages held = files whose latest certification in the log is this "
    "reviewer's and that were not removed since. problem pages = held pages that were later disliked (a dislike dated on or "
    "after the certification), flagged stale by the source check, or are in a confirmed contradiction (a lead's verdict in "
    "kb_contradict). problem rate = problem pages / pages held, with a 95% Wilson interval (lower and upper bound). "
    "reversals = files this reviewer certified that a different person later removed by certified removal; reversal rate = "
    "reversals / certifications. weight = 1 - Wilson upper bound of the problem rate (the share of certified pages that stay "
    "clean, read cautiously: few pages gives a low weight). With fewer than min_decisions decisions there is no weight: "
    "'not enough history'. Rejections are logged per batch without file names, so they are shown per reviewer, not per area.")

DEFAULT_POLICY = {"min_decisions": 20, "max_problem_rate": 0.10, "max_reversal_rate": 0.10, "lookback_days": 365,
                  "sample_share": None, "floor_files": 3, "floor_share": 0.10, "fast_lane_max_lines": 10}
NOT_ENOUGH = "not enough history"


def policy(kb):
    """The trust policy from the profile key review.trust, with the defaults filled in.
    `active` is False when the key is absent: weights are then advisory only and nothing is ever reduced."""
    review = kb_gate.profile(kb).get("review")
    raw = review.get("trust") if isinstance(review, dict) else None
    pol = dict(DEFAULT_POLICY, active=isinstance(raw, dict), notes=[])
    if not isinstance(raw, dict):
        return pol
    spec = {"min_decisions": (int, 1, None), "max_problem_rate": (float, 0, 1), "max_reversal_rate": (float, 0, 1),
            "lookback_days": (int, 0, None), "sample_share": (float, 0.0001, 1), "floor_files": (int, 1, None),
            "floor_share": (float, 0, 1), "fast_lane_max_lines": (int, 0, None)}
    for k, (typ, lo, hi) in spec.items():
        if k not in raw or raw[k] is None:
            continue
        try:
            v = typ(raw[k])
            if isinstance(raw[k], bool) or v < lo or (hi is not None and v > hi):
                raise ValueError
            pol[k] = v
        except (TypeError, ValueError):
            pol["notes"].append("review.trust.%s = %r is not valid; the default is used" % (k, raw[k]))
    return pol


def wilson(k, n, z=1.96):
    """(lower, upper) Wilson score bounds for k of n, or (None, None) when n is 0."""
    if n <= 0:
        return None, None
    p = k / float(n)
    denom = 1 + z * z / n
    centre = (p + z * z / (2.0 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4.0 * n * n)) / denom
    return round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)


def area_of(kb, rel):
    """The area a file belongs to: its owning team, else its top folder."""
    t = kb_gate.team_of(kb, rel)
    if t:
        return t["name"]
    parts = str(rel).split("/")
    return parts[0] if len(parts) > 1 else "(root)"


def when_of(row):
    try:
        return datetime.datetime.strptime(row["timestamp"], "%Y-%m-%d %H:%M").date()
    except (ValueError, TypeError):
        return None


def problem_signals(kb):
    """Later problems per page, from feedback, the stale check and the contradiction report. Each source that is missing or
    fails is left out and named in notes; the rest still count."""
    sig = {"disliked": {}, "stale": set(), "contradicted": set(), "notes": []}
    try:
        for f in feedback.load(kb).get("feedback") or []:
            if f.get("rating") == "down" and f.get("status") != "declined":
                for rel in f.get("cited_files") or []:
                    sig["disliked"].setdefault(rel, []).append(str(f.get("on") or ""))
    except Exception as exc:
        sig["notes"].append("dislikes not available: %s" % exc)
    try:
        import page_owners
        rep = page_owners.stale_report(kb)
        sig["stale"] = {s["page"] for s in rep.get("stale_sources") or []}
        sig["notes"] += ["stale check: %s" % n for n in rep.get("notes") or []]
    except Exception as exc:
        sig["notes"].append("stale check not available: %s" % exc)
    try:
        import kb_contradict
        for e in (kb_contradict.load_report(kb).get("contradictions") or []):
            if e.get("status") == "confirmed":
                sig["contradicted"] |= {e["a"]["page"], e["b"]["page"]}
    except Exception as exc:
        sig["notes"].append("contradiction report not available: %s" % exc)
    return sig


def explain(row):
    """The counts behind one weight, in words."""
    if row["weight"] is None:
        return "%s: %d decisions (%d certified, %d removals certified); the minimum is %d" % (
            row["status"], row["decisions"], row["certifications"], row["removals"], row["min_decisions"])
    return ("%d of %d held pages had a later problem (%d disliked, %d stale, %d contradicted); problem rate %.1f%%, Wilson "
            "%.1f%% to %.1f%%; weight = 1 - %.3f = %.3f; reversals %d of %d certifications" % (
                row["problem_pages"], row["pages_held"], row["disliked"], row["stale"], row["contradicted"],
                100 * row["problem_rate"], 100 * row["wilson_low"], 100 * row["wilson_high"], row["wilson_high"], row["weight"],
                row["reversals"], row["certifications"]))


def trust_table(kb, today=None, signals=None):
    """Transparent trust weights per reviewer and area, from raw counts only.
    {policy, formula, rows: [...], rejections: {name: n}, notes}. A row without enough history has weight None."""
    pol = policy(kb)
    today = today or datetime.date.today()
    cutoff = today - datetime.timedelta(days=pol["lookback_days"]) if pol["lookback_days"] else None
    sig = signals or problem_signals(kb)
    entries, holder, rejections = {}, {}, {}

    def inwin(when):
        return cutoff is None or when is None or when >= cutoff

    for r in parse_log(kb):
        when = when_of(r)
        key = r["name"].lower()
        if r["action"] == "reject":
            if inwin(when):
                rejections[r["name"]] = rejections.get(r["name"], 0) + 1
            continue
        if r["action"] not in ("certify", "certify-removal") or not r["detail"]:
            continue
        rel = r["detail"][0].strip().replace("\\", "/")
        area = area_of(kb, rel)
        ek = (key, area)
        if r["action"] == "certify":
            if inwin(when):
                e = entries.setdefault(ek, {"reviewer": r["name"], "area": area, "certifications": 0, "removals": 0, "reversals": 0, "held": {}})
                e["certifications"] += 1
            holder[rel] = {"key": ek, "inwin": inwin(when), "on": when}
        else:
            if inwin(when):
                e = entries.setdefault(ek, {"reviewer": r["name"], "area": area, "certifications": 0, "removals": 0, "reversals": 0, "held": {}})
                e["removals"] += 1
            h = holder.pop(rel, None)
            if h and h["inwin"] and h["key"][0] != key:
                entries[h["key"]]["reversals"] += 1
    for rel, h in holder.items():
        if h["inwin"]:
            entries[h["key"]]["held"][rel] = h["on"]

    rows = []
    for (key, area), e in sorted(entries.items(), key=lambda kv: (kv[0][1].lower(), kv[0][0])):
        dis = st = con = bad = 0
        for rel, on in e["held"].items():
            d = any(x and (on is None or x >= on.isoformat()) for x in sig["disliked"].get(rel, []))
            s, c = rel in sig["stale"], rel in sig["contradicted"]
            dis, st, con, bad = dis + d, st + s, con + c, bad + (d or s or c)
        n, decisions = len(e["held"]), e["certifications"] + e["removals"]
        low, high = wilson(bad, n)
        rate = bad / float(n) if n else None
        rev_rate = e["reversals"] / float(e["certifications"]) if e["certifications"] else None
        row = {"reviewer": e["reviewer"], "area": area, "certifications": e["certifications"], "removals": e["removals"],
               "decisions": decisions, "pages_held": n, "disliked": dis, "stale": st, "contradicted": con, "problem_pages": bad,
               "problem_rate": rate, "wilson_low": low, "wilson_high": high, "reversals": e["reversals"], "reversal_rate": rev_rate,
               "min_decisions": pol["min_decisions"], "weight": None, "within_limits": None, "eligible": False}
        if decisions < pol["min_decisions"]:
            row["status"] = NOT_ENOUGH
        elif not n:
            row["status"] = "no certified pages left to measure"
        else:
            row["weight"] = round(1 - high, 3)
            over = []
            if rate > pol["max_problem_rate"]:
                over.append("problem rate above %.0f%%" % (100 * pol["max_problem_rate"]))
            if rev_rate is not None and rev_rate > pol["max_reversal_rate"]:
                over.append("reversal rate above %.0f%%" % (100 * pol["max_reversal_rate"]))
            row["within_limits"] = not over
            row["status"] = "within the policy limits" if not over else "above a limit: " + "; ".join(over)
            if not pol["active"]:
                row["status"] += " (advisory only: no review.trust in the profile)"
            row["eligible"] = pol["active"] and not over
        row["explain"] = explain(row)
        rows.append(row)
    return {"policy": pol, "formula": FORMULA, "rows": rows, "rejections": rejections, "notes": pol["notes"] + sig["notes"]}


def trust_text(table):
    """The table as plain text lines (CLI)."""
    pol = table["policy"]
    out = ["Policy (review.trust): %s" % ("active" if pol["active"] else "absent, so weights are advisory only"),
           "  min_decisions %d, max_problem_rate %.2f, max_reversal_rate %.2f, lookback_days %d" % (
               pol["min_decisions"], pol["max_problem_rate"], pol["max_reversal_rate"], pol["lookback_days"]),
           "Formula: " + table["formula"], ""]
    for r in table["rows"]:
        out.append("%-18s %-18s decisions %-3d held %-3d weight %s  [%s]" % (
            r["reviewer"], r["area"], r["decisions"], r["pages_held"], "none" if r["weight"] is None else "%.3f" % r["weight"], r["status"]))
        out.append("    " + r["explain"])
    if table["rejections"]:
        out.append("Rejections (per reviewer, not per area): " + ", ".join("%s %d" % kv for kv in sorted(table["rejections"].items())))
    out += ["note: " + n for n in table["notes"]]
    return out


# ---- contributors (people who suggest edits) ----------------------------------------------------------
def contributor_records(kb, today=None):
    """Facts about each person's suggestions, from page_suggest: suggested, approved, declined, open, and approved suggestions whose
    page was disliked after the decision. Counts only: no score. Honours review.trust.lookback_days."""
    pol = policy(kb)
    today = today or datetime.date.today()
    since = (today - datetime.timedelta(days=pol["lookback_days"])).isoformat() if pol["lookback_days"] else None
    recs = page_suggest.contributor_record(kb, since=since)
    for r in recs.values():
        r["text"] = ("%s: %d suggested; %d approved, %d declined, %d open; %d approved suggestion%s on a page disliked afterwards" % (
            r["name"], r["suggested"], r["approved"], r["declined"], r["open"], r["approved_later_disliked"],
            "" if r["approved_later_disliked"] == 1 else "s"))
    return recs



def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("stats")
    a.add_argument("kb")
    a.add_argument("--reviewer")

    a = sub.add_parser("route")
    a.add_argument("kb")
    a.add_argument("target")

    a = sub.add_parser("trust")
    a.add_argument("kb")
    a.add_argument("--reviewer")

    a = sub.add_parser("contributors")
    a.add_argument("kb")

    args = ap.parse_args(argv)
    kb = os.path.abspath(args.kb)

    if args.cmd == "stats":
        if args.reviewer:
            st = reviewer_stats(kb, args.reviewer)
            if not st:
                print("no record found for %s" % args.reviewer)
            else:
                print(advisory_text(st))
                if st["later_disliked_pages"]:
                    print("Later-disliked certified pages:")
                    for p in st["later_disliked_pages"]:
                        print("  %s (%d down, %d up)" % (p["file"], p["down"], p["up"]))
        else:
            all_st = reviewer_stats(kb)
            if not all_st:
                print("no reviewer certification events recorded yet")
            for st in sorted(all_st.values(), key=lambda x: -x["certified_count"]):
                print(advisory_text(st))

    elif args.cmd == "route":
        routes = suggest_routing(kb, args.target)
        print("Suggested reviewer routing for %s:" % args.target)
        for r in routes:
            print("  %-20s area_certified: %-3d  total_certified: %-3d  rejected: %-2d  disliked: %-2d  [%s]" % (
                r["name"], r["area_certifications"], r["total_certified"], r["total_rejected"], r["later_disliked_pages"], r["advisory"]
            ))

    elif args.cmd == "trust":
        table = trust_table(kb)
        if args.reviewer:
            who = kb_gate.clean(args.reviewer).lower()
            table["rows"] = [r for r in table["rows"] if r["reviewer"].lower() == who]
        print("\n".join(trust_text(table)))
        if not table["rows"]:
            print("no certification events recorded for this selection")

    elif args.cmd == "contributors":
        recs = contributor_records(kb)
        if not recs:
            print("no suggestions recorded yet")
        for r in sorted(recs.values(), key=lambda x: (-x["suggested"], x["name"].lower())):
            print(r["text"])

    return 0


if __name__ == "__main__":
    sys.exit(main())
