"""Argus — a local page that drives the whole SDLC through Devin sessions.

Argus runs on your own machine (bookmark http://127.0.0.1:8787), or in your own Devin Cloud session
(!argus or /argus, opened from the session's preview link). Each run it starts is a Devin session used as
a background worker, and the next answer or sign-off wakes it. Run history is rebuilt
from the Devin sessions tagged ``sdlc-workbench`` / ``sdlc-console``, so a fresh machine sees past runs.
The top menu comes from the viewer's role in .devin/rules/people.yaml and role-routing.yaml.

Pick a story from the team's Jira board — or type a requirement of your own — start a run, and the console
creates a Devin session with the ``/intake <PROJECT>-nnnn`` (or ``/intake "<text>"``) prompt plus the
dry-run rules. When the intake gate is approved with the "create a Jira story" box ticked, the
console turns the intake spec into a Jira Story (summary, user story, acceptance criteria in
the acceptance field, IT Team, assignee) and tells the session its key. It then polls that session's messages, turns
``[SDLC]`` progress lines into a stage/skill/playbook timeline, numbered questions into an answer
form, gate presentations into Approve / Reject cards, and ``[SDLC] artefact|diff|pr`` blocks into
the right-hand panel. Answers and decisions go back to the session as chat messages, so the
framework rules (``approved`` closes a gate, questions are numbered) still apply unchanged.

Stdlib only. Run from the repo root:  python3 <framework>/console/server.py [--port 8787]
Supervised (auto-restart, detached):  <framework>/console/run.sh start|restart|stop|status
Reaching Devin (SDLC_DEVIN_TRANSPORT): `bridge`, the default, is the hosting Devin Cloud session's own tools
(console/bridge.py), no key; `api` (set by start-workbench.cmd and the desktop icon) is a Devin API key from
DEVIN_API_KEY or saved once on the page (Windows Credential Manager).
Team values (product name, Jira project, repo, Devin org) come from .devin/rules/sdlc-profile.json
(console/sdlc_profile.py).
Jira: with the Jira token variable (jira.token_env in sdlc-profile.json) set (Devin Cloud, /devin-window) the ticket lists are read here; without it
(a tester's PC) a short Devin Cloud session reads them with the service account and hands back the list,
so no Jira token is ever needed on a PC. "Test on my PC" (console/pctest.py) runs the story's test pack
on this machine with Devin Local and sends the evidence back to the Cloud session. When Bitbucket has a newer
commit of the branch this checkout is on, the page offers "Update" (console/update.py): fast-forward, then restart.
Optional: --user <Jira username, e-mail or Devin user id> (or SDLC_CONSOLE_JIRA_USER) — who is using
the page, matched against people.yaml; /argus passes the requester's Devin user id so the page
opens as them instead of asking.
State lives in ~/.sdlc/console/runs.json (a cache; Devin is the source) — nothing is written into the repository.
"""
import argparse
import datetime
import io
import base64
import concurrent.futures
import json
import os
import re
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import bridge  # noqa: E402
import pctest  # noqa: E402
import sdlc_profile as team  # noqa: E402
import update  # noqa: E402
import doctor  # noqa: E402
import backlog  # noqa: E402
import poker_room  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import question_subtask as qs  # noqa: E402
import workbench_config  # noqa: E402
import observer  # noqa: E402
import sprint_leave  # noqa: E402
import artifact_kit  # noqa: E402
import gen_reference_pages  # noqa: E402
import grooming_prep  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = team.ROOT
KIT = os.path.join(team.FRAMEWORK_DIR, "tools", "artifact_kit")
STATIC = os.path.join(HERE, "static")
STATE_DIR = os.path.expanduser(os.environ.get("SDLC_CONSOLE_HOME", "~/.sdlc/console"))
STATE_PATH = os.path.join(STATE_DIR, "runs.json")
DELETED_PATH = os.path.join(STATE_DIR, "deleted.json")

JIRA_HOST = (os.environ.get("SDLC_JIRA_BASE") or os.environ.get("SDLC_SANDBOX_URL") or team.JIRA_HOST).rstrip("/")
JIRA = JIRA_HOST + "/rest"
JIRA_BROWSE = JIRA_HOST + "/browse/"
PROJECT = team.PROJECT
IT_TEAM = team.IT_TEAM
JIRA_TOKEN_ENV = team.JIRA_TOKEN_ENV
F_POINTS = team.FIELDS["story_points"]
F_SPRINT = team.FIELDS["sprint"]
F_ACCEPTANCE = team.FIELDS["acceptance"]
F_IT_TEAM = team.FIELDS["it_team"]
F_EPIC_LINK = team.FIELDS.get("epic_link") or ""
TICKET_RE = re.compile(r"^%s$" % team.TICKET)
TICKET_OR_REQ_RE = re.compile(r"^(?:%s|REQ-\d+)$" % team.TICKET)
STORY_FIELDS = "summary,status,assignee,reporter,priority,labels,issuetype,parent,%s,%s,updated" % (F_POINTS, F_SPRINT) + ("," + F_EPIC_LINK if F_EPIC_LINK else "")
# Ticket lists, from sdlc-profile.json jira.queries. qa and uat are the QA and UAT dashboard queues
# (.devin/rules/dashboard-roles.yaml test_queue, uat_queue); waiting is the Approval sub-tasks (/send-approval)
# and Question sub-tasks (/ask-question) waiting on this person.
JQL = dict(team.JQL)
# The Backlog tab's lists: groomable work and the open epics (console/backlog.py).
JQL.setdefault("backlog", backlog.BACKLOG_JQL)
JQL.setdefault("epics", backlog.EPICS_JQL)
PERSONAL_SCOPES = ("mine", "mine_sprint", "waiting") + (("automation",) if "automation" in JQL else ())
PEOPLE_PATH = os.path.join(ROOT, ".devin", "rules", "people.yaml")
ROUTING_PATH = os.path.join(ROOT, ".devin", "rules", "role-routing.yaml")
BUSINESS_PATH = os.path.join(ROOT, ".devin", "rules", "business-screens.json")
GATES_PATH = os.path.join(ROOT, ".devin", "rules", "approval-gates.yaml")
SKILLS_DIR = os.path.join(ROOT, ".devin", "skills")
GEN_DASHBOARD = os.path.join(team.FRAMEWORK_DIR, "tools", "gen_dashboard.py")
DASHBOARD_CACHE = os.environ.get("SDLC_WORKBENCH_DASHBOARD_CACHE", "")
DASHBOARD_PATH = os.path.join(STATE_DIR, "dashboard.html")
ACTIONS_PATH = os.path.join(STATE_DIR, "actions.html")  # the actions page: answers, approvals, handovers, config
# /dashboard before anyone pressed Dashboard: a page that builds it for the person picked in Argus.
DASHBOARD_MISSING = (
    "<!doctype html><title>Dashboard</title><style>body{margin:0;min-height:100vh;display:flex;align-items:center;"
    "justify-content:center;font-family:system-ui,sans-serif;color:#3b2a63;background:#f6f4fb}main{max-width:460px;"
    "text-align:center}button{font:inherit;padding:8px 16px;border-radius:6px;border:0;background:#5b3fa0;color:#fff;"
    "cursor:pointer}#m{color:#8a80a3;margin-top:12px}</style><main><h1>Your dashboard isn't built yet</h1>"
    "<p>It is built from Jira for your role. This takes up to a minute.</p><button id=b type=button>Build it now</button>"
    "<div id=m></div></main><script>document.getElementById('b').onclick=function(){var b=this,m=document.getElementById('m');"
    "b.disabled=true;m.textContent='Building\u2026';fetch('/api/dashboard',{method:'POST',headers:{'Content-Type':'application/json'},"
    "body:JSON.stringify({user:localStorage.getItem('sdlc-jira-me')||'',role:localStorage.getItem('sdlc-role-preview')||''})})"
    ".then(function(r){return r.json().then(function(j){if(!r.ok){throw new Error(j.error||r.statusText);}location=j.url+'?t='+Date.now();});})"
    ".catch(function(e){b.disabled=false;m.textContent='Could not build it: '+e.message;});};</script>")
DEFAULT_JIRA_USER = os.environ.get("SDLC_CONSOLE_JIRA_USER", "")
# Every roster person's dashboard is built from Jira each night and the Dashboard button opens that copy.
NIGHTLY_DIR = os.path.join(STATE_DIR, "dashboards")
NIGHTLY_AT = (21, 0)
NIGHTLY_TZ = "America/New_York"
NIGHTLY_TIMEOUT = 4 * 3600
GEN_VALIDATION = os.path.join(team.FRAMEWORK_DIR, "tools", "gen_validation_form.py")
VALIDATION_REGISTRY = team.KB + "/VALIDATION/KB_OPEN_QUESTIONS.yaml"
VALIDATION_DIR = os.path.join(STATE_DIR, "validation")
KB_BRANCH = team.KB_BRANCH
READ_REMOTE = os.environ.get("SDLC_WORKBENCH_READ_REMOTE", "1") != "0"
# the update check fetches the Workbench's own repo; it follows READ_REMOTE unless set on its own
UPDATE_FETCH = os.environ.get("SDLC_WORKBENCH_UPDATE_FETCH", "1" if READ_REMOTE else "0") != "0"
FETCH_EVERY_SECONDS = 120
REPO_FILE_TYPES = {".html": "text/html; charset=utf-8", ".md": "text/html; charset=utf-8",
                   ".yaml": "text/plain; charset=utf-8", ".txt": "text/plain; charset=utf-8",
                   ".csv": "text/plain; charset=utf-8"}

# Menu items that open a ready-made page instead of starting a Devin session: the same answer for everyone.
PAGE_FOR_SKILL = {"help": "/page/help", "catalogue": "/page/catalogue", "onboarding-guide": "/page/onboarding",
                  "presentation": "/page/presentation", "document-validation": "/validation",
                  "roster-check": "/page/roster", "team-insights": "/page/team-insights"}
TEAM_INSIGHTS_DECKS = team.KB + "/REPORTS/team-insights"
CLOSED_TAG = "closed"
ARCHIVED_TAG = "sdlc-archived"   # hidden in Argus, still resumable in Devin
DELETED_TAG = "sdlc-deleted"     # ended and removed from every Argus; never adopted again
PRESENTATION_PAGE = team.FRAMEWORK + "/ARCHITECTURE.html"
DELIVERY_TEAMS_PAGE = team.KB + "/SHARED/%s_DELIVERY_TEAMS.html" % team.PROJECT
BUILD_DISTRIBUTION = os.path.join(team.FRAMEWORK_DIR, "tools", "build_distribution.py")
SHARED_COPY_TAG = "shared-copy"
WRITE_TOOLS = {"write", "edit", "bash", "exec"}
REUSE_SECONDS = 24 * 3600
SHARED_ASSISTANT = os.environ.get("SDLC_SHARED_ASSISTANT", "1") != "0"
ASSISTANT_TAG = "workbench-assistant"
# Menu items that always get a session of their own: an SDLC run is tied to one ticket, and a resumed
# or locally running app keeps its session busy.
OWN_SESSION_SKILLS = {"sdlc", "resume-session", "run-app-locally"}
LONG_SESSION = int(os.environ.get("SDLC_LONG_SESSION", "40"))
REQUEST_RE = re.compile(r"^\[SDLC\] (request|reply) ([0-9a-f]{10})\s*$", re.M)
DEVIN_API = os.environ.get("DEVIN_API_BASE", "https://api.devin.ai").rstrip("/")
DEVIN_APP = os.environ.get("DEVIN_APP_BASE", team.DEVIN_APP).rstrip("/")
DEVIN_ORG = os.environ.get("DEVIN_ORG_ID", team.DEVIN_ORG)
REPO_SLUG = team.REPO_SLUG
PRODUCT = team.PRODUCT
WORKBENCH_TITLE = team.WORKBENCH_TITLE
WORKBENCH_SHORT = team.WORKBENCH_SHORT
PAGE_VALUES = {"PRODUCT": PRODUCT, "BRAND": team.BRAND, "WORKBENCH_BRAND": team.WORKBENCH_BRAND, "WORKBENCH_TITLE": WORKBENCH_TITLE,
               "PROJECT": PROJECT, "IT_TEAM": IT_TEAM, "DEVIN_APP": DEVIN_APP}

STAGES = ["intake", "research", "plan", "implement", "test", "release", "kb-refresh"]
STAGE_LABELS = {"intake": "Intake", "research": "Research", "plan": "Plan", "implement": "Implement",
                "test": "Test", "release": "Release", "kb-refresh": "KB refresh"}
STAGE_ALIASES = {"pr": "implement", "pr-readiness": "implement", "implementation": "implement", "planning": "plan",
                 "eval": "test", "testing": "test", "qa": "test", "kb": "kb-refresh", "kb refresh": "kb-refresh",
                 "kb_refresh": "kb-refresh", "knowledge": "kb-refresh"}
POLL_SECONDS = 5
IDLE_POLL_SECONDS = 30
SLEEP_POLL_SECONDS = 300
WATCHED_SECONDS = 20     # a page polled this run this recently: read it as if busy
REPLY_WAIT_SECONDS = 600  # after you send, read it as if busy until Devin answers
WORKBENCH_TAG = "sdlc-workbench"
CHAT_TAG = "workbench-chat"
LEGACY_TAG = "sdlc-console"
BUSY = ("new", "claimed", "working", "running", "resumed", "resume_requested", "resume_requested_frontend", "")
ENDED = ("exit", "error", "expired")

# Knowledge base menu: (skill, label, roles that see it or None for every role). Entries whose skill folder
# is missing are dropped.
KB_AUTHOR_ROLES = ("solution_lead", "manager")
KB_MAINTAINER_ROLES = ("solution_lead", "architect", "manager")
KB_LOOKUP, KB_UPKEEP = "Look things up", "Keep it current"
KB_ACTIONS = [
    ("investigate", "Ask a question", None, KB_LOOKUP),
    ("explain-capability", "Explain a capability", None, KB_LOOKUP),
    ("kb-refresh", "Refresh after a release", KB_MAINTAINER_ROLES, KB_UPKEEP),
    ("source-staleness-check", "Find drift", KB_MAINTAINER_ROLES, KB_UPKEEP),
    ("document-validation", "Settle open questions", KB_MAINTAINER_ROLES, KB_UPKEEP),
    ("app-discovery", "Generate new knowledge", KB_AUTHOR_ROLES, KB_UPKEEP),
]
NOT_IN_TOOLS = {"dashboard", "test-on-pc", "argus", "workbench", "console", "devin-window"}
KB_BLURB = {
    "investigate": "Ask anything about %s and get an answer with its sources: code, KB documents and past sessions" % PRODUCT,
    "explain-capability": "What a %s feature does, in plain English" % PRODUCT,
    "kb-refresh": "Brings the knowledge base up to date after a production release",
    "source-staleness-check": "Finds KB documents that no longer match the code",
    "document-validation": "Answer the questions the knowledge base can't settle from its own sources",
    "app-discovery": "Writes the first knowledge documents for one API or UI module",
}
MENU_TEXT = {
    "acme-auto-setup": ("Set up test automation", "Gets the automation repo, Python and the app ready on the Cloud machine"),
    "acme-auto-story": ("Automate a story", "Fills in the automation template, asks you at Gate 1, then writes and runs the tests"),
    "acme-auto-run": ("Run automated tests", "Runs a tag on the Cloud machine, one browser or several at once"),
    "acme-auto-fix": ("Triage test failures", "Finds why scenarios failed: fixes the test or drafts a defect"),
    "adr": ("Record an architecture decision (ADR)", "A short dated note of what we decided, why, and what we turned down"),
    "ask-question": ("Ask someone a question", "Sends your question to a named person as a Jira Question sub-task"),
    "compliance-view": ("See what touches HIPAA and HEDIS", "Which features handle protected health information or quality measures"),
    "app-diagrams": ("Draw module diagrams", "Architecture diagrams for one module"),
    "app-knowledge-refresh": ("Refresh database knowledge", "Finds stale database docs and rebuilds only those"),
    "app-ui-spec": ("Write a UI spec", "The UI specification for one front-end module"),
    "db-change-analysis": ("Check a database change", "What a database change affects, for one requirement"),
    "db-trd": ("Write the database TRD", "Database technical requirements"),
    "eval": ("Run the test stage", "Runs the tests, checks coverage and prepares QA sign-off"),
    "epics-from-roadmap": ("Create epics from a roadmap", "A PO roadmap sheet becomes epics, with the missing answers asked first"),
    "feasibility-check": ("Check if an idea is feasible", "A five-minute look at size and risk before a full intake"),
    "gate-review": ("Find manual work to automate", "Ranks the manual steps in our delivery that a tool could do"),
    "grooming-assistant": ("Get stories ready to estimate", "Works through the stories marked as needing grooming"),
    "help": ("What can I do here?", "Every command, grouped by role"),
    "impact-radar": ("What does a change affect?", "If I change this, what else breaks, across DB, API, UI and ETL"),
    "implement": ("Build a story", "Writes the code, tests it and raises the pull request"),
    "intake": ("Write up a requirement", "Turns a rough request into a spec with acceptance criteria"),
    "migration-status": ("Legacy migration status", "How far each capability has moved from %s to %s" % (
        team.and_join(team.LEGACY_SYSTEMS) or "the legacy systems", PRODUCT)),
    "onboarding-guide": ("Onboarding guide", "A learning guide for your role"),
    "pi-plan": ("Plan the program increment", "Sizes requirements and lays them across five sprints"),
    "plan": ("Plan a story", "Which files change, where, and in what order"),
    "po-story-review": ("Review stories as PO", "Checks every acceptance criterion has a story"),
    "pr-readiness": ("Check a PR is ready to merge", "Acceptance criteria, security, tests and description"),
    "loe": ("LOE estimate", "Size a requirement: epics, stories, points per layer, staffing and timeline (read only)"),
    "presentation": ("Show how it all fits together", "The architecture and flow diagrams"),
    "promote": ("Promote to the next environment", "Raises the PRs to move code from dev to SIT, UAT or prod"),
    "qa-scenarios": ("Write QA scenarios", "Behave scenarios from a story's acceptance criteria"),
    "release": ("Run the release stage", "Deployment and rollback plans, promotion and monitoring"),
    "release-notes": ("Write release notes", "An executive summary and a change log"),
    "roster-check": ("Check the team roster", "Finds people missing from the roster, or with the wrong role"),
    "security-audit": ("Run a security audit", "Secrets, SQL injection and PII checks on a file, story or PR"),
    "spec-vs-delivery": ("Check what was built against the spec", "Each acceptance criterion: covered, partly covered or not covered"),
    "sprint-close-check": ("Is the sprint ready to close?", "Stories and sub-tasks still missing time, labels, estimates or status"),
    "sprint-review-summary": ("Sum up the sprint", "A slide-ready summary for the sprint review"),
    "vacation": ("Vacation planner", "Everyone's time off and backups; add or change your own"),
    "story-splitter": ("Split a large story", "Breaks a story over 13 points into smaller ones"),
    "what-if": ("What if we change a rule?", "Who and what a business rule change would affect"),
    "approve": (
        "Approve a gate",
        "Approve or send back the gate waiting on you"
    ),
    "build-check": (
        "Build and test the components",
        "Install, lint, test and build the components the way their Dockerfiles do"
    ),
    "catalogue": (
        "Everything installed",
        "Every skill, playbook and agent, one line each"
    ),
    "product-roadmap": (
        "Rebuild the roadmap",
        "The year plan and the live sprint grid"
    ),
    "app-knowledge-sync": (
        "KB docs a PR made stale",
        "Which knowledge-base documents a code change needs updated"
    ),
    "app-run-pipeline": (
        "Document a UI or API module",
        "Runs the module documentation stages into a staging folder"
    ),
    "app-runtime-sync": (
        "KB staleness from git",
        "Which KB documents are older than the code they describe"
    ),
    "db-run-pipeline": (
        "Document the database",
        "Runs the database documentation stages for one Snowflake environment"
    ),
    "defects-by-specialty": (
        "Defects by specialty",
        "Open SIT and UAT defects by specialty and IT team"
    ),
    "demo-needed": (
        "Record DEMO-NEEDED demos",
        "A captioned demo per acceptance criterion for approved PRs"
    ),
    "etl-run-pipeline": (
        "Document an ETL repo",
        "Runs the ETL documentation stages into a staging folder"
    ),
    "export-jira": (
        "Export the backlog",
        "The Jira backlog file, after the PO and Tech Lead gates"
    ),
    "gate-timeout-check": (
        "Overdue approvals",
        "Gates waiting longer than their timeout, escalated once a day"
    ),
    "handover": (
        "Hand work over",
        "Give a session and its Jira items to a teammate"
    ),
    "identify-requester": (
        "Who am I here?",
        "Your roles, your defaults and your first commands"
    ),
    "jira-hygiene": (
        "Jira hygiene",
        "Tickets that do not follow the Jira rule book yet"
    ),
    "kb-build": (
        "Rebuild KB documents",
        "Rebuild knowledge-base documents side by side in a staging folder"
    ),
    "kb-compare": (
        "Compare a KB rebuild",
        "What a staged rebuild changes in the live knowledge base"
    ),
    "kb-context-build": (
        "Rebuild the domain context",
        "The team context file every documentation prompt reads"
    ),
    "learn-more": (
        "Learn about who you serve",
        "Answer the questions Devin has for you"
    ),
    "research": (
        "Research a requirement",
        "Gap analysis, stories, estimates and the Jira backlog"
    ),
    "resume-session": (
        "Resume a session",
        "Pick up an SDLC session where it stopped"
    ),
    "run-app-locally": (
        "Run the app locally",
        "The SDLC API and front end running in a Devin session, with the preview links"
    ),
    "roster-sync": (
        "Sync the roster",
        "people.yaml against the Confluence roster page"
    ),
    "sdlc": (
        "Start SDLC with every gate",
        "From a requirement to release, with every gate"
    ),
    "send-approval": (
        "Ask someone to approve",
        "Send a gate, or some of its items, to a named person"
    ),
    "source-staleness-check": (
        "KB drift against the code",
        "Which KB documents no longer match the source code"
    ),
    "start": (
        "Ask Devin Cloud anything",
        "Say what you need; Devin routes it"
    ),
    "status": (
        "Where is my requirement?",
        "Where it is, what is next and who acts"
    ),
    "status-report": (
        "Monthly status report",
        "The program or area status report from Jira"
    ),
    "team-insights": (
        "Team Insights",
        "How the team used Devin this month, what to teach and what to change"
    ),
}

SDLC_RE = re.compile(
    r"^\s*\[SDLC\]\s+(?P<kind>stage|step|agent|skill|playbook|question round|gate|artefact|artifact|diff|pr|note"
    r"|route|kb|rule|chain|ontology|graph|drift|sync|qa|evidence|tests|contract|decision)"
    r"\s+(?P<name>.*?)\s*(?:\s[—–:]\s|\s-{1,2}\s|:\s)\s*(?P<detail>.*)$",
    re.IGNORECASE,
)
NUMBERED_RE = re.compile(r"^\s*(\d+)[.)]\s+(.*\S)\s*$")
GATE_RE = re.compile(r"\b(SDLC_\d{2}[A-Za-z]?(?:_[A-Z_]+)?)\b")
FENCE_RE = re.compile(r"```(\w+)?\n(.*?)```", re.S)


def _ctx():
    return ssl._create_unverified_context()


def http_json(method, url, headers=None, body=None, timeout=60, settings=None):
    data = json.dumps(body).encode() if body is not None else None
    hdrs = {"Accept": "application/json"}
    if data is not None:
        hdrs["Content-Type"] = "application/json"
    hdrs.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, context=_ctx(), timeout=timeout) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError:
        raise
    except urllib.error.URLError as exc:
        host = urllib.parse.urlsplit(url).hostname
        if host in LOCAL_HOSTS:
            raise ApiError(502, local_unreachable(url, exc.reason, settings))
        raise ApiError(502, "Cannot reach %s from this box (%s). If the console runs on a Devin Cloud VM, "
                            "the host must be on the session's network allowlist." % (host, exc.reason))


LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")
# The settings that can point an outside system at this machine; the first whose address matches is named.
JIRA_URL_SETTINGS = (("SDLC_JIRA_BASE", "Jira"), ("SDLC_SANDBOX_URL", "Jira and Confluence (the sandbox)"))
DEVIN_URL_SETTINGS = (("DEVIN_API_BASE", "the Devin API"),)
LOCAL_URL_SETTINGS = JIRA_URL_SETTINGS + DEVIN_URL_SETTINGS


def local_unreachable(url, reason, settings=None):
    """Why a call to this machine failed, naming the setting of the system that made the call."""
    parts = urllib.parse.urlsplit(url)
    where = "%s://%s" % (parts.scheme, parts.netloc)
    for var, what in settings or LOCAL_URL_SETTINGS:
        if (os.environ.get(var) or "").rstrip("/").startswith(where):
            return ("Nothing answers at %s (%s). %s is set to %s, so %s is read there. Start that server, or "
                    "change %s to the right address and start Argus again." % (
                        where, reason, var, os.environ[var], what, var))
    return "Nothing answers at %s (%s). No Argus setting points there; check the address in the profile." % (
        where, reason)


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class Health:
    """What Argus last saw of each outside system. Configured means a setting or key is there;
    connected means the last call to the system worked."""

    def __init__(self):
        self.seen, self.lock = {}, threading.Lock()
        self.on_fail = None

    def ok(self, name):
        with self.lock:
            self.seen[name] = {"ok": True, "at": time.time(), "error": ""}

    def fail(self, name, error):
        with self.lock:
            self.seen[name] = {"ok": False, "at": time.time(), "error": str(error)[:400]}
        if self.on_fail:
            self.on_fail(name, error)

    def wait(self, name, note):
        """The system is coming back by itself (the bridge loop restarts after a message): not an error yet."""
        with self.lock:
            self.seen[name] = {"ok": False, "waiting": True, "at": time.time(), "error": str(note)[:400]}

    def forget(self, name):
        with self.lock:
            self.seen.pop(name, None)

    def record(self, name, exc):
        """An HTTP answer still proves the system is reachable, unless it refused the key or failed itself."""
        if isinstance(exc, urllib.error.HTTPError) and exc.code not in (401, 403) and exc.code < 500:
            self.ok(name)
        else:
            self.fail(name, exc)

    def report(self, name, configured, via=""):
        with self.lock:
            seen = dict(self.seen.get(name) or {})
        state = ("not_configured" if not configured else "not_checked" if not seen
                 else "connected" if seen["ok"] else "reconnecting" if seen.get("waiting") else "failing")
        return {"configured": bool(configured), "connected": state == "connected", "state": state,
                "checked_at": seen.get("at"), "error": seen.get("error", ""), "via": via}


HEALTH = Health()
OBSERVER = observer.Observer(os.path.join(STATE_DIR, "observer"))
HEALTH.on_fail = lambda name, error: OBSERVER.note(name, error)
STUCK_SECONDS = int(os.environ.get("SDLC_STUCK_MINUTES", "30")) * 60
WAKE_REPEAT = 3  # Wake this many times on one run within WAKE_WINDOW is a problem worth noting
WAKE_WINDOW = 900
FEEDBACK_SEND_HOURS = float(os.environ.get("SDLC_FEEDBACK_SEND_HOURS", "24"))


# --------------------------------------------------------------------------- Jira

STORY_PAGE = 100
STORY_READ_CAP = 1000
JIRA_READ_TIMEOUT = 120
JIRA_TRIES = 2
JIRA_RETRY_PAUSE = 2


class Jira:
    def __init__(self):
        self.token = os.environ.get(JIRA_TOKEN_ENV)
        self.validated = False
        self.dead = None

    def get(self, path, **params):
        if not self.token:
            raise ApiError(503, "%s is not set on this box" % JIRA_TOKEN_ENV)
        if self.dead:
            raise ApiError(503, self.dead)
        if not self.validated:
            self._call("/api/2/myself")
            self.validated = True
        return self._call(path, **params)

    def recheck(self):
        """Check now: one /myself call. A good answer turns Jira back on after an earlier 401/403; Argus never
        retries a refusal by itself, so the service account is not locked out."""
        self._call("/api/2/myself")
        self.dead, self.validated = None, True

    def _call(self, path, **params):
        url = JIRA + path + (("&" if "?" in path else "?") + urllib.parse.urlencode(params) if params else "")
        try:
            out = self._get_retrying(url)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                self.dead = "Jira returned %d for the service account; not retrying (token may be locked)." % exc.code
                HEALTH.fail("jira", self.dead)
                raise ApiError(503, self.dead)
            HEALTH.record("jira", exc if exc.code < 500 else "Jira %d on %s" % (exc.code, path))
            raise ApiError(exc.code, "Jira %d on %s" % (exc.code, path))
        except ApiError as exc:
            HEALTH.fail("jira", exc)
            raise
        except OSError as exc:
            err = "Jira could not be reached (%s: %s)" % (type(exc).__name__, exc)
            HEALTH.fail("jira", err)
            raise ApiError(503, err)
        HEALTH.ok("jira")
        return out

    def _get_retrying(self, url):
        """One GET, tried again once when Jira was slow or the connection dropped. A refused key
        (401/403) or any other HTTP answer is not retried."""
        for attempt in range(JIRA_TRIES):
            try:
                return http_json("GET", url, {"Authorization": "Bearer " + self.token}, timeout=JIRA_READ_TIMEOUT,
                                 settings=JIRA_URL_SETTINGS)
            except urllib.error.HTTPError:
                raise
            except (ApiError, OSError) as exc:
                if attempt + 1 >= JIRA_TRIES or (isinstance(exc, ApiError) and exc.status != 502):
                    raise
                time.sleep(JIRA_RETRY_PAUSE)

    def stories(self, scope, jira_user="", with_description=False):
        if scope in PERSONAL_SCOPES:
            if not re.match(r"^[A-Za-z0-9._-]+$", jira_user or ""):
                raise ApiError(400, "Pick who you are (top right) to list the tickets assigned to you.")
            jql = JQL[scope] % jira_user
        else:
            jql = JQL.get(scope, JQL["sprint"])
        fields = STORY_FIELDS + (",description,fixVersions,%s" % F_ACCEPTANCE if with_description else "")
        issues, total = self._search_all(jql, fields)
        out = []
        for issue in issues:
            f = issue["fields"]
            sprint = f.get(F_SPRINT) or []
            sprint_name = ""
            if sprint:
                last = sprint[-1]
                if isinstance(last, dict):
                    sprint_name = last.get("name", "")
                else:
                    m = re.search(r"name=([^,\]]+)", str(last))
                    sprint_name = m.group(1) if m else ""
            out.append({
                "key": issue["key"],
                "summary": f.get("summary", ""),
                "status": (f.get("status") or {}).get("name", ""),
                "type": (f.get("issuetype") or {}).get("name", ""),
                "assignee": (f.get("assignee") or {}).get("displayName", "Unassigned"),
                "reporter": (f.get("reporter") or {}).get("displayName", ""),
                "priority": (f.get("priority") or {}).get("name", ""),
                "points": f.get(F_POINTS) or "",
                "sprint": sprint_name,
                "labels": f.get("labels") or [],
                "parent": (f.get("parent") or {}).get("key", "") or (f.get(F_EPIC_LINK) or "" if F_EPIC_LINK else ""),
                "updated": f.get("updated", ""),
                "url": JIRA_BROWSE + issue["key"],
            })
            if with_description:
                ac = f.get(F_ACCEPTANCE) or ""
                out[-1].update(description=f.get("description") or "",
                               acceptance=ac if isinstance(ac, str) else str(ac.get("value", "") if isinstance(ac, dict) else ac),
                               releases=[{"name": v.get("name", ""), "date": v.get("releaseDate", "")}
                                         for v in f.get("fixVersions") or []])
        return {"jql": jql, "stories": out, "total": total, "truncated": total > len(out)}

    def _search_all(self, jql, fields):
        """Pages /api/2/search with startAt until Jira's total is read, capped at STORY_READ_CAP."""
        issues, total = [], 0
        while len(issues) < STORY_READ_CAP:
            data = self.get("/api/2/search", jql=jql, fields=fields, startAt=len(issues),
                            maxResults=min(STORY_PAGE, STORY_READ_CAP - len(issues)))
            page = data.get("issues", [])
            total = data.get("total", len(issues) + len(page))
            issues.extend(page)
            if not page or len(issues) >= total:
                break
        return issues, total

    def story(self, key):
        f = self.get("/api/2/issue/" + key, fields="summary,description,status,assignee,reporter,labels,priority," + F_POINTS).get("fields", {})
        return {
            "key": key, "summary": f.get("summary", ""), "description": f.get("description") or "",
            "status": (f.get("status") or {}).get("name", ""), "assignee": (f.get("assignee") or {}).get("displayName", ""),
            "reporter": (f.get("reporter") or {}).get("displayName", ""), "labels": f.get("labels") or [],
            "points": f.get(F_POINTS) or "", "url": JIRA_BROWSE + key,
        }

    def post(self, path, payload):
        return self.request("POST", path, payload)

    def request(self, method, path, payload=None):
        """A Jira write (POST/PUT). Only the Backlog tab calls this with anything but POST, and only
        when backlog writes are switched on for an allow-listed ticket."""
        if not self.token:
            raise ApiError(503, "%s is not set on this box" % JIRA_TOKEN_ENV)
        if self.dead:
            raise ApiError(503, self.dead)
        try:
            return http_json(method, JIRA + path, {"Authorization": "Bearer " + self.token}, payload, timeout=120)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                self.dead = "Jira returned %d for the service account; not retrying (token may be locked)." % exc.code
                raise ApiError(503, self.dead)
            detail = exc.read().decode(errors="replace")[:600]
            raise ApiError(exc.code, "Jira %d on %s: %s" % (exc.code, path, detail))

    def create_story(self, summary, description, acceptance, assignee, labels):
        fields = {
            "project": {"key": PROJECT},
            "issuetype": {"name": "Story"},
            "summary": summary[:250],
            "description": description,
            F_ACCEPTANCE: acceptance,
            F_IT_TEAM: [{"value": IT_TEAM}],
            "labels": labels,
        }
        if assignee:
            fields["assignee"] = {"name": assignee}
        result = self.post("/api/2/issue", {"fields": fields})
        key = (result or {}).get("key")
        if not key:
            raise ApiError(502, "Jira did not return a created issue key")
        return key


