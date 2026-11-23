"""Audit log, Teams and rights, Settings.

/audit     one list of what happened in this KB, merged from the records the tools already keep. Nothing is invented: a line is a
           record on disk, and the page names the records it reads.
/teams     who owns the KB, who the leads are, which teams own which files, and what each person may do as kb_gate decides today.
/settings  the profile sections as stored (a secret is never shown; only the NAME of a Devin secret is), and a small safe set a
           named lead may change: the base branch, the certifiers and the role holders. The write goes through setup_ops.save_profile.
"""
import datetime
import glob
import os
import re
import sys
import urllib.parse

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import ui_common as C  # noqa: E402
from ui_common import esc, form, field, pill, page  # noqa: E402
import answers  # noqa: E402
import builds  # noqa: E402
import feedback  # noqa: E402
import kb_gate  # noqa: E402
import questions  # noqa: E402
import sensitive  # noqa: E402
import setup_ops  # noqa: E402
import tasks  # noqa: E402
import telemetry  # noqa: E402

SAY_WHO = "Say who you are first (top right, 'You are'). Your name goes on every approval, rating and answer."
KINDS = ("lock", "certification", "rejection", "rating", "rating decision", "question raised", "question answered", "question asked",
         "build started", "build finished", "task claimed", "task finished", "setup approval", "context pack")
MAX_ROWS = 300
HIDDEN = "(hidden: looks like a secret)"


# =============================================================================================== small helpers
def lead_of(ctx):
    """(name, role) of the named lead using the page, or a refusal the person can act on."""
    if not C.clean(ctx.user):
        raise C.UiError(SAY_WHO)
    try:
        return kb_gate.who(ctx.kb, ctx.user)
    except kb_gate.GateError as err:
        raise C.UiError(str(err))


def standing(ctx):
    if not C.clean(ctx.user):
        return "<p>%s</p>" % pill(False, "", "set your name top right", True)
    lead = kb_gate.certifiers(ctx.kb).get(kb_gate.clean(ctx.user).lower())
    return "<p>%s</p>" % pill(bool(lead), "you are a lead (%s)" % lead[1] if lead else "",
                              "you are not a lead: you can read this page but not change it", True)


def short(text, n=100):
    t = C.clean(text)
    return t if len(t) <= n else t[:n - 3] + "..."


def valid_date(s):
    try:
        datetime.date.fromisoformat(s)
        return len(s) == 10
    except ValueError:
        return False


def file_href(kb, rel):
    """A link to the KB file when it is there, otherwise the Approve screen."""
    if rel and os.path.isfile(os.path.join(kb, rel)):
        return "/files?page=" + urllib.parse.quote(rel)
    return "/approve"


def check_text(*texts):
    """A person's words never carry a secret into the profile."""
    for t in texts:
        if sensitive.blocking(sensitive.scan(str(t))):
            raise C.UiError("That looks like a secret. Metis never stores one; name the Devin secret instead.")


def check_name(name):
    n = C.clean(name)
    if not n or not C.real(n):
        raise C.UiError("Give the person's name.")
    if len(n) > 80 or "," in n:
        raise C.UiError("A name is at most 80 characters and has no comma.")
    check_text(n)
    return n


