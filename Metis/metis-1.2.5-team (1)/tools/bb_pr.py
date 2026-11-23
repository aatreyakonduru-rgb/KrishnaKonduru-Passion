#!/usr/bin/env python3
"""Bitbucket pull request impact comment: tell reviewers which KB objects, pages and open questions a PR touches.

    python3 bb_pr.py comment <kb> --pr ID [--post] [--files PATH ...] [--max-chars N]
    python3 bb_pr.py ci      <kb> [--post]                      the same, with the PR read from pipeline environment variables
    python3 bb_pr.py check   <kb>                               the bitbucket settings, and whether the token variable is set

THIS IS THE ONLY METIS TOOL THAT WRITES TO AN EXTERNAL SYSTEM, AND IT ONLY EVER WRITES ONE THING: A COMMENT ON A PULL REQUEST.
It never approves, merges, declines, edits a PR, a branch or a file, and never touches Jira or Confluence. It is a DRY RUN unless
--post is given: the dry run reads the PR (GET requests only) and prints the comment. --post creates the comment, or, when a
comment of its own is already on the PR (it carries the marker line `[//]: # (metis-pr-impact)`), edits that one instead of adding
a new one on every push.

NEEDS YOUR BITBUCKET TO VERIFY. The Release Record lists the Bitbucket comment route as unconfirmed. The two routes below follow the
Bitbucket REST documentation and are tested here only against a fake server. Whether your instance allows the token to comment, whether
the marker line survives its markdown filter, and how it paginates are not confirmed until you run it once against a test PR.

Settings: the `bitbucket:` section of <kb>/.metis/kb-profile.yaml

    bitbucket:
      flavor: server                      # server (Bitbucket Server / Data Center) or cloud
      base_url: https://bitbucket.example.com   # server: your host; cloud: leave empty (https://api.bitbucket.org)
      project: PROJ                       # server project key
      workspace: my-workspace             # cloud workspace
      repo: payments-api                  # repository slug
      token_env: METIS_BB_TOKEN           # the NAME of the environment variable that holds the bearer token; never the token
      source_repo: api                    # the repo name used in the KB's [E: api/path:line] tags (sources.repos); default: the slug
      max_chars: 8000                     # the comment is cut to this size
      metis_url: http://metis.example:8765   # optional, for the link to the pack screen (else notify.base_url)

Routes (bearer token in the Authorization header):
  server  GET  /rest/api/1.0/projects/{p}/repos/{r}/pull-requests/{id}/changes        the changed files
          GET  /rest/api/1.0/projects/{p}/repos/{r}/pull-requests/{id}/activities     to find the earlier Metis comment
          POST /rest/api/1.0/projects/{p}/repos/{r}/pull-requests/{id}/comments       {"text": ...}
          PUT  /rest/api/1.0/projects/{p}/repos/{r}/pull-requests/{id}/comments/{c}   {"text": ..., "version": n}
  cloud   GET  /2.0/repositories/{ws}/{repo}/pullrequests/{id}/diffstat              the changed files
          GET  /2.0/repositories/{ws}/{repo}/pullrequests/{id}/comments              to find the earlier Metis comment
          POST /2.0/repositories/{ws}/{repo}/pullrequests/{id}/comments              {"content": {"raw": ...}}
          PUT  /2.0/repositories/{ws}/{repo}/pullrequests/{id}/comments/{c}          {"content": {"raw": ...}}

What the comment says, from files already in the KB (no model): the changed files that the KB cites, the graph objects they define,
what moves when those change (each link with its origin, parsed or ai-proposed, and its trust signals from trust.py), the KB pages
that cite the changed files, the open questions that block those pages (ids and priority, not their text), and a pointer to the
context pack for the objects. The whole comment goes through sensitive.py before it leaves; a line that matches is withheld.

CI mode reads: METIS_BB_PR_ID or BITBUCKET_PR_ID; METIS_BB_FLAVOR; METIS_BB_BASE_URL; METIS_BB_PROJECT; METIS_BB_WORKSPACE or
BITBUCKET_WORKSPACE; METIS_BB_REPO or BITBUCKET_REPO_SLUG. They override the profile. See templates/bitbucket-pipelines.yml.
"""
import argparse
import datetime
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_plan  # noqa: E402
import context_pack  # noqa: E402
import graph_store  # noqa: E402
import kb_gate  # noqa: E402
import notify  # noqa: E402
import trust as trust_signals  # noqa: E402
import verify_kb  # noqa: E402

