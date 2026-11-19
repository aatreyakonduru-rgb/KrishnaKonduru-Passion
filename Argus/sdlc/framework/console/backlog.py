"""Backlog tab of Argus — the PO's day-to-day Jira work from buttons.

Grooming, pointing, planning poker, moving stories between sprints, cloning, creating an epic or
story from pasted notes and adding notes to a ticket. Reading uses Argus's Jira object
(service account, or the Cloud reader on a PC). Every write is planned as the exact Jira calls it
would make and shown back as a preview; nothing is sent to Jira unless both

  * writes are switched on   — SDLC_BACKLOG_WRITES=1 in Argus's environment, and
  * the ticket is allowed    — its key (or, for a new ticket, its parent/epic) is in
                               SDLC_BACKLOG_TICKETS, a comma-separated allow-list.

Every planned write names the person who asked for it (label ``requested-by-<jira user>`` and a
comment), so the shared service account never hides who did what. Previews and poker rounds are
kept under ~/.sdlc/console/.
"""
import datetime
import json
import os
import re
import sys
import threading
import time
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import sdlc_profile as team  # noqa: E402
import question_subtask as qs  # noqa: E402

PROJECT = team.PROJECT
IT_TEAM = team.IT_TEAM
PHASES = team.PHASES
F_POINTS = team.FIELDS["story_points"]
F_SPRINT = team.FIELDS["sprint"]
F_ACCEPTANCE = team.FIELDS["acceptance"]
F_IT_TEAM = team.FIELDS["it_team"]
F_EPIC_LINK = "customfield_10010"
F_PRIORITY = "customfield_10012"
F_EPIC_NAME = "customfield_10020"
WRITES_ENV = "SDLC_BACKLOG_WRITES"
TICKETS_ENV = "SDLC_BACKLOG_TICKETS"
TEAM_CLAUSE = 'project = %s AND "IT Team" = %s' % (PROJECT, IT_TEAM)
BACKLOG_JQL = (TEAM_CLAUSE + " AND resolution = Unresolved AND issuetype in (Story, Bug, Task, Defect)"
               " AND (sprint is EMPTY OR sprint in openSprints() OR sprint in futureSprints()) ORDER BY rank ASC")
EPICS_JQL = TEAM_CLAUSE + " AND issuetype = Epic AND resolution = Unresolved ORDER BY summary ASC"
DEMO_LABELS = ("DEMO-NEEDED", "Demo")
DEMO_JQL = (TEAM_CLAUSE + ' AND labels in ("DEMO-NEEDED", "Demo") AND status in ({statuses.demo_ready})'
            " ORDER BY updated ASC")
AI_LABELS = ("AI-Used", "AI-NA")
POINT_SCALE = (1, 2, 3, 5, 8, 13)
SUGGESTED_AC_LABEL = "suggested-acceptance-criteria"
DEVIN_CREATED_LABEL = "devin_created"
URL_RE = re.compile(r"https?://\S+")
PLACEHOLDER_AC = re.compile(r"please enter acceptance criteria", re.I)
NUMBERED = re.compile(r"(?m)^\s*\d+[.)]\s+\S")
SPRINT_NAME = re.compile(r"name=([^,\]]+)")
MAX_PREVIEWS = 200
NEW_PARENT = "<new story>"
TICKET_RE = re.compile(r"^%s$" % team.TICKET)


class BacklogError(Exception):
    def __init__(self, status, message):
        Exception.__init__(self, message)
        self.status = status


def writes_on(env=None):
    return (env if env is not None else os.environ).get(WRITES_ENV, "") == "1"


def allowed_tickets(env=None):
    raw = (env if env is not None else os.environ).get(TICKETS_ENV, "")
    return sorted({t.strip().upper() for t in raw.split(",") if t.strip()})


def sprint_names(value):
    names = []
    for item in value or []:
        if isinstance(item, dict):
            names.append(item.get("name", ""))
        else:
            m = SPRINT_NAME.search(str(item))
            names.append(m.group(1) if m else str(item))
    return [n for n in names if n]


def requester_label(jira_user):
    return "requested-by-" + re.sub(r"[^a-z0-9]+", "-", (jira_user or "").lower()).strip("-")


def _working_days_since(day, today):
    """Mon-Fri days from `day` (YYYY-MM-DD) to today, not counting `day` itself."""
    try:
        d = datetime.date.fromisoformat(day)
    except ValueError:
        return 0
    n = 0
    while d < today:
        d += datetime.timedelta(days=1)
        n += d.weekday() < 5
    return n


def on_behalf(jira_user, what):
    return ("%s — asked for by %s through Argus (service account write)."
            % (what, jira_user or "unknown"))


# ----------------------------------------------------------------------------- rule-book precheck
SPECIALTY_FILE = os.path.join(team.ROOT, ".devin", "rules", "defect-specialties.yaml")
CROSS_CUTTING = "Platform"
# TennCare defect titles (jira-ticket-standards.yaml -> defect.tenncare_prefix)
TENNCARE = {"PCMH": "PCMH", "THL": "THL", "EOC": "EoC"}
TENNCARE_RE = re.compile(r"^(SIT|UAT)-TC-(PCMH|THL|EoC): (.+)$")
EOC_RE = re.compile(r"^(SIT|UAT)-TC-EoC: ([^-]+?) - .+$")
EPISODES_JQL = ("project = %s AND issuetype in (Defect, Bug, Story) AND summary ~ \"TC-EoC\" "
                "ORDER BY updated DESC")


def defect_phase(environment):
    """SIT / UAT / PROD from a Jira 'Detected in' value, or '' when it is none of those."""
    e = (environment or "").upper()
    if "(SIT)" in e or "SYSTEM INTEGRATION" in e:
        return "SIT"
    if "(UAT)" in e or "USER ACCEPTANCE" in e:
        return "UAT"
    if "PRODUCTION" in e:
        return "PROD"
    return ""


def defect_title(title, specialty, environment, episode=""):
    """The title the rule book wants for a defect raised from Argus.

    TennCare specialties (PCMH, THL, EOC) found in SIT or UAT get '<SIT|UAT>-TC-<token>: title', EoC with
    '<Episode> - ' in front of the title; anything else keeps '<Specialty> - title - <PHASE>'."""
    title = " ".join((title or "").split())
    if TENNCARE_RE.match(title):
        return title
    phase = defect_phase(environment)
    sp = (specialty or "").strip()
    token = TENNCARE.get(sp.upper())
    if token and phase in ("SIT", "UAT"):
        body = ("%s - %s" % (episode.strip(), title)) if token == "EoC" and episode else title
        return "%s-TC-%s: %s" % (phase, token, body)
    if sp and not re.match(r"^%s\s+-\s" % re.escape(sp), title, re.I):
        title = "%s - %s" % (sp, title)
    if phase and not re.search(r"\s-\s*%s$" % phase, title, re.I):
        title = "%s - %s" % (title, phase)
    return title


def tenncare_title_check(summary, specialty, environment):
    """Text of what the rule book would flag on a defect title, or '' when it is fine."""
    summary = (summary or "").strip()
    phase = defect_phase(environment)
    token = TENNCARE.get((specialty or "").strip().upper())
    if token and phase in ("SIT", "UAT"):
        m = TENNCARE_RE.match(summary)
        if not m or m.group(1) != phase or m.group(2) != token:
            return "TennCare %s defects are titled '%s-TC-%s: what is wrong, where'." % (token, phase, token)
        if token == "EoC" and not EOC_RE.match(summary):
            return "EoC defects name the episode first: '%s-TC-EoC: <Episode> - what is wrong'." % phase
    return ""


def specialties(path=SPECIALTY_FILE):
    """Specialty names from defect-specialties.yaml (the list defects-by-specialty uses) plus Platform."""
    names = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                m = re.match(r"\s*-\s*name:\s*([A-Za-z]+)", line)
                if m:
                    names.append(m.group(1))
    except OSError:
        pass
    return names + [CROSS_CUTTING]


