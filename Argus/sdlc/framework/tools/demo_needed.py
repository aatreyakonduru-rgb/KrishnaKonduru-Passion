#!/usr/bin/env python3
"""DEMO-NEEDED demos: find the stories owed one, record the run with on-screen captions, publish it.

  find      Acme Claims stories labelled DEMO-NEEDED, not yet released, with an open PR in Jira. Each gets an
            action: v1 (no demo yet), vN (a linked defect was fixed after the last demo) or skip.
  record    start / stop a screen recording (ffmpeg x11grab, H.264 MP4). Captions are drawn by ffmpeg
            from two text files, so they survive page loads.
  caption   card / step / result: change the captions, hold them on screen, and log each result.
  publish   Confluence: Acme Claims Demo Recordings > <EPIC> > <KEY> > one <KEY>_AC<n>_demo page per
            criterion. The run is cut into one video per criterion (<KEY>_AC1_demo_v1.mp4, after a fix
            <KEY>_AC1_demo_v2_after-<DEFECT>-fix.mp4), each on its criterion's page with its versions;
            the story page lists every criterion's result and links its page; then one Jira comment.
            Dry run unless --live. Labels are never changed. Nothing is
            overwritten: an existing attachment name is skipped.

Runs are kept under ~/.sdlc/demos/<KEY>/v<N>/.
"""
import argparse
import datetime
import html
import json
import os
import re
import shutil
import signal
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import team_links  # noqa: E402

LABEL = "DEMO-NEEDED"
RELEASED = ("Ready For Release", "Closed", "Resolved", "Abandoned")
DEFECT_LINKS = ("Blocks", "Linked CNR")
FIXED = ("Resolved", "Closed")
EPIC_FIELD = "customfield_10010"
AC_FIELD = "customfield_10003"
JIRA = (os.environ.get("SDLC_SANDBOX_URL") or "https://jira.acme.example").rstrip("/")
JIRA_TOKEN_ENV = "ACME_JIRA_TOKEN"
MAX_MB = 100
HOLD = 4
WIDTH = 1280
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
HOME = os.environ.get("SDLC_DEMO_HOME") or os.path.expanduser("~/.sdlc/demos")


class DemoError(Exception):
    pass


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ctx():
    return ssl._create_unverified_context()


# ---- Jira and Confluence ------------------------------------------------------------------------

class Http:
    """Bearer-token JSON client. dry_run prints writes instead of sending them."""

    def __init__(self, base, token_env, dry_run=True):
        self.base, self.token_env, self.dry_run = base, token_env, dry_run
        self.token = os.environ.get(token_env, "")

    def call(self, method, path, payload=None, raw=None, headers=None):
        if not self.token:
            raise DemoError("%s is not set in this session" % self.token_env)
        h = {"Authorization": "Bearer " + self.token, "Accept": "application/json"}
        data = raw
        if payload is not None:
            data, h["Content-Type"] = json.dumps(payload).encode(), "application/json"
        h.update(headers or {})
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, context=_ctx(), timeout=600) as resp:
                body = resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise DemoError("%s returned %d on %s. Not retrying." % (self.base, exc.code, path)) from exc
            raise DemoError("%s returned %d on %s: %s" % (self.base, exc.code, path,
                            exc.read().decode(errors="replace")[:300])) from exc
        return json.loads(body) if body else {}

    def get(self, path, **params):
        return self.call("GET", path + ("?" + urllib.parse.urlencode(params) if params else ""))

    def write(self, method, path, payload=None, raw=None, headers=None, note=""):
        if self.dry_run:
            print("DRY-RUN %s %s%s %s" % (method, self.base, path, note or json.dumps(payload)[:400]))
            return {"id": "(dry-run)", "version": {"number": 1}, "results": [{"id": "(dry-run)"}]}
        return self.call(method, path, payload, raw, headers)


def jira(dry_run=True):
    return Http(JIRA, JIRA_TOKEN_ENV, dry_run)


def confluence(dry_run=True):
    c = team_links.confluence()
    return Http(c["host"], c["token_env"], dry_run)


# ---- find -----------------------------------------------------------------------------------------

def search_jql():
    return ('project = ACME AND labels = "%s" AND issuetype = Story AND status not in (%s) ORDER BY key'
            % (LABEL, ", ".join('"%s"' % s for s in RELEASED)))