def _lines(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read().splitlines()
    except OSError:
        return []


def _scalar(v):
    v = v.split(" #", 1)[0].strip().strip("'\"")
    return "" if v in ("null", "~") else v


def _flow_list(v):
    v = v.split(" #", 1)[0].strip()
    if not (v.startswith("[") and v.endswith("]")):
        return None
    return [x.strip().strip("'\"") for x in v[1:-1].split(",") if x.strip()]


def load_roster():
    """people.yaml → one dict per person (jira_user, name, email, devin_user_id, primary_role, roles, secondary_roles)."""
    out, cur, listkey = [], None, None
    for line in _lines(PEOPLE_PATH):
        m = re.match(r"^- jira_user:\s*(.*)$", line)
        if m:
            cur = {"jira_user": _scalar(m.group(1)), "name": "", "email": "", "devin_user_id": "",
                   "primary_role": "", "roles": [], "secondary_roles": []}
            out.append(cur)
            listkey = None
            continue
        if cur is None:
            continue
        if re.match(r"^[A-Za-z]", line):
            cur = None
            continue
        m = re.match(r"^  ([a-z_]+):\s*(.*)$", line)
        if m:
            key, val = m.group(1), m.group(2)
            flow = _flow_list(val)
            if key in ("roles", "secondary_roles"):
                cur[key] = flow or []
                listkey = key if flow is None and not val.strip() else None
            elif key in ("name", "email", "devin_user_id", "primary_role"):
                cur[key] = _scalar(val)
                listkey = None
            else:
                listkey = None
            continue
        m = re.match(r"^  - (\S.*)$", line)
        if m and listkey:
            cur[listkey].append(_scalar(m.group(1)))
    for p in out:
        p["name"] = p["name"] or p["jira_user"]
    return out


def team_board():
    """The Jira Agile board the team plans on: dashboard-roles.yaml team.board."""
    try:
        with open(os.path.join(ROOT, ".devin", "rules", "dashboard-roles.yaml"), encoding="utf-8") as fh:
            m = re.search(r"(?m)^team:\n(?:  .*\n)*?  board:\s*(\S+)", fh.read())
        return m.group(1).strip("'\"") if m else ""
    except OSError:
        return ""


TEAM_SESSION_DAYS = 7


def team_activity_audience(lens):
    """Roles that see the team_activity panel on this lens (an empty set means everyone on the lens), or None
    when the lens has no such panel: read from dashboard-roles.yaml."""
    try:
        with open(os.path.join(ROOT, ".devin", "rules", "dashboard-roles.yaml"), encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return None
    m = re.search(r"(?m)^  %s:\n(?:    .*\n)*?    panels:\s*\[([^\]]*)\]" % re.escape(lens or ""), text)
    if not m or "team_activity" not in [x.strip() for x in m.group(1).split(",")]:
        return None
    m = re.search(r"(?m)^  team_activity:\n(?:    .*\n)*?    audience:\s*\[([^\]]*)\]", text)
    return {x.strip().strip("'\"") for x in m.group(1).split(",") if x.strip()} if m else set()


def load_people():
    """jira_user + name per person, for the assignee and forward pickers."""
    return sorted(({"jira_user": p["jira_user"], "name": p["name"]} for p in load_roster() if p["jira_user"]),
                  key=lambda p: p["name"].lower())


def find_person(who, roster=None):
    """Match a Jira username, e-mail or Devin user id to a roster entry (case-insensitive)."""
    who = (who or "").strip().lower()
    if not who:
        return None
    for p in roster if roster is not None else load_roster():
        if who in (p["jira_user"].lower(), p["email"].lower(), p["devin_user_id"].lower()):
            return p
    return None


def load_roles():
    """role-routing.yaml `roles:` → {role_id: {label, dashboard_lens, gate_roles, default_skills, more_skills,
    everyone_skills}}; everyone_skills is the top-level list, given to every role."""
    roles, cur, inside, everyone = {}, None, False, []
    for line in _lines(ROUTING_PATH):
        m = re.match(r"^everyone_skills:\s*(.*)$", line)
        if m:
            everyone = _flow_list(m.group(1)) or []
            continue
        if re.match(r"^roles:\s*$", line):
            inside = True
            continue
        if not inside:
            continue
        if re.match(r"^[A-Za-z]", line):
            break
        m = re.match(r"^  ([a-z_]+):\s*$", line)
        if m:
            cur = roles.setdefault(m.group(1), {"label": m.group(1), "dashboard_lens": "", "gate_roles": [],
                                                "default_skills": [], "more_skills": []})
            continue
        m = re.match(r"^    (label|dashboard_lens|gate_roles|default_skills|more_skills):\s*(.*)$", line)
        if m and cur is not None:
            flow = _flow_list(m.group(2))
            cur[m.group(1)] = flow if flow is not None else _scalar(m.group(2))
    for role in roles.values():
        role["everyone_skills"] = list(everyone)
    return roles


LAYOUT_DEFAULT = {"list": "mine_sprint", "left": "open", "right": "open", "right_width": 420}
LAYOUT_SIDES = ("open", "rail", "auto")
LAYOUT_LISTS = ("mine_sprint", "mine", "sprint", "open", "qa", "uat", "automation", "automation_open")


def load_layouts():
    """role-routing.yaml `workbench_layouts:` → {lens: {list, left, right, right_width}}, bad values dropped."""
    layouts, cur, inside = {}, None, False
    for line in _lines(ROUTING_PATH):
        if re.match(r"^workbench_layouts:\s*$", line):
            inside = True
            continue
        if not inside:
            continue
        if re.match(r"^[A-Za-z#]", line):
            break
        m = re.match(r"^  ([a-z_]+):\s*$", line)
        if m:
            cur = layouts.setdefault(m.group(1), dict(LAYOUT_DEFAULT))
            continue
        m = re.match(r"^    (list|left|right|right_width):\s*(.*)$", line)
        if m and cur is not None:
            key, val = m.group(1), _scalar(m.group(2))
            if key == "right_width":
                if re.match(r"^\d{3}$", val) and 280 <= int(val) <= 640:
                    cur[key] = int(val)
            elif val in (LAYOUT_LISTS if key == "list" else LAYOUT_SIDES[:2] if key == "left" else LAYOUT_SIDES):
                cur[key] = val
    return layouts


def skill_info(name):
    """Name, one-line blurb and command for a skill folder, or None when .devin/skills/<name> has no SKILL.md."""
    if not re.match(r"^[a-z0-9][a-z0-9-]*$", name or ""):
        return None
    lines = _lines(os.path.join(SKILLS_DIR, name, "SKILL.md"))
    if not lines:
        return None
    desc, grab = [], False
    for line in lines[1:]:
        if line.strip() == "---":
            break
        m = re.match(r"^description:\s*(.*)$", line)
        if m:
            grab = True
            if m.group(1).strip() not in (">", "|", ">-", "|-"):
                desc.append(m.group(1).strip().strip("'\""))
            continue
        if grab:
            if re.match(r"^\S", line):
                break
            desc.append(line.strip())
    text = " ".join(desc).strip().strip("'\"").strip()
    first = re.split(r"(?<=[.!?])\s", text, 1)[0] if text else ""
    hint, tools, in_tools = "", [], False
    for line in lines[1:]:
        if line.strip() == "---":
            break
        m = re.match(r"^argument-hint:\s*(.*)$", line)
        if m:
            hint = m.group(1).strip().strip("'\"")
        m = re.match(r"^allowed-tools:\s*(.*)$", line)
        if m:
            in_tools = True
            tools += [t.strip() for t in m.group(1).strip("[] ").split(",") if t.strip()]
            continue
        if in_tools:
            m = re.match(r"^\s+-\s*(\S+)", line)
            if m:
                tools.append(m.group(1))
            elif re.match(r"^\S", line):
                in_tools = False
    return {"skill": name, "command": "/" + name, "label": skill_label(name), "blurb": first[:200],
            "input": skill_input(hint), "opens": PAGE_FOR_SKILL.get(name, ""),
            "read_only": bool(tools) and not WRITE_TOOLS.intersection(tools)}


def skill_input(hint):
    """What a skill asks for, from its argument-hint: `<...>` must be given, `[...]` may be left out.

    A bracket that lists single words separated by `|` becomes a set of choices, e.g.
    "[optional: architecture | sdlc | all]" or "<role: BSA | PO | developer>".
    """
    hint = (hint or "").strip()
    if not hint:
        return {"required": False, "hint": "", "choices": []}
    m = re.match(r"^[<\[]([^>\]]*)[>\]]", hint)
    inner = m.group(1) if m else hint
    listed = inner.split(":", 1)[1] if ":" in inner else inner
    choices = []
    if "|" in listed:
        parts = [re.sub(r"\(.*?\)", "", p).strip() for p in listed.split("|")]
        if all(re.match(r"^[A-Za-z][\w-]*$", p) for p in parts):
            choices = parts
    return {"required": hint.startswith("<"), "hint": hint, "choices": choices}


ACRONYMS = {"pr", "kb", "bsa", "ui", "pi", "db", "po", "trd", "brd", "acme", "uat", "qa"}


def skill_label(name):
    words = name.split("-")
    return " ".join(w.upper() if w in ACRONYMS else (w.capitalize() if i == 0 else w) for i, w in enumerate(words))


def load_business(path=None):
    """business-screens.json: the 'What I do' groups of the PO, BSA and Scrum Master lenses."""
    try:
        with open(path or BUSINESS_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def business_tasks(lens, data=None):
    """[{group, tasks}] for a lens, each skill task carrying what the page needs to start it; [] for other lenses."""
    data = load_business() if data is None else data
    out = []
    for group in (data.get("lenses") or {}).get(lens) or []:
        tasks = []
        for task in group.get("tasks") or []:
            task = dict(task)
            if task.get("skill"):
                info = skill_info(task["skill"])
                if not info:
                    continue
                task["action"] = dict(info, label=task.get("label", info["label"]), blurb=task.get("what", info["blurb"]))
            if task.get("more"):
                info = skill_info(task["more"])
                if info:
                    task["more_action"] = info
            tasks.append(task)
        if tasks:
            out.append({"group": group.get("group", ""), "tasks": tasks})
    return out


def merge_tasks(lists):
    """One 'What I do' list for someone with several business hats: groups by name, each task once."""
    out, seen = [], set()
    for groups in lists:
        for group in groups:
            new = [t for t in group["tasks"] if t["id"] not in seen]
            seen.update(t["id"] for t in new)
            if not new:
                continue
            same = next((g for g in out if g["group"] == group["group"]), None)
            if same:
                same["tasks"].extend(new)
            else:
                out.append({"group": group["group"], "tasks": list(new)})
    return out


def role_view(role_id, roles=None, layouts=None):
    """What Argus shows for one role: its label, dashboard lens, screen layout and menu entries."""
    roles = roles if roles is not None else load_roles()
    layouts = layouts if layouts is not None else load_layouts()
    role = roles.get(role_id) or {}
    in_kb_menu = {a[0] for a in KB_ACTIONS}
    tools = []
    seen = set()
    for name in (role.get("default_skills") or []) + (role.get("more_skills") or []) + (role.get("everyone_skills") or []):
        if name in seen:
            continue
        seen.add(name)
        info = skill_info(name)
        if info and name not in NOT_IN_TOOLS and name not in in_kb_menu:
            label, blurb = MENU_TEXT.get(name, (info["label"], info["blurb"]))
            tools.append(dict(info, label=label, blurb=blurb))
    kb = []
    for name, label, only, group in KB_ACTIONS:
        info = skill_info(name)
        if info and (only is None or role_id in only):
            kb.append(dict(info, label=label, group=group, blurb=KB_BLURB.get(name, info["blurb"])))
    tasks = business_tasks(role.get("dashboard_lens", ""))
    return {"id": role_id, "label": role.get("label", role_id), "lens": role.get("dashboard_lens", ""),
            "hat_ids": [role_id], "lenses": [role.get("dashboard_lens", "")],
            "gate_roles": role.get("gate_roles") or [], "business": bool(tasks), "delivery": not tasks, "tasks": tasks,
            "layout": dict(layouts.get(role.get("dashboard_lens", ""), LAYOUT_DEFAULT)),
            "menus": [{"id": "tools", "label": "My tools", "items": tools},
                      {"id": "kb", "label": "Knowledge base", "items": kb}]}


def all_hats_view(views):
    """Someone with several hats sees every hat's buttons: the first hat's view plus the others' menu items,
    gates, lenses and What I do tasks, each once."""
    out = dict(views[0], menus=[dict(m, items=list(m["items"])) for m in views[0]["menus"]])
    for v in views[1:]:
        for key in ("hat_ids", "lenses", "gate_roles"):
            out[key] = out[key] + [x for x in v[key] if x not in out[key]]
        for mine, theirs in zip(out["menus"], v["menus"]):
            have = {i["skill"] for i in mine["items"]}
            mine["items"] += [i for i in theirs["items"] if i["skill"] not in have]
    kb_order = [a[0] for a in KB_ACTIONS]
    out["menus"][1]["items"].sort(key=lambda i: kb_order.index(i["skill"]) if i["skill"] in kb_order else len(kb_order))
    out["tasks"] = merge_tasks(v["tasks"] for v in views if v["tasks"])
    out["business"] = bool(out["tasks"])
    out["delivery"] = any(v["delivery"] for v in views)
    return out


def load_gates():
    """approval-gates.yaml → {gate_id: {name, stage, required_role, timeout_hours, approval_criteria, artifacts_to_review}}."""
    gates, cur, listkey = {}, None, None
    for line in _lines(GATES_PATH):
        m = re.match(r"^  - id:\s*(\S+)", line)
        if m:
            cur = gates.setdefault(_scalar(m.group(1)), {"id": _scalar(m.group(1)), "name": "", "stage": "",
                                                         "required_role": "", "timeout_hours": "",
                                                         "approval_criteria": [], "artifacts_to_review": []})
            listkey = None
            continue
        if cur is None:
            continue
        m = re.match(r"^    ([a-z_]+):\s*(.*)$", line)
        if m:
            key, val = m.group(1), m.group(2)
            listkey = key if key in ("approval_criteria", "artifacts_to_review") and not val.strip() else None
            if key in ("name", "stage", "required_role", "timeout_hours"):
                cur[key] = _scalar(val)
            continue
        m = re.match(r"^      - (\S.*)$", line)
        if m and listkey:
            cur[listkey].append(_scalar(m.group(1)))
        elif re.match(r"^\S", line):
            cur, listkey = None, None
    return gates


def gate_info(gate_id, gates=None):
    """The gate definition for an ID as Devin printed it (full ID or the SDLC_nn prefix)."""
    gates = gates if gates is not None else load_gates()
    if gate_id in gates:
        return gates[gate_id]
    for gid, g in gates.items():
        if gate_id and (gid.startswith(gate_id + "_") or gate_id.startswith(gid)):
            return g
    return None


# --------------------------------------------------------------------------- Devin

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def saved_devin_key():
    try:
        return pctest.load_key()
    except (OSError, AttributeError, ValueError):
        return ""


class Devin:
    def __init__(self):
        self.key = os.environ.get("DEVIN_API_KEY") or saved_devin_key()

    def _headers(self):
        if not self.key:
            raise ApiError(503, "No Devin API key yet. Add it once under Test on my PC (top bar), or set DEVIN_API_KEY.")
        return {"Authorization": "Bearer " + self.key}

    def _url(self, path):
        return "%s/v1%s" % (DEVIN_API, path)

    def _do(self, method, path, body=None):
        headers = self._headers()
        try:
            out = http_json(method, self._url(path), headers, body, settings=DEVIN_URL_SETTINGS)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:400]
            err = ApiError(exc.code, "Devin API %d on %s: %s" % (exc.code, path, detail))
            HEALTH.record("devin", exc if exc.code not in (401, 403) and exc.code < 500 else err)
            raise err
        except ApiError as exc:
            HEALTH.fail("devin", exc)
            raise
        HEALTH.ok("devin")
        return out

    def create_session(self, prompt, title, tags):
        return self._do("POST", "/sessions", {"prompt": prompt, "title": title, "tags": tags})

    def session(self, devin_id):
        info = self._do("GET", "/sessions/" + devin_id) or {}
        info.setdefault("url", "%s/sessions/%s" % (DEVIN_APP, devin_id.replace("devin-", "")))
        return info

    @staticmethod
    def messages(info):
        """v1 returns the transcript inline; normalise to event_id/created_at/source/message."""
        out = []
        for m in info.get("messages") or []:
            out.append({
                "event_id": m.get("event_id"),
                "created_at": m.get("timestamp"),
                "source": "devin" if m.get("type") == "devin_message" else "user",
                "message": m.get("message", ""),
            })
        return out

    def send(self, devin_id, text):
        return self._do("POST", "/sessions/%s/message" % devin_id, {"message": text})

    def list_sessions(self, tag, limit=50):
        query = urllib.parse.urlencode({"tags": tag, "limit": limit})
        return (self._do("GET", "/sessions?" + query) or {}).get("sessions") or []

    def sessions_of(self, email, limit=100):
        query = urllib.parse.urlencode({"user_email": email, "limit": limit})
        return (self._do("GET", "/sessions?" + query) or {}).get("sessions") or []

    def team_sessions(self, people, since):
        """Sessions of these roster people updated since `since` (unix seconds), each with its owner's user_id."""
        out = []
        for person in people:
            if not person.get("email"):
                continue
            for s in self.sessions_of(person["email"]):
                if iso_epoch(s.get("updated_at") or 0) >= since:
                    out.append(dict(s, user_id=s.get("user_id") or person.get("devin_user_id") or person["email"]))
        return out

    def terminate(self, devin_id):
        return self._do("DELETE", "/sessions/" + devin_id)

    def set_tags(self, devin_id, tags):
        return self._do("PUT", "/sessions/%s/tags" % devin_id, {"tags": tags})

    def upload(self, path, name):
        boundary = uuid.uuid4().hex
        with open(path, "rb") as fh:
            data = fh.read()
        body = (("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"%s\"\r\n"
                 "Content-Type: application/octet-stream\r\n\r\n") % (boundary, name)).encode() + data + (
                    "\r\n--%s--\r\n" % boundary).encode()
        headers = dict(self._headers(), **{"Content-Type": "multipart/form-data; boundary=" + boundary,
                                           "Accept": "application/json"})
        req = urllib.request.Request(self._url("/attachments"), data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, context=_ctx(), timeout=120) as resp:
                url = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            raise ApiError(exc.code, "Devin API %d on /attachments: %s" % (
                exc.code, exc.read().decode(errors="replace")[:400]))
        except urllib.error.URLError as exc:
            raise ApiError(502, "Cannot reach %s (%s)" % (DEVIN_API, exc.reason))
        if isinstance(url, dict):
            url = url.get("url", "")
        return url

    def download(self, attachment_id, name):
        """The file's bytes. The API answers with a redirect to a short-lived presigned URL, which is
        fetched without the Devin key."""
        path = "/attachments/%s/%s" % (attachment_id, urllib.parse.quote(name, safe=""))
        opener = urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=_ctx()))
        req = urllib.request.Request(self._url(path), headers=self._headers())
        try:
            with opener.open(req, timeout=60) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            where = exc.headers.get("Location") if exc.code in (301, 302, 303, 307, 308) else None
            if not where:
                raise ApiError(exc.code, "Devin API %d on %s" % (exc.code, path))
        except urllib.error.URLError as exc:
            raise ApiError(502, "Cannot reach %s (%s)" % (DEVIN_API, exc.reason))
        try:
            with urllib.request.urlopen(where, context=_ctx(), timeout=120) as resp:
                return resp.read()
        except (urllib.error.URLError, OSError) as exc:
            raise ApiError(502, "Could not download %s: %s" % (name, exc))



SAVED_BLOCKS = {
    "SDLC-DASHBOARD-SKILL-CONFIG": ("dashboard", "Skill config change"),
    "SDLC-DASHBOARD-ROLE-CONFIG": ("dashboard", "Role config change"),
    "SDLC-DASHBOARD-GATE-CONFIG": ("dashboard", "Gate config change"),
    "SDLC-DASHBOARD-WORKBENCH-CONFIG": ("dashboard", "Argus config change"),
    "SDLC-DASHBOARD-ANSWERS": ("dashboard", "Answers to questions"),
    "SDLC-DASHBOARD-DELEGATIONS": ("dashboard", "Question handovers"),
    "SDLC-DASHBOARD-OBSERVATIONS": ("dashboard", "Observations"),
    "SDLC-DASHBOARD-APPROVALS": ("send-approval", "Approvals"),
    "SDLC-DASHBOARD-SESSION-HANDOVERS": ("handover", "Session handovers"),
    "SDLC-DASHBOARD-SESSION-CLOSE": ("dashboard", "Close sessions"),
    "SDLC-DASHBOARD-BACKLOG": ("dashboard", "Backlog change"),
    "SDLC-INTAKE-ANSWERS": ("intake", "Intake answers"),
    observer.BLOCK: ("dashboard", "Argus feedback"),
}
REPO_BLOCKS = {
    "SDLC-DASHBOARD-SKILL-CONFIG": ".devin/rules/role-routing.yaml",
    "SDLC-DASHBOARD-ROLE-CONFIG": ".devin/rules/people.yaml",
    "SDLC-DASHBOARD-GATE-CONFIG": ".devin/rules/approval-gates.yaml",
    "SDLC-DASHBOARD-WORKBENCH-CONFIG": ".devin/rules/workbench-settings.yaml",
}
SAVE_BRANCH = os.environ.get("SDLC_SAVE_BRANCH") or team.KB_BRANCH


def saved_block_kind(block):
    """The block's marker when Save may take it (first non-blank line, `# ` allowed), else ''."""
    first = next((ln.strip().lstrip("#").strip() for ln in (block or "").splitlines() if ln.strip()), "")
    kind = first.split(" v")[0].strip()
    return kind if kind in SAVED_BLOCKS and len(block) <= 200000 else ""


SAVE_APPROVES_ROLES = ("solution_lead",)  # the roles whose dashboard lens is the Tech Lead one


def save_is_approval(person, kind, dry_run):
    """A tech lead's real (not dry-run) Save on a config tab is their approval: the run raises the PR at once."""
    hats = [person.get("primary_role", "")] + list(person.get("secondary_roles") or []) if person else []
    return kind in REPO_BLOCKS and not dry_run and any(h in SAVE_APPROVES_ROLES for h in hats)


def save_prompt(kind, block, requester, approved=False):
    """What the run is told to do with a saved block: the same steps as when it is pasted into chat."""
    if kind in REPO_BLOCKS and approved:
        how = ("This change edits %s. The requester is a tech lead and pressing Save is their approval, so do not "
               "wait for `approved`. Run the apply tool named in .devin/skills/dashboard/SKILL.md for this block "
               "without --write and show the preview, then run it with --write straight away, commit only that file "
               "on a new devin/ branch from origin/%s and raise a pull request into %s for the reviewers that file "
               "names. The pull request is still reviewed and merged in Bitbucket. Never push to %s directly."
               % (REPO_BLOCKS[kind], SAVE_BRANCH, SAVE_BRANCH, SAVE_BRANCH))
    elif kind in REPO_BLOCKS:
        how = ("This change edits %s. Run the apply tool named in .devin/skills/dashboard/SKILL.md for this block "
               "without --write and show the preview. Wait for the requester's `approved`. Then run it with --write, "
               "commit only that file on a new devin/ branch from origin/%s and raise a pull request into %s for "
               "the reviewers that file names. Never push to %s directly." % (REPO_BLOCKS[kind], SAVE_BRANCH,
                                                                            SAVE_BRANCH, SAVE_BRANCH))
    elif kind == observer.BLOCK:
        return feedback_prompt(block, requester)
    elif kind == "SDLC-INTAKE-ANSWERS":
        how = ("Apply it as the intake skill says for a returned SDLC-INTAKE-ANSWERS block: save it verbatim next to "
               "the requirement, check requirement_id and carry on with the intake.")
    else:
        how = ("Apply it exactly as the skill says for this block when it is pasted: show the preview, wait for the "
               "requester's `approved`, then apply. Jira is written only when SDLC_BACKLOG_WRITES=1.")
    return ("The requester pressed Save in Argus; this block came from that page, not from chat.\n%s\n\n"
            "```\n%s\n```" % (how, block))

def feedback_prompt(block, requester):
    """Feedback and noticed problems need no review: the run adds one file, raises the PR and merges it."""
    how = ("This is Argus's feedback: what people sent from the Feedback form, with the session details "
           "Argus had, and the problems it noticed itself. The tech lead has said these pull requests need "
           "no approval or review, so do not wait for `approved` and add no reviewers. Do exactly this, as "
           ".devin/skills/dashboard/SKILL.md says for a %(b)s block:\n"
           "1. Save the block below to a file and run `python3 %(fw)s/tools/framework_feedback.py "
           "import --block FILE` (preview), then the same with --write. It writes one new file under "
           "SHARED/workbench-feedback/.\n"
           "2. On a new devin/ branch from origin/%(br)s, stage only that file. If the access guard asks for an "
           "approval, run `access_guard.py approve`: pressing Send was the requester's approval. Commit with "
           "SDLC_OWNER set to the requester, with trailers `Pushed-by:` (the requester) and "
           "`Work-ID: WORKBENCH-FEEDBACK`. Never use --no-verify.\n"
           "3. Push the branch and raise a pull request into %(br)s titled `Argus feedback <batch>`.\n"
           "4. Merge it yourself when its diff is exactly that one new file: fetch origin/%(br)s, merge the devin/ "
           "branch into it with `git merge --no-ff` and push that to %(br)s (never force). Bitbucket then shows the "
           "pull request as merged.\n"
           "5. If Bitbucket refuses the push or anything else is in the diff, leave the pull request open, say why in "
           "one line and stop. Change nothing else." % {"b": observer.BLOCK, "br": SAVE_BRANCH,
                                                  "fw": os.path.relpath(team.FRAMEWORK_DIR, ROOT)})
    return ("Argus sent this feedback block; it came from the Feedback form or Argus's own daily "
            "send, not from chat.\n%s\n\n%s\n\n```\n%s\n```" % (how, requester, block))


class BridgedDevin(bridge.BridgeDevin):
    """The Devin client in Devin Cloud: calls go through the host session's tools, so no API key is needed."""

    def __init__(self):
        super().__init__(os.path.join(STATE_DIR, "bridge"), DEVIN_APP, user_ids=self._user_ids)

    @staticmethod
    def _user_ids(email):
        person = find_person(email)
        return [person["devin_user_id"]] if person and person.get("devin_user_id") else []

    def call(self, *calls):
        try:
            out = super().call(*calls)
        except bridge.BridgeError as exc:
            err = ApiError(exc.status, str(exc))
            if exc.status >= 500:
                HEALTH.wait("devin", err) if self.reconnecting() else HEALTH.fail("devin", err)
            raise err
        HEALTH.ok("devin")
        return out


def make_devin():
    return BridgedDevin() if bridge.transport() == "bridge" else Devin()

CLOUD_JIRA_TAG = "sdlc-jira-read"
CLOUD_JIRA_DIR = os.path.join(STATE_DIR, "cloud-jira")
CLOUD_JIRA_TTL = int(os.environ.get("SDLC_CLOUD_JIRA_TTL", "0"))
CLOUD_JIRA_GIVE_UP = 900
CLOUD_READER_TITLE = "RESERVED – do not type · Argus Jira reader"
ATTACHMENT_RE = re.compile(r"/attachments/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
                           r"/([^\s)\]>\"'`]+)")
READ_REQ_RE = re.compile(r"^[0-9a-f]{8}$")
LIST_FILE_RE = re.compile(r"^stories-(.+)\.([0-9a-f]{8})\.json$")


def list_name(scope, jira_user=""):
    return scope + "-" + jira_user if scope in PERSONAL_SCOPES else scope


LAST_STORIES_DIR = os.path.join(STATE_DIR, "last-stories")


def _last_stories_path(scope, jira_user=""):
    return os.path.join(LAST_STORIES_DIR, re.sub(r"[^A-Za-z0-9._-]", "_", list_name(scope, jira_user)) + ".json")


def save_last_stories(scope, jira_user, out):
    path = _last_stories_path(scope, jira_user)
    try:
        os.makedirs(LAST_STORIES_DIR, exist_ok=True)
        with open(path + ".tmp", "w") as fh:
            json.dump(out, fh)
        os.replace(path + ".tmp", path)
    except OSError:
        pass


def load_last_stories(scope, jira_user=""):
    try:
        with open(_last_stories_path(scope, jira_user)) as fh:
            saved = json.load(fh)
    except (OSError, ValueError):
        return None
    return saved if isinstance(saved, dict) and saved.get("stories") else None


STORIES_FRESH_FOR = 300
STORIES_RETRY_AFTER = 60
_STORY_REFRESH = {}
_STORY_REFRESH_LOCK = threading.Lock()


def _refresh_stories(jira, scope, jira_user, name):
    try:
        out = dict(jira.stories(scope, jira_user), fetched_at=time.time())
        if out.get("stories") and not out.get("error"):
            save_last_stories(scope, jira_user, out)
        error = out.get("error") or ""
    except Exception as exc:  # noqa: BLE001 - the page keeps the saved list and says why
        error = str(exc)
    with _STORY_REFRESH_LOCK:
        _STORY_REFRESH[name] = {"running": False, "at": time.time(), "error": error}


def stories_saved_first(jira, scope, jira_user="", refresh=False, start=None):
    """The saved ticket list at once. When it is older than STORIES_FRESH_FOR, Jira is read again in the
    background and the page asks again (`refreshing`). No saved list, or `refresh`, reads Jira now."""
    saved = None if refresh else load_last_stories(scope, jira_user)
    if not saved:
        return stories_or_last_good(jira, scope, jira_user)
    if time.time() - (saved.get("fetched_at") or 0) < STORIES_FRESH_FOR:
        return saved
    name = list_name(scope, jira_user)
    with _STORY_REFRESH_LOCK:
        st = _STORY_REFRESH.get(name) or {}
        if st.get("running"):
            return dict(saved, refreshing=True)
        if st.get("error") and time.time() - st.get("at", 0) < STORIES_RETRY_AFTER:
            return dict(saved, stale=True, error=st["error"])
        _STORY_REFRESH[name] = {"running": True, "at": time.time(), "error": ""}
    (start or (lambda f: threading.Thread(target=f, daemon=True).start()))(
        lambda: _refresh_stories(jira, scope, jira_user, name))
    return dict(saved, refreshing=True)


def stories_or_last_good(jira, scope, jira_user=""):
    """Ticket list read straight from Jira. When Jira is slow or down, the last list read for this
    scope and person comes back instead, marked stale with when it was read."""
    try:
        out = dict(jira.stories(scope, jira_user), fetched_at=time.time())
    except ApiError as exc:
        saved = load_last_stories(scope, jira_user) if exc.status >= 500 else None
        if not saved:
            raise
        return dict(saved, stale=True, error=str(exc))
    if out.get("stories") and not out.get("error"):
        save_last_stories(scope, jira_user, out)
    return out


def cloud_read_command(scopes, jira_user="", req=""):
    cmd = "python3 %s/console/server.py --cloud-stories %s" % (team.FRAMEWORK, ",".join(scopes))
    if any(s in PERSONAL_SCOPES for s in scopes):
        cmd += " --user %s" % jira_user
    if req:
        cmd += " --req %s" % req
    return cmd


def cloud_read_request(scopes, jira_user, req):
    return "\n".join([
        "Jira read %s. From the repository root, run exactly:" % req,
        "   " + cloud_read_command(scopes, jira_user, req),
        "Post every `[SDLC] attachment` line it prints, exactly as printed, in one message. If it fails, post",
        "`[SDLC] note jira-read %s — failed: <first error line>`. Then wait for the next read." % req,
    ])


def cloud_reader_prompt(scopes, jira_user, req):
    """The first message of the day's reader session: the standing job, then the first read."""
    return "\n".join([
        "Repository: @%s" % REPO_SLUG,
        "",
        "A SDLC Argus on a tester's PC has no Jira access. This session is its Jira reader for today: it",
        "reads ticket lists with the Jira service account and hands them back. Each read arrives as a chat",
        "message that starts with `Jira read <id>` and holds one command.",
        "",
        "For every read:",
        "1. From the repository root, run the command exactly as given. It reads Jira (bearer token, /myself",
        "   checked once), uploads each list as a Devin attachment and prints one line per list starting with",
        "   `[SDLC] attachment`.",
        "2. Post those lines in chat exactly as printed, in one message. Then stop and wait for the next read.",
        "3. If the command fails, post `[SDLC] note jira-read <id> — failed: <first error line>`. Never retry",
        "   Jira after HTTP 401 or 403.",
        "Do nothing else between reads. Do not change the repository, Jira or Confluence, and do not open a PR.",
        "This session is machine-only. If a person types anything other than a `Jira read` message, answer once:",
        "\"This session only reads Jira for Argus. Ask in Argus chat, or start a new Devin session",
        "with /start.\" Then go back to waiting for the next read.",
        "Argus closes this session at the end of the day.",
        "",
        cloud_read_request(scopes, jira_user, req),
    ])


