"""Compare and promote: the live KB against a staging folder or another KB folder, and promotion of chosen files.

The comparison is kb_compare.py. Promotion is kb_promote.py while the KB is open. Once kb_gate says the KB is locked, nothing is
written into it: the chosen files are proposed as a batch with kb_gate.propose and a lead certifies them under Approve.
The person can only pick a folder from a list this module builds (staging runs in <KB>/_REGEN, and KB folders next to this KB);
a path typed or posted by hand is never used.
"""
import difflib
import os
import shutil
import sys
import tempfile
import urllib.parse

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import ui_common as C  # noqa: E402
from ui_common import esc, form, field, pill, page  # noqa: E402
import builds  # noqa: E402
import kb_compare  # noqa: E402
import kb_gate  # noqa: E402
import kb_promote  # noqa: E402
import sensitive  # noqa: E402
import verify_kb  # noqa: E402

LOG = os.path.join(".metis", "COMPARE_PROMOTIONS.log")
MAX_DIFF = 300
MAX_TAG_ROWS = 100
NO_USER = "Say who you are first (top right, 'You are'). Your name goes on every approval, rating and answer."


def need_user(ctx):
    if not C.clean(ctx.user):
        raise C.UiError(NO_USER)
    return C.clean(ctx.user)


# ---- which folders may be compared -----------------------------------------------------------------
def inside(base, path):
    base, path = os.path.normcase(os.path.realpath(base)), os.path.normcase(os.path.realpath(path))
    try:
        return path != base and os.path.commonpath([base, path]) == base
    except ValueError:
        return False


def sides(kb):
    """[(key, label, path)]: staging runs under <kb>/_REGEN and KB folders next to this KB. Only folders that exist."""
    out = []
    regen = os.path.join(kb, "_REGEN")
    parent = os.path.dirname(kb)
    try:
        names = sorted(os.listdir(regen)) if os.path.isdir(regen) else []
        for n in names:
            if os.path.isdir(os.path.join(regen, n)) and not n.startswith("."):
                out.append(("regen/" + n, "Staging folder %s" % n, os.path.join(regen, n)))
        for n in sorted(os.listdir(parent)):
            p = os.path.join(parent, n)
            if n.startswith(".") or not os.path.isdir(p) or os.path.normcase(os.path.abspath(p)) == os.path.normcase(kb):
                continue
            if os.path.isfile(os.path.join(p, ".metis", "kb-profile.yaml")) or os.path.isfile(os.path.join(p, "KNOWLEDGE-MANIFEST.yaml")):
                out.append(("kb/" + n, "Other KB folder %s" % n, p))
    except OSError:
        pass
    return out


def resolve(kb, key):
    """(label, folder) for a key from sides(); anything else, including a path or '..', is refused."""
    for k, label, path in sides(kb):
        if k == key:
            base = os.path.join(kb, "_REGEN") if k.startswith("regen/") else os.path.dirname(kb)
            if os.path.normcase(os.path.dirname(os.path.realpath(path))) != os.path.normcase(os.path.realpath(base)):
                raise C.UiError("%s is a link that leads out of its folder, so it cannot be compared." % label)
            return label, path
    raise C.UiError("That folder is not on the list. Pick a staging folder from _REGEN, or another KB folder next to this one.")


def ignored(rel):
    """Files the gate does not govern, and build bookkeeping: they are neither compared nor promoted."""
    top = rel.split("/")[0]
    return top in kb_gate.EXEMPT_DIRS or top in builds.SKIP_TOP or top.startswith(("_", ".")) or kb_gate.derived(rel)


def load_lists(kb):
    try:
        mapping = C.load_yaml(os.path.join(kb, ".metis", "kb-output-names.yaml"))
        if not isinstance(mapping, dict) or not all(isinstance(v, (str, list)) for v in mapping.values()):
            raise ValueError("it must map a staged name to a live name")
        keep = builds.keep_patterns(kb)
    except (yaml.YAMLError, ValueError, AttributeError, KeyError, TypeError) as err:
        raise C.UiError("The name map or keep list in .metis cannot be read (%s). Fix it first." % err)
    return mapping, keep


