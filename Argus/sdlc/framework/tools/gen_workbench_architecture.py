"""Argus architecture pictures: ten looks of the same diagram (animated SVG, one role at a time), a still Pastel cards SVG for Confluence and slides, and a gallery page with Look and Role selectors.

Stdlib only. Run from anywhere: python3 sdlc/framework/tools/gen_workbench_architecture.py
Writes into sdlc/framework/architecture/. The PNG of the still picture is made from its SVG in Chrome (see architecture/README.md)."""
import html, math, os, re

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "architecture")
W, H = 1600, 900
T = 16  # seconds per animation cycle

COLS = [  # x centre, header
    (110, "People"),
    (345, "Argus pages"),
    (600, "Argus server"),
    (840, "Devin link"),
    (1095, "Devin Cloud sessions"),
    (1395, "Systems of record"),
]
LANE_NOTE = ["", "in the browser", "on your PC or in your Devin Cloud session", "bridge (team default) or API key",
             "each run is its own session", "written only after `approved`"]

# id: (col, y, title, sub, kind)   kind: node | chip
N = {
    "dev":   (0, 170, "Developers, leads", "start runs, answer questions", "node"),
    "po":    (0, 330, "PO, BSA, Scrum Master", "backlog, sprint, leave", "node"),
    "appr":  (0, 490, "Approver", "replies approved / rejected", "node"),
    "qa":    (0, 650, "Tester", "on their own PC", "node"),
    "runs":  (1, 130, "Runs page", "stage rail, questions, gate cards", "node"),
    "back":  (1, 235, "Backlog grid", "estimate, team poker, raise story", "node"),
    "dash":  (1, 345, "Role dashboard", "one lens per role (people.yaml)", "node"),
    "c_leave": (1, 425, "Sprint leave calendar", "", "chip"),
    "c_vac":   (1, 467, "Vacation planner", "", "chip"),
    "c_load":  (1, 509, "Sprint workload and scope", "", "chip"),
    "c_cfg":   (1, 551, "Role, skill, gate config", "", "chip"),
    "c_road":  (1, 593, "Roadmap and epics", "", "chip"),
    "c_def":   (1, 635, "Defects, Jira hygiene", "", "chip"),
    "c_appr":  (1, 677, "Approvals, review queue", "", "chip"),
    "pc":    (1, 790, "Test on my PC", "runs the story's test pack", "node"),
    "srv":   (2, 210, "Argus server", "server.py, 127.0.0.1:8787", "node"),
    "state": (2, 345, "Run cache", "~/.sdlc/console/runs.json", "node"),
    "poll":  (2, 480, "Progress reader", "[SDLC] lines to timeline, gates", "node"),
    "upd":   (2, 615, "Updater", "update.py, fast-forward, restart", "node"),
    "local": (2, 790, "Devin Local", "pctest.py on the PC", "node"),
    "outb":  (3, 175, "Bridge outbox", "one file per Devin call", "node"),
    "loop":  (3, 315, "Bridge loop", "host session, scripted_tools", "node"),
    "inb":   (3, 455, "Bridge inbox", "tool output, API shapes", "node"),
    "alive": (3, 580, "Heartbeat", "alive file, every second", "node"),
    "api":   (3, 720, "Devin API", "PC: SDLC_DEVIN_TRANSPORT=api", "node"),
    "host":  (4, 115, "Host session", "/argus in your Devin Cloud", "node"),
    "sdlc":  (4, 235, "SDLC run session", "intake, plan, build, test, release", "node"),
    "chat":  (4, 350, "Day assistant session", "menu, chat, dashboard Save", "node"),
    "jr":    (4, 460, "Jira reader session", "sdlc-jira-read", "node"),
    "prs":   (4, 560, "PR state session", "sdlc-pr-state", "node"),
    "db":    (4, 660, "Dashboard build session", "sdlc-dashboard-build", "node"),
    "ins":   (4, 760, "Story insight session", "insight, AC rewrite", "node"),
    "jira":  (5, 150, "Jira", "stories, sub-tasks, questions", "node"),
    "conf":  (5, 300, "Confluence", "roster, sprint leave, demos", "node"),
    "bb":    (5, 450, "Bitbucket", "devin/* branch, PR to feature", "node"),
    "repo":  (5, 600, "Repo rules and KB", "people.yaml, gates, sprint sheets", "node"),
    "snow":  (5, 750, "Snowflake", "read only, through MCP", "node"),
}
CHIPS = [k for k, v in N.items() if v[4] == "chip"]