class CloudJira:
    """Ticket lists for an Argus with no Jira token. One Devin Cloud session a day (the reader) reads them
    with the service account: each read is a chat message to it, and it answers with the lists as attachments.
    Each list is read once and kept until Refresh. The reader is closed when the day changes."""
    via = "cloud"
    token = None

    def __init__(self, devin, folder=None, ttl=None, today=None):
        self.devin, self.folder = devin, folder or CLOUD_JIRA_DIR
        self.ttl = CLOUD_JIRA_TTL if ttl is None else ttl
        self.today = today or (lambda: datetime.date.today().isoformat())
        self.reads, self.pending, self.errors = {}, {}, {}
        self.checked = 0
        self.lock = threading.Lock()

    def _path(self, name):
        return os.path.join(self.folder, name + ".json")

    def _cached(self, name):
        try:
            with open(self._path(name), encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return None

    def _reader_path(self):
        return os.path.join(self.folder, "reader.state")

    def reader(self):
        try:
            with open(self._reader_path(), encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_reader(self, data):
        os.makedirs(self.folder, exist_ok=True)
        with open(self._reader_path() + ".tmp", "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        os.replace(self._reader_path() + ".tmp", self._reader_path())

    def _stale(self, name, refresh):
        """A list is read once and then kept: only Refresh / Check now (or a TTL set on purpose) reads Jira again."""
        cached = self._cached(name)
        return not cached or refresh or bool(self.ttl and time.time() - cached.get("fetched_at", 0) > self.ttl)

    def stories(self, scope, jira_user="", refresh=False):
        if scope in PERSONAL_SCOPES:
            if not re.match(r"^[A-Za-z0-9._-]+$", jira_user or ""):
                raise ApiError(400, "Pick who you are (top right) to list the tickets assigned to you.")
        else:
            scope = scope if scope in JQL else "sprint"
        name = list_name(scope, jira_user)
        with self.lock:
            self._poll()
            self._clean_up()
            if self._stale(name, refresh) and name not in self.pending and not (self.errors.get(name) and not refresh):
                # One read brings all of this person's lists, so the other personal lists don't need their own.
                scopes = [scope] if scope not in PERSONAL_SCOPES else [scope] + [
                    s for s in PERSONAL_SCOPES if s != scope and list_name(s, jira_user) not in self.pending
                    and not self.errors.get(list_name(s, jira_user)) and self._stale(list_name(s, jira_user), False)]
                try:
                    self._start(scopes, jira_user)
                except ApiError as exc:
                    HEALTH.fail("jira", "Jira is read through Devin Cloud, which failed: %s" % exc)
                    raise
            cached = self._cached(name)
            out = {"jql": (cached or {}).get("jql", ""), "stories": (cached or {}).get("stories", [])}
            out.update(source="cloud", fetched_at=(cached or {}).get("fetched_at"), pending=name in self.pending,
                       session_url=self.reader().get("url", "") if name in self.pending else "",
                       error=self.errors.get(name, ""))
            return out

    def _reader_alive(self, r):
        if not r.get("session_id") or r.get("day") != self.today():
            return False
        try:
            return (self.devin.session(r["session_id"]).get("status_enum") or "") not in ENDED
        except ApiError:
            return False

    def _start(self, scopes, jira_user):
        req = uuid.uuid4().hex[:8]
        names = [list_name(s, jira_user) for s in scopes]
        for n in names:
            self.errors.pop(n, None)
        r = self.reader()
        sent = False
        if self._reader_alive(r):
            try:
                self.devin.send(r["session_id"], cloud_read_request(scopes, jira_user, req))
                sent = True
            except ApiError:
                pass
        if not sent:
            self._close_reader(r)
            day = self.today()
            title = "%s · %s · %s" % (CLOUD_READER_TITLE, jira_user or "team lists", day)
            session = self.devin.create_session(cloud_reader_prompt(scopes, jira_user, req), title, [CLOUD_JIRA_TAG])
            r = {"day": day, "session_id": session.get("session_id", ""), "url": session.get("url", ""),
                 "opened": sorted(set(r.get("opened") or []) | {session.get("session_id", "")})}
            self._save_reader(r)
        self.reads[req] = {"names": names, "sent": time.time()}
        for n in names:
            self.pending[n] = req

    def _poll(self):
        if not self.reads or time.time() - self.checked < 8:
            return
        self.checked = time.time()
        r = self.reader()
        try:
            info = self.devin.session(r.get("session_id", ""))
        except ApiError:
            info = {"status_enum": "error"}
        for m in Devin.messages(info):
            if m["source"] != "devin":
                continue
            text = m.get("message", "")
            for req in list(self.reads):
                if ("[SDLC] note jira-read %s" % req) in text:
                    self._fail(req, "Devin Cloud could not read Jira: " + text.split("failed:", 1)[-1].strip()[:300])
            for attachment_id, fname in ATTACHMENT_RE.findall(text):
                fname = urllib.parse.unquote(fname).rstrip(".,;:")
                hit = LIST_FILE_RE.match(fname)
                if not hit or self.pending.get(hit.group(1)) != hit.group(2):
                    continue
                self._save_list(hit.group(1), hit.group(2), self.devin.download(attachment_id, fname))
        ended = (info.get("status_enum") or "") in ENDED
        for req, read in list(self.reads.items()):
            if ended or time.time() - read["sent"] > CLOUD_JIRA_GIVE_UP:
                self._fail(req, "the Devin Cloud session that reads Jira stopped without sending the list")
        if ended:
            self._close_reader(r)

    def _save_list(self, name, req, raw):
        try:
            data = json.loads(raw.decode("utf-8"))
        except ValueError:
            data = None
        if not isinstance(data, dict) or not isinstance(data.get("stories"), list):
            self.errors[name] = "Devin Cloud sent a ticket list this Argus cannot read"
            HEALTH.fail("jira", self.errors[name])
        else:
            HEALTH.ok("jira")
            data["fetched_at"] = time.time()
            os.makedirs(self.folder, exist_ok=True)
            with open(self._path(name) + ".tmp", "w", encoding="utf-8") as fh:
                json.dump(data, fh)
            os.replace(self._path(name) + ".tmp", self._path(name))
        self._done(name, req)

    def _done(self, name, req):
        self.pending.pop(name, None)
        read = self.reads.get(req)
        if read:
            read["names"] = [n for n in read["names"] if n != name]
            if not read["names"]:
                self.reads.pop(req)

    def _fail(self, req, error):
        HEALTH.fail("jira", error)
        for name in list((self.reads.get(req) or {}).get("names", [])):
            self.errors[name] = error
            self._done(name, req)

    def _close_reader(self, r):
        if not r.get("session_id"):
            return
        try:
            close_session(self.devin, r["session_id"], [CLOUD_JIRA_TAG])
        except ApiError:
            return
        r = dict(r, session_id="", url="", opened=[s for s in r.get("opened") or [] if s != r["session_id"]])
        self._save_reader(r)

    def _clean_up(self):
        """Once a day: close yesterday's reader and any reader this Argus opened and didn't close."""
        r = self.reader()
        day = self.today()
        if r.get("swept") == day or self.reads:
            return
        live = r.get("session_id") if r.get("day") == day else ""
        left = []
        for sid in r.get("opened") or []:
            if sid == live:
                left.append(sid)
                continue
            try:
                close_session(self.devin, sid, [CLOUD_JIRA_TAG])
            except ApiError:
                left.append(sid)
        r.update(opened=left, swept=day)
        if not live:
            r.update(session_id="", url="")
        self._save_reader(r)

    def story(self, key):
        names = sorted(os.listdir(self.folder)) if os.path.isdir(self.folder) else []
        for n in names:
            if not n.endswith(".json"):
                continue
            for item in (self._cached(n[:-5]) or {}).get("stories", []):
                if item.get("key") == key:
                    return dict({"description": ""}, **item)
        return {"key": key, "summary": key, "description": "", "status": "", "assignee": "", "reporter": "",
                "labels": [], "points": "", "url": JIRA_BROWSE + key,
                "note": "Devin Cloud reads this ticket when the run starts."}

    def create_story(self, *args):
        raise ApiError(409, "this Argus has no Jira access; the session creates the story")


YEAR_PLAN_PATH = os.path.join(team.FRAMEWORK_DIR, "context", "roadmap", "year-plan.yaml")


SCRUM_RULES = os.path.join(ROOT, ".devin", "rules", "scrum-master-metrics.yaml")


def idle_working_days(path=SCRUM_RULES):
    """cycle_time.idle_working_days: working days without a change before an In Progress story counts as idle."""
    for line in _lines(path):
        m = re.match(r"^\s+idle_working_days:\s*(\d+)", line)
        if m:
            return int(m.group(1))
    return 2


def leave_view(sprints, token=""):
    """The leave grid for one sprint: the Confluence page section, else a fresh one from the roster."""
    known = [dict(s, **(sprint_leave.sprint_of(s.get("name", ""), s.get("start"), s.get("end")) or {}))
             for s in sprints]
    seen, uniq = set(), []
    for s in known:
        if s.get("token") and s["token"] not in seen:
            seen.add(s["token"])
            uniq.append(s)
    known = uniq
    pick = next((s for s in known if s["token"] == token), None) or \
        next((s for s in known if s.get("state") == "active"), None) or (known[0] if known else None)
    out = {"sprints": [{"token": s["token"], "name": s.get("name", ""), "start": s.get("start", ""),
                        "end": s.get("end", ""), "state": s.get("state", "")} for s in known],
           "page": "", "saved": False, "error": ""}
    try:
        out["page"] = team_links_page_url()
        out["page_title"] = sprint_leave.page_ref()[1]["title"]
        page, stored = sprint_leave.load()
        out["time_off"] = sprint_leave.parse_time_off(page["body"]["storage"]["value"])
    except Exception as exc:  # noqa: BLE001 - shown on the screen; the grid still works from the roster
        stored, out["error"] = {}, "The Sprint Leave page could not be read (%s)." % exc
    token = (pick or {}).get("token") or token
    if not token:
        return dict(out, error=out["error"] or "No sprint on the team board.")
    sprint = stored.get(token)
    out["saved"] = sprint is not None
    if sprint is None:
        if not pick or not (pick.get("start") and pick.get("end")):
            return dict(out, token=token, error="Sprint %s has no dates in Jira or its name." % token)
        sprint = sprint_leave.apply_time_off(sprint_leave.new_sprint(pick), out.get("time_off") or [])
    days = sprint_leave.working_days(sprint["start"], sprint["end"], sprint.get("holidays") or ())
    return dict(out, token=token, sprint=sprint, days=days, capacity=sprint_leave.capacity(token, sprint))


def sprint_checks(b, active, sprints):
    """The stand-up gaps, each person's points against capacity and who has not answered about leave, for
    the active sprint; read with Argus's Jira account and the Sprint Leave page."""
    out = {"gaps": [], "load": [], "unanswered": [], "checks_error": ""}
    if not active.get("id") or not b._live():
        return out
    try:
        import scrum_metrics   # needs PyYAML, so only when the checks are asked for
        data = scrum_metrics.fetch_sprint(b.jira.get, active["id"])
        scrum_metrics.add_history(b.jira.get, data["stories"])
        leave = leave_view(sprints, "")
        if leave.get("capacity"):
            data["capacity"] = leave["capacity"]
        rules = scrum_metrics.load_rules()
        out.update(gaps=scrum_metrics.standup_rows(data, rules), load=scrum_metrics.load_rows(data, rules),
                   unanswered=scrum_metrics.unanswered(data))
    except Exception as exc:  # noqa: BLE001 - shown on the screen; the other follow-ups still work
        out["checks_error"] = "The sprint checks could not be read (%s)." % exc
    return out


NUDGE_CODES = ("no_time", "closed_no_time", "no_due_date", "close_story")
NUDGE_ANSWERS = {"no_due_date": "due", "close_story": "note"}


def _who(name):
    return "".join(sorted(re.findall(r"[a-z0-9]+", (name or "").lower())))


def nudge_rows(follow, gaps, name):
    """One person's reminders for Waiting on me: their stand-up gaps, their stories in progress at the same time
    and their idle stories, from backlog.followups and sprint_checks for the active sprint."""
    me, out = _who(name), []
    if not me:
        return out
    for g in gaps or []:
        if g.get("code") in NUDGE_CODES and _who(g.get("owner")) == me:
            text = ("Log your hours on %s" % g["key"]) if g["code"] in ("no_time", "closed_no_time") else g["check"]
            out.append({"id": "%s:%s" % (g["code"], g["key"]), "code": g["code"], "key": g["key"],
                        "summary": g.get("summary", ""), "text": text, "detail": g.get("check", ""),
                        "answer": NUDGE_ANSWERS.get(g["code"], "")})
    for p in (follow or {}).get("parallel") or []:
        if _who(p.get("owner")) == me:
            keys = [r["key"] for r in p.get("stories") or []]
            out.append({"id": "parallel:" + ",".join(keys), "code": "parallel", "key": keys[0] if keys else "",
                        "keys": keys, "summary": "", "answer": "",
                        "text": "You have %d stories In Progress: %s. Which one is next?" % (len(keys), ", ".join(keys)),
                        "detail": "One story at a time keeps cycle time down."})
    for r in (follow or {}).get("idle") or []:
        if _who(r.get("owner")) == me:
            out.append({"id": "idle:" + r["key"], "code": "idle", "key": r["key"], "summary": r.get("summary", ""),
                        "answer": "", "text": "%s has not moved for %d working days" % (r["key"], r.get("quiet", 0)),
                        "detail": "No change on the story or its sub-tasks since %s." % (r.get("last") or "?")})
    return out


def team_links_page_url():
    import team_links
    return team_links.page_url(sprint_leave.PAGE_KEY)


def plan_velocity(path=None):
    """Points a sprint, from the roadmap year plan (`velocity_points_per_sprint:`); None when it isn't set."""
    for line in _lines(path or YEAR_PLAN_PATH):
        m = re.match(r"^velocity_points_per_sprint:\s*(\d+)", line)
        if m:
            return int(m.group(1))
    return None


def cloud_stories(scopes, jira_user="", req="", jira=None, devin=None, out_dir=None):
    """Runs in Devin Cloud: reads ticket lists with the service account and uploads each as an attachment."""
    scopes = scopes.split(",") if isinstance(scopes, str) else list(scopes)
    if not scopes or any(s not in JQL for s in scopes) or (req and not READ_REQ_RE.match(req)):
        print("--cloud-stories takes lists from: %s; --req is 8 hex characters" % ", ".join(sorted(JQL)),
              file=sys.stderr)
        return 1
    jira, devin = jira or Jira(), devin or make_devin()
    folder = out_dir or os.path.join(STATE_DIR, "cloud-jira-out")
    lines = []
    try:
        for scope in scopes:
            data = jira.stories(scope, jira_user, with_description=True)
            name = "stories-%s%s.json" % (list_name(scope, jira_user), "." + req if req else "")
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, name)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh)
            lines.append("[SDLC] attachment %s — %s" % (name, devin.upload(path, name)))
    except ApiError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print("\n".join(lines))
    return 0


CLOUD_PR_TAG = "sdlc-pr-state"
CLOUD_PR_FILE = os.path.join(STATE_DIR, "cloud-prs.json")
PR_NUMBER_RE = re.compile(r"/projects/%s/repos/%s/pull-requests/(\d+)" % tuple(re.escape(p) for p in REPO_SLUG.split("/")))
PR_STATE_RE = re.compile(r"\[SDLC\] pr-state (\d+) (open|merged|declined|unknown)(?: (\S+) -> (\S+))?")
PR_STATES_MAX = 40


def pr_number(url):
    m = PR_NUMBER_RE.search(url or "")
    return int(m.group(1)) if m else None


def pr_link(p):
    """The Devin API names a session's PR link `url`; Argus pages read `pr_url`."""
    return {"pr_url": (p or {}).get("pr_url") or (p or {}).get("url") or ""}


def cloud_prs_prompt(numbers):
    return "\n".join([
        "Repository: @%s" % REPO_SLUG,
        "",
        "A SDLC Argus on a developer's PC can't call the Bitbucket API. Look up the state of these pull",
        "requests in %s/%s and hand it back: %s." % (
            team.REPO_HOST, REPO_SLUG, ", ".join("#%d" % n for n in numbers)),
        "",
        "1. Look up each one with your git_view_pr tool. Don't use the Bitbucket REST API or a script.",
        "2. Post one message with one line per pull request, exactly in this form:",
        "   [SDLC] pr-state <number> <open|merged|declined> <source branch> -> <target branch>",
        "   Closed and merged is `merged`; closed without merging is `declined`.",
        "   If a lookup fails, post `[SDLC] pr-state <number> unknown` for it.",
        "3. That is the whole task; Argus closes this session.",
        "Read only: don't merge, approve, decline, comment on or change any pull request, and don't change the",
        "repository, Jira or Confluence.",
    ])


class CloudPrs:
    """PR state for an Argus with no Bitbucket API access: on request, a short Devin Cloud session looks
    the PRs up with its Bitbucket tool and posts one line each. Read only; the last answer is cached."""

    def __init__(self, devin, path=None, give_up=CLOUD_JIRA_GIVE_UP):
        self.devin, self.path, self.give_up = devin, path or CLOUD_PR_FILE, give_up
        self.job, self.error = None, ""
        self.lock = threading.Lock()

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def status(self):
        with self.lock:
            self._poll()
            return {"prs": self._load(), "pending": bool(self.job),
                    "session_url": (self.job or {}).get("url", ""), "error": self.error}

    def refresh(self, numbers):
        numbers = sorted(set(n for n in numbers if isinstance(n, int) and n > 0))[-PR_STATES_MAX:]
        if not numbers:
            raise ApiError(400, "None of your sessions has a pull request yet.")
        with self.lock:
            if self.job:
                raise ApiError(409, "Devin Cloud is already checking the pull requests.")
            self.error = ""
            session = self.devin.create_session(cloud_prs_prompt(numbers), "Argus PR state", [CLOUD_PR_TAG])
            self.job = {"session_id": session.get("session_id", ""), "url": session.get("url", ""),
                        "started": time.time(), "checked": 0, "numbers": numbers}
        return self.status()

    def _poll(self):
        job = self.job
        if not job or time.time() - job["checked"] < 8:
            return
        job["checked"] = time.time()
        info = self.devin.session(job["session_id"])
        found = {}
        for m in Devin.messages(info):
            if m["source"] != "devin":
                continue
            for num, state, src, dst in PR_STATE_RE.findall(m.get("message", "")):
                if int(num) in job["numbers"]:
                    found[num] = {"state": state, "from": src, "to": dst, "checked_at": time.time()}
        status = info.get("status_enum") or ""
        if found and (len(found) == len(job["numbers"]) or status not in BUSY):
            data = self._load()
            data.update(found)
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path + ".tmp", "w", encoding="utf-8") as fh:
                json.dump(data, fh)
            os.replace(self.path + ".tmp", self.path)
            missing = [n for n in job["numbers"] if str(n) not in found]
            if missing:
                self.error = "Devin Cloud didn't report " + ", ".join("#%d" % n for n in missing)
            return self._finish()
        if status in ENDED or time.time() - job["started"] > self.give_up:
            self.error = "the Devin Cloud session that checks the pull requests stopped without an answer"
            self._finish()

    def _finish(self):
        job, self.job = self.job, None
        try:
            close_session(self.devin, job["session_id"], [CLOUD_PR_TAG])
        except ApiError:
            pass


TASK_REPLY_TAG = "sdlc-task-reply"
TASK_REPLY_FILE = os.path.join(STATE_DIR, "task-replies.json")
TASK_REPLY_RE = re.compile(r"\[SDLC\] task-reply (%s) done" % team.TICKET)
TASK_REPLY_FAIL = "[SDLC] note task-reply"
TASK_KINDS = {"answer": "Question", "approve": "Approval", "reject": "Approval"}
TASK_TEXT_MAX = 4000


def task_kind_ok(kind, labels):
    return TASK_KINDS.get(kind) in (labels or [])


def task_reply_prompt(key, kind, jira_user, text):
    tool = team.FRAMEWORK + "/tools/"
    if kind == "answer":
        cmd = "python3 %squestion_subtask.py answer --key %s --answered-by %s --answer \"$TEXT\"" % (tool, key, jira_user)
    else:
        cmd = "python3 %sapproval_subtask.py decide --key %s --decision %s --items all --by %s" % (
            tool, key, "approve" if kind == "approve" else "reject", jira_user)
        if text:
            cmd += " --note \"$TEXT\""
    what = {"answer": "answered the question", "approve": "approved", "reject": "rejected"}[kind]
    lines = [
        "Repository: @%s" % REPO_SLUG,
        "",
        "%s %s Jira sub-task %s in the SDLC Argus. Record it on the sub-task with the Jira service account."
        % (jira_user, what, key),
        "",
    ]
    if text:
        lines += [
            "1. Put the text between the two marker lines below into the shell variable TEXT exactly as written",
            "   (a quoted here-doc, so nothing in it is expanded):",
            "-----BEGIN WORKBENCH TEXT-----",
            text,
            "-----END WORKBENCH TEXT-----",
        ]
    lines += [
        "%d. From the repository root, run exactly:" % (2 if text else 1),
        "   " + cmd,
        "%d. Post `[SDLC] task-reply %s done` in chat. That is the whole task; Argus closes this session."
        % (3 if text else 2, key),
        "If the command fails, post `%s — failed: <first error line>`. Never retry Jira after HTTP 401 or 403."
        % TASK_REPLY_FAIL,
        "Do nothing else: no other Jira change, no repository change, no PR.",
    ]
    return "\n".join(lines)


INSIGHT_TAG = "story-insight"
INSIGHT_FILE = os.path.join(STATE_DIR, "story-insight.json")
INSIGHT_GIVE_UP = 1800
INSIGHT_RE = re.compile(r"\[SDLC\] story-insight (%s)\s*```(?:json)?\s*(\{.*?\})\s*```" % team.TICKET, re.S)
INSIGHT_FAIL = "[SDLC] note story-insight"
INSIGHT_SCALE = (1, 2, 3, 5, 8, 13)


MATRIX_PATH = os.path.join(ROOT, ".devin", "templates", "complexity-matrix.yaml")
MATRIX_DIMENSIONS = ("SCOPE", "RISK", "UNKNOWNS", "DEPENDENCY", "TESTABILITY")
MATRIX_LOOKUP = ((1, 1), (3, 2), (5, 3), (7, 5), (9, 8), (10, 13))
MATRIX_MODIFIERS = ("MOD_BREAKING_CHANGE", "MOD_DATA_MIGRATION", "MOD_NO_PRIOR_ART",
                    "MOD_PERFORMANCE_SENSITIVE", "MOD_SECURITY_SENSITIVE")
MATRIX_MAX_BUMPS = 2
STORY_TYPES = ("code", "design", "spike", "automation", "uat", "sit")


def matrix_rules():
    """points_lookup and the risk modifiers from .devin/templates/complexity-matrix.yaml; the defaults mirror it."""
    lookup, mods, bumps = MATRIX_LOOKUP, MATRIX_MODIFIERS, MATRIX_MAX_BUMPS
    yaml = team._yaml()
    try:
        with open(MATRIX_PATH, encoding="utf-8") as fh:
            doc = yaml.safe_load(fh) if yaml else None
    except (OSError, ValueError):
        doc = None
    if isinstance(doc, dict):
        rows = [(max(r["score_range"]), int(r["fibonacci_points"])) for r in doc.get("points_lookup") or []
                if isinstance(r, dict) and r.get("score_range") and "fibonacci_points" in r]
        lookup = tuple(sorted(rows)) or lookup
        mods = tuple(m["id"] for m in doc.get("risk_modifiers") or [] if isinstance(m, dict) and m.get("id")) or mods
        cap = re.search(r"maximum\s*\+?(\d+)", str(doc.get("modifier_cap_rule") or ""), re.I)
        bumps = int(cap.group(1)) if cap else bumps
    return lookup, mods, bumps


def matrix_points(out):
    """Devin's card from its matrix answer, worked out here so it follows the rule book exactly: the five dimensions
    summed, looked up, then bumped once per risk modifier (two at most). Design, spike, automation, UAT and SIT
    stories use the matrix's own rules for their type. Returns the card plus the basis shown at reveal."""
    lookup, known, max_bumps = matrix_rules()
    kind = str(out.get("story_type") or "code").lower()
    kind = kind if kind in STORY_TYPES else "code"
    scores, reasons = {}, {}
    for d in MATRIX_DIMENSIONS:
        raw = (out.get("scores") or {}).get(d)
        val, why = (raw[0], raw[1] if len(raw) > 1 else "") if isinstance(raw, (list, tuple)) and raw else (raw, "")
        try:
            scores[d] = max(0, min(2, int(val)))
        except (TypeError, ValueError):
            scores[d] = None
        reasons[d] = str(why or "")[:200]
    mods = [m for m in out.get("modifiers") or [] if m in known]
    res = {"story_type": kind, "scores": scores, "reasons": reasons, "modifiers": mods,
           "needs_split": False, "needs_grooming": False}
    if kind == "uat":
        return dict(res, points=1, rule="UAT stories are always 1 point")
    if kind != "code":
        try:
            pts = int(out.get("points"))
        except (TypeError, ValueError):
            pts = 0
        if kind == "spike":
            pts = max(1, min(5, pts))
        pts = min((p for p in INSIGHT_SCALE if p >= pts), default=13) if pts else 0
        rule = {"design": "design/analysis: points from artefacts and review rounds",
                "spike": "spike: one point per time-boxed day, five at most",
                "automation": "automation: points from the number of scenarios",
                "sit": "SIT: follows the implementation story's points"}[kind]
        return dict(res, points=pts or None, rule=rule)
    if any(v is None for v in scores.values()):
        try:
            return dict(res, points=int(out.get("points")), rule="Devin did not score every dimension")
        except (TypeError, ValueError):
            return dict(res, points=None, rule="Devin did not score every dimension")
    total = sum(scores.values())
    base = next(p for top, p in lookup if total <= top) if total <= lookup[-1][0] else lookup[-1][1]
    scale = list(INSIGHT_SCALE)
    idx = scale.index(base) + min(len(mods), max_bumps) if base in scale else len(scale) - 1
    res.update(total=total, base=base)
    if scores["UNKNOWNS"] == 2 and any(scores[d] == 2 for d in MATRIX_DIMENSIONS if d != "UNKNOWNS"):
        res["needs_grooming"] = True
    if total >= 10 or idx >= len(scale):
        res["needs_split"] = True
    return dict(res, points=scale[min(idx, len(scale) - 1)], rule="")


def insight_card(r):
    """The card Devin plays in team poker: ? when the matrix says groom first, 13 when it says split."""
    if r.get("state") != "done" or not r.get("points"):
        return None
    if r.get("needs_grooming"):
        return "?"
    return "13" if r.get("needs_split") else str(r["points"])


def insight_basis(r):
    """Devin's matrix working in one line: each dimension with its reason, the lookup and the modifiers."""
    if not insight_card(r):
        return ""
    if r.get("rule"):
        return "%s — %s." % (r["points"], r["rule"])
    dims = " · ".join("%s %s%s" % (d, (r.get("scores") or {}).get(d),
                                   " (%s)" % r["reasons"][d] if (r.get("reasons") or {}).get(d) else "")
                      for d in MATRIX_DIMENSIONS)
    out = "%s = %s/10 → %s" % (dims, r.get("total"), r.get("base"))
    if r.get("modifiers"):
        out += ", + %s → %s" % (", ".join(r["modifiers"]), r["points"])
    if r.get("needs_grooming"):
        out += "; needs grooming first (UNKNOWNS 2 with another 2)"
    if r.get("needs_split"):
        out += "; needs splitting (over 13)"
    return out + "."


def insight_prompt(story):
    key = story["key"]
    return "\n".join([
        "Read-only story insight for %s. Do not change code, branches, Jira or Confluence, and do not open a PR." % key,
        "You are also a voter in the team's planning poker for this story, so score it the way the rule book says.",
        "Ticket summary: %s" % story.get("summary", ""),
        "Description:\n%s" % (story.get("description") or "(none)")[:6000],
        "Current acceptance criteria:\n%s" % (story.get("acceptance") or "(none)")[:3000],
        "1. In this repository find the code the story would change (UI, API, DB, ETL — see AGENTS.md) and the tests.",
        "2. Write 3 to 8 numbered, testable acceptance criteria in the shape .devin/rules/jira-ticket-standards.yaml asks for.",
        "3. Estimate with .devin/templates/complexity-matrix.yaml. Pick story_type (%s); for code stories score each of %s "
        "0, 1 or 2 with a one-line reason that names what you found, and list the risk modifiers that apply. "
        "For design, spike, automation and SIT stories give points by that type's rule instead. Points are complexity, "
        "risk and uncertainty, never hours." % (", ".join(STORY_TYPES), ", ".join(MATRIX_DIMENSIONS)),
        "4. Say what would have to be true for the story to be bigger than your number, and what for it to be smaller; "
        "the team will hear these as your challenge when the votes are shown.",
        "Reply with exactly one message: the line `[SDLC] story-insight %s` followed by one ```json block" % key,
        '{"acceptance": "1. ...\\n2. ...", "story_type": "code", "scores": {"SCOPE": [1, "reason"], "RISK": [0, "reason"], '
        '"UNKNOWNS": [1, "reason"], "DEPENDENCY": [0, "reason"], "TESTABILITY": [1, "reason"]}, "modifiers": ["MOD_..."], '
        '"points": N, "why": "one or two sentences naming the files and layers", "bigger_if": "...", "smaller_if": "...", '
        '"files": ["path", ...]}',
        "points is your result on %s; above 13 means split." % ", ".join(str(p) for p in INSIGHT_SCALE),
        "If you cannot, reply `%s %s — failed: <reason>`. Then stop." % (INSIGHT_FAIL, key),
    ])


class StoryInsight:
    """Devin's suggested acceptance criteria and its own estimate for one story: a short read-only Cloud session
    that reads the code the story touches. Advice only; the PO edits the AC and the team's points stand."""

    def __init__(self, devin, path=None, give_up=INSIGHT_GIVE_UP, clock=time.time):
        self.devin, self.path, self.give_up, self.clock = devin, path or INSIGHT_FILE, give_up, clock
        self.lock = threading.Lock()

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self, data):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path + ".tmp", "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        os.replace(self.path + ".tmp", self.path)

    def _poll(self, key, r):
        if self.clock() - r.get("checked", 0) < 8:
            return
        r["checked"] = self.clock()
        try:
            info = self.devin.session(r["session_id"])
        except ApiError:
            info = {}
        for m in Devin.messages(info):
            text = m.get("message", "") if m.get("source") == "devin" else ""
            if ("%s %s" % (INSIGHT_FAIL, key)) in text:
                r.update(state="failed", error=text.split("failed:", 1)[-1].strip()[:300])
            for hit_key, raw in INSIGHT_RE.findall(text):
                if hit_key != key:
                    continue
                try:
                    out = json.loads(raw)
                    claimed = int(out.get("points") or 0)
                    m = matrix_points(out)
                except (ValueError, TypeError, AttributeError):
                    continue
                if not m.get("points"):
                    continue
                r.update(m, state="done", acceptance=str(out.get("acceptance") or "")[:6000], claimed=claimed,
                         why=str(out.get("why") or "")[:600], files=[str(f) for f in out.get("files") or []][:12],
                         bigger_if=str(out.get("bigger_if") or "")[:300], smaller_if=str(out.get("smaller_if") or "")[:300])
        if r.get("state") == "working" and ((info.get("status_enum") or "") in ENDED or self.clock() - r["at"] > self.give_up):
            r.update(state="failed", error="the Devin session stopped without an answer")
        if r.get("state") != "working":
            try:
                self.devin.terminate(r["session_id"])
            except ApiError:
                pass

    def get(self, key):
        with self.lock:
            data = self._load()
            r = data.get(key)
            if r and r.get("state") == "working":
                self._poll(key, r)
                self._save(data)
            return r or {}

    def card(self, key):
        """Devin's poker card for a story once it has answered, else None."""
        return insight_card(self.get(key))

    def start(self, story, keep_done=False):
        key = (story.get("key") or "").strip().upper()
        if not re.match(r"^%s$" % team.TICKET, key):
            raise ApiError(400, "pick a story first")
        with self.lock:
            data = self._load()
            if (data.get(key) or {}).get("state") == "working" or (keep_done and insight_card(data.get(key) or {})):
                return data[key]
            session = self.devin.create_session(insight_prompt(dict(story, key=key)),
                                                "Argus story insight · %s" % key, [WORKBENCH_TAG, INSIGHT_TAG, key])
            data[key] = {"state": "working", "session_id": session.get("session_id", ""),
                         "url": session.get("url", ""), "at": self.clock()}
            self._save(data)
            return data[key]


