"""The eight screens of the Metis UI as functions from the KB to HTML, and the actions behind their buttons.

Home, Setup, Build, KB files, Ask, Questions, Approve, Coverage. A screen reads; an action changes something and returns the
path to show next plus a message. Nothing in here speaks HTTP, so each one can be tested by calling it.
"""
import datetime
import os
import sys
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import ui_common as C  # noqa: E402
from ui_common import esc, form, field, pill, page  # noqa: E402
import answers  # noqa: E402
import builds  # noqa: E402
import feedback  # noqa: E402
import kb_coverage  # noqa: E402
import kb_gate  # noqa: E402
import questions  # noqa: E402
import setup_ops  # noqa: E402
import tasks  # noqa: E402
import telemetry  # noqa: E402
import trust  # noqa: E402


def need_user(ctx):
    if not C.clean(ctx.user):
        raise C.UiError("Say who you are first (top right, 'You are'). Your name goes on every approval, rating and answer.")
    return C.clean(ctx.user)


def kb_pages(kb):
    return sorted(kb_coverage.page_files(kb))


# =============================================================================================== Home
def home(ctx, q, flash=None, error=None):
    steps = setup_ops.readiness(ctx.kb)
    rows, nxt = [], None
    for key, done, label, detail, link in steps:
        if not done and nxt is None and key != "databases":
            nxt = (label, link)
        rows.append("<tr><td>%s</td><td><a href=\"%s\">%s</a></td><td class=\"muted\">%s</td></tr>" % (
            pill(done, "done", "to do"), esc(link), esc(label), esc(detail)))
    body = ["<h1>Home</h1><p class=\"lead\">Set up the project, build its knowledge base, then ask it questions.</p>"]
    if nxt:
        body.append('<div class="card soft"><b>Next:</b> <a class="btn" href="%s">%s</a></div>' % (esc(nxt[1]), esc(nxt[0])))
    body.append("<h2>Where this project stands</h2><table>%s</table>" % "".join(rows))
    reg = questions.load(questions.reg_path(ctx.kb)).get("questions") or []
    fb = feedback.load(ctx.kb).get("feedback") or []
    ts = tasks.summary(ctx.kb)
    asks = answers.all_asks(ctx.kb)
    stat = [("KB pages", len(kb_pages(ctx.kb)), "/files"), ("Open questions", sum(1 for x in reg if x.get("status") == "open"), "/questions"),
            ("Questions asked", len(asks), "/ask"), ("Waiting for a lead", sum(1 for f in fb if f.get("status") == "open" and f.get("rating") == "down")
                                                     + len(kb_gate.batches(ctx.kb)), "/approve"),
            ("Tasks for Devin", ts.get("queued", 0) + ts.get("running", 0), "/build")]
    glance = "<div class=\"grid\">%s</div>" % "".join(
        '<a class="card" href="%s" style="text-decoration:none;color:inherit"><div class="stat">%d</div><div class="muted">%s</div></a>' % (
            h, n, esc(l)) for l, n, h in stat)
    body.insert(1, glance)
    if ts.get("queued"):
        body.append('<div class="card"><b>%d task(s) wait for a Devin session.</b> <span class="muted">Open the Devin session and say '
                    '"work the Metis tasks". See Build.</span></div>' % ts["queued"])
    waiting = stat[3][1]
    n_open = stat[1][1]
    items = [
        C.pane_item("/approve", "%d approval%s waiting" % (waiting, "" if waiting == 1 else "s"), "open Approve", dot="r" if waiting else "g"),
        C.pane_item("/questions", "%d open question%s" % (n_open, "" if n_open == 1 else "s"), "open Questions", dot="a" if n_open else "g"),
        C.pane_item("/build", "%d task%s for Devin" % (ts.get("queued", 0) + ts.get("running", 0), "" if ts.get("queued", 0) + ts.get("running", 0) == 1 else "s"),
                    "open Build", dot="a" if ts.get("queued", 0) + ts.get("running", 0) else "g"),
        C.pane_item(nxt[1], "Next: %s" % esc(nxt[0]), "setup step", dot="a") if nxt else C.pane_item("/ask", "Setup is complete", "ask the KB", dot="g"),
    ]
    return page(ctx, "Home", "/", "".join(body), flash, error, left=C.left_pane("Needs attention", "".join(items)))


# =============================================================================================== Setup
def setup(ctx, q, flash=None, error=None, values=None):
    v = setup_ops.form_values(ctx.kb)
    if values:  # keep what was typed after a refused save
        v.update({k: values[k] for k in v if k not in ("roles",) and k in values})
        v["roles"] = {r: values.get("role_" + r.replace(" ", "_"), n) for r, n in v["roles"].items()}
    prof = bool(C.profile(ctx.kb))
    roles = "".join('<div>%s</div>' % field("role_" + r.replace(" ", "_"), r, n) for r, n in v["roles"].items())
    top = form(ctx, "/setup/profile", (
        '<div class="row"><div>%s</div><div>%s</div></div>' % (field("name", "Product name", v["name"], required=True),
                                                              field("short", "Short name", v["short"], hint="used in file names"))
        + '<div class="row"><div>%s</div><div>%s</div></div>' % (field("team_repo", "Team repo URL", v["team_repo"], hint="holds the KB folder"),
                                                                field("branch", "Branch the KB PR goes to", v["branch"]))
        + field("workspace", "Folder the source repos are cloned into", v["workspace"], hint="for example /home/ubuntu/repos", required=True)
        + '<div id="repos">%s</div>' % field("repos", "Source repos", v["repos"], "textarea", "one per line: name|folder|clone URL", 4)
        + field("kb_owner", "KB owner", v["kb_owner"], hint="approves the KB and may certify changes", required=True)
        + '<h3>Who answers each kind of question</h3><div class="row">%s</div>' % roles
        + field("certifiers", "Other people who may certify changes", v["certifiers"], hint="comma separated; roles with 'lead' already may")
        + '<h3 id="modules">Modules</h3>'
        + field("app_modules", "Application modules", v["app_modules"], "textarea", "one per line: name|repo/folder|kind", 3)
        + field("etl_modules", "ETL and batch modules", v["etl_modules"], "textarea", "one per line: name|repo/folder|kind", 3)
        + '<h3>Jira and Confluence (optional)</h3><div class="row"><div>%s%s</div><div>%s%s</div></div>' % (
            field("jira_url", "Jira URL", v["jira_url"]), field("jira_projects", "Jira project keys", v["jira_projects"]),
            field("conf_url", "Confluence URL", v["conf_url"]), field("conf_spaces", "Confluence space keys", v["conf_spaces"]))
        + '<div class="row"><div>%s</div><div>%s</div></div>' % (
            field("jira_secret", "Devin secret holding the Jira token", v["jira_secret"], hint="the name only, never the token"),
            field("conf_secret", "Devin secret holding the Confluence token", v["conf_secret"], hint="the name only, never the token"))
        + '<p><button>Save profile</button></p>'))
    body = ["<h1>Setup</h1><p class=\"lead\">Tell Metis about the project. Nothing is guessed: what you leave empty stays empty, "
            "and what the code cannot show becomes a question.</p>", "<div class=\"card\" id=\"profile\"><h2 style=\"margin-top:0\">1. Profile and 2. Repos</h2>",
            top, "</div>"]
    ref, dbs = setup_ops.db_text(ctx.kb)
    body.append('<div class="card" id="databases"><h2 style="margin-top:0">3. Database environments (optional)</h2>' + form(ctx, "/setup/databases", (
        field("reference", "Reference environment", ref, hint="the full database documents are built from it")
        + field("dbs", "Databases", dbs, "textarea",
                "one per line: env|label|engine|database|schemas|warehouse|connection|paths (schema-files: connection = repo, paths = SQL files)", 5)
        + '<p class="muted">Engines: %s. A database with no live connection uses <code>schema-files</code>.</p><button>Save databases</button>' % (
            ", ".join(setup_ops.ENGINES)))) + "</div>")
    det, app = setup_ops.detected(ctx.kb), setup_ops.approved(ctx.kb)
    body.append('<div class="card" id="stack"><h2 style="margin-top:0">4. Stack detection %s</h2>' % pill(bool(app), "approved", "not approved", True))
    if not prof:
        body.append('<p class="muted">Save the profile first.</p>')
    else:
        body.append(form(ctx, "/setup/detect", '<p class="muted">Reads every repo in the profile and lists what the code and config files show, '
                         'each with its file and line. Secret values are never read.</p><button class="alt">%s</button>' % (
                             "Detect again" if det else "Detect the stack")))
        if det:
            body.append(stack_table(ctx, det, app))
    body.append("</div>")
    if prof:
        rows = "".join("<tr><td>%s</td><td>%s</td><td>%s</td><td class=\"muted\">%s</td></tr>" % (
            esc(s), pill(ok is True, "ok", "failed" if ok is False else "later", ok is None), esc(what), esc(todo)) for s, ok, what, todo in
            setup_ops.check_connections(ctx.kb))
        body.append('<div class="card" id="prompts"><h2 style="margin-top:0">5. Prompts: check the connections</h2><table><tr><th>Source</th><th>Result</th><th>What it says'
                    '</th><th>What to do</th></tr>%s</table>%s</div>' % (rows, form(ctx, "/setup/check", '<button class="alt">Run the prompt check</button>')))
    else:
        body.append('<div class="card" id="prompts"><h2 style="margin-top:0">5. Prompts: check the connections</h2><p class="muted">Save the profile first.</p></div>')
    steps = [("#profile", "1 Profile", "name, owner and roles", "g" if prof else "a"),
             ("#repos", "2 Repos", "source repos to read", "g" if C.clean(v["repos"]) else "a"),
             ("#databases", "3 Database Envs", "optional", "g" if C.clean(dbs) else ""),
             ("#stack", "4 Stack Detection", "approved" if app else ("detected" if det else "not detected"), "g" if app else "a"),
             ("#prompts", "5 Prompts", "connection and prompt check", "")]
    left = C.left_pane("Setup steps", "".join(C.pane_item(h, esc(t), esc(s), dot=d) for h, t, s, d in steps))
    ready = setup_ops.readiness(ctx.kb)
    side = "<h4>Setup readiness</h4><table>%s</table>" % "".join(
        '<tr><td>%s</td><td><a href="%s">%s</a><div class="muted">%s</div></td></tr>' % (
            pill(done, "done", "to do", key == "databases"), esc(link), esc(label), esc(detail)) for key, done, label, detail, link in ready)
    side += '<p class="muted">%d of %d done.</p>' % (sum(1 for r in ready if r[1]), len(ready))
    return page(ctx, "Setup", "/setup", "".join(body), flash, error, left=left, right=C.right_pane(side))


