#!/usr/bin/env python3
"""Keep .devin/rules/people.yaml in step with the Acme Claims roster page in Confluence.

The Confluence page (space ACMEWIKI, title "Acme Claims Team Roster") is the source of truth for who is on
the team and which hats they wear. Resource 1 owns the page and signs it; this tool never
edits it after the first publish. It reads the page, compares it with people.yaml, and rewrites
people.yaml when the page has moved on.

    roster_sync.py render                 print the page body (storage HTML) built from people.yaml
    roster_sync.py publish [--live]       create the page (or update it if --page-id / people.yaml
                                          already knows it); dry run unless --live
    roster_sync.py check                  exit 1 when the page version is newer than the one
                                          people.yaml was last synced from (used by the daily check)
    roster_sync.py pull [--write]         show the differences; with --write, regenerate people.yaml
                                          from the page and record the page version
    roster_sync.py verify                 exit 1 when anything that grants something differs between
                                          the page and people.yaml: people, roles, delegates, owner,
                                          sign-off, default role and the access rules

What the page controls: jira_user, name, email, roles, primary_role, secondary_roles, allocation,
delivery, delegate_to, the owner / backups / sign-off block and the access rules (who may change
which folders, which gates the requester may not sign). What stays local and is carried
over untouched: devin_user_id, role_hints, default_role, and the header comment in people.yaml.

Confluence access: bearer token from ACME_CONFLUENCE_TOKEN, one /rest/api/user/current validation,
no retries on 4xx. A 401/403 stops the run.
"""
import argparse
import datetime
import html
import io
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import team_links  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
PEOPLE_PATH = os.path.join(ROOT, ".devin", "rules", "people.yaml")
try:
    _PAGES = team_links.confluence()
except team_links.LinksError as exc:
    raise SystemExit("roster_sync: %s" % exc) from None
CONFLUENCE = _PAGES["host"]
SPACE = _PAGES["space"]
PAGE_TITLE = _PAGES["pages"]["roster"]["title"]
DEFAULT_PARENT = _PAGES["pages"]["team_home"]["id"]  # the page the roster sits under
TOKEN_ENV = _PAGES["token_env"]

PEOPLE_COLUMNS = ["Jira user", "Name", "Email", "Gate roles", "Primary role", "Secondary roles",
                  "Allocation %", "Delivery", "Delegate to"]
LIST_FIELDS = ("roles", "secondary_roles")
LOCAL_FIELDS = ("devin_user_id", "role_hints")
ACCESS_COLUMNS = ["Area", "Paths", "Roles"]


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_people_file(path=PEOPLE_PATH):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    return yaml.safe_load(text) or {}, text


def header_comment(text):
    """The comment block at the top of people.yaml, kept verbatim on every regeneration."""
    lines = []
    for line in text.splitlines():
        if line.startswith("#") or not line.strip():
            lines.append(line)
        else:
            break
    return "\n".join(lines).rstrip() + "\n\n" if lines else ""


# ---- Confluence ------------------------------------------------------------------------------