AC_REWRITE_TAG = "ac-rewrite"
AC_REWRITE_FILE = os.path.join(STATE_DIR, "ac-rewrite.json")
AC_REWRITE_RE = re.compile(r"\[SDLC\] ac-rewrite (%s)\s*```(?:json)?\s*(\{.*?\})\s*```" % team.TICKET, re.S)
AC_REWRITE_FAIL = "[SDLC] note ac-rewrite"


def clean_answers(answers):
    out = []
    for a in answers or []:
        if isinstance(a, dict):
            q, ans = str(a.get("question") or "").strip(), str(a.get("answer") or "").strip()
            if q:
                out.append({"question": q[:400], "answer": ans[:2000]})
    return out[:12]


def ac_rewrite_prompt(story, answers=None):
    key = story["key"]
    lines = [
        "Read-only acceptance-criteria rewrite for %s. Do not change code, branches, Jira or Confluence, and do not open a PR." % key,
        "Ticket summary: %s" % story.get("summary", ""),
        "Description:\n%s" % (story.get("description") or "(none)")[:6000],
        "Acceptance criteria as written:\n%s" % (story.get("acceptance") or "(none)")[:6000],
        "1. Rewrite the acceptance criteria the way .devin/rules/jira-ticket-standards.yaml asks: numbered, in the "
        "business's words, each line an outcome the PO and the team can confirm at the demo. They are not test cases "
        "and they do not say how to build it.",
        "2. Keep every outcome the ticket asks for and add none it does not support. Build steps, table and column "
        "names, API and screen work, and test steps go in `moved`, one line each saying where they belong (a DEV "
        "sub-task, the description, or QA's test scenarios).",
        "3. Do not guess. If an outcome needs something the ticket does not say (who the user is, which screen, what "
        "they see, how it is confirmed), ask it as a short question instead of inventing it.",
    ]
    answers = clean_answers(answers)
    if answers:
        lines.append("The PO answered your earlier questions; use these answers and ask again only if one leaves an "
                     "outcome unclear:")
        lines += ["Q: %s\nA: %s" % (a["question"], a["answer"] or "(no answer)") for a in answers]
    lines += [
        "Reply with exactly one message: the line `[SDLC] ac-rewrite %s` followed by one ```json block, either "
        '{"questions": ["...", "..."]} when you need answers first, or '
        '{"acceptance": "1. ...\\n2. ...", "moved": ["... -> DEV sub-task", "..."], "notes": "one line on what changed"}.' % key,
        "If you cannot, reply `%s %s — failed: <reason>`. Then stop." % (AC_REWRITE_FAIL, key),
    ]
    return "\n".join(lines)


class AcRewrite(StoryInsight):
    """Devin's rewrite of one story's acceptance criteria as numbered business outcomes: a short read-only Cloud
    session that asks the PO what the ticket does not say first. Advice only; Jira changes through the Backlog preview."""

    def __init__(self, devin, path=None, give_up=INSIGHT_GIVE_UP, clock=time.time):
        super().__init__(devin, path or AC_REWRITE_FILE, give_up, clock)

    def _poll(self, key, r):
        if self.clock() - r.get("checked", 0) < 8:
            return
        r["checked"] = self.clock()
        try:
            info = self.devin.session(r["session_id"])
        except ApiError:
            info = {}
        for m in Devin.messages(info):
            text = m.get("message", "") if m.get("source") == "devin" else ""
            if ("%s %s" % (AC_REWRITE_FAIL, key)) in text:
                r.update(state="failed", error=text.split("failed:", 1)[-1].strip()[:300])
            for hit_key, raw in AC_REWRITE_RE.findall(text):
                if hit_key != key:
                    continue
                try:
                    out = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(out, dict):
                    continue
                ac = str(out.get("acceptance") or "").strip()
                questions = [str(q).strip()[:400] for q in out.get("questions") or [] if str(q).strip()][:8]
                if ac:
                    r.update(state="done", acceptance=ac[:6000], notes=str(out.get("notes") or "")[:600],
                             moved=[str(x)[:300] for x in out.get("moved") or []][:12])
                elif questions:
                    r.update(state="questions", questions=questions)
        if r.get("state") == "working" and ((info.get("status_enum") or "") in ENDED or self.clock() - r["at"] > self.give_up):
            r.update(state="failed", error="the Devin session stopped without an answer")
        if r.get("state") != "working":
            try:
                self.devin.terminate(r["session_id"])
            except ApiError:
                pass

    def start(self, story, answers=None):
        key = (story.get("key") or "").strip().upper()
        if not re.match(r"^%s$" % team.TICKET, key):
            raise ApiError(400, "pick a story first")
        answers = (clean_answers((self.get(key) or {}).get("answers")) + clean_answers(answers)) if answers else []
        with self.lock:
            data = self._load()
            if (data.get(key) or {}).get("state") == "working":
                return data[key]
            session = self.devin.create_session(ac_rewrite_prompt(dict(story, key=key), answers),
                                                "Argus AC rewrite · %s" % key, [WORKBENCH_TAG, AC_REWRITE_TAG, key])
            data[key] = {"state": "working", "session_id": session.get("session_id", ""),
                         "url": session.get("url", ""), "at": self.clock(), "answers": answers}
            self._save(data)
            return data[key]


class CloudReplies:
    """Answers, approvals and rejections for Jira sub-tasks assigned to Argus user. Each one is a short
    Devin Cloud session that runs question_subtask.py / approval_subtask.py with the service account."""

    def __init__(self, devin, path=None, give_up=CLOUD_JIRA_GIVE_UP):
        self.devin, self.path, self.give_up = devin, path or TASK_REPLY_FILE, give_up
        self.lock = threading.Lock()

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self, data):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path + ".tmp", "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        os.replace(self.path + ".tmp", self.path)

    def status(self):
        with self.lock:
            data = self._load()
            if any(r.get("state") == "sending" for r in data.values()):
                for key, r in data.items():
                    if r.get("state") == "sending":
                        self._poll(key, r)
                self._save(data)
            return {"replies": data}

    def send(self, issue, kind, jira_user, text):
        key = issue.get("key", "")
        text = (text or "").strip()
        if kind not in TASK_KINDS:
            raise ApiError(400, "answer, approve or reject")
        if not task_kind_ok(kind, issue.get("labels")):
            raise ApiError(400, "%s is not %s sub-task" % (key, "a Question" if kind == "answer" else "an Approval"))
        if kind in ("answer", "reject") and not text:
            raise ApiError(400, "write the answer" if kind == "answer" else "say why you reject it")
        if len(text) > TASK_TEXT_MAX or "-----END WORKBENCH TEXT-----" in text:
            raise ApiError(400, "the text is too long or has a line Argus reserves")
        with self.lock:
            data = self._load()
            if (data.get(key) or {}).get("state") in ("sending", "done"):
                raise ApiError(409, "%s was already sent from this Argus" % key)
            session = self.devin.create_session(task_reply_prompt(key, kind, jira_user, text),
                                                "Argus %s %s" % (kind, key), [TASK_REPLY_TAG])
            data[key] = {"kind": kind, "state": "sending", "at": time.time(), "checked": 0,
                         "session_id": session.get("session_id", ""), "url": session.get("url", ""), "error": ""}
            self._save(data)
            return {"replies": data}

    def _poll(self, key, r):
        if time.time() - r.get("checked", 0) < 8:
            return
        r["checked"] = time.time()
        info = self.devin.session(r["session_id"])
        for m in Devin.messages(info):
            if m["source"] != "devin":
                continue
            text = m.get("message", "")
            if TASK_REPLY_FAIL in text:
                r.update(state="failed", error=text.split("failed:", 1)[-1].strip()[:300])
                return self._finish(r)
            if key in TASK_REPLY_RE.findall(text):
                r.update(state="done", done_at=time.time())
                return self._finish(r)
        if (info.get("status_enum") or "") in ENDED or time.time() - r["at"] > self.give_up:
            r.update(state="failed", error="the Devin Cloud session stopped without confirming")
            self._finish(r)

    def _finish(self, r):
        try:
            close_session(self.devin, r["session_id"], [TASK_REPLY_TAG])
        except ApiError:
            pass


CLOUD_DASHBOARD_TAG = "sdlc-dashboard-build"
DASHBOARD_BUILD = threading.Lock()


def cloud_dashboard_prompt(jira_user, lens="", actions=False):
    cmd = "python3 %s/console/server.py --cloud-dashboard --user %s" % (team.FRAMEWORK, jira_user)
    if lens:
        cmd += " --lens %s" % lens
    if actions:
        cmd += " --actions"
    return "\n".join([
        "Repository: @%s" % REPO_SLUG,
        "",
        "A SDLC Argus on a tester's PC has no Jira access. Build its /dashboard page with the Jira service",
        "account and hand it back.",
        "",
        "1. From the repository root, run exactly:",
        "   " + cmd,
        "   It builds the dashboard (bearer token, /myself checked once), uploads the HTML as a Devin attachment",
        "   and prints one line starting with `[SDLC] attachment`.",
        "2. Post that line in chat exactly as printed. That is the whole task; Argus closes this session.",
        "3. If the command fails, post `[SDLC] note dashboard — failed: <first error line>`. Never retry Jira",
        "   after HTTP 401 or 403.",
        "Do not change the repository, Jira or Confluence, and do not open a PR.",
    ])


def cloud_dashboard(jira_user, lens="", devin=None, out_dir=None, run=subprocess.run, actions=False):
    """Runs in Devin Cloud: builds one person's dashboard with the service account and uploads the HTML."""
    if not re.match(r"^[A-Za-z0-9._-]+$", jira_user or ""):
        print("--cloud-dashboard needs --user <Jira username>", file=sys.stderr)
        return 1
    folder = out_dir or os.path.join(STATE_DIR, "cloud-dashboard-out")
    os.makedirs(folder, exist_ok=True)
    name = "dashboard-%s.html" % jira_user
    path = os.path.join(folder, name)
    cmd = [sys.executable, GEN_DASHBOARD, "--user", jira_user, "-o", path] + (["--lens", lens] if lens else []) + (["--actions"] if actions else [])
    done = run(cmd, capture_output=True, text=True, timeout=600, cwd=ROOT)
    if done.returncode:
        print((done.stderr or done.stdout).strip()[-600:], file=sys.stderr)
        return 1
    try:
        url = (devin or make_devin()).upload(path, name)
    except ApiError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print("[SDLC] attachment %s — %s" % (name, url))
    return 0


def dashboard_through_cloud(devin, jira_user, lens, out_path, poll=8, give_up=CLOUD_JIRA_GIVE_UP, sleep=time.sleep, actions=False):
    """For an Argus with no Jira token: a short Devin Cloud session builds the dashboard and attaches it;
    this waits for the attachment, saves it to out_path and closes the session."""
    if not DASHBOARD_BUILD.acquire(blocking=False):
        raise ApiError(409, "The dashboard is already being built in Devin Cloud. Try again in a minute.")
    try:
        session = devin.create_session(cloud_dashboard_prompt(jira_user, lens, actions),
                                       "Argus dashboard: %s" % jira_user, [CLOUD_DASHBOARD_TAG])
        sid, started = session.get("session_id", ""), time.time()
        try:
            while True:
                sleep(poll)
                info = devin.session(sid)
                for m in Devin.messages(info):
                    text = m.get("message", "") if m["source"] == "devin" else ""
                    if "[SDLC] note dashboard" in text:
                        raise ApiError(502, "Devin Cloud could not build the dashboard: " +
                                       text.split("failed:", 1)[-1].strip()[:300])
                    for attachment_id, fname in ATTACHMENT_RE.findall(text):
                        fname = urllib.parse.unquote(fname).rstrip(".,;:")
                        if fname.endswith(".html"):
                            data = devin.download(attachment_id, fname)
                            with open(out_path + ".tmp", "wb") as fh:
                                fh.write(data)
                            os.replace(out_path + ".tmp", out_path)
                            return
                if (info.get("status_enum") or "") in ENDED or time.time() - started > give_up:
                    raise ApiError(502, "the Devin Cloud session that builds the dashboard stopped without "
                                        "sending it: " + session.get("url", ""))
        finally:
            try:
                close_session(devin, sid, [CLOUD_DASHBOARD_TAG])
            except ApiError:
                pass
    finally:
        DASHBOARD_BUILD.release()


def close_session(devin, devin_id, tags=()):
    """End a Devin session for good and tag it closed so lists can drop it; the tag is best effort."""
    devin_id = devin_id if devin_id.startswith("devin-") else "devin-" + devin_id
    try:
        devin.terminate(devin_id)
    except ApiError as exc:
        if exc.status not in (400, 404, 409, 422):
            raise
    try:
        devin.set_tags(devin_id, sorted(set(tags or ()) | {CLOSED_TAG}))
    except ApiError:
        pass
    return devin_id


# --------------------------------------------------------------------------- prompt

def custom_story(text):
    """A typed requirement gets a story-shaped record so the rest of the console treats it like a ticket."""
    first = text.strip().splitlines()[0].strip()
    summary = first if len(first) <= 120 else first[:117].rstrip() + "…"
    return {
        "key": "REQ-%s" % time.strftime("%m%d%H%M"), "custom": True,
        "summary": summary, "description": text.strip(),
        "status": "typed here", "assignee": "", "reporter": "", "labels": [], "points": "", "url": "",
    }


REPORTING_RULES = [
    "1. Progress lines. Print one line `[SDLC] <kind> <name> — <started|finished|detail>` whenever a "
    "stage, agent, skill, playbook, question round or gate starts or finishes. Kinds: stage "
    "(intake|research|plan|implement|test|release|kb-refresh), agent, skill, playbook, question round <n>, "
    "gate <GATE_ID>. Trace lines (`.devin/rules/workbench-trace.md`): when you match the routing map "
    "print `[SDLC] route <entry> — <module; layers; tables>`; for every knowledge-base or rule file you "
    "open or decide not to open print `[SDLC] kb <path> — loaded: <why>` / `skipped: <why>` or "
    "`[SDLC] rule <path> — loaded|deferred: <why>`; for a cross-layer matrix chain you use print "
    "`[SDLC] chain <DC-id> — <what it links>`; for a choice that shapes the work print "
    "`[SDLC] decision <what> — <detail>`. Give skills and agents a `why` after `started`.",
    "2. Questions. Ask intake and clarification questions as a numbered list, one question per line, "
    "right after a `[SDLC] question round <n> — started` line. Answers come back as a numbered list.",
    "3. Gates. Present every gate exactly as .devin/rules/gate-presentation.md says, after a "
    "`[SDLC] gate <GATE_ID> — presented` line, and wait for a reply whose first word is `approved` "
    "or `rejected`. A reply starting `/send-approval` sends the gate to someone else: follow the "
    "send-approval skill and keep waiting.",
    "4. Artefacts. When you finish an artefact (spec, gap analysis, backlog, routing map, insertion "
    "points, AI verification, test matrix, promotion plan, approvals.yaml, report), post it in chat as "
    "`[SDLC] artefact <file name> — ready` followed by its full content in a fenced code block, so the "
    "Argus can display it and offer it for download.",
]


def dry_run_rule(dry_run, branch_hint):
    if dry_run:
        return ("Dry run (framework is in development): do not commit, push, open pull requests, promote, or "
                "write to Jira or Confluence. Read only; keep artefacts in the session directory. Where a step "
                "would write, post what it would write as an artefact instead.")
    return ("Real run: commits, pushes and the pull request are allowed on a devin/%s-* branch. Still no Jira or "
            "Confluence writes and no promotion without an explicit approval in this session." % branch_hint)


def test_place_rule(local_test):
    if local_test:
        return ("Testing on the developer's PC (they ticked Bring to local): after the PR, write the test pack as "
                "/eval describes, then ask the developer to press Test on my PC in Argus and wait for the "
                "evidence it sends back before you run /eval and present SDLC_06.")
    return ("Testing in Devin Cloud: bring the backend and frontend up on this Devin machine (the SDLC local-run "
            "knowledge note has the settings) and run the tests and acceptance checks here.")


def hotfix_rule(key):
    """The hotfix question asked before intake on a Jira ticket (/sdlc STEP 0, tools/hotfix.py)."""
    return ("Before intake, run `python3 %s/tools/hotfix.py check --key %s`. If it passes, ask "
            "as question round 0: \"This is a production incident. Use the hotfix lane: one Tech Lead gate, "
            "HOTFIX_PLAN_CODE_APPROVAL, in place of SDLC_04 and SDLC_05? Yes or no.\" On yes, present "
            "HOTFIX_PLAN_CODE_APPROVAL instead of SDLC_04 and SDLC_05, run the independent verifier whatever the risk "
            "tier, and after approved show the follow-up review sub-task from `hotfix.py followup`. If it fails and "
            "the person says it is a hotfix, tell them what the check found missing and keep the normal gates. "
            "No other gate is skipped. " % (team.FRAMEWORK, key))


def build_prompt(story, dry_run, local_test=False):
    custom = story.get("custom")
    mode = dry_run_rule(dry_run, story["key"]) + " " + test_place_rule(local_test)
    if dry_run:
        mode += (" When you reach the PR step, produce the branch name, commit message and PR "
                 "title/description as text instead of opening one.")
    if custom:
        intake = "/intake %s" % json.dumps(story["description"])
        source = ("Requirement (typed into the console, no Jira ticket yet — the console may create one after the "
                  "intake gate and will tell you its key as `[SDLC] note jira <KEY> — created`):\n%s" % story["description"])
        ticket_rule = ("7. There is no Jira ticket to read; the requirement text above is the input. Skip the "
                       "ticket-reading step of /intake. ")
    else:
        intake = "/intake %s" % story["key"]
        source = "Story: %s — %s" % (story["key"], story["summary"])
        ticket_rule = ("7. Read the Jira ticket with bearer auth (%s, check /rest/api/2/myself once). " % JIRA_TOKEN_ENV
                       + hotfix_rule(story["key"]))
    return "\n".join([
        "Repository: @%s" % REPO_SLUG,
        intake,
        "",
        f"This session was started from the {WORKBENCH_TITLE} and is driven through it. Follow these "
        "reporting rules so Argus can render your work; they are additional to the repo rules.",
        "",
    ] + REPORTING_RULES + [
        "5. Code changes. For every file you change, post `[SDLC] diff <path> — <one-line why>` followed by a "
        "```diff fenced unified diff. When the PR is ready, post `[SDLC] pr <branch> — ready` followed by a "
        "fenced block with title, description, files changed and the PR URL if one exists.",
        "6. Keep going stage by stage without waiting between stages except at gates and question rounds: "
        "intake (2-3 short plain-English questions, draft spec, gate SDLC_01) → research (KB staleness, gap "
        "analysis, impact, one story with a complexity-matrix estimate, gate SDLC_02) → plan (routing map with "
        "exact files/functions/line numbers; just before gate SDLC_04 post `[SDLC] artefact <STORY>-SUBTASK-PLAN.json — ready` "
        "with a ```json block {\"story\": KEY, \"subtasks\": [{\"key\": \"\" for a new one or the existing sub-task key, "
        "\"summary\": \"DEV- ...\", \"hours\": N, \"description\": technical detail: files and functions from the "
        "routing map, the change at each, tests to add or run, AC numbers covered, \"change\": for an existing one, what "
        "you suggest changing and why, or \"\"}]}; read the story's sub-tasks in Jira first, and write nothing to Jira) → implement (diff + unit tests explained in plain "
        "English, compile/flake8; tests may not run because Artifactory returns 401, gate SDLC_05, then the PR "
        "as in rule 5) → test (/eval: test matrix and evidence as an artefact, gate SDLC_06) → release "
        "(/release: promotion plan and rollback as an artefact, gate SDLC_07) → kb-refresh (/kb-refresh: the "
        "knowledge-base documents this change makes stale, as an artefact, gate SDLC_08). "
        "Finish with `[SDLC] stage kb-refresh — finished`.",
        ticket_rule +
        "Record every approval with gate, approver name, role, decision, timestamp, the question asked and "
        "the answer verbatim. Do not use `.devin/rules/progress-lines.md` (it does not exist); rule 1 is the format.",
        "",
        mode,
        "",
        source,
    ])



CREATE_TAG = "create-epic-story"
CREATE_KINDS = ("Epic", "Story", "Epic with stories", "Epics from a roadmap")
CREATE_MAX_FILES = 10
CREATE_MAX_BYTES = 25 * 1024 * 1024
CREATE_FILE_TYPES = (".docx", ".doc", ".pdf", ".xlsx", ".xls", ".csv", ".pptx", ".txt", ".md", ".png", ".jpg", ".jpeg")