def stack_table(ctx, det, app):
    cat, rows = None, []
    removed = {setup_ops.stack_ident(i) for i in (app.get("removed") or [])}
    for it in det.get("items") or []:
        if it.get("category") != cat:
            cat = it.get("category")
            rows.append('<tr><th colspan="3">%s</th></tr>' % esc(cat))
        name = it["name"] + (" (%s)" % it["engine"] if it.get("engine") and it["engine"] != it["name"] else "") + (
            " = %s" % it["value"] if it.get("value") else "") + (" [%s]" % it["env"] if it.get("env") else "")
        rows.append('<tr><td style="width:60px"><label style="margin:0;font-weight:400"><input type="checkbox" name="remove" value="%s"%s> remove</label></td>'
                    '<td>%s <span class="muted">in %s</span></td><td class="muted">%s</td></tr>' % (
                        esc(setup_ops.stack_ident(it)), " checked" if setup_ops.stack_ident(it) in removed else "", esc(name), esc(it.get("repo")),
                        esc((it.get("sources") or [""])[0])))
    un = "".join("<li>%s in %s <span class=\"muted\">(%s)</span></li>" % (esc(u["key"]), esc(u["repo"]), esc(u["source"])) for u in det.get("unresolved") or [])
    return form(ctx, "/setup/approve", (
        '<p>%d repos read, %d findings. Tick anything that is wrong, add what is missing, then approve.</p><table>%s</table>%s'
        '<h3>Add something detection missed</h3><div class="row"><div>%s</div><div>%s</div><div>%s</div></div>'
        '<p class="muted">Each change is recorded as an answered question with your name.</p><button>Approve the stack as %s</button>' % (
            len(det.get("repos_read") or []), len(det.get("items") or []), "".join(rows),
            ('<h3>Set outside the repo (raised as questions)</h3><ul>%s</ul>' % un) if un else "",
            field("add_category", "Category", "", hint="e.g. database"), field("add_name", "Name", "", hint="e.g. PostgreSQL"),
            field("add_repo", "Repo", ""), esc(ctx.user or "you"))))


def act_setup_profile(ctx, f):
    v = {k: f.get(k, "") for k in ("name", "short", "team_repo", "branch", "workspace", "repos", "kb_owner", "certifiers", "app_modules",
                                   "etl_modules", "jira_url", "jira_projects", "jira_secret", "conf_url", "conf_spaces", "conf_secret")}
    v["roles"] = {r: f.get("role_" + r.replace(" ", "_"), "") for r in setup_ops.ROLES}
    setup_ops.save_profile(ctx.kb, v)
    return "/setup", "Profile saved. Next: detect the tech stack."


def act_setup_detect(ctx, f):
    code, out = setup_ops.detect(ctx.kb)
    if code:
        raise C.UiError(out or "detection failed")
    return "/setup#stack", out.splitlines()[-1] if out else "Detected."


def act_setup_approve(ctx, f):
    by = need_user(ctx)
    adds = []
    if C.clean(f.get("add_category")) and C.clean(f.get("add_name")):
        adds.append({"category": f["add_category"], "name": f["add_name"], "repo": f.get("add_repo", "")})
    removes = f.getall("remove") if hasattr(f, "getall") else ([f["remove"]] if f.get("remove") else [])
    out = setup_ops.stack_changes(ctx.kb, removes, adds, by)
    return "/setup#stack", out


def act_setup_databases(ctx, f):
    n = setup_ops.save_databases(ctx.kb, f.get("reference", ""), f.get("dbs", ""))
    return "/setup#databases", "Saved %d environment(s)." % n


def act_setup_check(ctx, f):
    code, out = setup_ops.lint(ctx.kb)
    if code:
        raise C.UiError("The prompt check found problems:\n" + out[-1500:])
    return "/setup", "The prompt check passes. " + (out.splitlines()[-1] if out else "")


# =============================================================================================== Build
def task_pill(status):
    cls = {"done": "ok", "failed": "no", "cancelled": "no", "running": "warn", "queued": "warn", "waiting-user": "warn"}.get(status, "")
    return '<span class="pill %s">%s</span>' % (cls, esc(status))