MARKER = "[//]: # (metis-pr-impact)"
MARKER_KEY = "metis-pr-impact"
LOG = os.path.join(".metis", "bb_pr_log.json")
CLOUD_BASE = "https://api.bitbucket.org"
DEFAULT_MAX_CHARS = 8000
MIN_CHARS = 600
DEPTH = 2
WALK_LIMIT = 200
MAX_SEEDS = 40
MAX_PAGES = 50       # pages of 100 read from a PR listing before giving up
LOOPBACK = ("127.0.0.1", "localhost", "::1")
ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class BbError(ValueError):
    pass


def clean(x):
    return " ".join(str(x or "").split())


# ---- settings ---------------------------------------------------------------------------------
def config(kb, env=None, ci=False):
    """The bitbucket settings (profile, then CI environment). Returns the dict; `problems` lists what is wrong. No secret is in it."""
    env = os.environ if env is None else env
    p = kb_gate.profile(kb).get("bitbucket")
    p = p if isinstance(p, dict) else {}
    cfg = {"flavor": clean(p.get("flavor")).lower(), "base_url": clean(p.get("base_url")).rstrip("/"), "project": clean(p.get("project")),
           "workspace": clean(p.get("workspace")), "repo": clean(p.get("repo")), "token_env": clean(p.get("token_env")),
           "source_repo": clean(p.get("source_repo")), "metis_url": clean(p.get("metis_url")).rstrip("/"), "pr": ""}
    try:
        cfg["max_chars"] = int(p.get("max_chars") or DEFAULT_MAX_CHARS)
    except (TypeError, ValueError):
        cfg["max_chars"] = DEFAULT_MAX_CHARS
    if ci:
        cloud = bool(env.get("BITBUCKET_WORKSPACE")) and not env.get("METIS_BB_FLAVOR")
        pairs = (("flavor", env.get("METIS_BB_FLAVOR") or ("cloud" if cloud else "")),
                 ("base_url", (env.get("METIS_BB_BASE_URL") or "").rstrip("/")),
                 ("project", env.get("METIS_BB_PROJECT")),
                 ("workspace", env.get("METIS_BB_WORKSPACE") or env.get("BITBUCKET_WORKSPACE")),
                 ("repo", env.get("METIS_BB_REPO") or env.get("BITBUCKET_REPO_SLUG")),
                 ("pr", env.get("METIS_BB_PR_ID") or env.get("BITBUCKET_PR_ID")))
        for k, v in pairs:
            if clean(v):
                cfg[k] = clean(v).lower() if k == "flavor" else clean(v)
    if not cfg["flavor"]:
        cfg["flavor"] = "cloud" if cfg["workspace"] and not cfg["project"] else "server"
    if cfg["flavor"] == "cloud" and not cfg["base_url"]:
        cfg["base_url"] = CLOUD_BASE
    cfg["source_repo"] = cfg["source_repo"] or cfg["repo"]
    cfg["metis_url"] = cfg["metis_url"] or notify.base_url(kb)
    cfg["max_chars"] = max(MIN_CHARS, cfg["max_chars"])
    cfg["problems"] = problems(cfg)
    cfg["token_set"] = bool(cfg["token_env"] and ENV_NAME.match(cfg["token_env"]) and env.get(cfg["token_env"]))
    return cfg


