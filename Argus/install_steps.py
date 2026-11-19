#!/usr/bin/env python3
"""The install steps behind the install window (install_ui.py), beyond the copy-in and value swap
in install.py: team settings, roster, Confluence pages, git branch and push, the saved draft,
playbooks and the Devin Cloud blueprint and knowledge note. Tokens come from the environment
variables named in the values and are never printed or written to a file."""
import csv
import datetime
import io
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from xml.etree import ElementTree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import install  # noqa: E402

PROFILE = ".devin/rules/sdlc-profile.json"
KB_PROFILE = ".devin/rules/kb-profile.yaml"
PEOPLE = ".devin/rules/people.yaml"
GATES = ".devin/rules/approval-gates.yaml"
APPROVERS = re.compile(r"(?P<head>- role: (?P<role>[\w-]+)[^\n]*\n(?P<ind>[ \t]+)names: )\[(?P<names>[^\]]*)\]"
                       r"(?:\n(?P=ind)backups: \[(?P<backups>[^\]]*)\])?")
NOT_ON_ROSTER = re.compile(r"(?m)^not_on_roster:[^\n]*\n(?:[ \t]+(?:#|- )[^\n]*\n)*")
DRAFT_NAME = "install-draft.yaml"
DRAFT_BRANCH = "devin/install-draft"
PAGE_KEYS = ("roster", "sprint_leave", "demo_recordings", "user_manual")
PAGE_TITLES = {"roster": "{product} Team Roster", "sprint_leave": "{product} Sprint Leave",
               "demo_recordings": "{product} Demo Recordings", "user_manual": "{product} Devin Cloud User Manual"}
ROSTER_COLUMNS = ("name", "email", "jira_user", "primary_role", "roles", "allocation", "delegate", "delivery")