# phases: (start, end, caption)
PH = [
    (0.00, 0.12, "1  A person clicks in Argus: start a run, Save on a dashboard tab, raise a story"),
    (0.12, 0.28, "2  The server turns it into a Devin call; the bridge loop in the host session creates or messages a child session"),
    (0.28, 0.46, "3  Child sessions read Jira, the repo knowledge base, Snowflake and Bitbucket"),
    (0.46, 0.62, "4  Progress comes back as [SDLC] lines: stage rail, numbered questions, gate cards, artefacts"),
    (0.62, 0.74, "5  The approver replies approved on the gate card; the answer goes back to the session"),
    (0.74, 0.96, "6  Only then: Jira update, Confluence page, devin/* branch and PR into feature/devin-sdlc"),
]
# (a, b, kind, label, [(phase, hop, hops)])   kind: req devin back read write gate link
E = [
    ("dev", "runs", "req", "start run", [(0, 0, 2)]),
    ("po", "back", "req", "", [(0, 0, 2)]),
    ("po", "dash", "req", "Save", [(0, 0, 2)]),
    ("runs", "srv", "req", "", [(0, 1, 2), (4, 1, 3)]),
    ("back", "srv", "req", "", [(0, 1, 2)]),
    ("dash", "srv", "req", "SDLC block", [(0, 1, 2)]),
    ("srv", "state", "link", "", [(1, 0, 4)]),
    ("srv", "outb", "devin", "create, message", [(1, 0, 4), (4, 2, 3)]),
    ("outb", "loop", "devin", "", [(1, 1, 4)]),
    ("loop", "host", "devin", "runs 4 tools", [(1, 2, 4)]),
    ("host", "sdlc", "devin", "", [(1, 3, 4), (4, 2, 3)]),
    ("host", "chat", "devin", "", [(1, 3, 4)]),
    ("host", "jr", "devin", "", [(1, 3, 4)]),
    ("host", "prs", "devin", "", [(1, 3, 4)]),
    ("host", "db", "devin", "", [(1, 3, 4)]),
    ("host", "ins", "devin", "", [(1, 3, 4)]),
    ("jira", "jr", "read", "tickets", [(2, 0, 2)]),
    ("repo", "sdlc", "read", "KB, rules", [(2, 0, 2)]),
    ("snow", "sdlc", "read", "data checks", [(2, 1, 2)]),
    ("bb", "prs", "read", "PR state", [(2, 0, 2)]),
    ("repo", "db", "read", "people.yaml", [(2, 1, 2)]),
    ("conf", "c_leave", "read", "Sprint Leave page", [(2, 1, 2)]),
    ("sdlc", "loop", "back", "[SDLC] lines", [(3, 0, 4)]),
    ("loop", "inb", "back", "", [(3, 1, 4)]),
    ("inb", "poll", "back", "", [(3, 2, 4)]),
    ("poll", "runs", "back", "timeline, gates", [(3, 3, 4)]),
    ("db", "dash", "back", "dashboard page", [(3, 1, 4)]),
    ("appr", "runs", "gate", "approved", [(4, 0, 3)]),
    ("sdlc", "jira", "write", "story, sub-tasks", [(5, 0, 2)]),
    ("sdlc", "bb", "write", "branch, PR", [(5, 0, 2)]),
    ("chat", "conf", "write", "roster, leave", [(5, 0, 2)]),
    ("chat", "bb", "write", "people.yaml PR", [(5, 0, 2)]),
    ("sdlc", "conf", "write", "", [(5, 1, 2)]),
    ("bb", "upd", "read", "newer commit", [(5, 1, 2)]),
    ("upd", "srv", "link", "", [(5, 1, 2)]),
    ("alive", "srv", "link", "heartbeat", []),
    ("api", "host", "link", "", []),
    ("qa", "pc", "req", "", [(0, 0, 2)]),
    ("pc", "local", "req", "", [(0, 1, 2)]),
    ("local", "sdlc", "back", "evidence", [(3, 2, 4)]),
]
E += [("dash", k, "link", "", []) for k in [k for k, v in N.items() if v[4] == "chip"]]
CHIP_IDS = [k for k, v in N.items() if v[4] == "chip"]
J = lambda *pairs: [tuple(p.split(">")) for p in pairs]
ROLES = [
    ("dev", "Developer or lead", [
        ("starts a run on the Runs page", J("dev>runs")), (None, J("runs>srv")),
        ("the server saves the run and writes a Devin call to the bridge outbox", J("srv>state", "srv>outb")),
        ("the bridge loop in the host session creates the SDLC run session", J("outb>loop")), (None, J("loop>host")),
        (None, J("host>sdlc")),
        ("the session reads the repo rules, knowledge base and Snowflake", J("repo>sdlc", "snow>sdlc")),
        ("its [SDLC] lines come back to the stage rail and numbered questions", J("sdlc>loop")), (None, J("loop>inb")),
        (None, J("inb>poll")), (None, J("poll>runs"))]),
    ("po", "PO, BSA or Scrum Master", [
        ("opens the backlog grid", J("po>back")), (None, J("back>srv")),
        ("a short Jira reader session fetches the tickets", J("srv>outb")), (None, J("outb>loop")),
        (None, J("loop>host")), (None, J("host>jr")), (None, J("jira>jr")),
        ("the dashboard build session reads people.yaml and builds this role's dashboard", J("host>db")),
        (None, J("repo>db")), (None, J("db>dash")),
        ("dashboard tabs open; the sprint leave calendar reads the Sprint Leave page",
         [("dash", k) for k in CHIP_IDS] + J("conf>c_leave")),
        ("Save on a tab sends a SDLC block to the day assistant session", J("po>dash")), (None, J("dash>srv")),
        (None, J("srv>outb")), (None, J("outb>loop")), (None, J("loop>host")), (None, J("host>chat")),
        ("after approved: the roster or leave page in Confluence, and a people.yaml PR", J("chat>conf", "chat>bb"))]),
    ("appr", "Approver", [
        ("replies approved on the gate card", J("appr>runs")), (None, J("runs>srv")), (None, J("srv>outb")),
        (None, J("outb>loop")), (None, J("loop>host")), (None, J("host>sdlc")),
        ("only now the session writes: Jira story and sub-tasks, Confluence pages, devin/* branch and PR",
         J("sdlc>jira", "sdlc>bb", "sdlc>conf")),
        ("the PR state session keeps the Runs page up to date", J("host>prs")), (None, J("bb>prs")),
        ("a person merges; when Bitbucket has a newer commit the updater restarts Argus", J("bb>upd")),
        (None, J("upd>srv"))]),
    ("qa", "Tester", [
        ("presses Test on my PC", J("qa>pc")), (None, J("pc>local")),
        ("Devin Local runs the story's test pack and sends the evidence to the run session", J("local>sdlc")),
        ("the result shows on the Runs page", J("sdlc>loop")), (None, J("loop>inb")), (None, J("inb>poll")),
        (None, J("poll>runs"))]),
]
STEP_S, GAP_S = 0.95, 1.6
SEGS = []  # (role key, start s, end s)
_t = 0.0
for _k, _n, _steps in ROLES:
    _d = len(_steps) * STEP_S + GAP_S
    SEGS.append((_k, _t, _t + _d))
    _t += _d
T = round(_t, 2)
_ekeys = {(a, b) for a, b, *_r in E}
for _k, _n, _steps in ROLES:
    for _c, _pairs in _steps:
        for _p in _pairs:
            assert _p in _ekeys, _p


def role_plan():
    """edge -> [(start frac, end frac)], edge/node -> set of segment indexes, captions [(a, b, text)]."""
    wins, used, caps = {}, {}, []
    for si, (k, name, steps) in enumerate(ROLES):
        t0 = SEGS[si][1]
        cur = None
        for i, (cap, pairs) in enumerate(steps):
            a = t0 + i * STEP_S
            if cap:
                if cur:
                    caps.append((cur[0] / T, a / T, cur[1]))
                cur = (a, "%s: %s" % (name, cap[0].upper() + cap[1:]))
            for p in pairs:
                wins.setdefault(p, []).append((a / T, (a + STEP_S * 1.1) / T))
                for x in (p, p[0], p[1]):
                    used.setdefault(x, set()).add(si)
        caps.append((cur[0] / T, SEGS[si][2] / T, cur[1]))
    return wins, used, caps


