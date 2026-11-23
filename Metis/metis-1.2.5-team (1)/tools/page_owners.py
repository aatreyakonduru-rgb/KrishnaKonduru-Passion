#!/usr/bin/env python3
"""Per-page owner and review-due dates for Metis knowledge bases.

    python3 page_owners.py set           <kb> <page> --owner NAME [--days N] [--by NAME]
    python3 page_owners.py show          <kb> [<page>]
    python3 page_owners.py due           <kb> [--as-of YYYY-MM-DD]
    python3 page_owners.py stale-report  <kb> [--as-of YYYY-MM-DD]
    python3 page_owners.py mark-reviewed <kb> <page> --by NAME [--date YYYY-MM-DD] [--note TEXT]

Stores metadata in <KB>/.metis/page_meta.yaml. Owner defaults from CODEOWNERS and gate.teams
path globs in kb-profile.yaml.
"""
import argparse
import datetime
import fnmatch
import os
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import codeowners  # noqa: E402
import kb_gate  # noqa: E402

STATE_FILE = os.path.join(".metis", "page_meta.yaml")
DEFAULT_REVIEW_DAYS = 90


def state_path(kb):
    return os.path.join(kb, STATE_FILE)


def load_meta(kb):
    """Load <KB>/.metis/page_meta.yaml. Returns dict with 'pages' map."""
    p = state_path(kb)
    if not os.path.isfile(p):
        return {"pages": {}}
    with open(p, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        return {"pages": {}}
    if "pages" not in data and any(isinstance(v, dict) for v in data.values()):
        return {"pages": data}
    return {"pages": data.get("pages") or {}}


def save_meta(kb, data):
    """Save metadata to <KB>/.metis/page_meta.yaml."""
    p = state_path(kb)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("# Written by page_owners.py. Per-page ownership and review cycles.\n")
        yaml.safe_dump(data, fh, sort_keys=True, allow_unicode=True, width=120)


def default_review_days(kb):
    prof = kb_gate.profile(kb)
    return int((prof.get("review") or {}).get("default_days") or DEFAULT_REVIEW_DAYS)


def parse_date(d_str):
    if not d_str:
        return None
    try:
        return datetime.date.fromisoformat(str(d_str)[:10])
    except (ValueError, TypeError):
        return None


def all_kb_pages(kb):
    """List relative paths of all governed / hand-written markdown pages in the KB."""
    try:
        import kb_coverage
        return sorted(kb_coverage.page_files(kb).keys())
    except Exception:
        out = []
        for d, dirs, fs in os.walk(kb):
            dirs[:] = sorted(x for x in dirs if x not in kb_gate.EXEMPT_DIRS)
            for f in sorted(fs):
                if f.endswith(".md"):
                    rel = os.path.relpath(os.path.join(d, f), kb).replace(os.sep, "/")
                    if not kb_gate.derived(rel):
                        out.append(rel)
        return sorted(out)


def page_info(kb, rel, as_of=None):
    """Detailed ownership, review frequency, and due status for a single KB page."""
    rel = rel.strip().replace("\\", "/").lstrip("/")
    today = parse_date(as_of) or datetime.date.today()
    meta = load_meta(kb).get("pages", {}).get(rel) or {}
    prof = kb_gate.profile(kb)
    gate_state = kb_gate.load_state(kb) if kb_gate.is_locked(kb) else {}
    cert_info = (gate_state.get("files") or {}).get(rel) or {}

    explicit_owner = meta.get("owner")
    owner = explicit_owner

    # If no explicit owner, resolve default from codeowners and gate.teams
    if not owner:
        owner = codeowners.suggest_owner_for_page(kb, rel)
    if not owner:
        t = kb_gate.team_of(kb, rel)
        if t:
            owner = t["name"]

    review_every_days = int(meta.get("review_every_days") or default_review_days(kb))

    # Last reviewed date
    last_reviewed_str = meta.get("last_reviewed") or cert_info.get("on")
    last_reviewed = parse_date(last_reviewed_str)

    if last_reviewed:
        next_due = last_reviewed + datetime.timedelta(days=review_every_days)
        is_overdue = next_due < today
        days_until_due = (next_due - today).days
        overdue_days = max(0, -days_until_due) if is_overdue else 0
    else:
        next_due = None
        is_overdue = True
        days_until_due = -9999
        overdue_days = 9999

    return {
        "page": rel,
        "owner": owner,
        "explicit_owner": explicit_owner,
        "review_every_days": review_every_days,
        "last_reviewed": last_reviewed.isoformat() if last_reviewed else None,
        "next_due": next_due.isoformat() if next_due else None,
        "is_overdue": is_overdue,
        "days_until_due": days_until_due,
        "overdue_days": overdue_days,
        "set_by": meta.get("set_by"),
        "set_on": meta.get("set_on"),
    }


def all_pages(kb, as_of=None):
    """List page_info for all pages in the KB."""
    return [page_info(kb, p, as_of=as_of) for p in all_kb_pages(kb)]


def due_pages(kb, as_of=None):
    """List of pages past their review due date, ordered by most overdue first."""
    pages = [p for p in all_pages(kb, as_of=as_of) if p["is_overdue"]]
    return sorted(pages, key=lambda x: (x["days_until_due"], x["page"]))


def set_page(kb, rel, owner=None, days=None, by=None):
    """Set per-page owner and review frequency."""
    rel = rel.strip().replace("\\", "/").lstrip("/")
    data = load_meta(kb)
    pages = data.setdefault("pages", {})
    entry = pages.setdefault(rel, {})

    if owner is not None:
        entry["owner"] = kb_gate.clean(owner)
    if days is not None:
        entry["review_every_days"] = int(days)
    if by is not None:
        entry["set_by"] = kb_gate.clean(by)
    entry["set_on"] = datetime.date.today().isoformat()

    save_meta(kb, data)
    return page_info(kb, rel)


def mark_reviewed(kb, rel, by, on=None, note=None):
    """Mark a page reviewed. Allowed for a named lead, page owner, or team approver."""
    rel = rel.strip().replace("\\", "/").lstrip("/")
    by_clean = kb_gate.clean(by)
    if not by_clean:
        raise kb_gate.GateError("say who reviewed the page")

    info = page_info(kb, rel)
    leads = kb_gate.certifiers(kb)
    is_lead = by_clean.lower() in leads

    # Check if `by` is owner or approver
    owner_str = str(info["owner"] or "").lower()
    is_owner = by_clean.lower() == owner_str or by_clean.lower().lstrip("@") == owner_str.lstrip("@")

    is_team_approver = False
    try:
        who_info = kb_gate.who_any(kb, by_clean)
        role = who_info[1]
        if "approver" in role.lower():
            # Check if matching team
            t = kb_gate.team_of(kb, rel)
            if t and t["name"].lower() in role.lower():
                is_team_approver = True
    except Exception:
        role = "owner" if is_owner else "reviewer"

    if not (is_lead or is_owner or is_team_approver):
        lead_list = ", ".join(v[0] for v in leads.values())
        raise kb_gate.GateError(
            "%s is neither a lead (leads: %s) nor the owner of %s (%s)" % (
                by_clean, lead_list, rel, info["owner"] or "unassigned"
            )
        )

    review_date = parse_date(on) or datetime.date.today()
    data = load_meta(kb)
    entry = data.setdefault("pages", {}).setdefault(rel, {})
    entry["last_reviewed"] = review_date.isoformat()
    entry["last_reviewed_by"] = by_clean
    save_meta(kb, data)

    # Log to .metis/CERTIFICATIONS.log
    try:
        user_role = leads.get(by_clean.lower(), (by_clean, role))[1] if is_lead else role
        kb_gate.log(kb, "review", by_clean, user_role, "page-review", rel, note or "")
    except Exception:
        pass

    return page_info(kb, rel)


def stale_report(kb, as_of=None):
    """Comprehensive stale report: source-code changed pages + overdue review pages."""
    notes = []
    stale_sources = []

    try:
        import build_plan
        stale_list, build_notes = build_plan.stale(kb)
        notes += build_notes
        for s in stale_list:
            stale_sources.append({
                "page": s["page"],
                "reasons": s["reasons"],
                "owner": page_info(kb, s["page"])["owner"] or "(unassigned)",
            })
    except Exception as exc:
        notes.append("source comparison not available: %s" % exc)

    overdue = due_pages(kb, as_of=as_of)

    return {
        "as_of": (parse_date(as_of) or datetime.date.today()).isoformat(),
        "stale_sources": stale_sources,
        "overdue_reviews": overdue,
        "notes": notes,
    }


def files_without_owner(kb):
    """kb_coverage.py compatible function: list of KB pages that have no owner."""
    unowned = []
    for info in all_pages(kb):
        if not info["owner"]:
            unowned.append(info["page"])
    return unowned


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("set")
    a.add_argument("kb")
    a.add_argument("page")
    a.add_argument("--owner", required=True)
    a.add_argument("--days", type=int)
    a.add_argument("--by")

    a = sub.add_parser("show")
    a.add_argument("kb")
    a.add_argument("page", nargs="?")

    a = sub.add_parser("due")
    a.add_argument("kb")
    a.add_argument("--as-of")

    a = sub.add_parser("stale-report")
    a.add_argument("kb")
    a.add_argument("--as-of")

    a = sub.add_parser("mark-reviewed")
    a.add_argument("kb")
    a.add_argument("page")
    a.add_argument("--by", required=True)
    a.add_argument("--date")
    a.add_argument("--note")

    args = ap.parse_args(argv)
    kb = os.path.abspath(args.kb)

    try:
        if args.cmd == "set":
            info = set_page(kb, args.page, owner=args.owner, days=args.days, by=args.by)
            print("set %s owner=%s review_every_days=%d" % (info["page"], info["owner"], info["review_every_days"]))

        elif args.cmd == "show":
            if args.page:
                info = page_info(kb, args.page)
                print("page:              %s" % info["page"])
                print("owner:             %s" % (info["owner"] or "(unassigned)"))
                print("review_every_days: %d" % info["review_every_days"])
                print("last_reviewed:     %s" % (info["last_reviewed"] or "never"))
                print("next_due:          %s" % (info["next_due"] or "immediately"))
                print("status:            %s" % ("OVERDUE" if info["is_overdue"] else "OK"))
            else:
                pages = all_pages(kb)
                for info in pages:
                    st = "OVERDUE (%dd)" % info["overdue_days"] if info["is_overdue"] else "OK"
                    print("%-30s  owner: %-15s  due: %-10s  [%s]" % (
                        info["page"][:30], str(info["owner"] or "-")[:15], str(info["next_due"] or "-")[:10], st
                    ))

        elif args.cmd == "due":
            due = due_pages(kb, as_of=args.as_of)
            if not due:
                print("no pages are overdue for review")
            for info in due:
                print("%-35s  owner: %-15s  last: %-10s  overdue: %d days" % (
                    info["page"][:35], str(info["owner"] or "-")[:15], str(info["last_reviewed"] or "never")[:10], info["overdue_days"]
                ))

        elif args.cmd == "stale-report":
            rep = stale_report(kb, as_of=args.as_of)
            print("Stale & Overdue Report (as of %s)" % rep["as_of"])
            for n in rep["notes"]:
                print("  note: %s" % n)
            print("\nPages with stale sources (%d):" % len(rep["stale_sources"]))
            for s in rep["stale_sources"]:
                print("  %-35s  owner: %-15s  %s" % (s["page"], s["owner"], "; ".join(s["reasons"][:2])))
            print("\nPages with overdue reviews (%d):" % len(rep["overdue_reviews"]))
            for info in rep["overdue_reviews"]:
                print("  %-35s  owner: %-15s  overdue: %d days" % (info["page"], str(info["owner"] or "-"), info["overdue_days"]))

        elif args.cmd == "mark-reviewed":
            info = mark_reviewed(kb, args.page, by=args.by, on=args.date, note=args.note)
            print("marked %s reviewed by %s on %s (next due: %s)" % (info["page"], args.by, info["last_reviewed"], info["next_due"]))

    except kb_gate.GateError as err:
        print("error: %s" % err, file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