def split_acs(text):
    """Acceptance criteria as a list: one per bullet, number or 'AC n' line; else one per line."""
    text = re.sub(r"\{[a-z]+[^}]*\}", "", text or "")
    items = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^(?:[*#\-\u2022]+|\d+[.)]|AC[- ]?\d+\s*[:.)\-]?)\s*(.*)$", line, re.I)
        if m and m.group(1).strip():
            items.append(m.group(1).strip())
        elif items and not m:
            items[-1] += " " + line
        elif not m:
            items.append(line)
    return [{"id": "AC-%d" % (i + 1), "text": t} for i, t in enumerate(items)]


def linked_defects(issue):
    out = []
    for link in (issue.get("fields") or {}).get("issuelinks") or []:
        other = link.get("outwardIssue") or link.get("inwardIssue") or {}
        f = other.get("fields") or {}
        if link.get("type", {}).get("name") in DEFECT_LINKS and (f.get("issuetype") or {}).get("name") == "Defect":
            out.append({"key": other.get("key"), "status": (f.get("status") or {}).get("name", ""),
                        "summary": f.get("summary", "")})
    return out


def pr_summary(client, issue_id):
    """Counts from Jira's development panel. The service account cannot read the PR details
    (reviewers, approval): the session checks those with its git tools."""
    try:
        s = client.get("/rest/dev-status/1.0/issue/summary", issueId=issue_id)
    except DemoError as exc:
        return {"error": str(exc)}
    d = ((s.get("summary") or {}).get("pullrequest") or {}).get("overall") or {}
    det = d.get("details") or {}
    return {"open": det.get("openCount", 0), "merged": det.get("mergedCount", 0), "total": det.get("total", 0)}


def decide(story, pr, history):
    """history: the results of earlier versions (dicts with version and defects_fixed)."""
    if pr.get("error"):
        return {"action": "skip", "reason": "Jira development panel not readable: " + pr["error"]}
    if not pr.get("open"):
        return {"action": "skip", "reason": "no open PR in Jira"}
    if not history:
        return {"action": "v1", "version": 1, "defects": []}
    covered = {d for h in history for d in h.get("defects_fixed") or []}
    new = [d["key"] for d in story["defects"] if d["status"] in FIXED and d["key"] not in covered]
    if not new:
        return {"action": "skip", "reason": "demo is up to date (v%d)" % max(h["version"] for h in history)}
    return {"action": "v%d" % (max(h["version"] for h in history) + 1),
            "version": max(h["version"] for h in history) + 1, "defects": new}


def story_from(issue):
    f = issue.get("fields") or {}
    return {"key": issue["key"], "id": issue.get("id"), "summary": f.get("summary", ""),
            "status": (f.get("status") or {}).get("name", ""), "epic": f.get(EPIC_FIELD) or "",
            "acs": split_acs(f.get(AC_FIELD) or ""), "defects": linked_defects(issue)}


def history_of(conf, key, page=None):
    """Earlier versions, read from the <KEY>_demo_vN.json attachments on the story page."""
    titles = (story_title(key), story_title(key) + " (demos)")
    pages = [page] if page else [p for p in (find_page(conf, t) for t in titles) if p]
    out = []
    for pg in pages:
        found = conf.get("/rest/api/content/%s/child/attachment" % pg["id"], limit=200)
        for a in found.get("results") or []:
            if re.match(r"^%s_demo_v\d+\.json$" % re.escape(key), a.get("title", "")):
                out.append(_download_json(conf, a["_links"]["download"]))
        if out:
            break
    return sorted(out, key=lambda h: h["version"])


def _download_json(conf, link):
    req = urllib.request.Request(conf.base + link, headers={"Authorization": "Bearer " + conf.token})
    with urllib.request.urlopen(req, context=_ctx(), timeout=120) as resp:
        return json.loads(resp.read())


def find(jira_client, conf_client):
    fields = ",".join(["summary", "status", "issuelinks", EPIC_FIELD, AC_FIELD])
    found = jira_client.get("/rest/api/2/search", jql=search_jql(), maxResults=100, fields=fields)
    out = []
    for issue in found.get("issues") or []:
        story = story_from(issue)
        story["pr"] = pr_summary(jira_client, issue["id"])
        history = history_of(conf_client, story["key"])
        story["history"] = [h["version"] for h in history]
        story.update(decide(story, story["pr"], history))
        out.append(story)
    return out


# ---- record and caption ---------------------------------------------------------------------------

def run_dir(key, version):
    return os.path.join(HOME, key, "v%d" % version)


def _state_path(key, version):
    return os.path.join(run_dir(key, version), "run.json")


def load_run(key, version):
    with open(_state_path(key, version), encoding="utf-8") as fh:
        return json.load(fh)


def save_run(run):
    path = _state_path(run["key"], run["version"])
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(run, fh, indent=2)
    os.replace(tmp, path)


def _write_caption(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


def wrap(text, width=90):
    words, lines, cur = (text or "").split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        lines.append(cur)
    return "\n".join(lines[:3])


def ffmpeg_command(display, size, top, bottom, out, width=WIDTH):
    def text(path, y):
        return ("drawtext=fontfile=%s:textfile=%s:reload=1:expansion=none:fontsize=22:fontcolor=white:line_spacing=6:"
                "box=1:boxcolor=black@0.72:boxborderw=14:x=(w-text_w)/2:y=%s" % (FONT, path, y))
    vf = "scale=%d:-2,%s,%s" % (width, text(top, "24"), text(bottom, "h-text_h-30"))
    return ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "x11grab", "-framerate", "10",
            "-video_size", size, "-i", display, "-vf", vf, "-c:v", "libx264", "-preset", "veryfast",
            "-crf", "30", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out]


def screen_size(display):
    try:
        out = subprocess.run(["xdpyinfo", "-display", display], capture_output=True, text=True, timeout=10).stdout
        m = re.search(r"dimensions:\s+(\d+x\d+)", out)
        if m:
            return m.group(1)
    except (OSError, subprocess.SubprocessError):
        pass
    return "1024x768"


def cmd_record(args):
    d = run_dir(args.key, args.version)
    if args.what == "start":
        os.makedirs(d, exist_ok=True)
        top, bottom = os.path.join(d, "caption-top.txt"), os.path.join(d, "caption-bottom.txt")
        _write_caption(top, "%s demo v%d" % (args.key, args.version))
        _write_caption(bottom, args.summary or "Starting")
        out = os.path.join(d, full_file(args.key, args.version, args.defects or ()))
        display = os.environ.get("DISPLAY", ":0")
        proc = subprocess.Popen(ffmpeg_command(display, screen_size(display), top, bottom, out),
                                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=open(os.path.join(d, "ffmpeg.log"), "w"))
        save_run({"key": args.key, "version": args.version, "summary": args.summary or "",
                  "defects_fixed": args.defects or [], "commit": args.commit or "", "pr": args.pr or "",
                  "started": now(), "t0": time.time(), "pid": proc.pid, "video": out,
                  "captions": [top, bottom], "results": []})
        print("recording %s (pid %d)" % (out, proc.pid))
        return 0
    run = load_run(args.key, args.version)
    try:
        os.kill(run["pid"], signal.SIGINT)
    except ProcessLookupError:
        pass
    for _ in range(60):
        try:
            os.kill(run["pid"], 0)
            time.sleep(0.5)
        except ProcessLookupError:
            break
    run["finished"], run["duration_s"] = now(), round(time.time() - run["t0"])
    save_run(run)
    size = os.path.getsize(run["video"]) / 1e6 if os.path.exists(run["video"]) else 0
    print("stopped: %s, %d s, %.1f MB" % (run["video"], run["duration_s"], size))
    return 0 if size else 1


def cmd_caption(args):
    run = load_run(args.key, args.version)
    top, bottom = run["captions"]
    if args.kind == "card":
        _write_caption(top, wrap(args.title))
        _write_caption(bottom, wrap(args.text or ""))
    elif args.kind == "step":
        _write_caption(top, wrap("%s: %s" % (args.ac, ac_text(run, args.ac, args.title))))
        _write_caption(bottom, wrap("Doing: %s\nChecking: %s" % (args.doing or "", args.checking or ""), 110))
        mark(run, args.ac, "running", "", ac_text(run, args.ac, args.title))
    else:
        label = {"passed": "PASSED", "failed": "FAILED", "not run": "NOT RUN"}[args.result]
        _write_caption(bottom, wrap("%s %s: %s" % (args.ac, label, args.note or ""), 110))
        mark(run, args.ac, args.result, args.note or "", ac_text(run, args.ac, args.title))
    save_run(run)
    time.sleep(args.hold)
    return 0


def ac_text(run, ac, given):
    for r in run["results"]:
        if r["id"] == ac and r.get("text"):
            return r["text"]
    return given or ""


def mark(run, ac, result, note, text):
    for r in run["results"]:
        if r["id"] == ac:
            r.update({"result": result, "note": note or r.get("note", ""), "text": text or r.get("text", "")})
            return
    run["results"].append({"id": ac, "text": text, "result": result, "note": note,
                           "at_s": round(time.time() - run["t0"], 1)})


# ---- publish --------------------------------------------------------------------------------------

def ac_tag(ac):
    return ac.replace("-", "").upper()


def epic_title(epic):
    return epic or "Demos without an epic"


def story_title(key):
    return key


def ac_title(key, ac):
    return "%s_%s_demo" % (key, ac_tag(ac))


def _tail(defects):
    return "_after-%s-fix" % "-".join(defects) if defects else ""


def ac_file(key, ac, version, defects=()):
    return "%s_%s_demo_v%d%s.mp4" % (key, ac_tag(ac), version, _tail(defects))


def full_file(key, version, defects=()):
    return "%s_demo_v%d_full%s.mp4" % (key, version, _tail(defects))


def find_page(conf, title):
    space = team_links.confluence()["space"]
    found = conf.get("/rest/api/content", spaceKey=space, title=title, expand="version,ancestors")
    res = found.get("results") or []
    return res[0] if res else None


def create_page(conf, title, parent_id, body):
    payload = {"type": "page", "title": title, "space": {"key": team_links.confluence()["space"]},
               "ancestors": [{"id": parent_id}], "body": {"storage": {"value": body, "representation": "storage"}}}
    page = conf.write("POST", "/rest/api/content", payload, note="create page %r under %s" % (title, parent_id))
    page.setdefault("title", title)
    return page


def place(conf, title, parent_id, body):
    """The page with this title under parent_id, created if missing. Titles are unique in the space,
    so when another page already has the title, '<title> (demos)' is used instead."""
    for t in (title, title + " (demos)"):
        page = None if parent_id == "(dry-run)" else find_page(conf, t)
        if not page:
            return create_page(conf, t, parent_id, body)
        if any(str(a.get("id")) == str(parent_id) for a in page.get("ancestors") or []):
            return page
    raise DemoError("%r and %r already exist outside the demo pages" % (title, title + " (demos)"))


def attachment_names(conf, page):
    if page.get("id") == "(dry-run)":
        return set()
    found = conf.get("/rest/api/content/%s/child/attachment" % page["id"], limit=200)
    return {a["title"] for a in found.get("results") or []}


def multipart(name, data, content_type):
    boundary = uuid.uuid4().hex
    head = ('--%s\r\nContent-Disposition: form-data; name="file"; filename="%s"\r\nContent-Type: %s\r\n\r\n'
            % (boundary, name, content_type)).encode()
    tail = ('\r\n--%s\r\nContent-Disposition: form-data; name="minorEdit"\r\n\r\ntrue\r\n--%s--\r\n'
            % (boundary, boundary)).encode()
    return head + data + tail, "multipart/form-data; boundary=" + boundary


def attach(conf, page_id, path, name, content_type, existing):
    if name in existing:
        print("kept %s: already attached, never overwritten" % name)
        return False
    if conf.dry_run:
        print("DRY-RUN attach %s (%.1f MB) to page %s" % (name, os.path.getsize(path) / 1e6, page_id))
        return True
    with open(path, "rb") as fh:
        body, ctype = multipart(name, fh.read(), content_type)
    conf.call("POST", "/rest/api/content/%s/child/attachment" % page_id, raw=body,
              headers={"Content-Type": ctype, "X-Atlassian-Token": "no-check"})
    return True


def split_by_ac(run, out_dir):
    """{AC id: file}: the run cut at the time each criterion's step started (no re-encode). The opening
    card stays in the full run; the summary card ends the last criterion's file."""
    starts = [r for r in run["results"] if r.get("at_s") is not None]
    parts = {}
    for i, r in enumerate(starts):
        end = starts[i + 1]["at_s"] if i + 1 < len(starts) else None
        path = os.path.join(out_dir, ac_file(run["key"], r["id"], run["version"], run["defects_fixed"]))
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", str(r["at_s"]), "-i", run["video"]]
        cmd += (["-to", str(end - r["at_s"])] if end else []) + ["-c", "copy", path]
        subprocess.run(cmd, check=True)
        parts[r["id"]] = path
    return parts


def counts(results):
    c = {"passed": 0, "failed": 0, "not run": 0}
    for r in results:
        c[r["result"] if r["result"] in c else "not run"] += 1
    return c


def counts_text(results):
    c = counts(results)
    return "%d passed, %d failed, %d not run" % (c["passed"], c["failed"], c["not run"])


def change(before, after):
    if before is None:
        return "new"
    return "same" if before == after else "%s → %s" % (before, after)


def _what(v):
    fixed = v.get("defects_fixed") or []
    return "after the fix for " + ", ".join(fixed) if fixed else "initial run"


def _player(name):
    return ('<ac:structured-macro ac:name="multimedia"><ac:parameter ac:name="width">960</ac:parameter>'
            '<ac:parameter ac:name="name"><ri:attachment ri:filename="%s"/></ac:parameter></ac:structured-macro>'
            % html.escape(name))


def _result(v, ac):
    return next((r for r in v["results"] if r["id"] == ac), None)


def ac_body(story, ac, versions):
    """One criterion's page: its text, a row per version, and its videos newest first."""
    e = html.escape
    text = next((r.get("text", "") for v in versions for r in v["results"] if r["id"] == ac and r.get("text")), "")
    rows, prev = [], None
    for v in versions:
        r = _result(v, ac)
        res = r["result"] if r else None
        rows.append("<tr><td>v%d</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
            v["version"], e(v.get("finished", v.get("started", ""))[:10]), e(v.get("commit", "")[:12]),
            e(", ".join(v.get("defects_fixed") or []) or "initial"), e(res or "-"), e((r or {}).get("note", "")),
            e(change(prev, res) if res else "-")))
        prev = res or prev
    watch = "".join("<h3>v%d: %s</h3>%s" % (v["version"], e(_what(v)), _player(v["videos"][ac]))
                    for v in reversed(versions) if (v.get("videos") or {}).get(ac))
    return ("<p><strong>%s %s</strong> of %s %s</p>"
            "<table><tbody><tr><th>Version</th><th>Date</th><th>Commit</th><th>Defects fixed</th><th>Result</th>"
            "<th>Note</th><th>Change</th></tr>%s</tbody></table><h2>Watch</h2>%s"
            % (e(ac), e(text), e(story["key"]), e(story.get("summary", "")), "".join(rows), watch))


def story_body(story, versions):
    """The story page: each criterion's latest result and its demo page, the versions, the full runs."""
    e = html.escape
    last, before = versions[-1], (versions[-2] if len(versions) > 1 else None)
    ids = []
    for v in versions:
        ids += [r["id"] for r in v["results"] if r["id"] not in ids]
    acs = []
    for ac in ids:
        r = _result(last, ac) or {}
        b = _result(before, ac) if before else None
        page = next((v["pages"][ac] for v in reversed(versions) if (v.get("pages") or {}).get(ac)), ac_title(story["key"], ac))
        text = next((x.get("text", "") for v in versions for x in v["results"] if x["id"] == ac and x.get("text")), "")
        moved = change(b["result"] if b else None, r.get("result")) if before else "new"
        acs.append('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td><ac:link><ri:page ri:content-title="%s"/>'
                   '</ac:link></td></tr>' % (e(ac), e(text), e(r.get("result", "-")), e(moved), e(page)))
    rows = "".join("<tr><td>v%d</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
        v["version"], e(v.get("finished", v.get("started", ""))[:10]), e(v.get("commit", "")[:12]), e(v.get("pr", "")),
        e(", ".join(v.get("defects_fixed") or []) or "initial"), e(counts_text(v["results"]))) for v in versions)
    watch = "".join("<h3>v%d: %s</h3>%s" % (v["version"], e(_what(v)), _player(v["full"]))
                    for v in reversed(versions) if v.get("full"))
    return ("<p>Recorded by Devin from the acceptance criteria of <strong>%s</strong> %s. Each criterion has its own "
            "demo page below this one. The DEMO-NEEDED label is left as it is. Earlier versions are kept.</p>"
            "<h2>Acceptance criteria (v%d)</h2><table><tbody><tr><th>AC</th><th>Criterion</th><th>Result</th>"
            "<th>Change since v%s</th><th>Demo page</th></tr>%s</tbody></table>"
            "<h2>Versions</h2><table><tbody><tr><th>Version</th><th>Date</th><th>Commit</th><th>PR</th>"
            "<th>Defects fixed</th><th>Result</th></tr>%s</tbody></table><h2>Watch the full run</h2>%s"
            % (e(story["key"]), e(story.get("summary", "")), last["version"],
               before["version"] if before else "-", "".join(acs), rows, watch))