def read_text(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def today():
    return datetime.date.today().isoformat()


def default_titles(values):
    return {k: v.format(product=values.get("product_name") or "Team") for k, v in PAGE_TITLES.items()}


def page_titles(values, settings):
    """The page titles: the ones typed in the window, the default for any left blank."""
    typed = {k: str(v).strip() for k, v in (settings.get("pages") or {}).items() if str(v or "").strip()}
    return dict(default_titles(values), **typed)


def page_id(text):
    """A Confluence page id from an id or a page link."""
    text = str(text or "").strip()
    m = re.search(r"pageId=(\d+)", text) or re.search(r"/pages/(\d+)", text) or re.fullmatch(r"(\d+)", text)
    return m.group(1) if m else ""


# ---- roles and roster -----------------------------------------------------------------------------

def rules_dir(root):
    for name in (".devin/rules", "dot-devin/rules"):
        path = os.path.join(root, name)
        if os.path.isdir(path):
            return path
    return None


def roles(root):
    """(job roles from role-routing.yaml, gate roles from approval-gates.yaml) of a copy or a repo."""
    rules = rules_dir(root)
    if not rules:
        return [], []
    routing = install.load_yaml(os.path.join(rules, "role-routing.yaml"))
    job = sorted(set(routing.get("roles") or {}) | set(routing.get("role_aliases") or {}))
    gate = set()

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in ("role", "required_role") and isinstance(v, str):
                    gate.add(v)
                walk(v)
        elif isinstance(o, list):
            for x in o:
                walk(x)
    walk(install.load_yaml(os.path.join(rules, "approval-gates.yaml")).get("gates"))
    return job, sorted(gate | {"tech_lead", "manager"})


def split(text):
    if isinstance(text, list):
        return [str(x).strip() for x in text if str(x).strip()]
    return [t.strip() for t in re.split(r"[,;]", str(text or "")) if t.strip()]


def clean_person(row):
    p = {k: row.get(k) for k in ROSTER_COLUMNS}
    p["name"] = str(p.get("name") or "").strip()
    p["email"] = str(p.get("email") or "").strip()
    p["jira_user"] = str(p.get("jira_user") or "").strip()
    p["primary_role"] = str(p.get("primary_role") or "").strip()
    p["roles"] = split(p.get("roles"))
    alloc = str(p.get("allocation") if p.get("allocation") is not None else "").strip().rstrip("%")
    p["allocation"] = int(alloc) if alloc.isdigit() else 100
    p["delegate"] = str(p.get("delegate") or "").strip()
    d = p.get("delivery")
    p["delivery"] = not (str(d).strip().lower() in ("no", "n", "false", "0")) if d not in (None, "") else True
    return p


HEADER_ALIASES = {"name": "name", "email": "email", "jira user": "jira_user", "jira_user": "jira_user",
                  "primary role": "primary_role", "primary_role": "primary_role", "gate roles": "roles",
                  "roles": "roles", "allocation": "allocation", "allocation %": "allocation",
                  "delegate": "delegate", "delegate to": "delegate", "delivery": "delivery"}


def rows_to_roster(rows):
    rows = [r for r in rows if any(str(c).strip() for c in r)]
    if not rows:
        return []
    head = [HEADER_ALIASES.get(str(h).strip().lower()) for h in rows[0]]
    if "name" not in head:
        raise ValueError("the first row must be the column names (Name, Email, Jira user, Primary role, "
                         "Gate roles, Allocation, Delegate, Delivery)")
    out = []
    for r in rows[1:]:
        out.append(clean_person({h: (r[i] if i < len(r) else "") for i, h in enumerate(head) if h}))
    return [p for p in out if p["name"]]


def xlsx_rows(data):
    """Rows of the first sheet of an .xlsx file, with the standard library only."""
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ElementTree.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", ns):
                shared.append("".join(x.text or "" for x in si.iter("{%s}t" % ns["m"])))
        sheets = sorted(n for n in z.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n))
        root = ElementTree.fromstring(z.read(sheets[0]))
    rows = []
    for row in root.iter("{%s}row" % ns["m"]):
        cells = {}
        for c in row.findall("m:c", ns):
            col = re.match(r"[A-Z]+", c.get("r", "A")).group(0)
            idx = 0
            for ch in col:
                idx = idx * 26 + ord(ch) - 64
            v = c.find("m:v", ns)
            text = v.text if v is not None else "".join(x.text or "" for x in c.iter("{%s}t" % ns["m"]))
            if c.get("t") == "s" and text is not None:
                text = shared[int(text)]
            cells[idx - 1] = text or ""
        rows.append([cells.get(i, "") for i in range(max(cells) + 1)] if cells else [])
    return rows


def parse_roster(data, filename=""):
    """A filled-in roster template (.csv or .xlsx) -> roster rows."""
    if filename.lower().endswith(".xlsx") or data[:2] == b"PK":
        return rows_to_roster(xlsx_rows(data))
    text = data.decode("utf-8-sig") if isinstance(data, bytes) else data
    return rows_to_roster(list(csv.reader(io.StringIO(text))))


def roster_problems(roster, settings, job_roles, gate_roles):
    out = []
    if not roster:
        return ["the roster is empty: add the team, starting with the tech lead"]
    users = {p["jira_user"] for p in roster if p.get("jira_user")}
    names = {p["name"] for p in roster}
    lead = (settings.get("tech_lead") or {}).get("email", "").lower()
    if lead and lead not in {p["email"].lower() for p in roster}:
        out.append("the tech lead (%s) is not on the roster" % lead)
    for p in roster:
        who = p.get("name") or "a row"
        if not p.get("email"):
            out.append("%s has no email" % who)
        if not p.get("jira_user"):
            out.append("%s has no Jira user" % who)
        if job_roles and p.get("primary_role") not in job_roles:
            out.append("%s: primary role %r is not one of the job roles" % (who, p.get("primary_role")))
        bad = [r for r in p.get("roles") or [] if gate_roles and r not in gate_roles]
        if bad:
            out.append("%s: %s not a gate role" % (who, ", ".join(bad)))
        if p.get("delegate") and p["delegate"] not in users and p["delegate"] not in names:
            out.append("%s: delegate %s is not on the roster" % (who, p["delegate"]))
    if len(users) != len([p for p in roster if p.get("jira_user")]):
        out.append("two people have the same Jira user")
    return out