# =============================================================================================== /audit: the records
def stamp(value):
    """'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM' (local time) from a record's date or ISO time; '' when the record has none."""
    s = str(value or "").strip()
    if not s:
        return ""
    try:
        t = datetime.datetime.fromisoformat(s)
    except ValueError:
        return s[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", s) else ""
    if len(s) <= 10:
        return t.date().isoformat()
    if t.tzinfo:
        t = t.astimezone().replace(tzinfo=None)
    return t.strftime("%Y-%m-%d %H:%M")


class Log(object):
    def __init__(self):
        self.items, self.undated = [], 0

    def add(self, at, who, kind, text, href="", label=""):
        at = stamp(at)
        if not at:
            self.undated += 1
            return
        self.items.append({"at": at, "who": kb_gate.clean(who), "kind": kind, "text": text, "href": href, "label": label,
                           "n": len(self.items)})


def read_gate_log(kb, log):
    path = os.path.join(kb, kb_gate.LOG)
    groups, order, locked_logged = {}, [], False
    if os.path.isfile(path):
        for line in C.read_text(path).splitlines():
            c = line.split("\t")
            if len(c) < 3:
                continue
            c += [""] * (7 - len(c))
            at, act, name, role, batch = c[:5]
            if act == "lock":
                locked_logged = True
                log.add(at, name, "lock", "locked the KB as %s (%s)" % (role, c[5]), "/approve", "Approve")
            elif act in ("certify", "certify-removal"):
                key = (at, act, name, role, batch)
                if key not in groups:
                    groups[key] = []
                    order.append(key)
                groups[key].append((c[5], c[6]))
            elif act == "reject":
                log.add(at, name, "rejection", "rejected batch %s as %s (%s): %s" % (batch, role, c[5], c[6]), "/approve", "Approve")
    for key in order:
        at, act, name, role, batch = key
        files = groups[key]
        if act == "certify-removal":
            log.add(at, name, "certification", "certified the removal of %d file(s) in batch %s as %s" % (len(files), batch, role), "/approve", "Approve")
        elif len(files) == 1:
            rel, note = files[0]
            log.add(at, name, "certification", "certified %s in batch %s as %s%s" % (rel, batch, role, ("; " + note) if note else ""),
                    file_href(kb, rel), rel)
        else:
            log.add(at, name, "certification", "certified %d files in batch %s as %s" % (len(files), batch, role), "/approve", "Approve")
    st = kb_gate.load_state(kb)
    if st.get("locked") and not locked_logged:
        log.add(st.get("locked_on"), st.get("locked_by"), "lock", "locked the KB (from certified.yaml; the log has no lock line)", "/approve", "Approve")


def read_feedback(kb, log):
    asked = {a.get("feedback"): a["id"] for a in answers.all_asks(kb) if a.get("feedback")}
    for f in feedback.load(kb).get("feedback") or []:
        fid = str(f.get("id"))
        href, label = ("/ask?id=" + urllib.parse.quote(asked[fid]), asked[fid]) if fid in asked else ("/approve", "Approve")
        up = f.get("rating") == "up"
        why = "" if up else " (why: %s)" % short(f.get("why"), 80)
        log.add(f.get("on"), f.get("by"), "rating", '%s %s an answer to "%s"%s' % (fid, "liked" if up else "disliked", short(f.get("question"), 80), why),
                href, label)
        if f.get("status") in ("approved", "declined"):
            log.add(f.get("decided_on"), f.get("decided_by"), "rating decision", "%s %s%s" % (f.get("status"), fid, ("; " + short(f.get("note"), 80)) if f.get("note") else ""),
                    "/approve", "Approve")
        if f.get("resolved_on"):
            log.add(f.get("resolved_on"), f.get("by"), "rating decision", "said the redirected answer for %s is now right" % fid, "/approve", "Approve")


def read_questions(kb, log):
    rated_by = {str(f.get("id")): f.get("by") for f in feedback.load(kb).get("feedback") or []}
    for x in questions.load(questions.reg_path(kb)).get("questions") or []:
        qid, rb = str(x.get("id")), str(x.get("raised_by_build") or "")
        by, fb = re.match(r"^asked by (.+)$", rb), re.match(r"^feedback (F-\d+)$", rb)
        who = by.group(1) if by else (rated_by.get(fb.group(1)) if fb else "")
        log.add(x.get("raised_on"), who, "question raised", "raised %s: %s%s" % (qid, short(x.get("question")), "" if by or not rb else " (from %s)" % rb),
                "/questions?status=all", "Questions")
        if x.get("answered_on"):
            log.add(x.get("answered_on"), x.get("answered_by"), "question answered", "answered %s: %s" % (qid, short(x.get("answer"))),
                    "/questions?status=all", "Questions")


def read_asks(kb, log):
    for a in answers.all_asks(kb):
        log.add(a.get("on"), a.get("by"), "question asked", "asked %s: %s (%s)" % (a["id"], short(a.get("question")), a.get("mode") or "local"),
                "/ask?id=" + urllib.parse.quote(a["id"]), a["id"])


def read_builds(kb, log):
    for r in builds.runs(kb):
        log.add(r.get("started"), r.get("started_by"), "build started", "started run %s (%s build)" % (r["run"], "first" if r.get("first_build") else "incremental"),
                "/build", "Build")
        if r.get("finished"):
            log.add(r.get("finished"), "", "build finished", "run %s ended: %s" % (r["run"], r.get("status")), "/build", "Build")


def read_tasks(kb, log):
    for t in tasks.all_tasks(kb):
        href, label = "/task?id=" + urllib.parse.quote(t["id"]), t["id"]
        log.add(t.get("claimed_on"), t.get("claimed_by"), "task claimed", "%s claimed: %s" % (t["id"], short(t.get("title"))), href, label)
        if t.get("finished_on"):
            gone = re.match(r"^cancelled by (.+)$", str(t.get("note") or ""))
            log.add(t["finished_on"], gone.group(1) if gone else t.get("claimed_by"), "task finished",
                    "%s %s: %s" % (t["id"], t.get("status"), short(t.get("title"))), href, label)


def read_stack(kb, log):
    app = setup_ops.approved(kb)
    if app:
        log.add(app.get("approved_on"), app.get("approved_by"), "setup approval", "approved the tech stack (%d items)" % len(app.get("items") or []),
                "/setup#stack", "Setup")


def read_packs(kb, log):
    for e in telemetry.events(kb):
        if e.get("kind") == "pack":
            files = e.get("files") or []
            log.add(e.get("at"), e.get("by"), "context pack", "built a context pack from %d KB file(s)" % len(files),
                    file_href(kb, files[0]) if files else "", files[0] if files else "")


READERS = (("locks, certifications, rejections", ".metis/CERTIFICATIONS.log", read_gate_log),
           ("ratings and the leads' decisions", "_FEEDBACK/FEEDBACK.yaml", read_feedback),
           ("questions raised and answered", "_QUESTIONS/VALIDATE_KB.yaml", read_questions),
           ("questions asked of the KB", ".metis/asks/*.yaml", read_asks),
           ("builds started and finished", ".metis/builds/*.yaml", read_builds),
           ("tasks claimed and finished", ".metis/tasks/*.yaml", read_tasks),
           ("setup approvals (tech stack)", ".metis/stack.yaml", read_stack),
           ("context packs built", ".metis/usage/*.jsonl", read_packs))


def collect(kb):
    """(events, sources, problems, undated). sources: [(what, where, found, events added)]."""
    log, sources, problems = Log(), [], []
    for what, where, fn in READERS:
        before = len(log.items)
        try:
            fn(kb, log)
        except Exception as err:  # one unreadable record must not hide the others
            problems.append("%s could not be read (%s: %s)." % (where, type(err).__name__, err))
        sources.append((what, where, bool(glob.glob(os.path.join(kb, where))), len(log.items) - before))
    return log.items, sources, problems, log.undated


# =============================================================================================== /audit: the page
def audit(ctx, q, flash=None, error=None):
    events, sources, problems, undated = collect(ctx.kb)
    person, kind = C.clean(q.get("person")), C.clean(q.get("kind"))
    d1, d2 = C.clean(q.get("from")), C.clean(q.get("to"))
    if (d1 and not valid_date(d1)) or (d2 and not valid_date(d2)):
        error = error or "Write dates as YYYY-MM-DD, for example 2026-05-31. The date filter was not applied."
        d1 = d2 = ""
    shown = [e for e in events if (not person or e["who"].lower() == person.lower()) and (not kind or e["kind"] == kind)
             and (not d1 or e["at"][:10] >= d1) and (not d2 or e["at"][:10] <= d2)]
    shown.sort(key=lambda e: (e["at"], e["n"]), reverse=True)
    names = sorted({e["who"] for e in events if e["who"]} | ({person} if person else set()), key=str.lower)

    def opts(values, chosen):
        return '<option value="">All</option>' + "".join('<option value="%s"%s>%s</option>' % (
            esc(v), " selected" if v == chosen else "", esc(v)) for v in values)
    body = ['<h1>Audit log</h1><p class="lead">What happened in this KB, newest first, merged from the records the tools keep. '
            'A line is a record on disk; nothing is added. A time is shown only where the record has one.</p>',
            '<form method="get" action="/audit"><div class="row"><div><label for="person">Person</label><select id="person" name="person">%s</select></div>'
            '<div><label for="kind">Kind</label><select id="kind" name="kind">%s</select></div><div>%s</div><div>%s</div></div>'
            '<p><button>Filter</button> <a class="btn alt" href="/audit">Clear</a></p></form>' % (
                opts(names, person), opts(KINDS, kind), field("from", "From", d1, hint="YYYY-MM-DD"), field("to", "To", d2, hint="YYYY-MM-DD"))]
    for p in problems:
        body.append('<div class="err">%s</div>' % esc(p))
    if shown:
        rows = "".join('<tr><td style="white-space:nowrap">%s</td><td>%s</td><td>%s</td><td><span class="pill">%s</span></td><td>%s</td></tr>' % (
            esc(e["at"]), esc(e["who"]) if e["who"] else '<span class="muted">not recorded</span>', esc(e["text"]), esc(e["kind"]),
            '<a href="%s">%s</a>' % (esc(e["href"]), esc(e["label"])) if e["href"] else '<span class="muted">-</span>') for e in shown[:MAX_ROWS])
        body.append('<p class="muted">%d of %d records%s.</p><table><tr><th>When</th><th>Who</th><th>What</th><th>Kind</th><th>Where</th></tr>%s</table>' % (
            len(shown), len(events), "; the newest %d are listed" % MAX_ROWS if len(shown) > MAX_ROWS else "", rows))
    else:
        body.append('<div class="card soft">%s</div>' % ("No record matches this filter." if events else "No record exists yet. Locks, ratings, questions, builds and tasks appear here as they happen."))
    body.append("<h2>Records this page reads</h2><table><tr><th>Records</th><th>Where</th><th>Found</th><th>Lines here</th></tr>%s</table>" % "".join(
        "<tr><td>%s</td><td><code>%s</code></td><td>%s</td><td>%d</td></tr>" % (esc(w), esc(p), pill(f, "yes", "not found", True), n) for w, p, f, n in sources))
    body.append('<p class="muted">Not recorded anywhere, so not listed: who finished a build (a run keeps who started it), who saved Setup or these settings, '
                'and any change made outside the UI. %s</p>' % ("%d record(s) had no date and are left out." % undated if undated else ""))

    # ---- left pane: event filters
    left_items = [
        C.pane_item("/audit", "All events", "%d records" % len(events), on=(not kind and not person and not d1 and not d2)),
        C.pane_item("/audit?kind=certification", "Certifications", "%d records" % sum(1 for e in events if e["kind"] == "certification"), on=(kind == "certification")),
        C.pane_item("/audit?kind=lock", "Locks", "%d records" % sum(1 for e in events if e["kind"] == "lock"), on=(kind == "lock")),
        C.pane_item("/audit?kind=task+claimed", "Tasks", "%d records" % sum(1 for e in events if e["kind"].startswith("task")), on=(kind.startswith("task"))),
        C.pane_item("/audit?kind=rejection", "Rejections", "%d records" % sum(1 for e in events if e["kind"] == "rejection"), on=(kind == "rejection")),
        C.pane_item("/audit?kind=rating", "Ratings", "%d records" % sum(1 for e in events if "rating" in e["kind"]), on=("rating" in kind)),
        C.pane_item("/audit?kind=question+raised", "Questions", "%d records" % sum(1 for e in events if "question" in e["kind"]), on=("question" in kind)),
        C.pane_item("/audit?kind=build+started", "Builds", "%d records" % sum(1 for e in events if "build" in e["kind"]), on=("build" in kind)),
    ]
    left = C.left_pane("Event filters", "".join(left_items), count=len(events))

    # ---- right pane: audit log summary stats
    side = [
        '<h4>Audit summary</h4>',
        '<table>',
        '<tr><td class="muted">Total records</td><td><b>%d</b></td></tr>' % len(events),
        '<tr><td class="muted">Shown (filtered)</td><td><b>%d</b></td></tr>' % len(shown),
        '<tr><td class="muted">People recorded</td><td>%d</td></tr>' % len(names),
        '<tr><td class="muted">Sources read</td><td>%d of %d</td></tr>' % (sum(1 for _, _, f, _ in sources if f), len(sources)),
    ]
    if undated:
        side.append('<tr><td class="muted">Undated records</td><td>%d</td></tr>' % undated)
    side.append('</table>')
    kind_counts = {}
    for e in events:
        k_name = "tasks" if e["kind"].startswith("task") else "ratings" if "rating" in e["kind"] else "questions" if "question" in e["kind"] else "builds" if "build" in e["kind"] else e["kind"]
        kind_counts[k_name] = kind_counts.get(k_name, 0) + 1
    side.append('<h4>Event breakdown</h4><table>')
    for k, c in sorted(kind_counts.items(), key=lambda x: -x[1]):
        side.append('<tr><td class="muted">%s</td><td>%d</td></tr>' % (esc(k), c))
    side.append('</table>')
    side.append('<p class="muted">Entries are read directly from on-disk records across tools and gate logs.</p>')
    right = C.right_pane("".join(side))

    return page(ctx, "Audit log", "/audit", "".join(body), flash, error, left=left, right=right)


# =============================================================================================== /teams
def held_by(kb):
    """{lowercase name: [name, [what the profile calls them]]} for everyone the profile names."""
    prof = C.profile(kb)
    owners = prof.get("owners") or {}
    out = {}

    def add(name, label):
        if kb_gate.real(name):
            out.setdefault(kb_gate.clean(name).lower(), [kb_gate.clean(name), []])[1].append(label)
    for key in ("kb_owner", "app_owner", "db_owner", "etl_owner"):
        add(owners.get(key), key.replace("_", " "))
    for role, name in (owners.get("roles") or {}).items():
        add(name, "role: %s" % role)
    for name in (prof.get("gate") or {}).get("certifiers") or []:
        add(name, "named certifier")
    for t in kb_gate.teams(kb):
        for a in t["approvers"]:
            add(a, "approver, team %s" % t["name"])
    return out


def rights(kb, name):
    """What kb_gate lets this person do today. Answering and rating ask for a name only."""
    def ok(fn):
        try:
            fn(kb, name)
            return True
        except kb_gate.GateError:
            return False
    lead = ok(kb_gate.who)
    mine = [t["name"] for t in kb_gate.teams(kb) if name.lower() in [a.lower() for a in t["approvers"]]]
    certify = "any file" if lead else ("files of %s" % ", ".join(mine) if mine and ok(kb_gate.who_any) else "")
    return {"approve": lead, "certify": certify, "reject": lead, "lock": lead}


def teams_view(ctx, q, flash=None, error=None):
    kb = ctx.kb
    prof = C.profile(kb)
    owners, gate = prof.get("owners") or {}, prof.get("gate") or {}
    leads = kb_gate.certifiers(kb)
    body = ['<h1>Teams and rights</h1><p class="lead">Who owns the KB, who may certify, and what each person may do, as kb_gate decides today. '
            'This page reads the profile; it changes nothing except through the two forms below.</p>', standing(ctx)]
    if not prof:
        body.append('<div class="card soft">There is no profile yet. <a href="/setup">Fill in Setup</a> first.</div>')
        return page(ctx, "Teams and rights", "/teams", "".join(body), flash, error)
    owner = owners.get("kb_owner")
    body.append('<div class="card"><b>KB owner:</b> %s<br><b>Leads</b> (may certify any file, lock the KB, approve ratings): %s<br><b>The KB is</b> %s.</div>' % (
        esc(owner) if kb_gate.real(owner) else '<span class="no">not named (owners.kb_owner)</span>',
        ", ".join("%s <span class=\"muted\">(%s)</span>" % (esc(n), esc(r)) for n, r in leads.values()) or '<span class="no">nobody is named yet</span>',
        "locked: changes wait for a lead" if kb_gate.is_locked(kb) else "open: the first build has not been locked"))
    # ---- teams
    ts = kb_gate.teams(kb)
    count = {t["name"]: 0 for t in ts} if ts else {}
    body.append("<h2>Teams and what they own</h2>")
    if ts:
        loose = 0
        for rel in kb_gate.governed(kb):
            t = kb_gate.team_of(kb, rel)
            if t:
                count[t["name"]] += 1
            else:
                loose += 1
        body.append("<table><tr><th>Team</th><th>Owns (first match wins)</th><th>Approvers</th><th>KB files owned now</th></tr>%s</table>" % "".join(
            "<tr><td>%s</td><td>%s</td><td>%s</td><td>%d</td></tr>" % (
                esc(t["name"]), ", ".join("<code>%s</code>" % esc(g) for g in t["owns"]) or "-", esc(", ".join(t["approvers"]) or "none"), count[t["name"]]) for t in ts))
        body.append('<p class="muted">%d KB file(s) belong to no team and wait for the leads. A team\'s approvers may certify only its own files.</p>' % loose)
    else:
        body.append('<div class="card soft">No team is set (<code>gate.teams</code> is empty): one shared pool, the leads, certifies everything.</div>')
    # ---- people and rights
    people = held_by(kb)
    rows = []
    for key in sorted(people):
        name, labels = people[key]
        r = rights(kb, name)
        rows.append("<tr><td>%s</td><td class=\"muted\">%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
            esc(name), esc("; ".join(labels)), pill(True, "yes"), pill(True, "yes"), pill(r["approve"], "yes", "no"),
            pill(bool(r["certify"]), r["certify"], "no"), pill(r["reject"], "yes", "no"), pill(r["lock"], "yes", "no")))
    rows.append('<tr><td><i>Anyone else with a name</i></td><td class="muted">not in the profile</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>' % (
        pill(True, "yes"), pill(True, "yes"), pill(False, "", "no"), pill(False, "", "no"), pill(False, "", "no"), pill(False, "", "no")))
    body.append("<h2>What each person may do</h2><table><tr><th>Person</th><th>Named as</th><th>Answer a question</th><th>Rate an answer</th>"
                "<th>Approve a rating</th><th>Certify</th><th>Reject a batch</th><th>Lock the KB</th></tr>%s</table>" % "".join(rows))
    body.append('<p class="muted">Answering and rating ask for a name only; kb_gate checks nothing there. Approving a rating, rejecting, locking and certifying ask kb_gate '
                '(<code>who</code>, <code>who_any</code>). Certifying also refuses the person who gave a document when another lead exists%s.</p>' % (
                    "; this profile lifts that (gate.allow_self_certify: true)" if gate.get("allow_self_certify") else ""))
    # ---- who is asked
    people_roles = questions.people(kb)
    body.append("<h2>Who a question goes to</h2><table><tr><th>Question kind</th><th>Role</th><th>Person</th></tr>%s</table>" % "".join(
        "<tr><td>%s</td><td>%s</td><td>%s</td></tr>" % (esc(t), esc(questions.role_for(kb, t)), esc(people_roles.get(questions.role_for(kb, t)) or "not named")) for t in questions.TYPES))
    # ---- keys
    body.append('<h2>Profile keys that decide this</h2><p class="muted">In <code>.metis/kb-profile.yaml</code>:</p><ul>'
                '<li><code>owners.kb_owner</code>, <code>owners.app_owner</code>, <code>owners.db_owner</code>, <code>owners.etl_owner</code>: leads.</li>'
                '<li><code>owners.roles.&lt;role&gt;</code>: the person for a role. A role with "lead" in its name makes that person a lead.</li>'
                '<li><code>gate.certifiers</code>: extra people who may certify.</li>'
                '<li><code>gate.allow_self_certify</code>: true lets the giver of a document certify it.</li>'
                '<li><code>gate.teams[].name</code>, <code>.owns</code>, <code>.approvers</code>: teams, the globs they own, who may certify for them.</li>'
                '<li><code>questions.role_for_type.&lt;kind&gt;</code>: which role gets which kind of question.</li></ul>'
                '<p class="muted">Setup edits the owners, roles and certifiers, and the first two forms below use that same save. '
                '<code>gate.teams</code> has no Setup field: a lead can add an approver to a team below; the team list and its globs are changed in the profile file by the team.</p>')
    # ---- forms
    roles = list(setup_ops.form_values(kb)["roles"])
    body.append("<h2>Add a person</h2><p class=\"muted\">Only a named lead can do this. The profile does not keep who made the change; the Audit log does not list it.</p>")
    team_form = ""
    if ts:
        team_form = '<div class="card">%s</div>' % form(ctx, "/teams/approver", '<b>Add a team approver</b><label for="team">Team</label><select id="team" name="team">%s</select>%s'
                                                        '<p><button>Add approver</button></p>' % (
                                                            "".join("<option>%s</option>" % esc(t["name"]) for t in ts),
                                                            field("name", "Name", "", hint="may then certify only that team's files", required=True)))
    body.append('<div class="row"><div class="card">%s</div><div class="card">%s</div>%s</div>' % (
        form(ctx, "/teams/certifier", "<b>Add a certifier</b>" + field("name", "Name", "", hint="may then certify any file", required=True) + "<p><button>Add certifier</button></p>"),
        form(ctx, "/teams/role", '<b>Name the person for a role</b><label for="role">Role</label><select id="role" name="role">%s</select>%s<p><button>Save role</button></p>' % (
            "".join("<option>%s</option>" % esc(r) for r in roles), field("name", "Name", "", hint="replaces the person now in that role", required=True))), team_form))

    # ---- left pane: teams list
    team_items = []
    if ts:
        for t in ts:
            n_files = count.get(t["name"], 0)
            apprs = len(t.get("approvers") or [])
            team_items.append(C.pane_item("#team-" + urllib.parse.quote(t["name"]), esc(t["name"]), "%d file%s &middot; %d approver%s" % (
                n_files, "" if n_files == 1 else "s", apprs, "" if apprs == 1 else "s")))
    else:
        team_items.append('<div class="it muted">No teams configured</div>')
    left = C.left_pane("Teams", "".join(team_items), count=len(ts) if ts else 0)

    # ---- right pane: approver policy callouts
    side = [
        '<h4>Approver policy</h4>',
        '<div class="card soft"><b>Leads pool</b><p class="muted">Leads may certify any file, lock the KB, and approve ratings.</p></div>',
        '<div class="card soft"><b>Team approvers</b><p class="muted">A team\'s approvers may certify only its own files.</p></div>',
        '<div class="card soft"><b>Two-person rule</b><p class="muted">Approver lists are stored in the KB repo. A change to them needs approval from a second person.</p></div>',
        '<div class="card soft"><b>Self-certification</b><p class="muted">%s</p></div>' % (
            "Self-certification is allowed by gate.allow_self_certify." if gate.get("allow_self_certify") else "Certifying refuses the document giver when another lead exists."),
        '<h4>Profile keys</h4>',
        '<table>',
        '<tr><td class="muted">owners.kb_owner</td><td>Leads</td></tr>',
        '<tr><td class="muted">gate.certifiers</td><td>Certifiers</td></tr>',
        '<tr><td class="muted">gate.teams</td><td>Teams & globs</td></tr>',
        '</table>'
    ]
    right = C.right_pane("".join(side))

    return page(ctx, "Teams and rights", "/teams", "".join(body), flash, error, left=left, right=right)