def seg_anim(attr, idx_set, on, off):
    keys = ";".join("%.4f" % (s[1] / T) for s in SEGS)
    vals = ";".join(str(on if i in idx_set else off) for i in range(len(SEGS)))
    return ('<animate attributeName="%s" dur="%ss" repeatCount="indefinite" calcMode="discrete" values="%s" '
            'keyTimes="%s"/>' % (attr, T, vals, keys))


KINDS = [("req", "Request from a person"), ("devin", "Devin call"), ("back", "Progress back"),
         ("read", "Read"), ("write", "Write after approval"), ("gate", "Approval")]

# ---------- themes ----------
BASE = dict(font="Segoe UI, Arial, sans-serif", bg="#ffffff", grid=None, text="#2b2140", sub="#6b6380",
            node="#ffffff", nstroke="#5b2a86", nsw=1.4, rx=10, chip="#f2ecfa", cstroke="#c9b6e4",
            lane="#f6f2fb", lane2="#ffffff", lanetext="#5b2a86", shadow=True, glow=False, sketch=False,
            edge="curve", ew=1.6, dot=5, label="#5b2a86", labelbg="#ffffff",
            colors=dict(req="#7b3fb3", devin="#1f6fd1", back="#0f9d8a", read="#d48806", write="#c2185b",
                        gate="#d93025", link="#9a90ab"),
            title="#3d1a63", lanefill=None)
THEMES = [
    dict(key="purple", name="Acme Claims purple", layout="cols", best="House style; matches the team's other pages."),
    dict(key="neon", name="Night neon", layout="cols", bg="#0b1020", text="#e8ecff", sub="#8f9bc4",
         node="#121a33", nstroke="#3b4a80", chip="#18213f", cstroke="#2f3b66", lane="#0f1730", lane2="#0b1020",
         lanetext="#7fd3ff", shadow=False, glow=True, label="#c9d4ff", labelbg="#0b1020", title="#ffffff",
         colors=dict(req="#ff4fd8", devin="#3ec8ff", back="#39ff9e", read="#ffd23f", write="#ff6b6b",
                     gate="#ff2e63", link="#4a5684"), best="Big screens and demos; the moving data stands out."),
    dict(key="blueprint", name="Blueprint", layout="cols", font="Consolas, 'Courier New', monospace",
         bg="#0e3a6b", grid="#1d5089", text="#ffffff", sub="#b8d4f5", node="#0e3a6b", nstroke="#e6f1ff",
         nsw=1.2, rx=2, chip="#124679", cstroke="#9cc3ee", lane="none", lane2="none", lanetext="#ffffff",
         shadow=False, edge="ortho", label="#ffffff", labelbg="#0e3a6b", title="#ffffff",
         colors=dict(req="#ffffff", devin="#7fd4ff", back="#a8ffcf", read="#ffe08a", write="#ff9e9e",
                     gate="#ffb3d1", link="#6f9ccc"), best="Engineering audience; reads like a technical drawing."),
    dict(key="lanes", name="Swimlanes", layout="rows", bg="#fbfbfd", lanefill=["#f3eefb", "#eef5ff", "#eefaf6",
         "#fff7e8", "#fdeef3", "#f1f1f6"], lane2=None, lanetext="#3d1a63", rx=8,
         best="Shows who owns each layer, top to bottom."),
    dict(key="sketch", name="Sketchbook", layout="cols", font="'Comic Sans MS', 'Segoe Print', cursive",
         bg="#fffdf5", text="#2d2a26", sub="#5f5a52", node="#fffdf5", nstroke="#2d2a26", nsw=1.8, rx=14,
         chip="#fff4cf", cstroke="#2d2a26", lane="#fff8e0", lane2="#fffdf5", lanetext="#2d2a26", shadow=False,
         sketch=True, label="#2d2a26", labelbg="#fffdf5", title="#2d2a26",
         colors=dict(req="#6a3fb5", devin="#2a6fdb", back="#1a9c6b", read="#e08a00", write="#d6336c",
                     gate="#e03131", link="#8d877c"), best="Friendly, whiteboard feel for team sessions."),
    dict(key="pastel", name="Pastel cards", layout="cols", bg="#f7f8fc", rx=18, nsw=0, lane="none", lane2="none",
         lanefill=["#efe7fb", "#e6f0ff", "#e3f6f1", "#fff1dc", "#fde6ee", "#ecebf5"], node=None,
         chip="#ffffff", cstroke="#e1d8ef", best="Soft and readable; each layer has its own colour."),
    dict(key="metro", name="Metro map", layout="cols", bg="#ffffff", node="#ffffff", nstroke="#222222", nsw=3,
         rx=26, edge="ortho", ew=5, dot=6, lane="none", lane2="none", lanetext="#222222", shadow=False,
         colors=dict(req="#9c27b0", devin="#0072ce", back="#00a651", read="#f7a600", write="#e3001b",
                     gate="#222222", link="#b0b0b0"), metro=True,
         best="Each kind of data is its own line; easy to follow one path."),
    dict(key="mono", name="Executive grey", layout="cols", bg="#ffffff", text="#222222", sub="#777777",
         node="#ffffff", nstroke="#bdbdbd", nsw=1, rx=4, chip="#f5f5f5", cstroke="#e0e0e0", lane="#fafafa",
         lane2="#ffffff", lanetext="#555555", shadow=False, ew=1.1, dot=4, label="#555555", title="#222222",
         colors=dict(req="#5b2a86", devin="#5b2a86", back="#5b2a86", read="#9e9e9e", write="#5b2a86",
                     gate="#5b2a86", link="#cfcfcf"), best="Print-friendly; one accent colour for leadership decks."),
    dict(key="orbit", name="Hub and orbit", layout="hub", bg="#1c0f2e", text="#f4eefc", sub="#bba9d6",
         node="#2a1745", nstroke="#8c5cc7", chip="#2a1745", cstroke="#6e48a3", lanetext="#d9c5f5",
         shadow=False, glow=True, label="#e9dcff", labelbg="#1c0f2e", title="#ffffff", edge="hub",
         colors=dict(req="#ff8ad8", devin="#6cc4ff", back="#5cf2b8", read="#ffd166", write="#ff7a7a",
                     gate="#ff4d6d", link="#5a427d"), best="Puts Argus in the middle of everything it touches."),
    dict(key="sequence", name="Sequence story", layout="seq", best="Walks one run step by step, in order."),
]