def build(ctx, q, flash=None, error=None):
    body = ["<h1>Build</h1><p class=\"lead\">Build the knowledge base for this project. Model stages are done by a Devin session; "
            "Metis checks every line against its source afterwards.</p>"]
    r = builds.latest(ctx.kb)
    if r:
        r = builds.refresh(ctx.kb, r)
    bad = builds.missing(ctx.kb)
    body.append('<h2 id="readiness">Readiness checklist</h2><div class="card"><table>%s</table>%s</div>' % ("".join(
        "<tr><td>%s</td><td><a href=\"%s\">%s</a></td><td class=\"muted\">%s</td></tr>" % (
            pill(done, "done", "to do", key == "databases"), esc(link), esc(label), esc(detail))
        for key, done, label, detail, link in setup_ops.readiness(ctx.kb)),
        "" if not bad else '<p class="muted">The build cannot start until: %s</p>' % esc("; ".join(bad))))
    if not r or r["status"] != "running":
        locked = kb_gate.is_locked(ctx.kb)
        card = ['<div class="card" id="start"><h2 style="margin-top:0">%s</h2>' % ("Rebuild" if r else "Start the first build")]
        if bad:
            card.append("<p>Not ready yet:</p><ul>%s</ul>" % "".join("<li>%s</li>" % esc(b) for b in bad))
        else:
            stages = builds.model_stages(ctx.kb)
            card.append("<p>This build has %d stages for Devin, then checks and outputs by Metis. %s</p>" % (
                len(stages), "The KB is locked, so the result waits for a lead under Approve." if locked
                else "This is the first build: pages go straight into the KB, then a lead locks it."))
            card.append(form(ctx, "/build/start", '<button>Start build</button>'))
        card.append("</div>")
        body += card
    if r:
        body.append(run_card(ctx, r))
    for old in reversed(builds.runs(ctx.kb)[:-1][-5:]):
        body.append('<p class="muted">Earlier: %s, %s (%s)</p>' % (esc(old["run"]), esc(old["status"]), esc(old.get("started_by"))))
    qd = tasks.summary(ctx.kb)
    body.append('<h2 id="tasks">Devin task queue</h2><p class="muted">%d queued, %d running, %d done, %d failed.</p>' % (
        qd["queued"], qd["running"], qd["done"], qd["failed"]))
    body.append(task_table(ctx))
    # left pane: recent runs, then task status
    run_dot = {"running": "a", "waiting for lead": "a", "failed": "r", "cancelled": "r"}
    items = ['<div class="grp">Recent runs</div>']
    for old in reversed(builds.runs(ctx.kb)[-6:]):
        items.append(C.pane_item("#run", esc(old["run"]), "%s &middot; %s" % (esc(old["status"]), esc(old.get("started_by"))),
                                 dot=run_dot.get(old["status"], "g")))
    if len(items) == 1:
        items.append('<div class="it muted">No run yet.</div>')
    items.append('<div class="grp">Task status</div>')
    by_status = [s for s in ("queued", "running", "waiting-user", "done", "failed", "cancelled") if qd.get(s)]
    for s in by_status:
        items.append(C.pane_item("#tasks", esc(s), "%d task%s" % (qd[s], "" if qd[s] == 1 else "s"),
                                 dot={"done": "g", "failed": "r", "cancelled": "r"}.get(s, "a")))
    if not by_status:
        items.append('<div class="it muted">No tasks yet.</div>')
    left = C.left_pane("Runs and tasks", "".join(items))
    # right pane: environment and build metadata
    env = C.current_env(ctx) or "no environment"
    meta = [("Environment", env), ("KB", "locked" if kb_gate.is_locked(ctx.kb) else "not locked"), ("Pages in KB", str(len(kb_pages(ctx.kb)))),
            ("Runs so far", str(len(builds.runs(ctx.kb))))]
    if r:
        meta += [("Latest run", r["run"]), ("Status", r["status"]), ("Started by", str(r.get("started_by"))),
                 ("Kind", "first build" if r.get("first_build") else "incremental"), ("Stale pages", str(r.get("stale_pages", 0)))]
    side = "<h4>Environment and build</h4><table>%s</table>" % "".join(
        '<tr><td class="muted">%s</td><td>%s</td></tr>' % (esc(k), esc(v)) for k, v in meta)
    side += '<h4>Devin</h4><p class="muted">%s</p>' % esc(C.devin_text(ctx.kb))
    return page(ctx, "Build", "/build", "".join(body), flash, error, left=left, right=C.right_pane(side))


def run_card(ctx, r):
    rows = []
    for s in r["stages"]:
        extra = ""
        if s.get("task"):
            extra = ' <span class="muted">%s</span>' % esc(s["task"])
        if s.get("output"):
            extra += '<details><summary class="muted">output</summary><pre>%s</pre></details>' % esc(s["output"])
        if s.get("note"):
            extra += '<div class="muted">%s</div>' % esc(s["note"])
        rows.append("<tr><td>%s</td><td>%s%s</td><td class=\"muted\">%s</td></tr>" % (task_pill(s["status"]), esc(s["label"]), extra, esc(s["kind"])))
    acts = ""
    if r["status"] == "running":
        ready = builds.ready_to_finish(r)
        acts = form(ctx, "/build/finish", '<input type="hidden" name="run" value="%s"><button%s>Check and bring in the pages</button> %s' % (
            esc(r["run"]), "" if ready else ' class="alt"', "" if ready else '<span class="muted">waits until every Devin stage is done</span>'))
        acts += form(ctx, "/build/cancel", '<input type="hidden" name="run" value="%s"><button class="alt bad">Cancel this run</button>' % esc(r["run"]), cls="inline")
    elif r["status"] == "waiting for lead":
        acts = '<p>The pages are proposed. <a class="btn" href="/approve">A lead certifies them under Approve</a></p>'
    return ('<div class="card" id="run"><h2 style="margin-top:0">Run %s %s</h2><p class="muted">Started by %s on %s. %s. %d pages are stale since the last build.</p>'
            '<table>%s</table>%s</div>') % (esc(r["run"]), task_pill(r["status"]), esc(r.get("started_by")), esc(r.get("started")),
                                             "First build" if r.get("first_build") else "Incremental build", r.get("stale_pages", 0), "".join(rows), acts)


def task_table(ctx):
    ts = tasks.all_tasks(ctx.kb)
    if not ts:
        return '<p class="muted">No tasks yet.</p>'
    rows = "".join('<tr><td>%s</td><td>%s</td><td>%s</td><td class="muted">%s</td><td>%s</td></tr>' % (
        esc(t["id"]), task_pill(t["status"]), esc(t["title"]), esc(t.get("claimed_by") or ""),
        '<a href="/task?id=%s">instructions</a>' % esc(t["id"])) for t in reversed(ts[-30:]))
    return "<table><tr><th>Task</th><th>Status</th><th>What</th><th>Devin session</th><th></th></tr>%s</table>" % rows


def task_view(ctx, q):
    t = tasks.get(ctx.kb, q.get("id", ""))
    extra = ""
    if t["status"] in ("failed", "cancelled", "running"):
        extra = form(ctx, "/task/requeue", '<input type="hidden" name="id" value="%s"><button class="alt">Queue again</button>' % esc(t["id"]))
    body = ('<h1>%s</h1><p class="lead">%s, %s</p><div class="card"><b>Give this to a Devin session</b> (or say "work the Metis tasks"):'
            '<pre>%s</pre></div>%s<p><a href="/build">Back to Build</a></p>') % (
        esc(t["id"]), task_pill(t["status"]), esc(t["title"]), esc(t["instructions"]), extra)
    if t.get("note"):
        body += '<p class="muted">Note: %s</p>' % esc(t["note"])
    return page(ctx, t["id"], "/build", body)


def act_build_start(ctx, f):
    r = builds.start(ctx.kb, need_user(ctx))
    return "/build", "Run %s started. %d stages are waiting for a Devin session." % (r["run"], sum(1 for s in r["stages"] if s["kind"] == "model"))


def act_build_finish(ctx, f):
    r = builds.finish(ctx.kb, f.get("run", ""), need_user(ctx))
    bad = [s for s in r["stages"] if s["status"] == "failed"]
    if bad:
        raise C.UiError("Stopped at: %s\n%s" % (bad[0]["label"], bad[0].get("output", "")[-1500:]))
    return "/build", "Run %s: %s." % (r["run"], r["status"])


def act_build_cancel(ctx, f):
    builds.cancel(ctx.kb, f.get("run", ""), need_user(ctx))
    return "/build", "Run cancelled."


def act_task_requeue(ctx, f):
    tasks.requeue(ctx.kb, f.get("id", ""))
    return "/build", "%s is queued again." % f.get("id")


# =============================================================================================== KB files
def file_tree(ctx, pages, sel="", find=""):
    """Left pane: pages grouped by top folder, filtered by the search words."""
    f = C.clean(find).lower()
    shown = [p for p in pages if not f or f in p.lower()]
    groups = {}
    for rel in shown:
        groups.setdefault(rel.split("/")[0] if "/" in rel else "(top)", []).append(rel)
    out = []
    for g, rels in sorted(groups.items()):
        out.append('<div class="grp">%s <span class="c">(%d)</span></div>' % (esc(g), len(rels)))
        for rel in rels[:60]:
            out.append(C.pane_item("/files?page=%s" % rel, esc(os.path.basename(rel)), esc(os.path.dirname(rel)), on=(rel == sel)))
        if len(rels) > 60:
            out.append('<div class="it muted">%d more. Narrow the search.</div>' % (len(rels) - 60))
    if not shown:
        out.append('<div class="it muted">No page matches.</div>')
    flt = form(ctx, "/files", '<input type="text" name="find" value="%s" placeholder="Filter files...">' % esc(find), method="get", cls="flt")
    return C.left_pane("KB files", "".join(out), len(pages), top=flt)