def recorded(conf, root=None):
    """{story key: {"url", "acs"}} for every story with at least one AC demo page under the
    Acme Claims Demo Recordings page, read with one paged CQL search of its descendants."""
    root = root or team_links.confluence()["pages"]["demo_recordings"]["id"]
    titles, start = [], 0
    while True:
        found = conf.get("/rest/api/content/search", cql="ancestor = %s AND type = page" % root,
                         limit=200, start=start)
        page = found.get("results") or []
        titles += [(p.get("title", ""), p.get("id")) for p in page]
        if len(page) < 200:
            break
        start += len(page)
    ids = dict(titles)
    out = {}
    for title, _ in titles:
        m = re.match(r"^(.+)_AC\d+_demo$", title)
        if not m:
            continue
        key = m.group(1)
        story = ids.get(story_title(key)) or ids.get(story_title(key) + " (demos)") or ids[title]
        row = out.setdefault(key, {"url": "%s/pages/viewpage.action?pageId=%s" % (conf.base, story), "acs": 0})
        row["acs"] += 1
    return out


def page_url(conf, page):
    if page.get("id") == "(dry-run)":
        return "(dry-run page)"
    return conf.base + ((page.get("_links") or {}).get("webui") or "/pages/viewpage.action?pageId=%s" % page["id"])