def theme(t):
    d = dict(BASE)
    d.update(t)
    c = dict(BASE["colors"])
    c.update(t.get("colors", {}))
    d["colors"] = c
    return d


def e(s):
    return html.escape(str(s), quote=True)


def wrap(s, n):
    words, lines, cur = s.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > n and cur:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        lines.append(cur)
    return lines


# ---------- layouts ----------
def positions(layout):
    pos = {}
    if layout == "cols":
        for k, (c, y, *_r) in N.items():
            x = COLS[c][0] + (10 if N[k][4] == "chip" else 0)
            w, h = (200, 32) if N[k][4] == "chip" else ((180, 56) if c == 0 else (210, 58))
            pos[k] = (x, y + 30, w, h)
    elif layout == "rows":
        lane_h = (H - 60) / 6
        by = {}
        for k, (c, y, *_r) in N.items():
            by.setdefault(c, []).append((y, k))
        for c, items in by.items():
            items.sort()
            nodes = [k for _, k in items if N[k][4] != "chip"]
            chips = [k for _, k in items if N[k][4] == "chip"]
            cy = 60 + lane_h * c + lane_h / 2
            if c == 1:
                order = [k for k in nodes if k != "pc"]
                xs = [320, 530, 740]
                for i, k in enumerate(order):
                    pos[k] = (xs[i], cy - 22, 196, 50)
                pos["pc"] = (1490, cy - 22, 190, 50)
                for i, k in enumerate(chips):
                    col, row = i % 3, i // 3
                    pos[k] = (960 + col * 150, cy - 40 + row * 36, 142, 28)
            else:
                n = len(nodes)
                span = 1290
                for i, k in enumerate(nodes):
                    pos[k] = (300 + span * (i + 0.5) / n, cy, min(212, span / n - 18), 52)
    elif layout == "hub":
        cx, cy = 800, 470
        pos["srv"] = (cx, cy, 230, 70)
        inner = ["outb", "loop", "inb", "alive", "api", "local", "upd", "poll", "state"]
        for i, k in enumerate(inner):
            a = math.radians(-90 + i * 40)
            pos[k] = (cx + 335 * math.cos(a), cy + 190 * math.sin(a), 168, 46)
        for k, ang in zip(["runs", "back", "dash", "pc"], [-135, -160, 160, 135]):
            a = math.radians(ang)
            pos[k] = (cx + 540 * math.cos(a), cy + 330 * math.sin(a), 182, 48)
        for i, k in enumerate(["host", "sdlc", "chat", "jr", "prs", "db", "ins"]):
            a = math.radians(-60 + i * 20)
            pos[k] = (cx + 530 * math.cos(a), cy + 340 * math.sin(a), 182, 48)
        for i, k in enumerate(["dev", "po", "appr", "qa"]):
            pos[k] = (95, 190 + i * 150, 160, 52)
        for i, k in enumerate(["jira", "conf", "bb", "repo", "snow"]):
            pos[k] = (1522, 160 + i * 150, 140, 52)
        for i, k in enumerate(CHIPS):
            pos[k] = (100 + (i % 4) * 160, 800 + (i // 4) * 36, 152, 28)
    return pos


def anchor(p, q, horiz):
    x, y, w, h = p
    if horiz:
        return (x + (w / 2 if q[0] > x else -w / 2), y)
    return (x, y + (h / 2 if q[1] > y else -h / 2))


def edge_path(a, b, pos, style, layout):
    p, q = pos[a], pos[b]
    dx, dy = q[0] - p[0], q[1] - p[1]
    if layout == "hub":
        horiz = abs(dx) > abs(dy) * 1.3
        s, t = anchor(p, q, horiz), anchor(q, p, horiz)
        mx, my = (s[0] + t[0]) / 2, (s[1] + t[1]) / 2
        cx = mx + (800 - mx) * 0.35
        cy = my + (470 - my) * 0.35
        return "M%.1f,%.1f Q%.1f,%.1f %.1f,%.1f" % (s[0], s[1], cx, cy, t[0], t[1]), (cx * .5 + mx * .5, cy * .5 + my * .5)
    horiz = abs(dx) > 40 if layout == "cols" else abs(dy) < 40
    if layout == "cols" and a == "dash" and b in CHIPS:
        x0 = p[0] - p[2] / 2 + 14
        return "M%.1f,%.1f V%.1f H%.1f" % (x0, p[1] + p[3] / 2, q[1], q[0] - q[2] / 2), (x0, q[1])
    if layout == "cols" and abs(dx) < 40 and a == "host":
        sx, tx = p[0] + p[2] / 2, q[0] + q[2] / 2
        bend = 40 + abs(dy) * 0.12
        if style == "ortho":
            return "M%.1f,%.1f H%.1f V%.1f H%.1f" % (sx, p[1], sx + 18, q[1], tx), (sx + 18, q[1])
        return ("M%.1f,%.1f C%.1f,%.1f %.1f,%.1f %.1f,%.1f" % (sx, p[1], sx + bend, p[1], tx + bend, q[1], tx, q[1]),
                (tx + bend * 0.75, (p[1] + q[1]) / 2))
    s, t = anchor(p, q, horiz), anchor(q, p, horiz)
    if style == "ortho":
        if horiz:
            mx = (s[0] + t[0]) / 2
            return "M%.1f,%.1f H%.1f V%.1f H%.1f" % (s[0], s[1], mx, t[1], t[0]), (mx, (s[1] + t[1]) / 2)
        my = (s[1] + t[1]) / 2
        return "M%.1f,%.1f V%.1f H%.1f V%.1f" % (s[0], s[1], my, t[0], t[1]), ((s[0] + t[0]) / 2, my)
    if horiz:
        k = max(40, abs(t[0] - s[0]) * 0.45)
        sg = 1 if t[0] > s[0] else -1
        c1, c2 = (s[0] + sg * k, s[1]), (t[0] - sg * k, t[1])
    else:
        k = max(30, abs(t[1] - s[1]) * 0.45)
        sg = 1 if t[1] > s[1] else -1
        c1, c2 = (s[0], s[1] + sg * k), (t[0], t[1] - sg * k)
    mid = ((s[0] + 3 * c1[0] + 3 * c2[0] + t[0]) / 8, (s[1] + 3 * c1[1] + 3 * c2[1] + t[1]) / 8)
    return "M%.1f,%.1f C%.1f,%.1f %.1f,%.1f %.1f,%.1f" % (s[0], s[1], c1[0], c1[1], c2[0], c2[1], t[0], t[1]), mid


def window(ph, hop, hops):
    s, t, _ = PH[ph]
    step = (t - s) / hops
    a = s + hop * step
    return max(a, 0.002), min(a + step * 1.15, 0.995)


def dot(pid, color, r, a, b, glow):
    kt = "0;%.3f;%.3f;1" % (a, b)
    f = ' filter="url(#%s-glow)"' % pid.split("-e")[0] if glow else ""
    return ('<circle r="%s" fill="%s"%s opacity="0">'
            '<animateMotion dur="%ss" repeatCount="indefinite" keyPoints="0;0;1;1" keyTimes="%s" calcMode="linear">'
            '<mpath href="#%s" xlink:href="#%s"/></animateMotion>'
            '<animate attributeName="opacity" dur="%ss" repeatCount="indefinite" calcMode="discrete" '
            'values="0;1;0" keyTimes="0;%.3f;%.3f"/></circle>') % (r, color, f, T, kt, pid, pid, T, a, b)


def defs(pid, th):
    out = ['<defs>']
    for k, c in th["colors"].items():
        out.append('<marker id="%s-ar-%s" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="11" markerHeight="11" markerUnits="userSpaceOnUse" '
                   'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="%s"/></marker>' % (pid, k, c))
    out.append('<filter id="%s-sh" x="-10%%" y="-20%%" width="120%%" height="150%%"><feDropShadow dx="0" dy="2" '
               'stdDeviation="2.5" flood-color="#3d1a63" flood-opacity="0.16"/></filter>' % pid)
    out.append('<filter id="%s-glow" x="-50%%" y="-50%%" width="200%%" height="200%%"><feGaussianBlur stdDeviation="2.6" '
               'result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>' % pid)
    out.append('<filter id="%s-rough"><feTurbulence type="fractalNoise" baseFrequency="0.03" numOctaves="2" seed="3"/>'
               '<feDisplacementMap in="SourceGraphic" scale="3.2"/></filter>' % pid)
    if th["grid"]:
        out.append('<pattern id="%s-grid" width="20" height="20" patternUnits="userSpaceOnUse"><path d="M20,0 H0 V20" '
                   'fill="none" stroke="%s" stroke-width="0.6"/></pattern>' % (pid, th["grid"]))
    out.append('</defs>')
    return "".join(out)


def caption(th, y):
    out = []
    for a, b, txt in role_plan()[2]:
        a = max(a, 0.0005)
        out.append('<text x="%d" y="%d" text-anchor="middle" font-size="16" font-weight="600" fill="%s" opacity="0">%s'
                   '<animate attributeName="opacity" dur="%ss" repeatCount="indefinite" calcMode="discrete" '
                   'values="0;1;0" keyTimes="0;%.4f;%.4f"/></text>' % (W / 2, y, th["title"], e(txt), T, a, min(b, 0.9999)))
    return "".join(out)


def legend(th, x, y):
    out = []
    for i, (k, lab) in enumerate(KINDS):
        xx = x + i * 205
        out.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="%s" stroke-width="3"/>'
                   '<circle cx="%d" cy="%d" r="4" fill="%s"/>'
                   '<text x="%d" y="%d" font-size="12.5" fill="%s">%s</text>' %
                   (xx, y, xx + 26, y, th["colors"][k], xx + 13, y, th["colors"][k], xx + 34, y + 4, th["text"], e(lab)))
    return "".join(out)


def node_svg(pid, k, p, th, lane_i):
    c, _y, title, sub, kind = N[k]
    x, y, w, h = p
    chip = kind == "chip"
    fill = th["chip"] if chip else (th["node"] or "#ffffff")
    stroke = th["cstroke"] if chip else th["nstroke"]
    sw = th["nsw"] if not chip else 1
    if th["lanefill"] and th["node"] is None and not chip:
        fill = th["lanefill"][lane_i]
    flt = ""
    if th["shadow"] and not chip:
        flt = ' filter="url(#%s-sh)"' % pid
    if th["glow"] and not chip:
        flt = ' filter="url(#%s-glow)"' % pid
    rx = min(th["rx"], h / 2)
    detail = "%s. %s" % (title, sub) if sub else title
    used = role_plan()[1].get(k, set())
    out = ['<g class="nd" data-k="%s"><title>%s</title>' % (k, e(detail))]
    if th.get("metro") and not chip:
        out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="%.1f" fill="#ffffff" stroke="#222" '
                   'stroke-width="3"/>' % (x - w / 2, y - h / 2, w, h, rx))
        out.append('<circle cx="%.1f" cy="%.1f" r="7" fill="#fff" stroke="#222" stroke-width="3"/>' % (x - w / 2 + 18, y))
        tx, anchor_ = x - w / 2 + 34, "start"
    else:
        out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="%.1f" fill="%s" stroke="%s" '
                   'stroke-width="%s"%s/>' % (x - w / 2, y - h / 2, w, h, rx, fill, stroke if sw else "none", sw, flt))
        tx, anchor_ = x, "middle"
    if chip:
        out.append('<text x="%.1f" y="%.1f" text-anchor="middle" font-size="12" fill="%s">%s</text>' %
                   (x, y + 4, th["text"], e(title)))
    else:
        out.append('<text x="%.1f" y="%.1f" text-anchor="%s" font-size="14" font-weight="700" fill="%s">%s</text>' %
                   (tx, y - 4 if sub else y + 5, anchor_, th["text"], e(title)))
        if sub:
            room = (w - 16) if tx == x else (x + w / 2 - tx - 8)
            fs = max(8.5, min(11.5, room / (len(sub) * 0.56)))
            out.append('<text x="%.1f" y="%.1f" text-anchor="%s" font-size="%.1f" fill="%s">%s</text>' %
                       (tx, y + 13, anchor_, fs, th["sub"], e(sub)))
    out.append("</g>")
    return "".join(out)