def create_request(body, writes):
    """Check a Create epic / story request from the Backlog screen.

    Returns (kind, text, files, dry_run, note); files are [(safe name, bytes)]. A live run needs the
    Argus's Backlog writes switched on; otherwise it is turned into a dry run and `note` says why."""
    req = body.get("create") or {}
    kind = str(req.get("kind") or "")
    if kind not in CREATE_KINDS:
        raise ApiError(400, "pick Epic, Story, Epic with stories or Epics from a roadmap")
    text = str(req.get("text") or "").strip()[:20000]
    files, total = [], 0
    for f in (req.get("files") or [])[:CREATE_MAX_FILES + 1]:
        name = re.sub(r"[^A-Za-z0-9._ -]", "_", os.path.basename(str(f.get("name") or "")))[:120].strip()
        if not name or os.path.splitext(name)[1].lower() not in CREATE_FILE_TYPES:
            raise ApiError(400, "%s: upload Word, PDF, Excel, CSV, PowerPoint, text or image files" % (name or "a file"))
        try:
            data = base64.b64decode(str(f.get("data") or ""), validate=True)
        except (ValueError, TypeError):
            raise ApiError(400, "%s could not be read" % name)
        total += len(data)
        files.append((name, data))
    if len(files) > CREATE_MAX_FILES:
        raise ApiError(400, "upload at most %d files" % CREATE_MAX_FILES)
    if total > CREATE_MAX_BYTES:
        raise ApiError(400, "the files add up to more than %d MB" % (CREATE_MAX_BYTES // (1024 * 1024)))
    if len(text) < 15 and not files:
        raise ApiError(400, "describe the need in a sentence or upload a file")
    if kind == "Epics from a roadmap" and not any(n.lower().endswith((".xlsx", ".csv")) for n, _ in files):
        raise ApiError(400, "upload the roadmap as an .xlsx or .csv file")
    dry_run, note = bool(req.get("dry_run", True)), ""
    if not dry_run and not writes:
        dry_run, note = True, "Backlog writes are off on this Argus, so this runs as a dry run."
    return kind, text, files, dry_run, note


def build_roadmap_prompt(text, files, dry_run, key):
    """Prompt for Epics from a roadmap: /epics-from-roadmap on the uploaded sheet, questions to the PO, epics
    as a dry-run preview — or created through the same Backlog path when writes are on and the PO approves."""
    sources = ["- %s — %s" % (name, url) for name, url in files]
    if dry_run:
        finish = ("6. Dry run: do not write to Jira or Confluence and do not commit. When every epic has its answers "
                  "post `[SDLC] artefact %s-EPIC-PLAN.md — ready` with the plan page (each epic field by field, the "
                  "Jira calls that a live run would make, the PO's answers verbatim, the source line of every epic). "
                  "That file is the deliverable." % key)
    else:
        finish = ("6. Live run: after the PO types `approved` on the plan — and only then — create each ready epic "
                  "through the Backlog create path (Backlog.create with the draft; service account, bearer auth "
                  "with %s, check /rest/api/2/myself once, never retry after HTTP 401 or 403). Attach the uploaded "
                  "document to the epic whose source it is. Post `[SDLC] note jira <KEY> — created` per epic, then "
                  "`[SDLC] artefact %s-EPIC-PLAN.md — ready` with the same page a dry run gives, plus the keys. "
                  "Epics that still have "
                  "open questions are not created. Do not commit or open a pull request." % (JIRA_TOKEN_ENV, key))
    return "\n".join([
        "Repository: @%s" % REPO_SLUG,
        "/epics-from-roadmap %s" % json.dumps(text or "(the uploaded spreadsheet is the input)"),
        "",
        f"This session was started from Create epics from a roadmap on the {WORKBENCH_TITLE} Backlog screen and "
        "is driven through it by a PO. Follow these reporting rules so Argus can render your work; they "
        "are additional to the repo rules.",
        "",
    ] + REPORTING_RULES + [
        "5. Download the roadmap file below and run `python3 " + team.FRAMEWORK + "/tools/roadmap_epics.py "
        "<file> --markdown` first: it maps the columns, drafts one epic per row against the epic contract in "
        ".devin/rules/jira-ticket-standards.yaml and lists what each epic still needs. Ask the PO those questions "
        "in one round per epic (`[SDLC] question round 1 — <n> questions`). Confluence links are read with the "
        "team service account; when a page cannot be read, ask the PO to upload the document instead and tell "
        "them plainly that this is ongoing: whenever that page changes they upload the newer copy. Every epic "
        "description ends with the Source line the tool gives. No stories, no estimates, no code.",
        finish,
        "",
        "Files uploaded by the PO:" if sources else "No files were uploaded.",
    ] + sources)


def build_create_prompt(kind, text, files, dry_run, key):
    """Prompt for Create epic / story: intake Q&A with the BSA and PO, then drafts in the rule-book shape."""
    sources = ["- %s — %s" % (name, url) for name, url in files]
    notes = text or "(no typed notes — the uploaded files are the input)"
    if dry_run:
        finish = ("7. Dry run: do not write to Jira or Confluence and do not commit. After the PO approves "
                  "SDLC_02b, post `[SDLC] artefact %s-%s.md — ready` with the whole result as Markdown: each "
                  "ticket's type, title, description, numbered acceptance criteria, points, specialty and phase, "
                  "the epic each story belongs to, the intake questions with their answers verbatim, and the "
                  "source file names. That file is the deliverable." % (key, "EPIC-STORIES"))
    else:
        finish = ("7. Live run: after the PO approves SDLC_02b — and only then — create the tickets in Jira "
                  "with the service account (bearer auth with %s, check /rest/api/2/myself once, never retry "
                  "after HTTP 401 or 403): the epic first, then each story linked to it, in the shapes of "
                  "`.devin/rules/jira-ticket-standards.yaml`, labelled `AI-Used` and `requested-by-<jira user of "
                  "the approver>`. Attach every source file listed below to the epic (or to the story when there "
                  "is no epic). Post `[SDLC] note jira <KEY> — created` for each ticket, then "
                  "`[SDLC] artefact %s-EPIC-STORIES.md — ready` with the same Markdown a dry run would give, "
                  "including the keys. Do not commit or open a pull request." % (JIRA_TOKEN_ENV, key))
    return "\n".join([
        "Repository: @%s" % REPO_SLUG,
        "/intake notes %s" % json.dumps(notes),
        "",
        f"This session was started from Create epic / story on the {WORKBENCH_TITLE} Backlog screen and is "
        "driven through it by a BSA or PO. Follow these reporting rules so Argus can render your "
        "work; they are additional to the repo rules.",
        "",
    ] + REPORTING_RULES + [
        "5. Scope: they asked for %s. Read every source file below first (download each URL), then run "
        "/intake in notes mode: the question rounds are answered by the BSA, who may forward a question to "
        "the PO. Present SDLC_01. Then run /research top-down only as far as the epic and story candidates, "
        "and present SDLC_02b to the PO. No code, no branch, no pull request, no estimates beyond story points."
        % ("one epic" if kind == "Epic" else "one story" if kind == "Story" else "an epic with its stories"),
        "6. Every draft must pass the rule book: titles '<Specialty> - <what> - <PHASE>' for stories, numbered "
        "acceptance criteria, an epic for every story, Issue Priority, and exactly one of AI-Used / AI-NA. "
        "List anything still missing at the gate instead of guessing.",
        finish,
        "",
        "Source files uploaded by the BSA/PO:" if sources else "No files were uploaded.",
    ] + sources)


def build_action_prompt(skill, text, dry_run):
    """Prompt for a one-off menu action (a single skill, not a full SDLC run)."""
    return "\n".join([
        "Repository: @%s" % REPO_SLUG,
        ("/%s %s" % (skill, text)).strip(),
        "",
        f"This session was started from the {WORKBENCH_TITLE} menu and is driven through it. Follow "
        "these reporting rules so Argus can render your work; they are additional to the repo rules.",
        "",
    ] + REPORTING_RULES + [
        "5. Start with `[SDLC] skill %s — started` and finish with `[SDLC] skill %s — finished`. Ask any question "
        "before the finished line: once it is posted Argus keeps your answer and closes this session." % (skill, skill),
        "6. Results. Argus opens your chat messages and artefacts in a result page; attachments do not "
        "reach it. Where the skill says to attach a file that is already in the repository, post "
        "`[SDLC] artefact <path from the repo root> — repo file` with no code block, and the page opens that "
        "file from the branch. Anything else you would attach, post as an artefact under rule 4. Write your "
        "closing message so it reads on its own as the answer.",
        "",
        dry_run_rule(dry_run, "UNTRACKED"),
    ])


def requester_note(person, role, previewing):
    """The person and role picked in the page, so a session started from it uses them."""
    if not person and not role:
        return ""
    who = "%s (%s)" % (person["name"] or person["jira_user"], person["jira_user"]) if person else "nobody picked"
    return ("Requester: %s, in the role %s%s, as picked in the %s. Use this person and role for the role "
            "defaults, lens, menus and gate checks; do not work them out again from the roster." % (
                who, role["label"] if role else "none", " (picked under View Argus as)" if previewing else "",
                WORKBENCH_TITLE))


def chat_story(text):
    first = (text.strip().splitlines() or [""])[0].strip()
    return {"key": "Chat", "custom": False, "summary": first if len(first) <= 120 else first[:117].rstrip() + "…",
            "description": text.strip(), "status": "chat", "assignee": "", "reporter": "", "labels": [],
            "points": "", "url": ""}


def assistant_prompt():
    """Opening rules for the one Argus assistant session a person gets each day."""
    return "\n".join([
        f"This is the {WORKBENCH_TITLE} assistant session for one person for one day. Menu items, chats and "
        "follow-ups from Argus all come into this session as separate requests, and Argus shows "
        "each answer on its own card.",
        "Each request starts with a line `[SDLC] request <id>`. Work on one request at a time, in the order they "
        "arrive. Start every reply with a line `[SDLC] reply <id>` naming the request it answers, and keep the "
        "work, files and decisions of one request out of the others. Do not end this session when a request is "
        "done; wait for the next one.",
        "",
    ])


def request_text(run_id, prompt):
    return "[SDLC] request %s\n%s" % (run_id, prompt)


def own_messages(msgs, run_id):
    """The messages of one request in a shared session: from its request line to the next request or reply line."""
    out, mine = [], False
    for m in msgs:
        tag = REQUEST_RE.search(m.get("message") or "")
        if tag:
            mine = tag.group(2) == run_id
        if mine:
            out.append(m)
    return out


def build_chat_prompt(text):
    """Prompt for a plain chat started from Argus: no SDLC stages, no gates."""
    return "\n".join([
        "Repository: @%s" % REPO_SLUG,
        "",
        text.strip(),
        "",
        f"This is a plain chat started from the {WORKBENCH_TITLE}, not an SDLC run: answer in chat. Do not "
        "commit, push, open a pull request, or write to Jira or Confluence unless the person asks for it here.",
    ])


_last_fetch = [0.0]
_fetched = [False]
_FETCH_LOCK = threading.Lock()


def repo_rel(path):
    """A repository path the result page may open, or None: inside the repo, a readable type, no dot folders."""
    rel = os.path.normpath((path or "").strip().lstrip("/")).replace(os.sep, "/")
    if rel.startswith("..") or rel.startswith(".") or "/." in rel:
        return None
    if os.path.splitext(rel)[1].lower() not in REPO_FILE_TYPES:
        return None
    return rel


def _fetch_kb(env):
    """git fetch of the KB branch; releases _FETCH_LOCK, which the caller holds."""
    try:
        done = subprocess.run(["git", "-c", "http.sslVerify=false", "fetch", "-q", "origin", KB_BRANCH],
                              cwd=ROOT, capture_output=True, timeout=60, env=env)
        if done.returncode == 0:
            _fetched[0] = True
    except (OSError, subprocess.SubprocessError):
        pass
    finally:
        _FETCH_LOCK.release()


def _git_branch(*args):
    """stdout of a git command against origin/<KB branch>, fetched at most every FETCH_EVERY_SECONDS; None if unreadable."""
    if not READ_REMOTE:
        return None
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    if time.time() - _last_fetch[0] > FETCH_EVERY_SECONDS and _FETCH_LOCK.acquire(blocking=False):
        # One fetch at a time, and a failed one waits its turn too. After the first good fetch it runs in the
        # background, so a page never waits on Bitbucket and reads what was fetched last.
        _last_fetch[0] = time.time()
        if _fetched[0]:
            threading.Thread(target=_fetch_kb, args=(env,), daemon=True, name="argus-kb-fetch").start()
        else:
            _fetch_kb(env)
    try:
        done = subprocess.run(["git"] + list(args), cwd=ROOT, capture_output=True, timeout=30, env=env)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def repo_file(rel):
    """(bytes, where it came from) for a repo file: the remote KB branch when reachable, else this checkout."""
    data = _git_branch("show", "origin/%s:%s" % (KB_BRANCH, rel))
    if data is not None:
        return data, "origin/" + KB_BRANCH
    with open(os.path.join(ROOT, rel), "rb") as fh:
        return fh.read(), "this machine's checkout"


def repo_list(rel_dir):
    """File names directly inside a repo folder, from the KB branch when reachable, else this checkout."""
    out = _git_branch("ls-tree", "--name-only", "origin/%s" % KB_BRANCH, rel_dir.rstrip("/") + "/")
    if out is not None:
        return sorted(os.path.basename(n) for n in out.decode("utf-8").split("\n") if n)
    path = os.path.join(ROOT, rel_dir)
    return sorted(os.listdir(path)) if os.path.isdir(path) else []


class BranchFiles:
    """Sources for gen_reference_pages read from the KB branch, so a page follows the branch without a rebuild."""

    def read(self, rel):
        return repo_file(rel)[0].decode("utf-8")

    def read_bytes(self, rel):
        return repo_file(rel)[0]

    def list(self, rel_dir):
        return repo_list(rel_dir)


PAGE_BAR = """<div id="wb-bar" style="position:sticky;top:0;z-index:50;display:flex;flex-wrap:wrap;gap:10px;
align-items:center;padding:8px 16px;background:#4a1fb8;color:#fff;font:13px system-ui,sans-serif">
<b>%(title)s</b><span style="opacity:.85">A ready-made page from %(source)s: no Devin session
was started to show it.</span><span id="wb-state" style="flex-basis:100%%;opacity:.9" hidden></span></div>
<script>
document.addEventListener("DOMContentLoaded", function () {
  document.querySelectorAll("[data-wb-skill]").forEach(function (b) {
    b.hidden = false;
    b.addEventListener("click", function () {
      var win = window.open("", "_blank"), note = document.getElementById("wb-state");
      if (win) { win.document.write("<p style='font-family:sans-serif;padding:24px'>Starting a Devin session\u2026</p>"); }
      fetch("/api/actions", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ skill: b.dataset.wbSkill, text: b.dataset.wbText || "", dry_run: false, fresh: true }) })
        .then(function (r) {
          return r.json().then(function (j) { if (!r.ok) { throw new Error(j.error || r.statusText); } return j; });
        })
        .then(function (run) {
          if (win) { win.location = "/run/" + run.id; } else { location = "/run/" + run.id; }
          note.hidden = false;
          note.textContent = "Devin is writing it. When the change is merged this page shows it on the next load.";
        })
        .catch(function (e) { if (win) { win.close(); } note.hidden = false; note.textContent = e.message; });
    });
  });
});
</script>
"""


def with_bar(page, bar):
    """Put Argus bar at the top of a page's body."""
    m = re.search(r"<body[^>]*>", page)
    return page[:m.end()] + bar + page[m.end():] if m else bar + page


def reference_page(name):
    """A ready-made menu page (help, catalogue, onboarding, presentation) from the KB branch, as bytes."""
    if name == "presentation":
        data, source = repo_file(PRESENTATION_PAGE)
        page = data.decode("utf-8")
    elif name == "team-insights":
        page, source = team_insights_page()
    elif name == "delivery-teams":
        data, source = repo_file(DELIVERY_TEAMS_PAGE)
        page = data.decode("utf-8")
    elif name in gen_reference_pages.PAGES + gen_reference_pages.LIVE_PAGES:
        source = "origin/" + KB_BRANCH if _git_branch("rev-parse", "origin/" + KB_BRANCH) else "this machine's checkout"
        page = gen_reference_pages.render(name, BranchFiles())
    else:
        raise ApiError(404, "no page called %r" % name)
    return with_bar(page, PAGE_BAR % {"source": artifact_kit.esc(source), "title": artifact_kit.esc(WORKBENCH_TITLE)}).encode("utf-8")


def team_insights_page():
    """The monthly Team Insights decks, newest first, with a button to run the month now; (page, source)."""
    esc = artifact_kit.esc
    try:
        decks = sorted((n for n in repo_list(TEAM_INSIGHTS_DECKS) if re.match(r"^TEAM-INSIGHTS-\d{4}-\d{2}\.html$", n)),
                       reverse=True)
    except OSError:
        decks = []
    source = "origin/" + KB_BRANCH if _git_branch("rev-parse", "origin/" + KB_BRANCH) else "this machine's checkout"
    if decks:
        latest = TEAM_INSIGHTS_DECKS + "/" + decks[0]
        body = ('<p><a class="a-btn a-btn--primary" href="/repo-file?path=%s" target="_blank" rel="noopener">Open the '
                '%s deck</a></p><h2 class="a-section__title">Every month</h2><ul>%s</ul>'
                % (esc(latest), esc(decks[0][14:21]), "".join(
                    '<li><a href="/repo-file?path=%s/%s" target="_blank" rel="noopener">%s</a></li>'
                    % (esc(TEAM_INSIGHTS_DECKS), esc(n), esc(n[14:21])) for n in decks)))
    else:
        body = "<p>No deck yet. The monthly Team Insights run writes the first one.</p>"
    body += ('<p>The numbers, prompts, skill gaps and learning plan behind each deck are on the Tech Lead dashboard under '
             '<a href="/dashboard" target="_blank" rel="noopener">Team Insights</a>, and the recommended framework '
             'changes under Framework feedback.</p><p><button type="button" class="a-btn a-btn--outline" '
             'data-wb-skill="team-insights" hidden>Run Team Insights for last month now</button></p>')
    page = artifact_kit.render_page("Team Insights decks", '<section class="a-section">%s</section>' % body,
                                    subtitle="How the team used Devin each month: wins named, learning points anonymous")
    return page, source


def markdown_page(title, text, note=""):
    """Markdown as a readable page rather than raw text."""
    heading, body = gen_reference_pages.split_title(text)
    return artifact_kit.render_page(heading or title, '<article class="ref-doc">%s</article>' %
                                    artifact_kit.markdown_html(body), subtitle=artifact_kit.esc(note),
                                    extra_css=gen_reference_pages.CSS).encode("utf-8")


VALIDATION_BAR = """<div id="wb-bar" style="position:sticky;top:0;z-index:50;display:flex;flex-wrap:wrap;gap:10px;
align-items:center;padding:10px 16px;background:#4a1fb8;color:#fff;font:14px system-ui,sans-serif">
<b>%(title)s</b><span style="opacity:.85">Questions from %(source)s</span>
<span style="flex:1"></span>
<label title="A dry run shows what would change; a real run commits to the knowledge base">
<input type="checkbox" id="wb-dry" checked> Dry run</label>
<button type="button" id="wb-send">Send my answers to Devin</button>
<button type="button" class="ghost" id="wb-refresh" style="background:#fff">Look for new questions</button>
<span id="wb-state" style="width:100%%;opacity:.9"></span></div>
<script>
(function () {
  function $(id) { return document.getElementById(id); }
  function start(url, body) {
    var win = window.open("", "_blank");
    if (win) { win.document.write("<p style='font-family:sans-serif;padding:24px'>Starting a Devin session\u2026</p>"); }
    return fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
      .then(function (r) {
        return r.json().then(function (j) { if (!r.ok) { throw new Error(j.error || r.statusText); } return j; });
      })
      .then(function (run) { if (win) { win.location = "/run/" + run.id; } else { window.location = "/run/" + run.id; } })
      .catch(function (e) { if (win) { win.close(); } $("wb-state").textContent = e.message; });
  }
  $("wb-send").addEventListener("click", function () {
    $("build").click();
    var block = $("yaml").value;
    if (!/decision:/.test(block)) { $("wb-state").textContent = "Answer at least one question first."; return; }
    $("wb-state").textContent = "Sending your answers; the run opens in a new tab.";
    start("/api/validation/answers", { answers: block, dry_run: $("wb-dry").checked });
  });
  $("wb-refresh").addEventListener("click", function () {
    $("wb-state").textContent = "Devin is checking the knowledge base for new questions. " +
      "A real run commits them, and they show here when you reload.";
    start("/api/actions", { skill: "document-validation", text: "new", dry_run: $("wb-dry").checked });
  });
})();
</script>
"""


def validation_page():
    """The validation form rendered from the registry on the KB branch, with Argus's send bar on top."""
    registry, source = repo_file(VALIDATION_REGISTRY)
    os.makedirs(VALIDATION_DIR, exist_ok=True)
    src = os.path.join(VALIDATION_DIR, "KB_OPEN_QUESTIONS.yaml")
    out = os.path.join(VALIDATION_DIR, "KB-VALIDATION-FORM.html")
    with open(src, "wb") as fh:
        fh.write(registry)
    done = subprocess.run([sys.executable, GEN_VALIDATION, src, "-o", out], capture_output=True, text=True,
                          timeout=120, cwd=ROOT)
    if done.returncode:
        raise ApiError(502, "the validation form did not render: " + (done.stderr or done.stdout)[-600:])
    with open(out, encoding="utf-8") as fh:
        page = fh.read()
    bar = VALIDATION_BAR % {"source": source.replace("&", "&amp;").replace("<", "&lt;"),
                            "title": artifact_kit.esc(WORKBENCH_TITLE)}
    at = max(page.find("<main"), 0)
    return (page[:at] + bar + page[at:]).encode("utf-8")


def action_story(skill, text):
    info = skill_info(skill) or {"label": skill}
    return {"key": "/" + skill, "action": skill, "custom": False, "summary": text or info["label"],
            "description": text, "status": "menu action", "assignee": "", "reporter": "", "labels": [],
            "points": "", "url": ""}


# Gates that sit just before code changes start: the developer may add the story's sub-tasks there.
SUBTASK_GATES = ("SDLC_04", "HOTFIX_PLAN_CODE")


def subtask_gate(gate_id):
    return any((gate_id or "").startswith(g) for g in SUBTASK_GATES)


def run_story_key(run):
    """The Jira story a run works on: the ticket it started from, or the one created at the intake gate."""
    story = run.get("story") or {}
    key = story.get("jira_key") or (run.get("jira_story") or {}).get("key") or ("" if story.get("custom") else story.get("key"))
    return key if re.match(r"^[A-Z][A-Z0-9]+-\d+$", key or "") else ""


SUBTASK_PLAN_RE = re.compile(r"-SUBTASK-PLAN\.json$", re.I)


def subtask_plan(run):
    """Devin's suggested sub-tasks from the latest *-SUBTASK-PLAN.json artefact /plan posts before SDLC_04."""
    arts = [a for a in run.get("artefacts") or [] if SUBTASK_PLAN_RE.search(a.get("name") or "")]
    if not arts:
        return []
    try:
        data = json.loads(re.sub(r"^\s*```\w*\s*|\s*```\s*$", "", arts[-1].get("body") or ""))
    except ValueError:
        return []
    out = []
    for st in (data.get("subtasks") if isinstance(data, dict) else data) or []:
        if isinstance(st, dict) and str(st.get("summary") or "").strip():
            out.append({k: str(st.get(k) or "").strip()[:4000] for k in ("key", "summary", "hours", "description", "change")})
    return out[:backlog.MAX_SUBTASKS]


def subtask_lines(rows):
    out = []
    for r in rows:
        out.append("- %s%s | %s" % (r["key"] + " ← " if r.get("key") else "", r["summary"], backlog.jira_duration(r["hours"])))
        if r.get("description"):
            out.append("  " + r["description"].replace("\n", "\n  "))
    return "\n".join(out)


def subtask_request(key, rows, assignee, dry_run):
    """The note sent with the gate decision when the session, not Argus, writes the sub-tasks."""
    total = backlog.jira_duration(sum(r["hours"] for r in rows))
    if dry_run:
        return ("\n[SDLC] note subtasks — dry run: the developer listed these sub-tasks for %s with their original "
                "estimates (%s in total). Do not write them to Jira; post them as the artefact `%s-SUBTASKS.md` and "
                "say which sub-task each code change belongs to.\n%s" % (key, total, key, subtask_lines(rows)))
    return ("\n[SDLC] note subtasks — the developer confirmed this Jira write. Before any code change, with the Jira "
            "service account: for each line with a key (KEY ← title), update that sub-task of %s to the title, original "
            "estimate and description given, only if it is a sub-task of %s; for each line without a key, create a "
            "Sub-task under %s with the title, original estimate and description given (%s in total), labels AI-Used "
            "and %s, assignee %s, status Open, skipping any whose title is already a sub-task of %s. Then post "
            "`[SDLC] note subtasks <KEY>, <KEY> — created` (and `— updated` for the others) and log the work against "
            "them.\n%s" % (key, key, key, total, backlog.DEVIN_CREATED_LABEL, assignee or "nobody", key, subtask_lines(rows)))


def forward_text(gate_id, person, note, items=""):
    """The chat line that hands an open gate to someone else through the send-approval skill."""
    items = re.sub(r"[^0-9, ]", "", items or "").strip(" ,")
    return '/send-approval %s to %s%s "%s"' % (gate_id, person, " items " + items if items else "",
                                               note.replace('"', "'").strip())


# --------------------------------------------------------------------------- spec → Jira story

SPEC_NAME_RE = re.compile(r"spec", re.I)
HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$")


def spec_sections(body):
    """Split a Markdown spec into {lower-case heading: text}. Text before the first heading is keyed ''."""
    sections, cur, buf = {}, "", []
    for line in body.splitlines():
        m = HEADING_RE.match(line)
        if m:
            sections[cur] = "\n".join(buf).strip()
            cur, buf = m.group(1).strip().lower(), []
        else:
            buf.append(line)
    sections[cur] = "\n".join(buf).strip()
    return sections


def pick_section(sections, *needles):
    for key, text in sections.items():
        if text and any(n in key for n in needles):
            return text
    return ""


def story_from_run(run, assignee_display):
    """Build the Jira Story fields from the intake spec artefact (or, failing that, the requirement text)."""
    specs = [a for a in run["artefacts"] if SPEC_NAME_RE.search(a["name"] or "")]
    spec = specs[-1] if specs else None
    story = run["story"]
    body = (spec or {}).get("body") or ""
    sections = spec_sections(body) if body else {}
    acceptance = pick_section(sections, "acceptance")
    user_story = pick_section(sections, "user story", "requirement", "summary", "problem", "goal")
    title = ""
    m = re.search(r"^\s{0,3}#\s+(.+)$", body, re.M)
    if m:
        title = re.sub(r"^REQ-\d+\s*[—:-]\s*", "", m.group(1)).strip()
    summary = title or story["summary"]
    if not re.search(r"\s-\s(%s)$" % "|".join(map(re.escape, team.PHASES)), summary):
        summary = summary + " - " + team.PHASES[0]
    lines = ["*Requirement as typed:*" if story.get("custom") else "*Source story:* %s" % story["key"],
             story["description"] if story.get("custom") else story["summary"], ""]
    if user_story:
        lines += ["*From the intake spec:*", user_story, ""]
    elif body:
        lines += ["*Intake spec (%s):*" % spec["name"], "{noformat}", body[:6000], "{noformat}", ""]
    lines += ["Created from Argus at intake gate approval by %s." % (assignee_display or "the console user"),
              "Devin session: %s" % (run.get("session_url") or "(none)")]
    if not acceptance:
        acceptance = ("Acceptance criteria were not found as a section of the intake spec. Copy them from the spec "
                      "artefact in the console before this story is groomed.")
    return summary, "\n".join(lines), acceptance, spec["name"] if spec else None


# --------------------------------------------------------------------------- run parsing

def norm_stage(name):
    n = re.sub(r"\s+", " ", name.strip().lower())
    return STAGE_ALIASES.get(n, n)


GATE_ITEM_RE = re.compile(r"^\s*(?:\[(\d+)\]|(\d+)[.)])\s+(.+?)\s*$")


def gate_items(text):
    """The numbered decision items of a presented gate; one item when none are listed."""
    lines = text.splitlines()
    start = next((i + 1 for i, line in enumerate(lines) if re.match(r"^[\s*#]*decision items", line, re.I)), None)
    items = []
    for line in lines[start:] if start is not None else lines:
        m = GATE_ITEM_RE.match(line)
        if m and (start is not None or m.group(1)):
            items.append({"n": int(m.group(1) or m.group(2)), "text": m.group(3).strip("* ")})
        elif start is not None and items and line.strip():
            break
    seen, out = set(), []
    for item in items:
        if item["n"] not in seen:
            seen.add(item["n"])
            out.append(item)
    return out or [{"n": 1, "text": "Approve this gate as presented"}]


def items_reply(gate_id, wanted, picks):
    """One reply for a gate decided item by item; any rejected item rejects the gate."""
    if len(wanted) == 1:
        verdict, note = picks[wanted[0]]
        if verdict == "reject":
            return "rejected %s — %s" % (gate_id, note)
        return "approved %s with notes: %s" % (gate_id, note) if note else "approved %s" % gate_id
    nums = lambda ns: ",".join(str(n) for n in ns)  # noqa: E731
    ok = [n for n in wanted if picks[n][0] == "approve"]
    bad = [n for n in wanted if picks[n][0] == "reject"]
    if not bad:
        notes = "; ".join("%d: %s" % (n, picks[n][1]) for n in ok if picks[n][1])
        return "approved %s — approved %s" % (gate_id, nums(ok)) + ("; notes: " + notes if notes else "")
    parts = (["approved %s" % nums(ok)] if ok else []) + ["rejected %d — %s" % (n, picks[n][1]) for n in bad]
    return "rejected %s — %s" % (gate_id, "; ".join(parts))


def parse_devin_message(text):
    """Turn one Devin chat message into console events, questions, gates and artefacts."""
    events, questions, artefacts, diffs, pr = [], [], [], [], None
    gate = None
    lines = text.splitlines()
    fences = FENCE_RE.findall(text)
    fence_i = 0
    in_round = False
    for i, line in enumerate(lines):
        m = SDLC_RE.match(line)
        if m:
            kind = m.group("kind").lower()
            name = m.group("name").strip()
            detail = m.group("detail").strip()
            kind = "artefact" if kind == "artifact" else kind
            events.append({"kind": kind, "name": name, "detail": detail})
            if kind == "question round":
                in_round = "started" in detail.lower() or "finished" not in detail.lower()
            if kind == "gate" and "present" in detail.lower():
                gid = GATE_RE.search(name or "")
                gate = {"id": gid.group(1) if gid else (name or "GATE"), "text": "\n".join(lines[i + 1:]).strip() or text}
            if kind == "artefact" and "repo file" in detail.lower():
                artefacts.append({"name": name, "detail": detail, "body": "", "repo_file": True})
                continue
            if kind in ("artefact", "diff", "pr"):
                body = ""
                while fence_i < len(fences):
                    lang, content = fences[fence_i]
                    fence_i += 1
                    body = content
                    break
                if kind == "artefact":
                    artefacts.append({"name": name, "detail": detail, "body": body})
                elif kind == "diff":
                    diffs.append({"path": name, "why": detail, "body": body})
                else:
                    pr = {"branch": name, "detail": detail, "body": body}
            continue
        q = NUMBERED_RE.match(line)
        if q and (in_round or "?" in q.group(2)) and not gate:
            questions.append({"n": int(q.group(1)), "text": q.group(2)})
    if gate is None and not events and GATE_RE.search(text) and re.search(r"\bapprov", text, re.I) and re.search(r"reject", text, re.I):
        gate = {"id": GATE_RE.search(text).group(1), "text": text}
    if gate:
        questions = []
        gate["items"] = gate_items(gate["text"])
    return events, questions, gate, artefacts, diffs, pr


# --------------------------------------------------------------------------- state

def load_state_file(path, default, kind):
    """A state file's JSON, or `default` when it is missing. A damaged file is moved aside as <name>.bad-<time>
    and noted, so Argus still starts; /api/sync brings the runs back from their Devin Cloud tags."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, kind):
            return data
        err = "it holds a %s, not a %s" % (type(data).__name__, kind.__name__)
    except FileNotFoundError:
        return default
    except (OSError, ValueError) as exc:
        err = "%s: %s" % (type(exc).__name__, exc)
    bad = "%s.bad-%s" % (path, time.strftime("%Y%m%d-%H%M%S"))
    try:
        os.replace(path, bad)
    except OSError:
        bad = path
    OBSERVER.note("state", "%s could not be read (%s); kept as %s and Argus started without it. "
                           "Load my runs brings past runs back from Devin Cloud." % (os.path.basename(path), err, bad))
    return default


class Store:
    """Every run on this machine, saved in runs.json. `lock` is re-entrant: hold it to read or change runs;
    save() takes it to copy the runs and writes the file after letting go, newest copy last."""

    def __init__(self):
        self.lock = threading.RLock()
        self._write_lock = threading.Lock()
        self._copied = self._written = 0
        self.dirty, self.saved_at = False, 0.0
        os.makedirs(STATE_DIR, exist_ok=True)
        self.runs = load_state_file(STATE_PATH, {}, dict)
        for run in self.runs.values():
            migrate_run(run)
        self.deleted = set(load_state_file(DELETED_PATH, [], list))

    def delete(self, run_id):
        """Drop a run for good; its session id is remembered so /api/sync never brings it back."""
        with self.lock:
            run = self.runs.pop(run_id)
            if run.get("session_id"):
                self.deleted.add(run["session_id"])
                tmp = DELETED_PATH + ".tmp"
                with open(tmp, "w", encoding="utf-8") as fh:
                    json.dump(sorted(self.deleted), fh)
                os.replace(tmp, DELETED_PATH)
        self.save()
        return run

    def touch(self):
        """Something small changed (when a run was last read): it goes to disk with the next save."""
        self.dirty = True

    def save(self):
        with self.lock:
            data = json.dumps(self.runs, separators=(",", ":"))
            self._copied += 1
            seq = self._copied
            self.dirty, self.saved_at = False, time.time()
        with self._write_lock:
            if seq < self._written:
                return
            tmp = STATE_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(data)
            os.replace(tmp, STATE_PATH)
            self._written = seq

    def sdlc_started(self, key):
        """Why the ticket's description and acceptance criteria are fixed: the first SDLC run on it, or ""."""
        with self.lock:
            runs = [r for r in self.runs.values() if r.get("kind", "sdlc") == "sdlc"
                    and (r.get("story") or {}).get("key") == key and r.get("id") not in self.deleted]
        if not runs:
            return ""
        first = min(runs, key=lambda r: r.get("created_at") or 0)
        return "SDLC started on it %s%s" % (time.strftime("%Y-%m-%d", time.localtime(first.get("created_at") or 0)),
                                           " (dry run)" if first.get("dry_run") else "")

    def new_run(self, story, dry_run, session, kind="sdlc", created_at=None, save=True):
        run = {
            "id": uuid.uuid4().hex[:10],
            "story": story,
            "dry_run": dry_run,
            "session_id": session.get("session_id"),
            "session_url": session.get("url"),
            "created_at": created_at or time.time(),
            "kind": kind,
            "title": session.get("title"),
            "status": session.get("status_enum") or session.get("status", "new"),
            "status_detail": None,
            "stage": "intake" if kind == "sdlc" else None,
            "stages": {s: "pending" for s in STAGES} if kind == "sdlc" else {},
            "events": [],
            "messages": [],
            "seen": [],
            "pending_questions": None,
            "pending_gate": None,
            "artefacts": [],
            "diffs": [],
            "pr": None,
            "pull_requests": [],
            "forwarded": [],
            "tags": list(session.get("tags") or []),
            "error": None,
        }
        if kind == "sdlc" and not created_at:
            run["stages"]["intake"] = "running"
        with self.lock:
            self.runs[run["id"]] = run
        if save:
            self.save()
        return run

    def session_messages(self, session_id):
        """How many messages Argus holds for one Cloud session, across every run in it."""
        with self.lock:
            return sum(len(r.get("messages") or []) for r in self.runs.values() if r.get("session_id") == session_id)

    def handover_text(self, session_id):
        """What a new session needs to carry on from an earlier one: its link, the requests and the last messages."""
        with self.lock:
            runs = sorted((r for r in self.runs.values() if r.get("session_id") == session_id),
                          key=lambda r: r["created_at"])
        if not runs:
            return ""
        lines = ["Handover: this carries on from the earlier session %s, which had %d messages."
                 % (runs[0].get("session_url") or session_id, self.session_messages(session_id)),
                 "Requests in it:"]
        lines += ["- %s" % (r["story"].get("summary") or r["story"].get("key") or r["id"])[:120] for r in runs[-12:]]
        last = [m for r in runs for m in (r.get("messages") or []) if (m.get("text") or "").strip()][-6:]
        if last:
            lines.append("Last messages:")
            lines += ["- %s: %s" % ("you" if m.get("source") == "user" else "Devin",
                                    re.sub(r"\s+", " ", m["text"]).strip()[:400]) for m in last]
        return "\n".join(lines + ["", ""])

    def assistant_host(self, owner):
        """The newest run in this person's assistant session for today, if that session is still open."""
        with self.lock:
            found = [r for r in self.runs.values() if r.get("assistant") == owner and r.get("session_id")
                     and r.get("status") not in ENDED]
        return max(found, key=lambda r: r["created_at"]) if found else None

    def recent_action(self, skill, text, dry_run, now=None, requester=""):
        """The newest menu run of the same skill, input, mode and requester from the last REUSE_SECONDS that did not fail."""
        now = now or time.time()
        with self.lock:
            found = [r for r in self.runs.values()
                     if r.get("kind") == "action" and r["story"].get("action") == skill
                     and (r["story"].get("input") or "") == text and bool(r.get("dry_run")) == dry_run
                     and (r.get("requester") or "") == requester
                     and now - r.get("created_at", 0) < REUSE_SECONDS and r.get("status") not in ENDED]
        return max(found, key=lambda r: r["created_at"]) if found else None

    def adopt(self, sessions, owner_email=""):
        """Add runs for Argus/console sessions found on Devin that this machine has not seen yet (takes the lock)."""
        with self.lock:
            added = self._adopt(sessions, owner_email)
        if added:
            self.save()
        return added

    def _adopt(self, sessions, owner_email):
        known = {r.get("session_id") for r in self.runs.values()}
        added = 0
        for info in sessions:
            sid = info.get("session_id")
            tags = info.get("tags") or []
            if not sid or sid in known or sid in self.deleted or DELETED_TAG in tags \
                    or not (WORKBENCH_TAG in tags or LEGACY_TAG in tags):
                continue
            who = (info.get("requesting_user_email") or "").lower()
            if owner_email and who and who != owner_email.lower():
                continue
            kind, story = run_from_tags(tags, info.get("title") or "")
            run = self.new_run(story, "live" not in tags, info, kind, created_at=iso_epoch(info.get("created_at")),
                               save=False)
            run["archived"] = ARCHIVED_TAG in tags
            known.add(sid)
            added += 1
        return added

    def public(self, run):
        with self.lock:
            return self._public(run)

    def _public(self, run):
        r = dict(run)
        r.pop("seen", None)
        r["subtask_plan"] = subtask_plan(run)
        r["complete"] = sdlc_complete(run)
        if run.get("session_id"):
            r["session_messages"] = self.session_messages(run["session_id"])
            r["long_session"] = r["session_messages"] >= LONG_SESSION
        return r


TRACE_AGENTS = {"intake": "intake (BSA)", "research": "research (BSA)", "plan": "plan (Tech Lead)",
                "implement": "implement (Developer)", "test": "eval (QA)", "release": "release (Release Manager)",
                "kb-refresh": "documenter (KB)"}


def trace_fields(detail, first):
    """`<first>; why: ...; gain: ...; result: ...` from a trace line's detail."""
    parts = re.split(r";\s*(why|gain|result):\s*", detail, flags=re.I)
    entry = {first: parts[0].strip()}
    for label, text in zip(parts[1::2], parts[2::2]):
        entry[label.lower()] = text.strip()
    return entry


def trace_tree(run):
    """What the run actually loaded and decided, per stage, from the [SDLC] lines the session printed.

    Only evidence the session reported is shown: there are no token counts or similarity scores in this
    pipeline, so none are invented. `stages` is in STAGES order; a stage without events is still listed so
    the panel can show it as queued or done."""
    stages = {}
    for name in STAGES:
        stages[name] = {"stage": name, "agent": TRACE_AGENTS[name], "status": (run.get("stages") or {}).get(name, "pending"),
                        "agents": [], "skills": [], "playbooks": [], "rules": [], "kb": [], "chains": [], "ontology": [], "graph": [],
                        "drift": [], "sync": [], "qa": [], "evidence": [], "tests": [], "contract": [], "routes": [], "decisions": [], "gates": [], "notes": []}
    current = run.get("stage") or STAGES[0]
    running = None   # the stage whose `started` line came last: a line belongs to the stage running when it was printed
    for ev in run.get("events") or []:
        kind, name, detail = ev.get("kind"), ev.get("name") or "", ev.get("detail") or ""
        d = detail.lower()
        if kind == "stage":
            if norm_stage(name) in stages and not re.search(r"finish|done|complete|abandon|fail|block", d):
                running = norm_stage(name)
            continue
        node = stages.get(running or current) or stages[STAGES[0]]
        if kind in ("agent", "skill", "playbook"):
            bucket = node[kind + "s"]
            why = re.sub(r"^(started|finished|done)\b[\s—–:-]*", "", detail).strip()
            state = "finished" if re.search(r"finish|done|complete", d) else "running"
            prev = next((x for x in bucket if x["name"] == name), None)
            if prev:
                prev["state"] = state
                if why:
                    prev["why"] = why
            else:
                bucket.append({"name": name, "state": state, "why": why})
        elif kind in ("kb", "rule"):
            m = re.match(r"^(loaded|read|hit|skipped|skip|deferred|not loaded)\b[\s—–:-]*(.*)$", detail, re.I)
            verdict = (m.group(1).lower() if m else ("loaded" if "load" in d or "read" in d else "noted"))
            verdict = {"read": "loaded", "hit": "loaded", "skip": "skipped", "not loaded": "skipped"}.get(verdict, verdict)
            node["rules" if kind == "rule" else "kb"].append(
                {"path": name, "verdict": verdict, "why": (m.group(2) if m else detail).strip()})
        elif kind == "chain":
            node["chains"].append({"id": name, "what": detail})
        elif kind in ("ontology", "graph"):
            command, _, term = name.partition(" ")
            entry = {"command": command, "term": term.strip().strip('"'), "found": "", "why": "", "gain": ""}
            entry.update(trace_fields(detail, "found"))
            node[kind].append(entry)
        elif kind in ("drift", "sync", "qa", "evidence", "tests", "contract"):
            entry = {"artifact": name, "what": "", "why": "", "result": ""}
            entry.update(trace_fields(detail, "what"))
            node[kind].append(entry)
        elif kind == "route":
            node["routes"].append({"entry": name, "detail": detail})
        elif kind == "decision":
            node["decisions"].append({"what": name, "detail": detail})
        elif kind == "gate":
            gid = GATE_RE.search(name)
            node["gates"].append({"id": gid.group(1) if gid else name, "state": detail})
        elif kind == "note":
            node["notes"].append({"name": name, "detail": detail})
    pending = run.get("pending_gate") or {}
    waiting = None
    if pending.get("id"):
        info = gate_info(pending["id"]) or {}
        waiting = {"id": pending["id"], "name": info.get("name") or "", "role": info.get("required_role") or "",
                   "timeout_hours": info.get("timeout_hours") or ""}
    return {"current": current, "pending_gate": waiting, "stages": [stages[n] for n in STAGES]}


def trace_text(run):
    """The Trace window as plain text, every stage, for download."""
    t = trace_tree(run)
    story = run.get("story") or {}
    out = ["Trace — %s %s" % (story.get("key") or run.get("id") or "", story.get("summary") or ""),
           "Only what the session reported with [SDLC] lines (.devin/rules/workbench-trace.md).", ""]

    def why(x):
        return ("  why: " + x["why"]) if x.get("why") else ""
    for s in t["stages"]:
        out.append("%s · agent: %s · %s" % (s["stage"].upper(), s["agent"], s["status"]))
        branches = [("Agents active", ["%s (%s)" % (a["name"], a["state"]) for a in s["agents"]]),
                    ("Routing", ["%s  %s" % (r["entry"], r["detail"]) for r in s["routes"]]),
                    ("Skills invoked", ["skill:%s (%s)%s" % (k["name"], k["state"], why(k)) for k in s["skills"]]),
                    ("Playbooks", ["%s%s" % (k["name"], why(k)) for k in s["playbooks"]]),
                    ("Rulebooks loaded", ["%s %s%s" % (r["path"], r["verdict"], why(r)) for r in s["rules"]]),
                    ("Knowledge base", ["%s %s%s" % (k["path"], k["verdict"].upper(), why(k)) for k in s["kb"]]),
                    ("Matrix chains", ["%s — %s" % (c["id"], c["what"]) for c in s["chains"]]),
                    ("Ontology", ["%s %s — %s%s%s" % (o["command"], o["term"], o["found"],
                                                    ("  why: " + o["why"]) if o["why"] else "",
                                                    ("  gain: " + o["gain"]) if o["gain"] else "") for o in s["ontology"]]),
                    ("Link graph", ["%s %s — %s%s%s" % (o["command"], o["term"], o["found"],
                                                       ("  why: " + o["why"]) if o["why"] else "",
                                                       ("  gain: " + o["gain"]) if o["gain"] else "") for o in s["graph"]]),
                    ("Drift checks", ["%s — %s%s  result: %s" % (x["artifact"], x["what"], ("  why: " + x["why"]) if x["why"] else "",
                                                                 x["result"] or "?") for x in s["drift"]]),
                    ("KB sync", ["%s — %s%s  result: %s" % (x["artifact"], x["what"], ("  why: " + x["why"]) if x["why"] else "",
                                                           x["result"] or "?") for x in s["sync"]]),
                    ("QA suite", ["%s — %s%s  result: %s" % (x["artifact"], x["what"], ("  why: " + x["why"]) if x["why"] else "",
                                                            x["result"] or "?") for x in s["qa"]]),
                    ("Evidence", ["%s — %s%s  result: %s" % (x["artifact"], x["what"], ("  why: " + x["why"]) if x["why"] else "",
                                         x["result"] or "?") for x in s["evidence"]]),
                    ("Tests picked", ["%s — %s%s  result: %s" % (x["artifact"], x["what"], ("  why: " + x["why"]) if x["why"] else "",
                                         x["result"] or "?") for x in s["tests"]]),
                    ("Contract checks", ["%s — %s%s  result: %s" % (x["artifact"], x["what"], ("  why: " + x["why"]) if x["why"] else "",
                                         x["result"] or "?") for x in s["contract"]]),
                    ("Gates", ["%s — %s" % (g["id"], g["state"]) for g in s["gates"]]),
                    ("Decisions", ["%s — %s" % (x["what"], x["detail"]) for x in s["decisions"]])]
        branches = [(label, items) for label, items in branches if items]
        if not branches:
            out.append("   " + ("queued" if s["status"] == "pending" else "no trace lines reported for this stage"))
        for i, (label, items) in enumerate(branches):
            last = i == len(branches) - 1
            out.append(("└─ " if last else "├─ ") + label)
            for j, item in enumerate(items):
                out.append(("   " if last else "│  ") + ("└─ " if j == len(items) - 1 else "├─ ") + item)
        out.append("")
    if t["pending_gate"]:
        g = t["pending_gate"]
        out.append("Waiting: %s %s — on %s" % (g["id"], g["name"], (g["role"] or "?").replace("_", " ")))
    return "\n".join(out) + "\n"


def migrate_run(run):
    """Runs saved by the five-stage console: the old `pr` stage is part of implement now."""
    run.setdefault("kind", "sdlc")
    run.setdefault("forwarded", [])
    if run["kind"] != "sdlc":
        return run
    stages = run.setdefault("stages", {})
    old = stages.pop("pr", None)
    if old in ("running", "done", "blocked"):
        stages["implement"] = "done" if old == "done" else old
    for name in STAGES:
        stages.setdefault(name, "pending")
    if run.get("stage") == "pr":
        run["stage"] = "implement"
    return run


def iso_epoch(value):
    if isinstance(value, (int, float)) and value > 0:
        return float(value)
    try:
        return datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return time.time()


def run_from_tags(tags, title):
    """Rebuild the story record of a run from the tags and title Argus gave its session."""
    summary = title.split(" — ", 1)[1] if " — " in title else title
    if CHAT_TAG in tags:
        return "chat", chat_story(summary)
    if "action" in tags:
        skill = next((t for t in tags if skill_info(t)), "")
        story = action_story(skill or "action", summary)
        return "action", story
    key = next((t for t in tags if TICKET_OR_REQ_RE.match(t)), "SESSION")
    custom = key.startswith("REQ-")
    return "sdlc", {"key": key, "custom": custom, "summary": summary, "description": summary if custom else "",
                    "status": "", "assignee": "", "reporter": "", "labels": [], "points": "",
                    "url": JIRA_BROWSE + key if TICKET_RE.match(key) else ""}


def last_reply(run):
    """Devin's latest message on the run, for the runs list (desktop notifications compare event_id)."""
    m = next((m for m in reversed(run.get("messages") or []) if m.get("source") == "devin"), None)
    return {"event_id": m.get("event_id"), "text": re.sub(r"\s+", " ", m.get("text") or "")[:160]} if m else None


def apply_message(run, msg):
    """Fold one API message into the run. Devin messages are parsed; user messages are echoed."""
    entry = {"event_id": msg.get("event_id"), "at": msg.get("created_at"), "source": msg.get("source"),
             "text": REQUEST_RE.sub("", msg.get("message") or "").strip("\n")}
    echo = None
    if msg.get("source") != "devin":
        echo = next((m for m in run["messages"] if m.get("local") and m.get("text") == entry["text"]), None)
    if echo:
        echo.clear()
        echo.update(entry)
    else:
        run["messages"].append(entry)
    if msg.get("source") != "devin":
        # our own answer/decision: clear whatever was waiting
        first = entry["text"].strip().split(" ", 1)[0].lower() if entry["text"].strip() else ""
        if run["pending_gate"] and first in ("approved", "rejected"):
            run["rejected_gate"] = run["pending_gate"].get("id") if first == "rejected" else None
            run["pending_gate"] = None
        if run["pending_questions"] and NUMBERED_RE.match(entry["text"].strip().splitlines()[0] if entry["text"].strip() else ""):
            run["pending_questions"] = None
        return
    events, questions, gate, artefacts, diffs, pr = parse_devin_message(entry["text"])
    for ev in events:
        ev = dict(ev, at=entry["at"])
        run["events"].append(ev)
        if ev["kind"] == "stage":
            stage = norm_stage(ev["name"])
            d = ev["detail"].lower()
            if stage in run["stages"]:
                if "finish" in d or "done" in d or "complete" in d:
                    run["stages"][stage] = "done"
                elif "abandon" in d or "fail" in d or "block" in d:
                    run["stages"][stage] = "blocked"
                else:
                    run["stages"][stage] = "running"
                    run["stage"] = stage
        if ev["kind"] == "step":
            run.setdefault("steps", {})[ev["name"].strip().lower()] = step_status(ev["detail"])
        if ev["kind"] == "gate" and "reject" in ev["detail"].lower():
            run["rejected_gate"] = ev["name"]
            run["pending_gate"] = None
        elif ev["kind"] == "gate" and ("approved" in ev["detail"].lower() or "closed" in ev["detail"].lower() or "signed" in ev["detail"].lower()):
            run["pending_gate"] = None
            run["rejected_gate"] = None
    if questions:
        run["pending_questions"] = {"event_id": entry["event_id"], "items": questions}
        run["pending_gate"] = None
    if gate:
        run["pending_gate"] = dict(gate, event_id=entry["event_id"], at=entry.get("at"))
        run["rejected_gate"] = None
        run["pending_questions"] = None
    for a in artefacts:
        run["artefacts"] = [x for x in run["artefacts"] if x["name"] != a["name"]] + [dict(a, at=entry["at"])]
    for d in diffs:
        run["diffs"] = [x for x in run["diffs"] if x["path"] != d["path"]] + [dict(d, at=entry["at"])]
    if pr:
        run["pr"] = dict(pr, at=entry["at"])


def regrow_message(run, msg):
    """A message first read cut short (`... [truncated]`) and now read in full is parsed again in its place, so a
    question round or gate at its end shows. 1 when it changed the run."""
    text = REQUEST_RE.sub("", msg.get("message") or "").strip("\n")
    i = next((i for i, e in enumerate(run["messages"]) if e.get("event_id") == msg.get("event_id")), None)
    if i is None or not run["messages"][i].get("text", "").rstrip().endswith("[truncated]") or \
            text.rstrip().endswith("[truncated]") or text == run["messages"][i].get("text"):
        return 0
    old = run["messages"].pop(i)
    known = {(e.get("kind"), e.get("name"), e.get("detail"), e.get("at")) for e in run["events"]}
    n, waiting = len(run["events"]), (run["pending_questions"], run["pending_gate"])
    apply_message(run, msg)
    run["messages"].insert(i, run["messages"].pop())
    run["events"][n:] = [e for e in run["events"][n:] if (e.get("kind"), e.get("name"), e.get("detail"), e.get("at")) not in known]
    if any(e.get("source") != "devin" for e in run["messages"][i + 1:]) or old.get("source") != "devin":
        run["pending_questions"], run["pending_gate"] = waiting
    return 1


def step_status(detail):
    """One automation step line's detail (started, waiting for you, done, failed) as the stepper's state."""
    d = detail.lower()
    if "finish" in d or "done" in d or "complete" in d or "pass" in d:
        return "done"
    if "wait" in d:
        return "waiting"
    if "fail" in d or "block" in d or "abandon" in d:
        return "blocked"
    return "running"


def sdlc_complete(run):
    """An SDLC run whose last stage (KB refresh) is done, whose last gate decision was not a rejection,
    and that waits on no gate, question or reply in progress."""
    if run.get("kind", "sdlc") != "sdlc" or run.get("pending_gate") or run.get("pending_questions") or run.get("rejected_gate"):
        return False
    if (run.get("status") or "") in BUSY or run.get("sent_at"):
        return False
    return (run.get("stages") or {}).get(STAGES[-1]) == "done"


def answered(run):
    """A menu action whose skill has posted its finished line and is not waiting on anyone."""
    if run.get("kind") != "action" or run.get("closed_at") or run.get("pending_questions") or run.get("pending_gate"):
        return False
    status = run.get("status") or ""
    if status not in ("blocked", "finished") and "suspend" not in status:
        return False
    return any(ev["kind"] == "skill" and "finished" in ev["detail"].lower() for ev in run.get("events") or [])


def watchable(run):
    """A run whose session can still change: it has one, and it has not ended or been closed since its last read."""
    if not run.get("session_id"):
        return False
    return not ((run.get("status") in ENDED or run.get("closed_at")) and run.get("polled_at"))


def due(run, now):
    """How often a run's session is read without a sign it moved: busy often, waiting less, asleep or finished
    rarely, ended once."""
    if not watchable(run):
        return False
    last = run.get("polled_at") or 0
    status = run.get("status") or ""
    watched, sent = run.get("watched_at"), run.get("sent_at")
    live = bool(watched and now - watched < WATCHED_SECONDS) or bool(sent and now - sent < REPLY_WAIT_SECONDS)
    if status in BUSY or live:
        wait = POLL_SECONDS
    elif status == "finished" or "suspend" in status or "suspend" in (run.get("status_detail") or ""):
        wait = SLEEP_POLL_SECONDS
    else:
        wait = IDLE_POLL_SECONDS
    return now - last >= wait


def notice_run(run, now):
    """A run that ended in error, or went quiet after Argus wrote to it, is noted once: the (where, detail, page)
    notes to hand to OBSERVER. Call it holding the store lock and note them after letting go."""
    notes = []
    what = "%s %s" % (run.get("kind") or "run", (run.get("story") or {}).get("action") or
                      (run.get("story") or {}).get("key") or "")
    if run.get("status") == "error" and not run.get("noticed_error"):
        run["noticed_error"] = True
        notes.append(("run_error", "%s ended in error: %s" % (what, run.get("status_detail") or run.get("error") or ""),
                      run.get("stage") or ""))
    sent = run.get("sent_at")
    if sent and now - sent > STUCK_SECONDS and run.get("noticed_stuck") != sent and not run.get("closed_at") \
            and run.get("status") not in ENDED:
        run["noticed_stuck"] = sent
        notes.append(("run_stuck", "%s: no answer from Devin for %d minutes (status %s)"
                      % (what, (now - sent) // 60, run.get("status_detail") or run.get("status")),
                      run.get("stage") or ""))
    return notes


POLL_WORKERS = max(1, int(os.environ.get("SDLC_POLL_WORKERS", "4")))
UNCHANGED_RECHECK = 60   # a session the search says has not moved is still read this often (when due)
FLUSH_SECONDS = 60       # small changes (when a run was last read) reach runs.json at least this often


def run_snapshot(run):
    """What a page shows of a run, to tell whether a read changed anything worth saving at once."""
    return (run.get("status"), run.get("status_detail"), run.get("session_url"), run.get("title"), run.get("error"),
            json.dumps(run.get("pull_requests"), sort_keys=True))


class Poller(threading.Thread):
    """Reads due runs from Devin Cloud: a few at a time, each run by one reader at once, and only the sessions
    that moved since their last read."""

    def __init__(self, store, devin, workers=None):
        super().__init__(daemon=True, name="argus-poller")
        self.store, self.devin = store, devin
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=workers or POLL_WORKERS,
                                                          thread_name_prefix="argus-poll")
        self.busy, self.busy_lock = set(), threading.Lock()

    def run(self):
        while True:
            try:
                self.cycle()
            except Exception as exc:  # noqa: BLE001  the poller never stops
                OBSERVER.note("run_poll", "poll round failed: %s" % exc)
            time.sleep(POLL_SECONDS)

    def cycle(self, now=None):
        """One round; the futures of the reads it started."""
        now = now or time.time()
        try:
            self._adopt_late()
        except Exception as exc:  # noqa: BLE001  a late bridge reply never stops the round
            OBSERVER.note("bridge", "late bridge reply not added: %s" % exc)
        with self.store.lock:
            open_ids = [rid for rid, r in self.store.runs.items() if watchable(r)]
        jobs = [self.pool.submit(self._poll_one, rid, updated) for rid, updated in self.changed(open_ids, now)
                if self._claim(rid)]
        notes = []
        with self.store.lock:
            for run in self.store.runs.values():
                notes += notice_run(run, now)
        for where, detail, page in notes:
            OBSERVER.note(where, detail, page=page)
        if self.store.dirty and time.time() - self.store.saved_at >= FLUSH_SECONDS:
            self.store.save()
        return jobs

    def _updated(self, run_ids):
        """{bare session id: updated time} for these runs: one search for exactly their sessions on the bridge,
        else one search of the Argus tag (the Devin API lists the newest sessions only)."""
        with self.store.lock:
            sids = [self.store.runs[rid]["session_id"] for rid in run_ids if rid in self.store.runs]
        by_id = getattr(self.devin, "updated_of", None)
        rows = by_id(sids) if by_id else self.devin.list_sessions(WORKBENCH_TAG, 100)
        moved = {}
        for s in rows or []:
            at = s.get("updated_at")
            at = iso_epoch(at) if isinstance(at, str) else at
            if s.get("session_id") and isinstance(at, (int, float)) and at:
                moved[bridge.bare_id(s["session_id"])] = at
        return moved

    def changed(self, run_ids, now):
        """[(run id, session updated time or None)] worth reading now. Every round one search says which of the
        open runs' sessions moved, and those are read at once whatever their status, so a question or a gate shows
        within a round. One that has not moved is read only when due and not read for UNCHANGED_RECHECK; one the
        search does not list is read when due. With no search, the due ones are read, as before."""
        if not run_ids:
            return []
        try:
            moved = self._updated(run_ids)
        except Exception:  # noqa: BLE001  no search: read the due ones
            with self.store.lock:
                return [(rid, None) for rid in run_ids if rid in self.store.runs and due(self.store.runs[rid], now)]
        out = []
        with self.store.lock:
            for rid in run_ids:
                run = self.store.runs.get(rid)
                if not run:
                    continue
                at = moved.get(bridge.bare_id(run.get("session_id") or ""))
                last = run.get("session_updated")
                if at is not None and last is not None and at > last:
                    out.append((rid, at))
                elif not due(run, now):
                    continue
                elif at is None or last is None or now - (run.get("polled_at") or 0) >= UNCHANGED_RECHECK:
                    out.append((rid, at))
        return out

    def _claim(self, run_id):
        with self.busy_lock:
            if run_id in self.busy:
                return False
            self.busy.add(run_id)
            return True

    def _poll_one(self, run_id, updated=None):
        try:
            self.refresh(run_id)
            if updated:
                with self.store.lock:
                    run = self.store.runs.get(run_id)
                    if run:
                        run["session_updated"] = updated
        except Exception as exc:  # noqa: BLE001  keep polling other runs
            err = str(exc) if isinstance(exc, ApiError) else "poll failed: %s" % exc
            with self.store.lock:
                run = self.store.runs.get(run_id)
                if run:
                    run["error"] = err
                page = (run or {}).get("kind") or ""
            OBSERVER.note("run_poll", err, page=page)
        finally:
            with self.busy_lock:
                self.busy.discard(run_id)

    def _adopt_late(self):
        """Sessions the bridge started after Argus stopped waiting for them go on the run list."""
        late = getattr(self.devin, "collect_late", None)
        for calls, texts in (late() if late else []):
            if not calls or calls[0][0] != "devin_session_create" or not texts:
                continue
            spec = ((calls[0][1].get("sessions") or [{}])[0])
            sid = bridge.bare_id(texts[0])
            if not bridge.SESSION_ID_RE.fullmatch(sid):
                continue
            app = getattr(self.devin, "app", DEVIN_APP)
            info = {"session_id": "devin-" + sid, "url": "%s/sessions/%s" % (app, sid),
                    "title": spec.get("title") or "", "tags": list(spec.get("tags") or []), "status_enum": "working"}
            if self.store.adopt([info]):
                OBSERVER.note("bridge", "A Devin Cloud session started after Argus stopped waiting for it (%s); "
                                        "it is now on the run list." % info["title"][:80])

    def refresh(self, run_id, force=False):
        with self.store.lock:
            run = self.store.runs.get(run_id)
            if not run or not run.get("session_id"):
                return
            sid, after = run["session_id"], None if run.get("assistant") else run.get("msg_after")
        info = self.devin.session(sid, after=after) if after else self.devin.session(sid)
        msgs = self.devin.messages(info)
        if run.get("assistant"):
            msgs = own_messages(msgs, run["id"])
        with self.store.lock:
            before, added = run_snapshot(run), 0
            if info.get("msg_after"):
                run["msg_after"] = info["msg_after"]
            run["status"] = info.get("status_enum") or info.get("status", run["status"])
            run["status_detail"] = info.get("status")
            try:
                if info.get("acus_consumed") not in (None, ""):
                    run["acus"] = round(float(info.get("acus_consumed")), 2)
            except (TypeError, ValueError):
                pass
            run["session_url"] = info.get("url") or run["session_url"]
            run["pull_requests"] = [pr_link(info["pull_request"])] if info.get("pull_request") else []
            run["title"] = info.get("title")
            seen = set(run["seen"])
            for m in msgs:
                if m.get("event_id") in seen:
                    added += regrow_message(run, m)
                    continue
                seen.add(m.get("event_id"))
                run["seen"].append(m.get("event_id"))
                apply_message(run, m)
                added += 1
                if m.get("source") == "devin":
                    run.pop("sent_at", None)
            run["error"] = None
            run["polled_at"] = time.time()
            worth_saving = added or run_snapshot(run) != before
        if worth_saving:
            self.store.save()
        else:
            self.store.touch()
        if answered(run):
            self.close(run_id)

    def close(self, run_id):
        run = self.store.runs.get(run_id)
        if not run:
            return
        if not run.get("assistant"):
            close_session(self.devin, run["session_id"], run.get("tags") or ())
        with self.store.lock:
            run["closed_at"] = time.time()
        self.store.save()


# --------------------------------------------------------------------------- HTTP

CLIENT_GONE = (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)
MAX_BODY_BYTES = 48 * 1024 * 1024   # the create form's 25 MB of files, base64 in JSON, with room to spare


class Handler(BaseHTTPRequestHandler):
    store = None
    jira = None
    devin = None
    poker = None
    insight = None
    ac_rewrite = None
    pc = None
    poller = None

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

    def _send(self, status, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        path = urllib.parse.urlparse(self.path or "").path
        if status >= 400 and status != 409 and path.startswith("/api/") and not path.startswith("/api/observe"):
            err = body.get("error") if isinstance(body, dict) else ""
            OBSERVER.note("api", "%d on %s %s: %s" % (status, self.command or "", path, err or ""), page=path)
        try:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
        except CLIENT_GONE:
            self.close_connection = True

    def _file(self, path, ctype):
        try:
            with open(path, "rb") as fh:
                self._send(200, fh.read(), ctype)
        except FileNotFoundError:
            self._send(404, {"error": "not found"})

    def _page(self, name):
        """A static page with the team's values filled in."""
        try:
            with open(os.path.join(STATIC, name), "rb") as fh:
                self._send(200, team.fill_page(fh.read(), PAGE_VALUES), "text/html; charset=utf-8")
        except FileNotFoundError:
            self._send(404, {"error": "not found"})

    def _body(self):
        """The request's JSON object; 400 when it is not one, 413 when it is too big to read."""
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = -1
        if n < 0:
            raise ApiError(400, "the request had a bad Content-Length")
        if n > MAX_BODY_BYTES:
            self.close_connection = True
            raise ApiError(413, "the request is too big: %d MB at most" % (MAX_BODY_BYTES // (1024 * 1024)))
        raw = self.rfile.read(n) if n else b""
        if not raw.strip():
            return {}
        try:
            body = json.loads(raw)
        except ValueError:
            raise ApiError(400, "the request was not valid JSON")
        if not isinstance(body, dict):
            raise ApiError(400, "the request must be a JSON object")
        return body

    def _whoami(self, who, role_override=""):
        """Viewer identity and menus: the person picked in the page (or --user) on the roster."""
        roster = load_roster()
        person = find_person(who or DEFAULT_JIRA_USER, roster)
        roles = load_roles()
        hats = []
        if person:
            hats = [r for r in [person["primary_role"]] + person["secondary_roles"] if r in roles]
        role_id = role_override if role_override in roles else (hats[0] if hats else "")
        view = role_view(role_id, roles) if role_id else None
        previewing = bool(role_override and role_override not in hats)
        if view and not role_override and len(hats) > 1:
            view = all_hats_view([role_view(h, roles) for h in hats])
        return {
            "person": person,
            "hats": [{"id": r, "label": roles[r]["label"]} for r in hats],
            "all_roles": [{"id": r, "label": v["label"]} for r, v in roles.items()],
            "role": view,
            "previewing": previewing,
        }

    def _requester(self, body):
        if not body.get("user") and not body.get("role"):
            return ""
        who = self._whoami(body.get("user", ""), body.get("role", ""))
        return requester_note(who["person"], who["role"], who["previewing"])

    def _feedback_context(self, q):
        """What Argus already knows about the person's session, so they never have to type it."""
        who = self._whoami(q.get("user", ""), q.get("role", ""))
        person, role = who["person"] or {}, who["role"] or {}
        with self.store.lock:
            runs = sorted(self.store.runs.values(), key=lambda r: -(r.get("created_at") or 0))
        pick = [r for r in runs if r["id"] == q.get("run")] + [r for r in runs if r["id"] != q.get("run")][:3]
        out_runs = []
        for r in pick:
            story = r.get("story") or {}
            reply = last_reply(r) or {}
            out_runs.append({
                "id": r["id"], "kind": r.get("kind"), "what": story.get("action") or story.get("key") or "",
                "summary": (story.get("summary") or r.get("title") or "")[:100], "stage": r.get("stage") or "",
                "status": r.get("status_detail") or r.get("status") or "", "session": r.get("session_url") or "",
                "error": (r.get("error") or "")[:300], "last_devin": reply.get("text", "")[:300],
                "waiting_on_you": bool(r.get("pending_questions") or r.get("pending_gate")),
                "started": observer._now_iso(r.get("created_at") or time.time()),
                "minutes_since_devin": int((time.time() - r["sent_at"]) // 60) if r.get("sent_at") else None,
                "dry_run": bool(r.get("dry_run")), "this_one": r["id"] == q.get("run")})
        health = integrations(self.devin, self.jira)
        about = update.about(ROOT)
        return {
            "person": person.get("name", ""), "role": role.get("label", ""), "page": q.get("page", "")[:60],
            "ticket": q.get("story", "")[:40], "runs": out_runs,
            "status_light": {k: {"state": v["state"], "error": v["error"][:200]} for k, v in health.items()},
            "noticed": [{"title": n["title"], "detail": n["detail"][:200], "count": n["count"],
                         "last": observer._now_iso(n["last"])} for n in OBSERVER.recent(24)[:10]],
            "workbench": {"version": about.get("version"), "commit": about.get("commit"),
                          "branch": about.get("branch"), "transport": bridge.transport(),
                          "jira_via": getattr(self.jira, "via", "here")},
            "browser": (q.get("browser") or "")[:160],
        }

    def _feedback(self, body):
        """Feedback form Send: keep the words with the session details, then send everything not sent yet."""
        q = {k: str(body.get(k) or "") for k in ("user", "role", "run", "story", "page", "browser")}
        context = self._feedback_context(q)
        context["screen_errors"] = [str(e)[:200] for e in (body.get("screen_errors") or [])[:5]]
        try:
            entry = OBSERVER.add_feedback(context["person"], context["role"], body.get("kind"), body.get("about"),
                                          body.get("text"), context)
        except ValueError as exc:
            return self._send(400, {"error": str(exc)})
        run = self._send_feedback(body, context["workbench"])
        return self._send(201, {"feedback": entry["id"], "run": run})

    def _send_feedback(self, body, workbench):
        """One run takes everything not sent yet; None when there is nothing to send or nobody to send it as."""
        requester = self._requester(body) or (self._requester({"user": DEFAULT_JIRA_USER}) if DEFAULT_JIRA_USER else "")
        who = self._whoami(body.get("user", ""), body.get("role", ""))
        if not requester or not who["person"]:
            return None
        block, _ = OBSERVER.batch(who["person"].get("name", ""), (who["role"] or {}).get("label", ""), workbench)
        if not block:
            return None
        run = self._start_action("dashboard", save_prompt(observer.BLOCK, block, requester), False,
                                 "Argus feedback", requester=requester)
        OBSERVER.mark_sent(block)
        return run

    def _start_action(self, skill, text, dry_run, title="", requester=""):
        prompt = build_action_prompt(skill, text, dry_run) + ("\n\n" + requester if requester else "")
        tags = [WORKBENCH_TAG, "action", skill, "dry-run" if dry_run else "live"]
        run = self._new_request(action_story(skill, title or text), dry_run, "action", prompt,
                                "Argus /%s — %s" % (skill, (title or text or "no input")[:60]), tags,
                                own=skill in OWN_SESSION_SKILLS)
        run["story"]["input"] = text
        run["requester"] = requester
        run["prompt"] = prompt
        self.store.save()
        return self.store.public(run)

    def _new_request(self, story, dry_run, kind, prompt, title, tags, own=False, fresh=False):
        """A run for a menu item or chat: a new request in today's assistant session, or its own session.

        The assistant session moves to a new one, with a handover, once it holds LONG_SESSION messages
        or when `fresh` asks for it."""
        if not SHARED_ASSISTANT or own:
            session = self.devin.create_session(prompt, title, tags)
            return self.store.new_run(story, dry_run, dict(session, tags=tags), kind=kind)
        owner = "%s|%s" % (DEFAULT_JIRA_USER or "anyone", time.strftime("%Y-%m-%d"))
        with self.store.lock:
            host = self.store.assistant_host(owner)
            handover = ""
            if host and (fresh or self.store.session_messages(host["session_id"]) >= LONG_SESSION):
                handover = self.store.handover_text(host["session_id"])
                host = None
        run = self.store.new_run(story, dry_run, {"tags": tags}, kind=kind)
        sent = False
        if host:
            try:
                self.devin.send(host["session_id"], request_text(run["id"], prompt))
                sent = True
            except ApiError:
                sent = False
        if sent:
            session = {"session_id": host["session_id"], "url": host.get("session_url"), "status": "working"}
        else:
            session = self.devin.create_session(
                assistant_prompt() + handover + request_text(run["id"], prompt),
                "Argus assistant — %s %s" % (DEFAULT_JIRA_USER or "", owner.split("|")[1]),
                [WORKBENCH_TAG, ASSISTANT_TAG] + [t for t in tags if t != WORKBENCH_TAG])
        with self.store.lock:
            run.update(session_id=session.get("session_id"), session_url=session.get("url"),
                       status=session.get("status_enum") or session.get("status", "new"), assistant=owner,
                       queued=bool(sent and host.get("status") in BUSY))
            self.store.save()
        return run

    def _exit(self, body):
        """Exit button: end the Cloud sessions the person ticked, then stop this Argus unless one failed."""
        ids = []
        for i in body.get("session_ids") or []:
            m = re.search(r"([0-9a-f]{32})", str(i))
            if m and "devin-" + m.group(1) not in ids:
                ids.append("devin-" + m.group(1))
        closed, failed = [], []
        for sid in ids:
            try:
                closed.append(close_session(self.devin, sid, self._tags_of(sid)))
            except ApiError as exc:
                failed.append({"session_id": sid, "error": str(exc)})
        with self.store.lock:
            for run in self.store.runs.values():
                if run.get("session_id") in closed:
                    run["closed_at"] = time.time()
            self.store.save()
        stopping = not failed and callable(getattr(Handler, "stop", None))
        if stopping:
            threading.Timer(1.0, Handler.stop).start()
        return {"closed": closed, "failed": failed, "stopping": stopping}

    @staticmethod
    def _wrap_target(src):
        m = re.search(r"([0-9a-f]{32})", str(src.get("session") or ""))
        ticket = str(src.get("ticket") or "").strip().upper()
        return ("devin-" + m.group(1), ticket) if m and pctest.JIRA_TICKET.match(ticket) else (None, ticket)

    def _wrap_state(self, sid, ticket):
        return pctest.wrapup_state(self.devin.messages(self.devin.session(sid)), ticket)

    nudge_cache = {}

    def _nudges(self, user, refresh=False):
        """Reminders for one person: read once a day from the active sprint (Check now reads again)."""
        person = find_person(user)
        if not person:
            return {"available": False, "items": [], "note": "Pick who you are to see your reminders."}
        if not self.backlog._live():
            return {"available": False, "items": [],
                    "note": "Reminders need the Jira read with the service account, as in Devin Cloud."}
        today = datetime.date.today().isoformat()
        hit = self.nudge_cache.get(person["jira_user"])
        if hit and hit["day"] == today and not refresh:
            return hit["out"]
        try:
            active = next((x for x in self._sprints() if x.get("state") == "active"), {})
            checks = sprint_checks(self.backlog, active, self._sprints()) if active.get("id") else {}
            follow = self.backlog.followups(active.get("id"), idle_working_days()) if active.get("id") else {}
        except Exception as exc:  # noqa: BLE001 - shown in Waiting on me; the rest of the page still works
            return {"available": True, "items": [], "note": "Jira could not be read for your reminders (%s)." % exc}
        if not active.get("id"):
            out = {"available": True, "items": [], "note": "There is no active sprint.", "day": today}
        else:
            out = {"available": True, "sprint": active.get("name", ""), "day": today, "browse": JIRA_BROWSE,
                   "items": nudge_rows(follow, checks.get("gaps"), person["name"]),
                   "note": checks.get("checks_error", ""), "writes": self.backlog.mode()["writes"]}
        self.nudge_cache[person["jira_user"]] = {"day": today, "out": out}
        return out

    def _nudge_answer(self, body):
        """An answer on a due-date or close-story reminder: a Jira change shown back, sent only when writes are on."""
        user, key = str(body.get("user") or ""), str(body.get("key") or "").upper()
        person = find_person(user)
        hit = (self.nudge_cache.get(person["jira_user"]) or {}).get("out", {}) if person else {}
        item = next((i for i in hit.get("items") or [] if i.get("key") == key and i.get("answer")), None)
        if not item:
            raise ApiError(404, "%s is not one of your reminders; press Check now" % key)
        import sm_reminders
        due = str(body.get("due") or "") if item["answer"] == "due" else ""
        note = str(body.get("note") or "").strip() if item["answer"] == "note" else ""
        try:
            calls = sm_reminders.answer_calls(key, person["name"], due=due, note=note, question=item["text"])
        except ValueError:
            raise ApiError(400, "give the due date" if item["answer"] == "due" else "write the answer first")
        return self.backlog._change("reminder", [key], "%s ← %s" % (key, due and "due " + due or note), calls,
                                    person["name"])

    def _waiting_issue(self, user, key):
        """The sub-task, only if Jira listed it as waiting on this user (the last list read)."""
        if getattr(self.jira, "via", "") == "cloud":
            items = (self.jira._cached("waiting-" + user) or {}).get("stories", [])
        else:
            items = self.jira.stories("waiting", user).get("stories", [])
        return next((i for i in items if i.get("key") == key), None)

    def _tags_of(self, sid):
        """A session's tags, so closing it adds the closed tag instead of replacing the others."""
        try:
            sid = sid if sid.startswith("devin-") else "devin-" + sid
            return self.devin.session(sid).get("tags") or ()
        except ApiError:
            return ()

    def _team_sessions(self, person, lens):
        """The team's Devin Cloud sessions of the last TEAM_SESSION_DAYS for the Team activity tab, as a file
        path; None when this viewer does not get the tab or Devin Cloud could not be read."""
        audience = team_activity_audience(lens)
        hats = {person.get("primary_role")} | set(person.get("roles") or []) | set(person.get("secondary_roles") or [])
        if audience is None or (audience and not hats & audience) or not self.devin.key:
            return None
        since = int(time.time()) - TEAM_SESSION_DAYS * 86400
        try:
            found = self.devin.team_sessions(load_roster(), since)
        except (ApiError, bridge.BridgeError):
            return None
        keep = [{"session_id": i.get("session_id"), "title": i.get("title"),
                 "status": i.get("status_enum") or i.get("status"), "updated": i.get("updated_at"),
                 "tags": i.get("tags") or [], "user_id": i.get("user_id") or ""}
                for i in found if not {CLOSED_TAG, ARCHIVED_TAG} & set(i.get("tags") or [])]
        path = os.path.join(STATE_DIR, "dashboard-team-sessions.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"sessions": keep, "days": TEAM_SESSION_DAYS}, fh)
        return path

    def _my_sessions(self, person):
        """The viewer's Devin sessions for the dashboard's Sessions tab, as a file path; None if unreadable."""
        if not person.get("email") or not self.devin.key:
            return None
        try:
            found = self.devin.sessions_of(person["email"])
        except ApiError:
            return None
        keep = [{"session_id": i.get("session_id"), "title": i.get("title"),
                 "status": i.get("status_enum") or i.get("status"), "updated": i.get("updated_at"),
                 "tags": i.get("tags") or []}
                for i in found if not {CLOSED_TAG, ARCHIVED_TAG} & set(i.get("tags") or [])
                and (i.get("status_enum") or i.get("status")) not in ENDED]
        path = os.path.join(STATE_DIR, "dashboard-sessions.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"sessions": keep}, fh)
        return path

    def _send_to_session(self, run, text):
        self.devin.send(run["session_id"], request_text(run["id"], text) if run.get("assistant") else text)
        with self.store.lock:
            run["messages"].append({"event_id": "local-%s" % uuid.uuid4().hex[:8], "at": int(time.time()),
                                    "source": "user", "text": text, "local": True})
            if run.get("status") not in BUSY:
                run["status"] = "resume_requested"
            run["polled_at"] = 0
            self.store.save()

    def _bundle(self, run):
        """Every artefact, diff and the PR text of a run as one zip, plus the transcript of what was sent."""
        buf = io.BytesIO()

        def safe(name):
            return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_") or "file"

        def stamp(at):
            return time.strftime("%Y-%m-%d %H:%M", time.localtime(at)) if isinstance(at, (int, float)) else at or ""
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for a in run["artefacts"]:
                zf.writestr("artefacts/" + safe(a["name"]), a.get("body") or a.get("detail") or "")
            for d in run["diffs"]:
                zf.writestr("diffs/" + safe(d["path"]) + ".diff", d.get("body") or "")
            if run.get("pr"):
                zf.writestr("pr.txt", "%s\n%s\n\n%s" % (run["pr"]["branch"], run["pr"]["detail"], run["pr"]["body"]))
            if run.get("kind") == "sdlc":
                zf.writestr("trace.txt", trace_text(run))
            sent = [m for m in run["messages"] if m.get("source") != "devin"]
            zf.writestr("decisions-and-answers.txt",
                        "\n\n".join("%s\n%s" % (stamp(m.get("at")), m["text"]) for m in sent))
        return buf.getvalue()

    def _create_story(self, run, body):
        assignee = (body.get("assignee") or DEFAULT_JIRA_USER or "").strip()
        display = assignee
        for person in load_people():
            if person["jira_user"] == assignee:
                display = person["name"]
        summary, description, acceptance, spec_name = story_from_run(run, display)
        key = self.jira.create_story(summary, description, acceptance, assignee, ["AI-Used", "sdlc-console"])
        created = {"key": key, "url": JIRA_BROWSE + key, "summary": summary, "assignee": assignee,
                   "assignee_name": display, "from_spec": spec_name, "at": time.time()}
        with self.store.lock:
            run["jira_story"] = created
            if run["story"].get("custom"):
                run["story"]["url"] = created["url"]
                run["story"]["jira_key"] = key
            self.store.save()
        return created

    def _gate_subtasks(self, run, gate_id, body):
        """Sub-tasks the developer confirmed at the last gate before coding. An Argus with Backlog writes on
        writes them itself; otherwise the session does, with the service account (a dry run only lists them)."""
        if not subtask_gate(gate_id):
            raise ApiError(400, "sub-tasks are added at the gate before coding (%s)" % ", ".join(SUBTASK_GATES))
        key = run_story_key(run)
        if not key:
            raise ApiError(400, "this run has no Jira story yet, so there is nothing to add sub-tasks to")
        rows = backlog.clean_subtasks(body.get("subtasks"))
        assignee = (body.get("assignee") or DEFAULT_JIRA_USER or "").strip()
        by = (body.get("user") or assignee).strip()
        record = {"key": key, "rows": rows, "assignee": assignee, "gate": gate_id, "at": time.time(), "keys": []}
        change = None
        if not run.get("dry_run") and getattr(self.backlog, "_live", lambda: False)():
            change = self.backlog.add_subtasks(key, rows, by, assignee,
                                               "Added in the %s at %s for %s." % (WORKBENCH_TITLE, gate_id, key))
        if change and change["status"] == "applied":
            record.update(via="workbench", keys=change.get("created") or [])
            record["updated"] = change.get("updated") or []
            done = ", ".join(x for x in ("%s created" % ", ".join(record["keys"]) if record["keys"] else "",
                                         "%s updated" % ", ".join(record["updated"]) if record["updated"] else "") if x)
            note = ("\n[SDLC] note subtasks %s — under %s by Argus with the developer's original estimates "
                    "and descriptions. Log the work against them.\n%s" % (done, key, subtask_lines(rows)))
        else:
            record["via"] = "dry run" if run.get("dry_run") else "session"
            note = subtask_request(key, rows, assignee, run.get("dry_run"))
        with self.store.lock:
            run["subtasks"] = record
            self.store.save()
        return note

    def _cloud_story_request(self, body):
        assignee = (body.get("assignee") or DEFAULT_JIRA_USER or "").strip()
        return ("\n[SDLC] note jira-create — this Argus has no Jira access. Create the %s Story yourself now "
                "with the Jira service account, from the intake spec you just presented: project %s, type Story, "
                "summary and user story from the spec, acceptance criteria in %s, IT Team %s, assignee %s, labels "
                "AI-Used and sdlc-console. The tester approved this one Jira write, even in a dry run. Then post "
                "`[SDLC] note jira <KEY> — created` and use that key as the story key from here on."
                % (PROJECT, PROJECT, F_ACCEPTANCE, IT_TEAM, assignee or "nobody"))

    def _ticket_sessions(self, ticket):
        """Cloud sessions for a ticket: this Argus's runs, then sessions tagged with the ticket."""
        out, seen = [], set()
        with self.store.lock:
            runs = sorted(self.store.runs.values(), key=lambda r: -r["created_at"])
            for r in runs:
                if (r.get("story") or {}).get("key", "").upper() == ticket and r.get("session_url"):
                    out.append({"url": r["session_url"], "title": r.get("title") or ticket})
        if self.devin.key:
            try:
                for s in self.devin.list_sessions(ticket, 20):
                    sid = s.get("session_id") or ""
                    out.append({"url": "%s/sessions/%s" % (DEVIN_APP, sid.replace("devin-", "")),
                                "title": s.get("title") or sid})
            except ApiError:
                pass
        unique = []
        for s in out:
            m = pctest.SESSION_RE.search(s["url"])
            sid = m.group(1).replace("devin-", "") if m else s["url"]
            if sid not in seen:
                seen.add(sid)
                unique.append(s)
        return unique

    def _runs_list(self):
        with self.store.lock:
            runs = sorted(self.store.runs.values(), key=lambda r: -r["created_at"])
            keys = ("id", "kind", "title", "story", "dry_run", "status", "status_detail", "stage", "stages",
                    "created_at", "session_url", "pending_gate", "pending_questions", "jira_story", "subtasks",
                    "forwarded", "error", "pull_requests", "archived", "closed_at", "steps", "acus")
            return [dict({k: r.get(k) for k in keys}, last_reply=last_reply(r), complete=sdlc_complete(r)) for r in runs]

    def _pc_config(self):
        return {"key_store": pctest.key_store(), "devin_cli": bool(pctest.devin_cli()),
                "python": pctest.tester_python(), "work_root": pctest.work_root(),
                "windows": ON_WINDOWS, "transport": bridge.transport(),
                "test_on_pc": workbench_config.mode_for(DEFAULT_JIRA_USER)}

    def _save_block(self, body):
        """Save on a dashboard tab, review page or form: the block goes to a run, which previews it, waits for
        approved, then raises the pull request (repo files) or writes Jira (SDLC_BACKLOG_WRITES=1)."""
        block = (body.get("block") or "").strip()
        kind = saved_block_kind(block)
        if not kind:
            return self._send(400, {"error": "Save only takes a block from a dashboard tab, review page or form"})
        requester = self._requester(body) or (self._requester({"user": DEFAULT_JIRA_USER}) if DEFAULT_JIRA_USER else "")
        if not requester:
            return self._send(400, {"error": "pick who you are first, so the change is recorded against you"})
        skill, label = SAVED_BLOCKS[kind]
        dry_run = bool(body.get("dry_run", True))
        who = self._whoami(body.get("user", "") or DEFAULT_JIRA_USER, body.get("role", ""))
        approved = save_is_approval(None if who["previewing"] else who["person"], kind, dry_run)
        text = save_prompt(kind, block, requester, approved=approved)
        return self._send(201, self._start_action(skill, text, dry_run, label, requester=requester))

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        q = dict(urllib.parse.parse_qsl(url.query))
        p = url.path
        try:
            if p in ("/", "/index.html"):
                return self._page("index.html")
            if p == "/static/kit.css":
                return self._file(os.path.join(KIT, "kit.css"), "text/css")
            if p == "/static/acme.css":
                return self._file(os.path.join(KIT, "acme.css"), "text/css")
            if p == "/static/kit.js":
                return self._file(os.path.join(KIT, "kit.js"), "application/javascript")
            if p.startswith("/static/"):
                name = os.path.basename(p)
                ctype = ("text/css" if name.endswith(".css") else "application/javascript" if name.endswith(".js")
                         else "image/svg+xml" if name.endswith(".svg") else "text/plain")
                return self._file(os.path.join(STATIC, name), ctype)
            if p == "/api/config":
                health = integrations(self.devin, self.jira)
                return self._send(200, {
                    "jira_ok": health["jira"]["connected"], "jira_configured": health["jira"]["configured"],
                    "jira_via": getattr(self.jira, "via", "here"), "devin_ok": health["devin"]["connected"],
                    "devin_configured": health["devin"]["configured"], "integrations": health,
                    "pc": self._pc_config(), "transport": bridge.transport(),
                    "devin_api": DEVIN_API, "org": DEVIN_ORG, "repo": REPO_SLUG, "team": IT_TEAM,
                    "scopes": {k: v for k, v in JQL.items()}, "stages": STAGES,
                    "people": load_people(), "default_jira_user": DEFAULT_JIRA_USER, "can_switch": can_switch_user(),
                    "stage_labels": STAGE_LABELS, "gates": load_gates(), "session_link": DEVIN_APP,
                    "product": PRODUCT, "workbench_short": WORKBENCH_SHORT, "project": PROJECT, "kb": team.KB,
                    "docs": team.DOCS, "can_build_copy": can_build_copy(), "automation": team.AUTOMATION,
                })
            if p == "/api/health":
                if q.get("fresh"):
                    check_integrations(self.devin, self.jira)
                return self._send(200, dict(integrations(self.devin, self.jira), dashboard_data=shared_data_age()))
            if p == "/api/update":
                return self._send(200, self.updater.status(fresh=bool(q.get("fresh"))))
            if p == "/api/shared-copy":
                if not can_build_copy():
                    return self._send(403, {"error": "only the people on act_as.allowed build the shared copy"})
                return self._send(200, dict(SHARED_COPY.status(), version_now=current_copy_version()))
            if p == "/api/about":
                return self._send(200, update.about(ROOT))
            if p == "/api/feedback":
                return self._send(200, {"context": self._feedback_context(q), "kinds": observer.KINDS,
                                        "about": observer.ABOUT, "waiting": len(OBSERVER.pending),
                                        "unsent": len(OBSERVER.unsent())})
            if p == "/api/doctor":
                return self._send(200, {"checks": doctor.run(ROOT, self.updater, self.devin)})
            if p == "/api/me":
                return self._send(200, self._whoami(q.get("user", ""), q.get("role", "")))
            if p in ("/dashboard", "/actions"):
                page = DASHBOARD_PATH if p == "/dashboard" else ACTIONS_PATH
                if not os.path.exists(page):
                    return self._send(404, DASHBOARD_MISSING.encode(), "text/html; charset=utf-8")
                return self._file(page, "text/html; charset=utf-8")
            if re.match(r"^/run/[a-f0-9]+$", p):
                return self._page("run.html")
            if p == "/validation":
                return self._send(200, validation_page(), "text/html; charset=utf-8")
            m = re.match(r"^/page/([a-z-]+)$", p)
            if m:
                return self._send(200, reference_page(m.group(1)), "text/html; charset=utf-8")
            m = re.match(r"^/view/([a-f0-9]+)/(\d+)$", p)
            if m:
                run = self.store.runs.get(m.group(1))
                arts = run["artefacts"] if run else []
                if int(m.group(2)) >= len(arts):
                    return self._send(404, {"error": "no such document"})
                art = arts[int(m.group(2))]
                name, body = art.get("name") or "document", art.get("body") or art.get("detail") or ""
                if re.search(r"\.html?$", name, re.I):
                    return self._send(200, body.encode("utf-8"), "text/html; charset=utf-8")
                if re.search(r"\.(md|markdown)$", name, re.I):
                    return self._send(200, markdown_page(name, body, "From %s" % run["story"]["key"]),
                                      "text/html; charset=utf-8")
                return self._send(200, body.encode("utf-8"), "text/plain; charset=utf-8")
            if p == "/repo-file":
                rel = repo_rel(q.get("path", ""))
                if not rel:
                    return self._send(400, {"error": "not a repository file this page can open"})
                try:
                    data, _ = repo_file(rel)
                except OSError:
                    return self._send(404, {"error": "%s is not on %s or in this checkout" % (rel, KB_BRANCH)})
                if rel.lower().endswith(".md"):
                    data = markdown_page(os.path.basename(rel), data.decode("utf-8"), rel)
                return self._send(200, data, REPO_FILE_TYPES[os.path.splitext(rel)[1].lower()])
            if p == "/api/backlog/sprint-sheet.html":
                import sprint_sheet
                token = (q.get("sprint") or "").strip() or sprint_sheet.current()
                if not token:
                    return self._send(404, {"error": "no sprint planning sheet in the repo yet"})
                try:
                    page = sprint_sheet.render_page(sprint_sheet.load(token), save_url="/api/backlog/sprint-sheet")
                except sprint_sheet.SheetError as exc:
                    return self._send(404, {"error": str(exc)})
                return self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
            if p == "/api/backlog/leave.xlsx":
                v = leave_view(self._sprints(), (q.get("sprint") or "").strip())
                if not v.get("sprint"):
                    return self._send(404, {"error": v.get("error") or "no sprint"})
                path = os.path.join(STATE_DIR, "leave-%s.xlsx" % v["token"])
                os.makedirs(STATE_DIR, exist_ok=True)
                sprint_leave.xlsx(v["token"], v["sprint"], path)
                with open(path, "rb") as fh:
                    data = fh.read()
                os.remove(path)
                self.send_response(200)
                self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                self.send_header("Content-Disposition", 'attachment; filename="Sprint_%s_capacity.xlsx"' % v["token"])
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return None
            if p.startswith(("/api/backlog", "/api/poker/")):
                out = (self._poker(p, {"user": q.get("user", "")}) if p in ("/api/poker/room", "/api/poker/chat")
                       else self._backlog_get(p, q))
                if out is not None:
                    return self._send(200, out)
            if p == "/api/stories":
                if getattr(self.jira, "via", "") == "cloud":
                    return self._send(200, self.jira.stories(q.get("scope", "sprint"), q.get("user", ""),
                                                             refresh=bool(q.get("refresh"))))
                return self._send(200, stories_saved_first(self.jira, q.get("scope", "sprint"), q.get("user", ""),
                                                           refresh=bool(q.get("refresh"))))
            if p == "/api/pc":
                return self._send(200, dict(self._pc_config(), tests=self.pc.all()))
            if p == "/api/pc/lookup":
                return self._send(200, pctest.lookup(q.get("ticket", ""), sessions=self._ticket_sessions))
            if p == "/api/prs":
                return self._send(200, self.prs.status())
            if p == "/api/waiting/replies":
                return self._send(200, self.replies.status())
            if p == "/api/waiting/nudges":
                return self._send(200, self._nudges(q.get("user", ""), bool(q.get("refresh"))))
            if p == "/api/pc/history":
                m = re.search(r"([0-9a-f]{32})", q.get("session", ""))
                if not m:
                    return self._send(400, {"error": "give the Cloud session link or devin-<id>"})
                sid = "devin-" + m.group(1)
                runs = pctest.evidence_history(self.devin.messages(self.devin.session(sid)))
                return self._send(200, {"session": sid, "runs": runs})
            if p == "/api/pc/wrapup":
                sid, ticket = self._wrap_target(q)
                if not sid:
                    return self._send(400, {"error": "give the Cloud session and a %s ticket" % PROJECT})
                return self._send(200, dict(self._wrap_state(sid, ticket), session=sid, ticket=ticket))
            m = re.match(r"^/api/pc/([a-f0-9]{12})$", p)
            if m:
                return self._send(200, self.pc.public(m.group(1)))
            m = re.match(r"^/api/story/(%s)$" % team.TICKET, p)
            if m:
                return self._send(200, self.jira.story(m.group(1)))
            if p == "/api/runs":
                return self._send(200, self._runs_list())
            if p == "/api/status":
                # One background refresh for the page: the runs list and the PC tests, both from this PC only.
                return self._send(200, {"runs": self._runs_list(), "pc": dict(self._pc_config(), tests=self.pc.all())})
            m = re.match(r"^/api/runs/([a-f0-9]+)/bundle\.zip$", p)
            if m:
                run = self.store.runs.get(m.group(1))
                if not run:
                    return self._send(404, {"error": "no such run"})
                with self.store.lock:
                    data = self._bundle(run)
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Disposition", 'attachment; filename="%s-artefacts.zip"' %
                                 re.sub(r"[^A-Za-z0-9-]+", "_", run["story"]["key"]).strip("_"))
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return None
            m = re.match(r"^/api/runs/([a-f0-9]+)/trace\.txt$", p)
            if m:
                run = self.store.runs.get(m.group(1))
                if not run:
                    return self._send(404, {"error": "no such run"})
                with self.store.lock:
                    data = trace_text(run).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Disposition", 'attachment; filename="%s-trace.txt"' %
                                 re.sub(r"[^A-Za-z0-9-]+", "_", run["story"]["key"]).strip("_"))
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return None
            m = re.match(r"^/api/runs/([a-f0-9]+)$", p)
            if m:
                run = self.store.runs.get(m.group(1))
                if not run:
                    return self._send(404, {"error": "no such run"})
                run["watched_at"] = time.time()
                if q.get("refresh"):
                    self.poller.refresh(run["id"], force=True)
                with self.store.lock:
                    out = self.store.public(run)
                out["skill"] = skill_info(run["story"].get("action") or "") if run.get("kind") == "action" else None
                out["trace"] = trace_tree(run)
                return self._send(200, out)
            return self._send(404, {"error": "not found"})
        except (ApiError, pctest.PcError, backlog.BacklogError) as exc:
            return self._send(exc.status, {"error": str(exc)})
        except CLIENT_GONE:
            self.close_connection = True
            return None
        except Exception as exc:
            return self._send(500, {"error": "%s: %s" % (type(exc).__name__, exc)})

    def _poker(self, p, body):
        """Team poker across Argus pages; the round lives on each Argus's seat session (poker_room)."""
        tp = self.poker
        if tp is None:
            raise ApiError(409, "Team poker needs Devin Cloud: run Argus in Devin Cloud, or read Jira through it.")
        user, lens = (body.get("user") or "").strip(), body.get("lens") or ""
        try:
            if p == "/api/poker/room":
                return tp.room(user)
            if p == "/api/poker/chat":
                return poker_room.TeamChat(tp).inbox(user)
            if p == "/api/poker/chat/send":
                to = find_person(body.get("to") or "")
                if (body.get("to") or "").strip().lower() in ("everyone", poker_room.EVERYONE):
                    return poker_room.TeamChat(tp).send(user, poker_room.EVERYONE, body.get("text"))
                if not to:
                    raise ApiError(400, "%s is not on the roster." % (body.get("to") or "That person"))
                return poker_room.TeamChat(tp).send(user, to["jira_user"], body.get("text"))
            if p == "/api/poker/start":
                invite = body.get("invite") or []
                r = tp.start(user, lens, body.get("key"), invite, body.get("seconds"))
                if poker_room.DEVIN_SEAT in invite:
                    story = body.get("story") if isinstance(body.get("story"), dict) else {}
                    self.insight.start(dict(story, key=r["key"]), keep_done=True)
                return r
            if p == "/api/poker/vote":
                return tp.vote(user, body.get("round"), body.get("points"))
            if p == "/api/poker/reveal":
                return tp.reveal(user, lens, body.get("round"))
            if p == "/api/poker/again":
                return tp.again(user, lens, body.get("round"), body.get("seconds"))
            if p == "/api/poker/agree":
                rid = body.get("round")
                key = next((x["key"] for x in tp.room(user)["rounds"] if x["id"] == rid), "")
                basis = insight_basis(self.insight.get(key)) if key else ""
                r = tp.finish(user, lens, rid, body.get("points"), body.get("dissent") or [], basis)
                return dict(r, change=self.backlog.set_points(r["key"], r["points"], user),
                            note=self.backlog.note(r["key"], r["record"], user))
        except poker_room.PokerError as exc:
            raise ApiError(exc.status, str(exc))
        return None

    def _sprints(self):
        try:
            return self.backlog.sprints(team_board())
        except ApiError:
            return []

    def _backlog_get(self, p, q):
        if p == "/api/backlog":
            data = self.backlog.issues(q.get("user", ""), refresh=bool(q.get("refresh")))
            try:
                sprints = self.backlog.sprints(team_board())
            except ApiError as exc:
                sprints, data["error"] = [], data.get("error") or str(exc)
            return dict(data, sprints=sprints, mode=dict(self.backlog.mode(), velocity=plan_velocity()), browse=JIRA_BROWSE)
        if p == "/api/backlog/grooming-prep":
            data = self.backlog.issues(q.get("user", ""))
            plan, teams, cfg = grooming_prep.context()
            prep = grooming_prep.analyse_with_roadmap(data.get("stories") or [], data.get("epics") or [], self._sprints(),
                                         plan, teams, cfg)
            return dict(prep, html=grooming_prep.render(prep, JIRA_BROWSE, actions=True), source=data.get("source", ""),
                        pending=bool(data.get("pending")), error=data.get("error", ""))
        if p == "/api/backlog/leave":
            return leave_view(self._sprints(), (q.get("sprint") or "").strip())
        if p == "/api/backlog/followups":
            active = next((x for x in self._sprints() if x.get("state") == "active"), {})
            idle = idle_working_days()
            return dict(self.backlog.followups(active.get("id"), idle), sprint=active.get("name", ""), idle_days=idle,
                        **sprint_checks(self.backlog, active, self._sprints()))
        if p == "/api/backlog/previews":
            return {"previews": self.backlog.list_previews(), "mode": self.backlog.mode(), "browse": JIRA_BROWSE}
        if p == "/api/backlog/poker":
            return {"rounds": self.backlog.poker_for(q.get("key", ""))}
        if p == "/api/backlog/blockers":
            return {"blockers": self.backlog.blockers(self.backlog._key(q.get("key", "")))}
        if p == "/api/backlog/raise/options":
            return {"kinds": list(self.backlog.RAISE_KINDS), "severities": list(qs.SEVERITIES),
                    "environments": list(qs.DETECTED_IN), "specialties": backlog.specialties(),
                    "tenncare": backlog.TENNCARE}
        if p == "/api/backlog/episodes":
            return {"episodes": self.backlog.episodes()}
        if p == "/api/backlog/subtasks":
            return {"tickets": self.backlog.subtasks(q.get("key", ""))}
        if p == "/api/backlog/specialties":
            return {"specialties": backlog.specialties()}
        if p == "/api/backlog/insight":
            return self.insight.get((q.get("key") or "").strip().upper())
        if p == "/api/backlog/ac-rewrite":
            return self.ac_rewrite.get((q.get("key") or "").strip().upper())
        return None

    def _backlog_post(self, p, body):
        """Every Backlog tab write: planned as the exact Jira calls, shown back, sent only when allowed."""
        by = (body.get("user") or "").strip()
        b = self.backlog
        if p == "/api/backlog/points":
            return b.set_points(body.get("key"), body.get("points"), by)
        if p == "/api/backlog/move":
            return b.move(body.get("keys") or [], body.get("sprint"), by)
        if p == "/api/backlog/bulk":
            return b.bulk(body.get("keys") or [], body.get("field"), body.get("value"), by, bool(body.get("send")))
        if p == "/api/backlog/acceptance":
            return b.set_acceptance(body.get("key"), body.get("acceptance"), by, bool(body.get("suggested")))
        if p == "/api/backlog/insight":
            return self.insight.start(body.get("story") or {})
        if p == "/api/backlog/ac-rewrite":
            return self.ac_rewrite.start(body.get("story") or {}, body.get("answers"))
        if p == "/api/backlog/groom":
            return b.groom(body.get("key"), body, by)
        if p == "/api/backlog/specialties":
            return {"specialties": backlog.specialties()}
        if p == "/api/backlog/subtask-plan":
            draft = body.get("draft") or {}
            return {"subtasks": backlog.default_subtasks(dict(draft, subtasks=draft.get("subtasks") or [])),
                    "hours": draft.get("hours") or backlog.story_hours(draft.get("points"))}
        if p == "/api/backlog/raise":
            return b.raise_item(body.get("story"), body.get("kind"), body.get("title"), body.get("detail"), by,
                                specialty=body.get("specialty", ""), episode=body.get("episode", ""),
                                severity=body.get("severity") or "", environment=body.get("environment") or "",
                                assignee=body.get("assignee") or "")
        if p == "/api/backlog/order":
            return b.order(body.get("keys") or [], body.get("why") or "", by)
        if p == "/api/backlog/precheck":
            return {"checks": backlog.precheck(body.get("draft") or {})}
        if p == "/api/backlog/create":
            return b.create(body.get("draft") or {}, by, source=(body.get("source") or "")[:40])
        if p == "/api/backlog/clone":
            return b.clone(body.get("key"), by, body.get("overrides") or {})
        if p == "/api/backlog/note":
            return b.note(body.get("key"), body.get("text"), by, filename=(body.get("filename") or "")[:120])
        if p == "/api/backlog/sprint-sheet":
            import sprint_sheet
            try:
                return sprint_sheet.workbench_save((body.get("sprint") or "").strip(), body.get("edits") or {},
                                                   by or (body.get("by") or "").strip(), bool(body.get("write")))
            except sprint_sheet.SheetError as exc:
                raise backlog.BacklogError(400, str(exc))
        if p == "/api/backlog/leave":
            try:
                return sprint_leave.save((body.get("token") or "").strip(), body.get("sprint") or {}, by)
            except sprint_leave.LeaveError as exc:
                raise backlog.BacklogError(400, str(exc))
        if p == "/api/backlog/ai-label":
            return b.set_ai_label(body.get("key"), body.get("label"), by)
        if p == "/api/backlog/estimate":
            return b.set_estimate(body.get("key"), body.get("hours"), by)
        if p == "/api/backlog/hold":
            return b.hold(body.get("key"), body.get("why"), by)
        if p == "/api/backlog/resume":
            return b.resume(body.get("key"), by)
        if p == "/api/backlog/hours":
            return b.log_hours(body.get("key"), body.get("hours"), body.get("note"), by,
                               started=(body.get("started") or "")[:10])
        if p == "/api/backlog/poker/start":
            return b.poker_start(body.get("key"), by, body.get("voters") or [])
        if p == "/api/backlog/poker/vote":
            return b.poker_vote(body.get("round"), body.get("voter") or by, body.get("points"))
        if p == "/api/backlog/poker/reveal":
            return b.poker_reveal(body.get("round"))
        if p == "/api/backlog/poker/agree":
            return b.poker_agree(body.get("round"), body.get("points"), by)
        return None

    def do_POST(self):
        p = urllib.parse.urlparse(self.path).path
        try:
            body = self._body()
            if p.startswith(("/api/backlog/", "/api/poker/")):
                out = self._poker(p, body) if p.startswith("/api/poker/") else self._backlog_post(p, body)
                if out is not None:
                    return self._send(200, out)
            if p == "/api/actions":
                skill = (body.get("skill") or "").strip()
                text = (body.get("text") or "").strip()
                info = skill_info(skill)
                if not info:
                    return self._send(400, {"error": "no skill called %r in .devin/skills" % skill})
                if info["input"]["required"] and not text:
                    return self._send(400, {"error": "/%s needs %s" % (skill, info["input"]["hint"])})
                dry_run = bool(body.get("dry_run", True))
                requester = self._requester(body)
                if not body.get("fresh"):
                    with self.store.lock:
                        prev = self.store.recent_action(skill, text, dry_run, requester=requester)
                        if prev:
                            OBSERVER.note("repeat_action", "/%s started again within minutes" % skill, page="actions")
                            return self._send(200, dict(self.store.public(prev), reused=True))
                return self._send(201, self._start_action(skill, text, dry_run, requester=requester))
            if p == "/api/blocks":
                return self._save_block(body)
            if p == "/api/observe":
                where = body.get("where") if body.get("where") in ("screen",) else "screen"
                OBSERVER.note(where, (body.get("detail") or "")[:400], page=(body.get("page") or "")[:60])
                return self._send(200, {"ok": True})
            if p == "/api/feedback":
                return self._feedback(body)
            if p == "/api/validation/answers":
                block = (body.get("answers") or "").strip()
                if "SDLC-KB-VALIDATION-ANSWERS" not in block or "decision:" not in block:
                    return self._send(400, {"error": "that is not an answers block from the validation form"})
                text = "apply these answers\n\n```yaml\n%s\n```" % block
                return self._send(201, self._start_action("document-validation", text, bool(body.get("dry_run", True)),
                                                          "apply answers"))
            if p == "/api/sync":
                person = find_person(body.get("user") or DEFAULT_JIRA_USER)
                if not person or not person["email"]:
                    return self._send(200, {"seen": 0, "added": 0, "note": "pick who you are to load your runs"})
                email = person["email"]
                found = []
                for tag in (WORKBENCH_TAG, LEGACY_TAG):
                    found += self.devin.list_sessions(tag)
                added = self.store.adopt(found, email)
                return self._send(200, {"seen": len(found), "added": added})
            if p == "/api/key":
                key = (body.get("key") or "").strip()
                if not re.match(r"^[A-Za-z0-9_.:-]{20,300}$", key):
                    return self._send(400, {"error": "that does not look like a Devin API key"})
                probe = Devin()
                probe.key = key
                probe.list_sessions(WORKBENCH_TAG, 1)
                pctest.save_key(key)
                self.devin.key = key
                HEALTH.ok("devin")
                return self._send(200, {"saved": pctest.key_store()})
            if p == "/api/pc":
                return self._send(201, self.pc.start(body.get("ticket"), body.get("branch"), body.get("session"),
                                                     body.get("pack") or ""))
            if p == "/api/pc/login":
                return self._send(200, pctest.login())
            if p == "/api/prs/refresh":
                with self.store.lock:
                    nums = [pr_number(x.get("pr_url")) for r in self.store.runs.values()
                            for x in r.get("pull_requests") or []]
                return self._send(202, self.prs.refresh([n for n in nums if n]))
            if p == "/api/pc/history/jira":
                m = re.search(r"([0-9a-f]{32})", body.get("session") or "")
                ticket = (body.get("ticket") or "").strip().upper()
                if not m or not pctest.JIRA_TICKET.match(ticket):
                    return self._send(400, {"error": "give the Cloud session and a %s ticket" % PROJECT})
                sid = "devin-" + m.group(1)
                runs = pctest.evidence_history(self.devin.messages(self.devin.session(sid)))
                run = next((r for r in runs if r["event_id"] == body.get("event_id")), None)
                if not run:
                    return self._send(404, {"error": "that run is not in the Cloud session's evidence"})
                if run["jira"]["ticket"]:
                    return self._send(409, {"error": "this run was already sent to %s" % run["jira"]["ticket"]})
                self.devin.send(sid, pctest.jira_comment_request(run, ticket, JIRA_HOST))
                return self._send(200, {"asked": True, "ticket": ticket})
            if p in ("/api/pc/wrapup", "/api/pc/wrapup/jira"):
                sid, ticket = self._wrap_target(body)
                if not sid:
                    return self._send(400, {"error": "give the Cloud session and a %s ticket" % PROJECT})
                st = self._wrap_state(sid, ticket)
                if p == "/api/pc/wrapup":
                    if st["asked"] and not st["verdict"]:
                        return self._send(409, {"error": "Devin Cloud is still checking %s" % ticket})
                    self.devin.send(sid, pctest.wrapup_request(ticket, JIRA_HOST))
                    return self._send(200, {"asked": True, "ticket": ticket})
                if st["verdict"] != "ready":
                    return self._send(409, {"error": "Devin Cloud has not said %s is ready" % ticket})
                if st["move"]:
                    return self._send(409, {"error": "a Jira move was already asked for; check again to pick another"})
                pick = next((t for t in st["transitions"] if t["id"] == str(body.get("transition") or "")), None)
                if not pick:
                    return self._send(400, {"error": "that is not one of %s's Jira transitions" % ticket})
                self.devin.send(sid, pctest.jira_move_request(ticket, pick, JIRA_HOST))
                return self._send(200, {"asked": True, "ticket": ticket, "transition": pick})
            m = re.match(r"^/api/pc/([a-f0-9]{12})/(prompt|permission|return|release|stop)$", p)
            if m:
                tid, act = m.groups()
                if act == "prompt":
                    return self._send(200, self.pc.prompt(tid, body.get("text") or ""))
                if act == "permission":
                    return self._send(200, self.pc.permission(tid, body.get("request") or "", body.get("option") or ""))
                if act in ("return", "release"):
                    return self._send(200, self.pc.return_to_cloud(tid, release_only=act == "release"))
                return self._send(200, self.pc.stop_agent(tid))
            if p == "/api/dashboard":
                who = self._whoami(body.get("user", ""), body.get("role", ""))
                if not who["person"]:
                    return self._send(400, {"error": "pick who you are first (top right)"})
                actions = bool(body.get("actions"))
                out, url = (ACTIONS_PATH, "/actions") if actions else (DASHBOARD_PATH, "/dashboard")
                if getattr(self.jira, "via", "") == "cloud":
                    lens = who["role"]["lens"] if who["role"] else ""
                    dashboard_through_cloud(self.devin, who["person"]["jira_user"], lens, out, actions=actions)
                    return self._send(200, {"url": url, "via": "cloud"})
                lens = who["role"]["lens"] if who["role"] else ""
                saved = None if actions or body.get("rebuild") or DASHBOARD_CACHE else \
                    nightly_page(who["person"]["jira_user"], lens)
                if saved:
                    built_at = open_nightly_page(saved, out)
                    return self._send(200, {"url": url, "built_at": built_at, "saved": True})
                cmd = [sys.executable, GEN_DASHBOARD, "--user", who["person"]["jira_user"], "-o", out] + (["--actions"] if actions else [])
                if who["role"] and who["role"]["lens"]:
                    cmd += ["--lens", who["role"]["lens"]]
                if DASHBOARD_CACHE:
                    cmd += ["--cache", DASHBOARD_CACHE]
                sessions = self._my_sessions(who["person"])
                if sessions is not None:
                    cmd += ["--sessions", sessions]
                team_file = self._team_sessions(who["person"], lens)
                if team_file is not None:
                    cmd += ["--team-sessions", team_file]
                done = subprocess.run(cmd, capture_output=True, text=True, timeout=600, cwd=ROOT)
                if done.returncode:
                    return self._send(502, {"error": "dashboard failed: " + (done.stderr or done.stdout)[-600:]})
                return self._send(200, {"url": url, "log": done.stdout[-600:]})
            if p == "/api/update":
                return self._send(200, self.updater.apply())
            if p == "/api/shared-copy":
                if not can_build_copy():
                    return self._send(403, {"error": "only the people on act_as.allowed build the shared copy"})
                version = str(body.get("version") or "").strip()
                if not SHARED_COPY_VERSION_RE.match(version):
                    return self._send(400, {"error": "a version looks like 2.2.110126"})
                if body.get("action") == "pr":
                    prompt = shared_copy_prompt(version)
                    tags = [WORKBENCH_TAG, "action", SHARED_COPY_TAG, "live"]
                    run = self._new_request(action_story(SHARED_COPY_TAG, "Shared copy v%s" % version), False, "action",
                                            prompt, "Argus shared copy — v%s" % version, tags, own=True)
                    run["prompt"] = prompt
                    self.store.save()
                    return self._send(201, self.store.public(run))
                return self._send(202, SHARED_COPY.start(version))
            if p == "/api/desktop-icon":
                return self._send(*make_desktop_icon())
            if p == "/api/runs/open":
                m = re.search(r"(?:devin-)?([0-9a-f]{32})", str(body.get("session") or ""))
                if not m:
                    return self._send(400, {"error": "that is not a Devin session"})
                sid = "devin-" + m.group(1)
                with self.store.lock:
                    run = next((r for r in self.store.runs.values() if r.get("session_id") == sid), None)
                if not run:
                    info = dict(self.devin.session(sid), session_id=sid)
                    tags = list(info.get("tags") or [])
                    ticket = str(body.get("ticket") or "").strip().upper()
                    if TICKET_OR_REQ_RE.match(ticket) and ticket not in tags:
                        tags.append(ticket)
                    kind, story = run_from_tags(tags, info.get("title") or "")
                    run = self.store.new_run(story, "dry-run" in tags, dict(info, tags=tags), kind,
                                             created_at=iso_epoch(info.get("created_at")))
                with self.store.lock:
                    return self._send(200, self.store.public(run))
            if p == "/api/runs" and "create" in body:
                kind, text, files, dry_run, note = create_request(body, backlog.writes_on())
                story = custom_story(text or "%s from %s" % (kind, ", ".join(n for n, _ in files)))
                story["summary"] = "%s: %s" % (kind, story["summary"])
                folder = os.path.join(STATE_DIR, "create-uploads", story["key"] + "-" + uuid.uuid4().hex[:6])
                os.makedirs(folder, exist_ok=True)
                uploaded = []
                for name, data in files:
                    path = os.path.join(folder, name)
                    with open(path, "wb") as fh:
                        fh.write(data)
                    uploaded.append((name, self.devin.upload(path, name)))
                prompt = (build_roadmap_prompt(text, uploaded, dry_run, story["key"]) if kind == "Epics from a roadmap"
                          else build_create_prompt(kind, text, uploaded, dry_run, story["key"]))
                tags = [WORKBENCH_TAG, story["key"], CREATE_TAG, "dry-run" if dry_run else "live", "custom-requirement"]
                session = self.devin.create_session(
                    prompt, "Create %s %s — %s" % (kind.lower(), story["key"], story["summary"][:60]), tags)
                run = self.store.new_run(story, dry_run, dict(session, tags=tags))
                run["prompt"], run["note"] = prompt, note
                self.store.save()
                return self._send(201, dict(self.store.public(run), note=note))
            if p == "/api/runs" and "chat" in body:
                text = str(body.get("chat") or "").strip()
                if len(text) < 2:
                    return self._send(400, {"error": "type what you want to ask Devin"})
                tags = [WORKBENCH_TAG, CHAT_TAG, "live"]
                prompt = build_chat_prompt(text)
                run = self._new_request(chat_story(text), False, "chat", prompt,
                                        "Argus chat — %s" % text.splitlines()[0][:60], tags)
                run["prompt"] = prompt
                self.store.save()
                return self._send(201, self.store.public(run))
            if p == "/api/runs":
                key = body.get("key", "").strip().upper()
                text = (body.get("text") or "").strip()
                dry_run = bool(body.get("dry_run", True))
                local_test = bool(body.get("local_test"))
                if text:
                    if len(text) < 15:
                        return self._send(400, {"error": "say a little more — one full sentence is enough"})
                    story = custom_story(text)
                    key = story["key"]
                elif TICKET_RE.match(key):
                    story = self.jira.story(key)
                else:
                    return self._send(400, {"error": "pick a story (%s-1234) or type a requirement" % PROJECT})
                requester = self._requester(body)
                prompt = build_prompt(story, dry_run, local_test) + ("\n\n" + requester if requester else "")
                tags = ([WORKBENCH_TAG, key, "dry-run" if dry_run else "live"] + (["custom-requirement"] if text else [])
                        + (["local-test"] if local_test else []))
                session = self.devin.create_session(
                    prompt, "SDLC %s %s — %s" % ("dry run" if dry_run else "run", key, story["summary"][:60]), tags)
                run = self.store.new_run(story, dry_run, dict(session, tags=tags))
                run["prompt"] = prompt
                self.store.save()
                return self._send(201, self.store.public(run))
            if p == "/api/sessions/close":
                ids = [str(i) for i in body.get("session_ids") or [] if re.match(r"^(devin-)?[A-Za-z0-9_-]{8,64}$", str(i))]
                if not ids:
                    return self._send(400, {"error": "no session to close"})
                closed, failed = [], []
                for sid in ids:
                    try:
                        closed.append(close_session(self.devin, sid, self._tags_of(sid)))
                    except ApiError as exc:
                        failed.append({"session_id": sid, "error": str(exc)})
                with self.store.lock:
                    for run in self.store.runs.values():
                        if run.get("session_id") in closed:
                            run["closed_at"] = time.time()
                    self.store.save()
                return self._send(200, {"closed": closed, "failed": failed})
            if p == "/api/exit":
                return self._send(200, self._exit(body))
            if p == "/api/waiting/nudge-answer":
                return self._send(200, self._nudge_answer(body))
            if p == "/api/waiting/reply":
                user, key = str(body.get("user") or ""), str(body.get("key") or "")
                if not re.match(r"^[A-Za-z0-9._-]+$", user) or not TICKET_RE.match(key):
                    return self._send(400, {"error": "pick who you are and the sub-task"})
                issue = self._waiting_issue(user, key)
                if not issue:
                    return self._send(404, {"error": "%s is not in your Jira list; click Check now" % key})
                return self._send(200, self.replies.send(issue, str(body.get("kind") or ""), user, body.get("text")))
            if p == "/api/sessions/archive":
                m = re.search(r"([0-9a-f]{32})", str(body.get("session") or ""))
                if not m:
                    return self._send(400, {"error": "give the Cloud session"})
                sid, on = "devin-" + m.group(1), bool(body.get("archived", True))
                tags = set(self.devin.session(sid).get("tags") or ())
                self.devin.set_tags(sid, sorted(tags | {ARCHIVED_TAG} if on else tags - {ARCHIVED_TAG}))
                with self.store.lock:
                    for run in self.store.runs.values():
                        if run.get("session_id") == sid:
                            run["archived"] = on
                    self.store.save()
                return self._send(200, {"session": sid, "archived": on})
            m = re.match(r"^/api/runs/([a-f0-9]+)/delete$", p)
            if m:
                run = self.store.runs.get(m.group(1))
                if not run:
                    return self._send(404, {"error": "no such run"})
                if run.get("session_id") and not run.get("assistant"):
                    try:
                        close_session(self.devin, run["session_id"], set(run.get("tags") or ()) | {DELETED_TAG})
                    except ApiError as exc:
                        return self._send(502, {"error": "Could not end the Devin session, so nothing was deleted: %s" % exc})
                self.store.delete(m.group(1))
                return self._send(200, {"deleted": m.group(1), "session_id": run.get("session_id")})
            m = re.match(r"^/api/runs/([a-f0-9]+)/fresh$", p)
            if m:
                run = self.store.runs.get(m.group(1))
                if not run:
                    return self._send(404, {"error": "no such run"})
                if run.get("kind") not in ("chat", "action"):
                    return self._send(400, {"error": "only a chat or menu item can move to a new session"})
                with self.store.lock:
                    handover = self.store.handover_text(run["session_id"])
                text = str(body.get("text") or "").strip() or "Carry on from the handover above."
                tags = [WORKBENCH_TAG, CHAT_TAG, "live"]
                prompt = build_chat_prompt(text)
                story = chat_story(text)
                if SHARED_ASSISTANT and run.get("assistant"):
                    new = self._new_request(story, False, "chat", prompt, "Argus chat — %s" % text[:60], tags, fresh=True)
                else:
                    session = self.devin.create_session(handover + prompt, "Argus chat — %s" % text[:60], tags)
                    new = self.store.new_run(story, False, dict(session, tags=tags), kind="chat")
                new["prompt"], new["fresh_from"] = prompt, run["id"]
                self.store.save()
                return self._send(201, self.store.public(new))
            m = re.match(r"^/api/runs/([a-f0-9]+)/close$", p)
            if m:
                if m.group(1) not in self.store.runs:
                    return self._send(404, {"error": "no such run"})
                self.poller.close(m.group(1))
                return self._send(200, self.store.public(self.store.runs[m.group(1)]))
            m = re.match(r"^/api/runs/([a-f0-9]+)/(message|answers|gate|forward|wake|attach)$", p)
            if not m:
                return self._send(404, {"error": "not found"})
            run = self.store.runs.get(m.group(1))
            if not run:
                return self._send(404, {"error": "no such run"})
            action = m.group(2)
            if action == "message":
                text = body.get("text", "").strip()
            elif action == "answers":
                items = body.get("answers") or []
                text = "\n".join("%s. %s" % (a.get("n"), a.get("text", "").strip()) for a in items if a.get("text", "").strip())
            elif action == "gate":
                decision = body.get("decision")
                note = body.get("note", "").strip()
                gate_id = (run.get("pending_gate") or {}).get("id", "")
                if decision == "approve":
                    text = "approved %s" % gate_id
                elif decision == "approve_notes":
                    text = "approved %s with notes: %s" % (gate_id, note or "(none)")
                elif decision == "reject":
                    if not note:
                        return self._send(400, {"error": "a rejection needs reasons"})
                    text = "rejected %s — %s" % (gate_id, note)
                elif decision == "items":
                    wanted = [i["n"] for i in (run.get("pending_gate") or {}).get("items") or [{"n": 1}]]
                    picks = {}
                    for it in body.get("items") or []:
                        try:
                            picks[int(it.get("n"))] = (it.get("decision"), str(it.get("note") or "").strip())
                        except (TypeError, ValueError):
                            continue
                    open_items = [n for n in wanted if picks.get(n, (None,))[0] not in ("approve", "reject")]
                    if open_items:
                        return self._send(400, {"error": "decide every item first: %s" % ", ".join(map(str, open_items))})
                    if any(picks[n][0] == "reject" and not picks[n][1] for n in wanted):
                        return self._send(400, {"error": "a rejected item needs reasons"})
                    text = items_reply(gate_id, wanted, picks)
                    decision = "reject" if any(picks[n][0] == "reject" for n in wanted) else "approve"
                else:
                    return self._send(400, {"error": "decision must be approve, approve_notes, reject or items"})
                if body.get("subtasks") and decision != "reject":
                    text += self._gate_subtasks(run, gate_id, body)
                if body.get("create_jira") and decision != "reject" and getattr(self.jira, "via", "") == "cloud":
                    text += self._cloud_story_request(body)
                elif body.get("create_jira") and decision != "reject":
                    created = self._create_story(run, body)
                    text += "\n[SDLC] note jira %s — created from the intake spec, assigned to %s. Use it as the story key from here on." % (
                        created["key"], created["assignee"] or "nobody")
            elif action == "forward":
                gate = run.get("pending_gate")
                person = (body.get("person") or "").strip()
                note = (body.get("note") or "").strip()
                if not gate:
                    return self._send(400, {"error": "there is no open gate to forward"})
                if not find_person(person):
                    return self._send(400, {"error": "pick someone from the roster"})
                if not note:
                    return self._send(400, {"error": "say in one sentence why this person, and what to look at"})
                if run["story"].get("custom") and not run.get("jira_story"):
                    return self._send(400, {"error": "forwarding creates a Jira approval sub-task, so this run needs a "
                                                     f"{PROJECT} story first (tick 'create a Jira story' at the intake gate)"})
                text = forward_text(gate["id"], person, note, body.get("items", ""))
            elif action == "wake":
                text = ("Argus: carry on from where you stopped. If you are waiting on me, repeat the open "
                        "question or gate.")
                now = time.time()
                with self.store.lock:
                    run["wakes"] = [t for t in run.get("wakes") or [] if now - t < WAKE_WINDOW] + [now]
                    wakes = len(run["wakes"])
                if wakes >= WAKE_REPEAT:
                    OBSERVER.note("wake_repeat", "Wake pressed %d times in %d minutes on a %s run at stage %s (%s)" % (
                        wakes, WAKE_WINDOW // 60, run.get("kind"), run.get("stage") or "-",
                        run.get("status_detail") or run.get("status")), page=run.get("stage") or "")
            else:
                return self._send(400, {"error": "unsupported"})
            if not text:
                return self._send(400, {"error": "nothing to send"})
            self._send_to_session(run, text)
            with self.store.lock:
                run["sent_at"] = time.time()
                if action == "forward":
                    run["forwarded"].append({"gate": run["pending_gate"]["id"], "person": body.get("person"),
                                             "note": body.get("note"), "at": time.time()})
                if action == "answers":
                    run["pending_questions"] = None
                if action == "gate":
                    run["pending_gate"] = None
                self.store.save()
            if action == "gate" and decision == "reject":
                self.poller.close(run["id"])
                return self._send(200, {"sent": text, "closed": True})
            return self._send(200, {"sent": text})
        except (ApiError, pctest.PcError, backlog.BacklogError) as exc:
            return self._send(exc.status, {"error": str(exc)})
        except CLIENT_GONE:
            self.close_connection = True
            return None
        except Exception as exc:
            return self._send(500, {"error": "%s: %s" % (type(exc).__name__, exc)})


SHARED_COPY_VERSION_RE = re.compile(r"^\d+(\.\d+)*$")


def can_build_copy():
    """Build shared copy is for the people on act_as.allowed, and only once Argus knows who you are."""
    return bool(DEFAULT_JIRA_USER) and DEFAULT_JIRA_USER.upper() in team.ACT_AS


def current_copy_version():
    try:
        with open(os.path.join(team.FRAMEWORK_DIR, "tools", "distribution_map.yaml"), encoding="utf-8") as fh:
            m = re.search(r'(?m)^version:\s*"?([^"\n]+)"?', fh.read())
        return m.group(1).strip() if m else ""
    except OSError:
        pass
    try:
        with open(os.path.join(team.FRAMEWORK_DIR, "tools", "VERSION"), encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def shared_copy_prompt(version):
    return "\n".join([
        "Repository: @%s" % REPO_SLUG,
        "",
        "Rebuild the shared copy of Argus as version %s. It was asked for from the %s by a "
        "person on act_as.allowed." % (version, WORKBENCH_TITLE),
        "1. Branch devin/<timestamp>-shared-copy-v%s from origin/%s." % (version, KB_BRANCH),
        "2. Run `python3 %s/tools/build_distribution.py --version %s`. It writes the version "
        "into tools/distribution_map.yaml and builds sdlc/kb/v%s and its zip. Older dated folders stay as they "
        "are." % (team.FRAMEWORK, version, version),
        "3. Stop if the leak count is not 0, and post the LEAK lines.",
        "4. Run the copy's checks: from %s/tools, "
        "`python3 -c \"import build_distribution as b; print(b.run_checks('<repo>/sdlc/kb/v%s'))\"`."
        % (team.FRAMEWORK, version),
        "5. Post the file count, the leak count and the check result, and wait for a reply that starts with "
        "`approved` before you commit.",
        "6. Commit distribution_map.yaml, sdlc/kb/v%s and sdlc/kb/v%s.zip and open a PR into %s. "
        "Post the PR link." % (version, version, KB_BRANCH),
    ])


class SharedCopyBuild:
    """Check here: build_distribution.py --scratch in the background, one build at a time."""

    def __init__(self):
        self.lock = threading.Lock()
        self.state = {"running": False, "version": "", "exit": None, "log": "", "zip": "", "leaks": None}

    def status(self):
        with self.lock:
            return dict(self.state)

    def start(self, version):
        with self.lock:
            if self.state["running"]:
                return dict(self.state)
            self.state = {"running": True, "version": version, "exit": None, "log": "", "zip": "", "leaks": None}
        threading.Thread(target=self._run, args=(version,), daemon=True).start()
        return self.status()

    def _run(self, version):
        try:
            done = subprocess.run([sys.executable, BUILD_DISTRIBUTION, "--scratch", "--version", version],
                                  capture_output=True, text=True, errors="replace", timeout=1800, cwd=ROOT)
            code, log = done.returncode, (done.stdout + done.stderr)
        except (OSError, subprocess.SubprocessError) as exc:
            code, log = 1, str(exc)
        leaks = re.search(r"(\d+) leak\(s\)", log)
        zip_path = re.search(r"(?m)^ZIP (.+)$", log)
        with self.lock:
            self.state.update(running=False, exit=code, log=log[-4000:],
                              leaks=int(leaks.group(1)) if leaks else None,
                              zip=zip_path.group(1).strip() if zip_path else "")


SHARED_COPY = SharedCopyBuild()


def can_switch_user():
    """Whether this Argus may show Me > Who you are: it started as someone on act_as.allowed, or as nobody yet."""
    return not DEFAULT_JIRA_USER or DEFAULT_JIRA_USER.upper() in team.ACT_AS


def set_default_user(who):
    """Resolve --user to the roster's Jira username; an unknown person leaves the page asking."""
    global DEFAULT_JIRA_USER
    person = find_person(who)
    DEFAULT_JIRA_USER = person["jira_user"] if person else ""
    if who and not person:
        print("--user %r is not on %s; the page will ask who you are" % (who, PEOPLE_PATH))
    elif person:
        print("Argus opens as %s (%s)" % (person["name"], person["jira_user"]))


ON_WINDOWS = os.name == "nt"
DESKTOP_ICON_PS = (
    "$q=[char]34; $lnk=[Environment]::GetFolderPath('Desktop')+'\\@SHORT@.lnk';"
    "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($lnk);"
    "$s.TargetPath=$env:ComSpec; $s.Arguments='/c '+$q+$q+$env:TARGET+$q+' '+$env:WB_ARG+$q;"
    "$s.WorkingDirectory=$env:REPO; $s.WindowStyle=7; $s.Description='@TITLE@';"
    "$s.IconLocation=$env:SystemRoot+'\\System32\\shell32.dll,13'; $s.Save(); Write-Output ('Made '+$lnk)"
).replace("@SHORT@", WORKBENCH_SHORT.replace("'", "''")).replace("@TITLE@", WORKBENCH_TITLE.replace("'", "''"))


def make_desktop_icon():
    """Settings → Create desktop icon: the same Argus icon make-shortcut.cmd puts on the desktop."""
    if not ON_WINDOWS:
        return 400, {"error": "The desktop icon is for a Windows PC. Start Argus on your PC and try there."}
    env = dict(os.environ, TARGET=os.path.join(HERE, "start-workbench.cmd"), REPO=ROOT, WB_ARG="")
    try:
        done = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", DESKTOP_ICON_PS],
                              env=env, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 502, {"error": "Could not make the icon: %s" % e}
    out = (done.stdout or "").strip()
    if done.returncode or not out.startswith("Made "):
        return 502, {"error": "Could not make the icon: " + ((done.stderr or out).strip()[-300:] or "PowerShell said nothing")}
    return 200, {"ok": True, "path": out[len("Made "):]}


def pc_busy():
    """Why Argus must not restart now: a Test on my PC run that is still going."""
    for t in Handler.pc.tests.values():
        if t.get("state") in ("preparing", "testing", "returning"):
            return "A test of %s is still running on this PC. Return it to Cloud or stop it first." % t.get("ticket")
    return ""


def integrations(devin, jira):
    """Each outside system: configured (a key or setting is there) apart from connected (its last call worked)."""
    via = getattr(jira, "via", "here")
    jira_set = bool(getattr(jira, "token", None)) or (via == "cloud" and bool(getattr(devin, "key", None)))
    return {"jira": HEALTH.report("jira", jira_set, "Devin Cloud" if via == "cloud" else JIRA_HOST),
            "devin": HEALTH.report("devin", getattr(devin, "key", None), DEVIN_API),
            "bitbucket": HEALTH.report("bitbucket", True, "Bitbucket")}


update.ON_FETCH = lambda ok, err: HEALTH.ok("bitbucket") if ok else HEALTH.fail("bitbucket", "Bitbucket could not be reached: " + (err or "git fetch failed"))


def check_integrations(devin, jira):
    """Call each configured system once, so its state is a real answer and not just a key being there."""
    if getattr(devin, "dir", None) and devin.reconnecting():
        HEALTH.wait("devin", bridge.RECONNECT_HINT)
    elif getattr(devin, "key", None) or getattr(devin, "dir", None):
        try:
            devin.list_sessions(WORKBENCH_TAG, limit=1)
        except ApiError:
            pass
    if getattr(jira, "via", "") == "cloud":
        cloud = HEALTH.report("devin", getattr(devin, "key", None))
        if cloud["state"] == "failing":
            HEALTH.fail("jira", "Jira is read through Devin Cloud, which failed: %s" % cloud["error"])
    elif getattr(jira, "token", None):
        try:
            jira.recheck()
        except ApiError:
            pass


def nightly_page(jira_user, lens=""):
    """The newest page the nightly build saved for this person (and lens, when one is picked), or None."""
    try:
        names = os.listdir(NIGHTLY_DIR)
    except OSError:
        return None
    mine = [n for n in names if n.endswith(".html") and n.split(".")[0] == jira_user
            and (not lens or n == "%s.%s.html" % (jira_user, lens))]
    paths = [os.path.join(NIGHTLY_DIR, n) for n in mine]
    return max(paths, key=os.path.getmtime) if paths else None


def eastern(t):
    try:
        import zoneinfo
        return datetime.datetime.fromtimestamp(t, zoneinfo.ZoneInfo(NIGHTLY_TZ))
    except Exception:  # noqa: BLE001 - no time zone data: the box's own clock
        return datetime.datetime.fromtimestamp(t)


NIGHTLY_BAR = (
    '<div id="argusBuilt" style="position:sticky;top:0;z-index:50;padding:6px 14px;background:#efeaf8;'
    'color:#3b2a63;font:13px system-ui,sans-serif">Built at %s from Jira. <a href="#" id="argusRebuild">'
    'Rebuild now</a> <span id="argusRebuildMsg"></span></div><script>document.getElementById("argusRebuild")'
    '.onclick=function(e){e.preventDefault();var m=document.getElementById("argusRebuildMsg");'
    'm.textContent="Building from Jira, this takes a few minutes\u2026";fetch("/api/dashboard",{method:"POST",'
    'headers:{"Content-Type":"application/json"},body:JSON.stringify({user:localStorage.getItem("sdlc-jira-me")||"",'
    'role:localStorage.getItem("sdlc-role-preview")||"",rebuild:true})}).then(function(r){return r.json().then('
    'function(j){if(!r.ok){throw new Error(j.error||r.statusText);}location=j.url+"?t="+Date.now();});})'
    '.catch(function(x){m.textContent="Could not rebuild: "+x.message;});};</script>')


def open_nightly_page(saved, out):
    """Copies the saved page to the /dashboard file with a "Built at <time>" bar and a Rebuild now link."""
    built = os.path.getmtime(saved)
    with open(saved, encoding="utf-8") as fh:
        page = fh.read()
    bar = NIGHTLY_BAR % eastern(built).strftime("%-I:%M %p %Z on %b %-d")
    page = re.sub(r"(<body[^>]*>)", lambda m: m.group(1) + bar, page, count=1) if "<body" in page else bar + page
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(page)
    return built


def last_nightly_due(now):
    """The most recent NIGHTLY_AT in NIGHTLY_TZ at or before `now`, as a timestamp."""
    local = eastern(now)
    due = local.replace(hour=NIGHTLY_AT[0], minute=NIGHTLY_AT[1], second=0, microsecond=0)
    if due > local:
        due -= datetime.timedelta(days=1)
    return due.timestamp()


def nightly_attempted():
    try:
        with open(os.path.join(NIGHTLY_DIR, "last-run.json")) as fh:
            return float(json.load(fh).get("at") or 0)
    except (OSError, ValueError, TypeError):
        return 0.0


SHARED_READS = os.path.relpath(os.path.join(team.FRAMEWORK_DIR, "context", "dashboard-data", "jira-reads.json"),
                               ROOT).replace(os.sep, "/")
SHARED_READS_MAX_AGE = 36 * 3600
_DATA_AGE = {"at": 0.0, "value": None}


def shared_reads(out_path, now=None):
    """Copy the team's shared nightly Jira answers (merged into the KB branch) to out_path; True when there are
    some from the last SHARED_READS_MAX_AGE, False when this Argus must read Jira itself."""
    try:
        raw, _ = repo_file(SHARED_READS)
        data = json.loads(raw)
    except (OSError, ValueError):
        return False
    if not isinstance(data, dict) or not data.get("reads") or \
            (now or time.time()) - float(data.get("saved_at") or 0) > SHARED_READS_MAX_AGE:
        return False
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path + ".tmp", "wb") as fh:
        fh.write(raw)
    os.replace(out_path + ".tmp", out_path)
    return True


def shared_data_age(now=None):
    """{"saved_at", "stale"} of the shared nightly dashboard data on the KB branch (read at most every 10 minutes),
    or None when there is none yet."""
    now = now or time.time()
    if now - _DATA_AGE["at"] < 600:
        return _DATA_AGE["value"]
    _DATA_AGE["at"] = now
    try:
        saved = float(json.loads(repo_file(SHARED_READS)[0]).get("saved_at") or 0)
    except (OSError, ValueError, TypeError, AttributeError):
        _DATA_AGE["value"] = None
        return None
    _DATA_AGE["value"] = {"saved_at": saved, "stale": now - saved > SHARED_READS_MAX_AGE}
    return _DATA_AGE["value"]


def nightly_dashboards(check_every=300, run=subprocess.run):
    """At NIGHTLY_AT each night, or as soon as Argus wakes after it, builds this Argus person's dashboards from the
    team's shared nightly Jira answers (one scheduled Devin Cloud build reads Jira for everyone); with none from
    the last day and a half it reads Jira itself, for this person only (every roster person when none is set).
    The shared answers come from the Argus maintenance job "nightly dashboard data", which commits them to the
    KB branch."""
    while True:
        time.sleep(check_every)
        try:
            if nightly_attempted() >= last_nightly_due(time.time()):
                continue
            os.makedirs(NIGHTLY_DIR, exist_ok=True)
            with open(os.path.join(NIGHTLY_DIR, "last-run.json"), "w") as fh:
                json.dump({"at": time.time()}, fh)
            cmd = [sys.executable, GEN_DASHBOARD, "--all", NIGHTLY_DIR]
            if DEFAULT_JIRA_USER:
                cmd += ["--user", DEFAULT_JIRA_USER]
            reads = os.path.join(NIGHTLY_DIR, "jira-reads.json")
            if shared_reads(reads):
                cmd += ["--reads", reads]
            done = run(cmd, capture_output=True, text=True, timeout=NIGHTLY_TIMEOUT, cwd=ROOT)
            if done.returncode:
                OBSERVER.note("api", "nightly dashboards failed: %s" % (done.stderr or done.stdout)[-300:],
                              page="dashboard")
        except Exception as exc:  # noqa: BLE001  never stop Argus over the nightly build
            OBSERVER.note("api", "nightly dashboards failed: %s" % exc, page="dashboard")


def daily_feedback(check_every=600):
    """Noticed problems go to the Leads dashboard on their own once a day, even if nobody opens the form."""
    while True:
        time.sleep(check_every)
        try:
            if DEFAULT_JIRA_USER and OBSERVER.daily_due(FEEDBACK_SEND_HOURS):
                handler = Handler.__new__(Handler)
                handler._send_feedback({"user": DEFAULT_JIRA_USER}, update.about(ROOT))
        except Exception as exc:  # noqa: BLE001  never stop Argus over a feedback send
            OBSERVER.note("api", "daily feedback send failed: %s" % exc, page="feedback")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--user", default=DEFAULT_JIRA_USER,
                    help="who is using the page: Jira username, e-mail or Devin user id on people.yaml")
    ap.add_argument("--cloud-stories", metavar="SCOPES",
                    help="in Devin Cloud: read ticket lists (comma-separated) with the Jira service account and attach them")
    ap.add_argument("--req", default="", help="with --cloud-stories: Argus's read id, added to each file name")
    ap.add_argument("--cloud-dashboard", action="store_true",
                    help="in Devin Cloud: build --user's dashboard with the Jira service account and attach it")
    ap.add_argument("--lens", default="", help="with --cloud-dashboard: the role lens to build")
    ap.add_argument("--actions", action="store_true", help="with --cloud-dashboard: build the actions page")
    args = ap.parse_args()
    if args.cloud_stories:
        return cloud_stories(args.cloud_stories, args.user, args.req)
    if args.cloud_dashboard:
        return cloud_dashboard(args.user, args.lens, actions=args.actions)
    set_default_user(args.user)
    Handler.store = Store()
    Handler.devin = make_devin()
    Handler.jira = Jira() if os.environ.get(JIRA_TOKEN_ENV) else CloudJira(Handler.devin)
    Handler.backlog = backlog.Backlog(Handler.jira, STATE_DIR)
    Handler.backlog.started = Handler.store.sdlc_started
    if getattr(Handler.jira, "via", "") == "cloud":
        Handler.poker = poker_room.TeamPoker(Handler.devin, lambda: Handler.jira.reader().get("session_id", ""),
                                             devin_vote=lambda key: Handler.insight.card(key))
    elif isinstance(Handler.devin, bridge.BridgeDevin):
        Handler.poker = poker_room.TeamPoker(
            Handler.devin, Handler.devin.host_session, devin_vote=lambda key: Handler.insight.card(key),
            tag=poker_room.SEAT_TAG, missing="Argus's Devin bridge has not started yet: send any message to "
                                             "the Devin session that hosts this Argus, then try again.")
    Handler.pc = pctest.PcTests()
    Handler.prs = CloudPrs(Handler.devin)
    Handler.replies = CloudReplies(Handler.devin)
    Handler.insight = StoryInsight(Handler.devin)
    Handler.ac_rewrite = AcRewrite(Handler.devin)
    Handler.updater = update.Updater(ROOT, busy=pc_busy, fetch=UPDATE_FETCH)
    Handler.poller = Poller(Handler.store, Handler.devin)
    Handler.poller.start()
    threading.Thread(target=check_integrations, args=(Handler.devin, Handler.jira), daemon=True).start()
    threading.Thread(target=daily_feedback, daemon=True).start()
    if Handler.jira.token and os.environ.get("SDLC_NIGHTLY_DASHBOARDS", "on") != "off":
        threading.Thread(target=nightly_dashboards, daemon=True).start()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    Handler.updater.restart = srv.shutdown
    Handler.stop = srv.shutdown
    print(WORKBENCH_TITLE + " on http://%s:%d  (Devin API %s, Jira %s)" % (
        args.host, args.port, "through this Devin session" if bridge.transport() == "bridge"
        else "key set, not checked yet (see Health)" if Handler.devin.key else "NO KEY - add it on the page",
        "read here" if Handler.jira.token else "read through Devin Cloud"))
    srv.serve_forever()
    srv.server_close()
    if Handler.updater.restarting:
        print("Argus updated; restarting")
        update.restart_process()


if __name__ == "__main__":
    sys.exit(main())