def specialty_rules(path=SPECIALTY_FILE):
    """[(name, compiled regex)] from the keywords/patterns in defect-specialties.yaml, in file order."""
    rules, name = [], None
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return []
    parts = {}
    for line in lines:
        m = re.match(r"\s*-\s*name:\s*([A-Za-z]+)", line)
        if m:
            name = m.group(1)
            rules.append(name)
            parts[name] = []
            continue
        m = re.match(r"\s*(keywords|patterns):\s*\[(.*)\]\s*$", line)
        if m and name:
            for item in re.findall(r"'([^']*)'|\"([^\"]*)\"|([^,\s][^,]*)", m.group(2)):
                word = next(x for x in item if x).strip()
                parts[name].append(r"(?<![A-Za-z0-9])%s(?![A-Za-z0-9])" % re.escape(word) if m.group(1) == "keywords" else word)
    return [(n, re.compile("|".join("(?:%s)" % x for x in parts[n]), re.I)) for n in rules if parts[n]]


def specialty_of(texts, rules):
    """The first specialty whose words appear in `texts` (story summary first, then its epic), else ""."""
    for text in texts:
        for name, rx in rules:
            if rx.search(text or ""):
                return name
    return ""


FOUNDATIONAL_FILE = os.path.join(team.ROOT, ".devin", "rules", "foundational-work.yaml")
FOUNDATIONAL = "Foundational"


def foundational_rules(path=FOUNDATIONAL_FILE):
    """{labels, words, misc} from foundational-work.yaml: what marks work on the application itself."""
    out = {"labels": set(), "words": None, "misc": "Misc"}
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return out
    for line in lines:
        m = re.match(r"(labels|keywords):\s*\[(.*)\]\s*$", line)
        if m:
            items = [x.strip().strip("'\"") for x in m.group(2).split(",") if x.strip()]
            if m.group(1) == "labels":
                out["labels"] = {x.lower() for x in items}
            elif items:
                out["words"] = re.compile("|".join(r"(?<![A-Za-z0-9])%s(?![A-Za-z0-9])" % re.escape(x)
                                                   for x in items), re.I)
        m = re.match(r"misc:\s*(\S.*?)\s*$", line)
        if m:
            out["misc"] = m.group(1).strip("'\"")
    return out


def bucket_of(story, epic, rules, found):
    """Backlog group for a story: its specialty, else Foundational, else Misc."""
    epic = epic or {}
    texts = [story.get("summary"), epic.get("summary", "")]
    name = specialty_of(texts, rules)
    if name:
        return name
    labels = {str(x).lower() for x in list(story.get("labels") or []) + list(epic.get("labels") or [])}
    if labels & found["labels"] or (found["words"] and any(found["words"].search(t or "") for t in texts)):
        return FOUNDATIONAL
    return found["misc"]


MATRIX = os.path.join(team.ROOT, ".devin", "templates", "complexity-matrix.yaml")
# The 8-step sub-task pattern, mapped onto Acme Claims's DEV / SIT / UAT stories (jira-ticket-standards.yaml standard_sets).
DEV_SUBTASKS = ("DEV- Analysis of the story", "DEV- Design", "DEV- Backend implementation",
                "DEV- Frontend implementation",
                "DEV- Unit and integration testing", "DEV- Code review and PR", "DEV- Deployment readiness",
                "DEV- Documentation / KB update")
PERF_SUBTASK = "DEV- Performance validation"
SIT_SUBTASKS = ("SIT- Analysis and Test Case Preparation", "SIT- Review Test Cases and Attach to story",
                "SIT- Upload Testcases to qTest and Test Execution in qTest", "SIT- Test Execution",
                "SIT- Logging Defects and Link to user Story", "SIT- Regression Testing", "SIT- Sanity Testing")
UAT_SUBTASKS = ("UAT- Demo and sign-off",)
PERF_RE = re.compile(r"\b(performance|response time|latency|load test|page load|within \d+(\.\d+)?\s*"
                     r"(ms|milliseconds|seconds|secs?)\b)", re.I)
_HOURS = {}


def hours_reference(path=MATRIX):
    """points -> typical hours from the complexity matrix's hours_reference table (provisional, by its own note)."""
    if path not in _HOURS:
        table, pts = {}, None
        try:
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    m = re.match(r"\s*-\s*fibonacci_points:\s*(\d+)", line)
                    if m:
                        pts = int(m.group(1))
                        continue
                    m = re.match(r"\s*typical_hours:\s*([\d.]+)", line)
                    if m and pts is not None:
                        table[pts] = float(m.group(1))
                        pts = None
        except OSError:
            pass
        _HOURS[path] = table or {1: 4.0, 2: 8.0, 3: 16.0, 5: 32.0, 8: 60.0, 13: 96.0}
    return _HOURS[path]


def story_hours(points):
    try:
        return hours_reference().get(int(points))
    except (TypeError, ValueError):
        return None