def problems(cfg):
    out = []
    if cfg["flavor"] not in ("server", "cloud"):
        out.append("flavor must be server or cloud")
    if not cfg["base_url"]:
        out.append("base_url is required for Bitbucket Server / Data Center")
    elif not _url_ok(cfg["base_url"]):
        out.append("base_url must be https (http is accepted for localhost only)")
    if cfg["flavor"] == "server" and not (cfg["project"] and cfg["repo"]):
        out.append("server needs project and repo")
    if cfg["flavor"] == "cloud" and not (cfg["workspace"] and cfg["repo"]):
        out.append("cloud needs workspace and repo")
    if not cfg["token_env"]:
        out.append("token_env is required: the NAME of the environment variable that holds the bearer token")
    elif not ENV_NAME.match(cfg["token_env"]):
        out.append("token_env must be the NAME of an environment variable, never the token itself")
    return out


def _url_ok(url):
    p = urllib.parse.urlparse(url)
    return bool(p.hostname) and (p.scheme == "https" or (p.scheme == "http" and p.hostname in LOOPBACK))


# ---- the Bitbucket client ---------------------------------------------------------------------
class Client(object):
    """The small interface to Bitbucket. Reads (GET) and writes exactly one kind of thing: a comment on a PR."""

    def __init__(self, cfg, token, timeout=20):
        if cfg["problems"]:
            raise BbError("the bitbucket settings have problems: " + "; ".join(cfg["problems"]))
        self.cfg, self.token, self.timeout = cfg, token, timeout
        self.host = urllib.parse.urlparse(cfg["base_url"]).netloc

    def pr_url(self, pr):
        q = urllib.parse.quote
        c = self.cfg
        if not re.match(r"^\d+$", str(pr)):
            raise BbError("a pull request id is a number")
        if c["flavor"] == "server":
            return "%s/rest/api/1.0/projects/%s/repos/%s/pull-requests/%s" % (c["base_url"], q(c["project"], safe=""), q(c["repo"], safe=""), pr)
        return "%s/2.0/repositories/%s/%s/pullrequests/%s" % (c["base_url"], q(c["workspace"], safe=""), q(c["repo"], safe=""), pr)

    def call(self, method, url, body=None):
        if urllib.parse.urlparse(url).netloc != self.host:
            raise BbError("refusing to send the token to another host than the configured Bitbucket")
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": "Bearer " + self.token, "Accept": "application/json", "User-Agent": "metis-bb-pr",
            **({"Content-Type": "application/json"} if data is not None else {})})
        path = urllib.parse.urlparse(url).path
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                raw = r.read()
        except urllib.error.HTTPError as err:
            hint = {401: " (the token was not accepted)", 403: " (the token may not read or comment on this repository)",
                    404: " (no such PR or repository, or the token cannot see it)"}.get(err.code, "")
            raise BbError("Bitbucket answered HTTP %s for %s %s%s" % (err.code, method, path, hint))
        except (urllib.error.URLError, OSError) as err:
            raise BbError("cannot reach Bitbucket for %s %s: %s" % (method, path, type(err).__name__))
        try:
            return json.loads(raw.decode("utf-8")) if raw.strip() else {}
        except ValueError:
            raise BbError("Bitbucket answered something that is not JSON for %s %s" % (method, path))

    def pages(self, first_url):
        """Every `values` entry of a paged listing, both flavours (server: start/isLastPage; cloud: next)."""
        url, out = first_url, []
        for _ in range(MAX_PAGES):
            data = self.call("GET", url)
            out += data.get("values") or []
            if self.cfg["flavor"] == "server":
                if data.get("isLastPage", True):
                    return out
                url = "%s%sstart=%s" % (first_url, "&" if "?" in first_url else "?", data.get("nextPageStart"))
            else:
                if not data.get("next"):
                    return out
                url = data["next"]
        raise BbError("the listing has more than %d pages; not read" % MAX_PAGES)

    def changed_files(self, pr):
        base = self.pr_url(pr)
        out = set()
        if self.cfg["flavor"] == "server":
            for v in self.pages(base + "/changes?limit=100"):
                for k in ("path", "srcPath"):
                    s = (v.get(k) or {}).get("toString")
                    if s:
                        out.add(s)
        else:
            for v in self.pages(base + "/diffstat?pagelen=100"):
                for k in ("new", "old"):
                    s = (v.get(k) or {}).get("path")
                    if s:
                        out.add(s)
        return sorted(out)

    def own_comment(self, pr):
        """{id, version} of the latest comment that carries the Metis marker, or None."""
        base = self.pr_url(pr)
        found = []
        if self.cfg["flavor"] == "server":
            for a in self.pages(base + "/activities?limit=100"):
                c = a.get("comment") if a.get("action") == "COMMENTED" else None
                if c and MARKER_KEY in str(c.get("text") or ""):
                    found.append({"id": c["id"], "version": c.get("version", 0)})
        else:
            for c in self.pages(base + "/comments?pagelen=100"):
                if not c.get("deleted") and MARKER_KEY in str((c.get("content") or {}).get("raw") or ""):
                    found.append({"id": c["id"], "version": 0})
        return max(found, key=lambda c: int(c["id"])) if found else None

    def post_comment(self, pr, text, existing=None):
        """Create the comment, or edit `existing` (from own_comment). Returns {action, id}."""
        base = self.pr_url(pr)
        server = self.cfg["flavor"] == "server"
        if existing:
            body = {"text": text, "version": existing["version"]} if server else {"content": {"raw": text}}
            r = self.call("PUT", "%s/comments/%s" % (base, existing["id"]), body)
            return {"action": "updated", "id": r.get("id", existing["id"])}
        r = self.call("POST", base + "/comments", {"text": text} if server else {"content": {"raw": text}})
        return {"action": "created", "id": r.get("id")}


