#!/usr/bin/env python3
"""The review queue: what is waiting for certification, grouped by the team that owns it, riskiest first.

    python3 review_queue.py queue   <kb>                          every pending file, by owning team
    python3 review_queue.py plan    <kb> [--date YYYY-MM-DD]      write one PR body per team under <kb>/_PENDING/_QUEUE/ and print the branch names
    python3 review_queue.py certify <kb> --team NAME --by NAME [--accept-review NOTE]
                                                                  certify every pending file that team owns, across all batches

Ownership comes from `gate.teams` in <kb>/.metis/kb-profile.yaml: [{name, owns: [path globs], approvers: [names]}]. The first team
whose glob matches a file owns it. A file no team owns waits under "(no owning team)" for the leads. With no `gate.teams`, the
queue is one group and nothing else about the gate changes. Leads can still certify any file.

`plan` does not touch git. It names the branch `metis/<date>-review-<team>` and writes the PR body (files, risk, findings, who
should approve), so one PR can go to each team. Mētis never merges.

    python3 review_queue.py route <kb>      suggest reviewers for every pending file, and label the low-risk ones

`route` only suggests. It ranks the people who may certify a file (kb_gate.pool_for: the leads and the owning team's approvers, minus
the person who gave the document while another approver exists) by whether they have a trust weight in that area (reviewer_stats.py),
then by open load. A low-risk pending file is labelled "suitable for sampling review"; that is a label and nothing else. Certifying
still takes a named lead or team approver acting through kb_gate. `sample_size` may shorten the random sample for bulk approval only
under the profile key review.trust.sample_share, only for a reviewer with enough history in that area, and never below the floor.
"""
import argparse
import datetime
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kb_gate  # noqa: E402
import reviewer_stats  # noqa: E402

QUEUE_DIR = "_QUEUE"
FAST_LANE_LABEL = "suitable for sampling review"
FAST_LANE_NOTE = "A label only. It certifies nothing: a named lead or team approver still has to certify through the gate."
MAX_SUGGESTED = 3


def queue(kb):
    """{"teams": [{team, approvers, files: [...]}]} with every pending file placed under its owning team, riskiest first.
    Teams appear in profile order, then the unowned group. Teams with nothing waiting are left out."""
    by_team = {}
    for batch in kb_gate.batches(kb):
        for r in kb_gate.analyse(kb, batch):
            t = kb_gate.team_of(kb, r["file"])
            by_team.setdefault(t["name"] if t else kb_gate.UNASSIGNED, []).append(dict(r, batch=batch))
    order = [t["name"] for t in kb_gate.teams(kb)] + [kb_gate.UNASSIGNED]
    leads = sorted(v[0] for v in kb_gate.certifiers(kb).values())
    out = []
    for name in order:
        files = by_team.get(name)
        if not files:
            continue
        team = next((t for t in kb_gate.teams(kb) if t["name"] == name), None)
        approvers = sorted(set((team["approvers"] if team else []) + leads), key=str.lower)
        out.append({"team": name, "approvers": approvers, "files": sorted(files, key=lambda r: (-r["risk"], r["file"]))})
    return {"teams": out}


def branch_name(team, date):
    return "metis/%s-review-%s" % (date, kb_gate.slug(team))


def pr_body(group, date):
    files = group["files"]
    L = ["# Certify: %s" % group["team"], "",
         "Knowledge pieces waiting for certification. Mētis does not merge this PR; an approver below does, after reading the list.", "",
         "- Approvers: %s" % (", ".join(group["approvers"]) or "none named in the profile"),
         "- Files: %d (%d new, %d changed, %d removed)" % (len(files), sum(r["action"] == "new" for r in files),
                                                          sum(r["action"] == "change" for r in files), sum(r["action"] == "remove" for r in files)),
         "- Blocked by a secret or id number: %d" % sum(any(f["level"] == "block" for f in r["findings"]) for r in files),
         "- Date: %s" % date, "",
         "| Order | File | Batch | What | Lines | Risk | Why it ranks here |", "|---|---|---|---|---|---|---|"]
    for i, r in enumerate(files, 1):
        why = ["%s (%s)" % (f["kind"], f["level"]) for f in r["findings"][:3]]
        if r["problems"]:
            why.append("%d source problems" % len(r["problems"]))
        if r["action"] == "remove":
            why.append("removes a certified file")
        L.append("| %d | %s | %s | %s | +%d -%d | %d | %s |" % (i, r["file"], r["batch"], r["action"], r["lines_added"], r["lines_removed"],
                                                             r["risk"], "; ".join(why) or "none found"))
    given = sorted({g for r in files for g in r["given_by"]})
    if given:
        L += ["", "Documents were given by: %s. They do not certify their own pages while another approver exists." % ", ".join(given)]
    return "\n".join(L) + "\n"