def files(ctx, q, flash=None, error=None):
    sel = q.get("page")
    pages = kb_pages(ctx.kb)
    tr = None
    try:
        tr = trust.Trust(ctx.kb)
    except Exception:
        tr = None
    if sel:
        return file_view(ctx, sel, tr)
    find = q.get("find", "")
    if C.clean(find):
        pages_shown = [p for p in pages if C.clean(find).lower() in p.lower()]
    else:
        pages_shown = pages
    groups = {}
    for rel in pages_shown:
        groups.setdefault(rel.split("/")[0] if "/" in rel else "(top)", []).append(rel)
    body = ["<h1>KB files</h1><p class=\"lead\">%d pages. Open one to read it with its sources and trust signals.</p>" % len(pages)]
    if not pages:
        body.append('<div class="card soft">Nothing is built yet. <a href="/build">Build the KB</a>.</div>')
    for g, rels in sorted(groups.items()):
        rows = []
        for rel in rels:
            sig = tr.page(rel) if tr else None
            rows.append('<tr><td><a href="/files?page=%s">%s</a></td><td class="muted">%s</td></tr>' % (
                esc(rel), esc(rel), esc(trust.Trust.page_text(sig, False) if sig else "")))
        body.append("<h2>%s</h2><table>%s</table>" % (esc(g), "".join(rows)))
    other = [("CROSS-LAYER/LINK_GRAPH.yaml", "Link graph"), ("CROSS-LAYER/IMPACT_MATRIX.yaml", "Impact matrix"), ("CROSS-LAYER/COVERAGE.yaml", "Coverage report")]
    have = [(p, n) for p, n in other if os.path.isfile(os.path.join(ctx.kb, p))]
    if have:
        body.append("<h2>Generated</h2><p>%s</p>" % " &middot; ".join('<a href="/files?page=%s">%s</a>' % (esc(p), esc(n)) for p, n in have))
    if os.path.isfile(os.path.join(ctx.kb, "VISUALIZATION", "index.html")):
        body.append('<p><a href="/viz/index.html">Open the generated visualizations</a> (ontology, ERD, health)</p>')
    return page(ctx, "KB files", "/files", "".join(body), flash, error, left=file_tree(ctx, pages, "", find))


def safe_rel(kb, rel):
    p = os.path.normpath(os.path.join(kb, rel))
    if not p.startswith(os.path.normpath(kb) + os.sep) or not os.path.isfile(p):
        raise C.UiError("not a KB file: %s" % rel)
    return p


def origin_chip(origin):
    cls = {"parsed": "ok", "ai-proposed": "warn"}.get(origin, "")
    return '<span class="pill %s">%s</span>' % (cls, esc(origin or "unknown"))


def dependency_side(kb, rel):
    """Right pane: what this page's graph entity depends on (upstream) and what depends on it (downstream), from
    .metis/graph.sqlite, each with its origin (parsed or ai-proposed). Empty when there is no graph or no entity of that name."""
    stem = os.path.splitext(os.path.basename(rel))[0].lower()
    if not (os.path.isfile(os.path.join(kb, ".metis", "graph.sqlite")) or os.path.isfile(os.path.join(kb, "CROSS-LAYER", "LINK_GRAPH.yaml"))):
        return ""
    try:
        import graph_store
        con = graph_store.connect(kb)
        try:
            nodes = [r[0] for r in con.execute("select id from nodes where lower(name)=? order by id", (stem,))][:3]
        finally:
            con.close()
        out = ""
        for node in nodes:
            up, _ = graph_store.upstream(kb, node, depth=1, limit=50)
            down, _ = graph_store.impact(kb, node, depth=1, limit=50)
            out += "<h4>%s</h4>" % esc(node)
            for title, rows, key in (("Upstream", up, "changes"), ("Downstream", down, "moves")):
                items = "".join("<div>%s %s</div>" % (esc(r[key]), origin_chip(r["via"][-1].get("origin"))) for r in rows)
                out += "<h4>%s (%d)</h4>%s" % (title, len(rows), items or '<div class="muted">none</div>')
        return out
    except (Exception, SystemExit):
        return ""


def file_view(ctx, rel, tr):
    path = safe_rel(ctx.kb, rel)
    text = C.read_text(path)
    note = ""
    try:  # claim labels: lines above the signed-in name's clearance are left out and counted (no effect when the KB has no labels)
        import claim_labels
        text, hidden = claim_labels.Viewer(ctx.kb, C.clean(ctx.user)).filter(rel, text)
        if hidden:
            note = '<div class="card soft">%d line%s withheld by label. Ask a lead if you need %s.</div>' % (
                hidden, "" if hidden == 1 else "s", "it" if hidden == 1 else "them")
    except Exception:  # noqa: BLE001  fail closed: never show text that could not be checked
        text, note = "", '<div class="card soft">This page could not be checked against its labels, so it is not shown.</div>'
    sig = ""
    if tr and rel.endswith((".md", ".yaml", ".yml")):
        try:
            sig = '<div class="card soft"><b>Trust signals</b> <span class="muted">(facts, not a score)</span><br>%s</div>' % esc(
                trust.Trust.page_text(tr.page(rel)))
        except Exception:
            sig = ""
    shown = C.render_md(text) if rel.endswith(".md") else "<pre>%s</pre>" % esc(text)
    props = [("Folder", os.path.dirname(rel) or "(top)"), ("Size", "%d bytes" % os.path.getsize(path)),
             ("Last changed", datetime.datetime.fromtimestamp(os.path.getmtime(path)).strftime("%d %b %Y, %H:%M")),
             ("Citations", str(len(C.TAG.findall(text))))]
    side = "<h4>Properties</h4><table>%s</table>" % "".join('<tr><td class="muted">%s</td><td>%s</td></tr>' % (esc(k), esc(v)) for k, v in props)
    side += dependency_side(ctx.kb, rel)
    sug = ('<a class="btn alt" href="/suggest?page=%s">Suggest an edit</a>' % urllib.parse.quote(rel)
           if os.path.isfile(os.path.join(os.path.dirname(os.path.abspath(__file__)), "screens_suggest.py")) else "")
    side += '<h4>Next</h4><p><a class="btn alt" href="/ask">Ask about this</a> %s</p>' % sug
    return page(ctx, rel, "/files", '<p class="muted"><a href="/files">KB files</a> / %s</p><h1>%s</h1>%s<div class="card">%s</div>' % (
        esc(rel), esc(os.path.basename(rel)), sig + note, shown),
        left=file_tree(ctx, kb_pages(ctx.kb), rel, ""), right=C.right_pane(side))


# =============================================================================================== Ask
def ask_side(ctx, a):
    """Right pane: the pages the answer used and what its confidence is built from."""
    if not a or a.get("status") == "waiting":
        return C.right_pane("<h4>Answer basis</h4><p class=\"muted\">The pages an answer used show here, with how its confidence was computed.</p>")
    chk = a.get("checked") or {}
    files_ = "".join('<tr><td><a href="/files?page=%s">%s</a></td></tr>' % (esc(f), esc(f)) for f in a.get("files") or [])
    out = "<h4>Answer basis</h4>%s" % ("<table>%s</table>" % files_ if files_ else '<p class="muted">No KB page was used.</p>')
    c = a.get("confidence")
    if c:
        out += "<h4>Confidence is built from</h4><table>%s</table>" % "".join("<tr><td>%s</td></tr>" % esc(r) for r in c["reasons"])
    out += ('<h4>Checked</h4><table><tr><td class="muted">Lines checked</td><td>%d</td></tr><tr><td class="muted">Source problems</td><td>%d</td></tr></table>'
            % (chk.get("lines", 0), len(chk.get("problems") or [])))
    out += '<p class="muted">Confidence is computed from the KB lines found. Thumbs-down reasons go to a lead. Nothing changes in the KB until a lead approves.</p>'
    return C.right_pane(out)


def ask(ctx, q, flash=None, error=None):
    aid = q.get("id")
    body = ["<h1>Ask</h1><p class=\"lead\">Ask the KB a question. Every line of the answer quotes a KB page and is checked against it. "
            "A point the KB does not cover is shown as not covered, never filled in.</p>"]
    body.append(form(ctx, "/ask/new", (
        field("question", "Your question", q.get("question", ""), hint="e.g. Which tables does pets have a foreign key to?", required=True)
        + '<p><label style="display:inline;font-weight:400">Answer for <select name="audience">%s</select></label> '
          '<span class="muted">same true lines, ordered for the reader; it never changes a fact or what you may see</span></p>' % C.audience_options(ctx)
        + '<p><label style="display:inline;font-weight:400"><input type="radio" name="mode" value="local" checked> Answer now from the KB lines</label> '
          '&nbsp; <label style="display:inline;font-weight:400"><input type="radio" name="mode" value="devin"> Ask a Devin session (reads and reasons, then is checked)</label></p>'
          '<button>Ask</button>')))
    if aid:
        body.append(answer_card(ctx, answers.get(ctx.kb, aid)))
    allasks = list(reversed(answers.all_asks(ctx.kb)))
    items = "".join(C.pane_item("/ask?id=%s" % a["id"], esc(a["question"][:70]), "%s &middot; %s" % (esc(a["by"]), rating_pill(a)), on=(a["id"] == aid))
                    for a in allasks[:40]) or '<div class="it muted">No question yet.</div>'
    cur = answers.get(ctx.kb, aid) if aid else None
    return page(ctx, "Ask", "/ask", "".join(body), flash, error,
                left=C.left_pane("Conversations", items, len(allasks)), right=ask_side(ctx, cur))