def svg_graph(th, pid):
    layout = th["layout"]
    pos = positions(layout)
    o = ['<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 %d %d" '
         'role="img" aria-label="%s" font-family="%s">' % (W, H, e("Argus architecture, " + th["name"]),
                                                          e(th["font"])), defs(pid, th)]
    o.append('<rect width="%d" height="%d" fill="%s"/>' % (W, H, th["bg"]))
    if th["grid"]:
        o.append('<rect width="%d" height="%d" fill="url(#%s-grid)"/>' % (W, H, pid))
    body = ['<g%s>' % (' filter="url(#%s-rough)"' % pid if th["sketch"] else "")]
    if layout == "cols":
        for i, (x, name) in enumerate(COLS):
            lw = 236 if i else 200
            fill = (th["lanefill"][i] if th["lanefill"] else (th["lane"] if i % 2 == 0 else th["lane2"]))
            if fill != "none":
                body.append('<rect x="%d" y="62" width="%d" height="770" rx="12" fill="%s"%s/>' %
                            (x - lw / 2, lw, fill, ' opacity="0.55"' if th["lanefill"] else ""))
            body.append('<text x="%d" y="86" text-anchor="middle" font-size="15" font-weight="700" fill="%s">%s</text>'
                        % (x, th["lanetext"], e(name)))
            if LANE_NOTE[i]:
                body.append('<text x="%d" y="104" text-anchor="middle" font-size="11" fill="%s">%s</text>'
                            % (x, th["sub"], e(LANE_NOTE[i])))
    elif layout == "rows":
        lane_h = (H - 60) / 6
        for i, (_x, name) in enumerate(COLS):
            y0 = 52 + lane_h * i
            body.append('<rect x="20" y="%.1f" width="%d" height="%.1f" rx="10" fill="%s"/>' %
                        (y0 + 4, W - 40, lane_h - 6, th["lanefill"][i]))
            body.append('<text x="40" y="%.1f" font-size="15" font-weight="700" fill="%s">%s</text>' %
                        (y0 + lane_h / 2, th["lanetext"], e(name)))
            body.append('<text x="40" y="%.1f" font-size="11" fill="%s">%s</text>' %
                        (y0 + lane_h / 2 + 17, th["sub"], e(LANE_NOTE[i])))
    elif layout == "hub":
        for r, op in ((330, .25), (560, .14)):
            body.append('<ellipse cx="800" cy="470" rx="%d" ry="%d" fill="none" stroke="%s" stroke-dasharray="4 8" '
                        'opacity="%s"><animateTransform attributeName="transform" type="rotate" from="0 800 470" '
                        'to="360 800 470" dur="120s" repeatCount="indefinite"/></ellipse>' %
                        (r, r * .58, th["nstroke"], op))
        for txt, x, y in (("People", 95, 140), ("Systems of record", 1522, 110), ("Dashboard tabs", 100, 775)):
            body.append('<text x="%d" y="%d" text-anchor="middle" font-size="15" font-weight="700" fill="%s">%s</text>'
                        % (x, y, th["lanetext"], e(txt)))
    edges, labels, dots = [], [], []
    rwins, rused, _caps = role_plan()
    for i, (a, b, kind, lab, _w) in enumerate(E):
        wins = rwins.get((a, b), [])
        pid_e = "%s-e%d" % (pid, i)
        d, mid = edge_path(a, b, pos, th["edge"], layout)
        col = th["colors"][kind]
        dash = ' stroke-dasharray="5 5"' if kind == "link" else ""
        op = 0.85 if th.get("metro") else 0.55
        if kind == "link" and lab == "heartbeat":
            dash = ' stroke-dasharray="2 6"'
        w = th["ew"] if (b not in CHIPS or a != "dash") else 1
        inner = ('<animate attributeName="stroke-dashoffset" from="16" to="0" dur="1s" repeatCount="indefinite"/>'
                 if kind == "link" else "")
        if (a, b) in rused:
            inner += (seg_anim("opacity", rused[(a, b)], 1, op) +
                      seg_anim("stroke-width", rused[(a, b)], round(w * 1.9, 1), w))
        edges.append('<path id="%s" d="%s" fill="none" stroke="%s" stroke-width="%s" opacity="%s"%s '
                     'marker-end="url(#%s-ar-%s)" stroke-linecap="round" stroke-linejoin="round">%s</path>' %
                     (pid_e, d, col, w, op, dash, pid, kind, inner))
        for ws, we in wins:
            dots.append(dot(pid_e, col, th["dot"], max(ws, 0.0005), min(we, 0.9995), th["glow"]))
        if lab:
            lab_anim = ""
            lw = len(lab) * 6.2 + 10
            labels.append('<g>' + lab_anim + '<rect x="%.1f" y="%.1f" width="%.1f" height="16" rx="8" fill="%s" opacity="0.92"/>'
                          '<text x="%.1f" y="%.1f" text-anchor="middle" font-size="10.5" fill="%s">%s</text></g>' %
                          (mid[0] - lw / 2, mid[1] - 9, lw, th["labelbg"], mid[0], mid[1] + 3, col
                           if th["key"] not in ("mono",) else th["label"], e(lab)))
    body += edges
    for k, p in pos.items():
        body.append(node_svg(pid, k, p, th, N[k][0]))
    body += labels
    body.append("</g>")
    o += body + dots
    o.append('<text x="24" y="34" font-size="20" font-weight="700" fill="%s">Argus: how it works</text>'
             % th["title"])
    o.append(legend(th, 330, {"rows": 888, "hub": 884}.get(layout, 860)))
    o.append(caption(th, 36 if layout != "rows" else 36).replace('x="800"', 'x="1000"'))
    o.append("</svg>")
    return "".join(o)