class ConfluenceClient:
    def __init__(self, dry_run=False):
        self.dry_run = dry_run
        self.token = os.environ.get(TOKEN_ENV)
        self.validated = False
        if not self.token:
            raise RuntimeError("%s is not set; cannot reach Confluence." % TOKEN_ENV)

    def request(self, method, path, payload=None, **params):
        url = CONFLUENCE + path
        if params:
            url += ("&" if "?" in path else "?") + urllib.parse.urlencode(params)
        req = urllib.request.Request(
            url, method=method,
            data=json.dumps(payload).encode("utf-8") if payload is not None else None,
            headers={"Authorization": "Bearer " + self.token, "Accept": "application/json",
                     "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, context=ssl._create_unverified_context(), timeout=120) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise RuntimeError("Confluence returned %d. The service account token is invalid or locked; "
                                   "an admin must reset it. Not retrying." % exc.code) from exc
            raise RuntimeError("Confluence returned %d: %s" % (exc.code, exc.read().decode("utf-8", "replace")[:400])) from exc

    def get(self, path, **params):
        if not self.validated:
            self.request("GET", "/rest/api/user/current")
            self.validated = True
        return self.request("GET", path, **params)

    def write(self, method, path, payload):
        if self.dry_run:
            print(json.dumps({"method": method, "url": CONFLUENCE + path, "json": payload}, indent=2)[:3000])
            return {"id": "(dry-run)", "version": {"number": 0}}
        if not self.validated:
            self.request("GET", "/rest/api/user/current")
            self.validated = True
        return self.request(method, path, payload)

    def comments(self, page_id):
        found = self.get("/rest/api/content/%s/child/comment" % page_id,
                         expand="body.storage,history", limit=100)
        return found.get("results") or []

    def find_page(self, page_id=None):
        if page_id:
            return self.get("/rest/api/content/%s" % page_id, expand="body.storage,version")
        cql = 'space="%s" and type=page and title="%s"' % (SPACE, PAGE_TITLE)
        found = self.get("/rest/api/content/search", cql=cql, expand="body.storage,version", limit=5)
        results = found.get("results") or []
        return results[0] if results else None


# ---- render people.yaml -> storage HTML --------------------------------------------------------

def cell(value):
    if isinstance(value, list):
        value = ", ".join(str(v) for v in value)
    if value is None:
        value = ""
    if isinstance(value, bool):
        value = "yes" if value else "no"
    return "<td>%s</td>" % html.escape(str(value))


def person_row(p):
    return "<tr>%s</tr>" % "".join(cell(v) for v in (
        p.get("jira_user"), p.get("name"), p.get("email"), p.get("roles") or [],
        p.get("primary_role"), p.get("secondary_roles") or [],
        p.get("allocation") if p.get("allocation") is not None else 100,
        p.get("delivery", True), p.get("delegate_to")))


def name_of(data, jira_user):
    for p in data.get("people") or []:
        if p.get("jira_user") == jira_user:
            return p.get("name") or jira_user
    return jira_user or ""


def render_page(data):
    owner = data.get("owner") or {}
    signoff = owner.get("signoff") or {}
    out = io.StringIO()
    out.write("<p>This page is the single list of who is on the Acme Claims team and which roles they hold "
              "for the agentic SDLC gates. Devin reads it and regenerates "
              "<code>.devin/rules/people.yaml</code> from it, so a change here changes who can sign which gate. "
              "Edit the tables, save, and the next daily check picks it up.</p>")
    out.write("<h2>Ownership and sign-off</h2>")
    out.write('<table><tbody>')
    out.write("<tr><th>Owner</th>%s</tr>" % cell("%s (%s)" % (name_of(data, owner.get("primary")), owner.get("primary"))))
    out.write("<tr><th>Backups</th>%s</tr>" % cell(", ".join(
        "%s (%s)" % (name_of(data, b), b) for b in owner.get("backups") or [])))
    out.write("<tr><th>Review cadence</th>%s</tr>" % cell(owner.get("review_cadence")))
    out.write("<tr><th>Last reviewed</th>%s</tr>" % cell(str(owner.get("last_reviewed") or "")))
    signed_by = signoff.get("signed_by")
    out.write("<tr><th>Owner sign-off</th>%s</tr>" % cell(signoff.get("status") or "pending"))
    out.write("<tr><th>Signed by</th>%s</tr>" % cell(
        ("%s (%s)" % (name_of(data, signed_by), signed_by)) if signed_by else ""))
    out.write("<tr><th>Signed on</th>%s</tr>" % cell(str(signoff.get("signed_on") or "")))
    out.write("</tbody></table>")
    out.write("<p>To sign: either leave a comment on this page that starts with the word <strong>approved</strong> (or <strong>approve</strong>), "
              "or put your name and ID in <em>Signed by</em> and today's date in <em>Signed on</em>. "
              "Signed by the owner reads as <strong>signed</strong>; signed by a backup reads as "
              "<strong>interim</strong> until the owner signs; anything else is pending.</p>")
    out.write("<h2>People</h2>")
    out.write("<table><tbody><tr>%s</tr>" % "".join("<th>%s</th>" % c for c in PEOPLE_COLUMNS))
    for p in data.get("people") or []:
        out.write(person_row(p))
    out.write("</tbody></table>")
    out.write(render_access(data.get("access")))
    out.write("<h2>Column guide</h2><ul>"
              "<li><strong>Gate roles</strong>: the roles from approval-gates.yaml this person may sign for "
              "(bsa, po, tech_lead, developer, dev_team, tester, uat_team, release_manager, manager...).</li>"
              "<li><strong>Primary / secondary role</strong>: how Devin shapes a session for this person "
              "(role-routing.yaml). Routing only; it grants no access.</li>"
              "<li><strong>Allocation %</strong>: share of a sprint this person is available; 100 if unsure.</li>"
              "<li><strong>Delivery</strong>: no for managers and stewards who carry no sprint work.</li>"
              "<li><strong>Delegate to</strong>: Jira user who receives this person's approvals while away.</li>"
              "</ul>")
    out.write("<p><em>Default role for anyone not listed: %s.</em></p>" % html.escape(str(data.get("default_role") or "developer")))
    return out.getvalue()


def render_access(access):
    if not access:
        return ""
    out = io.StringIO()
    out.write("<h2>Access</h2>")
    out.write("<p>Which roles may change which folders of the repository. The longest matching path wins; "
              "<code>{owner}</code> is the person's own session folder and <code>any</code> means anyone on "
              "this roster. Devin's write guard, the git pre-commit check and the approval gates read these "
              "rules, so a change here changes who may change what.</p>")
    out.write("<table><tbody><tr>%s</tr>" % "".join("<th>%s</th>" % c for c in ACCESS_COLUMNS))
    for area in access.get("areas") or []:
        out.write("<tr>%s</tr>" % "".join(cell(v) for v in (area.get("name"), area.get("paths") or [],
                                                           area.get("roles") or [])))
    out.write("</tbody></table>")
    out.write("<p><em>Roles that may change anything not listed: %s.</em></p>" %
              html.escape(", ".join(access.get("default_roles") or [])))
    out.write("<p><em>Gates the requester may not sign: %s.</em></p>" %
              html.escape(", ".join(access.get("no_self_approval") or [])))
    for mode, who in sorted((access.get("roster_signoff") or {}).items()):
        out.write("<p><em>Roster sign-off that unlocks guarded writes and gates in %s mode: %s.</em></p>" %
                  (html.escape(str(mode)), html.escape(", ".join(who or []))))
    return out.getvalue()


def parse_access(tables, storage_html):
    """The Access table and its notes, or None when the page has no Access table."""
    table = next((t for t in tables if t and [c.strip().lower() for c in t[0]] == [c.lower() for c in ACCESS_COLUMNS]), None)
    if table is None:
        return None
    areas = []
    for row in table[1:]:
        if not any(c.strip() for c in row):
            continue
        row = row + [""] * (3 - len(row))
        areas.append({"name": row[0].strip(), "paths": split_list(row[1]), "roles": split_list(row[2])})
    note = lambda label: re.search(label + r":\s*([^<.]*)", storage_html)  # noqa: E731
    default, no_self = note("Roles that may change anything not listed"), note("Gates the requester may not sign")
    signoff = {m: split_list(who) for m, who in
               re.findall(r"Roster sign-off that unlocks guarded writes and gates in (\w+) mode:\s*([^<.]*)", storage_html)}
    access = {"default_roles": split_list(default.group(1)) if default else [],
              "no_self_approval": split_list(no_self.group(1)) if no_self else [],
              "areas": areas}
    if signoff:
        access["roster_signoff"] = signoff
    return access


# ---- parse storage HTML -> records -----------------------------------------------------------

class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables, self._table, self._row, self._cell = [], None, None, None
        self.headings, self._heading = [], None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
        elif tag == "h2":
            self._heading = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None:
            self._row.append("".join(self._cell).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            self.tables.append(self._table)
            self._table = None
        elif tag == "h2" and self._heading is not None:
            self.headings.append("".join(self._heading).strip())
            self._heading = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)
        if self._heading is not None:
            self._heading.append(data)


def split_list(text):
    return [t.strip() for t in re.split(r"[,;]", text or "") if t.strip()]


def to_bool(text, default=True):
    t = (text or "").strip().lower()
    if t in ("yes", "y", "true", "1"):
        return True
    if t in ("no", "n", "false", "0"):
        return False
    return default


def signoff_for(owner, signed_by, signed_on):
    """Status follows who signed: the owner -> signed, a backup -> interim, nobody/anyone else -> pending."""
    if signed_by and signed_by == owner.get("primary"):
        status = "signed"
    elif signed_by and signed_by in (owner.get("backups") or []):
        status = "interim"
    else:
        status, signed_by, signed_on = "pending", None, None
    return {"status": status, "signed_by": signed_by, "signed_on": signed_on}


SIGNOFF_RANK = {"pending": 0, "interim": 1, "signed": 2}


def comment_text(comment):
    return html.unescape(re.sub(r"<[^>]+>", " ", comment.get("body", {}).get("storage", {}).get("value", ""))).strip()


def signoff_from_comments(owner, comments):
    """A page comment that starts with the word `approved` (or `approve`), written by the owner or
    a backup, is a sign-off. The owner's approval wins over a backup's; otherwise the newest
    comment wins. Looser than the gates, which take `approved` only: `ok`, `looks good` do not count."""
    best = signoff_for(owner, None, None)
    for c in comments:
        text = comment_text(c).lower()
        if not re.match(r"^\W*approved?\b", text):
            continue
        who = ((c.get("history") or {}).get("createdBy") or {}).get("username")
        when = ((c.get("history") or {}).get("createdDate") or "")[:10] or None
        cand = signoff_for(owner, who, when)
        if SIGNOFF_RANK[cand["status"]] > SIGNOFF_RANK[best["status"]] or (
                cand["status"] == best["status"] and cand["status"] != "pending"
                and (cand["signed_on"] or "") >= (best["signed_on"] or "")):
            best = cand
            best["signed_via"] = "comment"
    return best


def best_signoff(table_signoff, comment_signoff):
    if SIGNOFF_RANK[comment_signoff["status"]] > SIGNOFF_RANK[table_signoff["status"]]:
        return comment_signoff
    return table_signoff


def confluence_time(text):
    """'2026-09-25T11:42:25.000-04:00' -> aware datetime, or None."""
    try:
        return datetime.datetime.fromisoformat(re.sub(r"\.\d+", "", (text or "").replace("Z", "+00:00")))
    except ValueError:
        return None


def page_signoff(page, page_data, comments):
    """The sign-off that stands for the page as it is now. The Signed-by rows count only when the
    signer made the latest edit, and an approved comment only when written after that edit, so any
    other edit (a publish included) puts the roster back to pending until the owner signs again."""
    version = page.get("version") or {}
    editor = (version.get("by") or {}).get("username")
    edited = confluence_time(version.get("when"))
    owner = page_data["owner"]
    table = owner["signoff"]
    if not editor or table.get("signed_by") != editor:
        table = signoff_for(owner, None, None)
    fresh = []
    for c in comments:
        created = confluence_time(((c.get("history") or {}).get("createdDate")))
        if edited and created and created >= edited:
            fresh.append(c)
    return best_signoff(table, signoff_from_comments(owner, fresh))


def parse_page(storage_html):
    """-> {"owner": {...}, "people": [...], "default_role": str, "access": {...} or None} as read from the page."""
    parser = TableParser()
    parser.feed(storage_html)
    if len(parser.tables) < 2:
        raise ValueError("roster page needs an ownership table and a people table; found %d table(s)" % len(parser.tables))
    kv = {row[0].strip().lower(): (row[1] if len(row) > 1 else "") for row in parser.tables[0] if row}
    ids = lambda text: re.findall(r"\(([A-Za-z0-9._-]+)\)", text)  # noqa: E731
    owner = {
        "primary": (ids(kv.get("owner", "")) or [None])[0],
        "backups": ids(kv.get("backups", "")),
        "review_cadence": kv.get("review cadence") or None,
        "last_reviewed": kv.get("last reviewed") or None,
    }
    signed_by = (ids(kv.get("signed by", "")) or [None])[0]
    owner["signoff"] = signoff_for(owner, signed_by, kv.get("signed on") or None)
    header, *rows = parser.tables[1]
    index = {h.strip().lower(): i for i, h in enumerate(header)}
    missing = [c for c in PEOPLE_COLUMNS if c.lower() not in index]
    if missing:
        raise ValueError("people table is missing column(s): %s" % ", ".join(missing))
    people = []
    for row in rows:
        if not any(c.strip() for c in row):
            continue
        get = lambda col: row[index[col.lower()]].strip() if index[col.lower()] < len(row) else ""  # noqa: E731
        alloc = get("Allocation %")
        person = {
            "jira_user": get("Jira user") or None,
            "name": get("Name"),
            "email": get("Email") or None,
            "roles": split_list(get("Gate roles")),
            "primary_role": get("Primary role") or None,
            "secondary_roles": split_list(get("Secondary roles")),
            "delegate_to": get("Delegate to") or None,
        }
        if alloc and alloc.isdigit() and int(alloc) != 100:
            person["allocation"] = int(alloc)
        if not to_bool(get("Delivery")):
            person["delivery"] = False
        people.append(person)
    m = re.search(r"Default role for anyone not listed:\s*([a-z_]+)", storage_html)
    return {"owner": owner, "people": people, "default_role": m.group(1) if m else None,
            "access": parse_access(parser.tables[2:], storage_html)}


# ---- merge + diff -------------------------------------------------------------------------------

def merge(page_data, local_data):
    """Page fields win; local-only fields (devin_user_id, role_hints) are carried over. Access rules come
    from the page; while the page has no Access table yet, the local ones are kept."""
    local_by_user = {p.get("jira_user"): p for p in local_data.get("people") or []}
    local_by_email = {(p.get("email") or "").lower(): p for p in local_data.get("people") or []}
    people = []
    for p in page_data["people"]:
        old = local_by_user.get(p.get("jira_user")) or local_by_email.get((p.get("email") or "").lower()) or {}
        rec = {"jira_user": p.get("jira_user"), "name": p.get("name"), "email": p.get("email"),
               "devin_user_id": old.get("devin_user_id")}
        if "allocation" in p:
            rec["allocation"] = p["allocation"]
        if "delivery" in p:
            rec["delivery"] = p["delivery"]
        rec.update({"roles": p["roles"], "primary_role": p["primary_role"],
                    "secondary_roles": p["secondary_roles"], "role_hints": old.get("role_hints") or {},
                    "delegate_to": p.get("delegate_to")})
        people.append(rec)
    owner = dict(local_data.get("owner") or {})
    for key in ("primary", "backups", "review_cadence", "last_reviewed", "signoff"):
        if page_data["owner"].get(key) not in (None, [], ""):
            owner[key] = page_data["owner"][key]
    out = {"owner": owner, "people": people,
           "default_role": page_data.get("default_role") or local_data.get("default_role") or "developer"}
    access = page_data.get("access") if page_data.get("access") is not None else local_data.get("access")
    if access is not None:
        out["access"] = access
    return out


def diff(page_people, local_people):
    by_user = lambda rows: {p.get("jira_user"): p for p in rows}  # noqa: E731
    page, local = by_user(page_people), by_user(local_people)
    lines = []
    for user in sorted(set(page) - set(local), key=str):
        lines.append("+ %s %s" % (user, page[user].get("name")))
    for user in sorted(set(local) - set(page), key=str):
        lines.append("- %s %s" % (user, local[user].get("name")))
    for user in sorted(set(page) & set(local), key=str):
        for field in ("name", "email", "roles", "primary_role", "secondary_roles", "delegate_to"):
            a, b = local[user].get(field), page[user].get(field)
            if (a or None) != (b or None) and not (a in ([], None) and b in ([], None)):
                lines.append("~ %s %s: %s -> %s" % (user, field, a, b))
        for field in ("allocation", "delivery"):
            a = local[user].get(field, 100 if field == "allocation" else True)
            b = page[user].get(field, 100 if field == "allocation" else True)
            if a != b:
                lines.append("~ %s %s: %s -> %s" % (user, field, a, b))
    return lines


def norm_access(access):
    if not access:
        return None
    return {"default_roles": sorted(access.get("default_roles") or []),
            "no_self_approval": sorted(access.get("no_self_approval") or []),
            "roster_signoff": {m: sorted(w or []) for m, w in (access.get("roster_signoff") or {}).items()},
            "areas": sorted((str(a.get("name") or ""), tuple(a.get("paths") or []), tuple(sorted(a.get("roles") or [])))
                            for a in access.get("areas") or [])}


def verify_differences(page_data, local_data, signed):
    """Everything that grants something, page vs people.yaml. Empty list = they agree."""
    lines = diff(page_data["people"], local_data.get("people") or [])
    owner, local_owner = page_data.get("owner") or {}, local_data.get("owner") or {}
    for key in ("primary", "backups"):
        if (owner.get(key) or None) != (local_owner.get(key) or None):
            lines.append("~ owner %s: %s -> %s" % (key, local_owner.get(key), owner.get(key)))
    local_signoff = (local_owner.get("signoff") or {}).get("status", "pending")
    if signed["status"] != local_signoff:
        lines.append("~ owner sign-off: %s -> %s" % (local_signoff, signed["status"]))
    if page_data.get("default_role") and page_data["default_role"] != local_data.get("default_role"):
        lines.append("~ default_role: %s -> %s" % (local_data.get("default_role"), page_data["default_role"]))
    if page_data.get("access") is None and local_data.get("access"):
        lines.append("~ access: the page has no Access table yet; publish it (roster_sync.py publish --live) "
                     "and have the owner sign")
    elif norm_access(page_data.get("access")) != norm_access(local_data.get("access")):
        lines.append("~ access: the Access rules on the page differ from people.yaml")
    return lines


def verify_file(path=PEOPLE_PATH, page_id=None, client=None):
    """-> (ok, page version, lines). Raises RuntimeError/ValueError/OSError when it cannot check."""
    data, _ = load_people_file(path)
    client = client or ConfluenceClient()
    page = fetch(argparse.Namespace(page_id=page_id), data, client)
    page_data = parse_page(page["body"]["storage"]["value"])
    signoff = page_signoff(page, page_data, client.comments(page["id"]))
    lines = verify_differences(page_data, data, signoff)
    return not lines, page["version"]["number"], lines


def write_people(data, source, header, path=PEOPLE_PATH):
    body = {"source": source, "owner": data["owner"], "people": data["people"], "default_role": data["default_role"]}
    if data.get("access") is not None:
        body["access"] = data["access"]
    generated = "# GENERATED from the Confluence roster page recorded under `source:`. Edit the page, not this\n" \
                "# file; tools/roster_sync.py pull --write regenerates it.\n\n"
    if generated in header:
        header = header.split(generated)[0]
    text = header + generated
    text += yaml.safe_dump(body, sort_keys=False, allow_unicode=True, width=100)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


# ---- commands ---------------------------------------------------------------------------------

def cmd_render(args):
    data, _ = load_people_file(args.people)
    print(render_page(data))
    return 0


def cmd_publish(args):
    data, _ = load_people_file(args.people)
    client = ConfluenceClient(dry_run=not args.live)
    page_id = args.page_id or (data.get("source") or {}).get("confluence_page_id")
    existing = client.find_page(page_id) if (args.live or page_id) else None
    unsigned = dict(data, owner=dict(data.get("owner") or {}, signoff={
        "status": "pending", "signed_by": None, "signed_on": None, "signed_via": None}))
    body = {"storage": {"value": render_page(unsigned), "representation": "storage"}}
    if existing:
        payload = {"id": existing["id"], "type": "page", "title": PAGE_TITLE,
                   "version": {"number": existing["version"]["number"] + 1, "message": "roster_sync publish"},
                   "body": body}
        result = client.write("PUT", "/rest/api/content/%s" % existing["id"], payload)
    else:
        payload = {"type": "page", "title": PAGE_TITLE, "space": {"key": SPACE},
                   "ancestors": [{"id": args.parent}], "body": body}
        result = client.write("POST", "/rest/api/content", payload)
    print("%s page %s (version %s)%s" % ("updated" if existing else "created", result.get("id"),
                                         (result.get("version") or {}).get("number"),
                                         "" if args.live else " [dry run]"))
    if args.live:
        print("%s/pages/viewpage.action?pageId=%s" % (CONFLUENCE, result.get("id")))
    print("owner sign-off is pending until the owner signs this version")
    return 0


def fetch(args, data, client=None):
    client = client or ConfluenceClient()
    page_id = args.page_id or (data.get("source") or {}).get("confluence_page_id")
    page = client.find_page(page_id)
    if not page:
        raise RuntimeError("no page titled %r in space %s (and no page id recorded in people.yaml). "
                           "Run: roster_sync.py publish --live" % (PAGE_TITLE, SPACE))
    return page


def cmd_check(args):
    data, _ = load_people_file(args.people)
    client = ConfluenceClient()
    page = fetch(args, data, client)
    known = (data.get("source") or {}).get("confluence_version")
    current = page["version"]["number"]
    local_signoff = ((data.get("owner") or {}).get("signoff") or {}).get("status", "pending")
    signed = page_signoff(page, parse_page(page["body"]["storage"]["value"]), client.comments(page["id"]))
    if known == current and signed["status"] == local_signoff:
        print("roster in sync: page %s version %s, sign-off %s" % (page["id"], current, local_signoff))
        return 0
    if known == current:
        print("roster page %s sign-off is now %s (people.yaml says %s). Run: roster_sync.py pull --write"
              % (page["id"], signed["status"], local_signoff))
        return 1
    print("roster page %s is at version %s; people.yaml was synced from %s. Run: roster_sync.py pull --write"
          % (page["id"], current, known))
    return 1


def cmd_verify(args):
    ok, version, lines = verify_file(args.people, args.page_id)
    if ok:
        print("roster verified: people.yaml matches the roster page (version %s)" % version)
        return 0
    print("roster NOT verified: people.yaml differs from the roster page (version %s):" % version)
    print("\n".join(lines))
    print("Fix the page, or have the tech lead run: roster_sync.py pull --write")
    return 1


def cmd_pull(args):
    data, text = load_people_file(args.people)
    client = ConfluenceClient()
    page = fetch(args, data, client)
    page_data = parse_page(page["body"]["storage"]["value"])
    lines = diff(page_data["people"], data.get("people") or [])
    signoff = page_signoff(page, page_data, client.comments(page["id"]))
    page_data["owner"]["signoff"] = signoff
    print("page %s version %s — owner sign-off: %s%s%s" % (
        page["id"], page["version"]["number"], signoff["status"],
        (" by " + signoff["signed_by"]) if signoff.get("signed_by") else "",
        (" on " + signoff["signed_on"]) if signoff.get("signed_on") else ""))
    print("\n".join(lines) if lines else "no people changes")
    if not args.write:
        return 1 if lines else 0
    merged = merge(page_data, data)
    source = {"confluence_page_id": page["id"], "confluence_version": page["version"]["number"],
              "confluence_title": page["title"], "synced_at": now(),
              "owner_signoff": signoff["status"]}
    write_people(merged, source, header_comment(text), args.people)
    print("people.yaml regenerated from page version %s" % page["version"]["number"])
    return 0


def confirmation_text(signoff, data, commit, branch):
    who = signoff.get("signed_by")
    return ("Roster sign-off recorded: %s by %s (%s) on %s. Argus, Agentic SDLC Framework has taken this page as the "
            "roster of record: people.yaml was regenerated from page version %s (names, gate roles, primary and "
            "secondary roles, delegates) and committed as %s on %s, so sessions now route work by these roles. "
            "No further action needed." % (signoff.get("status"), name_of(data, who) if who else "-", who or "-",
                                            signoff.get("signed_on") or "-",
                                            (data.get("source") or {}).get("confluence_version", "-"), commit, branch))


def already_confirmed(comments, commit):
    return any(commit in comment_text(c) for c in comments)


def cmd_confirm(args):
    """Tell the page (as a comment) that the sign-off has been picked up and committed. Idempotent per commit."""
    data, _ = load_people_file(args.people)
    client = ConfluenceClient(dry_run=not args.live)
    page = fetch(args, data, client)
    signoff = (data.get("owner") or {}).get("signoff") or {}
    if signoff.get("status", "pending") == "pending":
        print("people.yaml has no sign-off to confirm; nothing posted")
        return 0
    if already_confirmed(client.comments(page["id"]), args.commit):
        print("page %s already has a confirmation for commit %s; nothing posted" % (page["id"], args.commit))
        return 0
    text = confirmation_text(signoff, data, args.commit, args.branch)
    client.write("POST", "/rest/api/content", {
        "type": "comment",
        "container": {"id": page["id"], "type": "page"},
        "body": {"storage": {"value": "<p>%s</p>" % html.escape(text), "representation": "storage"}},
    })
    print(("posted" if args.live else "dry-run, would post") + " on page %s: %s" % (page["id"], text))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--people", default=PEOPLE_PATH)
    parser.add_argument("--page-id")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("render")
    p = sub.add_parser("publish"); p.add_argument("--live", action="store_true"); p.add_argument("--parent", default=DEFAULT_PARENT)
    sub.add_parser("check")
    sub.add_parser("verify")
    p = sub.add_parser("pull"); p.add_argument("--write", action="store_true")
    p = sub.add_parser("confirm"); p.add_argument("--commit", required=True); p.add_argument("--branch", default="feature/devin-sdlc"); p.add_argument("--live", action="store_true")
    args = parser.parse_args(argv)
    try:
        return {"render": cmd_render, "publish": cmd_publish, "check": cmd_check, "pull": cmd_pull,
                "confirm": cmd_confirm, "verify": cmd_verify}[args.command](args)
    except (RuntimeError, ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