def rating_pill(a):
    if a.get("status") == "waiting":
        return '<span class="pill warn">waiting for Devin</span>'
    r = a.get("rating")
    return pill(r == "up", "liked", "not rated") if r != "down" else '<span class="pill no">disliked</span>'


def page_link(p, title=None):
    return '<a href="/files?page=%s">%s</a>' % (esc(p), esc(title or p))


def waiting_for_you(ctx, a, t):
    """Devin asked the asker to say more. One box per question; the reply goes back to the session."""
    cur = t["rounds"][-1]
    qs = "".join('<p><b>%s</b></p>%s' % (esc(q), field("r%d" % i, "Your answer", "", "textarea", rows=2)) for i, q in enumerate(cur["questions"]))
    note = '<p class="muted">The Devin session read the KB first and needs this to find the right place. Answer what you can; a short answer is fine.</p>'
    return ('<div class="card soft"><h3 style="margin-top:0">Devin has a question for you</h3>%s%s</div>' % (
        note, form(ctx, "/ask/reply", '<input type="hidden" name="id" value="%s">%s<p><button>Send</button></p>' % (esc(a["id"]), qs))))


def guidance_card(ctx, a):
    g = a.get("guidance") or {}
    if not g:
        return ""
    out = ['<div class="card soft"><h3 style="margin-top:0">Let me help you find it</h3>']
    if g.get("known"):
        out.append('<p>I searched the KB for <b>%s</b>. It knows %s.</p>' % (
            esc(", ".join(g["searched"])), ", ".join("<b>%s</b> (%d page%s)" % (esc(k["word"]), k["pages"], "" if k["pages"] == 1 else "s") for k in g["known"])))
    elif g.get("searched"):
        out.append('<p>I searched the KB for <b>%s</b>, and none of those words appear in it.</p>' % esc(", ".join(g["searched"])))
    if g.get("unknown") and g.get("known"):
        out.append('<p>The KB never uses: <b>%s</b>.</p>' % esc(", ".join(g["unknown"])))
    for t in g.get("typos") or []:
        opts = " ".join(form(ctx, "/ask/reword", '<input type="hidden" name="id" value="%s"><input type="hidden" name="question" value="%s">'
                             '<button class="alt">%s</button>' % (esc(a["id"]), esc(o["question"]), esc(o["word"])), cls="inline") for o in t["options"])
        out.append('<p>I could not find <b>%s</b>. Did you mean: %s</p>' % (esc(t["word"]), opts))
    if g.get("nearest"):
        out.append('<p>The nearest pages are: %s.</p>' % ", ".join(page_link(n["page"], n["title"]) for n in g["nearest"]))
    elif g.get("overview"):
        out.append('<p>Nothing matches yet. These pages show what the KB covers: %s.</p>' % ", ".join(page_link(n["page"], n["title"]) for n in g["overview"]))
    if g.get("names"):
        out.append('<p class="muted">Names the KB uses, for example: %s.</p>' % esc(", ".join(g["names"])))
    if g.get("tips"):
        out.append("<p><b>To get an answer</b></p><ul>%s</ul>" % "".join("<li>%s</li>" % esc(x) for x in g["tips"]))
    out.append(form(ctx, "/ask/clarify", '<input type="hidden" name="id" value="%s">%s<p><button>Ask again</button></p>' % (
        esc(a["id"]), field("text", "Tell me more about what you meant", "", "textarea",
                            "a name, a screen, a table, the layer, or what you will do with the answer", 2))))
    out.append("</div>")
    return "".join(out)


def confidence_badge(c):
    if not c:
        return ""
    cls = {"High": "ok", "Medium": "warn", "Low": "no", "None": "no"}[c["band"]]
    why = "".join("<li>%s</li>" % esc(x) for x in c["reasons"])
    return ('<p><span class="pill %s">Confidence: %s &middot; %d / 100</span> '
            '<span class="muted">rule-based from the checked answer, not guessed; uncalibrated until the '
            '<a href="/usage#calibration">Usage</a> check shows High beats Low</span></p>'
            '<ul class="muted" style="margin-top:0">%s</ul>') % (cls, esc(c["band"]), c["score"], why)


def rounds_card(t):
    out = []
    for r in (t or {}).get("rounds") or []:
        if r.get("replies") is not None:
            out.append("".join('<p class="muted">Devin asked: %s<br>%s replied: %s</p>' % (esc(q), esc(r.get("replied_by")), esc(x or "(no answer)"))
                               for q, x in zip(r["questions"], r["replies"])))
    return "".join(out)


def answer_card(ctx, a):
    out = ['<div class="card"><div class="muted">%s asked: %s%s</div>' % (esc(a["by"]), esc(a["question"]),
                                                                      (" &middot; direction: " + esc(a["direction"])) if a.get("direction") else "")]
    if a["status"] == "waiting":
        t = tasks.get(ctx.kb, a["task"]) if a.get("task") else None
        out.append(rounds_card(t))
        if t and t["status"] == "waiting-user":
            out.append("</div>")
            out.append(waiting_for_you(ctx, a, t))
            return "".join(out)
        out.append('<p><b>Waiting for a Devin session.</b> Task %s is %s. <a href="/task?id=%s">See the instructions</a>. '
                   'This page shows the answer once the session completes the task and it passes the check.</p></div>' % (
                       esc(a.get("task")), esc(t["status"] if t else "?"), esc(a.get("task"))))
        return "".join(out)
    chk = a.get("checked") or {}
    out.append(rounds_card(tasks.get(ctx.kb, a["task"]) if a.get("task") else None))
    out.append(confidence_badge(a.get("confidence")))
    out.append(audience_note(a.get("audience")))
    out.append('<div>%s</div>' % C.render_md(answers.answer_text(ctx.kb, a)))
    out.append('<p>%s <span class="muted">%d lines checked against the KB</span>%s</p>' % (
        pill(not chk.get("problems"), "0 source problems", "%d source problems" % len(chk.get("problems") or []), False),
        chk.get("lines", 0), (" &middot; used " + ", ".join('<a href="/files?page=%s">%s</a>' % (esc(f), esc(f)) for f in a.get("files") or [])) if a.get("files") else ""))
    for h in a.get("hints") or []:
        out.append('<p class="muted">A lead approved this direction for a similar question: %s</p>' % esc(h["direction"]))
    if a.get("follows"):
        out.append('<p class="muted">This is the second try for <a href="/ask?id=%s">%s</a>, with the direction given.</p>' % (esc(a["follows"]), esc(a["follows"])))
    out.append("</div>")
    out.append(guidance_card(ctx, a))
    if a.get("feedback"):
        out.append('<div class="card soft">Rated %s as %s. %s</div>' % (esc(a["feedback"]), esc(a["rating"]), feedback_line(ctx, a)))
    else:
        out.append(rate_forms(ctx, a))
    return "".join(out)


def feedback_line(ctx, a):
    f = next((x for x in feedback.load(ctx.kb)["feedback"] if x["id"] == a["feedback"]), {})
    if f.get("question_id"):
        return "Your correction is question %s in the register for the right lead to confirm. The KB is not changed until a lead certifies it." % f["question_id"]
    if f.get("redirect"):
        return "Your direction is kept for you now and for everyone once a lead approves it."
    return "Thank you."


def rate_forms(ctx, a):
    up = form(ctx, "/ask/rate", '<input type="hidden" name="id" value="%s"><input type="hidden" name="rating" value="up">'
              '<button class="thumb" title="Right: like this answer" aria-label="Like">&#128077;</button>' % esc(a["id"]), cls="inline")
    down = form(ctx, "/ask/rate", (
        '<input type="hidden" name="id" value="%s"><input type="hidden" name="rating" value="down">' % esc(a["id"])
        + field("why", "What is wrong or missing?", "", "textarea", rows=2)
        + '<p><b>Then give one of these</b> <span class="muted">(a dislike needs exactly one)</span></p>'
        + field("correct", "The right answer", "", "textarea", "the claim becomes a question for a lead; the KB is not changed", 2)
        + field("redirect", "Or where to look instead", "", hint="a folder, page, table, or \"the ETL, not the app\"; Metis asks again at once")
        + '<p><button class="bad">Dislike</button></p>'))
    box = "dn-" + esc(a["id"])
    return ('<div class="card rate"><b>Was this right?</b><input type="checkbox" id="%s" class="dn-toggle">%s'
            '<label for="%s" class="thumb" title="Wrong or incomplete: dislike this answer" aria-label="Dislike">&#128078;</label>'
            '<div class="reason">%s</div></div>') % (box, up, box, down)