# ---------- sequence ----------
LIFE = [("person", "Person"), ("page", "Argus page"), ("srv", "Argus server"), ("bridge", "Bridge loop"),
        ("sess", "Child session"), ("repo", "Repo and KB"), ("snow", "Snowflake"), ("jira", "Jira"),
        ("conf", "Confluence"), ("bb", "Bitbucket")]
MSG = [("person", "page", "req", "Pick a story, start run"),
       ("page", "srv", "req", "POST /api/runs"),
       ("srv", "bridge", "devin", "outbox: devin_session_create"),
       ("bridge", "sess", "devin", "/intake ACME-nnnn + rules"),
       ("sess", "repo", "read", "routing map, KB, rules"),
       ("sess", "snow", "read", "table checks"),
       ("sess", "jira", "read", "story, acceptance criteria"),
       ("sess", "bridge", "back", "[SDLC] stage and question lines"),
       ("bridge", "srv", "back", "inbox: messages"),
       ("srv", "page", "back", "timeline, numbered questions"),
       ("person", "page", "req", "Answers"),
       ("page", "sess", "devin", "answers as a chat message"),
       ("sess", "page", "back", "[SDLC] gate card"),
       ("person", "page", "gate", "approved"),
       ("page", "sess", "gate", "approved"),
       ("sess", "jira", "write", "story, sub-tasks"),
       ("sess", "bb", "write", "devin/* branch, PR to feature"),
       ("sess", "conf", "write", "pages, demo recording"),
       ("sess", "page", "back", "[SDLC] pr and artefacts")]