# =============================================================================================== writing the profile, safely
def changed(a, b, prefix=""):
    """Dotted paths in the old profile `a` whose value is different or gone in `b`. A key only new in `b` is a Setup default and is ignored."""
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in a:
            out += changed(a[k], b[k], "%s%s." % (prefix, k)) if k in b else ["%s%s" % (prefix, k)]
        return out
    return [] if a == b else [prefix.rstrip(".")]


def edit_profile(kb, change, allowed):
    """Apply change(values) to the Setup form values and save with setup_ops.save_profile. Setup's save rewrites the whole profile; if it
    would alter anything outside `allowed` (dotted paths), the old file is put back and the person is told."""
    path = C.profile_path(kb)
    if not os.path.isfile(path):
        raise C.UiError("There is no profile yet. Fill in Setup first.")
    old = C.profile(kb)
    with open(path, "rb") as fh:
        raw = fh.read()
    values = setup_ops.form_values(kb)
    change(values)
    done = False
    try:
        setup_ops.save_profile(kb, values)
        stray = [p for p in changed(old, C.profile(kb)) if not any(p == a or p.startswith(a + ".") for a in allowed)]
        if stray:
            raise C.UiError("Setup's save would also change or drop: %s. Nothing was changed. Edit the profile file by hand for this change."
                            % ", ".join(stray[:8]))
        done = True
    finally:
        if not done:
            with open(path, "wb") as fh:
                fh.write(raw)