def audience_note(info):
    """Say what the audience lens did, so a reader knows the answer is ordered for them and what else the KB holds."""
    if not info:
        return ""
    bits = []
    left = {k: v for k, v in (info.get("left_out") or {}).items() if v}
    if left:
        bits.append("%d more matching line%s at the %s layer%s did not fit" % (
            sum(left.values()), "" if sum(left.values()) == 1 else "s", " and ".join(sorted(left)), "" if len(left) == 1 else "s"))
    if info.get("links_cut"):
        bits.append("%d link line%s left out for this reader" % (info["links_cut"], "" if info["links_cut"] == 1 else "s"))
    used = info.get("layers_used") or []
    if len(used) == 1:
        bits.append("every line comes from the %s layer, so the order is the same for every audience; the KB has no page at another "
                    "layer for this question" % used[0])
    return '<p class="muted">Ordered for: %s.%s Ask again for another audience to see them.</p>' % (
        esc(info.get("describe", "")), (" " + esc("; ".join(bits)) + ".") if bits else "")


def act_ask_new(ctx, f):
    r = answers.ask(ctx.kb, f.get("question", ""), need_user(ctx), mode="devin" if f.get("mode") == "devin" else "local",
                    audience=f.get("audience") or None)
    return "/ask?id=" + r["id"], ("Queued for a Devin session as %s." % r["task"]) if r["status"] == "waiting" else "Answered."


def act_ask_reply(ctx, f):
    t = tasks.get(ctx.kb, answers.get(ctx.kb, f.get("id", "")).get("task") or "")
    n = len(t["rounds"][-1]["questions"]) if t.get("rounds") else 0
    tasks.reply(ctx.kb, t["id"], need_user(ctx), [f.get("r%d" % i, "") for i in range(n)])
    return "/ask?id=" + f.get("id", ""), "Sent. The Devin session carries on with your answer."


def act_ask_clarify(ctx, f):
    r = answers.clarify(ctx.kb, f.get("id", ""), need_user(ctx), f.get("text", ""))
    return "/ask?id=" + r["id"], ("Queued for a Devin session as %s." % r["task"]) if r["status"] == "waiting" else "Asked again with what you said."


def act_ask_reword(ctx, f):
    r = answers.reword(ctx.kb, f.get("id", ""), need_user(ctx), f.get("question", ""))
    return "/ask?id=" + r["id"], "Asked with that wording."


def act_ask_rate(ctx, f):
    by = need_user(ctx)
    item, again = answers.rate(ctx.kb, f.get("id", ""), by, f.get("rating", ""), f.get("why"), f.get("correct"), f.get("redirect"))
    if again:
        return "/ask?id=" + again["id"], "Recorded %s. Asked again with your direction." % item["id"]
    return "/ask?id=" + f.get("id", ""), "Recorded %s." % item["id"]


# =============================================================================================== Questions
def questions_view(ctx, q, flash=None, error=None):
    reg = questions.load(questions.reg_path(ctx.kb)).get("questions") or []
    status = q.get("status", "open")
    shown = [x for x in reg if status == "all" or x.get("status") == status]
    shown.sort(key=lambda x: (str(x.get("priority")), str(x.get("answer_role")), str(x.get("id"))))
    body = ["<h1>Questions</h1><p class=\"lead\">What the sources could not show, and who can answer it. An answer is cited by later builds.</p>"]
    people = questions.people(ctx.kb)
    for x in shown:
        who = people.get(x.get("answer_role")) or "not named in Setup"
        ctxl = "".join('<li class="muted">%s</li>' % C.inline(c) for c in x.get("context") or [])
        opts = "".join('<li>A source offers: %s</li>' % C.inline(o) for o in x.get("possible_answers") or [])
        blocks = x.get("blocks") or []
        blocks = blocks if isinstance(blocks, list) else [blocks]
        card = ['<div class="card" id="q-%s"><b>%s</b> <span class="pill">%s</span> <span class="pill">%s</span> <span class="muted">for %s (%s)</span><p>%s</p>' % (
            esc(x["id"]), esc(x["id"]), esc(x.get("priority")), esc(x.get("type")), esc(x.get("answer_role")), esc(who), esc(x.get("question")))]
        if ctxl or opts:
            card.append("<ul>%s%s</ul>" % (ctxl, opts))
        if blocks:
            card.append('<p class="muted">Blocks: %s</p>' % ", ".join('<a href="/files?page=%s">%s</a>' % (esc(b), esc(b)) for b in blocks if os.path.isfile(os.path.join(ctx.kb, b))) or esc(", ".join(blocks)))
        if x.get("status") == "open":
            card.append(form(ctx, "/questions/answer", '<input type="hidden" name="id" value="%s">%s<button>Record answer as %s</button>' % (
                esc(x["id"]), field("answer_" + x["id"], "Your answer, and where it comes from", "", "textarea", rows=2), esc(ctx.user or "you"))))
        else:
            card.append('<p><b>Answer:</b> %s <span class="muted">%s, %s</span></p>' % (esc(x.get("answer")), esc(x.get("answered_by")), esc(x.get("answered_on"))))
        card.append("</div>")
        body.append("".join(card))
    if not shown:
        body.append('<div class="card soft">No %s questions.</div>' % esc(status))
    body.append('<h2 id="raise">Raise a question</h2>' + form(ctx, "/questions/raise", (
        field("question", "Question", "", "textarea", rows=2)
        + '<div class="row"><div><label for="type">Kind</label><select id="type" name="type">%s</select></div>'
          '<div><label for="priority">Priority</label><select id="priority" name="priority"><option>P2</option><option>P1</option><option>P3</option></select></div></div>'
          % "".join("<option>%s</option>" % esc(t) for t in questions.TYPES) + '<p><button class="alt">Raise</button></p>')))
    # left pane: filter tabs and the quick list of open questions with priority dots
    counts = {s: len(reg) if s == "all" else sum(1 for x in reg if x.get("status") == s) for s in ("open", "answered", "closed", "all")}
    flt = '<div class="flt">%s</div>' % " ".join('<a class="pill%s" href="/questions?status=%s">%s %d</a>' % (
        " blue" if s == status else "", s, s, counts[s]) for s in ("open", "answered", "closed", "all"))
    dot = {"P1": "r", "P2": "a", "P3": "g"}
    quick = [x for x in reg if x.get("status") == "open"]
    quick.sort(key=lambda x: (str(x.get("priority")), str(x.get("id"))))
    items = "".join(C.pane_item("/questions?status=open#q-%s" % x["id"], "<b>%s</b>" % esc(x["id"]), esc(str(x.get("question"))[:60]),
                                dot=dot.get(str(x.get("priority")), "")) for x in quick[:40]) or '<div class="it muted">No open question.</div>'
    left = C.left_pane("Open questions", items, counts["open"], top=flt)
    # right pane: summary table
    blocked = set()
    roles = {}
    for x in quick:
        b = x.get("blocks") or []
        blocked.update(str(f) for f in (b if isinstance(b, list) else [b]) if f)
        roles[str(x.get("answer_role"))] = roles.get(str(x.get("answer_role")), 0) + 1
    side = ('<h4>Summary</h4><table><tr><td class="muted">Open</td><td>%d</td></tr><tr><td class="muted">Answered</td><td>%d</td></tr>'
            '<tr><td class="muted">Blocked files</td><td>%d</td></tr></table>' % (counts["open"], counts["answered"], len(blocked)))
    side += "<h4>Open by role</h4>" + ("<table>%s</table>" % "".join('<tr><td>%s</td><td>%d</td></tr>' % (esc(r), n) for r, n in sorted(roles.items()))
                                      if roles else '<p class="muted">none</p>')
    return page(ctx, "Questions", "/questions", "".join(body), flash, error, left=left, right=C.right_pane(side))


def act_question_answer(ctx, f):
    by = need_user(ctx)
    qid = f.get("id", "")
    text = C.clean(f.get("answer_" + qid))
    if not text:
        raise C.UiError("Write the answer first.")
    path = os.path.join(ctx.kb, ".metis", "_answer.yaml")
    C.dump_yaml(path, {"answers": [{"id": qid, "answer": text, "answered_by": by}]})
    try:
        code = questions.cmd_answer(ctx.kb, path)
    finally:
        os.remove(path)
    if code:
        raise C.UiError("The answer was not accepted.")
    return "/questions", "Answer recorded for %s." % qid