def svg_sequence(th, pid):
    th = dict(th)
    o = ['<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 %d %d" '
         'role="img" aria-label="Argus run, step by step" font-family="%s">' % (W, H, e(th["font"])), defs(pid, th),
         '<rect width="%d" height="%d" fill="#ffffff"/>' % (W, H)]
    xs = {k: 90 + i * (1420 / (len(LIFE) - 1)) for i, (k, _) in enumerate(LIFE)}
    for k, name in LIFE:
        x = xs[k]
        o.append('<rect x="%.1f" y="60" width="140" height="40" rx="8" fill="#5b2a86"/>'
                 '<text x="%.1f" y="85" text-anchor="middle" font-size="13.5" font-weight="700" fill="#fff">%s</text>'
                 '<line x1="%.1f" y1="100" x2="%.1f" y2="840" stroke="#c9b6e4" stroke-dasharray="4 5"/>' %
                 (x - 70, x, e(name), x, x))
    step = 0.92 / len(MSG)
    for i, (a, b, kind, lab) in enumerate(MSG):
        y = 130 + i * 37
        x1, x2 = xs[a], xs[b]
        col = th["colors"][kind]
        s = 0.02 + i * step
        pe = "%s-m%d" % (pid, i)
        sg = 1 if x2 > x1 else -1
        o.append('<g opacity="0"><animate attributeName="opacity" dur="%ss" repeatCount="indefinite" calcMode="discrete" '
                 'values="0;1;0" keyTimes="0;%.3f;0.985"/>'
                 '<path id="%s" d="M%.1f,%.1f H%.1f" stroke="%s" stroke-width="2" marker-end="url(#%s-ar-%s)" fill="none"/>'
                 '<rect x="%.1f" y="%.1f" width="%.1f" height="17" rx="4" fill="#fff"/>'
                 '<text x="%.1f" y="%.1f" text-anchor="middle" font-size="12" fill="%s">%d. %s</text></g>' %
                 (T, s, pe, x1 + sg * 6, y, x2 - sg * 6, col, pid, kind,
                  (x1 + x2) / 2 - len(lab) * 3.4 - 14, y - 19, len(lab) * 6.8 + 28,
                  (x1 + x2) / 2, y - 6, col, i + 1, e(lab)))
        o.append(dot(pe, col, 5, s, min(s + step * 1.3, 0.99), False))
    o.append('<text x="24" y="34" font-size="20" font-weight="700" fill="#3d1a63">Argus: one run, step by step</text>')
    o.append(legend(th, 330, 878))
    o.append("</svg>")
    return "".join(o)


def render(t, pid):
    th = theme(t)
    return svg_sequence(th, pid) if th["layout"] == "seq" else svg_graph(th, pid)


def standalone(svg):
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + svg.replace("<svg ", '<svg width="%d" height="%d" ' % (W, H), 1)


def still(svg):
    """The same picture with no animation: every box and line at full strength, no moving dots or captions."""
    svg = re.sub(r'<circle[^>]*opacity="0"[^>]*>.*?</circle>', "", svg, flags=re.S)
    svg = re.sub(r'<text[^>]*opacity="0"[^>]*>.*?</text>', "", svg, flags=re.S)
    svg = re.sub(r'<animate[^>]*/>', "", svg)
    svg = re.sub(r'<animate[^>]*>.*?</animate>', "", svg, flags=re.S)
    return svg



STEPS_TEXT = [
    ("Developer or lead", "Starts a run on the Runs page. The server keeps the run in a small cache and writes a Devin call to the bridge outbox. The bridge loop in the host Devin Cloud session runs it with the session's own tools and creates the SDLC run session, which reads the repo rules, knowledge base and Snowflake (read only, through MCP). Its [SDLC] lines come back through the bridge inbox and turn into the stage rail and numbered questions. On a PC the same calls go straight to the Devin API with the person's key."),
    ("PO, BSA or Scrum Master", "Opens the backlog grid; a short Jira reader session fetches the tickets. The dashboard build session reads people.yaml and builds the dashboard for that role, with its tabs such as the sprint leave calendar, which reads the Confluence Sprint Leave page. Save on a tab sends a SDLC block to the day assistant session, and after approved it updates the roster or leave page and raises a people.yaml PR."),
    ("Approver", "Replies approved on the gate card. Only then does the run session write: Jira story and sub-tasks, Confluence pages, a devin/* branch and a PR into feature/devin-sdlc. The PR state session keeps the Runs page up to date, a person merges, and when Bitbucket has a newer commit the updater offers Update and restarts Argus."),
    ("Tester", "Presses Test on my PC. Devin Local runs the story's test pack on the PC and sends the evidence to the run session, and the result shows on the Runs page."),
]


def gallery(path):
    opts, svgs = [], []
    for i, t in enumerate(THEMES, 1):
        opts.append('<option value="%d">%d. %s</option>' % (i, i, e(t["name"])))
        svgs.append('<figure class="look" data-look="%d" data-seq="%d" data-best="%s"%s>%s</figure>' %
                    (i, int(t["layout"] == "seq"), e(t["best"]), "" if i == 1 else " hidden", render(t, "g%d" % i)))
    steps = "".join('<li><b>%s.</b> %s</li>' % (e(a), e(b)) for a, b in STEPS_TEXT)
    page = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Argus architecture, 10 looks</title>