def act_add_approver(ctx, f):
    """Add one approver to one team in gate.teams. Setup's save keeps gate.teams but has no field for it, so this changes that one list
    in the profile as data (not text) and writes it with the same C.dump_yaml Setup uses."""
    name, _ = lead_of(ctx)
    team, new = C.clean(f.get("team")), check_name(f.get("name"))
    prof = C.profile(ctx.kb)
    raw = ((prof.get("gate") or {}).get("teams")) or []
    hit = next((t for t in raw if isinstance(t, dict) and C.clean(t.get("name")) == team), None)
    if not hit:
        raise C.UiError("Pick one of the listed teams.")
    if new.lower() in [C.clean(a).lower() for a in hit.get("approvers") or []]:
        return "/teams", "%s already approves for %s." % (new, team)
    hit["approvers"] = list(hit.get("approvers") or []) + [new]
    C.dump_yaml(C.profile_path(ctx.kb), prof, "# Mētis settings. Written by the Mētis UI (Setup). Every value is the team's own.\n")
    return "/teams", "%s now approves for %s. Added by %s." % (new, team, name)


def act_add_certifier(ctx, f):
    name, _ = lead_of(ctx)
    new = check_name(f.get("name"))
    if new.lower() in kb_gate.certifiers(ctx.kb):
        return "/teams", "%s may already certify." % new
    edit_profile(ctx.kb, lambda v: v.update(certifiers=", ".join([x for x in re.split(r"[,\n]", v["certifiers"]) if C.clean(x)] + [new])),
                 ("gate.certifiers",))
    return "/teams", "%s may now certify. Added by %s." % (new, name)