# ---- what changed ----------------------------------------------------------------------------------
def tags_in(line):
    return {m.group(0) for m in verify_kb.TAG.finditer(line)}


def tag_changes(old, new):
    """Changed lines that lose or gain a source tag: [{what, before, after}]. A replaced line is paired with the line in its place."""
    a, b = old.splitlines(), new.splitlines()
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op != "replace":
            continue
        for o, n in zip(a[i1:i2], b[j1:j2]):
            if tags_in(o) and not tags_in(n):
                out.append({"what": "loses", "before": o, "after": n})
            elif tags_in(n) and not tags_in(o):
                out.append({"what": "gains", "before": o, "after": n})
    return out


def problems(kb, rel, text, checker):
    found, _ = kb_gate.source_problems(kb, rel, text, checker)
    return [(n, why) for _, n, why in found]


def plain(kb, err):
    t = str(err)
    head, _, rest = t.partition(": ")
    if head == "not in the staging folder":
        return "%s is not in the chosen folder." % rest
    if head.startswith("on the keep list"):
        return "%s is on the keep list (.metis/kb-keep.yaml). No prompt builds it, so a rebuilt copy must not replace it." % rest
    if head.startswith("already archived today"):
        return ("Today's archive already holds an old copy of this file (%s), and the tool will not overwrite an archive copy. "
                "Promote it tomorrow, or move that archive copy away first." % os.path.relpath(rest, kb).replace(os.sep, "/"))
    return t


def refusal(kb, stage, rel, live_rel, mapping, keep):
    """Why the tools would refuse this file, in plain words, or None."""
    try:
        kb_promote.plan(kb, stage, [rel], mapping, os.path.join(kb, "Archive"), C.today(), keep)
    except ValueError as err:
        # a locked KB gets a proposed batch, not an archive copy, so the archive clash does not apply there
        if not (kb_gate.is_locked(kb) and str(err).startswith("already archived today")):
            return plain(kb, err)
    if not inside(kb, os.path.join(kb, live_rel)):
        return "The output-name map sends it outside the KB."
    if ignored(live_rel):
        return "The gate does not govern this file (it is derived, or kept outside the gate), so it is not promoted here."
    blocked = sensitive.blocking(kb_gate.findings(live_rel, kb_promote.read_text(os.path.join(stage, rel))))
    if blocked:
        return "It has a %s on line %d. Take it out of the chosen copy first; a secret or id number is never moved into the KB." % (blocked[0]["kind"], blocked[0]["line"])
    return None


def analyse(kb, key):
    label, stage = resolve(kb, key)
    mapping, keep = load_lists(kb)
    rep = kb_compare.compare(kb, stage, mapping, keep)
    files = {rel: e for rel, e in rep["files"].items() if not ignored(rel) and inside(stage, os.path.join(stage, rel))}
    checker = verify_kb.Checker(kb)
    rows = {}
    for rel, e in sorted(files.items()):
        live_rel = e["live_file"]
        if not inside(kb, os.path.join(kb, live_rel)):
            raise C.UiError("The output-name map sends %s outside the KB. Fix .metis/kb-output-names.yaml." % rel)
        new = kb_compare.read(os.path.join(stage, rel))
        d = {"rel": rel, "live_file": live_rel, "status": e["status"], "entry": e, "live_problems": [],
             "stage_problems": problems(kb, live_rel, new, checker), "tags": [], "diff": [], "diff_more": 0, "refused": None}
        if e["status"] != "new":
            old = kb_compare.read(os.path.join(kb, live_rel))
            d["live_problems"] = problems(kb, live_rel, old, checker)
            if e["status"] == "changed":
                lines = list(difflib.unified_diff(old.splitlines(), new.splitlines(), "live", "chosen", n=2, lineterm=""))[2:]
                d["diff"], d["diff_more"] = lines[:MAX_DIFF], max(0, len(lines) - MAX_DIFF)
                d["tags"] = tag_changes(old, new)
        if e["status"] != "same":
            d["refused"] = refusal(kb, stage, rel, live_rel, mapping, keep)
        rows[rel] = d
    by = lambda s: [r for r, d in rows.items() if d["status"] == s]  # noqa: E731
    return {"key": key, "label": label, "stage": stage, "rows": rows, "added": by("new"), "changed": by("changed"), "same": by("same"),
            "removed": sorted(r for r in rep["not_rebuilt"] if not ignored(r)),
            "keep_conflicts": [r for r in rep["keep_conflicts"] if r in rows],
            "live_problems": sum(len(d["live_problems"]) for d in rows.values()),
            "stage_problems": sum(len(d["stage_problems"]) for d in rows.values())}


