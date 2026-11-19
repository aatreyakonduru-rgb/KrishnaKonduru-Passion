#!/usr/bin/env python3
"""The install window for Argus: a small local web page over install.py.

    python3 install_ui.py [--target ~/repos/<your repo>] [--draft install-draft.yaml] [--port 8790]

Devin starts it when the tech lead types "install this" (START-HERE.md) and shows it through the
session's preview link (Devin Cloud), or opens it in the tech lead's own browser (Devin Local).
Ten steps, each checked before Next; every Next saves the values to a draft
on this machine, and "Save and finish later" keeps the draft in the chat, on the PC or on a branch
of the team's repo. Nothing is written to the repo, Confluence or Devin Cloud before Install on the
Review step. Secrets are only checked for being there; their values are never shown or saved.
Standard library only (plus PyYAML, which the framework needs anyway).
"""
import argparse
import contextlib
import io
import json
import os
import platform
import shutil
import subprocess
import sys
import threading
import re
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import install  # noqa: E402
import install_steps as steps  # noqa: E402

STEPS = ["check", "team", "jira", "confluence", "repos", "envs", "roster", "review", "install", "next"]
STEP_KEYS = {
    "team": ("product_name", "company_name", "email_domain", "devin_host"),
    "jira": ("jira_host", "jira_project", "jira_token_env"),
    "confluence": ("wiki_host", "wiki_space", "confluence_token_env"),
    "repos": ("git_host", "repo_slug", "deploy_slug", "qa_repo_slug", "work_branch", "sdlc_dir", "kb_dir"),
}
STATUS_QUEUES = ("review", "qa", "retest", "uat", "uat_recheck", "business_approval", "release", "prod_validation")
FIELD_KEYS = ("story_points", "sprint", "acceptance", "it_team", "epic_link")
EVENT = "SDLC-INSTALL-EVENT"
WHERE = {"uep": "UEP Devin Cloud", "cloud": "Other Devin Cloud", "local": "Devin Local"}
MCP_KEYS = (("jira", "Jira", True), ("confluence", "Confluence", True), ("snowflake", "Snowflake", False))
MCP_NAME = r"[A-Za-z0-9][\w.-]*"
# what the sandbox's sample app installs, to see whether pip and npm can reach a registry from here
SAMPLE_PACKAGES = {"pip": "django-ninja", "npm": "next"}


def is_clone(path):
    """A git checkout given as an absolute path (never the current folder by accident)."""
    return bool(path) and os.path.isabs(path) and os.path.isdir(os.path.join(path, ".git"))


def find_source(given=None):
    """The shared copy (the folder with dot-devin/) to install from."""
    for cand in [given, HERE, os.path.dirname(HERE)]:
        if cand and os.path.isdir(os.path.join(cand, "dot-devin")):
            return os.path.abspath(cand)
    return None


def kit():
    for cand in (os.path.join(HERE, "sdlc", "framework", "tools"), os.path.dirname(HERE),
                 os.path.join(HERE, "framework", "tools")):
        if os.path.isdir(os.path.join(cand, "artifact_kit")):
            sys.path.insert(0, cand)
            import artifact_kit
            return artifact_kit
    return None