def plan(kb, date=None):
    """Write one PR body per team; return [{team, branch, body_file, files}]."""
    date = date or datetime.date.today().isoformat()
    base = os.path.join(kb_gate.pending_dir(kb), QUEUE_DIR)
    out = []
    for group in queue(kb)["teams"]:
        os.makedirs(base, exist_ok=True)
        path = os.path.join(base, "%s.md" % kb_gate.slug(group["team"]))
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(pr_body(group, date))
        out.append({"team": group["team"], "branch": branch_name(group["team"], date), "body_file": path,
                    "files": [r["file"] for r in group["files"]]})
    return out


def in_area(kb, rel, area):
    """Check if relative path matches an area (folder prefix, glob, or team owns-glob)."""
    a = area.strip()
    clean_rel = rel.strip().replace("\\", "/").lstrip("/")
    if kb_gate.owns(a, clean_rel):
        return True
    if clean_rel.startswith(a.rstrip("/") + "/"):
        return True
    if clean_rel == a.rstrip("/"):
        return True
    for t in kb_gate.teams(kb):
        if t["name"].lower() == a.lower():
            if any(kb_gate.owns(g, clean_rel) for g in t["owns"]):
                return True
        elif any(kb_gate.owns(g, clean_rel) for g in t["owns"] if g.lower() == a.lower()):
            return True
    return False


def certify_area(kb, area, by, accept_review=None):
    """Certify every pending file matching the area (folder prefix, glob, or team owns-glob) across all batches.
    Returns the number of files certified."""
    a = kb_gate.clean(area)
    if not a:
        raise kb_gate.GateError("specify an area to certify")
    by_batch = {}
    for batch in kb_gate.batches(kb):
        for r in kb_gate.analyse(kb, batch):
            if in_area(kb, r["file"], a):
                by_batch.setdefault(batch, []).append(r["file"])
    if not by_batch:
        raise kb_gate.GateError("nothing is waiting for area %s" % a)
    done = 0
    for batch, files in sorted(by_batch.items()):
        done += kb_gate.certify(kb, batch, by, files, accept_review)
    return done


def certify_team(kb, team, by, accept_review=None):
    """Certify every pending file the named team owns, in every batch. Returns the number of files certified."""
    name = kb_gate.clean(team).lower()
    group = next((g for g in queue(kb)["teams"] if g["team"].lower() == name), None)
    if not group:
        raise kb_gate.GateError("nothing is waiting for %s" % (kb_gate.clean(team) or "(no team)"))
    by_batch = {}
    for r in group["files"]:
        by_batch.setdefault(r["batch"], []).append(r["file"])
    # each batch is all-or-nothing; a refusal stops the run and leaves the later batches waiting
    done = 0
    for batch, files in sorted(by_batch.items()):
        done += kb_gate.certify(kb, batch, by, files, accept_review)
    return done


# ---- routing: who should look at it, never who approves it --------------------------------------
def cannot_certify(kb, r, name, pool):
    """Why `name` may not certify this pending file, or "" when nothing stops them. The same rule kb_gate.certify applies: the person
    who gave a document does not certify pages made from it while another approver exists (gate.allow_self_certify lifts it)."""
    if r["action"] == "remove" or (kb_gate.profile(kb).get("gate") or {}).get("allow_self_certify"):
        return ""
    others = [k for k, v in pool.items() if v[0].lower() != name.lower()]
    if others and name.lower() in {g.lower() for g in r["given_by"]}:
        return "%s gave the document; another approver must certify it" % name
    return ""


def _lines(r):
    return r["lines_added"] + r["lines_removed"]