# ---- the screen ------------------------------------------------------------------------------------
def diff_html(d):
    out = []
    for ln in d["diff"]:
        bg = "#e6ffec" if ln.startswith("+") else "#ffebe9" if ln.startswith("-") else "#f0f1f3" if ln.startswith("@@") else "#fff"
        out.append('<div style="background:%s">%s</div>' % (bg, esc(ln)))
    more = '<p class="muted">%d more lines are not shown.</p>' % d["diff_more"] if d["diff_more"] else ""
    return ('<div style="font:12.5px/1.45 ui-monospace,Consolas,monospace;white-space:pre-wrap;border:1px solid #e5e7eb;'
            'border-radius:5px;overflow:auto">%s</div>%s' % ("".join(out), more))


def changed_html(d):
    e, tags = d["entry"], d["tags"]
    lost, gained = sum(t["what"] == "loses" for t in tags), sum(t["what"] == "gains" for t in tags)
    flags = []
    if e.get("hand_facts_dropped"):
        flags.append(pill(False, "", "drops a hand-supplied fact"))
    if e.get("patches_sidecar"):
        flags.append(pill(False, "", "has hand patches", True))
    if e.get("headings_gone"):
        flags.append(pill(False, "", "%d section(s) gone" % len(e["headings_gone"]), True))
    head = ('<code>%s</code> <span class="muted">+%d -%d lines; source problems %d &rarr; %d; source tags lost %d, gained %d</span> %s' % (
        esc(d["rel"]), e["lines_added"], e["lines_removed"], len(d["live_problems"]), len(d["stage_problems"]), lost, gained, " ".join(flags)))
    inner = []
    if d["live_file"] != d["rel"]:
        inner.append('<p class="muted">Replaces the live file <code>%s</code>.</p>' % esc(d["live_file"]))
    notes = ["Dropped a hand-supplied fact: %s" % f[:200] for f in e.get("hand_facts_dropped", [])]
    notes += ["Hand patches in %s: check each entry is in the chosen copy." % e["patches_sidecar"]] if e.get("patches_sidecar") else []
    notes += ["Section gone: %s" % h for h in e.get("headings_gone", [])]
    notes += ["Renamed: %s -> %s" % (o, n) for o, n in e.get("headings_renamed", [])]
    if notes:
        inner.append("<ul>%s</ul>" % "".join("<li>%s</li>" % esc(n) for n in notes))
    if d["stage_problems"]:
        inner.append('<p class="no">Source problems in the chosen copy: %s</p>' % esc("; ".join(
            "line %d: %s" % p for p in d["stage_problems"][:5]) + (" ..." if len(d["stage_problems"]) > 5 else "")))
    if tags:
        trs = "".join('<tr><td>%s</td><td>%s</td><td>%s</td></tr>' % (
            pill(t["what"] == "gains", "gains a tag", "loses a tag", True), esc(t["before"][:240]), esc(t["after"][:240]))
            for t in tags[:MAX_TAG_ROWS])
        inner.append('<table><tr><th>Source tag</th><th>Live line</th><th>Chosen line</th></tr>%s</table>' % trs)
    inner.append(diff_html(d))
    return "<details><summary>%s</summary>%s</details>" % (head, "".join(inner))