def act_set_role(ctx, f):
    name, _ = lead_of(ctx)
    role, new = C.clean(f.get("role")), check_name(f.get("name"))
    if role not in setup_ops.form_values(ctx.kb)["roles"]:
        raise C.UiError("Pick one of the listed roles.")
    edit_profile(ctx.kb, lambda v: v["roles"].update({role: new}), ("owners.roles",))
    return "/teams", "%s is now %s. Saved by %s." % (new, role, name)


# =============================================================================================== /settings
SECRET_KEY = re.compile(r"(password|passwd|pwd|token|api[_-]?key|access[_-]?key|client[_-]?secret|private[_-]?key)", re.I)
SECRET_NAME = re.compile(r"^([A-Za-z_][A-Za-z0-9_.-]*|<[^>]*>)$")
ORDER = ("product", "repo", "paths", "owners", "gate", "verify", "questions", "viz", "thresholds", "db", "app", "etl", "sources", "lint")
EDITABLE = {"repo": "base_branch", "gate": "certifiers", "owners": "roles"}


def redact(data, key=""):
    """The profile as stored, except that a secret is never shown: a key named secret keeps its value only when it is a NAME."""
    if isinstance(data, dict):
        return {k: redact(v, str(k)) for k, v in data.items()}
    if isinstance(data, list):
        return [redact(v, key) for v in data]
    if isinstance(data, str) and data:
        blocked = bool(sensitive.blocking(sensitive.scan(data)))
        if key == "secret":
            return data if SECRET_NAME.match(data) and not blocked and len(data) <= 80 else HIDDEN
        if SECRET_KEY.search(key) or blocked:
            return HIDDEN
    return data