# ---- from changed files to graph objects ------------------------------------------------------
def cites(source, repo):
    """Paths in `repo` that a source tag cites."""
    out = set()
    for kind, value in verify_kb.TAG.findall(str(source or "")):
        if kind != "E":
            continue
        for part in value.split(";"):
            m = build_plan.CITE.match(part.strip())
            if m and m.group(1) == repo:
                out.add(m.group(2))
    return out


def touched(kb, changed, repo):
    """({node: [{file, rel, other, origin, source}]}, notes): graph objects on a link whose source tag cites a changed file."""
    want, hit, notes = set(changed), {}, []
    try:
        con = graph_store.connect(kb)
    except (Exception, SystemExit) as err:  # no link graph yet (graph_store exits): nothing to map, say so
        return {}, ["no link graph to map files to objects (%s)" % err]
    try:
        for src, rel, dst, source, origin in con.execute("select src, rel, dst, source, origin from edges order by n"):
            files = cites(source, repo) & want
            for f in sorted(files):
                for node, other in ((src, dst), (dst, src)):
                    hit.setdefault(node, []).append({"file": f, "rel": rel, "from": src, "to": dst, "other": other,
                                                     "origin": origin or "unknown", "source": source})
    finally:
        con.close()
    return hit, notes


def downstream(kb, seeds, depth=DEPTH):
    """[{node, depth, start, via}] unique by node: what moves when the touched objects change."""
    seen, out, cut = set(seeds), [], False
    for s in sorted(seeds):
        rows, c = graph_store.impact(kb, s, depth, WALK_LIMIT)
        cut = cut or c
        for r in sorted(rows, key=lambda r: (r["depth"], r["moves"])):
            if r["moves"] in seen:
                continue
            seen.add(r["moves"])
            out.append({"node": r["moves"], "depth": r["depth"], "start": s, "via": r["via"]})
    return sorted(out, key=lambda r: (r["depth"], r["node"])), cut


def cell(x):
    return str(x).replace("|", "/").replace("\n", " ")