def act_question_raise(ctx, f):
    qid, added = questions.cmd_raise(ctx.kb, f.get("question", ""), f.get("type", ""), need_user(ctx), f.get("priority", "P2"))
    return "/questions", ("Raised %s." if added else "That question is already open as %s.") % qid


# =============================================================================================== Approve
def approve(ctx, q, flash=None, error=None):
    leads = kb_gate.certifiers(ctx.kb)
    me = kb_gate.clean(ctx.user).lower()
    is_lead = me in leads
    locked = kb_gate.is_locked(ctx.kb)
    body = ["<h1>Approve</h1><p class=\"lead\">Only a named lead can approve. Ratings and corrections wait here; nothing enters the KB without a lead's name on it.</p>"]
    names = ", ".join(v[0] for v in leads.values()) or "nobody is named yet (Setup: KB owner and lead roles)"
    my_role = leads[me][1] if is_lead else ""
    body.append('<p>%s <span class="muted">Leads: %s.</span></p>' % (
        pill(is_lead, ("you are a lead (%s)" % my_role) if is_lead else "", "you are not a lead" if ctx.user else "set your name top right", True), esc(names)))
    # ---- first build: lock
    pages = len(kb_pages(ctx.kb))
    if not locked and pages:
        rep = verify_summary(ctx.kb)
        body.append('<div class="card"><h2 style="margin-top:0">Lock the KB</h2><p>The first build is in the KB (%d pages; %s). When you accept it, lock it: from then on '
                    'every change needs a lead to certify it.</p>%s</div>' % (pages, esc(rep), form(ctx, "/approve/lock", '<button>Accept and lock as %s</button>' % esc(ctx.user or "you"))))
    # ---- batches
    batches = kb_gate.batches(ctx.kb)
    if locked:
        body.append("<h2>Proposed changes</h2>")
        if not batches:
            body.append('<div class="card soft">Nothing waits for certification.</div>')
        for b in batches:
            body.append(batch_card(ctx, b, is_lead))
    # ---- feedback
    fb = [f for f in feedback.load(ctx.kb)["feedback"] if f.get("rating") == "down"]
    open_fb = [f for f in fb if f.get("status") in ("open", "resolved")]
    body.append("<h2>Ratings waiting for a lead (%d)</h2>" % len(open_fb))
    if not open_fb:
        body.append('<div class="card soft">No disliked answer is waiting.</div>')
    for f in reversed(open_fb):
        what = ("Right answer given: %s" % f["correct"]) if f.get("correct") else ("Direction given: %s" % f.get("redirect"))
        card = ['<div class="card" id="%s"><b>%s</b> <span class="pill no">disliked</span> <span class="muted">by %s on %s</span><p>%s</p>'
                '<p class="muted">Why: %s<br>%s%s</p>' % (esc(f["id"]), esc(f["id"]), esc(f["by"]), esc(f["on"]), esc(f["question"]), esc(f.get("why")), esc(what),
                                                         (" &rarr; question %s" % esc(f["question_id"])) if f.get("question_id") else "")]
        if f.get("cited_files"):
            card.append('<p class="muted">Pages the answer used: %s</p>' % ", ".join('<a href="/files?page=%s">%s</a>' % (esc(x), esc(x)) for x in f["cited_files"]))
        card.append(form(ctx, "/approve/feedback", '<input type="hidden" name="id" value="%s">%s<button name="do" value="approve">Approve</button> '
                         '<button class="alt" name="do" value="decline">Decline</button>' % (esc(f["id"]), field("note", "Note (needed to decline)", "", hint="why"))))
        card.append("</div>")
        body.append("".join(card))
    done = [f for f in fb if f.get("status") in ("approved", "declined")]
    if done:
        body.append("<h3>Decided</h3><table>%s</table>" % "".join('<tr><td>%s</td><td>%s</td><td>%s</td><td class="muted">%s, %s</td></tr>' % (
            esc(f["id"]), esc(f["status"]), esc(f["question"][:70]), esc(f.get("decided_by")), esc(f.get("decided_on"))) for f in done[-10:]))
    up = [f for f in feedback.load(ctx.kb)["feedback"] if f.get("rating") == "up" and f.get("status") == "open"]
    if up:
        body.append('<h3>Likes (%d)</h3><p class="muted">Approving a like adds the question to the golden set, which tests later changes.</p><table>%s</table>' % (
            len(up), "".join('<tr><td>%s</td><td>%s</td><td class="muted">%s</td><td>%s</td></tr>' % (
                esc(f["id"]), esc(f["question"][:80]), esc(f["by"]),
                form(ctx, "/approve/feedback", '<input type="hidden" name="id" value="%s"><button class="alt" name="do" value="approve">Approve</button>' % esc(f["id"]), cls="inline")) for f in up)))
    items = []
    for b in (batches if locked else []):
        items.append('<a class="it" href="#b-%s"><span class="dot r"></span>Batch %s<span class="s">%d files</span></a>' % (
            esc(b), esc(b), len(kb_gate.pending_files(kb=ctx.kb, batch=b))))
    for f in reversed(open_fb):
        items.append('<a class="it" href="#%s"><span class="dot a"></span>%s<span class="s">%s</span></a>' % (esc(f["id"]), esc(f["question"][:60]), esc(f["by"])))
    if not items:
        items.append('<div class="it muted">Nothing is waiting.</div>')
    who = "".join('<tr><td>%s</td><td class="muted">%s</td></tr>' % (esc(v[0]), esc(v[1])) for v in leads.values()) or '<tr><td class="muted">nobody named yet</td></tr>'
    side = ('<h4>Who can approve this</h4><table>%s</table><p>%s</p>'
            '<p class="muted">Approval is logged with your name and time, in the KB repo.</p>') % (
        who, pill(is_lead, "You can approve", "You cannot approve", True))
    return page(ctx, "Approve", "/approve", "".join(body), flash, error,
                left=C.left_pane("Pending, riskiest first", "".join(items), len(batches if locked else []) + len(open_fb)), right=C.right_pane(side))


def verify_summary(kb):
    rep = __import__("verify_kb").Checker(kb).run()
    return "%d source problems" % len(rep["problems"]) if rep["problems"] else "every line checks against its source"


def batch_card(ctx, b, is_lead):
    files_ = kb_gate.pending_files(kb=ctx.kb, batch=b)
    digest = os.path.join(kb_gate.pending_dir(ctx.kb, b), "DIGEST.md")
    d = C.render_md(C.read_text(digest)) if os.path.isfile(digest) else '<p class="muted">No digest yet.</p>'
    acts = form(ctx, "/approve/batch", (
        '<input type="hidden" name="batch" value="%s">%s<button name="do" value="certify"%s>Certify all %d files as %s</button> '
        '<button class="alt bad" name="do" value="reject">Reject the batch</button>' % (
            esc(b), field("note", "Reason (needed to reject; or why personal-looking data may stay)", ""), "" if is_lead else ' class="alt"', len(files_), esc(ctx.user or "you"))))
    return '<div class="card" id="b-%s"><h3 style="margin-top:0">Batch %s <span class="muted">%d files</span></h3><details><summary>Digest, riskiest first</summary>%s</details>%s</div>' % (
        esc(b), esc(b), len(files_), d, acts)


def act_approve_lock(ctx, f):
    n = kb_gate.lock(ctx.kb, need_user(ctx))
    return "/approve", "KB locked: %d files certified by %s." % (n, ctx.user)


def act_approve_batch(ctx, f):
    by, batch = need_user(ctx), f.get("batch", "")
    if f.get("do") == "reject":
        n = kb_gate.reject(ctx.kb, batch, by, f.get("note", ""))
        return "/approve", "Rejected %d files in %s." % (n, batch)
    n = kb_gate.certify(ctx.kb, batch, by, accept_review=f.get("note") or None)
    msg = "Certified %d files in %s by %s." % (n, batch, by)
    for r in builds.runs(ctx.kb):
        if r.get("batch") == batch and r.get("status") == "waiting for lead":
            builds.after_certification(ctx.kb, r["run"])
            msg += " The outputs were rebuilt."
    return "/approve", msg