def log_rows(kb):
    path = os.path.join(kb, LOG)
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8", errors="replace") as fh:
        cols = [ln.rstrip("\n").split("\t") for ln in fh if ln.strip()]
    return [c for c in cols if len(c) == 7][-10:]


def promote_html(ctx, a, locked):
    cands = [a["rows"][r] for r in a["added"] + a["changed"]]
    if not cands:
        return '<h2>Promote</h2><div class="card soft">Nothing to promote: the chosen folder adds nothing and changes nothing.</div>'
    if locked:
        intro = ('<p>%s The KB is locked. Nothing is written into it. The ticked files are proposed as a batch, and a lead certifies it under '
                 '<a href="/approve">Approve</a>.</p>' % pill(False, "", "KB is locked", True))
    else:
        intro = ('<p>%s The ticked files are copied into the live KB. Each old copy is kept under <code>Archive/&lt;date&gt;/</code> and the move is '
                 'logged in <code>Archive/PROMOTIONS.log</code>.</p>' % pill(True, "KB is open"))
    rows = []
    for d in cands:
        why = d["refused"]
        box = '<input type="checkbox" name="files" value="%s"%s>' % (esc(d["rel"]), " disabled" if why else "")
        live = ' <span class="muted">as %s</span>' % esc(d["live_file"]) if d["live_file"] != d["rel"] else ""
        rows.append("<tr><td>%s</td><td><code>%s</code>%s</td><td>%s</td><td>%s</td></tr>" % (
            box, esc(d["rel"]), live, "new" if d["status"] == "new" else "changed",
            '<span class="no">Refused: %s</span>' % esc(why) if why else '<span class="muted">can be promoted</span>'))
    who = ('<p class="muted">Recorded as <b>%s</b>.</p>' % esc(ctx.user)) if ctx.user else '<p class="warn">Set your name top right first.</p>'
    body = ('<input type="hidden" name="side" value="%s"><table><tr><th></th><th>File</th><th>What</th><th>The tools say</th></tr>%s</table>%s%s'
            '<button>%s</button>' % (esc(a["key"]), "".join(rows), who,
                                      field("reason", "Why are you promoting these files?", "", hint="goes in the record, with your name", required=True),
                                      "Propose the ticked files to a lead" if locked else "Promote the ticked files into the live KB"))
    return "<h2>Promote</h2>%s%s" % (intro, form(ctx, "/compare/promote", body))


def result_html(ctx, a):
    n = len(a["rows"])
    cards = "".join('<div class="card"><div class="stat">%d</div>%s</div>' % (c, esc(t)) for c, t in (
        (len(a["added"]), "added"), (len(a["removed"]), "removed"), (len(a["changed"]), "changed"), (len(a["same"]), "the same")))
    body = ['<h2>%s</h2><div class="grid">%s</div>' % (esc(a["label"]), cards),
            '<p>Source problems, counted over the %d files compared: <b>%d</b> in the live copies, <b>%d</b> in the chosen copies %s '
            '<span class="muted">(the chosen copies are checked as they would be once in the live KB)</span></p>' % (
                n, a["live_problems"], a["stage_problems"], pill(a["stage_problems"] <= a["live_problems"], "no more than live", "more than live", True))]
    if a["keep_conflicts"]:
        body.append('<div class="err">These live files are on the keep list, so a chosen copy must not replace them: %s</div>' % esc(", ".join(a["keep_conflicts"])))
    body.append("<h2>Added (%d)</h2>" % len(a["added"]))
    body.append("<table>%s</table>" % "".join("<tr><td><code>%s</code></td><td class=\"muted\">%d source problems</td></tr>" % (
        esc(r), len(a["rows"][r]["stage_problems"])) for r in a["added"]) if a["added"] else '<p class="muted">None.</p>')
    body.append('<h2>Removed (%d)</h2><p class="muted">In the live KB, not in the chosen folder. Only folders the chosen folder also has are checked, as kb_compare does. '
                'Promoting never removes a file.</p>' % len(a["removed"]))
    body.append("<ul>%s</ul>" % "".join("<li><code>%s</code></li>" % esc(r) for r in a["removed"]) if a["removed"] else '<p class="muted">None.</p>')
    body.append("<h2>Changed (%d)</h2>" % len(a["changed"]))
    body.append("".join('<div class="card">%s</div>' % changed_html(a["rows"][r]) for r in a["changed"]) or '<p class="muted">None.</p>')
    body.append(promote_html(ctx, a, kb_gate.is_locked(ctx.kb)))
    return "".join(body)