def fit(lines, cap, more, keep=0):
    """Keep lines while they fit `cap` characters (the first `keep` lines, a heading, always stay); say how many were left out."""
    if sum(len(ln) + 1 for ln in lines) <= cap:
        return lines
    reserve = len(more % 9999) + 1
    kept, used = [], 0
    for i, ln in enumerate(lines):
        if i >= keep and used + len(ln) + 1 + reserve > cap:
            return kept + [more % (len(lines) - i)]
        kept.append(ln)
        used += len(ln) + 1
    return kept


def analyse(kb, changed, cfg):
    """Everything the comment says, as data: {changed, cited_files, objects, impact, pages, questions, notes, pack_id}."""
    repo = cfg["source_repo"]
    notes = []
    hit, more = touched(kb, changed, repo)
    notes += more
    cited_files = sorted({m["file"] for ms in hit.values() for m in ms})
    pages = []
    try:
        for page, repos in sorted(build_plan.cited_files(kb).items()):
            if repos.get(repo, set()) & set(changed) and not kb_gate.derived(page):
                pages.append(page)
    except Exception as err:
        notes.append("pages that cite the changed files not available: %s" % err)
    try:
        tr = trust_signals.Trust(kb)
        notes += tr.notes
    except Exception as err:
        tr = None
        notes.append("trust signals not available: %s" % err)
    impact, cut = ([], False)
    if hit:
        impact, cut = downstream(kb, list(hit)[:MAX_SEEDS])
        if cut:
            notes.append("a walk stopped at the limit; more objects may move")
        if len(hit) > MAX_SEEDS:
            notes.append("%d objects are touched; the impact of the first %d is shown" % (len(hit), MAX_SEEDS))
    objects = []
    for node, ms in sorted(hit.items()):
        m = ms[0]
        sig = tr.edge_text(tr.edge(m["origin"], m["source"])) if tr else ""
        objects.append({"node": node, "files": sorted({x["file"] for x in ms}), "origin": m["origin"], "signals": sig})
    rows = []
    for r in impact:
        last = r["via"][-1]
        sig = tr.edge_text(tr.edge(last.get("origin"), last["source"])) if tr else ""
        rows.append({"node": r["node"], "depth": r["depth"], "start": r["start"], "rel": "%s -%s-> %s" % (last["from"], last["rel"], last["to"]),
                     "origin": last.get("origin") or "unknown", "signals": sig})
    blocked = {}
    if tr:
        for p in pages:
            try:
                for b in tr.page(p)["blocked_by"]:
                    blocked.setdefault(b["id"], {"id": b["id"], "priority": b["priority"], "pages": []})["pages"].append(p)
            except ValueError:
                pass
    page_rows = []
    for p in pages:
        try:
            page_rows.append({"page": p, "signals": tr.page_text(tr.page(p)) if tr else ""})
        except ValueError:
            page_rows.append({"page": p, "signals": ""})
    return {"changed": list(changed), "cited_files": cited_files, "objects": objects, "impact": rows, "pages": page_rows,
            "questions": sorted(blocked.values(), key=lambda q: (q["priority"] or "P9", q["id"])), "notes": notes}


def pack_info(kb, a):
    seeds = [o["node"] for o in a["objects"]][:8]
    if not seeds:
        return None
    try:
        p = context_pack.build(kb, seeds=seeds, budget=6000, stale_marks=False, signals=False)
        return {"id": p["pack_id"], "seeds": seeds}
    except Exception:  # a pack is a pointer here; never fail the comment for it
        return {"id": None, "seeds": seeds}