def header_lines(text):
    lines = []
    for line in text.splitlines():
        if line.startswith("#") or not line.strip():
            lines.append(line)
        else:
            break
    return "\n".join(lines).rstrip() + "\n\n" if lines else ""


def keep_example_roster(target, values):
    """Keep the shipped roster and gates for the framework's own tests, which are written against them."""
    dest = os.path.join(target, install.sp(values, install.EXAMPLE_ROSTER))
    if os.path.isdir(dest):
        return
    os.makedirs(dest)
    for rel in (PEOPLE, GATES):
        if os.path.exists(os.path.join(target, rel)):
            shutil.copyfile(os.path.join(target, rel), os.path.join(dest, os.path.basename(rel)))
    with open(os.path.join(dest, "README.md"), "w", encoding="utf-8") as fh:
        fh.write("# Example roster for the framework's tests\n\nThe placeholder people and gates the framework "
                 "came with. Its own tests are written against them, so the install checks run those tests with "
                 "these two files in place of your roster. Your roster is `.devin/rules/people.yaml`.\n")


def flow_name(name):
    return json.dumps(name) if any(c in name for c in ",:#[]{}'\"") else name


def write_gates(target, roster, lead_name):
    """Gate approvers from the team's roster: everyone holding the gate's role, else the tech lead."""
    path = os.path.join(target, GATES)
    if not roster or not os.path.exists(path):
        return None
    lead_name = lead_name or roster[0]["name"]

    def one(m):
        role = m.group("role")
        names = [p["name"] for p in roster if role in p["roles"] or p["primary_role"] == role] or [lead_name]
        out = m.group("head") + "[%s]" % ", ".join(flow_name(n) for n in names)
        if m.group("backups") is not None:
            backups = [] if lead_name in names else [lead_name]
            out += "\n%sbackups: [%s]" % (m.group("ind"), ", ".join(flow_name(n) for n in backups))
        return out
    text, n = APPROVERS.subn(one, read_text(path))
    text = NOT_ON_ROSTER.sub("not_on_roster: []\n\n", text, count=1)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return "gates: %d approver lists set from the roster" % n


def write_roster(target, values, settings, page=None):
    """people.yaml from the window's roster; the tech lead owns it and its sign-off is pending."""
    import yaml
    path = os.path.join(target, PEOPLE)
    text = read_text(path) if os.path.exists(path) else ""
    data = yaml.safe_load(text) or {} if text else {}
    roster = [clean_person(p) for p in settings.get("roster") or []]
    by_name = {p["name"]: p["jira_user"] for p in roster}
    lead_email = ((settings.get("tech_lead") or {}).get("email") or "").lower()
    lead = next((p for p in roster if p["email"].lower() == lead_email), roster[0] if roster else None)
    titles = page_titles(values, settings)
    source = dict(data.get("source") or {})
    source.update({"confluence_page_id": (page or {}).get("id") or (settings.get("page_ids") or {}).get("roster"),
                   "confluence_version": (page or {}).get("version", 1),
                   "confluence_title": titles["roster"], "synced_at": None, "owner_signoff": "pending"})
    owner = dict(data.get("owner") or {})
    leads = [p["jira_user"] for p in roster if p is not lead and
             any("lead" in r for r in p["roles"] + [p["primary_role"]])]
    owner.update({"primary": lead["jira_user"] if lead else None, "backups": leads,
                  "review_cadence": owner.get("review_cadence") or "quarterly", "last_reviewed": today(),
                  "signoff": {"status": "pending", "signed_by": None, "signed_on": None, "signed_via": None}})
    people = []
    for p in roster:
        rec = {"jira_user": p["jira_user"], "name": p["name"], "email": p["email"], "devin_user_id": None}
        if not p["delivery"]:
            rec["delivery"] = False
        rec.update({"roles": p["roles"], "primary_role": p["primary_role"], "secondary_roles": [],
                    "role_hints": {}})
        if p["allocation"] != 100:
            rec["allocation"] = p["allocation"]
        rec["delegate_to"] = by_name.get(p["delegate"], p["delegate"]) or None
        people.append(rec)
    if roster:
        keep_example_roster(target, values)
    out = dict(data)
    out.update({"source": source, "owner": owner, "people": people})
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(header_lines(text) + yaml.safe_dump(out, sort_keys=False, allow_unicode=True, width=110))
    gates = write_gates(target, roster, lead["name"] if lead else None)
    return "roster: %d people in %s, owner %s, sign-off pending%s" % (
        len(people), PEOPLE, owner["primary"], "; " + gates if gates else "")