def settings(ctx, q, flash=None, error=None):
    kb = ctx.kb
    prof = C.profile(kb)
    body = ['<h1>Settings</h1><p class="lead">The profile as it is stored in <code>.metis/kb-profile.yaml</code>. A secret is never shown or accepted: '
            'where the profile names a Devin secret, only its name appears.</p>', standing(ctx)]
    if not prof:
        body.append('<div class="card soft">There is no profile yet. <a href="/setup">Fill in Setup</a> first.</div>')
        return page(ctx, "Settings", "/settings", "".join(body), flash, error)
    shown = [k for k in ORDER if k in prof] + [k for k in prof if k not in ORDER]
    for k in shown:
        note = ' <span class="pill">a lead can change %s here</span>' % esc("%s.%s" % (k, EDITABLE[k])) if k in EDITABLE else ""
        body.append('<div class="card"><h3 style="margin-top:0">%s%s</h3><pre>%s</pre></div>' % (
            esc(k), note, esc(yaml.safe_dump({k: redact(prof[k], k)}, sort_keys=False, allow_unicode=True, width=110).rstrip())))
    if "thresholds" not in prof:
        body.append('<p class="muted">This profile has no <code>thresholds</code> section. The values the tools read today are '
                    '<code>verify.strict_tags</code> (the source check) and <code>gate.allow_self_certify</code> (the gate).</p>')
    v = setup_ops.form_values(kb)
    roles = "".join('<div>%s</div>' % field("role_" + r.replace(" ", "_"), r, n) for r, n in v["roles"].items())
    body.append("<h2>Change a setting</h2><p class=\"muted\">Only a named lead can save. Everything else is changed in Setup or in the profile file. "
                "If Setup's save would touch anything beyond these three, nothing is changed and you are told.</p>")
    body.append('<div class="card">%s</div>' % form(ctx, "/settings/save", (
        field("branch", "Branch the KB pull request goes to", v["branch"], hint="repo.base_branch")
        + field("certifiers", "Other people who may certify", v["certifiers"], hint="gate.certifiers, comma separated")
        + '<h3>Who is named for each role</h3><div class="row">%s</div><p><button>Save settings</button></p>' % roles)))

    # ---- left pane: settings sections navigation
    sec_items = []
    for k in shown:
        is_edit = k in EDITABLE
        sec_items.append(C.pane_item("#sec-" + k, esc(k), "lead editable" if is_edit else "read-only"))
    sec_items.append(C.pane_item("#change-settings", "Change a setting", "forms"))
    left = C.left_pane("Settings sections", "".join(sec_items), count=len(shown))

    # ---- right pane: configuration overview
    side = [
        '<h4>Configuration overview</h4>',
        '<table>',
        '<tr><td class="muted">Product</td><td><b>%s</b></td></tr>' % esc(C.get(prof, "product.name") or "Not set"),
        '<tr><td class="muted">Base branch</td><td><code>%s</code></td></tr>' % esc(C.get(prof, "repo.base_branch") or "main"),
        '<tr><td class="muted">Sections</td><td>%d defined</td></tr>' % len(shown),
        '<tr><td class="muted">Editable in UI</td><td>%d keys</td></tr>' % len(EDITABLE),
        '</table>',
        '<h4>Security note</h4>',
        '<p class="muted">Devin secrets and sensitive values are never displayed in plaintext or saved in UI forms. Only secret names (e.g. <code>JIRA_TOKEN</code>) are accepted.</p>',
        '<h4>Storage</h4>',
        '<p class="muted">Settings are stored in <code>.metis/kb-profile.yaml</code> and versioned with the KB repository.</p>'
    ]
    right = C.right_pane("".join(side))

    return page(ctx, "Settings", "/settings", "".join(body), flash, error, left=left, right=right)