def compose(kb, a, pr, cfg, max_chars=None):
    """The comment text, cut to max_chars, with the marker line first."""
    max_chars = max(MIN_CHARS, int(max_chars or cfg["max_chars"]))
    origins = {}
    for r in a["impact"]:
        origins[r["origin"]] = origins.get(r["origin"], 0) + 1
    head = [MARKER, "### Metis impact review for PR %s" % pr, "",
            "%d changed file%s; %d cited by the KB; %d graph object%s touched; %d more move downstream; %d KB page%s cite the changed files; "
            "%d open question%s blocking them." % (
                len(a["changed"]), "" if len(a["changed"]) == 1 else "s", len(a["cited_files"]), len(a["objects"]),
                "" if len(a["objects"]) == 1 else "s", len(a["impact"]), len(a["pages"]), "" if len(a["pages"]) == 1 else "s",
                len(a["questions"]), "" if len(a["questions"]) == 1 else "s")]
    if origins:
        head.append("Links followed by origin: %s. An ai-proposed link was written by a model and needs a person to confirm it." %
                    ", ".join("%d %s" % (n, o) for o, n in sorted(origins.items())))
    if not a["objects"]:
        head.append("")
        head.append("No changed file is cited by a link in the KB graph, so no impact could be traced. This does not mean there is none: "
                    "the KB may not cover these files.")
    pack = pack_info(kb, a)
    tail = ["", "---"]
    if pack:
        link = "%s/pack" % cfg["metis_url"] if cfg["metis_url"] else ""
        tail.append("Context pack for these objects: %s%s. Rebuild: `python tools/context_pack.py <KB> %s`%s" % (
            pack["id"] or "(not built)", " (open %s)" % link if link else "", " ".join("--node %s" % s for s in pack["seeds"][:4]),
            " ..." if len(pack["seeds"]) > 4 else ""))
    tail.append("Metis only comments on this PR. It does not approve, merge or change anything. Facts come from the KB and git; "
                "no model wrote this comment.")
    fixed = len("\n".join(head + tail)) + 120
    room = max(0, max_chars - fixed)
    body = []
    if a["impact"] or a["objects"]:
        lines = ["", "**Objects in the changed files**", "", "| Object | Files | Origin | Signals |", "|---|---|---|---|"]
        lines += ["| %s | %s | %s | %s |" % (cell(o["node"]), cell(", ".join(o["files"][:3])), cell(o["origin"]), cell(o["signals"])) for o in a["objects"]]
        body.append(fit(lines, int(room * 0.30), "| (%d more objects not shown) | | | |"))
    if a["impact"]:
        lines = ["", "**What moves when they change**", "", "| Object | Depth | Via | Origin | Signals |", "|---|---|---|---|---|"]
        lines += ["| %s | %d | %s | %s | %s |" % (cell(r["node"]), r["depth"], cell(r["rel"]), cell(r["origin"]), cell(r["signals"])) for r in a["impact"]]
        body.append(fit(lines, int(room * 0.40), "| (%d more not shown; run graph_store.py impact) | | | | |", 5))
    if a["questions"]:
        lines = ["", "**Open questions blocking pages that cite these files**", ""]
        lines += ["- %s (%s) blocks %s" % (q["id"], q["priority"], ", ".join(q["pages"][:3])) for q in a["questions"]]
        body.append(fit(lines, int(room * 0.15), "- (%d more not shown)"))
    if a["pages"]:
        lines = ["", "**KB pages that cite the changed files**", ""]
        lines += ["- %s: %s" % (p["page"], p["signals"]) for p in a["pages"]]
        body.append(fit(lines, int(room * 0.15), "- (%d more not shown)"))
    if a["notes"]:
        body.append(["", "Notes: " + "; ".join(a["notes"][:3])])
    text = "\n".join(head + [ln for part in body for ln in part] + tail)
    text, withheld = notify.clean_message(text)
    truncated = len(text) > max_chars
    if truncated:
        text = text[:max_chars - 40].rstrip() + "\n\n(comment cut to the size limit)"
    return {"text": text, "truncated": truncated, "withheld": withheld, "pack_id": (pack or {}).get("id")}


# ---- run --------------------------------------------------------------------------------------
def log_post(kb, pr, result, a):
    p = os.path.join(kb, LOG)
    rows = []
    if os.path.isfile(p):
        try:
            with open(p, encoding="utf-8") as fh:
                rows = json.load(fh)
        except (OSError, ValueError):
            rows = []
    rows.append({"pr": str(pr), "at": datetime.datetime.now().isoformat(timespec="seconds"), "action": result["action"],
                 "files": len(a["changed"]), "objects": len(a["objects"]) + len(a["impact"])})
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(rows[-200:], fh, indent=2)
        fh.write("\n")


