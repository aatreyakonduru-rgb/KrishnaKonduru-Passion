"""Page owners, review schedules, reviewer track records, and calibration screen for Metis UI.

Path /owners, nav label "Owners & Reviews".
Lists KB pages with their owners, review schedules, and due dates; allows leads to set owners
and review frequencies; allows leads and owners to mark pages reviewed; displays reviewer track
records from CERTIFICATIONS.log; and provides a viewer for confidence recalibration proposals.
"""
import datetime
import os
import sys
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
for _p in (TOOLS, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import kb_gate  # noqa: E402
import page_owners  # noqa: E402
import recalibrate  # noqa: E402
import reviewer_stats  # noqa: E402
import ui_common as C  # noqa: E402
from ui_common import esc, field, form, page, pill  # noqa: E402


def need_user(ctx):
    if not C.clean(ctx.user):
        raise C.UiError("Say who you are first (top right, 'You are'). Your name goes on every approval, review, and rating.")
    return C.clean(ctx.user)


def need_lead(ctx):
    by = need_user(ctx)
    try:
        return kb_gate.who(ctx.kb, by)[0]
    except kb_gate.GateError as err:
        raise C.UiError("Only a named lead can perform this action. %s" % err)


def page_link(kb, p):
    if os.path.isfile(os.path.join(kb, p)):
        return '<a href="/files?page=%s"><code>%s</code></a>' % (urllib.parse.quote(p), esc(p))
    return '<span class="no"><code>%s</code> (missing)</span>' % esc(p)


def status_pill(info):
    if not info["owner"]:
        return '<span class="pill warn">unassigned</span>'
    if info["is_overdue"]:
        return '<span class="pill no">overdue (%dd)</span>' % info["overdue_days"]
    if info["days_until_due"] <= 14:
        return '<span class="pill warn">due in %dd</span>' % info["days_until_due"]
    return '<span class="pill ok">up to date</span>'


def left_side(all_p, due_p, stale_r, unowned, view_sel):
    items = [
        C.pane_item("/owners", "All pages", "%d pages" % len(all_p), on=(view_sel == "")),
        C.pane_item("/owners?view=overdue", "Overdue reviews", "%d overdue" % len(due_p), on=(view_sel == "overdue"),
                    dot="r" if due_p else ""),
        C.pane_item("/owners?view=stale", "Stale sources", "%d stale" % len(stale_r["stale_sources"]), on=(view_sel == "stale"),
                    dot="a" if stale_r["stale_sources"] else ""),
        C.pane_item("/owners?view=unowned", "Unassigned owner", "%d unowned" % len(unowned), on=(view_sel == "unowned"),
                    dot="a" if unowned else ""),
        C.pane_item("/owners?view=stats", "Reviewer stats", "Track records", on=(view_sel == "stats")),
        C.pane_item("/owners?view=trust", "Reviewer trust", "Weights and routing", on=(view_sel == "trust")),
        C.pane_item("/owners?view=recalibrate", "Recalibration", "Confidence loop", on=(view_sel == "recalibrate")),
    ]
    return C.left_pane("Governance", "".join(items), len(all_p))


def right_side(ctx, all_p, due_p, unowned, stale_r):
    out = [
        '<h4>Page Governance</h4><div class="grid">'
        '<div class="card"><div class="stat">%d</div><span class="muted">pages</span></div>'
        '<div class="card"><div class="stat">%d</div><span class="muted">overdue</span></div>'
        '<div class="card"><div class="stat">%d</div><span class="muted">unassigned</span></div>'
        '<div class="card"><div class="stat">%d</div><span class="muted">stale src</span></div>'
        '</div>' % (len(all_p), len(due_p), len(unowned), len(stale_r["stale_sources"])),
        '<h4>Set Page Owner</h4>',
        '<p class="muted"><small>Leads can assign per-page ownership and review cycles.</small></p>',
    ]
    set_body = (
        field("page", "Page path (relative)", "", hint="e.g. context/rules.md", required=True) +
        field("owner", "Owner name / team", "", hint="person or team name", required=True) +
        field("days", "Review every (days)", "90", hint="default: 90 days") +
        '<p><button>Set Page Meta</button></p>'
    )
    out.append(form(ctx, "/owners/set", set_body))

    out.append('<h4>Mark Page Reviewed</h4>')
    out.append('<p class="muted"><small>Record audit trail that page contents were verified.</small></p>')
    mark_body = (
        field("page", "Page path", "", hint="e.g. context/rules.md", required=True) +
        field("note", "Review note", "", hint="optional note") +
        '<p><button class="alt">Mark Reviewed</button></p>'
    )
    out.append(form(ctx, "/owners/mark", mark_body))
    return "".join(out)


def pct(x):
    return "-" if x is None else "%.1f%%" % (100 * x)


def trust_html(kb):
    """The 'Reviewer trust' view: every weight beside the counts that produced it, the formula, the thresholds, the routing."""
    tbl = reviewer_stats.trust_table(kb)
    pol = tbl["policy"]
    out = ['<h2>Reviewer Trust</h2>',
           '<p class="muted">Counts first, then one formula over those counts. No hidden number, and nothing here approves or certifies '
           'anything: a certification always needs a named lead or team approver acting through the gate.</p>',
           '<div class="card soft"><b>Policy</b> (profile key <code>review.trust</code>): %s<ul>'
           '<li>minimum decisions per reviewer and area: <b>%d</b> (below that: &ldquo;%s&rdquo;, no weight)</li>'
           '<li>highest problem rate: <b>%s</b>; highest reversal rate: <b>%s</b>; lookback: <b>%d days</b></li>'
           '<li>sampling floor for bulk approval: the larger of <b>%d files</b> or <b>%s</b> of the batch; '
           'shorter samples: %s</li></ul></div>' % (
               "set" if pol["active"] else "absent, so weights are advisory only", pol["min_decisions"], esc(reviewer_stats.NOT_ENOUGH),
               pct(pol["max_problem_rate"]), pct(pol["max_reversal_rate"]), pol["lookback_days"], pol["floor_files"], pct(pol["floor_share"]),
               "allowed up to %s of the batch" % pct(pol["sample_share"]) if pol["active"] and pol["sample_share"] else "not enabled (sample_share is not set)"),
           '<div class="card soft"><b>Formula</b><p class="muted">%s</p></div>' % esc(tbl["formula"])]
    for n in tbl["notes"]:
        out.append('<p class="muted">Note: %s</p>' % esc(n))
    if not tbl["rows"]:
        out.append('<div class="card soft">No certification events recorded yet in CERTIFICATIONS.log.</div>')
    else:
        rows = []
        for r in tbl["rows"]:
            w = "none" if r["weight"] is None else "%.3f" % r["weight"]
            rows.append('<tr><td><b>%s</b></td><td>%s</td><td>%d</td><td>%d</td><td>%d</td><td>%d / %d / %d</td><td>%d (%s)</td><td>%s</td>'
                        '<td>%d (%s)</td><td><b>%s</b></td><td><small class="muted">%s<br>%s</small></td></tr>' % (
                            esc(r["reviewer"]), esc(r["area"]), r["certifications"], r["removals"], r["pages_held"],
                            r["disliked"], r["stale"], r["contradicted"], r["problem_pages"], pct(r["problem_rate"]),
                            "%s to %s" % (pct(r["wilson_low"]), pct(r["wilson_high"])), r["reversals"], pct(r["reversal_rate"]), w,
                            esc(r["status"]), esc(r["explain"])))
        out.append('<table><tr><th>Reviewer</th><th>Area</th><th>Certified</th><th>Removals certified</th><th>Pages held</th>'
                   '<th>Disliked / stale / contradicted</th><th>Problem pages (rate)</th><th>Wilson 95%% interval</th><th>Reversals (rate)</th>'
                   '<th>Weight</th><th>Status and the counts behind it</th></tr>%s</table>' % "".join(rows))
        if tbl["rejections"]:
            out.append('<p class="muted">Rejected batches (logged per batch, so per reviewer, not per area): %s.</p>' % esc(
                ", ".join("%s %d" % kv for kv in sorted(tbl["rejections"].items()))))
    try:
        import review_queue
        rt = review_queue.route(kb)
    except Exception as exc:
        out.append('<p class="muted">Routing not available: %s</p>' % esc(exc))
        return out
    out.append('<h2>Routing Suggestions</h2><p class="muted">For each waiting file: who to ask, by weight in its area, then by open load. '
               'The person who gave a document is left out while another approver exists. A suggestion, not an assignment.</p>')
    if not rt["items"]:
        out.append('<div class="card soft">Nothing is waiting for certification.</div>')
    else:
        rows = []
        for it in rt["items"]:
            ask = "<br>".join("%s: %s, load %d" % (esc(c["name"]), ("weight %.3f" % c["weight"]) if c["weight"] is not None else "no weight (%s)" % esc(c["status"]),
                                                    c["load"]) for c in it["suggested"]) or "nobody can certify this"
            notx = "<br>".join("not %s: %s" % (esc(x["name"]), esc(x["reason"])) for x in it["excluded"])
            lane = ('<span class="pill ok">%s</span><br><small class="muted">%s</small>' % (esc(it["fast_lane_label"]), esc(it["note"]))
                    if it["fast_lane"] else '<small class="muted">not suitable: %s</small>' % esc("; ".join(it["fast_lane_failed"])))
            rows.append("<tr><td><code>%s</code><br><small class='muted'>%s; risk %d</small></td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                esc(it["file"]), esc(it["team"]), it["risk"], ask, notx or "-", lane))
        out.append("<table><tr><th>File</th><th>Suggested reviewer</th><th>Ruled out</th><th>Sampling label</th></tr>%s</table>" % "".join(rows))
    return out


def owners_view(ctx, q, flash=None, error=None):
    kb = ctx.kb
    view = C.clean(q.get("view")).lower()

    leads = kb_gate.certifiers(kb)
    me = C.clean(ctx.user).lower()
    lead_names = ", ".join(v[0] for v in leads.values()) or "nobody is named yet (Setup: KB owner and lead roles)"

    all_p = page_owners.all_pages(kb)
    due_p = [p for p in all_p if p["is_overdue"]]
    unowned = page_owners.files_without_owner(kb)
    stale_r = page_owners.stale_report(kb)

    body = [
        '<h1>Page Ownership &amp; Governance</h1>',
        '<p class="lead">Per-page owners, review cycles, reviewer track records, and confidence recalibration.</p>',
        '<p>%s <span class="muted">Leads: %s.</span></p>' % (
            pill(me in leads, "you are a lead (%s)" % leads[me][1] if me in leads else "",
                 "you are not a lead" if ctx.user else "set your name top right", True),
            esc(lead_names)
        ),
    ]

    if view == "stats":
        body.append('<h2>Reviewer Track Record</h2>')
        body.append('<p class="muted">Parsed from <code>.metis/CERTIFICATIONS.log</code> and joined with likes/dislikes. Pure facts and numbers only — no hidden score.</p>')
        all_stats = reviewer_stats.reviewer_stats(kb)
        if not all_stats:
            body.append('<div class="card soft">No reviewer certification events recorded yet in CERTIFICATIONS.log.</div>')
        else:
            rows = []
            for st in sorted(all_stats.values(), key=lambda x: -x["certified_count"]):
                disliked_txt = "%d page(s)" % st["later_disliked_count"]
                if st["later_disliked_pages"]:
                    disliked_txt = '<span class="pill no">%d disliked</span>' % st["later_disliked_count"]
                rows.append(
                    '<tr><td><b>%s</b></td><td>%s</td><td>%d</td><td>%d</td><td>%d</td><td>%s</td><td><small class="muted">%s</small></td></tr>' % (
                        esc(st["name"]), esc(", ".join(st["roles"]) or "certifier"),
                        st["certified_count"], st["rejected_count"], st["reviews_count"],
                        disliked_txt, esc(reviewer_stats.advisory_text(st))
                    )
                )
            body.append('<table><tr><th>Reviewer</th><th>Roles</th><th>Certified Files</th><th>Rejected Batches</th><th>Page Reviews</th><th>Later-Disliked Pages</th><th>Advisory Summary</th></tr>%s</table>' % "".join(rows))

        # Suggested Routing Table
        teams = kb_gate.teams(kb)
        if teams:
            body.append('<h2>Suggested Reviewer Routing by Team</h2>')
            for t in teams:
                routes = reviewer_stats.suggest_routing(kb, t["name"])
                r_rows = []
                for r in routes[:5]:
                    r_rows.append('<tr><td><b>%s</b></td><td>%d</td><td>%d</td><td>%d</td><td>%d</td><td>%s</td></tr>' % (
                        esc(r["name"]), r["area_certifications"], r["total_certified"], r["total_rejected"], r["later_disliked_pages"], esc(r["advisory"])
                    ))
                body.append('<h3>Team: %s</h3><table><tr><th>Reviewer</th><th>Team Certifications</th><th>Total Certified</th><th>Total Rejected</th><th>Later-Disliked</th><th>Advisory</th></tr>%s</table>' % (
                    esc(t["name"]), "".join(r_rows)
                ))

    elif view == "trust":
        body.extend(trust_html(kb))

    elif view == "recalibrate":
        body.append('<h2>Confidence Recalibration Loop</h2>')
        body.append('<p class="muted">Proposes confidence cap and deduction adjustments based on empirical Wilson score intervals. Never edits <code>answers.py</code> and never auto-applies.</p>')
        prop = recalibrate.load_proposal(kb)
        if prop:
            body.append('<div class="card"><h3 style="margin-top:0">Active Proposal (Generated %s)</h3>'
                        '<p><b>Status:</b> <span class="pill warn">%s</span> &middot; <b>Rated Answers Evaluated:</b> %d</p>'
                        '<p class="muted">%s</p>' % (
                            esc(prop.get("generated_on")), esc(prop.get("status")),
                            prop.get("total_rated_answers", 0), esc(prop.get("notice", ""))
                        ))
            # Proposed vs Current Weights Table
            curr = prop.get("current_weights", {})
            prop_w = prop.get("proposed_weights", {})
            w_rows = []
            for k, v in prop_w.items():
                old_v = curr.get(k)
                chg = '<span class="pill warn">changed</span>' if old_v != v else '<span class="muted">same</span>'
                w_rows.append('<tr><td><code>%s</code></td><td>%s</td><td><b>%s</b></td><td>%s</td></tr>' % (
                    esc(k), esc(old_v), esc(v), chg
                ))
            body.append('<table><tr><th>Weight / Cap Parameter</th><th>Current Value</th><th>Proposed Value</th><th>Status</th></tr>%s</table>' % "".join(w_rows))

            if prop.get("rationale"):
                body.append('<h4>Rationale</h4><ul>%s</ul>' % "".join("<li>%s</li>" % esc(r) for r in prop["rationale"]))
            body.append('</div>')
        else:
            body.append('<div class="card soft">No recalibration proposal generated yet. Run a recalibration check below.</div>')

        rec_body = (
            field("min_volume", "Minimum rated answers per band", "30", hint="default: 30") +
            '<label><input type="checkbox" name="force" value="1" style="display:inline"> Force proposal generation even if rating volume is below threshold</label>'
            '<p><button>Generate Recalibration Proposal</button></p>'
        )
        body.append('<div class="card"><h3 style="margin-top:0">Run Recalibration</h3>'
                    '<p class="muted">Checks rating intervals and generates <code>.metis/CALIBRATION_PROPOSAL.yaml</code>.</p>%s</div>' % form(ctx, "/owners/recalibrate", rec_body))

    elif view == "stale":
        body.append('<h2>Pages with Stale Cited Sources (%d)</h2>' % len(stale_r["stale_sources"]))
        body.append('<p class="muted">Pages whose cited repository source files have changed since the last recorded build.</p>')
        if not stale_r["stale_sources"]:
            body.append('<div class="card soft">All cited repository source files are up to date with the latest build.</div>')
        else:
            rows = []
            for s in stale_r["stale_sources"]:
                rows.append('<tr><td>%s</td><td><b>%s</b></td><td>%s</td></tr>' % (
                    page_link(kb, s["page"]), esc(s["owner"]), esc("; ".join(s["reasons"]))
                ))
            body.append('<table><tr><th>Page</th><th>Owner</th><th>Stale Reasons</th></tr>%s</table>' % "".join(rows))

    else:
        # Table of Pages
        if view == "overdue":
            shown = due_p
            heading = "Overdue Reviews (%d)" % len(due_p)
        elif view == "unowned":
            shown = [p for p in all_p if not p["owner"]]
            heading = "Unassigned Pages (%d)" % len(shown)
        else:
            shown = all_p
            heading = "All Governed Pages (%d)" % len(all_p)

        body.append('<h2>%s</h2>' % heading)
        if not shown:
            body.append('<div class="card soft">No pages in this view.</div>')
        else:
            rows = []
            for p in shown:
                owner_disp = '<b>%s</b>' % esc(p["owner"]) if p["owner"] else '<span class="pill warn">unassigned</span>'
                last_rev = esc(p["last_reviewed"] or "never")
                next_due = esc(p["next_due"] or "immediately")
                rows.append(
                    '<tr><td>%s</td><td>%s</td><td>%d days</td><td>%s</td><td>%s</td><td>%s</td></tr>' % (
                        page_link(kb, p["page"]), owner_disp, p["review_every_days"], last_rev, next_due, status_pill(p)
                    )
                )
            body.append('<table><tr><th>Page</th><th>Owner</th><th>Review Cycle</th><th>Last Reviewed</th><th>Next Due</th><th>Status</th></tr>%s</table>' % "".join(rows))

    return page(
        ctx, "Owners & Reviews", "/owners", "".join(body), flash, error,
        left=left_side(all_p, due_p, stale_r, unowned, view),
        right=C.right_pane(right_side(ctx, all_p, due_p, unowned, stale_r))
    )


def act_set_owner(ctx, f):
    by = need_lead(ctx)
    rel = C.clean(f.get("page"))
    owner = C.clean(f.get("owner"))
    days = f.get("days")
    if not rel:
        raise C.UiError("Page path is required.")
    if not owner:
        raise C.UiError("Owner name or team is required.")
    days_val = int(days) if days and str(days).isdigit() else None

    page_owners.set_page(ctx.kb, rel, owner=owner, days=days_val, by=by)
    return "/owners", "Updated ownership and review cycle for %s." % rel


def act_mark_reviewed(ctx, f):
    by = need_user(ctx)
    rel = C.clean(f.get("page"))
    note = C.clean(f.get("note")) or None
    if not rel:
        raise C.UiError("Page path is required.")

    try:
        info = page_owners.mark_reviewed(ctx.kb, rel, by=by, note=note)
    except (kb_gate.GateError, ValueError) as err:
        raise C.UiError(str(err))

    return "/owners", "Marked %s reviewed by %s (next due: %s)." % (rel, by, info["next_due"])


def act_recalibrate(ctx, f):
    need_lead(ctx)
    min_vol = int(f.get("min_volume") or 30)
    force = bool(f.get("force"))
    ok, res = recalibrate.propose(ctx.kb, min_volume=min_vol, force=force)
    if not ok:
        raise C.UiError(res["message"])
    return "/owners?view=recalibrate", "Recalibration proposal generated successfully."


SCREENS = {"/owners": owners_view}
ACTIONS = {
    "/owners/set": ("/owners", act_set_owner),
    "/owners/mark": ("/owners", act_mark_reviewed),
    "/owners/recalibrate": ("/owners", act_recalibrate),
}
NAV = [("/owners", "Owners & Reviews")]