def fast_lane(kb, r, pol, tr=None):
    """({check: bool}, [what failed]) for one pending file. All checks passing only earns the label FAST_LANE_LABEL."""
    team = kb_gate.team_of(kb, r["file"])
    checks = {"not a removal": r["action"] != "remove",
              "no source problems": not r["problems"],
              "no sensitive-data hits": not r["findings"],
              "small change (%d lines or fewer)" % pol["fast_lane_max_lines"]: _lines(r) <= pol["fast_lane_max_lines"],
              "an owning team with a named approver": bool(team and team["approvers"])}
    # the source checks need trust.py; without it (or for a removal) these three stay False, so the label is never given by default
    verified = quiet = hand_made = False
    if r["action"] != "remove" and tr is not None:
        try:
            text = kb_gate.read_text(os.path.join(kb_gate.pending_dir(kb, r["batch"]), r["file"]))
            verified = bool(r.get("tags")) and tr.edge(None, text)["quote"] == "verified"
            quiet = not any(r["file"] in (q.get("blocks") if isinstance(q.get("blocks"), list) else [q.get("blocks")]) for q in tr.open_q)
            import gen_graph
            hand_made = not (r["file"].endswith(".links.yaml") and gen_graph.origin_of(r["file"]) == "ai-proposed")
        except Exception:
            verified = quiet = hand_made = False
    checks["every source tag verified"] = verified
    checks["no open question blocks it"] = quiet
    checks["not an AI-proposed link file"] = hand_made
    return checks, [k for k, ok in checks.items() if not ok]


def route(kb, today=None, assigned=None, tr=None):
    """For each pending file: who to ask, who is ruled out and why, and whether it is a fast-lane candidate.
    {policy, notes, items: [{file, batch, team, area, risk, suggested: [...], excluded: [...], fast_lane, fast_lane_label, ...}]}
    `assigned` is an optional {"batch/file": name} of items already handed to someone; those count toward that person's load, as does
    each item routed earlier in this same pass. Nothing is assigned, approved or certified by this call."""
    pol = reviewer_stats.policy(kb)
    table = reviewer_stats.trust_table(kb, today)
    by_area = {(r["reviewer"].lower(), r["area"]): r for r in table["rows"]}
    load = {}
    for name in (assigned or {}).values():
        load[kb_gate.clean(name).lower()] = load.get(kb_gate.clean(name).lower(), 0) + 1
    notes = list(table["notes"])
    if tr is None:
        try:
            import trust
            tr = trust.Trust(kb)
            notes += tr.notes
        except Exception as exc:
            notes.append("source checks not available, so nothing is marked as a fast-lane candidate: %s" % exc)
    items = []
    for g in queue(kb)["teams"]:
        for r in g["files"]:  # riskiest first, so the riskiest files are routed while the best reviewers are least loaded
            team_name, pool = kb_gate.pool_for(kb, r["file"])
            area = reviewer_stats.area_of(kb, r["file"])
            cands, excluded = [], []
            for key, (name, role) in sorted(pool.items()):
                why = cannot_certify(kb, r, name, pool)
                if why:
                    excluded.append({"name": name, "reason": why})
                    continue
                row = by_area.get((key, area))
                cands.append({"name": name, "role": role, "area": area, "weight": row["weight"] if row else None,
                              "decisions": row["decisions"] if row else 0, "status": row["status"] if row else reviewer_stats.NOT_ENOUGH,
                              "within_limits": row["within_limits"] if row else None, "load": load.get(key, 0),
                              "why": row["explain"] if row else "no certification record in %s" % area})
            # people with a weight for this area first, then the lighter load, then the better weight, then more history here
            cands.sort(key=lambda c: (c["weight"] is None, c["load"], -(c["weight"] or 0), -c["decisions"], c["name"].lower()))
            suggested = cands[:MAX_SUGGESTED]
            if suggested:
                load[suggested[0]["name"].lower()] = load.get(suggested[0]["name"].lower(), 0) + 1
            checks, failed = fast_lane(kb, r, pol, tr)
            items.append({"file": r["file"], "batch": r["batch"], "team": team_name or kb_gate.UNASSIGNED, "area": area, "risk": r["risk"],
                          "suggested": suggested, "excluded": excluded, "fast_lane": not failed, "fast_lane_checks": checks,
                          "fast_lane_failed": failed, "fast_lane_label": FAST_LANE_LABEL if not failed else "",
                          "note": FAST_LANE_NOTE if not failed else ""})
    return {"policy": pol, "notes": notes, "items": items}