class App:
    def __init__(self, source, state_dir, target=None, offline=False):
        self.source, self.state_dir, self.offline = source, state_dir, offline
        os.makedirs(state_dir, exist_ok=True)
        self.draft_path = os.path.join(state_dir, steps.DRAFT_NAME)
        self.events_path = os.path.join(state_dir, "events.log")
        self.lock = threading.Lock()
        self.run = {"status": "idle", "lines": [], "steps": [], "result": {}}
        self.job_roles, self.gate_roles = steps.roles(source) if source else ([], [])
        self.gates = self._gates()
        self.draft = self._fresh(target)
        if os.path.exists(self.draft_path):
            with contextlib.suppress(Exception):
                self.draft = self._merge(steps.read_draft(steps.read_text(self.draft_path)))

    # ---- draft
    def _profile_example(self):
        rules = steps.rules_dir(self.source) if self.source else None
        path = os.path.join(rules, "sdlc-profile.json") if rules else ""
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        return {}

    def _gates(self):
        rules = steps.rules_dir(self.source) if self.source else None
        if not rules:
            return []
        gates = install.load_yaml(os.path.join(rules, "approval-gates.yaml")).get("gates") or []
        return [g["id"] for g in gates if isinstance(g, dict) and g.get("id")]

    def _fresh(self, target=None):
        prof = self._profile_example()
        envs = [{k: e.get(k, "") for k in ("name", "app_branch", "deploy_branch", "values", "gate")}
                for e in (prof.get("workflow") or {}).get("environments") or []]
        values = {k: "" for k in install.DEFAULTS}
        values.update({"sdlc_dir": "sdlc", "kb_dir": "docs/knowledge-base"})
        return {"values": values, "settings": {
            "tech_lead": {"name": "", "email": "", "jira_user": ""}, "it_team": "",
            "jira_statuses": {q: ", ".join(v) for q, v in ((prof.get("jira") or {}).get("statuses") or {}).items()},
            "jira_fields": {k: "" for k in FIELD_KEYS}, "confluence_parent": "", "pages": {},
            "where": "cloud", "where_chosen": False, "mcp": {k: "" for k, _, _ in MCP_KEYS}, "environments": envs, "kb_source_dirs": [], "etl_repo_slug": "", "target": target or "",
            "clone_url": "", "roster": []}, "step": 0, "saved_to": None}

    def _merge(self, loaded):
        d = self._fresh(self.draft["settings"].get("target") if hasattr(self, "draft") else None)
        d["values"].update({k: str(v) for k, v in (loaded.get("values") or {}).items() if k in install.DEFAULTS})
        d["settings"].update(loaded.get("settings") or {})
        d["saved_to"] = loaded.get("saved_to")
        return d

    def save(self):
        with open(self.draft_path, "w", encoding="utf-8") as fh:
            fh.write(steps.draft_text({k: self.draft[k] for k in ("values", "settings", "saved_to")}))

    def values(self):
        return install.normalise(dict(install.DEFAULTS, **{k: v for k, v in self.draft["values"].items() if v}))

    def raw_values(self):
        return install.normalise(self.draft["values"])

    def event(self, kind, **data):
        line = "%s %s %s" % (EVENT, kind, json.dumps(data))
        with open(self.events_path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        sys.__stdout__.write(line + "\n")
        sys.__stdout__.flush()

    # ---- checks per step
    def problems(self, step):
        v, s = self.raw_values(), self.draft["settings"]
        out = []
        if step in STEP_KEYS:
            keys = STEP_KEYS[step]
            out += [p for p in install.problems(v) if p.split(" ")[0] in keys]
        if step == "check":
            out += self.mcp_problems()
        if step == "team":
            lead = s.get("tech_lead") or {}
            if not lead.get("name") or not lead.get("email"):
                out.append("tech lead name and email are needed")
            if not s.get("sandbox") and (v.get("product_name") or "").strip().lower() == install.DEFAULTS["product_name"].lower():
                out.append("product_name: use your own team name, not the example %r" % install.DEFAULTS["product_name"])
        if step == "confluence" and not steps.page_id(s.get("confluence_parent")):
            out.append("the parent page must be a page link or id")
        if step == "repos":
            t = s.get("target") or ""
            if not is_clone(t):
                out.append("the local clone (%s) is not a git repository: clone it first" % (t or "not set"))
            else:
                for key in ("sdlc_dir", "kb_dir"):
                    p = os.path.join(t, v.get(key) or "")
                    if (v.get(key) and os.path.isdir(p) and os.listdir(p) and not s.get("force")
                            and not self.run["result"].get("branch")):
                        out.append("%s/ already has files in your repo: pick a new or empty folder" % v[key])
        if step == "envs":
            envs = s.get("environments") or []
            if not envs:
                out.append("add at least one environment")
            for i, e in enumerate(envs):
                if not e.get("name") or not e.get("app_branch"):
                    out.append("environment %d needs a name and an app branch" % (i + 1))
        if step == "roster":
            out += steps.roster_problems([steps.clean_person(p) for p in s.get("roster") or []], s,
                                         self.job_roles, self.gate_roles)
        if step == "review":
            for st in STEPS[:7]:
                out += ["%s: %s" % (st, p) for p in self.problems(st)]
            if not self.offline:
                for name in (v["jira_token_env"], v["confluence_token_env"]):
                    if name and not os.environ.get(name):
                        out.append("secret %s is not in this session" % name)
        return out

    def first_open(self):
        for i, st in enumerate(STEPS[1:7], start=1):
            if self.problems(st):
                return i
        return STEPS.index("review")

    def secrets(self):
        v = self.raw_values()
        names = [n for n in (v.get("jira_token_env"), v.get("confluence_token_env")) if n]
        return {n: bool(os.environ.get(n)) for n in names + ["DEVIN_API_KEY"]}

    def real_ready(self):
        """Devin Cloud with the Jira and Confluence secrets set: the real systems are used, no sandbox."""
        v = self.raw_values()
        names = [n for n in (v.get("jira_token_env"), v.get("confluence_token_env")) if n]
        return bool(names) and all(os.environ.get(n) for n in names) and not os.environ.get("SDLC_SANDBOX_URL")

    def sandbox_dir(self):
        for d in (os.path.join(os.path.dirname(HERE), "sandbox"),
                  os.path.join(self.source or "", "sdlc", "framework", "tools", "sandbox")):
            if os.path.isfile(os.path.join(d, "make_sandbox.py")):
                return d
        return None

    def sandbox_on(self, folder):
        """Make the sandbox (sample company, Jira, Confluence, database, KB, repo), start its server and
        fill the window with its values."""
        if not self.local() and self.real_ready():
            return {"ok": False, "detail": "Jira and Confluence are set up in this session; the real ones are used"}
        d = self.sandbox_dir()
        if not d:
            return {"ok": False, "detail": "no tools/sandbox in this copy"}
        sys.path.insert(0, d)
        import make_sandbox
        folder = os.path.abspath(os.path.expanduser(folder or "~/Documents/sdlc-sandbox"))
        mine = os.path.exists(os.path.join(folder, "jira.yaml"))
        if os.path.isdir(folder) and os.listdir(folder) and not mine:
            return {"ok": False, "detail": "%s already has other files; pick an empty or new folder" % folder}
        out = make_sandbox.make(folder, force=mine)
        v = dict(install.DEFAULTS, product_name="Sandbox Claims", work_branch="main")
        url = self._serve_sandbox(folder, v)
        if not url:
            return {"ok": False, "detail": "no free port for the sandbox server"}
        with open(os.path.join(folder, "roster.csv"), "rb") as fh:
            roster = fh.read()
        s = self.draft["settings"]
        self.draft["values"] = {k: v[k] for k in self.draft["values"]} if self.draft.get("values") else v
        self.draft["values"].update(v)
        s.update({"sandbox": True, "sandbox_folder": folder, "sandbox_url": url, "target": out["repo"],
                  "tech_lead": {"name": "Resource 2", "email": "resource2@acme.example", "jira_user": "resource2"},
                  "confluence_parent": "100000", "it_team": "Acme-Claims-Web",
                  "roster": steps.parse_roster(roster, "roster.csv")})
        self.save()
        return {"ok": True, "detail": "sandbox in %s, server %s" % (folder, url), "url": url}

    def _serve_sandbox(self, folder, values):
        """Start (or restart) the sandbox server on the folder and point Jira and Confluence at it."""
        sys.path.insert(0, self.sandbox_dir())
        import sandbox_server
        if getattr(self, "sandbox_srv", None):
            self.sandbox_srv.shutdown()
            self.sandbox_srv = None
        for port in range(sandbox_server.PORT, sandbox_server.PORT + 10):
            try:
                self.sandbox_srv = sandbox_server.serve(folder, port=port)
                break
            except OSError:
                continue
        else:
            return None
        threading.Thread(target=self.sandbox_srv.serve_forever, daemon=True).start()
        url = "http://127.0.0.1:%d" % self.sandbox_srv.server_address[1]
        os.environ.update({"SDLC_SANDBOX": folder, "SDLC_SANDBOX_URL": url,
                           values["jira_token_env"]: "resource2", values["confluence_token_env"]: "resource2"})
        return url

    def sandbox_resume(self):
        """A loaded draft that was a sandbox install starts its server again, if the folder is still there."""
        s = self.draft["settings"]
        if not s.get("sandbox") or getattr(self, "sandbox_srv", None):
            return
        folder = s.get("sandbox_folder") or ""
        url = None
        if self.sandbox_dir() and os.path.isfile(os.path.join(folder, "jira.yaml")):
            url = self._serve_sandbox(folder, self.raw_values())
        if url:
            s["sandbox_url"] = url
        else:
            s["sandbox"] = False
        self.save()

    def local(self):
        return self.draft["settings"].get("where") == "local"

    def uep(self):
        return self.draft["settings"].get("where") == "uep"

    def pick_where(self):
        """A Devin Cloud session that already has the Jira and Confluence secrets is taken to be UEP,
        until the person picks a place themselves."""
        s = self.draft["settings"]
        if not s.get("where_chosen") and s.get("where") == "cloud" and self.real_ready():
            s["where"] = "uep"

    def mcp_names(self):
        names = self.draft["settings"].get("mcp") or {}
        return {k: str(names.get(k) or "").strip() for k, _, _ in MCP_KEYS}

    def mcp_problems(self):
        """Outside UEP the chat skills reach Jira and Confluence through the team's own MCP servers."""
        out, names = [], self.mcp_names()
        for key, label, needed in MCP_KEYS:
            if names[key] and not re.fullmatch(MCP_NAME, names[key]):
                out.append("the %s MCP server name %r has characters an MCP server name can't have" % (label, names[key]))
            elif needed and not names[key] and not self.uep() and not self.draft["settings"].get("sandbox"):
                out.append("name your %s MCP server: outside UEP, Argus's chat skills reach %s through it" % (label, label))
        return out

    def mcp_event(self):
        """Ask Devin to check each named MCP server with one read-only call, once per set of names."""
        named = {k: v for k, v in self.mcp_names().items() if v}
        if named and named != getattr(self, "mcp_sent", None):
            self.mcp_sent = named
            self.event("MCP_CHECK", servers=named)

    def registry_rows(self):
        """Can pip and npm fetch the sample app's packages from here? Asked once per window."""
        if getattr(self, "registry", None) is None:
            def ask(cmd):
                try:
                    r = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
                    return r.returncode == 0, (r.stdout or r.stderr).strip().splitlines()[-1:] or [""]
                except (OSError, subprocess.TimeoutExpired) as e:
                    return False, [str(e)]
            tmp = os.path.join(self.state_dir, "registry-check")
            npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
            pip_ok, pip_out = ask([sys.executable, "-m", "pip", "download", "-q", "--no-deps", "-d", tmp,
                                   SAMPLE_PACKAGES["pip"]])
            shutil.rmtree(tmp, ignore_errors=True)
            npm_ok, npm_out = ask([npm, "view", SAMPLE_PACKAGES["npm"], "version"]) if npm else (False, ["npm not found"])
            node = shutil.which("node")
            self.registry = [
                ("Sample app: Python packages", pip_ok, "pip can fetch them" if pip_ok else
                 "pip can't fetch %s here (%s)" % (SAMPLE_PACKAGES["pip"], pip_out[0][-120:])),
                ("Sample app: Node.js and npm packages", bool(node) and npm_ok,
                 "npm can fetch them" if node and npm_ok else
                 ("Node.js 18+ is not installed" if not node else "npm can't fetch %s here (%s)" % (
                     SAMPLE_PACKAGES["npm"], npm_out[0][-120:])))]
        return [(item, True if ok else None, detail if ok else detail + ". The sandbox works without it; only "
                 "the running sample app (run.py) needs it") for item, ok, detail in self.registry]

    def live(self, step):
        v, s = self.values(), self.draft["settings"]
        rows, extra = [], {}

        def row(item, ok, detail=""):
            rows.append({"item": item, "ok": ok, "detail": detail})
        if step == "check":
            self.pick_where()
            row("Installing in", True, WHERE.get(s.get("where"), WHERE["cloud"]))
            if self.local():
                row("Devin Local", True, "%s %s" % (platform.system(), platform.release()))
            row("Python 3.8+", sys.version_info >= (3, 8), sys.version.split()[0])
            try:
                import yaml  # noqa: F401
                row("PyYAML", True, "installed")
            except ImportError:
                row("PyYAML", False, "pip install pyyaml")
            row("git", bool(shutil.which("git")), shutil.which("git") or "not on PATH")
            if self.local():
                bash = install.find_bash()
                row("bash (hook checks)", bool(bash), bash or "not found: install Git for Windows and use its Git Bash")
            row("Framework files", bool(self.source), self.source or "no shared copy (dot-devin/) found")
            for name, ok in self.secrets().items():
                optional = name == "DEVIN_API_KEY"
                missing = ("missing: set the environment variable %s on this PC, then start the window again" % name
                           if self.local() else "missing: ask your Devin admin to add it in Settings > Secrets")
                row(("Environment variable " if self.local() else "Secret ") + name,
                    True if ok else (None if optional else False),
                    "present" if ok else ("optional: registers the playbooks" if optional else missing))
            names = self.mcp_names()
            for key, label, needed in MCP_KEYS:
                if names[key]:
                    row("%s MCP server" % label, True, "%s: Devin checks it in the chat with one read-only call" % names[key])
                elif self.uep():
                    row("%s MCP server" % label, None, "optional in UEP: the service accounts reach %s" % label)
                elif needed:
                    row("%s MCP server" % label, None if s.get("sandbox") else False,
                        "not needed for the sandbox" if s.get("sandbox") else
                        "needed: Argus's chat skills reach %s through it" % label)
                else:
                    row("%s MCP server" % label, None, "optional: only for the database and ETL parts of the "
                        "knowledge base; without it those parts can't be built (the sandbox uses its sample "
                        "database instead)")
            if not self.uep():
                row("Git access to your repo", None, "the Repositories step checks it: the repo connected in Devin "
                    "Cloud, or your own git login on this PC")
            self.mcp_event()
            if self.draft["settings"].get("sandbox"):
                row("Sandbox", True, "Jira and Confluence of the sample company at %s, folder %s" % (
                    self.draft["settings"].get("sandbox_url"), self.draft["settings"].get("sandbox_folder")))
            elif not self.local() and self.real_ready():
                row("Sandbox", None, "not offered: this session has the Jira and Confluence secrets, so the real ones are used")
            else:
                row("Sandbox", None, "available: try the framework on a made-up company, nothing real is touched")
            extra["sandbox_offered"] = self.local() or not self.real_ready()
            extra["where"] = s.get("where")
            if (extra["sandbox_offered"] or s.get("sandbox")) and not self.offline:
                for item, ok, detail in self.registry_rows():
                    row(item, ok, detail)
        elif step == "jira":
            token = os.environ.get(v["jira_token_env"], "")
            base = install.site(v["jira_host"])
            if not token:
                row("Jira token", False, "secret %s is not set" % v["jira_token_env"])
            else:
                st, me = install.api("GET", base + "/rest/api/2/myself", token)
                row("Sign in", st == 200, me.get("displayName") or "HTTP %s %s" % (st, me.get("error", "")))
                st, pj = install.api("GET", base + "/rest/api/2/project/" + v["jira_project"], token)
                row("Project " + v["jira_project"], st == 200, pj.get("name") or "HTTP %s" % st)
                if st == 200:
                    st, types = install.api("GET", base + "/rest/api/2/project/%s/statuses" % v["jira_project"], token)
                    names = sorted({x["name"] for t in (types if isinstance(types, list) else [])
                                    for x in t.get("statuses") or []})
                    extra["statuses"] = names
                    row("Statuses", bool(names), "%d found" % len(names))
                    st, fields = install.api("GET", base + "/rest/api/2/field", token)
                    extra["fields"] = sorted(["%s %s" % (f["id"], f.get("name", "")) for f in
                                              (fields if isinstance(fields, list) else []) if f.get("custom")])
                    row("Custom fields", bool(extra["fields"]), "%d found" % len(extra["fields"]))
        elif step == "confluence":
            base, bearer = steps.confluence(v)
            if not bearer:
                row("Confluence token", False, "secret %s is not set" % v["confluence_token_env"])
            else:
                st, sp = install.api("GET", base + "/rest/api/space/" + v["wiki_space"], bearer)
                row("Space " + v["wiki_space"], st == 200, sp.get("name") or "HTTP %s" % st)
                pid = steps.page_id(s.get("confluence_parent"))
                if pid:
                    st, pg = install.api("GET", base + "/rest/api/content/" + pid, bearer)
                    row("Parent page", st == 200, pg.get("title") or "HTTP %s" % st)
                    if st == 200:
                        s["confluence_parent_title"] = pg.get("title")
                titles = steps.page_titles(v, s)
                for key in steps.PAGE_KEYS:
                    try:
                        found = steps.find_page(base, bearer, v["wiki_space"], titles[key])
                        row("Page " + titles[key], True, "already there, kept" if found else "will be created")
                    except RuntimeError as e:
                        row("Page " + titles[key], False, str(e))
        elif step == "repos":
            t = s.get("target") or ""
            ok = is_clone(t)
            row("Local clone", ok, t or "not set")
            if ok:
                url = steps.git(t, "remote", "get-url", "origin", check=False).stdout.strip()
                reach = steps.git(t, "ls-remote", "--heads", "origin", check=False, timeout=60)
                row("origin", reach.returncode == 0, url if reach.returncode == 0 else reach.stderr.strip()[-200:])
                if reach.returncode == 0:
                    has = steps.remote_has(t, v["work_branch"])
                    row("Work branch " + v["work_branch"], True,
                        "there" if has else "will be created from %s" % (steps.remote_head(t) or "the default branch"))
                for key in ("sdlc_dir", "kb_dir"):
                    p = os.path.join(t, v[key])
                    busy = os.path.isdir(p) and os.listdir(p)
                    row("Folder %s/" % v[key], False if busy else True, "has files already" if busy else "new folder")
                extra["folders"] = steps.top_folders(t)
        elif step == "roster":
            token = os.environ.get(v["jira_token_env"], "")
            base = "https://" + v["jira_host"]
            out = []
            for p in s.get("roster") or []:
                p = dict(p)
                email = (p.get("email") or "").strip()
                if not token or not email:
                    p["found"] = None
                else:
                    st, users = install.api("GET", base + "/rest/api/2/user/search?" + urllib.parse.urlencode(
                        {"username": email}), token)
                    hit = users[0] if st == 200 and isinstance(users, list) and users else None
                    p["found"] = bool(hit)
                    if hit and not p.get("jira_user"):
                        p["jira_user"] = hit.get("name") or hit.get("key")
                out.append(p)
            s["roster"] = [{k: v2 for k, v2 in p.items() if k != "found"} for p in out]
            extra["roster"] = out
            self.save()
        return {"rows": rows, "extra": extra}

    def clone(self):
        s, v = self.draft["settings"], self.values()
        url = s.get("clone_url") or "https://%s/%s.git" % (v["git_host"], v["repo_slug"])
        t = os.path.abspath(os.path.expanduser(s.get("target") or "~/repos/" + v["repo_slug"].split("/")[-1]))
        if is_clone(t):
            s["target"] = t
            return {"ok": True, "detail": "already cloned at %s" % t}
        r = subprocess.run(["git", "clone", "-q", url, t], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
                           env=dict(os.environ, GIT_TERMINAL_PROMPT="0"))
        if r.returncode == 0:
            s["target"] = t
            self.save()
        return {"ok": r.returncode == 0, "detail": t if r.returncode == 0 else r.stderr.strip()[-300:]}

    # ---- finish later
    def finish_later(self, where):
        self.save()
        if where == "chat":
            self.event("ATTACH", path=self.draft_path, why="Save and finish later")
            return {"ok": True, "detail": "Devin is posting %s in the chat. Download it from there." % steps.DRAFT_NAME}
        if where == "repo":
            t = self.draft["settings"].get("target") or ""
            if not is_clone(t):
                return {"ok": False, "detail": "set the local clone on the Repositories step first, or pick another option"}
            try:
                self.draft["saved_to"] = {"repo": self.values()["repo_slug"], "branch": steps.DRAFT_BRANCH}
                steps.save_draft_to_repo(t, {k: self.draft[k] for k in ("values", "settings", "saved_to")})
                self.save()
                return {"ok": True, "detail": "Saved on %s in %s. Next time say: install this, my values are on %s in %s"
                        % (steps.DRAFT_BRANCH, self.values()["repo_slug"], steps.DRAFT_BRANCH, self.values()["repo_slug"])}
            except (RuntimeError, subprocess.CalledProcessError) as e:
                return {"ok": False, "detail": str(e)}
        return {"ok": True, "detail": "download"}

    # ---- review and install
    def review(self):
        v, s = self.values(), self.draft["settings"]
        titles = steps.page_titles(v, s)
        files = len(install.copy_plan(self.source, v)) if self.source else 0
        return {
            "values": [[k, v[k]] for k in install.DEFAULTS],
            "files": files, "target": s.get("target"),
            "pages": [titles[k] for k in steps.PAGE_KEYS],
            "parent": s.get("confluence_parent_title") or steps.page_id(s.get("confluence_parent")),
            "roster": len(s.get("roster") or []),
            "branch": "devin/<time>-sdlc-install from %s" % v["work_branch"],
            "problems": self.problems("review"),
            "mcp": ["%s: %s" % (k, n) for k, n in self.mcp_names().items() if n],
        }

    def log(self, line):
        for part in str(line).rstrip("\n").split("\n"):
            self.run["lines"].append(part)

    def start_install(self):
        with self.lock:
            if self.run["status"] == "running":
                return False
            again = self.run["status"] == "failed"
            self.run.update(status="running", lines=[], steps=[], result=dict(self.run.get("result") or {}) if again else {})
        threading.Thread(target=self._install, args=(again,), daemon=True).start()
        return True

    def _install(self, again):
        v, s = self.values(), self.draft["settings"]
        t = s["target"]
        res = self.run["result"]

        class Out(io.TextIOBase):
            def write(inner, text):
                if text.strip():
                    self.log(text)
                return len(text)

        def step(name, fn):
            self.run["steps"].append({"name": name, "status": "running"})
            self.log("== " + name)
            try:
                with contextlib.redirect_stdout(Out()):
                    fn()
                self.run["steps"][-1]["status"] = "ok"
                return True
            except Exception as e:  # noqa: BLE001 - shown in the window, install stops here
                self.run["steps"][-1]["status"] = "failed"
                self.log("FAILED: %s" % e)
                if not isinstance(e, RuntimeError):
                    self.log(traceback.format_exc()[-1200:])
                return False

        def branch():
            current = steps.git(t, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
            if again and res.get("branch") == current:
                self.log("  carrying on on %s" % current)
                return
            res["branch"] = steps.prepare_branch(t, v, self.log)

        def copy():
            if not install.copy_in(self.source, t, force=again or bool(s.get("force")), values=v):
                raise RuntimeError("files are already there (see above)")
            print("updated %d files with your values" % install.apply(t, install.DEFAULTS, v))
            for line in steps.apply_settings(t, v, s):
                print(line)
            install.dump_values(os.path.join(t, install.VALUES_FILE), v,
                                {k: x for k, x in s.items() if k not in install.NOT_STORED})
            if s.get("sandbox") and s.get("sandbox_folder"):
                kb = os.path.join(s["sandbox_folder"], "sample-kb")
                if os.path.isdir(kb):
                    shutil.copytree(kb, os.path.join(t, v["kb_dir"]), dirs_exist_ok=True)
                    install.apply(t, install.DEFAULTS, v)
                    print("sample knowledge base copied into %s" % v["kb_dir"])
                    sys.path.insert(0, self.sandbox_dir())
                    import sample_app
                    for name, ok, detail in sample_app.build_kb(t, v["sdlc_dir"]):
                        print("%-20s %s %s" % (name, "ok" if ok else "FAILED", detail))
                        if not ok:
                            raise RuntimeError("the sample KB build stopped at %s; the KB is incomplete" % name)
            install.regenerate(t, v)

        def pages():
            if self.offline:
                print("skipped (offline)")
                return
            ids = steps.create_pages(t, v, s, self.log)
            s["page_ids"] = ids
            self.save()
            steps.apply_settings(t, v, dict(s, roster=None))
            steps.write_roster(t, v, s, page={"id": ids.get("roster"), "version": 1})
            install.dump_values(os.path.join(t, install.VALUES_FILE), v,
                                {k: x for k, x in s.items() if k not in install.NOT_STORED})
            res["pages"] = ids
            res["wiki"] = install.site(v["wiki_host"])

        def checks():
            if not install.check(t, v, self.offline):
                raise RuntimeError("some checks failed (see above); fix them and press Run again")

        def push():
            if self.offline:
                print("skipped (offline): nothing committed or pushed; the files are in %s" % t)
                return
            steps.commit_and_push(t, v, s, res["branch"], self.log)
            self.event("OPEN_PR", repo=v["repo_slug"], branch=res["branch"], base=v["work_branch"],
                       title="Install Argus (%s)" % v["product_name"])

        def devin():
            if s.get("sandbox"):
                print("Sandbox: no Devin Cloud setup; Jira and Confluence are at %s" % s.get("sandbox_url"))
                return
            if self.local():
                print("Devin Local: no Devin Cloud machine to set up")
                if (self.draft.get("saved_to") or {}).get("branch") and steps.delete_draft_branch(t):
                    print("deleted %s" % steps.DRAFT_BRANCH)
                return
            ok, out = steps.playbooks(t, v)
            print(out.splitlines()[0] if out else "playbooks listed")
            tdir = os.path.join(HERE, "templates")
            made = steps.render_templates(tdir, os.path.join(self.state_dir, "devin-cloud"), v, s)
            res["devin"] = made
            if "blueprint" in made:
                self.event("BLUEPRINT", path=made["blueprint"], repo=v["repo_slug"])
            if "knowledge" in made:
                self.event("KNOWLEDGE_NOTE", path=made["knowledge"])
            if (self.draft.get("saved_to") or {}).get("branch") and steps.delete_draft_branch(t):
                print("deleted %s" % steps.DRAFT_BRANCH)

        for name, fn in (("Branch", branch), ("Copy and rewrite", copy), ("Confluence pages", pages),
                         ("Checks", checks), ("Commit and push", push), ("Devin Cloud setup", devin)):
            if not step(name, fn):
                self.run["status"] = "failed"
                return
        self.run["status"] = "done"

    def playbooks(self, apply):
        ok, out = steps.playbooks(self.draft["settings"]["target"], self.values(), apply=apply)
        return {"ok": ok, "detail": out[-3000:]}


# ---- HTTP ----------------------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    app = None
    page = ""

    def log_message(self, fmt, *args):
        pass

    def send(self, code, body, ctype="application/json", extra=None):
        data = body if isinstance(body, bytes) else (json.dumps(body) if ctype == "application/json" else body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if not isinstance(body, bytes) else ""))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def json(self):
        raw = self.body()
        return json.loads(raw.decode("utf-8")) if raw else {}

    def state(self):
        a = self.app
        return {"draft": a.draft, "steps": STEPS, "roles": {"job": a.job_roles, "gate": a.gate_roles},
                "gates": a.gates, "queues": STATUS_QUEUES, "fields": FIELD_KEYS, "secrets": a.secrets(),
                "first_open": a.first_open(), "run": {"status": a.run["status"]}, "offline": a.offline,
                "sandbox_offered": a.local() or not a.real_ready(), "where": WHERE,
                "titles": steps.default_titles(a.values()), "source": a.source}

    def do_GET(self):
        try:
            return self._get()
        except Exception as e:  # noqa: BLE001 - shown in the window instead of a dropped connection
            return self.send(500, {"error": "%s: %s" % (type(e).__name__, e)})

    def do_POST(self):
        try:
            return self._post()
        except Exception as e:  # noqa: BLE001
            return self.send(500, {"error": "%s: %s" % (type(e).__name__, e)})

    def _get(self):
        a, path = self.app, urllib.parse.urlparse(self.path).path
        if path == "/":
            return self.send(200, self.page, "text/html")
        if path == "/api/state":
            return self.send(200, self.state())
        if path == "/api/draft.yaml":
            a.save()
            return self.send(200, open(a.draft_path, "rb").read(), "application/x-yaml",
                             {"Content-Disposition": 'attachment; filename="%s"' % steps.DRAFT_NAME})
        if path == "/templates/roster-template.csv":
            return self.send(200, open(os.path.join(HERE, "templates", "roster-template.csv"), "rb").read(), "text/csv",
                             {"Content-Disposition": 'attachment; filename="roster-template.csv"'})
        if path == "/api/review":
            return self.send(200, a.review())
        if path == "/api/log" or path.startswith("/api/log/"):
            tail = path[len("/api/log/"):] if path.startswith("/api/log/") else ""
            n = int(tail) if tail.isdigit() else 0
            return self.send(200, {"lines": a.run["lines"][n:], "next": len(a.run["lines"]), "status": a.run["status"],
                                   "steps": a.run["steps"], "result": a.run["result"]})
        return self.send(404, {"error": "not found"})

    def _post(self):
        a, path = self.app, urllib.parse.urlparse(self.path).path
        try:
            if path == "/api/step":
                body = self.json()
                a.draft["values"].update({k: str(v) for k, v in (body.get("values") or {}).items() if k in install.DEFAULTS})
                a.draft["settings"].update(body.get("settings") or {})
                if a.draft["settings"].get("target"):
                    a.draft["settings"]["target"] = os.path.abspath(os.path.expanduser(a.draft["settings"]["target"]))
                step = body.get("step", "check")
                a.draft["step"] = STEPS.index(step) if step in STEPS else 0
                a.save()
                return self.send(200, {"problems": a.problems(step)})
            if path == "/api/check":
                return self.send(200, a.live(self.json().get("step", "check")))
            if path == "/api/sandbox":
                return self.send(200, a.sandbox_on(self.json().get("folder") or ""))
            if path == "/api/clone":
                a.draft["settings"].update(self.json().get("settings") or {})
                return self.send(200, a.clone())
            if path == "/api/roster/upload":
                rows = steps.parse_roster(self.body(), self.headers.get("X-Filename") or "")
                return self.send(200, {"roster": rows})
            if path == "/api/draft":
                a.draft = a._merge(steps.read_draft(self.body().decode("utf-8")))
                a.save()
                a.sandbox_resume()
                return self.send(200, {"first_open": a.first_open()})
            if path == "/api/finish-later":
                return self.send(200, a.finish_later(self.json().get("where", "chat")))
            if path == "/api/install":
                if a.run["status"] != "failed" and a.problems("review"):
                    return self.send(409, {"error": "fix the items on the Review step first"})
                return self.send(200, {"started": a.start_install()})
            if path == "/api/playbooks":
                return self.send(200, a.playbooks(bool(self.json().get("apply"))))
        except (ValueError, KeyError) as e:
            return self.send(400, {"error": str(e)})
        return self.send(404, {"error": "not found"})


CSS = r"""
.iw { border: 1px solid rgb(var(--border-primary)); border-radius: 10px; overflow: hidden; background: rgb(var(--bg-elevated));
  box-shadow: 0 6px 24px rgb(0 0 0 / .10); }
.iw-bar { display: flex; gap: 10px; align-items: center; padding: 9px 16px; color: #fff; font-size: 13px;
  background: linear-gradient(90deg, rgb(var(--brand-purple)), rgb(var(--brand-purple-light))); }
.iw-bar b { font-size: 14px; } .iw-bar .r { margin-left: auto; opacity: .9; }
.iw-body { display: grid; grid-template-columns: 210px 1fr; min-height: 560px; }
.iw-nav { border-right: 1px solid rgb(var(--border-secondary)); padding: 14px 0; background: rgb(var(--brand-wash-soft)); }
.iw-nav div { padding: 7px 16px; font-size: 13px; display: flex; gap: 8px; align-items: center; cursor: pointer; }
.iw-nav .n { display: inline-flex; width: 20px; height: 20px; border-radius: 50%; align-items: center; justify-content: center;
  font-size: 11px; border: 1px solid rgb(var(--border-primary)); }
.iw-nav .done .n { background: rgb(var(--brand-success)); color: #fff; border-color: transparent; }
.iw-nav .cur { background: rgb(var(--brand-pale)); font-weight: 600; border-left: 3px solid rgb(var(--brand-purple)); }
.iw-nav .cur .n { background: rgb(var(--brand-purple)); color: #fff; border-color: transparent; }
.iw-main { padding: 18px 24px; display: flex; flex-direction: column; min-width: 0; }
.iw-main h2 { margin: 0 0 4px; font-size: 18px; } .iw-lead { margin: 0 0 14px; font-size: 13px; }
.iw-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px 18px; }
.iw-grid.three { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.iw-f label { display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px; }
.iw-f input, .iw-f select, .iw-t input, .iw-t select { width: 100%; box-sizing: border-box; border: 1px solid rgb(var(--border-primary));
  border-radius: 6px; padding: 7px 9px; font: inherit; font-size: 13px; background: rgb(var(--bg-page)); color: inherit; }
.iw-t input, .iw-t select { padding: 5px 7px; font-size: 12.5px; }
.iw-f small { display: block; font-size: 11.5px; margin-top: 3px; opacity: .8; }
.iw-h { margin: 16px 0 6px; font-size: 13px; font-weight: 600; }
.ok { color: rgb(var(--brand-success)); font-weight: 600; } .bad { color: rgb(var(--brand-error)); font-weight: 600; }
.warn { color: rgb(180 130 0); font-weight: 600; }
.iw-t { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.iw-t th, .iw-t td { border-bottom: 1px solid rgb(var(--border-secondary)); padding: 6px 6px; text-align: left; vertical-align: top; }
.iw-t th { background: rgb(var(--brand-pale)); font-size: 12px; }
.iw-foot { margin-top: auto; padding-top: 18px; display: flex; gap: 10px; justify-content: flex-end; align-items: center; }
.iw-foot .hint { margin-right: auto; font-size: 12.5px; }
.btn { padding: 7px 16px; border-radius: 6px; font: inherit; font-size: 13px; border: 1px solid rgb(var(--border-primary));
  background: rgb(var(--bg-elevated)); color: inherit; cursor: pointer; }
.btn.p { background: rgb(var(--brand-purple)); color: #fff; border-color: transparent; }
.btn.s { padding: 4px 10px; font-size: 12px; } .btn:disabled { opacity: .5; cursor: default; }
.iw-probs { border-left: 4px solid rgb(var(--brand-error)); background: rgb(var(--brand-error) / .07); padding: 8px 12px; border-radius: 4px;
  font-size: 12.5px; margin: 12px 0 0; } .iw-probs li { margin: 2px 0; }
.iw-alert { border-left: 4px solid rgb(var(--brand-error)); background: rgb(var(--brand-error) / .07); padding: 9px 12px; border-radius: 4px; font-size: 13px; margin: 4px 0 12px; }
.iw-opt { border: 1px solid rgb(var(--border-primary)); border-radius: 8px; padding: 10px 14px; margin-bottom: 10px; font-size: 13px; cursor: pointer; display: block; }
.iw-opt input { margin-right: 8px; } .iw-opt small { display: block; opacity: .85; font-size: 12px; margin: 3px 0 0 24px; }
.iw-log { font-family: ui-monospace, Menlo, monospace; font-size: 12px; background: rgb(35 30 51); color: #e9e6f5; border-radius: 6px;
  padding: 12px 14px; line-height: 1.6; max-height: 360px; overflow: auto; white-space: pre-wrap; }
.iw-drop { border: 2px dashed rgb(var(--border-primary)); border-radius: 8px; padding: 10px; text-align: center; font-size: 12.5px; margin-top: 12px; }
.iw-modal { position: fixed; inset: 0; background: rgb(0 0 0 / .35); display: flex; align-items: center; justify-content: center; z-index: 50; }
.iw-modal > div { background: rgb(var(--bg-elevated)); border-radius: 10px; padding: 20px 24px; width: min(720px, 92vw); max-height: 90vh; overflow: auto; }
.chip { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11.5px; background: rgb(var(--brand-pale)); margin: 0 4px 4px 0; }
@media (max-width: 900px) { .iw-body { grid-template-columns: 1fr; } .iw-nav { display: none; } .iw-grid, .iw-grid.three { grid-template-columns: 1fr; } }
"""

JS = r"""
const NAMES = {check: 'Check', team: 'Team', jira: 'Jira', confluence: 'Confluence', repos: 'Repositories',
  envs: 'Environments', roster: 'Roster', review: 'Review', install: 'Install', next: 'Next steps'};
let S = null, cur = 0, live = {}, probs = [], logFrom = 0, timer = null;
const $ = (q) => document.querySelector(q);
const h = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
async function api(path, body, raw) {
  const opt = body === undefined ? {} : {method: 'POST', body: raw ? body : JSON.stringify(body), headers: raw ? {} : {'Content-Type': 'application/json'}};
  if (raw && raw.name) opt.headers['X-Filename'] = raw.name;
  const r = await fetch(path, opt); const j = await r.json().catch(() => ({}));
  if (!r.ok && j.error) throw new Error(j.error); return j;
}
const V = () => S.draft.values, T = () => S.draft.settings;
function get(path) { const [root, ...ks] = path.split('.'); let o = root === 'v' ? V() : T(); for (const k of ks) o = (o || {})[k]; return o == null ? '' : o; }
function set(path, val) { const [root, ...ks] = path.split('.'); let o = root === 'v' ? V() : T();
  for (const k of ks.slice(0, -1)) o = o[k] = o[k] || {}; o[ks[ks.length - 1]] = val; }
function field(label, path, hint, opts) { opts = opts || {};
  return `<div class="iw-f"><label>${h(label)}</label><input data-k="${path}" value="${h(get(path))}" placeholder="${h(opts.ph || '')}"${opts.list ? ` list="${opts.list}"` : ''}>${hint ? `<small>${hint}</small>` : ''}</div>`; }
function mark(ok) { return ok === true ? '<span class="ok">&#10003; OK</span>' : ok === false ? '<span class="bad">&#10007; Fix</span>' : '<span class="warn">! Optional</span>'; }
function sandboxBox() { if (T().sandbox) return `<div class="iw-drop">Sandbox on: the sample company Acme Claims, with its Jira and Confluence at <a target="_blank" href="${h(T().sandbox_url)}">${h(T().sandbox_url)}</a>. Every step is filled in; go through them and press Install.</div>`;
  const ex = (live.check || {}).extra || {};
  if (!('sandbox_offered' in ex ? ex.sandbox_offered : S.sandbox_offered)) return '';
  return `<div class="iw-drop"><b>Try it in a sandbox</b> (a made-up company: sample Jira, Confluence pages, database, knowledge base and repo; nothing real is touched)<br>
  <input id="sbdir" style="width:60%" value="${h(T().sandbox_folder || '~/Documents/sdlc-sandbox')}"> <button class="btn s" onclick="makeSandbox()">Make the sandbox</button> <span id="sbmsg"></span></div>`; }
async function makeSandbox() { collect(); $('#sbmsg').textContent = 'Making the sandbox…'; const r = await api('/api/sandbox', {folder: $('#sbdir').value});
  if (!r.ok) { $('#sbmsg').innerHTML = `<span class="bad">${h(r.detail)}</span>`; return; } S = await api('/api/state'); live.check = await api('/api/check', {step: 'check'}); render(); }
function checks(step) { const c = live[step]; if (!c) return '';
  return `<table class="iw-t" style="margin-top:12px"><thead><tr><th>Item</th><th>Status</th><th>Detail</th></tr></thead><tbody>${c.rows.map(r =>
    `<tr><td>${h(r.item)}</td><td>${mark(r.ok)}</td><td>${h(r.detail)}</td></tr>`).join('')}</tbody></table>`; }
function collect() {
  document.querySelectorAll('[data-k]').forEach(el => set(el.dataset.k, el.type === 'checkbox' ? el.checked : el.value));
  document.querySelectorAll('[data-env]').forEach(el => { const [i, k] = el.dataset.env.split(':'); T().environments[+i][k] = el.value; });
  document.querySelectorAll('[data-ro]').forEach(el => { const [i, k] = el.dataset.ro.split(':');
    T().roster[+i][k] = el.type === 'checkbox' ? (el.checked ? 'yes' : 'no') : el.value; });
  const dirs = [...document.querySelectorAll('[data-kbdir]:checked')].map(x => x.value);
  const more = $('#kbmore'); if (more || document.querySelector('[data-kbdir]')) T().kb_source_dirs = dirs.concat((more ? more.value : '').split(',').map(x => x.trim()).filter(Boolean));
}
const SCREENS = {
  check: () => { const w = T().where || 'cloud', mcp = T().mcp || {};
    return {title: w === 'local' ? 'Check this PC' : 'Check this session',
    lead: w === 'uep' ? 'What the install needs in this UEP Devin Cloud session. The service accounts in its secrets reach Jira, Confluence, Snowflake and the repos. Secrets are only checked for being there; their values are never shown.'
      : w === 'local' ? 'What the install needs on this PC with Devin Local. The Jira and Confluence tokens come from environment variables with the names you give; they are only checked for being there and their values are never shown.'
      : 'What the install needs in this Devin Cloud session. Secrets are only checked for being there; their values are never shown.',
    html: `<div class="iw-grid"><div class="iw-f"><label>Where are you installing?</label><select data-k="s.where" onchange="T().where_chosen = true; runCheck('check')">
      ${[['uep', 'UEP Devin Cloud (service accounts)'], ['cloud', 'Other Devin Cloud'], ['local', 'Devin Local (Windows, Mac or Linux PC)']].map(([k, l]) => `<option value="${k}"${w === k ? ' selected' : ''}>${l}</option>`).join('')}</select>
      <small>Picked for you when this session already has the Jira and Confluence secrets. Devin Local opens this window in your own browser and skips the Devin Cloud setup.</small></div></div>
      ${w === 'uep' ? '' : `<div class="iw-alert"><b>Outside UEP you need these before you can use Argus:</b> MCP servers for Jira and Confluence (Devin's chat skills use them), your own Jira and Confluence API tokens (personal access tokens, which Argus and its programs use; ${w === 'local' ? 'set them as environment variables on this PC' : 'save them as Devin secrets'}), and git access to your repo. A Snowflake MCP server is optional: without it the database and ETL parts of the knowledge base can't be built (the sandbox uses its own sample database). Getting these is up to your team; the install then sets Argus up to use them.</div>`}
      <p class="iw-h">Your MCP servers (the names as Devin shows them)</p><div class="iw-grid three">${field('Jira MCP server', 's.mcp.jira', w === 'uep' ? 'Optional in UEP' : 'Needed', {ph: 'jira'})}${field('Confluence MCP server', 's.mcp.confluence', w === 'uep' ? 'Optional in UEP' : 'Needed', {ph: 'confluence'})}${field('Snowflake MCP server', 's.mcp.snowflake', 'Optional', {ph: 'snowflake'})}</div>`
      + sandboxBox() + checks('check') + `<div class="iw-drop">Coming back? <label class="btn s">Load a saved draft<input type="file" accept=".yaml,.yml" hidden onchange="loadDraft(this.files[0])"></label> (install-draft.yaml)</div>`, run: 'check'}; },
  team: () => ({title: 'Your team', lead: 'How the framework names your team everywhere: pages, dashboards, decks and Jira comments.',
    html: `<div class="iw-grid">${field('Product or team name', 'v.product_name', '', {ph: 'Acme Claims'})}${field('Company', 'v.company_name', '', {ph: 'Acme Corp'})}
      ${field('Email domain', 'v.email_domain', 'Used to recognise your people in chat and git', {ph: '@acme.example'})}${field('Devin Cloud host', 'v.devin_host', '', {ph: 'acme.devinenterprise.com'})}
      ${field('Tech lead (Last, First)', 's.tech_lead.name', 'You. Roster owner and first approver', {ph: 'Doe, Jane'})}${field('Tech lead email', 's.tech_lead.email', '', {ph: 'jane.doe@acme.example'})}</div>`}),
  jira: () => { const st = (live.jira && live.jira.extra.statuses) || [], fl = (live.jira && live.jira.extra.fields) || [];
    return {title: 'Jira', lead: (T().where === 'uep' ? 'Use a service-account token saved as a Devin secret. Personal tokens are not used.' : T().where === 'local' ? 'Use your Jira API token (personal access token), set as an environment variable on this PC.' : 'Use your Jira API token (personal access token), saved as a Devin secret.') + ' Check reads the project and offers its statuses and custom fields.', run: 'jira',
    html: `<datalist id="dl-st">${st.map(x => `<option value="${h(x)}">`).join('')}</datalist><datalist id="dl-f">${fl.map(x => `<option value="${h(x.split(' ')[0])}">${h(x)}</option>`).join('')}</datalist>
      <div class="iw-grid three">${field('Jira host', 'v.jira_host', 'No https://', {ph: 'jira.acme.example'})}${field('Project key', 'v.jira_project', '', {ph: 'ACME'})}
      ${field(T().where === 'local' ? 'Token environment variable' : 'Token secret name', 'v.jira_token_env', T().where === 'local' ? 'The environment variable that holds the token' : 'The Devin secret that holds the token', {ph: 'ACME_JIRA_TOKEN'})}</div>
      <div class="iw-grid three" style="margin-top:12px">${field('IT team (if your JQL filters on one)', 's.it_team', '', {ph: 'Acme-Claims-Web'})}</div>
      <p class="iw-h">Statuses behind each queue (comma separated)</p><div class="iw-grid three">${S.queues.map(q => field(q.replace(/_/g, ' '), 's.jira_statuses.' + q, '', {list: 'dl-st'})).join('')}</div>
      <p class="iw-h">Custom fields</p><div class="iw-grid three">${S.fields.map(f => field(f.replace(/_/g, ' '), 's.jira_fields.' + f, '', {list: 'dl-f', ph: 'customfield_…'})).join('')}</div>` + checks('jira')}; },
  confluence: () => ({title: 'Confluence', lead: 'The install creates four pages under a parent page you can write under. A page that is already there is kept.', run: 'confluence',
    html: `<div class="iw-grid three">${field('Confluence host', 'v.wiki_host', 'No https://', {ph: 'wiki.acme.example'})}${field('Space key', 'v.wiki_space', '', {ph: 'ACMEWIKI'})}
      ${field(T().where === 'local' ? 'Token environment variable' : 'Token secret name', 'v.confluence_token_env', T().where === 'uep' ? 'A service-account token' : 'Your Confluence API token (personal access token)', {ph: 'ACME_CONFLUENCE_TOKEN'})}</div><div class="iw-grid" style="margin-top:12px">${field('Parent page (link or id)', 's.confluence_parent', 'The team pages go under it')}</div>
      <p class="iw-h">Pages it will create</p><div class="iw-grid">${['roster', 'sprint_leave', 'demo_recordings', 'user_manual'].map(k => field(k.replace(/_/g, ' '), 's.pages.' + k, '', {ph: S.titles[k]})).join('')}</div>` + checks('confluence')}),
  repos: () => { const fl = (live.repos && live.repos.extra.folders) || [], chosen = T().kb_source_dirs || [];
    return {title: 'Repositories', lead: 'The framework goes on your work branch through a pull request. The install never merges.', run: 'repos',
    html: `<div class="iw-grid">${field('Git host', 'v.git_host', 'No https://', {ph: 'git.acme.example'})}${field('App repository (PROJECT/repo)', 'v.repo_slug', '', {ph: 'ACME/claims-web'})}
      ${field('Local clone on this machine', 's.target', 'Devin Cloud clones connected repos under ~/repos/', {ph: '~/repos/claims-web'})}
      <div class="iw-f"><label>Clone URL (only if it isn't cloned yet)</label><input data-k="s.clone_url" value="${h(get('s.clone_url'))}" placeholder="https://git.acme.example/ACME/claims-web.git"><small><button class="btn s" onclick="cloneRepo()">Clone</button></small></div>
      ${field('Work branch', 'v.work_branch', "Created from the default branch if it isn't there", {ph: 'feature/devin-sdlc'})}${field('Deploy repository', 'v.deploy_slug', '', {ph: 'ACME/claims-deploy'})}
      ${field('QA automation repository', 'v.qa_repo_slug', '', {ph: 'ACME/claims-qa'})}${field('ETL repository (optional)', 's.etl_repo_slug', 'Leave empty to skip the ETL part of the KB')}</div>
      <p class="iw-h">Where the framework goes in your repo</p><div class="iw-grid">${field('SDLC folder', 'v.sdlc_dir', 'Playbooks, workflows, tools, Argus, KB prompts. One folder at the repo root')}
      ${field('Knowledge base folder', 'v.kb_dir', 'The KB documents')}</div><p style="font-size:12px;margin:4px 0 0">.devin/ (rules and skills) always goes at the repo root.</p>
      <p class="iw-h">Source folders for the knowledge base</p><div>${fl.map(f => `<label class="chip"><input type="checkbox" data-kbdir value="${h(f)}"${chosen.includes(f) ? ' checked' : ''}> ${h(f)}/</label>`).join('') || '<small>Press Check to list the folders of your repo.</small>'}</div>
      <div class="iw-f" style="margin-top:8px"><label>Other source folders (comma separated, e.g. web/app)</label><input id="kbmore" value="${h(chosen.filter(x => !fl.includes(x)).join(', '))}"></div>` + checks('repos')}; },
  envs: () => ({title: 'Environments', lead: 'Promotion order, with the app and deploy branches, the values-file suffix and the gate before each one.',
    html: `<table class="iw-t"><thead><tr><th>Order</th><th>Name</th><th>App branch</th><th>Deploy branch</th><th>Values file</th><th>Gate before it</th><th></th></tr></thead><tbody>${(T().environments || []).map((e, i) =>
      `<tr><td>${i + 1}</td>${['name', 'app_branch', 'deploy_branch', 'values'].map(k => `<td><input data-env="${i}:${k}" value="${h(e[k])}"></td>`).join('')}
      <td><select data-env="${i}:gate"><option value=""></option>${S.gates.map(g => `<option${g === e.gate ? ' selected' : ''}>${h(g)}</option>`).join('')}</select></td><td><button class="btn s" onclick="rmEnv(${i})">Remove</button></td></tr>`).join('')}</tbody></table>
      <p><button class="btn s" onclick="addEnv()">+ Add environment</button></p>`}),
  roster: () => { const found = {}; ((live.roster && live.roster.extra.roster) || []).forEach(p => found[p.email] = p.found);
    return {title: 'Roster', lead: 'Your team, their roles and who can sign which gate. Type them in or upload the filled-in template. Check looks the Jira users up by email.', run: 'roster',
    html: `<datalist id="dl-gate">${S.roles.gate.map(r => `<option value="${h(r)}">`).join('')}</datalist><table class="iw-t"><thead><tr><th>Name (Last, First)</th><th>Email</th><th>Jira user</th><th>Primary role</th><th>Gate roles</th><th>Alloc %</th><th>Delegate</th><th>Delivery</th><th></th></tr></thead><tbody>${(T().roster || []).map((p, i) =>
      `<tr><td><input data-ro="${i}:name" value="${h(p.name)}"></td><td><input data-ro="${i}:email" value="${h(p.email)}"></td>
      <td><input data-ro="${i}:jira_user" value="${h(p.jira_user)}">${found[p.email] === true ? '<span class="ok">&#10003; found</span>' : found[p.email] === false ? '<span class="bad">&#10007; not found</span>' : ''}</td>
      <td><select data-ro="${i}:primary_role">${S.roles.job.map(r => `<option${r === p.primary_role ? ' selected' : ''}>${h(r)}</option>`).join('')}</select></td>
      <td><input data-ro="${i}:roles" list="dl-gate" value="${h(Array.isArray(p.roles) ? p.roles.join(', ') : p.roles)}"></td><td><input data-ro="${i}:allocation" value="${h(p.allocation == null ? 100 : p.allocation)}" style="width:56px"></td>
      <td><input data-ro="${i}:delegate" value="${h(p.delegate)}"></td><td><input type="checkbox" data-ro="${i}:delivery"${String(p.delivery) === 'no' || p.delivery === false ? '' : ' checked'}></td><td><button class="btn s" onclick="rmPerson(${i})">Remove</button></td></tr>`).join('')}</tbody></table>
      <div class="iw-drop">Upload a filled-in <b>roster-template.csv</b> or <b>.xlsx</b> <label class="btn s">Choose file<input type="file" accept=".csv,.xlsx" hidden onchange="upload(this.files[0])"></label>
      &middot; <a href="/templates/roster-template.csv">Download the template</a> &middot; <button class="btn s" onclick="addPerson()">+ Add person</button></div>` + checks('roster')}; },
  review: () => ({title: 'Review', lead: 'Nothing has been written yet. This is everything Install will do.', html: '<div id="rev">Loading&hellip;</div>'}),
  install: () => ({title: 'Installing', lead: 'Each step stops the install if it fails. You can close this window; the log stays on this machine.', html: '<div id="steps"></div><div class="iw-log" id="log"></div>'}),
  next: () => ({title: 'Installed. What is left', lead: 'Three things only people can do, then the knowledge base.', html: '<div id="nxt"></div>'}),
};
function render() {
  const st = S.steps[cur], sc = SCREENS[st]();
  const nav = S.steps.map((s, i) => `<div class="${i < cur ? 'done' : i === cur ? 'cur' : ''}" onclick="jump(${i})"><span class="n">${i < cur ? '&#10003;' : i + 1}</span>${NAMES[s]}</div>`).join('');
  const busy = S.run.status === 'running', canSave = cur < 8;
  const next = st === 'review' ? 'Install' : st === 'install' ? (S.run.status === 'failed' ? 'Run again' : 'Next') : st === 'next' ? '' : 'Next';
  $('#app').innerHTML = `<div class="iw"><div class="iw-bar"><b>Install Argus</b><span>Step ${cur + 1} of ${S.steps.length}</span><span class="r">${S.draft.values.product_name ? h(S.draft.values.product_name) : ''}</span></div>
    <div class="iw-body"><nav class="iw-nav">${nav}</nav><div class="iw-main"><h2>${sc.title}</h2><p class="iw-lead">${sc.lead}</p>${sc.html}
    ${probs.length ? `<ul class="iw-probs">${probs.map(p => `<li>${h(p)}</li>`).join('')}</ul>` : ''}
    <div class="iw-foot"><span class="hint" id="hint"></span>${sc.run ? `<button class="btn" onclick="runCheck('${sc.run}')">Check</button>` : ''}
    ${canSave ? '<button class="btn" onclick="later()">Save and finish later</button>' : ''}${cur > 0 && st !== 'install' && st !== 'next' ? '<button class="btn" onclick="go(-1)">Back</button>' : ''}
    ${next ? `<button class="btn p" id="nextb" onclick="go(1)"${busy ? ' disabled' : ''}>${next}</button>` : ''}</div></div></div></div>`;
  if (st === 'review') review(); if (st === 'install') poll(); if (st === 'next') nextSteps();
}
async function save(step) { collect(); const r = await api('/api/step', {step, values: V(), settings: T()}); return r.problems || []; }
async function go(d) {
  const st = S.steps[cur];
  if (d < 0) { await save(st); probs = []; cur--; return render(); }
  if (st === 'review') { try { await api('/api/install', {}); S.run.status = 'running'; probs = []; cur++; return render(); } catch (e) { probs = [e.message]; return render(); } }
  if (st === 'install') { if (S.run.status === 'failed') { await api('/api/install', {}); S.run.status = 'running'; logFrom = 0; return render(); } cur++; return render(); }
  probs = await save(st); if (probs.length) return render(); cur++; render();
}
async function jump(i) { if (i <= cur && cur < 8) { await save(S.steps[cur]); probs = []; cur = i; await runCheckSilent(); render(); } }
function takeWhere() { const w = ((live.check || {}).extra || {}).where; if (w) T().where = w; }
async function runCheck(step) { await save(S.steps[cur]); $('#hint').textContent = 'Checking…'; live[step] = await api('/api/check', {step}); if (step === 'check') takeWhere();
  if (step === 'roster') S = await api('/api/state'); render(); }
async function cloneRepo() { collect(); $('#hint').textContent = 'Cloning…'; const r = await api('/api/clone', {settings: T()}); S = await api('/api/state'); render();
  $('#hint').innerHTML = r.ok ? `<span class="ok">Cloned: ${h(r.detail)}</span>` : `<span class="bad">${h(r.detail)}</span>`; }
async function upload(f) { if (!f) return; collect(); try { const r = await api('/api/roster/upload', await f.arrayBuffer(), f); T().roster = r.roster; probs = []; } catch (e) { probs = [e.message]; } render(); }
async function loadDraft(f) { if (!f) return; try { const r = await api('/api/draft', await f.text(), f); S = await api('/api/state'); cur = r.first_open; probs = []; for (const k in live) delete live[k]; await runCheckSilent(); } catch (e) { probs = [e.message]; } render(); }
function addPerson() { collect(); T().roster.push({name: '', email: '', jira_user: '', primary_role: 'developer', roles: '', allocation: 100, delegate: '', delivery: 'yes'}); render(); }
function rmPerson(i) { collect(); T().roster.splice(i, 1); render(); }
function addEnv() { collect(); T().environments.push({name: '', app_branch: '', deploy_branch: '', values: '', gate: ''}); render(); }
function rmEnv(i) { collect(); T().environments.splice(i, 1); render(); }
async function review() { const r = await api('/api/review'); probs = r.problems;
  $('#rev').innerHTML = `<div class="iw-grid"><div><p class="iw-h">Values</p><table class="iw-t"><tbody>${r.values.map(([k, v]) => `<tr><td>${h(k)}</td><td>${h(v)}</td></tr>`).join('')}</tbody></table></div>
  <div><p class="iw-h">It will</p><ol style="font-size:13px;padding-left:18px">
  <li>Make a branch ${h(r.branch)} in ${h(r.target)}.</li><li>Copy ${r.files} framework files in, with your values and folders.</li>
  <li>Write the roster (${r.roster} people), Jira statuses and fields, environments and KB folders.</li>
  <li>Create under <b>${h(r.parent)}</b>: ${r.pages.map(h).join(', ')}. Pages already there are kept.</li>
  ${r.mcp.length ? `<li>Point the chat skills at your MCP servers: ${r.mcp.map(h).join(', ')}.</li>` : ''}
  <li>Run the checks: connectivity, validation, prompt lint, tests, no example values left.</li>
  <li>Commit and push the branch; Devin opens the pull request. A person merges it.</li>
  ${T().where === 'local' ? '' : '<li>List the playbooks, and prepare the Devin Cloud blueprint and knowledge note for you to approve.</li>'}</ol></div></div>`;
  if (probs.length) { $('#app .iw-main').insertAdjacentHTML('beforeend', ''); const b = $('#nextb'); if (b) b.disabled = true;
    $('#rev').insertAdjacentHTML('afterend', `<ul class="iw-probs">${probs.map(p => `<li>${h(p)}</li>`).join('')}</ul>`); } }
async function poll() { clearTimeout(timer); const r = await api('/api/log/' + logFrom); logFrom = r.next; const L = $('#log'); if (!L) return;
  L.textContent += r.lines.map(x => x + '\n').join(''); L.scrollTop = L.scrollHeight;
  $('#steps').innerHTML = `<p>${r.steps.map(s => `<span class="chip">${s.status === 'ok' ? '&#10003;' : s.status === 'failed' ? '&#10007;' : '&#9679;'} ${h(s.name)}</span>`).join('')}</p>`;
  if (S.run.status !== r.status) { S.run.status = r.status; S.result = r.result; const keep = L.textContent; render(); $('#log').textContent = keep; }
  if (r.status === 'running') timer = setTimeout(poll, 1000); else S.result = r.result; }
async function nextSteps() { const r = (await api('/api/log/999999')).result || {}; const v = V(), wiki = r.wiki || '';
  const page = (k) => r.pages && r.pages[k] ? `<a target="_blank" href="${h(wiki)}/pages/viewpage.action?pageId=${h(r.pages[k])}">${h(k.replace(/_/g, ' '))}</a>` : h(k.replace(/_/g, ' '));
  $('#nxt').innerHTML = `<ol style="font-size:13.5px;line-height:1.7;padding-left:18px">
  <li><b>Merge the pull request</b> of branch <code>${h(r.branch)}</code> into <code>${h(v.work_branch)}</code>. Devin posts its link in the chat.</li>
  <li><b>Sign the roster</b> on the ${page('roster')} page: comment <i>approved</i>. Until then gate sign-offs and guarded writes are blocked on purpose.
     Then in Devin${T().where === 'local' ? '' : ' Cloud'}: <code>/roster-sync</code>. Other pages: ${page('sprint_leave')}, ${page('demo_recordings')}, ${page('user_manual')}.</li>
  ${T().where === 'local' || T().sandbox ? '' : `<li><b>Approve the Devin Cloud setup</b>: Devin proposes the repo blueprint and the knowledge note for <code>${h(v.work_branch)}</code> in the chat.</li>`}
  <li><b>Playbooks</b>: <button class="btn s" onclick="pb(false)">List</button> <button class="btn s" onclick="pb(true)"${S.secrets.DEVIN_API_KEY ? '' : ' disabled title="needs the DEVIN_API_KEY secret"'}>Register in Devin Cloud</button></li>
  <li><b>Argus</b> on each PC: clone the repo on <code>${h(v.work_branch)}</code>, then run <code>${h(v.sdlc_dir)}/framework/console/start-workbench.cmd</code> (Windows) or <code>run.sh</code>.</li>
  ${T().sandbox ? `<li><b>Sandbox</b>: its Jira and Confluence are at <a target="_blank" href="${h(T().sandbox_url)}">${h(T().sandbox_url)}</a> while this window runs. Later, start them with <code>python3 ${h(v.sdlc_dir)}/framework/tools/sandbox/sandbox_server.py --folder ${h(T().sandbox_folder)}</code> and turn the sandbox on in your shell with <code>switch.py</code> in the same folder.</li>` : ''}
  <li>Then start with <code>/help</code>, and <code>/kb-context-build</code> for the knowledge base.</li></ol><pre class="iw-log" id="pbout" hidden></pre>`; }
async function pb(apply) { const r = await api('/api/playbooks', {apply}); const o = $('#pbout'); o.hidden = false; o.textContent = r.detail; }
function later() { collect();
  const m = document.createElement('div'); m.className = 'iw-modal';
  m.innerHTML = `<div><h2 style="margin-top:0">Save and finish later</h2><p style="font-size:13px">Your values are kept on this Devin machine while this session lives. To come back later, or in a new session, save them somewhere first.</p>
  <div class="iw-alert"><b>If you don't save,</b> a new session starts on a fresh machine and you start afresh: every value and the roster have to be typed again.</div>
  <label class="iw-opt"><input type="radio" name="w" value="chat" checked><b>Save to my PC (recommended)</b><small>Devin posts install-draft.yaml in this chat. Download it from the chat any time; it stays there after the session ends.
  Next time: attach the zip and this file to a new session and type "install this with my values".</small></label>
  <label class="iw-opt"><input type="radio" name="w" value="download"><b>Download now from this window</b><small>Saves install-draft.yaml to your browser's Downloads folder. Next time: same as above.</small></label>
  <label class="iw-opt"><input type="radio" name="w" value="repo"><b>Check it into my repo</b><small>Commits only install-draft.yaml to a branch devin/install-draft in your app repo. Your work branch is not touched, and the branch is deleted when the install finishes.
  Next time: type "install this, my values are on devin/install-draft in &lt;your repo&gt;".</small></label>
  <p style="font-size:12.5px">Secrets are not in the file, only their names.</p><p id="lmsg" style="font-size:13px"></p>
  <div class="iw-foot"><button class="btn" id="lcancel">Carry on instead</button><button class="btn p" id="lsave">Save</button></div></div>`;
  document.body.appendChild(m); m.querySelector('#lcancel').onclick = () => m.remove();
  m.querySelector('#lsave').onclick = async () => { await save(S.steps[cur]); const w = m.querySelector('input[name=w]:checked').value;
    if (w === 'download') { location.href = '/api/draft.yaml'; m.querySelector('#lmsg').innerHTML = '<span class="ok">Downloading install-draft.yaml.</span>'; return; }
    m.querySelector('#lmsg').textContent = 'Saving…'; const r = await api('/api/finish-later', {where: w});
    m.querySelector('#lmsg').innerHTML = `<span class="${r.ok ? 'ok' : 'bad'}">${h(r.detail)}</span>`; };
}
(async () => { S = await api('/api/state'); cur = S.run.status === 'running' || S.run.status === 'failed' ? 8 : (S.run.status === 'done' ? 9 : (S.draft.step || 0));
  if (cur === 0 && S.draft.saved_to === undefined) cur = 0; await runCheckSilent(); render(); })();
async function runCheckSilent() { if (cur === 0) { live.check = await api('/api/check', {step: 'check'}); takeWhere(); } }
"""


def page_html():
    kit_mod = kit()
    body = '<div id="app">Loading&hellip;</div>'
    if kit_mod:
        return kit_mod.render_page("Install Argus", body, subtitle="Devin Cloud or Devin Local",
                                   extra_css=CSS, extra_js=JS)
    return ("<!doctype html><html><head><meta charset='utf-8'><title>Install Argus</title>"
            "<style>:root{--brand-purple:82 15 186;--brand-purple-light:124 77 255;--brand-pale:237 231 255;"
            "--brand-wash-soft:248 246 255;--brand-success:40 160 130;--brand-error:200 30 60;--border-primary:200 196 214;"
            "--border-secondary:228 225 236;--bg-elevated:255 255 255;--bg-page:250 250 252}body{font-family:system-ui,"
            "sans-serif;margin:24px;color:#1d1a2b}%s</style></head><body>%s<script>%s</script></body></html>" % (CSS, body, JS))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--source", help="the shared copy (default: the folder of this script)")
    ap.add_argument("--target", help="your repo's local clone, to prefill the Repositories step")
    ap.add_argument("--state", default=os.path.expanduser("~/sdlc-install"), help="where the draft and log are kept")
    ap.add_argument("--draft", help="start from a saved install-draft.yaml")
    ap.add_argument("--draft-repo", help="start from the draft on devin/install-draft in this local clone")
    ap.add_argument("--offline", action="store_true", help="skip Jira, Confluence and push (for a dry run)")
    args = ap.parse_args(argv)
    source = find_source(args.source)
    if not source:
        print("No shared copy found (a folder with dot-devin/). Run this from the unzipped copy, or pass --source.")
        return 1
    app = App(source, args.state, target=os.path.abspath(os.path.expanduser(args.target)) if args.target else None,
              offline=args.offline)
    if args.draft:
        app.draft = app._merge(steps.read_draft(steps.read_text(args.draft)))
    elif args.draft_repo:
        app.draft = app._merge(steps.load_draft_from_repo(os.path.expanduser(args.draft_repo)))
        app.draft["settings"]["target"] = os.path.abspath(os.path.expanduser(args.draft_repo))
    if args.draft or args.draft_repo:
        app.draft["step"] = app.first_open()
        app.save()
    app.sandbox_resume()
    Handler.app, Handler.page = app, page_html()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print("Install window on http://%s:%d  (draft: %s)" % (args.host, args.port, app.draft_path), flush=True)
    print("%s READY %s" % (EVENT, json.dumps({"port": args.port, "first_step": STEPS[app.draft["step"]]})), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