def jira_comment(story, run, url):
    return ("Demo v%d recorded by Devin (%s), one video per acceptance criterion, at commit %s: %s\n%s."
            % (run["version"], _what(run), (run.get("commit") or "?")[:12], url, counts_text(run["results"])))


def _update(conf, page, body, note):
    ver = ((page.get("version") or {}).get("number") or 1) + 1
    conf.write("PUT", "/rest/api/content/%s" % page["id"],
               {"id": page["id"], "type": "page", "title": page["title"], "version": {"number": ver, "minorEdit": True},
                "body": {"storage": {"value": body, "representation": "storage"}}}, note=note)


def publish(story, run, conf, jira_client, max_mb=MAX_MB):
    if any(r["result"] == "running" for r in run["results"]):
        raise DemoError("an acceptance criterion has no result yet; caption result each one first")
    if not os.path.exists(run["video"]):
        raise DemoError("no video at %s" % run["video"])
    key = story["key"]
    root = team_links.confluence()["pages"]["demo_recordings"]["id"]
    epic = place(conf, epic_title(story.get("epic")), root,
                 "<p>Demo recordings for the stories in %s.</p>" % html.escape(story.get("epic") or "no epic"))
    spage = place(conf, story_title(key), epic["id"], "<p>Demo recordings for %s.</p>" % html.escape(key))
    existing = attachment_names(conf, spage)
    results_name = "%s_demo_v%d.json" % (key, run["version"])
    if results_name in existing:
        raise DemoError("v%d is already published for %s" % (run["version"], key))
    parts = split_by_ac(run, os.path.dirname(run["video"]))
    too_big = [os.path.basename(p) for p in parts.values() if os.path.getsize(p) > max_mb * 1e6]
    if too_big:
        raise DemoError("over %d MB even per criterion: %s" % (max_mb, ", ".join(too_big)))
    full = os.path.basename(run["video"]) if os.path.getsize(run["video"]) <= max_mb * 1e6 else None
    if full:
        attach(conf, spage["id"], run["video"], full, "video/mp4", existing)
    pages = {}
    for r in run["results"]:
        ap = place(conf, ac_title(key, r["id"]), spage["id"], "<p>%s</p>" % html.escape(r.get("text", "")))
        attach(conf, ap["id"], parts[r["id"]], os.path.basename(parts[r["id"]]), "video/mp4", attachment_names(conf, ap))
        pages[r["id"]] = ap
    record = {k: run[k] for k in ("key", "version", "summary", "defects_fixed", "commit", "pr", "started",
                                  "finished", "duration_s", "results") if k in run}
    record.update({"videos": {ac: os.path.basename(p) for ac, p in parts.items()}, "full": full,
                   "pages": {ac: p.get("title", ac_title(key, ac)) for ac, p in pages.items()}})
    rpath = os.path.join(os.path.dirname(run["video"]), results_name)
    with open(rpath, "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=2)
    attach(conf, spage["id"], rpath, results_name, "application/json", existing)
    versions = (history_of(conf, key, spage) if spage.get("id") != "(dry-run)" else []) + [record]
    versions = sorted({v["version"]: v for v in versions}.values(), key=lambda v: v["version"])
    for ac, ap in pages.items():
        _update(conf, ap, ac_body(story, ac, versions), "update %s with v%d" % (ap.get("title"), run["version"]))
    _update(conf, spage, story_body(story, versions), "update %s with v%d" % (spage.get("title"), run["version"]))
    url = page_url(conf, spage)
    jira_client.write("POST", "/rest/api/2/issue/%s/comment" % key, {"body": jira_comment(story, run, url)})
    return {"page": url, "videos": sorted(record["videos"].values()), "full": full, "results": results_name}


# ---- CLI ------------------------------------------------------------------------------------------

def cmd_find(args):
    rows = find(jira(), confluence())
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    for r in rows:
        print("%-11s %-6s %-14s ACs:%-2d PR open:%s  %s" % (r["key"], r["action"], r["status"], len(r["acs"]),
              (r["pr"] or {}).get("open", "?"), r.get("reason") or r["summary"][:60]))
    return 0


def cmd_publish(args):
    run = load_run(args.key, args.version)
    j = jira(dry_run=not args.live)
    issue = j.get("/rest/api/2/issue/%s" % args.key, fields="summary,status,issuelinks,%s,%s" % (EPIC_FIELD, AC_FIELD))
    out = publish(story_from(issue), run, confluence(dry_run=not args.live), j, args.max_mb)
    print(json.dumps(out, indent=2))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("find")
    f.add_argument("--json", action="store_true")
    r = sub.add_parser("record")
    r.add_argument("what", choices=["start", "stop"])
    r.add_argument("--key", required=True)
    r.add_argument("--version", type=int, required=True)
    r.add_argument("--defects", nargs="*")
    r.add_argument("--commit")
    r.add_argument("--pr")
    r.add_argument("--summary")
    c = sub.add_parser("caption")
    c.add_argument("kind", choices=["card", "step", "result"])
    c.add_argument("--key", required=True)
    c.add_argument("--version", type=int, required=True)
    c.add_argument("--ac")
    c.add_argument("--title", default="")
    c.add_argument("--text")
    c.add_argument("--doing")
    c.add_argument("--checking")
    c.add_argument("--result", choices=["passed", "failed", "not run"], default="not run")
    c.add_argument("--note")
    c.add_argument("--hold", type=float, default=HOLD)
    u = sub.add_parser("publish")
    u.add_argument("--key", required=True)
    u.add_argument("--version", type=int, required=True)
    u.add_argument("--live", action="store_true")
    u.add_argument("--max-mb", type=float, default=MAX_MB)
    args = p.parse_args(argv)
    if args.cmd == "caption" and args.kind in ("step", "result") and not args.ac:
        p.error("caption %s needs --ac" % args.kind)
    try:
        return {"find": cmd_find, "record": cmd_record, "caption": cmd_caption, "publish": cmd_publish}[args.cmd](args)
    except DemoError as exc:
        print("demo_needed: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    if not shutil.which("ffmpeg") and len(sys.argv) > 1 and sys.argv[1] == "record":
        sys.exit("demo_needed: ffmpeg is not installed")
    sys.exit(main())