<style>
:root{--p:#5b2a86;--pd:#3d1a63;--pl:#f3eefb;--t:#2b2140;--s:#6b6380}
*{box-sizing:border-box}body{margin:0;font-family:"Segoe UI",Arial,sans-serif;color:var(--t);background:#faf8fd}
header{background:linear-gradient(90deg,var(--pd),var(--p));color:#fff;padding:14px 24px}
header h1{margin:0;font-size:20px}header p{margin:4px 0 0;font-size:13px;opacity:.9}
.bar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;padding:10px 24px;background:#fff;border-bottom:1px solid #e4daf2;position:sticky;top:0;z-index:2}
.bar label{font-weight:600;font-size:13px;color:var(--pd)}
select,button{font:inherit;font-size:13px;padding:6px 10px;border:1px solid #c9b6e4;border-radius:6px;background:#fff;color:var(--t);cursor:pointer}
select{min-width:220px}button:hover,select:hover{border-color:var(--p)}button:focus-visible,select:focus-visible{outline:2px solid var(--p);outline-offset:2px}
.best{font-size:13px;color:var(--s)}.best b{color:var(--pd)}
main{padding:14px 24px 30px}figure{margin:0}.look svg{width:100%;height:auto;display:block;border:1px solid #e4daf2;border-radius:10px;background:#fff}
.cols{display:grid;grid-template-columns:1.4fr 1fr;gap:18px;margin-top:16px}
section{background:#fff;border:1px solid #e4daf2;border-radius:10px;padding:12px 16px}
h2{font-size:15px;margin:0 0 8px;color:var(--pd)}ol{margin:0;padding-left:20px;font-size:13.5px;line-height:1.5}li{margin-bottom:6px}
p.n{font-size:13.5px;line-height:1.5;margin:0 0 8px}
@media (max-width:900px){.cols{grid-template-columns:1fr}}
@media (prefers-reduced-motion:reduce){.look svg circle{display:none}}
</style></head><body>
<header><h1>Argus: how it works</h1>
<p>One architecture, ten looks. The dots show data moving for one role at a time: developer or lead, PO/BSA/Scrum Master, approver, then tester. Pick a look, and pick a role to watch only that one.</p></header>
<div class="bar"><label for="look">Look</label><select id="look">%s</select>
<label for="role">Role</label><select id="role" style="min-width:250px"><option value="-1">All roles, one by one</option>%s</select>
<button id="prev" type="button" aria-label="Previous look">&#8592;</button><button id="next" type="button" aria-label="Next look">&#8594;</button>
<button id="pause" type="button">Pause</button><button id="restart" type="button">Restart</button>
<span class="best" id="best"></span></div>
<main>%s
<div class="cols"><section><h2>What the picture shows</h2><ol>%s</ol></section>
<section><h2>Notes</h2>
<p class="n">Every look shows the same parts and links, taken from Argus code: console/server.py, console/bridge.py, the dashboard roles in .devin/rules/dashboard-roles.yaml and the tools that keep the roster, Sprint Leave page and sprint sheets.</p>
<p class="n">The dashboard tabs listed are a sample; each role sees its own set of tabs.</p>
<p class="n">Hover over a box to see its full name and what it does.</p></section></div></main>
<script>
(function(){var show,sel=document.getElementById('look'),best=document.getElementById('best'),looks=[].slice.call(document.querySelectorAll('.look')),paused=false;
function cur(){return looks[sel.selectedIndex].querySelector('svg')}
show=function(i){looks.forEach(function(f,j){f.hidden=j!==i;var s=f.querySelector('svg');if(j===i){s.setCurrentTime(0);paused?s.pauseAnimations():s.unpauseAnimations()}else s.pauseAnimations()});
sel.selectedIndex=i;best.innerHTML='<b>Best for:</b> '+looks[i].dataset.best;try{history.replaceState(null,'','#look='+(i+1))}catch(e){}};
sel.onchange=function(){show(sel.selectedIndex)};
document.getElementById('prev').onclick=function(){show((sel.selectedIndex+looks.length-1)%%looks.length)};
document.getElementById('next').onclick=function(){show((sel.selectedIndex+1)%%looks.length)};
document.getElementById('pause').onclick=function(){paused=!paused;paused?cur().pauseAnimations():cur().unpauseAnimations();this.textContent=paused?'Play':'Pause'};
document.getElementById('restart').onclick=function(){cur().setCurrentTime(0)};
var role=document.getElementById('role'),SEGS=%SEGS%;
role.onchange=function(){var s=cur();if(+role.value>=0&&looks[sel.selectedIndex].dataset.seq!=='1')s.setCurrentTime(SEGS[+role.value][0])};
setInterval(function(){var r=+role.value,f=looks[sel.selectedIndex];if(r<0||f.dataset.seq==='1'||paused)return;var s=f.querySelector('svg'),t=s.getCurrentTime()%%%T%;
if(t<SEGS[r][0]||t>=SEGS[r][1]-0.05)s.setCurrentTime(SEGS[r][0])},120);
var _show=show;show=function(i){_show(i);var q=looks[i].dataset.seq==='1';role.disabled=q;role.title=q?'This look follows one run from start to end':'';if(!q&&+role.value>=0)cur().setCurrentTime(SEGS[+role.value][0])};
var m=/look=(\d+)/.exec(location.hash);show(m?Math.min(looks.length,Math.max(1,+m[1]))-1:0)})();
</script></body></html>""".replace("%%", "%")
    ropts = "".join('<option value="%d">%s</option>' % (i, e(n)) for i, (_k, n, _s) in enumerate(ROLES))
    for part in ("".join(opts), ropts, "".join(svgs), steps):
        page = page.replace("%s", part, 1)
    page = page.replace("%SEGS%", "[" + ",".join("[%.3f,%.3f]" % (a, b) for _k, a, b in SEGS) + "]").replace("%T%", str(T))
    with open(path, "w") as f:
        f.write(page)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for i, t in enumerate(THEMES, 1):
        with open(os.path.join(OUT, "workbench-architecture-%02d-%s.svg" % (i, t["key"])), "w") as f:
            f.write(standalone(render(t, "s%d" % i)))
        if t["key"] == "pastel":
            with open(os.path.join(OUT, "workbench-architecture-%02d-%s-still.svg" % (i, t["key"])), "w") as f:
                f.write(standalone(still(render(t, "s%d" % i))))
    gallery(os.path.join(OUT, "workbench-architecture-gallery.html"))
    print("ok")