def compare_view(ctx, q, flash=None, error=None):
    opts = sides(ctx.kb)
    key = q.get("side", "")
    body = ['<h1>Compare and promote</h1><p class="lead">Compare the live KB with a staging folder or another KB folder, then promote chosen files. '
            'Nothing here changes the KB until you promote, and a locked KB is never written to: files are proposed to a lead instead.</p>']
    if opts:
        options = "".join('<option value="%s"%s>%s</option>' % (esc(k), " selected" if k == key else "", esc(label)) for k, label, _ in opts)
        body.append('<form method="get" action="/compare"><label for="side">Compare the live KB with</label><select id="side" name="side">%s</select> '
                    '<button>Compare</button></form>' % options)
    else:
        body.append('<div class="card soft">No staging folder exists in <code>_REGEN</code> and no other KB folder sits next to this KB. '
                    'A build writes a staging folder; see Build.</div>')
    analysis = None
    if key:
        try:
            analysis = analyse(ctx.kb, key)
            body.append(result_html(ctx, analysis))
        except C.UiError as err:
            error = "\n".join(x for x in (error, str(err)) if x)
    rows = log_rows(ctx.kb)
    if rows:
        body.append("<h2>Recent promotions from here</h2><table><tr><th>When</th><th>Who</th><th>What</th><th>From</th><th>Batch</th><th>Files</th><th>Reason</th></tr>%s</table>" %
                    "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % esc(c) for c in r) for r in reversed(rows)))

    # ---- left pane: environments list
    items = []
    if opts:
        for k, label, _ in opts:
            items.append(C.pane_item("/compare?side=" + urllib.parse.quote(k, safe=""), esc(label), esc(k), on=(k == key)))
    else:
        items.append('<div class="it muted">No staging or other KB folders found</div>')
    left = C.left_pane("Environments", "".join(items), count=len(opts))

    # ---- right pane: promotion rules & environment summary
    is_locked = kb_gate.is_locked(ctx.kb)
    env_names, env_ref = C.environments(ctx.kb)
    side = [
        '<h4>Database environment</h4><div class="card soft"><b>%s</b><p class="muted">%s</p></div>' % (
            esc(C.current_env(ctx) or "none set"),
            "Chosen in the top bar (reference: %s). The comparison below is of KB files and does not depend on it." % esc(env_ref or "none")
            if len(env_names) > 1 else "The only environment in db-environments.yaml (the comparison is of KB files)."
            if env_names else "No database environments are set up."),
        '<h4>Promotion rules</h4>',
        '<div class="card soft"><b>%s</b><p class="muted">%s</p></div>' % (
            "KB is locked" if is_locked else "KB is open",
            "Nothing is written directly into the KB. Promoted files are proposed as a batch for a lead to certify on Approve." if is_locked else
            "Promoted files are copied directly into the live KB. Old copies are archived under Archive/ with timestamp."),
        '<div class="card soft"><b>Keep list protection</b><p class="muted">Files on the keep list (<code>.metis/kb-keep.yaml</code>) cannot be overwritten by rebuilt copies.</p></div>',
        '<div class="card soft"><b>Sensitive data guard</b><p class="muted">Files containing credentials, keys, or card numbers are refused and blocked from promotion.</p></div>',
    ]
    if analysis:
        side.append('<h4>Environment summary</h4>')
        side.append('<table>')
        side.append('<tr><td class="muted">Folder</td><td><code>%s</code></td></tr>' % esc(key))
        side.append('<tr><td class="muted">Added</td><td><b>%d</b></td></tr>' % len(analysis["added"]))
        side.append('<tr><td class="muted">Changed</td><td><b>%d</b></td></tr>' % len(analysis["changed"]))
        side.append('<tr><td class="muted">Same</td><td>%d</td></tr>' % len(analysis["same"]))
        side.append('<tr><td class="muted">Removed</td><td>%d</td></tr>' % len(analysis["removed"]))
        side.append('<tr><td class="muted">Stage problems</td><td>%d</td></tr>' % analysis["stage_problems"])
        side.append('<tr><td class="muted">Live problems</td><td>%d</td></tr>' % analysis["live_problems"])
        side.append('</table>')
    right = C.right_pane("".join(side))

    return page(ctx, "Compare and promote", "/compare", "".join(body), flash, error, left=left, right=right)


# ---- promote ---------------------------------------------------------------------------------------
def record(kb, by, how, label, batch, files, reason):
    path = os.path.join(kb, LOG)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write("\t".join(C.clean(c) for c in (C.now(), by, how, label, batch or "-", ", ".join(files), reason)) + "\n")


def act_promote(ctx, f):
    by = need_user(ctx)
    reason = C.clean(f.get("reason"))
    if not reason:
        raise C.UiError("Say why you are promoting these files. The reason goes in the record with your name.")
    key = f.get("side", "")
    label, stage = resolve(ctx.kb, key)
    chosen = list(dict.fromkeys(f.getall("files")))
    if not chosen:
        raise C.UiError("Tick at least one file to promote.")
    a = analyse(ctx.kb, key)
    mapping, keep = load_lists(ctx.kb)
    for rel in chosen:
        d = a["rows"].get(rel)
        if not d:
            raise C.UiError("%s is not one of the files in the chosen folder." % rel)
        if d["status"] == "same":
            raise C.UiError("%s is the same in both places; there is nothing to promote." % rel)
        if d["refused"]:
            raise C.UiError("%s is refused: %s" % (rel, d["refused"]))
    back = "/compare?side=" + urllib.parse.quote(key, safe="")
    try:
        if kb_gate.is_locked(ctx.kb):
            batch = propose(ctx.kb, stage, chosen, a, by, reason, label)
            record(ctx.kb, by, "proposed", label, batch, chosen, reason)
            return back, "Proposed %d file(s) as batch %s. A lead certifies it under Approve; nothing was written into the KB." % (len(chosen), batch)
        kb_promote.promote(ctx.kb, stage, chosen, by, mapping, keep=keep)
    except ValueError as err:  # kb_gate.GateError is a ValueError
        raise C.UiError(plain(ctx.kb, err))
    record(ctx.kb, by, "promoted", label, "", chosen, reason)
    return back, "Promoted %d file(s) into the live KB as %s. Old copies are in Archive/%s/." % (len(chosen), by, C.today())


def propose(kb, stage, chosen, a, by, reason, label):
    """Copy the chosen files under their live names into a scratch folder inside the KB and hand it to kb_gate.propose."""
    os.makedirs(os.path.join(kb, ".metis"), exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="compare-", dir=os.path.join(kb, ".metis"))
    try:
        for rel in chosen:
            dst = os.path.join(tmp, a["rows"][rel]["live_file"])
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(os.path.join(stage, rel), dst)
        batch = kb_gate.new_batch(kb, "compare " + os.path.basename(stage))
        kb_gate.propose(kb, batch, tmp)
        path, _ = kb_gate.digest(kb, batch)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write("\n## Why this was proposed\n\nProposed by %s on %s from %s. Reason: %s\n" % (by, C.today(), label, reason))
    return batch


SCREENS = {"/compare": compare_view}
ACTIONS = {"/compare/promote": ("/compare", act_promote)}
NAV = [("/compare", "Compare and promote")]