def act_settings_save(ctx, f):
    name, _ = lead_of(ctx)
    cur = setup_ops.form_values(ctx.kb)
    branch = C.clean(f.get("branch"))
    if branch and not re.match(r"^[\w./-]{1,100}$", branch):
        raise C.UiError("A branch name has letters, digits, dot, dash, slash and underscore only.")
    check_text(branch)
    certs = [check_name(x) for x in re.split(r"[,\n]", f.get("certifiers") or "") if C.clean(x)]
    roles = {r: check_name(f.get(k)) if C.clean(f.get(k)) else "" for r in cur["roles"] for k in ["role_" + r.replace(" ", "_")] if k in f}
    old_certs = [C.clean(x) for x in re.split(r"[,\n]", cur["certifiers"]) if C.clean(x)]
    what = [label for label, differs in (("branch", branch != C.clean(cur["branch"])), ("certifiers", certs != old_certs),
                                         ("roles", any(C.clean(cur["roles"].get(r)) != n for r, n in roles.items()))) if differs]
    if not what:
        return "/settings", "Nothing changed."

    def change(v):
        v["branch"], v["certifiers"] = branch, ", ".join(certs)
        v["roles"].update(roles)
    edit_profile(ctx.kb, change, ("repo.base_branch", "gate.certifiers", "owners.roles"))
    return "/settings", "Saved by %s: %s." % (name, ", ".join(what))


SCREENS = {"/audit": audit, "/teams": teams_view, "/settings": settings}
ACTIONS = {"/teams/certifier": ("/teams", act_add_certifier), "/teams/role": ("/teams", act_set_role), "/teams/approver": ("/teams", act_add_approver),
           "/settings/save": ("/settings", act_settings_save)}
NAV = [("/audit", "Audit log"), ("/teams", "Teams and rights"), ("/settings", "Settings")]