def act_approve_feedback(ctx, f):
    by, fid = need_user(ctx), f.get("id", "")
    try:
        if f.get("do") == "decline":
            feedback.decline(ctx.kb, fid, by, f.get("note", ""))
            return "/approve", "%s declined." % fid
        feedback.approve(ctx.kb, fid, by, f.get("note") or None)
    except feedback.FeedbackError as err:
        raise C.UiError(str(err))
    return "/approve", "%s approved by %s." % (fid, by)


# =============================================================================================== Coverage
def coverage_left(ctx, rep):
    """Left pane: how much of each kind of thing has a page, from the coverage report."""
    objs = (rep or {}).get("objects") or {}
    ct = (rep or {}).get("catalogue_tables") or {}
    sql = (rep or {}).get("sql_read")
    sql = sql if isinstance(sql, dict) else {}

    def of(*types):
        n = sum((objs.get(t) or {}).get("in_graph", 0) for t in types)
        miss = sum((objs.get(t) or {}).get("named_in_no_page", 0) for t in types)
        return n, miss

    def dot(miss):
        return "g" if not miss else "a"
    tables_n = ct.get("in_registry", 0) or of("table", "view")[0]
    tables_miss = ct.get("named_in_no_page", 0) if ct.get("in_registry") else of("table", "view")[1]
    jobs_n, jobs_miss = of("job")
    api_n, api_miss = of("endpoint")
    repos = C.get(C.profile(ctx.kb), "sources.repos") or {}
    unparsed = len(sql.get("not_parsed") or [])
    rows = [("#objects", "Tables", "%d of %d named in a page" % (tables_n - tables_miss, tables_n), dot(tables_miss)),
            ("#repos", "Repos", "%d in the profile" % len(repos), "g" if repos else "a"),
            ("#objects", "Jobs / ETL", "%d of %d named in a page" % (jobs_n - jobs_miss, jobs_n), dot(jobs_miss)),
            ("#objects", "APIs", "%d of %d named in a page" % (api_n - api_miss, api_n), dot(api_miss)),
            ("#sql", "Unparsed SQL", "%d file%s not parsed" % (unparsed, "" if unparsed == 1 else "s") if sql else "not run", dot(unparsed) if sql else "")]
    return C.left_pane("Coverage by type", "".join(C.pane_item(h, esc(t), esc(s), dot=d) for h, t, s, d in rows))


def coverage(ctx, q, flash=None, error=None):
    body = ["<h1>Coverage</h1><p class=\"lead\">What the KB does not know yet, and what has been read.</p>"]
    path = os.path.join(ctx.kb, "CROSS-LAYER", "COVERAGE.yaml")
    rep = C.load_yaml(path)
    refresh = form(ctx, "/coverage/refresh", '<button class="alt">Refresh the numbers</button>', cls="inline")
    if not rep:
        body.append(refresh)
        body.append('<div class="card soft">No coverage report yet. It is made by a build, or press Refresh once the KB has a link graph.</div>')
        side = "<h4>Coverage</h4><p class=\"muted\">No report yet.</p><h4>Refresh</h4>" + refresh
        return page(ctx, "Coverage", "/coverage", "".join(body), flash, error, left=coverage_left(ctx, None), right=C.right_pane(side))
    body.append('<p class="muted">As of %s. %s</p>' % (esc(rep.get("as_of")), esc(rep.get("method"))))
    objs = rep.get("objects") or {}
    rows = "".join("<tr><td>%s</td><td>%d</td><td>%d</td><td class=\"muted\">%s</td></tr>" % (
        esc(t), v["in_graph"], v["named_in_no_page"], esc(", ".join(v["names"][:8]) + (" ..." if len(v["names"]) > 8 else ""))) for t, v in objs.items())
    body.append("<h2 id=\"objects\">Objects no page names</h2><table><tr><th>Type</th><th>In graph</th><th>Named in no page</th><th>Which</th></tr>%s</table>" % rows)
    ct = rep.get("catalogue_tables") or {}
    body.append("<h2>Catalogue tables</h2><p>%d in the registry, %d named in no page. <span class=\"muted\">%s</span></p>" % (
        ct.get("in_registry", 0), ct.get("named_in_no_page", 0), esc(", ".join((ct.get("names") or [])[:10]))))
    sql = rep.get("sql_read")
    body.append('<h2 id="sql">Unparsed SQL</h2>')
    if isinstance(sql, dict):
        bad = sql.get("not_parsed") or []
        part = sql.get("partly_read") or []
        body.append("<p>%d of %d SQL files parsed; %d not parsed, %d partly read, %d links dropped.</p>" % (
            sql.get("parsed", 0), sql.get("files", 0), len(bad), len(part), sql.get("links_dropped", 0)))
        if bad:
            body.append("<table><tr><th>File</th><th>Why</th></tr>%s</table>" % "".join(
                "<tr><td>%s</td><td class=\"muted\">%s</td></tr>" % (esc(b.get("file")), esc(b.get("reason"))) if isinstance(b, dict)
                else "<tr><td>%s</td><td></td></tr>" % esc(b) for b in bad[:40]))
    else:
        body.append('<p class="muted">%s</p>' % esc(sql or "no SQL report"))
    inu = rep.get("impact_not_understood") or {}
    body.append("<h2>Unsupported relations</h2>")
    if inu.get("relations") or inu.get("node_types"):
        body.append("<p>Relations: %s. Node types: %s.</p>" % (esc(", ".join(map(str, inu.get("relations") or [])) or "none"),
                                                              esc(", ".join(map(str, inu.get("node_types") or [])) or "none")))
    else:
        body.append('<p class="muted">The impact matrix understands every relation and node type.</p>')
    body.append("<h2>Where links come from</h2><p>%s</p>" % (", ".join("%s: %d" % (esc(k), v) for k, v in (rep.get("edges_by_origin") or {}).items()) or "no links"))
    oq = rep.get("open_questions") or {}
    body.append('<h2>Blocked files</h2><p>%d open question(s) (%s). <a href="/questions">Answer them</a></p>' % (
        oq.get("total", 0), ", ".join("%s: %d" % (esc(k), v) for k, v in (oq.get("by_priority") or {}).items()) or "none"))
    blocked = oq.get("blocked_files") or {}
    if blocked:
        body.append("<table>%s</table>" % "".join("<tr><td>%s</td><td class=\"muted\">%s</td></tr>" % (esc(k), esc(", ".join(v))) for k, v in blocked.items()))
    rej = rep.get("rejected_links") or []
    if rej:
        body.append("<h2>Links rejected (%d)</h2><p class=\"muted\">A link whose source does not check out is kept out of the graph.</p>" % len(rej))
    t = None
    try:
        t = telemetry.report(ctx.kb)
        body.append("<h2>What is read</h2><p>%d answers and %d context packs recorded; %d of %d pages never used.</p>" % (
            t["answers"], t["packs"], len(t["pages_never_used"]), t["pages"]))
        if t["look_first"]:
            body.append('<p>Pages in disliked answers, look first: %s</p>' % ", ".join('<a href="/files?page=%s">%s</a>' % (esc(f), esc(f)) for f in t["look_first"][:8]))
        if t["pages_never_used"]:
            body.append('<details><summary class="muted">Pages never used</summary><p>%s</p></details>' % ", ".join(esc(x) for x in t["pages_never_used"][:40]))
    except Exception:
        t = None
    unnamed = sum(v["named_in_no_page"] for v in objs.values())
    metrics = [("Objects in the graph", sum(v["in_graph"] for v in objs.values())), ("Named in no page", unnamed),
               ("Catalogue tables unnamed", ct.get("named_in_no_page", 0)), ("Rejected links", len(rej)),
               ("Open questions", oq.get("total", 0)), ("Blocked files", len(blocked))]
    if isinstance(sql, dict):
        metrics.append(("SQL files not parsed", len(sql.get("not_parsed") or [])))
    if t:
        metrics.append(("Pages never used", "%d of %d" % (len(t["pages_never_used"]), t["pages"])))
    side = "<h4>Coverage metrics</h4><table>%s</table>" % "".join(
        '<tr><td class="muted">%s</td><td>%s</td></tr>' % (esc(k), esc(v)) for k, v in metrics)
    side += '<h4>As of</h4><p class="muted">%s</p><h4>Refresh</h4>%s' % (esc(rep.get("as_of")), refresh)
    return page(ctx, "Coverage", "/coverage", "".join(body), flash, error, left=coverage_left(ctx, rep), right=C.right_pane(side))


def act_coverage_refresh(ctx, f):
    code, out = C.run_tool("kb_coverage.py", [ctx.kb], kb=ctx.kb)
    if code:
        raise C.UiError(out or "coverage failed")
    return "/coverage", "Refreshed."