def jira_duration(hours):
    """Hours -> Jira duration string, e.g. 6.5 -> '6h 30m'."""
    mins = int(round(float(hours) * 60))
    parts = [x for x in ("%dh" % (mins // 60) if mins // 60 else "", "%dm" % (mins % 60) if mins % 60 else "") if x]
    return " ".join(parts) or "0m"


def split_estimate(total_hours, n):
    """Spread the story's hours over n sub-tasks in half-hour steps so they add up exactly."""
    if not n or not total_hours:
        return [0.0] * (n or 0)
    halves = int(round(float(total_hours) * 2))
    base, extra = divmod(halves, n)
    return [(base + (1 if i < extra else 0)) / 2.0 for i in range(n)]


def story_phase(draft):
    """DEV, SIT or UAT from the title's phase suffix ('… - SIT'); DEV when there is none."""
    m = re.search(r"\s-\s*([A-Za-z]+)\s*$", draft.get("summary") or "")
    phase = m.group(1).upper() if m else ""
    return phase if phase in ("SIT", "UAT") else "DEV"


def standard_subtasks(draft):
    """The standard set for the story's phase. A DEV story whose text names a performance target also gets
    DEV- Performance validation, after the testing step."""
    phase = story_phase(draft)
    if phase == "SIT":
        return list(SIT_SUBTASKS)
    if phase == "UAT":
        return list(UAT_SUBTASKS)
    rows = list(DEV_SUBTASKS)
    text = " ".join(str(draft.get(k) or "") for k in ("summary", "description", "acceptance"))
    if PERF_RE.search(text):
        rows.insert(rows.index("DEV- Unit and integration testing") + 1, PERF_SUBTASK)
    return rows


def default_subtasks(draft):
    """Sub-task drafts for a story: the given ones (or the standard set for its phase), estimates defaulted so they
    sum to the story's hours — any estimate the person typed is kept and the rest absorbs the difference."""
    rows = []
    for st in draft.get("subtasks") or []:
        if isinstance(st, str):
            st = {"summary": st}
        if (st.get("summary") or "").strip():
            rows.append({"summary": st["summary"].strip()[:250], "hours": st.get("hours")})
    if not rows and draft.get("subtasks") is None:
        return []
    if not rows:
        rows = [{"summary": t, "hours": None} for t in standard_subtasks(draft)]
    total = draft.get("hours") or story_hours(draft.get("points")) or 0
    fixed = sum(float(r["hours"]) for r in rows if r["hours"] not in (None, ""))
    free = [r for r in rows if r["hours"] in (None, "")]
    for r, h in zip(free, split_estimate(max(float(total) - fixed, 0), len(free))):
        r["hours"] = h
    for r in rows:
        r["hours"] = float(r["hours"])
    return rows


MAX_SUBTASKS = 20


def clean_subtasks(rows):
    """Sub-tasks for an existing story, as the developer left them: a title and an original estimate in hours on
    every row, an optional technical description, and the key when the row updates a sub-task already in Jira."""
    out, seen = [], set()
    for st in rows or []:
        st = {"summary": st} if isinstance(st, str) else (st if isinstance(st, dict) else {})
        summary = re.sub(r"\s+", " ", str(st.get("summary") or "")).strip()[:250]
        if not summary:
            continue
        key = str(st.get("key") or "").strip().upper()
        if key and not re.match(r"^[A-Z][A-Z0-9]+-\d+$", key):
            raise BacklogError(400, "\"%s\" is not a Jira key" % key)
        try:
            hours = float(st.get("hours"))
        except (TypeError, ValueError):
            raise BacklogError(400, "give \"%s\" an original estimate in hours, e.g. 2.5" % summary)
        if not 0 < hours <= 80:
            raise BacklogError(400, "the estimate for \"%s\" must be between 0 and 80 hours" % summary)
        if summary.lower() in seen or (key and key in seen):
            raise BacklogError(400, "\"%s\" is listed twice" % (key or summary))
        seen.update([summary.lower()] + ([key] if key else []))
        out.append({"key": key, "summary": summary, "hours": round(hours * 4) / 4.0,
                    "description": str(st.get("description") or "").strip()[:4000]})
    if not out:
        raise BacklogError(400, "add at least one sub-task with a title and an estimate")
    if len(out) > MAX_SUBTASKS:
        raise BacklogError(400, "at most %d sub-tasks at a time" % MAX_SUBTASKS)
    return out


def sprint_rank(sprint):
    """Order key for a sprint: by start date when Jira has one, else the numbers in the name (26.4.3)."""
    if not sprint:
        return None
    if isinstance(sprint, dict):
        if sprint.get("start"):
            return ("d", sprint["start"])
        name = sprint.get("name") or ""
    else:
        name = str(sprint)
    nums = re.findall(r"\d+", name)
    return ("n", tuple(int(x) for x in nums)) if nums else ("z", name)


def order_line(keys, why=""):
    return "Order: %s%s" % (" \u2192 ".join(keys), (" \u2014 " + why.strip()) if why and why.strip() else "")


def source_line(draft):
    """'Source BRD: <link>' when the draft names the BRD or source page it came from."""
    link = str(draft.get("brd") or "").strip()
    return "Source BRD: " + link if link else ""


def with_source(draft):
    """The description with the source line first, unless the description already carries that link."""
    desc = draft.get("description") or ""
    line = source_line(draft)
    if not line or line.split(": ", 1)[1] in desc:
        return desc
    return (line + "\n\n" + desc).strip()


def precheck(draft):
    """What the rule book would flag on a ticket drafted in Argus, before it is created.

    `draft` is {type, summary, description, acceptance, epic, labels, priority, points}. Returns
    [{check, severity, text}] — the same check names the Jira hygiene page uses."""
    out = []
    kind = (draft.get("type") or "Story").strip().title()
    summary = (draft.get("summary") or "").strip()
    ac = (draft.get("acceptance") or "").strip()
    labels = [str(x) for x in draft.get("labels") or []]

    def add(check, severity, text):
        out.append({"check": check, "severity": severity, "text": text})

    if not summary:
        add("SUMMARY_MISSING", "high", "The title is empty.")
    if kind == "Epic":
        if len((draft.get("description") or "").strip()) < 80:
            add("EPIC_DESCRIPTION_THIN", "medium", "An epic needs a few sentences on the outcome, not just a title.")
        if not URL_RE.search(with_source(draft)):
            add("EPIC_SOURCE_LINK_MISSING", "medium", "Link the BRD or Confluence page that holds the detail.")
        outcomes = len(NUMBERED.findall(draft.get("acceptance") or ""))
        if outcomes < 2:
            add("EPIC_OUTCOMES_MISSING", "medium",
                "List two to six measurable business outcomes as the epic's acceptance criteria.")
        if re.search(r"\b(20\d\d|Q[1-4]|sprint|phase\s*\d|DEV|SIT|UAT)\b", summary, re.I):
            add("EPIC_TITLE_DATED", "low", "Epic titles name the outcome, not a date, sprint or phase.")
        known = {x.lower() for x in specialties()} | {"foundational", "core"}
        if (draft.get("specialty") or "").strip().lower() not in known:
            add("SPECIALTY_MISSING", "high",
                "Which specialty is this epic for (%s), or Foundational for a change to the application itself? "
                "Ask if the request does not say." % " / ".join(specialties()[:-1]))
        return out
    if PLACEHOLDER_AC.search(ac):
        add("AC_PLACEHOLDER", "high", "Acceptance criteria still say 'Please Enter Acceptance Criteria'.")
    elif not ac:
        add("AC_MISSING", "high", "Acceptance criteria are empty.")
    elif not NUMBERED.search(ac):
        add("AC_UNNUMBERED", "medium", "Number the acceptance criteria (1. 2. 3.) so each one can be tested.")
    if kind in ("Story", "Defect", "Bug", "Task") and not draft.get("epic"):
        add("EPIC_LINK_MISSING", "high", "Pick the epic this belongs to.")
    tc_text = ""
    if kind == "Defect":
        tc_text = tenncare_title_check(summary, draft.get("specialty"), draft.get("environment"))
    if tc_text:
        add("DEFECT_TITLE_PREFIX", "medium", tc_text)
    elif kind in ("Story", "Defect", "Bug", "Task") and not TENNCARE_RE.match(summary):
        first = re.split(r"\s+-\s+", summary, 1)[0].strip() if summary else ""
        if first.lower() not in {x.lower() for x in specialties()}:
            add("SPECIALTY_MISSING", "medium",
                "Start the title with the specialty: %s - … (%s for cross-cutting work)."
                % (" / ".join(specialties()[:-1]), CROSS_CUTTING))
    if kind == "Story":
        suffix = re.search(r"\s-\s*([A-Za-z]+)\s*$", summary)
        if not suffix:
            add("PHASE_SUFFIX_MISSING", "medium", "End the title with the phase: ' - %s'." % " / - ".join(PHASES))
        elif suffix.group(1).upper() not in PHASES:
            add("PHASE_SUFFIX_UNKNOWN", "medium", "The phase suffix should be one of %s." % ", ".join(PHASES))
        elif suffix.group(1) != suffix.group(1).upper():
            add("PHASE_SUFFIX_CASE", "low", "Write the phase suffix in capitals (%s)." % suffix.group(1).upper())
    if not draft.get("priority"):
        add("PRIORITY_MISSING", "medium", "Set the Issue Priority.")
    if sum(1 for lb in labels if lb in AI_LABELS) != 1:
        add("AI_LABEL_MISSING", "low", "Add exactly one of AI-Used / AI-NA.")
    for lb in labels:
        if lb.upper() in [a.upper() for a in AI_LABELS] and lb not in AI_LABELS:
            right = [a for a in AI_LABELS if a.upper() == lb.upper()][0]
            add("LABEL_CASE", "low", "Label %r should be spelt %s." % (lb, right))
    subs = default_subtasks(draft) if kind != "Epic" else []
    total = draft.get("hours") or story_hours(draft.get("points"))
    if subs and total and abs(sum(r["hours"] for r in subs) - float(total)) > 0.01:
        out.append({"check": "SUBTASK_ESTIMATE_SUM", "severity": "medium",
                    "text": "Sub-task estimates add up to %s, the story estimate is %s — reports read the story's number."
                    % (jira_duration(sum(r["hours"] for r in subs)), jira_duration(total))})
    return out


# ----------------------------------------------------------------------------- the tab
class Backlog:
    def __init__(self, jira, state_dir, env=None):
        self.jira = jira
        self.env = env if env is not None else os.environ
        self.previews_path = os.path.join(state_dir, "backlog-previews.json")
        self.poker_path = os.path.join(state_dir, "poker.json")
        self.lock = threading.Lock()
        self.previews = self._load(self.previews_path, [])
        self.rounds = self._load(self.poker_path, {})
        self._sprints = (0, [])

    # ---- state files
    @staticmethod
    def _load(path, default):
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, type(default)) else default
        except (OSError, ValueError):
            return default

    @staticmethod
    def _save(path, data):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".tmp", "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1)
        os.replace(path + ".tmp", path)

    # ---- mode
    def mode(self):
        return {"writes": writes_on(self.env), "allowed": allowed_tickets(self.env),
                "writes_env": WRITES_ENV, "tickets_env": TICKETS_ENV, "scale": list(POINT_SCALE),
                "phases": list(PHASES), "ai_labels": list(AI_LABELS)}

    def _can_write(self, keys):
        if not writes_on(self.env):
            return False, "Writes are off: this Argus shows previews only (%s is not 1)." % WRITES_ENV
        allowed = allowed_tickets(self.env)
        outside = [k for k in keys if k and k.upper() not in allowed]
        if outside:
            return False, ("%s is not on the test allow-list (%s), so this stays a preview."
                           % (", ".join(outside), TICKETS_ENV))
        return True, ""

    # ---- reads
    def _live(self):
        return getattr(self.jira, "via", "here") != "cloud" and bool(self.jira.token)

    def sprints(self, board):
        """Active and future sprints on the team board; [] when Argus reads through Cloud."""
        if not self._live() or not board:
            return []
        at, cached = self._sprints
        if time.time() - at < 300:
            return cached
        out = []
        for state in ("active", "future"):
            page = self.jira.get("/agile/1.0/board/%s/sprint" % board, state=state, maxResults=50)
            for s in page.get("values") or []:
                out.append({"id": s.get("id"), "name": s.get("name", ""), "state": s.get("state", state),
                            "start": (s.get("startDate") or "")[:10], "end": (s.get("endDate") or "")[:10]})
        self._sprints = (time.time(), out)
        return out

    def issues(self, jira_user="", refresh=False):
        """The team's groomable work: backlog + open and future sprints, plus the open epics for the pickers."""
        if getattr(self.jira, "via", "") == "cloud":
            data = self.jira.stories("backlog", jira_user, refresh=refresh)
            epics = self.jira.stories("epics", jira_user, refresh=refresh)
        else:
            data = self.jira.stories("backlog", jira_user, with_description=True)
            epics = self.jira.stories("epics", jira_user)
        by_key = {e.get("key"): e for e in epics.get("stories", [])}
        parents = self._parents(sorted({s.get("parent") for s in data.get("stories", [])
                                        if s.get("parent") and s.get("parent") not in by_key}))
        rules, found = specialty_rules(), foundational_rules()
        for story in data.get("stories", []):
            parent = story.get("parent")
            story["specialty"] = bucket_of(story, by_key.get(parent) or parents.get(parent), rules, found)
        return {"stories": data.get("stories", []), "epics": epics.get("stories", []),
                "parents": {k: v.get("summary", "") for k, v in parents.items()},
                "source": data.get("source", "jira"), "pending": bool(data.get("pending")), "fetched_at": data.get("fetched_at"),
                "error": data.get("error", "") or epics.get("error", ""), "jql": data.get("jql", ""),
                "total": data.get("total", len(data.get("stories", []))), "truncated": bool(data.get("truncated"))}

    def _parents(self, keys):
        """Summary and labels of parent epics that are not in the team's open-epic list (closed, or
        another team's), so their stories still get an epic name and a group. Live Jira only."""
        keys = [k for k in keys if re.match(r"^[A-Z][A-Z0-9]+-\d+$", k or "")][:100]
        if not keys or not self._live():
            return {}
        try:
            page = self.jira.get("/api/2/search", jql="key in (%s)" % ",".join(keys),
                                 fields="summary,labels", maxResults=len(keys))
        except Exception:  # a missing name is cosmetic; never fail the backlog over it
            return {}
        return {i.get("key"): {"key": i.get("key"), "summary": (i.get("fields") or {}).get("summary", ""),
                               "labels": (i.get("fields") or {}).get("labels") or []}
                for i in page.get("issues") or [] if i.get("key")}

    # ---- planning writes
    def _change(self, kind, keys, title, calls, by, extra=None):
        ok, why = self._can_write(keys)
        change = {"id": uuid.uuid4().hex[:10], "kind": kind, "keys": [k for k in keys if k], "title": title,
                  "by": by, "at": int(time.time()), "calls": calls, "status": "preview", "note": why}
        change.update(extra or {})
        if ok:
            change["status"] = "applied"
            change["result"] = []
            for c in calls:
                body = c.get("body") if isinstance(c.get("body"), dict) else {}
                parent = (body.get("fields") or {}).get("parent") or body.get("outwardIssue") or body.get("inwardIssue")
                if parent and parent.get("key") == NEW_PARENT:
                    first = change["result"][0] if change["result"] else {}
                    parent["key"] = first.get("key", "") if isinstance(first, dict) else ""
                change["result"].append(self._send(c))
            change["note"] = "written to Jira"
        with self.lock:
            self.previews.insert(0, change)
            del self.previews[MAX_PREVIEWS:]
            self._save(self.previews_path, self.previews)
        return change

    def _send(self, call):
        return self.jira.request(call["method"], call["path"], call.get("body"))

    @staticmethod
    def _comment(key, by, what):
        return {"method": "POST", "path": "/api/2/issue/%s/comment" % key, "body": {"body": on_behalf(by, what)}}

    def _key(self, key):
        key = (key or "").strip().upper()
        if not TICKET_RE.match(key):
            raise BacklogError(400, "give a %s ticket key" % PROJECT)
        return key

    @staticmethod
    def _points(points):
        try:
            pts = float(points)
        except (TypeError, ValueError):
            raise BacklogError(400, "points must be a number")
        if pts <= 0:
            raise BacklogError(400, "points must be more than 0")
        return int(pts) if pts == int(pts) else pts

    def set_points(self, key, points, by):
        key = self._key(key)
        pts = self._points(points)
        calls = [{"method": "PUT", "path": "/api/2/issue/" + key, "body": {"fields": {F_POINTS: pts}}},
                 self._comment(key, by, "Story points set to %s" % pts)]
        return self._change("points", [key], "%s → %s points" % (key, pts), calls, by, {"points": pts})

    def _story_text_open(self, key):
        """Once SDLC has started on a ticket its description and acceptance criteria stay as they are;
        the run only moves it, adds sub-tasks, logs hours, comments and asks for approvals."""
        why = self.started(key) if callable(getattr(self, "started", None)) else ""
        if why:
            raise BacklogError(409, "%s: %s, so its description and acceptance criteria are not changed. "
                                    "Add a comment or a sub-task instead." % (key, why))

    def set_acceptance(self, key, text, by, suggested=False):
        key, text = self._key(key), (text or "").strip()
        self._story_text_open(key)
        if not text or PLACEHOLDER_AC.search(text):
            raise BacklogError(400, "write the acceptance criteria first")
        fields = {"fields": {F_ACCEPTANCE: text[:20000]}}
        if suggested:
            fields["update"] = {"labels": [{"add": SUGGESTED_AC_LABEL}]}
        calls = [{"method": "PUT", "path": "/api/2/issue/" + key, "body": fields},
                 self._comment(key, by, "Acceptance criteria updated" + (" from Devin's suggestion, edited in grooming" if suggested else ""))]
        return self._change("acceptance", [key], "%s → acceptance criteria (%d lines)" % (key, len(text.splitlines())),
                            calls, by, {"acceptance": text})

    EDITABLE = {"summary": "summary", "description": "description", "acceptance": F_ACCEPTANCE, "epic": F_EPIC_LINK}

    def edit(self, key, changes, by):
        """Change the title, description, acceptance criteria or epic link of one ticket."""
        key = self._key(key)
        fields = {}
        for name, value in (changes or {}).items():
            if name not in self.EDITABLE or value in (None, ""):
                continue
            value = str(value).strip()
            if name == "epic":
                value = self._key(value)
            if name == "acceptance" and PLACEHOLDER_AC.search(value):
                raise BacklogError(400, "write the acceptance criteria first")
            fields[self.EDITABLE[name]] = value[:250] if name == "summary" else value[:20000]
        if not fields:
            raise BacklogError(400, "nothing to change")
        if "description" in fields or F_ACCEPTANCE in fields:
            self._story_text_open(key)
        names = ", ".join(n for n in self.EDITABLE if self.EDITABLE[n] in fields)
        calls = [{"method": "PUT", "path": "/api/2/issue/" + key, "body": {"fields": fields}},
                 self._comment(key, by, "Edited: %s" % names)]
        return self._change("edit", [key], "%s \u2192 %s" % (key, names), calls, by, {"fields": sorted(fields)})

    def groom(self, key, changes, by):
        """The grooming Save for one story: description, acceptance criteria, points and Fix Version in one Jira
        update, plus the sprint move when the sprint changed."""
        key, changes = self._key(key), changes or {}
        if str(changes.get("description") or "").strip() or str(changes.get("acceptance") or "").strip():
            self._story_text_open(key)
        fields, said = {}, []
        desc = str(changes.get("description") or "").strip()
        if desc:
            fields["description"] = desc[:20000]
            said.append("description")
        ac = str(changes.get("acceptance") or "").strip()
        if ac:
            if PLACEHOLDER_AC.search(ac):
                raise BacklogError(400, "write the acceptance criteria first")
            fields[F_ACCEPTANCE] = ac[:20000]
            said.append("acceptance criteria")
        if changes.get("points") not in (None, ""):
            fields[F_POINTS] = self._points(changes.get("points"))
            said.append("%s points" % fields[F_POINTS])
        fix = str(changes.get("fix_version") or "").strip()
        if fix:
            fields["fixVersions"] = [{"name": fix[:100]}]
            said.append("Fix Version " + fix)
        moves = []
        if changes.get("sprint") not in (None, ""):
            moves, where = self._sprint_calls([key], changes.get("sprint"))
            said.append("moved to " + where)
        if not fields and not moves:
            raise BacklogError(400, "nothing changed on this story")
        body = {"fields": fields}
        suggested = bool(changes.get("suggested")) and F_ACCEPTANCE in fields
        if suggested:
            body["update"] = {"labels": [{"add": SUGGESTED_AC_LABEL}]}
        what = "Groomed: " + ", ".join(said) + (" (acceptance criteria from Devin's rewrite, edited in grooming)" if suggested else "")
        calls = ([{"method": "PUT", "path": "/api/2/issue/" + key, "body": body}] if fields else []) + moves + [self._comment(key, by, what)]
        return self._change("groom", [key], "%s \u2192 %s" % (key, ", ".join(said)), calls, by,
                            {"fields": said, "points": fields.get(F_POINTS)})

    def move(self, keys, sprint, by):
        keys = [self._key(k) for k in keys]
        if not keys:
            raise BacklogError(400, "pick at least one ticket")
        calls, where = self._sprint_calls(keys, sprint)
        calls += [self._comment(k, by, "Moved to %s" % where) for k in keys]
        return self._change("move", keys, "%s → %s" % (", ".join(keys), where), calls, by, {"to": where})

    def _sprint_calls(self, keys, sprint):
        if sprint in ("", "backlog", None):
            return [{"method": "POST", "path": "/agile/1.0/backlog/issue", "body": {"issues": keys}}], "the backlog"
        try:
            sid = int(sprint["id"] if isinstance(sprint, dict) else sprint)
        except (TypeError, ValueError, KeyError):
            raise BacklogError(400, "pick a sprint")
        self._guard_order(keys, sprint)
        where = (sprint.get("name") if isinstance(sprint, dict) else "") or "sprint %d" % sid
        return [{"method": "POST", "path": "/agile/1.0/sprint/%d/issue" % sid, "body": {"issues": keys}}], where

    BULK_FIELDS = ("points", "sprint", "epic", "assignee")

    def bulk(self, keys, field, value, by, send=False):
        """One change on many tickets. Without send it only lists the Jira calls for the combined preview;
        with send it goes through _change like every other write (still a preview while writes are off)."""
        keys = list(dict.fromkeys(self._key(k) for k in keys or []))
        if not keys:
            raise BacklogError(400, "pick at least one ticket")
        if field not in self.BULK_FIELDS:
            raise BacklogError(400, "pick what to change: points, sprint, epic or assignee")
        if field == "sprint":
            if not send:
                where = "the backlog" if value in ("", "backlog", None) else (
                    (value.get("name") if isinstance(value, dict) else "") or "sprint %s" % value)
                return {"status": "draft", "kind": "bulk", "keys": keys, "field": field,
                        "title": "%d tickets → %s" % (len(keys), where),
                        "lines": ["%s → %s" % (k, where) for k in keys]}
            return self.move(keys, value, by)
        text = str(value if value is not None else "").strip()
        if not text:
            raise BacklogError(400, "give the new %s" % field)
        if field == "points":
            try:
                pts = float(text)
            except ValueError:
                raise BacklogError(400, "points must be a number")
            if pts <= 0:
                raise BacklogError(400, "points must be more than 0")
            val = int(pts) if pts == int(pts) else pts
            shown, fields = "%s points" % val, {F_POINTS: val}
        elif field == "epic":
            epic = self._key(text)
            shown, fields = "epic " + epic, {F_EPIC_LINK: epic}
        else:
            shown, fields = "assigned to " + text, {"assignee": {"name": text}}
        title = "%d tickets → %s" % (len(keys), shown)
        if not send:
            return {"status": "draft", "kind": "bulk", "keys": keys, "field": field, "title": title,
                    "lines": ["%s → %s" % (k, shown) for k in keys]}
        calls = []
        for k in keys:
            calls.append({"method": "PUT", "path": "/api/2/issue/" + k, "body": {"fields": dict(fields)}})
            calls.append(self._comment(k, by, "Set in bulk: %s" % shown))
        return self._change("bulk", keys, title, calls, by, {"field": field, "value": text})

    def blockers(self, key):
        """Open tickets that block this one ('is blocked by' links), with the sprint each sits in."""
        return self.blockers_of([key]).get(key, [])

    def _fields_of(self, keys, fields):
        """{key: fields} for many tickets in searches of 80; a ticket the search did not return (moved to a new
        key) is read on its own, as before."""
        found = {}
        for i in range(0, len(keys), 80):
            chunk = keys[i:i + 80]
            page = self.jira.get("/api/2/search", jql="key in (%s)" % ",".join(chunk), fields=fields,
                                 maxResults=200)
            for issue in (page.get("issues") if isinstance(page, dict) else None) or []:
                found[issue.get("key")] = issue.get("fields") or {}
        for k in keys:
            if k not in found:
                found[k] = self.jira.get("/api/2/issue/" + k, fields=fields).get("fields", {})
        return found

    def blockers_of(self, keys):
        """{key: open blockers} for many tickets: two Jira searches, not one read per link."""
        keys = list(dict.fromkeys(keys))
        if not self._live() or not keys:
            return {k: [] for k in keys}
        links = self._fields_of(keys, "issuelinks")
        wanted = []
        for k in keys:
            for ln in links[k].get("issuelinks") or []:
                src = ln.get("inwardIssue")
                if not src or (ln.get("type") or {}).get("name") != "Blocks":
                    continue
                if ((src.get("fields") or {}).get("status") or {}).get("statusCategory", {}).get("key") == "done":
                    continue
                wanted.append((k, src))
        info = self._fields_of(list(dict.fromkeys(src["key"] for _, src in wanted)), "summary,%s" % F_SPRINT) \
            if wanted else {}
        out = {k: [] for k in keys}
        for k, src in wanted:
            bf = info.get(src["key"]) or {}
            name = ""
            for sp in bf.get(F_SPRINT) or []:
                m = SPRINT_NAME.search(sp) if isinstance(sp, str) else None
                name = m.group(1) if m else (sp.get("name", "") if isinstance(sp, dict) else name)
            out[k].append({"key": src["key"], "summary": bf.get("summary") or (src.get("fields") or {}).get("summary")
                           or "", "sprint": name})
        return out

    def _guard_order(self, keys, sprint):
        """Refuse a sprint that comes before the sprint of anything that blocks the ticket (rule book: order)."""
        target = sprint_rank(sprint)
        found = self.blockers_of(keys)
        for k in keys:
            for b in found.get(k, []):
                before = sprint_rank(b["sprint"])
                if before is None or (target is not None and before > target):
                    raise BacklogError(409, "%s is blocked by %s (%s), which is %s — it cannot be scheduled first."
                                       % (k, b["key"], b["summary"][:50],
                                          ("in " + b["sprint"]) if b["sprint"] else "not in a sprint yet"))

    def order(self, keys, why, by):
        """Business order A → B → C as Blocks links (A blocks B, B blocks C) plus the order line on each ticket."""
        keys = [self._key(k) for k in keys]
        if len(keys) < 2:
            raise BacklogError(400, "pick at least two tickets, in the order they must ship")
        if len(set(keys)) != len(keys):
            raise BacklogError(400, "a ticket appears twice in the order")
        line = order_line(keys, why)
        calls = []
        for a_, b_ in zip(keys, keys[1:]):
            calls.append({"method": "POST", "path": "/api/2/issueLink",
                          "body": {"type": {"name": "Blocks"}, "inwardIssue": {"key": a_}, "outwardIssue": {"key": b_}}})
        calls += [self._comment(k, by, line) for k in keys]
        return self._change("order", keys, line, calls, by, {"order": keys, "why": why})

    RAISE_KINDS = ("question", "clarification", "observation", "defect", "risk")

    def episodes(self):
        """Episode names seen in EoC defect titles in Jira (read-only search), for the Raise form's picker."""
        try:
            page = self.jira.get("/api/2/search", jql=EPISODES_JQL, maxResults=200, fields="summary")
        except Exception:  # noqa: BLE001 - a picker with no suggestions beats a failed form
            return []
        names = set()
        for issue in (page or {}).get("issues") or []:
            m = EOC_RE.match(((issue.get("fields") or {}).get("summary") or "").strip())
            if m:
                names.add(m.group(2).strip())
        return sorted(names)

    def raise_item(self, story, kind, title, detail, by, severity="", environment="", assignee="",
                   specialty="", episode=""):
        """QA / UAT / anyone: a question or clarification (Question sub-task under the story), an observation,
        a defect (Defect ticket, Defect link to the story) or a risk — the same shapes question_subtask.py writes."""
        story = self._key(story)
        kind = (kind or "").strip().lower()
        if kind not in self.RAISE_KINDS:
            raise BacklogError(400, "kind must be one of " + ", ".join(self.RAISE_KINDS))
        title = " ".join((title or "").split())
        if not title:
            raise BacklogError(400, "say what it is in one line")
        user = (by or "").strip()
        who = "%s (%s)" % (user, kind)
        if kind in ("question", "clarification"):
            if not assignee:
                raise BacklogError(400, "who should answer? pick a person")
            fields = {"project": {"key": PROJECT}, "parent": {"key": story}, "issuetype": {"id": qs.SUBTASK_TYPE},
                      "labels": [qs.QUESTION_LABEL, qs.ASKER_LABEL_PREFIX + user, kind.title()],
                      "assignee": {"name": assignee},
                      "summary": "%s from %s: %s" % (kind.title(), user, qs.issue_summary(title)),
                      "description": "*Asked by:* %s\n*Story:* %s\n\n%s\n\n*Answer here or via Argus.*"
                                     % (user, story, (detail or title).strip())}
            calls = [{"method": "POST", "path": "/api/2/issue", "body": {"fields": fields}}]
        else:
            summary = "%s: %s" % (story, title)
            if kind == "defect":
                summary = defect_title(title, specialty, environment, episode)
            fields = {"project": {"key": PROJECT}, "issuetype": {"id": qs.OBSERVATION_TYPES[kind]},
                      "summary": qs.issue_summary(summary),
                      "labels": ["Observation", "ACME-Dashboard", requester_label(user)],
                      "description": "*Raised by:* %s\n*Story:* %s\n*Seen in:* %s\n*Severity:* %s\n*What happened:*\n%s"
                                     % (user, story, environment or "not stated", severity or "not stated",
                                        (detail or title).strip())}
            if assignee:
                fields["assignee"] = {"name": assignee}
            if kind == "defect":
                if severity not in qs.SEVERITIES:
                    raise BacklogError(400, "severity must be one of " + ", ".join(qs.SEVERITIES))
                if environment not in qs.DETECTED_IN:
                    raise BacklogError(400, "environment must be one of " + ", ".join(qs.DETECTED_IN))
                fields[qs.SEVERITY_FIELD] = {"value": severity}
                fields[qs.DETECTED_IN_FIELD] = {"value": environment}
            if kind == "risk":
                fields[qs.RISK_LEVEL_FIELD] = {"value": qs.SEVERITY_TO_RISK.get(severity.lower(), "2 - Moderate")}
            calls = [{"method": "POST", "path": "/api/2/issue", "body": {"fields": fields}},
                     {"method": "POST", "path": "/api/2/issueLink",
                      "body": {"type": {"name": "Defect" if kind == "defect" else "Relates"},
                               "inwardIssue": {"key": NEW_PARENT}, "outwardIssue": {"key": story}}}]
        calls.append(self._comment(story, by, "%s raised: %s" % (kind.title(), title)))
        return self._change("raise", [story], "%s on %s: %s" % (kind, story, title), calls, by,
                            {"kind": kind, "raised_by": who})

    def _fields(self, draft, by):
        kind = (draft.get("type") or "Story").strip().title()
        labels = sorted({str(x).strip() for x in draft.get("labels") or [] if str(x).strip()}
                        | {requester_label(by), DEVIN_CREATED_LABEL})
        fields = {"project": {"key": PROJECT}, "issuetype": {"name": kind},
                  "summary": (draft.get("summary") or "")[:250], "description": with_source(draft),
                  F_IT_TEAM: [{"value": IT_TEAM}], "labels": labels}
        if kind == "Epic":
            fields[F_EPIC_NAME] = fields["summary"]
            if draft.get("specialty"):
                fields["labels"] = sorted(set(labels) | {str(draft["specialty"]).strip()})
        else:
            fields[F_ACCEPTANCE] = draft.get("acceptance") or ""
            if draft.get("epic"):
                fields[F_EPIC_LINK] = self._key(draft["epic"])
            if draft.get("points"):
                fields[F_POINTS] = draft["points"]
            total = draft.get("hours") or story_hours(draft.get("points"))
            if total:
                fields["timetracking"] = {"originalEstimate": jira_duration(total)}
        if draft.get("priority"):
            fields[F_PRIORITY] = {"value": draft["priority"]}
        if draft.get("assignee"):
            fields["assignee"] = {"name": draft["assignee"]}
        return fields

    def create(self, draft, by, source=""):
        """A new epic or story from the form (or from pasted notes / a clone). Gated on the parent key."""
        fields = self._fields(draft, by)
        if not fields["summary"].strip():
            raise BacklogError(400, "the title is empty")
        checks = precheck(draft)
        if any(c["severity"] == "high" for c in checks) and not draft.get("force"):
            raise BacklogError(422, "The rule book would flag this ticket: " +
                               "; ".join(c["text"] for c in checks if c["severity"] == "high"))
        gate = [fields.get(F_EPIC_LINK, "")] if fields["issuetype"]["name"] != "Epic" else [draft.get("epic") or ""]
        if source.startswith("clone:"):
            gate = [source.split(":", 1)[1]]
        calls = [{"method": "POST", "path": "/api/2/issue", "body": {"fields": fields}}]
        subs = default_subtasks(draft) if fields["issuetype"]["name"] != "Epic" else []
        for st in subs:
            calls.append({"method": "POST", "path": "/api/2/issue", "body": {"fields": {
                "project": {"key": PROJECT}, "issuetype": {"name": "Sub-task"}, "parent": {"key": NEW_PARENT},
                "summary": st["summary"], F_ACCEPTANCE: "1. %s done and reviewed." % st["summary"],
                "timetracking": {"originalEstimate": jira_duration(st["hours"])},
                "labels": ([x for x in fields["labels"] if x in AI_LABELS] or ["AI-Used"]) + [DEVIN_CREATED_LABEL],
                **({"description": source_line(draft)} if source_line(draft) else {})}}})
        blocked_by = [self._key(k) for k in draft.get("blocked_by") or [] if str(k).strip()]
        if blocked_by:
            fields["description"] = (order_line(blocked_by + ["this"], draft.get("order_why", "")) + "\n\n"
                                     + fields["description"]).strip()
            for k in blocked_by:
                calls.append({"method": "POST", "path": "/api/2/issueLink",
                              "body": {"type": {"name": "Blocks"}, "inwardIssue": {"key": k},
                                       "outwardIssue": {"key": NEW_PARENT}}})
        title = "new %s: %s" % (fields["issuetype"]["name"], fields["summary"])
        if subs:
            title += " + %d sub-tasks (%s)" % (len(subs), jira_duration(sum(r["hours"] for r in subs)))
        change = self._change("create", [k for k in gate if k] or [""], title, calls, by,
                              {"draft": draft, "checks": checks, "source": source})
        if change["status"] == "applied" and change["result"] and isinstance(change["result"][0], dict):
            change["created"] = change["result"][0].get("key", "")
        change["subtasks"] = subs
        return change

    def clone(self, key, by, overrides=None):
        """Copy a ticket with the sprint and fix version cleared, so the copy cannot inherit a stale release."""
        key = self._key(key)
        f = self.jira.get("/api/2/issue/" + key,
                          fields="summary,description,issuetype,labels,priority,%s,%s,%s,%s" %
                          (F_ACCEPTANCE, F_EPIC_LINK, F_PRIORITY, F_POINTS)).get("fields", {})
        kind = (f.get("issuetype") or {}).get("name", "Story")
        draft = {"type": kind, "summary": "CLONE - " + (f.get("summary") or ""),
                 "description": f.get("description") or "",
                 "acceptance": f.get(F_ACCEPTANCE) or "", "epic": f.get(F_EPIC_LINK) or "",
                 "labels": [lb for lb in f.get("labels") or [] if not lb.startswith(("requested-by-", "asked-by-"))],
                 "priority": ((f.get(F_PRIORITY) or {}).get("value") or ""), "points": f.get(F_POINTS)}
        draft.update(overrides or {})
        return self.create(draft, by, source="clone:" + key)

    def note(self, key, text, by, filename=""):
        """Meeting notes or a decision on the ticket: a comment, or an attachment when a file name is given."""
        key = self._key(key)
        text = (text or "").strip()
        if not text:
            raise BacklogError(400, "the note is empty")
        if filename:
            calls = [{"method": "POST", "path": "/api/2/issue/%s/attachments" % key,
                      "body": {"multipart": True, "filename": filename, "bytes": len(text.encode("utf-8"))}}]
            title = "%s ← attach %s" % (key, filename)
        else:
            calls = [{"method": "POST", "path": "/api/2/issue/%s/comment" % key,
                      "body": {"body": text + "\n\n" + on_behalf(by, "Note added")}}]
            title = "%s ← note (%d chars)" % (key, len(text))
        return self._change("note", [key], title, calls, by, {"filename": filename})

    # ---- hours
    def subtasks(self, key):
        """The ticket's sub-tasks (hours belong there, per the rule book), plus the ticket itself."""
        key = self._key(key)
        if getattr(self.jira, "via", "") == "cloud":
            s = self.jira.story(key)
            kind = s.get("type") or s.get("issuetype") or ""
            return [{"key": key, "summary": s.get("summary") or "", "type": kind,
                     "hours_ok": kind == "Sub-task" or bool(s.get("parent") and kind != "Story")}]
        f = self.jira.get("/api/2/issue/" + key, fields="summary,issuetype,subtasks,parent").get("fields", {})
        kind = (f.get("issuetype") or {}).get("name", "")
        rows = [{"key": key, "summary": f.get("summary") or "", "type": kind,
                 "hours_ok": kind == "Sub-task" or bool(f.get("parent"))}]
        for st in f.get("subtasks") or []:
            sf = st.get("fields") or {}
            rows.append({"key": st.get("key", ""), "summary": sf.get("summary") or "",
                         "type": (sf.get("issuetype") or {}).get("name", "Sub-task"), "hours_ok": True})
        return rows

    def add_subtasks(self, key, rows, by, assignee="", why=""):
        """Create the new sub-tasks under an existing story and update the ones the developer changed, each with
        the original estimate and technical description they left. Gated on the story key."""
        key = self._key(key)
        rows = clean_subtasks(rows)
        updates = [r for r in rows if r["key"]]
        if updates and getattr(self.jira, "via", "") != "cloud":
            have = {t["key"] for t in self.subtasks(key) if t["key"] != key}
            stray = [r["key"] for r in updates if r["key"] not in have]
            if stray:
                raise BacklogError(400, "%s is not a sub-task of %s" % (", ".join(stray), key))
        calls = []
        for st in rows:
            if st["key"]:
                fields = {"summary": st["summary"], "timetracking": {"originalEstimate": jira_duration(st["hours"])}}
                if st["description"]:
                    fields["description"] = st["description"]
                calls.append({"method": "PUT", "path": "/api/2/issue/" + st["key"], "body": {"fields": fields}})
                continue
            fields = {"project": {"key": PROJECT}, "issuetype": {"name": "Sub-task"}, "parent": {"key": key},
                      "summary": st["summary"], F_ACCEPTANCE: "1. %s done and reviewed." % st["summary"],
                      "timetracking": {"originalEstimate": jira_duration(st["hours"])},
                      "labels": ["AI-Used", DEVIN_CREATED_LABEL]}
            desc = "\n\n".join(x for x in (st["description"], why) if x)
            if desc:
                fields["description"] = desc
            if assignee:
                fields["assignee"] = {"name": assignee}
            calls.append({"method": "POST", "path": "/api/2/issue", "body": {"fields": fields}})
        made, total = len(rows) - len(updates), jira_duration(sum(r["hours"] for r in rows))
        what = ", ".join(x for x in ("%d sub-tasks added" % made if made else "",
                                       "%d updated" % len(updates) if updates else "") if x)
        calls.append(self._comment(key, by, "%s (%s original estimate)" % (what, total)))
        change = self._change("subtasks", [key] + [r["key"] for r in updates], "%s ← %s (%s)" % (key, what, total),
                              calls, by, {"subtasks": rows})
        if change["status"] == "applied":
            res = change["result"][:-1]
            change["created"] = [r.get("key", "") for r, st in zip(res, rows) if not st["key"] and isinstance(r, dict)]
            change["updated"] = [r["key"] for r in updates]
        return change

    def log_hours(self, key, hours, note, by, started=""):
        """A Jira worklog on the ticket: hours spent and what was done, in the name of the person."""
        key = self._key(key)
        try:
            h = float(hours)
        except (TypeError, ValueError):
            raise BacklogError(400, "hours must be a number, e.g. 1.5")
        if not 0 < h <= 24:
            raise BacklogError(400, "hours must be between 0 and 24")
        body = {"timeSpentSeconds": int(round(h * 3600)),
                "comment": ((note or "").strip() + "\n\n" if (note or "").strip() else "") + on_behalf(by, "Hours logged")}
        if started:
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", started):
                raise BacklogError(400, "the date must be YYYY-MM-DD")
            body["started"] = started + "T09:00:00.000+0000"
        calls = [{"method": "POST", "path": "/api/2/issue/%s/worklog" % key, "body": body}]
        return self._change("hours", [key], "%s ← %gh %s" % (key, h, (note or "")[:60]), calls, by,
                            {"hours": h, "started": started})

    def set_ai_label(self, key, label, by):
        """Add the exact-case AI label (AI-Used or AI-NA); a wrong-case or the other AI label comes off."""
        key = self._key(key)
        if label not in AI_LABELS:
            raise BacklogError(400, "the label must be one of %s" % " / ".join(AI_LABELS))
        have = []
        if self._live():
            have = (self.jira.get("/api/2/issue/" + key, fields="labels").get("fields") or {}).get("labels") or []
        drop = [lb for lb in have if lb != label and lb.upper() in [a.upper() for a in AI_LABELS]]
        calls = [{"method": "PUT", "path": "/api/2/issue/" + key,
                  "body": {"update": {"labels": [{"add": label}] + [{"remove": lb} for lb in drop]}}},
                 self._comment(key, by, "AI label set to %s" % label)]
        return self._change("ai_label", [key], "%s \u2192 %s%s" % (key, label, " (removed %s)" % ", ".join(drop) if drop else ""),
                            calls, by, {"label": label, "removed": drop})

    def set_estimate(self, key, hours, by):
        """Set the original estimate in hours."""
        key = self._key(key)
        try:
            h = float(hours)
        except (TypeError, ValueError):
            raise BacklogError(400, "hours must be a number, e.g. 4")
        if not 0 < h <= 200:
            raise BacklogError(400, "the estimate must be between 0 and 200 hours")
        calls = [{"method": "PUT", "path": "/api/2/issue/" + key,
                  "body": {"fields": {"timetracking": {"originalEstimate": "%gh" % h}}}},
                 self._comment(key, by, "Original estimate set to %gh" % h)]
        return self._change("estimate", [key], "%s \u2192 %gh estimate" % (key, h), calls, by, {"hours": h})

    # ---- planning poker
    def poker_start(self, key, by, voters):
        key = self._key(key)
        rid = uuid.uuid4().hex[:8]
        voters = [v for v in voters or [] if v]
        rnd = {"id": rid, "key": key, "by": by, "voters": voters, "votes": {}, "revealed": False,
               "agreed": None, "at": int(time.time())}
        with self.lock:
            for other in self.rounds.values():
                if other["key"] == key and other["agreed"] is None:
                    other["closed"] = True
            self.rounds[rid] = rnd
            self._save(self.poker_path, self.rounds)
        return self.poker_view(rid)

    def _round(self, rid):
        rnd = self.rounds.get(rid)
        if not rnd:
            raise BacklogError(404, "no such poker round")
        return rnd

    def poker_vote(self, rid, voter, points):
        rnd = self._round(rid)
        if rnd["revealed"]:
            raise BacklogError(409, "votes are already shown; start a new round to vote again")
        try:
            pts = int(points)
        except (TypeError, ValueError):
            raise BacklogError(400, "vote with a number")
        if pts not in POINT_SCALE:
            raise BacklogError(400, "vote with one of %s" % ", ".join(str(p) for p in POINT_SCALE))
        with self.lock:
            rnd["votes"][voter or "anonymous"] = pts
            self._save(self.poker_path, self.rounds)
        return self.poker_view(rid)

    def poker_reveal(self, rid):
        rnd = self._round(rid)
        with self.lock:
            rnd["revealed"] = True
            self._save(self.poker_path, self.rounds)
        return self.poker_view(rid)

    def poker_agree(self, rid, points, by):
        rnd = self._round(rid)
        if not rnd["revealed"]:
            raise BacklogError(409, "show the votes before agreeing")
        change = self.set_points(rnd["key"], points, by)
        with self.lock:
            rnd["agreed"] = change["points"]
            rnd["change"] = change["id"]
            self._save(self.poker_path, self.rounds)
        return dict(self.poker_view(rid), change=change)

    def poker_view(self, rid):
        rnd = self._round(rid)
        votes = rnd["votes"]
        shown = dict(votes) if rnd["revealed"] else {v: "✓" for v in votes}
        values = sorted(votes.values())
        out = {"id": rid, "key": rnd["key"], "by": rnd["by"], "voters": rnd["voters"], "votes": shown,
               "voted": len(votes), "revealed": rnd["revealed"], "agreed": rnd["agreed"], "at": rnd["at"],
               "waiting": [v for v in rnd["voters"] if v not in votes], "closed": bool(rnd.get("closed"))}
        if rnd["revealed"] and values:
            out["spread"] = {"low": values[0], "high": values[-1], "median": values[len(values) // 2],
                             "agree": values[0] == values[-1]}
        return out

    def poker_for(self, key):
        key = (key or "").upper()
        rows = [self.poker_view(r) for r, v in self.rounds.items() if not key or v["key"] == key]
        return sorted(rows, key=lambda r: -r["at"])

    # ---- Scrum Master follow-ups: one story at a time, questions put the story on hold
    WAIT_LABELS = ("Question", "Approval")

    def followups(self, sprint_id, idle_days=2, today=None):
        """In Progress / On Hold stories in the sprint: who has more than one going, which have not moved for
        `idle_days` working days, which wait on an open Question or Approval sub-task and are not on hold yet,
        and which are on hold with nothing left to wait on."""
        if not self._live() or not sprint_id:
            return {"parallel": [], "idle": [], "hold": [], "resume": [], "on_hold": []}
        page = self.jira.get("/api/2/search", jql='sprint = %s AND issuetype = Story AND status in ("In Progress", "On Hold")'
                             % int(sprint_id), maxResults=200, fields="summary,status,assignee,updated,subtasks")
        stories = page.get("issues") or []
        subs = {}
        keys = [st["key"] for s in stories for st in (s.get("fields") or {}).get("subtasks") or []]
        for i in range(0, len(keys), 80):
            got = self.jira.get("/api/2/search", jql="key in (%s)" % ",".join(keys[i:i + 80]), maxResults=200,
                                fields="summary,status,assignee,labels,updated,parent")
            for st in got.get("issues") or []:
                subs.setdefault(((st.get("fields") or {}).get("parent") or {}).get("key", ""), []).append(st)
        today = today or datetime.date.today()
        out = {"parallel": [], "idle": [], "hold": [], "resume": [], "on_hold": []}
        mine = {}
        for s in stories:
            f = s.get("fields") or {}
            who = (f.get("assignee") or {}).get("displayName") or "Unassigned"
            status = (f.get("status") or {}).get("name", "")
            kids = subs.get(s["key"], [])
            waits = [{"key": k["key"], "summary": (k.get("fields") or {}).get("summary", ""),
                      "kind": next(l for l in (k["fields"].get("labels") or []) if l in self.WAIT_LABELS),
                      "on": ((k["fields"].get("assignee") or {}).get("displayName") or "nobody")}
                     for k in kids if set(k["fields"].get("labels") or []) & set(self.WAIT_LABELS)
                     and ((k["fields"].get("status") or {}).get("statusCategory") or {}).get("key") != "done"]
            last = max([str(f.get("updated") or "")[:10]] + [str(k["fields"].get("updated") or "")[:10] for k in kids])
            row = {"key": s["key"], "summary": f.get("summary", ""), "owner": who, "status": status, "waits": waits,
                   "last": last, "quiet": _working_days_since(last, today)}
            if status == "On Hold":
                out["on_hold" if waits else "resume"].append(row)
                continue
            mine.setdefault(who, []).append(row)
            if waits:
                out["hold"].append(row)
            elif row["quiet"] >= idle_days:
                out["idle"].append(row)
        for who, rows in sorted(mine.items()):
            if len(rows) > 1 and who != "Unassigned":
                out["parallel"].append({"owner": who, "stories": sorted(rows, key=lambda r: r["last"])})
        return out

    def _transition(self, key, to):
        for t in self.jira.get("/api/2/issue/%s/transitions" % key).get("transitions") or []:
            if (t.get("to") or {}).get("name", "").lower() == to.lower():
                return t["id"]
        raise BacklogError(409, "%s cannot move to %s from where it is" % (key, to))

    def hold(self, key, why, by):
        """Story to On Hold, with a comment naming what it waits on."""
        key = self._key(key)
        why = (why or "").strip() or "waiting on an answer"
        calls = [{"method": "POST", "path": "/api/2/issue/%s/transitions" % key,
                  "body": {"transition": {"id": self._transition(key, "On Hold")}}},
                 self._comment(key, by, "On hold: %s" % why)]
        return self._change("hold", [key], "%s → On Hold (%s)" % (key, why), calls, by)

    def demo_scheduled(self, key, when, audience, by):
        """A comment saying when the demo is and who it is for; the label stays until it is given."""
        key = self._key(key)
        when, audience = (when or "").strip(), (audience or "").strip()
        if not when or not audience:
            raise BacklogError(400, "give the demo date and who it is for")
        what = "Demo scheduled for %s with %s" % (when, audience)
        return self._change("demo", [key], "%s ← %s" % (key, what), [self._comment(key, by, what)], by)

    def demo_given(self, key, when, audience, by):
        """Demo done: the demo label comes off, with a comment naming the date and audience."""
        key = self._key(key)
        when, audience = (when or "").strip(), (audience or "").strip()
        if not when or not audience:
            raise BacklogError(400, "give the date and who saw the demo")
        what = "Demo given on %s to %s" % (when, audience)
        calls = [{"method": "PUT", "path": "/api/2/issue/%s" % key,
                  "body": {"update": {"labels": [{"remove": lb} for lb in DEMO_LABELS]}}},
                 self._comment(key, by, what)]
        return self._change("demo", [key], "%s − demo label (%s)" % (key, what), calls, by)

    def resume(self, key, by):
        """Story back to In Progress once nothing is left to wait on."""
        key = self._key(key)
        calls = [{"method": "POST", "path": "/api/2/issue/%s/transitions" % key,
                  "body": {"transition": {"id": self._transition(key, "In Progress")}}},
                 self._comment(key, by, "Back in progress: the question or approval it waited on is closed")]
        return self._change("resume", [key], "%s → In Progress" % key, calls, by)

    # ---- previews
    def list_previews(self, limit=50):
        return self.previews[:limit]