def sample_size(kb, total, reviewer=None, area=None, base=None, today=None):
    """How many items the random part of a bulk-approval sample holds. `base` is the existing rule's number (screens_review:
    the larger of 5 or 20 percent of the batch; passed in by the caller). The size is shortened only when ALL hold: the profile has
    review.trust with sample_share, `reviewer` has a trust weight in `area` (at least min_decisions there) and is within both limits.
    It is then max(floor, ceil(sample_share * total)) but never above `base`; floor = the larger of floor_files and floor_share of
    the batch (defaults 3 files, 10 percent), and never above the batch itself. Returns {size, base, floor, reduced, reason}."""
    pol = reviewer_stats.policy(kb)
    total = int(total)
    base = min(total, int(base if base is not None else max(5, math.ceil(0.2 * total))))
    floor = min(total, max(pol["floor_files"], math.ceil(pol["floor_share"] * total)))
    out = {"size": base, "base": base, "floor": floor, "reduced": False, "reason": ""}
    if not pol["active"] or not pol["sample_share"]:
        out["reason"] = "no sample_share in review.trust: the standard sample applies"
        return out
    row = next((r for r in reviewer_stats.trust_table(kb, today)["rows"]
                if r["reviewer"].lower() == kb_gate.clean(reviewer).lower() and r["area"] == area), None) if reviewer and area else None
    if not row or row["weight"] is None:
        out["reason"] = "%s has not enough history in %s (needs %d decisions there): the standard sample applies" % (
            kb_gate.clean(reviewer) or "this reviewer", area, pol["min_decisions"])
    elif not row["within_limits"]:
        out["reason"] = "%s is above a policy limit in %s: the standard sample applies" % (row["reviewer"], area)
    else:
        size = min(base, max(floor, math.ceil(pol["sample_share"] * total)))
        out.update(size=size, reduced=size < base, reason="%s has %d decisions in %s, weight %.3f, within the limits; the floor is %d" % (
            row["reviewer"], row["decisions"], area, row["weight"], floor))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("route"); a.add_argument("kb")
    a = sub.add_parser("queue"); a.add_argument("kb")
    a = sub.add_parser("plan"); a.add_argument("kb"); a.add_argument("--date")
    a = sub.add_parser("certify"); a.add_argument("kb"); a.add_argument("--team")
    a.add_argument("--area"); a.add_argument("--by", required=True); a.add_argument("--accept-review")
    args = ap.parse_args(argv)
    kb = os.path.abspath(args.kb)
    try:
        if args.cmd == "queue":
            q = queue(kb)["teams"]
            if not q:
                print("nothing is waiting for certification")
            for g in q:
                print("%s (%d files; approvers: %s)" % (g["team"], len(g["files"]), ", ".join(g["approvers"]) or "none named"))
                for r in g["files"]:
                    print("  risk %-4d %-7s %s  [%s]" % (r["risk"], r["action"], r["file"], r["batch"]))
        elif args.cmd == "route":
            rt = route(kb)
            if not rt["items"]:
                print("nothing is waiting for certification")
            for it in rt["items"]:
                print("%s [%s] risk %d%s" % (it["file"], it["team"], it["risk"], "  <" + it["fast_lane_label"] + ">" if it["fast_lane"] else ""))
                for c in it["suggested"]:
                    print("    ask %-18s weight %-6s decisions in %s: %-3d load %d  (%s)" % (
                        c["name"], "none" if c["weight"] is None else "%.3f" % c["weight"], c["area"], c["decisions"], c["load"], c["why"]))
                for x in it["excluded"]:
                    print("    not %s: %s" % (x["name"], x["reason"]))
            print("Routing suggests only. %s" % FAST_LANE_NOTE)
            for n in rt["notes"]:
                print("note: " + n)
        elif args.cmd == "plan":
            rows = plan(kb, args.date)
            if not rows:
                print("nothing is waiting for certification")
            for p in rows:
                print("%s: branch %s, %d files, PR body %s" % (p["team"], p["branch"], len(p["files"]), p["body_file"]))
        else:
            if args.team:
                print("certified %d files for %s by %s" % (certify_team(kb, args.team, args.by, args.accept_review), kb_gate.clean(args.team), kb_gate.clean(args.by)))
            elif args.area:
                print("certified %d files for area %s by %s" % (certify_area(kb, args.area, args.by, args.accept_review), kb_gate.clean(args.area), kb_gate.clean(args.by)))
            else:
                raise kb_gate.GateError("specify --team or --area to certify")
    except kb_gate.GateError as err:
        print("error: %s" % err, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