def comment(kb, pr, post=False, files=None, max_chars=None, env=None, ci=False, timeout=20):
    """Build the impact comment for one PR. Dry run unless post=True.
    `files` (a list of changed paths) skips reading the PR. Returns {text, action, comment_id, posted, analysis, ...}."""
    env = os.environ if env is None else env
    cfg = config(kb, env, ci)
    pr = str(pr or cfg["pr"] or "").strip()
    if not pr:
        raise BbError("give the pull request id (--pr)")
    own, token = None, env.get(cfg["token_env"]) if cfg["token_env"] and ENV_NAME.match(cfg["token_env"]) else None
    client = None
    if files is None or post:
        if not token:
            raise BbError("environment variable %s is not set (it holds the Bitbucket token)" % (cfg["token_env"] or "(token_env not set in the profile)"))
        client = Client(cfg, token, timeout)
    elif token and not cfg["problems"]:
        client = Client(cfg, token, timeout)
    if files is None:
        files = client.changed_files(pr)
    files = sorted({str(f).strip().lstrip("/") for f in files if str(f).strip()})
    a = analyse(kb, files, cfg)
    c = compose(kb, a, pr, cfg, max_chars)
    note = ""
    if client:
        try:
            own = client.own_comment(pr)
        except BbError as err:
            if post:
                raise
            note = " (earlier Metis comment not looked up: %s)" % err
    res = {"pr": pr, "text": c["text"], "truncated": c["truncated"], "withheld": c["withheld"], "analysis": a, "posted": False,
           "action": "would update comment %s" % own["id"] if own else "would create a new comment", "comment_id": own["id"] if own else None,
           "dry_run": not post, "flavor": cfg["flavor"], "note": note.strip()}
    if own is None and client is None:
        res["action"] = "would create a comment, or update an earlier Metis one (not looked up: no token here)"
    if post:
        r = client.post_comment(pr, c["text"], own)
        res.update(posted=True, action=r["action"], comment_id=r["id"], dry_run=False)
        log_post(kb, pr, r, a)
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("comment"); a.add_argument("kb"); a.add_argument("--pr"); a.add_argument("--files", nargs="*")
    a.add_argument("--max-chars", type=int); a.add_argument("--post", action="store_true", help="really post (the default is a dry run)")
    a = sub.add_parser("ci"); a.add_argument("kb"); a.add_argument("--max-chars", type=int); a.add_argument("--post", action="store_true")
    a = sub.add_parser("check"); a.add_argument("kb")
    args = ap.parse_args(argv)
    kb = os.path.abspath(args.kb)
    sys.stdout.reconfigure(encoding="utf-8")
    if args.cmd == "check":
        c = config(kb)
        print("flavor %s, base_url %s, repo %s, token variable %s (%s)" % (c["flavor"], c["base_url"] or "(none)", c["repo"] or "(none)",
                                                                       c["token_env"] or "(none)", "set" if c["token_set"] else "not set"))
        for p in c["problems"]:
            print("PROBLEM " + p)
        return 1 if c["problems"] else 0
    try:
        r = comment(kb, getattr(args, "pr", None), args.post, getattr(args, "files", None), args.max_chars, ci=args.cmd == "ci")
    except BbError as err:
        print("error: %s" % err, file=sys.stderr)
        return 2
    print(r["text"])
    print("\n--")
    if r["posted"]:
        print("posted: comment %s %s on PR %s" % (r["comment_id"], r["action"], r["pr"]))
    else:
        print("dry run: nothing was posted (%s on PR %s). Add --post to post. %s" % (r["action"], r["pr"], r["note"]))
    if r["withheld"]:
        print("lines withheld by the sensitive check: %s" % ", ".join(r["withheld"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