# ---- team settings --------------------------------------------------------------------------------

def load_profile(target):
    path = os.path.join(target, PROFILE)
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def save_profile(target, profile):
    with open(os.path.join(target, PROFILE), "w", encoding="utf-8") as fh:
        json.dump(profile, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


# the MCP server names the shared copy's skills use, by the key the window asks for
MCP_DEFAULTS = {"jira": "acme-jira", "confluence": "acme-confluence", "snowflake": "acme-snowflake"}


def apply_mcp(target, names):
    """Point the skills and agents at the team's MCP servers (mcp__<name>__<tool> and plain mentions);
    returns how many files changed."""
    pairs = [(re.compile(r"(?<![A-Za-z0-9-])%s(?![A-Za-z0-9-])" % re.escape(MCP_DEFAULTS[k])), n.strip())
             for k, n in (names or {}).items() if k in MCP_DEFAULTS and str(n or "").strip()
             and n.strip() != MCP_DEFAULTS[k]]
    changed = 0
    if not pairs:
        return 0
    for root, _dirs, files in os.walk(os.path.join(target, ".devin")):
        for name in files:
            if not name.endswith((".md", ".yaml", ".yml", ".json")):
                continue
            path = os.path.join(root, name)
            text = read_text(path)
            out = text
            for rx, new in pairs:
                out = rx.sub(new, out)
            if out != text:
                with open(path, "w", encoding="utf-8", newline="") as fh:
                    fh.write(out)
                changed += 1
    return changed


def apply_settings(target, values, settings):
    """Write the window's settings into the installed team files; returns what it did."""
    done = []
    mcp_names = {k: str(v).strip() for k, v in (settings.get("mcp") or {}).items() if str(v or "").strip()}
    if mcp_names:
        n = apply_mcp(target, mcp_names)
        done.append("MCP servers %s in %d skill and agent files" % (
            ", ".join("%s=%s" % kv for kv in sorted(mcp_names.items())), n))
    if os.path.exists(os.path.join(target, PROFILE)):
        prof = load_profile(target)
        jira = prof.setdefault("jira", {})
        for queue, names in (settings.get("jira_statuses") or {}).items():
            names = split(names)
            if names:
                jira.setdefault("statuses", {})[queue] = names
        for field, fid in (settings.get("jira_fields") or {}).items():
            if str(fid or "").strip():
                jira.setdefault("fields", {})[field] = str(fid).strip()
        team = str(settings.get("it_team") or "").strip()
        if team and team != jira.get("it_team"):
            old = jira.get("it_team")
            if old:
                for k, q in (jira.get("queries") or {}).items():
                    jira["queries"][k] = q.replace(old, team)
            jira["it_team"] = team
        envs = settings.get("environments") or []
        if envs:
            wf = prof.setdefault("workflow", {})
            before = {e.get("name"): e for e in wf.get("environments") or []}
            merged = []
            for e in envs:
                rec = dict(before.get(e.get("name")) or {})
                rec.update({k: v for k, v in e.items() if v not in (None, "")})
                merged.append(rec)
            wf["environments"] = merged
        conf = prof.setdefault("confluence", {})
        pages = conf.setdefault("pages", {})
        titles = page_titles(values, settings)
        ids = settings.get("page_ids") or {}
        for key in PAGE_KEYS:
            pages.setdefault(key, {})["title"] = titles[key]
            if ids.get(key):
                pages[key]["id"] = str(ids[key])
        parent = page_id(settings.get("confluence_parent"))
        if parent:
            pages.setdefault("team_home", {})["id"] = parent
            if settings.get("confluence_parent_title"):
                pages["team_home"]["title"] = settings["confluence_parent_title"]
        if mcp_names or settings.get("where"):
            mcp = {k: "" for k in MCP_DEFAULTS}
            mcp.update(prof.get("mcp") or {})
            mcp.update(mcp_names)
            mcp["where"] = settings.get("where") or mcp.get("where") or "cloud"
            prof["mcp"] = mcp
        save_profile(target, prof)
        done.append("team settings: Jira statuses and fields, environments and Confluence pages in %s" % PROFILE)
    dirs = split(settings.get("kb_source_dirs"))
    kbp = os.path.join(target, KB_PROFILE)
    if dirs and os.path.exists(kbp):
        text = read_text(kbp)
        block = "  source_dirs:\n" + "".join("    - %s\n" % d.rstrip("/") for d in dirs)
        new, n = re.subn(r"(?m)^  source_dirs:[ \t]*\n(?:[ \t]*(?:#.*)?\n|    - .*\n)*", block, text, count=1)
        if not n:
            new, n = re.subn(r"(?m)^  source_dirs: *\[[^\]]*\] *\n", block, text, count=1)
        if n:
            with open(kbp, "w", encoding="utf-8") as fh:
                fh.write(new)
            done.append("knowledge base source folders: %s in %s" % (", ".join(dirs), KB_PROFILE))
    if settings.get("roster"):
        done.append(write_roster(target, values, settings))
    return done


# ---- Confluence -----------------------------------------------------------------------------------

def confluence(values):
    token = os.environ.get(values["confluence_token_env"], "")
    return install.site(values["wiki_host"]), token


def find_page(base, token, space, title):
    status, body = install.api("GET", "%s/rest/api/content?%s" % (base, urlencode(
        {"spaceKey": space, "title": title, "expand": "version"})), token)
    if status != 200:
        raise RuntimeError("Confluence search for %r: HTTP %s %s" % (title, status, body.get("message", "")))
    results = body.get("results") or []
    return results[0] if results else None


def urlencode(params):
    import urllib.parse
    return urllib.parse.urlencode(params)


def page_body(key, values, settings):
    product = values.get("product_name")
    sdlc = values.get("sdlc_dir", "sdlc")
    if key == "sprint_leave":
        return ("<p>Sprint leave and the <strong>Time off and backups</strong> planner of the %s team. "
                "<code>/vacation</code> and the Scrum Master tools write the tables on this page.</p>" % product)
    if key == "demo_recordings":
        return ("<p>Demo recordings of the %s team: one page per epic, one per story, one per acceptance "
                "criterion. <code>/demo-needed</code> adds them.</p>" % product)
    manual = os.path.join(settings.get("target") or "", sdlc, "framework", "USER-MANUAL.md")
    intro = ("<p>How the %s team uses Argus in Devin Cloud. The source is "
             "<code>%s/framework/USER-MANUAL.md</code> in the repository.</p>" % (product, sdlc))
    try:
        tools = os.path.join(settings.get("target") or "", sdlc, "framework", "tools")
        sys.path.insert(0, tools)
        import artifact_kit
        return intro + artifact_kit.markdown_html(read_text(manual))
    except Exception:  # noqa: BLE001 - a plain page is fine when the manual can't be rendered
        return intro


def create_pages(target, values, settings, log=print):
    """The roster, sprint leave, demo recordings and manual pages under the parent page; returns
    {key: id}. A page that already has the title is kept, not overwritten."""
    base, bearer = confluence(values)
    if not bearer:
        raise RuntimeError("secret %s is not set" % values["confluence_token_env"])
    parent = page_id(settings.get("confluence_parent"))
    if not parent:
        raise RuntimeError("no parent page: set it on the Confluence step")
    titles = page_titles(values, settings)
    ids = {}
    for key in ("sprint_leave", "demo_recordings", "user_manual"):
        found = find_page(base, bearer, values["wiki_space"], titles[key])
        if found:
            ids[key] = found["id"]
            log("  %s: page %s is already there (%s), kept" % (key, titles[key], found["id"]))
            continue
        payload = {"type": "page", "title": titles[key], "space": {"key": values["wiki_space"]},
                   "ancestors": [{"id": parent}],
                   "body": {"storage": {"value": page_body(key, values, settings), "representation": "storage"}}}
        status, body = install.api("POST", base + "/rest/api/content", bearer, payload)
        if status == 400 and key == "user_manual":
            payload["body"]["storage"]["value"] = page_body("user_manual", values, {})
            status, body = install.api("POST", base + "/rest/api/content", bearer, payload)
        if status not in (200, 201):
            raise RuntimeError("creating %r: HTTP %s %s" % (titles[key], status, body.get("message", "")))
        ids[key] = body["id"]
        log("  %s: created %s (%s)" % (key, titles[key], body["id"]))
    tool = os.path.join(target, values["sdlc_dir"], "framework", "tools", "roster_sync.py")
    r = subprocess.run([sys.executable, tool, "publish", "--live", "--parent", parent], cwd=target,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    m = re.search(r"(?:created|updated) page (\d+)", r.stdout)
    if r.returncode or not m:
        raise RuntimeError("roster page: %s" % (r.stdout + r.stderr).strip()[-600:])
    ids["roster"] = m.group(1)
    log("  roster: %s (%s), owner sign-off pending" % (titles["roster"], ids["roster"]))
    return ids


# ---- git ------------------------------------------------------------------------------------------

def need_repo(target):
    if not target or not os.path.isabs(target) or not os.path.isdir(os.path.join(target, ".git")):
        raise RuntimeError("not a local clone: %r" % target)


def git(target, *args, check=True, timeout=120):
    need_repo(target)
    r = subprocess.run(["git", "-C", target] + list(args), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                       env=dict(os.environ, GIT_TERMINAL_PROMPT="0"))
    if check and r.returncode:
        raise RuntimeError("git %s: %s" % (" ".join(args[:2]), (r.stderr or r.stdout).strip()[-400:]))
    return r


def remote_head(target):
    r = git(target, "ls-remote", "--symref", "origin", "HEAD", check=False)
    m = re.search(r"ref: refs/heads/(\S+)\s+HEAD", r.stdout)
    return m.group(1) if m else None


def remote_has(target, branch):
    r = git(target, "ls-remote", "--heads", "origin", branch, check=False)
    return r.returncode == 0 and bool(r.stdout.strip())


def top_folders(target):
    try:
        return sorted(d for d in os.listdir(target) if os.path.isdir(os.path.join(target, d))
                      and not d.startswith(".") and d != "node_modules")
    except OSError:
        return []


def prepare_branch(target, values, log=print):
    """A new devin/ branch from the work branch (made from the default branch if it isn't there)."""
    dirty = git(target, "status", "--porcelain").stdout.strip()
    if dirty:
        raise RuntimeError("%s has uncommitted changes; commit or stash them first" % target)
    work = values["work_branch"]
    git(target, "fetch", "-q", "origin")
    if not remote_has(target, work):
        base = remote_head(target)
        if not base:
            raise RuntimeError("cannot tell the default branch of origin")
        git(target, "push", "-q", "origin", "refs/remotes/origin/%s:refs/heads/%s" % (base, work))
        git(target, "fetch", "-q", "origin")
        log("  work branch %s created from %s" % (work, base))
    branch = "devin/%d-sdlc-install" % int(datetime.datetime.now().timestamp())
    git(target, "checkout", "-q", "-b", branch, "origin/" + work)
    log("  branch %s from %s" % (branch, work))
    return branch


def commit_and_push(target, values, settings, branch, log=print):
    paths = [p for p in (".devin", values["sdlc_dir"], values["kb_dir"], "AGENTS.md")
             if os.path.exists(os.path.join(target, p))]
    git(target, "add", "--", *paths)
    lead = settings.get("tech_lead") or {}
    who = "%s <%s>" % (lead.get("name") or "", lead.get("email") or "")
    git(target, "commit", "-q", "-m", "Install Argus (%s)" % values["product_name"],
        "-m", "Values in %s.\n\nRequested-by: %s" % (install.VALUES_FILE, who.strip()))
    git(target, "push", "-q", "-u", "origin", branch, timeout=300)
    log("  pushed %s" % branch)


# ---- saved draft ----------------------------------------------------------------------------------

def draft_text(draft):
    import yaml
    head = ("# Saved install window values for Argus (%s).\n"
            "# Secrets are not in this file, only the names of the Devin secrets that hold them.\n"
            "# Next time: attach the zip and this file to a new Devin Cloud session and type\n"
            "#   install this with my values\n" % today())
    return head + yaml.safe_dump(dict(draft, saved_on=today()), sort_keys=False, allow_unicode=True, width=110)


def read_draft(text):
    import yaml
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict) or "values" not in data:
        raise ValueError("this is not an install draft (no values:)")
    return data


def save_draft_to_repo(target, draft, log=print):
    """Commit only install-draft.yaml to devin/install-draft, without touching the working tree."""
    need_repo(target)
    blob = subprocess.run(["git", "-C", target, "hash-object", "-w", "--stdin"], input=draft_text(draft),
                          capture_output=True, text=True, encoding="utf-8", errors="replace", check=True).stdout.strip()
    tree = subprocess.run(["git", "-C", target, "mktree"], input="100644 blob %s\t%s\n" % (blob, DRAFT_NAME),
                          capture_output=True, text=True, encoding="utf-8", errors="replace", check=True).stdout.strip()
    parent = []
    if remote_has(target, DRAFT_BRANCH):
        git(target, "fetch", "-q", "origin", DRAFT_BRANCH)
        parent = ["-p", git(target, "rev-parse", "FETCH_HEAD").stdout.strip()]
    commit = git(target, "commit-tree", tree, *parent, "-m", "Saved install window values").stdout.strip()
    git(target, "push", "-q", "origin", "%s:refs/heads/%s" % (commit, DRAFT_BRANCH), timeout=120)
    log("  draft saved on %s" % DRAFT_BRANCH)
    return DRAFT_BRANCH


def load_draft_from_repo(target, branch=DRAFT_BRANCH):
    git(target, "fetch", "-q", "origin", branch)
    return read_draft(git(target, "show", "FETCH_HEAD:" + DRAFT_NAME).stdout)


def delete_draft_branch(target):
    if remote_has(target, DRAFT_BRANCH):
        r = git(target, "push", "-q", "origin", "--delete", DRAFT_BRANCH, check=False)
        return r.returncode == 0
    return False


# ---- Devin Cloud ----------------------------------------------------------------------------------

def playbooks(target, values, apply=False):
    tool = os.path.join(target, values["sdlc_dir"], "framework", "tools", "register_playbooks.py")
    cmd = [sys.executable, tool] + (["--apply"] if apply else [])
    r = subprocess.run(cmd, cwd=target, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode == 0, (r.stdout + r.stderr).strip()


def render_templates(template_dir, out_dir, values, settings):
    """The blueprint and knowledge note for the tech lead to approve in Devin Cloud."""
    lead = settings.get("tech_lead") or {}
    fill = dict(values, repo_name=values["repo_slug"].split("/")[-1], tech_lead_name=lead.get("name", ""),
                tech_lead_email=lead.get("email", ""), today=today())
    os.makedirs(out_dir, exist_ok=True)
    out = {}
    for name in ("blueprint-template.yaml", "knowledge-note-template.md"):
        src = os.path.join(template_dir, name)
        if not os.path.exists(src):
            continue
        text = read_text(src)
        text = re.sub(r"\{\{(\w+)\}\}", lambda m: str(fill.get(m.group(1), m.group(0))), text)
        dest = os.path.join(out_dir, name.replace("-template", ""))
        with open(dest, "w", encoding="utf-8") as fh:
            fh.write(text)
        out[name.split("-")[0]] = dest
    return out
