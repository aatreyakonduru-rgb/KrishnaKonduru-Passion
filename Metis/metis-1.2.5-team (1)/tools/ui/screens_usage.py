"""Usage screen: is a confidence band worth anything, what is read, and answers per week. Read only: it writes nothing."""
import calibration
import telemetry
import ui_common as C

esc = C.esc
SHOW = 15


def table(head, rows):
    return "<table><tr>%s</tr>%s</table>" % ("".join("<th>%s</th>" % h for h in head),
                                             "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % c for c in r) for r in rows))


def page_link(rel):
    return '<a href="/files?page=%s">%s</a>' % (esc(rel), esc(rel))


def calibration_block(kb, rep=None):
    if rep is None:
        rep = calibration.bands(kb)
    none = '<span class="muted">no ratings</span>'
    rows = []
    for r in rep["rows"]:
        rows.append([esc(r["band"]), r["answers"], r["rated"],
                     "%s (%d)" % (calibration.pct(r["liked_share"]), r["liked"]) if r["rated"] else none,
                     "%s (%d)" % (calibration.pct(r["disliked_share"]), r["disliked"]) if r["rated"] else none,
                     esc(calibration.span(r["ci"])) if r["ci"] else "",
                     C.pill(r["enough"], "enough to read", "not enough ratings yet", warn=True)])
    out = ['<h2 id="calibration">Confidence bands against ratings</h2>',
           '<p class="muted">A band is a label Metis computes from fixed rules, not fitted to your ratings, so treat it as uncalibrated until the '
           'verdict below says High is better than Low. It means something only if people like High answers more '
           'than Low ones. Shares are of the rated answers; the range is a 95%% Wilson interval for the liked share. A band needs %d '
           'rated answers before its numbers are read.</p>' % calibration.MIN_RATED,
           table(["Band", "Answers", "Rated", "Liked", "Disliked", "Liked share, 95% range", "Ratings"], rows),
           '<div class="card soft"><b>Is High better than Low?</b><p>%s</p></div>' % esc(rep["verdict"])]
    notes = []
    if rep["waiting"]:
        notes.append("%d question%s still waiting for an answer, not counted." % (rep["waiting"], "" if rep["waiting"] == 1 else "s"))
    if rep["unscored"]:
        notes.append("%d answer%s have no band, not counted." % (rep["unscored"], "" if rep["unscored"] == 1 else "s"))
    notes.append("The golden question set has %d question%s. golden.py checks them and prints a score, but keeps no result, so no golden "
                 "result is used here." % (rep["golden"], "" if rep["golden"] == 1 else "s"))
    out.append('<p class="muted">%s</p>' % " ".join(esc(n) for n in notes))
    return "".join(out)


def read_block(t):
    out = ['<h2 id="read-and-cited">What is read, cited and ignored</h2>',
           "<p>%d answers and %d context packs recorded; %d of %d hand-written pages never used.</p>" % (
               t["answers"], t["packs"], len(t["pages_never_used"]), t["pages"])]
    out.append('<h3 id="look-first">Look first</h3>')
    if t["look_first"]:
        out.append("<p>Pages cited in disliked answers, most dislikes first: %s</p>" % ", ".join(page_link(f) for f in t["look_first"][:SHOW]))
    else:
        out.append('<p class="muted">No page is cited in a disliked answer.</p>')
    used = sorted(t["files_used"].items(), key=lambda kv: (-(kv[1]["packs"] + kv[1]["answers"]), kv[0]))
    out.append('<h3 id="read-cited">Read and cited</h3>')
    if used:
        out.append(table(["Page", "In context packs (read)", "In answers (cited)"],
                         [[page_link(f), c["packs"], c["answers"]] for f, c in used[:SHOW]]))
        if len(used) > SHOW:
            out.append('<p class="muted">%d more pages not shown.</p>' % (len(used) - SHOW))
    else:
        out.append('<p class="muted">Nothing has been recorded as read or cited yet.</p>')
    out.append('<h3 id="unused">Ignored</h3>')
    if t["pages_never_used"]:
        out.append("<p>Pages no pack or answer used: %s%s</p>" % (", ".join(page_link(f) for f in t["pages_never_used"][:SHOW]),
                   " and %d more." % (len(t["pages_never_used"]) - SHOW) if len(t["pages_never_used"]) > SHOW else ""))
    else:
        out.append('<p class="muted">Every hand-written page has been used at least once.</p>')
    return "".join(out)


def weeks_block(kb):
    weeks = calibration.per_week(kb)
    out = ['<h2 id="per-week">Answers per week</h2>']
    if not weeks:
        return out[0] + '<p class="muted">No answers yet.</p>'
    top = max(n for _, n in weeks) or 1
    out.append(table(["Week starting (Monday)", "Answers", ""],
                     [[esc(w), n, '<div style="background:#7c3aed;height:10px;width:%dpx"></div>' % round(220 * n / top) if n else ""]
                      for w, n in weeks]))
    return "".join(out)


def disliked_block(t):
    rows = sorted(((f, m) for f, m in t["feedback"].items() if m["down"]), key=lambda kv: (-kv[1]["down"], kv[1]["up"], kv[0]))
    out = ['<h2 id="disliked-pages">Most disliked cited pages</h2>',
           '<p class="muted">A dislike names an answer, not a page. A page cited in a disliked answer may be right and the answer wrong '
           '(the wrong page was picked, or a right page was misread). Read this as where to look first, not as a verdict on a page. '
           'A dislike a lead declined is counted apart.</p>']
    if not rows:
        return "".join(out) + '<p class="muted">No disliked answer has cited a page yet.</p>'
    out.append(table(["Page", "Disliked answers that cited it", "Liked answers that cited it", "Declined by a lead", "Times used"],
                     [[page_link(f), m["down"], m["up"], m["declined"], m["used"]] for f, m in rows[:SHOW]]))
    return "".join(out)


def usage(ctx, q, flash=None, error=None):
    rep = calibration.bands(ctx.kb)
    body = ['<h1>Usage</h1><p class="lead">Whether the confidence label can be trusted, and what the KB is used for.</p>',
            calibration_block(ctx.kb, rep=rep)]
    try:
        t = telemetry.report(ctx.kb)
    except Exception as err:
        t = None
        body.append('<div class="err">The usage report could not be read: %s</div>' % esc(err))
    if t:
        body += [read_block(t), weeks_block(ctx.kb), disliked_block(t)]
    else:
        body.append(weeks_block(ctx.kb))

    # ---- left pane: telemetry views
    left_items = [
        C.pane_item("#calibration", "Confidence calibration", "Wilson 95% intervals"),
        C.pane_item("#read-cited", "All cited", "%d pages" % len(t["files_used"]) if t else "0 pages"),
        C.pane_item("#look-first", "Look first / Dislikes", "%d pages" % len(t["look_first"]) if t else "0 pages"),
        C.pane_item("#unused", "Unused", "%d pages" % len(t["pages_never_used"]) if t else "0 pages"),
        C.pane_item("#per-week", "Answers per week", "Activity history"),
        C.pane_item("#disliked-pages", "Most disliked pages", "%d pages" % len([f for f, m in t["feedback"].items() if m["down"]]) if t else "0 pages"),
    ]
    left = C.left_pane("Telemetry views", "".join(left_items))

    # ---- right pane: usage summary metrics
    side = [
        '<h4>Usage summary</h4>',
        '<table>',
        '<tr><td class="muted">Answers recorded</td><td><b>%d</b></td></tr>' % (t["answers"] if t else 0),
        '<tr><td class="muted">Context packs</td><td><b>%d</b></td></tr>' % (t["packs"] if t else 0),
        '<tr><td class="muted">KB pages total</td><td>%d</td></tr>' % (t["pages"] if t else 0),
        '<tr><td class="muted">Unused pages</td><td>%d</td></tr>' % (len(t["pages_never_used"]) if t else 0),
        '<tr><td class="muted">Look first</td><td>%d</td></tr>' % (len(t["look_first"]) if t else 0),
        '</table>',
        '<h4>Confidence vs rating</h4>',
        '<div class="muted">%s</div>' % esc(rep["verdict"]),
        '<h4>Wilson calibration</h4>',
        '<p class="muted">Confidence intervals use a 95% Wilson score interval for binomial proportions to ensure ratings differences are statistically meaningful.</p>'
    ]
    right = C.right_pane("".join(side))

    return C.page(ctx, "Usage", "/usage", "".join(body), flash, error, left=left, right=right)


SCREENS = {"/usage": usage}
ACTIONS = {}
NAV = [("/usage", "Usage")]
